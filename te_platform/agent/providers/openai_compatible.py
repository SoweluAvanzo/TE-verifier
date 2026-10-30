## =============================================================================
## te_platform/agent/providers/openai_compatible.py — a model behind an
## OpenAI-compatible chat API (e.g. the department's Open WebUI)
## =============================================================================
## PURPOSE      ChatProvider for any server that speaks the OpenAI chat
##              completions protocol (POST {base}/chat/completions, streamed
##              as server-sent events, tools as "function" definitions):
##              Open WebUI (utopia.hpc4ai.unito.it), vLLM, Ollama, LiteLLM.
## FORMAT       The stored history stays in the format the rest of the
##              platform reads (agent/transcript.py, reports/method.py,
##              reports/design.py): content blocks of type text, tool_use and
##              tool_result. This provider translates that history to the
##              OpenAI format on every request, and returns each answer in
##              the stored format. Blocks it cannot send (Anthropic thinking
##              blocks from an earlier provider) are left out of the request,
##              never removed from the history.
## NOT HERE     Prompt caching control, adaptive thinking, effort and the
##              refusal fallback are Anthropic features (providers/anthropic.py).
## DEPENDS ON   httpx2 (extra "agent"), config.py (llm_base_url, llm_api_key,
##              agent_model, agent_max_tokens).
## SELECTED BY  TE_LLM_PROVIDER=openai_compatible (agent/chat_api.get_provider).
## =============================================================================

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx2

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

_SERVER_ERROR = 500
_RETRY_STATUSES = {408, 429, 502, 503, 504}
_RETRIES = 2  # attempts after the first, only before any text reached the user
_BACKOFF_S = 2.0
_ERROR_DETAIL_CHARS = 300

## finish_reason (OpenAI) -> Stop.reason. A tool call wins over the reason:
## some servers (Ollama, some vLLM parsers) report "stop" with tool calls.
_REASONS: dict[str, Literal["end_turn", "tool_use", "max_tokens", "refusal"]] = {
    "stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens",
    "content_filter": "refusal",
}


