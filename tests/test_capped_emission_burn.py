"""Supply-dependent rules and capped emission with burn.

A live Bitcoin session wrote its lost-coin removal as
``state.M['BTC'] * param.lost_rate`` (docs/dsl-reference.md). The
simulator crashed on it ("key 'M' not found in dict") and the trajectory
and risk layers silently read it as zero. And adding that removal turned
FM3 from pass_as_intended (capped, no burn) into fail, although removal
can only help (docs/proofs/fm3.md, "Capped emission").
"""

from __future__ import annotations

import copy

import pytest
import yaml

from schema import TokenEconomy
from verifier import verify
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.report import SimulationConfig
from verifier.abm.samplers import Sampler
from verifier.failure_modes.base import Status
from verifier.simulate.trajectory import simulate_token_trajectory

RATE = 2e-5

BTC = yaml.safe_load(
    f"""
meta: {{name: Capped coin with losses, archetype: native_protocol_asset}}
events:
  - {{id: block, kind: time_based, label: Weekly issuance,
     frequency: {{family: constant, parameter_ranges: {{c: {{min: 1, max: 1}}}}}}}}
  - {{id: lost, kind: time_based, label: Coins lost,
     frequency: {{family: constant, parameter_ranges: {{c: {{min: 1, max: 1}}}}}}}}
tokens:
  - id: BTC
    function: [store_of_value]
    value_anchor: market_price
    earning_mechanisms: [algorithmic_issuance]
    offer_variety_K: {{min: 10, max: 20}}
    initial_distribution:
      kind: pre_minted_reserve
      amount: {{min: 1000000, max: 1000000}}
    emission_rules:
      - trigger: {{event_id: block}}
        function: {{sign: always_positive, expression: "3150"}}
        schedule: {{supply_cap: 1250000}}
    burn_rules:
      - trigger: {{event_id: lost}}
        function:
          sign: always_negative
          expression: "state.M['BTC'] * param.lost_rate"
          parameters: [{{name: lost_rate, range: {{min: {RATE}, max: {RATE}}}}}]
governance:
  type: hybrid
  rule_structure: {{creation_rule: smart_contract}}
participants:
  count_N: {{min: 100, max: 200}}
  expected_Q: {{min: 100000, max: 200000}}
  average_demand_d: {{min: 0.1, max: 0.2}}
  growth_g: {{family: constant, parameter_ranges: {{value: {{min: 0, max: 0}}}}}}
"""
)


def _te(spec: dict) -> TokenEconomy:
    return TokenEconomy.model_validate(spec)


def test_simulator_rule_reads_the_current_supply_every_period() -> None:
    state, params = _build_initial_state(_te(BTC), Sampler(seed=1), None)
    for _ in range(5):
        supply = state["tokens"]["BTC"]["M"]
        state = _step_state(state, params)
        assert params["static_rates"]["BTC"]["B"] == pytest.approx(RATE * supply)
    assert state["tokens"]["BTC"]["M"] > 1_000_000


def test_trajectory_removal_follows_the_supply() -> None:
    traj = simulate_token_trajectory(_te(BTC), _te(BTC).tokens[0], horizon=10)
    first, last = traj.samples[1], traj.samples[-1]
    assert first.B == pytest.approx(RATE * 1_000_000)
    assert last.B > first.B  # supply grew, so removal grew with it


def test_monte_carlo_runs_on_a_supply_dependent_rule() -> None:
    from verifier.abm.engine import run_simulation

    report = run_simulation(_te(BTC), config=SimulationConfig(n_runs=3, horizon_periods=20, seed=1))
    assert report.per_fm_results


def _fm3(spec: dict):
    return next(v for v in verify(_te(spec)).verdicts if v.failure_mode.startswith("FM3"))


def test_removal_never_worsens_a_capped_token() -> None:
    no_burn = copy.deepcopy(BTC)
    no_burn["tokens"][0]["burn_rules"] = []
    assert _fm3(no_burn).status == Status.PASS_AS_INTENDED
    assert _fm3(BTC).status == Status.PASS_AS_INTENDED


def test_burn_that_covers_emission_still_passes_outright() -> None:
    spec = copy.deepcopy(BTC)
    spec["tokens"][0]["burn_rules"][0]["function"] = {
        "sign": "always_negative",
        "expression": "4000",
    }
    assert _fm3(spec).status == Status.PASS
