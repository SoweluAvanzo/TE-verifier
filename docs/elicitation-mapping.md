# Elicitation mapping — questionnaire → IR field → derived parameter

This document is the **contract** between the (future) questionnaire
UI and the verifier. Each row says: when the user answers a Roadmap
docx question, this is the IR field populated, this is the formal
paper parameter affected, and this is the override semantics.

The webapp renders prompts directly from the columns below. Every
question carries a "why we ask" surface that links to the failure
mode it feeds.

## Read this document like

| Roadmap Q# | Prompt | IR field | Derivation function | Paper parameter | Affected FM(s) |
|---|---|---|---|---|---|

## Group 1 — Token design

| Q# | Prompt | IR field | Derivation | Paper parameter | FM(s) |
|---|---|---|---|---|---|
| 1.1 | What is the primary purpose of the token? | `Token.function` (multi-select) | — | implicit (drives FM applicability) | FM1, FM2, FM3 |
| 1.2 | How do participants obtain tokens? | `Token.earning_mechanisms` (multi-select) | — | implicit (informs emission trigger) | FM3 |
| 1.3 | What anchors the token's value? | `Token.value_anchor` | — | implicit (drives Phase 5 external-signal stage) | FM1, FM3 |
| 1.4 | Does the system give participants any reason to hold tokens? | `Token.holding_incentives` (multi-select) | `holding_time_floor_from()` → τ floor | τ̄ (FM2) | FM2 |
| 1.5 | How does the system confirm a contribution before issuing tokens? | `Token.contribution_verification` | `gamma_range_from()` → γ ∈ [lo, hi] | γ (FM4) | FM4 |
| 1.6 | How do participants spend or exchange tokens? | `Token.redemption_mechanism` | `temptation_gap_from(verification, redemption)` → T − R | T − R (FM4) | FM4 |
| 1.7 | How many distinct redemption opportunities are available? | `Token.offer_variety_K` (NumberRange) | — | K (FM4, FM5) | FM4, FM5 |

## Group 2 — Emission

| Q# | Prompt | IR field | Derivation | Paper parameter | FM(s) |
|---|---|---|---|---|---|
| 2.1 | When does this token come into existence? | `Rule.trigger.kind` | — | implicit | FM1, FM3 |
| 2.2 | How many tokens are emitted per trigger? | `Rule.function` (sign + asymptotic class + parameter ranges) | `rule_rate_per_period()` → E(t) | E(t) | FM1, FM3 |
| 2.3 | (computed) | derived from 2.1 + 2.2 | `rule_rate_per_period()` | E(t) | FM1, FM3 |
| 2.4 | Initial token distribution | `Token.initial_distribution` | — | implicit | FM6 (Gini secondary) |

## Group 3 — Burn

| Q# | Prompt | IR field | Derivation | Paper parameter | FM(s) |
|---|---|---|---|---|---|
| 3.1 | Are tokens ever permanently destroyed? | `Token.burn_rules` (presence) | — | implicit | FM3 |
| 3.2 | What causes tokens to be destroyed? | `Rule.trigger.kind` (BurnTriggerKind) | — | structural credit | FM3 |
| 3.3 | Burn coverage ratio ρ | (computed) | `rule_rate_per_period(burn) / rule_rate_per_period(emit)` | ρ | FM3 |

## Group 4 — Governance

| Q# | Prompt | IR field | Derivation | Paper parameter | FM(s) |
|---|---|---|---|---|---|
| 4.1 | Who controls the rules of the token economy? | `GovernanceSpec.type` | — | implicit | FM6 |
| 4.2 | Per-decision controlling actor | `GovernanceSpec.rule_structure` (dict[decision → ControllingActor]) | counted internally | Γ | FM6 |
| 4.3 | Token creation and modification rights | (folded into `rule_structure` for now; Phase 5 will split out) | — | Γ | FM6 |
| 4.4 | Probability of detecting a free-rider | `GovernanceSpec.monitoring_capacity_gamma` (NumberRange) **or** `Token.contribution_verification` | `gamma_range_from()` (Phase 2 elicitation) | γ | FM4 |
| 4.5 | What happens to a detected non-compliant participant | `GovernanceSpec.sanction_structure` (kind + optional S_normalized) | `s_normalized_from()` | S | FM4 |

## Group 5 — Participants and network

