"""FM3 counts tokens minted INTO a token by cross-token flows as emission.

A debt token minted 1:1 with a credit token (Aave-style debt token, a
mutual-credit ledger) has no emission rules of its own. Before this fix FM3
called it "no emission" and passed it whatever its repayment; now its
inflow is its emission, as in FM1 (docs/proofs/fm3.md, "Emission includes
inflows").
"""

from __future__ import annotations

import copy

import yaml

from schema import TokenEconomy
from verifier import verify
from verifier.failure_modes.base import Status

BASE = yaml.safe_load(
    """
meta: {name: Credit with a debt token, archetype: community_reward,
       nfrs: {circulation_speed: circulate_fast}}
events:
  - {id: trade, label: Trades on credit, kind: behavioral,
     frequency: {family: constant, parameter_ranges: {c: {min: 1, max: 1}}}}
  - {id: repay, label: Debtors sell back, kind: behavioral,
     frequency: {family: constant, parameter_ranges: {c: {min: 1, max: 1}}}}
tokens:
  - id: SRD
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
      - trigger: {event_id: repay}
        function: {asymptotic_class: {family: constant,
                   parameter_ranges: {c: {min: 1000, max: 1000}}}}
    initial_distribution: {kind: none}
  - id: DEBT
    function: [unit_of_account]
    value_anchor: pegged
    transferable: false
    earning_mechanisms: [behavioral_reward]
    redemption_mechanism: unspecified
    offer_variety_K: {min: 20, max: 40}
    emission_rules: []
    burn_rules:
      - trigger: {event_id: repay}
        function: {asymptotic_class: {family: constant,
                   parameter_ranges: {c: {min: 1000, max: 1000}}}}
    initial_distribution: {kind: none}
cross_token_flows:
  - {source_token: SRD, source_event: trade, target_token: DEBT, target_action: mint,
     amount: {family: constant, parameter_ranges: {c: {min: 0, max: 0}}},
     coupling: proportional_to_source, coupling_ratio: {min: 1, max: 1}}
participants:
  count_N: {min: 300, max: 400}
  expected_Q: {min: 60000, max: 120000}
  average_demand_d: {min: 0.5, max: 2.0}
  growth_g: {family: linear, parameter_ranges: {a: {min: 0, max: 0}, b: {min: 0, max: 0.01}}}
governance:
  type: committee
  monitoring_capacity_gamma: {min: 0.7, max: 0.9}
  sanction_structure: {kind: economic, S_normalized: {min: 0.3, max: 0.6}}
"""
)


def _fm3(spec: dict, subject: str):
    te = TokenEconomy.model_validate(spec)
    return next(
        v for v in verify(te).verdicts
        if v.failure_mode.startswith("FM3") and v.subject == subject
    )


def test_debt_repaid_in_full_passes() -> None:
    assert _fm3(BASE, "DEBT").status == Status.PASS


def test_debt_repaid_in_part_fails() -> None:
    """Repaying 800 of every 1000 created: outstanding debt grows (ρ = 0.8 < 1)."""
    spec = copy.deepcopy(BASE)
    spec["tokens"][1]["burn_rules"][0]["function"]["asymptotic_class"]["parameter_ranges"][
        "c"] = {"min": 800, "max": 800}
    v = _fm3(spec, "DEBT")
    assert v.status == Status.FAIL
    assert "no emission" not in v.explanation


def test_debt_never_repaid_fails() -> None:
    spec = copy.deepcopy(BASE)
    spec["tokens"][1]["burn_rules"] = []
    assert _fm3(spec, "DEBT").status == Status.FAIL
