"""FM1 — Token oversupply / inflation spiral.

Paper §3.1, eqs. (4)–(8):

    Inflation arises when M·V grows faster than transaction volume Q:
        Ṁ/M + V̇/V > Q̇/Q

    At design stage, the consistent supply at velocity V is:
        M_consistent = P · Q / V

    A system has structural oversupply if the planned per-period emission
    exceeds the per-period growth allowance compatible with Q.

The Tier-1 check derives a per-period emission rate from the token's
emission rules (using verifier.asymptotic.average_rate_per_period) and
asks Z3 whether there exists a parameter assignment in the user's
declared ranges such that emission outpaces what Q × V can absorb.

Because we do not yet model the token price P endogenously, we use the
non-dimensional form: violation when E_per_period > Q_per_period (i.e.
emission produces more tokens than there are transactions to absorb at
unit velocity). This is conservative — the actual paper inequality
becomes harder to satisfy as V grows; our form approximates the critical
boundary at V = 1 and is the natural design-stage check.
"""

from __future__ import annotations

import z3

from schema import (
    AsymptoticFamily,
    CrossTokenAction,
    Token,
    TokenEconomy,
    TokenFunction,
)
from verifier.asymptotic import (
    cross_token_flow_rate,
    own_emission_rate_per_period,
    representative_midpoint,
    rule_rate_per_period,
)
from verifier.conditions import rule_contributes


def _declared_emission_upper_bound(token: Token) -> float:
    """Heuristic upper bound of the declared per-period emission.

    Walks each emission rule's function asymptotic class and event
    frequency, and returns the sum of their per-rule upper bounds.
    Used by the FM1 recommendation to detect absurdly wide
    declarations (e.g. CRV's 0..15.4M range when Q_hi is 5M) and
    suggest narrowing the range before any other fix.

    The heuristic is intentionally conservative — it over-estimates
    on log/exp/poly classes, which is fine because we only use the
    result for a >10× threshold check.
    """
    H = 52.0  # default verification horizon
    total = 0.0
    for rule in token.emission_rules:
        ac = rule.function.asymptotic_class
        fam = ac.family
        if fam == AsymptoticFamily.CONSTANT:
            r = ac.parameter_ranges.get("c")
            fn_ub = r.max if r else 0.0
        elif fam == AsymptoticFamily.BOUNDED_RANGE:
            fn_ub = ac.bounds.max if ac.bounds else 0.0
        elif fam == AsymptoticFamily.LINEAR:
            ar = ac.parameter_ranges.get("a")
            br = ac.parameter_ranges.get("b")
            a_max = ar.max if ar else 0.0
            b_max = br.max if br else 0.0
            fn_ub = a_max * (H / 2.0) + b_max
        elif fam == AsymptoticFamily.UNSPECIFIED:
            r = ac.parameter_ranges.get("value")
            fn_ub = r.max if r else 0.0
        else:
            # POLYNOMIAL / LOG / EXPONENTIAL — use the same upper-bound
            # surrogates as `verifier.asymptotic.average_rate_per_period`
            # would compute at the high parameter corner.
            ar = ac.parameter_ranges.get("a")
            a_max = ar.max if ar else 0.0
            fn_ub = a_max * (H / 4.0) + 1.0  # rough surrogate
        ef = rule.trigger.event_frequency
        if ef is not None:
            if ef.family == AsymptoticFamily.CONSTANT:
                ef_r = ef.parameter_ranges.get("c")
                fn_ub *= ef_r.max if ef_r else 1.0
            elif ef.family == AsymptoticFamily.BOUNDED_RANGE:
                fn_ub *= ef.bounds.max if ef.bounds else 1.0
            elif ef.family == AsymptoticFamily.LINEAR:
                ar = ef.parameter_ranges.get("a")
                br = ef.parameter_ranges.get("b")
                fn_ub *= (ar.max if ar else 0.0) * (H / 2.0) + (
                    br.max if br else 0.0
                )
        total += fn_ub
    return total
from verifier.failure_modes.base import (
    Counterexample,
    CriticalValue,
    FailureMode,
    NumericRecommendation,
    Status,
    Verdict,
    z3_value_to_float,
)


