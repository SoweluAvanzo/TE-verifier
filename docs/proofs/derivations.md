# Elicitation derivations

> **Status.** Phase 2 — created.

This file documents the **derivation rules** that map structured user
choices onto formal paper parameters. The verifier prefers structured
choices over direct parameter values because the choices are what the
user can answer with confidence; the formal parameters (γ, τ, T − R)
are derived consequences. See `verifier/elicitation.py`.

## Why these are calibrations, not theorems

The mappings in this file are calibrations: they translate qualitative
descriptions in the Roadmap docx (e.g. "physical presence — strongest
verification") into numeric ranges (e.g. `γ ∈ [0.85, 0.95]`). The
calibrations are **justified** but not provable from the paper. Each
default lives in `verifier/config.py` and can be overridden per run.

What we *can* prove about the calibrations is structural:

1. **Monotonicity.** Stronger verification → higher γ floor; longer-
   commitment incentive → higher τ floor; less liquid redemption →
   smaller T − R gap. These are testable invariants and are locked by
   `tests/test_elicitation.py`.
2. **Coherence-rule consistency.** Each coherence rule has a logical
   justification (e.g. P2P transfer has no redemption event, so
   demand-driven burn cannot fire on it).

These two structural properties are the part of this document a Lean
mechanization would target; the numeric values themselves are
configurable parameters, not theorems.

## Derivation 1 — `verification → γ range`

### Statement

Define `γ_range : ContributionVerification → [0,1] × [0,1]` by the
table in `VerifierConfig.contribution_verification_to_gamma`.

The function is **monotone** in the verification-strength order

> `self_reporting ≺ third_party ≺ peer ≺ physical ≈ smart_contract`

i.e. `γ_lo` is non-decreasing along this order.

### Justification

The Roadmap docx 1.5 ranks the five verification mechanisms by
detection capability:

| Mechanism | docx description | γ range |
|---|---|---|
| `physical_presence` | "Strongest verification; hardest to fake." | [0.85, 0.95] |
| `smart_contract_automation` | "Objective and tamper-proof." | [0.90, 1.00] |
| `peer_verification` | "Strong; requires trust between participants." | [0.50, 0.80] |
| `third_party_certification` | "Reliable but introduces governance dependency." | [0.40, 0.70] |
| `self_reporting` | "Weakest verification; highest free-rider risk." | [0.05, 0.20] |
| `unspecified` | "I don't know." | [0.00, 1.00] |

The intervals are calibrated as follows: the **upper** bound captures
the best plausible detection rate when the mechanism operates as
designed; the **lower** bound captures realistic operational laxness
(the sign-in sheet that wasn't enforced; the on-chain check that
covered only part of the desired predicate). `unspecified` returns
the full interval — this is the formal handle that lets the verifier
ask "what is the minimum γ at which the system is sustainable?" and
return a critical value `γ*` the user can then compare to mechanism
ranges.

### Tests

- `test_every_verification_has_gamma_range`
- `test_gamma_range_monotone`
- `test_gamma_range_unspecified_is_full_interval`
- `test_gamma_range_returns_none_when_input_none`

## Derivation 2 — `holding_incentives → τ floor`

### Statement

Define `τ_floor : HoldingIncentiveMechanism → ℝ_{≥0}` by the table in
`VerifierConfig.holding_incentive_to_tau_floor`. For a list of
incentives `[I_1, …, I_k]`, the combined floor is

> `τ_floor([I_1, …, I_k]) = max_j τ_floor(I_j)`.

Empty list = `[NONE]` (baseline).

### Justification

The Roadmap docx 1.4 distinguishes mechanisms by their structural
strength:

| Mechanism | τ floor (periods) | Justification |
|---|---|---|
| `none` | 1.0 | Velocity-trap baseline; spend-on-receipt. |
| `tiered_redemption` | 2.0 | Soft holding pressure; users wait for higher-value rewards. |
| `reputation` | 2.0 | Soft social pressure; depends on community culture. |
| `governance_rights` | 4.0 | Voting requires holding above threshold. |
| `staking` | 4.0 | Lock period typically ≥ 4 weeks. |
| `time_locked_rewards` | 4.0 | Vesting period typically ≥ 4 weeks. |

The `max` aggregation reflects that the **strongest** incentive
dominates: a token with both staking and tiered redemption is at
least as held as a token with only staking.

### Tests

- `test_every_holding_incentive_has_tau_floor`
- `test_holding_incentive_none_is_lowest_floor`
- `test_holding_incentive_stacking_takes_max`
- `test_holding_incentive_empty_list_is_baseline`

## Derivation 3 — `(verification, redemption) → T − R`

### Statement

Define `gap : ContributionVerification × RedemptionMechanism → [0,1]`
by the matrix in
`VerifierConfig.verification_redemption_to_temptation_gap`. The matrix
is **monotone in both axes**:

- For fixed redemption, stronger verification → smaller gap.
- For fixed verification, less liquid redemption → smaller gap.

### Justification

The temptation gap T − R is the asymmetry between the payoff a
defector can extract and the reward a cooperator earns. Two factors
shape it structurally:

1. **Verification strength** caps how easily a defector can hide
   defection. Strong verification (smart contract / physical presence)
   makes defection visible, so the realized T − R is small. Weak
   verification (self-reporting) lets defectors claim cooperation
   payoffs without producing the contribution.
2. **Redemption liquidity** caps how readily a defector can convert
   tokens into liquid value. Structured redemption (specific goods
   from a fixed catalogue) limits the gain; liquid redemption
   (open-market exchange, P2P transfer) lets defectors cash out at
   full value.

The `(strong-verification, structured-redemption)` corner has
T − R ≈ 0.05 (defection is hard to hide and unprofitable when caught).
The `(weak-verification, liquid-redemption)` corner has T − R ≈ 0.95
(defection is easy and immediately profitable).

The matrix entries between corners are calibrated to preserve
monotonicity in both axes.

### Tests

- `test_every_pair_has_temptation_gap`
- `test_temptation_gap_monotone_in_verification`
- `test_temptation_gap_monotone_in_redemption`

## Derivation 4 — `agent_types → φ`

### Statement

Define `φ_range : list[AgentType] → [0,1] × [0,1]` by

> `φ_range(agents) = (0, max(0.05, sum_{a : a.role = CONTRIBUTOR} a.fraction))`

when at least one agent has an explicit role. When no agent has a
role, fall back to the legacy keyword-matching heuristic on
`agent.id` and `agent.utility_hint` — same algorithm as the
Phase 0 `FM4FreeRider._estimate_phi_range`.

### Justification

Aggregate contributor share is the sum of declared contributor
fractions. The lower bound is 0 (worst case: all declared
contributors disengage). The 0.05 floor on the upper bound prevents
a system with declared contributors from collapsing to φ = 0 in the
verifier's solver — it preserves the structural distinction between
"contributors exist but might disengage" and "no contributors
declared."

### Tests

- `test_contributor_fraction_uses_explicit_role`
- `test_contributor_fraction_keyword_fallback_when_role_unset`

## Derivation 5 — `sanction_structure → S`

### Statement

Define `S_range : SanctionStructure → NumberRange`:

- If `S_normalized` is set, return it directly.
- Else look up `kind` in `VerifierConfig.sanction_kind_to_S_normalized`
  and return `[default − 0.1, default + 0.1]` clamped to `[0, 1]`.

### Justification

User-supplied numeric values are honored (the user knows their own
penalty schedule better than the calibration table does). The
fallback table is calibrated from the docx 4.5 ordering:

| Kind | default | Rationale |
|---|---|---|
| `none` | 0.0 | "No formal sanction" — definitional. |
| `warning` | 0.1 | Token weight: social, not material. |
| `token_penalty` | 0.5 | Mid-magnitude material penalty. |
| `economic` | 0.8 | E.g. PoW slashing — large but not exclusion. |
| `exclusion` | 0.9 | "Removed from the system" — near-maximal. |
| `graduated` | 0.7 | Phase 2: structured escalation list pending; default to upper-mid pending the Phase 5 graduated-sanctions input format. |

## Coherence rules

Each rule has a logical justification rather than a numeric calibration.

### Rule 1 — P2P transfer is incompatible with demand-driven burn

**Statement.** If `redemption_mechanism = peer_to_peer_transfer`, the
system has no redemption-event predicate; therefore any
`burn_rule.trigger.kind = demand_driven` has no event to fire on.

**Severity.** Error — the IR is internally contradictory.

**Justification.** Demand-driven burn fires on a redemption event
(`event_predicate` like "coupon redeemed", "service consumed"). P2P
transfer is a balance change between two participants; nothing is
consumed and there is no redemption. The combination is structurally
impossible.

**Resolution.** Either change `redemption_mechanism` to one that
supports a redemption event (`specific_goods_or_services`,
`time_based_borrowing`, `fungible_access`) or change
`burn_rule.trigger.kind` to one independent of redemption
(`rule_driven`, `expiry`, `threshold_driven`).

### Rule 2 — `circulation_speed=retain_value` + `holding_incentives=[none]`

**Statement.** If NFR6 declares `retain_value` (tokens should be
held) and the token's `holding_incentives = [none]`, the declared
intent contradicts the structure.

**Severity.** Warn — the IR is parseable but the verdict will be
incoherent (FM2 verdict → fail because no incentives, but NFR6
asks for retention).

**Justification.** Holding requires a structural reason. None of
the tokens with `holding_incentives = [none]` will be held by
rational participants regardless of the NFR declaration.

### Rule 3 — `accessibility ≥ 4` + `verification = smart_contract_automation`

**Statement.** High-accessibility NFR (≥ 4 on the 1–5 scale) combined
with smart-contract verification raises the technical bar for
non-technical users.

**Severity.** Warn.

**Justification.** Cryptographic verification is objective and
tamper-proof but typically requires participants to operate
wallets, sign transactions, and reason about chain state. The docx
NFR3 (accessibility) explicitly favors mechanisms accessible to
participants without blockchain knowledge.

## Phase 2 ↔ Phase 1 interaction

The elicitation derivations feed Phase 1's critical-value extraction
seamlessly: when γ is derived from a verification mechanism, FM4's
critical value `γ* = (T − R) / S_lo` automatically reflects the
**derived** lower bound `S_lo`. The mechanism-mapping section of the
verdict (Phase 4 will populate `NumericRecommendation.mechanism_mappings`)
translates the critical γ\* back into the mechanism subset that
satisfies it — closing the loop between elicitation and
recommendation.

## Lean stub

```lean
-- File: TEVerifier/Derivations.lean
import Mathlib.Data.Real.Basic

-- Derivation 1: monotonicity of γ_floor in verification strength
inductive VerificationStrength : Type
  | self_reporting | third_party | peer | physical | smart_contract

def verification_order : VerificationStrength → ℕ
  | .self_reporting => 0
  | .third_party => 1
  | .peer => 2
  | .physical => 3
  | .smart_contract => 4

theorem gamma_floor_monotone
    (γ : VerificationStrength → ℝ × ℝ)
    (hmono : ∀ a b, verification_order a ≤ verification_order b →
                    (γ a).1 ≤ (γ b).1) : True := by
  trivial -- skeleton; full proof obligation in Tier-2
```
