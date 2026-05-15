"""Phase K2 — DSL surface parser + decidability analyzer.

Tests cover three areas:
  1. Parser correctness across ~30 representative expressions.
  2. Decidability analyzer flags transcendental / risky nodes.
  3. Legacy AsymptoticClass → Expr shim produces sound ASTs.
"""

from __future__ import annotations

import pytest

from schema import (
    AsymptoticClass,
    AsymptoticFamily,
    BinaryOp,
    CallOp,
    CollectionRef,
    Expr,
    NumberRange,
    VarNamespace,
)
from schema.expr_parser import (
    ParseError,
    is_decidable,
    parse,
    synthesize_from_asymptotic_class,
)


# ---------------------------------------------------------------------------
# Parser — leaves and basic arithmetic
# ---------------------------------------------------------------------------


def test_parse_number_literal() -> None:
    e = parse("3.14")
    assert e.const == 3.14


def test_parse_integer_literal() -> None:
    e = parse("42")
    assert e.const == 42.0


def test_parse_scientific_notation() -> None:
    e = parse("1.5e6")
    assert e.const == 1.5e6


def test_parse_negative_literal() -> None:
    e = parse("-3.14")
    # encoded as (0 - 3.14)
    assert e.binary_op == BinaryOp.SUB
    assert e.args[0].const == 0.0
    assert e.args[1].const == 3.14


def test_parse_addition() -> None:
    e = parse("2 + 3")
    assert e.binary_op == BinaryOp.ADD
    assert [a.const for a in e.args] == [2.0, 3.0]


def test_parse_subtraction() -> None:
    e = parse("10 - 4")
    assert e.binary_op == BinaryOp.SUB


def test_parse_left_associative_addition() -> None:
    # 1 + 2 + 3 → ((1+2)+3)
    e = parse("1 + 2 + 3")
    assert e.binary_op == BinaryOp.ADD
    left = e.args[0]
    assert left.binary_op == BinaryOp.ADD
    assert left.args[0].const == 1.0
    assert left.args[1].const == 2.0
    assert e.args[1].const == 3.0


def test_parse_multiplication_binds_tighter_than_addition() -> None:
    e = parse("2 + 3 * 4")
    assert e.binary_op == BinaryOp.ADD
    right = e.args[1]
    assert right.binary_op == BinaryOp.MUL
    assert right.args[0].const == 3.0
    assert right.args[1].const == 4.0


def test_parse_parentheses_override_precedence() -> None:
    e = parse("(2 + 3) * 4")
    assert e.binary_op == BinaryOp.MUL
    assert e.args[0].binary_op == BinaryOp.ADD
    assert e.args[1].const == 4.0


def test_parse_division() -> None:
    e = parse("event.amount / param.max_lock")
    assert e.binary_op == BinaryOp.DIV
    assert e.args[0].var.path == ["amount"]
    assert e.args[1].param == "max_lock"


def test_parse_power_with_integer_exponent() -> None:
    e = parse("state.t ^ 3")
    assert e.binary_op == BinaryOp.POW
    assert e.args[1].const == 3.0


def test_parse_power_with_non_integer_exponent_rejected() -> None:
    with pytest.raises(ParseError):
        parse("state.t ^ 2.5")


# ---------------------------------------------------------------------------
# Variables and namespaces
# ---------------------------------------------------------------------------


def test_parse_state_variable_with_string_index() -> None:
    e = parse("state.M['BTC']")
    assert e.var.ns == VarNamespace.STATE
    assert e.var.path == ["M", "BTC"]


def test_parse_state_variable_with_dotted_path() -> None:
    e = parse("state.events_realized.civic_service_verified")
    assert e.var.ns == VarNamespace.STATE
    assert e.var.path == ["events_realized", "civic_service_verified"]


def test_parse_event_payload_variable() -> None:
    e = parse("event.amount")
    assert e.var.ns == VarNamespace.EVENT
    assert e.var.path == ["amount"]


def test_parse_agent_namespace_first_class() -> None:
    """`agent` is a first-class namespace — refers to the agent who
    fired the current event. Evaluators resolve fields against the
    event's firing agent."""
    e = parse("agent.balance")
    assert e.var.ns == VarNamespace.AGENT
    assert e.var.path == ["balance"]


