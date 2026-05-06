# Multi-mechanism mint/burn composition

> **Status.** Phase A — implemented for FM1 and FM3.

## Statement

For a token `T` with `emission_rules = [r₁, …, rₘ]` and
`burn_rules = [s₁, …, sₙ]`, plus cross-token flows
`F` whose `target_token = T`, the per-period emission and burn rates are

> `E_T(t) = Σᵢ rate(rᵢ, t) + Σ_{f ∈ F, f.action = MINT} rate(f.amount, t)`
>
> `B_T(t) = Σⱼ rate(sⱼ, t) + Σ_{f ∈ F, f.action = BURN} rate(f.amount, t)`

i.e. the total mint and burn rates are the **linear sum** of every
mechanism that contributes to that side, regardless of trigger type
(time-based, behavioral-event, threshold) or mechanism class
(constant, linear, log, polynomial, exponential, bounded_range).

## Paper / Simulator references

- Paper §3.1, §3.3 (single-rule formulation; the paper is single-mechanism).
- `Simulator.pdf` §3.3, equation (7):
  `E(t) = Σⱼ fₐ,ⱼ × N × Yⱼ` — the explicit multi-mechanism emission
  composition rule. Our composition is the equivalence-class
  generalization of (7): we sum *rates* rather than the simulator's
  closed-form `f × N × Y` triple, but the additivity is identical.
- `Simulator.pdf` §2.6 enumerates per-mechanism burn formulas; under
  multiple coexisting burn mechanisms (e.g. demand-driven plus
  expiry), the same additive composition applies on `B(t)`.

## Assumptions

1. **Linearity of rates.** Every per-period rate is a real-valued
   function of time integrated over a period. The integral is linear,
   so a sum of rates equals the rate of the sum.
2. **Sign correctness.** `emission_rules[].function.sign` is positive
   (mint) and `burn_rules[].function.sign` is negative (burn) — these
   are schema invariants enforced at construction time. Cross-token
   flows are placed on the side specified by `target_action`.
3. **Mechanism independence.** Phase A treats every mechanism's
   asymptotic class and parameter ranges as independent. Coupled
   amounts (Phase B1: `coupling = proportional_to_source`) lift this
   assumption and are handled separately in
   `docs/proofs/conditional_rules.md`.
4. **TRANSFER flows do not contribute.** `target_action = TRANSFER`
   moves balances between actors of the target token without changing
   total supply, so it adds no term to `E` or `B`. Verifier ignores
   it in the composition sums.

## Proof

**Linearity.** For any per-period rates `aᵢ ∈ ℝ` defined on a period
`[t, t+1]`,
`∫_t^{t+1} (Σᵢ aᵢ(s)) ds = Σᵢ ∫_t^{t+1} aᵢ(s) ds`
by linearity of the Lebesgue integral. The total per-period rate
expressed in `tokens / period` is therefore the sum of the per-mechanism
rates expressed in the same units. ∎

**Sign placement.** The paper's `Ṁ = E − B` definition assigns mints
to `E` and burns to `B`. For per-token rules, the `Token` schema's
`sign` invariant places each rule on the correct side. For cross-token
flows, `target_action` does the same job — `MINT` increments `E_T`,
`BURN` increments `B_T`. The placement is **definitional**, not derived. ∎

**Closure under composition.** The asymptotic equivalence-class lattice
defined in `verifier/asymptotic.py` is closed under finite linear
combinations: a sum of two `O(f) + O(g)` rates is in `O(max(f, g))`.
The Z3 encoding implements this implicitly because every rate is a
`z3.ArithRef` over the same continuous reals; Z3 handles the addition
exactly. ∎

## Z3 encoding

`verifier/failure_modes/fm1_oversupply.py` and
`verifier/failure_modes/fm3_burn_emission.py` build:

```python
E_terms = [
    rule_rate_per_period(solver, f"{token.id}_emit_{i}", rule)
    for i, rule in enumerate(token.emission_rules)
]
for i, flow in enumerate(te.cross_token_flows):
    if flow.target_token == token.id and flow.target_action == CrossTokenAction.MINT:
        E_terms.append(
            average_rate_per_period(solver, f"{token.id}_xtmint_{i}", flow.amount)
        )
E_total = sum(E_terms[1:], E_terms[0]) if E_terms else z3.RealVal(0)
```

— and analogously for `B_total`. The sum aggregates seamlessly because
every term is a `z3.ArithRef` in `tokens / period`.

FM2 does **not** consume rule lists directly; its inequality is over
`τ̄`, not `E`. Multi-mechanism composition is therefore vacuous for
FM2 — the relationship to `E` is mediated through the Fisher-equation
lower bound `V ≥ 1/τ̄`, which is independent of how `E` is composed.

## Numerical correctness

The composition introduces no new sources of slack beyond what
`verifier/asymptotic.average_rate_per_period` already documents. Every
per-mechanism rate is bounded; their sum is bounded; Z3 reasons over
`ℚ` exactly.

## Tests

- `tests/test_multi_mechanism.py::test_two_emission_rules_compose_additively`
- `tests/test_multi_mechanism.py::test_two_burn_rules_compose_additively`
- `tests/test_multi_mechanism.py::test_fm1_includes_cross_token_mint`
- `tests/test_multi_mechanism.py::test_fm1_includes_cross_token_burn`
- `tests/test_multi_mechanism.py::test_fm1_no_emission_rules_but_cross_token_mint`
- `tests/test_phase5.py::test_cross_token_mint_adds_to_E` (existing — FM3 path)

## Lean stub

```lean
-- File: TEVerifier/Composition.lean
import Mathlib.Algebra.BigOperators.Basic

theorem multi_mechanism_E_additive
    {ι : Type} [Fintype ι] (own_rates : ι → ℝ) (xt_rates : ι → ℝ) :
    (Finset.univ.sum own_rates) + (Finset.univ.sum xt_rates)
    = Finset.univ.sum (fun i => own_rates i + xt_rates i) := by
  rw [Finset.sum_add_distrib]
```
