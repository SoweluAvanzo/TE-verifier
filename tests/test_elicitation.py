"""Phase 2 — elicitation derivation and coherence tests.

Locks the calibration tables, monotonicity properties, and coherence
rules against drift.
"""

from __future__ import annotations

import pytest

from schema import (
    AgentRole,
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
    HoldingIncentiveMechanism,
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
from verifier import elicitation, verify
from verifier.config import VerifierConfig


# ---------------------------------------------------------------------------
# γ derivation — every enum value has a derivation; monotonicity holds
# ---------------------------------------------------------------------------


def test_every_verification_has_gamma_range() -> None:
    for cv in ContributionVerification:
        r = elicitation.gamma_range_from(cv)
        assert r is not None, f"no γ derivation for {cv}"
        assert 0.0 <= r.min <= r.max <= 1.0


def test_gamma_range_monotone() -> None:
    """Stronger verification → higher γ floor.

    Order: self_reporting < third_party < peer < physical < smart_contract.
    """
    order = [
        ContributionVerification.SELF_REPORTING,
        ContributionVerification.THIRD_PARTY_CERTIFICATION,
        ContributionVerification.PEER_VERIFICATION,
        ContributionVerification.PHYSICAL_PRESENCE,
        ContributionVerification.SMART_CONTRACT_AUTOMATION,
    ]
    floors = [elicitation.gamma_range_from(cv).min for cv in order]
    for a, b in zip(floors, floors[1:]):
        assert a <= b, f"γ floor non-monotone: {floors}"


def test_gamma_range_unspecified_is_full_interval() -> None:
    r = elicitation.gamma_range_from(ContributionVerification.UNSPECIFIED)
    assert r is not None
    assert r.min == 0.0
    assert r.max == 1.0


def test_gamma_range_returns_none_when_input_none() -> None:
    assert elicitation.gamma_range_from(None) is None


# ---------------------------------------------------------------------------
# τ floor derivation — every enum value, monotonicity, max-stack
# ---------------------------------------------------------------------------


def test_every_holding_incentive_has_tau_floor() -> None:
    for inc in HoldingIncentiveMechanism:
        floor = elicitation.holding_time_floor_from([inc])
        assert floor > 0.0


def test_holding_incentive_none_is_lowest_floor() -> None:
    none_floor = elicitation.holding_time_floor_from(
        [HoldingIncentiveMechanism.NONE]
    )
    for inc in HoldingIncentiveMechanism:
        if inc == HoldingIncentiveMechanism.NONE:
            continue
        assert (
            elicitation.holding_time_floor_from([inc]) >= none_floor
        ), f"{inc} should not have τ floor below NONE"


def test_holding_incentive_stacking_takes_max() -> None:
    """Multiple incentives stack: floor = max across them."""
    f_governance = elicitation.holding_time_floor_from(
        [HoldingIncentiveMechanism.GOVERNANCE_RIGHTS]
    )
    f_reputation = elicitation.holding_time_floor_from(
        [HoldingIncentiveMechanism.REPUTATION]
    )
    f_combined = elicitation.holding_time_floor_from(
        [
            HoldingIncentiveMechanism.GOVERNANCE_RIGHTS,
            HoldingIncentiveMechanism.REPUTATION,
        ]
    )
    assert f_combined == max(f_governance, f_reputation)


def test_holding_incentive_empty_list_is_baseline() -> None:
    """Empty list = treat as `[NONE]`."""
    assert elicitation.holding_time_floor_from(
        []
    ) == elicitation.holding_time_floor_from([HoldingIncentiveMechanism.NONE])


# ---------------------------------------------------------------------------
# Temptation gap — every (verification, redemption) has a value;
# monotonicity in both axes
# ---------------------------------------------------------------------------


def test_every_pair_has_temptation_gap() -> None:
    for cv in ContributionVerification:
        for rm in RedemptionMechanism:
            gap = elicitation.temptation_gap_from(cv, rm)
            assert gap is not None, f"no T−R for ({cv}, {rm})"
            assert 0.0 <= gap <= 1.0


def test_temptation_gap_monotone_in_verification() -> None:
    """Stronger verification → smaller gap, holding redemption fixed."""
    rm = RedemptionMechanism.SPECIFIC_GOODS_OR_SERVICES
    order = [
        ContributionVerification.SMART_CONTRACT_AUTOMATION,
        ContributionVerification.PHYSICAL_PRESENCE,
        ContributionVerification.THIRD_PARTY_CERTIFICATION,
        ContributionVerification.PEER_VERIFICATION,
        ContributionVerification.SELF_REPORTING,
    ]  # strong → weak
    gaps = [elicitation.temptation_gap_from(cv, rm) for cv in order]
    for a, b in zip(gaps, gaps[1:]):
        assert a <= b, f"T−R non-monotone in verification: {gaps}"


def test_temptation_gap_monotone_in_redemption() -> None:
    """Less liquid redemption → smaller gap, holding verification fixed."""
    cv = ContributionVerification.PHYSICAL_PRESENCE
    order = [
        RedemptionMechanism.SPECIFIC_GOODS_OR_SERVICES,
        RedemptionMechanism.TIME_BASED_BORROWING,
        RedemptionMechanism.FUNGIBLE_ACCESS,
        RedemptionMechanism.OPEN_MARKET_EXCHANGE,
        RedemptionMechanism.PEER_TO_PEER_TRANSFER,
    ]  # structured → liquid
    gaps = [elicitation.temptation_gap_from(cv, rm) for rm in order]
    for a, b in zip(gaps, gaps[1:]):
        assert a <= b, f"T−R non-monotone in redemption: {gaps}"


# ---------------------------------------------------------------------------
# φ derivation — explicit role beats keyword fallback
# ---------------------------------------------------------------------------


def test_contributor_fraction_uses_explicit_role() -> None:
    agents = [
        AgentType(
            id="someone",
            fraction=0.3,
            role=AgentRole.CONTRIBUTOR,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
        AgentType(
            id="other",
            fraction=0.7,
            role=AgentRole.CONSUMER,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
    ]
    lo, hi = elicitation.contributor_fraction_from(agents)
    assert hi == pytest.approx(0.3, abs=1e-9)


def test_contributor_fraction_keyword_fallback_when_role_unset() -> None:
    """When no agent has role=, the legacy keyword heuristic kicks in."""
    agents = [
        AgentType(
            id="validator_node",
            fraction=0.4,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
        AgentType(
            id="user",
            fraction=0.6,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        ),
    ]
    lo, hi = elicitation.contributor_fraction_from(agents)
    # 'validator' keyword matches → contributor share = 0.4
    assert hi == pytest.approx(0.4, abs=1e-9)


# ---------------------------------------------------------------------------
# Coherence — rules fire on violations, stay silent on compatible inputs
# ---------------------------------------------------------------------------


def _make_te_with_token(token: Token, *, nfrs: NFRs | None = None) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=nfrs or NFRs()),
        tokens=[token],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
        ),
    )


def _emission_rule() -> Rule:
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


def _burn_rule(kind: BurnTriggerKind) -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=kind,
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


def test_coherence_p2p_plus_demand_driven_burn_flagged() -> None:
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_rule()],
        burn_rules=[_burn_rule(BurnTriggerKind.DEMAND_DRIVEN)],
        offer_variety_K=NumberRange.point(5),
        redemption_mechanism=RedemptionMechanism.PEER_TO_PEER_TRANSFER,
    )
    te = _make_te_with_token(token)
    issues = elicitation.coherence_violations(te)
    assert any(
        i.severity == "error" and "peer-to-peer" in i.message.lower()
        for i in issues
    )


