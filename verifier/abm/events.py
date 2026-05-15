"""Phase-C population-dynamics events.

The engine fires these at the start of each period (before action
selection) so the event takes effect for the period the user
specified. Each event kind has a focused, idempotent effect:

  • SPAWN_AGENTS    — append ``count`` agents to ``state['agents']``.
                      New agents inherit ``balance_per_agent`` (default
                      0) and the holding_time / role of their type.
                      Neighbor graph and delegate assignments are
                      rebuilt so the new agents can interact.
  • DESPAWN_AGENTS  — remove the ``count`` lowest-balance agents of
                      the named type (real-world attrition).
  • SHIFT_UTILITY   — replace the type's softmax cache with one built
                      from ``new_utility``. Affects every subsequent
                      action selection for that type.

Multiple events at the same period are applied in the order declared.
"""

from __future__ import annotations

from typing import Any

from schema import (
    AgentType,
    ParticipantsSpec,
    PopulationEvent,
    PopulationEventKind,
)
from verifier.abm.actions import build_type_cache, sample_agent_utility_offsets
from verifier.abm.delegation import assign_delegates
from verifier.abm.regimes import is_condition_active
from verifier.abm.samplers import Sampler
from verifier.abm.topology import build_neighbor_graph


def apply_population_events(
    state: dict[str, Any],
    params: dict[str, Any],
    period: int,
    events: list[PopulationEvent],
    participants: ParticipantsSpec,
    sampler: Sampler,
) -> None:
    """Fire every event whose trigger fires this period.

    Two trigger modes:

    * ``at_period`` matches the current period (the Phase-C scheduled
      path).
    * ``conditions`` (non-empty) become true for the first time. We
      track which conditional events have already fired in
      ``params['_pop_event_fired']`` (set of event ids) so each fires
      exactly once.

    Mutates ``state['agents']``, ``params['type_cache_by_id']``,
    ``params['neighbor_graph']`` in place as needed. No-op when no
    events fire this period (the common case)."""
    fired = params.setdefault("_pop_event_fired", set())
    firing: list[PopulationEvent] = []
    for ev in events:
        if ev.at_period is not None and ev.at_period == period:
            firing.append(ev)
        elif ev.conditions:
            eid = id(ev)
            if eid in fired:
                continue
            if all(is_condition_active(c, state) for c in ev.conditions):
                fired.add(eid)
                firing.append(ev)
    if not firing:
        return

    agent_types_by_id = params.get("agent_types_by_id", {})
    type_cache_by_id = params.get("type_cache_by_id", {})

    population_changed = False
    for ev in firing:
        if ev.kind == PopulationEventKind.SHIFT_UTILITY:
            _shift_utility(ev, agent_types_by_id, type_cache_by_id)
        elif ev.kind == PopulationEventKind.SPAWN_AGENTS:
            _spawn_event(ev, state, agent_types_by_id, sampler, period)
            population_changed = True
        elif ev.kind == PopulationEventKind.DESPAWN_AGENTS:
            _despawn_event(ev, state)
            population_changed = True

    if population_changed:
        # Rebuild interaction graph + delegate assignments so the new
        # population sees consistent topology going forward.
        params["neighbor_graph"] = build_neighbor_graph(
            participants, state["agents"], sampler
        )
        assign_delegates(
            state["agents"],
            params.get("vote_weighting"),
            sampler,
        )


def _shift_utility(
    event: PopulationEvent,
    agent_types_by_id: dict[str, AgentType],
    type_cache_by_id: dict[str, dict[str, Any]],
) -> None:
    """Replace the cached softmax data for ``event.agent_type_id``.

    Because ``AgentType`` is a frozen pydantic model, we construct a
    transient AgentType with the new utility, then build a fresh cache
    from it. The original schema object is left untouched (the next
    run will start from the declared utility again).
    """
    if event.new_utility is None:
        return
    ag_type = agent_types_by_id.get(event.agent_type_id)
    if ag_type is None:
        return
    transient = ag_type.model_copy(update={"utility": event.new_utility})
    type_cache_by_id[event.agent_type_id] = build_type_cache(transient)


def _spawn_event(
    event: PopulationEvent,
    state: dict[str, Any],
    agent_types_by_id: dict[str, AgentType],
    sampler: Sampler,
    period: int,
) -> None:
    count = max(0, event.count or 0)
    if count == 0:
        return
    ag_type = agent_types_by_id.get(event.agent_type_id)
    if ag_type is None:
        return
    agents = state.setdefault("agents", [])
    # Continue id allocation past the current max so analytics and
    # the explore-page node ids stay unique.
    next_id = max((a["id"] for a in agents), default=-1) + 1
    balance = float(event.balance_per_agent or 0.0)
    for _ in range(count):
        agent = {
            "id": next_id,
            "type": ag_type.id,
            "balance": balance,
            "holding_time": sampler.sample_range(
                ag_type.expected_holding_time.expected_periods
            ),
            "last_action": period,
            # Phase E3: mid-run spawns start with zero reputation,
            # symmetric with agents created at simulation start.
            "reputation": 0.0,
        }
        # Phase E2: mid-run spawned agents inherit the type's jitter
        # spec, just like agents created at simulation start.
        offsets = sample_agent_utility_offsets(ag_type, sampler)
        if offsets is not None:
            agent.update(offsets)
        agents.append(agent)
        next_id += 1


def _despawn_event(event: PopulationEvent, state: dict[str, Any]) -> None:
    count = max(0, event.count or 0)
    if count == 0:
        return
    agents = state.get("agents", []) or []
    # Filter to the targeted type, sort ascending by balance, mark the
    # lowest-N for removal. Stable identity via id.
    targeted = [a for a in agents if a["type"] == event.agent_type_id]
    if not targeted:
        return
    targeted.sort(key=lambda a: a.get("balance", 0.0))
    to_remove = {a["id"] for a in targeted[:count]}
    state["agents"] = [a for a in agents if a["id"] not in to_remove]
