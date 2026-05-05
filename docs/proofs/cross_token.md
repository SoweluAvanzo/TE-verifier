# Cross-token flows

> **Status.** Phase 5b — implemented for FM3.

## Statement

For a multi-token system with `cross_token_flows: list[CrossTokenFlow]`,
the per-period emission and burn rates of token `T` are

> `E_T = Σ_{r ∈ T.emission_rules} rate(r) + Σ_{f : f.target=T ∧ f.action=MINT} rate(f)`
>
> `B_T = Σ_{r ∈ T.burn_rules} rate(r) + Σ_{f : f.target=T ∧ f.action=BURN} rate(f)`

i.e. cross-token-flow contributions add linearly to the per-rule
contributions on the same side (mint/burn).

## Paper reference

Verifier extension — the paper is single-token in §3. The IR's
`CrossTokenFlow` is documented in `architecture.md` §4 as the
multi-token generalization.

## Assumptions

1. **(Linear additivity.)** Cross-token flow contributions add linearly
   to per-rule contributions. This is justified because both are
   per-period rates measured in the same units (tokens/period); rates
   add by definition.
2. **(Independence.)** The cross-token flow's amount is not coupled to
   the token's own emission/burn rules. Phase 5+ may introduce coupling
   (e.g. a flow whose amount depends on another rule's volume); for
   Tier-1 we treat the flow as an independent contribution.
3. **(Sign correctness.)** `target_action ∈ {MINT, BURN, TRANSFER}`.
   `TRANSFER` flows do not change the supply of the target token (they
   move balances) and therefore do not contribute to E or B; the
   verifier ignores them in the FM3 sum.

## Proof

**Linearity of rates.** A per-period rate is a real-valued function of
time integrated over a period. The integral is linear, so a sum of
rates is the rate of the sum. ∎

**Sign placement.** `MINT` events add to circulating supply
(`Ṁ ↑`); the paper's `Ṁ = E − B` definition assigns mints to `E`. By
the same definitional split, `BURN` events go to `B`. ∎

## Z3 encoding

`verifier/failure_modes/fm3_burn_emission.py` adds, for each
`CrossTokenFlow` whose `target_token` matches the current token:

- if `target_action = MINT`: an additional term in the `E_total` sum
  computed via `average_rate_per_period(flow.amount)`.
- if `target_action = BURN`: an additional term in the `B_total` sum
  computed the same way.

The sum aggregates seamlessly with the per-rule terms because both
are `z3.ArithRef` expressions in the same units.

## Numerical correctness

Linear addition of bounded `average_rate_per_period` expressions. No
new sources of slack beyond what `verifier/asymptotic.py` already
documents.

## Tests

- `tests/test_phase5_cross_token.py::test_cross_token_mint_adds_to_E`
- `tests/test_phase5_cross_token.py::test_cross_token_burn_adds_to_B`
(added in Phase 5e).

Existing case-study verdict matrix is preserved because none of the
five YAMLs declare `cross_token_flows` yet — the feature is dormant
on those examples until they are migrated in a follow-up.

## Lean stub

```lean
-- File: TEVerifier/CrossToken.lean
import Mathlib.Algebra.BigOperators.Basic

theorem cross_token_E_additive
    {ι : Type} (own_rates : ι → ℝ) (xt_rates : ι → ℝ) :
    (Finset.univ.sum own_rates) + (Finset.univ.sum xt_rates)
    = Finset.univ.sum (fun i => own_rates i + xt_rates i) := by
  rw [Finset.sum_add_distrib]
```