def test_coherence_p2p_plus_rule_driven_burn_ok() -> None:
    """P2P transfer is incompatible with *demand-driven* burn only."""
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_rule()],
        burn_rules=[_burn_rule(BurnTriggerKind.RULE_DRIVEN)],
        offer_variety_K=NumberRange.point(5),
        redemption_mechanism=RedemptionMechanism.PEER_TO_PEER_TRANSFER,
    )
    te = _make_te_with_token(token)
    issues = elicitation.coherence_violations(te)
    assert not any(i.severity == "error" for i in issues)


def test_coherence_retain_value_plus_no_incentive_flagged() -> None:
    token = Token(
        id="T",
        function=[TokenFunction.STORE_OF_VALUE],
        holding_incentives=[HoldingIncentiveMechanism.NONE],
        emission_rules=[_emission_rule()],
        offer_variety_K=NumberRange.point(5),
    )
    nfrs = NFRs(circulation_speed=CirculationSpeed.RETAIN_VALUE)
    te = _make_te_with_token(token, nfrs=nfrs)
    issues = elicitation.coherence_violations(te)
    assert any("retain_value" in i.message or "hold" in i.message for i in issues)


def test_coherence_high_accessibility_plus_smart_contract_flagged() -> None:
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_rule()],
        offer_variety_K=NumberRange.point(5),
        contribution_verification=ContributionVerification.SMART_CONTRACT_AUTOMATION,
    )
    nfrs = NFRs(accessibility=5)
    te = _make_te_with_token(token, nfrs=nfrs)
    issues = elicitation.coherence_violations(te)
    assert any("accessibility" in i.message.lower() for i in issues)


