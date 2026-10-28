## =============================================================================
## tests/platform_tests/test_platform_transcript.py — the conversation as the page shows it
## =============================================================================
## GUIDE STEP   none yet (conversation history extension; te_platform/agent/transcript.py)
## PURPOSE      display_transcript() turns the stored provider messages into
##              what the person saw: their texts, the assistant's answers,
##              one line per tool call, forms (asked, answered, skipped);
##              never thinking blocks or raw tool results. No database.
## USED BY      pytest. The endpoints are tested in test_platform_agent.py.
## =============================================================================

import json
from typing import Any

from te_platform.agent.forms import answers_result, skipped_result
from te_platform.agent.transcript import TITLE_LENGTH, conversation_title, display_transcript

FORM = {"title": "Who takes part", "questions": [{"label": "How many people?"}]}


def _user(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"role": "user", "content": {"role": "user", "content": list(blocks)}, "usage": None}


def _assistant(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": {"role": "assistant", "content": list(blocks)},
        "usage": None,
    }


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


ROWS = [
    _user(_text("I run a garden.")),
    _assistant(
        {"type": "thinking", "thinking": "secret reasoning", "signature": "sig"},
        _text("Let me look."),
        {"type": "tool_use", "id": "t1", "name": "elicit__next_questions__v1", "input": {}},
        {"type": "tool_use", "id": "t2", "name": "lit__search__v1", "input": {}},
    ),
    _user(
        {"type": "tool_result", "tool_use_id": "t1", "content": "{}", "is_error": False},
        {"type": "tool_result", "tool_use_id": "t2", "content": "{}", "is_error": True},
    ),
    {"role": "usage", "content": {}, "usage": {"input_tokens": 1}},
    _assistant(
        _text("Two questions."), {"type": "tool_use", "id": "f1", "name": "ask_user", "input": FORM}
    ),
    _user(
        {
            "type": "tool_result",
            "tool_use_id": "f1",
            "content": answers_result(
                [
                    {
                        "question": "How many people?",
                        "display": "20 to 40 people",
                        "status": "answered",
                    }
                ]
            ),
            "is_error": False,
        }
    ),
    _assistant({"type": "tool_use", "id": "f2", "name": "ask_user", "input": FORM}),
    _user(
        {
            "type": "tool_result",
            "tool_use_id": "f2",
            "content": skipped_result(),
            "is_error": False,
        },
        _text("Let's talk about shoes instead."),
    ),
    _assistant({"type": "tool_use", "id": "t3", "name": "sim__monte_carlo__v1", "input": {}}),
]


def test_transcript_shows_what_the_person_saw() -> None:
    items = display_transcript(ROWS)
    assert [i["kind"] for i in items] == [
        "user_text",
        "assistant_text",
        "tool",
        "tool",
        "assistant_text",
        "form_asked",
        "form_answers",
        "form_asked",
        "form_skipped",
        "user_text",
        "tool",
    ]
    assert items[2] == {"kind": "tool", "tool": "elicit.next_questions.v1", "ok": True}
    assert items[3]["ok"] is False
    assert items[5]["questions"] == ["How many people?"] and items[5]["title"] == "Who takes part"
    assert items[6]["answers"] == [{"question": "How many people?", "display": "20 to 40 people"}]
    assert items[10]["ok"] is None  # still waiting for the user's confirmation


def test_thinking_and_raw_tool_results_never_reach_the_page() -> None:
    text = json.dumps(display_transcript(ROWS))
    assert "secret reasoning" not in text and "sig" not in text
    assert "tool_result" not in text


def test_plain_string_content_and_odd_rows_are_handled() -> None:
    rows = [
        {"role": "user", "content": {"role": "user", "content": "hello"}},
        {"role": "assistant", "content": {"role": "assistant", "content": [_text("   ")]}},
        {"role": "assistant", "content": {}},
    ]
    assert display_transcript(rows) == [{"kind": "user_text", "text": "hello"}]


def test_title_is_the_first_user_text_shortened() -> None:
    assert conversation_title(ROWS) == "I run a garden."
    long = [_user(_text("word " * 40))]
    title = conversation_title(long)
    assert len(title) <= TITLE_LENGTH and title.endswith("…")
    assert conversation_title([]) == "New conversation"
