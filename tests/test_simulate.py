"""Sprint 1+3 — trajectory + sensitivity + refinement tests.

Pin the dynamic layer's behaviour: trajectory metrics on simple
synthetic IRs, sensitivity ranking on FAIL verdicts, refined-diagnosis
attachment rules.
"""

from __future__ import annotations

from schema import (
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
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
from verifier import verify
from verifier.simulate import (
    compute_pairwise_sensitivity,
    compute_sensitivity,
    refine_verdicts,
    simulate_token_trajectory,
)


def _emit(c: float = 1.0) -> Rule:
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


def _burn(c: float = 1.0) -> Rule:
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


def _make_te(*, tokens, Q=100.0, N=1000, K=5, d=2.0, agent_types=None):
    if agent_types is None:
        agent_types = [
            AgentType(
                id="u",
                fraction=1.0,
                expected_holding_time=HoldingTimeDistribution(
                    expected_periods=NumberRange.point(5)
                ),
            )
        ]
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=tokens,
        participants=ParticipantsSpec(
            count_N=NumberRange.point(N),
            expected_Q=NumberRange.point(Q),
            average_demand_d=NumberRange.point(d),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=agent_types,
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
        ),
    )


# ---------------------------------------------------------------------------
# Trajectory
# ---------------------------------------------------------------------------


def test_trajectory_no_burn_grows_linearly() -> None:
    """Constant emission, no burn → linear monotone growth."""
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=10.0)],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    traj = simulate_token_trajectory(te, tok, horizon=100)
    # 100 periods × 10/period = 1000
    assert traj.metrics.M_terminal == 1000.0
    assert traj.metrics.M_initial == 0.0
    assert traj.metrics.diverges  # M_terminal / max(M_init, 1) = 1000 > 100
    # Burn-free → ρ_avg = 0
    assert traj.metrics.rho_avg == 0.0
    # ρ falls below 1 immediately
    assert traj.metrics.rho_below_one_at_period == 1


def test_trajectory_balanced_emission_burn_stable_rho() -> None:
    """E = B = 10 → ρ = 1, M stays roughly flat."""
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=10.0)],
        burn_rules=[_burn(c=10.0)],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    traj = simulate_token_trajectory(te, tok, horizon=100)
    # E = B per period → net dM/dt = 0 → M stays at initial
    assert traj.metrics.M_terminal == 0.0
    assert abs(traj.metrics.rho_avg - 1.0) < 1e-9


def test_trajectory_high_burn_contracts_supply() -> None:
    """B > E → supply contracts (capped at 0)."""
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=5.0)],
        burn_rules=[_burn(c=10.0)],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    traj = simulate_token_trajectory(te, tok, horizon=20)
    assert traj.metrics.rho_avg > 1.0  # burn dominates
    assert traj.metrics.M_terminal == 0.0  # capped at floor


def test_trajectory_decreasing_positive_emits_note() -> None:
    """When emission sign is decreasing_positive but class is constant,
    a note flags the missing halving schedule (Bitcoin pattern)."""
    rule = Rule(
        trigger=RuleTrigger(
            kind=EmissionTriggerKind.TIME_BASED,
            event_frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
        function=FunctionShape(
            sign=FunctionSign.DECREASING_POSITIVE,  # the hint
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(100.0)},
            ),
        ),
    )
    tok = Token(
        id="BTC",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[rule],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    traj = simulate_token_trajectory(te, tok, horizon=50)
    assert any("decreasing_positive" in n for n in traj.metrics.notes)
    assert any("halving" in n.lower() for n in traj.metrics.notes)


def test_trajectory_sample_count_bounded() -> None:
    """Even with horizon=260, surfaced samples stay around 30."""
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=1.0)],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    traj = simulate_token_trajectory(te, tok, horizon=260)
    # ~30 samples, allow up to 35 for the "include last" tail.
    assert 20 <= len(traj.samples) <= 40


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------


