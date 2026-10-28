# Outstanding supply cap (credit limits, debt ceilings)

> **Status.** Full derivation; encoding in
> `verifier/failure_modes/fm1_oversupply.py`,
> `verifier/failure_modes/fm3_burn_emission.py`, `verifier/risk.py`,
> `verifier/simulate/trajectory.py`, `verifier/abm/engine.py`,
> `verifier/abm/actions.py`. Tests: `tests/test_outstanding_cap.py`.

## Motivation

Credit and debt systems bound the tokens **outstanding** at any time, not
the tokens ever created: the sum of members' credit limits in a
mutual-credit network (Sardex, WIR), a debt ceiling (MakerDAO), a borrow
cap (Aave). Creation that would exceed the bound is refused. Without the
bound in the specification the verifier cannot credit the design with it
and treats every period of under-repayment as a possible spiral.

`Token.outstanding_supply_cap = [C_min, C_max]` declares the bound; the
range is the designer's uncertainty about it, quantified universally like
every other range. It differs from `ScheduleModifiers.supply_cap`, which
bounds cumulative emission (the Bitcoin case; `fm3.md`).

## Model

Time is discrete (periods). The FM1 and FM3 encodings abstract a token by
its declared per-period creation rate `E ≥ 0` (own emission rules plus
cross-token mint inflows, `fm3.md` "Emission includes inflows") and burn
rate `B ≥ 0` (own burn rules plus burn inflows). Under that abstraction an
uncapped token evolves as `M(t+1) = M(t) + E − B`.

With a cap `C`, the protocol refuses creation beyond the bound. The
realized creation in period `t` is

> `e(t) = min(E, C − M(t) + B)`

(the burn of the period frees room for the same amount of creation), and

> `M(t+1) = M(t) + e(t) − B`,  with `M(0) = M₀ ≤ C`.

The schema enforces `M₀ ≤ C` (validator `_initial_supply_within_cap`:
`initial_distribution.amount.max ≤ C_min`). `e(t) ≥ 0` because
`M(t) ≤ C` (Lemma 1) and `B ≥ 0`.

## Lemma 1 (invariant)

`M(t) ≤ C` for every `t ≥ 0`.

*Proof.* Induction. `M(0) = M₀ ≤ C`. If `M(t) ≤ C` then
`M(t+1) = M(t) + e(t) − B ≤ M(t) + (C − M(t) + B) − B = C`. ∎

## Lemma 2 (FM1 under a cap)

The realized net creation `n(t) = e(t) − B` satisfies
`n(t) ≤ min(E − B, C − M(t)) ≤ min(E − B, C)`, and the bound
`min(E − B, C)` is attained (at `t = 0` with `M₀ = 0`).

*Proof.* `e(t) ≤ E` gives `n(t) ≤ E − B`; `e(t) ≤ C − M(t) + B` gives
`n(t) ≤ C − M(t) ≤ C` since `M(t) ≥ 0`. With `M₀ = 0`,
`n(0) = min(E, C + B) − B = min(E − B, C)`. ∎

**Corollary (encoding).** FM1's violation `n > Q` (`fm1.md`, design-stage
form at `P = V = 1`) is possible for a capped token iff

> `∃ params: E − B > Q ∧ C > Q`.

`fm1_oversupply.py` adds the cap variable `C ∈ [C_min, C_max]` and the
conjunct `C > Q` to the existing violation query; the safety dual used by
the structural triage becomes `E − B ≤ Q ∨ C ≤ Q`. In particular, if
`C_max ≤ Q_min` FM1 holds for every parameter assignment: the stock itself
never exceeds the design-consistent money supply `M_consistent = P·Q/V`
(Lemma 1). The simulation predicate `net_emission_per_period ≤ Q_min`
needs no change: the simulators enforce the cap (below), so realized net
creation obeys Lemma 2.

## Lemma 3 (FM3 under a cap)

Let `E∞ = min(E, B)`. After at most
`t* = ⌈(C − M₀) / (E − B)⌉` periods when `E > B` (and from the start
when `E ≤ B`), the realized creation is constant and equal to `E∞`.

