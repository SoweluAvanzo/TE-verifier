# Specification Flow — Guided Decision Tree for Token Economy Designers

This document is the **first user-facing decision flow** for the Token Economy Verifier. It replaces the linear questionnaire in `Roadmap Simulatore Irene.docx` with an archetype-aware branching flow that asks the right questions in the right order and skips fields that do not apply.

## Why this exists and who it is for

The verifier needs a complete TE-IR (the data model in [docs/architecture.md](architecture.md)) before it can run. Asking the user to fill a 30-field form straight through fails for two reasons documented in [docs/case-studies.md](case-studies.md):

1. **Most fields don't apply to most designs.** A Bitcoin-style fixed-supply system has no governance lever to specify; an Axie-style P2E system has no oracle dependency; a community-redemption system has no algorithmic issuance schedule. Forcing every user through every question wastes their time and produces noisy IR with placeholder values.
2. **The questions that matter most are the ones the user is most likely to skip.** External signal dependencies, behavioral holding-time assumptions, and growth-rate bounds drove every real failure in the case studies, and they are easy to gloss over in a long flat form.

This decision flow targets a user who knows roughly what they want their token economy to do but has not formalized it. They should be able to complete the flow in 20–40 minutes, end with a complete TE-IR, and understand why each question was asked.

The flow is organized as **stages**. Each stage either asks a question that determines the next stage, or fills in a section of the TE-IR. Every stage names the IR fields it produces and the failure-mode conditions those fields feed. Where a stage corresponds to the original roadmap, the roadmap reference is given (e.g. "Group 1.3 in roadmap").

## How to read this document

Every question is shown in the format the verifier UI should render. A question carries:

- **Plain-language prompt.** What the user actually sees.
- **Why we ask.** One sentence on which failure mode(s) the answer feeds.
- **Answer space.** Either a small enum (with examples), a number / range, or "I don't know" if underspecification is allowed.
- **IR target.** Where the answer lands in the TE-IR.
- **Routing.** What stage the user goes to next, conditional on the answer.

When an answer can be "I don't know," the flow continues but flags the IR field as `unspecified`, which the verifier handles by checking across all plausible values (see [architecture.md §3.5](architecture.md) on underspecification).

---

## Stage 0 — Orientation

Before any question is asked, present a short one-paragraph orientation:

> "We are going to walk through your token economy design together. By the end you will have a complete formal description that we can verify against six known sustainability conditions from the academic literature. Most questions are short and structured. A few will ask you to commit to ranges — for example, how many participants you expect — and for those it is fine to say 'I don't know'; the verifier will check across all plausible values. We will tell you which questions are critical to the result and which are bookkeeping."

This sets expectations: rigour, time-bounded, "I don't know" is fine, ranges over point values.

---

## Stage 1 — Archetype recognition (the most consequential single question)

**Q1. Which of these best describes the *purpose* of your token economy?**

> *Why we ask.* The archetype determines which IR fields are active and pre-populates sensible defaults. From the case studies, six archetypes cover the vast majority of real systems:

| Archetype | One-line description | Real example |
|---|---|---|
| **Native protocol asset** | A token that secures a base-layer network and accrues value from network usage. | Bitcoin, Ethereum |
| **Stablecoin or pegged asset** | A token whose value tracks an external reference (currency, basket, commodity). | DAI, USDC, FoodReborn |
| **Governance + utility pair** | One token holds voting rights, another circulates as the working asset. | MakerDAO (MKR/DAI), Curve (CRV/veCRV) |
| **Play-to-earn / contribution-to-earn dual token** | One token is earned through activity, the other gates access or governance. | Axie Infinity, STEPN |
| **Community reward / mutual credit** | Tokens are earned by contribution and redeemed for goods/services within a defined community. | NLAB4CIT, Sardex, time banks |
| **Other / hybrid** | None of the above fits cleanly. | (free description) |

**Routing.** Each archetype activates a different default set of IR fields:

- *Native protocol asset* → emission group (2.x) emphasized; multi-token defaults to off; governance defaults to "informal off-chain"; oracle dependency defaults to none.
- *Stablecoin* → cross-token flow stage activated; **external signal stage forced** (the peg target is an external signal); FM2 reweighted as a goal not a risk.
- *Governance + utility pair* → multi-token stage forced; cross-token flow stage activated; FM6 emphasis.
- *Play-to-earn dual token* → multi-token forced; **agent-type heterogeneity stage emphasized** (case study showed scholar/manager/breeder split is decisive); FM1+FM2+FM3+FM4 all evaluated tightly.
- *Community reward* → roadmap groups 1.5 (contribution verification), 1.6 (redemption), 4.4 (monitoring), 4.5 (sanctions) emphasized; FM4 is the headline failure mode.
- *Other* → fall back to the full questionnaire, no stages skipped.

