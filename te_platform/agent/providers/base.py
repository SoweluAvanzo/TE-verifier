## =============================================================================
## te_platform/agent/providers/base.py — the ChatProvider interface
## =============================================================================
## GUIDE STEP   8.2
## PURPOSE      Defines WHAT any model provider must offer to the agent loop,
##              without saying HOW: one method, stream(), that sends the system
##              prompt, the conversation history and the tool definitions to a
##              model, and yields provider-neutral events while the model
##              answers:
##                TextDelta  — a piece of visible text;
##                ToolCall   — the model asks to run a tool;
##                Usage      — LLM tokens consumed;
##                Stop       — the model finished; includes the complete
##                             assistant message to append to the history.
##              And ProviderError: the one exception a provider raises when the
##              model API fails, carrying a message safe to show to the user.
## USED BY      agent/loop.py (the only caller), providers/anthropic.py and
##              providers/fake.py (implement it).
## DEPENDS ON   Standard library only (typing.Protocol, dataclasses).
## WHY          Architecture D8: the loop logic is tested with the fake
##              provider (deterministic, free) and the real provider is tested
##              separately. A Protocol (structural typing) means a provider
##              does not need to inherit from anything: having the right
##              method is enough, and mypy checks it.
## ACTIVATE     Uncomment together with providers/fake.py (guide 8.2).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep every class and field name
## exactly: loop.py, mcp_bridge.py and both providers use them. Write this
## file together with providers/fake.py.
##
## Guide 8.2
## [ ] 1. Imports at the top: AsyncIterator (collections.abc), dataclass and
##        field, and Any, Literal, Protocol from typing.
## [ ] 2. Four provider events, each a frozen dataclass with a docstring:
##          | @dataclass(frozen=True)
##          | class TextDelta:
##          |     text: str
##        then ToolCall (tool_use_id, name, arguments: dict[str, Any]), Usage
##        (input_tokens, output_tokens, cache_read_input_tokens,
##        cache_creation_input_tokens, all int = 0) and Stop (reason: a
##        Literal of "end_turn", "tool_use", "max_tokens", "refusal",
##        "other"; assistant_message: dict; detail: str | None = None).
## [ ] 3. `ProviderEvent = TextDelta | ToolCall | Usage | Stop`.
## [ ] 4. `ToolDef`, a frozen dataclass: name, description, input_schema, and
##        extra: dict with field(default_factory=dict).
## [ ] 5. `class ProviderError(Exception)`: raised by a provider when the
##        model API fails (rate limit, server error, network). __init__ takes
##        the user-safe message and a keyword-only `retryable: bool`; keep
##        both as attributes (user_message, retryable). agent/chat_api.py shows
##        user_message to the user; the technical cause stays in the log.
## [ ] 6. `class ChatProvider(Protocol)` with three methods whose body is
##        only a docstring: stream(self, *, system, messages, tools) ->
##        AsyncIterator[ProviderEvent], declared WITHOUT `async` (the
##        SOLUTION comment explains why); user_message(text, tool_results=
##        None) -> dict; tool_result(tool_use_id, content, *, is_error) ->
##        dict (is_error keyword-only: a bare True/False at the call site
##        would not say what it means).
## [ ] 7. Check: `uv run mypy te_platform`. The loop's tests, which run on
##        the fake provider without network, come with the loop (guide 8.4).
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

## --- Provider-neutral events -------------------------------------------------------
## Plain dataclasses: they never leave the process, so they need no JSON
## validation (unlike events.py, which is the browser contract).


@dataclass(frozen=True)
class TextDelta:
    """A piece of visible text, as the model generates it."""

    text: str


@dataclass(frozen=True)
class ToolCall:
    """The model asks to run one tool."""

    tool_use_id: str  # provider's ID; the result must quote it back
    name: str  # PROVIDER-SIDE name (e.g. "verify__run__v1"); mcp_bridge maps it
    arguments: dict[str, Any]  # already parsed from JSON by the provider


@dataclass(frozen=True)
class Usage:
    """LLM tokens consumed by ONE model request (not a running total)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0  # served from the prompt cache (cheaper)
    cache_creation_input_tokens: int = 0  # written to the cache this time


@dataclass(frozen=True)
class Stop:
    """The model finished this request.

    reason:
      "end_turn"   final answer, no tool calls;
      "tool_use"   the model wants the ToolCalls yielded before this;
      "max_tokens" the answer was cut off by the length limit;
      "refusal"    the model declined (safety); see `detail`;
      "other"      any other stop reason; `detail` names it.
    assistant_message: the COMPLETE assistant message in the provider's own
      format (for Anthropic: the full list of content blocks, thinking
      blocks included). The loop appends it to the history UNCHANGED.
    """

    reason: Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]
    assistant_message: dict[str, Any]
    detail: str | None = None


ProviderEvent = TextDelta | ToolCall | Usage | Stop


## --- Tool definition in provider-neutral form -----------------------------------------
@dataclass(frozen=True)
class ToolDef:
    """One tool as offered to the model."""

    name: str  # provider-safe name (see mcp_bridge.to_provider_name)
    description: str  # generated from the policy (registry/describe.py)
    input_schema: dict[str, Any]  # JSON Schema of the tool's input model
    extra: dict[str, Any] = field(default_factory=dict)


## --- Errors ---------------------------------------------------------------------------
## A provider turns ITS OWN exception classes (for Anthropic: RateLimitError,
## APIStatusError, APIConnectionError, ...) into this one class, so agent/chat_api.py
## can show a useful message without knowing which provider is in use.
class ProviderError(Exception):
    """The model API failed; `user_message` is safe to show to the user."""

    def __init__(self, user_message: str, *, retryable: bool) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.retryable = retryable  # True: trying again later may work


## --- The interface ----------------------------------------------------------------------
class ChatProvider(Protocol):
    """What the agent loop needs from a model provider."""

    # Declared WITHOUT `async`: an implementation written as
    # `async def stream(...)` containing `yield` is an *async generator*, and
    # calling it returns an AsyncIterator directly (no await). Declaring it
    # `async def` here would instead promise a coroutine, which is wrong.
    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDef],
    ) -> AsyncIterator[ProviderEvent]:
        """Send one request; yield events until exactly one Stop.

        `messages` is the history in the provider's own format, exactly as
        previously returned in Stop.assistant_message plus the user / tool
        result messages built by the loop via the two helpers below.
        Raises ProviderError when the model API fails.
        """

    def user_message(
        self, text: str, tool_results: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Build one user message in the provider's format.

        Optional tool results come FIRST (they answer the previous assistant
        message), then the text.
        """

    def tool_result(self, tool_use_id: str, content: str, *, is_error: bool) -> dict[str, Any]:
        """Build one tool-result block in the provider's format."""
