"""The agent-based simulation agrees with what the formal layer proves.

docs/abm-bridge.md: a SOUND failure mode is one the verifier proved cannot
fail anywhere in the declared box, and P(deploy) counts runs whose sampled
parameters violate at t = 0. So, simulating everything
(skip_non_fragile=False, the documented sanity check), a SOUND failure mode
must never be violated at deployment. Three bugs broke this (FM2 measured
the age since any action, FM5 conjoined alternative predicates, FM6 started
agents with balances in shares instead of tokens); these tests pin the fixes.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from schema import TokenEconomy, VoteWeighting
from te_platform import service
from verifier.abm.agents import spawn_agents, wealth_weighted_holding_time
from verifier.abm.predicates import fm_safe
from verifier.abm.samplers import Sampler
from verifier.safety_predicate import SafetyPredicate

EXAMPLES = Path("examples")


def _spec(name: str) -> dict:
    return yaml.safe_load((EXAMPLES / f"{name}.yaml").read_text())


@pytest.mark.parametrize("example", ["time_bank", "bitcoin", "makerdao", "cascina_roccafranca"])
def test_a_sound_failure_mode_is_never_violated_at_deployment(example: str) -> None:
    spec = _spec(example)
    triage = {(t["failure_mode"], t["subject"]): t["structural_status"]
              for t in service.minimal(spec)}
    report = service.simulate(spec, n_runs=10, horizon=26, seed=5, skip_non_fragile=False)
    for r in report["per_fm_results"]:
        if triage[(r["failure_mode"], r["subject"])] == "sound":
            assert r["n_violations_at_deployment"] == 0, r["failure_mode"]


def test_time_bank_sound_modes_are_not_violated_at_all() -> None:
    """FM2, FM5 (network topology) and FM6 were 100% violated before the fixes."""
    report = service.simulate(_spec("time_bank"), n_runs=10, horizon=52, seed=3,
                              skip_non_fragile=False)
    p = {r["failure_mode"][:3]: r["p_violation"] for r in report["per_fm_results"]}
    assert p["FM2"] == 0 and p["FM5"] == 0 and p["FM6"] == 0


def test_alternative_predicates_are_or_ed_and_the_rest_and_ed() -> None:
    def pred(group: str | None) -> SafetyPredicate:
        return SafetyPredicate(variable="N", operator=">=", threshold=1, alternative_group=group)

    alt = [pred("g"), pred("g")]
    assert fm_safe(alt, [False, True]) and not fm_safe(alt, [False, False])
    both = [pred(None), pred(None)]
    assert not fm_safe(both, [False, True]) and fm_safe(both, [True, True])


def test_spawned_balances_are_tokens_adding_up_to_the_supply() -> None:
    te = TokenEconomy.model_validate(_spec("time_bank"))
    agents = spawn_agents(te, Sampler(seed=1), max_agents=40, initial_supply=875.0)
    total = sum(a["balance"] for a in agents)
    # Types are rounded to whole agents; shares still add up to 1 per type.
    assert total == pytest.approx(875.0, rel=1e-9)


def test_holding_time_is_the_wealth_weighted_declared_one() -> None:
    agents = [
        {"balance": 30.0, "holding_time": 2.0},
        {"balance": 10.0, "holding_time": 10.0},
        {"balance": 0.0, "holding_time": 50.0},
    ]
    assert wealth_weighted_holding_time(agents, fallback=7.0) == pytest.approx(4.0)
    assert wealth_weighted_holding_time([{"balance": 0.0, "holding_time": 3.0}], 7.0) == 7.0


def test_non_linear_vote_weighting_keeps_the_effective_gini() -> None:
    """Under reputation weighting the balance Gini is not FM6's effective Gini."""
    from verifier.abm.engine import _build_initial_state, _primary_supply, _step_state

    spec = copy.deepcopy(_spec("time_bank"))
    spec["governance"]["vote_weighting"] = VoteWeighting.REPUTATION_WEIGHTED.value
    spec["governance"]["vote_weighting_params"] = {"reputation_gini": {"min": 0.2, "max": 0.2}}
    te = TokenEconomy.model_validate(spec)
    sampler = Sampler(seed=2)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=30)
    state["agents"] = spawn_agents(
        te, sampler, max_agents=30, initial_supply=_primary_supply(state, params)
    )
    declared = state["effective_gini"]
    for _ in range(3):
        state = _step_state(state, params)
    assert state["effective_gini"] == declared  # the sampled effective value is kept
    assert "balance_gini" in state  # the live balance Gini is stored apart
