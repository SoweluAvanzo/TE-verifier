"""Phase D3 — Simulator.pdf §5 coherence checks (C2..C7).

Existing rules 1–3 already covered by other tests; here we cover the
six new Simulator.pdf §5 rules. C7 is verdict-aware (uses risk-band
data) and is therefore tested through the full `verify(te)` path.
"""

from __future__ import annotations

import pytest

from schema import (
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    CirculationSpeed,
    ContributionVerification,
    ControllingActor,
    EmissionTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceMaturity,
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
from verifier.elicitation import coherence_violations


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


def _expiry_burn() -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=BurnTriggerKind.EXPIRY,
            event_frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_NEGATIVE,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(0.5)},
            ),
        ),
    )


def _make_te(*, nfrs=None, governance=None, tokens=None) -> TokenEconomy:
    if tokens is None:
        tokens = [
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=[_emit(c=1.0)],
                offer_variety_K=NumberRange.point(5),
            )
        ]
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=nfrs or NFRs()),
        tokens=tokens,
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
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
        governance=governance
        or GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
        ),
    )


# ---------------------------------------------------------------------------
# C2: NFR5 ≥ 4 + verification = self_reporting (CRITICAL)
# ---------------------------------------------------------------------------


def test_c2_proportionality_vs_self_reporting() -> None:
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit()],
            contribution_verification=ContributionVerification.SELF_REPORTING,
            offer_variety_K=NumberRange.point(5),
        )
    ]
    te = _make_te(tokens=tokens, nfrs=NFRs(proportionality=5))
    issues = coherence_violations(te)
    c2 = [i for i in issues if "C2" in i.message]
    assert len(c2) == 1
    assert c2[0].severity == "error"


def test_c2_does_not_fire_when_verification_strong() -> None:
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit()],
            contribution_verification=ContributionVerification.PHYSICAL_PRESENCE,
            offer_variety_K=NumberRange.point(5),
        )
    ]
    te = _make_te(tokens=tokens, nfrs=NFRs(proportionality=5))
    issues = coherence_violations(te)
    assert not any("C2" in i.message for i in issues)


# ---------------------------------------------------------------------------
# C3: NFR1 ≥ 4 + no burn (CRITICAL)
# ---------------------------------------------------------------------------


def test_c3_resilience_vs_no_burn() -> None:
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit()],
            burn_rules=[],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    te = _make_te(tokens=tokens, nfrs=NFRs(resilience=5))
    issues = coherence_violations(te)
    c3 = [i for i in issues if "C3" in i.message]
    assert len(c3) == 1
    assert c3[0].severity == "error"


# ---------------------------------------------------------------------------
# C4: NFR7 = immediate + Γ = 1.0
# ---------------------------------------------------------------------------


def test_c4_immediate_maturity_vs_full_centralization() -> None:
    gov = GovernanceSpec(
        type=GovernanceType.CENTRALIZED,
        rule_structure={
            f"d{i}": ControllingActor.SINGLE_ENTITY for i in range(7)
        },
    )
    te = _make_te(
        nfrs=NFRs(governance_maturity=GovernanceMaturity.IMMEDIATE),
        governance=gov,
    )
    issues = coherence_violations(te)
    c4 = [i for i in issues if "C4" in i.message]
    assert len(c4) == 1
    assert c4[0].severity == "warn"


# ---------------------------------------------------------------------------
# C5: NFR3 ≥ 4 + governance = DAO
# ---------------------------------------------------------------------------


def test_c5_accessibility_vs_dao_governance() -> None:
    gov = GovernanceSpec(
        type=GovernanceType.DAO,
        rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
    )
    te = _make_te(
        nfrs=NFRs(accessibility=5),
        governance=gov,
    )
    issues = coherence_violations(te)
    c5 = [i for i in issues if "C5" in i.message]
    assert len(c5) == 1
    assert c5[0].severity == "warn"


# ---------------------------------------------------------------------------
# C6: NFR6 = retain_value + burn = expiry
# ---------------------------------------------------------------------------


def test_c6_retain_value_vs_expiry_burn() -> None:
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit()],
            burn_rules=[_expiry_burn()],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    te = _make_te(
        tokens=tokens,
        nfrs=NFRs(circulation_speed=CirculationSpeed.RETAIN_VALUE),
    )
    issues = coherence_violations(te)
    c6 = [i for i in issues if "C6" in i.message]
    assert len(c6) == 1
    assert c6[0].severity == "warn"


# ---------------------------------------------------------------------------
# C7: ros>1.5 + ρ=0 + Γ=1 (CRITICAL, verdict-aware)
# ---------------------------------------------------------------------------


def test_c7_supply_side_triad_critical() -> None:
    """Build a system that triggers all three supply-side conditions."""
    gov = GovernanceSpec(
        type=GovernanceType.CENTRALIZED,
        rule_structure={
            f"d{i}": ControllingActor.SINGLE_ENTITY for i in range(7)
        },
    )
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit(c=200.0)],  # high emission
            burn_rules=[],  # no burn
            offer_variety_K=NumberRange.point(5),
        )
    ]
    te = _make_te(tokens=tokens, governance=gov)
    # Use the full verify() path to get verdicts attached for C7.
    report = verify(te)
    c7 = [i for i in report.coherence_issues if "C7" in i.message]
    assert len(c7) == 1
    assert c7[0].severity == "error"


def test_c7_does_not_fire_when_governance_distributed() -> None:
    """Even with FM1 red and FM3 red_critical, distributed governance
    means the corrective lever exists — C7 should not fire."""
    gov = GovernanceSpec(
        type=GovernanceType.DAO,
        rule_structure={
            f"d{i}": ControllingActor.TOKEN_HOLDER_VOTE for i in range(7)
        },
    )
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit(c=200.0)],
            burn_rules=[],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    te = _make_te(tokens=tokens, governance=gov)
    report = verify(te)
    assert not any("C7" in i.message for i in report.coherence_issues)


def test_coherence_violations_back_compat_without_verdicts() -> None:
    """Calling coherence_violations(te) without verdicts must not crash
    (back-compat) — it just skips C7."""
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit()],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    te = _make_te(tokens=tokens)
    issues = coherence_violations(te)
    assert isinstance(issues, list)
    assert not any("C7" in i.message for i in issues)
