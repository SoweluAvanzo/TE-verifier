# FM2 — Token Velocity Trap

> **Status.** Phase 1 — full derivation.

## Statement

Let `M_i / M` be the fraction of circulating supply held by agent type
`i`, and `E_i[τ]` the expected holding time of that agent type. The
**wealth-weighted average holding time** is

> `τ̄ = Σ_i (M_i / M) · E_i[τ]`.

The system is in the velocity trap iff

> `τ̄ ≤ τ_ceiling`

where `τ_ceiling = config.tau_bar_velocity_trap_ceiling` (default 1.5,
configurable; see `verifier/config.py`).

The paper writes the condition asymptotically as `τ̄ → 1`; the
verifier uses a configurable conservative ceiling so that the
design-stage check is decidable in finite Z3 reasoning.

## Paper reference

§3.2, eqs. (9)–(12). The wealth-weighted decomposition is the paper's
"MicroVelocity" formulation.

## Assumptions

1. **(Per-agent holding time independent of supply.)** Each agent
   type's `E_i[τ]` is taken as an exogenous behavioral parameter at
   design stage. Paper §3.2.
2. **(Wealth weights sum to 1.)** `Σ_i M_i/M = 1`. Definitional.
3. **(Velocity-from-holding-time bound.)** Jensen's inequality gives
   `V ≥ 1/τ̄`. Paper eq. (10). This is what makes a low τ̄
   structurally bad: it forces a high lower bound on velocity.

## Proof

**Convex-combination bounds.** Since the weights `M_i / M ≥ 0` sum
to 1 (assumption 2), τ̄ is a convex combination:

> `min_i E_i[τ]  ≤  τ̄  ≤  max_i E_i[τ]`.

**Velocity lower bound (Jensen).** The function `f(τ) = 1/τ` is
convex on `τ > 0`. Jensen's inequality applied with weights `M_i/M`
gives

> `Σ_i (M_i/M) · (1 / E_i[τ])  ≥  1 / Σ_i (M_i/M) · E_i[τ]  =  1 / τ̄`.

The left-hand side is the wealth-weighted velocity decomposition
(paper §3.2 eq. 11), so

> `V ≥ 1 / τ̄`.

**Trap interpretation.** `τ̄ → 1` forces `V → 1` from below, which
is the per-period upper bound on velocity (a token cannot turn over
more than once per period if periods are the unit of time-step). The
trap is reached when participants spend tokens essentially on
receipt — `τ_i → 1` for every agent type, and therefore `τ̄ → 1`. ∎

**Discrete proxy.** The asymptotic statement `τ̄ → 1` is undecidable
at design stage. The verifier checks the discrete proxy

> `τ̄  ≤  τ_ceiling`

with `τ_ceiling = config.tau_bar_velocity_trap_ceiling` (default 1.5,
configurable). This captures systems whose τ̄ is within 50% of the
trap regime. The user can tighten the proxy via config override; the
proxy is monotone (lowering `τ_ceiling` only changes verdicts in the
direction PASS → FAIL, never the reverse).

## NFR6 reweighting

When `meta.nfrs.circulation_speed = circulate_fast`, the verdict for a
violation is `PASS_AS_INTENDED` rather than `FAIL`. Justification: the
user has declared that high velocity is the design goal; finding it
is confirmation, not failure. The Verdict's
`status_change_reason` field records the NFR that triggered the
reclassification, so the user knows the structural finding stands and
only the verdict label was reweighted.

> **Proof obligation (Phase 5):** prove that this reweighting is
> monotone — i.e. setting NFR6 = circulate_fast cannot turn a passing
> token into a failing one, only the reverse.

## Critical-value formula

`τ̄* = τ_ceiling`. The redesign hint identifies which agent types are
dragging τ̄ below the ceiling and what holding-incentive mechanism
choices (Phase 2) would lift their `E_i[τ]`.

## Z3 encoding

`verifier/failure_modes/fm2_velocity.py` declares per-agent τ as Z3
reals bounded by `expected_holding_time.expected_periods`, computes
`τ̄ = Σ_i w_i · τ_i` symbolically, and asserts the violation
`τ̄ ≤ τ_ceiling`. Phase 1 adds optimization to find the per-agent τ
assignment that makes τ̄ closest to the ceiling.

## Numerical correctness

Sum-of-products of bounded rationals. Exact in Z3 modulo
`numeric_epsilon`.

## Lean stub

```lean
-- File: TEVerifier/FM2.lean
import Mathlib.Analysis.MeanInequalities
import Mathlib.Data.Real.Basic

theorem fm2_velocity_lower_bound (n : ℕ) (w τ : Fin n → ℝ)
    (hw_pos : ∀ i, 0 ≤ w i) (hw_sum : (Finset.univ.sum w) = 1)
    (hτ_pos : ∀ i, 0 < τ i) :
    -- V ≥ 1 / τ̄ via Jensen on 1/x
    sorry := by
  sorry
```

## Tests

- `tests/test_unit_failure_modes.py` — original FM2 unit coverage.
- `tests/test_threshold_extraction.py::test_fm2_tau_bar_critical_is_ceiling`
  — verifies `critical_values["tau_bar"]` equals `τ_ceiling`.
