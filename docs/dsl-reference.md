# Phase K DSL Reference

The Phase-K **state-dependent expression DSL** extends `FunctionShape`
beyond the legacy time-only `AsymptoticClass` primitive. Where AC could
only describe `rate = f(t)`, the DSL writes
`rate = f(state, event payload, agent attributes, params)`. This is
what unlocks per-lock veCRV mint, MakerDAO CDR-driven mint, tiered
redemption, and similar state-of-the-economy formulas that the legacy
form had to flatten into aggregate ranges.

The DSL is **fully integrated** into all three verification layers:

| Layer | Backend | Notes |
|-------|---------|-------|
| Static verifier (FM1, FM3) | Z3 NRA | Decidable subset: arithmetic, comparisons, `if`, `min`, `max`, `abs`, `clamp`, `^` with integer exponent, aggregators over the agent collection. `log(x)` and `exp(x)` are decidable only when the argument is a literal. |
| Monte Carlo | Python evaluator | Full DSL — no decidability restriction. |
| ABM | Python evaluator | Full DSL — event payload sampled per period from the catalog. |

## Authoring a DSL rule

Inside any YAML rule, replace `asymptotic_class:` with `expression:` and
declare `parameters:` for every `param.*` reference:

```yaml
emission_rules:
  - trigger:
      event_id: user_locks_crv     # references the events: catalog below
    function:
      sign: always_positive
      expression: "event.amount * event.duration / param.max_lock_periods"
      parameters:
        - name: max_lock_periods
          range: { min: 208, max: 208 }
events:
  - id: user_locks_crv
    label: User locks CRV to mint veCRV
    kind: behavioral
    frequency:
      family: linear
      parameter_ranges:
        a: { min: 0, max: 5 }
        b: { min: 100, max: 500 }
    payload:
      - name: amount
        type: scalar
        range: { min: 100, max: 100000 }
      - name: duration
        type: scalar
        range: { min: 4, max: 208 }
```

The loader parses the surface syntax inside `expression:` automatically.
Per-period rate = `expression(event payload, state, params) × event.frequency`.

## Namespaces

| Namespace | What it resolves to | Static verifier? |
|-----------|--------------------|------------------|
| `param.NAME` | A rule-local `ParamDecl` constrained by its declared range | Yes — bound as a Z3 real |
| `event.FIELD` | Scalar field declared in the event's `payload:` | Yes — bound when `rule.trigger.event_id` resolves to an EventDefinition |
| `state.PATH` | Live state slot (e.g. `state.M['BTC']`, `state.events_realized.user_locks_crv`) | Only `state.t` is bound to the verification horizon midpoint; other state slots become free variables |
| `agent.FIELD` | Field on the agent currently being evaluated inside an aggregator | Encoded by unrolling aggregator over the declared agent set; raises outside an aggregator |
| `asset.NAME.FIELD` | Per-period state of a non-tokenized asset | MC/ABM only |
| `const.NAME` | Verifier-supplied constants — currently `const.horizon` | Yes |

## Operators

| Form | Meaning |
|------|---------|
| `a + b`, `a - b`, `a * b`, `a / b` | Standard arithmetic. Division by zero returns NaN in the numeric evaluator. |
| `a ^ k` | Power. Z3 accepts only integer exponents. |
| `-a` | Negation. |
| `a > b`, `a >= b`, `a < b`, `a <= b`, `a == b`, `a != b` | Comparisons. Return 1.0 / 0.0 in the numeric evaluator. |
| `a && b`, `a \|\| b` | Logical AND / OR. |
| `if(cond, then, else)` | Conditional. |
| `min(a, b)`, `max(a, b)`, `abs(a)`, `clamp(x, lo, hi)` | Built-ins. |
| `log(x)`, `exp(x)` | Static verifier requires literal argument; otherwise fall to inconclusive. |

## Aggregators

Run an inner expression over a collection and reduce:

```text
sum_over(agents, agent.balance * agent.lock_remaining)
mean_over(agents_of_type[locker], agent.veCRV_balance)
count_of(agents, agent.reputation > 40)
fraction_of(agents, agent.reputation > 40)
```

Collections: `agents`, `agents_of_type[<type_id>]`, `tokens`, `events`,
`assets`. The static verifier unrolls aggregators over the
*declared* agent set at verification time — large populations stay
tractable because Z3 sees a sum-of-N terms, not a quantifier.

## Decidability

Use `schema.expr_parser.is_decidable(ast)` to introspect. Non-decidable
expressions are still fully supported by MC + ABM; the static verifier
emits an Inconclusive verdict and surfaces a free-variable
counterexample placeholder rather than blocking.

## Migrating from AsymptoticClass

The legacy compact AC forms remain valid; the loader keeps both paths
alive. Migrate only when the per-event physics actually depends on
state / payload / agent attributes:

| Legacy AC | DSL equivalent |
|-----------|-----------------|
| `constant { c: [c0, c1] }` | `expression: "param.c"` with `param.c.range=[c0,c1]` |
| `linear { a: [a0,a1], b: [b0,b1] }` | `expression: "param.a * state.t + param.b"` |
| `polynomial degree k { a, b }` | `expression: "param.a * state.t ^ k + param.b"` |

The `verifier.expr_parser.synthesize_from_asymptotic_class` helper
returns the corresponding AST programmatically — used by the loader
when a YAML keeps the legacy `asymptotic_class:` form.

## Receipts

Phase K1–K8 ships 16 dedicated integration tests on top of the 750+
pre-existing ones:

- `tests/test_expr_schema.py` (19) — AST + Pydantic validators
- `tests/test_expr_parser.py` (49) — surface parser + decidability
- `tests/test_expr_eval.py` (38) — numeric evaluator (ABM / MC)
- `tests/test_expr_z3.py` (20) — Z3 encoder
- `tests/test_expr_engine_integration.py` (6) — ABM wiring
- `tests/test_expr_yaml_loader.py` (4) — YAML string-form parsing
- `tests/test_expr_vecrv_migration.py` (6) — veCRV legacy ↔ DSL parity

Run `pytest tests/test_expr_*.py -v` to validate the DSL stack in
isolation.
