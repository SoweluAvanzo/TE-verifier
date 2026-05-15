"""Phase K4 — Z3 encoder.

Confirms the encoder builds Z3 expressions that match the numeric
evaluator's output and that the FM-style reachability check fires
correctly when the user constrains the parameter box."""

from __future__ import annotations

import math

import pytest
import z3

from schema import NumberRange
from schema.expr_parser import parse
from verifier.expr_eval import (
    EvalEnv,
    Z3EncodingError,
    Z3Env,
    bind_param,
    encode_z3,
    evaluate,
)


def _state_vars(solver, mapping):
    out = {}
    for name, val in mapping.items():
        v = z3.Real(f"state__{name}")
        solver.add(v == val)
        out[name] = v
    return out


# ---------------------------------------------------------------------------
# Sanity: constants and arithmetic
# ---------------------------------------------------------------------------


def test_encode_constant_resolves() -> None:
    s = z3.Solver()
    e = encode_z3(parse("3.14"), Z3Env(
        solver=s, state_vars={}, param_vars={}, event_payload_vars={},
        const_values={}, agents=[], tokens=[], events=[], assets=[]))
    s.add(e == 3.14)
    assert s.check() == z3.sat


def test_encode_addition() -> None:
    s = z3.Solver()
    a = bind_param(s, "a", NumberRange(min=2.0, max=2.0))
    b = bind_param(s, "b", NumberRange(min=3.0, max=3.0))
    expr = parse("param.a + param.b")
    encoded = encode_z3(expr, Z3Env(
        solver=s, state_vars={}, param_vars={"a": a, "b": b},
        event_payload_vars={}, const_values={}, agents=[], tokens=[],
        events=[], assets=[]))
    s.add(encoded == 5.0)
    assert s.check() == z3.sat


def test_encode_multiplication_and_division() -> None:
    s = z3.Solver()
    amount = bind_param(s, "amount", NumberRange(min=100.0, max=100.0))
    duration = bind_param(s, "duration", NumberRange(min=104.0, max=104.0))
    max_lock = bind_param(s, "max_lock", NumberRange(min=208.0, max=208.0))
    expr = parse("param.amount * param.duration / param.max_lock")
    encoded = encode_z3(expr, Z3Env(
        solver=s, state_vars={},
        param_vars={"amount": amount, "duration": duration, "max_lock": max_lock},
        event_payload_vars={}, const_values={}, agents=[], tokens=[],
        events=[], assets=[]))
    s.add(encoded == 50.0)
    assert s.check() == z3.sat


def test_encode_power_integer_exponent() -> None:
    s = z3.Solver()
    t = bind_param(s, "t", NumberRange(min=3.0, max=3.0))
    expr = parse("param.t ^ 4")
    encoded = encode_z3(expr, Z3Env(
        solver=s, state_vars={}, param_vars={"t": t},
        event_payload_vars={}, const_values={}, agents=[], tokens=[],
        events=[], assets=[]))
    s.add(encoded == 81.0)
    assert s.check() == z3.sat


# ---------------------------------------------------------------------------
# Comparisons + conditional
# ---------------------------------------------------------------------------


def test_encode_if_chooses_then_branch() -> None:
    s = z3.Solver()
    rep = bind_param(s, "rep", NumberRange(min=50.0, max=50.0))
    high = bind_param(s, "high", NumberRange(min=5.0, max=5.0))
    low = bind_param(s, "low", NumberRange(min=2.0, max=2.0))
    expr = parse("if(param.rep >= 40, param.high, param.low)")
    encoded = encode_z3(expr, Z3Env(
        solver=s, state_vars={},
        param_vars={"rep": rep, "high": high, "low": low},
        event_payload_vars={}, const_values={}, agents=[], tokens=[],
        events=[], assets=[]))
    s.add(encoded == 5.0)
    assert s.check() == z3.sat


def test_encode_clamp() -> None:
    s = z3.Solver()
    x = bind_param(s, "x", NumberRange(min=20.0, max=20.0))
    expr = parse("clamp(param.x, 0, 10)")
    encoded = encode_z3(expr, Z3Env(
        solver=s, state_vars={}, param_vars={"x": x},
        event_payload_vars={}, const_values={}, agents=[], tokens=[],
        events=[], assets=[]))
    s.add(encoded == 10.0)
    assert s.check() == z3.sat


# ---------------------------------------------------------------------------
# Range reasoning — Z3 actually finds the boundary
# ---------------------------------------------------------------------------


