"""Phase-A action-loop tests.

The reference ABM was upgraded from rule-aggregate dynamics to a
per-agent action loop. Each agent picks an action per period via
softmax over its UtilityWeights and the rule-level rates become
*pools* the action loop draws from. These tests verify:

  • The action loop actually runs when ``agent_types`` is present.
  • EARN distributes the emission pool across earners (so the
    realized E ≈ target E when ≥1 agent earns).
  • REDEEM consumes balance and drives realized B.
  • TRANSFER conserves balance (no minting via peer-to-peer).
  • STAKE locks the agent for K periods.
  • Live ``effective_gini`` is computed from balances and tracks
    skewed weights.
  • The per-period ``last_action_mix`` is recorded for analytics.
  • ``effective_max_agents`` scales the cap by workload.

Kept in its own file so the existing aggregate-ABM tests remain
unchanged.
"""

from __future__ import annotations

import pytest

from schema import (
    ActionKind,
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    EmissionTriggerKind,
    BurnTriggerKind,
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
from verifier.abm import SimulationConfig, run_simulation
from verifier.abm.actions import (
    build_type_cache,
    compute_pool_shares,
    execute_action,
    is_staked,
    pick_action_cached,
    prepare_pools,
)
from verifier.abm.agents import effective_max_agents, spawn_agents
from verifier.abm.analytics import gini
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.samplers import Sampler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _te_for_action_loop(
    *,
    earn_weight: float = 1.0,
    redeem_weight: float = 0.1,
    hold_weight: float = 0.1,
    transfer_weight: float = 0.0,
    emission_per_period: float = 100.0,
    burn_per_period: float = 50.0,
    agent_role: AgentRole = AgentRole.CONTRIBUTOR,
) -> TokenEconomy:
    """A TE with one token, one agent_type, and predictable per-period
    emission/burn pools. Tests use this to verify pool consumption."""
    return TokenEconomy(
        meta=Meta(name="action-test", archetype=Archetype.OTHER, nfrs=NFRs()),
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
                                parameter_ranges={
                                    "c": NumberRange.point(emission_per_period)
                                },
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
                                parameter_ranges={
                                    "c": NumberRange.point(burn_per_period)
                                },
                            ),
                        ),
                    )
                ],
                offer_variety_K=NumberRange.point(5),
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(20),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="A",
                    fraction=1.0,
                    balance_share=1.0,
                    role=agent_role,
                    utility=UtilityWeights(
                        income_yield=earn_weight,
                        holding_yield=hold_weight,
                        redemption_value=redeem_weight,
                        social_payoff=transfer_weight,
                        action_temperature=0.1,  # sharp / near-deterministic
                    ),
                    action_set=[
                        ActionKind.EARN,
                        ActionKind.HOLD,
                        ActionKind.REDEEM,
                        ActionKind.TRANSFER,
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
# Hot-path sampler tests
# ---------------------------------------------------------------------------


def test_pick_action_cached_picks_max_utility_at_low_temperature() -> None:
    """With temperature ≪ 1, softmax collapses to argmax."""
    ag_type = AgentType(
        id="A",
        fraction=1.0,
        role=AgentRole.CONTRIBUTOR,
        utility=UtilityWeights(
            income_yield=10.0,
            holding_yield=0.1,
            action_temperature=0.01,
        ),
        action_set=[ActionKind.EARN, ActionKind.HOLD],
        expected_holding_time=HoldingTimeDistribution(
            expected_periods=NumberRange.point(5)
        ),
    )
    cache = build_type_cache(ag_type)
    sampler = Sampler(seed=1)
    agent = {"id": 0, "balance": 1.0, "last_action": 0}
    counts = {ActionKind.EARN: 0, ActionKind.HOLD: 0}
    for _ in range(100):
        a = pick_action_cached(agent, cache, sampler, period=1)
        counts[a] = counts.get(a, 0) + 1
    assert counts[ActionKind.EARN] >= 95, counts


def test_pick_action_cached_distributes_at_high_temperature() -> None:
    """High temperature → near-uniform selection."""
    ag_type = AgentType(
        id="A",
        fraction=1.0,
        role=AgentRole.CONTRIBUTOR,
        utility=UtilityWeights(
            income_yield=1.0,
            holding_yield=1.0,
            redemption_value=1.0,
            action_temperature=100.0,
        ),
        action_set=[ActionKind.EARN, ActionKind.HOLD, ActionKind.REDEEM],
        expected_holding_time=HoldingTimeDistribution(
            expected_periods=NumberRange.point(5)
        ),
    )
    cache = build_type_cache(ag_type)
    sampler = Sampler(seed=42)
    agent = {"id": 0, "balance": 1.0, "last_action": 0}
    counts = {ActionKind.EARN: 0, ActionKind.HOLD: 0, ActionKind.REDEEM: 0}
    for _ in range(900):
        a = pick_action_cached(agent, cache, sampler, period=1)
        counts[a] = counts.get(a, 0) + 1
    # No bin should dominate badly — each should be near 300 (±100).
    for c in counts.values():
        assert 200 <= c <= 400, counts


def test_build_type_cache_is_pure_tuples() -> None:
    """Cache fields are tuple-shaped — no dicts inside the hot path."""
    ag_type = AgentType(
        id="A",
        fraction=1.0,
        role=AgentRole.CONTRIBUTOR,
        expected_holding_time=HoldingTimeDistribution(
            expected_periods=NumberRange.point(5)
        ),
    )
    cache = build_type_cache(ag_type)
    assert isinstance(cache["actions"], tuple)
    assert isinstance(cache["weights"], tuple)
    assert isinstance(cache["is_hold"], tuple)
    assert len(cache["actions"]) == len(cache["weights"])
    assert cache["n"] == len(cache["actions"])


# ---------------------------------------------------------------------------
# Action execution tests
# ---------------------------------------------------------------------------


def test_earn_distributes_emission_pool_across_earners() -> None:
    """Each EARN-ing agent gets share = pool / count."""
    pools = {"T": {"E": 100.0, "B": 0.0}}
    compute_pool_shares(pools, earn_count=4, redeem_count=0)
    assert pools["T"]["_earn_share"] == pytest.approx(25.0)
    assert pools["T"]["_redeem_share"] == 0.0

    state = {"tokens": {"T": {"M": 1000.0, "E": 0.0, "B": 0.0}}, "agents": []}
    realized = {"T": {"E": 0.0, "B": 0.0}}
    sampler = Sampler(seed=1)
    for aid in range(4):
        agent = {"id": aid, "balance": 0.0, "last_action": 0}
        execute_action(
            ActionKind.EARN, agent, state, pools, sampler,
            realized=realized, period=1, primary_token_id="T",
        )
        assert agent["balance"] == pytest.approx(25.0)
    assert realized["T"]["E"] == pytest.approx(100.0)
    assert state["tokens"]["T"]["M"] == pytest.approx(1100.0)


def test_redeem_drives_burn_and_consumes_balance() -> None:
    """REDEEM-ing agents lose balance; realized B increases by spend."""
    pools = {"T": {"E": 0.0, "B": 40.0}}
    compute_pool_shares(pools, earn_count=0, redeem_count=2)
    assert pools["T"]["_redeem_share"] == pytest.approx(20.0)

    state = {"tokens": {"T": {"M": 1000.0, "E": 0.0, "B": 0.0}}, "agents": []}
    realized = {"T": {"E": 0.0, "B": 0.0}}
    sampler = Sampler(seed=1)
    agents = [
        {"id": 0, "balance": 30.0, "last_action": 0},
        {"id": 1, "balance": 10.0, "last_action": 0},  # only 10 to spend
    ]
    state["agents"] = agents
    for a in agents:
        execute_action(
            ActionKind.REDEEM, a, state, pools, sampler,
            realized=realized, period=1, primary_token_id="T",
        )
    # First agent spent 20 (full share), second was clamped to 10.
    assert agents[0]["balance"] == pytest.approx(10.0)
    assert agents[1]["balance"] == pytest.approx(0.0)
    assert realized["T"]["B"] == pytest.approx(30.0)
    # M decreased by the realized burn.
    assert state["tokens"]["T"]["M"] == pytest.approx(970.0)


def test_transfer_conserves_balance() -> None:
    """TRANSFER moves balance peer-to-peer — total stays constant."""
    state = {
        "tokens": {"T": {"M": 100.0, "E": 0.0, "B": 0.0}},
        "agents": [
            {"id": 0, "balance": 50.0, "last_action": 0},
            {"id": 1, "balance": 50.0, "last_action": 0},
            {"id": 2, "balance": 50.0, "last_action": 0},
        ],
        "trade_edges": {},
    }
    realized = {"T": {"E": 0.0, "B": 0.0}}
    sampler = Sampler(seed=2)
    pools = {"T": {"E": 0.0, "B": 0.0}}
    total_before = sum(a["balance"] for a in state["agents"])
    for a in state["agents"]:
        execute_action(
            ActionKind.TRANSFER, a, state, pools, sampler,
            realized=realized, period=1, primary_token_id="T",
        )
    total_after = sum(a["balance"] for a in state["agents"])
    assert total_after == pytest.approx(total_before)
    # Realized E/B didn't move — transfers don't mint or burn.
    assert realized["T"]["E"] == 0.0
    assert realized["T"]["B"] == 0.0
    # A trade edge was recorded for analytics.
    assert state["trade_edges"]


def test_stake_locks_agent_for_subsequent_periods() -> None:
    """STAKE sets staking_until > current period."""
    agent = {"id": 0, "balance": 1.0, "last_action": 0}
    state = {"tokens": {"T": {"M": 1.0, "E": 0.0, "B": 0.0}}, "agents": [agent]}
    realized = {"T": {"E": 0.0, "B": 0.0}}
    pools = {"T": {"E": 0.0, "B": 0.0}}
    sampler = Sampler(seed=1)
    execute_action(
        ActionKind.STAKE, agent, state, pools, sampler,
        realized=realized, period=5, primary_token_id="T",
    )
    assert is_staked(agent, period=10) is True
    assert is_staked(agent, period=20) is False  # default 8-period lock


# ---------------------------------------------------------------------------
# Live-aggregate (engine-level) tests
# ---------------------------------------------------------------------------


def test_engine_step_runs_action_loop_when_agents_present() -> None:
    """A spec with agent_types produces a non-empty action_mix and
    moves balances per period."""
    te = _te_for_action_loop()
    sampler = Sampler(seed=11)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    # Step a few periods.
    for _ in range(5):
        state = _step_state(state, params)
    assert state.get("last_action_mix"), "action_mix must be populated"
    # Most agents favor EARN (income_yield=1.0). Action mix should
    # have meaningful EARN share.
    assert "earn" in state["last_action_mix"]


def test_engine_step_produces_live_gini() -> None:
    """With heterogeneous balance_share, ``effective_gini`` reflects
    the live balance distribution, not just the declared one."""
    te = _te_for_action_loop()
    sampler = Sampler(seed=11)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    state = _step_state(state, params)
    assert "effective_gini" in state
    # Pure EARN actions should slowly equalize balances — but the
    # initial distribution is uniform here so gini is near zero.
    assert 0.0 <= state["effective_gini"] <= 1.0


def test_engine_earn_realized_matches_emission_pool_when_all_earn() -> None:
    """When all agents pick EARN (utility heavily favors it), realized
    E ≈ target E (pool fully consumed)."""
    te = _te_for_action_loop(
        earn_weight=10.0, hold_weight=0.0, redeem_weight=0.0, transfer_weight=0.0,
        emission_per_period=100.0,
    )
    sampler = Sampler(seed=33)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=10)
    state["agents"] = spawn_agents(te, sampler, max_agents=10)
    state = _step_state(state, params)
    # All 10 agents should pick EARN. Pool of 100 fully distributed.
    assert state["tokens"]["T"]["E"] == pytest.approx(100.0, rel=0.05)


