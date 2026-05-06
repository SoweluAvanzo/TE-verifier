# Redesign plan — multi-mechanism, multi-token, conditional flows

> **Scope.** Five user-visible asks: (1) per-token list of mint
> mechanisms with composition; (2) cross-token conditional mint/burn
> with coupled amounts; (3) full asymptotic-class specification for
> burn (parity with mint) plus multi-mechanism burn; (4) multi-token
> form UI; (5) integration of `Simulator.pdf` (the *Token Economy
> Simulator — Diagnostic Calculation Layer Specification* doc) where
> it is complementary, without giving up the Z3 formal layer.
>
> **Non-goals.** Replacing the SMT pass/fail layer with the Simulator's
> risk bands. The Simulator is added as a complementary surface — the
> formal layer remains the rigorous core.

## Audit (state before redesign)

| Concern | Current state |
|---|---|
| Per-token multi-mint | Schema supports it (`Token.emission_rules: list[Rule]`); FM1 and FM3 already iterate the list and compose additively. **Form** collapses to a single rule. |
| Per-token multi-burn | Schema supports it (`Token.burn_rules: list[Rule]`); FMs iterate. **Form** collapses to a single rule, no asymptotic-class selector for burn. |
| Cross-token flows | Schema (`CrossTokenFlow`) and FM3 implement them; **FM1 ignores them**. **Form** has no UI for them at all. |
| Conditional rules | `RuleTrigger.event_predicate: str \| None` and `RegimeSwitch.predicate: str` exist as free-form strings, not structured. |
| Coupled amounts | Cross-token amount is an independent `AsymptoticClass`; no coupling to the source event's amount. |
| Multi-token | Schema is multi-token; CLI and YAML editor handle it. **Form** edits only the first token. |
| Risk bands | None. Verdicts are `pass`/`fail`/`pass_as_intended`/`inconclusive`/`not_applicable`. |
| Overall risk score | None. |

## Phases

### Phase A — Backend correctness (FM-level composition)

| # | Change | Files |
|---|---|---|
| A1 | Audit FM1, FM2, FM3 — confirm all per-rule lists compose additively. Add explicit multi-mechanism tests. | `verifier/failure_modes/fm{1,3}_*.py`, `tests/test_multi_mechanism.py` (new) |
| A2 | Make FM1 consume `cross_token_flows` (currently only FM3 does). Mirror the FM3 pattern. | `verifier/failure_modes/fm1_oversupply.py` |
| A3 | Document the additive composition theorem. | `docs/proofs/composition.md` (new) |

Status: **in progress.**

### Phase B — Schema: conditional & coupled flows

| # | Change | Files |
|---|---|---|
| B1 | `CrossTokenFlow.coupling: Literal["independent","proportional_to_source"]` and optional `coupling_ratio: NumberRange`. When `proportional_to_source`, the flow rate is `source_rule_rate × ratio` instead of an independent class. Default `independent` (back-compat). | `schema/te_ir.py`, FM1+FM3 cross-token sums |
| B2 | Structured `Condition` model: `ThresholdCondition(var, op, value) \| TimeWindow(start, end) \| EventOccurrence(token, event)`. Attach optionally to `Rule.trigger.conditions: list[Condition]`. Free-text `event_predicate` kept for back-compat. | `schema/te_ir.py` |
| B3 | Encode conditional rules in Z3: rule contributes only when the condition is satisfiable in the box; for negative predicates use `z3.If`. | `verifier/asymptotic.py`, `docs/proofs/conditional_rules.md` (new) |

### Phase C — Frontend rebuild

| # | Change | Files |
|---|---|---|
| C1 | Multi-token UI: token-card list + `+ Add token`. | `webapp/templates/form.html`, `webapp/static/form.js`, `webapp/static/form.css` |
| C2 | Multi-mechanism mint UI per token: rule-card list + `+ Add mint mechanism`. Each card has trigger, sign, asymptotic class, parameter ranges, optional conditions. | same |
| C3 | Multi-mechanism burn UI with full asymptotic-class selector + `+ Add burn mechanism`. | same |
| C4 | Cross-token flows UI: top-level "Inter-token relationships" + `+ Add flow`. Source token / source event / target token / action / amount class / coupling (independent vs proportional_to_source). | same |
| C5 | Live composition preview: human-readable rendering of composed `E(t)`/`B(t)` (e.g. *"E(t) ≈ linear[100..200] + constant[50] + 0.3 × source(MKR.fee_event)"*). | `webapp/static/form.js` (new module) |
| C6 | Hydrate / serialize multi-token IR; remove single-token caveat from `webapp/README.md`. | form.js, README |

