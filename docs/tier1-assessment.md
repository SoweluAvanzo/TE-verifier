# Tier-1 Verifier — Implementation and Assessment

> **Phase 5 update.** This document was originally written for the
> Phase 0 Tier-1 release (Z3 + Python, 38 tests). Through Phases 1–5
> the verifier has been extended with closed-form critical-value
> extraction, a paper-faithful elicitation layer, archetype-driven
> routing, cross-token-flow consumption, topology correction, and NFR
> reweighting. **150 tests pass.** Below is the original Phase 0
> narrative, preserved for historical context. See the `docs/` index
> for the full post-Phase-5 doc map.

This document records the actual Tier-1 verifier implementation: what was built, what the modifications to the architecture were, what the empirical test results are on the five case studies, and what the implementation surfaces about the limits and next steps.

## Suitability evaluation (decision recap)

The architecture in [docs/architecture.md](architecture.md) proposed KeYmaera X + dReach + Lean 4 + cadCAD as the verification stack. Two facts pushed Tier-1 toward a leaner choice:

1. **The paper's six failure-mode conditions are closed-form algebraic inequalities.** The case studies in [docs/case-studies.md](case-studies.md) were all decidable analytically — no continuous-time hybrid reasoning was strictly required to flag any of them. KeYmaera X / dReach are over-specified for design-stage verification.
2. **The "small laptop" constraint** rules out heavy installations (KeYmaera X needs JVM and complex setup; Lean 4 + Mathlib is ~5 GB; dReach requires a C++ build).

Modification adopted: a pragmatic two-tier architecture. Tier-1 uses **Z3 SMT** + **Python** + **Pydantic** + **PyYAML** — all pip-installable, ~30 MB of dependencies, runs in 0.2 s on 70 MB of RAM for the largest case study. The architecture document's IR, dispatcher, FM-as-modules, and counterexample-first output are all preserved; only the heavy backends are deferred. Adding a Tier-2 backend later means writing one translator and registering it behind the existing `FailureMode` interface — the IR, CLI, and tests do not change.

## What was built

```
schema/
  te_ir.py          # Pydantic v2 models for the TE-IR
verifier/
  __init__.py
  constants.py      # Named thresholds (paper-citable, no magic numbers)
  asymptotic.py     # AsymptoticClass → Z3 expression helpers
  dispatcher.py     # Runs all FMs, aggregates Verdicts into a Report
  cli.py            # te-verify CLI entry point
  failure_modes/
    __init__.py     # ALL_FAILURE_MODES registry
    base.py         # FailureMode ABC, Verdict, Counterexample, Z3 helpers
    fm1_oversupply.py
    fm2_velocity.py
    fm3_burn_emission.py
    fm4_freerider.py
    fm5_critical_mass.py
    fm6_governance.py
examples/
  bitcoin.yaml
  ethereum.yaml
  makerdao.yaml
  curve_vecrv.yaml
  axie_infinity.yaml
tests/
  conftest.py
  test_unit_failure_modes.py    # 13 unit tests
  test_case_studies.py          # 25 integration tests
pyproject.toml
```

### Design properties

- **No hardcoded thresholds in failure-mode logic.** All numerical thresholds (`τ̄ ≤ 1.5`, `Γ > 0.5`, `Gini > 0.6`, `ρ ≥ 1`) live in `verifier/constants.py` with explicit citations to paper equations.
- **No hardcoded token names or token-economy specifics.** The verifier is fully driven by the IR; the same dispatcher runs Bitcoin and Axie without knowing which is which.
- **Each failure mode is a self-contained module** implementing the `FailureMode` ABC. Adding FM7 is a one-file addition plus registration in `__init__.py`.
- **YAML examples are external.** Case studies are not Python literals — they live in `examples/*.yaml` and are loaded the same way an end-user TE would be.
- **The ALL_FAILURE_MODES registry is the single source of truth** for which checks the dispatcher runs. Tests can pass a subset to `verify(...)` for isolation.
- **NFR reweighting is implemented.** A token that declares `circulation_speed = circulate_fast` and triggers FM2 is reported as `pass_as_intended` rather than `fail`, matching the paper's NFR-driven semantics.
- **Verdicts include explanation, formal_condition, counterexample, and suggestions.** The output is designed for the user-facing narrator described in the architecture, not a developer dump.

## Empirical results — five case studies

