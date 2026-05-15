"""Regime-switch tests — Rule.regimes drives a function-shape swap
when a structured Condition fires during the trajectory."""

from __future__ import annotations

import pytest

from schema import (
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    EmissionTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceSpec,
    GovernanceType,
    HoldingTimeDistribution,
    Meta,
    NFRs,
    NumberRange,
    ParticipantsSpec,
    RegimeSwitch,
    Rule,
    RuleTrigger,
    ThresholdCondition,
    ThresholdOp,
    ThresholdVar,
    TimeWindow,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
)
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.samplers import Sampler


def _te_with_regime(*, predicate, base_rate=10.0, regime_rate=0.0):
    return TokenEconomy(
        meta=Meta(name="regime-test", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[Rule(
                trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                function=FunctionShape(
                    sign=FunctionSign.ALWAYS_POSITIVE,
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(base_rate)},
                    ),
                ),
                regimes=[RegimeSwitch(
                    predicate=predicate,
                    function=FunctionShape(
                        sign=FunctionSign.ALWAYS_POSITIVE,
                        asymptotic_class=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(regime_rate)},
                        ),
                    ),
                )],
            )],
            burn_rules=[Rule(
                trigger=RuleTrigger(kind=BurnTriggerKind.DEMAND_DRIVEN),
                function=FunctionShape(
                    sign=FunctionSign.ALWAYS_NEGATIVE,
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(0.0)},
                    ),
                ),
            )],
            offer_variety_K=NumberRange.point(5),
        )],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(10),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[],   # rule-aggregate path
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )


# ---------------------------------------------------------------------------
# Time-window predicate: regime activates inside the window.
# ---------------------------------------------------------------------------


def test_time_window_regime_swaps_rate_inside_window() -> None:
    te = _te_with_regime(
        predicate=TimeWindow(start_period=5, end_period=10),
        base_rate=10.0,
        regime_rate=0.0,
    )
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    # t=0..4: base rate active → emission=10.
    state = _step_state(state, params)  # t=1
    assert state["tokens"]["T"]["E"] == pytest.approx(10.0)
    # Advance to t=5 (inside window).
    for _ in range(4):
        state = _step_state(state, params)
    assert state["t"] == 5
    assert state["tokens"]["T"]["E"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Threshold predicate on supply: regime fires once M crosses the line.
# ---------------------------------------------------------------------------


def test_threshold_regime_activates_when_supply_crosses() -> None:
    # M starts at 0 and grows by 10/period. Predicate: M >= 30 → rate 0
    # (caps the supply at 30 effectively).
    te = _te_with_regime(
        predicate=ThresholdCondition(
            var=ThresholdVar.M, op=ThresholdOp.GTE, value=30.0,
        ),
        base_rate=10.0,
        regime_rate=0.0,
    )
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    # No agents → rule-aggregate path. M updates after each step.
    state = _step_state(state, params)  # t=1, M += 10
    state = _step_state(state, params)  # t=2, M=20
    assert state["tokens"]["T"]["M"] == pytest.approx(20.0)
    assert state["tokens"]["T"]["E"] == pytest.approx(10.0)
    state = _step_state(state, params)  # t=3, M=30 — threshold reached
    # At t=3 the rate computation happens BEFORE the M update for the
    # period. So the regime fires at t=4 (next period after M reaches 30).
    assert state["tokens"]["T"]["M"] == pytest.approx(30.0)
    state = _step_state(state, params)  # t=4 — regime fired
    assert state["tokens"]["T"]["E"] == pytest.approx(0.0)
    assert state["tokens"]["T"]["M"] == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Sticky activation: once a regime fires it stays even if the predicate
# stops holding (mirrors halvings / supply caps).
# ---------------------------------------------------------------------------


def test_regime_activation_is_sticky() -> None:
    """Predicate: TimeWindow [3, 5]. After t=5 the window closes but
    the regime stays active because activations are sticky."""
    te = _te_with_regime(
        predicate=TimeWindow(start_period=3, end_period=5),
        base_rate=10.0,
        regime_rate=2.0,
    )
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    for _ in range(3):
        state = _step_state(state, params)  # t=1..3
    assert state["tokens"]["T"]["E"] == pytest.approx(2.0)
    # Advance past the window — regime stays in effect.
    for _ in range(5):
        state = _step_state(state, params)  # t=4..8
    assert state["tokens"]["T"]["E"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# No regime ⇒ no override.
# ---------------------------------------------------------------------------


def test_rules_without_regimes_unchanged() -> None:
    """Sanity: when rule.regimes is empty, behavior matches pre-Phase-F."""
    te = _te_with_regime(
        predicate=TimeWindow(start_period=3),
        base_rate=10.0,
        regime_rate=0.0,
    )
    # Strip the regime so the rule has none.
    te = te.model_copy(update={
        "tokens": [te.tokens[0].model_copy(update={
            "emission_rules": [te.tokens[0].emission_rules[0].model_copy(update={"regimes": []})],
        })],
    })
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    for _ in range(8):
        state = _step_state(state, params)
    # E stays at base rate throughout.
    assert state["tokens"]["T"]["E"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Static verifier picks up the regime as a Z3 disjunction candidate.
# ---------------------------------------------------------------------------


def test_static_verifier_considers_regime_rates() -> None:
    """FM1 should flip from PASS to FAIL once a regime introduces a
    rate the base function alone wouldn't reach. Confirms the static
    layer no longer ignores regimes."""
    from verifier.dispatcher import verify

    # Base rate 1 (safe under Q=200); regime ramps emission to 500
    # (overshoots Q=200). With the disjunction wiring, FM1 must fail.
    te = _te_with_regime(
        predicate=TimeWindow(start_period=10),
        base_rate=1.0,
        regime_rate=500.0,
    )
    # Pin Q low so the regime rate clearly breaches Fisher consistency.
    te = te.model_copy(update={
        "participants": te.participants.model_copy(update={
            "expected_Q": NumberRange.point(200.0),
        }),
    })
    report = verify(te)
    fm1_verdicts = [v for v in report.verdicts if "FM1" in v.failure_mode and v.subject == "T"]
    assert fm1_verdicts, "expected an FM1 verdict on token T"
    # With the regime considered, the verdict must NOT be a pass.
    assert fm1_verdicts[0].status.value != "pass", fm1_verdicts[0].status
