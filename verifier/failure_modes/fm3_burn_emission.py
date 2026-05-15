"""FM3 — Burn / emission imbalance.

Paper §3.3, eqs. (13)–(16):

    Net supply change: Ṁ = E(t) − B(t)
    Sustainability:    E(t) − B(t) ≤ g(t) · M(t)
    Burn coverage:     ρ = B(t) / E(t),   ρ ≥ 1 required for stability under
                                          zero growth.

The Tier-1 check has two parts:

1. **Structural correctness** of the burn mechanism. Demand-driven burn
   (B is a function of transaction volume Q) earns full structural credit;
   rule-driven burn (fixed schedule) is flagged because it does not respond
   to demand; absent burn is the most flagged.

2. **Quantitative ρ check** over the parameter ranges. We compute average
   E and B per period using `verifier.asymptotic.average_rate_per_period`
   and ask Z3 whether there exists an assignment with B/E < 1 (equivalently
   E − B > 0 when growth is small).

The structural and quantitative parts are reported together so the user
can see both whether the design *can* fail and why it has the structural
profile it has.
"""

from __future__ import annotations

import z3

from schema import (
    BurnTriggerKind,
    CrossTokenAction,
    EmissionTriggerKind,
    Token,
    TokenEconomy,
    TokenFunction,
)
from verifier.asymptotic import (
    average_rate_per_period,
    cross_token_flow_rate,
    own_emission_rate_per_period,
    rule_rate_per_period,
)
from verifier.conditions import rule_contributes
from verifier.failure_modes.fm1_oversupply import _declared_emission_upper_bound
from verifier.config import VerifierConfig
from verifier.constants import RHO_BURN_COVERAGE_FLOOR
from verifier.failure_modes.base import (
    Counterexample,
    CriticalValue,
    FailureMode,
    NumericRecommendation,
    Status,
    Verdict,
    z3_value_to_float,
)


# Burn trigger kinds that count as demand-driven (i.e. respond to Q).
DEMAND_DRIVEN_BURN_KINDS: frozenset[BurnTriggerKind] = frozenset(
    {BurnTriggerKind.DEMAND_DRIVEN, BurnTriggerKind.THRESHOLD_DRIVEN}
)


