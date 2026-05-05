# Threshold cross-check plan

Hardening proposal for the closed-form / `optimize_threshold` discrepancy
risk surfaced while reviewing `verifier/failure_modes/`. Companion to
`docs/proofs/optimization.md`.

## Motivation

Every shipped `CriticalValue` in `verifier/failure_modes/fm*.py` carries
`source="closed_form"` or `source="config"`. The `optimize_threshold`
primitive at `verifier/failure_modes/base.py:196` (built on
`z3.Optimize` / νZ) is implemented and tested but is not invoked on any
production code path. `fm5_critical_mass.py:29` imports it without
calling it.

The closed-form answers are correct **iff** the per-FM violation surface
is monotone in each declared parameter across the entire declared box —
the corner of the box is then the extremum. The proofs in
`docs/proofs/fm{1..6}.md` carry this argument FM-by-FM.

This is sound for the IR shape currently exercised by the five case
studies. It becomes fragile as the IR grows toward the richer
modeling shapes the architecture anticipates:

1. **Piecewise / regime-switch rules.** Worst case can sit at a
   breakpoint, not at a corner of the box.
2. **Composed (event-arrival × per-event-emission) asymptotic classes.**
   Cross-terms can break per-axis monotonicity.
3. **Multi-token cross-token coupling** (e.g. one token's emission
   triggered by another's burn). Per-FM closed-forms are token-local.

If any of these silently violates the monotonicity invariant, the
user-facing threshold is wrong and no test catches it. The fix is not
to replace the closed-form (it is faster, more actionable, and works on
nonlinear classes where Z3 is incomplete) but to **assert it agrees
with `optimize_threshold` on the same encoding** under a flag.

## Invariant to check

For every `CriticalValue cv` with `source="closed_form"`, on the same
constraint set the FM passed to `solver.check()`, the following must
hold within `VerifierConfig.numeric_epsilon`:

```
optimize_threshold(constraints, cv_target_expr, cv.direction) ≈ cv.value
```

When `optimize_threshold` returns `None` (Z3 incomplete on the encoding,
or unbounded), that is **not** a failure of the cross-check — it is the
case the closed-form path is designed to handle. Record it as
`skipped_unbounded` rather than `disagreement`.

## Implementation sketch

### 1. New config flag

`VerifierConfig` (in `verifier/config.py`) gains:

```python
threshold_cross_check: Literal["off", "warn", "strict"] = "off"
```

- `off` — production default, current behavior.
- `warn` — run νZ alongside closed-form, log discrepancies, do not fail.
- `strict` — raise `ThresholdDisagreement` on any disagreement.

### 2. FM refactor

Each FM that currently constructs a `CriticalValue` with
`source="closed_form"` needs to expose, at the point of construction:

- the list of `z3.BoolRef` constraints that bound the feasibility
  region for that threshold (a subset of what is already added to
  `solver`),
- the `z3.ArithRef` target expression (e.g. `E_total - B_total` for
  FM1, `2*K_var*d_var + 1` for FM5),
- the `direction` (`"max"` or `"min"`).

Concrete touch points:

| FM | File | Closed-form site | Target expr |
|----|------|------------------|-------------|
| FM1 | `fm1_oversupply.py:149` | `E_net* = Q_lo` | `E_total - B_total` (max) over `Q ∈ [Q_lo, Q_hi]` |
| FM3 | `fm3_burn_emission.py:103, 180, 325` | `ρ* = 1 - g/E` | `B_total / E_total` (min) |
| FM4 | `fm4_freerider.py:165, 185, 204` | Ostrom corner, monitoring corner | `φ - d/K` (min), `γ·S - (T - R)` (min) |
| FM5 | `fm5_critical_mass.py:71` | `n_star = 2·K_hi·d_hi + 1` | `2*K_var*d_var + 1` (max) |
| FM6 | `fm6_governance.py:135` | analytic Γ | per-decision sum (max) |

FM2 thresholds are `source="config"` (the τ̄ ceiling is paper-derived,
not box-derived), so no cross-check is required.

### 3. Cross-check helper

In `verifier/failure_modes/base.py`, add:

```python
def cross_check_threshold(
    constraints: list[z3.BoolRef],
    target: z3.ArithRef,
    direction: Literal["max", "min"],
    closed_form_value: float,
    label: str,
    config: VerifierConfig,
) -> Literal["agree", "skipped_unbounded", "disagreement"]:
    ...
```

It calls `optimize_threshold`, compares against `closed_form_value`
within `config.numeric_epsilon`, and dispatches per `threshold_cross_check`
mode. On `strict` it raises; on `warn` it logs structured JSON
(label, closed_form, optimum, delta) so CI can grep for drift.

### 4. CI wiring

A new pytest module `tests/test_threshold_cross_check.py` runs every
example in `examples/` with `threshold_cross_check="strict"` and asserts
agreement. This is the runtime realization of the per-FM monotonicity
proofs. It will live under a `pytest -m crosscheck` mark to keep the
default suite under the current ~1 s budget.

### 5. Counterexample for disagreement

When `cross_check_threshold` reports `disagreement`, the structured log
includes:

- the FM name and subject,
- the closed-form value,
- νZ's optimum,
- the model νZ found at its optimum (so the engineer can see which
  parameter assignment broke monotonicity).

This is the most actionable artifact: it is the witness that the
closed-form proof is wrong for the current encoding.

## Out of scope for this plan

- Lean mechanization of monotonicity lemmas. The cross-check is a
  *runtime* assertion; mechanized proofs (Tier-2, see
  `docs/proofs/`) remain a separate track.
- Replacing closed-form with νZ on production paths. Closed-form stays
  the user-facing source — it is faster and works on encodings where
  Z3 is incomplete.
- `source="config"` thresholds (FM2 ceiling, etc.). These are
  paper-derived constants, not box-derived; cross-check does not apply.

## Open questions

1. **Granularity of the constraint subset.** For FM1, the cross-check
   wants to maximize `E_total - B_total` over the declared rule
   parameter ranges with `Q` free. Does the current
   `rule_rate_per_period` encoding (`verifier/asymptotic.py`) support
   detaching from `Q`? If not, the helper has to rebuild a parallel
   encoding, doubling the surface area to maintain.
2. **Nonlinear timeouts.** For exponential / high-degree polynomial
   classes, `z3.Optimize` may timeout rather than return `None`. We
   need an explicit timeout in the helper and a `skipped_timeout`
   classification distinct from `skipped_unbounded`.
3. **Multi-token mixed-profile pass.** This plan covers per-FM
   per-token cross-checks. The final mixed-profile evaluation pass
   (run after all token interactions are known) is the regime where
   monotonicity is *most* likely to fail and is not addressed here.
   A second iteration of this plan should target that pass once it
   lands.
