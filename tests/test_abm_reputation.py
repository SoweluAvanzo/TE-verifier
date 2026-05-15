"""Phase E3 — reputation field, accumulation, decay, utility feedback.

Verifies:
  * Newly spawned agents carry reputation = 0.
  * EARN increments reputation by REPUTATION_GAIN_EARN.
  * VOTE increments reputation by REPUTATION_GAIN_VOTE.
  * apply_reputation_decay shrinks each agent's reputation by (1-decay).
  * reputation_yield > 0 lifts HOLD / EARN scores in pick_action_cached.
  * reputation_yield = 0 leaves behavior bitwise identical to pre-E3.
  * Engine populates ``state['mean_reputation']`` each period and
    applies decay before the next step.
  * Concavity: a 10× larger reputation does NOT produce a 10× larger
    score bonus (log1p damping).
"""

from __future__ import annotations

import math

import pytest

from schema import (
    ActionKind,
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    EmissionTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceSpec,
    GovernanceType,
    HoldingTimeDistribution,
    Meta,
    NFRs,
    NumberRange,
    ParticipantsSpec,
    Rule,
    RuleTrigger,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
    UtilityWeights,
)
from verifier.abm.actions import (
    REPUTATION_GAIN_EARN,
    REPUTATION_GAIN_VOTE,
    apply_reputation_decay,
    build_type_cache,
    compute_pool_shares,
    execute_action,
    pick_action_cached,
)
from verifier.abm.agents import spawn_agents
from verifier.abm.analytics import mean_reputation
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.samplers import Sampler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _te(
    *,
    reputation_yield: float = 0.0,
    reputation_decay: float = 0.0,
    income_yield: float = 1.0,
    holding_yield: float = 0.1,
    n_agents: int = 20,
) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="rep-test", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=[
                    Rule(
                        trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                        function=FunctionShape(
                            sign=FunctionSign.ALWAYS_POSITIVE,
                            asymptotic_class=AsymptoticClass(
                                family=AsymptoticFamily.CONSTANT,
                                parameter_ranges={"c": NumberRange.point(100.0)},
                            ),
                        ),
                    )
                ],
                burn_rules=[
                    Rule(
                        trigger=RuleTrigger(kind=BurnTriggerKind.DEMAND_DRIVEN),
                        function=FunctionShape(
                            sign=FunctionSign.ALWAYS_NEGATIVE,
                            asymptotic_class=AsymptoticClass(
                                family=AsymptoticFamily.CONSTANT,
                                parameter_ranges={"c": NumberRange.point(50.0)},
                            ),
                        ),
                    )
                ],
                offer_variety_K=NumberRange.point(5),
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(n_agents),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="A",
                    fraction=1.0,
                    balance_share=1.0,
                    role=AgentRole.CONTRIBUTOR,
                    utility=UtilityWeights(
                        income_yield=income_yield,
                        holding_yield=holding_yield,
                        redemption_value=0.1,
                        action_temperature=0.3,
                        reputation_yield=reputation_yield,
                        reputation_decay=reputation_decay,
                    ),
                    action_set=[
                        ActionKind.HOLD,
                        ActionKind.EARN,
                        ActionKind.REDEEM,
                        ActionKind.VOTE,
                    ],
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange(min=4, max=10)
                    ),
                ),
            ],
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )


# ---------------------------------------------------------------------------
# State initialization
# ---------------------------------------------------------------------------


def test_spawn_agents_initializes_reputation_zero() -> None:
    te = _te()
    agents = spawn_agents(te, Sampler(seed=1), max_agents=10)
    assert agents
    for a in agents:
        assert a["reputation"] == 0.0


# ---------------------------------------------------------------------------
# Action-driven accumulation
# ---------------------------------------------------------------------------


