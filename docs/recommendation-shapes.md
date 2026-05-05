# Recommendation shapes — per-FM verdict UI rendering

Per-FM guide for rendering the `Verdict` JSON on a verdict screen.
Each section: status states, what to render for the headline, what
the recommendation looks like, and what the failing counterexample
tells the user.

## Universal layout

For every FM card the UI renders (in this order):

1. **Header.** FM name and short description (from `paper.py`).
2. **Status badge.** PASS / FAIL / PASS-AS-INTENDED / INCONCLUSIVE / N/A.
3. **Why this matters.** From `paper.PaperCondition.why_it_matters`.
4. **Result.** The `explanation` field plus the formal_condition.
5. **Critical values.** Table of (parameter, direction, value, formula).
6. **Counterexample.** When fail/inconclusive — table + narrative + binding constraint.
7. **Recommendation.** When fail — narrative + mechanism options.
8. **Swept fields.** Notice telling the user which fields were "I don't know" and got swept.
9. **Suggestions.** Free-text design advice (always last).

## FM1: Token Oversupply

**States.** PASS, FAIL, NOT_APPLICABLE.

**N/A reasons.** Non-transferable token; pure reputation marker.

**Critical value.** `net_emission ≤ Q_lo`.

**Counterexample format.** Z3 model values for emission/burn rule
parameters (`<token>__Q`, `<token>_emit_<i>_fn__c`, etc.).

**Recommendation.** "Cap net per-period emission at `Q_lo`." Either
lower emission rate or add demand-driven burn.

**UI rendering.** Show a comparison: declared E (from rule
parameters) vs. derived `Q_lo` ceiling.

## FM2: Token Velocity Trap

**States.** PASS, FAIL, PASS_AS_INTENDED, INCONCLUSIVE, NOT_APPLICABLE.

**N/A reasons.** Non-transferable token; pure reputation marker.

**INCONCLUSIVE reasons.** No agent_types and no holding_incentives.

**PASS_AS_INTENDED.** When NFR6 = circulate_fast and τ̄ ≤ ceiling. UI
should render a special label: "Design-intended fast circulation."

**Critical value.** `tau_bar ≥ tau_ceiling` (configurable; default 1.5).

**Counterexample format.** Per-agent τ values that drive τ̄ below the
ceiling.

**Recommendation.** "Raise the expected holding time of agent type
'X' (wealth share Y%) to at least Z periods." Plus
`mechanism_mappings`: which holding-incentive mechanism's τ floor
clears the threshold.

**UI rendering.** A diagram of agent_types with their τ ranges, the
binding agent highlighted.

## FM3: Burn / Emission Imbalance

**States.** PASS, FAIL, NOT_APPLICABLE.

**N/A reasons.** Pure reputation marker; no emission rules.

**Critical value.** `rho ≥ rho_floor` (configurable, default 1).

**Counterexample format.** Z3 model values for E_per_period,
B_per_period, ρ.

**Recommendation.** "Raise per-period burn to at least
`E * rho_floor` tokens." Plus a note on demand-driven vs rule-driven
burn structure.

**Special UI rendering.** When `burn_rules = []`, show a structural
diagnostic ("No burn mechanism — supply grows monotonically") rather
than the quantitative analysis.

## FM4: Free-Rider Collapse

**States.** PASS, FAIL, NOT_APPLICABLE.

**N/A reasons.** No contribution-reward economy (no token earns supply
through behavioral or physical contribution AND has redemption).

**Critical values.** `γ ≥ γ*`, `K ≥ K*`, `φ ≥ φ*`.

**Counterexample format.** Z3 model values for K, d, γ, S, φ; plus
`binding_constraint = "contribution clause (φ < d/K) is binding"` or
`"monitoring clause (γS ≤ T − R) is binding"` or both.

**Recommendation.** Selected by binding constraint:
- Monitoring binding → recommend γ\* with verification mechanism
  options.
- Contribution binding → recommend K\* (or φ\*).

**UI rendering.** Two-column layout — Ostrom condition (`φ ≥ d/K`)
on the left, monitoring (`γ·S > T − R`) on the right; the binding
constraint highlighted.

## FM5: Insufficient Critical Mass

**States.** PASS, FAIL, INCONCLUSIVE.

**INCONCLUSIVE reasons.** Topology is not well-mixed and the
well-mixed bound fails (network/spatial may rescue via local
reciprocity). Network topology with insufficient `average_degree`
declared.

**Critical values.** `N ≥ N*`, `K ≤ K*`. For network topology,
additionally `average_degree ≥ 2·K·d`.

**Counterexample format.** N, K, d values; threshold = 2Kd + 1.

**Recommendation.** "Grow N to ≥ N\*" or "Lower K to ≤ K\*" — chosen
by which is the binding constraint.

**UI rendering.** Plot showing the (N, K, d) triple against the
threshold surface; highlight where the user's declared range crosses
the surface.

## FM6: Governance Capture

**States.** PASS, FAIL, PASS_AS_INTENDED.

**PASS_AS_INTENDED.** When NFR7 = indefinite AND governance.type =
centralized AND no Gini violation. UI label: "Centralized by design,
not capture."

**Critical values.** `Γ ≤ Γ_threshold` (default 0.5),
`n_demote ≥ ⌈U − T·Γ\*⌉`, optionally `token_gini ≤ G_threshold`.

**Counterexample format.** Γ value, unilateral count vs total,
list of unilateral decisions.

**Recommendation.** "Demote at least N decisions to token-vote or
smart-contract control." When Gini-only failure: reduce token-balance
concentration.

**UI rendering.** A table of decisions with their controlling actors;
highlight unilateral ones; show Γ before / Γ after demoting N
decisions.

## Mechanism mappings

When a recommendation has `mechanism_mappings`, render them as a
small comparison table:

| Mechanism | Range | Status |
|---|---|---|
| smart_contract_automation | γ ∈ [0.90, 1.00] | ✓ safe |
| physical_presence | γ ∈ [0.85, 0.95] | ✓ safe |
| peer_verification | γ ∈ [0.50, 0.80] | ⚠ partially safe |
| third_party_certification | γ ∈ [0.40, 0.70] | ⚠ partially safe |
| self_reporting | γ ∈ [0.05, 0.20] | ✗ unsafe |

The user clicks a mechanism to see its full description (from
`docs/elicitation-mapping.md`), what changing to that mechanism
implies for other elicitation questions (e.g. NFR3 accessibility),
and a "switch to this" button that re-runs the verifier with the
edited IR.

## Sensitivity-marked counterexamples

`Verdict.swept_fields` lists which fields the verifier searched over
(because the user said "I don't know" or supplied a wide range).
`Verdict.committed_fields` lists fields with point values.

Render these as two annotation pills under the counterexample:

> **Searched (range or unspecified):** `participants.average_demand_d`,
> `governance.monitoring_capacity_gamma`
>
> **Committed (point value):** `tokens[T].offer_variety_K`

This tells the user *why* the counterexample landed where it did —
"we found a failure inside the range you swept over" vs "we found a
failure at the exact value you committed to."

## Coherence issues at top of report

Coherence issues are **above** all FM verdicts. Use a top-level alert
panel:

> **!** Peer-to-peer transfer redemption + demand-driven burn is
> structurally incoherent (`tokens[T].burn_rules + .redemption_mechanism`).
>
> *Either change redemption_mechanism to one that supports a redemption
> event, or use a different burn trigger kind.*

When severity is `error`, the top alert is red and the UI strongly
suggests the user fix the IR before relying on the verdicts.