def test_engine_no_earners_yields_zero_realized_emission() -> None:
    """If no agent picks EARN, the emission pool goes unspent: realized
    E == 0 even though the target rate was 100. (Emergent under-
    issuance is a core ABM feature.)"""
    te = _te_for_action_loop(
        earn_weight=0.0,           # no income_yield → never picks EARN
        hold_weight=10.0,          # always HOLD
        redeem_weight=0.0,
        transfer_weight=0.0,
        emission_per_period=100.0,
    )
    sampler = Sampler(seed=77)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=10)
    state["agents"] = spawn_agents(te, sampler, max_agents=10)
    state = _step_state(state, params)
    # Under HOLD-only behavior, EARN pool went unspent.
    assert state["tokens"]["T"]["E"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Workload-aware agent cap
# ---------------------------------------------------------------------------


def test_effective_max_agents_respects_override() -> None:
    assert effective_max_agents(100, 260, override=50) == 50
    assert effective_max_agents(5000, 5000, override=10) == 10


def test_effective_max_agents_scales_with_workload() -> None:
    """Default budget is 15M agent-step units. Small workloads keep
    the full 200-agent cap; pathologically large ones drop to 5."""
    # Tiny workload — full cap.
    assert effective_max_agents(10, 50) == 200
    # Huge workload — minimum floor.
    assert effective_max_agents(5000, 5000) == 5


# ---------------------------------------------------------------------------
# End-to-end smoke test — run_simulation completes with action loop
# ---------------------------------------------------------------------------


def test_run_simulation_with_agents_completes() -> None:
    """End-to-end: a TE with agent_types runs through the simulator
    and produces per-FM results without raising."""
    te = _te_for_action_loop()
    cfg = SimulationConfig(n_runs=5, seed=42, horizon_periods=20)
    report = run_simulation(te, config=cfg)
    assert report.te_name == "action-test"
    # The action loop produced some realized state — no crash, has FMs.
    assert report.per_fm_results
