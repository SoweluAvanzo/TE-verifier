"""Stochastic agent exit (Phase E1).

Adds a per-period exit roll driven by an agent's scalar utility versus
the population mean. Mirrors the ``p_exit`` rule from the
Domenicale et al. sample but operates on ABM scalar utility derived
from ``balance``, optional ``reputation``, and governance eligibility.

Disabled by default: an agent_type with ``UtilityWeights.exit_propensity``
== 0 (the field's default) is never considered for exit. The engine
short-circuits the whole sweep when no type opts in.

Mechanics, per period (after the action loop, before live aggregates):

  1. For every agent compute ``u_self`` via :func:`agent_scalar_utility`.
  2. ``u_mean`` = simple mean over the active population.
  3. ``gap = max(0, u_mean - u_self)`` — social-comparison shortfall.
  4. ``net = -u_self + δ * gap`` where δ = ``social_comparison_delta``.
  5. ``p_exit = exit_propensity * sigmoid(net)``.
  6. Bernoulli draw decides whether the agent is removed.

Removed agents are dropped from ``state['agents']``. The engine then
rebuilds the neighbor graph and rescales ``state['N']`` so that
downstream FM checks (notably FM5's critical-mass threshold) see the
reduced live population.
"""

from __future__ import annotations

import math
from typing import Any

from schema import AgentType, UtilityWeights
from verifier.abm.samplers import Sampler


def _sigmoid(x: float) -> float:
    """Logistic with overflow guard (mirrors sample's clip-then-exp)."""
    clamped = max(-500.0, min(500.0, x))
    return 1.0 / (1.0 + math.exp(-clamped))


def agent_scalar_utility(
    agent: dict[str, Any], utility: UtilityWeights | None
) -> float:
    """Reduce per-agent state to a single utility scalar for exit
    comparison.

    Approximates the sample's ``U = α·U_econ + β·U_social + γ·U_govern``
    decomposition using existing fields:

    * ``U_econ``   = (income_yield + redemption_value) · balance
    * ``U_social`` = social_payoff · reputation  (zero pre-Phase-E3)
    * ``U_govern`` = governance_payoff · 1[balance > 0]

    When ``utility`` is None (agent type has no weights and no role
    default) the scalar is zero — those agents fall back to behavior
    governed by global propensity (which is also zero when unset).
    """
    if utility is None:
        return 0.0
    balance = float(agent.get("balance", 0.0))
    reputation = float(agent.get("reputation", 0.0))
    u_econ = (utility.income_yield + utility.redemption_value) * balance
    u_social = utility.social_payoff * reputation
    u_govern = utility.governance_payoff * (1.0 if balance > 0 else 0.0)
    return u_econ + u_social + u_govern


def any_exit_enabled(agent_types_by_id: dict[str, AgentType]) -> bool:
    """True iff at least one declared agent type has positive
    ``exit_propensity``. The engine uses this to skip the sweep
    entirely on the common (disabled) path."""
    for at in agent_types_by_id.values():
        uw = at.utility
        if uw is not None and uw.exit_propensity > 0.0:
            return True
    return False


def apply_exit_decisions(
    state: dict[str, Any],
    agent_types_by_id: dict[str, AgentType],
    sampler: Sampler,
) -> int:
    """Run the per-period exit roll and remove agents that leave.

    Mutates ``state['agents']`` in place. Returns the count removed
    so the caller can decide whether to rebuild auxiliary structures
    (neighbor graph, delegate assignments, scaled N). Returns 0 when
    no type opts in or when the agent list is empty.
    """
    agents = state.get("agents") or []
    if not agents:
        return 0
    if not any_exit_enabled(agent_types_by_id):
        return 0

    # First pass: scalar utility per agent (so u_mean reflects the
    # population *before* removals — a fixed reference point per turn).
    utilities: list[float] = []
    for a in agents:
        at = agent_types_by_id.get(a["type"])
        uw = at.utility if at is not None else None
        utilities.append(agent_scalar_utility(a, uw))

    n = len(utilities)
    u_mean = sum(utilities) / n if n > 0 else 0.0

    # Second pass: per-agent Bernoulli decision.
    #
    # The bare ``sigma(net)`` from the sample produces p = 0.5 at the
    # neutral point (u_self == u_mean, net = 0), so even when the entire
    # population sits at identical utility every agent leaves at a 50 %
    # baseline rate. That conflates "everyone equally well off" with
    # "everyone bleeds out". To match the intent — agents leave when
    # their relative position is strictly worse than peers — we rescale:
    #
    #     activation = max(0, 2 · (sigma(net) - 0.5))
    #     p_exit     = exit_propensity · activation
    #
    # Mapping:
    #   sigma(0)   = 0.5  → activation = 0   (at-or-above mean: no exit)
    #   sigma(+∞)  = 1.0  → activation = 1   (max exit when way behind)
    #   sigma(-∞)  = 0.0  → activation = 0   (over-performer: no exit)
    #
    # Preserves the sample's qualitative shape (laggards exit, leaders
    # don't) but kills the spurious baseline that drove the documented
    # FM4-style consumer/lurker depopulation in the time-bank fixture.
    survivors: list[dict[str, Any]] = []
    removed = 0
    for a, u_self in zip(agents, utilities):
        at = agent_types_by_id.get(a["type"])
        uw = at.utility if at is not None else None
        if uw is None or uw.exit_propensity == 0.0:
            survivors.append(a)
            continue
        gap = max(0.0, u_mean - u_self)
        net = -u_self + uw.social_comparison_delta * gap
        activation = max(0.0, 2.0 * (_sigmoid(net) - 0.5))
        p_exit = uw.exit_propensity * activation
        if sampler.rng.random() < p_exit:
            removed += 1
        else:
            survivors.append(a)

    state["agents"] = survivors
    return removed