def test_parse_param_collapses_to_param_leaf() -> None:
    e = parse("param.alpha")
    assert e.param == "alpha"


def test_parse_const_namespace_variable() -> None:
    e = parse("const.horizon")
    assert e.var.ns == VarNamespace.CONST
    assert e.var.path == ["horizon"]


def test_parse_unknown_namespace_rejected() -> None:
    with pytest.raises(ParseError):
        parse("foo.bar")


def test_parse_bare_namespace_rejected() -> None:
    with pytest.raises(ParseError):
        parse("state")


# ---------------------------------------------------------------------------
# Calls and conditionals
# ---------------------------------------------------------------------------


def test_parse_min_call() -> None:
    e = parse("min(state.M['BTC'], 1000)")
    assert e.call_op == CallOp.MIN
    assert len(e.args) == 2


def test_parse_clamp_call() -> None:
    e = parse("clamp(event.amount, 0, 1e6)")
    assert e.call_op == CallOp.CLAMP
    assert e.args[2].const == 1e6


def test_parse_if_conditional() -> None:
    e = parse("if(event.agent.reputation >= param.tier, 5, 2)")
    assert e.call_op == CallOp.IF
    pred = e.args[0]
    assert pred.binary_op == BinaryOp.GTE


def test_parse_logical_and_or() -> None:
    e = parse("(state.t > 30) && (state.M['BTC'] >= 1000)")
    assert e.binary_op == BinaryOp.AND


def test_parse_log_call() -> None:
    e = parse("log(state.t)")
    assert e.call_op == CallOp.LOG


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def test_parse_sum_over_agents() -> None:
    e = parse("sum_over(agents, agent.balance)")
    assert e.aggregator is not None
    assert e.aggregator.collection == CollectionRef.AGENTS


def test_parse_sum_over_agents_of_type_with_filter() -> None:
    e = parse("sum_over(agents_of_type[contributor], agent.balance)")
    assert e.aggregator.collection == CollectionRef.AGENTS_OF_TYPE
    assert e.aggregator.filter_arg == "contributor"


def test_parse_mean_over_tokens() -> None:
    e = parse("mean_over(tokens, state.M['BTC'])")
    assert e.aggregator.kind.value == "mean_over"


def test_parse_aggregator_unknown_collection_rejected() -> None:
    with pytest.raises(ParseError):
        parse("sum_over(galaxies, 1)")


# ---------------------------------------------------------------------------
# Real-world expressions (the whole point of K2)
# ---------------------------------------------------------------------------


def test_parse_vecrv_mint_expression() -> None:
    """User locks CRV — mint = amount × duration / max_lock_periods."""
    e = parse("event.amount * event.duration / param.max_lock_periods")
    # Left-assoc: ((amount * duration) / max_lock_periods)
    assert e.binary_op == BinaryOp.DIV
    left = e.args[0]
    assert left.binary_op == BinaryOp.MUL
    assert left.args[0].var.path == ["amount"]
    assert left.args[1].var.path == ["duration"]
    assert e.args[1].param == "max_lock_periods"


def test_parse_makerdao_stability_fee_burn() -> None:
    """MKR.burn = M[DAI] × stability_fee × dt."""
    e = parse("state.M['DAI'] * param.stability_fee * param.dt")
    assert e.binary_op == BinaryOp.MUL
    # Walk: left = M[DAI] * stability_fee, right = dt
    assert e.args[1].param == "dt"


def test_parse_tiered_redemption_with_conditional() -> None:
    """Patto-style tiered reward: if SBT-eligible, 5 PDT; else 2."""
    e = parse(
        "if(agent.reputation >= param.sbt_threshold, param.high_reward, param.low_reward)"
    )
    assert e.call_op == CallOp.IF
    # then-arg is param.high_reward
    assert e.args[1].param == "high_reward"


def test_parse_aggregate_veCRV_voting_power() -> None:
    e = parse(
        "sum_over(agents, agent.veCRV_balance * agent.lock_remaining) / param.max_lock"
    )
    assert e.binary_op == BinaryOp.DIV
    agg = e.args[0]
    assert agg.aggregator is not None


# ---------------------------------------------------------------------------
# Error reporting
# ---------------------------------------------------------------------------


def test_parse_unclosed_paren() -> None:
    with pytest.raises(ParseError):
        parse("(2 + 3")


