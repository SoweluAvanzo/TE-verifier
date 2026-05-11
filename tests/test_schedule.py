"""ScheduleModifiers — schema validation, trajectory honouring,
static FM3 reclassification.

The new `Rule.schedule` field captures three real-world modifiers
(supply_cap, halving, vesting) that the asymptotic-class abstraction
alone cannot express. These tests pin:

- Pydantic validation rules (positive values, factor in (0,1)).
- Trajectory: cap freezes M, halving applies the factor at each
  period boundary, vesting ramps from 0 to 1.
- Static FM3: a no-burn token with supply_cap on every emission rule
  is reclassified PASS_AS_INTENDED ("Bitcoin pattern"), not FAIL.
- Round-trip via Pydantic dump/load.
"""

from __future__ import annotations

import pytest

from schema import (
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    ControllingActor,
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
    Rule,
    RuleTrigger,
    ScheduleModifiers,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
)
from verifier import Status, verify
from verifier.simulate import simulate_token_trajectory


def _emit_with_schedule(c: float, schedule: ScheduleModifiers | None = None) -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=EmissionTriggerKind.TIME_BASED,
            event_frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
        function=FunctionShape(
            sign=FunctionSign.DECREASING_POSITIVE,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(c)},
            ),
        ),
        schedule=schedule,
    )


def _make_te(*, tokens, Q=100.0):
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=tokens,
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(Q),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="u",
                    fraction=1.0,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                )
            ],
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
        ),
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_schedule_default_is_no_op() -> None:
    """Default ScheduleModifiers() means no caps, no halving, no vesting."""
    s = ScheduleModifiers()
    assert s.supply_cap is None
    assert s.halving_period is None
    assert s.vesting_periods is None
    # halving_factor has a default value but it's only applied when halving_period is set
    assert s.halving_factor == 0.5


def test_schedule_rejects_invalid_factor() -> None:
    with pytest.raises(ValueError, match="halving_factor"):
        ScheduleModifiers(halving_factor=1.5)
    with pytest.raises(ValueError, match="halving_factor"):
        ScheduleModifiers(halving_factor=0.0)


def test_schedule_rejects_negative_cap() -> None:
    with pytest.raises(ValueError, match="supply_cap"):
        ScheduleModifiers(supply_cap=-100)


def test_schedule_rejects_zero_period() -> None:
    with pytest.raises(ValueError, match="halving_period"):
        ScheduleModifiers(halving_period=0)
    with pytest.raises(ValueError, match="vesting_periods"):
        ScheduleModifiers(vesting_periods=0)


# ---------------------------------------------------------------------------
# Trajectory honours schedule
# ---------------------------------------------------------------------------


def test_trajectory_supply_cap_freezes_M() -> None:
    """E = 10/period, cap = 100 → M reaches 100 by period 10 and freezes."""
    schedule = ScheduleModifiers(supply_cap=100.0)
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit_with_schedule(c=10.0, schedule=schedule)],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    traj = simulate_token_trajectory(te, tok, horizon=50)
    assert traj.metrics.M_terminal == 100.0
    # M should stop growing once cap hit
    samples_at_end = [s for s in traj.samples if s.t > 15]
    for s in samples_at_end:
        assert s.M == 100.0


def test_trajectory_halving_decreases_emission() -> None:
    """E = 100/period, halving_period = 10, factor = 0.5.
    Cumulative ≈ 100·10·(1 + 0.5 + 0.25 + ...) → bounded at 200·10 = 2000."""
    schedule = ScheduleModifiers(halving_period=10, halving_factor=0.5)
    tok = Token(
        id="BTC",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit_with_schedule(c=100.0, schedule=schedule)],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    traj = simulate_token_trajectory(te, tok, horizon=200)
    # Geometric sum: 100·10 · 1/(1-0.5) = 2000 (asymptotic)
    # Allow generous tolerance for the discrete approximation.
    assert 1500 < traj.metrics.M_terminal < 2500


def test_trajectory_vesting_ramps_emission() -> None:
    """E = 100/period nominal, vesting_periods = 50 → first period emits ≈ 0,
    period 25 emits ≈ 50, period 50+ emits 100."""
    schedule = ScheduleModifiers(vesting_periods=50)
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit_with_schedule(c=100.0, schedule=schedule)],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    traj = simulate_token_trajectory(te, tok, horizon=100)
    # Find the sample at t=50: emission should be ≈ 100
    sample_50 = min(traj.samples, key=lambda s: abs(s.t - 50))
    assert 95 < sample_50.E <= 100


def test_trajectory_decreasing_positive_with_schedule_no_warning() -> None:
    """When the user declared decreasing_positive AND set a schedule
    with halving, the "un-modelled regime" note should NOT appear."""
    schedule = ScheduleModifiers(halving_period=10)
    tok = Token(
        id="BTC",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit_with_schedule(c=100.0, schedule=schedule)],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    traj = simulate_token_trajectory(te, tok, horizon=50)
    assert not any(
        "halving_period / supply_cap" in n for n in traj.metrics.notes
    )


# ---------------------------------------------------------------------------
# Static FM3 reclassification
# ---------------------------------------------------------------------------


def test_fm3_capped_no_burn_passes_as_intended() -> None:
    """Bitcoin pattern: no burn rules but supply_cap declared on every
    emission rule → FM3 reclassifies as PASS_AS_INTENDED."""
    schedule = ScheduleModifiers(supply_cap=21_000_000)
    tok = Token(
        id="BTC",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit_with_schedule(c=100.0, schedule=schedule)],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    rep = verify(te)
    fm3 = next(v for v in rep.verdicts if v.failure_mode.startswith("FM3"))
    assert fm3.status == Status.PASS_AS_INTENDED
    assert "Capped supply" in fm3.formal_condition
    # The supply_cap critical value is surfaced
    cap_cv = next(c for c in fm3.critical_values if c.parameter == "supply_cap")
    assert cap_cv.value == 21_000_000


def test_fm3_uncapped_no_burn_still_fails() -> None:
    """No burn AND no supply_cap → FM3 still FAILs (the no-burn case)."""
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit_with_schedule(c=100.0)],  # no schedule
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    rep = verify(te)
    fm3 = next(v for v in rep.verdicts if v.failure_mode.startswith("FM3"))
    assert fm3.status == Status.FAIL


def test_fm3_partial_cap_does_not_reclassify() -> None:
    """If only some emission rules have supply_cap but others don't,
    the verdict stays FAIL — the un-capped rules still threaten
    monotone growth."""
    capped = ScheduleModifiers(supply_cap=1_000_000)
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[
            _emit_with_schedule(c=100.0, schedule=capped),
            _emit_with_schedule(c=50.0, schedule=None),  # uncapped
        ],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    rep = verify(te)
    fm3 = next(v for v in rep.verdicts if v.failure_mode.startswith("FM3"))
    assert fm3.status == Status.FAIL


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_schedule_roundtrips_through_pydantic() -> None:
    schedule = ScheduleModifiers(
        supply_cap=21_000_000,
        halving_period=210,
        halving_factor=0.5,
        vesting_periods=52,
    )
    rule = _emit_with_schedule(c=100.0, schedule=schedule)
    dumped = rule.model_dump(mode="json")
    rebuilt = Rule.model_validate(dumped)
    assert rebuilt.schedule.supply_cap == 21_000_000
    assert rebuilt.schedule.halving_period == 210
    assert rebuilt.schedule.halving_factor == 0.5
    assert rebuilt.schedule.vesting_periods == 52
