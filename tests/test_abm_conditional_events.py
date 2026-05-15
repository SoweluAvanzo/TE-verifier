"""Phase-F: condition-triggered PopulationEvents (despawn / spawn /
utility shift fired when state predicates first satisfy)."""

from __future__ import annotations

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
    PopulationEvent,
    PopulationEventKind,
    Rule,
    RuleTrigger,
    ThresholdCondition,
    ThresholdOp,
    ThresholdVar,
    TimeWindow,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
    UtilityWeights,
)
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.samplers import Sampler


def _te(events):
    return TokenEconomy(
        meta=Meta(name="cond-evt-test", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[Rule(
                trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                function=FunctionShape(
                    sign=FunctionSign.ALWAYS_POSITIVE,
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(50.0)},
                    ),
                ),
            )],
            burn_rules=[Rule(
                trigger=RuleTrigger(kind=BurnTriggerKind.DEMAND_DRIVEN),
                function=FunctionShape(
                    sign=FunctionSign.ALWAYS_NEGATIVE,
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(0.0)},
                    ),
                ),
            )],
            offer_variety_K=NumberRange.point(5),
        )],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(20),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[AgentType(
                id="A", fraction=1.0, balance_share=1.0,
                role=AgentRole.CONTRIBUTOR,
                utility=UtilityWeights(income_yield=1.0, action_temperature=0.5),
                action_set=[ActionKind.EARN, ActionKind.HOLD],
                expected_holding_time=HoldingTimeDistribution(
                    expected_periods=NumberRange.point(5)
                ),
            )],
            population_events=events,
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )


# ---------------------------------------------------------------------------
# Schema: at_period OR conditions required.
# ---------------------------------------------------------------------------


def test_schema_rejects_event_without_trigger() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PopulationEvent(
            kind=PopulationEventKind.SPAWN_AGENTS,
            agent_type_id="A",
            count=1,
        )


def test_schema_accepts_event_with_conditions_only() -> None:
    ev = PopulationEvent(
        kind=PopulationEventKind.SPAWN_AGENTS,
        agent_type_id="A",
        count=1,
        conditions=[TimeWindow(start_period=5)],
    )
    assert ev.at_period is None
    assert len(ev.conditions) == 1


# ---------------------------------------------------------------------------
# Conditional spawn fires when threshold met.
# ---------------------------------------------------------------------------


def test_threshold_triggered_spawn() -> None:
    """SPAWN fires when M crosses a threshold."""
    ev = PopulationEvent(
        kind=PopulationEventKind.SPAWN_AGENTS,
        agent_type_id="A",
        count=10,
        balance_per_agent=0.0,
        conditions=[ThresholdCondition(
            var=ThresholdVar.M, op=ThresholdOp.GTE, value=120.0,
        )],
    )
    te = _te([ev])
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=30)
    from verifier.abm.agents import spawn_agents
    state["agents"] = spawn_agents(te, sampler, max_agents=30)
    initial = len(state["agents"])
    # Run until M crosses 120 (emission 50/period * agents-driven).
    for _ in range(15):
        state = _step_state(state, params)
        if len(state["agents"]) > initial:
            break
    assert len(state["agents"]) == initial + 10


def test_conditional_event_fires_only_once() -> None:
    """Even if the predicate stays true, the event fires once."""
    ev = PopulationEvent(
        kind=PopulationEventKind.SPAWN_AGENTS,
        agent_type_id="A",
        count=2,
        balance_per_agent=0.0,
        conditions=[TimeWindow(start_period=2)],
    )
    te = _te([ev])
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=30)
    from verifier.abm.agents import spawn_agents
    state["agents"] = spawn_agents(te, sampler, max_agents=30)
    before = len(state["agents"])
    for _ in range(10):
        state = _step_state(state, params)
    # Exactly one firing → +2 agents.
    assert len(state["agents"]) == before + 2


def test_at_period_path_still_works() -> None:
    """Phase-C backward compatibility: at_period-only events still fire."""
    ev = PopulationEvent(
        kind=PopulationEventKind.SPAWN_AGENTS,
        agent_type_id="A",
        at_period=3,
        count=5,
        balance_per_agent=0.0,
    )
    te = _te([ev])
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=30)
    from verifier.abm.agents import spawn_agents
    state["agents"] = spawn_agents(te, sampler, max_agents=30)
    before = len(state["agents"])
    for _ in range(5):
        state = _step_state(state, params)
    assert len(state["agents"]) == before + 5
