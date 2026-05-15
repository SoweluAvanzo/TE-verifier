"""Phase K5 — YAML loader integration for DSL expressions.

A YAML author can write ``expression: "<surface syntax>"`` and the
FunctionShape model parses it into an Expr AST on load. This receipt
test exercises the full path: yaml.safe_load → Pydantic validate →
expression evaluation.
"""

from __future__ import annotations

import textwrap

import yaml

from schema import TokenEconomy, VarNamespace
from schema.expr_parser import parse
from schema.te_ir import FunctionShape
from verifier.expr_eval import EvalEnv, evaluate


def test_function_shape_accepts_yaml_string_expression() -> None:
    """A YAML payload with ``expression:`` as a string parses to an AST."""
    payload = yaml.safe_load(textwrap.dedent("""
        expression: "event.amount * event.duration / param.max_lock"
        parameters:
          - name: max_lock
            range:
              min: 208
              max: 208
    """))
    fs = FunctionShape.model_validate(payload)
    assert fs.expression is not None
    # Equality with manually-parsed AST.
    expected = parse("event.amount * event.duration / param.max_lock")
    # Compare structurally — Expr is frozen Pydantic, so equality is
    # deep field-by-field.
    assert fs.expression == expected


def test_loaded_expression_evaluates() -> None:
    """End-to-end: YAML string → FunctionShape → numeric value."""
    payload = yaml.safe_load(textwrap.dedent("""
        expression: "event.amount * 2 + param.b"
        parameters:
          - name: b
            range:
              min: 5
              max: 5
    """))
    fs = FunctionShape.model_validate(payload)
    val = evaluate(
        fs.expression,
        EvalEnv(
            state={"t": 0.0},
            params={"b": 5.0},
            consts={},
            event={"amount": 7.0},
            agents=[], tokens=[], events=[], assets=[],
        ),
    )
    # 7×2 + 5 = 19
    assert val == 19.0


def test_yaml_te_with_dsl_expression_loads() -> None:
    """Minimal TokenEconomy YAML using ``expression:`` loads cleanly."""
    yaml_doc = textwrap.dedent("""
        meta:
          name: dsl-yaml
          archetype: other
          nfrs: {}
        tokens:
          - id: T
            function: [medium_of_exchange]
            emission_rules:
              - trigger:
                  kind: time_based
                function:
                  sign: always_positive
                  expression: "param.a * state.t + param.b"
                  parameters:
                    - name: a
                      range: {min: 2, max: 2}
                    - name: b
                      range: {min: 5, max: 5}
        participants:
          count_N: {min: 100, max: 100}
          expected_Q: {min: 100, max: 100}
          average_demand_d: {min: 1, max: 1}
          growth_g:
            family: constant
          topology: well_mixed
        governance:
          type: dao
    """)
    te = TokenEconomy.model_validate(yaml.safe_load(yaml_doc))
    rule = te.tokens[0].emission_rules[0]
    assert rule.function.expression is not None
    # Parsed parameters survived the round-trip.
    assert {p.name for p in rule.function.parameters} == {"a", "b"}


def test_loaded_dsl_rule_drives_z3_encoding() -> None:
    """The loaded DSL rule encodes into Z3 via the verifier hook."""
    import z3
    from verifier.asymptotic import rule_rate_per_period

    yaml_doc = textwrap.dedent("""
        meta:
          name: dsl-z3
          archetype: other
          nfrs: {}
        tokens:
          - id: T
            function: [medium_of_exchange]
            emission_rules:
              - trigger:
                  kind: time_based
                function:
                  sign: always_positive
                  expression: "param.a * 10"
                  parameters:
                    - name: a
                      range: {min: 3, max: 3}
        participants:
          count_N: {min: 100, max: 100}
          expected_Q: {min: 100, max: 100}
          average_demand_d: {min: 1, max: 1}
          growth_g:
            family: constant
          topology: well_mixed
        governance:
          type: dao
    """)
    te = TokenEconomy.model_validate(yaml.safe_load(yaml_doc))
    rule = te.tokens[0].emission_rules[0]
    solver = z3.Solver()
    rate = rule_rate_per_period(
        solver, "T_emit_0", rule, periods_horizon=52.0, te=te,
    )
    solver.add(rate == 30.0)
    assert solver.check() == z3.sat
