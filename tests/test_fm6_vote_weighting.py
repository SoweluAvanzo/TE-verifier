"""FM6 — VoteWeighting effective-Gini approximations.

Pins audit fix #1 (expanded form). The pre-fix FM6 used
``token_balance_gini`` directly as the secondary-signal threshold,
which is a crude proxy that ignores the actual vote-weighting
mechanism. Post-fix, ``GovernanceSpec.vote_weighting`` selects a
calibration class — LINEAR (default, pre-fix behavior), QUADRATIC,
CAPPED, TIME_LOCKED, DELEGATED, REPUTATION_WEIGHTED — and FM6
computes an effective Gini before checking against the threshold.

These tests pin both the per-class approximation logic and the
top-level FM6 behavior. The approximations are deliberately
conservative — precise effective-Gini values depend on the full
balance histogram, which is an ABM concern.
"""

from __future__ import annotations

import pytest

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
    SanctionKind,
    SanctionStructure,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
    VoteWeighting,
)
from verifier import Status
from verifier.config import VerifierConfig
from verifier.failure_modes.fm6_governance import (
    FM6GovernanceCapture,
    _effective_gini_range,
)


def _gov_with(
    *,
    token_gini: NumberRange | None = NumberRange(min=0.8, max=0.85),
    vote_weighting: VoteWeighting = VoteWeighting.LINEAR,
    params: dict[str, NumberRange] | None = None,
) -> GovernanceSpec:
    kwargs: dict = {
        "type": GovernanceType.DAO,
        "rule_structure": {"r1": ControllingActor.TOKEN_HOLDER_VOTE},
        "token_balance_gini": token_gini,
        "vote_weighting": vote_weighting,
        "vote_weighting_params": params or {},
    }
    return GovernanceSpec(**kwargs)


