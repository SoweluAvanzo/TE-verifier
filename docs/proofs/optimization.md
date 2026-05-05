# Threshold extraction in Tier-1

## Statement

For every closed-form FM violation predicate `V(x; θ)` (where `θ` is a
parameter we want a critical value for and `x` are the other declared
parameters), the verifier returns

> `θ* = sup { θ : ∃ x ∈ X. V(x; θ) }`   (or `inf`, depending on direction)

up to the `numeric_epsilon` tolerance defined in
`verifier.config.VerifierConfig.numeric_epsilon`.

## Paper reference

Calibration / encoding theorem — not stated by the source paper. The
correctness reference is Bjørner, Phan, Fleckenstein, *νZ — An
Optimizing SMT Solver* (TACAS 2015), which defines the `Optimize` API
the primitive in `verifier/failure_modes/base.py` exposes.

## Assumptions

1. **(Monotone closed-form for FMs in Tier-1.)** Every FM critical
   value is a monotone polynomial in its variables on the declared
   non-negative box. This includes `2·K·d + 1` (FM5), `(T − R)/S`
   (FM4), `d/φ` (FM4), `Q_lo` (FM1), and the integer expression
   `⌈U − T·Γ_threshold⌉` (FM6).
2. **(Bounded variables.)** Every variable has a declared `NumberRange`
   or a derived bounded range. This guarantees the optimizer's
   feasibility region is bounded and the supremum/infimum is attained
   at a corner.
3. **(Strict / non-strict inequalities.)** The encoding uses `<` for
   strict and `≤` for non-strict; Z3 reasons over rationals exactly,
   preserving the distinction.

## Proof

For each FM, the worst-case critical value is the extremum of a
**monotone** polynomial on a non-negative box. By monotonicity:

> If `f(x_1, ..., x_n)` is non-decreasing in each `x_i ≥ 0` and the
> domain is `∏_i [a_i, b_i]`, then `max f = f(b_1, ..., b_n)` and
> `min f = f(a_1, ..., a_n)`.

This is standard real analysis (every coordinatewise-monotone function
on a compact box attains its extrema at corners; see Rudin's
*Principles of Mathematical Analysis*, §4.16).

Because corners of the box are reached by direct substitution, the
critical-value formulas are evaluated **without invoking the Z3
optimizer** in Tier-1. This avoids Z3's known performance ceiling on
nonlinear real arithmetic over wide ranges.

The optimization primitive `optimize_threshold` is preserved in
`verifier/failure_modes/base.py` for cases where:

1. The constraints are non-monotone (anticipated in Phase 5 with
   regime predicates that introduce piecewise behavior),
2. Integer variables interact with rational ones (for which `νZ`'s
   mixed-integer-arithmetic engine is the canonical tool), or
3. Tests need a tool-independent check that closed-form formulas
   agree with `νZ`'s reported optimum.

## Critical-value formulas

| FM | Parameter | Direction | Formula | Source |
|---|---|---|---|---|
| FM1 | `net_emission` | `<=` | `E_net* = Q_lo` | Closed-form (monotone in Q) |
| FM2 | `tau_bar` | `>=` | `τ̄* = config.tau_bar_velocity_trap_ceiling` | Configurable |
| FM3 | `rho` | `>=` | `ρ* = config.rho_burn_coverage_floor` | Configurable |
| FM4 | `gamma` | `>=` | `γ* = (T − R) / S_lo` | Closed-form |
| FM4 | `K` | `>=` | `K* = d_hi / φ_lo` | Closed-form |
| FM4 | `phi` | `>=` | `φ* = d_hi / K_lo` | Closed-form |
| FM5 | `N` | `>=` | `N* = 2·K_hi·d_hi + 1` | Closed-form (monotone) |
| FM5 | `K` | `<=` | `K* = (N_lo − 1)/(2·d_hi)` | Closed-form |
| FM6 | `Gamma` | `<=` | `Γ* = config.gamma_capture_threshold` | Configurable |
| FM6 | `n_demote` | `>=` | `n_demote* = max(0, ⌈U − T·Γ*⌉)` | Closed-form (integer) |

Each formula is derived in the corresponding `fm{n}.md` file.

## Z3 encoding

The threshold-extraction primitive lives in
`verifier/failure_modes/base.py::optimize_threshold`. Sketch:

```python
def optimize_threshold(
    constraints: list[z3.BoolRef],
    target: z3.ArithRef,
    direction: Literal["max", "min"],
) -> float | None:
    opt = z3.Optimize()
    for c in constraints:
        opt.add(c)
    if direction == "max":
        opt.maximize(target)
    else:
        opt.minimize(target)
    if opt.check() != z3.sat:
        return None
    return z3_value_to_float(opt.model().eval(target, model_completion=True))
```

`opt.maximize(target)` returns a `z3.OptimizeObjective` handle whose
`upper()` and `lower()` bounds carry the extremum. `model.eval(target,
model_completion=True)` returns the same value at the optimal model;
we use the model-evaluation path because it handles the corner cases
(`+oo`, `epsilon` modifiers) by returning a concrete numeric.

## Numerical correctness

Z3 reasons over `ℚ` exactly. The optimizer's reported optimum is an
exact rational; `z3_value_to_float` converts via numerator/denominator
division (one rounding ulp ~2.2e-16 for `float64`). This is well
within `config.numeric_epsilon` (1e-9 default).

For the closed-form path used in Tier-1, the only numerical operations
are floating-point divisions and ceiling-of-rational; both are exact
within IEEE 754 modulo the standard rounding error which is below
`numeric_epsilon`.

## Lean stub

```lean
-- File: TEVerifier/Optimization.lean
import Mathlib.Order.Bounds.Basic
import Mathlib.Data.Real.Basic

theorem monotone_corner_extremum
    {n : ℕ} (f : (Fin n → ℝ) → ℝ)
    (hmono : ∀ i x y, x i ≤ y i → f x ≤ f y)
    (a b : Fin n → ℝ) (hab : ∀ i, a i ≤ b i) :
    ⨆ x ∈ Set.Icc a b, f x = f b := by
  sorry
```

## Tests

Implemented in `tests/test_threshold_extraction.py`:

- `test_optimize_threshold_max_simple` — small linear case, exact answer.
- `test_optimize_threshold_min_linear` — linear minimum, exact answer.
- `test_optimize_threshold_unsat_returns_none` — empty feasibility region.
- `test_fm{1..6}_*_closed_form` — the closed-form formulas evaluated
  on synthetic IRs with hand-computable thresholds.
- `test_case_study_critical_values_populated` — every non-N/A verdict
  carries critical_values.
- `test_case_study_failed_verdicts_have_recommendation` — every FAIL
  carries a numeric recommendation (or has a documented exemption).