def test_sensitivity_q_flips_fm1_when_q_lo_too_low() -> None:
    """FM1 fails because Q_lo=10 forces tight cap. Raising Q to 200
    should flip the verdict."""
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=50.0)],
        offer_variety_K=NumberRange.point(5),
    )
    # Q range [10, 200] — at midpoint Q=105, but Q_lo=10 binds.
    te = TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[tok],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange(min=10, max=200),
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
    inputs = compute_sensitivity(te, "FM1", subject="T")
    q = next(i for i in inputs if i.field == "participants.expected_Q")
    # At Q_max=200 the FM should pass (E=50 ≤ 200), at Q_min=10 it
    # should fail.
    assert q.flips_verdict
    assert q.verdict_at_max == "pass"


def test_pairwise_sensitivity_finds_joint_flip() -> None:
    """FM4 has two clauses (φ≥d/K AND γS>T-R). Construct a TE where
    neither γ_max alone nor K_max alone flips the verdict, but moving
    both at once does. Verify pairwise sweep catches this."""
    # The trick to surface a joint flip is to pick an FM4 setup where
    # neither candidate at its extreme flips the verdict alone, but two
    # candidates simultaneously do. We pin the φ-clause as structurally
    # satisfied (d = 0) and tune the γ-clause so it requires *both*
    # γ and S near their upper bounds:
    #   • T-R defaults to 0.5 (no contribution_verification + redemption)
    #   • γ ∈ [0.5, 0.95], S ∈ [0.3, 0.6]
    #   • baseline picks γ=0.5, S=0.3 → γ·S = 0.15 < 0.5 → fail
    #   • γ=0.95 alone: Z3 still picks S=0.3 → γ·S = 0.285 → fail
    #   • S=0.6 alone: Z3 still picks γ=0.5 → γ·S = 0.30  → fail
    #   • γ=0.95 + S=0.6: γ·S = 0.57 > 0.5 → pass
    # That last combination is exactly what pairwise should surface.
    # NB: contribution_verification is intentionally left None — when set,
    # γ is *derived* from it (and the user-supplied gamma range is
    # ignored), so the sensitivity setter would have no effect.
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        earning_mechanisms=[],
        emission_rules=[
            Rule(
                trigger=RuleTrigger(kind=EmissionTriggerKind.BEHAVIORAL_EVENT),
                function=FunctionShape(
                    sign=FunctionSign.ALWAYS_POSITIVE,
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(1.0)},
                    ),
                ),
            )
        ],
        offer_variety_K=NumberRange(min=1, max=100),
    )
    te = TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[tok],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(10000),
            expected_Q=NumberRange.point(1000),
            # d=0 pins the φ-clause as satisfied (0 ≥ 0/K) so the only
            # way the FM can fail is via the γ-clause.
            average_demand_d=NumberRange.point(0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="contrib",
                    fraction=0.05,
                    role=AgentRole.CONTRIBUTOR,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(10)
                    ),
                ),
                AgentType(
                    id="rest",
                    fraction=0.95,
                    role=AgentRole.OBSERVER,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(10)
                    ),
                ),
            ],
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
            monitoring_capacity_gamma=NumberRange(min=0.5, max=0.95),
            sanction_structure=SanctionStructure(
                kind=SanctionKind.WARNING,
                S_normalized=NumberRange(min=0.3, max=0.6),
            ),
        ),
    )

    singles = compute_sensitivity(te, "FM4")
    pairs = compute_pairwise_sensitivity(te, "FM4", single_results=singles)

    # The sweep finds *some* joint flip — either gamma+K at max,max or
    # similar. We don't pin which exact pair: the assertion is that
    # the multi-input pathway surfaces a flipping corner that no single
    # input could.
    assert len(pairs) > 0, (
        "Pairwise sweep should surface at least one joint flip when "
        "FM4 fails on both clauses but each clause has a fixable knob."
    )
    # All reported pairs must use fields that did NOT single-flip.
    single_flippers = {s.field for s in singles if s.flips_verdict}
    for p in pairs:
        assert p.field_a not in single_flippers
        assert p.field_b not in single_flippers


