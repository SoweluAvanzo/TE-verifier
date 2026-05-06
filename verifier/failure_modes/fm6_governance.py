"""FM6 — Governance capture.

Paper §3.6, eq. (22):

    Γ = |unilateral_decisions| / |total_decisions|

    A system with Γ = 1 is fully centralized; Γ = 0 requires full consensus.
    The paper proposes Γ ≤ 0.5 as a minimum condition for meaningful
    distributed governance.

Secondary signal: token balance Gini coefficient G. A high G in a
token-vote DAO (Curve / Convex pattern) creates effective single-actor
control even when the nominal Γ is low.

NFR7 reweighting (governance_maturity = INDEFINITE): a centralized
governance design that *declares* it does not aim to decentralize is
internally consistent and reported as PASS_AS_INTENDED instead of FAIL.
"""

from __future__ import annotations

import math

from schema import (
    ControllingActor,
    GovernanceMaturity,
    GovernanceType,
    TokenEconomy,
)
from verifier.constants import GAMMA_CAPTURE_THRESHOLD, GINI_SECONDARY_THRESHOLD
from verifier.failure_modes.base import (
    Counterexample,
    CriticalValue,
    FailureMode,
    NumericRecommendation,
    Status,
    Verdict,
)


# Controlling actors that constitute a "unilateral" decision in the Γ
# computation. The paper's §3.6 definition is "decisions that can be taken
# unilaterally by a single actor or small group."
UNILATERAL_ACTORS: frozenset[ControllingActor] = frozenset(
    {ControllingActor.SINGLE_ENTITY, ControllingActor.COMMITTEE}
)


