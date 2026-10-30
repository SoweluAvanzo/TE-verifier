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