The archetype is also stored in `meta.archetype` for the narrator to reference.

---

## Stage 2 — Token count and roles

**Q2. How many distinct token types does your system define?**

> *Why we ask.* Drives whether the cross-token-flow stage runs at all. Most "other tokens" people forget about (LP tokens, receipts, vouchers) are not really separate tokens for verification purposes; the question prompt clarifies this.

- **One.** Continue to Stage 3 with a single token.
- **Two or more.** Continue to Stage 2a, repeated per token.

**Q2a (per token). What is this token's role in the system?**

> *Why we ask.* Token role drives the function set in IR (`Token.function`), which in turn drives which failure modes apply (e.g. velocity trap is not relevant for pure governance tokens; free-rider collapse is not relevant for pure store-of-value).

Multi-select from:

- *Medium of exchange* — used to pay for goods, services, or access.
- *Unit of account* — used to denominate prices and contributions.
- *Governance right* — held to vote on system rules.
- *Access right* — held or spent to unlock spaces, services, or tiers.
- *Store of value* — designed to be held over time.
- *Reputation marker* — non-transferable, signals trust or contribution history.

→ Populates `Token.function`. (Roadmap Group 1.1.)

**Q2b (per token, only if archetype = stablecoin or user selects *unit of account* / *medium of exchange*). What anchors this token's value?**

→ Populates `Token.value_anchor`. Choices: `none`, `physical_quantity`, `market_price`, `pegged`. If `pegged` or `market_price`, the **external signal stage (Stage 6) is forced active**. (Roadmap Group 1.3.)

---

## Stage 3 — Emission per token

This stage runs once per token. The questions converge on the (sign, asymptotic class, parameter range) triple that the verifier needs.

**Q3.1. When does this token come into existence?**

> *Why we ask.* This is the trigger kind. Whether emission tracks real activity or runs on a clock determines whether the IR populates `event_frequency` and whether the verifier needs to bound that frequency.

- *On a regular schedule, regardless of usage* → `trigger.kind = time_based`. Skip Q3.2.
- *When a user takes a specific action (logging in, completing a task, etc.)* → `trigger.kind = behavioral_event`. Continue to Q3.2.
- *When a measurable real-world resource flows in (food, hours, etc.)* → `trigger.kind = physical_resource_flow`. Continue to Q3.2.
- *Algorithmically by a smart contract on chain conditions* → `trigger.kind = algorithmic`. Continue to Q3.2.
- *Tokens are pre-minted at launch and never created again* → `trigger.kind = none`. Skip Q3.2 and Q3.3, jump to Q3.4 (initial distribution).

**Q3.2 (only if event-based). How often does this triggering event happen, on average?**

> *Why we ask.* This is the second-order asymptotic class — the frequency itself is a function of time and must be classified. Case studies showed Axie failed precisely because the IRL trigger frequency (player breeding) collapsed once growth stopped, while the design assumed it would track player count linearly.

The user selects a class with examples:

- *Constant — happens roughly the same amount per period regardless of how many users we have.* (e.g. weekly board meetings.)
- *Bounded range — happens at least X but at most Y per period, no clear trend.* User provides X, Y.
- *Linear in user count — more users, proportionally more events.*
- *Linear in time — frequency grows steadily as the system ages.*
- *Logarithmic — events get more frequent at first, then plateau.*
- *Polynomial of degree k — events grow faster than linear but not exponential.* User provides k.
- *Exponential — events compound, doubling on a fixed period.* (Use with extreme caution.)
- *I don't know.* → `event_frequency.family = unspecified`; verifier sweeps.

→ Populates `Rule.trigger.event_frequency`. (Roadmap Group 2.1.)

**Q3.3. How many tokens are emitted each time the trigger fires?**

> *Why we ask.* This is the function class proper. The case studies showed users almost never know exact constants but usually know the *shape* — "fixed amount", "linear in some input", etc.

Step A — sign:

- *Always positive — emission always happens when the trigger fires.*
- *Positive only above some threshold* — user provides predicate (e.g. "only if contribution > 2 hours").
- *Decreasing positive — emission shrinks over time or as supply grows.*

Step B — class (same options as Q3.2). Each class shows a one-line shape: constant `Y = c`; linear `Y = ax + b`; quadratic `Y = ax² + bx + c`; exponential `Y = a · b^x`. Plus *I don't know* (→ `unspecified`).

