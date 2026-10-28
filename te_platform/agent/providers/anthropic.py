## =============================================================================
## te_platform/agent/providers/anthropic.py — the real model, via the Anthropic API
## =============================================================================
## GUIDE STEP   8.3
## PURPOSE      Implements ChatProvider (base.py) with the official Anthropic
##              Python SDK: sends the system prompt, history and tools to
##              Claude, streams the answer, and converts the SDK's stream into
##              provider-neutral events (TextDelta, ToolCall, Usage, Stop).
## USED BY      agent/chat_api.py (creates one AnthropicProvider at startup and
##              gives it to every AgentLoop).
## DEPENDS ON   anthropic (official SDK, extra "agent"), config.py (model,
##              effort, API key), providers/base.py.
## WHY          Architecture D9: strongest model by default, streaming for a
##              responsive chat, prompt caching on the fixed prefix to make
##              long interviews cheaper. D8: everything Anthropic-specific
##              lives in this file only.
## ACTIVATE     Needs TE_ANTHROPIC_API_KEY (a Docker secret in production).
##              Uncomment, then run the integration test
##              test_integration_anthropic_verify_turn in
##              test_platform_agent.py (it is skipped unless
##              TE_ANTHROPIC_API_KEY is set, so it costs credits only when you
##              run it on purpose): one verify turn completes, and the 2nd
##              request has usage.cache_read_input_tokens > 0.
## IMPORTANT    API rules this file respects (from the Anthropic docs):
##              - history is append-only: each assistant message is stored
##                EXACTLY as returned (thinking blocks included) and never
##                edited, or the API rejects / ignores earlier thinking;
##              - all tool results of one assistant message go back in ONE
##                user message; failed tools are sent with is_error=True, not
##                dropped;
##              - no "prefill" (an assistant message we write ourselves at the
##                end of the history): not supported by this model;
##              - tool_choice stays "auto" (forcing a specific tool returns an
##                error on this model; the system prompt steers instead).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the class name
## AnthropicProvider exactly (agent/chat_api.py creates it), and respect the API
## rules listed under IMPORTANT in the header.
##
## Guide 8.3
## [ ] 1. Imports at the top: AsyncIterator, Any, `anthropic`, the seven names
##        of providers/base.py (ProviderError, ProviderEvent, Stop, TextDelta,
##        ToolCall, ToolDef, Usage) and get_settings.
## [ ] 2. Constants: `_FALLBACK_BETA = "server-side-fallback-2026-07-01"` and
##        `_SERVER_ERROR = 500` (status codes from here up are the API's own
##        failures).
## [ ] 3. `class AnthropicProvider`, `__init__(self)`: read the settings; the
##        key is anthropic_api_key's secret value, or None when unset; create
##        `anthropic.AsyncAnthropic(api_key=key)`; store agent_model,
##        agent_effort, agent_max_tokens and agent_enable_refusal_fallback as
##        _model, _effort, _max_tokens, _fallback.
## [ ] 4. `_request(system, messages, tools) -> dict[str, Any]`: model,
##        max_tokens, messages, thinking={"type": "adaptive"},
##        output_config={"effort": ...}, the tools as {"name",
##        "description", "input_schema"} (no eager_input_streaming: see the
##        comment in the SOLUTION), the
##        system prompt as ONE cached text block:
##          | system=[{"type": "text", "text": system,
##          |          "cache_control": {"type": "ephemeral"}}],
##        and a top-level cache_control (caches the history too). When
##        _fallback is on, add betas=[_FALLBACK_BETA] and fallbacks="default".
## [ ] 4b. Preserved thinking: thinking={"type": "adaptive", "block_binding":
##        {"prefix_mismatch_behavior": "drop_block"}} and betas always
##        holding _THINKING_BINDING_BETA ("thinking-binding-controls-
##        2026-08-01"; the fallback beta is appended to the same list). An
##        old thinking block whose system prompt or tool list has changed
##        since (a deploy, a new tool, a state change) is then dropped by the
##        API instead of failing the whole request with a 400.
## [ ] 5. `async def stream(self, *, system, messages, tools)`, an async
##        generator: `async with self._client.beta.messages.stream(
##        **request) as stream:`, yield TextDelta for every
##        content_block_delta whose delta is a text_delta, then final =
##        await stream.get_final_message(). Catch, most specific first,
##        anthropic.RateLimitError, APIStatusError, APIConnectionError and
##        raise ProviderError(user message, retryable=...) `from` each.
## [ ] 6. After the stream: yield a ToolCall for every "tool_use" block of
##        final.content (block.input is already a dict), then one Usage from
##        final.usage (cache fields may be None: use `or 0`).
## [ ] 7. The Stop: assistant_message = {"role": "assistant", "content":
##        [b.to_dict(mode="json") for b in final.content]} (all blocks,
##        unchanged). Map final.stop_reason: "refusal" (detail from
##        stop_details.explanation when present); "end_turn", "tool_use",
##        "max_tokens" as they are; anything else -> "other" with
##        detail=str(reason).
## [ ] 8. `user_message(text, tool_results=None)`: tool results FIRST, then a
##        text block if text is not empty. `tool_result(tool_use_id, content,
##        *, is_error)`: one "tool_result" block dict.
## [ ] 9. Check: `uv run mypy te_platform`; then, with TE_ANTHROPIC_API_KEY
##        set, run the integration test (header, ACTIVATE):
##          | uv run pytest tests/platform_tests/test_platform_agent.py
##          |     -k integration -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from collections.abc import AsyncIterator
from typing import Any

