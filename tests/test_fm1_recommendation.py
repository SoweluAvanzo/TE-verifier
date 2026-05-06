"""FM1 recommendation wording — narrows wide declarations.

When the declared emission upper bound is more than 10× Q_hi, the
recommendation should lead with "narrow your declared emission range"
rather than "cap net emission at min(Q)" — otherwise the user gets a
trivially-low cap that doesn't reflect the actual binding issue.
"""

from __future__ import annotations

from schema import (
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
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
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
)
from verifier import Status, verify


def _emit_range(lo: float, hi: float) -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=EmissionTriggerKind.BEHAVIORAL_EVENT,
            event_frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange(min=lo, max=hi)},
            ),
        ),
    )


def _make_te(*, tokens, Q_lo: float, Q_hi: float) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=tokens,
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange(min=Q_lo, max=Q_hi),
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


def _fm1(report, subject="T"):
    return next(
        v for v in report.verdicts
        if v.failure_mode.startswith("FM1") and v.subject == subject
    )


def test_fm1_recommendation_for_wide_range_says_narrow_first() -> None:
    """Curve-shape: emission range [0, 15.4M], Q in [100k, 5M]. The
    recommendation should mention narrowing the range, not just
    capping at Q_lo."""
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit_range(0, 15_400_000)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r = verify(_make_te(tokens=tokens, Q_lo=100_000, Q_hi=5_000_000))
    fm1 = _fm1(r)
    assert fm1.status == Status.FAIL
    assert fm1.recommendation is not None
    narrative = fm1.recommendation.narrative.lower()
    assert "narrow" in narrative
    assert "range" in narrative


def test_fm1_recommendation_for_realistic_range_uses_simple_cap() -> None:
    """When the emission upper bound is within 3× of Q_hi, the
    recommendation reverts to the simple "cap at Q_lo" form."""
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit_range(0, 1_500_000)],  # 1.5× Q_hi
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r = verify(_make_te(tokens=tokens, Q_lo=100_000, Q_hi=1_000_000))
    fm1 = _fm1(r)
    assert fm1.status == Status.FAIL
    assert fm1.recommendation is not None
    narrative = fm1.recommendation.narrative.lower()
    assert "cap" in narrative
    assert "narrow" not in narrative
