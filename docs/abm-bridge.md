# ABM bridge — verifier → cadCAD contract

## Reference ABM (`te-simulate`)

A reference implementation lives at `verifier/abm/`. It consumes
`ReachabilityVerdict` JSON, runs a Monte Carlo over the declared
parameter ranges, and reports `P(violation)` with Wilson 95% CIs,
plus the *deployment-vs-dynamic* split per failure mode.

```bash
# Two-step pipeline:
te-verify spec.yaml --minimal --json > verdicts.json
te-simulate spec.yaml --verdicts verdicts.json --runs 1000 --seed 42

# One-step (te-simulate runs the verifier itself):
te-simulate spec.yaml --runs 1000
```

Sample output (Axie, condensed):

```
FM   subject     verifier        P(deploy)   P(dynamic)   t_med  t_p95
----------------------------------------------------------------------
FM1  SLP         fragile         92%         0%           —      —
FM3  SLP         fragile         92%         0%           —      —
FM4  system      fragile         100%        0%           —      —
FM6  system      broken          —           —            —      —

Headline:
  • FM1[SLP]: violates AT DEPLOYMENT in 92% of runs — the sampled
    parameters often land in the unsafe region from the start.
  • FM6[system]: verifier says BROKEN — no parameter assignment in
    the box satisfies the FM. The ABM cannot rescue a structurally-
    broken design; redesign first.
```

The reference engine is intentionally cadCAD-shaped (state is a
plain dict, per-period evolution is a pure function, predicates are
state→bool). Migrating to real cadCAD is a translation, not a rewrite.

### Deployment vs dynamic — the load-bearing distinction

The reference engine reports two violation probabilities per FM:

* **P(deploy)** — fraction of runs where the *sampled* parameters
  already violate at `t=0`. This is a *configuration* signal: the
  user's declared parameter ranges include unsafe corners that the
  uniform sampling reaches. The fix is to tighten the ranges.
* **P(dynamic)** — fraction of runs that pass at `t=0` but drift
  into the unsafe region during the horizon. This is a *dynamics*
  signal: even safe initial parameters evolve into violation over
  time. The fix is a corrective mechanism (burn, vote cap,
  adjustable rate) that triggers before the drift escalates.

This split is what makes the ABM output *actionable*. The verifier
says "violation reachable somewhere in the box"; the ABM tells the
user whether the unsafe region is the parameter-range upper-bound
they should tighten, or a long-run drift their static spec doesn't
capture.

### Triage rules

The engine consults `ReachabilityVerdict.structural_status` to decide
whether to simulate each FM:

| Status | Engine behavior |
|---|---|
| `SOUND` | Skipped. Verifier proved unreachability. |
| `FRAGILE` | Simulated. The headline case. |
| `INCONCLUSIVE` | Simulated. Surface a caveat in the report. |
| `BROKEN` | Skipped. No parameter shift in the box passes — redesign first. |
| `NOT_APPLICABLE` | Skipped. The FM doesn't apply. |

`--simulate-all` overrides this triage for sanity checking.

### Suppressed predicates

When the verifier's design intent rules out a check (e.g. FM3 for a
capped-supply token like Bitcoin, where ρ=0 is *intentional*), the
FM emits no `SafetyPredicate`. The ABM then skips it rather than
falsely reporting `100% deployment violation` from a predicate the
user's design doesn't claim to satisfy. The verifier's
`pass_as_intended` is the canonical signal for these cases; the ABM
defers rather than re-evaluating.

### Three engine extensions (shipped)

The reference engine has grown three substantive features beyond the
v0 aggregate Monte Carlo:

**1. Per-period rate noise via `DistributionSpec`.**

A rule's `FunctionShape.distribution` field (optional, defaults None)
opts that rule into per-period resampling. The verifier still sees the
*support* of the distribution and reasons over that range; the ABM
samples from the distribution proper each period.