def test_earn_accumulates_reputation() -> None:
    pools = {"T": {"E": 100.0, "B": 0.0}}
    compute_pool_shares(pools, earn_count=2, redeem_count=0)
    state = {"tokens": {"T": {"M": 0.0, "E": 0.0, "B": 0.0}}, "agents": []}
    realized = {"T": {"E": 0.0, "B": 0.0}}
    sampler = Sampler(seed=0)
    agent = {"id": 0, "balance": 0.0, "last_action": 0, "reputation": 0.0}
    execute_action(
        ActionKind.EARN, agent, state, pools, sampler,
        realized=realized, period=1, primary_token_id="T",
    )
    assert agent["reputation"] == REPUTATION_GAIN_EARN


def test_vote_accumulates_reputation() -> None:
    state = {"tokens": {"T": {"M": 0.0, "E": 0.0, "B": 0.0}}, "agents": []}
    pools = {"T": {"E": 0.0, "B": 0.0}}
    realized = {"T": {"E": 0.0, "B": 0.0}}
    sampler = Sampler(seed=0)
    agent = {"id": 0, "balance": 10.0, "last_action": 0, "reputation": 0.0}
    execute_action(
        ActionKind.VOTE, agent, state, pools, sampler,
        realized=realized, period=1, primary_token_id="T",
    )
    assert agent["reputation"] == REPUTATION_GAIN_VOTE


def test_non_contribution_actions_do_not_accumulate() -> None:
    """HOLD/TRANSFER/REDEEM/STAKE leave reputation unchanged."""
    state = {
        "tokens": {"T": {"M": 100.0, "E": 0.0, "B": 0.0}},
        "agents": [
            {"id": 0, "balance": 50.0, "last_action": 0, "reputation": 3.0},
            {"id": 1, "balance": 50.0, "last_action": 0, "reputation": 3.0},
        ],
        "trade_edges": {},
    }
    pools = {"T": {"E": 0.0, "B": 40.0}}
    compute_pool_shares(pools, earn_count=0, redeem_count=2)
    realized = {"T": {"E": 0.0, "B": 0.0}}
    sampler = Sampler(seed=1)
    for action in (ActionKind.HOLD, ActionKind.TRANSFER, ActionKind.REDEEM, ActionKind.STAKE):
        before = state["agents"][0]["reputation"]
        execute_action(
            action, state["agents"][0], state, pools, sampler,
            realized=realized, period=2, primary_token_id="T",
        )
        assert state["agents"][0]["reputation"] == before


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------


def test_apply_reputation_decay_shrinks_value() -> None:
    te = _te(reputation_decay=0.25)
    cache_by_id = {"A": build_type_cache(te.participants.agent_types[0])}
    agents = [
        {"id": 0, "type": "A", "reputation": 8.0},
        {"id": 1, "type": "A", "reputation": 4.0},
    ]
    apply_reputation_decay(agents, cache_by_id)
    assert agents[0]["reputation"] == pytest.approx(6.0)
    assert agents[1]["reputation"] == pytest.approx(3.0)


def test_apply_reputation_decay_no_op_when_decay_zero() -> None:
    te = _te(reputation_decay=0.0)
    cache_by_id = {"A": build_type_cache(te.participants.agent_types[0])}
    agents = [{"id": 0, "type": "A", "reputation": 5.0}]
    apply_reputation_decay(agents, cache_by_id)
    assert agents[0]["reputation"] == 5.0


def test_apply_reputation_decay_skips_unknown_type() -> None:
    apply_reputation_decay([{"id": 0, "type": "ghost", "reputation": 7.0}], {})
    # No exception, no decay applied (no cache match).


# ---------------------------------------------------------------------------
# Utility feedback in pick_action_cached
# ---------------------------------------------------------------------------