import anthropic

from te_platform.agent.providers.base import (
    ProviderError,
    ProviderEvent,
    Stop,
    TextDelta,
    ToolCall,
    ToolDef,
    Usage,
)
from te_platform.config import get_settings

## Server-side refusal fallback (opt-in, Settings.agent_enable_refusal_fallback).
## If the model declines a request for safety reasons, the API re-runs it on
## a fallback model inside the same call ("default": the API picks the model
## by refusal category). It is a beta feature, hence the beta client below
## and this header value. Read Anthropic's "refusals and fallback" docs
## before switching it on: the fallback model's answer is billed at its own
## rates, and the response may contain "fallback" blocks (kept unchanged in
## the history, like every other block).
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

## Preserved thinking: each thinking block in the history is bound to the
## system prompt, the tool list and the messages it was produced under. When
## one of them has changed (a deploy edits system.md, a tool is added, or the
## session state changes the offered tools), replaying an old block is a 400
## ("bound to a different conversation") that no retry clears. With
## drop_block the API instead drops the blocks that no longer match: the
## conversation goes on with its text and tool calls, only that earlier
## reasoning is left out. The history itself is never edited here.
_THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
_SERVER_ERROR = 500  # HTTP status codes from here up: the API's own failures


def _provider_error(exc: Exception) -> ProviderError:
    """Turn an SDK error into a ProviderError with a message the user can act on."""
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError(
            "The AI model is busy right now. Please try again in a minute.", retryable=True
        )
    if isinstance(exc, anthropic.APIStatusError) and "credit balance" in str(exc.message).lower():
        # The account behind the API key has no credits left: retrying cannot help.
        return ProviderError(
            "The AI service has run out of credits. The platform administrator "
            "needs to add credits to the API account.",
            retryable=False,
        )
    if isinstance(exc, anthropic.APIStatusError):
        # 5xx: the API failed. 4xx: our request was wrong (a bug to fix).
        return ProviderError(
            "The AI model could not answer. Please try again.",
            retryable=exc.status_code >= _SERVER_ERROR,
        )
    if isinstance(exc, anthropic.APIConnectionError):
        # Network problems (including timeouts) between our server and the API.
        return ProviderError(
            "The AI model cannot be reached. Please try again shortly.", retryable=True
        )
    # ValueError: the SDK could not parse a tool input the model streamed.
    # Should not happen without eager input streaming (see _request); if it
    # does, the turn ends with a message the user can act on instead of an
    # internal error. Any other APIError (e.g. a malformed response) too.
    return ProviderError(
        "The AI model sent an incomplete answer. Please send your message again.",
        retryable=True,
    )


