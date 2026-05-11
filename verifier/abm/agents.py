"""Per-agent state for the reference ABM.

Three changes vs. the aggregate-only v0:

1. ``state["agents"]`` is a list of per-agent dicts (id, type, balance,
   holding_time, last_action_period). Initialized from
   ``participants.agent_types`` proportionally.
2. Per-period: each agent's clock advances. When (period - last_action)
   exceeds their drawn holding_time, the agent "acts" (resets the
   clock). This generates a live trajectory of holding times rather
   than a constant value.
3. ``tau_bar`` becomes a live computation from per-agent state rather
   than a once-per-run aggregate. Time-evolving FM2 risk now surfaces.

The cap on simulated agents is a tractability decision: at most
``MAX_AGENTS`` regardless of declared ``count_N``. The cap doesn't
distort tau_bar because the per-type fractions are preserved; it
just bounds the per-period work.

Future extensions documented in ``docs/abm-bridge.md`` — trading
between agents (live Gini evolution), utility-driven action choice
(replace clock with payoff-comparing decisions), spawn/death dynamics
(agents arriving/leaving per growth_g).
"""

from __future__ import annotations

from typing import Any

from schema import TokenEconomy
from verifier.abm.samplers import Sampler


# Cap the simulated agent population for tractability. The cap is
# preserved across type proportions, so tau_bar weighting is faithful.
# Set low enough that the inner loop stays fast across many runs.
# Power users override by passing skip_non_fragile=False or simulating
# fewer FMs at a time.
MAX_AGENTS = 200


def spawn_agents(
    te: TokenEconomy,
    sampler: Sampler,
) -> list[dict[str, Any]]:
    """Create per-agent instances from agent_types proportionally.

    Each agent is a flat dict so it survives JSON round-trip through
    cadCAD-style state. Per-type ``balance_share`` (when present) is
    divided across that type's agents; otherwise share follows
    fraction.
    """
    if not te.participants.agent_types:
        return []
    # Cap N for tractability — preserve type proportions.
    n_target = min(MAX_AGENTS, max(1, int(round(_n_estimate(te)))))
    agents: list[dict[str, Any]] = []
    aid = 0
    for ag_type in te.participants.agent_types:
        n_this_type = max(1, int(round(n_target * ag_type.fraction)))
        share = (
            ag_type.balance_share
            if ag_type.balance_share is not None
            else ag_type.fraction
        )
        balance_per_agent = share / max(n_this_type, 1)
        for _ in range(n_this_type):
            agents.append(
                {
                    "id": aid,
                    "type": ag_type.id,
                    "balance": balance_per_agent,
                    "holding_time": sampler.sample_range(
                        ag_type.expected_holding_time.expected_periods
                    ),
                    "last_action": 0,
                }
            )
            aid += 1
    return agents


def _n_estimate(te: TokenEconomy) -> float:
    """Midpoint-like estimate of N for agent spawn count.

    The actual sampled N for the run can be much larger than the cap;
    using the midpoint here just lets us preserve type proportions
    without ballooning the agent count.
    """
    return (te.participants.count_N.min + te.participants.count_N.max) / 2.0


def step_agents(
    agents: list[dict[str, Any]],
    period: int,
) -> None:
    """Advance one period. Each agent whose held time ≥ holding_time
    "acts" — resets the clock. Mutates the list in place (cadCAD-style)."""
    for agent in agents:
        held_for = period - agent["last_action"]
        if held_for >= agent["holding_time"]:
            agent["last_action"] = period


def tau_bar_from_agents(
    agents: list[dict[str, Any]],
    period: int,
    fallback: float = 0.0,
) -> float:
    """Balance-weighted average of (period - last_action), per agent.

    Falls back to ``fallback`` (typically the static aggregate value)
    when agent list is empty or zero-balance.
    """
    if not agents:
        return fallback
    total_balance = sum(a["balance"] for a in agents)
    if total_balance <= 0:
        return fallback
    weighted = sum(
        a["balance"] * max(0, period - a["last_action"]) for a in agents
    )
    return weighted / total_balance