def test_pairwise_sensitivity_returns_empty_when_singles_cover() -> None:
    """If the verdict is already explained by single-input flips, the
    pairwise sweep should return empty (single-flippers are skipped)."""
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=50.0)],
        offer_variety_K=NumberRange.point(5),
    )
    te = TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[tok],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange(min=10, max=200),  # single-flipper
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
    singles = compute_sensitivity(te, "FM1", subject="T")
    pairs = compute_pairwise_sensitivity(
        te, "FM1", subject="T", single_results=singles
    )
    # FM1 has only one candidate (expected_Q) and it's a single-flipper,
    # so there are no pairs to evaluate. Empty list is the right answer.
    assert pairs == []


def test_sensitivity_robust_failure_lists_no_flippers() -> None:
    """If no input flips the verdict, no flippers are returned."""
    # No burn rules → FM3 fails by construction; no input at extreme
    # can rescue this (the failure is structural).
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=10.0)],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok])
    inputs = compute_sensitivity(te, "FM3", subject="T")
    flippers = [i for i in inputs if i.flips_verdict]
    # No-burn FAIL is structural — moving Q won't fix it.
    assert flippers == []


# ---------------------------------------------------------------------------
# Refinement integration
# ---------------------------------------------------------------------------


def test_refinement_attaches_to_failing_verdict() -> None:
    """A FAIL verdict gets a refined_diagnosis dict via the dispatcher."""
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=100.0)],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok], Q=10.0)
    rep = verify(te)
    fm3 = next(v for v in rep.verdicts if v.failure_mode.startswith("FM3"))
    assert fm3.status.value == "fail"
    assert fm3.refined_diagnosis is not None
    assert "headline" in fm3.refined_diagnosis
    # Trajectory should report monotone growth
    assert fm3.refined_diagnosis["trajectory"] is not None
    metrics = fm3.refined_diagnosis["trajectory"]["metrics"]
    assert metrics["M_terminal"] > metrics["M_initial"]


def test_refinement_skips_passing_verdict() -> None:
    """PASS verdicts don't carry a refined_diagnosis."""
    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=10.0)],
        burn_rules=[_burn(c=20.0)],  # burn covers
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok], Q=100.0)
    rep = verify(te)
    fm3 = next(v for v in rep.verdicts if v.failure_mode.startswith("FM3"))
    assert fm3.status.value == "pass"
    assert fm3.refined_diagnosis is None


def test_refinement_attaches_to_pass_as_intended() -> None:
    """A governance-token PASS_AS_INTENDED gets a refined_diagnosis
    explaining the relax + showing the trajectory."""
    tok = Token(
        id="MKR",
        function=[TokenFunction.GOVERNANCE_RIGHT, TokenFunction.STORE_OF_VALUE],
        emission_rules=[_emit(c=10.0)],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok], Q=100.0)
    rep = verify(te)
    fm3 = next(v for v in rep.verdicts if v.failure_mode.startswith("FM3"))
    assert fm3.status.value == "pass_as_intended"
    assert fm3.refined_diagnosis is not None
    assert "design-intended" in fm3.refined_diagnosis["headline"]


def test_refined_diagnosis_dict_is_json_serialisable() -> None:
    """The dict shape must round-trip through model_dump(mode='json')
    so the API response can be JSON-encoded without surprises."""
    import json

    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emit(c=100.0)],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = _make_te(tokens=[tok], Q=10.0)
    rep = verify(te)
    fm3 = next(v for v in rep.verdicts if v.failure_mode.startswith("FM3"))
    # Should not raise
    serialized = json.dumps(fm3.refined_diagnosis)
    assert "headline" in serialized
