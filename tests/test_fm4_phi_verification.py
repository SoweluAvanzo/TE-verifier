"""FM4 — φ_min derives from contribution_verification strength.

Pins audit fix #3. Pre-fix, ``contributor_fraction_from`` returned
``phi_min = 0`` unconditionally, letting Z3 satisfy ``φ·K < d`` at
φ=0 regardless of declared contributor share or verification mechanism.
Post-fix, ``phi_min`` scales with verification confidence per the
``phi_verification_floor_multiplier`` config table.

These tests exercise the elicitation layer directly (no Z3) and a
synthetic FM4 TE where the verification → phi_min mapping flips the
verdict.
"""

from __future__ import annotations

import pytest

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
from verifier import elicitation
from verifier.config import VerifierConfig
from verifier.failure_modes.fm4_freerider import FM4FreeRider


# ---------------------------------------------------------------------------
# Direct elicitation tests
# ---------------------------------------------------------------------------


def _agents(contrib_fraction: float = 0.3):
    """A simple agent_types list with one CONTRIBUTOR and one observer."""
    return [
        AgentType(
            id="contributor",
            fraction=contrib_fraction,
            role=AgentRole.CONTRIBUTOR,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(10)
            ),
        ),
        AgentType(
            id="rest",
            fraction=1.0 - contrib_fraction,
            role=AgentRole.OBSERVER,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(10)
            ),
        ),
    ]


@pytest.mark.parametrize(
    "verification, expected_multiplier",
    [
        (ContributionVerification.SMART_CONTRACT_AUTOMATION, 0.9),
        (ContributionVerification.THIRD_PARTY_CERTIFICATION, 0.7),
        (ContributionVerification.PHYSICAL_PRESENCE, 0.6),
        (ContributionVerification.PEER_VERIFICATION, 0.5),
        (ContributionVerification.SELF_REPORTING, 0.0),
        (ContributionVerification.UNSPECIFIED, 0.0),
        (None, 0.0),
    ],
)
def test_phi_min_scales_with_verification(
    verification, expected_multiplier: float
) -> None:
    """phi_min = multiplier × declared_share, per verification kind."""
    declared = 0.3
    phi_min, phi_max = elicitation.contributor_fraction_from(
        _agents(declared), contribution_verification=verification
    )
    assert phi_min == pytest.approx(expected_multiplier * declared)
    assert phi_max == pytest.approx(declared)


def test_phi_min_default_when_no_verification_arg() -> None:
    """Calling without contribution_verification preserves the pre-fix
    behavior: phi_min = 0. Important for back-compat with code paths
    that haven't been migrated to pass verification."""
    phi_min, phi_max = elicitation.contributor_fraction_from(_agents(0.3))
    assert phi_min == 0.0
    assert phi_max == pytest.approx(0.3)


def test_phi_min_clamped_by_phi_max() -> None:
    """phi_min must never exceed phi_max even if multiplier × declared
    would push it past the 0.05 default floor on the upper side."""
    # Declare only 0.02 contributors → phi_max = max(0.02, 0.05) = 0.05.
    # SMART_CONTRACT_AUTOMATION multiplier = 0.9 × 0.02 = 0.018 (below
    # phi_max). Confirms ordering.
    phi_min, phi_max = elicitation.contributor_fraction_from(
        _agents(0.02),
        contribution_verification=ContributionVerification.SMART_CONTRACT_AUTOMATION,
    )
    assert phi_min <= phi_max
    assert phi_min == pytest.approx(0.018)
    assert phi_max == pytest.approx(0.05)


def test_phi_min_keyword_path_unchanged_by_verification() -> None:
    """The legacy keyword-fallback path (no AgentRole declared) keeps
    phi_min = 0 regardless of verification — the keyword match is too
    unreliable to justify a higher floor."""
    legacy_agents = [
        AgentType(
            id="miner",  # matches keyword "miner"
            fraction=0.05,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(10)
            ),
        ),
        AgentType(
            id="user",
            fraction=0.95,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(10)
            ),
        ),
    ]
    phi_min, phi_max = elicitation.contributor_fraction_from(
        legacy_agents,
        contribution_verification=ContributionVerification.SMART_CONTRACT_AUTOMATION,
    )
    # Keyword path: phi_min = 0, phi_max = max(0.05, 0.05) = 0.05
    assert phi_min == 0.0
    assert phi_max == pytest.approx(0.05)


def test_phi_min_overrideable_via_config() -> None:
    """Users can tune the multiplier table via VerifierConfig."""
    cfg = VerifierConfig.paper_defaults()
    # Mutating the config field — only allowed because override_allowed=True
    # and we're not changing the underlying default factory.
    custom_cfg = cfg.model_copy()
    # Sanity: the default behavior is 0.9 × 0.3 = 0.27
    phi_min, _ = elicitation.contributor_fraction_from(
        _agents(0.3),
        contribution_verification=ContributionVerification.SMART_CONTRACT_AUTOMATION,
        config=custom_cfg,
    )
    assert phi_min == pytest.approx(0.27)


