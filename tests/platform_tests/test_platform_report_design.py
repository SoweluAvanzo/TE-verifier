## =============================================================================
## tests/platform_tests/test_platform_report_design.py — the design half of the report
## =============================================================================
## GUIDE STEP   none yet (report-as-design-document extension; reports/design.py)
## PURPOSE      The inputs table says who gave each value and on what basis;
##              the verifier's internal names become readable labels; the
##              designer's own figures may appear in the narrative, invented
##              ones still may not; the PDF presents the design before the
##              verdicts and prints the legal-feasibility disclaimer.
## USED BY      pytest. No database.
## =============================================================================

from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
import yaml
from pypdf import PdfReader

from te_platform import service
from te_platform.errors import InvalidInput
from te_platform.reports.design import design_context, fmt_value, humanize_name

SPEC_TEXT = (Path("examples") / "time_bank.yaml").read_text()
SPEC = yaml.safe_load(SPEC_TEXT)

ANSWERS = [
    {
        "slot_id": "participants.N",
        "indices": [],
        "value": {"min": 30, "max": 50},
        "status": "committed",
        "user_quote": "about 40 volunteers, between 30 and 50",
    },
    {
        "slot_id": "tokens.K",
        "indices": [0],
        "value": {"min": 4, "max": 6},
        "status": "estimated",
        "user_quote": "4 to 6",
    },
    {
        "slot_id": "governance.gamma",
        "indices": [],
        "value": None,
        "status": "unknown",
        "user_quote": "no idea",
    },
]


def _msg(role: str, *blocks: dict[str, Any]) -> dict[str, Any]:
    return {"role": role, "content": {"role": role, "content": list(blocks)}}


MESSAGES = [
    _msg("user", {"type": "text", "text": "A garden where 40 volunteers earn HOUR tokens."}),
    _msg(
        "assistant",
        {
            "type": "tool_use",
            "id": "f1",
            "name": "ask_user",
            "input": {
                "title": "Estimates",
                "questions": [
                    {
                        "id": "tokens.K",
                        "label": "Kinds of offer",
                        "estimate": {"min": 4, "max": 6},
                        "basis": "You listed vegetables, tools, seeds and 17 workshops.",
                    }
                ],
            },
        },
    ),
]


def test_inputs_say_who_gave_each_value_and_why() -> None:
    rows = {r["label"]: r for r in design_context(SPEC, ANSWERS, MESSAGES)["inputs"]}
    n = rows["Active members"]
    assert (n["value"], n["source"]) == ("30 to 50", "You")
    assert n["note"] == "about 40 volunteers, between 30 and 50"
    k = next(r for label, r in rows.items() if label.startswith("Kinds of things to spend on"))
    assert k["source"] == "Estimate" and "17 workshops" in k["note"]
    noticed = rows["Chance that taking without contributing is noticed"]
    assert noticed["source"] == "Unknown"


def test_design_has_the_description_rules_and_a_diagram() -> None:
    d = design_context(SPEC, ANSWERS, MESSAGES)
    assert d["description"].startswith("A garden")
    assert {r["kind"] for r in d["rules"]} == {"Created", "Removed"}
    assert d["flow_svg"].startswith("<svg") and "in circulation" in d["flow_svg"]


def test_an_incomplete_spec_still_gives_the_inputs_table() -> None:
    d = design_context({"meta": {"name": "draft"}}, ANSWERS, [])
    assert d["rules"] == [] and d["flow_svg"] is None and len(d["inputs"]) == len(ANSWERS)


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("HOUR_burn_0__state_t", "HOUR, removal rule 1: period at which it is evaluated"),
        (
            "tokens[HOUR].burn_rules[1].function.unspec",
            "HOUR, removal rule 2: amount per period (shape not specified)",
        ),
        ("SRD_emit_0__expr_free", "SRD, creation rule 1: amount per period (any value)"),
        ("param__credit_limit", "parameter “credit limit”"),
        ("HOUR.Q (transaction volume)", "HOUR: value traded per period"),
    ],
)
def test_internal_names_become_readable(name: str, label: str) -> None:
    assert humanize_name(name) == label


def test_values_are_short_and_readable() -> None:
    assert fmt_value(825003.123) == "825,003"
    assert fmt_value(0.27312) == "0.2731"
    assert fmt_value({"min": 2, "max": 2}) == "2"
    assert fmt_value(["medium_of_exchange", "unit_of_account"]) == (
        "medium of exchange, unit of account"
    )


def _render() -> Any:
    try:
        from te_platform.reports import render
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"WeasyPrint's system libraries are missing: {exc}")
    return render


def _pdf(narrative: dict[str, str]) -> str:
    render = _render()
    result = service.verify(SPEC_TEXT)
    verification = {
        "verification_ref": result.verification_ref,
        "severity": result.report["severity"],
        "verdicts": service.merged_verdicts(result),
    }
    pdf = render.render_pdf(
        verification=verification,
        simulation=None,
        narrative=narrative,
        provenance={
            "spec_name": "Garden",
            "spec_hash": result.spec_hash,
            "verifier_version": "test",
            "policy_version": "0",
            "protocol_version": "0",
            "generated_at": "fixed",
            "overrides": [],
            "spec_summary": [],
        },
        citations=[{"citation_key": "psd2_2015", "title": "Directive (EU) 2015/2366"}],
        design=design_context(SPEC, ANSWERS, MESSAGES),
    )
    return "".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)


def test_the_report_answers_first_then_explains() -> None:
    text = _pdf(
        {
            "design_overview": "About 40 volunteers trade HOUR.",
            "check_FM3": "Hours are removed when spent.",
            "legal_feasibility": "See the exclusion in Directive 2015/2366.",
        }
    )
    flat = " ".join(text.split())
    # The answer comes first, then the design, the six questions, the methods, the
    # specialists' appendix.
    assert flat.index("Not yet sustainable") < flat.index("The six questions at a glance")
    assert (
        flat.index("1. Your design")
        < flat.index("2. Is it sustainable?")
        < flat.index("How the design was studied")
        < flat.index("Technical appendix")
    )
    assert "Hours are removed when spent." in flat
    assert "not legal advice" in flat and "In your words" in flat
    # Jargon only in the appendix: the main part names the questions plainly.
    main = flat[: flat.index("Technical appendix")]
    assert "FM1" not in main and "Monte Carlo" not in main and "verifier" not in main.lower()
    assert "HOUR_burn" not in flat  # internal names are humanised


def test_agent_text_with_jargon_is_flagged() -> None:
    from te_platform.reports.plain import jargon

    assert jargon("The burn coverage check FM3 fails (ρ < 1).")
    assert jargon("Members spend tokens on produce, which removes them.") == []


def test_invented_numbers_are_still_refused_with_a_design() -> None:
    with pytest.raises(InvalidInput):
        _pdf({"design_overview": "About 41234 volunteers."})
