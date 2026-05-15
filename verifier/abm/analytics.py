"""Live analytics computed from per-agent state.

Functions here are pure (state → number); the engine calls them once
per period to update live aggregates. Three groups:

  • Concentration: Gini coefficient, Lorenz fractions.
  • Participation: φ (live contributor fraction), action mix.
  • Network: trade-graph edge density, top-N hubs.

Kept light and dependency-free so the engine can call them in the
inner per-period loop without slowdown. Heavier analytics (force-
directed layout, community detection) live on the page-rendering
side, not here.
"""

from __future__ import annotations

from typing import Any


def gini(values: list[float]) -> float:
    """Standard Gini coefficient over a list of non-negative values.

    Returns 0.0 for perfectly equal distributions, 1.0 for maximally
    unequal. Handles the degenerate case (empty list, all zeros,
    single element) by returning 0.0.

    Implementation: sorted-cumulative form, O(n log n).
    """
    if not values:
        return 0.0
    cleaned = [max(0.0, v) for v in values]
    total = sum(cleaned)
    if total == 0:
        return 0.0
    sorted_vals = sorted(cleaned)
    n = len(sorted_vals)
    cumulative = 0.0
    for i, v in enumerate(sorted_vals, start=1):
        cumulative += i * v
    # Gini = (2·Σ(i·x_i) − (n+1)·Σx) / (n · Σx)
    return (2.0 * cumulative - (n + 1) * total) / (n * total)


def lorenz_curve(values: list[float], n_points: int = 21) -> list[tuple[float, float]]:
    """Lorenz curve as ``n_points`` (cumulative-population-share,
    cumulative-balance-share) pairs.

    Used by the /explore page to show *where* the concentration sits
    (top 1% holds X%, top 10% holds Y%, etc.). Returns equally-spaced
    population fractions on [0, 1]."""
    if not values:
        return [(0.0, 0.0), (1.0, 0.0)]
    cleaned = sorted(max(0.0, v) for v in values)
    total = sum(cleaned)
    if total == 0:
        return [(i / (n_points - 1), 0.0) for i in range(n_points)]
    n = len(cleaned)
    cumulative_share = [0.0] * (n + 1)
    running = 0.0
    for i, v in enumerate(cleaned, start=1):
        running += v
        cumulative_share[i] = running / total
    out = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        idx = int(round(frac * n))
        out.append((frac, cumulative_share[idx]))
    return out


def contributor_fraction(
    agents: list[dict[str, Any]],
    period: int,
    contributor_action_history_window: int = 8,
) -> float:
    """Live φ: fraction of agents that took an EARN-able action
    recently and have non-zero balance.

    Compared to the static elicitation-derived φ (which is read from
    declared agent roles), this captures actual participation in the
    economy."""
    if not agents:
        return 0.0
    active = 0
    for a in agents:
        if a.get("balance", 0.0) <= 0:
            continue
        # Agent counts as a contributor if they acted in the last K
        # periods. This is a proxy for "actively producing value".
        last = a.get("last_action", 0)
        if period - last <= contributor_action_history_window:
            active += 1
    return active / len(agents)


def action_mix(
    agents: list[dict[str, Any]],
    action_counts_this_period: dict[str, int],
) -> dict[str, float]:
    """Fraction of agents that took each action this period.

    Useful for the page-level "what's the population doing" chart.
    """
    total = sum(action_counts_this_period.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in action_counts_this_period.items()}


def top_hubs(
    trade_edges: dict[tuple[int, int], float], k: int = 10
) -> list[tuple[int, float]]:
    """Return the top-k agent ids by trade-edge weight sum.

    Used to surface the most-connected agents in the trade graph.
    """
    weights: dict[int, float] = {}
    for (a, b), w in trade_edges.items():
        weights[a] = weights.get(a, 0.0) + w
        weights[b] = weights.get(b, 0.0) + w
    return sorted(weights.items(), key=lambda kv: -kv[1])[:k]


def network_density(
    trade_edges: dict[tuple[int, int], float], n_agents: int
) -> float:
    """Edge density of the trade graph — actual edges / possible
    edges. Ranges 0 (no trades) to 1 (everyone-traded-with-everyone).
    """
    if n_agents < 2:
        return 0.0
    max_edges = n_agents * (n_agents - 1) / 2
    return len(trade_edges) / max_edges if max_edges > 0 else 0.0


def mean_reputation(agents: list[dict[str, Any]]) -> float:
    """Population-mean reputation (Phase E3).

    Reputation is a non-negative scalar agents accumulate via EARN /
    VOTE (see ``verifier.abm.actions``). When no agent has been
    spawned with reputation tracking, this returns 0.0.
    """
    if not agents:
        return 0.0
    total = 0.0
    n = 0
    for a in agents:
        total += float(a.get("reputation", 0.0))
        n += 1
    return total / n if n > 0 else 0.0
