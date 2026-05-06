# API contract — Report JSON shape

This is the contract a webapp (or any other client) consumes. It
describes the JSON structure produced by `te-verify <yaml> --json`
and by the Python API `verifier.verify(te).model_dump()`.

The JSON is the source of truth: every field the UI displays, every
piece of "why we ask" explanatory copy, every recommendation, every
critical value, and every coherence issue is here.

## Top-level shape

```jsonc
{
  "te_name": "Axie Infinity",
  "verdicts": [ ... per-FM verdicts (see below) ... ],
  "severity": "fail",                // "ok" | "warn" | "fail"
  "summary": {                       // counts by status
    "pass": 2,
    "fail": 5,
    "pass_as_intended": 2,
    "not_applicable": 0,
    "inconclusive": 0
  },
  "coherence_issues": [              // cross-field IR consistency warnings
    {
      "severity": "error" | "warn",
      "location": "tokens[T].burn_rules + .redemption_mechanism",
      "message": "...",
      "suggestion": "..."
    }
  ],
  "overall_risk": {                  // Phase D — Simulator.pdf §6
    "weighted": 12.5,                // raw weighted score
    "normalized_pct": 37.9,          // weighted / Smax * 100
    "band": "moderate",              // low | moderate | high | critical
    "message": "Several conditions require attention before deployment.",
    "per_fm_max": {                  // worst risk band per FM (across tokens)
      "FM1": "amber",
      "FM3": "red_critical",
      "FM6": "green"
    },
    "contradiction_penalty": 1.0     // sum of coherence-issue penalties
  }
}
```

## `Verdict`

Every verdict contains the formal result plus all the explanatory
material a UI needs to render a per-FM card.

```jsonc
{
  "failure_mode": "FM4: Free-Rider Collapse",
  "subject": "system",                       // "system" or a token id
  "status": "fail",                          // pass | fail | pass_as_intended | inconclusive | not_applicable
  "formal_condition": "φ ≥ d/K   AND   γ·S > T − R",
  "explanation": "There exist parameter values...",
  "counterexample": { ... } | null,          // see below
  "margin": null,                            // legacy; use critical_values instead
  "suggestions": [                            // free-text design advice
    "Increase offer variety K to lower the d/K threshold.",
    "..."
  ],
  "critical_values": [ ... ],                // see below
  "recommendation": { ... } | null,          // see below — the actionable one
  "swept_fields": [                          // IR fields the verifier searched over
    "participants.average_demand_d",
    "governance.monitoring_capacity_gamma"
  ],
  "committed_fields": [                      // IR fields the user gave point values for
    "tokens[T].offer_variety_K"
  ],
  "risk_level": "amber"                      // Phase D — green | green_borderline | amber | red | red_critical | not_applicable
}
```

### `risk_level` — Simulator.pdf §4

Complementary to `status`. The SMT-derived `status` answers "does
*any* parameter assignment in the declared box violate the condition?";
`risk_level` answers "at the **midpoint** of the box, how bad is it?".
Both are useful and they are reported side-by-side. Bands per
Simulator.pdf §4 (FM1 ros, FM2 τ̄ in days, FM3 ρ, FM5 rcm, FM6 Γ).

### `Counterexample`

A concrete parameter assignment that exhibits the violation. Always
populated for fail/inconclusive verdicts; null for pass.

```jsonc
{
  "parameter_values": {                       // every Z3-model variable
    "K": 2.0,
    "d": 2.0,
    "gamma": 0.94,
    "S_normalized": 0.75,
    "phi": 0.0,
    "T_minus_R_normalized": 0.3,
    "phi_K": 0.0,
    "gamma_S": 0.7
  },
  "narrative": "Free-rider risk concrete: φ·K = 0.000 < d = 2.000 ...",
  "binding_constraint": "contribution clause (φ < d/K) is binding"
}
```

`binding_constraint` is empty when there's a single clause; for FM4
it identifies which of the two clauses (Ostrom or monitoring) failed.
The webapp uses this to highlight the right design knob.

### `CriticalValue`