### Phase D — Risk stratification (Simulator.pdf §4–§6, complementary)

| # | Change | Files |
|---|---|---|
| D1 | Add `risk_level: green \| amber \| red \| red_critical` to `Verdict` alongside `Status`. Bands per Simulator.pdf §4. | `verifier/failure_modes/base.py`, all 6 FM modules |
| D2 | `OverallRiskScore`: weighted sum + normalized %, interpretation band (Simulator.pdf §6). | `verifier/dispatcher.py` |
| D3 | Add Simulator.pdf §5 coherence checks (C1–C7) on top of existing `coherence_violations`. | `verifier/elicitation.py` |
| D4 | Multi-token role-based applicability (Simulator.pdf §4 "Multi-Token Systems"). | `verifier/dispatcher.py` |
| D5 | Verdict cards render risk band; report header shows overall score. | `webapp/static/verdict.js` |

### Phase E — Tests + documentation

| # | Change | Files |
|---|---|---|
| E1 | Tests: multi-mechanism composition; proportional cross-token coupling; conditional rules; multi-token form serialization; risk-band assignment; overall score. | `tests/test_multi_mechanism.py`, `tests/test_conditional_rules.py`, `tests/test_risk_levels.py`, `tests/test_overall_score.py`, `tests/test_form_multi_token.py` |
| E2 | Update `docs/elicitation-mapping.md`, `docs/architecture.md`, `docs/api-contract.md`, `docs/recommendation-shapes.md`, `docs/error-states.md`. | docs/ |
| E3 | Update `CLAUDE.md` repository-status section. | CLAUDE.md |
| E4 | New doc `docs/simulator-mapping.md` — line-by-line mapping of Simulator.pdf §1–§7 to verifier code (companion to `docs/paper-mapping.md`). | new file |
| E5 | Update `webapp/README.md` to remove the single-token caveat. | webapp/README.md |

## Backwards compatibility

- Schema changes in B1, B2 default to today's behaviour. The five
  case-study YAMLs continue to verify with **identical verdicts**.
- Form UI in C1–C5 is additive; the YAML editor remains for advanced
  cases (regime switches, exotic asymptotic families).
- Risk bands in D1 are added alongside `Status`, not in place of it.
  Clients that key on `Status` are unaffected.

## Decision log (locked)

1. Risk stratification is **additive** to the formal `Status`, not a
   replacement. The SMT layer remains the rigorous core.
2. Conditional predicates are restricted to three structured types
   (threshold, time-window, event-occurrence). Free-text predicates
   stay deferred to Tier-2.
3. Multi-token form coexists with the YAML editor.
4. Case-study YAMLs are migrated to the new list shape with a
   verdict-preserving rewrite (no semantic change).

## Implementation order and status

1. **A1+A2+A3 — DONE.** Backend composition, FM1 cross-token wiring,
   `docs/proofs/composition.md`. 6 new tests
   (`tests/test_multi_mechanism.py`).
2. **B1 — DONE.** `CrossTokenFlow.coupling` and `coupling_ratio` schema;
   `verifier.asymptotic.cross_token_flow_rate` helper;
   `docs/proofs/coupled_flows.md`. 7 new tests
   (`tests/test_coupled_flows.py`). Also fixed FM3's "no burn" early
   return to account for incoming cross-token BURN flows.
3. **C1+C2+C3+C4+C5 — DONE.** Multi-token form shell with `+ Add token`,
   per-token multi-mechanism mint/burn lists with full asymptotic-class
   selectors (parity for burn), cross-token flows UI with coupling toggle,
   and live composition preview. The form template uses HTML `<template>`
   elements cloned by JS; all five case-study YAMLs round-trip cleanly.
4. **D1+D2+D5 — DONE.** `RiskLevel` enum on `Verdict` with midpoint-based
   computation per Simulator.pdf §4 bands; `OverallRiskScore` on the
   Report per §6; `verdict.js` renders the colour-coded band on each card
   and the overall score in the report header. 14 new tests
   (`tests/test_risk_levels.py`).
