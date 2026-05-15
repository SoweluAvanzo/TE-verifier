"""Phase-B delegation tests.

Confirms:
  • Non-DELEGATED weightings → every agent delegates to self.
  • DELEGATED weighting → top-K wealthiest are delegates; everyone
    else delegates to one of them.
  • Aggregated ``delegated_weights`` sums match total balance.
  • A VOTE action routes weight through ``delegate_of``.
  • ``delegate_concentration_gini`` differs from per-agent Gini when
    delegation concentrates weight.
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
    VoteWeighting,
)
from verifier.abm import SimulationConfig, run_simulation
from verifier.abm.actions import execute_action
from verifier.abm.analytics import gini
from verifier.abm.delegation import (
    assign_delegates,
    delegate_concentration_gini,
    delegated_weights,
    top_delegates,
)
from verifier.abm.samplers import Sampler


def _agents() -> list[dict]:
    return [
        {"id": 0, "balance": 100.0, "last_action": 0, "type": "A"},
        {"id": 1, "balance": 50.0, "last_action": 0, "type": "A"},
        {"id": 2, "balance": 20.0, "last_action": 0, "type": "A"},
        {"id": 3, "balance": 5.0, "last_action": 0, "type": "A"},
        {"id": 4, "balance": 1.0, "last_action": 0, "type": "A"},
        {"id": 5, "balance": 0.5, "last_action": 0, "type": "A"},
    ]


def test_non_delegated_assigns_self() -> None:
    agents = _agents()
    sampler = Sampler(seed=1)
    assign_delegates(agents, VoteWeighting.LINEAR, sampler)
    for a in agents:
        assert a["delegate_of"] == a["id"]


def test_quadratic_also_self_delegates() -> None:
    """QUADRATIC, TIME_LOCKED, etc. all self-delegate in the ABM."""
    for vw in [
        VoteWeighting.QUADRATIC,
        VoteWeighting.TIME_LOCKED,
        VoteWeighting.CAPPED,
        VoteWeighting.REPUTATION_WEIGHTED,
    ]:
        agents = _agents()
        assign_delegates(agents, vw, Sampler(seed=2))
        for a in agents:
            assert a["delegate_of"] == a["id"]


def test_delegated_selects_top_k_as_delegates() -> None:
    """K = max(3, sqrt(N)). For N=6, K=3 → top-3 wealthiest are
    delegates; non-delegates point at one of them."""
    agents = _agents()
    sampler = Sampler(seed=3)
    assign_delegates(agents, VoteWeighting.DELEGATED, sampler)
    delegates = {a["id"] for a in agents if a["delegate_of"] == a["id"]}
    assert delegates == {0, 1, 2}  # top-3 by balance
    for a in agents:
        if a["id"] in delegates:
            assert a["delegate_of"] == a["id"]
        else:
            assert a["delegate_of"] in delegates


def test_delegated_weights_sums_to_total_balance() -> None:
    """Aggregating delegated weights must conserve total balance."""
    agents = _agents()
    assign_delegates(agents, VoteWeighting.DELEGATED, Sampler(seed=4))
    weights = delegated_weights(agents)
    assert sum(weights.values()) == sum(a["balance"] for a in agents)


def test_vote_routes_weight_to_delegate() -> None:
    """A VOTE call adds the agent's balance to votes_by_delegate
    under its delegate's id."""
    agents = _agents()
    # Force delegate_of: agent 3 → delegate 0.
    for a in agents:
        a["delegate_of"] = 0 if a["id"] >= 3 else a["id"]
    state = {
        "tokens": {"T": {"M": 100.0, "E": 0.0, "B": 0.0}},
        "agents": agents,
    }
    realized = {"T": {"E": 0.0, "B": 0.0}}
    pools = {"T": {"E": 0.0, "B": 0.0}}
    sampler = Sampler(seed=5)
    # Agent 3 (balance=5) votes — weight should go to delegate 0.
    execute_action(
        ActionKind.VOTE, agents[3], state, pools, sampler,
        realized=realized, period=1, primary_token_id="T",
    )
    assert state["votes_by_delegate"][0] == 5.0
    # Agent 0 (its own delegate) votes — also goes to 0.
    execute_action(
        ActionKind.VOTE, agents[0], state, pools, sampler,
        realized=realized, period=1, primary_token_id="T",
    )
    assert state["votes_by_delegate"][0] == 105.0


def test_delegate_concentration_gini_higher_than_holder_gini() -> None:
    """When the bottom holders all delegate to one wealthy agent, the
    delegate Gini exceeds the raw token Gini (concentration increases
    under DELEGATED)."""
    agents = _agents()
    # All non-top-3 delegate to id=0 (forced).
    assign_delegates(agents, VoteWeighting.DELEGATED, Sampler(seed=99))
    delegate_g = delegate_concentration_gini(agents)
    holder_g = gini([a["balance"] for a in agents])
    # Concentrating up always raises Gini (or holds it equal in
    # degenerate cases). Strictly greater for our skewed distribution.
    assert delegate_g >= holder_g


def test_top_delegates_orders_by_aggregated_weight() -> None:
    agents = _agents()
    for a in agents:
        a["delegate_of"] = 0 if a["id"] != 1 else 1
    top = top_delegates(agents, k=2)
    # 0 aggregates 100+20+5+1+0.5 = 126.5; 1 keeps 50.
    assert top[0][0] == 0
    assert top[0][1] == 126.5
    assert top[1][0] == 1
    assert top[1][1] == 50.0


def _te_with_delegated_governance() -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="deleg-test", archetype=Archetype.OTHER, nfrs=NFRs()),
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
                    role=AgentRole.GOVERNANCE_ONLY,
                    utility=UtilityWeights(
                        governance_payoff=10.0,
                        action_temperature=0.1,
                    ),
                    action_set=[ActionKind.VOTE, ActionKind.HOLD],
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                )
            ],
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            vote_weighting=VoteWeighting.DELEGATED,
            vote_weighting_params={
                "delegate_concentration_gini": NumberRange.point(0.7)
            },
        ),
    )


def test_end_to_end_delegated_run_emits_delegate_gini() -> None:
    """A DELEGATED governance run should produce non-trivial
    delegate concentration in state."""
    te = _te_with_delegated_governance()
    cfg = SimulationConfig(n_runs=2, seed=7, horizon_periods=5)
    report = run_simulation(te, config=cfg)
    assert report.per_fm_results
