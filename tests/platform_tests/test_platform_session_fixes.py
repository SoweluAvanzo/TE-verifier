"""Bugs found by following one real design from the first message to the PDF report."""

import json
import re
from pathlib import Path
from uuid import uuid4

import anyio
import pytest
import yaml
from pydantic import BaseModel, ValidationError

from te_platform import service
from te_platform.agent.context import (
    _SUPERSEDED_BY_NEXT,
    current_state_note,
    fit_history,
)
from te_platform.db.repo import LiteratureRepository, Repository
from te_platform.db.session import session_scope
from te_platform.registry.context import CallContext, Principal, SessionFacts
from te_platform.registry.pipeline import _decode_json_arguments
from te_platform.tools.elicit_next_questions import NextQuestionsInput
from te_platform.tools.lit_search import LitSearchInput
from te_platform.tools.report_render_pdf import _checked_citations
from te_platform.tools.spec_save import SpecSaveInput, handle
from verifier.abm.actions import redeem_remaining, resolve_action_set, with_spending_path
from verifier.abm.engine import _steady_rate
from schema import ActionKind

ROOT = Path(__file__).parents[2]
PROMPT = ROOT / "te_platform" / "agent" / "prompts" / "interview.md"


def _template() -> dict:
    match = re.search(r"```yaml\n(.*?)```", PROMPT.read_text(encoding="utf-8"), re.DOTALL)
    assert match, "the interview prompt must show a whole design"
    return yaml.safe_load(match.group(1))


## --- The design the agent is told to copy ---------------------------------------------
def test_the_template_in_the_instructions_is_valid_and_can_be_verified() -> None:
    spec = _template()
    checked = service.validate(spec)
    assert checked.valid, checked.errors
    assert len(service.merged_verdicts(service.verify(spec))) == 6


def test_the_templates_expiry_is_really_simulated() -> None:
    run = service.trajectory(_template(), horizon=20, seed=1, max_agents=30)
    assert sum(s["B_by_token"]["CREDIT"] for s in run["snapshots"][1:]) > 0


## --- Simulation: known answers --------------------------------------------------------
def _matched(earn: float, spend: float) -> dict:
    """One token, two events at the same fixed frequency: coverage is spend / earn."""
    spec = _template()
    spec["meta"]["nfrs"]["resilience"] = 3
    for event, amount in zip(spec["events"], (earn, spend), strict=True):
        event["frequency"] = {"family": "bounded_range", "bounds": {"min": 100, "max": 100}}
        event["payload"][0]["range"] = {"min": amount, "max": amount}
    spec["tokens"][0]["burn_rules"] = spec["tokens"][0]["burn_rules"][:1]
    return spec


def _fm3_runs(spec: dict) -> dict:
    report = service.simulate(
        spec, n_runs=30, horizon=120, seed=7, failure_modes=["FM3"], skip_non_fragile=False
    )
    return report["per_fm_results"][0]


def test_removal_short_of_creation_fails_from_the_start() -> None:
    result = _fm3_runs(_matched(7, 5))
    assert result["n_violations_at_deployment"] == result["n_runs"]


def test_removal_above_creation_does_not_fail() -> None:
    assert _fm3_runs(_matched(7, 8))["n_violations"] == 0


def test_types_declared_unable_to_spend_are_caught() -> None:
    spec = _matched(7, 8)
    spec["participants"]["agent_types"][0]["action_set"] = ["earn", "hold"]
    result = _fm3_runs(spec)
    assert result["n_violations"] == result["n_runs"]


def test_a_single_role_can_retire_tokens_by_default() -> None:
    spec = _matched(7, 8)
    del spec["participants"]["agent_types"][0]["action_set"]
    run = service.trajectory(spec, horizon=30, seed=1, max_agents=30)
    assert sum(s["B_by_token"]["CREDIT"] for s in run["snapshots"][1:]) > 0