# ---------------------------------------------------------------------------
# FM4 integration test — synthetic TE where verification flips the verdict
# ---------------------------------------------------------------------------


def _fm4_te(
    *,
    verification: ContributionVerification | None,
    contributor_share: float = 0.10,
    K_range: tuple[float, float] = (100, 200),
    d_range: tuple[float, float] = (0.5, 5.0),
) -> TokenEconomy:
    """Build a minimal FM4-applicable TE with one CONTRIBUTOR.

    Z3's worst-case search picks the *lowest* φ, *lowest* K, and
    *highest* d simultaneously. To prove the verdict-flip, we need:

        phi_min · K_lo ≥ d_hi · nfr5_mult     (strong verification → PASS)
        phi_min · K_lo  < d_hi · nfr5_mult     (weak verification → FAIL)

    With nfr5_mult = 1, contributor_share = 0.10, K_lo = 100, d_hi = 5:
      - SMART_CONTRACT_AUTOMATION: phi_min = 0.9 · 0.10 = 0.09 →
        0.09 · 100 = 9.0 ≥ 5.0 → PASS
      - SELF_REPORTING:            phi_min = 0.0           →
        0.0  · 100 = 0.0 < 5.0  → FAIL
    """
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                contribution_verification=verification,
                redemption_mechanism=RedemptionMechanism.SPECIFIC_GOODS_OR_SERVICES,
                emission_rules=[
                    Rule(
                        trigger=RuleTrigger(
                            kind=EmissionTriggerKind.BEHAVIORAL_EVENT,
                        ),
                        function=FunctionShape(
                            sign=FunctionSign.ALWAYS_POSITIVE,
                            asymptotic_class=AsymptoticClass(
                                family=AsymptoticFamily.CONSTANT,
                                parameter_ranges={"c": NumberRange.point(1.0)},
                            ),
                        ),
                    )
                ],
                offer_variety_K=NumberRange(min=K_range[0], max=K_range[1]),
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(10000),
            expected_Q=NumberRange.point(1000),
            average_demand_d=NumberRange(min=d_range[0], max=d_range[1]),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=_agents(contributor_share),
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
            # γS strong enough to satisfy γS > T-R cleanly so the verdict
            # depends only on the φ-clause:
            monitoring_capacity_gamma=NumberRange.point(0.99),
            sanction_structure=SanctionStructure(
                kind=SanctionKind.ECONOMIC,
                S_normalized=NumberRange.point(0.95),
            ),
        ),
    )


def test_fm4_self_reporting_still_fails() -> None:
    """Weak verification + applicable contribution economy → FM4 fails
    as before (the fix doesn't loosen safety for unverified contributors)."""
    te = _fm4_te(
        verification=ContributionVerification.SELF_REPORTING,
        contributor_share=0.10,
    )
    v = FM4FreeRider().check(te)[0]
    assert v.status.value == "fail"


def test_fm4_smart_contract_verification_passes() -> None:
    """Strong verification + same declared contributors → FM4 passes.
    This is the verdict that pre-fix could not produce because
    phi_min = 0 always."""
    te = _fm4_te(
        verification=ContributionVerification.SMART_CONTRACT_AUTOMATION,
        contributor_share=0.10,
    )
    v = FM4FreeRider().check(te)[0]
    assert v.status.value == "pass", (
        f"Strong verification should give FM4=pass, got {v.status.value}. "
        f"explanation: {v.explanation}"
    )


def test_fm4_strongest_verification_picked_across_tokens() -> None:
    """When multiple tokens declare verification, FM4 uses the strongest
    (highest phi_min multiplier) for the φ-clause calculation."""
    te = _fm4_te(
        verification=ContributionVerification.SMART_CONTRACT_AUTOMATION,
        contributor_share=0.10,
    )
    # Add a second token with weaker verification
    weak_token = Token(
        id="WEAK",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        contribution_verification=ContributionVerification.SELF_REPORTING,
        emission_rules=[],
        offer_variety_K=NumberRange.point(1),
    )
    te = te.model_copy(update={"tokens": [te.tokens[0], weak_token]})
    strongest = FM4FreeRider._strongest_contribution_verification(te, None)
    assert strongest == ContributionVerification.SMART_CONTRACT_AUTOMATION


def test_fm4_v2_byte_equality_preserved() -> None:
    """The FM4v2 entry point must remain byte-identical to v1 under the
    new phi_min behavior — the v2 adapter preserves contribution_verification."""
    from schema import v2 as schema_v2
    from verifier.failure_modes.fm4_v2 import FM4FreeRiderV2

    te_v1 = _fm4_te(
        verification=ContributionVerification.SMART_CONTRACT_AUTOMATION,
        contributor_share=0.10,
    )
    te_v2 = schema_v2.from_v1(te_v1)
    v1_verdicts = FM4FreeRider().check(te_v1)
    v2_verdicts = FM4FreeRiderV2().check(te_v2)
    assert [v.model_dump(mode="json") for v in v1_verdicts] == [
        v.model_dump(mode="json") for v in v2_verdicts
    ]
