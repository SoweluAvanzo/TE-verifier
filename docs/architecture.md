# Token Economy Verifier — Architecture

This is the canonical project document. It is written for collaborators who may not have a background in formal verification, mathematical logic, or theorem proving. Every technical term is defined inline. Read it once before contributing.

---

## 1. Context — what we are building and why

The repository starts from two source artifacts:

- `Roadmap Simulatore Irene.docx` — a roadmap describing a structured questionnaire that elicits a token economy design from a user.
- `Six_Failure_Modes…pdf` (DLT2026, Domenicale–Avanzo–Schifanella) — a paper defining the formal sustainability conditions that a community token economy must satisfy.

On top of these, we are building a **verifier**: a tool that reads the questionnaire output and tells the designer, automatically, whether their token economy will fail and exactly *how* — backed by mathematical proof, not just simulation.

The two source documents play complementary roles:

- The roadmap defines the **left edge of the pipeline** (what the user tells the tool).
- The paper defines the **right edge** (what the tool must verify and prove).

Everything in this architecture — the intermediate representation, the formal model, the model checker, the simulator, the proofs document — is the bridge between those two edges. **When the two source documents disagree, the paper wins**: the paper's conditions are the formal target; the roadmap is a UX/elicitation design that can be rewritten as needed.

---

## 2. Glossary — every term used below, in one place

These are the words a non-specialist reader will keep tripping on. Read this section once; the rest of the document assumes it.

- **Token economy (TE).** A set of rules describing how digital tokens are created, exchanged, and destroyed in a community — who earns them, what they buy, how their supply changes over time. Concretely: the volunteer-reward, library-of-things, and food-redistribution case studies in §4 of the paper.

- **Specification.** A precise written description of what a system *is* and what it *must guarantee*. The questionnaire output is a specification of the user's TE.

- **Failure mode.** A specific way a token economy breaks down — for example, "tokens become worthless because too many were issued" or "nobody participates because there are not enough users to trade with." The paper defines six.

- **Property / sustainability condition.** A mathematical statement that, if true, means a particular failure mode is *not* triggered. Example: `N ≥ 2Kd + 1` (enough participants, given offer variety `K` and demand `d`).

- **Verification.** Checking, with mathematical certainty, whether a specification satisfies a property. Different from *testing*, which only checks specific examples. Verification covers all possible scenarios at once.

- **Model checker.** A program that takes (a model of) a system and a property, and either *proves* the property holds in every possible run of the system, or returns a **counterexample** — a concrete scenario in which it fails. Strength: fully automated. Weakness: limited expressiveness; some properties are too rich to encode.

- **Theorem prover (interactive).** A program that lets a human write mathematical proofs, then mechanically checks every logical step. Slower than a model checker, but can express anything that mathematics can express. Examples: Lean, Coq, Isabelle.

- **Counterexample.** A concrete failing case the model checker hands back: "with 47 participants, 5 offer types, and average demand 2, on day 23 the system enters the velocity trap; here is the trajectory." This is the artifact a user actually wants to see, because it explains *what* breaks.

- **Hybrid system.** A system whose state evolves both *continuously* (smoothly over time, like a token supply growing) and in *discrete jumps* (events, like a coupon redemption that burns a token instantly). Token economies are hybrid: supply curves are continuous, but redemption events are jumps. This is why ordinary discrete model checkers (designed for, say, network protocols) are not enough.

- **Differential dynamic logic (dL).** A formal language designed specifically to talk about hybrid systems. It mixes ordinary logic (∧, ∨, ∀, ∃) with mathematical descriptions of how things change over time (differential equations). KeYmaera X is the model checker that understands dL.

- **δ-decision procedure.** A practical compromise: when an exact yes/no answer to a continuous-math question is uncomputable, a δ-decision procedure gives a fast answer that is correct *up to a small numerical tolerance δ*. dReach/dReal use this. It is not as strong as a full proof, but it is much faster and produces counterexamples readily.

- **Asymptotic equivalence class.** A way of grouping functions by *how fast they grow over time*, ignoring exact constants. "Linear" means "grows roughly proportional to time." "Exponential" means "doubles every fixed period." If a user does not know the exact formula for their token emission, they can usually still say which growth family it belongs to. The model checker can then verify the property *for the entire family at once*.

- **Intermediate Representation (IR).** A single canonical data structure that every tool in the pipeline reads from and writes to. Without an IR, every tool has its own input format and you have to maintain `n × m` translators. With an IR, you only write `n + m`. The TE-IR is this project's IR.

