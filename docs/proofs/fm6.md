# FM6 — Governance Capture

> **Status.** Phase 1 — full derivation.

## Statement

For a token economy with governance rule structure assigning each of
`T` decision levers to a controlling actor (single entity, committee,
token-holder vote, smart contract, or not adjustable), let `U` be the
number of decisions controlled unilaterally (single entity or
committee). Define the **centralization index**

> `Γ = U / T`.

The system is sustainable in the governance-distribution sense iff

> `Γ ≤ Γ_threshold`

where `Γ_threshold = config.gamma_capture_threshold` (default 0.5).

A secondary signal: `G > G_secondary_threshold` (token-balance Gini
above a configurable threshold, default 0.6) flags FM6 even when Γ is
low, because concentrated holdings produce effective single-actor
control in token-vote DAOs.

## Paper reference

§3.6, eq. (22). The Gini secondary signal is qualitative in the paper;
its threshold is a calibration with paper citation in `config.py`.

## Assumptions

1. **(Discrete decision levers.)** The governance rule structure is a
   finite list of distinct decision types. Paper §3.6 enumerates 7+;
   the verifier uses the user's declared list.
2. **(Unilateral = single_entity ∪ committee.)** Paper §3.6 defines
   unilateral as "decisions that can be taken unilaterally by a single
   actor or small group." Committee qualifies as a small group.
3. **(Token-balance Gini orthogonal to Γ.)** A system can have low Γ
   on paper but high effective Γ if vote weight is balance-weighted
   and balances are concentrated. Paper §3.6 last paragraph.

## Proof

`Γ = U/T` is a definitional fraction. The paper's sustainability
condition is `Γ ≤ Γ_threshold` (§3.6 eq. 22 with `Γ_threshold = 0.5`
in the published default). Violation iff `U/T > Γ_threshold`, i.e.
`U > T · Γ_threshold`. The contrapositive is the sustainability
predicate the verifier checks.

The Gini secondary signal is a projection of token-balance distribution
onto the same governance-capture axis; the verifier flags either
channel independently. The two are decoupled because nothing in
§3.6's text claims `G > 0.6 ⟹ Γ > 0.5` or vice versa — the channels
are alternative routes to capture. ∎

## Critical-value formulas

- `Γ* = Γ_threshold` — the configurable threshold.
- `n_demote* = ⌊T/2⌋ + 1 − U` — minimum number of currently-unilateral
  decisions that must be demoted to non-unilateral control to bring
  `Γ` to or below `Γ*`. This is integer programming; Z3 supports
  `Int` directly.

**Proof.** By definition `Γ = U / T`. Demoting `n` decisions
(transferring `n` decisions from unilateral to non-unilateral control)
changes `U` to `U − n`. Sustainability post-demotion requires

> `(U − n) / T ≤ Γ_threshold`,

i.e.

> `n ≥ U − T · Γ_threshold`.

The smallest non-negative integer `n` satisfying this is

> `n_demote* = max(0, ⌈U − T · Γ_threshold⌉)`.

The `max(0, ·)` term handles the already-passing case (`U ≤ T ·
Γ_threshold` ⟹ no demotion needed). The ceiling handles the
non-integer right-hand side that arises whenever `T · Γ_threshold` is
not an integer (e.g. `T = 9, Γ_threshold = 0.5`).

When `Γ_threshold = 0.5` (the paper default) and `T` is even, we have
`T · 0.5 = T/2` (integer), so `⌈U − T/2⌉ = U − T/2`. When `T` is odd,
`T · 0.5 = T/2 + 0.5` and `⌈U − T/2 − 0.5⌉ = U − ⌊T/2⌋`. Both forms
agree: `n_demote* = U − ⌊T · Γ_threshold⌋` for `Γ_threshold = 0.5`. ∎

**Implementation note.** The verifier uses `math.ceil(U − T ·
Γ_threshold)` directly (configurable threshold), not the `⌊T/2⌋`
form, so any user override of `gamma_capture_threshold` works
correctly for non-half values.

## NFR7 reweighting

When `meta.nfrs.governance_maturity = indefinite` AND `governance.type
= centralized`, the FM6 verdict is `PASS_AS_INTENDED` rather than
`FAIL`. Justification: the user has declared centralized governance is
appropriate for the foreseeable future; finding it is consistent
design, not capture.

> **Proof obligation (Phase 5):** prove that this reweighting is
> consistent with NFR6's reweighting (FM2) — i.e. the two reweightings
> cannot interact perversely.

## Z3 encoding

`verifier/failure_modes/fm6_governance.py` computes Γ directly from
`governance.rule_structure` (no Z3 needed for the primary signal — it's
a counting expression). Phase 1 adds Z3 `Int` programming to compute
`n_demote*`. The Gini secondary signal is a single comparison.

## Numerical correctness

Counting and integer comparisons — exact.

## Lean stub

```lean
-- File: TEVerifier/FM6.lean
import Mathlib.Data.Nat.Basic

theorem fm6_n_demote_correct (T U : ℕ) (h : U ≤ T) :
    -- minimum demotions to bring U/T ≤ 1/2
    sorry := by
  sorry
```

## Tests

> *Phase 1 obligation.*
>
> - Existing FM6 tests.
> - `tests/test_threshold_extraction.py::test_fm6_n_demote` —
>   synthetic rule_structure with known unilateral count; assert
>   `critical_values["n_demote"]` matches the analytical formula.
