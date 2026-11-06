## =============================================================================
## te_platform/agent/context.py — keep a long conversation inside the model's window
## =============================================================================
## GUIDE STEP   extension of 8.4
## PURPOSE      fit_history(history, budget) returns what one model request sees.
##              Under the budget it is the history, unchanged. Over it, tool output
##              that later calls have superseded is thinned, oldest kinds first,
##              only as far as needed. current_state_note() states the session's
##              current facts, from the platform, in the system prompt.
## USED BY      agent/loop.py, on a copy: the stored history is never changed.
## WHY          Measured on real conversations:
##              - Utopia's qwen keeps at most 131072 tokens and silently drops the
##                START of a longer prompt, with no error: rules and early answers
##                vanish. A conversation with experiments and a report reached
##                124000 tokens.
##              - At 73000 tokens the full history was recalled correctly, and a
##                thinned one lost a fact. So nothing is thinned while there is room.
##              - No model summarises anything here: a summary can introduce errors.
##                The designer's words, the agent's own text and the latest result
##                of each tool are always kept whole.
## =============================================================================

import copy
import json
from dataclasses import dataclass
from typing import Any

from te_platform.registry.context import SessionFacts

CHARS_PER_TOKEN = 3.6  # measured against the server's token counts on real conversations

# Arguments that repeat a whole document; only the latest call's are worth keeping.
_BULKY_ARGUMENTS = frozenset(
    {
        "spec__validate__v1",
        "spec__save__v1",
        "graph__flow__v1",
        "report__render_pdf__v1",
        "sim__experiment__v1",
    }
)
# Results made out of date by the next call of the same tool: what a tool said
# about the design as it was then.
_SUPERSEDED_BY_NEXT = frozenset(
    {
        "elicit__next_questions__v1",
        "spec__validate__v1",
        "graph__flow__v1",
    }
)
_KEEP_FROM_RESULT = {
    "elicit__next_questions__v1": ("complete", "open_decisive_slots"),
    "spec__validate__v1": ("valid", "spec_hash"),
}
# Levels, applied in order until the prompt fits.
_LEVEL_SUPERSEDED = 1  # superseded results, and arguments of superseded calls
_LEVEL_POLLS = 2  # job polls: only each job's last one, and only its outcome after that
_LEVEL_LITERATURE = 3  # older searches keep citation and context, not the excerpt
_LEVEL_RESULTS = 4  # results of older verifications and experiments: their verdicts only
_LAST_LEVEL = _LEVEL_RESULTS
_KEEP_SEARCHES = 2  # the latest searches stay whole at every level


@dataclass(frozen=True)
class Thinned:
    """What fit_history did."""

    level: int  # 0: nothing was changed
    tokens: int
    over_budget: bool  # the budget could not be met; the caller must say so


def prompt_tokens(text: str) -> int:
    """Estimate the tokens of a text."""
    return int(len(text) / CHARS_PER_TOKEN)


def _blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _history_tokens(history: list[dict[str, Any]]) -> int:
    return prompt_tokens(json.dumps(history, default=str, ensure_ascii=False))


def _result_payload(block: dict[str, Any]) -> dict[str, Any] | None:
    content = block.get("content")
    if not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _thin(history: list[dict[str, Any]], level: int) -> list[dict[str, Any]]:
    """Return a copy of the history with superseded output thinned, up to `level`."""
    thinned = copy.deepcopy(history)
    names: dict[str, str] = {}
    last_call: dict[str, str] = {}
    calls_of_tool: dict[str, list[str]] = {}
    last_poll: dict[str, str] = {}
    for message in thinned:
        for block in _blocks(message):
            if block.get("type") == "tool_use":
                call_id, name = str(block.get("id")), str(block.get("name"))
                names[call_id] = name
                last_call[name] = call_id
                calls_of_tool.setdefault(name, []).append(call_id)
                if name == "jobs__status__v1":
                    last_poll[str((block.get("input") or {}).get("job_id"))] = call_id
    recent_searches = set(calls_of_tool.get("lit__search__v1", [])[-_KEEP_SEARCHES:])
    polls_kept = set(last_poll.values())
    for message in thinned:
        for block in _blocks(message):
            if block.get("type") == "tool_use":
                name = str(block.get("name"))
                if name in _BULKY_ARGUMENTS and last_call[name] != block.get("id"):
                    # Tool calls must stay paired with their results: only the content goes.
                    block["input"] = {"note": "arguments omitted: a later call supersedes them"}
            elif block.get("type") == "tool_result":
                call_id = str(block.get("tool_use_id"))
                _thin_result(
                    block,
                    names.get(call_id, ""),
                    call_id,
                    level,
                    last_call,
                    recent_searches,
                    polls_kept,
                )
    return thinned