def test_coherence_low_accessibility_plus_smart_contract_ok() -> None:
    """Low accessibility (≤ 3) + smart contract: no flag."""
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_rule()],
        offer_variety_K=NumberRange.point(5),
        contribution_verification=ContributionVerification.SMART_CONTRACT_AUTOMATION,
    )
    nfrs = NFRs(accessibility=2)
    te = _make_te_with_token(token, nfrs=nfrs)
    issues = elicitation.coherence_violations(te)
    assert not issues


# ---------------------------------------------------------------------------
# Report wiring: coherence_issues surface in the Report
# ---------------------------------------------------------------------------


def test_report_carries_coherence_issues() -> None:
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_rule()],
        burn_rules=[_burn_rule(BurnTriggerKind.DEMAND_DRIVEN)],
        offer_variety_K=NumberRange.point(5),
        redemption_mechanism=RedemptionMechanism.PEER_TO_PEER_TRANSFER,
    )
    te = _make_te_with_token(token)
    report = verify(te)
    assert report.coherence_issues
    assert any(i.severity == "error" for i in report.coherence_issues)


# ---------------------------------------------------------------------------
# Back-compat: legacy holding_incentive_present=True maps to the list
# ---------------------------------------------------------------------------


def test_backcompat_holding_incentive_bool_to_list() -> None:
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        holding_incentive_present=True,
        emission_rules=[_emission_rule()],
        offer_variety_K=NumberRange.point(5),
    )
    assert token.holding_incentives  # auto-populated by validator
    assert (
        HoldingIncentiveMechanism.GOVERNANCE_RIGHTS in token.holding_incentives
    )


def test_backcompat_holding_incentive_list_sets_bool() -> None:
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        holding_incentives=[HoldingIncentiveMechanism.STAKING],
        emission_rules=[_emission_rule()],
        offer_variety_K=NumberRange.point(5),
    )
    assert token.holding_incentive_present is True


def test_backcompat_holding_incentive_list_with_none_does_not_set_bool() -> None:
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        holding_incentives=[HoldingIncentiveMechanism.NONE],
        emission_rules=[_emission_rule()],
        offer_variety_K=NumberRange.point(5),
    )
    assert token.holding_incentive_present is False


# ---------------------------------------------------------------------------
# Override semantics
# ---------------------------------------------------------------------------


def test_config_override_changes_gamma_table() -> None:
    overridden = VerifierConfig.with_overrides(
        {
            "contribution_verification_to_gamma": {
                "physical_presence": [0.5, 0.6],  # tighter than default
                "smart_contract_automation": [0.95, 1.00],
                "peer_verification": [0.5, 0.8],
                "third_party_certification": [0.4, 0.7],
                "self_reporting": [0.05, 0.20],
                "unspecified": [0.0, 1.0],
            }
        }
    )
    r = elicitation.gamma_range_from(
        ContributionVerification.PHYSICAL_PRESENCE, config=overridden
    )
    assert r is not None
    assert r.min == 0.5
    assert r.max == 0.6
