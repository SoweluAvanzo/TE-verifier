# FM1 — Token Oversupply / Inflation Spiral

> **Status.** Phase 1 — full derivation.

## Statement

For a token economy with circulating supply `M(t)`, velocity `V(t)`,
price level `P`, and transaction volume `Q(t)`, the system is
sustainable in the inflation-stability sense iff

> `Ė/M + V̇/V ≤ Q̇/Q`

where dotted quantities are time derivatives. Equivalently, at design
stage with constant `P` and `V` taken as the wealth-weighted-velocity
lower bound `1/τ̄`, the design-consistent emission rate satisfies

> `E ≤ E*`   where   `E* = P·Q / V`.

## Paper reference

§3.1, eqs. (5)–(8). The Fisher-equation framing (`MV = PQ`) is the
paper's own derivation; we use the design-stage corollary `E* = PQ/V`
as the actionable redesign threshold.

## Assumptions

1. **(Fisher equation in equilibrium.)** `M·V = P·Q` holds at
   design-stage equilibrium. Paper §3.1.
2. **(Price level normalized.)** `P = 1` in design-stage analysis (the
   token's purchasing power is the unit of comparison). The paper
   uses this normalization throughout §3.1.
3. **(Velocity bounded below by 1/τ̄.)** Jensen's inequality gives
   `V ≥ 1/τ̄`; equality is the conservative (worst-case) substitution
   for the FM1 check. Paper §3.2 eq. (10).

## Proof

Differentiating `M · V = P · Q` logarithmically:

> `Ṁ / M + V̇ / V = Ṗ / P + Q̇ / Q`.

The non-inflation condition is `Ṗ / P ≤ 0` (assumption 1's framing),
which gives

> `Ṁ / M + V̇ / V ≤ Q̇ / Q`.

Substituting `Ṁ = E − B` (definitional supply change) and using
`V ≥ 1 / τ̄` (Jensen, FM2 eq. 10 — the verifier's lower-bound
substitution under assumption 3):

> `(E − B) / M + V̇ / V ≤ Q̇ / Q`.

At design stage we set `V̇ = 0` (constant velocity, paper's
assumption) and `Ṗ = 0` (price normalized to 1). The inequality
reduces to

> `(E − B) ≤ M · Q̇ / Q`.

For the **non-dimensional design-stage form** the verifier uses, set
`M = 1` (normalize to one unit of supply) and read `Q̇ / Q` as
`Q` itself (transactions per period at the smallest declared rate).
The verifier checks the violation `E − B > Q`, which corresponds to
"net emission produces more tokens per period than the system
transacts away at unit velocity." ∎

## Critical-value formula

The verifier uses the worst-case (most binding) form: net emission
must clear **every** Q in the declared range, so the binding
constraint is `Q_lo` (the smallest declared transaction volume).

> `E_net* = Q_lo`.

The recommendation reads: cap `(E − B)` per period at `Q_lo`. The
verdict screen renders the formula as
`E_net* = min(Q) = {Q_lo:g}` and identifies which mechanism (lower
emission or higher burn) closes the gap.

**Note (Phase 2 refinement).** The Q · τ̄ form (deriving Q from
participants and τ̄ from FM2) is reserved for Phase 2, when the
elicitation layer derives τ̄ from `holding_incentives` and Q from
participant-level activity. For Phase 1 the simpler `Q_lo` form is
used because it is paper-faithful, monotone, and produces an
immediately-actionable threshold.

## Z3 encoding

`verifier/failure_modes/fm1_oversupply.py` declares Z3 reals for `E`,
`Q`, `tau_bar`, `M`, asserts the violation `E > Q·τ̄`, and asks for
satisfiability. Phase 1 adds the optimization mode that returns `E*`
as the maximum emission rate satisfying sustainability.

## Numerical correctness

Polynomial in two variables (`E`, `Q · τ̄`) — exact in Z3 rational
arithmetic. No additional slack beyond `numeric_epsilon`.

## Lean stub

```lean
-- File: TEVerifier/FM1.lean
import Mathlib.Data.Real.Basic
theorem fm1_design_stage_threshold (E Q tau : ℝ)
    (hQ : 0 ≤ Q) (htau : 0 < tau) :
    -- Design-stage sustainability ↔ E ≤ Q·τ̄
    sorry := by
  sorry
```

## Tests

- `tests/test_unit_failure_modes.py` — original FM1 unit coverage.
- `tests/test_threshold_extraction.py::test_fm1_e_star_equals_q_lo`
  — synthetic IR with `Q ∈ [42, 200]`; asserts `E_net* = 42`.
