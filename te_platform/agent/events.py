## =============================================================================
## te_platform/agent/events.py — the events streamed to the browser (SSE)
## =============================================================================
## GUIDE STEP   8.4 (the event models: agent/loop.py yields them),
##              8.5 (to_sse: the SSE text format, used by agent/chat_api.py),
##              10.3 (JobProgress.download_url)
## PURPOSE      Defines every event the agent service can send to the chat page
##              during one turn, as typed Pydantic models, and to_sse(), which
##              formats one event in the Server-Sent Events text format:
##
##                  event: text_delta
##                  data: {"type": "text_delta", "text": "Hello"}
##                  <empty line>
##
##              The empty line marks the end of one event. The type appears
##              twice on purpose: the browser (webapp/static/chat.js)
##              dispatches on the `event:` line, while simpler clients (the
##              evaluation harness, evals/run.py) read only the `data:` JSON
##              and still know what each event is.
## USED BY      agent/loop.py (creates the events), agent/chat_api.py (turns
##              them into the streamed response), webapp/static/chat.js (parses
##              them; its event names MUST match the `type` values below),
##              evals/run.py (reads data["type"]).
## DEPENDS ON   pydantic.
## WHY          A closed, typed list of events is a contract between server
##              and browser: adding or renaming one is a visible change in one
##              file, reviewed together with chat.js (architecture §3.4, §3.5).
## ACTIVATE     8.4: uncomment the models (the loop needs them). 8.5: the
##              twice-commented json import and to_sse(); test the formatting
##              in test_platform_agent.py (multi-line text must not break the
##              SSE framing). 10.3: JobProgress.download_url.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep every class name and every
## `type` value exactly as written: loop.py, app.py, chat.js and evals/run.py
## rely on them.
##
## Guide 8.4 (the event models)
## [ ] 1. Imports at the top: Any and Literal from typing, BaseModel and
##        Field from pydantic.
## [ ] 2. One Pydantic model per event, each with a one-line docstring. Each
##        starts with a fixed `type`:
##          | type: Literal["text_delta"] = "text_delta"
##        Models and their fields:
##        - TextDelta ("text_delta"): text;
##        - ToolStarted ("tool_started"): tool_use_id, tool, summary="";
##        - ToolFinished ("tool_finished"): tool_use_id, tool, ok,
##          error_code: str | None = None;
##        - ConfirmationRequired ("confirmation_required"): tool_use_id, tool,
##          question;
##        - SpecUpdated ("spec_updated"): spec_hash, state, slots (a list of
##          dicts, Field(default_factory=list));
##        - VerdictUpdated ("verdict_updated"): verification_ref, verdicts;
##        - JobProgress ("job_progress"): job_id, status,
##          progress: float | None = None (download_url comes at 10.3);
##        - Done ("done"): reason, a Literal of "final_answer",
##          "awaiting_confirmation", "awaiting_input", "limit_reached",
##          "refusal"; usage (dict[str, int], default_factory=dict);
##        - ErrorEvent ("error"): message, correlation_id.
##        - (forms extension) FormRequested ("form_requested"):
##          tool_use_id, form (dict[str, Any], an agent/forms.py
##          AskUserInput as JSON).
## [ ] 3. `AgentEvent`: the union (with |) of the ten models.
## [ ] 4. Check: `uv run mypy te_platform` (the loop tests of guide 8.4 use
##        these models).
##
## Guide 8.5 (later: the "# # " lines in the SOLUTION)
## [ ] 5. Add `import json` at the top.
## [ ] 6. `to_sse(event: AgentEvent) -> str`: payload =
##        event.model_dump(mode="json"), then return
##          | data = json.dumps(payload, ensure_ascii=False)
##          | return f"event: {event.type}\ndata: {data}\n\n"
##        json.dumps keeps the data on one line (see the docstring).
## [ ] 7. Check: activate test_sse_text_with_newlines_stays_one_event in
##        tests/platform_tests/test_platform_agent.py, then
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##          | uv run mypy te_platform
##
## Guide 10.3 (later: the "# # " line in the SOLUTION)
## [ ] 8. In JobProgress, toggle `download_url: str | None = None`: the
##        signed link of a report job (tools/report_render_pdf.py), which the
##        chat shows when the PDF is ready.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## Phase 8.5: json is used only by to_sse() at the end of the file.
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

## --- One model per event ---------------------------------------------------------
## Each model has a fixed `type` (a Literal), so the event name can never be
## misspelled when an event is created.