def test_a_declared_action_set_is_kept() -> None:
    spec = _matched(7, 8)
    spec["participants"]["agent_types"][0]["action_set"] = ["earn", "hold"]
    te = service.parse_spec(spec) if hasattr(service, "parse_spec") else None
    if te is None:
        from schema import TokenEconomy  # noqa: PLC0415

        te = TokenEconomy.model_validate(spec)
    kept = with_spending_path(te).participants.agent_types[0]
    assert ActionKind.REDEEM not in resolve_action_set(kept)


def test_burn_not_paid_by_one_redeemer_is_paid_by_the_others() -> None:
    redeemers = [{"balance": 1.0}, {"balance": 100.0}]
    state = {"tokens": {"T": {"M": 101.0}}}
    realized = {"T": {"E": 0.0, "B": 1.0 + 25.0}}  # both took their share of 50 up to balance
    redeem_remaining(redeemers, state, {"T": {"B": 50.0}}, realized, "T")
    assert realized["T"]["B"] == pytest.approx(50.0)
    assert state["tokens"]["T"]["M"] == pytest.approx(101.0 - 24.0)
    assert all(a["balance"] >= 0 for a in redeemers)


def test_burn_never_exceeds_what_redeemers_hold() -> None:
    redeemers = [{"balance": 2.0}]
    state = {"tokens": {"T": {"M": 2.0}}}
    realized = {"T": {"E": 0.0, "B": 0.0}}
    redeem_remaining(redeemers, state, {"T": {"B": 50.0}}, realized, "T")
    assert realized["T"]["B"] == pytest.approx(2.0)
    assert redeemers[0]["balance"] == pytest.approx(0.0)


def test_coverage_uses_capacity_when_all_that_exists_is_being_removed() -> None:
    period = {"E": 100.0, "B": 95.0, "E_capacity": 100.0, "B_capacity": 120.0}
    assert _steady_rate("rho[T]", 1.1, [period] * 30) == pytest.approx(1.2)


def test_coverage_is_measured_when_agents_do_not_spend() -> None:
    period = {"E": 100.0, "B": 10.0, "E_capacity": 100.0, "B_capacity": 120.0}
    assert _steady_rate("rho[T]", 1.1, [period] * 30) == pytest.approx(0.1)


def _fm4_runs(offers: float, demand: tuple[float, float]) -> dict:
    spec = _matched(7, 8)
    spec["meta"]["nfrs"]["proportionality"] = 3
    spec["governance"]["monitoring_capacity_gamma"] = {"min": 0.9, "max": 0.9}
    spec["tokens"][0]["offer_variety_K"] = {"min": offers, "max": offers}
    spec["participants"]["average_demand_d"] = {"min": demand[0], "max": demand[1]}
    report = service.simulate(
        spec, n_runs=30, horizon=60, seed=5, failure_modes=["FM4"], skip_non_fragile=False
    )
    return report["per_fm_results"][0]


def test_enough_offers_for_the_demand_do_not_fail_free_riding() -> None:
    assert _fm4_runs(10, (4, 4))["n_violations"] == 0


def test_too_few_offers_for_the_demand_fail_free_riding() -> None:
    result = _fm4_runs(3, (4, 4))
    assert result["n_violations"] == result["n_runs"]


def test_each_run_is_judged_on_its_own_demand_not_the_worst_declared() -> None:
    result = _fm4_runs(6, (1, 4))
    assert result["n_violations"] < result["n_runs"] / 2


## --- Verification text ----------------------------------------------------------------
def _fm3(spec: dict) -> dict:
    return next(
        v for v in service.merged_verdicts(service.verify(spec)) if v["failure_mode"].startswith("FM3")
    )


def test_fm3_names_the_floor_it_really_applies() -> None:
    spec = _matched(7, 5)
    spec["meta"]["nfrs"]["resilience"] = 5
    verdict = _fm3(spec)
    assert "1.1" in verdict["formal_condition"]
    assert verdict["critical_values"][0]["value"] == pytest.approx(1.1)


def test_fm3_recommends_what_would_really_pass_with_independent_events() -> None:
    spec = _template()
    spec["meta"]["nfrs"]["resilience"] = 3
    spec["tokens"][0]["burn_rules"] = spec["tokens"][0]["burn_rules"][:1]
    verdict = _fm3(spec)
    assert verdict["recommendation"]["safe_threshold"] == pytest.approx(7 * 150)
    assert "independently" in verdict["recommendation"]["narrative"]


