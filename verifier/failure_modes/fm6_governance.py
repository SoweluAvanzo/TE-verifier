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
    NumberRange,
    TokenEconomy,
    VoteWeighting,
)
from verifier.config import VerifierConfig
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
#
# COMMITTEE_TRUSTED — a small trusted group that ratifies decisions by
# fiat — counts as unilateral. The plain COMMITTEE variant captures
# real-world multisig / voting committees (Bitcoin core dev rough
# consensus, EIP process, multisig treasuries) whose internal vote
# dynamics distribute control beyond what Γ-on-actor-identity captures.
# Treating COMMITTEE as unilateral over-flagged every committee-governed
# protocol; treating it as non-unilateral matches the paper's intent
# ("can be taken unilaterally") more faithfully.
#
# Migration note: existing v1 IRs using ``committee`` keep the value
# but acquire the new semantics. The five case-study examples (Bitcoin
# / Ethereum protocol_change, eip_acceptance, consensus_rules) all
# describe multi-stakeholder committee processes, so the new semantics
# is more accurate for them. Users who genuinely meant "single trusted
# committee" should switch their YAML to ``committee_trusted``.
UNILATERAL_ACTORS: frozenset[ControllingActor] = frozenset(
    {ControllingActor.SINGLE_ENTITY, ControllingActor.COMMITTEE_TRUSTED}
)


def _gini_recommendation_narrative(
    weighting: VoteWeighting, gini_signal: float
) -> str:
    """Class-aware narrative for the Gini-driven FM6 recommendation.

    Generic "vote caps / QV / distribution rules" advice is wrong for
    most non-LINEAR weightings: a system that *already* declares QV
    doesn't need to "introduce QV"; one that uses DELEGATED needs to
    address delegate concentration, not underlying token Gini. This
    helper picks the right advice per the declared weighting.
    """
    base = (
        f"Reduce the {'effective' if weighting.value != 'linear' else 'token-balance'} "
        f"Gini below {GINI_SECONDARY_THRESHOLD}. "
    )

    if weighting == VoteWeighting.LINEAR:
        return base + (
            "Vote caps, quadratic voting, time-locked vote-escrow, or "
            "distribution rules that flatten ownership all reduce "
            "effective single-actor control. Consider declaring one of "
            "these mechanisms via `vote_weighting` if it's already in "
            "place; FM6 will then credit it in the effective-Gini "
            "calculation."
        )

    if weighting == VoteWeighting.QUADRATIC:
        return base + (
            "Quadratic voting is already declared — the residual effective "
            "Gini reflects underlying token concentration the QV "
            "transformation cannot fully mask. Reduce ``token_balance_gini`` "
            "directly (airdrops to a broader holder set, fee-based "
            "redistribution), or guard against Sybil attacks that would "
            "let large holders fragment into many small addresses and "
            "defeat QV's √-scaling."
        )

    if weighting == VoteWeighting.CAPPED:
        return base + (
            "A vote cap is already declared. Either tighten the cap "
            "(reduce ``cap_fraction``) to bind harder on the top holders, "
            "or address the broader distribution: a cap clips the top "
            "but does not flatten the middle. Consider combining the "
            "cap with QV (CAPPED + QV is a common pattern in modern "
            "DAO designs)."
        )

    if weighting == VoteWeighting.TIME_LOCKED:
        return base + (
            "Time-locked voting is partially effective — the average "
            "lock fraction is doing some work, but residual concentration "
            "still clears the threshold. Options: (1) require longer "
            "minimum locks for governance participation, raising the "
            "weighted ``avg_lock_fraction``; (2) reduce the underlying "
            "``token_balance_gini`` (broader distribution); (3) model "
            "the downstream aggregation explicitly — if a wrapper like "
            "Convex/cvxCRV holds a large fraction of locks, switch "
            "``vote_weighting`` to ``delegated`` and supply "
            "``delegate_concentration_gini`` to capture the real "
            "concentration."
        )

    if weighting == VoteWeighting.DELEGATED:
        return base + (
            "The delegate concentration drives the verdict — addressing "
            "underlying token Gini will not fix this. Options: (1) "
            "encourage smaller-delegate participation (delegate-platform "
            "fees, profile requirements, anti-Sybil enforcement); (2) "
            "introduce a per-delegate vote cap so no single delegate "
            "exceeds a hard ceiling; (3) require token holders to ratify "
            "delegate decisions (split-delegation / ratification "
            "patterns); (4) bound delegation duration so concentrated "
            "delegates lose voting power if not actively re-affirmed."
        )

    if weighting == VoteWeighting.REPUTATION_WEIGHTED:
        return base + (
            "Reputation concentration drives the verdict. Token Gini is "
            "not the relevant signal here — token-distribution levers "
            "(airdrops, caps) won't help. Options: (1) expand the "
            "reputation-earning surface (more ways to earn reputation, "
            "more participants eligible); (2) introduce reputation decay "
            "(so dormant high-reputation actors lose voting power); (3) "
            "cap reputation per identity; (4) Sybil-resist the identity "
            "layer so fragmenting reputation across many accounts is "
            "infeasible."
        )

    return base + (
        "Reduce concentration via vote caps, QV, time-locking, or "
        "broader distribution."
    )