def _thin_result(  # noqa: PLR0913, PLR0917 (the facts one decision needs)
    block: dict[str, Any],
    name: str,
    call_id: str,
    level: int,
    last_call: dict[str, str],
    recent_searches: set[str],
    polls_kept: set[str],
) -> None:
    payload = _result_payload(block)
    result = payload.get("result") if payload else None
    if not isinstance(result, dict):
        return
    if name in _SUPERSEDED_BY_NEXT and last_call.get(name) != call_id:
        kept = {k: result[k] for k in _KEEP_FROM_RESULT.get(name, ()) if k in result}
        payload["result"] = {**kept, "superseded": "a later call of this tool replaces this result"}
    elif level >= _LEVEL_POLLS and name == "jobs__status__v1" and call_id not in polls_kept:
        payload["result"] = {"status": result.get("status"), "superseded": "see the later poll"}
    elif (
        level >= _LEVEL_LITERATURE and name == "lit__search__v1" and call_id not in recent_searches
    ):
        payload["result"] = {
            "hits": [
                {k: h.get(k) for k in ("cite_markdown", "citation_key", "context", "passage_id")}
                for h in result.get("hits", [])
            ],
            "note": "excerpts omitted: read them again with lit.read.v1 and the passage_id",
        }
    elif level >= _LEVEL_RESULTS and name in ("verify__run__v1", "jobs__status__v1"):
        if last_call.get(name) != call_id:
            payload["result"] = _verdicts_only(result)
    else:
        return
    block["content"] = json.dumps(payload, ensure_ascii=False)


def _verdicts_only(result: dict[str, Any]) -> dict[str, Any]:
    keep = {k: result[k] for k in ("verification_ref", "kind", "status", "job_id") if k in result}
    verdicts = result.get("verdicts")
    if isinstance(verdicts, list):
        keep["verdicts"] = [
            {k: v.get(k) for k in ("failure_mode", "subject", "status")}
            for v in verdicts
            if isinstance(v, dict)
        ]
    keep["note"] = "details omitted: an older result; call the tool again if you need them"
    return keep


def fit_history(history: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], Thinned]:
    """Return the history that fits `budget` tokens, thinned as little as possible."""
    tokens = _history_tokens(history)
    if tokens <= budget:
        return history, Thinned(level=0, tokens=tokens, over_budget=False)
    fitted = history
    for level in range(_LEVEL_SUPERSEDED, _LAST_LEVEL + 1):
        fitted = _thin(history, level)
        tokens = _history_tokens(fitted)
        if tokens <= budget:
            return fitted, Thinned(level=level, tokens=tokens, over_budget=False)
    return fitted, Thinned(level=_LAST_LEVEL, tokens=tokens, over_budget=True)


def current_state_note(facts: SessionFacts, state: str, *, full: bool) -> str:
    """Return the session's current facts, from the platform, for the system prompt.

    The note is always there; the design is added once older output is thinned,
    since it may be what the thinned output described.
    """
    open_slots = ", ".join(facts.open_decisive_slots) or "none"
    lines = [
        (
            "Current state of this session (from the platform, always up to date; "
            "older tool results may describe an earlier design):"
        ),
        f"- State: {state}. Decisive questions still open: {open_slots}.",
        f"- Latest verification: {facts.verification_ref or 'none for the current design'}.",
    ]
    if full and facts.current_spec is not None:
        lines.append(
            "- Current design (older tool output was shortened to fit the model's window):\n"
            + json.dumps(facts.current_spec, ensure_ascii=False, default=str)
        )
    return "\n".join(lines)
