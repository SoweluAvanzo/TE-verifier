"""FM5 — Insufficient critical mass.

Paper §3.5, eqs. (19)–(21):

    Expected matches per period (well-mixed, double coincidence of wants):
        E[matches] = N(N-1) / (2K)
    Critical mass threshold (above which liquid exchange is sustainable):
        N(N-1) / (2K) ≥ d · N
    Equivalently:
        N ≥ 2 · K · d + 1

For spatially structured topologies, this is a *conservative upper bound*
on critical mass risk — local reciprocity may sustain exchange below it.
The verifier reports this caveat in its explanation.
"""

from __future__ import annotations

import z3

from schema import NumberRange, TokenEconomy, Topology
from verifier.failure_modes.base import (
    Counterexample,
    CriticalValue,
    FailureMode,
    NumericRecommendation,
    Status,
    Verdict,
    optimize_threshold,
    z3_value_to_float,
)


class FM5CriticalMass(FailureMode):
    name = "FM5: Insufficient Critical Mass"
    description = (
        "Below a minimum participant count, exchange opportunities are too "
        "sparse to sustain liquid token usage."
    )

    def check(self, te: TokenEconomy, config=None) -> list[Verdict]:
        return [self._check_system(te)]

    def _check_system(self, te: TokenEconomy) -> Verdict:
        N_range = te.participants.count_N
        d_range = te.participants.average_demand_d
        N_lo, N_hi = N_range.min, N_range.max
        d_lo, d_hi = d_range.min, d_range.max
        K_lo, K_hi = self._aggregate_offer_variety(te)
        if K_lo is None:
            return Verdict(
                failure_mode=self.name,
                subject="system",
                status=Status.INCONCLUSIVE,
                formal_condition="N ≥ 2Kd + 1   (K unknown)",
                explanation=(
                    "Cannot evaluate FM5 without offer variety K. Set "
                    "offer_variety_K on at least one token."
                ),
                swept_fields=["tokens[].offer_variety_K"],
            )
        K_range = NumberRange(min=K_lo, max=K_hi)

        # ------------------------------------------------------------------
        # Critical values — closed-form by monotonicity.
        # ------------------------------------------------------------------
        # The function f(K, d) = 2·K·d + 1 is monotone increasing in both K
        # and d on K, d ≥ 0. The worst-case sustainability threshold over
        # the declared box [K_lo, K_hi] × [d_lo, d_hi] is therefore reached
        # at the corner (K_hi, d_hi). See docs/proofs/fm5.md for the proof.
        n_star = 2 * K_hi * d_hi + 1
        # K* = (N − 1)/(2·d). The strictest upper bound on K corresponds to
        # the smallest sustainable N and the largest plausible d. When d_hi
        # = 0, K is structurally unconstrained (no demand).
        k_star: float | None = None
        if d_hi > 0 and N_lo >= 1:
            k_star = max(0.0, (N_lo - 1) / (2 * d_hi))

        critical_values: list[CriticalValue] = [
            CriticalValue(
                parameter="N",
                value=n_star,
                direction=">=",
                formula="N* = 2·K·d + 1   (worst-case over declared K, d ranges)",
                explanation=(
                    f"Minimum participant count for which the well-mixed "
                    f"critical-mass condition holds across all declared "
                    f"K and d. With K up to {K_hi:g} and d up to {d_hi:g}, "
                    f"the system needs at least {n_star:.0f} participants."
                ),
                source="closed_form",
            )
        ]
        if k_star is not None:
            critical_values.append(
                CriticalValue(
                    parameter="K",
                    value=k_star,
                    direction="<=",
                    formula="K* = (N − 1) / (2·d)   (worst-case over declared N, d ranges)",
                    explanation=(
                        f"Maximum offer variety the declared participant range "
                        f"can sustain. Above {k_star:.2f}, demand thins below "
                        f"the matching probability needed for liquid exchange."
                    ),
                    source="closed_form",
                )
            )

        # Swept/committed marking — a field is committed when the user
        # supplied a point value (min == max); a range counts as swept.
        swept, committed = self._mark_fields(te, N_range, K_range, d_range)

        # ------------------------------------------------------------------
        # Existential check (does any assignment violate?)
        # ------------------------------------------------------------------
        solver = self.make_solver()
        N_var = z3.Real("N")
        K_var = z3.Real("K")
        d_var = z3.Real("d")
        solver.add(N_var >= N_lo, N_var <= N_hi, N_var >= 1)
        solver.add(K_var >= K_lo, K_var <= K_hi, K_var >= 1)
        solver.add(d_var >= d_lo, d_var <= d_hi, d_var >= 0)
        solver.add(N_var < 2 * K_var * d_var + 1)

        is_well_mixed = te.participants.topology == Topology.WELL_MIXED

        # Phase 5c: degree-corrected critical-mass condition for networks.
        # When the user supplies `average_degree`, the per-participant
        # reachable population is the degree, not N − 1. The condition
        # becomes `average_degree ≥ 2·K·d` (independent of N).
        # See docs/proofs/topology.md.
        avg_deg_range = te.participants.topology_params.get("average_degree")
        if (
            te.participants.topology == Topology.NETWORK
            and avg_deg_range is not None
        ):
            deg_star = 2 * K_hi * d_hi
            critical_values.append(
                CriticalValue(
                    parameter="average_degree",
                    value=deg_star,
                    direction=">=",
                    formula=(
                        f"avg_degree* = 2·K·d "
                        f"= 2·{K_hi:g}·{d_hi:g} = {deg_star:g}   "
                        f"(network-topology-corrected condition)"
                    ),
                    explanation=(
                        f"For a network topology, the condition reduces to "
                        f"avg_degree ≥ 2·K·d (independent of N). With the "
                        f"declared K and d ranges, every participant must "
                        f"reach at least {deg_star:g} neighbours."
                    ),
                    source="closed_form",
                )
            )
            # If avg_degree.min ≥ deg_star, FM5 passes by the network rule
            # regardless of the well-mixed Z3 outcome.
            if avg_deg_range.min >= deg_star:
                return Verdict(
                    failure_mode=self.name,
                    subject="system",
                    status=Status.PASS,
                    formal_condition=(
                        f"average_degree ≥ 2·K·d   (network topology, "
                        f"degree-corrected)"
                    ),
                    explanation=(
                        f"Network topology: average degree "
                        f"{avg_deg_range.min:g} clears the network-corrected "
                        f"threshold {deg_star:g} = 2·K·d. The well-mixed "
                        f"bound is not the binding constraint here."
                    ),
                    critical_values=critical_values,
                    swept_fields=swept,
                    committed_fields=committed,
                )

        result = solver.check()
        if result == z3.sat:
            model = solver.model()
            ce = self._build_counterexample(model, N_var, K_var, d_var, is_well_mixed)
            recommendation = self._build_recommendation(
                n_star=n_star, k_star=k_star, N_range=N_range, K_range=K_range
            )
            if not is_well_mixed:
                return Verdict(
                    failure_mode=self.name,
                    subject="system",
                    status=Status.INCONCLUSIVE,
                    formal_condition="N ≥ 2Kd + 1   (well-mixed upper bound)",
                    explanation=(
                        f"For some parameter assignments in the declared ranges, "
                        f"N falls below the well-mixed critical-mass threshold "
                        f"2Kd + 1. Topology is {te.participants.topology.value}, "
                        f"so local reciprocity may sustain exchange below this "
                        f"threshold; the well-mixed bound is conservative. "
                        f"Verify empirically or via simulation."
                    ),
                    counterexample=ce,
                    critical_values=critical_values,
                    recommendation=recommendation,
                    swept_fields=swept,
                    committed_fields=committed,
                )
            return Verdict(
                failure_mode=self.name,
                subject="system",
                status=Status.FAIL,
                formal_condition="N ≥ 2Kd + 1",
                explanation=(
                    "There exist parameter values within the declared ranges "
                    "under which N falls below the critical-mass threshold "
                    "2Kd + 1. Match probability is too low to sustain liquid "
                    "exchange in a well-mixed population."
                ),
                counterexample=ce,
                suggestions=self._suggestions(),
                critical_values=critical_values,
                recommendation=recommendation,
                swept_fields=swept,
                committed_fields=committed,
            )

        return Verdict(
            failure_mode=self.name,
            subject="system",
            status=Status.PASS,
            formal_condition="N ≥ 2Kd + 1   (for all in range)",
            explanation=(
                "Participant count exceeds the critical-mass threshold "
                "across the full parameter space."
            ),
            critical_values=critical_values,
            swept_fields=swept,
            committed_fields=committed,
        )

    @staticmethod
    def _mark_fields(
        te: TokenEconomy,
        N_range: NumberRange,
        K_range: NumberRange,
        d_range: NumberRange,
    ) -> tuple[list[str], list[str]]:
        """Classify the FM5 input fields as swept (range) or committed (point).

        A NumberRange where min == max is committed: the user supplied a
        precise value. A range is swept: the verifier searches across it.
        Used by the verdict screen to tell the user *why* a counterexample
        landed where it did.
        """
        swept: list[str] = []
        committed: list[str] = []
        for label, rng in (
            ("participants.count_N", N_range),
            ("tokens[].offer_variety_K", K_range),
            ("participants.average_demand_d", d_range),
        ):
            if rng.is_point:
                committed.append(label)
            else:
                swept.append(label)
        return swept, committed

    @staticmethod
    def _build_recommendation(
        *,
        n_star: float | None,
        k_star: float | None,
        N_range: NumberRange,
        K_range: NumberRange,
    ) -> NumericRecommendation | None:
        """Pick the most actionable redesign instruction for FM5.

        Prefer N* when N is the binding constraint (current N below N*);
        otherwise recommend K* (lower offer variety).
        """
        if n_star is not None and N_range.min < n_star:
            return NumericRecommendation(
                parameter="N",
                current_range=(N_range.min, N_range.max),
                safe_threshold=n_star,
                direction=">=",
                narrative=(
                    f"Grow the participant base to at least {n_star:.0f} "
                    f"before launch. Current declared range starts at "
                    f"{N_range.min:.0f}, which leaves room for the "
                    f"well-mixed critical-mass condition to fail."
                ),
            )
        if k_star is not None and K_range.max > k_star:
            return NumericRecommendation(
                parameter="K",
                current_range=(K_range.min, K_range.max),
                safe_threshold=k_star,
                direction="<=",
                narrative=(
                    f"Reduce offer variety to at most {k_star:.2f} so the "
                    f"declared participant base supports the matching "
                    f"probability needed for liquid exchange."
                ),
            )
        return None

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
    def _build_counterexample(
        model: z3.ModelRef,
        N: z3.ArithRef,
        K: z3.ArithRef,
        d: z3.ArithRef,
        is_well_mixed: bool,
    ) -> Counterexample:
        Nv = z3_value_to_float(model, N)
        Kv = z3_value_to_float(model, K)
        dv = z3_value_to_float(model, d)
        threshold = 2 * Kv * dv + 1
        narrative = (
            f"At N = {Nv:.0f}, K = {Kv:.2f}, d = {dv:.2f}, the critical-mass "
            f"threshold 2Kd+1 = {threshold:.0f} is not met."
            + (
                " (Note: topology is not well-mixed; this is a conservative "
                "upper bound and local reciprocity may compensate.)"
                if not is_well_mixed
                else ""
            )
        )
        return Counterexample(
            parameter_values={"N": Nv, "K": Kv, "d": dv, "threshold": threshold},
            narrative=narrative,
        )

    @staticmethod
    def _suggestions() -> list[str]:
        return [
            "Lower offer variety K (concentrate demand on fewer offer types).",
            "Lower average demand d per participant.",
            "Grow participant count N above 2Kd + 1 before launch.",
            "Adopt a spatially structured topology to leverage local "
            "reciprocity if the well-mixed bound is hard to meet.",
        ]
