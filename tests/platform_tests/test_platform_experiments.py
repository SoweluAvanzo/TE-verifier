## =============================================================================
## tests/platform_tests/test_platform_experiments.py — what-if experiments
## =============================================================================
## GUIDE STEP   none yet (custom-experiment extension; te_platform/experiments.py)
## PURPOSE      Paths select the right field; invalid requests and variants are
##              refused with the reason; every variant goes through the verified
##              pipeline (its verdicts are those of verify on the changed
##              design); the Monte Carlo of an experiment never simulates a
##              failure mode the formal triage decided; the report prints the
##              experiment, its charts, their captions and the agent's notes.
## USED BY      pytest. No database.
## =============================================================================

import copy
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from pypdf import PdfReader

from te_platform import service
from te_platform.errors import InvalidInput
from te_platform.experiments import ExperimentDesign, run_experiment, set_path, variants_of
from te_platform.reports.method import figure_ids, glossary, steps

SPEC = yaml.safe_load((Path("examples") / "time_bank.yaml").read_text())
BURN = "tokens[HOUR].burn_rules[0].function.asymptotic_class.parameter_ranges.c"


def test_paths_select_by_id_or_position_and_numbers_fill_ranges() -> None:
    spec = copy.deepcopy(SPEC)
    set_path(spec, BURN, 3)
    assert spec["tokens"][0]["burn_rules"][0]["function"]["asymptotic_class"]["parameter_ranges"][
        "c"
    ] == {"min": 3, "max": 3}
    set_path(spec, "tokens[0].offer_variety_K", {"min": 2, "max": 4})
    assert spec["tokens"][0]["offer_variety_K"] == {"min": 2, "max": 4}
    with pytest.raises(InvalidInput):
        set_path(spec, "tokens[NOPE].offer_variety_K", 3)


def test_a_design_needs_exactly_one_kind_of_experiment() -> None:
    with pytest.raises(ValidationError):
        ExperimentDesign(title="t", question="q")
    with pytest.raises(ValidationError):
        ExperimentDesign(
            title="t",
            question="q",
            variants=[{"name": "Current design", "changes": [{"path": "a", "value": 1}]}],
        )


def test_an_invalid_variant_is_named() -> None:
    design = ExperimentDesign(
        title="t",
        question="q",
        variants=[{"name": "No use", "changes": [{"path": "tokens[HOUR].function", "value": []}]}],
    )
    with pytest.raises(InvalidInput, match="No use"):
        variants_of(SPEC, design)


def _experiment(**kw: Any) -> dict[str, Any]:
    design = ExperimentDesign(
        title="Burn more",
        question="Does removing more HOUR fix the supply checks?",
        variants=[
            {
                "name": "Burn 3",
                "description": "3 per redemption",
                "changes": [{"path": BURN, "value": 3}],
            }
        ],
        horizon=26,
        **kw,
    )
    return {**run_experiment(SPEC, design), "job_id": "job-test"}


def test_every_variant_is_verified_like_the_design() -> None:
    exp = _experiment()
    base, variant = exp["variants"]
    assert base["name"] == "Current design" and not base["changes"]
    changed = copy.deepcopy(SPEC)
    set_path(changed, BURN, 3)
    expected = [d["status"] for d in service.merged_verdicts(service.verify(changed))]
    assert [d["status"] for d in variant["verdicts"]] == expected
    assert base["trajectories"]["HOUR"][0]["t"] == 0


def test_experiment_monte_carlo_follows_the_formal_triage() -> None:
    """A failure mode the triage decided (sound / broken) is never simulated."""
    exp = _experiment(monte_carlo_runs=5, seed=2)
    changed = copy.deepcopy(SPEC)
    set_path(changed, BURN, 3)
    for v, spec in zip(exp["variants"], [SPEC, changed], strict=True):
        triage = {
            (t["failure_mode"], t["subject"]): t["structural_status"] for t in service.minimal(spec)
        }
        for r in v["monte_carlo"]:
            if triage[(r["failure_mode"], r["subject"])] in ("sound", "broken"):
                assert not r["simulated"] and r["skip_reason"]


