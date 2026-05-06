"""P4 + P5 — FM4 recommendation routing.

P4: when phi_min == 0 (no agent_types declared with role=contributor),
the recommendation must point at the agent-role lever, not at γ.

P5: when d_hi / K_lo > 1 (φ* infeasibly above 1), the recommendation
must point at K (and provide a target ≥ d_hi), not present an
unreachable φ threshold as actionable.
"""

from __future__ import annotations

from schema import (
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    ContributionVerification,
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
    RedemptionMechanism,
    Rule,
    RuleTrigger,
    SanctionKind,
    SanctionStructure,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
)
from verifier import Status, verify


def _emit_rule() -> Rule:
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
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
    )


def _make_te(
    *,
    K_range,
    d_range,
    agent_types,
    verification=ContributionVerification.PEER_VERIFICATION,
) -> TokenEconomy:
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit_rule()],
            offer_variety_K=K_range,
            contribution_verification=verification,
            redemption_mechanism=RedemptionMechanism.SPECIFIC_GOODS_OR_SERVICES,
        )
    ]
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=tokens,
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=d_range,
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=agent_types,
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
            sanction_structure=SanctionStructure(kind=SanctionKind.WARNING),
        ),
    )


def _fm4(report):
    return next(v for v in report.verdicts if v.failure_mode.startswith("FM4"))


# ---------------------------------------------------------------------------
# P4 — phi_min == 0 routes to agent_types lever
# ---------------------------------------------------------------------------


def test_fm4_phi_min_zero_routes_to_agent_role_recommendation() -> None:
    """No agent declared with role=contributor → recommendation
    targets `agent_types[].role`, not γ."""
    agents = [
        AgentType(
            id="consumer",
            fraction=1.0,
            role=AgentRole.CONSUMER,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        )
    ]
    te = _make_te(
        K_range=NumberRange.point(10),
        d_range=NumberRange.point(2),
        agent_types=agents,
    )
    r = _fm4(verify(te))
    assert r.status == Status.FAIL
    assert r.recommendation is not None
    assert r.recommendation.parameter == "agent_types[].role"
    assert "role=contributor" in r.recommendation.narrative


# ---------------------------------------------------------------------------
# P5 — phi_star > 1 routes to K with target ≥ d_hi
# ---------------------------------------------------------------------------


def test_fm4_phi_star_infeasible_critical_value_marked() -> None:
    """d_hi / K_lo > 1 produces an INFEASIBLE-tagged φ critical value."""
    agents = [
        AgentType(
            id="contributor",
            fraction=0.5,
            role=AgentRole.CONTRIBUTOR,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
        AgentType(
            id="consumer",
            fraction=0.5,
            role=AgentRole.CONSUMER,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
    ]
    # K = 1, d = 5 → φ* = 5 > 1 → infeasible.
    te = _make_te(
        K_range=NumberRange.point(1),
        d_range=NumberRange.point(5),
        agent_types=agents,
    )
    r = _fm4(verify(te))
    assert r.status == Status.FAIL
    phi_cv = next(c for c in r.critical_values if c.parameter == "phi")
    assert "INFEASIBLE" in phi_cv.formula
    assert phi_cv.value == 5.0


def test_fm4_phi_star_infeasible_routes_to_k_with_d_hi_target() -> None:
    """When φ* infeasible, recommendation is `K ≥ d_hi`, not `raise γ`."""
    agents = [
        AgentType(
            id="contributor",
            fraction=0.5,
            role=AgentRole.CONTRIBUTOR,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
        AgentType(
            id="consumer",
            fraction=0.5,
            role=AgentRole.CONSUMER,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
    ]
    te = _make_te(
        K_range=NumberRange.point(1),
        d_range=NumberRange.point(5),
        agent_types=agents,
    )
    r = _fm4(verify(te))
    assert r.recommendation is not None
    assert r.recommendation.parameter == "K"
    assert r.recommendation.safe_threshold >= 5.0  # at least d_hi
    assert "infeasible" in r.recommendation.narrative.lower()


def test_fm4_phi_star_feasible_keeps_simple_k_recommendation() -> None:
    """When φ* ≤ 1 (e.g. d/K = 1/10 = 0.1), the existing K* path is
    preserved — no infeasibility branch."""
    agents = [
        AgentType(
            id="contributor",
            fraction=0.05,  # very low contributor fraction
            role=AgentRole.CONTRIBUTOR,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
        AgentType(
            id="consumer",
            fraction=0.95,
            role=AgentRole.CONSUMER,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
    ]
    # d=2, K=10 → φ* = 0.2 (feasible). With phi=0.05, contribution clause fails.
    te = _make_te(
        K_range=NumberRange.point(10),
        d_range=NumberRange.point(2),
        agent_types=agents,
    )
    r = _fm4(verify(te))
    assert r.status == Status.FAIL
    # Critical value present but not marked INFEASIBLE
    phi_cv = next(c for c in r.critical_values if c.parameter == "phi")
    assert "INFEASIBLE" not in phi_cv.formula