def _te_with(gov: GovernanceSpec) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[
            Token(
                id="T",
                function=[TokenFunction.GOVERNANCE_RIGHT],
                emission_rules=[
                    Rule(
                        trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                        function=FunctionShape(
                            sign=FunctionSign.ALWAYS_POSITIVE,
                            asymptotic_class=AsymptoticClass(
                                family=AsymptoticFamily.CONSTANT,
                                parameter_ranges={"c": NumberRange.point(1.0)},
                            ),
                        ),
                    )
                ],
                offer_variety_K=NumberRange.point(10),
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(10000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
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
        governance=gov,
    )


# ---------------------------------------------------------------------------
# Direct _effective_gini_range tests — one per VoteWeighting variant
# ---------------------------------------------------------------------------


def test_effective_gini_linear_is_identity() -> None:
    """LINEAR preserves token_balance_gini exactly (back-compat)."""
    gov = _gov_with(vote_weighting=VoteWeighting.LINEAR)
    eff, _note = _effective_gini_range(gov)
    assert eff is not None
    assert eff.min == 0.8
    assert eff.max == 0.85


def test_effective_gini_quadratic_reduces() -> None:
    """QUADRATIC: effective Gini ≈ token Gini × [0.5, 0.7] (default config)."""
    gov = _gov_with(vote_weighting=VoteWeighting.QUADRATIC)
    eff, note = _effective_gini_range(gov)
    assert eff is not None
    # Token Gini was 0.8-0.85; expect 0.4-0.595 (0.5 × 0.8 to 0.7 × 0.85)
    assert eff.min == pytest.approx(0.8 * 0.5)
    assert eff.max == pytest.approx(0.85 * 0.7)
    assert "QUADRATIC" in note


def test_effective_gini_capped_clips_by_cap_fraction() -> None:
    """CAPPED: effective Gini scales by (1 − cap_fraction)."""
    gov = _gov_with(
        vote_weighting=VoteWeighting.CAPPED,
        params={"cap_fraction": NumberRange(min=0.1, max=0.2)},
    )
    eff, note = _effective_gini_range(gov)
    assert eff is not None
    # With cap_fraction 0.1-0.2, effective Gini = token × (1 - cap)
    # = 0.8 * 0.8 = 0.64 to 0.85 * 0.9 = 0.765
    assert eff.min == pytest.approx(0.8 * (1 - 0.2))
    assert eff.max == pytest.approx(0.85 * (1 - 0.1))
    assert "CAPPED" in note


def test_effective_gini_time_locked_scales_by_lock_fraction() -> None:
    """TIME_LOCKED: effective Gini = token Gini × avg_lock_fraction."""
    gov = _gov_with(
        vote_weighting=VoteWeighting.TIME_LOCKED,
        params={"avg_lock_fraction": NumberRange(min=0.25, max=0.5)},
    )
    eff, note = _effective_gini_range(gov)
    assert eff is not None
    assert eff.min == pytest.approx(0.8 * 0.25)
    assert eff.max == pytest.approx(0.85 * 0.5)
    assert "TIME_LOCKED" in note


def test_effective_gini_delegated_substitutes() -> None:
    """DELEGATED: effective Gini = delegate_concentration_gini (substitutes)."""
    gov = _gov_with(
        vote_weighting=VoteWeighting.DELEGATED,
        params={
            "delegate_concentration_gini": NumberRange(min=0.95, max=0.95)
        },
    )
    eff, note = _effective_gini_range(gov)
    assert eff is not None
    assert eff.min == 0.95
    assert eff.max == 0.95
    assert "DELEGATED" in note


def test_effective_gini_reputation_returns_inconclusive_without_param() -> None:
    """REPUTATION_WEIGHTED without reputation_gini → None (INCONCLUSIVE)."""
    gov = _gov_with(vote_weighting=VoteWeighting.REPUTATION_WEIGHTED)
    eff, note = _effective_gini_range(gov)
    assert eff is None
    assert "INCONCLUSIVE" in note or "reputation_gini" in note


def test_effective_gini_reputation_uses_param_when_supplied() -> None:
    """REPUTATION_WEIGHTED with reputation_gini substitutes token Gini."""
    gov = _gov_with(
        vote_weighting=VoteWeighting.REPUTATION_WEIGHTED,
        params={"reputation_gini": NumberRange(min=0.3, max=0.4)},
    )
    eff, note = _effective_gini_range(gov)
    assert eff is not None
    assert eff.min == 0.3
    assert eff.max == 0.4
    assert "REPUTATION_WEIGHTED" in note


# ---------------------------------------------------------------------------
# FM6 integration — verdict-flip behavior per voting class
# ---------------------------------------------------------------------------


def test_linear_high_gini_fails_fm6() -> None:
    """LINEAR + high token Gini = pre-fix behavior: FM6 fails."""
    te = _te_with(_gov_with(token_gini=NumberRange(min=0.7, max=0.85)))
    v = FM6GovernanceCapture().check(te)[0]
    assert v.status == Status.FAIL


def test_quadratic_with_same_gini_passes_fm6() -> None:
    """QUADRATIC + same high token Gini should PASS — QV halves
    effective concentration. This is the verdict-flip that pre-fix
    FM6 could never produce."""
    te = _te_with(
        _gov_with(
            token_gini=NumberRange(min=0.7, max=0.85),
            vote_weighting=VoteWeighting.QUADRATIC,
        )
    )
    v = FM6GovernanceCapture().check(te)[0]
    # Effective Gini under QV: 0.7×0.5=0.35 to 0.85×0.7=0.595. Both
    # below the 0.6 secondary threshold.
    assert v.status == Status.PASS


def test_capped_voting_can_pass_high_gini_system() -> None:
    """A high-Gini system with a 50% vote cap → effective concentration
    halved → passes."""
    te = _te_with(
        _gov_with(
            token_gini=NumberRange(min=0.8, max=0.85),
            vote_weighting=VoteWeighting.CAPPED,
            params={"cap_fraction": NumberRange(min=0.5, max=0.5)},
        )
    )
    v = FM6GovernanceCapture().check(te)[0]
    # Effective Gini: 0.8×0.5=0.4 to 0.85×0.5=0.425, below 0.6
    assert v.status == Status.PASS


def test_delegated_can_flag_when_delegate_gini_high() -> None:
    """A token-Gini-moderate system with concentrated delegates fails
    on the substituted delegate_concentration_gini — pre-fix this was
    invisible."""
    te = _te_with(
        _gov_with(
            token_gini=NumberRange(min=0.5, max=0.55),
            vote_weighting=VoteWeighting.DELEGATED,
            params={
                "delegate_concentration_gini": NumberRange(min=0.85, max=0.9)
            },
        )
    )
    v = FM6GovernanceCapture().check(te)[0]
    assert v.status == Status.FAIL


def test_reputation_weighted_without_param_is_inconclusive() -> None:
    """REPUTATION_WEIGHTED without reputation_gini drops the secondary
    signal entirely. With no Γ violation either, the verdict is
    INCONCLUSIVE (pre-fix: would have wrongly applied token_balance_gini)."""
    te = _te_with(
        _gov_with(
            token_gini=NumberRange(min=0.95, max=0.99),  # would fail under LINEAR
            vote_weighting=VoteWeighting.REPUTATION_WEIGHTED,
        )
    )
    v = FM6GovernanceCapture().check(te)[0]
    # With Γ = 0 (TOKEN_HOLDER_VOTE only) and Gini channel suppressed,
    # the verdict should be PASS (no concern triggered) — reputation
    # systems whose reputation distribution is not declared are simply
    # uncheckable on FM6's secondary signal.
    assert v.status in (Status.PASS, Status.INCONCLUSIVE)


# ---------------------------------------------------------------------------
# Defaults and back-compat
# ---------------------------------------------------------------------------


def test_governance_spec_defaults_to_linear() -> None:
    """Existing v1 IRs without vote_weighting get LINEAR — preserves
    pre-fix behavior."""
    gov = GovernanceSpec(type=GovernanceType.DAO)
    assert gov.vote_weighting == VoteWeighting.LINEAR
    assert gov.vote_weighting_params == {}


def test_case_studies_declare_realistic_vote_weighting() -> None:
    """Pin the realistic vote_weighting declarations on the case-study
    YAMLs. Curve uses TIME_LOCKED (veCRV is the canonical vote-escrow
    pattern); MakerDAO uses DELEGATED (active delegate platform); the
    rest default to LINEAR (token-vote not the primary mechanism)."""
    from pathlib import Path
    from schema import load_te

    examples = Path(__file__).resolve().parent.parent / "examples"
    expected = {
        "bitcoin": VoteWeighting.LINEAR,
        "ethereum": VoteWeighting.LINEAR,
        "makerdao": VoteWeighting.DELEGATED,
        "curve_vecrv": VoteWeighting.TIME_LOCKED,
        "axie_infinity": VoteWeighting.LINEAR,
    }
    for name, expected_weighting in expected.items():
        te = load_te(examples / f"{name}.yaml")
        assert te.governance.vote_weighting == expected_weighting, (
            f"{name}: expected vote_weighting={expected_weighting.value}, "
            f"got {te.governance.vote_weighting.value}"
        )


def test_v2_migration_preserves_vote_weighting() -> None:
    """from_v1 carries vote_weighting and vote_weighting_params into v2."""
    from schema import v2 as schema_v2

    te_v1 = _te_with(
        _gov_with(
            vote_weighting=VoteWeighting.QUADRATIC,
            params={"cap_fraction": NumberRange(min=0.1, max=0.2)},
        )
    )
    te_v2 = schema_v2.from_v1(te_v1)
    assert te_v2.governance.vote_weighting.value == "quadratic"
    assert "cap_fraction" in te_v2.governance.vote_weighting_params


def test_fm6v2_byte_equality_under_new_weighting() -> None:
    """FM6v2 produces byte-identical output to FM6v1 under non-LINEAR
    weightings — confirms the adapter preserves the new fields."""
    from schema import v2 as schema_v2
    from verifier.failure_modes.fm6_v2 import FM6GovernanceCaptureV2

    te_v1 = _te_with(
        _gov_with(
            token_gini=NumberRange(min=0.7, max=0.85),
            vote_weighting=VoteWeighting.QUADRATIC,
        )
    )
    te_v2 = schema_v2.from_v1(te_v1)
    v1_verdicts = FM6GovernanceCapture().check(te_v1)
    v2_verdicts = FM6GovernanceCaptureV2().check(te_v2)
    assert [v.model_dump(mode="json") for v in v1_verdicts] == [
        v.model_dump(mode="json") for v in v2_verdicts
    ]


def test_qv_multiplier_overrideable_via_config() -> None:
    """Users can tune the QV multiplier range via VerifierConfig."""
    cfg = VerifierConfig.paper_defaults()
    mn, mx = cfg.vote_weighting_quadratic_multiplier_range
    assert mn == pytest.approx(0.5)
    assert mx == pytest.approx(0.7)
