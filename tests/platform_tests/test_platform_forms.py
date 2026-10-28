## =============================================================================
## tests/platform_tests/test_platform_forms.py — the agent's question forms
## =============================================================================
## GUIDE STEP   none yet (forms extension of phases 8-9; te_platform/agent/forms.py)
## PURPOSE      The form the model sends (ask_user) is validated strictly, and
##              every answer from the browser is checked against the form the
##              server stored: values outside the options, non-finite numbers,
##              inverted ranges, oversized texts and "I don't know" where it is
##              not allowed are refused. No database, no network.
## USED BY      pytest. The loop and HTTP tests of the forms are in
##              test_platform_agent.py (they need the MCP server and Redis).
## =============================================================================

import json
import math
from typing import Any

import pytest

from te_platform.agent.forms import (
    ASK_USER_TOOL,
    MAX_TEXT_ANSWER,
    FormAnswerError,
    FormError,
    answers_result,
    parse_form,
    skipped_result,
    validate_all,
    validate_answers,
)

## One question of every kind, as the model would send it.
FORM: dict[str, Any] = {
    "title": "Your exchange",
    "questions": [
        {
            "id": "meta.archetype",
            "label": "What is the exchange mainly for?",
            "kind": "single_choice",
            "options": [
                {"value": "community_reward", "label": "Rewarding contributions"},
                {"value": "marketplace", "label": "Buying and selling"},
            ],
            "allow_other": True,
        },
        {
            "id": "goods",
            "label": "What can people get?",
            "kind": "multiple_choice",
            "options": [
                {"value": "food", "label": "Food"},
                {"value": "help", "label": "Help at home"},
                {"value": "tools", "label": "Tools"},
            ],
        },
        {"id": "transferable", "label": "Can credits be given away?", "kind": "yes_no"},
        {
            "id": "participants.N",
            "label": "How many people take part?",
            "kind": "number",
            "unit": "people",
            "min": 1,
        },
        {
            "id": "hours",
            "label": "Hours per week per volunteer?",
            "kind": "range",
            "min": 0,
            "max": 168,
        },
        {
            "id": "notes",
            "label": "Anything else?",
            "kind": "text",
            "required": False,
            "allow_unknown": False,
        },
    ],
}

GOOD: dict[str, Any] = {
    "meta.archetype": {"status": "answered", "value": "community_reward"},
    "goods": {"status": "answered", "value": ["food", "help"]},
    "transferable": {"status": "answered", "value": False},
    "participants.N": {"status": "answered", "value": 30},
    "hours": {"status": "answered", "value": {"min": 5, "max": 10}},
}


def _form() -> Any:
    return parse_form(FORM)


def _with(qid: str, answer: Any) -> dict[str, Any]:
    return {**GOOD, qid: answer}


## --- The form the model sends ------------------------------------------------------------
def test_a_form_of_every_kind_is_accepted() -> None:
    form = _form()
    assert [q.kind for q in form.questions] == [
        "single_choice",
        "multiple_choice",
        "yes_no",
        "number",
        "range",
        "text",
    ]


def test_tool_schema_is_self_contained() -> None:
    # One schema without $ref/$defs: what every tool-use API accepts.
    text = json.dumps(ASK_USER_TOOL.input_schema)
    assert "$ref" not in text and "$defs" not in text
    assert ASK_USER_TOOL.name == "ask_user" and "." not in ASK_USER_TOOL.name


def _question(**fields: Any) -> dict[str, Any]:
    return {"questions": [{"id": "q", "label": "Q?", **fields}]}


@pytest.mark.parametrize(
    ("form", "problem"),
    [
        (_question(kind="single_choice", options=[{"value": "a", "label": "A"}]), "2 options"),
        (
            _question(
                kind="multiple_choice",
                options=[{"value": "a", "label": "A"}, {"value": "a", "label": "B"}],
            ),
            "unique",
        ),
        (_question(kind="number", options=[{"value": "a", "label": "A"}]), "only for choices"),
        (_question(kind="text", allow_other=True), "only for choices"),
        (_question(kind="text", unit="people"), "number and range"),
        (_question(kind="range", min=10, max=1), "greater than max"),
        (_question(kind="number", min=math.inf), "finite"),
        (_question(kind="slider"), "kind"),
        (_question(kind="text", onclick="x"), "Extra inputs"),
        ({"questions": []}, "questions"),
        (
            {"questions": [{"id": "a", "label": "A", "kind": "text"}] * 2},
            "unique",
        ),
        (_question(kind="text", id="bad id with spaces"), "id"),
    ],
)
def test_invalid_forms_are_refused_with_a_fixable_message(form: Any, problem: str) -> None:
    with pytest.raises(FormError, match="The form is invalid") as err:
        parse_form(form)
    assert problem in str(err.value)


def test_form_sizes_are_bounded() -> None:
    many = {"questions": [{"id": f"q{i}", "label": "Q?", "kind": "text"} for i in range(11)]}
    with pytest.raises(FormError):
        parse_form(many)
    with pytest.raises(FormError):
        parse_form(_question(kind="text", label="x" * 301))


## --- Answers from the browser ------------------------------------------------------------
def test_good_answers_come_back_typed_with_readable_labels() -> None:
    out = {a["question_id"]: a for a in validate_answers(_form(), GOOD)}
    assert out["meta.archetype"]["display"] == "Rewarding contributions"
    assert out["goods"]["value"] == ["food", "help"]
    assert out["goods"]["display"] == "Food; Help at home"
    assert out["transferable"] == {**out["transferable"], "value": False, "display": "No"}
    assert out["participants.N"]["display"] == "30 people"
    assert out["hours"]["value"] == {"min": 5.0, "max": 10.0}
    assert out["notes"]["status"] == "skipped"  # optional and not answered
    # Every question gets an entry, in the form's order.
    assert list(out) == [q["id"] for q in FORM["questions"]]


