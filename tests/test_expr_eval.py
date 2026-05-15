"""Phase K3 — numeric evaluator (ABM + MC).

Covers leaves, all binary ops, all call ops, aggregators, var resolution
across every namespace, and a few real-world expressions (veCRV mint,
tiered redemption, MakerDAO stability-fee burn, Curve voting power)."""

from __future__ import annotations

import math

import pytest

from schema import (
    AggregatorKind,
    AggregatorSpec,
    BinaryOp,
    CallOp,
    CollectionRef,
    Expr,
    VarNamespace,
    VarRef,
)
from schema.expr_parser import parse
from verifier.expr_eval import EvalEnv, EvalError, evaluate


def _env(**kwargs) -> EvalEnv:
    """Build an EvalEnv with a minimal state stub by default."""
    defaults = dict(
        state={"M": {"BTC": 19850000.0, "DAI": 5000000.0},
               "Q": 2.5e6, "N": 1.5e8, "t": 52.0,
               "events_realized": {"user_locks_crv": 100.0},
               "assets": {"local_goods": {"count": 50.0}}},
        params={},
        consts={"horizon": 260.0, "max_lock": 208.0},
        agents=[],
        tokens=["BTC", "DAI"],
        events=["user_locks_crv"],
        assets=["local_goods"],
    )
    defaults.update(kwargs)
    return EvalEnv(**defaults)


# ---------------------------------------------------------------------------
# Leaves
# ---------------------------------------------------------------------------


def test_const_leaf() -> None:
    assert evaluate(parse("3.14"), _env()) == pytest.approx(3.14)


def test_param_leaf() -> None:
    assert evaluate(parse("param.alpha"), _env(params={"alpha": 7.5})) == 7.5


def test_state_var_resolution() -> None:
    assert evaluate(parse("state.M['BTC']"), _env()) == 19850000.0


def test_state_nested_path() -> None:
    assert evaluate(parse("state.events_realized.user_locks_crv"), _env()) == 100.0


def test_event_var_requires_event_in_env() -> None:
    with pytest.raises(EvalError):
        evaluate(parse("event.amount"), _env())
    e = _env(event={"amount": 42.0})
    assert evaluate(parse("event.amount"), e) == 42.0


def test_agent_var_requires_agent_in_env() -> None:
    with pytest.raises(EvalError):
        evaluate(parse("agent.balance"), _env())
    e = _env(agent={"balance": 12.5})
    assert evaluate(parse("agent.balance"), e) == 12.5


def test_const_namespace() -> None:
    assert evaluate(parse("const.horizon"), _env()) == 260.0


def test_asset_lookup() -> None:
    assert evaluate(parse("asset.local_goods.count"), _env()) == 50.0


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------


def test_addition() -> None:
    assert evaluate(parse("2 + 3"), _env()) == 5.0


def test_precedence_mul_over_add() -> None:
    assert evaluate(parse("2 + 3 * 4"), _env()) == 14.0


def test_division_normal() -> None:
    assert evaluate(parse("10 / 4"), _env()) == 2.5


def test_division_by_zero_returns_nan() -> None:
    result = evaluate(parse("1 / 0"), _env())
    assert math.isnan(result)


def test_negation() -> None:
    assert evaluate(parse("-5"), _env()) == -5.0


def test_power_integer_exponent() -> None:
    assert evaluate(parse("state.t ^ 2"), _env()) == 52.0 ** 2


# ---------------------------------------------------------------------------
# Comparisons + logical
# ---------------------------------------------------------------------------


def test_comparison_truth_returns_one() -> None:
    assert evaluate(parse("state.t > 10"), _env()) == 1.0
    assert evaluate(parse("state.t < 10"), _env()) == 0.0


def test_logical_and() -> None:
    assert evaluate(parse("(state.t > 10) && (state.t < 100)"), _env()) == 1.0
    assert evaluate(parse("(state.t > 100) && (state.t < 10)"), _env()) == 0.0


def test_logical_or() -> None:
    assert evaluate(parse("(state.t > 100) || (state.t > 10)"), _env()) == 1.0


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


def test_min_max() -> None:
    assert evaluate(parse("min(7, 3)"), _env()) == 3.0
    assert evaluate(parse("max(7, 3)"), _env()) == 7.0


def test_abs() -> None:
    assert evaluate(parse("abs(-9.5)"), _env()) == 9.5


def test_clamp_within_bounds() -> None:
    assert evaluate(parse("clamp(5, 0, 10)"), _env()) == 5.0


def test_clamp_above_max() -> None:
    assert evaluate(parse("clamp(20, 0, 10)"), _env()) == 10.0


def test_clamp_below_min() -> None:
    assert evaluate(parse("clamp(-5, 0, 10)"), _env()) == 0.0


def test_if_true_branch() -> None:
    assert evaluate(parse("if(state.t > 10, 100, 200)"), _env()) == 100.0


def test_if_false_branch() -> None:
    assert evaluate(parse("if(state.t > 100, 100, 200)"), _env()) == 200.0