- **Mechanized proof.** A mathematical proof written in a form a computer can re-verify from first principles. The advantage over a human-written proof is that no step can be wrong unnoticed: the computer either accepts the whole proof or points to the exact gap.

- **Simulation (agent-based).** Running the system forward in time on specific numerical inputs, with each participant modeled as a software agent making decisions. Tells you *what happens in this particular run* — not what happens in *all* runs. Useful when verification is too expensive or when you want concrete numbers.

- **Parameter sweep.** Re-running the simulation across a grid of input values (e.g. `N` from 50 to 500, `K` from 2 to 20) to find the boundary at which the system starts failing. The simulator's analogue of what a model checker does symbolically.

---

## 3. Why this technology stack — justified for a non-expert reader

A reasonable reader will ask: why not just write a simulator and run lots of experiments? Why introduce model checkers, theorem provers, intermediate representations? The short answer is **scope of guarantee**, and the long answer follows.

### 3.1 Why verification (not only simulation)

Simulation tells you what happens *in the runs you tried*. If a TE has 5 parameters, each with 10 plausible values, that is 100 000 combinations. A simulator can only hit a handful. Verification — done with a model checker or theorem prover — reasons about *all combinations at once*, mathematically. If a sustainability condition holds for the entire family, the user gets a much stronger statement: "your design is safe for **every** participant count in 50–500, **every** offer variety in 2–20, **every** emission rate in this asymptotic class." Simulation cannot deliver that. We still keep simulation as a fallback (see below), but it is not the primary line of defense.

### 3.2 Why a model checker first, simulation second

Model checkers are *cheap and precise* about whether a property holds, but *limited* in what kinds of properties they can express. Simulation is *expensive and approximate* (it samples), but can model arbitrary detail. The right strategy is: try the cheap precise tool first; reach for the expensive numeric tool only when the cheap one is silent (i.e. the property is outside what it can handle, or the user wants real-world numerical estimates rather than a yes/no). Reversing the order — simulating everything first — burns compute and gives weaker guarantees.

### 3.3 Why a hybrid model checker (KeYmaera X / dReach), not a discrete one

Token economies have continuous time evolution (supply rising, growth rates) *and* discrete events (a coupon redemption, a governance vote, a regime switch at a threshold). Discrete model checkers (NuSMV, SPIN, TLA+) cannot represent continuous dynamics natively — at best they discretize time into ticks, which is both slow and inaccurate. Hybrid model checkers are designed exactly for the "smooth + jumps" combination.

- **KeYmaera X** uses differential dynamic logic and produces *certified proofs*, the strongest possible output.
- **dReach/dReal** uses δ-decision procedures and produces *counterexamples quickly* — what a designer interactively iterating wants.

We adopt both: dReach for the interactive design loop, KeYmaera X for the rigorous final report.

### 3.4 Why Lean 4 + Mathlib for the proofs document

The project requires a parallel proofs document, ideally backed by a mechanized theorem prover. The reason to pick **Lean 4** specifically — not Coq or Isabelle — is that its mathematics library `Mathlib` already contains a full, polished treatment of *asymptotic equivalence classes* (the `Asymptotics` namespace, with `IsBigO`, `IsTheta`, `IsLittleO`). Since asymptotic classes are the central abstraction of our function modeling, this saves us from re-implementing them from scratch and gives us pre-proven theorems about how they compose. In short: the math the project needs is already formalized in Lean. Picking a different prover would mean rebuilding that foundation.

### 3.5 Why an IR (intermediate representation)

Without an IR, the questionnaire frontend would need to know how to talk to the simulator, the model checker, and the theorem prover — three different output formats, three different bug surfaces. With an IR, the questionnaire produces *one* well-defined data structure and small dedicated translators emit each tool's input. This is the standard "compiler frontend / backend" pattern and it lets us swap any tool without rewriting the questionnaire.

### 3.6 Why cadCAD for the simulator

cadCAD is a Python framework explicitly built for tokenomics simulation. The token-engineering research community already uses it. Choosing it makes the work legible to that community and avoids reinventing patterns (state-update functions, partial state updates, parameter sweeps) that already exist there. **Mesa** is kept as a fallback for cases where we need richer per-agent heterogeneity than cadCAD's update style affords.

### 3.7 Why the LLM has a tiny, well-defined role