Step C — parameters: ask for ranges, not point values. ("Between what numbers do you expect `a` to fall?") Range can be `[c, c]` if the user is certain.

Step D — regime switches:

> *Optional. Does the function behave differently in some periods than others — for example, one rate for the first 30 days, then another rate?*

If yes, ask for each regime: predicate, sign, class, parameters. (Roadmap Group 2.2.)

→ Populates `Rule.function` and `Rule.regimes`.

**Q3.4. What's the initial token distribution at launch?**

→ `Token.initial_distribution`: `none`, `welcome_allocation` (number per joiner), `pre_minted_reserve` (total + distribution rule), `founder_allocation` (amount + lock period). (Roadmap Group 2.4.)

---

## Stage 4 — Burn per token

**Q4.1. Are tokens ever permanently destroyed?**

> *Why we ask.* This is the headline FM3 question. The case studies showed *whether* burn exists matters less than *how* it is triggered: demand-driven (Ethereum) is structurally sound; rule-driven or absent (Curve, Axie) is structurally flagged.

- *No — supply only grows.* → `burn_rules: []`. Verifier flags the FM3 condition `ρ = 0`. The flow continues but warns: "without burn, your supply grows monotonically; this is the headline structural failure mode for community token economies. Consider whether redemption or expiry mechanisms could fit your design."
- *Yes — tokens are destroyed in some circumstances.* → continue to Q4.2.

**Q4.2. What causes tokens to be destroyed?**

> *Why we ask.* Demand-driven vs rule-driven is the structural distinction the paper hinges on for FM3.

- *When users redeem the token for goods, services, or access* → `trigger.kind = behavioral_event`, structurally **demand-driven** (best case). Capture the redemption event predicate.
- *On a fixed schedule regardless of usage* (e.g. "10% of supply burned monthly") → `trigger.kind = time_based`, structurally **rule-driven** (warning).
- *When supply exceeds a target* → `trigger.kind = algorithmic` with threshold predicate.
- *Tokens expire after a fixed period* → `trigger.kind = time_based` with per-token age predicate.

**Q4.3. How much is burned each time?**

Same triple as Q3.3 (sign — here always negative — class, parameters, regime switches). (Roadmap Group 3.1–3.2.)

---

## Stage 5 — Cross-token flows (only if multi-token)

For each pair of tokens in the system, ask:

**Q5. Does an event involving token A trigger a mint, burn, or transfer of token B?**

> *Why we ask.* Cross-token flows were essential in three of the five case studies (MakerDAO, Curve, Axie). Missing them gives a structurally incomplete IR.

If yes, capture: source token, source event predicate, target token, target action, amount class + parameters. (No roadmap section — this is new in the IR.)

---

## Stage 6 — External signals (forced active for stablecoin / market-price archetypes)

**Q6.1. Does any rule in your system depend on a value that comes from outside the protocol — for example, a price from an exchange, a temperature reading, a real-world quantity?**

> *Why we ask.* This was the gap that surfaced in the MakerDAO case study (Black Thursday). Without bounding the rate of change of external signals, the verifier cannot detect failure modes that fire only under fast external moves. Forcing this question for stablecoins and any system that picked `value_anchor != none` is non-negotiable.

If no → skip to Stage 7.
If yes → for each external signal, capture:

- **Q6.2.** What is the signal's plausible value range? (Min and max the user is willing to commit to.)
- **Q6.3.** How fast can it change in the worst case? Per hour, per day, per week. ("ETH price can drop by 50% within 24 hours" is a bound.)
- **Q6.4.** How quickly does your system see the new value after it changes? (Oracle latency.)
- **Q6.5.** What happens to your system's rules if the signal feed is stale or missing?

→ Populates a new IR construct `ExternalSignal` (named in the architecture doc as a needed addition). Verifier treats the signal as a nondeterministic input bounded by the value range and rate.

---

## Stage 7 — Governance

**Q7.1. Who controls the rules of the token economy?**

> *Why we ask.* Direct input to FM6 (`Γ`).

- *A single entity (cooperative, project manager, company)* → `governance.type = centralized`, `Γ = 1`.
- *A small designated committee* → `governance.type = committee`, ask for committee size and decision threshold.
- *Token holders by vote* → `governance.type = dao`, ask for vote weighting.
- *Smart contracts with no human input* → `governance.type = algorithmic`, `Γ = 0` (but ask Q7.2).
- *Hybrid — different decisions handled differently* → `governance.type = hybrid`, continue to Q7.2.

**Q7.2 (per decision lever). For each of the following decisions, who controls it?**

