"""Phase B2+B3 — structured conditional rules.

Pins the three-valued evaluation (ALWAYS / EVER / NEVER) and the
side-correct conservatism (emission rules over-counted, burn rules
under-counted) used by FM1 and FM3 to gate per-rule contributions.

See `docs/proofs/conditional_rules.md` for the soundness proof.
"""

from __future__ import annotations

from schema import (
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    ControllingActor,
    EmissionTriggerKind,
    EventOccurrence,
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
    ThresholdCondition,
    ThresholdOp,
    ThresholdVar,
    TimeWindow,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
)
from verifier import Status, verify
from verifier.conditions import (
    ConditionStatus,
    conjunction_status,
    evaluate_condition,
    rule_contributes,
)


def _emit(c: float, conditions=None) -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=EmissionTriggerKind.BEHAVIORAL_EVENT,
            event_frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
            conditions=conditions or [],
        ),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(c)},
            ),
        ),
    )


def _burn(c: float, conditions=None) -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=BurnTriggerKind.DEMAND_DRIVEN,
            event_frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
            conditions=conditions or [],
        ),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_NEGATIVE,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(c)},
            ),
        ),
    )


def _make_te(*, tokens, Q=100.0, N=1000, K=5, d=2):
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=tokens,
        participants=ParticipantsSpec(
            count_N=NumberRange.point(N),
            expected_Q=NumberRange.point(Q),
            average_demand_d=NumberRange.point(d),
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


def _fm(report, fm_id, subject="T"):
    return next(v for v in report.verdicts
                if v.failure_mode.startswith(fm_id) and v.subject == subject)


# ---------------------------------------------------------------------------
# Static evaluator
# ---------------------------------------------------------------------------


def test_threshold_always_when_box_strictly_above_value() -> None:
    """N ∈ [1000, 1000], condition `N >= 100` → ALWAYS."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1.0)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens, N=1000)
    c = ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=100.0)
    assert evaluate_condition(c, te) == ConditionStatus.ALWAYS


def test_threshold_never_when_box_strictly_below_value() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1.0)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens, N=10)
    c = ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=100.0)
    assert evaluate_condition(c, te) == ConditionStatus.NEVER


def test_time_window_outside_horizon_is_never() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1.0)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens)
    c = TimeWindow(start_period=100.0, end_period=200.0)  # past horizon
    assert evaluate_condition(c, te) == ConditionStatus.NEVER


def test_time_window_covers_horizon_is_always() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1.0)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens)
    c = TimeWindow(start_period=0.0, end_period=None)  # open-ended
    assert evaluate_condition(c, te) == ConditionStatus.ALWAYS


def test_event_occurrence_missing_source_is_never() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1.0)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens)
    c = EventOccurrence(source_token="GHOST", source_event="x")
    assert evaluate_condition(c, te) == ConditionStatus.NEVER


def test_conjunction_any_never_is_never() -> None:
    """C1 ALWAYS, C2 NEVER → conjunction NEVER."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1.0)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens, N=100)
    c1 = ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=10.0)  # ALWAYS
    c2 = ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=10000.0)  # NEVER
    assert conjunction_status([c1, c2], te) == ConditionStatus.NEVER


# ---------------------------------------------------------------------------
# FM-side integration
# ---------------------------------------------------------------------------


def test_emission_rule_with_never_condition_is_excluded_from_fm1() -> None:
    """An emission rule whose condition is NEVER must not contribute to E."""
    never_cond = ThresholdCondition(var=ThresholdVar.T, op=ThresholdOp.GTE, value=1000.0)
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[
                        _emit(c=10.0),  # always-active
                        _emit(c=500.0, conditions=[never_cond]),  # gated out
                    ],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens, Q=100.0))
    # Without gating: total E = 510 > 100 → FAIL.
    # With gating:    total E = 10 ≤ 100 → PASS.
    assert _fm(r, "FM1").status == Status.PASS


def test_emission_rule_with_ever_condition_is_included_in_fm1() -> None:
    """EVER → over-conservatively included → still triggers FM1."""
    ever_cond = ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=500.0)
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[
                        _emit(c=500.0, conditions=[ever_cond]),
                    ],
                    offer_variety_K=NumberRange.point(5))]
    # N ∈ [100, 1000] → condition is EVER (sometimes true, sometimes not).
    te = _make_te(tokens=[
        Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
              emission_rules=[_emit(c=500.0, conditions=[ever_cond])],
              offer_variety_K=NumberRange.point(5)),
    ])
    te = te.model_copy(update={
        "participants": te.participants.model_copy(update={"count_N": NumberRange(min=100, max=1000)})
    })
    r = verify(te)
    # Rule still contributes (EVER), so E = 500 > Q=100 → FAIL.
    assert _fm(r, "FM1").status == Status.FAIL


def test_burn_rule_with_ever_condition_is_excluded_from_fm3() -> None:
    """Burn rule with EVER conditions must NOT contribute (under-conservative)."""
    ever_cond = ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=500.0)
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=10.0)],
                    burn_rules=[_burn(c=10.0, conditions=[ever_cond])],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens)
    te = te.model_copy(update={
        "participants": te.participants.model_copy(update={"count_N": NumberRange(min=100, max=1000)})
    })
    r = verify(te)
    # Burn EVER → not counted on burn side → effective ρ = 0 → FAIL.
    assert _fm(r, "FM3").status == Status.FAIL


def test_burn_rule_with_always_condition_is_included_in_fm3() -> None:
    """Burn rule with ALWAYS conditions DOES contribute → FM3 PASS."""
    always_cond = ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=10.0)
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=10.0)],
                    burn_rules=[_burn(c=10.0, conditions=[always_cond])],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens, N=1000))
    # Burn ALWAYS → counted → ρ = 1 → PASS.
    assert _fm(r, "FM3").status == Status.PASS


def test_back_compat_no_conditions_unchanged() -> None:
    """Rules without conditions behave exactly as before."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=10.0)],
                    burn_rules=[_burn(c=10.0)],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens))
    # No conditions → both rules contribute → same behaviour as Phase A.
    assert _fm(r, "FM1").status == Status.PASS
    assert _fm(r, "FM3").status == Status.PASS


def test_rule_contributes_helper_directions() -> None:
    """Direct API check on the rule_contributes helper."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1.0)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens, N=100)
    never_rule = _emit(c=1.0, conditions=[
        ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=1000.0)
    ])
    ever_rule = _emit(c=1.0, conditions=[
        ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=50.0)  # ALWAYS at N=100
    ])
    # Emission side: NEVER excluded, ALWAYS included
    assert rule_contributes(never_rule, te, side="emission") is False
    assert rule_contributes(ever_rule, te, side="emission") is True
    # Burn side: only ALWAYS included
    burn_never = _burn(c=1.0, conditions=[
        ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=1000.0)
    ])
    burn_always = _burn(c=1.0, conditions=[
        ThresholdCondition(var=ThresholdVar.N, op=ThresholdOp.GTE, value=50.0)
    ])
    assert rule_contributes(burn_never, te, side="burn") is False
    assert rule_contributes(burn_always, te, side="burn") is True