```yaml
emission_rules:
  - trigger: { kind: time_based }
    function:
      sign: always_positive
      asymptotic_class:
        family: constant
        parameter_ranges:
          c: { min: 1000, max: 2000 }
      # New: opt-in stochastic per-period sampling
      distribution:
        kind: lognormal
        parameters: { mu: 7.3, sigma: 0.3 }
```

Supported families: `uniform`, `normal`, `lognormal`, `bernoulli`,
`poisson`, `beta`. Without `distribution`, the rule samples once per
run from its declared NumberRange (current behavior preserved).

**2. Per-agent state.**

`state["agents"]` is a list of agent dicts (`id`, `type`, `balance`,
`holding_time`, `last_action`). Spawned proportionally from
`participants.agent_types`, capped at 200 for tractability. Lazy
spawn: agents are only created if FM2 is among the simulated FMs (no
cost for supply-side-only runs).

`tau_bar` becomes a live computation: per period each agent's clock
advances; agents whose holding time has elapsed "act" (reset). The
balance-weighted average across all agents is the live `tau_bar`,
replacing the once-per-run aggregate.

Future extensions (deferred): trading between agents (live Gini
evolution), utility-driven action choice (replace the clock with
payoff-comparing decisions), spawn/death (agents arriving and leaving
per growth_g).

**3. cadCAD-compatible export (`verifier.abm.cadcad_export`).**

`export_cadcad_config(te, verdicts)` produces a config dict matching
cadCAD's expectations:

* `initial_state` — genesis state from IR midpoints.
* `state_update_blocks` — one PSUB per simulable (FM, subject), with
  policies derived from the SafetyPredicate contract.
* `sim_config` — `N` (replicates), `T` (timesteps), `M` (variants).
* `params` — sweepable parameter dict; cadCAD interprets length-N
  value lists as sweep grids.
* `metadata.skipped_fms` — verifier verdicts (SOUND, BROKEN,
  NOT_APPLICABLE) that didn't get a PSUB, with skip reasons.

The exporter does **not** import cadCAD. It produces the data; the
user wires it into their own cadCAD `Experiment` / `Executor`. This
keeps cadCAD as an optional heavy dependency while letting users
who want it have a clean handoff.

### Still deferred to a future iteration

* **External shocks** — no oracle-delay model, no exchange-rate
  noise. The IR's stochastic envelope is fully evaluated only after
  the schema's `DistributionSpec` infrastructure lands across more
  fields (event_frequency, cross-token flow amounts, etc.).
* **Trading mechanics + live Gini evolution.** Agents currently hold
  static balances. Adding peer-to-peer transfers and redemption
  outflows produces meaningful Gini dynamics — needed for the FM6
  long-run-concentration story.
* **Utility-driven action selection.** Agents currently act on a
  clock; replacing the clock with `UtilityWeights` lookups closes the
  loop with the IR's utility model.

Each gap is a deliberate boundary between v1 reference and a
production ABM. The contract (state dict, predicate evaluation,
report shape, cadCAD export shape) is stable across these extensions.



The verifier produces a **minimal reachability output** (`verifier.minimal.minimal_verdicts`,
`te-verify --minimal`) that downstream agent-based simulators consume
to add likelihood, time-resolved trajectories, and per-agent dynamics
on top of the formal yes/no facts. This document specifies the
contract so cadCAD configs, native-Python ABMs, or any other
simulator can pick it up cleanly.

## Why the split exists

The verifier and the ABM answer different questions:

| | Verifier (this codebase) | ABM (cadCAD or equivalent) |
|---|---|---|
| Native question | "∃ x ∈ box. violation?" | "P(violation \| stochastic dynamics, starting from x)" |
| Layer | Formal (Z3 / arithmetic, decidable) | Empirical (Monte Carlo, samples) |
| Output | Reachability, threshold, witness | Likelihood, trajectory, per-agent breakdown |
| Confidence | Universal quantification over the box | Frequentist over N replicates |

Neither replaces the other. The verifier's answer is qualitatively
sharper (existence is closed-form); the ABM's answer is
quantitatively richer (likelihood is something users care about).

The minimal output is the precise interface between the two.

