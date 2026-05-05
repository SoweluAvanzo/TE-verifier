# Proof template

Every proof file in `docs/proofs/` follows this structure. The
sections are mandatory and appear in this order. Headings are level-2
(`##`); subsections are level-3 (`###`).

---

## Statement

The formal claim, as a single mathematical sentence. Includes the
universal/existential quantifiers and the domain of every variable.

> Example (FM5): For all `N ∈ ℕ_{≥1}`, `K ∈ ℕ_{≥1}`, `d ∈ ℝ_{≥0}`, the
> well-mixed token economy is sustainable in the matching-probability
> sense iff `N ≥ 2·K·d + 1`.

## Paper reference

The §-reference and equation numbers from the source paper. If the
claim is a calibration the paper does not pin down, this section
explicitly states "Calibration; paper is qualitative."

> Example: §3.5, eqs. (19)–(21).

## Assumptions

A numbered list of every assumption the proof relies on. Each
assumption has a short name (used by later sections to refer back) and
a one-line justification.

> Example:
>
> 1. **(Well-mixed)** Any participant can transact with any other with
>    equal probability. Justification: paper §3.5 first paragraph.
> 2. **(Double coincidence of wants)** A successful exchange requires
>    both parties to want each other's offer types. Justification:
>    paper §3.5 second paragraph.
> 3. **(Per-period demand independence)** Each participant's `d`
>    redemption events per period are independent of other participants'.
>    Justification: simplifying assumption stated by the paper.

## Proof

Rigorous mathematical English. Every step that is not algebraic
manipulation must cite an earlier step or an assumption. Substitutions
are explicit. Elided steps are spelled out enough that a competent
reader can fill them in without ambiguity.

If the claim depends on a closed-form algebraic manipulation, the
manipulation appears in full. If it depends on an external theorem
(e.g. "by Jensen's inequality"), the theorem is named and cited.

> Example sketch (FM5): The expected number of matches per period in a
> well-mixed population of `N` participants offering `K` types is
> `N(N−1)/(2K)` by counting unordered pairs and dividing by the offer
> diversity. For sustainability, this must meet aggregate demand `d·N`
> (each participant demands `d` redemptions per period). Setting
> `N(N−1)/(2K) ≥ d·N` and solving for `N` yields `N ≥ 2K·d + 1`. ∎

## Critical-value formula

If the claim has an associated boundary value (`γ*`, `K*`, etc.), this
section derives the closed-form formula from the sustainability
inequality. The formula is the one consumed by the Z3 optimization
layer for redesign-hint extraction.

> Example: From `N ≥ 2K·d + 1`, the critical participant count is
> `N* = 2K·d + 1`. By symmetry, `K* = (N − 1)/(2d)`.

## Z3 encoding

A short prose description of how the failure-mode module encodes the
violation predicate in Z3. Names the variables (linking to
`verifier.paper.PaperVariable` symbols), the constraints, and the
solver mode (`Solver` for satisfiability or `Optimize` for threshold
extraction).

> Example: `verifier/failure_modes/fm5_critical_mass.py` declares
> `N`, `K`, `d` as `z3.Real` bounded by their declared `NumberRange`s,
> asserts `N < 2*K*d + 1` (the violation), and asks for satisfiability.
> A satisfying model is a counterexample. For threshold extraction
> (Phase 1), we instead use `z3.Optimize` to maximize `N` subject to
> the violation, yielding `N*` as the boundary value.

## Numerical correctness

A statement that the Z3 encoding faithfully realizes the mathematical
claim, given Z3's exact reasoning over rationals. Cite Bjørner et al.
(2014) on the `νZ` optimization layer when threshold extraction is
involved. Identify any sources of numerical slack and bound them by
`config.numeric_epsilon`.

> Example: Z3 reasons over `ℚ` exactly; the only source of numerical
> slack is the `numeric_epsilon` boundary guard, which is 1e-9 by
> default. The encoding is exact within that tolerance.

## Lean stub

The Lean 4 + Mathlib signature that will mechanize this claim in
Tier-2. The stub is not yet imported into a Lean project; it documents
the eventual mechanization target.

```lean
-- File: TEVerifier/FM5.lean
import Mathlib.Data.Real.Basic
import Mathlib.Data.Nat.Basic

theorem fm5_critical_mass_iff (N K : ℕ) (d : ℝ) (hd : 0 ≤ d) :
    -- well-mixed sustainability ↔ algebraic threshold
    (∀ ⟨_⟩, _) ↔ (N : ℝ) ≥ 2 * K * d + 1 := by
  sorry
```

## Tests

A bullet list of test files that exercise this claim. Tests are the
runtime check that the implementation matches the proof.

> Example:
>
> - `tests/test_unit_failure_modes.py::test_fm5_well_mixed_threshold`
> - `tests/test_case_studies.py::test_axie_fm5_pass`
> - `tests/test_threshold_extraction.py::test_fm5_critical_value` (Phase 1)

---

## Style notes

- Use Unicode mathematical symbols (`τ̄`, `Γ`, `≥`, `∈`, `∀`, `∃`, `≤`)
  rather than LaTeX in body text. LaTeX is acceptable inside fenced
  blocks for complex expressions.
- Variable names match `verifier/paper.py` exactly (`gamma`, `tau_bar`,
  `Gamma`, etc.). When citing in prose, use the symbol form.
- Avoid waffle. The proof exists to be checkable, not to be readable
  prose. One short paragraph per logical step.
- When the paper and the implementation disagree, the paper wins and
  the implementation file gets a corresponding fix in the same PR.
