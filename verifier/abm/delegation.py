"""Delegation model for the Phase-B ABM.

When ``governance.vote_weighting == DELEGATED``, token holders don't
vote directly — they delegate their stake to a smaller set of
"delegates", who then cast aggregate votes on their behalf. The
effective concentration of *governance* power is over delegates, not
over raw token holders.

This module:
  • assigns each agent a delegate at spawn time (``assign_delegates``),
  • aggregates per-agent VOTE weights onto delegates per period,
  • computes the live delegate-concentration Gini, which the /explore
    page surfaces alongside the token-balance Gini.

Delegate selection is the load-bearing modeling choice. We use a
"top-K by initial balance" heuristic: the K wealthiest agents at spawn
become delegates; everyone else delegates to one of them uniformly at
random. K defaults to ``max(3, sqrt(N))`` — empirical sweet spot from
real DAOs (Compound, Uniswap have ~50-200 active delegates over
thousands of holders).

For non-DELEGATED weightings, each agent delegates to themselves (so
the VOTE pathway reduces to direct token-weighted voting).
"""

from __future__ import annotations

import math
from typing import Any

from schema import VoteWeighting
from verifier.abm.samplers import Sampler


def assign_delegates(
    agents: list[dict[str, Any]],
    vote_weighting: VoteWeighting,
    sampler: Sampler,
) -> None:
    """Add a ``delegate_of`` field to each agent in place.

    For ``DELEGATED`` weighting: select top-K wealthiest agents at
    spawn as delegates; everyone else picks one of them uniformly.
    Top-K agents delegate to themselves.

    For all other weightings: each agent delegates to itself (vote
    weight is self-directed).
    """
    if not agents:
        return
    if vote_weighting != VoteWeighting.DELEGATED:
        for a in agents:
            a["delegate_of"] = a["id"]
        return

    n = len(agents)
    k = max(3, int(round(math.sqrt(n))))
    k = min(k, n)
    sorted_by_balance = sorted(agents, key=lambda a: -a.get("balance", 0.0))
    delegates = [a["id"] for a in sorted_by_balance[:k]]
    delegate_set = set(delegates)
    for a in agents:
        if a["id"] in delegate_set:
            a["delegate_of"] = a["id"]
        else:
            a["delegate_of"] = sampler.rng.choice(delegates)


def delegated_weights(
    agents: list[dict[str, Any]],
) -> dict[int, float]:
    """Aggregate token balance under each delegate.

    Returns ``{delegate_id: total_balance_delegated_to_them}``. Used by
    the /explore page (Phase D) to render delegate concentration and
    by ``delegate_concentration_gini`` to summarize it.
    """
    weights: dict[int, float] = {}
    for a in agents:
        delegate = a.get("delegate_of", a["id"])
        weights[delegate] = weights.get(delegate, 0.0) + a.get("balance", 0.0)
    return weights


def delegate_concentration_gini(agents: list[dict[str, Any]]) -> float:
    """Gini over the population's *effective voting power*.

    Effective voting power per agent:
      • delegate → sum of all tokens delegated to them (incl. their own),
      • non-delegate → 0 (their voice is fully captured by the delegate).

    This matches how on-chain DAOs (Compound, Uniswap) actually behave:
    a non-delegating holder casts no vote of their own. Measuring Gini
    only over the delegate subset would understate concentration — the
    bottom-of-distribution zeros are load-bearing for the "governance is
    concentrated" claim. Returns 0 for empty / zero-balance populations.
    """
    from verifier.abm.analytics import gini

    if not agents:
        return 0.0
    weights = delegated_weights(agents)
    power_per_agent = [weights.get(a["id"], 0.0) for a in agents]
    return gini(power_per_agent)


def top_delegates(
    agents: list[dict[str, Any]], k: int = 10
) -> list[tuple[int, float]]:
    """Return the top-k delegates by aggregated balance.

    Useful for the /explore page's delegate-concentration panel.
    """
    weights = delegated_weights(agents)
    return sorted(weights.items(), key=lambda kv: -kv[1])[:k]
