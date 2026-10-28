# FM3 — Burn / Emission Imbalance

> **Status.** Phase 1 — full derivation.

## Statement

For a token economy with emission rate `E(t)`, burn rate `B(t)`,
circulating supply `M(t)`, and participant growth rate `g(t)`, the
system is sustainable in the supply-stability sense iff

> `E(t) − B(t) ≤ g(t) · M(t)`

or, in the steady-state form, iff the burn-coverage ratio

> `ρ = B/E`

satisfies `ρ ≥ ρ_floor` where
`ρ_floor = config.rho_burn_coverage_floor` (default 1, configurable).

## Paper reference

§3.3, eqs. (13)–(16).

## Assumptions

1. **(Continuity of E and B.)** Both rates are well-defined per-period
   averages over the design horizon. The verifier computes them via
   `verifier.asymptotic.rule_rate_per_period`.
2. **(Non-negativity.)** `E ≥ 0`, `B ≥ 0`, `M ≥ 0`. Definitional.
3. **(Steady-state for the ρ form.)** The ρ ≥ 1 inequality holds in
   the zero-growth steady state. The full inequality
   `E − B ≤ g·M` covers the non-zero-growth case.

## Structural credit for demand-driven burn

Beyond the quantitative ρ check, the verifier flags **structural** FM3
risk based on the burn trigger kind:

- `demand_driven` or `threshold_driven`: full structural credit.
- `rule_driven` (time-based): structural risk flagged even if ρ ≥ 1
  numerically, because the burn does not scale with demand and will
  drift out of balance once the system deviates from the assumed
  trajectory.
- No burn: the most flagged.

**Proof.** A demand-driven burn rule `B(t)` is a function of the
redemption-event volume `Q(t)`: `B(t) = β · Q(t)` for some structural
coefficient β > 0 (e.g. EIP-1559's base fee). If emission is also a
function of `Q(t)` (which it is for any system whose contributors
earn from real activity), then both `E(t)` and `B(t)` track `Q(t)`
proportionally and `ρ(t) = B(t)/E(t)` is asymptotically constant.

A rule-driven burn `B(t) = c` (constant per period) is independent of
`Q(t)`. As `Q(t)` grows, `E(t)` grows but `B(t)` stays flat, so
`ρ(t) → 0`. The verifier therefore flags rule-driven burn as
structurally fragile even when ρ is currently at the floor — the
margin disappears as the system scales. ∎

This corresponds to the paper's qualitative argument in §3.3 that
"only demand-driven burn keeps ρ stable as the system scales."

## Critical-value formulas

- `ρ* = ρ_floor` — the minimum sustainable ρ (configurable).
- `B* = E − g·M` — the boundary burn rate at which the inequality
  just holds. The verdict screen renders this as the actionable
  redesign instruction: "your burn must reach at least B* tokens per
  period."

## Emission includes inflows

`E` is the token's whole per-period creation: its own emission rules
**plus** every cross-token flow with `target_action = mint` into it
(`docs/proofs/cross_token.md`, `coupled_flows.md`). Symmetrically `B`
is its own burn rules plus every flow with `target_action = burn` into
it. A token with no emission rules of its own but an inflow (for
example a non-transferable debt token minted 1:1 with a credit token,
as in Aave's debt tokens or a mutual-credit ledger) therefore has
`E > 0` and is checked like any other token; only a token with neither
rules nor inflows has `E ≡ 0`, for which `ρ` is undefined and FM3 holds
vacuously. Likewise a token counts as supply-capped (the Bitcoin case,
`pass_as_intended` without burn) only when every source of new tokens is
a capped emission rule: an inflow has no cap. FM1 already used this
definition of `E`; `_has_inflow` and `_all_emission_capped` in
`fm3_burn_emission.py` apply it to FM3's early exits, its structural
triage and its simulation predicate (`tests/test_fm3_inflows.py`).

## Capped emission

**Lemma.** If every source of new tokens is an emission rule with a
schedule `supply_cap` (`_all_emission_capped`), FM3 holds in steady
state, whatever the burn.

*Proof.* Each rule stops creating once its cumulative emission reaches
its cap (`Rule.schedule.supply_cap`), so total creation is at most the
sum of the caps and `E(t) = 0` from some finite `t₀` on. In steady
state `E∞ = 0`, so the violation `E∞ > 0 ∧ B < ρ_floor·E∞` is
unsatisfiable. Burn enters only the second conjunct, so the argument
does not depend on it. ∎

The verdict is therefore never worse with burn than without: adding a
removal rule cannot turn a capped token from holding to failing.
When the uncapped query `E > 0 ∧ B < ρ_floor·E` is satisfiable, the
cap and only the cap holds FM3 and the verdict is `pass_as_intended`
(as without burn); when it is unsatisfiable the burn alone covers
emission and the usual query gives `pass`. The structural triage
returns "holds" for capped tokens and the simulation emits no `ρ`
predicate for them, since the realized `ρ` stays below 1 until the cap
is reached by construction (`tests/test_capped_emission_burn.py`).

The cap counts emission from the start of the analysis: for an
existing token whose supply already exists (`initial_distribution`),
the cap to declare is the amount still to be created (Bitcoin:
21 M minus the coins already mined).

## Z3 encoding

`verifier/failure_modes/fm3_burn_emission.py` declares E and B as
sums of per-rule `rule_rate_per_period` expressions plus the
cross-token inflow terms (section above), and asserts the steady-state
violation `E > 0 ∧ B < ρ_floor · E`, with `ρ_floor` tightened by NFR1
(`docs/proofs/nfr_reweighting.md`). The growth form `E − B ≤ g·M` of
the Statement is not encoded: the steady-state form is the stricter
check whenever `g·M ≥ 0` (Assumption 3), so a design that passes it
also satisfies the growth form; a design that fails only because it
is growing is reported as failing (conservative).

## Numerical correctness

Polynomial in the rate compositions; exact in Z3 modulo
`numeric_epsilon`. The `rate_per_period` averaging surrogates for
log/exponential classes are documented in
`verifier/asymptotic.py`'s docstring and are deterministic functions
of the asymptotic class plus the 52-period horizon — not magic
numbers in the sense the user has flagged.

## Lean stub

```lean
-- File: TEVerifier/FM3.lean
import Mathlib.Data.Real.Basic
theorem fm3_supply_stability (E B g M : ℝ → ℝ) (t : ℝ) :
    -- E - B ≤ g·M ↔ supply does not drift faster than population
    sorry := by
  sorry
```

## Tests

- `tests/test_unit_failure_modes.py` — original FM3 unit coverage.
- `tests/test_fm3_inflows.py` — a token fed only by a cross-token mint flow is checked (full repayment passes, partial or no repayment fails).
- `tests/test_case_studies.py` — regression on five case studies.
- `tests/test_threshold_extraction.py::test_fm3_rho_star_is_floor`
  — verifies `critical_values["rho"]` equals `config.rho_floor`.