class FM6GovernanceCapture(FailureMode):
    name = "FM6: Governance Capture"
    description = (
        "Decision-making authority over token-economy parameters concentrates "
        "in a small group, undermining distributed governance."
    )

    def check(self, te: TokenEconomy, config=None) -> list[Verdict]:
        return [self._check_system(te)]

    def _check_system(self, te: TokenEconomy) -> Verdict:
        gov = te.governance
        rules = gov.rule_structure
        if not rules:
            # Γ is not computable without rule_structure, but the Gini
            # secondary signal may still be informative. Surface it
            # rather than collapsing the whole verdict to INCONCLUSIVE.
            if (
                gov.token_balance_gini is not None
                and gov.token_balance_gini.max > GINI_SECONDARY_THRESHOLD
            ):
                gini_signal = gov.token_balance_gini.max
                return Verdict(
                    failure_mode=self.name,
                    subject="system",
                    status=Status.FAIL,
                    formal_condition=(
                        f"Γ uncomputable (rule_structure empty), "
                        f"but Gini > {GINI_SECONDARY_THRESHOLD}"
                    ),
                    explanation=(
                        f"governance.rule_structure is empty so the "
                        f"primary Γ centralization index cannot be "
                        f"computed, but the token-balance Gini = "
                        f"{gini_signal:.3f} exceeds the secondary-signal "
                        f"threshold {GINI_SECONDARY_THRESHOLD}. Effective "
                        f"single-actor control via concentrated holdings "
                        f"is the binding concern (Curve Wars / Convex "
                        f"pattern). Fill in rule_structure for a complete "
                        f"FM6 verdict; the Gini concern is independently "
                        f"actionable."
                    ),
                    counterexample=Counterexample(
                        parameter_values={"token_gini": gini_signal},
                        narrative=(
                            f"Token-balance Gini {gini_signal:.3f} "
                            f"exceeds the {GINI_SECONDARY_THRESHOLD} "
                            f"threshold even before Γ can be computed."
                        ),
                    ),
                    suggestions=[
                        "Address token-balance concentration: introduce "
                        "vote caps, quadratic voting, or distribution "
                        "rules that flatten the ownership Gini.",
                        "Fill in governance.rule_structure to also "
                        "evaluate the primary Γ centralization index.",
                    ],
                    critical_values=[
                        CriticalValue(
                            parameter="token_gini",
                            value=GINI_SECONDARY_THRESHOLD,
                            direction="<=",
                            formula=(
                                f"G* = {GINI_SECONDARY_THRESHOLD}   "
                                f"(secondary-signal threshold)"
                            ),
                            explanation=(
                                "Maximum Gini accepted before flagging "
                                "effective single-actor control via "
                                "concentrated holdings."
                            ),
                            source="config",
                        )
                    ],
                    recommendation=NumericRecommendation(
                        parameter="token_gini",
                        current_range=(
                            gov.token_balance_gini.min,
                            gov.token_balance_gini.max,
                        ),
                        safe_threshold=GINI_SECONDARY_THRESHOLD,
                        direction="<=",
                        narrative=(
                            f"Reduce the token-balance Gini below "
                            f"{GINI_SECONDARY_THRESHOLD}. Vote caps, "
                            f"quadratic voting, or distribution rules "
                            f"that flatten ownership all reduce "
                            f"effective single-actor control."
                        ),
                    ),
                    swept_fields=["governance.token_balance_gini"],
                    committed_fields=[],
                )
            return Verdict(
                failure_mode=self.name,
                subject="system",
                status=Status.INCONCLUSIVE,
                formal_condition="Γ = |unilateral|/|total|   (rule_structure empty)",
                explanation=(
                    "Cannot evaluate FM6 without governance.rule_structure. "
                    "List each adjustable parameter and its controlling actor. "
                    "(token_balance_gini, if provided, would also surface "
                    "the secondary-signal channel.)"
                ),
            )

        unilateral = sum(1 for actor in rules.values() if actor in UNILATERAL_ACTORS)
        total = len(rules)
        gamma = unilateral / total

        # Secondary signal: token balance Gini
        gini_signal: float | None = None
        if gov.token_balance_gini is not None:
            gini_signal = gov.token_balance_gini.max  # worst case

        # NFR7 reweighting: centralized-by-design declaration
        is_centralized_intended = (
            te.meta.nfrs.governance_maturity == GovernanceMaturity.INDEFINITE
            and gov.type == GovernanceType.CENTRALIZED
        )

        # Decide status
        gamma_violation = gamma > GAMMA_CAPTURE_THRESHOLD
        gini_violation = (
            gini_signal is not None and gini_signal > GINI_SECONDARY_THRESHOLD
        )

        # ------------------------------------------------------------------
        # Critical values (closed-form integer programming).
        # ------------------------------------------------------------------
        # We want to find the minimum number n of unilateral decisions to
        # demote so that (U − n) / T ≤ Γ_threshold. Solving for n:
        #
        #     n ≥ U − T · Γ_threshold
        #
        # The smallest non-negative integer satisfying this is
        # max(0, ceil(U − T · Γ_threshold)). See docs/proofs/fm6.md.
        n_demote = max(0, math.ceil(unilateral - total * GAMMA_CAPTURE_THRESHOLD))
        # P3 — only surface the Γ-channel critical values when Γ is
        # actually a concern (verdict will FAIL on Γ, or Γ is within
        # 20% of the threshold so the user benefits from seeing the
        # margin). When the only failure is Gini, the Γ-side critical
        # values are degenerate noise and we drop them.
        gamma_relevant = gamma > 0.8 * GAMMA_CAPTURE_THRESHOLD
        critical_values: list[CriticalValue] = []
        if gamma_relevant:
            critical_values.append(
                CriticalValue(
                    parameter="Gamma",
                    value=GAMMA_CAPTURE_THRESHOLD,
                    direction="<=",
                    formula=f"Γ* = {GAMMA_CAPTURE_THRESHOLD}   (configurable threshold)",
                    explanation=(
                        "The maximum centralization fraction the verifier "
                        "accepts as distributed governance. Above this, "
                        "FM6 triggers."
                    ),
                    source="config",
                )
            )
            critical_values.append(
                CriticalValue(
                    parameter="n_demote",
                    value=float(n_demote),
                    direction=">=",
                    formula=(
                        f"n_demote* = max(0, ⌈U − T·Γ*⌉) "
                        f"= max(0, ⌈{unilateral} − {total}·{GAMMA_CAPTURE_THRESHOLD}⌉) "
                        f"= {n_demote}"
                    ),
                    explanation=(
                        f"Minimum number of currently-unilateral decisions to "
                        f"demote from single-entity / committee control to "
                        f"token-vote or smart-contract control to bring Γ to "
                        f"or below {GAMMA_CAPTURE_THRESHOLD}. With "
                        f"{unilateral} unilateral of {total} total decisions, "
                        f"demoting {n_demote} suffices."
                    ),
                    source="closed_form",
                )
            )
        if gini_signal is not None:
            critical_values.append(
                CriticalValue(
                    parameter="token_gini",
                    value=GINI_SECONDARY_THRESHOLD,
                    direction="<=",
                    formula=f"G* = {GINI_SECONDARY_THRESHOLD}   (secondary signal threshold)",
                    explanation=(
                        "The maximum token-balance Gini the verifier accepts "
                        "before flagging effective single-actor control via "
                        "concentrated holdings."
                    ),
                    source="config",
                )
            )

        # Swept/committed marking
        swept_fields = (
            ["governance.token_balance_gini"]
            if gov.token_balance_gini is not None
            and not gov.token_balance_gini.is_point
            else []
        )
        committed_fields = ["governance.rule_structure"]
        if gov.token_balance_gini is not None and gov.token_balance_gini.is_point:
            committed_fields.append("governance.token_balance_gini")

        if not gamma_violation and not gini_violation:
            return Verdict(
                failure_mode=self.name,
                subject="system",
                status=Status.PASS,
                formal_condition=(
                    f"Γ ≤ {GAMMA_CAPTURE_THRESHOLD} and "
                    f"Gini ≤ {GINI_SECONDARY_THRESHOLD}"
                ),
                explanation=(
                    f"Computed Γ = {gamma:.3f} (unilateral decisions: "
                    f"{unilateral}/{total}). "
                    + (
                        f"Token Gini = {gini_signal:.3f} is below the "
                        f"secondary-signal threshold."
                        if gini_signal is not None
                        else "(Token Gini not provided; secondary signal not evaluated.)"
                    )
                ),
                critical_values=critical_values,
                swept_fields=swept_fields,
                committed_fields=committed_fields,
            )

        # Build counterexample listing the unilateral decisions
        unilateral_decisions = [
            decision
            for decision, actor in rules.items()
            if actor in UNILATERAL_ACTORS
        ]
        params = {
            "gamma": gamma,
            "unilateral_count": float(unilateral),
            "total_count": float(total),
        }
        if gini_signal is not None:
            params["token_gini"] = gini_signal
        narrative_parts = []
        if gamma_violation:
            narrative_parts.append(
                f"Γ = {gamma:.3f} > {GAMMA_CAPTURE_THRESHOLD}; "
                f"unilateral decisions: {unilateral_decisions}"
            )
        if gini_violation and gini_signal is not None:
            narrative_parts.append(
                f"Token Gini = {gini_signal:.3f} > "
                f"{GINI_SECONDARY_THRESHOLD} (effective single-actor control "
                f"via concentrated balances)"
            )
        ce = Counterexample(
            parameter_values=params,
            narrative=" ; ".join(narrative_parts),
        )

        if is_centralized_intended and not gini_violation:
            return Verdict(
                failure_mode=self.name,
                subject="system",
                status=Status.PASS_AS_INTENDED,
                formal_condition=f"Γ ≤ {GAMMA_CAPTURE_THRESHOLD}",
                explanation=(
                    f"Γ = {gamma:.3f} > {GAMMA_CAPTURE_THRESHOLD}, but the "
                    f"system declares NFR7 = indefinite centralized governance, "
                    f"so this is design-intended rather than capture."
                ),
                counterexample=ce,
                critical_values=critical_values,
                swept_fields=swept_fields,
                committed_fields=committed_fields,
            )

        # Build the recommendation from the binding violation.
        recommendation: NumericRecommendation | None = None
        if gamma_violation:
            recommendation = NumericRecommendation(
                parameter="n_demote",
                current_range=None,
                safe_threshold=float(n_demote),
                direction=">=",
                narrative=(
                    f"Demote at least {n_demote} of the {unilateral} currently-"
                    f"unilateral decisions to token-vote or smart-contract "
                    f"control. This brings Γ from {gamma:.3f} to ≤ "
                    f"{GAMMA_CAPTURE_THRESHOLD}."
                ),
            )
        elif gini_violation and gini_signal is not None:
            recommendation = NumericRecommendation(
                parameter="token_gini",
                current_range=(
                    gov.token_balance_gini.min if gov.token_balance_gini else 0,
                    gini_signal,
                ),
                safe_threshold=GINI_SECONDARY_THRESHOLD,
                direction="<=",
                narrative=(
                    f"Reduce the token-balance Gini below "
                    f"{GINI_SECONDARY_THRESHOLD}. Vote caps, quadratic voting, "
                    f"or distribution rules that flatten ownership all "
                    f"reduce effective single-actor control."
                ),
            )

        return Verdict(
            failure_mode=self.name,
            subject="system",
            status=Status.FAIL,
            formal_condition=(
                f"Γ ≤ {GAMMA_CAPTURE_THRESHOLD}"
                + (
                    f" and Gini ≤ {GINI_SECONDARY_THRESHOLD}"
                    if gini_signal is not None
                    else ""
                )
            ),
            explanation=(
                "Governance is captured in the sense of the paper's §3.6: "
                + (
                    f"Γ = {gamma:.3f} exceeds the {GAMMA_CAPTURE_THRESHOLD} "
                    f"threshold; "
                    if gamma_violation
                    else ""
                )
                + (
                    f"token-balance Gini = {gini_signal:.3f} exceeds the "
                    f"{GINI_SECONDARY_THRESHOLD} secondary-signal threshold."
                    if gini_violation and gini_signal is not None
                    else ""
                )
            ).strip(),
            counterexample=ce,
            suggestions=self._suggestions(
                gamma_violation=gamma_violation, gini_violation=gini_violation
            ),
            critical_values=critical_values,
            recommendation=recommendation,
            swept_fields=swept_fields,
            committed_fields=committed_fields,
        )

    @staticmethod
    def _suggestions(*, gamma_violation: bool, gini_violation: bool) -> list[str]:
        s: list[str] = []
        if gamma_violation:
            s.append(
                "Reduce the number of decisions controlled by a single entity "
                "or committee; route them through token-holder votes or "
                "smart-contract automation."
            )
            s.append(
                "Define a governance roadmap that lowers Γ over time "
                "(matching NFR7 governance_maturity)."
            )
        if gini_violation:
            s.append(
                "Address token-balance concentration: introduce vote caps, "
                "quadratic voting, or distribution rules that flatten the "
                "ownership Gini."
            )
        return s
