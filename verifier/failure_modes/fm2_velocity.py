"""FM2 — Token velocity trap.

Paper §3.2, eqs. (9)–(12):

    Wealth-weighted average holding time:
        τ̄ = Σ_i (M_i / M) · E_i[τ]
    Velocity lower bound (Jensen):
        V ≥ 1/τ̄
    Velocity trap is indicated when τ̄ → 1.

Tier-1 implementation: compute τ̄ symbolically over the agent_type
holding-time ranges from the IR. Use Z3 to find a parameter assignment
with τ̄ ≤ TAU_BAR_VELOCITY_TRAP_CEILING.

NFR6 reweighting (CIRCULATE_FAST): the user has declared that high
velocity is the *design goal*. In that case a finding of low τ̄ is not
a failure but a confirmation; we return PASS_AS_INTENDED.
"""

from __future__ import annotations

import z3

from schema import CirculationSpeed, Token, TokenEconomy, TokenFunction
from verifier import elicitation
from verifier.constants import TAU_BAR_VELOCITY_TRAP_CEILING
from verifier.failure_modes.base import (
    Counterexample,
    CriticalValue,
    FailureMode,
    NumericRecommendation,
    Status,
    Verdict,
    z3_value_to_float,
)


class FM2VelocityTrap(FailureMode):
    name = "FM2: Token Velocity Trap"
    description = (
        "Tokens with no structural reason to be held are spent immediately, "
        "driving velocity high and amplifying any oversupply pressure."
    )

    def check(self, te: TokenEconomy, config=None) -> list[Verdict]:
        return [self._check_token(te, t) for t in te.tokens]

    def _check_token(self, te: TokenEconomy, token: Token) -> Verdict:
        # Pure governance / reputation tokens have intentionally low velocity
        # via non-transferability or by design; FM2 does not apply.
        if not token.transferable:
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.NOT_APPLICABLE,
                formal_condition="N/A (non-transferable)",
                explanation=(
                    f"Token {token.id} is non-transferable; there is no "
                    f"meaningful 'velocity' to fall into a trap on."
                ),
            )

        if (
            len(token.function) == 1
            and TokenFunction.REPUTATION_MARKER in token.function
        ):
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.NOT_APPLICABLE,
                formal_condition="N/A (reputation marker)",
                explanation="FM2 does not apply to pure reputation markers.",
            )

        # Check that we actually have agent type data; otherwise try
        # the Phase 2 elicitation fallback: synthesize a single-population
        # agent from `holding_incentives` if the token declares them.
        if not te.participants.agent_types:
            if token.holding_incentives:
                tau_floor = elicitation.holding_time_floor_from(
                    token.holding_incentives
                )
                ceiling = TAU_BAR_VELOCITY_TRAP_CEILING
                pass_or_fail = (
                    Status.PASS
                    if tau_floor > ceiling
                    else (
                        Status.PASS_AS_INTENDED
                        if te.meta.nfrs.circulation_speed
                        == CirculationSpeed.CIRCULATE_FAST
                        else Status.FAIL
                    )
                )
                return Verdict(
                    failure_mode=self.name,
                    subject=token.id,
                    status=pass_or_fail,
                    formal_condition=(
                        f"τ̄ derived from holding_incentives "
                        f"(no agent_types declared); τ_floor = {tau_floor:g}"
                    ),
                    explanation=(
                        f"No agent_types declared. Derived τ floor from "
                        f"{[hi.value for hi in token.holding_incentives]} "
                        f"= {tau_floor:g} periods; "
                        + (
                            f"above the trap ceiling ({ceiling}), so FM2 "
                            f"holds."
                            if pass_or_fail == Status.PASS
                            else f"at or below the trap ceiling ({ceiling})."
                        )
                    ),
                    critical_values=[
                        CriticalValue(
                            parameter="tau_bar",
                            value=ceiling,
                            direction=">=",
                            formula=f"τ̄* = τ_ceiling = {ceiling:g}",
                            explanation=(
                                "Wealth-weighted holding time at which the "
                                "system transitions out of the velocity trap."
                            ),
                            source="config",
                        )
                    ],
                    swept_fields=[f"tokens[{token.id}].holding_incentives (derived)"],
                )
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.INCONCLUSIVE,
                formal_condition="τ̄ = Σ_i (M_i/M) · E_i[τ]",
                explanation=(
                    "Cannot evaluate τ̄ without agent_types or "
                    "holding_incentives in the IR. Provide at least one "
                    "agent_type with an expected_holding_time, or set "
                    "holding_incentives on the token."
                ),
            )

        ceiling = TAU_BAR_VELOCITY_TRAP_CEILING
        is_intended = (
            te.meta.nfrs.circulation_speed == CirculationSpeed.CIRCULATE_FAST
        )

        solver = self.make_solver()

        # τ̄ = Σ_i w_i · τ_i, where w_i is balance_share if provided, else fraction.
        tau_terms: list[z3.ArithRef] = []
        for ag in te.participants.agent_types:
            w = ag.balance_share if ag.balance_share is not None else ag.fraction
            tau = z3.Real(f"tau_{token.id}_{ag.id}")
            solver.add(
                tau >= ag.expected_holding_time.expected_periods.min,
                tau <= ag.expected_holding_time.expected_periods.max,
            )
            tau_terms.append(z3.RealVal(w) * tau)
        tau_bar = sum(tau_terms[1:], tau_terms[0])

        # Violation: τ̄ ≤ ceiling
        solver.add(tau_bar <= ceiling)

        # ------------------------------------------------------------------
        # Critical value — τ̄* is the configurable ceiling itself.
        # ------------------------------------------------------------------
        critical_values: list[CriticalValue] = [
            CriticalValue(
                parameter="tau_bar",
                value=ceiling,
                direction=">=",
                formula=f"τ̄* = τ_ceiling = {ceiling:g}   (configurable)",
                explanation=(
                    f"Wealth-weighted holding time at which the system "
                    f"transitions out of the velocity trap. Per-agent τ "
                    f"values that drag τ̄ below this floor indicate the "
                    f"trap is active."
                ),
                source="config",
            )
        ]

        # Swept/committed marking — every per-agent holding-time range is
        # swept unless point-valued; balance_share is committed if set.
        swept_fields, committed_fields = self._mark_fields(te, token)

        result = solver.check()
        if result == z3.sat:
            model = solver.model()
            ce = self._build_counterexample(model, token, tau_bar)
            recommendation = self._build_recommendation(te, token, ce, ceiling)
            if is_intended:
                return Verdict(
                    failure_mode=self.name,
                    subject=token.id,
                    status=Status.PASS_AS_INTENDED,
                    formal_condition=f"τ̄ → 1 (currently τ̄ ≤ {ceiling})",
                    explanation=(
                        f"Token {token.id} can exhibit high velocity (τ̄ ≤ "
                        f"{ceiling} periods) under some parameter assignments. "
                        f"Your NFR6 declaration (circulate_fast) marks this "
                        f"as the design goal, not a failure."
                    ),
                    counterexample=ce,
                    critical_values=critical_values,
                    swept_fields=swept_fields,
                    committed_fields=committed_fields,
                )
            return Verdict(
                failure_mode=self.name,
                subject=token.id,
                status=Status.FAIL,
                formal_condition=f"τ̄ ≤ {ceiling} (velocity trap)",
                explanation=(
                    f"Wealth-weighted holding time τ̄ for {token.id} can be "
                    f"≤ {ceiling} periods given the declared agent-type "
                    f"holding-time ranges. Tokens are spent essentially "
                    f"immediately, amplifying any oversupply pressure."
                ),
                counterexample=ce,
                suggestions=[
                    "Add holding incentives: staking rewards, governance "
                    "rights, time-locked benefits, or tiered access.",
                    "Reweight wealth distribution toward agents with longer "
                    "expected holding times.",
                    "If high velocity is the goal, set NFRs.circulation_speed "
                    "to circulate_fast to reclassify this as design-intended.",
                ],
                critical_values=critical_values,
                recommendation=recommendation,
                swept_fields=swept_fields,
                committed_fields=committed_fields,
            )

        return Verdict(
            failure_mode=self.name,
            subject=token.id,
            status=Status.PASS,
            formal_condition=f"τ̄ > {ceiling} for all agent-type assignments",
            explanation=(
                f"Wealth-weighted holding time τ̄ for {token.id} stays above "
                f"the velocity-trap ceiling for all parameter values."
            ),
            critical_values=critical_values,
            swept_fields=swept_fields,
            committed_fields=committed_fields,
        )

    @staticmethod
    def _mark_fields(
        te: TokenEconomy, token: Token
    ) -> tuple[list[str], list[str]]:
        swept: list[str] = []
        committed: list[str] = []
        for ag in te.participants.agent_types:
            label = (
                f"participants.agent_types[{ag.id}].expected_holding_time"
            )
            if ag.expected_holding_time.expected_periods.is_point:
                committed.append(label)
            else:
                swept.append(label)
            if ag.balance_share is not None:
                committed.append(
                    f"participants.agent_types[{ag.id}].balance_share"
                )
        return swept, committed

    @staticmethod
    def _build_recommendation(
        te: TokenEconomy,
        token: Token,
        ce: Counterexample,
        ceiling: float,
    ) -> NumericRecommendation | None:
        """Identify the agent type whose τ should be raised to lift τ̄.

        τ̄ = Σ_i w_i · τ_i. Raising τ_i for the highest-weighted agent
        gives the most leverage. We compute how much τ_i would need to
        increase to push τ̄ above the ceiling, holding others at their
        counterexample values.
        """
        if not te.participants.agent_types:
            return None
        # Worst-case τ̄ in the counterexample
        tau_bar_curr = sum(
            (ag.balance_share if ag.balance_share is not None else ag.fraction)
            * ce.parameter_values.get(f"tau_{token.id}_{ag.id}", 0.0)
            for ag in te.participants.agent_types
        )
        # Identify the highest-weight agent
        weighted = sorted(
            te.participants.agent_types,
            key=lambda a: (
                a.balance_share if a.balance_share is not None else a.fraction
            ),
            reverse=True,
        )
        leverage_agent = weighted[0]
        w = (
            leverage_agent.balance_share
            if leverage_agent.balance_share is not None
            else leverage_agent.fraction
        )
        if w <= 0:
            return None
        # Required τ increase for this agent alone to raise τ̄ above ceiling
        delta_tau = (ceiling - tau_bar_curr) / w
        new_tau = ce.parameter_values.get(
            f"tau_{token.id}_{leverage_agent.id}", 0.0
        ) + delta_tau
        return NumericRecommendation(
            parameter=f"tau[{leverage_agent.id}]",
            current_range=(
                leverage_agent.expected_holding_time.expected_periods.min,
                leverage_agent.expected_holding_time.expected_periods.max,
            ),
            safe_threshold=new_tau,
            direction=">=",
            narrative=(
                f"Raise the expected holding time of agent type "
                f"'{leverage_agent.id}' (wealth share ≈ {w:.0%}) to at "
                f"least {new_tau:.2f} periods. Holding-incentive "
                f"mechanisms — staking, governance rights, time-locked "
                f"rewards — are the typical levers."
            ),
            mechanism_mappings=elicitation.holding_mechanisms_above(new_tau),
        )

    @staticmethod
    def _build_counterexample(
        model: z3.ModelRef, token: Token, tau_bar: z3.ArithRef
    ) -> Counterexample:
        params: dict[str, float] = {}
        for d in model.decls():
            try:
                params[d.name()] = z3_value_to_float(model, d())
            except Exception:
                pass
        narrative = (
            f"Under these holding times, the wealth-weighted average τ̄ "
            f"for {token.id} reaches the velocity-trap region (≤ "
            f"{TAU_BAR_VELOCITY_TRAP_CEILING})."
        )
        return Counterexample(parameter_values=params, narrative=narrative)
