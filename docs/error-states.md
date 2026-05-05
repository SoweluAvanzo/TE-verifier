# Error states — INCONCLUSIVE preconditions and UI prompts

For each FM, every reason a verdict can be `INCONCLUSIVE`, the IR
field that resolves it, and the UI prompt text the webapp should
show.

## Universal handling

When a verdict is `INCONCLUSIVE`, the UI should:

1. Render the verdict card with a yellow `INCONCLUSIVE` badge.
2. Show the reason from `Verdict.explanation`.
3. Render an actionable prompt linking back to the elicitation
   question that resolves it (using `paper.PaperCondition.elicitation_questions`
   to find the right Stage in `docs/specification-flow.md`).
4. Offer a "Resolve and re-run" button that takes the user back to
   that elicitation step.

## FM2: Token Velocity Trap

**Precondition.** No `agent_types` declared AND no `holding_incentives`
on the token.

**Resolution.** Either populate `participants.agent_types[]` with at
least one `expected_holding_time` range, or set
`tokens[].holding_incentives` to one or more values from the
`HoldingIncentiveMechanism` enum.

**UI prompt.**

> **We need to know how long participants hold this token.**
>
> Either go back and describe the agent types in your system (their
> expected holding times) — Roadmap question 5.5 — or tell us which
> holding-incentive mechanisms apply (governance rights, staking,
> tiered redemption, etc.) — Roadmap question 1.4.
>
> [Back to 5.5] [Back to 1.4]

## FM4: Free-Rider Collapse

**Preconditions for INCONCLUSIVE.** None today; FM4 returns
`NOT_APPLICABLE` when no contribution-reward economy is detected, but
no INCONCLUSIVE state. The Phase 2 elicitation makes γ derivation
robust enough that the previously-flat γ search no longer triggers
INCONCLUSIVE.

**Edge case.** If neither `contribution_verification` nor
`monitoring_capacity_gamma` is supplied AND the agent_types provide
no role information, FM4 sweeps γ ∈ [0, 1] with φ ∈ [0, 1] and the
verdict is FAIL with a wide critical-value bound.

**UI prompt.** When FM4 reports a wide γ\* range, suggest the user
provide either `contribution_verification` (Roadmap 1.5) or
`monitoring_capacity_gamma` (Roadmap 4.4) for a tighter answer.

## FM5: Insufficient Critical Mass

**Precondition 1.** No token has `offer_variety_K` declared.

**Resolution.** Set `Token.offer_variety_K` (NumberRange) on at least
one token.

**UI prompt.**

> **We can't compute the critical mass without knowing how many
> distinct offers your system supports.**
>
> Roadmap question 1.7: how many distinct types of goods, services,
> or exchange opportunities does each token unlock?
>
> [Back to 1.7]

**Precondition 2.** Topology is not well-mixed AND the well-mixed
bound `N < 2Kd + 1` is satisfiable for some assignment.

**Resolution.** Either supply `topology_params["average_degree"]`
(for network topology) or accept that the well-mixed bound is
conservative for spatially-structured systems.

**UI prompt.**

> **The well-mixed critical-mass bound fails for some declared
> parameters, but your topology is `network` / `spatial`. Local
> reciprocity may sustain exchange below this threshold.**
>
> If you know the average network degree (connections per
> participant), we can apply a tighter bound.
>
> [Set average degree] [Accept inconclusive]

## FM6: Governance Capture

**Precondition.** `governance.rule_structure` is empty.

**Resolution.** List at least one decision lever and its controlling
actor.

**UI prompt.**

> **We can't evaluate governance centralization without knowing who
> controls each rule.**
>
> Roadmap question 4.2: for each of the following decisions, who
> controls it? (emission rate adjustment, burn rate adjustment,
> participant eligibility, …)
>
> [Back to 4.2]

## Coherence issues (top-level Report warnings)

These don't change verdict status (verdicts still run on the
internally-inconsistent IR), but the UI surfaces them at report top
with structured guidance:

### `peer_to_peer_transfer + demand_driven_burn`

**Severity.** Error (the IR is contradictory).

**UI prompt.**

> **!** Token T uses peer-to-peer transfer redemption with a
> demand-driven burn rule. P2P transfer is a balance change, not a
> redemption event, so the demand-driven burn has no trigger to fire.
>
> [Change redemption to specific_goods] [Change burn to rule_driven]

### `circulation_speed = retain_value + holding_incentives = [none]`

**Severity.** Warn.

**UI prompt.**

> **!** You declared NFR6 = retain_value (tokens should be held), but
> token T has no holding incentives. Rational participants will spend
> the token on receipt regardless of the NFR.
>
> [Add a holding incentive] [Change NFR6 to balanced]

### `accessibility ≥ 4 + verification = smart_contract_automation`

**Severity.** Warn.

**UI prompt.**

> **!** You declared high accessibility (NFR3 ≥ 4), but token T uses
> smart-contract verification. Cryptographic verification typically
> raises the technical bar for non-technical participants.
>
> [Change verification to physical_presence] [Lower NFR3 to ≤ 3]

## Loading errors

If the IR fails to parse (Pydantic validation error), the verifier
returns exit code 2 and stderr message `error: failed to load <path>:
<message>`. The UI surfaces this at the top of the questionnaire,
linked to the offending field.

If the config YAML fails to load, exit code 2 with message `error:
failed to load <config-path>: <message>`. Webapp should validate
config-override YAMLs before submission.