def test_the_risk_band_reads_event_amounts() -> None:
    assert _fm3(_matched(7, 5))["risk_level"] == "amber"  # coverage 5/7 at the midpoint


def test_the_deterministic_trajectory_reads_event_amounts() -> None:
    verdict = _fm3(_matched(7, 5))
    samples = verdict["refined_diagnosis"]["trajectory"]["samples"]
    assert samples[0]["E"] == pytest.approx(700)
    assert samples[0]["B"] == pytest.approx(500)
    assert samples[-1]["M"] > samples[0]["M"]


## --- Tool arguments -------------------------------------------------------------------
class _Sweep(BaseModel):
    values: list[int]


class _Input(BaseModel):
    sweep: _Sweep | None = None
    variants: list[str] = []
    title: str = ""


def _error_for(raw: dict) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        _Input.model_validate(raw)
    return caught.value


def test_objects_and_lists_sent_as_text_are_decoded() -> None:
    raw = {"sweep": '{"values": [7, 9]}', "variants": '["a"]', "title": "keep me"}
    decoded = _decode_json_arguments(raw, _error_for(raw))
    assert _Input.model_validate(decoded).sweep.values == [7, 9]
    assert decoded["title"] == "keep me"


def test_text_that_is_not_json_is_left_to_fail() -> None:
    raw = {"sweep": "{not json"}
    assert _decode_json_arguments(raw, _error_for(raw)) is None


def test_asking_for_too_many_questions_is_not_an_error() -> None:
    assert NextQuestionsInput(max_questions=10).max_questions == 6
    assert NextQuestionsInput(max_questions="3").max_questions == 3


def test_a_misspelt_search_filter_is_refused() -> None:
    with pytest.raises(ValidationError):
        LitSearchInput(query="local currency", **{"parameter=kind": "empirical_value"})


## --- Context --------------------------------------------------------------------------
def _call(call_id: str, name: str, args: dict, result: dict) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": call_id, "name": name, "input": args}],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": json.dumps({"ok": True, "result": result}),
                }
            ],
        },
    ]


BIG = "x" * 40_000


def _long_history() -> list[dict]:
    history: list[dict] = [{"role": "user", "content": [{"type": "text", "text": "Earn 7, spend 5."}]}]
    history += _call("q1", "elicit__next_questions__v1", {}, {"complete": False, "open_decisive_slots": ["a"], "to_estimate": BIG})
    history += _call("v1", "spec__validate__v1", {"spec": BIG}, {"valid": False, "yaml": BIG})
    history += [{"role": "assistant", "content": [{"type": "text", "text": "My finding: FM3 fails."}]}]
    history += _call("q2", "elicit__next_questions__v1", {}, {"complete": True, "open_decisive_slots": [], "to_estimate": "latest"})
    history += _call("v2", "spec__validate__v1", {"spec": "the current design"}, {"valid": True, "yaml": "current"})
    return history


def test_nothing_changes_while_there_is_room() -> None:
    history = _long_history()
    fitted, thinned = fit_history(history, 1_000_000)
    assert fitted is history
    assert thinned.level == 0


def test_superseded_output_goes_and_the_latest_stays() -> None:
    fitted, thinned = fit_history(_long_history(), 5_000)
    text = json.dumps(fitted)
    assert thinned.level == 1 and not thinned.over_budget
    assert BIG not in text
    assert "latest" in text and "the current design" in text


def test_the_designers_words_and_the_agents_findings_are_never_touched() -> None:
    fitted, _ = fit_history(_long_history(), 10)
    text = json.dumps(fitted)
    assert "Earn 7, spend 5." in text
    assert "My finding: FM3 fails." in text


def test_the_stored_history_is_never_changed() -> None:
    history = _long_history()
    before = json.dumps(history)
    fit_history(history, 10)
    assert json.dumps(history) == before