def _effective_gini_range(
    gov,
    config: VerifierConfig | None = None,
) -> tuple[NumberRange | None, str]:
    """Compute effective voting-concentration Gini under the declared
    vote_weighting class.

    Returns ``(effective_gini_range, explanation)``:

    * ``effective_gini_range`` is a NumberRange of *effective* Gini
      (under the voting transformation). ``None`` means the verifier
      cannot derive an effective Gini from the available IR fields —
      typically because REPUTATION_WEIGHTED was declared without
      ``reputation_gini`` in vote_weighting_params.
    * ``explanation`` is a short narrative naming the weighting class
      and the parameter values used. Surfaced in the verdict so the
      user can see how the underlying token Gini was transformed.

    Approximations per class:

    * LINEAR: identity — effective Gini = token Gini.
    * QUADRATIC: effective ≈ token_gini × multiplier where
      multiplier ∈ [config.qv_mult_min, qv_mult_max]. Approximation —
      precise value depends on the balance distribution and is an
      ABM concern.
    * CAPPED: effective ≈ token_gini × (1 − cap_fraction). Conservative
      bound — vote caps clip the top of the distribution but do not
      flatten the middle.
    * TIME_LOCKED: effective ≈ token_gini × avg_lock_fraction. Reflects
      that holders who don't lock relinquish vote weight; long-term
      lockers gain it.
    * DELEGATED: effective = delegate_concentration_gini (substitutes
      token Gini entirely — the relevant distribution is over voters,
      not holders).
    * REPUTATION_WEIGHTED: effective = reputation_gini if supplied;
      else None (INCONCLUSIVE — token Gini doesn't apply).
    """
    cfg = config or VerifierConfig.paper_defaults()
    weighting = gov.vote_weighting
    params = gov.vote_weighting_params or {}
    token_gini = gov.token_balance_gini

    def _scale(rng: NumberRange, mult_lo: float, mult_hi: float) -> NumberRange:
        return NumberRange(
            min=max(0.0, min(rng.min * mult_lo, rng.min * mult_hi)),
            max=min(1.0, max(rng.max * mult_lo, rng.max * mult_hi)),
        )

    if weighting == VoteWeighting.LINEAR:
        if token_gini is None:
            return None, "LINEAR voting; token_balance_gini not supplied"
        return token_gini, "LINEAR (effective Gini = token Gini)"

    if weighting == VoteWeighting.QUADRATIC:
        if token_gini is None:
            return None, "QUADRATIC voting; token_balance_gini not supplied"
        mult_lo, mult_hi = cfg.vote_weighting_quadratic_multiplier_range
        eff = _scale(token_gini, mult_lo, mult_hi)
        return eff, (
            f"QUADRATIC: effective Gini = token Gini × [{mult_lo:g}, "
            f"{mult_hi:g}] ≈ [{eff.min:.3f}, {eff.max:.3f}]"
        )

    if weighting == VoteWeighting.CAPPED:
        cap = params.get("cap_fraction")
        if cap is None or token_gini is None:
            return token_gini, (
                "CAPPED voting declared but cap_fraction missing; falling "
                "back to LINEAR (token Gini)"
            )
        # cap_fraction is the max single-voter share. Effective Gini
        # reduces by (1 - cap_fraction).
        return (
            _scale(token_gini, 1.0 - cap.max, 1.0 - cap.min),
            f"CAPPED at cap_fraction ∈ [{cap.min:g}, {cap.max:g}]; "
            f"effective Gini ≈ token Gini × (1 − cap_fraction)",
        )

    if weighting == VoteWeighting.TIME_LOCKED:
        lockf = params.get("avg_lock_fraction")
        if lockf is None or token_gini is None:
            return token_gini, (
                "TIME_LOCKED voting declared but avg_lock_fraction missing; "
                "falling back to LINEAR (token Gini)"
            )
        return (
            _scale(token_gini, lockf.min, lockf.max),
            f"TIME_LOCKED with avg_lock_fraction ∈ [{lockf.min:g}, "
            f"{lockf.max:g}]; effective Gini scaled by the fraction "
            f"of supply actually locked",
        )

    if weighting == VoteWeighting.DELEGATED:
        dg = params.get("delegate_concentration_gini")
        if dg is None:
            return token_gini, (
                "DELEGATED voting declared but delegate_concentration_gini "
                "missing; falling back to token Gini (likely understates "
                "true voter concentration)"
            )
        return dg, (
            f"DELEGATED: substituting delegate_concentration_gini ∈ "
            f"[{dg.min:.3f}, {dg.max:.3f}] for token Gini — voting "
            f"concentration is over delegates, not holders"
        )

    if weighting == VoteWeighting.REPUTATION_WEIGHTED:
        rg = params.get("reputation_gini")
        if rg is None:
            return None, (
                "REPUTATION_WEIGHTED voting: token Gini is not applicable "
                "and reputation_gini was not supplied → INCONCLUSIVE on "
                "the secondary signal"
            )
        return rg, (
            f"REPUTATION_WEIGHTED: substituting reputation_gini ∈ "
            f"[{rg.min:.3f}, {rg.max:.3f}] for token Gini — voting power "
            f"is non-token-derived"
        )

    return token_gini, "unknown weighting class; falling back to LINEAR"