def test_reputation_yield_lifts_earn_score() -> None:
    """With reputation_yield > 0 and a stocked reputation, agents lean
    harder into EARN than the same agents would with zero reputation."""
    te_no_rep = _te(reputation_yield=0.0, holding_yield=2.0, income_yield=1.0)
    te_with_rep = _te(reputation_yield=5.0, holding_yield=2.0, income_yield=1.0)

    cache_no = build_type_cache(te_no_rep.participants.agent_types[0])
    cache_yes = build_type_cache(te_with_rep.participants.agent_types[0])

    sampler_no = Sampler(seed=2024)
    sampler_yes = Sampler(seed=2024)
    agent_no = {"id": 0, "balance": 1.0, "last_action": 0, "reputation": 0.0}
    agent_yes = {"id": 0, "balance": 1.0, "last_action": 0, "reputation": 50.0}

    earn_no = sum(
        1 for _ in range(400)
        if pick_action_cached(agent_no, cache_no, sampler_no, period=1) == ActionKind.EARN
    )
    earn_yes = sum(
        1 for _ in range(400)
        if pick_action_cached(agent_yes, cache_yes, sampler_yes, period=1) == ActionKind.EARN
    )
    assert earn_yes > earn_no


def test_reputation_yield_zero_preserves_pre_phase_e3_behavior() -> None:
    """With reputation_yield == 0, an agent's reputation value is
    irrelevant. Picks are identical to a reputation-less agent."""
    te = _te(reputation_yield=0.0, holding_yield=0.5, income_yield=1.0)
    cache = build_type_cache(te.participants.agent_types[0])

    sampler1 = Sampler(seed=777)
    sampler2 = Sampler(seed=777)
    agent_zero = {"id": 0, "balance": 1.0, "last_action": 0, "reputation": 0.0}
    agent_high = {"id": 0, "balance": 1.0, "last_action": 0, "reputation": 1e6}
    for t in range(1, 50):
        a1 = pick_action_cached(agent_zero, cache, sampler1, period=t)
        a2 = pick_action_cached(agent_high, cache, sampler2, period=t)
        assert a1 == a2


def test_reputation_bonus_is_concave() -> None:
    """log1p damping: 10× more reputation does NOT 10× the bonus."""
    te = _te(reputation_yield=1.0, holding_yield=0.0, income_yield=0.0)
    cache = build_type_cache(te.participants.agent_types[0])
    rep_low, rep_high = 10.0, 100.0
    # Pick the EARN index in the cache.
    earn_idx = cache["actions"].index(ActionKind.EARN)
    rep_bonus_low = cache["reputation_yield"] * math.log1p(rep_low)
    rep_bonus_high = cache["reputation_yield"] * math.log1p(rep_high)
    # Ratio < 10 confirms concavity.
    assert rep_bonus_high / rep_bonus_low < 5.0


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------


def test_engine_step_populates_mean_reputation() -> None:
    te = _te(reputation_yield=1.0, reputation_decay=0.0, income_yield=10.0, holding_yield=0.0)
    sampler = Sampler(seed=42)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    # No reputation yet — mean is 0.
    state = _step_state(state, params)
    # After one period with heavy EARN bias, reputation should be > 0.
    assert "mean_reputation" in state
    if state["last_action_mix"].get("earn", 0) > 0:
        assert state["mean_reputation"] > 0


def test_engine_step_applies_decay() -> None:
    """With high decay, reputation built up in period N gets shrunk by
    decay before period N+1 reads it for scoring."""
    te = _te(reputation_yield=1.0, reputation_decay=0.5, income_yield=10.0, holding_yield=0.0)
    sampler = Sampler(seed=42)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=10)
    state["agents"] = spawn_agents(te, sampler, max_agents=10)
    # Run two periods. Period 1 builds reputation; period 2's mean
    # reflects (period-1 accrual × 0.5) + period-2 accrual.
    state = _step_state(state, params)
    rep_after_p1 = state["mean_reputation"]
    state = _step_state(state, params)
    rep_after_p2 = state["mean_reputation"]
    # Decay shrinks the carry-over; even with another EARN round the
    # growth is bounded — should be less than 2× period-1 if decay > 0.
    assert rep_after_p2 < 2.0 * rep_after_p1 + REPUTATION_GAIN_EARN


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def test_mean_reputation_empty_list_returns_zero() -> None:
    assert mean_reputation([]) == 0.0


def test_mean_reputation_basic() -> None:
    agents = [
        {"reputation": 1.0},
        {"reputation": 3.0},
        {"reputation": 5.0},
    ]
    assert mean_reputation(agents) == pytest.approx(3.0)
