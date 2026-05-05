"""Elicitation derivation layer (Phase 2).

The user's questionnaire answers map onto formal paper parameters
through a small set of pure derivation functions. Every function in
this module:

- takes a structured user choice (an enum value or a small list),
- consults a calibration table in `verifier.config.VerifierConfig`,
- returns a derived parameter range (typically `NumberRange`-shaped).

The tables themselves live in `VerifierConfig` so users can override
them per run; the derivation logic itself is paper-faithful and
deterministic.

Why this layer exists
---------------------

Several paper parameters (γ, τ, T − R) are hard for users to estimate
directly. The Roadmap docx therefore asks the user *structurally*
("how does your system verify contributions?") and the verifier
*derives* the formal parameter from the answer. This separates
elicitation (what the user is qualified to answer) from formal
encoding (what the math needs).

Coherence checks
----------------

Some combinations of structured choices are internally inconsistent
(e.g. peer-to-peer redemption + demand-driven burn — there's no
redemption event to fire the burn on). `coherence_violations` returns
a list of `CoherenceIssue` per token; the dispatcher surfaces them as
top-level Report warnings rather than per-FM verdicts.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from schema import (
    AgentType,
    BurnTriggerKind,
    CirculationSpeed,
    ContributionVerification,
    HoldingIncentiveMechanism,
    NumberRange,
    RedemptionMechanism,
    SanctionKind,
    SanctionStructure,
    Token,
    TokenEconomy,
)
from verifier.config import VerifierConfig


# ---------------------------------------------------------------------------
# Coherence issue type
# ---------------------------------------------------------------------------


class CoherenceIssue(BaseModel):
    """A cross-field inconsistency in the user's IR.

    Surfaced as a Report-level warning; not a per-FM verdict, because
    coherence is about IR validity rather than failure-mode triggering.

    Attributes
    ----------
    severity:
        ``"warn"`` (the IR is parseable but suspicious) or ``"error"``
        (the IR is internally contradictory and the verifier cannot
        reason about it).
    location:
        Dotted IR path identifying the offending fields.
    message:
        Plain-English description of the issue.
    suggestion:
        Plain-English instruction for the user to resolve it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: str
    location: str
    message: str
    suggestion: str


# ---------------------------------------------------------------------------
# γ derivation (FM4 monitoring capacity)
# ---------------------------------------------------------------------------


def gamma_range_from(
    verification: ContributionVerification | None,
    config: VerifierConfig | None = None,
) -> NumberRange | None:
    """Derive γ ∈ [γ_lo, γ_hi] from the contribution-verification choice.

    Returns ``None`` when `verification` is None — the caller should
    fall back to the user-supplied `governance.monitoring_capacity_gamma`
    or a wide-open sweep range.
    """
    if verification is None:
        return None
    cfg = config or VerifierConfig.paper_defaults()
    table = cfg.gamma_table
    entry = table.get(verification.value)
    if entry is None:
        return None
    return NumberRange(min=float(entry[0]), max=float(entry[1]))


# ---------------------------------------------------------------------------
# τ floor derivation (FM2 expected_holding_time default)
# ---------------------------------------------------------------------------


def holding_time_floor_from(
    incentives: list[HoldingIncentiveMechanism],
    config: VerifierConfig | None = None,
) -> float:
    """Derive a default τ floor (in periods) from the incentive list.

    Multiple incentives stack: the floor is the **maximum** floor across
    declared mechanisms (the strongest incentive dominates). Empty list
    or `[NONE]` returns the trap baseline (1.0).
    """
    cfg = config or VerifierConfig.paper_defaults()
    table = cfg.tau_floor_table
    if not incentives:
        return float(table.get("none", 1.0))
    floors = [
        float(table.get(inc.value, table.get("none", 1.0))) for inc in incentives
    ]
    return max(floors)


# ---------------------------------------------------------------------------
# T − R derivation (FM4 temptation gap)
# ---------------------------------------------------------------------------


