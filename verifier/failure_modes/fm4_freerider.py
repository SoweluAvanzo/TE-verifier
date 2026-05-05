"""FM4 — Free-rider and contribution collapse.

Paper §3.4, eqs. (17)–(18):

    Minimum viable contributor rate (Ostrom proportionality):
        φ ≥ d / K

    Monitoring/sanction stability (Li et al.):
        γ · S > T − R

This failure mode applies only to systems with a contribution-reward
economy — i.e. tokens earned through resource contribution or behavioral
events, redeemed against a finite catalogue of offers (offer variety K).
Pure financial / store-of-value systems do not have a φ to collapse.

Tier-1 implementation: derive K from the per-token offer_variety_K
(summed across tokens that have it), pull d and γ from the IR, plug
into Z3 over their declared ranges, and ask whether the inequalities
fail.
"""

from __future__ import annotations

import z3

from schema import (
    EmissionTriggerKind,
    SanctionKind,
    TokenEconomy,
    TokenFunction,
)
from verifier import elicitation
from verifier.config import VerifierConfig
from verifier.constants import (
    DEFAULT_TEMPTATION_GAP_NORMALIZED,
    SANCTION_KIND_TO_S_NORMALIZED,
)
from verifier.failure_modes.base import (
    Counterexample,
    CriticalValue,
    FailureMode,
    NumericRecommendation,
    Status,
    Verdict,
    z3_value_to_float,
)


# Token earning mechanisms (encoded via emission trigger kinds) that imply
# a contribution-reward economy where FM4 applies.
CONTRIBUTION_TRIGGER_KINDS: frozenset[EmissionTriggerKind] = frozenset(
    {
        EmissionTriggerKind.BEHAVIORAL_EVENT,
        EmissionTriggerKind.PHYSICAL_RESOURCE_FLOW,
    }
)