The roadmap is explicit and we agree: only three of the questionnaire fields (the emission function shape, the governance rule structure, and graduated sanction escalation steps) genuinely need natural-language interpretation. Everywhere else, the input is a structured selection or a number. Letting the LLM creep into other fields would introduce nondeterminism into a system whose entire selling point is mathematical rigor. The LLM is a translator at three specific points — and a re-narrator at one (turning the verifier's output into prose for the user) — and nowhere else.

---

## 4. The Intermediate Representation (TE-IR) — one-page schema sketch

This is the core data structure. It is shown here as YAML-flavored pseudocode for readability; the *actual* format (JSON Schema, TypeScript types, Pydantic models) is an open implementation choice that does not affect the design. The schema is intentionally small enough to fit on one page.

```yaml
TokenEconomy:
  meta:
    name:               string
    description:        string
    nfrs:                                    # design declarations, used to reweight risks
      resilience:           1..5
      adaptability:         1..5
      accessibility:        1..5
      transparency:         1..5
      proportionality:      1..5
      circulation_speed:    enum{circulate_fast, balanced, retain_value}
      governance_maturity:  enum{immediate, short_term, medium_term, indefinite}

  tokens:                 [Token]            # multi-token first-class
  participants:           ParticipantsSpec
  governance:             GovernanceSpec
  cross_token_flows:      [CrossTokenFlow]   # one token's event triggers another's mint/burn

Token:
  id:                  string
  function:            [enum{medium_of_exchange, unit_of_account, governance_right,
                             access_right, store_of_value, reputation_marker}]
  value_anchor:        enum{none, physical_quantity, market_price, pegged}
  redemption:          RedemptionSpec
  initial_distribution: InitialDistributionSpec
  emission_rules:      [Rule]
  burn_rules:          [Rule]

Rule:                                        # used for both emission and burn
  trigger:
    kind:              enum{time_based, behavioral_event, physical_resource_flow, algorithmic}
    event_frequency:   AsymptoticClass?      # required iff kind != time_based
    event_predicate:   Predicate?            # what counts as the event
  function:
    sign:              enum{always_positive, always_negative,
                            threshold_positive, decreasing_positive}
    asymptotic_class:  AsymptoticClass
    parameters:        Map<string, NumberOrRange>
  regimes:             [RegimeSwitch]        # piecewise: different class above a threshold

AsymptoticClass:
  family:              enum{constant, bounded_range, linear, polynomial, log,
                            exponential, unspecified}
  degree:              int?                  # for polynomial only
  bounds:              {min, max}?           # for bounded_range only
  parameter_ranges:    Map<string, [min, max]>

RegimeSwitch:
  predicate:           Predicate             # e.g. t > 30d, M_total > 10_000, B_burned > E_emitted/2
  active_function:     {sign, asymptotic_class, parameters}

Predicate:                                   # small expression language; numbers, comparisons, and/or
  ast:                 ExpressionNode

ParticipantsSpec:
  count_N:             NumberOrRange
  expected_Q:          NumberOrRange
  growth:              AsymptoticClass
  agent_types:         [AgentType]
  topology:            enum{well_mixed, spatial, network}
  topology_params:     Map<string, any>?     # e.g. average degree for network

AgentType:
  id:                  string
  fraction:            float                 # share of population
  expected_holding_time: Distribution        # mean + variance, or a class
  utility_hint:        text                  # free-text input → LLM translates → utility function

GovernanceSpec:
  type:                enum{centralized, committee, dao, algorithmic, hybrid}
  rule_structure:      Map<DecisionId, ControllingActor>   # who controls each lever
  monitoring_capacity: float[0,1]            # γ
  sanction_structure:  SanctionSpec          # S
  centralization_index: float[0,1]?          # Γ — derived if not provided

CrossTokenFlow:
  source_token:        TokenId
  source_event:        Predicate             # e.g. "burn happens"
  target_token:        TokenId
  target_action:       enum{mint, burn, transfer}
  amount:              {asymptotic_class, parameters}
```

### 4.1 Key properties of this IR

- **Multi-token by construction.** The roadmap document is single-token; the IR is not. `tokens: [Token]` plus `cross_token_flows` is the generalization.
- **Functions described by *(sign, asymptotic class, parameter ranges)*** rather than exact formulas. The model checker can verify properties even when the user has not pinned down constants.
- **Threshold-driven regime switches are first-class** (`RegimeSwitch`). A function may be logarithmic below a threshold and exponential above it; this is captured directly.
- **Cross-token flows let one token's behavior depend on another's** — needed for any TE with multiple tokens (e.g. a governance token whose emission is triggered by a utility token's burn).
- **Underspecification is a legal value.** `AsymptoticClass.family = unspecified` tells the verifier: "the user did not pin this down — check across the whole class lattice." This is the formal handle for the "if the user has no sufficient ideas" case the project explicitly requires.
- **Mixed profiles evaluated late.** Cross-token flows and regime switches whose predicates depend on multiple tokens cannot be resolved until the full IR is assembled. The verifier evaluates them in a final pass after the per-token analysis.

---

## 5. End-to-end pipeline — minimal diagram

```
                      ┌─────────────────────────────┐
                      │    Questionnaire UI         │
                      │  (5 parameter groups, NFRs) │
                      └────────────┬────────────────┘
                                   │ structured answers
                                   ▼
                      ┌─────────────────────────────┐
   LLM translator ◄──►│   TE-IR (typed JSON)        │
   for fields         │   — partial, may have       │
   2.2 / 4.2 / 4.5    │     `unspecified` slots     │
                      └────────────┬────────────────┘
                                   │ resolved IR
                                   ▼
                      ┌─────────────────────────────┐
                      │   Static-checker dispatcher │
                      └─┬─────────┬───────────┬─────┘
                        │         │           │
              ┌─────────▼──┐ ┌────▼─────┐ ┌───▼──────────┐
              │ IR → .drh  │ │ IR → dL  │ │ IR → Lean 4  │
              └────┬───────┘ └────┬─────┘ └───┬──────────┘
                   │              │            │
              ┌────▼─────┐  ┌─────▼──────┐ ┌───▼─────────────┐
              │ dReach / │  │ KeYmaera X │ │ Lean + Mathlib  │
              │  dReal   │  │            │ │ (proofs document)│
              └────┬─────┘  └─────┬──────┘ └───┬─────────────┘
                   │              │            │
                   │ counterex.   │ certified  │ mechanized
                   │ trajectory   │ proof or   │ theorem
                   │              │ open goals │
                   ▼              ▼            ▼
              ┌─────────────────────────────────┐
              │   Diagnostic aggregator         │
              │   (per failure mode: pass /     │
              │    fail + counterexample)       │
              └────────────┬────────────────────┘
                           │
       ┌───────────────────┴────────────┐
       │   Falls back to simulation if  │
       │   static layer is inconclusive │
       │   or if user wants concrete    │
       │   numbers / sweeps             │
       │                                │
       │      IR → cadCAD model         │
       │           │                    │
       │           ▼                    │
       │     Simulation runs +          │
       │     parameter sweeps           │
       └───────────────┬────────────────┘
                       ▼
              ┌──────────────────────┐
              │  Result narrator LLM │
              │  (translates verdict │
              │  + counterexamples   │
              │  into user prose)    │
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │   User-facing report │
              │   (per-failure-mode  │
              │   verdict, scenario, │
              │   redesign hints)    │
              └──────────────────────┘
```

### 5.1 Stage-by-stage

1. **Questionnaire UI** — collects structured answers per the roadmap's five groups + seven NFRs. Implementation choice (TypeScript/React vs Python/FastAPI) is open and low-stakes.
2. **LLM translator (narrow)** — runs only on emission function descriptions, governance rule structures, and graduated-sanction escalation. Output is a *resolved* TE-IR with structured fields filled in.
3. **Static-checker dispatcher** — takes the resolved IR and fans it out to the three formal backends. Each backend has a translator (IR → tool input) maintained in this repo.
4. **dReach/dReal** — fast counterexample-finding for the interactive design loop. Returns "no failure found within δ" or a concrete failing trajectory.
5. **KeYmaera X** — for the user who wants the rigorous "this design is provably sustainable" statement. Returns a certified proof object or a list of unproven goals.
6. **Lean 4 + Mathlib** — produces the mechanized proofs document recording, for each verified property, the formal statement and proof. This is a project artifact, not a per-user output.
7. **Diagnostic aggregator** — collects per-failure-mode verdicts and counterexamples into a single result object indexed by the six failure modes from the paper.
8. **cadCAD simulation fallback** — runs whenever the static layer says "inconclusive" or the user explicitly requests concrete numerical projections / parameter sweeps.
9. **Result narrator LLM** — re-translates the verifier output into user-facing prose: which failure modes are flagged, the concrete scenario in which each one bites, and which design knob to turn to fix it.

---

## 6. Outcomes and implications

### 6.1 Direct outcome

A designer of a community token economy fills out a questionnaire and receives, automatically:

- A per-failure-mode verdict (one of the six from the paper).
- For each flagged failure mode, a concrete scenario showing exactly how it fails — specific participant counts, a specific day, a specific sequence of events.
- For verdicts the static checker proved, a certificate that can be re-checked by anyone.
- Where static reasoning was insufficient, simulation results with parameter sweeps showing the boundary at which failure begins.
- A natural-language redesign suggestion grounded in the failed condition.

### 6.2 Implications

- **Design-stage risk assessment without longitudinal data.** Today, validating a TE means deploying it and waiting months for transaction logs. This tool moves the assessment to before deployment, where corrections are cheap.
- **Reproducibility.** Anyone — reviewers, collaborators, future you — can re-run the verifier and re-check the proofs. There is no "trust me, I ran the simulator." Every claim is a re-checkable artifact.
- **Academic citability.** Because the proofs document is mechanized (computer-checked Lean), the rigor argument in any paper using this tool is unusually strong. This raises the ceiling of what claims the research group can credibly publish.
- **Extensibility.** Adding a seventh failure mode means adding one IR predicate and one translator clause per backend — not rewriting the questionnaire or the simulator. The IR is the load-bearing abstraction.
- **Cost of rigor.** KeYmaera X and Lean both have a learning curve. The first three to six months of work will feel slower than just writing a simulator. The payoff arrives the first time the verifier finds a failure mode that simulation missed, or the first time a reviewer asks "why should we believe this?" and the answer is a Lean proof.

---

## 7. Project layout (planned, not yet scaffolded)

These directories and files do not exist yet. They are listed so future implementation rounds know what to scaffold and in what order:

- `schema/` — the TE-IR definition. Format choice (JSON Schema / TypeScript / Pydantic) is open.
- `translators/`
  - `ir_to_drh.{py,ts}` — IR → dReach `.drh`.
  - `ir_to_dl.{py,ts}` — IR → KeYmaera X dL.
  - `ir_to_lean.{py,ts}` — IR → Lean 4 stubs.
  - `ir_to_cadcad.py` — IR → cadCAD model.
- `verifier/`
  - `dispatcher.py` — drives the three static backends and aggregates results.
  - `aggregator.py` — collates per-failure-mode verdicts and counterexamples.
- `proofs/` — Lean 4 project housing the mechanized proofs document. Each of the six failure modes gets a file containing the formal statement and its proof, leaning on `Mathlib.Asymptotics` for class-level reasoning.
- `narrator/` — LLM-driven result re-narration.
- `frontend/` — the questionnaire UI.

The recommended build order is: **schema → Lean 4 proofs of the six conditions → translators → dispatcher → frontend → narrator → cadCAD fallback.** Proving the conditions in Lean first forces us to confront any ambiguity in the paper before committing to a translator implementation.

---

## 8. Verification (how we know the architecture is sound)

This document is a design artifact, so "verification" means alignment, not test execution.

1. **Spot-check against the paper.** Every formal condition referenced in this document (`Γ > 0.5`, `τ̄ → 1`, `N ≥ 2Kd + 1`, `E(t) − B(t) ≤ g(t) · M(t)`, `φ ≥ d/K`, `γS > T − R`) is traceable to §3 of the failure-modes paper.
2. **Spot-check against the roadmap.** The five parameter groups and seven NFRs in the IR sketch match the roadmap's numbering 1.1–5.8 and NFR1–NFR7.
3. **Coverage of the project's stated requirements.**
   - Continuous-time verification ➜ KeYmaera X (dL) + dReach.
   - Asymptotic-class reasoning with second-order event-frequency dependencies ➜ `AsymptoticClass` is recursive (event frequency is itself an `AsymptoticClass`).
   - Threshold/regime switches ➜ `RegimeSwitch` first-class.
   - Mixed profile evaluated late ➜ explicit final pass over cross-token flows.
   - Multi-token support ➜ `tokens: [Token]` and `cross_token_flows: [CrossTokenFlow]`.
   - Mechanized proofs ➜ Lean 4 + Mathlib, with explicit reuse of `Asymptotics` for the equivalence-class abstraction.
   - Underspecified inputs handled by the model checker ➜ `unspecified` is a legal `AsymptoticClass.family`; dispatcher fans out across the class lattice.
   - Counterexample as the primary failure artifact ➜ pipeline final stage is exactly that.

If any of these is misaligned with the project's intent, that is the redirect signal — open an issue or amend this document directly.