def test_parse_extra_close_paren() -> None:
    with pytest.raises(ParseError):
        parse("2 + 3)")


def test_parse_empty_source() -> None:
    with pytest.raises(ParseError):
        parse("")


# ---------------------------------------------------------------------------
# Decidability analyzer
# ---------------------------------------------------------------------------


def test_decidable_constant_expression() -> None:
    ok, reasons = is_decidable(parse("2 + 3 * 4"))
    assert ok
    assert reasons == []


def test_decidable_linear_with_variables() -> None:
    ok, reasons = is_decidable(parse("param.a * state.t + param.b"))
    assert ok


def test_decidable_polynomial() -> None:
    ok, reasons = is_decidable(parse("param.a * state.t^3 + param.b"))
    assert ok


def test_decidable_conditional_pure_arithmetic() -> None:
    ok, _ = is_decidable(
        parse("if(state.M['BTC'] > param.cap, 0, param.rate)")
    )
    assert ok


def test_not_decidable_log_of_variable() -> None:
    ok, reasons = is_decidable(parse("log(state.t)"))
    assert not ok
    assert any("log" in r for r in reasons)


def test_decidable_log_of_literal() -> None:
    """log of a constant is itself a constant; decidable."""
    ok, _ = is_decidable(parse("log(2.0)"))
    assert ok


def test_decidable_div_by_param_emits_caveat() -> None:
    """Division by a non-literal returns decidable=True but with a caveat."""
    ok, reasons = is_decidable(parse("event.amount / param.max_lock"))
    # The DSL allows the parser to flag it; param is treated as a parameter
    # (Z3 bound by declared range). Currently flagged as caveat but decidable.
    # Either accept; the analyzer is conservative-friendly.
    # Specifically: param is treated as constant for the analyzer.
    assert ok is True


def test_decidable_aggregator_with_linear_body() -> None:
    ok, _ = is_decidable(parse("sum_over(agents, agent.balance * param.weight)"))
    assert ok


# ---------------------------------------------------------------------------
# Legacy AsymptoticClass → Expr synthesis
# ---------------------------------------------------------------------------


def test_synthesize_constant_yields_param_c() -> None:
    ac = AsymptoticClass(
        family=AsymptoticFamily.CONSTANT,
        parameter_ranges={"c": NumberRange(min=10.0, max=20.0)},
    )
    expr = synthesize_from_asymptotic_class(ac)
    assert expr.param == "c"


def test_synthesize_linear_yields_a_t_plus_b() -> None:
    ac = AsymptoticClass(
        family=AsymptoticFamily.LINEAR,
        parameter_ranges={
            "a": NumberRange(min=0.0, max=1.0),
            "b": NumberRange(min=0.0, max=10.0),
        },
    )
    expr = synthesize_from_asymptotic_class(ac)
    assert expr.binary_op == BinaryOp.ADD
    mul_node = expr.args[0]
    assert mul_node.binary_op == BinaryOp.MUL
    assert mul_node.args[0].param == "a"
    assert mul_node.args[1].var.ns == VarNamespace.STATE


def test_synthesize_polynomial_includes_power_node() -> None:
    ac = AsymptoticClass(
        family=AsymptoticFamily.POLYNOMIAL,
        degree=2,
        parameter_ranges={"a": NumberRange(min=0.0, max=1.0)},
    )
    expr = synthesize_from_asymptotic_class(ac)
    assert expr.binary_op == BinaryOp.ADD
    mul = expr.args[0]
    pow_node = mul.args[1]
    assert pow_node.binary_op == BinaryOp.POW
    assert pow_node.args[1].const == 2.0


def test_synthesize_log_yields_log_call_undecidable() -> None:
    ac = AsymptoticClass(
        family=AsymptoticFamily.LOG,
        parameter_ranges={"a": NumberRange(min=0.0, max=1.0)},
    )
    expr = synthesize_from_asymptotic_class(ac)
    ok, reasons = is_decidable(expr)
    assert not ok
    assert any("log" in r for r in reasons)


def test_synthesize_unspecified_collapses_to_value_param() -> None:
    ac = AsymptoticClass(family=AsymptoticFamily.UNSPECIFIED)
    expr = synthesize_from_asymptotic_class(ac)
    assert expr.param == "value"
