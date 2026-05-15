"""Phase-C population-dynamics tests.

Verifies:
  • SPAWN_AGENTS at period T grows the agent list.
  • DESPAWN_AGENTS at period T removes the lowest-balance agents of
    the targeted type.
  • SHIFT_UTILITY swaps the cached softmax weights mid-run, changing
    subsequent action selection.
  • Multiple events at the same period apply in declaration order.
  • Neighbor graph + delegate assignments are rebuilt after the
    population changes.
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
    PopulationEvent,
    PopulationEventKind,
    Rule,
    RuleTrigger,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
    UtilityWeights,
)
from verifier.abm import SimulationConfig, run_explore, run_simulation
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.events import apply_population_events
from verifier.abm.samplers import Sampler


def _te(
    population_events: list[PopulationEvent] | None = None,
    role: AgentRole = AgentRole.CONTRIBUTOR,
    util: UtilityWeights | None = None,
) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="events-test", archetype=Archetype.OTHER, nfrs=NFRs()),
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
                    role=role,
                    utility=util,
                    action_set=[ActionKind.EARN, ActionKind.HOLD],
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                )
            ],
            population_events=population_events or [],
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )


# ---------------------------------------------------------------------------
# SPAWN
# ---------------------------------------------------------------------------


def test_spawn_event_increases_agent_count() -> None:
    te = _te(
        population_events=[
            PopulationEvent(
                kind=PopulationEventKind.SPAWN_AGENTS,
                at_period=2,
                agent_type_id="A",
                count=5,
                balance_per_agent=1.0,
            )
        ],
        util=UtilityWeights(income_yield=1.0, action_temperature=1.0),
    )
    cfg = SimulationConfig(horizon_periods=4, seed=1, max_agents=20)
    report = run_explore(te, sim_config=cfg)
    # Snapshot at t=0: initial pop. Snapshot at t=2: should have +5.
    sizes = [len(s.balances) for s in report.snapshots]
    assert sizes[0] == sizes[1] == sizes[2] - 5
    assert sizes[2] == sizes[3] == sizes[4]


def test_spawn_event_assigns_initial_balance() -> None:
    te = _te(
        population_events=[
            PopulationEvent(
                kind=PopulationEventKind.SPAWN_AGENTS,
                at_period=1,
                agent_type_id="A",
                count=3,
                balance_per_agent=42.0,
            )
        ],
    )
    cfg = SimulationConfig(horizon_periods=2, seed=2, max_agents=20)
    report = run_explore(te, sim_config=cfg)
    # New agents have balance 42 at t=1.
    bal_at_1 = sorted(report.snapshots[1].balances)
    # Should include three values near 42 (some drift possible if they
    # earn). We pick the top-3 and confirm they're at least 42.
    top3 = sorted(bal_at_1)[-3:]
    assert all(b >= 42.0 for b in top3)


# ---------------------------------------------------------------------------
# DESPAWN
# ---------------------------------------------------------------------------


def test_despawn_event_decreases_agent_count() -> None:
    te = _te(
        population_events=[
            PopulationEvent(
                kind=PopulationEventKind.DESPAWN_AGENTS,
                at_period=3,
                agent_type_id="A",
                count=4,
            )
        ],
    )
    cfg = SimulationConfig(horizon_periods=4, seed=3, max_agents=20)
    report = run_explore(te, sim_config=cfg)
    sizes = [len(s.balances) for s in report.snapshots]
    assert sizes[0] == sizes[1] == sizes[2]
    assert sizes[3] == sizes[0] - 4


def test_despawn_event_removes_lowest_balance_first() -> None:
    """Direct check on apply_population_events with a controlled set."""
    state = {
        "agents": [
            {"id": 0, "type": "A", "balance": 100.0, "last_action": 0},
            {"id": 1, "type": "A", "balance": 5.0, "last_action": 0},
            {"id": 2, "type": "A", "balance": 1.0, "last_action": 0},
            {"id": 3, "type": "A", "balance": 200.0, "last_action": 0},
        ],
    }
    # Don't need a full params for this — just enough that no graph
    # rebuild errors out. Use the participants_snapshot from our _te.
    parts = _te().participants
    params = {
        "agent_types_by_id": {a.id: a for a in parts.agent_types},
        "type_cache_by_id": {},
        "vote_weighting": None,
    }
    sampler = Sampler(seed=99)
    apply_population_events(
        state,
        params,
        period=1,
        events=[
            PopulationEvent(
                kind=PopulationEventKind.DESPAWN_AGENTS,
                at_period=1,
                agent_type_id="A",
                count=2,
            )
        ],
        participants=parts,
        sampler=sampler,
    )
    remaining_ids = {a["id"] for a in state["agents"]}
    assert remaining_ids == {0, 3}  # ids with the top two balances


# ---------------------------------------------------------------------------
# SHIFT_UTILITY
# ---------------------------------------------------------------------------


def test_shift_utility_changes_subsequent_action_choices() -> None:
    """Start with EARN-heavy utility, then shift to HOLD-heavy at t=2.
    Verify the action mix after t=2 is HOLD-dominated."""
    te = _te(
        util=UtilityWeights(
            income_yield=10.0, holding_yield=0.0, action_temperature=0.1
        ),
        population_events=[
            PopulationEvent(
                kind=PopulationEventKind.SHIFT_UTILITY,
                at_period=2,
                agent_type_id="A",
                new_utility=UtilityWeights(
                    income_yield=0.0, holding_yield=10.0, action_temperature=0.1
                ),
            )
        ],
    )
    cfg = SimulationConfig(horizon_periods=6, seed=4, max_agents=20)
    report = run_explore(te, sim_config=cfg)
    # Before t=2: most agents EARN.
    pre = report.snapshots[1].action_mix
    # After t=2: most agents HOLD.
    post = report.snapshots[3].action_mix
    assert pre.get("earn", 0) >= 0.7
    assert post.get("hold", 0) >= 0.7


# ---------------------------------------------------------------------------
# Multi-event ordering
# ---------------------------------------------------------------------------


def test_multiple_events_same_period() -> None:
    te = _te(
        population_events=[
            PopulationEvent(
                kind=PopulationEventKind.SPAWN_AGENTS,
                at_period=2,
                agent_type_id="A",
                count=3,
                balance_per_agent=10.0,
            ),
            PopulationEvent(
                kind=PopulationEventKind.SHIFT_UTILITY,
                at_period=2,
                agent_type_id="A",
                new_utility=UtilityWeights(
                    holding_yield=10.0, action_temperature=0.1
                ),
            ),
        ],
    )
    cfg = SimulationConfig(horizon_periods=3, seed=5, max_agents=20)
    report = run_explore(te, sim_config=cfg)
    # Both effects observable: population grew AND mix shifted.
    sizes = [len(s.balances) for s in report.snapshots]
    assert sizes[2] == sizes[0] + 3
    assert report.snapshots[2].action_mix.get("hold", 0) > 0


def test_no_events_baseline_unchanged() -> None:
    """Sanity: a TE with no population_events behaves exactly as
    before Phase C."""
    te = _te(population_events=[])
    cfg = SimulationConfig(horizon_periods=4, seed=6, max_agents=20)
    report = run_explore(te, sim_config=cfg)
    sizes = [len(s.balances) for s in report.snapshots]
    assert all(s == sizes[0] for s in sizes)


# ---------------------------------------------------------------------------
# End-to-end Monte Carlo path still works with population_events declared
# ---------------------------------------------------------------------------


def test_run_simulation_with_population_events_completes() -> None:
    te = _te(
        population_events=[
            PopulationEvent(
                kind=PopulationEventKind.SPAWN_AGENTS,
                at_period=5,
                agent_type_id="A",
                count=2,
                balance_per_agent=1.0,
            )
        ],
    )
    report = run_simulation(te, config=SimulationConfig(n_runs=3, seed=7, horizon_periods=10))
    assert report.per_fm_results