def _block_text(content: Any) -> str:
    """Text of a tool_result's content (a string or a list of text blocks)."""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the stored history into OpenAI chat messages."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        content = m["content"]
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        texts = "\n\n".join(b["text"] for b in blocks if b.get("type") == "text")
        if m["role"] == "user":
            # Tool results answer the previous assistant message, so they
            # come first, one "tool" message each, then the user's text.
            for b in blocks:
                if b.get("type") == "tool_result":
                    text = _block_text(b.get("content", ""))
                    out.append({
                        "role": "tool",
                        "tool_call_id": b["tool_use_id"],
                        "content": f"ERROR: {text}" if b.get("is_error") else text,
                    })
            if texts:
                out.append({"role": "user", "content": texts})
        else:
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                }
                for b in blocks
                if b.get("type") == "tool_use"
            ]
            msg: dict[str, Any] = {"role": "assistant", "content": texts or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
    return out


def to_openai_tools(tools: list[ToolDef]) -> list[dict[str, Any]]:
    """Tool definitions in the OpenAI "function" format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _status_error(status: int, body: str) -> ProviderError:
    """Turn an HTTP error answer into a ProviderError the user can act on."""
    if status in (401, 403):  # noqa: PLR2004 - HTTP status codes
        return ProviderError(
            "The AI service rejected the platform's API key. The platform "
            "administrator needs to check the key.",
            retryable=False,
        )
    if status == 429:  # noqa: PLR2004
        return ProviderError(
            "The AI model is busy right now. Please try again in a minute.", retryable=True
        )
    if "context" in body.lower() and "length" in body.lower():
        return ProviderError(
            "This conversation has become too long for the AI model. "
            "Please start a new conversation.",
            retryable=False,
        )
    return ProviderError(
        "The AI model could not answer. Please try again.", retryable=status >= _SERVER_ERROR
    )


class _Accumulator:
    """Collects one streamed answer: text, tool-call fragments, reason, usage."""

    def __init__(self) -> None:
        self.text: list[str] = []
        self.calls: dict[int, dict[str, str]] = {}
        self.finish: str | None = None
        self.usage: dict[str, Any] = {}

    def feed(self, chunk: dict[str, Any]) -> str | None:
        """Take one chunk; return its visible text, if any."""
        if chunk.get("error"):
            raise ProviderError("The AI model could not answer. Please try again.", retryable=True)
        if chunk.get("usage"):
            self.usage = chunk["usage"]
        visible = None
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                visible = delta["content"]
                self.text.append(visible)
            # Tool calls arrive in fragments keyed by index: the id and name
            # in the first, the JSON arguments spread over several.
            for frag in delta.get("tool_calls") or []:
                empty = {"id": "", "name": "", "args": ""}
                call = self.calls.setdefault(frag.get("index", 0), empty)
                call["id"] = call["id"] or frag.get("id") or ""
                fn = frag.get("function") or {}
                call["name"] += fn.get("name") or ""
                call["args"] += fn.get("arguments") or ""
            if choice.get("finish_reason"):
                self.finish = choice["finish_reason"]
        return visible

    def tool_calls(self) -> list[ToolCall]:
        """Return the complete tool calls, arguments parsed."""
        result = []
        for _, c in sorted(self.calls.items()):
            try:
                args = json.loads(c["args"]) if c["args"].strip() else {}
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    "The AI model sent an incomplete answer. Please send your message again.",
                    retryable=True,
                ) from exc
            if not isinstance(args, dict):
                raise ProviderError(
                    "The AI model sent an incomplete answer. Please send your message again.",
                    retryable=True,
                )
            # A missing id would leave the result unmatched: make one.
            tool_id = c["id"] or f"call_{uuid.uuid4().hex[:24]}"
            result.append(ToolCall(tool_use_id=tool_id, name=c["name"], arguments=args))
        return result


def _stop(acc: _Accumulator, calls: list[ToolCall]) -> Stop:
    """Build the Stop event, with the answer in the stored format (module docstring)."""
    text = "".join(acc.text)
    content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    content += [
        {"type": "tool_use", "id": c.tool_use_id, "name": c.name, "input": c.arguments}
        for c in calls
    ]
    assistant_message = {"role": "assistant", "content": content}
    if calls:
        return Stop(reason="tool_use", assistant_message=assistant_message)
    reason = _REASONS.get(acc.finish or "stop")
    if reason is None:
        return Stop(reason="other", assistant_message=assistant_message, detail=acc.finish)
    return Stop(reason=reason, assistant_message=assistant_message)


class OpenAICompatibleProvider:
    """ChatProvider for an OpenAI-compatible chat completions API (async, streaming)."""

    def __init__(self, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        if not s.llm_api_key:
            raise RuntimeError("TE_LLM_API_KEY (secret te_llm_api_key) is not set")
        # The key comes from Settings (a Docker secret), never from code.
        self._client = httpx2.AsyncClient(
            base_url=s.llm_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {s.llm_api_key.get_secret_value()}"},
            # Generous read timeout: a local model may pause long between tokens.
            timeout=httpx2.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
            transport=transport,
        )
        self._model = s.agent_model
        self._max_tokens = s.agent_max_tokens

    def _request(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolDef]
    ) -> dict[str, Any]:
        """Build the request body of POST /chat/completions."""
        body: dict[str, Any] = {
            "model": self._model,
            "messages": to_openai_messages(system, messages),
            "max_tokens": self._max_tokens,
            "stream": True,
            # Token counts in the last chunk (budgets, agent/loop.py).
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = to_openai_tools(tools)
            body["tool_choice"] = "auto"
        return body

    async def _chunks(self, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """POST the request and yield the parsed stream chunks.

        Busy (429), server (5xx) and network errors are retried, but only
        before the first chunk: after that the user has seen part of the
        answer, and a second answer would be appended to it.
        """
        for attempt in range(_RETRIES + 1):
            started = False
            try:
                async with self._client.stream("POST", "/chat/completions", json=body) as resp:
                    status = resp.status_code
                    if status >= 400:  # noqa: PLR2004 - HTTP error statuses
                        raw = await resp.aread()
                        detail = raw.decode(errors="replace")[:_ERROR_DETAIL_CHARS]
                        if (status in _RETRY_STATUSES or status >= _SERVER_ERROR) and (
                            attempt < _RETRIES
                        ):
                            await asyncio.sleep(_BACKOFF_S * (attempt + 1))
                            continue
                        cause = RuntimeError(f"HTTP {status}: {detail}")
                        raise _status_error(status, detail) from cause
                    async for line in resp.aiter_lines():
                        # Server-sent events: "data: {json}" lines, then "data: [DONE]".
                        data = line[5:].strip() if line.startswith("data:") else ""
                        if data == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data) if data else None
                        except json.JSONDecodeError:
                            chunk = None
                        if chunk is not None:
                            started = True
                            yield chunk
                    return
            except (httpx2.TransportError, httpx2.TimeoutException) as exc:
                if not started and attempt < _RETRIES:
                    await asyncio.sleep(_BACKOFF_S * (attempt + 1))
                    continue
                raise ProviderError(
                    "The AI model cannot be reached. Please try again shortly.", retryable=True
                ) from exc

    async def stream(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[ToolDef]
    ) -> AsyncIterator[ProviderEvent]:
        """Send one request and yield TextDelta*, ToolCall*, Usage, Stop."""
        acc = _Accumulator()
        async for chunk in self._chunks(self._request(system, messages, tools)):
            visible = acc.feed(chunk)
            if visible:
                yield TextDelta(visible)

        calls = acc.tool_calls()
        for c in calls:
            yield c

        u = acc.usage
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        yield Usage(
            input_tokens=u.get("prompt_tokens") or 0,
            output_tokens=u.get("completion_tokens") or 0,
            cache_read_input_tokens=cached,
        )
        yield _stop(acc, calls)

    def user_message(
        self, text: str, tool_results: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Build a user message: tool results FIRST, then the text."""
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