The five YAML examples were run through the dispatcher and against `pytest`. Results match the analytical predictions in [docs/case-studies.md](case-studies.md) within Tier-1 conservatism limits.

### Verdict matrix (current run)

| Case | FM1 (per token) | FM2 | FM3 | FM4 | FM5 | FM6 |
|---|---|---|---|---|---|---|
| **Bitcoin** | BTC: pass | BTC: pass | BTC: **fail** (no burn) | N/A | pass | **fail** (Gini > 0.6) |
| **Ethereum** | ETH: pass | ETH: pass | ETH: pass (demand-driven) | N/A | pass | **fail** (Gini > 0.6) |
| **MakerDAO** | DAI: fail; MKR: pass | both pass | DAI: fail; MKR: pass | **fail** | **fail** | **fail** |
| **Curve / veCRV** | CRV: fail; veCRV: N/A | CRV: pass; veCRV: N/A | CRV: **fail** (no burn); veCRV: fail | N/A | pass | **fail** (Gini > 0.6) |
| **Axie Infinity** | AXS: pass; **SLP: fail** | both `pass_as_intended` (NFR6) | both **fail** | **fail** | pass | **fail** |

### What lines up with the case-study analytical traces

- **Bitcoin** — clean pass on supply-side modes; FM3 flagged for absent burn; FM6 flagged on Gini concentration. Exactly what the analytical trace predicted.
- **Ethereum** — clean structural pass on FM3 because burn is demand-driven (`BurnTriggerKind.DEMAND_DRIVEN` → demand-coupled rate). The structural-credit pathway in `fm3_burn_emission.py` rewards Ethereum's design correctly.
- **Curve veCRV** — non-transferable token correctly skipped for FM1 and FM2 (`Status.NOT_APPLICABLE`). CRV flagged for missing burn. FM6 flagged via Gini because veCRV concentration via Convex was encoded as `token_balance_gini.max = 0.85`.
- **Axie SLP** — **the headline result.** The verifier predicts FM1 oversupply and FM3 burn-imbalance for SLP from the public design parameters alone. With `event_frequency: linear` for emission events scaling with active player count and a constant per-event payout, the per-period emission rate explodes when the player base grows; the burn (breeding) is `event_frequency: unspecified` including zero, modeling the fact that breeding demand is not coupled to player count. The `(rule_rate_per_period = function × frequency)` helper is what makes this counterexample trigger correctly.
- **Axie FM2** — both AXS and SLP exhibit τ̄ ≤ 1.5 (scholar holding times of 0.1 periods drag the wealth-weighted average down), but the YAML declares `NFR6 = circulate_fast`, so the verdict is `pass_as_intended`, not fail. This is a useful pedagogical output: it tells the user *"your declared design intent matches the structural behaviour we found"* — for Axie, that NFR declaration was itself a misrepresentation, which is its own diagnostic finding.

### Where Tier-1 conservatism exceeds the analytical trace

The case-study document predicted clean passes for Ethereum FM3 and DAI FM3; the verifier flags DAI FM3 fail. Diagnosis: the YAML's emission and burn parameter ranges for DAI are wide and *independent in the verifier's view*. Z3 finds an assignment with emission at the upper bound (~3.3 M DAI/week) and burn at the lower bound (~50 K DAI/week). In reality these rates are tightly coupled (burn happens when vaults close, which scales with vault openings). Tier-1 cannot express this coupling without either (a) tighter user-supplied ranges or (b) a Tier-2 modeling construct for **rate coupling between emission and burn rules** (e.g. a shared event volume variable).

This is not a verifier bug — it is the cost of letting the user say "I don't know" for both rates independently. The honest fix is the IR addition outlined below.

### Headline performance numbers

- **Wall clock for a single TE verify (Axie, the largest example):** 0.21 s
- **Peak resident memory:** ~70 MB
- **Total test suite (38 tests):** 0.41 s

This satisfies the "small laptop" constraint with significant margin. A questionnaire UI could re-run the verifier on every parameter slider drag.

## What the implementation surfaces about the IR

The implementation work surfaced four concrete IR or modeling gaps that were not visible from the architecture-doc-level analysis. They are listed here in priority order for the next iteration.

1. **Rate coupling between emission and burn rules.** As above — Tier-1 treats the parameter ranges of emission and burn rules as independent. For demand-driven burn, they are not: the event frequency on the burn rule should be the *same* event variable as the redemption stream. The IR needs either a `shared_event` reference between rules or an explicit `coupled_to_emission_id` field so Z3 introduces a single variable.

