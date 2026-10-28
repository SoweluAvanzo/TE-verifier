"""Outstanding supply cap: docs/proofs/outstanding_cap.md, encoded and simulated.

Each test names the lemma or paragraph of the proof it checks. The base
design creates 1000 tokens per period and burns 800 (ρ = 0.8): uncapped,
FM3 fails; with a cap the supply stops at the cap (Lemma 3).
"""

from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from schema import TokenEconomy
from verifier import verify
from verifier.abm.explore import run_explore
from verifier.abm.report import SimulationConfig
from verifier.failure_modes.base import RiskLevel, Status
from verifier.simulate.trajectory import simulate_token_trajectory

BASE = yaml.safe_load(
    """
meta: {name: Capped credit}
events:
  - {id: trade, label: Trades on credit, kind: behavioral,
     frequency: {family: constant, parameter_ranges: {c: {min: 1, max: 1}}}}
tokens:
  - id: CR
    function: [medium_of_exchange]
    value_anchor: pegged
    earning_mechanisms: [behavioral_reward]
    redemption_mechanism: specific_goods_or_services
    offer_variety_K: {min: 20, max: 40}
    emission_rules:
      - trigger: {event_id: trade}
        function: {asymptotic_class: {family: constant,
                   parameter_ranges: {c: {min: 1000, max: 1000}}}}
    burn_rules:
      - trigger: {event_id: trade}
        function: {asymptotic_class: {family: constant,
                   parameter_ranges: {c: {min: 800, max: 800}}}}
    initial_distribution: {kind: none}
participants:
  count_N: {min: 300, max: 400}
  expected_Q: {min: 150, max: 300}
  average_demand_d: {min: 0.5, max: 2.0}
  growth_g: {family: linear, parameter_ranges: {a: {min: 0, max: 0}, b: {min: 0, max: 0}}}
governance:
  type: committee
  monitoring_capacity_gamma: {min: 0.7, max: 0.9}
  sanction_structure: {kind: economic, S_normalized: {min: 0.3, max: 0.6}}
"""
)


def _spec(cap: tuple[float, float] | None = None, **meta: object) -> dict:
    spec = copy.deepcopy(BASE)
    if cap is not None:
        spec["tokens"][0]["outstanding_supply_cap"] = {"min": cap[0], "max": cap[1]}
    spec["meta"].update(meta)
    return spec


def _verdict(spec: dict, fm: str):
    report = verify(TokenEconomy.model_validate(spec))
    return next(v for v in report.verdicts if v.failure_mode.startswith(fm))


# --- Schema ----------------------------------------------------------------------


def test_negative_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TokenEconomy.model_validate(_spec(cap=(-1, 10)))


def test_initial_supply_above_the_cap_is_rejected() -> None:
    """Model: M₀ ≤ C is the base case of Lemma 1."""
    spec = _spec(cap=(100, 200))
    spec["tokens"][0]["initial_distribution"] = {
        "kind": "pre_minted_reserve",
        "amount": {"min": 50, "max": 150},
    }
    with pytest.raises(ValidationError):
        TokenEconomy.model_validate(spec)


# --- FM1 (Lemma 2) ----------------------------------------------------------------


def test_fm1_without_cap_is_unchanged() -> None:
    """E − B = 200 > Q_min = 150: oversupply possible."""
    assert _verdict(_spec(), "FM1").status == Status.FAIL


def test_fm1_passes_when_the_cap_is_below_q() -> None:
    """C_max = 120 ≤ Q_min = 150: min(E − B, C) ≤ Q for every assignment."""
    v = _verdict(_spec(cap=(100, 120)), "FM1")
    assert v.status == Status.PASS
    assert v.risk_level == RiskLevel.GREEN


def test_fm1_fails_when_the_cap_allows_more_than_q() -> None:
    """C can exceed Q and E − B > Q: the violation conjunct C > Q is satisfiable."""
    v = _verdict(_spec(cap=(100, 5000)), "FM1")
    assert v.status == Status.FAIL
    values = v.counterexample.parameter_values
    assert values["CR.outstanding_supply_cap"] > values["CR.Q (transaction volume)"]


# --- FM3 (Lemma 3) ----------------------------------------------------------------


def test_fm3_without_cap_is_unchanged() -> None:
    assert _verdict(_spec(), "FM3").status == Status.FAIL


def test_fm3_under_repayment_with_a_cap_is_held_by_the_cap() -> None:
    """ρ = 0.8 < 1 uncapped, but E∞ = min(E, B) = B under the cap."""
    v = _verdict(_spec(cap=(10_000, 20_000)), "FM3")
    assert v.status == Status.PASS_AS_INTENDED
    assert v.risk_level == RiskLevel.GREEN
    # t* = ⌈(C_min − M₀)/(E − B)⌉ = ⌈10000/200⌉ = 50, at the witness E = 1000, B = 800.
    assert "about 50 periods" in v.explanation


def test_fm3_with_a_cap_still_fails_when_resilience_demands_more_burn() -> None:
    """ρ_floor = 1.10 > 1 (NFR1 = 5): B < ρ_floor · min(E, B) holds."""
    v = _verdict(_spec(cap=(10_000, 20_000), nfrs={"resilience": 5}), "FM3")
    assert v.status == Status.FAIL


def test_fm3_without_burn_but_with_a_cap() -> None:
    """B = 0: E∞ = 0, supply stops at the cap."""
    spec = _spec(cap=(10_000, 20_000))
    spec["tokens"][0]["burn_rules"] = []
    v = _verdict(spec, "FM3")
    assert v.status == Status.PASS_AS_INTENDED
    assert v.risk_level == RiskLevel.GREEN


def test_fm3_with_enough_burn_passes_with_or_without_cap() -> None:
    spec = _spec(cap=(10_000, 20_000))
    spec["tokens"][0]["burn_rules"][0]["function"]["asymptotic_class"]["parameter_ranges"][
        "c"
    ] = {"min": 1000, "max": 1200}
    assert _verdict(spec, "FM3").status == Status.PASS


# --- Simulators (Model, Lemma 1 realized) ------------------------------------------------


def test_trajectory_stops_at_the_cap() -> None:
    te = TokenEconomy.model_validate(_spec(cap=(10_000, 10_000)))
    traj = simulate_token_trajectory(te, te.tokens[0], horizon=120)
    assert max(s.M for s in traj.samples) <= 10_000 + 1e-9
    assert traj.samples[-1].M == pytest.approx(10_000)


@pytest.mark.parametrize("seed", [1, 7])
def test_agent_based_run_never_exceeds_the_cap(seed: int) -> None:
    te = TokenEconomy.model_validate(_spec(cap=(3_000, 4_000)))
    report = run_explore(te, SimulationConfig(n_runs=1, horizon_periods=80, seed=seed))
    supply = [snap.M_by_token["CR"] for snap in report.snapshots]
    assert max(supply) <= 4_000 + 1e-6
    assert max(supply) > 0  # tokens were created