class FM3BurnEmission(FailureMode):
    name = "FM3: Burn / Emission Imbalance"
    description = (
        "Without burn (or with burn that is rule-driven rather than demand-"
        "driven), token supply grows monotonically and the system cannot "
        "self-correct supply imbalances."
    )

    def check(
        self, te: TokenEconomy, config: VerifierConfig | None = None
    ) -> list[Verdict]:
        cfg = config or VerifierConfig.paper_defaults()
        return [self._check_token(te, t, cfg) for t in te.tokens]

    def _check_token(
        self, te: TokenEconomy, token: Token, config: VerifierConfig
    ) -> Verdict:
        # Pure reputation markers and non-transferable tokens are not
        # subject to burn-coverage analysis in the standard sense.
        if (
            len(token.function) == 1
            and TokenFunction.REPUTATION_MARKER in token.function
        ):
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.NOT_APPLICABLE,
                formal_condition="N/A (reputation marker)",
                explanation="FM3 does not apply to pure reputation markers.",
            )

        # No emission means no possibility of burn/emission imbalance from
        # emission. (If supply was pre-minted only, ρ is irrelevant.)
        if not token.emission_rules:
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.PASS,
                formal_condition="ρ undefined (no emission); supply does not grow",
                explanation=(
                    f"Token {token.id} has no emission rules; supply does not "
                    f"grow over time, so burn/emission imbalance does not arise."
                ),
                critical_values=[
                    CriticalValue(
                        parameter="rho",
                        value=RHO_BURN_COVERAGE_FLOOR,
                        direction=">=",
                        formula=f"ρ* = {RHO_BURN_COVERAGE_FLOOR:g}   (informational)",
                        explanation=(
                            "Burn coverage threshold is informational here — "
                            "the token has no emission rules so ρ does not "
                            "constrain its sustainability."
                        ),
                        source="config",
                    )
                ],
                committed_fields=[f"tokens[{token.id}].emission_rules (empty)"],
            )

        # Case A: no burn at all (no own burn_rules AND no cross-token
        # BURN flow targeting this token). Structural fail.
        has_xt_burn = any(
            flow.target_token == token.id
            and flow.target_action == CrossTokenAction.BURN
            for flow in te.cross_token_flows
        )
        if not token.burn_rules and not has_xt_burn:
            # Schema-aware refinement: a capped-supply design (every
            # emission rule has a supply_cap) is sustainable without
            # burn — Bitcoin pattern. Reclassify as PASS_AS_INTENDED
            # rather than FAIL.
            if (
                token.emission_rules
                and all(
                    r.schedule is not None and r.schedule.supply_cap is not None
                    for r in token.emission_rules
                )
            ):
                total_cap = sum(
                    r.schedule.supply_cap for r in token.emission_rules
                )
                return Verdict(
                    failure_mode=self.name,
                    subject=token.id,
                    status=Status.PASS_AS_INTENDED,
                    formal_condition=(
                        f"Capped supply ≤ {total_cap:g} (no burn required)"
                    ),
                    explanation=(
                        f"Token {token.id} has no burn mechanism, but every "
                        f"emission rule declares a supply_cap (total cap "
                        f"= {total_cap:g} tokens). Once the cap is reached "
                        f"emission stops — supply stability is achieved "
                        f"by termination, not by burn. Sustainability is "
                        f"now an FM1 question: does Q grow to absorb the "
                        f"bounded supply? See the FM1 verdict and the "
                        f"trajectory under Refined diagnosis."
                    ),
                    critical_values=[
                        CriticalValue(
                            parameter="supply_cap",
                            value=total_cap,
                            direction="<=",
                            formula=(
                                f"M_∞ ≤ {total_cap:g}   "
                                f"(declared via Rule.schedule.supply_cap)"
                            ),
                            explanation=(
                                "Terminal supply is bounded by the declared "
                                "cap; FM3's burn-coverage condition does "
                                "not apply to capped-supply tokens."
                            ),
                            source="closed_form",
                        )
                    ],
                    committed_fields=[
                        f"tokens[{token.id}].emission_rules[*].schedule.supply_cap"
                    ],
                )
            return self._verdict_no_burn(token)

        # Case B: rule-driven (time-based) burn — flagged as structurally weak.
        # Determine the dominant burn trigger kind.
        burn_kinds = {self._burn_kind_of(rule.trigger.kind) for rule in token.burn_rules}
        is_demand_driven = bool(burn_kinds & DEMAND_DRIVEN_BURN_KINDS)
        is_rule_driven = (
            BurnTriggerKind.RULE_DRIVEN in burn_kinds
            or EmissionTriggerKind.TIME_BASED in {rule.trigger.kind for rule in token.burn_rules}
        )

        # Quantitative ρ check
        solver = self.make_solver()

        # Phase B1 — precompute each token's own E (no cross-token
        # contributions) so proportional flows can multiply against it.
        source_own_E: dict[str, z3.ArithRef] = {}
        for src in te.tokens:
            source_own_E[src.id] = own_emission_rate_per_period(
                solver, f"{src.id}_ownE_for_fm3_{token.id}", src
            )

        # Phase B2 — emission rules contribute if EVER active (over-conservative).
        E_terms = [
            rule_rate_per_period(solver, f"{token.id}_emit_{i}", rule, te=te)
            for i, rule in enumerate(token.emission_rules)
            if rule_contributes(rule, te, side="emission")
        ]
        # Cross-token flows targeting this token with action=mint contribute
        # to E. Phase 5b + B1: see docs/proofs/cross_token.md and coupled_flows.md.
        for i, flow in enumerate(te.cross_token_flows):
            if flow.target_token == token.id and flow.target_action == CrossTokenAction.MINT:
                E_terms.append(
                    cross_token_flow_rate(
                        solver,
                        f"{token.id}_xtmint_{i}",
                        flow,
                        source_own_E.get(flow.source_token, z3.RealVal(0)),
                    )
                )
        # Phase B2 — guard against the empty case (every emission rule
        # statically NEVER and no cross-token MINTs targeting this token).
        E_total = sum(E_terms[1:], E_terms[0]) if E_terms else z3.RealVal(0)

        # Phase B2 — burn rules contribute only if ALWAYS active (under-conservative).
        B_terms = [
            rule_rate_per_period(solver, f"{token.id}_burn_{i}", rule, te=te)
            for i, rule in enumerate(token.burn_rules)
            if rule_contributes(rule, te, side="burn")
        ]
        # Cross-token flows targeting this token with action=burn contribute to B.
        for i, flow in enumerate(te.cross_token_flows):
            if flow.target_token == token.id and flow.target_action == CrossTokenAction.BURN:
                B_terms.append(
                    cross_token_flow_rate(
                        solver,
                        f"{token.id}_xtburn_{i}",
                        flow,
                        source_own_E.get(flow.source_token, z3.RealVal(0)),
                    )
                )
        # Phase B2 — guard against the empty case.
        B_total = sum(B_terms[1:], B_terms[0]) if B_terms else z3.RealVal(0)

        # Phase 5d: NFR1 (resilience) tightens the ρ floor.
        nfr1_mult = float(
            config.nfr1_rho_multiplier_table.get(
                str(te.meta.nfrs.resilience), 1.0
            )
        )
        rho_floor_effective = config.rho_floor * nfr1_mult

        # Violation: E - B > 0 (i.e. ρ = B / E < 1) for some parameter assignment.
        solver.add(E_total > 0)  # avoid trivial 0/0 case
        solver.add(B_total < E_total * rho_floor_effective)

        # Critical value — ρ* is the configurable floor. The actionable
        # quantity is the implied burn rate: any model with ρ < ρ_floor
        # tells the user how much more burn they need.
        critical_values: list[CriticalValue] = [
            CriticalValue(
                parameter="rho",
                value=RHO_BURN_COVERAGE_FLOOR,
                direction=">=",
                formula=f"ρ* = {RHO_BURN_COVERAGE_FLOOR:g}   (configurable floor)",
                explanation=(
                    f"Burn coverage ratio ρ = B/E must reach at least "
                    f"{RHO_BURN_COVERAGE_FLOOR:g} for the steady-state "
                    f"supply stability condition to hold."
                ),
                source="config",
            )
        ]

        # Mark fields swept/committed
        swept_fields: list[str] = []
        committed_fields: list[str] = []
        for i, _r in enumerate(token.emission_rules):
            swept_fields.append(f"tokens[{token.id}].emission_rules[{i}]")
        for i, _r in enumerate(token.burn_rules):
            swept_fields.append(f"tokens[{token.id}].burn_rules[{i}]")

        result = solver.check()
        if result == z3.sat:
            model = solver.model()
            ce = self._build_counterexample(model, token, E_total, B_total)
            structural_note = self._structural_note(
                is_demand_driven=is_demand_driven, is_rule_driven=is_rule_driven
            )
            # Build a recommendation: the burn must reach E (in the worst
            # case the model returned). We expose the per-period values
            # from the counterexample directly.
            E_val = ce.parameter_values.get("E_per_period", 0.0)
            B_val = ce.parameter_values.get("B_per_period", 0.0)
            # P2 — when the user's declared emission upper bound is far
            # above any plausible Q ceiling (3× Q_hi as in FM1), the
            # "raise burn to E_val" recommendation cites a worst-case
            # corner from a too-wide spec. Lead with "narrow the
            # declared emission range" instead.
            Q_hi = te.participants.expected_Q.max
            E_declared_ub = _declared_emission_upper_bound(token)
            wide_declaration = Q_hi > 0 and E_declared_ub > 3.0 * Q_hi
            # Fix F — Z3 finds the smallest violating witness. When
            # E_val is much smaller than the declared upper bound
            # (< 10% of E_ub), the user almost certainly has a
            # too-loose lower bound (e.g. emission rule with c.min = 0)
            # and Z3 picked the near-zero corner. The verdict is real
            # (the corner is in the box) but the recommendation should
            # tell the user to tighten the lower bound rather than
            # quote a meaninglessly small burn floor.
            degenerate_corner = (
                E_declared_ub > 0
                and E_val < 0.1 * E_declared_ub
                and not wide_declaration
            )
            if wide_declaration:
                narrative = (
                    f"Your declared emission range for {token.id} permits "
                    f"up to ≈{E_declared_ub:g} tokens/period — more than "
                    f"3× the upper Q bound ({Q_hi:g}/period). Z3 picked "
                    f"E ≈ {E_val:g} as the worst-case witness, which is "
                    f"why the implied burn floor "
                    f"({E_val * RHO_BURN_COVERAGE_FLOOR:.2f}) is so high. "
                    f"The first-order fix is to **narrow your declared "
                    f"emission range** so its upper bound reflects the "
                    f"realistic maximum. Once narrowed, the implied burn "
                    f"floor will drop accordingly."
                )
            elif degenerate_corner:
                narrative = (
                    f"Z3 found a near-zero corner of your declared "
                    f"emission range as the violating witness "
                    f"(E ≈ {E_val:g}, while your declared upper bound "
                    f"reaches ≈{E_declared_ub:g}). This is a fragile "
                    f"counterexample — it indicates your emission rule "
                    f"includes 0 (or near-zero) values that the verifier "
                    f"can use to satisfy `B/E < 1` even when burn is "
                    f"reasonable. The first-order fix is to **raise the "
                    f"lower bound** of your declared emission range so "
                    f"it reflects the realistic minimum (typically the "
                    f"average steady-state mint rate). If your minimum "
                    f"emission is genuinely zero, this verdict is not "
                    f"actionable — it is the trivial case ρ = 0/0."
                )
            else:
                tail = (
                    "Demand-driven burn (tied to redemption events) is "
                    "the structurally correct fix; rule-driven schedules "
                    "drift out of balance as the system scales."
                    if not is_demand_driven
                    else "The current burn is demand-driven; tightening "
                    "its parameter ranges (or coupling burn to a higher "
                    "fraction of redemption events) closes the gap."
                )
                narrative = (
                    f"Raise per-period burn for {token.id} to at least "
                    f"{E_val * RHO_BURN_COVERAGE_FLOOR:.2f} tokens — the "
                    f"emission rate at the worst-case Z3 assignment. "
                    + tail
                )
            recommendation = NumericRecommendation(
                parameter="B_per_period",
                current_range=(B_val, B_val),
                safe_threshold=E_val * RHO_BURN_COVERAGE_FLOOR,
                direction=">=",
                narrative=narrative,
            )
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.FAIL,
                formal_condition=f"ρ = B/E < {RHO_BURN_COVERAGE_FLOOR} (insufficient burn coverage)",
                explanation=(
                    f"There exist parameter values for {token.id} under which "
                    f"burn coverage ratio ρ falls below {RHO_BURN_COVERAGE_FLOOR}, "
                    f"meaning supply grows faster than it can be retired. "
                    f"{structural_note}"
                ),
                counterexample=ce,
                suggestions=self._suggestions(
                    has_demand_driven=is_demand_driven, has_rule_driven=is_rule_driven
                ),
                critical_values=critical_values,
                recommendation=recommendation,
                swept_fields=swept_fields,
                committed_fields=committed_fields,
            )

        return Verdict(
            failure_mode=self.name,
            subject=token.id,
            status=Status.PASS,
            formal_condition=f"ρ ≥ {RHO_BURN_COVERAGE_FLOOR} for all parameter values",
            explanation=(
                f"Burn coverage ratio ρ for {token.id} stays at or above "
                f"{RHO_BURN_COVERAGE_FLOOR} under every parameter assignment "
                f"in the declared ranges."
                + (
                    f" Burn is demand-driven, which is the structurally strong "
                    f"choice for FM3."
                    if is_demand_driven
                    else ""
                )
            ),
            critical_values=critical_values,
            swept_fields=swept_fields,
            committed_fields=committed_fields,
        )

    @staticmethod
    def _burn_kind_of(kind) -> BurnTriggerKind:
        # Defensive: emission-style triggers can appear on burn rules in
        # IR variants; map them to the closest burn kind.
        if isinstance(kind, BurnTriggerKind):
            return kind
        # Fallback: treat behavioral_event burn as demand-driven.
        return BurnTriggerKind.DEMAND_DRIVEN

    @staticmethod
    def _structural_note(*, is_demand_driven: bool, is_rule_driven: bool) -> str:
        if is_rule_driven and not is_demand_driven:
            return (
                "Burn is rule-driven (fixed schedule), which does not respond "
                "to actual demand; this amplifies the imbalance."
            )
        if is_demand_driven:
            return (
                "Burn is demand-driven, but its quantitative magnitude is "
                "insufficient under the declared parameter ranges."
            )
        return ""

    @staticmethod
    def _verdict_no_burn(token: Token) -> Verdict:
        return Verdict(
            failure_mode="FM3: Burn / Emission Imbalance",
            subject=token.id,
            status=Status.FAIL,
            formal_condition="ρ = 0 (no burn mechanism)",
            explanation=(
                f"Token {token.id} has no burn rules. Total supply grows "
                f"monotonically with each emission event regardless of usage. "
                f"This is the structural failure mode for FM3."
            ),
            counterexample=Counterexample(
                parameter_values={"rho": 0.0},
                narrative=(
                    "Burn coverage ρ = 0 by construction: no burn rules are "
                    "declared. Any positive emission rate violates ρ ≥ 1."
                ),
            ),
            suggestions=[
                "Introduce a demand-driven burn mechanism: tokens destroyed "
                "on redemption / consumption / fee payment.",
                "If circulation is not the goal, consider expiry to bound "
                "circulating supply.",
            ],
            critical_values=[
                CriticalValue(
                    parameter="rho",
                    value=RHO_BURN_COVERAGE_FLOOR,
                    direction=">=",
                    formula=f"ρ* = {RHO_BURN_COVERAGE_FLOOR:g}",
                    explanation=(
                        "Any positive ρ would lift this verdict; the system "
                        "currently declares ρ = 0 (no burn rules)."
                    ),
                    source="config",
                )
            ],
            committed_fields=[f"tokens[{token.id}].burn_rules (empty)"],
        )

    @staticmethod
    def _build_counterexample(
        model: z3.ModelRef,
        token: Token,
        E_total: z3.ArithRef,
        B_total: z3.ArithRef,
    ) -> Counterexample:
        params: dict[str, float] = {}
        for d in model.decls():
            try:
                params[d.name()] = z3_value_to_float(model, d())
            except Exception:
                pass
        E_val = z3_value_to_float(model, E_total) if hasattr(E_total, "decl") else 0.0
        B_val = z3_value_to_float(model, B_total) if hasattr(B_total, "decl") else 0.0
        rho = B_val / E_val if E_val > 0 else 0.0
        params["E_per_period"] = E_val
        params["B_per_period"] = B_val
        params["rho"] = rho
        narrative = (
            f"With these parameter values, average emission ≈ {E_val:.2f}/period "
            f"and average burn ≈ {B_val:.2f}/period, giving ρ ≈ {rho:.3f} "
            f"(below the {RHO_BURN_COVERAGE_FLOOR} floor)."
        )
        return Counterexample(parameter_values=params, narrative=narrative)

    @staticmethod
    def _suggestions(*, has_demand_driven: bool, has_rule_driven: bool) -> list[str]:
        s: list[str] = []
        if has_rule_driven and not has_demand_driven:
            s.append(
                "Replace or supplement the rule-driven burn with a demand-"
                "driven burn (fired on redemption / consumption events) so "
                "burn tracks Q rather than the clock."
            )
        s.append(
            "Increase burn-rate parameter ranges, or reduce emission rates, "
            "until ρ ≥ 1 holds across the full parameter space."
        )
        s.append(
            "Consider a threshold-driven burn that activates when supply "
            "exceeds a target M*."
        )
        return s

    # ------------------------------------------------------------------
    # Phase-C: dual encoding + structured safety predicate
    # ------------------------------------------------------------------

    def is_satisfaction_reachable_when_failing(
        self, te: TokenEconomy, config, subject: str
    ) -> str:
        """Dual: any (E, B) corner where B ≥ E · ρ_floor?

        Returns 'true' if the safety predicate is satisfiable in the
        declared box, 'false' if the box is structurally insufficient
        (e.g. burn_rules empty so B ≡ 0 < E), 'unknown' otherwise.
        """
        token = next((t for t in te.tokens if t.id == subject), None)
        if token is None:
            return "unknown"
        if (
            len(token.function) == 1
            and TokenFunction.REPUTATION_MARKER in token.function
        ):
            return "unknown"  # FM3 N/A
        if not token.emission_rules:
            return "true"  # no emission → ρ undefined / vacuously safe
        # Structural fail: no burn at all (and no cross-token burn flow)
        has_xt_burn = any(
            f.target_token == token.id
            and f.target_action == CrossTokenAction.BURN
            for f in te.cross_token_flows
        )
        if not token.burn_rules and not has_xt_burn:
            # Schema-aware: capped supply means burn isn't required.
            if (
                token.emission_rules
                and all(
                    r.schedule is not None and r.schedule.supply_cap is not None
                    for r in token.emission_rules
                )
            ):
                return "true"
            return "false"

        cfg = config or VerifierConfig.paper_defaults()
        solver = self.make_solver()
        source_own_E: dict[str, z3.ArithRef] = {}
        for src in te.tokens:
            source_own_E[src.id] = own_emission_rate_per_period(
                solver, f"{src.id}_ownE_for_fm3sat_{token.id}", src
            )
        E_terms = []
        for i, rule in enumerate(token.emission_rules):
            if not rule_contributes(rule, te, side="emission"):
                continue
            E_terms.append(
                rule_rate_per_period(solver, f"{token.id}_emit_sat_{i}", rule, te=te)
            )
        for i, flow in enumerate(te.cross_token_flows):
            if (
                flow.target_token == token.id
                and flow.target_action == CrossTokenAction.MINT
            ):
                E_terms.append(
                    cross_token_flow_rate(
                        solver,
                        f"{token.id}_xtmint_sat_{i}",
                        flow,
                        source_own_E.get(flow.source_token, z3.RealVal(0)),
                    )
                )
        E_total = sum(E_terms[1:], E_terms[0]) if E_terms else z3.RealVal(0)

        B_terms = []
        for i, rule in enumerate(token.burn_rules):
            if not rule_contributes(rule, te, side="burn"):
                continue
            B_terms.append(
                rule_rate_per_period(solver, f"{token.id}_burn_sat_{i}", rule, te=te)
            )
        for i, flow in enumerate(te.cross_token_flows):
            if (
                flow.target_token == token.id
                and flow.target_action == CrossTokenAction.BURN
            ):
                B_terms.append(
                    cross_token_flow_rate(
                        solver,
                        f"{token.id}_xtburn_sat_{i}",
                        flow,
                        source_own_E.get(flow.source_token, z3.RealVal(0)),
                    )
                )
        B_total = sum(B_terms[1:], B_terms[0]) if B_terms else z3.RealVal(0)

        nfr1_mult = float(
            cfg.nfr1_rho_multiplier_table.get(
                str(te.meta.nfrs.resilience), 1.0
            )
        )
        rho_floor_effective = cfg.rho_floor * nfr1_mult
        solver.add(E_total > 0)
        solver.add(B_total >= E_total * rho_floor_effective)  # safety
        result = solver.check()
        if result == z3.sat:
            return "true"
        if result == z3.unsat:
            return "false"
        return "unknown"

    def safety_predicates(self, te: TokenEconomy, config, subject: str) -> list:
        from verifier.safety_predicate import SafetyPredicate

        token = next((t for t in te.tokens if t.id == subject), None)
        if token is None or not token.emission_rules:
            return []
        # Capped-supply tokens (Bitcoin, Curve CRV) are sustained by
        # termination, not by burn. The verifier reports
        # ``pass_as_intended`` for FM3 in this case. Emitting a ρ
        # predicate here would force the ABM to evaluate ρ = 0/E for
        # every run and falsely report "100% deployment violation".
        # Suppress the predicate so the ABM defers to the verifier's
        # verdict instead of contradicting it.
        if all(
            r.schedule is not None and r.schedule.supply_cap is not None
            for r in token.emission_rules
        ):
            return []
        cfg = config or VerifierConfig.paper_defaults()
        nfr1_mult = float(
            cfg.nfr1_rho_multiplier_table.get(
                str(te.meta.nfrs.resilience), 1.0
            )
        )
        return [
            SafetyPredicate(
                failure_mode="FM3",
                variable=f"rho[{subject}]",
                operator=">=",
                threshold=RHO_BURN_COVERAGE_FLOOR * nfr1_mult,
                formula="ρ = B_per_period / E_per_period (burn-coverage ratio)",
                inputs=[
                    "B_per_period (sum of own burn + xt-BURN inflows)",
                    "E_per_period (sum of own emission + xt-MINT inflows)",
                ],
                paper_section="§3.3 eq. (14)",
            )
        ]
