## =============================================================================
## te_platform/agent/forms.py — structured questions ("forms") the agent asks
## =============================================================================
## GUIDE STEP   none yet (extension of phases 8-9: the chat's question forms)
## PURPOSE      The agent-side tool `ask_user`: instead of asking in prose,
##              the model can send a small form (single or multiple choice,
##              yes/no, number, range, open text). This module holds
##              1. AskUserInput, the form the model sends, validated
##                 strictly (bounded sizes, options only where they belong);
##              2. ASK_USER_TOOL, the ToolDef offered to the model;
##              3. validate_answers(), which checks the browser's answers
##                 against the form the SERVER stored (never against what
##                 the browser claims the form was);
##              4. answers_result() / skipped_result(), the JSON text the
##                 model receives as the tool result.
##              A question may carry the agent's `estimate` (pre-filled, with
##              its `basis`): the designer keeps it with one click or changes
##              it, and each answer says whether the estimate was kept
##              (`estimate_accepted`). This is how the short interview
##              proposes secondary values instead of asking for each.
## USED BY      agent/loop.py (offers the tool, pauses the turn, settles the
##              answers), agent/chat_api.py (MessageIn.form_answers; rejects
##              invalid answers with 422 before any model call),
##              agent/events.py (FormRequested carries the form),
##              webapp/static/chat.js (renders the form, sends the answers).
## DEPENDS ON   pydantic, agent/providers/base.py (ToolDef).
## WHY          Most interview questions are structured (the protocol's
##              answer types: enum, number, range, text); answering them by
##              clicking is faster and less ambiguous than prose, and the
##              answers arrive already typed. The tool is agent-only, not an
##              MCP tool: other MCP clients have their own user interface.
## SECURITY     Everything the model writes into a form is shown with
##              textContent only (chat.js). Answers are untrusted input: each
##              one is checked here against the stored form; a value outside
##              the options, a non-finite number or an oversized text is
##              rejected, never passed to the model.
## =============================================================================

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from te_platform.agent.providers.base import ToolDef

## The provider-side tool name. MCP tool ids always contain dots
## ("verify.run.v1" -> "verify__run__v1"), so this name never collides.
ASK_USER = "ask_user"

QuestionKind = Literal["single_choice", "multiple_choice", "yes_no", "number", "range", "text"]
_CHOICE_KINDS = ("single_choice", "multiple_choice")
_NUMERIC_KINDS = ("number", "range")

## Bounds on what the model may send and the browser may answer.
MAX_QUESTIONS = 10
MAX_OPTIONS = 12
MAX_TEXT_ANSWER = 2000
MAX_OTHER_TEXT = 500
MAX_FORMS_PER_MESSAGE = 4
_ID_PATTERN = r"^[A-Za-z0-9_.:\[\]-]{1,100}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormOption(_Strict):
    """One choice: the value recorded, and the text the designer sees."""

    value: str = Field(
        pattern=r"^[A-Za-z0-9_.:-]{1,80}$",
        description="Machine value, e.g. a protocol choice such as 'community_reward'.",
    )
    label: str = Field(min_length=1, max_length=200, description="What the designer reads.")


