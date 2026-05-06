"""Phase D — risk stratification (Simulator.pdf §4–§6).

Pins the risk-band evaluation at midpoint values and the overall
weighted score. The risk layer is complementary to the SMT pass/fail
status: it answers "at typical parameter values, how bad is this".
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
from verifier import verify
from verifier.failure_modes.base import RiskLevel
from verifier.risk import OverallRiskBand


def _emit(c: float) -> Rule:
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
                parameter_ranges={"c": NumberRange.point(c)},
            ),
        ),
    )


def _burn(c: float) -> Rule:
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
                parameter_ranges={"c": NumberRange.point(c)},
            ),
        ),
    )


def _make_te(*, tokens, Q=100.0, N=1000, K=5, d=2, tau=5):
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
                    id="user",
                    fraction=1.0,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(tau)
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
        v for v in report.verdicts
        if v.failure_mode.startswith(fm_id) and v.subject == subject
    )


# ---------------------------------------------------------------------------
# FM1 risk bands (Simulator.pdf §4.1)
# ---------------------------------------------------------------------------


def test_fm1_green_when_emission_within_q() -> None:
    """ros = E/Q ≤ 1 → GREEN."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=50)],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens, Q=100.0))
    assert _fm(r, "FM1").risk_level == RiskLevel.GREEN


def test_fm1_amber_when_ros_between_1_and_1_5() -> None:
    """1 < ros ≤ 1.5 → AMBER."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=130)],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens, Q=100.0))
    assert _fm(r, "FM1").risk_level == RiskLevel.AMBER


def test_fm1_red_when_ros_between_1_5_and_2_5() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=200)],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens, Q=100.0))
    assert _fm(r, "FM1").risk_level == RiskLevel.RED


def test_fm1_red_critical_when_ros_above_2_5() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=300)],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens, Q=100.0))
    assert _fm(r, "FM1").risk_level == RiskLevel.RED_CRITICAL


# ---------------------------------------------------------------------------
# FM3 risk bands (Simulator.pdf §4.3)
# ---------------------------------------------------------------------------


def test_fm3_green_when_rho_at_least_1() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=10)],
                    burn_rules=[_burn(c=10)],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens))
    assert _fm(r, "FM3").risk_level == RiskLevel.GREEN


def test_fm3_amber_when_rho_between_0_5_and_1() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=10)],
                    burn_rules=[_burn(c=7)],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens))
    assert _fm(r, "FM3").risk_level == RiskLevel.AMBER


def test_fm3_red_critical_when_no_burn_rules() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=10)],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens))
    assert _fm(r, "FM3").risk_level == RiskLevel.RED_CRITICAL


# ---------------------------------------------------------------------------
# FM5 risk bands (Simulator.pdf §4.5)
# ---------------------------------------------------------------------------


def test_fm5_green_when_n_well_above_threshold() -> None:
    """rcm = N / (2Kd+1) ≥ 2 → GREEN."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1)],
                    offer_variety_K=NumberRange.point(5))]
    # N=1000, K=5, d=2 → N* = 21, rcm = ~47 → GREEN
    r = verify(_make_te(tokens=tokens, N=1000, d=2))
    assert _fm(r, "FM5", subject="system").risk_level == RiskLevel.GREEN


def test_fm5_red_when_below_critical_mass() -> None:
    """rcm < 1 → RED."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1)],
                    offer_variety_K=NumberRange.point(50))]
    # N=10, K=50, d=2 → N* = 201, rcm ≈ 0.05 → RED_CRITICAL
    r = verify(_make_te(tokens=tokens, N=10, d=2))
    assert _fm(r, "FM5", subject="system").risk_level == RiskLevel.RED_CRITICAL


# ---------------------------------------------------------------------------
# FM6 risk bands (Simulator.pdf §4.6)
# ---------------------------------------------------------------------------


def test_fm6_green_when_governance_distributed() -> None:
    """Γ ≤ 0.30 → GREEN."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens)
    # Override governance — 1 unilateral / 7 = 14.3% → GREEN
    te = te.model_copy(update={
        "governance": GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={
                "a": ControllingActor.TOKEN_HOLDER_VOTE,
                "b": ControllingActor.TOKEN_HOLDER_VOTE,
                "c": ControllingActor.TOKEN_HOLDER_VOTE,
                "d": ControllingActor.TOKEN_HOLDER_VOTE,
                "e": ControllingActor.TOKEN_HOLDER_VOTE,
                "f": ControllingActor.TOKEN_HOLDER_VOTE,
                "g": ControllingActor.SINGLE_ENTITY,
            },
        )
    })
    r = verify(te)
    assert _fm(r, "FM6", subject="system").risk_level == RiskLevel.GREEN


def test_fm6_red_when_governance_highly_centralized() -> None:
    """Γ > 0.80 → RED."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=1)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens)
    te = te.model_copy(update={
        "governance": GovernanceSpec(
            type=GovernanceType.CENTRALIZED,
            rule_structure={
                "a": ControllingActor.SINGLE_ENTITY,
                "b": ControllingActor.SINGLE_ENTITY,
                "c": ControllingActor.SINGLE_ENTITY,
                "d": ControllingActor.SINGLE_ENTITY,
                "e": ControllingActor.SINGLE_ENTITY,
                "f": ControllingActor.SINGLE_ENTITY,
                "g": ControllingActor.TOKEN_HOLDER_VOTE,
            },
        )
    })
    r = verify(te)
    # 6/7 = 0.857 > 0.80 → RED
    assert _fm(r, "FM6", subject="system").risk_level == RiskLevel.RED


# ---------------------------------------------------------------------------
# Overall risk score
# ---------------------------------------------------------------------------


def test_overall_risk_score_is_attached() -> None:
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=10)],
                    burn_rules=[_burn(c=10)],
                    offer_variety_K=NumberRange.point(5))]
    r = verify(_make_te(tokens=tokens))
    assert r.overall_risk is not None
    assert 0 <= r.overall_risk.normalized_pct <= 100
    assert r.overall_risk.band in OverallRiskBand


def test_overall_risk_low_for_clean_design() -> None:
    """A balanced single-token design with full burn coverage and
    distributed governance should land in the LOW or MODERATE band."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE,
                                      TokenFunction.GOVERNANCE_RIGHT],
                    emission_rules=[_emit(c=10)],
                    burn_rules=[_burn(c=10)],
                    offer_variety_K=NumberRange.point(5))]
    te = _make_te(tokens=tokens, N=1000, K=5, d=2, tau=10)
    te = te.model_copy(update={
        "governance": GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={
                f"d{i}": ControllingActor.TOKEN_HOLDER_VOTE for i in range(7)
            },
        )
    })
    r = verify(te)
    assert r.overall_risk.band in (OverallRiskBand.LOW, OverallRiskBand.MODERATE)


def test_overall_risk_critical_for_broken_design() -> None:
    """No burn + heavily centralized governance + below critical mass
    should put the score in the HIGH or CRITICAL band."""
    tokens = [Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                    emission_rules=[_emit(c=200)],
                    offer_variety_K=NumberRange.point(50))]
    te = _make_te(tokens=tokens, Q=10.0, N=10, K=50, d=2)
    te = te.model_copy(update={
        "governance": GovernanceSpec(
            type=GovernanceType.CENTRALIZED,
            rule_structure={
                f"d{i}": ControllingActor.SINGLE_ENTITY for i in range(7)
            },
        )
    })
    r = verify(te)
    assert r.overall_risk.band in (OverallRiskBand.HIGH, OverallRiskBand.CRITICAL)