The boundary value at which the FM verdict flips. Multiple per
verdict — FM4 emits γ\*, K\*, φ\*; FM6 emits Γ\*, n_demote\*; FM5
emits N\*, K\*; etc.

```jsonc
{
  "parameter": "gamma",
  "value": 0.6,
  "direction": ">=",                         // safe side
  "formula": "γ* = (T − R) / S = 0.3 / 0.5",
  "explanation": "The minimum monitoring capacity at which ...",
  "source": "closed_form"                    // "optimize" | "closed_form" | "config"
}
```

`source` records how the value was obtained — useful for the UI to
decide whether to show "computed" vs "configured" labels.

### `NumericRecommendation`

The single, actionable redesign instruction. One per failing verdict
when a numeric instruction makes sense; null when only structural
advice (`suggestions`) applies.

```jsonc
{
  "parameter": "gamma",
  "current_range": [0.1, 0.4],               // [min, max] or null
  "safe_threshold": 0.6,
  "direction": ">=",
  "narrative": "Raise monitoring capacity γ to at least 0.600. Choose ...",
  "mechanism_mappings": [                    // structured-choice options
    "physical_presence: γ ∈ [0.85, 0.95] — safe",
    "smart_contract_automation: γ ∈ [0.90, 1.00] — safe",
    "peer_verification: γ ∈ [0.50, 0.80] — partially safe",
    "third_party_certification: γ ∈ [0.40, 0.70] — partially safe",
    "self_reporting: γ ∈ [0.05, 0.20] — unsafe"
  ]
}
```

The UI renders `narrative` as the headline instruction and
`mechanism_mappings` as a comparison table. Each entry is
`"name: range — safe|partially safe|unsafe"`.

### `CoherenceIssue`

Cross-field IR validity issue. `severity = "error"` means the IR is
internally contradictory; `"warn"` means it's parseable but suspicious.

```jsonc
{
  "severity": "error" | "warn",
  "location": "tokens[T].burn_rules + .redemption_mechanism",
  "message": "Peer-to-peer transfer redemption + demand-driven burn is structurally incoherent: ...",
  "suggestion": "Either change redemption_mechanism to one that supports a redemption event ..."
}
```

The UI renders these as top-level alerts above the per-FM verdicts.

## Status semantics

| Status | Meaning |
|---|---|
| `pass` | Verifier proved the FM condition holds across all parameter values in the declared ranges. |
| `fail` | Verifier found a parameter assignment that violates the condition. |
| `pass_as_intended` | The condition technically fails but the user's NFR declaration says this is intentional (NFR6=circulate_fast, NFR7=indefinite). |
| `inconclusive` | The verifier could not decide — typically because of `unspecified` IR fields or an open question (e.g. spatially-structured topology with the well-mixed bound failing). |
| `not_applicable` | The FM does not apply to this token or system (non-transferable token for FM2, no contribution-reward economy for FM4, archetype-skip override). |

## Severity

| Severity | Trigger |
|---|---|
| `ok` | Every verdict is `pass`, `pass_as_intended`, or `not_applicable`, and no error-severity coherence issues. |
| `warn` | At least one inconclusive verdict, OR an error-severity coherence issue with no FM fail. |
| `fail` | At least one `fail` verdict. |

## Why-we-ask copy

Every elicitation question's "why we ask" / "why it matters" /
"real world signal" / "design knobs" copy is in
`verifier/paper.py`'s `PaperCondition` dataclass. The UI imports
that module (or, for non-Python clients, the JSON dump produced by
running `python -c "import json; from verifier.paper import ALL_CONDITIONS; print(json.dumps({k: v.__dict__ for k, v in ALL_CONDITIONS.items()}, default=str))"`).

The structure mirrors the `Verdict` JSON: per-FM, four explanatory
fields the UI renders verbatim around the verdict card.

## Backward compatibility

The contract preserves backwards compatibility with Phase 0 verdicts:
every existing field has the same name and semantics. The Phase 1+
additions (`critical_values`, `recommendation`, `swept_fields`,
`committed_fields`, `coherence_issues`) default to empty when not
populated, so a client that ignores them still sees a valid Phase 0
report.