class AnthropicProvider:
    """ChatProvider for Claude, through the official SDK (async, streaming)."""

    def __init__(self) -> None:
        s = get_settings()
        # AsyncAnthropic: the SDK's async client, so waiting for the model
        # does not block other chat sessions served by this process.
        # The key comes from Settings (a Docker secret), never from code.
        key = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None
        # A key that is not scoped to a workspace must name one in every
        # request (TE_ANTHROPIC_WORKSPACE_ID); a scoped key needs nothing.
        headers = (
            {"anthropic-workspace-id": s.anthropic_workspace_id}
            if s.anthropic_workspace_id
            else None
        )
        self._client = anthropic.AsyncAnthropic(api_key=key, default_headers=headers)
        self._model = s.agent_model  # "claude-opus-5-5" (architecture D9)
        self._effort = s.agent_effort  # low | medium | high | xhigh | max
        # Streaming requests can be long; ~64k output tokens leaves room for
        # thinking plus a full answer. (Non-streaming would need far less.)
        self._max_tokens = s.agent_max_tokens
        self._fallback = s.agent_enable_refusal_fallback

    def _request(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolDef]
    ) -> dict[str, Any]:
        """Build the request body (keyword arguments of messages.stream)."""
        # Order of the prompt = tools -> system -> messages. Caching is a
        # PREFIX match: the tool list and the system prompt must be byte-for-
        # byte identical between requests (stable order, no timestamps or
        # session IDs inside them) or the cache is invalidated. The
        # cache_control marker on the system block caches tools + system; the
        # top-level cache_control also caches the conversation so far, so
        # each request of a long interview re-reads the history from cache.
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
            "cache_control": {"type": "ephemeral"},
            # No eager_input_streaming: with it, tool arguments stream
            # unvalidated, and an invalid fragment (e.g. an unquoted string)
            # makes the SDK's stream parser raise ValueError mid-turn. This
            # provider reads tool calls only from the final message (below),
            # so streaming their arguments early would gain nothing; without
            # it the API sends each tool input as complete, valid JSON.
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ],
            # The model decides how much to think; effort sets the overall
            # depth. Thinking cannot be disabled on this model, and a
            # thinking budget (budget_tokens) is rejected: never send one.
            # block_binding: see _THINKING_BINDING_BETA above.
            "thinking": {
                "type": "adaptive",
                "block_binding": {"prefix_mismatch_behavior": "drop_block"},
            },
            "output_config": {"effort": self._effort},
            "betas": [_THINKING_BINDING_BETA],
        }
        if self._fallback:
            request["betas"].append(_FALLBACK_BETA)
            request["fallbacks"] = "default"
        return request

    async def stream(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[ToolDef]
    ) -> AsyncIterator[ProviderEvent]:
        """Send one request and yield TextDelta*, ToolCall*, Usage, Stop."""
        # --- Streaming ----------------------------------------------------------
        # messages.stream(...) is an async context manager: it opens the HTTP
        # stream, and closes it even if we stop early. We forward text deltas
        # immediately (the user sees the answer being written), then read the
        # complete final message once the stream ends. The beta namespace is
        # the same Messages API; it is needed only for the fallback option.
        # The SDK already retried 429 / 5xx / network errors (max_retries)
        # before raising; each typed error becomes a ProviderError with a
        # message the user can act on (agent/chat_api.py shows it; the cause is
        # chained with `from` and lands in the log).
        try:
            async with self._client.beta.messages.stream(
                **self._request(system, messages, tools)
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield TextDelta(event.delta.text)
                final = await stream.get_final_message()
        except (anthropic.APIError, ValueError) as exc:
            raise _provider_error(exc) from exc

        # --- Tool calls -----------------------------------------------------------
        # Tool inputs arrive already parsed (block.input is a dict). Parse
        # nothing by string matching: escaping details may differ.
        for block in final.content:
            if block.type == "tool_use":
                yield ToolCall(tool_use_id=block.id, name=block.name, arguments=dict(block.input))

        u = final.usage
        yield Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_input_tokens=u.cache_read_input_tokens or 0,
            cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
        )

        # --- Stop ---------------------------------------------------------------
        # Append the FULL content (all blocks, including thinking blocks,
        # unchanged) to the history. to_dict() gives each block exactly as
        # the API returned it (the fields it set, under their API names),
        # which is also how the SDK itself sends response blocks back.
        content = [b.to_dict(mode="json") for b in final.content]
        assistant_message = {"role": "assistant", "content": content}
        reason = final.stop_reason
        if reason == "refusal":
            # stop_details explains which safety category declined; the loop
            # ends the turn with done(refusal); never retry blindly.
            detail = final.stop_details.explanation if final.stop_details else None
            yield Stop(reason="refusal", assistant_message=assistant_message, detail=detail)
        elif reason in ("end_turn", "tool_use", "max_tokens"):
            yield Stop(reason=reason, assistant_message=assistant_message)
        else:
            # e.g. "stop_sequence" or "model_context_window_exceeded": the turn ends.
            yield Stop(reason="other", assistant_message=assistant_message, detail=str(reason))

    def user_message(
        self, text: str, tool_results: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Build a user message: tool results FIRST, then the text.

        Tool results must come first in the user message that follows an
        assistant message with tool_use blocks; text after them is allowed.
        """
        content: list[dict[str, Any]] = list(tool_results or [])
        if text:
            content.append({"type": "text", "text": text})
        return {"role": "user", "content": content}

    def tool_result(self, tool_use_id: str, content: str, *, is_error: bool) -> dict[str, Any]:
        """Build one tool_result block (is_error=True marks a failed call)."""
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": is_error,
        }
