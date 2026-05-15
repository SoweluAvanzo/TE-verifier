"""Phase E1 — stochastic exit mechanism.

Verifies:
  * Default (exit_propensity=0) — population is invariant.
  * High propensity + zero-balance agents — population shrinks.
  * Social comparison amplifies exit for laggards (mean-gap effect).
  * After-exit state['N'] tracks the survivor fraction (FM5 hook).
  * Neighbor graph is rebuilt when exits happen.
  * apply_exit_decisions short-circuits on empty agent list and on
    all-types-disabled configurations.
"""

from __future__ import annotations

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
from verifier.abm.agents import spawn_agents
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.exit import (
    agent_scalar_utility,
    any_exit_enabled,
    apply_exit_decisions,
)
from verifier.abm.samplers import Sampler


def _te(
    *,
    exit_propensity: float = 0.0,
    social_comparison_delta: float = 0.3,
    income_yield: float = 1.0,
    redemption_value: float = 0.1,
    n_agents: int = 20,
    topology: Topology = Topology.WELL_MIXED,
) -> TokenEconomy:
    """Single-token, single-type TE — vary exit parameters per test."""
    return TokenEconomy(
        meta=Meta(name="exit-test", archetype=Archetype.OTHER, nfrs=NFRs()),
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
            topology=topology,
            agent_types=[
                AgentType(
                    id="A",
                    fraction=1.0,
                    balance_share=1.0,
                    role=AgentRole.CONTRIBUTOR,
                    utility=UtilityWeights(
                        income_yield=income_yield,
                        redemption_value=redemption_value,
                        action_temperature=0.5,
                        exit_propensity=exit_propensity,
                        social_comparison_delta=social_comparison_delta,
                    ),
                    action_set=[
                        ActionKind.HOLD,
                        ActionKind.EARN,
                        ActionKind.REDEEM,
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
# Scalar utility derivation
# ---------------------------------------------------------------------------


def test_agent_scalar_utility_combines_balance_and_governance() -> None:
    uw = UtilityWeights(
        income_yield=1.0,
        redemption_value=0.5,
        governance_payoff=0.2,
    )
    agent = {"balance": 10.0}
    # u_econ = (1.0 + 0.5) * 10 = 15; u_govern = 0.2 * 1 = 0.2.
    assert agent_scalar_utility(agent, uw) == 15.2


def test_agent_scalar_utility_zero_balance_drops_governance() -> None:
    uw = UtilityWeights(income_yield=1.0, governance_payoff=1.0)
    assert agent_scalar_utility({"balance": 0.0}, uw) == 0.0


def test_agent_scalar_utility_none_utility_returns_zero() -> None:
    assert agent_scalar_utility({"balance": 5.0}, None) == 0.0


# ---------------------------------------------------------------------------
# Enablement gate
# ---------------------------------------------------------------------------


def test_any_exit_enabled_default_is_false() -> None:
    te = _te()
    by_id = {at.id: at for at in te.participants.agent_types}
    assert any_exit_enabled(by_id) is False


def test_any_exit_enabled_returns_true_when_positive() -> None:
    te = _te(exit_propensity=0.5)
    by_id = {at.id: at for at in te.participants.agent_types}
    assert any_exit_enabled(by_id) is True


# ---------------------------------------------------------------------------
# Direct apply_exit_decisions
# ---------------------------------------------------------------------------


def test_apply_exit_decisions_noop_when_all_disabled() -> None:
    te = _te(exit_propensity=0.0)
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    before = len(state["agents"])
    removed = apply_exit_decisions(
        state, params["agent_types_by_id"], sampler
    )
    assert removed == 0
    assert len(state["agents"]) == before


def test_apply_exit_decisions_removes_some_when_enabled_high() -> None:
    # Force exit by setting propensity to its ceiling and creating a
    # split population: half rich, half poor. The poor agents are
    # strictly below the mean → activation > 0 → some exit.
    te = _te(exit_propensity=1.0, social_comparison_delta=2.0)
    sampler = Sampler(seed=42)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=40)
    state["agents"] = spawn_agents(te, sampler, max_agents=40)
    for i, a in enumerate(state["agents"]):
        # Half the cohort holds non-trivial balance, half holds nothing.
        # Mean utility lands well above zero → the zero-balance half
        # sees a strong gap → activation > 0 → exit roll fires.
        a["balance"] = 10.0 if i % 2 == 0 else 0.0
    before = len(state["agents"])
    removed = apply_exit_decisions(
        state, params["agent_types_by_id"], sampler
    )
    assert removed > 0
    assert len(state["agents"]) == before - removed


def test_apply_exit_decisions_zero_exit_at_uniform_zero_utility() -> None:
    """When every agent sits at u_self = u_mean = 0 (everyone equally
    poor at t=0), nobody exits — the rescaled sigmoid has activation 0
    at the neutral point. Prevents spurious early attrition."""
    te = _te(exit_propensity=1.0, social_comparison_delta=2.0)
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=40)
    state["agents"] = spawn_agents(te, sampler, max_agents=40)
    for a in state["agents"]:
        a["balance"] = 0.0
    before = len(state["agents"])
    removed = apply_exit_decisions(
        state, params["agent_types_by_id"], sampler
    )
    assert removed == 0
    assert len(state["agents"]) == before


def test_apply_exit_decisions_empty_population_no_op() -> None:
    te = _te(exit_propensity=1.0)
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=10)
    state["agents"] = []
    assert apply_exit_decisions(
        state, params["agent_types_by_id"], sampler
    ) == 0


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------


def test_step_state_population_invariant_when_exit_disabled() -> None:
    te = _te(exit_propensity=0.0)
    sampler = Sampler(seed=7)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    before = len(state["agents"])
    for _ in range(10):
        state = _step_state(state, params)
    assert len(state["agents"]) == before


def test_step_state_population_shrinks_under_aggressive_exit() -> None:
    te = _te(exit_propensity=1.0, social_comparison_delta=1.0)
    sampler = Sampler(seed=99)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=40)
    state["agents"] = spawn_agents(te, sampler, max_agents=40)
    # Wipe balances every period would defeat EARN-driven recovery, so
    # we only wipe once at t=0; subsequent EARN may refill.
    for a in state["agents"]:
        a["balance"] = 0.0
    before = len(state["agents"])
    for _ in range(20):
        state = _step_state(state, params)
    assert len(state["agents"]) < before


