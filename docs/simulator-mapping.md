# Simulator.pdf → verifier mapping

Companion to [paper-mapping.md](paper-mapping.md). This doc traces every
section of `Simulator.pdf` — the *Token Economy Simulator: Diagnostic
Calculation Layer Specification* — to the verifier code that
implements (or deliberately does not implement) it.

The verifier integrates Simulator.pdf as a **complementary
risk-stratification layer** on top of the SMT pass/fail core. The Z3
layer answers "does there exist a violation in the declared box";
the Simulator layer answers "at midpoint values, how bad is it".
Both surfaces appear in every `Verdict` and the aggregate
`OverallRiskScore` is computed per Simulator.pdf §6.

## §1 General Principles

**Status:** integrated as a complementary layer; the formal SMT layer
remains the rigorous core.

| Aspect | Where it lives |
|---|---|
| Pre-processing of qualitative inputs | `verifier/elicitation.py` (γ, S, T−R, ρ via existing tables) |
| Derived variables | `verifier/risk.py::_token_E_midpoint`, `_tau_bar_midpoint`, etc. |
| FM calculations | `verifier/risk.py::_risk_for_fm{1..6}` |
| Coherence checks | `verifier/elicitation.py::coherence_violations` (Phase D3 expansion pending) |
| Overall score | `verifier/risk.py::compute_overall_score` |

## §2 Input Pre-Processing Rules

| Sim §  | Input | Verifier site |
|---|---|---|
| 2.1 | γ from Low/Med/High | `verifier/elicitation.gamma_range_from` (per-mechanism table) |
| 2.2 | S from sanction kind | `verifier/elicitation.s_normalized_from` |
| 2.3 | T, R from verification + Econtrib + d·P̄ | T−R derived as a single normalized quantity from `temptation_gap_from(verification, redemption)` (we do not currently compute T and R separately) |
| 2.4 | g(t) from growth label | `participants.growth_g: AsymptoticClass` (richer encoding than the 4 categorical labels) |
| 2.5 | Topology factor (1.00 / 0.60 / 0.75) | Currently only well-mixed and degree-corrected; topology factors are not yet applied at the SMT layer (`docs/proofs/topology.md` notes this). |
| 2.6 | Burn rate per kind | Each kind handled by `BurnTriggerKind` + the per-rule asymptotic class. The Simulator's specific formulas (e.g. `B = Q·P̄·fb`) are realized symbolically through the rule's parameter ranges. |

## §3 Derived Variables

| Sim §  | Quantity | Verifier site |
|---|---|---|
| 3.1 | P̄ from value-anchor | Implicit (`token.value_anchor`); P is set to 1 in the non-dimensional FM1 form (`fm1_oversupply.py` comment block). |
| 3.2 | Q (entered or computed) | `participants.expected_Q: NumberRange`; the Simulator's `Q = min(Qsupply, Qdemand)` fallback is not yet implemented. |
| 3.3 | E(t) = Σⱼ fa,j × N × Yⱼ | **Phase A** — additive composition over `emission_rules`. Proof: `docs/proofs/composition.md`. |
| 3.4 | τ̄ = Σ wᵢ·τᵢ | `verifier/risk.py::_tau_bar_midpoint`; FM2 evaluates the same sum symbolically. |
| 3.5 | Bavg = Mtotal / N | Not currently used in the SMT layer; Bavg is implicit in the normalized S surface. |
| 3.6 | Mconsistent = P̄·Q / Vlower | FM1's design-stage check uses the equivalent `E ≤ Q` form (V = 1) symbolically. |
| 3.7 | φ̂ from verification mechanism | `verifier/elicitation.contributor_fraction_from` (uses agent-role declarations primarily; verification-derived default is a Phase 2 fallback). |

## §4 Failure-Mode Calculations

Risk bands are encoded in `verifier/risk.py`:

| FM | Sim §  | Risk band thresholds | Verifier function |
|---|---|---|---|
| FM1 | 4.1 | ros ≤ 1 GREEN; ≤1.5 AMBER; ≤2.5 RED; >2.5 RED_CRITICAL | `_risk_for_fm1` |
| FM2 | 4.2 | τ̄ in days: >14 GREEN; >7 BORDERLINE; >3 AMBER; >1 RED; ≤1 RED_CRITICAL | `_risk_for_fm2` (converts periods→days via ×7) |
| FM3 | 4.3 | ρ ≥ 1 GREEN; ≥0.5 AMBER; >0 RED; =0 RED_CRITICAL | `_risk_for_fm3` |
| FM4 | 4.4 | Both clauses: GREEN; one fails: AMBER; both fail: RED; φ_required>0.8: RED_CRITICAL | `_risk_for_fm4` (uses counterexample's binding-constraint info) |
| FM5 | 4.5 | rcm = N/N\*: ≥2 GREEN; ≥1.2 BORDERLINE; ≥1 AMBER; ≥0.5 RED; <0.5 RED_CRITICAL | `_risk_for_fm5` |
| FM6 | 4.6 | Γ ≤ 0.30 GREEN; ≤0.50 BORDERLINE; ≤0.80 AMBER; >0.80 RED | `_risk_for_fm6` |

**Multi-token applicability rules** (Sim §4 multi-token preface)
applied per token role in `verifier/token_role.py`. The dispatcher
calls `apply_role_applicability(te, verdicts)` after each FM runs;
governance tokens get NOT_APPLICABLE on FM2 and a Phase D4 note on
FM3; reputation tokens get NOT_APPLICABLE on FM1, FM2, FM3; resource
tokens get an FM1 mitigation note on `explanation`. See Phase D4 in
`docs/redesign-plan.md` for the role-derivation rules and the case
studies' classifications.

## §5 Coherence Check Logic

The Simulator's seven coherence checks (C1–C7) are now all
implemented. C7 is verdict-aware (uses risk_level on FM1 and FM3 to
detect the supply-side triad), so the dispatcher invokes
`coherence_violations(te, verdicts=verdicts)` after `attach_risk_levels`.

| Sim § | Check | Status | Site |
|---|---|---|---|
| C1 | NFR6 retain_value AND holding=[none] | DONE | `coherence_violations` rule 2 |
| C2 | NFR5 ≥ 4 AND verification = self_reporting (CRITICAL) | DONE | `coherence_violations` C2 |
| C3 | NFR1 ≥ 4 AND no burn (CRITICAL) | DONE | `coherence_violations` C3 |
| C4 | NFR7 immediate AND Γ = 1.0 | DONE | `coherence_violations` C4 |
| C5 | NFR3 ≥ 4 AND governance = DAO | DONE | `coherence_violations` C5 |
| C6 | NFR6 retain_value AND burn = expiry | DONE | `coherence_violations` C6 |
| C7 | ros > 1.5 AND ρ = 0 AND Γ ≈ 1.0 (CRITICAL) | DONE | `coherence_violations` C7 (verdict-aware) |

## §6 Overall Risk Score

Implemented in `verifier/risk.py::compute_overall_score`. Weights and
band thresholds match Simulator.pdf §6 verbatim:

```python
_FM_WEIGHTS = {"FM1": 1.5, "FM2": 1.0, "FM3": 1.5,
               "FM4": 1.0, "FM5": 1.0, "FM6": 0.5}
_S_MAX = 4 * sum(_FM_WEIGHTS.values()) + 7.0   # ≈ 33

# Snorm = Sweighted / Smax * 100
# 0–20% LOW, 21–40% MODERATE, 41–60% HIGH, 61–100% CRITICAL
```

`OverallRiskScore.per_fm_max` records the worst band per FM (across
all per-token verdicts), and `contradiction_penalty` records the sum
of coherence-issue penalties (1.0 per error, 0.5 per warn).

## §7 Developer Notes

- **Computation order.** §7.1's order is implicit in
  `verifier.dispatcher.verify`: SMT verdicts run first (independent
  per-FM), then `attach_risk_levels` walks each verdict and computes
  the midpoint band, then `compute_overall_score` aggregates.
- **Unit conventions.** §7.2 uses days; the IR uses periods (1 period ≈
  1 week). `_risk_for_fm2` converts periods→days via ×7 for the
  Simulator-band thresholds.
- **Precision.** §7.3 specifies 4-decimal intermediate / 2-decimal
  display. We round `OverallRiskScore.weighted` to 4 and
  `normalized_pct` to 2 decimals before serialization.
- **Missing inputs.** §7.4 says: block the affected FM, let others
  compute. Matches the verifier's existing INCONCLUSIVE behaviour.

## What the Simulator does that we have deferred

- The §3 derived variables Bavg and the explicit T/R split (we use
  T−R as a single normalized quantity).
- Per-token weighting in the overall risk score (Sim §4 utility ×1.5,
  governance ×0.75, reputation/resource ×1.0). Currently every FM has
  a global weight and the worst-band-per-FM rule aggregates across
  tokens uniformly. Adding per-role weighting would refine the
  overall percentage but the band classification is unaffected for
  the five case studies.
- The Sim §4 governance-token "33% holdings" check, which would
  require token-specific balance distribution data we do not yet
  model.

## What we do beyond the Simulator

- **Existential SMT search** over declared parameter ranges. The
  Simulator evaluates at midpoint; the verifier additionally answers
  "is there *any* assignment in the box that violates the condition".
- **Critical-value extraction** via Z3 `Optimize`. The Simulator
  reports the band; the verifier extracts the *exact threshold* the
  user must clear.
- **Asymptotic-class composition** uniformly across constant, linear,
  log, polynomial, exponential, and bounded-range function classes.
- **Cross-token coupled flows** (Phase B1) — proportional flows tied
  to source's own emission. See `docs/proofs/coupled_flows.md`.
- **Structured conditional rules** (Phase B2+B3) — three-valued
  static evaluation of threshold / time-window / event-occurrence
  predicates, side-correctly conservative in FM1/FM3. See
  `docs/proofs/conditional_rules.md`.
