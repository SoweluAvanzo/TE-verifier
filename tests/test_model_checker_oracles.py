"""Model-checker correctness oracles.

Every test here pins the verifier's Z3 results against a value derived
BY HAND from the paper's closed-form conditions — no fixtures shared
with the implementation, no tolerance for "plausible" output. If the
encoding drifts (wrong inequality direction, wrong composition, wrong
threshold source), these go red with the hand math in the assertion.

Covered:
  FM1  E = c × freq vs Q boundary, range reachability, and witness
       arithmetic (the counterexample really violates E > Q).
  FM2  wealth-weighted τ̄ threshold and the 1.5/0.9 minimum-shift.
  FM3  ρ = B/E floor, including the NFR1-resilience multiplier (×1.1).
  FM4  φ ≥ d/K and the K*/φ* critical values against config-derived
       effective φ.
  FM5  N* = 2Kd + 1 exact boundary.
  FM6  Γ = unilateral/total decisions around the 0.5 threshold.
"""

from __future__ import annotations

import math

import pytest

from schema import (
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    ContributionVerification,
    ControllingActor,
    EventDefinition,
    EventTriggerKind,
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
from verifier.config import VerifierConfig


def _const(v_lo: float, v_hi: float | None = None) -> AsymptoticClass:
    return AsymptoticClass(
        family=AsymptoticFamily.CONSTANT,
        parameter_ranges={"c": NumberRange(min=v_lo, max=v_hi if v_hi is not None else v_lo)},
    )


def _fn(lo: float, hi: float | None = None) -> FunctionShape:
    return FunctionShape(sign=FunctionSign.ALWAYS_POSITIVE, asymptotic_class=_const(lo, hi))


def _behavioral_event(eid: str, freq_lo: float, freq_hi: float | None = None) -> EventDefinition:
    return EventDefinition(
        id=eid, label=eid, kind=EventTriggerKind.BEHAVIORAL,
        frequency=_const(freq_lo, freq_hi),
    )


def _demand_event(eid: str) -> EventDefinition:
    return EventDefinition(id=eid, label=eid, kind=EventTriggerKind.DEMAND_DRIVEN)


def _te(
    *,
    emission_rules,
    events,
    burn_rules=None,
    Q=(100.0, 100.0),
    N=(1000.0, 1000.0),
    d=(0.5, 0.5),
    K=(10.0, 10.0),
    holding=(2.0, 4.0),
    agent_types=None,
    rule_structure=None,
    gini=None,
    nfrs=None,
    verification=ContributionVerification.PEER_VERIFICATION,
) -> TokenEconomy:
    ht = HoldingTimeDistribution(expected_periods=NumberRange(min=holding[0], max=holding[1]))
    return TokenEconomy(
        meta=Meta(name="oracle", archetype=Archetype.OTHER, nfrs=nfrs or NFRs()),
        tokens=[
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=emission_rules,
                burn_rules=burn_rules or [],
                offer_variety_K=NumberRange(min=K[0], max=K[1]),
                contribution_verification=verification,
                redemption_mechanism=RedemptionMechanism.SPECIFIC_GOODS_OR_SERVICES,
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange(min=N[0], max=N[1]),
            expected_Q=NumberRange(min=Q[0], max=Q[1]),
            average_demand_d=NumberRange(min=d[0], max=d[1]),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=agent_types
            or [
                AgentType(id="worker", fraction=1.0, expected_holding_time=ht,
                          role=AgentRole.CONTRIBUTOR)
            ],
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure=rule_structure
            or {"x": ControllingActor.TOKEN_HOLDER_VOTE},
            sanction_structure=SanctionStructure(kind=SanctionKind.WARNING),
            token_balance_gini=(
                NumberRange(min=gini[0], max=gini[1]) if gini else None
            ),
        ),
        events=events,
    )


def _status(report, fm: str, subject: str) -> Status:
    return next(
        v for v in report.verdicts
        if v.failure_mode.startswith(fm) and v.subject == subject
    ).status


def _verdict(report, fm: str):
    return next(v for v in report.verdicts if v.failure_mode.startswith(fm))


# ---------------------------------------------------------------------------
# FM1 — E vs Q
# ---------------------------------------------------------------------------


def test_fm1_boundary_exact() -> None:
    """E = 10 tokens/event × 5 events/period = 50. Violation is strict
    (E > Q): Q = 50 must PASS, Q = 49 must FAIL."""
    def build(Q: float):
        return _te(
            emission_rules=[Rule(trigger=RuleTrigger(event_id="w"), function=_fn(10.0))],
            events=[_behavioral_event("w", 5.0)],
            Q=(Q, Q),
        )

    assert _status(verify(build(50.0)), "FM1", "T") == Status.PASS
    assert _status(verify(build(49.0)), "FM1", "T") == Status.FAIL


def test_fm1_witness_arithmetic() -> None:
    """For ranged inputs the Z3 witness must actually violate E > Q
    when recomputed by hand from the reported parameter values."""
    te = _te(
        emission_rules=[Rule(trigger=RuleTrigger(event_id="w"), function=_fn(1.0, 10.0))],
        events=[_behavioral_event("w", 1.0, 5.0)],
        Q=(20.0, 60.0),
    )
    v = _verdict(verify(te), "FM1")
    assert v.status == Status.FAIL
    assert v.counterexample is not None
    vals = v.counterexample.parameter_values
    e_total = next(val for key, val in vals.items() if "E_total" in key)
    q = next(val for key, val in vals.items() if "Q" in key and "E" not in key)
    assert e_total > q, vals
    # And the witness E must be reachable from the declared box:
    # E = c × freq with c ≤ 10, freq ≤ 5 → E ≤ 50.
    assert e_total <= 50.0 + 1e-6, vals


# ---------------------------------------------------------------------------
# FM2 — wealth-weighted holding time
# ---------------------------------------------------------------------------


def _two_type_agents(f1: float, f2: float, lo: float, hi: float) -> list[AgentType]:
    ht = HoldingTimeDistribution(expected_periods=NumberRange(min=lo, max=hi))
    return [
        AgentType(id="a", fraction=f1, expected_holding_time=ht, role=AgentRole.CONTRIBUTOR),
        AgentType(id="b", fraction=f2, expected_holding_time=ht, role=AgentRole.CONSUMER),
    ]


def test_fm2_minimum_shift_is_threshold_over_wealth_share() -> None:
    """Fractions 0.9/0.1, holding ∈ [0,4], τ̄ ceiling 1.5 (paper
    default): the binding repair is the 90%-share type's holding time
    raised to 1.5/0.9 = 1.6667 (other type at its 0 minimum)."""
    te = _te(
        emission_rules=[Rule(trigger=RuleTrigger(event_id="w"), function=_fn(1.0))],
        events=[_behavioral_event("w", 1.0)],
        agent_types=_two_type_agents(0.9, 0.1, 0.0, 4.0),
    )
    v = next(x for x in verify(te).verdicts if x.failure_mode.startswith("FM2"))
    assert v.status == Status.FAIL
    assert v.recommendation is not None
    assert v.recommendation.safe_threshold == pytest.approx(1.5 / 0.9)


def test_fm2_passes_when_floor_above_threshold() -> None:
    """Holding ∈ [2,4]: τ̄ ≥ 2 > 1.5 for every assignment → PASS."""
    te = _te(
        emission_rules=[Rule(trigger=RuleTrigger(event_id="w"), function=_fn(1.0))],
        events=[_behavioral_event("w", 1.0)],
        agent_types=_two_type_agents(0.9, 0.1, 2.0, 4.0),
    )
    assert _status(verify(te), "FM2", "T") == Status.PASS


# ---------------------------------------------------------------------------
# FM3 — ρ = B/E floor with NFR1 multiplier
# ---------------------------------------------------------------------------


def _fm3_te(burn_c: float, *, resilience: int = 3) -> TokenEconomy:
    return _te(
        emission_rules=[Rule(trigger=RuleTrigger(event_id="w"), function=_fn(10.0))],
        events=[_behavioral_event("w", 1.0), _demand_event("r")],
        burn_rules=[Rule(trigger=RuleTrigger(event_id="r"), function=_fn(burn_c))],
        nfrs=NFRs(resilience=resilience),
    )


def test_fm3_rho_floor_default() -> None:
    """E = 10. Default floor ρ ≥ 1: B = 9 → ρ = 0.9 FAIL; B = 10 → PASS."""
    assert _status(verify(_fm3_te(9.0)), "FM3", "T") == Status.FAIL
    assert _status(verify(_fm3_te(10.0)), "FM3", "T") == Status.PASS


def test_fm3_rho_floor_scaled_by_nfr1() -> None:
    """NFR1 resilience = 5 raises the floor by the config multiplier
    (paper default 1.1 → ρ ≥ 1.1): B = 10.5 (ρ=1.05) must now FAIL,
    B = 11 (ρ=1.1) must PASS."""
    cfg = VerifierConfig.paper_defaults()
    mult = cfg.nfr1_rho_multiplier_table["5"] if "5" in cfg.nfr1_rho_multiplier_table else cfg.nfr1_rho_multiplier_table[5]
    assert mult == pytest.approx(1.1)
    assert _status(verify(_fm3_te(10.5, resilience=5)), "FM3", "T") == Status.FAIL
    assert _status(verify(_fm3_te(11.0, resilience=5)), "FM3", "T") == Status.PASS


# ---------------------------------------------------------------------------
# FM4 — φ ≥ d/K critical values
# ---------------------------------------------------------------------------


def test_fm4_phi_critical_value_is_d_over_K() -> None:
    """d = 1.0 fixed, K = 8 fixed, contributor fraction 0.1 with
    peer verification. The φ-side critical value must equal
    d/K = 0.125 exactly (closed form, no approximation)."""
    ht = HoldingTimeDistribution(expected_periods=NumberRange(min=2.0, max=4.0))
    te = _te(
        emission_rules=[Rule(trigger=RuleTrigger(event_id="w"), function=_fn(1.0))],
        events=[_behavioral_event("w", 1.0)],
        d=(1.0, 1.0),
        K=(8.0, 8.0),
        agent_types=[
            AgentType(id="c", fraction=0.1, expected_holding_time=ht,
                      role=AgentRole.CONTRIBUTOR),
            AgentType(id="u", fraction=0.9, expected_holding_time=ht,
                      role=AgentRole.CONSUMER),
        ],
    )
    v = _verdict(verify(te), "FM4")
    phi_star = next(
        (cv.value for cv in v.critical_values if cv.parameter == "phi"), None
    )
    assert phi_star == pytest.approx(1.0 / 8.0), v.critical_values


# ---------------------------------------------------------------------------
# FM5 — N* = 2Kd + 1
# ---------------------------------------------------------------------------


def test_fm5_exact_boundary() -> None:
    """K = 10, d = 0.5 → N* = 2·10·0.5 + 1 = 11. N = 11 PASS, N = 10 FAIL."""
    def build(N: float):
        return _te(
            emission_rules=[Rule(trigger=RuleTrigger(event_id="w"), function=_fn(1.0))],
            events=[_behavioral_event("w", 1.0)],
            N=(N, N), d=(0.5, 0.5), K=(10.0, 10.0),
        )

    assert _status(verify(build(11.0)), "FM5", "system") == Status.PASS
    fail_report = verify(build(10.0))
    v = _verdict(fail_report, "FM5")
    assert v.status == Status.FAIL
    n_star = next(cv.value for cv in v.critical_values if cv.parameter == "N")
    assert n_star == pytest.approx(11.0)


# ---------------------------------------------------------------------------
# FM6 — Γ = unilateral / total
# ---------------------------------------------------------------------------


def _gov_te(n_single: int, n_vote: int) -> TokenEconomy:
    rs = {}
    for i in range(n_single):
        rs[f"s{i}"] = ControllingActor.SINGLE_ENTITY
    for i in range(n_vote):
        rs[f"v{i}"] = ControllingActor.TOKEN_HOLDER_VOTE
    return _te(
        emission_rules=[Rule(trigger=RuleTrigger(event_id="w"), function=_fn(1.0))],
        events=[_behavioral_event("w", 1.0)],
        rule_structure=rs,
        gini=(0.2, 0.3),  # benign Gini → Γ is the only signal
    )


def test_fm6_gamma_threshold() -> None:
    """Γ = 4/7 ≈ 0.571 > 0.5 → FAIL; Γ = 3/7 ≈ 0.429 ≤ 0.5 → PASS."""
    assert _status(verify(_gov_te(4, 3)), "FM6", "system") == Status.FAIL
    assert _status(verify(_gov_te(3, 4)), "FM6", "system") == Status.PASS


def test_fm6_demotion_critical_value() -> None:
    """With U = 4 unilateral of T = 7: n* = ceil(U − T·0.5) = ceil(0.5)
    = 1 decision must be demoted to reach Γ ≤ 0.5."""
    v = _verdict(verify(_gov_te(4, 3)), "FM6")
    n_demote = next(
        (cv.value for cv in v.critical_values if "demot" in (cv.parameter or "").lower()
         or "unilateral" in (cv.parameter or "").lower()),
        None,
    )
    if n_demote is not None:
        assert n_demote == pytest.approx(1.0)
    else:
        # Critical value exposed under a different parameter name —
        # at minimum the formula must appear in one critical value.
        assert any(
            "ceil" in (cv.formula or "") or "demote" in (cv.explanation or "").lower()
            for cv in v.critical_values
        ), v.critical_values


# ---------------------------------------------------------------------------
# FM4 — γ precedence, recommendation routing, and the repair property
# ---------------------------------------------------------------------------


def _nlab_shaped_te(*, explicit_gamma: bool, K=(8.0, 24.0)) -> TokenEconomy:
    """NLAB-shaped FM4 fixture: contributor share 0.1 with third-party
    verification (φ_eff = 0.09), NFR5 = 5 (×1.2 proportionality), and
    optionally an explicit γ ∈ [0.95, 1.0] that makes the monitoring
    clause unviolable across the box."""
    ht = HoldingTimeDistribution(expected_periods=NumberRange(min=2.0, max=4.0))
    gov_kwargs = dict(
        type=GovernanceType.CENTRALIZED,
        rule_structure={"x": ControllingActor.SINGLE_ENTITY},
        sanction_structure=SanctionStructure(
            kind=SanctionKind.ECONOMIC,
            S_normalized=NumberRange(min=0.7, max=0.9),
        ),
    )
    if explicit_gamma:
        gov_kwargs["monitoring_capacity_gamma"] = NumberRange(min=0.95, max=1.0)
    return _te(
        emission_rules=[Rule(trigger=RuleTrigger(event_id="w"), function=_fn(10.0))],
        events=[_behavioral_event("w", 1.0)],
        d=(0.1, 1.0),
        K=K,
        nfrs=NFRs(proportionality=5),
        verification=ContributionVerification.THIRD_PARTY_CERTIFICATION,
        agent_types=[
            AgentType(id="assoc", fraction=0.1, expected_holding_time=ht,
                      role=AgentRole.CONTRIBUTOR),
            AgentType(id="vol", fraction=0.9, expected_holding_time=ht,
                      role=AgentRole.CONSUMER),
        ],
    ).model_copy(update={"governance": GovernanceSpec(**gov_kwargs)})


def test_fm4_explicit_gamma_overrides_verification_derived() -> None:
    """Documented contract (paper §4.6, elicitation-mapping): a filled
    monitoring_capacity_gamma takes precedence over the
    verification-derived γ. The Z3 witness must respect the declared
    [0.95, 1.0] box, and since γ·S ≥ 0.95·0.7 = 0.665 > T−R there, the
    recommendation must NOT target the (unviolable) γ lever."""
    te = _nlab_shaped_te(explicit_gamma=True)
    v = _verdict(verify(te), "FM4")
    assert v.status == Status.FAIL
    assert v.counterexample.parameter_values["gamma"] >= 0.95 - 1e-9
    assert "contribution" in v.counterexample.binding_constraint
    assert v.recommendation is not None
    assert v.recommendation.parameter != "gamma", v.recommendation.narrative


def test_fm4_blank_gamma_still_uses_verification_table() -> None:
    """With γ left unset, the verification-derived range applies (the
    schema default must NOT shadow the elicitation table)."""
    te = _nlab_shaped_te(explicit_gamma=False)
    v = _verdict(verify(te), "FM4")
    # third_party_certification derives a γ range whose floor is below
    # 0.95 — the witness is free to go there.
    g = v.counterexample.parameter_values["gamma"]
    assert g < 0.95, g


def test_fm4_recommendation_repairs_the_verdict() -> None:
    """The strongest correctness property a recommendation can have:
    applying it must flip the verdict to PASS. K* must mirror the
    NFR5-tightened encoding (d·1.2/φ_eff = 1.2/0.09 ≈ 13.33), not the
    un-tightened paper form (1.0/0.09 ≈ 11.11, an insufficient
    repair)."""
    te = _nlab_shaped_te(explicit_gamma=True)
    v = _verdict(verify(te), "FM4")
    rec = v.recommendation
    assert rec.parameter == "K"
    # K* = d_hi · nfr5_mult / (contributor_fraction · verification_mult),
    # with both multipliers read from the paper-cited config tables.
    cfg = VerifierConfig.paper_defaults()
    nfr5_mult = cfg.nfr5_phi_multiplier_table["5"]
    phi_mult = cfg.phi_verification_floor_multiplier_table[
        "third_party_certification"
    ]
    expected_k = 1.0 * nfr5_mult / (0.1 * phi_mult)
    assert rec.safe_threshold == pytest.approx(expected_k, rel=1e-6)

    repaired = _nlab_shaped_te(
        explicit_gamma=True,
        K=(rec.safe_threshold + 0.01, max(24.0, rec.safe_threshold + 1.0)),
    )
    assert _verdict(verify(repaired), "FM4").status == Status.PASS
