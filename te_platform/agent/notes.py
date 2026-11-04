## =============================================================================
## te_platform/agent/notes.py — platform notes in the user's message
## =============================================================================
## PURPOSE      Tell the model about things that happened outside the chat.
##              Today one: the designer edited the design in the form and the
##              form stored it in the session (agent/spec_api.py). The model
##              sees only the conversation, so without a note it answers
##              "there is no design yet" while the session holds one.
## FORMAT       A text block before the user's own text, starting with
##              NOTE_PREFIX. The transcript (agent/transcript.py) and the
##              report (reports/design.py, reports/method.py) skip such blocks:
##              they are not the designer's words. The system prompt says
##              what they are (prompts/system.md).
## USED BY      agent/chat_api.py (decides), agent/loop.py (adds the block).
## =============================================================================

import re
from typing import Any

import yaml

NOTE_PREFIX = "[Platform note, not written by the designer]"


def is_platform_note(text: str) -> bool:
    """Return True for a text block written by the platform, not by the designer."""
    return text.startswith(NOTE_PREFIX)


def spec_from_form_note(spec: dict[str, Any]) -> str:
    """Return the note for a design the designer saved in the form since the last message."""
    return (
        f"{NOTE_PREFIX} The designer edited the design in the form, and the session now "
        "holds that version as its current design. Work from it: the tools use the "
        "session's current design when called without a spec (verify.run.v1 checks it). "
        "Any earlier verification is of an older version. The design:\n"
        f"```yaml\n{yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)}```"
    )


## --- Guards against two loops seen in live use (agent/loop.py) ---------------------------
## 1. The model resent the same failing call until the turn limit (a time
##    bank interview: every answer refused with the same error, five rounds).
## 2. The model wrote "let me check the research" and ended its turn without
##    calling any tool, so the designer got no answer.

REPEATED_ERROR_NOTE = (
    "[Platform note] This tool has now failed twice in this turn with the same error. "
    "Do not send it again unchanged: read the error, change the arguments as it says, "
    "or tell the designer in plain words what could not be done."
)


def not_rerun_text(error: str) -> str:
    """Return the tool result for a call that already failed with the same arguments."""
    return (
        "Not run again: this exact call (same tool, same arguments) already failed in this "
        f"turn with: {error} Change the arguments as the error says, or tell the designer "
        "what could not be done."
    )


PROMISE_NOTE = (
    f"{NOTE_PREFIX} Your last message said you would look something up or check "
    "something, but you ended without calling a tool. If you meant to, call the tool now; "
    "otherwise give the designer your answer."
)

EMPTY_REPLY_NOTE = (
    f"{NOTE_PREFIX} Your last reply was empty: no text and no tool call. Answer the "
    "designer now, or call the tool you need."
)

## A short closing message that announces an action instead of doing it.
_PROMISE = re.compile(
    r"\b(let me|i'll|i will|i'm going to|i am going to|lasciami|fammi|ora|adesso)\s+"
    r"(now\s+|first\s+|quickly\s+)?"
    r"(check|search|look|pull|find|verify|run|query|fetch|consult|read|"
    r"controll|cerc|verific|guard)",
    re.IGNORECASE,
)
PROMISE_MAX_CHARS = 600


def promised_action(text: str) -> bool:
    """Return True when a short final message announces a lookup without doing it."""
    text = text.strip()
    if not text or len(text) > PROMISE_MAX_CHARS:
        return False
    return bool(_PROMISE.search(text[-300:]))
