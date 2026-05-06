# Conditional rules — three-valued static evaluation

> **Status.** Phase B2+B3 — implemented for FM1 and FM3.

## Statement

A `Rule.trigger.conditions` list is a conjunction (AND) of structured
predicates. Each predicate evaluates to one of three states over the
declared parameter box:

> `ALWAYS` — the predicate holds for **every** assignment in the box
>
> `EVER`   — the predicate holds for **at least one** assignment
>
> `NEVER`  — the predicate holds for **no** assignment

The rule's contribution to the symbolic E or B sum is gated on the
status with **side-correct conservatism**:

> Emission rule:  contribute iff status ≠ NEVER  (over-conservative)
>
> Burn rule:      contribute iff status = ALWAYS (under-conservative)

This double-conservativity preserves the soundness of the existential
SMT semantics: any counterexample produced by `solver.check()`
remains a witness that the formal sustainability inequality is
violated by some assignment in the box, even after rule gating.

## Paper / Simulator references

The paper (§3) is single-rule and unconditional. The Simulator.pdf
references conditions implicitly in §2.6 ("threshold-driven burn:
B(t) = br if M(t) > M\*"); we generalize the encoding to arbitrary
conjunctions of three structured predicate types.

## Predicate types

### `ThresholdCondition(var, op, value)`

`var` is one of `t / M / Q / N / K / d`; `op` is one of
`< / <= / > / >= / ==`. `var ∈ [lo, hi]` is read from the IR (e.g. `Q`
from `participants.expected_Q`). The three-valued result for each
operator (proof in `verifier/conditions.py::_eval_threshold`):

| Predicate | ALWAYS iff | NEVER iff |
|---|---|---|
| `var > value` | `lo > value` | `hi <= value` |
| `var >= value` | `lo >= value` | `hi < value` |
| `var < value` | `hi < value` | `lo >= value` |
| `var <= value` | `hi <= value` | `lo > value` |
| `var == value` | `lo == value == hi` | `value < lo` or `value > hi` |

`var = M` (circulating supply) currently has no a-priori bound; the
evaluator returns `EVER` (conservative) for any threshold on `M`.

### `TimeWindow(start_period, end_period)`

A rule active during `[start, end]`. The horizon is `[0, 52]` (default
verification horizon).

| Window | Status |
|---|---|
| `start ≤ 0 and end ≥ 52` | ALWAYS |
| `start > 52 or end < 0` | NEVER |
| Otherwise | EVER |

### `EventOccurrence(source_token, source_event)`

The rule fires when `source_token` emits `source_event`. We look up
`source_token` in `te.tokens`; if missing → `NEVER`. If present with
a matching `trigger.event_predicate` or `trigger.kind` → `ALWAYS`.
Otherwise → `EVER`.

## Conjunction

Multiple conditions on a single rule combine as logical AND:

> `ALWAYS = all subconditions ALWAYS`
>
> `NEVER  = any subcondition NEVER`
>
> `EVER   = otherwise`

## Soundness proof

Define the "true" rate of a conditional rule as `r(t) · 𝟙[c(t)]`
where `c(t)` is the conjunction's truth value at time `t`.

**Emission side over-conservatism.** The verifier replaces
`r(t) · 𝟙[c(t)]` with `r(t)` whenever `c` is not statically NEVER.
For all `t`, `r(t) · 𝟙[c(t)] ≤ r(t)` (since `r(t) ≥ 0` and
`𝟙[c(t)] ∈ {0, 1}`). Therefore the symbolic `E_total` is an
**upper bound** on the true emission rate. FM1's violation predicate
is `E - B > Q`; an upper bound on `E` makes the violation easier to
satisfy. If Z3 returns unsat (PASS) on the upper-bound encoding, the
true system is also safe. ∎

**Burn side under-conservatism.** The verifier replaces
`r(t) · 𝟙[c(t)]` with `r(t)` only when `c` is statically ALWAYS;
otherwise the rule's burn contribution is set to `0`. For all `t`,
`0 ≤ r(t) · 𝟙[c(t)]` (since `r(t) ≥ 0`). Therefore the symbolic
`B_total` is a **lower bound** on the true burn rate. FM3's
violation predicate is `B/E < ρ_floor`; a lower bound on `B` makes
the violation easier to satisfy. If Z3 returns unsat on the
lower-bound encoding, the true system is also safe. ∎

The combined effect: emission gets over-counted, burn gets
under-counted, and the verifier's PASS/FAIL verdict on the gated
encoding is sound with respect to the true conditional system.

## Z3 encoding

Pure-Python `verifier/conditions.py` decides per-rule contribution
*before* the Z3 sum is built. The Z3 query itself is unchanged from
the unconditional case — every contributing rule's term is a regular
`z3.ArithRef` over its parameter box.

## Numerical correctness

No new sources of slack: the gating is binary (include / exclude)
and operates on the unchanged per-rule rate computation.

## Tests

- `tests/test_conditional_rules.py::test_threshold_always_includes_rule`
- `tests/test_conditional_rules.py::test_threshold_never_excludes_rule`
- `tests/test_conditional_rules.py::test_threshold_ever_includes_emission`
- `tests/test_conditional_rules.py::test_threshold_ever_excludes_burn`
- `tests/test_conditional_rules.py::test_time_window_outside_horizon_excludes_rule`
- `tests/test_conditional_rules.py::test_event_occurrence_missing_source_excludes_rule`
- `tests/test_conditional_rules.py::test_conjunction_any_never_excludes`
- `tests/test_conditional_rules.py::test_back_compat_no_conditions_acts_as_always`

## Lean stub

```lean
-- File: TEVerifier/ConditionalRules.lean
theorem emission_upper_bound
    (r : ℝ) (hr : 0 ≤ r) (active : Bool) :
    r * (if active then 1 else 0) ≤ r := by
  cases active <;> simp <;> linarith

theorem burn_lower_bound
    (r : ℝ) (hr : 0 ≤ r) (active : Bool) :
    (0 : ℝ) ≤ r * (if active then 1 else 0) := by
  cases active <;> simp <;> linarith
```