2. **External signals are still not first-class.** Confirmed from the case-study work and now confirmed empirically: MakerDAO's actual failure mode (Black Thursday oracle delay) cannot be expressed in the current IR. The case-study YAML for MakerDAO produces verdicts that miss the real risk. Adding `ExternalSignal` with bounded value, bounded derivative, and observation-lag is the highest-priority IR addition for fidelity on stablecoin/oracle systems.

3. **Time-decaying balances.** Curve veCRV's per-position decay was approximated by a continuous burn rule on the aggregate, which is structurally wrong (decay is per-lock, not aggregate). Adding `LinearlyDecayingBalance` as an IR construct lets the FM machinery reason about per-position state.

4. **Asymptotic-class lattice gaps.** The current `AsymptoticFamily` is missing two real-world classes:
   - **Sub-linear root** (Ethereum's `√(stake)` issuance) — currently approximated by `linear` with tighter ranges, which is structurally wrong.
   - **Decreasing-toward-cap** (Bitcoin / Curve emission across halvings or vesting decay) — currently approximated by `constant` with bounds set to current rate, which loses the long-term-decay signal.

A `derived` family that defers to Lean's `IsBigO` machinery (planned for Tier-2) closes this gap without growing the lattice indefinitely.

## What the implementation tells us about the specification flow

[docs/specification-flow.md](specification-flow.md) was written before any code existed; the implementation validates the flow's structure and surfaces two refinements:

- **The "I don't know" handling works as designed.** Setting `event_frequency.family = unspecified` for Axie SLP's burn rule produced the expected counterexample (verifier searched over the entire range including zero, found the failure scenario corresponding to player-growth collapse). The flow's explicit "I don't know is fine" affordance is load-bearing — without it, Axie users would have specified an unrealistic positive lower bound for breeding frequency and the failure would have been hidden.
- **Stage 8.4's forced "worst-case decline rate" question is essential.** Axie's IR includes `growth_g.parameter_ranges.value: [-0.5, 1.0]` — the negative lower bound is what makes the verifier explore the post-saturation collapse trajectory. If the questionnaire let the user write `[0, 1.0]` (which is what Axie's designers implicitly assumed), the headline failure would not have been flagged.
- **The archetype-driven defaults need an actual implementation.** The `meta.archetype` field is now in the schema but not yet consumed. A small extension to the dispatcher could, for example, auto-mark FM4 as N/A for `native_protocol_asset` archetypes, saving the user from receiving an irrelevant `not_applicable` verdict.

## Limits to be transparent about

- **Tier-1 reasons over design-stage parameters, not trajectories.** It cannot say "in week 23 the system enters the velocity trap because growth dropped below `g*`." That kind of trajectory-level statement requires Tier-2 (KeYmaera X or cadCAD).
- **No oracle / external-signal reasoning.** MakerDAO's Black Thursday is not catchable until the IR grows the `ExternalSignal` construct.
- **Conservative independent worst-case search.** Without rate-coupling, the verifier flags real-but-unlikely combinations. The user can mitigate by tightening parameter ranges; the proper fix is the IR addition above.
- **NFR reweighting is binary** (pass / pass_as_intended / fail). A weighting scheme that quantifies "how much" an NFR mitigates a flag is future work.
- **No simulation fallback yet.** The architecture's cadCAD path is not built; when Tier-1 returns `inconclusive` (it does on FM5 for spatial topologies), there is no automatic recovery.

## How to run

```bash
# create a local venv and install
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# verify a TE-IR file
te-verify examples/axie_infinity.yaml

# JSON output for piping into other tools
te-verify examples/axie_infinity.yaml --json

# tests
pip install pytest
pytest -v
```

## Verdict on suitability

The Tier-1 stack (Z3 + Python) is **sufficient for design-stage verification** of the failure modes the paper formalizes, and it runs comfortably on any modern laptop. It correctly reproduces the analytical traces for Bitcoin, Ethereum, Curve, and Axie, with a transparent over-flagging on MakerDAO that points cleanly to the next IR addition (rate coupling / external signals).

The full architecture proposal (KeYmaera X + dReach + Lean + cadCAD) remains correct as a **Tier-2 superset** for users who need certified proofs, time-trajectory counterexamples, or oracle-rate reasoning. Tier-1 ships now and is enough for the questionnaire UI, the design-stage diagnostic, and the academic case-studies replication.