class FM4FreeRider(FailureMode):
    name = "FM4: Free-Rider Collapse"
    description = (
        "Active contributor rate φ falls below the demand-vs-offer ratio d/K, "
        "or monitoring × sanction is too weak to deter defection."
    )

    def check(
        self, te: TokenEconomy, config: VerifierConfig | None = None
    ) -> list[Verdict]:
        # FM4 is a system-level check, not per-token.
        cfg = config or VerifierConfig.paper_defaults()
        return [self._check_system(te, cfg)]

    def _check_system(self, te: TokenEconomy, config: VerifierConfig) -> Verdict:
        # Determine applicability: at least one token must earn its supply
        # through contribution-style behavior (behavioral or physical flow).
        applicable = self._is_applicable(te)
        if not applicable:
            return Verdict(
                failure_mode=self.name,
                subject="system",
                status=Status.NOT_APPLICABLE,
                formal_condition="N/A (no contribution-reward economy)",
                explanation=(
                    "No token in this TE earns supply through behavioral "
                    "events or physical resource contribution; FM4 (free-rider "
                    "collapse) does not apply."
                ),
            )

        # Aggregate offer variety K across tokens that declare it.
        K_lo, K_hi = self._aggregate_offer_variety(te)
        if K_lo is None:
            return Verdict(
                failure_mode=self.name,
                subject="system",
                status=Status.INCONCLUSIVE,
                formal_condition="φ ≥ d/K   (K unknown)",
                explanation=(
                    "Cannot evaluate FM4 without offer variety K. Set "
                    "offer_variety_K on at least one token."
                ),
            )

        d_lo, d_hi = (
            te.participants.average_demand_d.min,
            te.participants.average_demand_d.max,
        )

        # Phase 2 — γ is derived from contribution_verification when set
        # on any token; otherwise fall back to the user-supplied range.
        gamma_lo, gamma_hi, gamma_source = self._derive_gamma_range(te)

        # Phase 2 — S derived via the elicitation layer (which still
        # honors user-supplied S_normalized when present).
        s_range = elicitation.s_normalized_from(te.governance.sanction_structure)
        s_lo, s_hi = s_range.min, s_range.max

        # Phase 2 — T − R derived from (verification, redemption) when
        # both set on any token; otherwise config default.
        T_minus_R_normalized, tr_source = self._derive_temptation_gap(te)

        solver = self.make_solver()
        K = z3.Real("K")
        d = z3.Real("d")
        gamma = z3.Real("gamma")
        S = z3.Real("S")
        phi = z3.Real("phi")
        solver.add(K >= K_lo, K <= K_hi, K > 0)
        solver.add(d >= d_lo, d <= d_hi, d >= 0)
        solver.add(gamma >= gamma_lo, gamma <= gamma_hi, gamma >= 0, gamma <= 1)
        solver.add(S >= s_lo, S <= s_hi, S >= 0, S <= 1)
        # Phase 2 — φ derived from explicit agent role declarations,
        # falling back to the legacy keyword heuristic when role unset.
        phi_min, phi_max = elicitation.contributor_fraction_from(
            te.participants.agent_types
        )
        solver.add(phi >= phi_min, phi <= phi_max)

        # Phase 5d: NFR5 (proportionality) tightens the contributor-rate
        # condition. Multiplier ≥ 1 means demand effectively grows for the
        # purpose of the sustainability check.
        nfr5_mult = float(
            config.nfr5_phi_multiplier_table.get(
                str(te.meta.nfrs.proportionality), 1.0
            )
        )

        # Violation of FM4: contributor-rate AND monitoring conditions.
        # We flag violation if EITHER part fails:
        #   φ · K < d · nfr5_mult   OR   γS ≤ (T − R)
        cond_phi = phi * K < d * nfr5_mult
        cond_monitor = gamma * S <= T_minus_R_normalized
        solver.add(z3.Or(cond_phi, cond_monitor))

        # ------------------------------------------------------------------
        # Critical values — closed-form by monotonicity / direct inversion.
        # ------------------------------------------------------------------
        # γ* = (T − R) / S, worst-case across S range. (T − R) is a fixed
        # default in Phase 1; Phase 2 derives it from elicitation.
        critical_values: list[CriticalValue] = []
        gamma_star: float | None = None
        if s_lo > 0:
            gamma_star = T_minus_R_normalized / s_lo  # worst-case = use min S
            critical_values.append(
                CriticalValue(
                    parameter="gamma",
                    value=gamma_star,
                    direction=">=",
                    formula=f"γ* = (T − R) / S = {T_minus_R_normalized:g} / {s_lo:g}",
                    explanation=(
                        f"The minimum monitoring capacity at which the "
                        f"expected cost of cheating (γ·S) exceeds the gross "
                        f"gain (T − R). Below γ* = {gamma_star:.3f}, no "
                        f"realistic sanction will deter free-riding given "
                        f"this sanction magnitude."
                    ),
                    source="closed_form",
                )
            )
        # K* = d / φ, worst-case = max(d) / min(phi) (when phi > 0)
        k_star: float | None = None
        if phi_min > 0:
            k_star = d_hi / phi_min
            critical_values.append(
                CriticalValue(
                    parameter="K",
                    value=k_star,
                    direction=">=",
                    formula=f"K* = d / φ = {d_hi:g} / {phi_min:g}",
                    explanation=(
                        f"The minimum offer variety K such that φ ≥ d/K "
                        f"holds across the declared d range, given the "
                        f"declared minimum contributor share φ_min = "
                        f"{phi_min:.2f}."
                    ),
                    source="closed_form",
                )
            )
        # φ* = d / K, worst-case = max(d) / min(K)
        phi_star: float | None = None
        if K_lo > 0:
            phi_star = d_hi / K_lo
            critical_values.append(
                CriticalValue(
                    parameter="phi",
                    value=phi_star,
                    direction=">=",
                    formula=f"φ* = d / K = {d_hi:g} / {K_lo:g}",
                    explanation=(
                        f"The minimum contributor fraction needed to "
                        f"satisfy demand at the worst-case d and K. If "
                        f"declared agent-type fractions place φ below "
                        f"{phi_star:.3f}, the system structurally lacks "
                        f"contributors."
                    ),
                    source="closed_form",
                )
            )

        # Swept/committed marking
        swept_fields, committed_fields = self._mark_fields(te)

        result = solver.check()
        if result == z3.sat:
            model = solver.model()
            ce = self._build_counterexample(
                model, K, d, gamma, S, phi, T_minus_R_normalized
            )
            recommendation = self._build_recommendation(
                ce=ce,
                gamma_star=gamma_star,
                k_star=k_star,
                phi_star=phi_star,
                gamma_range=(gamma_lo, gamma_hi),
                K_range=(K_lo, K_hi),
            )
            return Verdict(
                failure_mode=self.name,
                subject="system",
                status=Status.FAIL,
                formal_condition="φ ≥ d/K   AND   γ·S > T − R",
                explanation=(
                    "There exist parameter values within the declared ranges "
                    "under which either the active contributor rate is "
                    "insufficient to satisfy demand (φ < d/K) or monitoring × "
                    "sanction fails to deter defection (γS ≤ T − R)."
                ),
                counterexample=ce,
                suggestions=self._suggestions(),
                critical_values=critical_values,
                recommendation=recommendation,
                swept_fields=swept_fields,
                committed_fields=committed_fields,
            )

        return Verdict(
            failure_mode=self.name,
            subject="system",
            status=Status.PASS,
            formal_condition="φ ≥ d/K   AND   γ·S > T − R   (for all in range)",
            explanation=(
                "Both Ostrom proportionality (φ ≥ d/K) and the monitoring "
                "condition (γS > T − R) hold across the declared parameter ranges."
            ),
            critical_values=critical_values,
            swept_fields=swept_fields,
            committed_fields=committed_fields,
        )

    @staticmethod
    def _mark_fields(te: TokenEconomy) -> tuple[list[str], list[str]]:
        """Mark which FM4 inputs are point-committed vs range-swept."""
        swept: list[str] = []
        committed: list[str] = []
        for label, rng in (
            ("participants.average_demand_d", te.participants.average_demand_d),
            ("governance.monitoring_capacity_gamma", te.governance.monitoring_capacity_gamma),
        ):
            if rng.is_point:
                committed.append(label)
            else:
                swept.append(label)
        if te.governance.sanction_structure.S_normalized is not None:
            label = "governance.sanction_structure.S_normalized"
            if te.governance.sanction_structure.S_normalized.is_point:
                committed.append(label)
            else:
                swept.append(label)
        else:
            swept.append("governance.sanction_structure (derived from kind)")
        # Aggregate K
        for tok in te.tokens:
            if tok.offer_variety_K is not None:
                label = f"tokens[{tok.id}].offer_variety_K"
                if tok.offer_variety_K.is_point:
                    committed.append(label)
                else:
                    swept.append(label)
        if not te.participants.agent_types:
            swept.append("participants.agent_types (φ search)")
        else:
            committed.append("participants.agent_types")
        return swept, committed

    @staticmethod
    def _build_recommendation(
        *,
        ce: Counterexample,
        gamma_star: float | None,
        k_star: float | None,
        phi_star: float | None,
        gamma_range: tuple[float, float],
        K_range: tuple[float, float],
    ) -> NumericRecommendation | None:
        """Pick the recommendation from the binding constraint.

        If the monitoring clause is binding, recommend γ* (typically
        achieved via stronger contribution_verification — Phase 2 fills
        in the mechanism mappings). If Ostrom is binding, recommend K*
        (raising offer variety is usually easier than reweighting the
        agent-type composition).
        """
        binding = ce.binding_constraint
        if "monitoring" in binding and gamma_star is not None:
            return NumericRecommendation(
                parameter="gamma",
                current_range=gamma_range,
                safe_threshold=gamma_star,
                direction=">=",
                narrative=(
                    f"Raise monitoring capacity γ to at least "
                    f"{gamma_star:.3f}. Choose a contribution-verification "
                    f"mechanism whose γ range clears this threshold."
                ),
                mechanism_mappings=elicitation.verification_mechanisms_above(
                    gamma_star
                ),
            )
        if "contribution" in binding and k_star is not None:
            return NumericRecommendation(
                parameter="K",
                current_range=K_range,
                safe_threshold=k_star,
                direction=">=",
                narrative=(
                    f"Increase offer variety K to at least {k_star:.2f} so "
                    f"that φ ≥ d/K holds across the declared d range."
                ),
            )
        # Fallback: prefer γ recommendation if available
        if gamma_star is not None:
            return NumericRecommendation(
                parameter="gamma",
                current_range=gamma_range,
                safe_threshold=gamma_star,
                direction=">=",
                narrative=(
                    f"Raise monitoring capacity γ to at least "
                    f"{gamma_star:.3f}."
                ),
                mechanism_mappings=elicitation.verification_mechanisms_above(
                    gamma_star
                ),
            )
        return None

    @staticmethod
    def _derive_gamma_range(te: TokenEconomy) -> tuple[float, float, str]:
        """Choose γ range from the strongest signal available.

        Priority:
        1. If any token has `contribution_verification` set (and it isn't
           UNSPECIFIED), derive γ from the elicitation table. When
           multiple tokens disagree, take the union (worst-case sweep).
        2. Else fall back to the user-supplied
           `governance.monitoring_capacity_gamma`.

        Returns (lo, hi, source-description).
        """
        from schema import ContributionVerification

        derived_ranges: list[tuple[float, float]] = []
        for token in te.tokens:
            cv = token.contribution_verification
            if cv is None or cv == ContributionVerification.UNSPECIFIED:
                continue
            r = elicitation.gamma_range_from(cv)
            if r is not None:
                derived_ranges.append((r.min, r.max))
        if derived_ranges:
            lo = min(r[0] for r in derived_ranges)
            hi = max(r[1] for r in derived_ranges)
            return lo, hi, "derived from contribution_verification"
        # Fall back to user-supplied
        g = te.governance.monitoring_capacity_gamma
        return g.min, g.max, "user-supplied governance.monitoring_capacity_gamma"

    @staticmethod
    def _derive_temptation_gap(te: TokenEconomy) -> tuple[float, str]:
        """Derive (T − R) from (verification, redemption) when both set.

        When multiple tokens declare different (verification, redemption)
        pairs, take the **largest** derived gap (worst case).
        """
        gaps: list[float] = []
        for token in te.tokens:
            v = token.contribution_verification
            r = token.redemption_mechanism
            gap = elicitation.temptation_gap_from(v, r)
            if gap is not None:
                gaps.append(gap)
        if gaps:
            return max(gaps), "derived from (verification, redemption)"
        return DEFAULT_TEMPTATION_GAP_NORMALIZED, "config default"

    @staticmethod
    def _is_applicable(te: TokenEconomy) -> bool:
        for token in te.tokens:
            for rule in token.emission_rules:
                if rule.trigger.kind in CONTRIBUTION_TRIGGER_KINDS:
                    # Also require at least one token whose function set
                    # implies redemption (medium_of_exchange or access_right).
                    if any(
                        f
                        in {TokenFunction.MEDIUM_OF_EXCHANGE, TokenFunction.ACCESS_RIGHT}
                        for f in token.function
                    ):
                        return True
        return False

    @staticmethod
    def _aggregate_offer_variety(te: TokenEconomy) -> tuple[float | None, float | None]:
        lo, hi = None, None
        for token in te.tokens:
            if token.offer_variety_K is not None:
                k_lo = token.offer_variety_K.min
                k_hi = token.offer_variety_K.max
                lo = k_lo if lo is None else min(lo, k_lo)
                hi = k_hi if hi is None else max(hi, k_hi)
        return lo, hi

    @staticmethod
    def _sanction_normalized_range(te: TokenEconomy) -> tuple[float, float]:
        # Phase 2 — delegated to the elicitation layer which honors
        # user-supplied numeric S_normalized when present and falls back
        # to the configurable sanction-kind table otherwise.
        r = elicitation.s_normalized_from(te.governance.sanction_structure)
        return r.min, r.max

    @staticmethod
    def _build_counterexample(
        model: z3.ModelRef,
        K: z3.ArithRef,
        d: z3.ArithRef,
        gamma: z3.ArithRef,
        S: z3.ArithRef,
        phi: z3.ArithRef,
        TR: float,
    ) -> Counterexample:
        Kv = z3_value_to_float(model, K)
        dv = z3_value_to_float(model, d)
        gv = z3_value_to_float(model, gamma)
        Sv = z3_value_to_float(model, S)
        pv = z3_value_to_float(model, phi)
        params = {
            "K": Kv,
            "d": dv,
            "gamma": gv,
            "S_normalized": Sv,
            "phi": pv,
            "T_minus_R_normalized": TR,
            "phi_K": pv * Kv,
            "gamma_S": gv * Sv,
        }
        contrib_failed = (pv * Kv) < dv
        monitor_failed = (gv * Sv) <= TR
        parts = []
        if contrib_failed:
            parts.append(
                f"φ·K = {pv * Kv:.3f} < d = {dv:.3f} (contribution insufficient)"
            )
        if monitor_failed:
            parts.append(
                f"γ·S = {gv * Sv:.3f} ≤ T−R = {TR:.3f} (monitoring too weak)"
            )
        narrative = "Free-rider risk concrete: " + "; ".join(parts) + "."
        binding = ""
        if contrib_failed and monitor_failed:
            binding = "both clauses (contribution and monitoring) failing"
        elif contrib_failed:
            binding = "contribution clause (φ < d/K) is binding"
        elif monitor_failed:
            binding = "monitoring clause (γS ≤ T − R) is binding"
        return Counterexample(
            parameter_values=params,
            narrative=narrative,
            binding_constraint=binding,
        )

    @staticmethod
    def _suggestions() -> list[str]:
        return [
            "Increase offer variety K to lower the d/K threshold.",
            "Add or strengthen contribution-verification mechanisms to keep "
            "φ above d/K.",
            "Raise monitoring capacity γ (more transparency, on-chain proofs) "
            "or sanction magnitude S (graduated penalties, exclusion).",
        ]