def test_log_call() -> None:
    assert evaluate(parse("log(state.t)"), _env()) == pytest.approx(math.log(52.0))


def test_exp_call() -> None:
    assert evaluate(parse("exp(2)"), _env()) == pytest.approx(math.exp(2.0))


# ---------------------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------------------


def test_sum_over_agents() -> None:
    agents = [{"balance": 10.0, "type": "a"},
              {"balance": 20.0, "type": "a"},
              {"balance": 30.0, "type": "b"}]
    e = _env(agents=agents)
    assert evaluate(parse("sum_over(agents, agent.balance)"), e) == 60.0


def test_sum_over_agents_of_type_filter() -> None:
    agents = [{"balance": 10.0, "type": "contributor"},
              {"balance": 20.0, "type": "contributor"},
              {"balance": 30.0, "type": "observer"}]
    e = _env(agents=agents)
    expr = "sum_over(agents_of_type[contributor], agent.balance)"
    assert evaluate(parse(expr), e) == 30.0


def test_mean_over_agents() -> None:
    agents = [{"balance": 10.0, "type": "x"}, {"balance": 20.0, "type": "x"}]
    e = _env(agents=agents)
    assert evaluate(parse("mean_over(agents, agent.balance)"), e) == 15.0


def test_count_of_eligible_agents() -> None:
    agents = [{"reputation": 5.0, "type": "x"},
              {"reputation": 50.0, "type": "x"},
              {"reputation": 80.0, "type": "x"}]
    e = _env(agents=agents)
    # count of agents with reputation > 40
    assert evaluate(parse("count_of(agents, agent.reputation > 40)"), e) == 2.0


def test_fraction_of_eligible_agents() -> None:
    agents = [{"reputation": 5.0, "type": "x"},
              {"reputation": 50.0, "type": "x"},
              {"reputation": 80.0, "type": "x"},
              {"reputation": 10.0, "type": "x"}]
    e = _env(agents=agents)
    # 2/4 above threshold
    expr = "fraction_of(agents, agent.reputation > 40)"
    assert evaluate(parse(expr), e) == 0.5


# ---------------------------------------------------------------------------
# Real-world expressions
# ---------------------------------------------------------------------------


def test_vecrv_mint_with_event_payload() -> None:
    """User locks 100 CRV for 104 weeks, max_lock = 208 weeks."""
    e = _env(
        event={"amount": 100.0, "duration": 104.0},
        params={"max_lock_periods": 208.0},
    )
    expr = "event.amount * event.duration / param.max_lock_periods"
    # 100 × 104 / 208 = 50
    assert evaluate(parse(expr), e) == 50.0


def test_makerdao_stability_fee_burn() -> None:
    e = _env(params={"stability_fee": 0.04, "dt": 1.0})
    expr = "state.M['DAI'] * param.stability_fee * param.dt"
    # 5M × 0.04 × 1 = 200k MKR-equivalent value
    assert evaluate(parse(expr), e) == pytest.approx(200000.0)


def test_tiered_redemption_high_tier() -> None:
    e = _env(
        agent={"reputation": 55.0},
        params={"sbt_threshold": 40.0, "high_reward": 5.0, "low_reward": 2.0},
    )
    expr = "if(agent.reputation >= param.sbt_threshold, param.high_reward, param.low_reward)"
    assert evaluate(parse(expr), e) == 5.0


def test_tiered_redemption_low_tier() -> None:
    e = _env(
        agent={"reputation": 10.0},
        params={"sbt_threshold": 40.0, "high_reward": 5.0, "low_reward": 2.0},
    )
    expr = "if(agent.reputation >= param.sbt_threshold, param.high_reward, param.low_reward)"
    assert evaluate(parse(expr), e) == 2.0


def test_curve_voting_power_aggregation() -> None:
    """Aggregate effective veCRV voting power across lockers.

    voting_power = veCRV_balance × lock_remaining / max_lock_periods
    Sum over agents.
    """
    agents = [
        {"type": "locker", "veCRV_balance": 1000.0, "lock_remaining": 208.0},   # 4y lock
        {"type": "locker", "veCRV_balance": 1000.0, "lock_remaining": 52.0},    # 1y lock
        {"type": "locker", "veCRV_balance": 1000.0, "lock_remaining": 26.0},    # 6mo lock
    ]
    e = _env(agents=agents, params={"max_lock": 208.0})
    expr = "sum_over(agents, agent.veCRV_balance * agent.lock_remaining) / param.max_lock"
    # (1000*208 + 1000*52 + 1000*26) / 208 = (208000 + 52000 + 26000)/208 ≈ 1375
    expected = (1000 * 208 + 1000 * 52 + 1000 * 26) / 208
    assert evaluate(parse(expr), e) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_unbound_param_raises() -> None:
    with pytest.raises(EvalError):
        evaluate(parse("param.missing"), _env())


def test_missing_state_key_raises() -> None:
    with pytest.raises(EvalError):
        evaluate(parse("state.M['UNKNOWN']"), _env())