class FormQuestion(_Strict):
    """One question of a form."""

    id: str = Field(
        pattern=_ID_PATTERN,
        description="Stable id, unique in the form. Use the protocol slot_id when the "
        "question answers a slot (e.g. 'participants.N').",
    )
    label: str = Field(min_length=1, max_length=300, description="The question, in plain words.")
    help: str = Field(
        default="", max_length=600, description="One sentence on why it is asked (optional)."
    )
    kind: QuestionKind = Field(
        description="single_choice (radio buttons), multiple_choice (tick several), yes_no, "
        "number, range (lowest and highest realistic value), text (open answer)."
    )
    options: list[FormOption] = Field(
        default_factory=list,
        max_length=MAX_OPTIONS,
        description="Only for single_choice and multiple_choice: 2 to 12 options.",
    )
    allow_other: bool = Field(
        default=False,
        description="Choice questions only: add an 'Other' option with a text field.",
    )
    allow_unknown: bool = Field(
        default=True, description="Offer 'I don't know' (keep true unless the slot forbids it)."
    )
    required: bool = Field(default=True, description="False: the designer may leave it empty.")
    unit: str = Field(
        default="", max_length=30, description="number/range only, e.g. 'people' or 'hours/week'."
    )
    min: float | None = Field(
        default=None,
        description="number/range only: the lowest POSSIBLE value (e.g. 0 for a count, 1 for "
        "members), never a guess of a plausible one.",
    )
    max: float | None = Field(
        default=None,
        description="number/range only: the highest POSSIBLE value (e.g. 1 for a share or "
        "probability, 5 for a 1-5 rating). Omit it for counts, amounts and rates: the "
        "designer's real numbers may be far larger than you expect.",
    )
    placeholder: str = Field(default="", max_length=120, description="Hint shown in empty fields.")
    estimate: Any = Field(
        default=None,
        description="Your proposed answer, shown pre-filled; the designer keeps it or changes "
        "it. Same shape as an answer: an option value (single_choice), a list of option "
        "values (multiple_choice), true/false (yes_no), a number, {min, max} (range), or text.",
    )
    basis: str = Field(
        default="",
        max_length=300,
        description="Required with an estimate: in one sentence, what it is based on "
        "(the designer's own words, or a typical value for comparable systems).",
    )

    @model_validator(mode="before")
    @classmethod
    def _type_means_kind(cls, data: Any) -> Any:
        """Accept `type` for `kind`: some models (gpt-oss) keep writing it.

        The stored and displayed form always says `kind` (model_dump).
        """
        if isinstance(data, dict) and "type" in data and "kind" not in data:
            data = {**data, "kind": data["type"]}
            del data["type"]
        return data

    @model_validator(mode="after")
    def _fits_its_kind(self) -> "FormQuestion":
        if self.kind in _CHOICE_KINDS:
            if len(self.options) < 2:  # noqa: PLR2004  a choice needs two options
                raise ValueError(f"question {self.id!r}: {self.kind} needs at least 2 options")
            values = [o.value for o in self.options]
            if len(set(values)) != len(values):
                raise ValueError(f"question {self.id!r}: option values must be unique")
        elif self.options or self.allow_other:
            raise ValueError(f"question {self.id!r}: options/allow_other only for choices")
        if self.kind not in _NUMERIC_KINDS and (
            self.unit or self.min is not None or self.max is not None
        ):
            raise ValueError(f"question {self.id!r}: unit/min/max only for number and range")
        for bound in (self.min, self.max):
            if bound is not None and not math.isfinite(bound):
                raise ValueError(f"question {self.id!r}: min/max must be finite numbers")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"question {self.id!r}: min is greater than max")
        self._check_estimate()
        return self

    def _check_estimate(self) -> None:
        """Require a basis with an estimate, and an estimate this question accepts."""
        if self.estimate is None:
            if self.basis:
                raise ValueError(f"question {self.id!r}: basis only goes with an estimate")
            return
        if not self.basis.strip():
            raise ValueError(f"question {self.id!r}: an estimate needs its basis")
        try:
            _check_value(self, FormAnswerIn(status="answered", value=self.estimate))
        except FormAnswerError as exc:
            raise ValueError(f"question {self.id!r}: the estimate does not fit: {exc}") from exc


class AskUserInput(_Strict):
    """A form: 1 to 6 related questions shown together."""

    title: str = Field(
        default="", max_length=200, description="Short heading, e.g. 'Who takes part'."
    )
    intro: str = Field(default="", max_length=1000, description="One or two sentences above.")
    questions: list[FormQuestion] = Field(min_length=1, max_length=MAX_QUESTIONS)

    @model_validator(mode="after")
    def _unique_ids(self) -> "AskUserInput":
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question ids must be unique within a form")
        return self


def parse_form(arguments: dict[str, Any]) -> AskUserInput:
    """Validate the model's ask_user arguments; raise FormError with a fixable message."""
    try:
        return AskUserInput.model_validate(arguments)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'form'}: {e['msg']}" for e in exc.errors()
        )
        raise FormError(f"The form is invalid, so it was not shown. Fix it: {problems}") from exc


class FormError(ValueError):
    """A form the model sent cannot be shown (the message tells it why)."""


