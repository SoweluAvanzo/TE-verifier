# Coupled cross-token flows (proportional_to_source)

> **Status.** Phase B1 — implemented for FM1 and FM3.

## Statement

A cross-token flow `f` from `source_token = S` to `target_token = T`
with `coupling = PROPORTIONAL_TO_SOURCE` and `coupling_ratio ∈ [r_lo, r_hi]`
contributes a per-period rate

> `rate(f, t) = r · E_own(S, t),    r ∈ [r_lo, r_hi]`

to `T`'s emission (when `target_action = MINT`) or burn (when
`target_action = BURN`), where

> `E_own(S, t) = Σ_{ρ ∈ S.emission_rules} rate(ρ, t)`

is the source token's per-period rate from its **own** emission rules
only — explicitly excluding any cross-token contributions into `S`.

## Paper / Simulator references

- Paper §3.3: cross-token couplings are mentioned as a multi-token
  generalization but not formalized.
- `Simulator.pdf` §3.3 eq (8) treats initial distribution as additive
  with E(t); §2.6 burn rules are additive. Coupled flows are **the
  multi-token generalization** of those additive sums: when one token's
  E feeds another's E or B, we still preserve linearity.

## Why excluding transitive cross-token contributions

Defining `E_own(S)` to use only `S.emission_rules` (and not `S`'s
cross-token MINTs) is what makes the dependency graph **acyclic by
construction**. If `E_own(S)` included cross-token MINTs into `S`,
then a flow `T → S` proportional to `E(T)` and a flow `S → T`
proportional to `E(S)` would form a feedback loop with no fixed point
in general.

The current restriction reads "the *primary* mint flow of the source
token drives the coupled flow", which matches the canonical use cases
(MakerDAO stability fees → MKR buyback; Curve fee revenue → veCRV
distribution): the primary action is the source's own emission, and
the coupled flow is the consequence of that emission.

A future extension can lift this restriction by introducing an
explicit fixed-point operator (Tarski) over the coupled-flow lattice;
that work is deferred to Tier-2.

## Assumptions

1. **Acyclic dependency graph.** Flows are proportional only to the
   source's `emission_rules`-derived rate; never to the source's
   cross-token-fed rate. Enforced structurally by
   `verifier.asymptotic.own_emission_rate_per_period`.
2. **Bounded ratio.** `coupling_ratio` is a `NumberRange` with finite
   `min` and `max`; Z3 declares one fresh real per flow and constrains
   it to that range.
3. **Sign correctness inherited from composition.md.**
   `target_action ∈ {MINT, BURN}` places the contribution on the right
   side of `Ṁ = E − B`. `TRANSFER` flows are still ignored.

## Proof (rate well-definedness)

The map `flow ↦ r · E_own(source)` with `r ∈ [r_lo, r_hi]` and
`E_own ≥ 0` is a continuous function on a compact box and therefore
attains its supremum and infimum. The Z3 encoding searches over both
`r` and the parameters of `E_own`'s asymptotic class jointly; any
counterexample produced by `solver.check()` is a witness that the
combined inequality is satisfiable somewhere in the joint box. ∎

## Z3 encoding

`verifier/asymptotic.py` adds two helpers:

```python
def own_emission_rate_per_period(solver, name_prefix, token, ...):
    # Sum of rule_rate_per_period over token.emission_rules only.

def cross_token_flow_rate(solver, name_prefix, flow, source_own_E, ...):
    if flow.coupling == FlowCoupling.PROPORTIONAL_TO_SOURCE:
        ratio = z3.Real(name_prefix + "__ratio")
        solver.add(ratio >= flow.coupling_ratio.min,
                   ratio <= flow.coupling_ratio.max)
        return ratio * source_own_E
    return average_rate_per_period(solver, name_prefix, flow.amount)
```

`fm1_oversupply.py` and `fm3_burn_emission.py` precompute
`source_own_E` per source token (one fresh symbolic E per source per
FM evaluation, named for the FM context) and pass it into
`cross_token_flow_rate` for every flow whose `target_token` matches
the token under check.

## Numerical correctness

Adding a multiplicative term `r · E_own` introduces no new sources of
slack: both factors are bounded `z3.ArithRef` expressions, and Z3
reasons over `ℚ` exactly. The Z3 `Optimize` engine continues to find
extrema via νZ.

## Worked example

MakerDAO's MKR buyback: stability fees on DAI mint pay for MKR
burns at roughly the same rate.

```yaml
tokens:
  - id: DAI
    emission_rules:
      - { trigger: { kind: behavioral_event, ... },
          function: { sign: always_positive,
                      asymptotic_class: { family: linear, ... } } }
  - id: MKR
    emission_rules: []     # MKR is not minted from rules
    burn_rules: []         # MKR's *own* burn rules are zero
cross_token_flows:
  - source_token: DAI
    source_event: stability_fee_collection
    target_token: MKR
    target_action: burn
    coupling: proportional_to_source
    coupling_ratio: { min: 0.4, max: 0.6 }
    amount: { family: constant }   # ignored when coupling != independent
```

Under this spec, MKR's `B(t) = r · E_own(DAI)` with `r ∈ [0.4, 0.6]`.
FM3 evaluates `ρ = B/E` for MKR — since MKR's `E_own = 0`, ρ is
undefined; the FM3 short-circuit (`E ≠ 0` precondition) returns
`PASS` with the supply-stable explanation.

For the symmetric case where DAI also has a small own-emission and
MKR has its own emission too, the coupled flow becomes one term among
many in MKR's E or B sum; FM1 and FM3 still compose additively.

## Tests

- `tests/test_coupled_flows.py::test_independent_coupling_is_back_compat`
- `tests/test_coupled_flows.py::test_proportional_coupling_scales_with_source_E`
- `tests/test_coupled_flows.py::test_proportional_coupling_ratio_bounds_honored`
- `tests/test_coupled_flows.py::test_proportional_burn_coupling_lifts_rho`
- `tests/test_coupled_flows.py::test_missing_source_token_falls_back_to_zero`

## Lean stub

```lean
-- File: TEVerifier/CoupledFlows.lean
import Mathlib.Algebra.Order.Field.Basic

theorem proportional_flow_bounded
    (r_lo r_hi : ℝ) (h_r : r_lo ≤ r_hi) (E : ℝ) (hE : 0 ≤ E)
    (r : ℝ) (h1 : r_lo ≤ r) (h2 : r ≤ r_hi) :
    r_lo * E ≤ r * E ∧ r * E ≤ r_hi * E := by
  refine ⟨?_, ?_⟩ <;> nlinarith
```