## The handoff format

`verifier.minimal.minimal_verdicts(te, config)` returns a list of
`ReachabilityVerdict`. Each entry has:

| Field | Type | Meaning |
|---|---|---|
| `failure_mode` | string (`"FM1"`...`"FM6"`) | which paper §3 mode |
| `subject` | string | token id or `"system"` |
| `violation_reachable` | `"true"` / `"false"` / `"unknown"` | does *some* parameter assignment in the declared box violate the safety predicate? |
| `satisfaction_reachable` | same | does *some* assignment satisfy it? |
| `structural_status` | `sound` / `fragile` / `broken` / `not_applicable` / `inconclusive` | derived from the two reachability bits |
| `minimum_param_shift` | `{parameter: threshold}` or `null` | one numeric threshold the design must clear |
| `witness` | `{param: value}` or `null` | concrete parameter values demonstrating a violation |
| `safety_predicates` | `list[SafetyPredicate]` | structured per-period checks the ABM should evaluate |

Each `SafetyPredicate` is:

| Field | Type | Meaning |
|---|---|---|
| `variable` | string | name of a per-period state quantity the ABM must compute |
| `operator` | `>=` / `<=` / `>` / `<` / `==` | safety relation (not violation) |
| `threshold` | float | numeric boundary |
| `formula` | string | how to compute `variable` from state (human-readable) |
| `inputs` | `list[string]` | state-variable names the formula reads |
| `paper_section` | string | citation in the DLT2026 paper |
| `failure_mode` | string | back-reference to the parent FM |

## Mapping to cadCAD

A natural cadCAD config maps each `SafetyPredicate` to one
**state-update function** that writes a boolean (or counter) into
state, and one **monitor policy** that aggregates the boolean over the
trajectory.

### Minimum-viable cadCAD wiring

```python
# 1. Load the verifier's minimal output.
import json, subprocess
result = subprocess.run(
    ["te-verify", "spec.yaml", "--minimal", "--json"],
    capture_output=True, text=True, check=True,
)
verdicts = json.loads(result.stdout)

# 2. Build a check function per safety predicate.
def make_checker(predicate):
    var = predicate["variable"]
    op  = predicate["operator"]
    thr = predicate["threshold"]
    def check(state):
        v = state[var]
        return {
            ">=": v >= thr, "<=": v <= thr,
            ">":  v >  thr, "<":  v <  thr,
            "==": v == thr,
        }[op]
    return check

# 3. Each FM becomes a PSUB writing a boolean to state.
def policy_fmN_monitor(_params, _substep, _history, state):
    return {
        f"{fm}_safe": all(checkers[fm](state) for fm in checkers_per_fm)
    }

# 4. Aggregate over runs; report P(violation) per FM.
```

The full cadCAD configuration is out of scope here — the verifier
guarantees the predicates are well-defined and the thresholds are
correct under the formal layer; the ABM author plugs them into their
PSUB structure.

### Where the verifier focuses ABM work

The `structural_status` field is the primary triage signal for ABM:

* `SOUND` — skip. The formal layer proved the FM cannot fail. No
  ABM needed.
* `FRAGILE` — **simulate**. Some parameter corners pass, others
  fail; likelihood is the question. Run Monte Carlo with the
  verifier's `witness` as one seed and the threshold as the safety
  boundary.
* `BROKEN` — **stop**. No parameter assignment in the declared box
  satisfies the FM. The structural fix needs to land before
  simulation is meaningful — the user has to redesign, not retune.
* `NOT_APPLICABLE` — skip. The FM doesn't apply to this subject.
* `INCONCLUSIVE` — re-run the verifier with tighter parameter
  ranges, or simulate with the heuristic understanding that the
  formal layer didn't decide. ABM authors should annotate output
  with this caveat.

This is the headline value of the contract: the ABM doesn't have to
re-discover which FMs are worth simulating; the verifier already
told it.

## Per-FM predicate catalog

For reference, the safety predicates each FM emits. Subject is
"token id" for per-token FMs (FM1, FM2, FM3) and "system" for the
system-level ones (FM4, FM5, FM6).