class FormAnswerError(ValueError):
    """An answer from the browser does not fit its form (shown to the user)."""

    def __init__(self, message: str, question_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.question_id = question_id


## --- The tool offered to the model -----------------------------------------------------
def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace every {"$ref": "#/$defs/X"} by X itself: one self-contained schema."""
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return walk(defs[ref.removeprefix("#/$defs/")])
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    result: dict[str, Any] = walk(schema)
    return result


ASK_USER_TOOL = ToolDef(
    name=ASK_USER,
    description=(
        "Show the designer a small form and wait for their answers. Use it for questions "
        "with fixed options (single_choice, multiple_choice, yes_no), numbers, ranges, or "
        "short open answers (text); group up to 10 related questions. To propose a value "
        "instead of asking for it, give the question an `estimate` (pre-filled) and its "
        "`basis`: the designer keeps it with one click or changes it. The turn ends "
        "when you call it: say nothing after it. The answers come back as this tool's "
        "result, each with its status (answered, unknown, skipped), value and readable "
        "label. If the designer types a message instead, the result says the form was "
        "skipped and their message follows."
    ),
    input_schema=_inline_refs(AskUserInput.model_json_schema()),
)


## --- Answers from the browser ------------------------------------------------------------
class FormAnswerIn(_Strict):
    """One answer as the browser sends it (checked against the form below)."""

    status: Literal["answered", "unknown", "skipped"]
    value: Any = None
    other: str | None = Field(default=None, max_length=MAX_OTHER_TEXT)


def _finite_number(v: Any, qid: str) -> float:
    # bool is an int in Python: True must not count as the number 1.
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise FormAnswerError("Enter a number.", qid)
    return float(v)


def _in_bounds(q: FormQuestion, x: float) -> None:
    if q.min is not None and x < q.min:
        raise FormAnswerError(f"The value must be at least {q.min:g}.", q.id)
    if q.max is not None and x > q.max:
        raise FormAnswerError(f"The value must be at most {q.max:g}.", q.id)


def _check_choice(q: FormQuestion, a: FormAnswerIn) -> dict[str, Any]:
    labels = {o.value: o.label for o in q.options}
    other = (a.other or "").strip()
    if other and not q.allow_other:
        raise FormAnswerError("This question has no 'Other' option.", q.id)
    if q.kind == "single_choice":
        if a.value is None and other:
            return {"value": None, "other": other, "display": f"Other: {other}"}
        if not isinstance(a.value, str) or a.value not in labels or other:
            raise FormAnswerError("Choose one of the options.", q.id)
        return {"value": a.value, "display": labels[a.value]}
    values = a.value if a.value is not None else []
    if (
        not isinstance(values, list)
        or not all(isinstance(v, str) and v in labels for v in values)
        or len(set(values)) != len(values)
    ):
        raise FormAnswerError("Choose among the listed options.", q.id)
    if not values and not other:
        raise FormAnswerError("Tick at least one option.", q.id)
    shown = [labels[v] for v in values] + ([f"Other: {other}"] if other else [])
    out: dict[str, Any] = {"value": values, "display": "; ".join(shown)}
    if other:
        out["other"] = other
    return out


def _check_yes_no(q: FormQuestion, a: FormAnswerIn) -> dict[str, Any]:
    if not isinstance(a.value, bool):
        raise FormAnswerError("Answer yes or no.", q.id)
    return {"value": a.value, "display": "Yes" if a.value else "No"}


def _check_number(q: FormQuestion, a: FormAnswerIn) -> dict[str, Any]:
    x = _finite_number(a.value, q.id)
    _in_bounds(q, x)
    return {"value": x, "display": f"{x:g}{_unit(q)}"}


def _check_range(q: FormQuestion, a: FormAnswerIn) -> dict[str, Any]:
    if not isinstance(a.value, dict) or set(a.value) != {"min", "max"}:
        raise FormAnswerError("Enter the lowest and the highest value.", q.id)
    lo, hi = _finite_number(a.value["min"], q.id), _finite_number(a.value["max"], q.id)
    if lo > hi:
        raise FormAnswerError("The lowest value is greater than the highest.", q.id)
    _in_bounds(q, lo)
    _in_bounds(q, hi)
    return {"value": {"min": lo, "max": hi}, "display": f"{lo:g} to {hi:g}{_unit(q)}"}


def _check_text(q: FormQuestion, a: FormAnswerIn) -> dict[str, Any]:
    if not isinstance(a.value, str) or not a.value.strip():
        raise FormAnswerError("Write an answer.", q.id)
    if len(a.value) > MAX_TEXT_ANSWER:
        raise FormAnswerError(f"Keep the answer under {MAX_TEXT_ANSWER} characters.", q.id)
    text = a.value.strip()
    return {"value": text, "display": text}


def _unit(q: FormQuestion) -> str:
    return f" {q.unit}" if q.unit else ""


_CHECKS = {
    "single_choice": _check_choice,
    "multiple_choice": _check_choice,
    "yes_no": _check_yes_no,
    "number": _check_number,
    "range": _check_range,
    "text": _check_text,
}


def _check_value(q: FormQuestion, a: FormAnswerIn) -> dict[str, Any]:
    """Check an 'answered' answer; return its value and readable form."""
    if a.other and q.kind not in _CHOICE_KINDS:
        raise FormAnswerError("This question has no 'Other' option.", q.id)
    return _CHECKS[q.kind](q, a)


def validate_answers(form: AskUserInput, raw: Any) -> list[dict[str, Any]]:
    """Check the browser's answers against the stored form; return one entry per question.

    Raises FormAnswerError (with the question id) for the first answer that
    does not fit. Every question gets an entry, in the form's order.
    """
    if not isinstance(raw, dict):
        raise FormAnswerError("The answers are not in the expected format.")
    known = {q.id for q in form.questions}
    unknown_ids = set(raw) - known
    if unknown_ids:
        raise FormAnswerError("The answers do not match the form; reload the page.")
    return [_check_one(q, raw.get(q.id)) for q in form.questions]


def _same(a: Any, b: Any) -> bool:
    """Equal answers; ticked options compare in any order."""
    if isinstance(a, list) and isinstance(b, list):
        return sorted(a) == sorted(b)
    return bool(a == b)


def _check_one(q: FormQuestion, raw: Any) -> dict[str, Any]:
    """Check the answer to one question (None: the browser sent none)."""
    entry: dict[str, Any] = {"question_id": q.id, "question": q.label, "kind": q.kind}
    if raw is None:
        a = FormAnswerIn(status="skipped")
    else:
        try:
            a = FormAnswerIn.model_validate(raw)
        except ValidationError as exc:
            raise FormAnswerError("The answer is not in the expected format.", q.id) from exc
    if a.status == "answered":
        checked = _check_value(q, a)
        if q.estimate is not None:
            proposed = _check_value(q, FormAnswerIn(status="answered", value=q.estimate))
            # Kept = the same value as proposed (the designer did not change it).
            checked["estimate_accepted"] = _same(checked["value"], proposed["value"])
        return {**entry, "status": "answered", **checked}
    # "I don't know" only where allowed; a skip only for optional questions.
    if (a.status == "unknown" and not q.allow_unknown) or (a.status == "skipped" and q.required):
        raise FormAnswerError("This question needs an answer.", q.id)
    if a.status == "unknown":
        return {**entry, "status": "unknown", "display": "I don't know"}
    return {**entry, "status": "skipped"}


def validate_all(
    forms: dict[str, AskUserInput], raw: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Check the answers to several open forms (tool_use_id -> answers)."""
    if len(raw) > MAX_FORMS_PER_MESSAGE:
        raise FormAnswerError("Too many forms answered at once.")
    stray = set(raw) - set(forms)
    if stray:
        raise FormAnswerError("This form is no longer open; reload the page and answer again.")
    return {tid: validate_answers(forms[tid], answers) for tid, answers in raw.items()}


## --- What the model receives -------------------------------------------------------------
def answers_result(answers: list[dict[str, Any]]) -> str:
    """Build the tool result for a submitted form (JSON text)."""
    return json.dumps(
        {
            "form": "submitted",
            "note": "The designer answered by selecting or typing in the form: each answered "
            "value is explicit. 'unknown' means they chose 'I don't know'. "
            "estimate_accepted true: they kept your estimate (record it as 'estimated'); "
            "false: they changed it (record their value as 'committed').",
            "answers": answers,
        },
        ensure_ascii=False,
    )


def skipped_result() -> str:
    """Build the tool result for a form the designer did not fill in."""
    return json.dumps(
        {
            "form": "not_submitted",
            "note": "The designer did not use the form. If they wrote a message, it follows; "
            "otherwise ask again.",
        }
    )
