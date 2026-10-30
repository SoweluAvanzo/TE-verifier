## =============================================================================
## tests/platform_tests/test_platform_openai_provider.py — OpenAI-compatible model
## =============================================================================
## PURPOSE      The stored history (text / tool_use / tool_result blocks) is
##              translated to the OpenAI chat format and back without loss,
##              streamed tool-call fragments are reassembled, and (with the
##              department key) a real model asks for verify.run.v1 and
##              answers after the real tool result.
## LIVE         The last test runs only when TE_LLM_API_KEY is set; it uses
##              TE_LLM_BASE_URL and TE_AGENT_MODEL.
## =============================================================================

import json
import os
from pathlib import Path

import pytest

from te_platform.agent.forms import AskUserInput
from te_platform.agent.providers.base import ProviderError, Stop, TextDelta, ToolCall, ToolDef
from te_platform.agent.providers.openai_compatible import (
    OpenAICompatibleProvider,
    _Accumulator,
    to_openai_messages,
    to_openai_tools,
)
from te_platform.config import get_settings
from te_platform.registry.loader import build_registry
from te_platform.registry.describe import describe
from te_platform.registry.pipeline import call
from te_platform.registry.context import CallContext, Principal

HISTORY = [
    {"role": "user", "content": [{"type": "text", "text": "Check my design."}]},
    {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "...", "signature": "x"},
            {"type": "text", "text": "Running the check."},
            {"type": "tool_use", "id": "call_1", "name": "verify__run__v1", "input": {"a": 1}},
            {"type": "tool_use", "id": "call_2", "name": "graph__flow__v1", "input": {}},
        ],
    },
    {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "ok", "is_error": False},
            {"type": "tool_result", "tool_use_id": "call_2", "content": "bad", "is_error": True},
            {"type": "text", "text": "And now?"},
        ],
    },
]


def test_history_becomes_openai_messages() -> None:
    out = to_openai_messages("SYS", HISTORY)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "Check my design."}
    # The thinking block is not sent; text and both calls are.
    assert out[2]["content"] == "Running the check."
    assert [c["id"] for c in out[2]["tool_calls"]] == ["call_1", "call_2"]
    assert json.loads(out[2]["tool_calls"][0]["function"]["arguments"]) == {"a": 1}
    # Tool results come first, one message each, then the user's text.
    assert out[3] == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}
    assert out[4] == {"role": "tool", "tool_call_id": "call_2", "content": "ERROR: bad"}
    assert out[5] == {"role": "user", "content": "And now?"}
    assert len(out) == 6


def test_assistant_with_only_tool_calls_has_null_content() -> None:
    msgs = [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "c", "name": "n", "input": {}}]}]
    assert to_openai_messages("S", msgs)[1]["content"] is None


def test_tools_use_the_function_format() -> None:
    tool = ToolDef(name="verify__run__v1", description="d", input_schema={"type": "object"})
    assert to_openai_tools([tool]) == [{
        "type": "function",
        "function": {"name": "verify__run__v1", "description": "d",
                     "parameters": {"type": "object"}},
    }]


def _chunk(delta: dict, finish: str | None = None) -> dict:
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def test_streamed_tool_call_fragments_are_reassembled() -> None:
    acc = _Accumulator()
    acc.feed(_chunk({"content": "Let me check."}))
    acc.feed(_chunk({"tool_calls": [{"index": 0, "id": "call_9", "type": "function",
                                     "function": {"name": "verify__run__v1", "arguments": ""}}]}))
    acc.feed(_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"spec_'}}]}))
    acc.feed(_chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'yaml": "x"}'}}]}))
    acc.feed(_chunk({}, finish="tool_calls"))
    acc.feed({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4}})
    (c,) = acc.tool_calls()
    assert (c.tool_use_id, c.name, c.arguments) == ("call_9", "verify__run__v1", {"spec_yaml": "x"})
    assert "".join(acc.text) == "Let me check."
    assert acc.finish == "tool_calls" and acc.usage["completion_tokens"] == 4


def test_missing_call_id_gets_one_and_bad_json_is_an_error() -> None:
    acc = _Accumulator()
    acc.feed(_chunk({"tool_calls": [{"index": 0, "function": {"name": "n", "arguments": "{}"}}]}))
    assert acc.tool_calls()[0].tool_use_id.startswith("call_")
    bad = _Accumulator()
    bad.feed(_chunk({"tool_calls": [{"index": 0, "function": {"name": "n", "arguments": "{x"}}]}))
    with pytest.raises(ProviderError):
        bad.tool_calls()


def test_form_question_accepts_type_for_kind() -> None:
    # gpt-oss writes "type"; the form shown and stored says "kind".
    form = AskUserInput.model_validate(
        {"title": "Describe", "questions": [{"id": "desc", "label": "Your system", "type": "text"}]}
    )
    dumped = form.model_dump(mode="json")["questions"][0]
    assert dumped["kind"] == "text" and "type" not in dumped


def test_note_and_text_stay_separate_paragraphs() -> None:
    msgs = [{"role": "user", "content": [{"type": "text", "text": "NOTE"},
                                         {"type": "text", "text": "Hi"}]}]
    assert to_openai_messages("S", msgs)[1] == {"role": "user", "content": "NOTE\n\nHi"}


@pytest.mark.skipif(not os.environ.get("TE_LLM_API_KEY"), reason="needs TE_LLM_API_KEY")
@pytest.mark.anyio
async def test_integration_openai_compatible_verify_turn() -> None:
    get_settings.cache_clear()
    registry = build_registry(Path("policy/tool_policy.yaml"))
    tools = [
        ToolDef(
            name=t.replace(".", "__"),
            description=describe(t, registry.policy),
            input_schema=registry.tools[t].input_model.model_json_schema(),
        )
        for t in sorted(registry.tools)
    ]
    provider = OpenAICompatibleProvider()
    system = "You verify token economy designs with the tools provided. Be brief."
    spec = Path("examples/bitcoin.yaml").read_text()
    history = [provider.user_message(f"Verify this spec with verify.run.v1:\n\n{spec}")]
    events = [ev async for ev in provider.stream(system=system, messages=history, tools=tools)]
    stop = events[-1]
    assert isinstance(stop, Stop) and stop.reason == "tool_use", stop
    calls = [ev for ev in events if isinstance(ev, ToolCall)]
    assert calls and calls[0].name == "verify__run__v1"
    history.append(stop.assistant_message)
    results = []
    for c in calls:
        tool_id = c.name.replace("__", ".")
        ctx = CallContext(
            principal=Principal(id="integration-test", kind="api_key"),
            tool_id=tool_id,
            tool_input=c.arguments,
        )
        outcome = await call(registry, tool_id, c.arguments, ctx)
        results.append(
            provider.tool_result(c.tool_use_id, outcome.model_dump_json(), is_error=not outcome.ok)
        )
    history.append(provider.user_message("", results))
    events = [ev async for ev in provider.stream(system=system, messages=history, tools=tools)]
    stop = events[-1]
    assert isinstance(stop, Stop) and stop.reason in ("end_turn", "tool_use"), stop
    assert any(isinstance(ev, TextDelta) for ev in events) or stop.reason == "tool_use"