### FM1 — Token oversupply
* `net_emission_per_period[<token>] <= expected_Q.min` — Fisher
  with V = 1.
* Inputs: emission rules, burn rules, cross-token flows, expected_Q.

### FM2 — Velocity trap
* `tau_bar[<token>] > 1.5` (configurable ceiling) — wealth-weighted
  holding time.
* Inputs: agent_types[*].balance_share, agent_types[*].fraction,
  agent_types[*].expected_holding_time.

### FM3 — Burn coverage
* `rho[<token>] >= 1.0 * nfr1_multiplier` — burn / emission ratio.
* Inputs: B_per_period, E_per_period.

### FM4 — Free-rider
Two predicates (both must hold):
* `phi_times_K >= d * nfr5_multiplier` — Ostrom proportionality.
* `gamma_times_S > T_minus_R` — monitoring/sanction.
* Inputs: phi (contributor fraction), offer_variety_K,
  monitoring_capacity_gamma, sanction_structure.S_normalized.

### FM5 — Critical mass
* `N >= 2 · K · d + 1` (well-mixed).
* Plus, for NETWORK topology: `average_degree >= 2 · K · d`.
* Inputs: count_N, offer_variety_K, average_demand_d, topology.

### FM6 — Governance capture
Two predicates (both must hold):
* `Gamma <= 0.5` — fraction of decisions controlled unilaterally.
* `effective_gini <= 0.6` — voting-concentration Gini under the
  declared vote_weighting.
* Inputs: rule_structure, token_balance_gini, vote_weighting,
  vote_weighting_params.

## When the verifier says BROKEN

The `BROKEN` status means: **for every parameter assignment in the
declared box, the safety predicate is violated**. This is a
structural claim about the design space, not a probabilistic one.

When the ABM gets a `BROKEN` verdict, it should refuse to simulate
without first asking the user to either:

1. Widen a parameter range (the user's box was too narrow), or
2. Change the structural design (add a burn mechanism, declare a
   vote_weighting, etc.).

ABM-derived likelihoods on BROKEN designs are meaningless — the
verifier proved every corner fails, so any sampling distribution
over the box reports P(violation) ≈ 1.

## When the verifier says FRAGILE

`FRAGILE` is the productive case for ABM:

* `violation_reachable = true` — there exist parameter
  combinations where the design fails.
* `satisfaction_reachable = true` — there exist parameter
  combinations where it passes.

The verifier has shown the cliffs are real; the ABM tells the user
the path. Likelihood-of-violation, time-to-first-violation, and
which agent dynamics push the trajectory toward failure are all ABM
questions, not verifier questions.

The verifier's `witness` field gives one concrete fail point; the
ABM should sample around it.

## Stability of the contract

* The `structural_status` enum values are pinned for back-compat.
  Future verifier versions may add new values (e.g. `PROVABLY_SOUND`
  as a stricter form of SOUND), but won't rename the existing ones.
* `SafetyPredicate.variable` names are conventional, not formally
  parsed. Future verifier versions may add `_canonical_id` for
  stricter machine-matching.
* `inputs` is a name list, not a path expression. ABM authors map
  these to their state structure manually; the verifier doesn't
  prescribe state-variable naming.

## Limitations (Phase B → C → ABM)

* Multi-knob analysis is not in the minimal output beyond what
  Z3-dual provides per FM. If `satisfaction_reachable = true` but
  no single parameter shift fixes a FAIL, the verifier may not
  identify the multi-knob fix. The ABM picks this up via stochastic
  exploration.
* External signals (oracle prices, exchange rates with stochastic
  underlying) are not first-class in the current schema. Their
  influence on FM-violation likelihood lives entirely in the ABM.
* Per-agent state is not in the verifier. FM2's `tau_bar` is an
  aggregate; the ABM can compute it from individual holding
  durations.

Each gap is a deliberate boundary. The verifier doesn't try to do
ABM's job; the ABM doesn't try to do the verifier's.
