# FM5 — Insufficient Critical Mass

> **Status.** Phase 1 — full derivation.

## Statement

For a well-mixed token economy with `N` participants, offer variety `K`,
and per-participant demand `d`, the system is sustainable in the
matching-probability sense iff

> `N ≥ 2·K·d + 1`.

For spatially structured or networked topologies, the bound is a
**conservative upper bound** — local reciprocity may sustain exchange
below it. The verifier reports `INCONCLUSIVE` (not `FAIL`) for
non-well-mixed topologies that fall below the bound.

## Paper reference

§3.5, eqs. (19)–(21).

## Assumptions

1. **(Well-mixed.)** Any participant can transact with any other with
   equal probability. Paper §3.5.
2. **(Double coincidence of wants.)** A successful exchange requires
   both parties to want each other's offer types; the probability of
   that is `1/K`. Paper §3.5.
3. **(Per-period demand independence.)** Each participant's `d`
   redemption events are independent of others'. Paper's simplifying
   assumption.

## Proof

The number of unordered participant pairs in a population of size
`N` is `N(N − 1)/2`. Under assumption (1) any pair can transact;
under assumption (2) a pair successfully transacts only when the two
sides want each other's offer types, which happens with probability
`1/K` (each side independently chooses among `K` types under the
double-coincidence model in §3.5).

The expected number of successful matches per period is therefore

> `M(N, K) = N(N − 1) / (2K)`.

Aggregate demand per period under assumption (3) is

> `D(N, d) = N · d`.

Sustainable matching requires `M(N, K) ≥ D(N, d)`. Substituting,

> `N(N − 1) / (2K) ≥ N · d`
>
> ⟺  `(N − 1) / (2K) ≥ d`     (dividing by `N > 0`)
>
> ⟺  `N − 1 ≥ 2 K d`
>
> ⟺  `N ≥ 2 K d + 1`.   ∎

## Worst-case critical value

The function `f(K, d) = 2 K d + 1` is monotone non-decreasing in each
of `K, d` on `K, d ≥ 0`. By the corner-extremum lemma in
`docs/proofs/optimization.md`, the maximum of `f` on
`[K_lo, K_hi] × [d_lo, d_hi]` is `f(K_hi, d_hi) = 2 K_hi d_hi + 1`.

Therefore the *worst-case* critical participant count over the
declared ranges is

> `N* = 2 K_hi d_hi + 1`.

Symmetrically, the largest `K` the system can support given the
declared `N` and `d` ranges is

> `K* = (N_lo − 1) / (2 d_hi)`     when `d_hi > 0`.

If `d_hi = 0` the system is structurally unconstrained on `K` because
no demand exists; the verifier returns `None` in this case and the
verdict explanation reflects it.

## Critical-value formulas

| Parameter | Direction | Formula | Verifier source |
|---|---|---|---|
| `N` | `≥` | `N* = 2 K_hi d_hi + 1` | Closed-form (corner of monotone polynomial) |
| `K` | `≤` | `K* = (N_lo − 1) / (2 d_hi)` (if `d_hi > 0`) | Closed-form |

## Topology correction (Phase 5)

For `topology = spatial` or `network`, the well-mixed bound is
conservative. Phase 5 introduces a degree-corrected variant
`N* = 2K·d + 1 − f(degree)` where `f` is bounded by `2K·d`.
Justification and proof land in `docs/proofs/topology.md` (Phase 5).

## Z3 encoding

`verifier/failure_modes/fm5_critical_mass.py` declares `N, K, d` as
`z3.Real` bounded by their declared `NumberRange`s and asserts the
violation `N < 2*K*d + 1`. The existential check produces a counter-
example. Critical values are computed in **closed form** (not via Z3
optimization): the `N*` formula evaluates `2 K_hi d_hi + 1`
directly, and `K*` evaluates `(N_lo − 1)/(2 d_hi)`. Z3's nonlinear
optimizer is too slow on wide rational ranges to make optimization
the right primitive here; the closed form is provably equivalent
(see Worst-case critical value section above).

For `topology != well_mixed`, the well-mixed bound is conservative
and the verifier returns `INCONCLUSIVE` rather than `FAIL`.

## Numerical correctness

Closed-form arithmetic over IEEE 754; no Z3 optimization slack. Bounds
on `K_hi`, `d_hi` come from validated `NumberRange` instances that
guarantee `min ≤ max`.

## Numerical correctness

Polynomial in three variables — exact in Z3 modulo `numeric_epsilon`.

## Lean stub

```lean
-- File: TEVerifier/FM5.lean
import Mathlib.Data.Real.Basic
import Mathlib.Data.Nat.Basic

theorem fm5_well_mixed_threshold (N K : ℕ) (d : ℝ)
    (hd : 0 ≤ d) (hN : 1 ≤ N) (hK : 1 ≤ K) :
    -- well-mixed sustainability ↔ N ≥ 2K·d + 1
    sorry := by
  sorry
```

## Tests

- `tests/test_unit_failure_modes.py` — original FM5 unit coverage.
- `tests/test_case_studies.py` — regression on five case studies.
- `tests/test_threshold_extraction.py::test_fm5_n_star_closed_form`
  — synthetic IR; `N*` extracted matches `2 K_hi d_hi + 1` exactly.
- `tests/test_threshold_extraction.py::test_fm5_n_star_passes_when_n_above_threshold`
  — `critical_values` populated even on PASS verdicts (margin signal).