5. **B2+B3 — DONE.** Structured `Condition` model
   (`ThresholdCondition` / `TimeWindow` / `EventOccurrence`) and
   3-valued (always / ever / never) static evaluator. FM1 and FM3
   gate per-rule contributions on the result with side-correct
   conservatism (emission rules: include if *ever* satisfied; burn
   rules: include only if *always* satisfied). Free-text
   `event_predicate` kept for back-compat. Proof:
   `docs/proofs/conditional_rules.md`.
6. **D3 — DONE.** Six new Simulator.pdf §5 coherence checks
   (C2 NFR5+self_reporting CRITICAL; C3 NFR1+no_burn CRITICAL;
   C4 NFR7=immediate+Γ=1; C5 NFR3+DAO; C6 retain_value+expiry;
   C7 ros>1.5+ρ=0+Γ=1 CRITICAL — verdict-aware). Existing rules 1–3
   preserved. C7 uses the post-Phase-D risk_level surface.
7. **D4 — DONE.** `derive_token_role(token)` returns one of
   `utility / governance / reputation / resource`. Dispatcher applies
   the Simulator.pdf §4 multi-token table after running the FMs:
   reputation tokens get NOT_APPLICABLE on FM1/FM2/FM3; governance
   tokens skip FM2 (always intended high τ̄) and relax FM3 (ρ=0 OK).
   Resource tokens carry an FM1 mitigation note in `explanation`.

## Design choices (memos)

### B2+B3 — three-valued static evaluation

A condition's status in the declared box is `ALWAYS | EVER | NEVER`.
For an emission rule, conservatism over the existential SMT query
demands inclusion if the condition is *ever* satisfied (over-counting
emission worsens FM1/FM3 sustainability — sound). For a burn rule,
conservatism demands inclusion *only when always* satisfied
(under-counting burn worsens FM3 — sound). This double-conservativity
is what makes the conditional layer compatible with the existential
verifier semantics. Conjunction of conditions: ALWAYS = all-ALWAYS;
NEVER = any-NEVER; otherwise EVER.

### D3 — verdict-aware coherence

`coherence_violations(te, verdicts=None)` runs IR-only checks unconditionally
and verdict-aware checks (C7) only when `verdicts` is supplied.
The dispatcher invokes the function twice: once for the early
severity escalation (IR-only), then again with verdicts attached for
the final report. C7's "ros>1.5" maps to "any FM1 verdict has
risk_level in {red, red_critical}"; "ρ=0" maps to "any FM3 verdict
has risk_level == red_critical"; "Γ=1.0" maps to "all
rule_structure entries are SINGLE_ENTITY".

### D4 — role derivation rules

```
function == [REPUTATION_MARKER]                → REPUTATION
GOVERNANCE_RIGHT in function and not transferable → GOVERNANCE
GOVERNANCE_RIGHT in function and STORE_OF_VALUE in function → GOVERNANCE
value_anchor == PHYSICAL_QUANTITY              → RESOURCE
otherwise                                       → UTILITY
```

Applied in `verifier.token_role.derive_token_role`. The dispatcher
post-processes verdicts: per-token FMs (FM1/FM2/FM3) get
NOT_APPLICABLE for the corresponding token-id when the role's skip
table includes that FM. This is a refinement on top of the existing
applicability gates inside each FM module — those still fire, this
adds explicit role-based skips that a future Tier-2 mechanization
can reason about.
8. **E2 — DONE.** Doc updates (this file, CLAUDE.md, webapp/README.md,
   api-contract.md, simulator-mapping.md).

Test count: **210** (started at 150, +60 across the redesign phases).

Per-phase test additions:
- A1+A2+A3 — `tests/test_multi_mechanism.py` (6)
- B1 — `tests/test_coupled_flows.py` (7)
- C1+C2+C3+C4+C5 — round-trip-only (no new pytest file; backend unchanged)
- D1+D2+D5 — `tests/test_risk_levels.py` (14)
- D3 — `tests/test_coherence_simulator.py` (9)
- B2+B3 — `tests/test_conditional_rules.py` (12)
- D4 — `tests/test_token_role.py` (12)
