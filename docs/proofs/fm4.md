# FM4 — Free-Rider Collapse

> **Status.** Phase 1 — full derivation.

## Statement

For a contribution-reward token economy with active-contributor rate
`φ ∈ [0, 1]`, demand per participant `d`, offer variety `K`, monitoring
capacity `γ ∈ [0, 1]`, sanction magnitude `S ∈ [0, 1]`, and temptation
gap `T − R ∈ [0, 1]`, the system is sustainable in the cooperation-
viability sense iff

> `φ ≥ d/K`   ∧   `γ·S > T − R`

The two clauses are independent failure channels — both must hold
simultaneously. Violation of either suffices to flag FM4.

## Paper reference

§3.4, eqs. (17) (Ostrom proportionality) and (18) (monitoring
condition).

## Assumptions

1. **(Linear matching.)** Demand `d` per participant translates
   linearly to required contributor share `d/K`. Paper §3.4.
2. **(Risk-neutral defection.)** A participant defects iff expected
   gain `T − R` exceeds expected cost `γ·S`. Paper eq. (18) with
   risk-neutrality assumption stated by the paper.
3. **(Normalization.)** `T − R`, `S` are normalized to `[0, 1]` so the
   comparison `γ·S > T − R` is dimensionless. The verifier preserves
   this normalization throughout.

## Proof

**Clause 1 (Ostrom proportionality).** Per period, aggregate demand
is `N · d` redemption events. Aggregate supplied capacity from the
contributor share `φ` distributed across `K` offer types is
`N · φ · K` (each contributor produces one slot per offer type per
period under assumption (1)). Sustainable matching requires

> `N · φ · K ≥ N · d`     ⟺     `φ ≥ d / K`.   ∎

**Clause 2 (monitoring).** Under assumption (2), a risk-neutral
participant prefers cooperation iff the expected payoff of
cooperation exceeds the expected payoff of defection:

> `R > (1 − γ) · T + γ · (T − S)`
>
> ⟺     `R > T − γ · S`
>
> ⟺     `γ · S > T − R`.   ∎

Sustainability requires both clauses to hold. Violation of either is
sufficient for FM4 to flag.

## Critical-value formulas

Worst-case over the declared parameter ranges:

- `γ* = (T − R) / S_lo` — the largest monitoring threshold attainable;
  obtained at the smallest `S` in the declared range. (When `S = 0`,
  the system is structurally undeterrable; the verifier returns
  `None` for `γ*` in that case.)
- `K* = d_hi / φ_lo` — the largest offer variety the worst-case
  demand and worst-case contributor share require.
- `φ* = d_hi / K_lo` — the largest contributor share required at the
  worst-case demand and the smallest declared offer variety.

All three are quotients of bounded non-negative quantities and are
extracted in closed form.

**Binding-constraint detection.** The verifier records which clause
failed in the satisfying model:

- `φ · K < d` only ⟹ `binding_constraint = "contribution clause (φ < d/K) is binding"`
- `γ · S ≤ T − R` only ⟹ `binding_constraint = "monitoring clause (γS ≤ T − R) is binding"`
- both ⟹ `binding_constraint = "both clauses ... failing"`

The recommendation is selected based on the binding constraint —
typically `γ` for monitoring failures (achievable via
contribution_verification mechanism choice in Phase 2) and `K` for
contribution failures.

## NFR5 reweighting (Phase 5)

`meta.nfrs.proportionality = 5` (high) tightens the FM4 contributor-
rate condition. Specifically, the verifier rejects systems whose ρ
margin against `φ ≥ d/K` is narrow on the assumption that the user
declared proportionality as a hard requirement.

> **Proof obligation (Phase 5):** specify and prove the exact tightening
> rule (e.g. `φ ≥ 1.2·d/K` for NFR5 = 5). Until then, NFR5 is
> advisory.

## Z3 encoding

`verifier/failure_modes/fm4_freerider.py` declares `K, d, γ, S, φ` as
`z3.Real` bounded by their derived ranges. The violation predicate is
a disjunction of the two clause violations:

```python
solver.add(z3.Or(phi * K < d, gamma * S <= T_minus_R_normalized))
```

Critical values are computed in closed form from the formulas above
(Phase 1 design decision; see `docs/proofs/optimization.md`). The
existential check produces a counterexample if any clause is
violatable, and the binding-constraint flag is set by inspecting the
satisfying model.

Phase 2 replaces the `T_minus_R_normalized` config default with the
elicitation derivation `temptation_gap_from(verification, redemption)`
and replaces the `S_normalized` table with the elicitation derivation
`s_normalized_from(sanction_structure)`.

## Numerical correctness

Linear inequalities over rationals — exact in Z3 modulo
`numeric_epsilon`.

## Lean stub

```lean
-- File: TEVerifier/FM4.lean
import Mathlib.Data.Real.Basic
theorem fm4_monitoring_threshold (γ S T R : ℝ)
    (hγ : 0 ≤ γ ∧ γ ≤ 1) (hS : 0 ≤ S ∧ S ≤ 1) (hgap : 0 ≤ T - R) :
    -- γ·S > T - R is equivalent to γ ≥ (T-R)/S (when S > 0)
    sorry := by
  sorry
```

## Tests

- `tests/test_unit_failure_modes.py` — original FM4 unit coverage.
- `tests/test_case_studies.py` — regression on five case studies.
- `tests/test_threshold_extraction.py::test_fm4_gamma_star_closed_form`
  — synthetic IR with exclusion sanction; verifies γ\* = (T−R)/S_lo.