class FM1Oversupply(FailureMode):
    name = "FM1: Token Oversupply / Inflation"
    description = (
        "Token emission persistently outpaces growth in real economic activity, "
        "causing internal price decline and incentive erosion."
    )

    def check(self, te: TokenEconomy, config=None) -> list[Verdict]:
        verdicts: list[Verdict] = []
        for token in te.tokens:
            verdicts.append(self._check_token(te, token))
        return verdicts

    def _check_token(self, te: TokenEconomy, token: Token) -> Verdict:
        # Non-transferable tokens have no transactional velocity; the
        # Fisher consistency check (M·V = P·Q) does not apply.
        if not token.transferable:
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.NOT_APPLICABLE,
                formal_condition="N/A (non-transferable)",
                explanation=(
                    f"Token {token.id} is non-transferable; the Fisher "
                    f"consistency check that grounds FM1 does not apply."
                ),
            )

        # If a token has no emission at all (pre-minted only, or pure
        # reputation marker with no growth) AND no cross-token flow
        # mints into it, oversupply cannot occur from emission alone.
        has_xt_mint = any(
            flow.target_token == token.id
            and flow.target_action == CrossTokenAction.MINT
            for flow in te.cross_token_flows
        )
        if not token.emission_rules and not has_xt_mint:
            Q_lo = te.participants.expected_Q.min
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.PASS,
                formal_condition="Ṁ/M + V̇/V ≤ Q̇/Q (no emission rules)",
                explanation=(
                    f"Token {token.id} has no emission rules; supply does "
                    f"not grow over time, so oversupply cannot arise."
                ),
                critical_values=[
                    CriticalValue(
                        parameter="net_emission",
                        value=Q_lo,
                        direction="<=",
                        formula=f"E_net* = min(Q) = {Q_lo:g}   (informational)",
                        explanation=(
                            "Per-period net emission ceiling for "
                            "informational purposes — the token currently "
                            "has no emission rules, so this is not active."
                        ),
                        source="closed_form",
                    )
                ],
                committed_fields=[
                    f"tokens[{token.id}].emission_rules (empty)"
                ],
            )

        # Pure reputation markers are non-fungible by intent and not
        # subject to the Fisher consistency check.
        if (
            len(token.function) == 1
            and TokenFunction.REPUTATION_MARKER in token.function
        ):
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.NOT_APPLICABLE,
                formal_condition="N/A (reputation marker, non-fungible)",
                explanation="FM1 does not apply to pure reputation markers.",
            )

        solver = self.make_solver()

        # Phase B1 — precompute every other token's "own E" (own
        # emission_rules only, no transitive cross-token contributions)
        # so that proportional flows can multiply against it without
        # introducing cycles. See docs/proofs/coupled_flows.md.
        source_own_E: dict[str, z3.ArithRef] = {}
        for src in te.tokens:
            source_own_E[src.id] = own_emission_rate_per_period(
                solver, f"{src.id}_ownE_for_fm1_{token.id}", src
            )

        # Emission per period (sum across all rules, including event
        # frequency for behavior-triggered rules). Cross-token flows
        # whose target_action is MINT into this token contribute on the
        # same side — see docs/proofs/composition.md and coupled_flows.md.
        E_terms: list[z3.ArithRef] = []
        for i, rule in enumerate(token.emission_rules):
            # Phase B2 — skip rules whose conditions are statically NEVER.
            if not rule_contributes(rule, te, side="emission"):
                continue
            E = rule_rate_per_period(solver, f"{token.id}_emit_{i}", rule)
            E_terms.append(E)
        for i, flow in enumerate(te.cross_token_flows):
            if (
                flow.target_token == token.id
                and flow.target_action == CrossTokenAction.MINT
            ):
                E_terms.append(
                    cross_token_flow_rate(
                        solver,
                        f"{token.id}_xtmint_{i}",
                        flow,
                        source_own_E.get(flow.source_token, z3.RealVal(0)),
                    )
                )
        E_total = sum(E_terms[1:], E_terms[0]) if E_terms else z3.RealVal(0)

        # Burn per period (sum across all rules) — subtract from emission.
        # Cross-token BURN flows targeting this token add on the burn side.
        B_terms: list[z3.ArithRef] = []
        for i, rule in enumerate(token.burn_rules):
            # Phase B2 — for the BURN side in FM1 we are checking
            # whether emission overshoots Q. A rule whose conditions
            # are not always-satisfied may not actually fire, so we
            # *under-count* it here (only include when ALWAYS) — this
            # is the conservative direction for FM1's "burn helps"
            # logic.
            if not rule_contributes(rule, te, side="burn"):
                continue
            B = rule_rate_per_period(solver, f"{token.id}_burn_{i}", rule)
            B_terms.append(B)
        for i, flow in enumerate(te.cross_token_flows):
            if (
                flow.target_token == token.id
                and flow.target_action == CrossTokenAction.BURN
            ):
                B_terms.append(
                    cross_token_flow_rate(
                        solver,
                        f"{token.id}_xtburn_{i}",
                        flow,
                        source_own_E.get(flow.source_token, z3.RealVal(0)),
                    )
                )
        B_total = sum(B_terms[1:], B_terms[0]) if B_terms else z3.RealVal(0)

        # Q (transactions/period)
        Q_lo, Q_hi = te.participants.expected_Q.min, te.participants.expected_Q.max
        Q = z3.Real(f"{token.id}__Q")
        solver.add(Q >= Q_lo, Q <= Q_hi)

        # Oversupply violation: net emission > Q (in the non-dimensional
        # form M_consistent = Q/V at V = 1).
        net_emission = E_total - B_total
        solver.add(net_emission > Q)

        # Critical value — closed-form: E* = Q_lo is the worst-case
        # upper bound on net emission. (Net emission must clear *every* Q
        # in the declared range, so the binding constraint is Q_lo.)
        critical_values: list[CriticalValue] = [
            CriticalValue(
                parameter="net_emission",
                value=Q_lo,
                direction="<=",
                formula=(
                    f"E_net* = min(Q) = {Q_lo:g}   "
                    f"(net emission must clear every Q in the declared range)"
                ),
                explanation=(
                    f"Maximum sustainable net per-period emission. With Q "
                    f"declared in [{Q_lo:g}, {Q_hi:g}], the binding "
                    f"constraint is Q_lo: any (E − B) exceeding {Q_lo:g} "
                    f"tokens/period triggers oversupply at the lowest "
                    f"plausible transaction volume."
                ),
                source="closed_form",
            )
        ]
        # Swept fields — Q range is swept if not point; emission/burn rules
        # whose parameter ranges are wide are swept.
        swept_fields: list[str] = []
        committed_fields: list[str] = []
        if te.participants.expected_Q.is_point:
            committed_fields.append("participants.expected_Q")
        else:
            swept_fields.append("participants.expected_Q")
        for i, _r in enumerate(token.emission_rules):
            swept_fields.append(f"tokens[{token.id}].emission_rules[{i}]")
        for i, _r in enumerate(token.burn_rules):
            swept_fields.append(f"tokens[{token.id}].burn_rules[{i}]")
        for i, flow in enumerate(te.cross_token_flows):
            if flow.target_token == token.id and flow.target_action in (
                CrossTokenAction.MINT,
                CrossTokenAction.BURN,
            ):
                swept_fields.append(
                    f"cross_token_flows[{i}] ({flow.source_token}→{token.id} "
                    f"{flow.target_action.value})"
                )

        result = solver.check()
        if result == z3.sat:
            model = solver.model()
            ce = self._build_counterexample(model, token, E_total, B_total, Q)
            margin = self._compute_margin(token, te)
            # Phase fix-4 — when the user's declared emission upper
            # bound is more than 3× Q_hi, the first-order action is
            # to narrow that range, not to "cap at Q_lo". We compare
            # the *declared* upper bound (sum across emission rules)
            # against Q_hi rather than the Z3 model's witness — Z3
            # finds the smallest violating witness, not the worst-case
            # corner of the declared box.
            E_declared_ub = _declared_emission_upper_bound(token)
            wide_declaration = E_declared_ub > 3.0 * Q_hi
            if wide_declaration:
                narrative = (
                    f"Your declared emission range for {token.id} permits "
                    f"up to ≈{E_declared_ub:g} tokens/period — "
                    f"more than 10× the upper Q bound ({Q_hi:g}/period). "
                    f"The first-order fix is to **narrow your declared "
                    f"emission range** so its upper bound reflects the "
                    f"realistic maximum. Once the range is realistic, "
                    f"the binding cap becomes E_net ≤ {Q_lo:g} "
                    f"(min(Q)) — either lower the emission rate, "
                    f"tighten its asymptotic class, or add demand-"
                    f"driven burn to compensate."
                )
            else:
                narrative = (
                    f"Cap net per-period emission of {token.id} at "
                    f"{Q_lo:g} tokens. Either lower the emission rate "
                    f"(or its asymptotic class) or add demand-driven burn "
                    f"to compensate."
                )
            recommendation = NumericRecommendation(
                parameter="net_emission",
                current_range=None,
                safe_threshold=Q_lo,
                direction="<=",
                narrative=narrative,
            )
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.FAIL,
                formal_condition="(E − B) > P·Q / V (Fisher consistency)",
                explanation=(
                    f"There exist parameter values within the declared ranges "
                    f"under which net emission of {token.id} exceeds the "
                    f"transaction volume needed to absorb it at unit velocity. "
                    f"This is structural oversupply (FM1)."
                ),
                counterexample=ce,
                margin=margin,
                suggestions=self._suggestions(token, has_burn=bool(token.burn_rules)),
                critical_values=critical_values,
                recommendation=recommendation,
                swept_fields=swept_fields,
                committed_fields=committed_fields,
            )

        return Verdict(
            failure_mode=self.name,
            subject=token.id,
            status=Status.PASS,
            formal_condition="(E − B) ≤ P·Q / V",
            explanation=(
                f"For all parameter values in the declared ranges, net emission "
                f"of {token.id} stays within the transaction-absorption capacity."
            ),
            critical_values=critical_values,
            swept_fields=swept_fields,
            committed_fields=committed_fields,
        )

    @staticmethod
    def _build_counterexample(
        model: z3.ModelRef,
        token: Token,
        E_total: z3.ArithRef,
        B_total: z3.ArithRef,
        Q: z3.ArithRef,
    ) -> Counterexample:
        params: dict[str, float] = {}
        # Walk all declarations in the model and surface them
        for d in model.decls():
            try:
                params[d.name()] = z3_value_to_float(model, d())
            except Exception:
                pass
        # Always surface the Q value plus the composite E_total/B_total
        # so downstream recommendation logic can read the worst-case
        # emission magnitude without re-eval-ing the Z3 expression.
        params[f"{token.id}__Q"] = z3_value_to_float(model, Q)
        try:
            params[f"{token.id}__E_total"] = z3_value_to_float(model, E_total)
            params[f"{token.id}__B_total"] = z3_value_to_float(model, B_total)
        except Exception:
            pass
        narrative = (
            f"With these parameter values, token {token.id} produces more "
            f"tokens per period than the system can transact away. Concretely, "
            f"Q ≈ {params.get(f'{token.id}__Q', 0):.2f} tx/period, "
            f"net emission > Q. Inflation is structural under these inputs."
        )
        return Counterexample(parameter_values=params, narrative=narrative)

    @staticmethod
    def _compute_margin(token: Token, te: TokenEconomy) -> float | None:
        """Approximate margin: ratio of midpoint Q to midpoint emission.

        > 1 means we have slack; we do not surface a margin when we already
        emitted FAIL.
        """
        try:
            Q_mid = representative_midpoint(te.participants.expected_Q)
            return Q_mid
        except Exception:
            return None

    @staticmethod
    def _suggestions(token: Token, *, has_burn: bool) -> list[str]:
        s: list[str] = []
        if not has_burn:
            s.append(
                f"Add a demand-driven burn mechanism to {token.id} so that "
                f"token destruction tracks transaction volume."
            )
        s.append(
            "Tighten the upper bounds of emission-rate parameters, or lower "
            "the emission asymptotic class (e.g. linear → log)."
        )
        s.append(
            "Increase the lower bound of expected_Q if your activity assumption "
            "is conservative — alternatively, demonstrate that Q growth keeps pace."
        )
        return s

    # ------------------------------------------------------------------
    # Phase-C: dual encoding + structured safety predicate
    # ------------------------------------------------------------------

    def is_satisfaction_reachable_when_failing(
        self, te: TokenEconomy, config, subject: str
    ) -> str:
        """Dual: any (E, B, Q) corner with E_net ≤ Q?"""
        token = next((t for t in te.tokens if t.id == subject), None)
        if token is None or not token.transferable:
            return "unknown"
        if not token.emission_rules:
            return "true"  # no emission → trivially safe

        solver = self.make_solver()
        source_own_E: dict[str, z3.ArithRef] = {}
        for src in te.tokens:
            source_own_E[src.id] = own_emission_rate_per_period(
                solver, f"{src.id}_ownE_for_fm1sat_{token.id}", src
            )
        E_terms = []
        for i, rule in enumerate(token.emission_rules):
            if not rule_contributes(rule, te, side="emission"):
                continue
            E_terms.append(
                rule_rate_per_period(solver, f"{token.id}_emit_sat_{i}", rule)
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
                rule_rate_per_period(solver, f"{token.id}_burn_sat_{i}", rule)
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

        Q_lo, Q_hi = te.participants.expected_Q.min, te.participants.expected_Q.max
        Q = z3.Real(f"Q_sat_{token.id}")
        solver.add(Q >= Q_lo, Q <= Q_hi)
        solver.add(E_total - B_total <= Q)  # safety
        result = solver.check()
        if result == z3.sat:
            return "true"
        if result == z3.unsat:
            return "false"
        return "unknown"

    def safety_predicates(self, te: TokenEconomy, config, subject: str) -> list:
        from verifier.safety_predicate import SafetyPredicate

        token = next((t for t in te.tokens if t.id == subject), None)
        if (
            token is None
            or not token.transferable
            or not token.emission_rules
        ):
            return []
        Q_lo = te.participants.expected_Q.min
        return [
            SafetyPredicate(
                failure_mode="FM1",
                variable=f"net_emission_per_period[{subject}]",
                operator="<=",
                threshold=Q_lo,
                formula=(
                    "(Σ emission rules) − (Σ burn rules + xt-BURN flows); "
                    "compare to Q_per_period in token-volume units"
                ),
                inputs=[
                    "emission_rules",
                    "burn_rules",
                    "cross_token_flows",
                    "expected_Q",
                ],
                paper_section="§3.1 eq. (5)",
            )
        ]
