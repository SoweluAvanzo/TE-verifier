"""Interaction-graph construction for the ABM (Phase B).

The TE-IR declares a ``Topology`` (WELL_MIXED / SPATIAL / NETWORK) and,
for NETWORK, an optional ``average_degree``. At simulation start the
engine builds an adjacency list from those parameters and threads it
through ``params``. The TRANSFER action then picks a peer from the
agent's neighbor list rather than the full population, producing
genuine network effects (clustering, hub concentration, slower
diffusion).

Three topologies:

  * ``WELL_MIXED`` — every agent is every other agent's neighbor. The
    adjacency list is implicit (None) and the action loop falls back
    to the prior "random peer from anywhere" behavior.
  * ``NETWORK`` — Erdős–Rényi random graph with edge probability
    ``p = avg_degree / (n - 1)``. If ``avg_degree`` is unspecified, we
    fall back to ``log(N)`` (a small-world-ish default).
  * ``SPATIAL`` — agents on a 1-D ring with k-nearest neighbors. The
    radius defaults to ``floor(avg_degree / 2)``. This produces high
    clustering and low diameter, contrasting NETWORK in obvious ways
    in the trade-graph viz.

The graph is built once at run start (seeded from the same sampler so
runs are reproducible). It is fixed for the duration of one trajectory
— births/deaths via Phase C will splice nodes in/out separately.

Why a sparse list (not an adjacency matrix): with up to 200 agents,
n² = 40k edges is fine memory-wise, but iterating to pick a random
neighbor scales linearly in degree, not n, with the list form.
"""

from __future__ import annotations

import math
import random
from typing import Any

from schema import ParticipantsSpec, Topology
from verifier.abm.samplers import Sampler


def build_neighbor_graph(
    participants: ParticipantsSpec,
    agents: list[dict[str, Any]],
    sampler: Sampler,
) -> dict[int, tuple[int, ...]] | None:
    """Return the per-agent neighbor adjacency list.

    Returns ``None`` for WELL_MIXED — the action loop interprets that
    as "no restriction, pick any peer". For NETWORK / SPATIAL, returns
    a dict ``{agent_id: tuple_of_neighbor_ids}``.

    ``agents`` is the already-spawned per-agent state (see
    ``spawn_agents``). The graph uses the agent ``id`` field as node
    identifier so peer lookups are O(1) into a dict.

    Robustness: when fewer than 2 agents are spawned, the graph is
    trivially empty (no transfers possible).
    """
    topology = participants.topology
    n = len(agents)
    if n < 2:
        return {a["id"]: tuple() for a in agents}
    if topology == Topology.WELL_MIXED:
        return None  # action loop falls back to full-peer selection

    avg_degree = _resolve_avg_degree(participants, n, sampler)

    if topology == Topology.SPATIAL:
        return _spatial_ring_graph(agents, avg_degree)
    return _erdos_renyi_graph(agents, avg_degree, sampler.rng)


def _resolve_avg_degree(
    participants: ParticipantsSpec, n: int, sampler: Sampler
) -> float:
    """Compute the effective average degree.

    Order: explicit ``topology_params['average_degree']`` →
    ``log(N)`` fallback for NETWORK / SPATIAL. Capped at n - 1 so we
    never request more neighbors than exist.
    """
    avg_deg_range = participants.topology_params.get("average_degree")
    if avg_deg_range is not None:
        avg_deg = sampler.sample_range(avg_deg_range)
    else:
        # log(N) preserves small-world scaling without ballooning
        # the per-period peer lookup; the same default FM5 uses.
        avg_deg = math.log(max(n, 2))
    return max(1.0, min(float(n - 1), avg_deg))


def _erdos_renyi_graph(
    agents: list[dict[str, Any]],
    avg_degree: float,
    rng: random.Random,
) -> dict[int, tuple[int, ...]]:
    """G(n, p) with ``p = avg_degree / (n - 1)``.

    Each undirected edge is included independently. We materialize
    neighbor lists by iterating pairs; for n ≤ 200 this is cheap
    (≤ ~20k pair checks). For larger n we'd switch to per-node
    sampling, but the agent cap prevents that.
    """
    n = len(agents)
    ids = [a["id"] for a in agents]
    p = avg_degree / max(1, n - 1)
    adjacency: dict[int, list[int]] = {aid: [] for aid in ids}
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < p:
                adjacency[ids[i]].append(ids[j])
                adjacency[ids[j]].append(ids[i])
    return {aid: tuple(neigh) for aid, neigh in adjacency.items()}


def _spatial_ring_graph(
    agents: list[dict[str, Any]],
    avg_degree: float,
) -> dict[int, tuple[int, ...]]:
    """Agents on a 1-D ring; each connects to k nearest neighbors on
    each side. radius = floor(avg_degree / 2)."""
    n = len(agents)
    radius = max(1, int(avg_degree // 2))
    ids = [a["id"] for a in agents]
    adjacency: dict[int, tuple[int, ...]] = {}
    for i in range(n):
        neigh = []
        for r in range(1, radius + 1):
            neigh.append(ids[(i - r) % n])
            neigh.append(ids[(i + r) % n])
        adjacency[ids[i]] = tuple(neigh)
    return adjacency


def graph_density(
    neighbor_graph: dict[int, tuple[int, ...]] | None,
    n_agents: int,
) -> float:
    """Edge density of the static interaction graph. Returns 1.0 for
    WELL_MIXED (None graph), 0.0 for empty graphs."""
    if neighbor_graph is None:
        return 1.0
    if n_agents < 2:
        return 0.0
    # Count directed-edge entries, divide by 2 for undirected, then
    # by max edges.
    edge_count = sum(len(neigh) for neigh in neighbor_graph.values()) / 2.0
    max_edges = n_agents * (n_agents - 1) / 2.0
    return edge_count / max_edges if max_edges > 0 else 0.0