def temptation_gap_from(
    verification: ContributionVerification | None,
    redemption: RedemptionMechanism | None,
    config: VerifierConfig | None = None,
) -> float | None:
    """Derive the normalized temptation gap T − R ∈ [0, 1].

    Returns ``None`` when either input is None — the caller falls back
    to ``config.temptation_gap_default``.
    """
    if verification is None or redemption is None:
        return None
    cfg = config or VerifierConfig.paper_defaults()
    inner = cfg.temptation_gap_table.get(verification.value)
    if inner is None:
        return None
    return inner.get(redemption.value)


# ---------------------------------------------------------------------------
# S derivation (FM4 sanction magnitude)
# ---------------------------------------------------------------------------


def s_normalized_from(
    sanction: SanctionStructure,
    config: VerifierConfig | None = None,
) -> NumberRange:
    """Derive S ∈ [S_lo, S_hi] from the sanction structure.

    Prefers the user-supplied numeric `S_normalized` when present;
    otherwise consults `config.sanction_table`. The fallback range is
    `default ± 0.1` clamped to [0, 1].
    """
    if sanction.S_normalized is not None:
        return sanction.S_normalized
    cfg = config or VerifierConfig.paper_defaults()
    default = float(cfg.sanction_table.get(sanction.kind.value, 0.5))
    return NumberRange(min=max(0.0, default - 0.1), max=min(1.0, default + 0.1))


# ---------------------------------------------------------------------------
# φ derivation (FM4 contributor share, role-based)
# ---------------------------------------------------------------------------


def contributor_fraction_from(agent_types: list[AgentType]) -> tuple[float, float]:
    """Compute (lo, hi) for the contributor fraction φ from agent_types.

    Phase 2 uses the explicit `role` enum when set; falls back to the
    legacy keyword-matching heuristic when role is None (back-compat).
    """
    if not agent_types:
        return (0.0, 1.0)

    # Prefer explicit role declarations
    explicit = [ag for ag in agent_types if ag.role is not None]
    if explicit:
        from schema import AgentRole

        contributor_share = sum(
            ag.fraction
            for ag in agent_types
            if ag.role == AgentRole.CONTRIBUTOR
        )
        # Treat declared share as the upper end and 0 as the worst-case
        # lower (declared contributors might disengage).
        return (0.0, max(contributor_share, 0.05))

    # Fall back to keyword matching (legacy)
    keywords = {
        "contributor",
        "provider",
        "merchant",
        "breeder",
        "validator",
        "miner",
        "lp",
        "liquidity",
        "vault",
        "vault_owner",
    }
    total = 0.0
    saw_any = False
    for ag in agent_types:
        tag = (ag.id + " " + (ag.utility_hint or "")).lower()
        if any(k in tag for k in keywords):
            total += ag.fraction
            saw_any = True
    if saw_any:
        return (0.0, max(total, 0.05))
    return (0.0, 1.0)


# ---------------------------------------------------------------------------
# Coherence checks
# ---------------------------------------------------------------------------


def verification_mechanisms_above(
    gamma_star: float,
    config: VerifierConfig | None = None,
) -> list[str]:
    """Return the contribution_verification mechanism names whose γ range
    fully clears `gamma_star`.

    A mechanism's range `[γ_lo, γ_hi]` is "safe" when `γ_lo ≥ γ*`
    (worst-case satisfies the threshold). "Partially safe" when only
    `γ_hi ≥ γ*`. "Unsafe" when even `γ_hi < γ*`.

    Returns formatted strings ready for the `NumericRecommendation`
    `mechanism_mappings` list.
    """
    cfg = config or VerifierConfig.paper_defaults()
    rows: list[tuple[str, list[float]]] = list(cfg.gamma_table.items())
    out: list[str] = []
    for name, (lo, hi) in (
        (k, (float(v[0]), float(v[1]))) for k, v in rows if k != "unspecified"
    ):
        if lo >= gamma_star:
            tag = "safe"
        elif hi >= gamma_star:
            tag = "partially safe"
        else:
            tag = "unsafe"
        out.append(f"{name}: γ ∈ [{lo:.2f}, {hi:.2f}] — {tag}")
    return out