def test_the_report_prints_the_experiment_with_its_charts_and_notes() -> None:
    try:
        from te_platform.reports import render
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"WeasyPrint's system libraries are missing: {exc}")
    exp = _experiment()
    result = service.verify(SPEC)
    verification = {
        "verification_ref": result.verification_ref,
        "severity": result.report["severity"],
        "verdicts": service.merged_verdicts(result),
    }
    ids = figure_ids(None, None, [exp])
    assert ids == ["experiment1-supply-HOUR"]
    pdf = render.render_pdf(
        verification=verification,
        simulation=None,
        narrative={"limitations": "Fees are approximated."},
        provenance={
            "spec_name": "Garden",
            "spec_hash": result.spec_hash,
            "verifier_version": "t",
            "policy_version": "0",
            "protocol_version": "0",
            "generated_at": "fixed",
            "overrides": [],
            "spec_summary": [],
        },
        citations=[],
        experiments=[exp],
        figure_notes={i: "The supply levels off." for i in ids},
    )
    text = " ".join("".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages).split())
    assert "Test 1. Burn more" in text and "Does removing more HOUR" in text
    assert "Figure 1. Test 1: HOUR in circulation, week by week" in text
    assert "What it shows." in text and "The supply levels off." in text
    assert "Words used in this report" in text and "C. The formal conditions" in text
    assert "What this analysis could not check" in text


def test_glossary_lists_only_the_terms_used() -> None:
    terms = dict(glossary(["The counterexample shows a burn of 3 tokens per period."]))
    assert {"counterexample", "burn", "token", "period"} <= terms.keys()
    assert "Gini" not in terms


def _call(call_id: str, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": args or {}}


def _ok(call_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "is_error": False,
        "content": json.dumps({"ok": True, "result": result}),
    }


def _turn(role: str, *blocks: dict[str, Any]) -> dict[str, Any]:
    return {"role": role, "content": {"content": list(blocks)}}


def test_steps_follow_the_conversation() -> None:
    messages = [
        _turn("user", {"type": "text", "text": "A garden."}),
        _turn(
            "assistant",
            _call("v", "verify__run__v1"),
            _call("l", "lit__search__v1", {"query": "time banks"}),
            _call("e", "sim__experiment__v1", {"title": "Burn more"}),
        ),
        _turn("user", _ok("v", {}), _ok("l", {}), _ok("e", {"job_id": "j1"})),
        _turn("assistant", _call("s", "jobs__status__v1", {"job_id": "j1"})),
        _turn("user", _ok("s", {"job_id": "j1", "status": "finished"})),
    ]
    answers = [{"status": "committed"}, {"status": "estimated"}, {"status": "estimated"}]
    st = steps(messages, answers)
    assert st["user_turns"] == 1
    assert st["answers"]["estimated"] == 2
    assert st["steps"] == [
        "Mathematical check of the six questions (worst and typical case)",
        "Search of the research and legal literature: “time banks”",
        "Test of an idea: Burn more",
    ]


def test_steps_leave_out_what_did_not_happen() -> None:
    """Live Bitcoin session: a declined what-if was listed as a completed step."""
    sim = {"n_runs": 100, "horizon": 260, "seed": 1}
    messages = [
        _turn(
            "assistant",
            _call("declined", "sim__experiment__v1", {"title": "Lost coins high"}),
            _call("refused", "lit__search__v1", {"query": "x"}),
            _call("crashed", "sim__monte_carlo__v1", sim),
        ),
        _turn(
            "user",
            {
                "type": "tool_result",
                "tool_use_id": "declined",
                "is_error": True,
                "content": "The user declined to run this tool.",
            },
            {
                "type": "tool_result",
                "tool_use_id": "refused",
                "is_error": True,
                "content": json.dumps({"ok": False, "error": {"error": "validation_error"}}),
            },
            _ok("crashed", {"job_id": "j"}),
        ),
        _turn("assistant", _call("s1", "jobs__status__v1", {"job_id": "j"})),
        _turn("user", _ok("s1", {"job_id": "j", "status": "failed"})),
        # The retry gets the same (content-based) job id and finishes; only the
        # retry is a step.
        _turn("assistant", _call("retry", "sim__monte_carlo__v1", {**sim, "seed": 2})),
        _turn("user", _ok("retry", {"job_id": "j"})),
        _turn("assistant", _call("s2", "jobs__status__v1", {"job_id": "j"})),
        _turn("user", _ok("s2", {"job_id": "j", "status": "finished"})),
        # Started but never seen finished: not a step.
        _turn("assistant", _call("open", "sim__experiment__v1", {"title": "Pending"})),
        _turn("user", _ok("open", {"job_id": "k"})),
    ]
    assert steps(messages, [])["steps"] == [
        "Simulation of the community: 100 runs of 260 weeks (random seed 2)"
    ]