def test_z3_finds_extreme_value_in_parameter_box() -> None:
    """linear shape: rate = a*t + b. With a in [0.1, 0.5], b in [1, 5],
    t in [0, 52]: max rate at t=52, a=0.5, b=5 → 31."""
    s = z3.Solver()
    a = bind_param(s, "a", NumberRange(min=0.1, max=0.5))
    b = bind_param(s, "b", NumberRange(min=1.0, max=5.0))
    t = bind_param(s, "t", NumberRange(min=0.0, max=52.0))
    expr = parse("param.a * param.t + param.b")
    encoded = encode_z3(expr, Z3Env(
        solver=s, state_vars={}, param_vars={"a": a, "b": b, "t": t},
        event_payload_vars={}, const_values={}, agents=[], tokens=[],
        events=[], assets=[]))
    # Ask Z3 whether the expression can reach 31. Should be SAT.
    s.add(encoded == 31.0)
    assert s.check() == z3.sat
    # Ask whether it can reach 100 (impossible — max is 31). UNSAT.
    s2 = z3.Solver()
    a2 = bind_param(s2, "a", NumberRange(min=0.1, max=0.5))
    b2 = bind_param(s2, "b", NumberRange(min=1.0, max=5.0))
    t2 = bind_param(s2, "t", NumberRange(min=0.0, max=52.0))
    enc2 = encode_z3(expr, Z3Env(
        solver=s2, state_vars={}, param_vars={"a": a2, "b": b2, "t": t2},
        event_payload_vars={}, const_values={}, agents=[], tokens=[],
        events=[], assets=[]))
    s2.add(enc2 == 100.0)
    assert s2.check() == z3.unsat


# ---------------------------------------------------------------------------
# Non-decidable rejection
# ---------------------------------------------------------------------------


def test_encode_log_of_variable_raises() -> None:
    s = z3.Solver()
    t = bind_param(s, "t", NumberRange(min=1.0, max=52.0))
    with pytest.raises(Z3EncodingError):
        encode_z3(parse("log(param.t)"), Z3Env(
            solver=s, state_vars={}, param_vars={"t": t},
            event_payload_vars={}, const_values={}, agents=[], tokens=[],
            events=[], assets=[]))


def test_encode_log_of_constant_succeeds() -> None:
    s = z3.Solver()
    enc = encode_z3(parse("log(2.0)"), Z3Env(
        solver=s, state_vars={}, param_vars={}, event_payload_vars={},
        const_values={}, agents=[], tokens=[], events=[], assets=[]))
    s.add(enc == math.log(2.0))
    assert s.check() == z3.sat


def test_encode_agent_ref_raises() -> None:
    """Z3 layer rejects agent.* — verifier reasons aggregately."""
    s = z3.Solver()
    with pytest.raises(Z3EncodingError):
        encode_z3(parse("agent.balance"), Z3Env(
            solver=s, state_vars={}, param_vars={},
            event_payload_vars={}, const_values={},
            agents=[], tokens=[], events=[], assets=[]))


# ---------------------------------------------------------------------------
# Numeric vs Z3 agreement on the decidable subset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source,values,expected", [
    ("param.a + param.b", {"a": 7.0, "b": 5.0}, 12.0),
    ("param.a * param.b - 3", {"a": 4.0, "b": 6.0}, 21.0),
    ("(param.a + param.b) * 2", {"a": 1.5, "b": 2.5}, 8.0),
    ("if(param.a > param.b, 1, -1)", {"a": 9.0, "b": 3.0}, 1.0),
    ("clamp(param.a, 0, 10)", {"a": 25.0}, 10.0),
    ("max(param.a, param.b)", {"a": 7.0, "b": 9.0}, 9.0),
    ("min(param.a, param.b)", {"a": 7.0, "b": 9.0}, 7.0),
    ("abs(param.a - param.b)", {"a": 3.0, "b": 10.0}, 7.0),
    ("param.a ^ 3", {"a": 4.0}, 64.0),
])
def test_numeric_and_z3_agree(source, values, expected) -> None:
    """For every decidable expression, the numeric and Z3 evaluators
    must agree (Z3 returns sat when the model equals the expected
    value)."""
    # Numeric
    env = EvalEnv(state={}, params=values, consts={}, agents=[], tokens=[],
                  events=[], assets=[])
    assert evaluate(parse(source), env) == pytest.approx(expected)
    # Z3
    s = z3.Solver()
    param_vars = {
        k: bind_param(s, k, NumberRange(min=v, max=v))
        for k, v in values.items()
    }
    enc = encode_z3(parse(source), Z3Env(
        solver=s, state_vars={}, param_vars=param_vars,
        event_payload_vars={}, const_values={},
        agents=[], tokens=[], events=[], assets=[]))
    s.add(enc == expected)
    assert s.check() == z3.sat


# ---------------------------------------------------------------------------
# Aggregator encoding
# ---------------------------------------------------------------------------


def test_z3_sum_over_agents_unrolled() -> None:
    """Aggregator over a 3-agent collection: encoded as a 3-term sum."""
    s = z3.Solver()
    agents = [{"balance": 10.0, "type": "x"},
              {"balance": 20.0, "type": "x"},
              {"balance": 30.0, "type": "x"}]
    expr = parse("sum_over(agents, agent.balance * 0.5)")
    enc = encode_z3(expr, Z3Env(
        solver=s, state_vars={}, param_vars={},
        event_payload_vars={}, const_values={},
        agents=agents, tokens=[], events=[], assets=[]))
    s.add(enc == 30.0)
    assert s.check() == z3.sat