class TextDelta(BaseModel):
    """A piece of the assistant's visible answer, as it is generated."""

    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolStarted(BaseModel):
    """The model asked for a tool; the agent is running it now."""

    type: Literal["tool_started"] = "tool_started"
    tool_use_id: str  # the model's ID for this call (pairs started/finished)
    tool: str  # our tool id, e.g. "verify.run.v1"
    summary: str = ""  # short human text, e.g. "Verifying your design…"


class ToolFinished(BaseModel):
    """A tool call has returned (successfully or with a ToolError)."""

    type: Literal["tool_finished"] = "tool_finished"
    tool_use_id: str
    tool: str
    ok: bool
    # For errors: the ToolError code (e.g. "precondition_failed"), so the UI
    # can show a neutral note instead of an alarming red error.
    error_code: str | None = None


class ConfirmationRequired(BaseModel):
    """The model wants to run an EXPENSIVE tool and the user must agree first.

    Expensive means: the policy's cost class has ask_user_first. The turn
    stops here; the browser shows Yes/No buttons, and the user's answer
    arrives with the next POST (see loop.py).
    """

    type: Literal["confirmation_required"] = "confirmation_required"
    tool_use_id: str
    tool: str
    question: str  # e.g. "This simulation takes about a minute. Run it?"


class FormRequested(BaseModel):
    """The model asked structured questions (tool ask_user, agent/forms.py).

    Like a confirmation, the turn stops here: the browser renders the form,
    and the answers arrive with the next POST as `form_answers`.
    """

    type: Literal["form_requested"] = "form_requested"
    tool_use_id: str
    form: dict[str, Any]  # agent/forms.py AskUserInput, already validated


class SpecUpdated(BaseModel):
    """The session's spec changed (an answer was recorded): refresh the panel."""

    type: Literal["spec_updated"] = "spec_updated"
    spec_hash: str
    state: str  # session state after the change (registry/state.py)
    # Every answered slot: {slot_id, indices, status, value}, status being
    # committed | unknown | default (the panel rebuilds its list from it).
    slots: list[dict[str, Any]] = Field(default_factory=list)


class VerdictUpdated(BaseModel):
    """A verification finished: show the verdicts in the panel (verdict.js)."""

    type: Literal["verdict_updated"] = "verdict_updated"
    verification_ref: str
    verdicts: list[dict[str, Any]]


class JobProgress(BaseModel):
    """A background job (simulation, report) changed status."""

    type: Literal["job_progress"] = "job_progress"
    job_id: str
    status: str  # queued | running | finished | failed | cancelled
    progress: float | None = None
    ## Guide 10.3: a report job also carries its signed download link.
    download_url: str | None = None
    # monte_carlo | trajectory | report: lets the page name the job and
    # know whether a finished one was a simulation.
    kind: str | None = None


class Done(BaseModel):
    """End of the turn. `reason` tells the UI why it stopped."""

    type: Literal["done"] = "done"
    reason: Literal[
        "final_answer", "awaiting_confirmation", "awaiting_input", "limit_reached", "refusal"
    ]
    usage: dict[str, int] = Field(default_factory=dict)  # LLM tokens used this turn


class ErrorEvent(BaseModel):
    """Something failed in the service itself (not a tool error, which the model handles).

    The message is safe to show; details stay in the log.
    """

    type: Literal["error"] = "error"
    message: str
    correlation_id: str
    # True when the turn failed before any answer and the user's message was
    # removed from the history (agent/chat_api.py): the page offers it back.
    message_discarded: bool = False


## The union of all event types: loop.py yields `AgentEvent` values.
AgentEvent = (
    TextDelta
    | ToolStarted
    | ToolFinished
    | ConfirmationRequired
    | FormRequested
    | SpecUpdated
    | VerdictUpdated
    | JobProgress
    | Done
    | ErrorEvent
)


## Phase 8.5: the Server-Sent Events text format (agent/chat_api.py streams it).
## The data is JSON on ONE line: json.dumps never emits raw newlines (they are
## escaped as \n inside strings), so text containing line breaks can never be
## mistaken for the end of an event. `type` stays inside the data too (see
## PURPOSE): self-describing JSON.
def to_sse(event: AgentEvent) -> str:
    """Format one event as SSE text: an `event:` line, a `data:` line, a blank line."""
    payload = event.model_dump(mode="json")
    return f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