| Q# | Prompt | IR field | Derivation | Paper parameter | FM(s) |
|---|---|---|---|---|---|
| 5.1 | Participant count | `ParticipantsSpec.count_N` (NumberRange) | — | N | FM5 |
| 5.2 | Expected transaction volume | `ParticipantsSpec.expected_Q` (NumberRange) | — | Q | FM1 |
| 5.3 | Average activity frequency per participant | `ParticipantsSpec.average_activity_frequency` (optional) | — | implicit (feeds Q indirectly) | FM1 |
| 5.4 | Participant growth rate | `ParticipantsSpec.growth_g` (AsymptoticClass) | — | g(t) | FM3 |
| 5.5 | Expected holding time per agent type | `AgentType.expected_holding_time` (per agent) | weighted sum → τ̄ | τ̄ | FM2 |
| 5.6 | Token balance distribution per agent type | `AgentType.balance_share` (per agent) | weights for τ̄ | τ̄ (weights), G (Gini) | FM2, FM6 |
| 5.7 | Average demand per participant | `ParticipantsSpec.average_demand_d` (NumberRange) | — | d | FM4, FM5 |
| 5.8 | How participants find each other | `ParticipantsSpec.topology` | — | implicit (FM5 structural correction in Phase 5) | FM5 |
| 5.9 | (Phase 2) Agent role | `AgentType.role` enum | `contributor_fraction_from()` → φ | φ | FM4 |

## Non-functional requirements

| Q# | Prompt | IR field | Effect on verdict | FM(s) |
|---|---|---|---|---|
| NFR1 | Resilience importance | `NFRs.resilience` (1–5) | **Phase 5**: tightens FM3 ρ floor | FM3 |
| NFR2 | Adaptability importance | `NFRs.adaptability` (1–5) | informational | — |
| NFR3 | Accessibility importance | `NFRs.accessibility` (1–5) | coherence: high accessibility + smart contract verification → warn | (coherence) |
| NFR4 | Transparency importance | `NFRs.transparency` (1–5) | informational | — |
| NFR5 | Proportionality importance | `NFRs.proportionality` (1–5) | **Phase 5**: tightens FM4 contributor margin | FM4 |
| NFR6 | Circulation speed | `NFRs.circulation_speed` enum | reweights FM2 verdict (FAIL → PASS_AS_INTENDED for `circulate_fast`) | FM2 |
| NFR7 | Governance maturity timeline | `NFRs.governance_maturity` enum | reweights FM6 verdict (FAIL → PASS_AS_INTENDED for `indefinite` + `centralized`) | FM6 |

## Validation rules (UI-side)

The webapp can pre-validate IR coherence before hitting the verifier:

- `tokens[].redemption_mechanism = peer_to_peer_transfer` and any
  `tokens[].burn_rules[].trigger.kind = demand_driven`: **error**.
- `meta.nfrs.circulation_speed = retain_value` and any token's
  `holding_incentives = [none]`: **warn**.
- `meta.nfrs.accessibility >= 4` and any token's
  `contribution_verification = smart_contract_automation`: **warn**.
- More rules: see `verifier.elicitation.coherence_violations`.

The same rules run server-side; the webapp surfaces them as live
form-validation feedback so the user can fix issues before submitting.

## Override semantics

Every calibration table that drives a derivation is configurable:

- `contribution_verification_to_gamma` — γ ranges per mechanism.
- `holding_incentive_to_tau_floor` — τ floors per mechanism.
- `verification_redemption_to_temptation_gap` — T − R matrix.
- `sanction_kind_to_S_normalized` — S defaults per sanction kind.

Users can:

1. Override per run via `te-verify --config overrides.yaml`.
2. Override per token by supplying explicit values that the
   derivation falls back from (e.g. set `governance.monitoring_capacity_gamma`
   directly to override the verification-derived γ).

## Reading the verdict

The verdict screen (Phase 4) for each FM renders:

- **Status.** Pass / fail / pass_as_intended / inconclusive / not_applicable.
- **Critical value(s).** From `Verdict.critical_values`. Format:
  `parameter direction value (formula)`.
- **Recommendation.** From `Verdict.recommendation`. Format:
  `parameter direction safe_threshold` plus a one-sentence narrative.
- **Counterexample.** When the verdict is fail/inconclusive: the
  parameter values that triggered the violation, plus a binding-
  constraint indicator for multi-clause FMs (FM4).
- **Swept fields.** Which IR fields the verifier searched over (because
  the user said "I don't know" or supplied a wide range).
- **Coherence issues.** Top-level Report warnings about
  cross-field inconsistencies.

## Phase 6 (webapp prototype) deliverables

The webapp prototype consumes:

- This file as the **questionnaire structure** (one screen per Group).
- `verifier/paper.py` as the **explanatory copy** (why-we-ask and
  why-it-matters per FM).
- `verifier/elicitation.py` as the **client-side validation** (the
  same coherence rules surface as form errors before submit).
- `Report` JSON as the **verdict-screen contract** (one card per
  FM with critical value, recommendation, counterexample).