*Proof.* Case `E ≤ B`: `C − M(t) + B ≥ B ≥ E`, so `e(t) = E = E∞` for
every `t`. Case `E > B`: while `M(t) + E − B ≤ C` the cap does not bind
and `M` grows by `E − B > 0` per period, so after at most `t*` periods
`M(t) + E − B > C`; then `e(t) = C − M(t) + B` and `M(t+1) = C`, after
which `e = B = E∞` for ever. ∎

**Corollary (encoding).** FM3 checks the steady-state burn coverage
(`fm3.md`, "Z3 encoding"). For a capped token the steady-state creation
is `E∞`, so the violation becomes

> `∃ params: E∞ > 0 ∧ B < ρ_floor · E∞`,   `E∞ = If(E < B, E, B)`.

- With `ρ_floor ≤ 1` (the default) it is unsatisfiable: `E∞ ≤ B` gives
  `ρ_floor · E∞ ≤ B`. Under-repayment cannot become a spiral; it makes
  the outstanding supply reach the cap, after which new creation is
  refused (in a credit network: members at their limit can no longer
  buy on credit).
- With `ρ_floor > 1` (NFR1 resilience 4 or 5 asks burn to exceed
  creation) the cap does not help: when `E ≥ B > 0`,
  `B < ρ_floor · B` holds.
- With no burn at all (`B = 0`), `E∞ = 0`: the supply stops at the cap,
  like a capped emission schedule; FM3 holds vacuously.

**Verdict.** If the uncapped query is satisfiable and the capped one is
not, the token is sustainable **because of the cap**: FM3 reports
`pass_as_intended` (as for `supply_cap`, `fm3.md`), with the critical value
`C` and `t*` evaluated at the uncapped counterexample's `E` and `B`, the
lowest cap `C_min` and the highest initial supply `M₀` (the earliest the
cap can bind at those rates). If the capped query is satisfiable the
verdict is `fail` as usual; if the uncapped one is unsatisfiable, `pass`.
The safety dual used by the structural triage is
`E∞ = 0 ∨ B ≥ ρ_floor · E∞`. The simulation predicate on `ρ` is
suppressed when the cap makes FM3 hold (`ρ_floor ≤ 1`), as for
`supply_cap`: before `t*` the realized `ρ` is below 1 by construction and
the predicate would contradict the proven steady-state verdict.

## Consistency of the other layers

- **Risk bands** (`verifier/risk.py`) evaluate the same quantities at the
  midpoint: FM1 uses `min(E − B, C)` for the net creation, FM3 uses `E∞`.
- **Trajectory** (`verifier/simulate/trajectory.py`) integrates the Model
  above at the midpoint of `C`.
- **Agent-based simulation** (`verifier/abm/`) samples `C` once per run in
  its range and clips every creation (EARN shares, cross-token mint
  inflows, the no-agent aggregate update) to the room `C − M(t)` left at
  that moment, so `M(t) ≤ C` holds in every run (Lemma 1 realized).
- FM2, FM4, FM5, FM6 do not read creation or supply rates and are
  unchanged. With `outstanding_supply_cap = None` every code path is the
  previous one, so no existing verdict changes.

## Lean stub

```lean
-- File: TEVerifier/OutstandingCap.lean
import Mathlib.Data.Real.Basic

/-- One period of the capped model. -/
noncomputable def step (E B C M : ℝ) : ℝ := M + min E (C - M + B) - B

-- The induction step of Lemma 1 (it needs no hypothesis on M; M₀ ≤ C is
-- the base case).
theorem cap_invariant (E B C M : ℝ) : step E B C M ≤ C := by
  unfold step
  have := min_le_right E (C - M + B)
  linarith

theorem fm1_net_bound (E B C M : ℝ) (hM : 0 ≤ M) :
    step E B C M - M ≤ min (E - B) C := by
  unfold step
  refine le_min ?_ ?_
  · have := min_le_left E (C - M + B); linarith
  · have := min_le_right E (C - M + B); linarith
```

## Tests

`tests/test_outstanding_cap.py`: the schema rejects a negative cap and an
initial supply above the cap; FM1 passes when `C_max ≤ Q_min` and fails
when the cap allows more than `Q` and `E − B > Q`; FM3 is
`pass_as_intended` for under-repayment with a cap, `fail` with
`ρ_floor > 1`, unchanged without a cap; the risk bands agree with the
verdicts; the trajectory and the agent-based runs never exceed the cap.
