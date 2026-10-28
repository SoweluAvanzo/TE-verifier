## =============================================================================
## te_platform/agent/providers/fake.py — scripted model, for tests only
## =============================================================================
## GUIDE STEP   8.2
## PURPOSE      A ChatProvider that does not call any API: it replays a list of
##              pre-written "model turns" (text and tool calls) in order. Tests
##              of agent/loop.py use it to check limits, the confirmation flow
##              and self-correction after a precondition error, quickly,
##              deterministically and for free.
## USED BY      tests/platform_tests/test_platform_agent.py; evals may use it to
##              dry-run scenario files.
## DEPENDS ON   providers/base.py.
## WHY          This is NOT a mock of our business logic: tools still run for
##              real through MCP (in tests: an in-process MCP server), the
##              pipeline still enforces preconditions. Only the EXTERNAL model
##              is replaced, because its answers are random and cost money.
##              The real model is covered by the marked integration test
##              (guide 8.3) and by the eval harness (phase 13).
## ACTIVATE     Uncomment together with base.py (guide 8.2). Never import this
##              module from production code (a test asserts it).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the names FakeProvider and
## ScriptedTurn exactly: the tests import them. Write this file together
## with providers/base.py.
##
## Guide 8.2
## [ ] 1. Imports at the top: AsyncIterator, dataclass and field, Any and
##        Literal, anyio, and the six names of providers/base.py
##        (ProviderEvent, Stop, TextDelta, ToolCall, ToolDef, Usage).
## [ ] 2. `@dataclass class ScriptedTurn` with a docstring: text: str = "",
##        tool_calls: a list of ToolCall with field(default_factory=list),
##        delay_s: float = 0.0 (a slow model, for the time-limit test) and
##        stop_reason: one of Stop's reasons or None (None: "tool_use" when
##        there are calls, else "end_turn"; set "refusal" or "max_tokens" to
##        test those paths).
## [ ] 3. `class FakeProvider`, `__init__(self, script)`: keep a COPY of the
##        script list, and self.requests = [] (tests inspect it).
## [ ] 4. `async def stream(self, *, system, messages, tools)` (an async
##        generator): record {"system", "messages": a copy, "tools": the
##        names}; raise AssertionError when the script is empty; pop the
##        first turn; `await anyio.sleep(turn.delay_s)` when it is > 0;
##        yield TextDelta (only if there is text), each ToolCall, then
##        Usage(input_tokens=100, output_tokens=10). Last, build the
##        assistant message in the SAME shape as the Anthropic provider (a
##        text block, then one block per call) and yield the Stop:
##          | {"type": "tool_use", "id": c.tool_use_id, "name": c.name,
##          |  "input": c.arguments}
## [ ] 5. `user_message` and `tool_result` (is_error keyword-only), in the
##        same shapes the Anthropic provider will use at 8.3:
##          | {"role": "user", "content": [*tool_results, {"type": "text", "text": text}]}
##          | {"type": "tool_result", "tool_use_id": ..., "content": ..., "is_error": ...}
##        (the text block only when the text is not empty).
## [ ] 6. Check: activate
##        test_fake_provider_is_never_imported_by_production_code in
##        tests/platform_tests/test_platform_agent.py, then
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

import anyio

from te_platform.agent.providers.base import (
    ProviderEvent,
    Stop,
    TextDelta,
    ToolCall,
    ToolDef,
    Usage,
)


@dataclass
class ScriptedTurn:
    """What the fake model 'says' in reply to one request."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Seconds to wait before answering: a slow model (tests of the time limit).
    delay_s: float = 0.0
    # None: "tool_use" when there are tool calls, else "end_turn".
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"] | None = None


class FakeProvider:
    """Replays ScriptedTurns in order and records every request it received.

    Tests assert on the records what the loop sent (e.g. that tool results
    came back in ONE user message, or that only state-allowed tools were
    offered).
    """

    def __init__(self, script: list[ScriptedTurn]) -> None:
        self._script = list(script)
        self.requests: list[dict[str, Any]] = []

    async def stream(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[ToolDef]
    ) -> AsyncIterator[ProviderEvent]:
        """Answer with the next scripted turn (same events as a real provider)."""
        self.requests.append(
            {"system": system, "messages": list(messages), "tools": [t.name for t in tools]}
        )
        if not self._script:
            raise AssertionError("FakeProvider ran out of scripted turns")
        turn = self._script.pop(0)
        if turn.delay_s > 0:
            await anyio.sleep(turn.delay_s)
        if turn.text:
            yield TextDelta(turn.text)
        for call in turn.tool_calls:
            yield call
        yield Usage(input_tokens=100, output_tokens=10)
        # Same message shape as the Anthropic provider, so the loop code path is identical.
        blocks: list[dict[str, Any]] = []
        if turn.text:
            blocks.append({"type": "text", "text": turn.text})
        blocks += [
            {"type": "tool_use", "id": c.tool_use_id, "name": c.name, "input": c.arguments}
            for c in turn.tool_calls
        ]
        reason = turn.stop_reason or ("tool_use" if turn.tool_calls else "end_turn")
        yield Stop(reason=reason, assistant_message={"role": "assistant", "content": blocks})

    def user_message(
        self, text: str, tool_results: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Build a user message: tool results first, then the text."""
        content = list(tool_results or [])
        if text:
            content.append({"type": "text", "text": text})
        return {"role": "user", "content": content}

    def tool_result(self, tool_use_id: str, content: str, *, is_error: bool) -> dict[str, Any]:
        """Build one tool-result block."""
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": is_error,
        }