def test_step_state_rescales_state_N_on_exit() -> None:
    te = _te(exit_propensity=1.0, social_comparison_delta=1.0)
    sampler = Sampler(seed=123)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=20)
    state["agents"] = spawn_agents(te, sampler, max_agents=20)
    n_initial = len(state["agents"])
    state["N"] = float(n_initial)  # align so the ratio is observable
    for a in state["agents"]:
        a["balance"] = 0.0
    for _ in range(15):
        state = _step_state(state, params)
    survivors = len(state["agents"])
    # state['N'] should have followed survivors (modulo growth_g=0 here).
    assert state["N"] <= n_initial
    if survivors < n_initial:
        assert state["N"] < n_initial


def test_step_state_rebuilds_neighbor_graph_after_exit() -> None:
    """When the topology is non-trivial, exits must trigger a graph
    rebuild so dropped agent ids stop appearing as neighbors."""
    te = _te(
        exit_propensity=1.0,
        social_comparison_delta=1.0,
        topology=Topology.NETWORK,
    )
    sampler = Sampler(seed=321)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=30)
    state["agents"] = spawn_agents(te, sampler, max_agents=30)
    from verifier.abm.topology import build_neighbor_graph
    params["neighbor_graph"] = build_neighbor_graph(
        te.participants, state["agents"], sampler
    )
    for a in state["agents"]:
        a["balance"] = 0.0
    for _ in range(15):
        state = _step_state(state, params)
    survivor_ids = {a["id"] for a in state["agents"]}
    # No dangling neighbor pointers — every key in the graph must
    # correspond to a surviving agent.
    graph = params["neighbor_graph"] or {}
    assert set(graph.keys()) == survivor_ids
    # And every neighbor referenced must also survive.
    for aid, neighbors in graph.items():
        for nid in neighbors:
            assert nid in survivor_ids