class FM6GovernanceCapture(FailureMode):
    name = "FM6: Governance Capture"
    description = (
        "Decision-making authority over token-economy parameters concentrates "
        "in a small group, undermining distributed governance."
    )

    def check(self, te: TokenEconomy, config: VerifierConfig | None = None) -> list[Verdict]:
        return [self._check_system(te, config)]

    def is_satisfaction_reachable_when_failing(
        self,
        te: TokenEconomy,
        config: VerifierConfig | None,
        subject: str,
    ) -> str:
        """Phase-C formal dual for FM6.

        Safety requires BOTH:
          • Γ ≤ Γ_threshold (centralization fraction)
          • effective_gini ≤ Gini_threshold (concentration via voting)

        Γ is deterministic from ``rule_structure`` (no range to search
        over). The effective Gini is a NumberRange; we check whether
        its minimum end clears the threshold.
        """
        gov = te.governance
        rules = gov.rule_structure
        if not rules:
            # No rule_structure → Γ uncomputable. Fall back to Gini alone.
            eff, _note = _effective_gini_range(gov, config)
            if eff is None:
                return "unknown"
            return "true" if eff.min <= GINI_SECONDARY_THRESHOLD else "false"

        unilateral = sum(1 for a in rules.values() if a in UNILATERAL_ACTORS)
        gamma = unilateral / len(rules)
        if gamma > GAMMA_CAPTURE_THRESHOLD:
            # Γ alone fails — no parameter assignment in the box can
            # fix it (rule_structure is committed, not ranged).
            return "false"

        eff, _note = _effective_gini_range(gov, config)
        if eff is None:
            # Gini side unevaluable but Γ side passes — satisfaction
            # reachable on the Γ axis; Gini side is undecidable.
            return "unknown"
        return "true" if eff.min <= GINI_SECONDARY_THRESHOLD else "false"

    def safety_predicates(
        self,
        te: TokenEconomy,
        config: VerifierConfig | None,
        subject: str,
    ) -> list:
        from verifier.safety_predicate import SafetyPredicate

        preds: list = []
        gov = te.governance
        if gov.rule_structure:
            preds.append(
                SafetyPredicate(
                    failure_mode="FM6",
                    variable="Gamma",
                    operator="<=",
                    threshold=GAMMA_CAPTURE_THRESHOLD,
                    formula=(
                        "unilateral_decisions / total_decisions; "
                        "unilateral = SINGLE_ENTITY or COMMITTEE_TRUSTED"
                    ),
                    inputs=["rule_structure"],
                    paper_section="§3.6 eq. (22)",
                )
            )
        # Always emit the Gini predicate when an effective Gini exists.
        eff, _note = _effective_gini_range(gov, config)
        if eff is not None:
            label = (
                "effective_gini"
                if gov.vote_weighting.value != "linear"
                else "token_balance_gini"
            )
            preds.append(
                SafetyPredicate(
                    failure_mode="FM6",
                    variable=label,
                    operator="<=",
                    threshold=GINI_SECONDARY_THRESHOLD,
                    formula=(
                        f"effective Gini under vote_weighting="
                        f"{gov.vote_weighting.value}"
                    ),
                    inputs=["token_balance_gini", "vote_weighting_params"],
                    paper_section="§3.6 (secondary signal)",
                )
            )
        return preds

    def _check_system(
        self, te: TokenEconomy, config: VerifierConfig | None = None
    ) -> Verdict:
        gov = te.governance
        rules = gov.rule_structure

        # Audit fix: compute the effective voting concentration via the
        # declared vote_weighting class. For LINEAR (default) this
        # equals token_balance_gini; for QUADRATIC / CAPPED / etc. it's
        # adjusted per the calibration in VerifierConfig.
        effective_gini_range, weighting_note = _effective_gini_range(gov, config)

        if not rules:
            # Γ is not computable without rule_structure, but the Gini
            # secondary signal may still be informative. Surface it
            # rather than collapsing the whole verdict to INCONCLUSIVE.
            if (
                effective_gini_range is not None
                and effective_gini_range.max > GINI_SECONDARY_THRESHOLD
            ):
                gini_signal = effective_gini_range.max
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
                        + (
                            f"  [{weighting_note}]"
                            if gov.vote_weighting.value != "linear"
                            else ""
                        )
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
                            effective_gini_range.min,
                            effective_gini_range.max,
                        ),
                        safe_threshold=GINI_SECONDARY_THRESHOLD,
                        direction="<=",
                        narrative=_gini_recommendation_narrative(
                            gov.vote_weighting, gini_signal
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

        # Secondary signal: effective Gini under the declared
        # vote_weighting. LINEAR collapses to token_balance_gini.max
        # (pre-fix behavior); other weightings adjust the underlying
        # distribution via ``_effective_gini_range``.
        gini_signal: float | None = None
        if effective_gini_range is not None:
            gini_signal = effective_gini_range.max  # worst case

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
            label = (
                "Effective Gini"
                if gov.vote_weighting.value != "linear"
                else "Token Gini"
            )
            narrative_parts.append(
                f"{label} = {gini_signal:.3f} > "
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
                    effective_gini_range.min
                    if effective_gini_range is not None
                    else 0,
                    gini_signal,
                ),
                safe_threshold=GINI_SECONDARY_THRESHOLD,
                direction="<=",
                narrative=_gini_recommendation_narrative(
                    gov.vote_weighting, gini_signal
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
                    (
                        f"effective Gini = {gini_signal:.3f} exceeds the "
                        f"{GINI_SECONDARY_THRESHOLD} secondary-signal "
                        f"threshold under vote_weighting={gov.vote_weighting.value} "
                        f"({weighting_note})."
                        if gov.vote_weighting.value != "linear"
                        else (
                            f"token-balance Gini = {gini_signal:.3f} "
                            f"exceeds the {GINI_SECONDARY_THRESHOLD} "
                            f"secondary-signal threshold."
                        )
                    )
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