The list is fixed and corresponds to the IR's `governance.rule_structure`:

- Emission rate adjustment
- Burn rate adjustment
- Participant eligibility
- Provider/merchant onboarding
- Exchange ratios / coupon values
- Reward structure modification
- System rule modification
- (multi-token: cross-token flow rates, oracle source choice)

Per lever the user selects: single entity / committee / token holder vote / smart contract / not adjustable. The verifier computes `Γ` automatically from this matrix. (Roadmap Group 4.2.)

**Q7.3. How likely is a non-compliant participant to be detected?**

> *Why we ask.* `γ` in FM4. Plain-language scale: low (γ ≈ 0.1), medium (γ ≈ 0.5), high (γ ≈ 0.9), or "I don't know" → unspecified.

**Q7.4. What happens when a non-compliant participant is detected?**

> *Why we ask.* `S` in FM4.
> Choices: none / warning only / token penalty (with amount) / exclusion / graduated sanctions (free-text escalation, LLM-translated).
(Roadmap Groups 4.4, 4.5.)

---

## Stage 8 — Participants and network

**Q8.1. How many participants do you expect in the system?**

> *Why we ask.* Direct input to FM5 critical mass.
> Enter as a range. "I don't know" allowed; verifier sweeps. (Roadmap 5.1.)

**Q8.2. Roughly how many goods/services/exchange opportunities are available in the system?**

> *Why we ask.* `K` in FM4 and FM5.
> (Roadmap 1.7.)

**Q8.3. Roughly how many redemption / exchange events does a typical participant want per period?**

> *Why we ask.* `d` in FM4 and FM5.
> (Roadmap 5.7.)

**Q8.4. How is the participant base growing?**

> *Why we ask.* `g(t)` in FM3. Case studies showed Axie's failure was driven precisely by the user's implicit assumption that growth would stay positive.

- *Stable* (`g ≈ 0`)
- *Slow growth* (`~5%/period`)
- *Moderate growth* (`~10%/period`)
- *Fast growth* (`>20%/period`)
- *Variable / can be negative* — user must provide a range that includes the worst case. **The flow forces a "what is the worst-case decline rate you could survive?" follow-up here.** This is the discipline Axie's designers lacked.
- *I don't know* → unspecified, verifier sweeps including negative growth.

**Q8.5. Are participants categorized into different roles with different behavior?**

> *Why we ask.* Agent-type heterogeneity drove the Axie velocity trap. The verifier needs per-type holding-time distributions to compute the wealth-weighted velocity.

If yes → for each role, capture:

- Role name (free text).
- Estimated fraction of population.
- Expected holding time (with "I don't know" → unspecified, verifier sweeps).
- Optional free-text utility hint (LLM-translated).

(Roadmap Groups 5.5, 5.6.)

**Q8.6. How do participants find each other?**

> *Why we ask.* `interaction_topology` in FM5.
> Choices: well-mixed / spatially structured / network-based (with average degree). (Roadmap 5.8.)

---

## Stage 9 — Non-functional requirement declarations

> *Why we ask.* These reweight failure modes from risks into goals (or vice versa). Specifically: NFR6 = `circulate_fast` flips FM2 from a risk into intended behavior. NFR7 reweights FM6 (a centralized governance design that declares NFR7 = "indefinite" is consistent and not flagged; one that declares "immediate" is incoherent).

Present the seven NFR questions from the roadmap (resilience, adaptability, accessibility, transparency, proportionality, circulation speed, governance maturity timeline). Each is rated 1–5 except circulation speed (3-way) and governance maturity (4-way). (Roadmap NFR1–NFR7.)

---

## Stage 10 — Sensitivity declaration and confirmation

Before submitting to the verifier, present a summary screen:

> "Here is the model of your token economy that we are about to verify. The fields marked **(swept)** are ones you said you don't know; the verifier will check all plausible values for them. The fields marked **(committed)** are ones you gave specific values or ranges for. If a failure mode triggers because of a swept field, the verifier will tell you exactly what value of that field caused it."

Show the IR rendered as a structured tree with these markers. Allow the user to revise any field. On confirm, the IR enters the dispatcher (architecture.md §5).

---

## Stage 11 — Verdict and counterexample presentation

After verification, present per-failure-mode results. From the case studies, the right structure is:

For each failure mode:

- **Verdict.** Pass / Fail / Pass-with-margin / Pass-as-intended (NFR-reweighted).
- **Why this verdict.** One sentence in plain language. (LLM-narrated from the formal output.)
- **Margin.** How close to failure the system is. ("Your `ρ` is 1.05; failure begins at `ρ < 1`.")
- **If failed: counterexample.** A concrete trajectory or parameter combination that triggers the failure. Both narrative ("at participant count = 47 with offer variety = 5...") and a small chart for trajectory-based counterexamples.
- **What you can change.** Which IR fields, if adjusted, would flip the verdict. ("Increasing `K` to ≥ 7 satisfies FM5 for the entire `N` range you specified.")

The Pass-as-intended verdict deserves special handling: the narrator should explicitly tell the user "this looks like a failure mode, but you declared NFR6 = circulate_fast, so we are treating it as design-intended velocity." This prevents users from second-guessing their own NFRs.

---

## Routing summary — what the flow looks like at the top level

```
Stage 0  Orientation
   │
Stage 1  Q1 archetype  ──→ pre-populates defaults, marks stages active/inactive
   │
Stage 2  Q2 token count
   │  ┌─ single ─────────────────────────────────┐
   │  └─ multi ── Q2a per token role + Q2b anchor│
   ▼                                              │
Stage 3  per-token emission                       │
   │                                              │
Stage 4  per-token burn                           │
   │                                              │
Stage 5  cross-token flows (only if multi-token) ◄┘
   │
Stage 6  external signals (forced if anchor != none)
   │
Stage 7  governance
   │
Stage 8  participants & network
   │
Stage 9  NFRs
   │
Stage 10 confirmation + sensitivity declaration
   │
Stage 11 verdict + counterexamples
```

## Field coverage matrix — flow stages vs IR sections

| IR section | Filled by stages |
|---|---|
| `meta.nfrs`, `meta.archetype` | 1, 9 |
| `tokens[].function`, `value_anchor` | 2 |
| `tokens[].emission_rules` | 3 (per token) |
| `tokens[].burn_rules` | 4 (per token) |
| `tokens[].initial_distribution` | 3.4 |
| `cross_token_flows` | 5 |
| `external_signals` *(new IR construct)* | 6 |
| `governance` | 7 |
| `participants` | 8 |

## Mapping flow questions to failure-mode conditions

| Failure mode | Conditions checked | Flow stages that supply the inputs |
|---|---|---|
| FM1 oversupply | `Ė/M + V̇/V > Q̇/Q`; `M_consistent = PQ/V` | 3 (E), 8.4 (g), 8.2 (Q proxy via K), 8.5 (V from holding times) |
| FM2 velocity trap | `τ̄ → 1` | 8.5 (per-agent holding times); reweighted by 9 (NFR6) |
| FM3 burn/emission imbalance | `E − B ≤ g·M`; `ρ ≥ 1` | 3 (E), 4 (B), 8.4 (g) |
| FM4 free-rider | `φ ≥ d/K`; `γS > T − R` | 7.3 (γ), 7.4 (S), 8.2 (K), 8.3 (d) |
| FM5 critical mass | `N ≥ 2Kd + 1` | 8.1 (N), 8.2 (K), 8.3 (d), 8.6 (topology) |
| FM6 governance capture | `Γ ≤ 0.5`; token Gini secondary | 7.1, 7.2 (Γ); reweighted by 9 (NFR7) |

Every parameter the paper requires is collected by some stage. No stage is collecting parameters that nothing uses.

---

## What this flow deliberately does *not* try to do

- **It does not validate that the user's range estimates are realistic.** Forcing the user to commit to ranges is the verifier's discipline; double-checking those ranges is the user's responsibility, supported by the sensitivity-analysis output in Stage 11.
- **It does not handle non-token-economy concerns** (UX of the actual user product, smart-contract security, KYC/AML compliance). These are out of scope; the verifier only reasons about sustainability against the six failure modes.
- **It does not auto-generate code.** The output is a TE-IR. Translation to a smart-contract implementation, simulator harness, etc. is downstream work.

---

## Implementation notes for the frontend

- Each stage should be one screen. Stage 3 and 4 (per-token emission/burn) repeat per token but should reuse the same component.
- "I don't know" must be a top-level option on every numeric/range question. The verifier handles it; users must not feel they need to fake an answer.
- The summary screen in Stage 10 should be navigable — clicking any field should jump back to the stage that produced it. This is how the user catches their own mistakes before running the verifier.
- The verdict screen in Stage 11 should be re-runnable with edited values without restarting the whole flow. Most user iteration cycles are "tweak one parameter, re-verify."

When the verifier stack is implemented, this flow drives integration testing: each of the five case studies in [docs/case-studies.md](case-studies.md) should be reproducible by walking through the flow with the public parameters of that system.
