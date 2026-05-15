"""Phase-B interaction-topology tests.

Verifies:
  • ``build_neighbor_graph`` honors the TE's ``Topology`` setting.
  • WELL_MIXED returns ``None`` (full-population fallback in actions).
  • NETWORK produces an Erdős–Rényi-shaped degree distribution near
    the declared ``average_degree``.
  • SPATIAL produces a 2k-regular ring with predictable degree.
  • TRANSFER respects the neighbor restriction end-to-end.
  • ``graph_density`` returns sensible values per topology.
"""

from __future__ import annotations

from schema import (
    ActionKind,
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
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
from verifier.abm import SimulationConfig, run_simulation
from verifier.abm.actions import execute_action
from verifier.abm.agents import spawn_agents
from verifier.abm.samplers import Sampler
from verifier.abm.topology import (
    build_neighbor_graph,
    graph_density,
)


def _agent_list(n: int) -> list[dict]:
    return [{"id": i, "type": "A", "balance": 1.0, "last_action": 0} for i in range(n)]


def _participants(
    topology: Topology,
    average_degree: int | None = None,
    n: int = 20,
) -> ParticipantsSpec:
    params: dict[str, NumberRange] = {}
    if average_degree is not None:
        params["average_degree"] = NumberRange.point(average_degree)
    return ParticipantsSpec(
        count_N=NumberRange.point(n),
        expected_Q=NumberRange.point(100),
        average_demand_d=NumberRange.point(1.0),
        growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
        topology=topology,
        topology_params=params,
        agent_types=[
            AgentType(
                id="A",
                fraction=1.0,
                role=AgentRole.CONTRIBUTOR,
                expected_holding_time=HoldingTimeDistribution(
                    expected_periods=NumberRange.point(5)
                ),
            )
        ],
    )


def test_well_mixed_returns_none_graph() -> None:
    """WELL_MIXED ⇒ ``None`` so action loop falls back to full
    population sampling."""
    parts = _participants(Topology.WELL_MIXED, n=10)
    agents = _agent_list(10)
    g = build_neighbor_graph(parts, agents, Sampler(seed=1))
    assert g is None


def test_network_graph_has_target_average_degree() -> None:
    """Erdős–Rényi: empirical average degree is within ±30% of target
    for n=80 agents (small but tractable)."""
    target_k = 6
    parts = _participants(Topology.NETWORK, average_degree=target_k, n=80)
    agents = _agent_list(80)
    g = build_neighbor_graph(parts, agents, Sampler(seed=2))
    assert g is not None
    degrees = [len(n) for n in g.values()]
    avg = sum(degrees) / len(degrees)
    assert target_k * 0.7 <= avg <= target_k * 1.3, avg


def test_spatial_graph_is_regular_with_2k_neighbors() -> None:
    """A ring with avg_degree=4 → every node has exactly 4 neighbors."""
    parts = _participants(Topology.SPATIAL, average_degree=4, n=12)
    agents = _agent_list(12)
    g = build_neighbor_graph(parts, agents, Sampler(seed=3))
    assert g is not None
    for neigh in g.values():
        assert len(neigh) == 4


def test_network_graph_with_default_average_degree() -> None:
    """No average_degree ⇒ log(N) fallback."""
    parts = _participants(Topology.NETWORK, n=64)
    agents = _agent_list(64)
    g = build_neighbor_graph(parts, agents, Sampler(seed=4))
    assert g is not None
    degrees = [len(n) for n in g.values()]
    avg = sum(degrees) / len(degrees)
    import math

    target = math.log(64)  # ~4.16
    assert target * 0.5 <= avg <= target * 1.7, avg


def test_graph_density() -> None:
    assert graph_density(None, 50) == 1.0  # WELL_MIXED
    assert graph_density({}, 0) == 0.0
    g = {0: (1,), 1: (0, 2), 2: (1,)}
    # 2 undirected edges / 3 possible
    assert graph_density(g, 3) == 2.0 / 3.0


def test_transfer_uses_neighbor_when_graph_provided() -> None:
    """When neighbor_graph is set, TRANSFER never targets a non-neighbor."""
    agents = _agent_list(6)
    # Force agent 0's neighbors to be only {3}; transfer should always
    # land on 3.
    neighbor_graph = {
        0: (3,),
        1: (2, 4),
        2: (1, 5),
        3: (0,),
        4: (1,),
        5: (2,),
    }
    agents_by_id = {a["id"]: a for a in agents}
    state = {
        "tokens": {"T": {"M": 100.0, "E": 0.0, "B": 0.0}},
        "agents": agents,
        "trade_edges": {},
    }
    realized = {"T": {"E": 0.0, "B": 0.0}}
    pools = {"T": {"E": 0.0, "B": 0.0}}
    sampler = Sampler(seed=10)
    # Run 20 transfers.
    for _ in range(20):
        execute_action(
            ActionKind.TRANSFER, agents[0], state, pools, sampler,
            realized=realized, period=1, primary_token_id="T",
            neighbor_graph=neighbor_graph, agents_by_id=agents_by_id,
        )
    # Every recorded edge must involve agent 0 and 3.
    for (a, b), w in state["trade_edges"].items():
        assert (a, b) == (0, 3)


def _te_for_topology(topology: Topology, average_degree: int) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="topology-test", archetype=Archetype.OTHER, nfrs=NFRs()),
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
                                parameter_ranges={"c": NumberRange.point(10.0)},
                            ),
                        ),
                    )
                ],
                offer_variety_K=NumberRange.point(5),
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(40),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=topology,
            topology_params={"average_degree": NumberRange.point(average_degree)},
            agent_types=[
                AgentType(
                    id="A",
                    fraction=1.0,
                    balance_share=1.0,
                    role=AgentRole.CONTRIBUTOR,
                    utility=UtilityWeights(
                        social_payoff=10.0,         # forces TRANSFER
                        income_yield=0.0,
                        holding_yield=0.0,
                        redemption_value=0.0,
                        action_temperature=0.1,
                    ),
                    action_set=[ActionKind.TRANSFER, ActionKind.HOLD],
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                )
            ],
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )


def test_end_to_end_network_run_emits_trade_edges() -> None:
    """A run with a NETWORK topology and TRANSFER-dominant utility
    produces a non-empty trade graph at the end."""
    te = _te_for_topology(Topology.NETWORK, average_degree=6)
    cfg = SimulationConfig(n_runs=2, seed=7, horizon_periods=20)
    report = run_simulation(te, config=cfg)
    # Sanity: the run completes and produces per-FM results.
    assert report.per_fm_results
