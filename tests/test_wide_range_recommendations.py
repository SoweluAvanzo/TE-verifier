"""P2 — wide-range diagnostic on FM3 and FM5.

When the user's declared range is much wider than realistic, the
verdict should lead with "narrow your declared range" rather than
quote a worst-case threshold from the wide spec.
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


def _burn_range(lo: float, hi: float) -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=BurnTriggerKind.DEMAND_DRIVEN,
            event_frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_NEGATIVE,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange(min=lo, max=hi)},
            ),
        ),
    )


def _make_te(*, tokens, Q_hi=1e6, Q_lo=1e5, N=1000, K_range=None, d=2.0):
    K = K_range or NumberRange.point(5)
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=tokens,
        participants=ParticipantsSpec(
            count_N=NumberRange.point(N),
            expected_Q=NumberRange(min=Q_lo, max=Q_hi),
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
    return next(
        v
        for v in report.verdicts
        if v.failure_mode.startswith(fm_id) and v.subject == subject
    )


# ---------------------------------------------------------------------------
# FM3 wide-range
# ---------------------------------------------------------------------------


def test_fm3_wide_range_recommendation_says_narrow_first() -> None:
    """MakerDAO-shape: emission [0, 5e9], Q [1e5, 5e6], small burn.
    Recommendation should mention narrowing the range, not "raise burn
    to 5 billion tokens"."""
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit_range(0, 5e9)],
            burn_rules=[_burn_range(0, 1e3)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r = verify(_make_te(tokens=tokens, Q_lo=1e5, Q_hi=5e6))
    fm3 = _fm(r, "FM3")
    assert fm3.status == Status.FAIL
    assert fm3.recommendation is not None
    narrative = fm3.recommendation.narrative.lower()
    assert "narrow" in narrative
    assert "emission range" in narrative


def test_fm3_realistic_range_uses_simple_burn_recommendation() -> None:
    """When emission upper bound is within 3× Q_hi AND the lower
    bound is realistic (not near-zero), recommendation uses the
    original "raise burn to E_val" form."""
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            # Tighter range so neither wide-declaration nor
            # degenerate-corner heuristics fire.
            emission_rules=[_emit_range(8e5, 1.2e6)],
            burn_rules=[_burn_range(1e2, 1e3)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r = verify(_make_te(tokens=tokens, Q_lo=1e5, Q_hi=1e6))
    fm3 = _fm(r, "FM3")
    assert fm3.status == Status.FAIL
    assert fm3.recommendation is not None
    narrative = fm3.recommendation.narrative.lower()
    assert "raise per-period burn" in narrative
    assert "narrow your declared emission range" not in narrative
    assert "near-zero corner" not in narrative


def test_fm3_degenerate_corner_recommendation() -> None:
    """When the declared E lower bound is near-zero (rule includes 0),
    Z3 picks the corner; recommendation should call this out and
    suggest raising the lower bound."""
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit_range(0, 1.5e6)],  # lower bound = 0
            burn_rules=[_burn_range(0, 1e3)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r = verify(_make_te(tokens=tokens, Q_lo=1e5, Q_hi=1e6))
    fm3 = _fm(r, "FM3")
    assert fm3.status == Status.FAIL
    assert fm3.recommendation is not None
    narrative = fm3.recommendation.narrative.lower()
    assert "near-zero corner" in narrative
    assert "raise the lower bound" in narrative


# ---------------------------------------------------------------------------
# FM5 wide-range
# ---------------------------------------------------------------------------


def test_fm5_wide_k_range_recommendation_says_narrow_first() -> None:
    """When N* > 10× N_lo (because K_hi is way too wide), the
    recommendation should attribute it to the K range, not just say
    'grow N to 1 million'."""
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit_range(0, 100)],
            offer_variety_K=NumberRange(min=10, max=100_000),  # 10,000× span
        )
    ]
    r = verify(_make_te(tokens=tokens, N=1000, K_range=NumberRange(min=10, max=100_000), d=5.0))
    fm5 = _fm(r, "FM5", subject="system")
    assert fm5.status == Status.FAIL
    assert fm5.recommendation is not None
    narrative = fm5.recommendation.narrative.lower()
    assert "narrow your k range" in narrative


def test_fm5_realistic_k_range_uses_simple_grow_n_recommendation() -> None:
    """When N* is within 10× of N_lo, the recommendation reverts to
    the original 'grow N before launch' form."""
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit_range(0, 100)],
            offer_variety_K=NumberRange(min=100, max=200),
        )
    ]
    # N* = 2*200*5 + 1 = 2001. N_lo = 500. N* / N_lo = 4 → not wide.
    r = verify(_make_te(tokens=tokens, N=500, K_range=NumberRange(min=100, max=200), d=5.0))
    fm5 = _fm(r, "FM5", subject="system")
    assert fm5.status == Status.FAIL
    assert fm5.recommendation is not None
    narrative = fm5.recommendation.narrative.lower()
    assert "grow the participant base" in narrative
    assert "narrow your k range" not in narrative
