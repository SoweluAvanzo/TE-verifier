## =============================================================================
## te_platform/agent/transcript.py — the stored conversation, as the chat page shows it
## =============================================================================
## GUIDE STEP   none yet (conversation history extension of phases 8-9)
## PURPOSE      The database keeps every provider message exactly as sent and
##              received (thinking blocks, tool calls, tool results): that is
##              what the model must see again. The chat page needs something
##              else: what the PERSON saw. display_transcript() turns the
##              stored messages into a flat list of display items:
##                user_text       {text}
##                assistant_text  {text}            (Markdown, rendered safely)
##                tool            {tool, ok}        (one line per tool call)
##                form_asked      {tool_use_id, title, questions}
##                form_answers    {tool_use_id, answers: [{question, display}]}
##                form_skipped    {tool_use_id}
##              Thinking blocks and raw tool results are left out. The title
##              of a conversation (the sidebar) is its first user text.
## USED BY      agent/chat_api.py (GET /agent/sessions and GET /agent/sessions/{id}).
## DEPENDS ON   agent/forms.py (ASK_USER), agent/mcp_bridge.py (tool names).
## WHY          A reload, a second tab or a return days later must show the
##              whole conversation, not only what arrives next.
## =============================================================================

import json
from typing import Any

from te_platform.agent.forms import ASK_USER
from te_platform.agent.mcp_bridge import from_provider_name

TITLE_LENGTH = 70


def _blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = (message.get("content") or {}).get("content", [])
    if isinstance(content, str):  # a plain-string content is one text block
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)]


def _form_result(text: Any) -> dict[str, Any]:
    try:
        payload = json.loads(text) if isinstance(text, str) else {}
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def display_transcript(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn stored messages (Repository.list_messages) into display items."""
    chat = [r for r in rows if r.get("role") in ("user", "assistant")]
    results = _results_by_id(chat)
    forms: set[str] = set()
    items: list[dict[str, Any]] = []
    for r in chat:
        for b in _blocks(r):
            kind = b.get("type")
            if r["role"] == "assistant" and kind == "text" and b.get("text", "").strip():
                items.append({"kind": "assistant_text", "text": b["text"]})
            elif r["role"] == "assistant" and kind == "tool_use":
                items.append(_tool_use_item(b, results, forms))
            elif r["role"] == "user" and kind == "text" and b.get("text", "").strip():
                items.append({"kind": "user_text", "text": b["text"]})
            elif r["role"] == "user" and kind == "tool_result" and b.get("tool_use_id") in forms:
                items.append(_form_result_item(b))
    return items


def _results_by_id(chat: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index the tool results by tool_use_id, so a tool line can say whether it worked."""
    return {
        str(b.get("tool_use_id")): b
        for r in chat
        if r["role"] == "user"
        for b in _blocks(r)
        if b.get("type") == "tool_result"
    }


def _tool_use_item(
    block: dict[str, Any], results: dict[str, dict[str, Any]], forms: set[str]
) -> dict[str, Any]:
    tid = str(block.get("id"))
    if block.get("name") == ASK_USER:
        forms.add(tid)
        form = block.get("input") or {}
        return {
            "kind": "form_asked",
            "tool_use_id": tid,
            "title": str(form.get("title") or ""),
            "questions": [str(q.get("label", "")) for q in form.get("questions", [])],
        }
    result = results.get(tid)
    return {
        "kind": "tool",
        "tool": from_provider_name(str(block.get("name", ""))),
        # None: no result yet (the call waits for the user's confirmation).
        "ok": None if result is None else not result.get("is_error", False),
    }


def _form_result_item(block: dict[str, Any]) -> dict[str, Any]:
    tid = str(block["tool_use_id"])
    payload = _form_result(block.get("content"))
    if payload.get("form") != "submitted":
        return {"kind": "form_skipped", "tool_use_id": tid}
    answers = [
        {"question": str(a.get("question", "")), "display": str(a.get("display", "(skipped)"))}
        for a in payload.get("answers", [])
        if isinstance(a, dict)
    ]
    return {"kind": "form_answers", "tool_use_id": tid, "answers": answers}


def conversation_title(rows: list[dict[str, Any]]) -> str:
    """Return the first user text, shortened: the conversation's name in the sidebar."""
    for item in display_transcript(rows):
        if item["kind"] == "user_text":
            text = " ".join(item["text"].split())
            return text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1].rstrip() + "…"
    return "New conversation"
