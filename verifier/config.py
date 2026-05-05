"""Verifier configuration — every paper-derived numeric value lives here.

Design principle
----------------

No failure-mode module hardcodes numeric thresholds. Every threshold,
every default calibration table, every magic number is a field on
`VerifierConfig` with:

- the paper section / equation it derives from,
- the default value the paper specifies (or our justified calibration
  if the paper is qualitative),
- the justification for that default,
- whether end-users may override it.

The paper is the source of truth for what each threshold *means*. The
default values track the paper as published; users may override per
run when the paper is silent or when their context warrants a different
calibration. This is the bridge between "the published paper is the
authoritative source" and "the verifier remains usable when local
conditions justify a different calibration."

Loading
-------

The dispatcher accepts an optional `config: VerifierConfig | None`. When
None, `VerifierConfig.paper_defaults()` is used. The CLI exposes
`--config path/to/overrides.yaml` to load user overrides from YAML; the
loader validates that every overridden field has `override_allowed=True`.

Citations
---------

Each `ConfigValue` carries `paper_section`, `paper_equation`,
`default_justification`. These propagate to `Verdict.threshold_used` so
the verdict screen can show the user *which* threshold the verdict
depended on and *why* that value was chosen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


T = TypeVar("T", float, int, str, dict)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ConfigValue(_FrozenModel, Generic[T]):
    """A configurable threshold or calibration table with full provenance.

    Attributes
    ----------
    value:
        The numeric (or tabular) value used by the verifier.
    paper_section:
        Section of the paper that introduces or motivates this value.
        Empty string when the value is a calibration not stated in the
        paper (for example, the SanctionKind → S_normalized table).
    paper_equation:
        Equation reference (``"eq. (22)"``) when applicable; empty for
        calibrations.
    default_justification:
        One-paragraph plain-English explanation of why this is the
        default. Used by the verdict screen and `docs/paper-mapping.md`.
    override_allowed:
        Whether end-users may override this in a config YAML. Some
        thresholds (e.g. the boolean violation predicates themselves)
        cannot be overridden because doing so would make the verifier
        unfaithful to the paper.
    """

    value: T
    paper_section: str
    paper_equation: str
    default_justification: str
    override_allowed: bool = True


class VerifierConfig(_FrozenModel):
    """Full numeric configuration of the verifier.

    Defaults come from `paper_defaults()`; users override per run via
    `from_yaml(path)`.
    """

    # ------------------------------------------------------------------
    # FM2 — Velocity trap
    # ------------------------------------------------------------------

    tau_bar_velocity_trap_ceiling: ConfigValue[float] = Field(
        default_factory=lambda: ConfigValue[float](
            value=1.5,
            paper_section="§3.2",
            paper_equation="eq. (12)",
            default_justification=(
                "The paper writes the velocity-trap condition as τ̄ → 1 — "
                "an asymptotic statement. For a discrete design-stage "
                "check we use a conservative ceiling slightly above 1; "
                "1.5 captures systems whose wealth-weighted holding time "
                "is within 50% of the trap regime. Users with stricter "
                "circulation requirements may lower this; users who "
                "explicitly want fast circulation set NFR6 = "
                "circulate_fast (which reclassifies the verdict)."
            ),
            override_allowed=True,
        )
    )

    # ------------------------------------------------------------------
    # FM3 — Burn / emission imbalance
    # ------------------------------------------------------------------

    rho_burn_coverage_floor: ConfigValue[float] = Field(
        default_factory=lambda: ConfigValue[float](
            value=1.0,
            paper_section="§3.3",
            paper_equation="eq. (16)",
            default_justification=(
                "Burn coverage ratio ρ = B/E. ρ ≥ 1 is the steady-state "
                "stability floor under zero population growth. Below 1 "
                "the system has structural inflationary pressure. Users "
                "with explicit positive growth declarations may use a "
                "slightly lower floor; the verifier still flags ρ < 1 "
                "as a risk and explains the growth-dependent margin."
            ),
            override_allowed=True,
        )
    )

    # ------------------------------------------------------------------
    # FM4 — Free-rider collapse
    # ------------------------------------------------------------------

    default_temptation_gap_normalized: ConfigValue[float] = Field(
        default_factory=lambda: ConfigValue[float](
            value=0.5,
            paper_section="§3.4",
            paper_equation="eq. (18)",
            default_justification=(
                "The temptation gap (T − R) appears in the FM4 monitoring "
                "condition γ·S > T − R. The paper does not pin the gap "
                "to a specific value; we use a normalized 0.5 as a "
                "design-stage neutral assumption (defection earns the "
                "same as cooperation plus a half-strength windfall). "
                "Phase 2 of the implementation derives this value from "
                "the verification × redemption mechanism choices, which "
                "is the elicitation-correct way; this default is the "
                "fallback when both are unspecified."
            ),
            override_allowed=True,
        )
    )

    sanction_kind_to_S_normalized: ConfigValue[dict[str, float]] = Field(
        default_factory=lambda: ConfigValue[dict[str, float]](
            value={
                "none": 0.0,
                "warning": 0.1,
                "token_penalty": 0.5,
                "exclusion": 0.9,
                "graduated": 0.7,
                "economic": 0.8,
            },
            paper_section="",
            paper_equation="",
            default_justification=(
                "Calibration table mapping the qualitative SanctionKind "
                "enum to a normalized [0,1] severity used in the FM4 "
                "monitoring condition. The paper is qualitative on "
                "absolute sanction magnitude; these values are calibrated "
                "from Ostrom's design principle 5 (graduated sanctions) "
                "and the docx's qualitative ordering. Phase 2 "
                "introduces structured graduated-sanction escalation "
                "input, at which point this table is used only for "
                "sanction kinds that don't carry numeric details."
            ),
            override_allowed=True,
        )
    )

    # ------------------------------------------------------------------
    # FM6 — Governance capture
    # ------------------------------------------------------------------

    gamma_capture_threshold: ConfigValue[float] = Field(
        default_factory=lambda: ConfigValue[float](
            value=0.5,
            paper_section="§3.6",
            paper_equation="eq. (22)",
            default_justification=(
                "The paper proposes Γ ≤ 0.5 as a minimum condition for "
                "meaningful distributed governance: more than half of "
                "decisions must not be unilateral. This is a definitional "
                "threshold and should normally not be overridden; it is "
                "exposed as configurable because some research uses 0.33 "
                "(supermajority) or other thresholds and the verifier "
                "should be able to operate under those conventions."
            ),
            override_allowed=True,
        )
    )

    gini_secondary_threshold: ConfigValue[float] = Field(
        default_factory=lambda: ConfigValue[float](
            value=0.6,
            paper_section="§3.6",
            paper_equation="",
            default_justification=(
                "Token-balance Gini coefficient is the paper's secondary "
                "FM6 signal — a token-vote DAO with high Gini has "
                "effective single-actor control even when nominal Γ is "
                "low. The paper's discussion is qualitative; 0.6 is our "
                "calibration based on the inflection point in real DAO "
                "data (Convex/Curve, where Gini around 0.85 produced "
                "documented capture). Adjustable for jurisdictions with "
                "different concentration norms."
            ),
            override_allowed=True,
        )
    )

    # ------------------------------------------------------------------
    # Phase 2 — elicitation calibration tables
    # ------------------------------------------------------------------
    #
    # These tables drive the elicitation layer: the user picks a
    # structured option (e.g. `physical_presence`) and the verifier
    # derives the formal parameter (γ, τ floor, T − R) from these
    # tables. Every entry is configurable so users with domain-specific
    # calibrations can override; defaults are paper- or docx-justified
    # in `docs/proofs/derivations.md`.

    contribution_verification_to_gamma: ConfigValue[
        dict[str, list[float]]
    ] = Field(
        default_factory=lambda: ConfigValue[dict[str, list[float]]](
            value={
                # The interval semantic is [min, max] of the γ range
                # implied by each verification mechanism. Empirical
                # justifications are in docs/proofs/derivations.md.
                "physical_presence": [0.85, 0.95],
                "smart_contract_automation": [0.90, 1.00],
                "peer_verification": [0.50, 0.80],
                "third_party_certification": [0.40, 0.70],
                "self_reporting": [0.05, 0.20],
                "unspecified": [0.00, 1.00],
            },
            paper_section="§3.4",
            paper_equation="eq. (18)",
            default_justification=(
                "γ = monitoring capacity in FM4. The Roadmap docx 1.5 "
                "describes each verification mechanism's monitoring strength "
                "qualitatively (\"physical presence — strongest verification, "
                "hardest to fake\"; \"self-reporting — weakest verification, "
                "highest free-rider risk\"). The numerical ranges here "
                "translate those descriptions into γ intervals. The "
                "self_reporting upper bound (0.20) reflects that even "
                "self-report systems catch some defectors via post-hoc audits; "
                "the smart_contract upper bound (1.00) reflects fully "
                "deterministic on-chain checks. Calibration; the paper does "
                "not pin numeric γ ranges."
            ),
            override_allowed=True,
        )
    )

    holding_incentive_to_tau_floor: ConfigValue[dict[str, float]] = Field(
        default_factory=lambda: ConfigValue[dict[str, float]](
            value={
                # Floor on per-agent expected_holding_time (in periods)
                # implied by each holding-incentive mechanism. When an
                # agent type lacks an explicit τ value, the verifier
                # uses the maximum floor across the token's declared
                # holding_incentives as the default τ for that agent.
                "none": 1.0,
                "tiered_redemption": 2.0,
                "governance_rights": 4.0,
                "staking": 4.0,
                "reputation": 2.0,
                "time_locked_rewards": 4.0,
            },
            paper_section="§3.2",
            paper_equation="eq. (12)",
            default_justification=(
                "τ floor = minimum expected_holding_time induced by each "
                "holding-incentive mechanism. The Roadmap docx 1.4 ranks "
                "the mechanisms by their effect on velocity: `none` is the "
                "trap-prone baseline (τ ≈ 1 period); tiered redemption and "
                "reputation create soft pressure (τ ≈ 2); governance, "
                "staking, and time-locked rewards force structural retention "
                "(τ ≈ 4 periods, matching a typical lock period or vesting "
                "schedule). Numeric calibration; the docx is qualitative."
            ),
            override_allowed=True,
        )
    )

    # Map (verification, redemption) → temptation gap T − R.
    # YAML-friendly nested dict: outer key = verification, inner = redemption.
    verification_redemption_to_temptation_gap: ConfigValue[
        dict[str, dict[str, float]]
    ] = Field(
        default_factory=lambda: ConfigValue[dict[str, dict[str, float]]](
            value={
                # Strong verification × structured redemption: small gap
                "physical_presence": {
                    "specific_goods_or_services": 0.10,
                    "time_based_borrowing": 0.10,
                    "fungible_access": 0.20,
                    "open_market_exchange": 0.40,
                    "peer_to_peer_transfer": 0.50,
                    "unspecified": 0.50,
                },
                "smart_contract_automation": {
                    "specific_goods_or_services": 0.05,
                    "time_based_borrowing": 0.05,
                    "fungible_access": 0.10,
                    "open_market_exchange": 0.30,
                    "peer_to_peer_transfer": 0.40,
                    "unspecified": 0.40,
                },
                "peer_verification": {
                    "specific_goods_or_services": 0.30,
                    "time_based_borrowing": 0.30,
                    "fungible_access": 0.40,
                    "open_market_exchange": 0.50,
                    "peer_to_peer_transfer": 0.60,
                    "unspecified": 0.50,
                },
                "third_party_certification": {
                    "specific_goods_or_services": 0.20,
                    "time_based_borrowing": 0.25,
                    "fungible_access": 0.35,
                    "open_market_exchange": 0.45,
                    "peer_to_peer_transfer": 0.55,
                    "unspecified": 0.45,
                },
                "self_reporting": {
                    "specific_goods_or_services": 0.60,
                    "time_based_borrowing": 0.65,
                    "fungible_access": 0.75,
                    "open_market_exchange": 0.85,
                    "peer_to_peer_transfer": 0.95,
                    "unspecified": 0.80,
                },
                "unspecified": {
                    "specific_goods_or_services": 0.50,
                    "time_based_borrowing": 0.50,
                    "fungible_access": 0.50,
                    "open_market_exchange": 0.50,
                    "peer_to_peer_transfer": 0.60,
                    "unspecified": 0.50,
                },
            },
            paper_section="§3.4",
            paper_equation="eq. (18)",
            default_justification=(
                "T − R = temptation gap in FM4. The gap is small when "
                "verification is strong (defection is hard to hide) and "
                "redemption is structured (defection has nowhere to "
                "convert into liquid value); large when verification is "
                "weak and redemption is liquid (open-market or P2P "
                "transfer let defectors cash out). The matrix is "
                "monotone in both axes: stronger verification or more "
                "structured redemption never increases the gap. "
                "Calibration; the paper does not pin numeric values."
            ),
            override_allowed=True,
        )
    )

    # ------------------------------------------------------------------
    # Phase 5 — archetype routing
    # ------------------------------------------------------------------
    archetype_fm_applicability: ConfigValue[dict[str, list[str]]] = Field(
        default_factory=lambda: ConfigValue[dict[str, list[str]]](
            value={
                # Which FMs each archetype skips (returns NOT_APPLICABLE).
                # Defaults are conservative — only skip FMs that are
                # structurally inapplicable, not merely unlikely.
                "native_protocol_asset": [],
                # Stablecoin: FM2 velocity trap is a goal, not a risk.
                # Reweighting is handled by NFR6, not archetype skipping;
                # so the default skip list is empty.
                "stablecoin": [],
                "governance_utility_pair": [],
                "play_to_earn_dual": [],
                # Community-reward systems often have informal off-chain
                # governance — but FM6 still applies. No default skips.
                "community_reward": [],
                "other": [],
            },
            paper_section="",
            paper_equation="",
            default_justification=(
                "Per-archetype FM skip list — calibration that the paper "
                "does not pin. Defaults are empty (every archetype "
                "evaluates every FM) because the paper does not license "
                "blanket archetype-based skipping. Users with "
                "domain-specific knowledge can override per run; for "
                "example, a Bitcoin-style native protocol asset can "
                "skip FM4 because there is no contribution-reward economy."
            ),
            override_allowed=True,
        )
    )

    # ------------------------------------------------------------------
    # Phase 5 — NFR-driven reweighting multipliers (advisory)
    # ------------------------------------------------------------------
    nfr1_resilience_rho_multiplier: ConfigValue[dict[str, float]] = Field(
        default_factory=lambda: ConfigValue[dict[str, float]](
            value={
                "1": 1.0,
                "2": 1.0,
                "3": 1.0,
                "4": 1.05,
                "5": 1.10,
            },
            paper_section="",
            paper_equation="",
            default_justification=(
                "NFR-driven calibration; the paper does not specify "
                "a coupling between non-functional requirements and the "
                "FM thresholds. This multiplier on rho_burn_coverage_floor "
                "by NFR1 resilience rating (1–5) lets high-resilience "
                "designs tighten ρ. Defaults are mild (≤ 10% tightening); "
                "users can override for stricter policy."
            ),
            override_allowed=True,
        )
    )

    nfr5_proportionality_phi_multiplier: ConfigValue[dict[str, float]] = Field(
        default_factory=lambda: ConfigValue[dict[str, float]](
            value={
                "1": 1.0,
                "2": 1.0,
                "3": 1.0,
                "4": 1.10,
                "5": 1.20,
            },
            paper_section="",
            paper_equation="",
            default_justification=(
                "NFR-driven calibration; the paper does not specify "
                "a coupling between non-functional requirements and the "
                "FM thresholds. Multiplier on the FM4 contributor-rate "
                "condition φ ≥ d/K as a function of NFR5 proportionality "
                "rating (1–5). Defaults are mild (≤ 20% tightening)."
            ),
            override_allowed=True,
        )
    )

    # ------------------------------------------------------------------
    # Numerical tolerances
    # ------------------------------------------------------------------

    numeric_epsilon: ConfigValue[float] = Field(
        default_factory=lambda: ConfigValue[float](
            value=1e-9,
            paper_section="",
            paper_equation="",
            default_justification=(
                "Z3 reasons over rationals; small slack guards against "
                "boundary degeneracy when the user enters point-value "
                "ranges. This is a numerical-method constant, not a "
                "modeling choice."
            ),
            override_allowed=False,
        )
    )

    # ==================================================================
    # Constructors
    # ==================================================================

    @classmethod
    def paper_defaults(cls) -> "VerifierConfig":
        """Return the default config — values as the paper specifies them."""
        return cls()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "VerifierConfig":
        """Load a config from a YAML file containing user overrides.

        The YAML format is a flat mapping of field name → new value. Only
        fields whose `override_allowed=True` may be overridden; attempting
        to override an `override_allowed=False` field raises ValueError.

        Example YAML:

            tau_bar_velocity_trap_ceiling: 1.2
            gamma_capture_threshold: 0.33
            sanction_kind_to_S_normalized:
              none: 0.0
              warning: 0.05
              token_penalty: 0.4
              exclusion: 1.0
              graduated: 0.65
              economic: 0.75
        """
        p = Path(path)
        with p.open("r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}
        return cls.with_overrides(raw)

    @classmethod
    def with_overrides(cls, overrides: dict[str, Any]) -> "VerifierConfig":
        """Apply a dict of overrides to the paper defaults.

        Validates that every key is a known field and that every field
        permits override.
        """
        defaults = cls.paper_defaults()
        new_fields: dict[str, ConfigValue[Any]] = {}
        for key, new_value in overrides.items():
            if not hasattr(defaults, key):
                raise ValueError(
                    f"Unknown config key '{key}'. "
                    f"Valid keys: {sorted(cls.model_fields.keys())}"
                )
            current: ConfigValue[Any] = getattr(defaults, key)
            if not current.override_allowed:
                raise ValueError(
                    f"Config key '{key}' does not allow override "
                    f"(override_allowed=False). "
                    f"Default justification: {current.default_justification}"
                )
            new_fields[key] = ConfigValue(
                value=new_value,
                paper_section=current.paper_section,
                paper_equation=current.paper_equation,
                default_justification=(
                    f"{current.default_justification} "
                    f"[USER OVERRIDE: {current.value} → {new_value}]"
                ),
                override_allowed=True,
            )
        return defaults.model_copy(update=new_fields)

    # ==================================================================
    # Convenience property accessors
    # ==================================================================
    #
    # These give the FM modules ergonomic access to the raw values
    # without having to write `config.tau_bar_velocity_trap_ceiling.value`
    # everywhere. The full ConfigValue is still available as a fallback
    # for verdict provenance.

    @property
    def tau_bar_ceiling(self) -> float:
        return self.tau_bar_velocity_trap_ceiling.value

    @property
    def rho_floor(self) -> float:
        return self.rho_burn_coverage_floor.value

    @property
    def temptation_gap_default(self) -> float:
        return self.default_temptation_gap_normalized.value

    @property
    def sanction_table(self) -> dict[str, float]:
        return self.sanction_kind_to_S_normalized.value

    @property
    def gamma_threshold(self) -> float:
        return self.gamma_capture_threshold.value

    @property
    def gini_threshold(self) -> float:
        return self.gini_secondary_threshold.value

    @property
    def epsilon(self) -> float:
        return self.numeric_epsilon.value

    @property
    def gamma_table(self) -> dict[str, list[float]]:
        return self.contribution_verification_to_gamma.value

    @property
    def tau_floor_table(self) -> dict[str, float]:
        return self.holding_incentive_to_tau_floor.value

    @property
    def temptation_gap_table(self) -> dict[str, dict[str, float]]:
        return self.verification_redemption_to_temptation_gap.value

    @property
    def archetype_skip_table(self) -> dict[str, list[str]]:
        return self.archetype_fm_applicability.value

    @property
    def nfr1_rho_multiplier_table(self) -> dict[str, float]:
        return self.nfr1_resilience_rho_multiplier.value

    @property
    def nfr5_phi_multiplier_table(self) -> dict[str, float]:
        return self.nfr5_proportionality_phi_multiplier.value

    # ==================================================================
    # Audit
    # ==================================================================

    def all_paper_citations(self) -> list[tuple[str, str, str, Any]]:
        """Return a list of (key, paper_section, paper_equation, value) tuples.

        Used by `docs/paper-mapping.md` consistency checks: every paper
        citation in the doc must correspond to a row in this list.
        """
        out: list[tuple[str, str, str, Any]] = []
        for key in type(self).model_fields:
            cv: ConfigValue[Any] = getattr(self, key)
            out.append((key, cv.paper_section, cv.paper_equation, cv.value))
        return out