def holding_mechanisms_above(
    tau_threshold: float,
    config: VerifierConfig | None = None,
) -> list[str]:
    """Return the holding_incentive mechanism names whose τ floor clears
    `tau_threshold`.

    A mechanism is "safe" when its τ floor ≥ `tau_threshold`. The
    formatting matches `verification_mechanisms_above`.
    """
    cfg = config or VerifierConfig.paper_defaults()
    out: list[str] = []
    for name, floor in cfg.tau_floor_table.items():
        tag = "safe" if float(floor) >= tau_threshold else "unsafe"
        out.append(f"{name}: τ floor = {float(floor):.1f} periods — {tag}")
    return out


def coherence_violations(te: TokenEconomy) -> list[CoherenceIssue]:
    """Detect cross-field inconsistencies in the user's IR.

    The list of rules below is the Phase 2 set; each rule has a one-line
    justification in `docs/proofs/derivations.md`.
    """
    issues: list[CoherenceIssue] = []
    for token in te.tokens:
        # Rule 1: P2P transfer is incompatible with demand-driven burn
        # (P2P transfer is a balance change, not a redemption event;
        # there's no redemption to fire the burn on.)
        if token.redemption_mechanism == RedemptionMechanism.PEER_TO_PEER_TRANSFER:
            for rule in token.burn_rules:
                if rule.trigger.kind == BurnTriggerKind.DEMAND_DRIVEN:
                    issues.append(
                        CoherenceIssue(
                            severity="error",
                            location=f"tokens[{token.id}].burn_rules + .redemption_mechanism",
                            message=(
                                "Peer-to-peer transfer redemption + "
                                "demand-driven burn is structurally "
                                "incoherent: P2P transfer is a balance "
                                "change, not a redemption event, so "
                                "demand-driven burn has no trigger to fire on."
                            ),
                            suggestion=(
                                "Either change redemption_mechanism to one "
                                "that supports a redemption event "
                                "(specific_goods_or_services, "
                                "fungible_access, time_based_borrowing) or "
                                "use a different burn trigger kind (rule_driven, "
                                "expiry, threshold_driven)."
                            ),
                        )
                    )

        # Rule 2: NFR6 = retain_value + holding_incentives = [none] is
        # internally contradictory.
        if (
            te.meta.nfrs.circulation_speed == CirculationSpeed.RETAIN_VALUE
            and token.holding_incentives
            and all(
                hi == HoldingIncentiveMechanism.NONE for hi in token.holding_incentives
            )
        ):
            issues.append(
                CoherenceIssue(
                    severity="warn",
                    location=f"tokens[{token.id}].holding_incentives + meta.nfrs.circulation_speed",
                    message=(
                        "The system declares NFR6 = retain_value (tokens "
                        "should be held) but the token's holding_incentives "
                        "is [none]. There is no structural incentive to "
                        "hold; the NFR cannot be satisfied."
                    ),
                    suggestion=(
                        "Add at least one holding incentive (governance, "
                        "staking, time-locked rewards, tiered redemption) "
                        "or relax NFR6 to balanced or circulate_fast."
                    ),
                )
            )

        # Rule 3: NFR3 = 5 (high accessibility) + verification =
        # smart_contract_automation is incoherent — cryptographic
        # verification raises the technical bar for non-technical users.
        if (
            te.meta.nfrs.accessibility >= 4
            and token.contribution_verification
            == ContributionVerification.SMART_CONTRACT_AUTOMATION
        ):
            issues.append(
                CoherenceIssue(
                    severity="warn",
                    location=f"tokens[{token.id}].contribution_verification + meta.nfrs.accessibility",
                    message=(
                        "High accessibility NFR (≥ 4) combined with "
                        "smart-contract automation verification: "
                        "cryptographic mechanisms typically raise the "
                        "technical bar for non-technical participants, "
                        "which conflicts with the accessibility goal."
                    ),
                    suggestion=(
                        "Consider physical_presence or peer_verification "
                        "for higher accessibility, or lower NFR3 to "
                        "≤ 3 if smart-contract verification is the "
                        "design intent."
                    ),
                )
            )

    return issues