def test_every_call_keeps_its_result() -> None:
    fitted, _ = fit_history(_long_history(), 10)
    calls = {b["id"] for m in fitted for b in m["content"] if b.get("type") == "tool_use"}
    results = {b["tool_use_id"] for m in fitted for b in m["content"] if b.get("type") == "tool_result"}
    assert calls == results


def test_an_impossible_budget_is_reported() -> None:
    _, thinned = fit_history(_long_history(), 1)
    assert thinned.over_budget


def test_superseded_tools_exclude_results_that_must_stay() -> None:
    assert "verify__run__v1" not in _SUPERSEDED_BY_NEXT


def test_the_state_note_gives_the_design_only_when_needed() -> None:
    facts = SessionFacts(
        session_id="s", owner_id="u", current_spec={"meta": {"name": "Maker"}}, open_decisive_slots=["a"]
    )
    short = current_state_note(facts, "eliciting", full=False)
    assert "eliciting" in short and "a" in short and "Maker" not in short
    assert "Maker" in current_state_note(facts, "eliciting", full=True)


## --- Answers survive a whole-design save, and citations come from the collection -------
ALICE = Principal(id=f"fixes-{uuid4().hex[:8]}", kind="user")


def _context(session_id: str) -> CallContext:
    with session_scope() as db:
        facts = Repository(db, ALICE).get_session_facts(session_id)
    return CallContext(principal=ALICE, tool_id="spec.save.v1", tool_input={}, session=facts)


def _session_with_answer(slot: str, value: object) -> str:
    with session_scope() as db:
        repo = Repository(db, ALICE)
        session_id = repo.create_session()
        version = repo.add_spec_version(session_id, {}, "", author="agent")
        repo.record_answer(session_id, slot, value, "committed", "their words", version, indices=[])
    return session_id


@pytest.mark.db
def test_an_answer_the_spec_left_out_is_put_back() -> None:
    session_id = _session_with_answer("governance.gini", {"min": 0.6, "max": 0.8})
    spec = _template()
    del spec["governance"]["token_balance_gini"]
    out = anyio.run(handle, SpecSaveInput(session_id=session_id, spec=spec), _context(session_id))
    assert out.saved and out.restored_answers == ["governance.gini"]
    saved = _context(session_id).session.current_spec
    assert saved["governance"]["token_balance_gini"] == {"min": 0.6, "max": 0.8}


@pytest.mark.db
def test_an_answer_the_spec_changed_is_reported_not_overwritten() -> None:
    session_id = _session_with_answer("governance.gini", {"min": 0.6, "max": 0.8})
    out = anyio.run(handle, SpecSaveInput(session_id=session_id, spec=_template()), _context(session_id))
    assert out.saved and out.restored_answers == []
    assert [d["slot"] for d in out.differs_from_answers] == ["governance.gini"]
    saved = _context(session_id).session.current_spec
    assert saved["governance"]["token_balance_gini"] == {"min": 0.3, "max": 0.5}


@pytest.fixture
def stored_work():
    key = f"citetest{uuid4().hex[:8]}"
    with session_scope() as db:
        LiteratureRepository(db).add_work(
            {
                "citation_key": key,
                "title": "The Real Title",
                "authors": "Real, Author",
                "year": 2020,
                "venue": None,
                "doi": "10.1/real",
                "licence": "test",
                "full_text_allowed": True,
            },
            [],
        )
    yield key
    from te_platform.db import models as m  # noqa: PLC0415

    with session_scope() as db:
        db.query(m.Work).filter(m.Work.citation_key == key).delete()


@pytest.mark.db
def test_citations_print_the_collections_data_not_the_models(stored_work: str) -> None:
    citations, unknown = _checked_citations(
        [{"citation_key": stored_work, "title": "A title the model misremembered", "page": 4}]
    )
    assert unknown == []
    assert citations[0]["title"] == "The Real Title"
    assert citations[0]["page"] == 4
    assert citations[0]["original_url"] == "https://doi.org/10.1/real"


@pytest.mark.db
def test_a_citation_outside_the_collection_is_refused() -> None:
    citations, unknown = _checked_citations([{"citation_key": "made-up-2024"}])
    assert citations == [] and unknown == ["made-up-2024"]