def test_other_and_unknown_are_accepted_where_allowed() -> None:
    answers = _with("meta.archetype", {"status": "answered", "value": None, "other": "Barter"})
    answers["participants.N"] = {"status": "unknown"}
    out = {a["question_id"]: a for a in validate_answers(_form(), answers)}
    assert out["meta.archetype"]["other"] == "Barter"
    assert out["meta.archetype"]["display"] == "Other: Barter"
    assert out["participants.N"]["status"] == "unknown"


@pytest.mark.parametrize(
    ("qid", "answer", "message"),
    [
        ("meta.archetype", {"status": "answered", "value": "<script>"}, "Choose one"),
        ("goods", {"status": "answered", "value": ["food", "food"]}, "Choose among"),
        ("goods", {"status": "answered", "value": ["cars"]}, "Choose among"),
        ("goods", {"status": "answered", "value": []}, "at least one"),
        ("goods", {"status": "answered", "value": ["food"], "other": "x"}, "no 'Other'"),
        ("transferable", {"status": "answered", "value": "yes"}, "yes or no"),
        ("participants.N", {"status": "answered", "value": True}, "a number"),
        ("participants.N", {"status": "answered", "value": "30"}, "a number"),
        ("participants.N", {"status": "answered", "value": 0}, "at least 1"),
        ("participants.N", {"status": "answered", "value": math.nan}, "a number"),
        ("hours", {"status": "answered", "value": {"min": 10, "max": 5}}, "greater than"),
        ("hours", {"status": "answered", "value": {"min": 1, "max": 200}}, "at most 168"),
        ("hours", {"status": "answered", "value": {"min": 1}}, "lowest and the highest"),
        ("participants.N", {"status": "skipped"}, "needs an answer"),
        ("notes", {"status": "unknown"}, "needs an answer"),
        ("notes", {"status": "answered", "value": "x" * (MAX_TEXT_ANSWER + 1)}, "under"),
        ("notes", {"status": "answered", "value": "   "}, "Write an answer"),
        ("participants.N", {"status": "answered", "value": 3, "extra": 1}, "expected format"),
    ],
)
def test_answers_that_do_not_fit_are_refused(qid: str, answer: Any, message: str) -> None:
    with pytest.raises(FormAnswerError, match=message) as err:
        validate_answers(_form(), _with(qid, answer))
    assert err.value.question_id == qid


def test_a_missing_required_answer_names_its_question() -> None:
    answers = dict(GOOD)
    del answers["participants.N"]
    with pytest.raises(FormAnswerError) as err:
        validate_answers(_form(), answers)
    assert err.value.question_id == "participants.N"


def test_answers_to_questions_the_form_does_not_have_are_refused() -> None:
    with pytest.raises(FormAnswerError, match="do not match"):
        validate_answers(_form(), {**GOOD, "is_admin": {"status": "answered", "value": True}})


def test_answers_to_a_form_that_is_not_open_are_refused() -> None:
    with pytest.raises(FormAnswerError, match="no longer open"):
        validate_all({"t1": _form()}, {"t2": GOOD})
    assert validate_all({"t1": _form()}, {"t1": GOOD})["t1"][0]["status"] == "answered"


def test_results_for_the_model_are_json() -> None:
    submitted = json.loads(answers_result(validate_answers(_form(), GOOD)))
    assert submitted["form"] == "submitted" and len(submitted["answers"]) == 6
    assert json.loads(skipped_result())["form"] == "not_submitted"


## --- Estimates (short interview) ---------------------------------------------------------
def _estimated(**fields: Any) -> dict[str, Any]:
    return {"questions": [{"id": "q", "label": "Q?", "basis": "You said so.", **fields}]}


def test_an_estimate_is_shown_with_its_basis_and_must_fit_its_question() -> None:
    form = parse_form(_estimated(kind="range", min=0, estimate={"min": 20, "max": 120}))
    assert form.questions[0].estimate == {"min": 20, "max": 120}
    choice = [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]
    parse_form(_estimated(kind="single_choice", options=choice, estimate="b"))
    for bad in (
        _estimated(kind="single_choice", options=choice, estimate="c"),  # not an option
        _estimated(kind="range", min=0, estimate={"min": -5, "max": 1}),  # below min
        _estimated(kind="number", estimate="many"),
        {"questions": [{"id": "q", "label": "Q?", "kind": "number", "estimate": 3}]},  # no basis
        _estimated(kind="number"),  # a basis without an estimate
    ):
        with pytest.raises(FormError):
            parse_form(bad)


def test_answers_say_whether_the_estimate_was_kept() -> None:
    form = parse_form(_estimated(kind="range", estimate={"min": 20, "max": 120}))
    kept = validate_answers(form, {"q": {"status": "answered", "value": {"min": 20, "max": 120}}})
    changed = validate_answers(form, {"q": {"status": "answered", "value": {"min": 20, "max": 90}}})
    assert kept[0]["estimate_accepted"] is True
    assert changed[0]["estimate_accepted"] is False
    plain = validate_answers(_form(), GOOD)  # no estimate: no flag
    assert all("estimate_accepted" not in a for a in plain)
