"""Agent action loop for the ABM.

Per period, each agent picks one action from its ``action_set`` via
softmax over per-action utilities. The action then mutates state
(agent balance, token supply, pool draws). This module:

  * Scores actions per agent (``score_action``).
  * Samples a choice via softmax (``pick_action``).
  * Executes the action and mutates state (``execute_action``).
  * Computes live aggregates from per-agent state (``live_aggregates``).

Utility model
-------------

Each ``ActionKind`` is scored as a weighted sum of factors that map
to the user's ``UtilityWeights``. The mapping is:

    HOLD     ← holding_yield × (current_period − last_action)
                + risk_aversion × (1 - balance_volatility)
    EARN     ← income_yield × pool_share_estimate
    TRANSFER ← social_payoff × neighbor_count_estimate
                − risk_aversion × transfer_volatility
    REDEEM   ← redemption_value × good_preference_avg
                + holding_yield × (negative — opportunity cost)
    STAKE    ← holding_yield × declared_lock_yield_estimate
                + risk_aversion × stake_safety
    VOTE     ← governance_payoff × (1 if agent has balance else 0)

The action_temperature on UtilityWeights controls the softmax sharpness:
β = 1 / action_temperature. Higher temperature → more random; lower →
more deterministic (always pick highest-utility action).

Pool model
----------

Emission and burn rules in the IR declare per-period *target* rates.
Those rates become the size of two pools the action loop draws from:

  * ``E_pool[token]`` — tokens that will be minted this period,
    distributed across agents that pick ``EARN`` and are eligible
    (i.e. EARN is in their action_set).
  * ``B_pool[token]`` — tokens that will be burned this period,
    drawn from agents who pick ``REDEEM`` and have balance.

When the agent population's chosen actions are insufficient to consume
the full pool, the rule's *realized* rate falls below its *target*
rate — emergent under-issuance / under-burning. This is the load-
bearing modeling decision: rules define target capacities, agents
realize them.
"""

from __future__ import annotations

import math
from typing import Any

from schema import (
    ActionKind,
    AgentRole,
    DEFAULT_ACTION_SET_BY_ROLE,
    Token,
    TokenEconomy,
    UtilityJitter,
    UtilityWeights,
)
from verifier.abm.samplers import Sampler


# Default utility weights per role. Used when AgentType.utility is None
# (the common case for v1 IRs). These calibrations preserve sane
# behavior on the case studies — a CONTRIBUTOR strongly favors EARN,
# a CONSUMER favors REDEEM, etc.
DEFAULT_UTILITY_BY_ROLE: dict[str, dict[str, float]] = {
    AgentRole.CONTRIBUTOR.value: {
        "income_yield": 1.0,
        "holding_yield": 0.3,
        "redemption_value": 0.1,
        "governance_payoff": 0.2,
        "social_payoff": 0.1,
        "risk_aversion": 0.1,
    },
    AgentRole.CONSUMER.value: {
        "income_yield": 0.1,
        "holding_yield": 0.2,
        "redemption_value": 1.0,
        "governance_payoff": 0.0,
        "social_payoff": 0.3,
        "risk_aversion": 0.1,
    },
    AgentRole.GOVERNANCE_ONLY.value: {
        "income_yield": 0.0,
        "holding_yield": 0.5,
        "redemption_value": 0.0,
        "governance_payoff": 1.0,
        "social_payoff": 0.1,
        "risk_aversion": 0.2,
    },
    AgentRole.OBSERVER.value: {
        "income_yield": 0.0,
        "holding_yield": 0.3,
        "redemption_value": 0.1,
        "governance_payoff": 0.0,
        "social_payoff": 0.1,
        "risk_aversion": 1.0,
    },
    AgentRole.UNSPECIFIED.value: {
        "income_yield": 0.25,
        "holding_yield": 0.25,
        "redemption_value": 0.25,
        "governance_payoff": 0.25,
        "social_payoff": 0.0,
        "risk_aversion": 0.1,
    },
}


def resolve_action_set(agent_type) -> list[ActionKind]:
    """Get the action_set for an agent type, falling back to role-based
    defaults when not declared."""
    if agent_type.action_set:
        return list(agent_type.action_set)
    if agent_type.role is not None:
        return list(DEFAULT_ACTION_SET_BY_ROLE.get(
            agent_type.role.value,
            DEFAULT_ACTION_SET_BY_ROLE[AgentRole.UNSPECIFIED.value],
        ))
    return list(DEFAULT_ACTION_SET_BY_ROLE[AgentRole.UNSPECIFIED.value])


def resolve_utility(agent_type) -> dict[str, float]:
    """Get UtilityWeights for an agent type as a plain dict.

    Falls back to role-based defaults when no utility is declared.
    Returns a flat dict so the scorer doesn't need to know whether
    UtilityWeights is set or not.
    """
    if agent_type.utility is not None:
        # AgentType.utility is a Pydantic UtilityWeights — convert to dict.
        return {
            "income_yield": agent_type.utility.income_yield,
            "holding_yield": agent_type.utility.holding_yield,
            "redemption_value": agent_type.utility.redemption_value,
            "governance_payoff": agent_type.utility.governance_payoff,
            "social_payoff": agent_type.utility.social_payoff,
            "risk_aversion": agent_type.utility.risk_aversion,
            "action_temperature": agent_type.utility.action_temperature,
            # Phase E3: reputation parameters carried through so the
            # cache builder can read them.
            "reputation_yield": agent_type.utility.reputation_yield,
            "reputation_decay": agent_type.utility.reputation_decay,
        }
    if agent_type.role is not None:
        w = dict(DEFAULT_UTILITY_BY_ROLE.get(
            agent_type.role.value,
            DEFAULT_UTILITY_BY_ROLE[AgentRole.UNSPECIFIED.value],
        ))
        w["action_temperature"] = 1.0
        w["reputation_yield"] = 0.0
        w["reputation_decay"] = 0.0
        return w
    w = dict(DEFAULT_UTILITY_BY_ROLE[AgentRole.UNSPECIFIED.value])
    w["action_temperature"] = 1.0
    w["reputation_yield"] = 0.0
    w["reputation_decay"] = 0.0
    return w


def build_type_cache(agent_type) -> dict[str, Any]:
    """Pre-resolve everything pick_action needs into a hot-path-ready
    dict. Built once per agent-type per run; per-period dispatch is
    pure tuple-walking + arithmetic.

    Returned shape::

        {
          "actions":    tuple[ActionKind, ...],            # ordered
          "n":          int,                                # len(actions)
          "weights":    tuple[float, ...],                  # per-action base
                                                            # utility coefficient
          "balance_dep":tuple[bool, ...],                   # action requires
                                                            # nonzero balance
          "is_hold":    tuple[bool, ...],                   # action == HOLD
          "beta":       float,                              # 1/temperature
        }

    The per-action ``weights[i]`` × held-for-multiplier (for HOLD) gives
    the score before softmax. Keeping this as parallel tuples means the
    inner loop is dict-free.
    """
    actions = tuple(resolve_action_set(agent_type))
    u = resolve_utility(agent_type)
    iy = u.get("income_yield", 0.0)
    hy = u.get("holding_yield", 0.0)
    rv = u.get("redemption_value", 0.0)
    gp = u.get("governance_payoff", 0.0)
    sp = u.get("social_payoff", 0.0)
    ra = u.get("risk_aversion", 0.0)
    temperature = max(0.01, u.get("action_temperature", 1.0))
    beta = 1.0 / temperature
    # Phase E3: reputation utility scales HOLD and EARN. Zero by
    # default — no behavioral effect. Decay is consumed by the engine
    # tick, not the cache.
    reputation_yield = u.get("reputation_yield", 0.0)
    reputation_decay = u.get("reputation_decay", 0.0)

    weights = []
    balance_dep = []
    is_hold = []
    is_reputation_bonus = []
    for a in actions:
        if a == ActionKind.HOLD:
            # HOLD score uses (holding_yield * (1 + 0.01*held_for) +
            # 0.5 * risk_aversion). We store coefficients for the
            # held-for-dependent and held-for-independent parts.
            weights.append(hy + 0.5 * ra)
        elif a == ActionKind.EARN:
            weights.append(iy)
        elif a == ActionKind.TRANSFER:
            weights.append(sp)
        elif a == ActionKind.REDEEM:
            weights.append(rv)
        elif a == ActionKind.STAKE:
            weights.append(0.8 * hy + 0.3 * ra)
        elif a == ActionKind.VOTE:
            weights.append(gp)
        else:
            weights.append(0.0)
        balance_dep.append(
            a in (ActionKind.TRANSFER, ActionKind.REDEEM, ActionKind.VOTE)
        )
        is_hold.append(a == ActionKind.HOLD)
        is_reputation_bonus.append(a in (ActionKind.HOLD, ActionKind.EARN))

    # Pre-compute the "no-balance score" — what the agent gets when its
    # balance is zero (most balance-dependent actions degrade to ×0.05).
    no_balance_weights = []
    for a, w in zip(actions, weights):
        if a == ActionKind.TRANSFER:
            no_balance_weights.append(sp * 0.05)
        elif a == ActionKind.REDEEM:
            no_balance_weights.append(rv * 0.05)
        elif a == ActionKind.VOTE:
            no_balance_weights.append(gp * 0.1)
        else:
            no_balance_weights.append(w)
    # Extra ``hold_increment`` term lets HOLD score grow with held-for
    # period. Held-for-multiplier coefficient is 0.01 × holding_yield.
    hy_held = 0.01 * hy
    return {
        "actions": actions,
        "n": len(actions),
        "weights": tuple(weights),
        "no_balance_weights": tuple(no_balance_weights),
        "balance_dep": tuple(balance_dep),
        "is_hold": tuple(is_hold),
        "is_reputation_bonus": tuple(is_reputation_bonus),
        "hy_held": hy_held,
        "beta": beta,
        "reputation_yield": reputation_yield,
        "reputation_decay": reputation_decay,
    }


def sample_agent_utility_offsets(
    agent_type,
    sampler: Sampler,
) -> dict[str, Any] | None:
    """Draw per-agent utility offsets from ``agent_type.utility_jitter``.

    Returns a dict suitable for splatting into an agent state dict —
    keys ``utility_offsets``, ``utility_offsets_no_balance``,
    ``hy_held_offset``. Returns None when the type has no jitter
    (the no-op fast path for pre-Phase-E2 agents).

    Offsets are derived from per-component Gaussian draws and then
    mapped to per-action offsets through the same arithmetic used by
    :func:`build_type_cache`: HOLD = hy + 0.5·ra, STAKE = 0.8·hy +
    0.3·ra, TRANSFER no-balance = sp · 0.05, etc. Keeping the mapping
    in lockstep with the cache means a per-agent draw of zero (sigma
    = 0) is exactly equivalent to the un-jittered baseline.
    """
    jitter = getattr(agent_type, "utility_jitter", None)
    if jitter is None:
        return None
    if (
        jitter.income_yield == 0.0
        and jitter.holding_yield == 0.0
        and jitter.redemption_value == 0.0
        and jitter.governance_payoff == 0.0
        and jitter.social_payoff == 0.0
        and jitter.risk_aversion == 0.0
    ):
        return None

    rng = sampler.rng
    off_iy = rng.gauss(0.0, jitter.income_yield) if jitter.income_yield > 0 else 0.0
    off_hy = rng.gauss(0.0, jitter.holding_yield) if jitter.holding_yield > 0 else 0.0
    off_rv = rng.gauss(0.0, jitter.redemption_value) if jitter.redemption_value > 0 else 0.0
    off_gp = rng.gauss(0.0, jitter.governance_payoff) if jitter.governance_payoff > 0 else 0.0
    off_sp = rng.gauss(0.0, jitter.social_payoff) if jitter.social_payoff > 0 else 0.0
    off_ra = rng.gauss(0.0, jitter.risk_aversion) if jitter.risk_aversion > 0 else 0.0

    actions = tuple(resolve_action_set(agent_type))
    weight_offsets: list[float] = []
    no_bal_offsets: list[float] = []
    for a in actions:
        if a == ActionKind.HOLD:
            w = off_hy + 0.5 * off_ra
            weight_offsets.append(w)
            no_bal_offsets.append(w)
        elif a == ActionKind.EARN:
            weight_offsets.append(off_iy)
            no_bal_offsets.append(off_iy)
        elif a == ActionKind.TRANSFER:
            weight_offsets.append(off_sp)
            no_bal_offsets.append(off_sp * 0.05)
        elif a == ActionKind.REDEEM:
            weight_offsets.append(off_rv)
            no_bal_offsets.append(off_rv * 0.05)
        elif a == ActionKind.STAKE:
            w = 0.8 * off_hy + 0.3 * off_ra
            weight_offsets.append(w)
            no_bal_offsets.append(w)
        elif a == ActionKind.VOTE:
            weight_offsets.append(off_gp)
            no_bal_offsets.append(off_gp * 0.1)
        else:
            weight_offsets.append(0.0)
            no_bal_offsets.append(0.0)

    return {
        "utility_offsets": tuple(weight_offsets),
        "utility_offsets_no_balance": tuple(no_bal_offsets),
        "hy_held_offset": 0.01 * off_hy,
    }


def pick_action_cached(
    agent: dict[str, Any],
    cache: dict[str, Any],
    sampler: Sampler,
    period: int,
) -> ActionKind:
    """Hot-path action sampler.

    Uses precomputed per-type cache (see ``build_type_cache``) to avoid
    re-resolving the agent type's action set + utility every period.
    The per-agent inner loop is now:

      • read cache fields (O(1))
      • build a scores tuple (O(n_actions))
      • softmax + cumulative sample (O(n_actions))

    For n_actions ≤ 6 this is ~50× faster than the dict-based
    ``pick_action`` and is the path the engine uses.

    Phase E2: when ``agent['utility_offsets']`` is present (a tuple of
    per-action offsets sampled once at spawn from
    :class:`UtilityJitter`), those values are added to the type-level
    ``weights`` so each agent in the cohort behaves slightly
    differently. The cache stays per-type — offsets are per-agent.
    """
    actions = cache["actions"]
    n = cache["n"]
    if n == 0:
        return ActionKind.HOLD
    weights = cache["weights"]
    no_balance_weights = cache["no_balance_weights"]
    is_hold = cache["is_hold"]
    balance_dep = cache["balance_dep"]
    is_reputation_bonus = cache.get("is_reputation_bonus")
    hy_held = cache["hy_held"]
    beta = cache["beta"]
    reputation_yield = cache.get("reputation_yield", 0.0)

    balance = agent.get("balance", 0.0)
    has_balance = balance > 0
    held_for = period - agent.get("last_action", 0)
    if held_for < 0:
        held_for = 0

    # Phase E2: per-agent jitter offsets. Default to empty tuples — the
    # `if` checks below stay branch-free in the common (no-jitter) case
    # because the loop body re-uses the cached weight directly.
    weight_offsets = agent.get("utility_offsets")
    no_balance_offsets = agent.get("utility_offsets_no_balance")
    hy_held_offset = agent.get("hy_held_offset", 0.0)

    # Phase E3: reputation utility bonus (concave in agent reputation).
    # Computed once per agent per period; applied to HOLD and EARN
    # scores below via ``is_reputation_bonus``.
    rep_bonus = 0.0
    if reputation_yield > 0.0:
        reputation = agent.get("reputation", 0.0)
        if reputation > 0.0:
            rep_bonus = reputation_yield * math.log1p(reputation)

    # Build score tuple.
    scores = [0.0] * n
    max_score = -1.0
    for i in range(n):
        if is_hold[i]:
            s = weights[i] + (hy_held + hy_held_offset) * held_for
            if weight_offsets is not None:
                s += weight_offsets[i]
        elif balance_dep[i] and not has_balance:
            s = no_balance_weights[i]
            if no_balance_offsets is not None:
                s += no_balance_offsets[i]
        else:
            s = weights[i]
            if weight_offsets is not None:
                s += weight_offsets[i]
        if is_reputation_bonus is not None and is_reputation_bonus[i]:
            s += rep_bonus
        scores[i] = s
        if s > max_score:
            max_score = s

    # Stable softmax.
    total = 0.0
    exps = [0.0] * n
    for i in range(n):
        e = math.exp(beta * (scores[i] - max_score))
        exps[i] = e
        total += e
    if total == 0.0:
        return sampler.rng.choice(actions)
    r = sampler.rng.random() * total
    cum = 0.0
    for i in range(n):
        cum += exps[i]
        if r <= cum:
            return actions[i]
    return actions[n - 1]


# ---------------------------------------------------------------------------
# Per-action utility scoring
# ---------------------------------------------------------------------------


def score_action(
    action: ActionKind,
    agent: dict[str, Any],
    utility: dict[str, float],
    state: dict[str, Any],
    period: int,
) -> float:
    """Return a real-valued utility for the agent taking ``action`` now.

    The score combines weighted utility components — see module
    docstring for the per-action mapping. Always returns a finite
    non-negative value before softmax (action_temperature handles
    selection sharpness; individual scores are kept positive to
    avoid degenerate softmax behavior).
    """
    held_for = max(0, period - agent.get("last_action", 0))
    balance = agent.get("balance", 0.0)

    if action == ActionKind.HOLD:
        return (
            utility.get("holding_yield", 0.0) * (1.0 + 0.01 * held_for)
            + utility.get("risk_aversion", 0.0) * 0.5
        )
    if action == ActionKind.EARN:
        # Income from earning. The actual share depends on how many
        # other agents also pick EARN this period; we approximate with
        # a constant attractor weighted by income_yield.
        return utility.get("income_yield", 0.0) * 1.0
    if action == ActionKind.TRANSFER:
        # Transferring requires balance to move. Score reflects
        # social-payoff weighted by remaining balance.
        return (
            utility.get("social_payoff", 0.0)
            * (1.0 if balance > 0 else 0.05)
        )
    if action == ActionKind.REDEEM:
        # Redemption requires balance and is sized by the redemption
        # value weight. Holding-yield penalizes spending (opportunity
        # cost of giving up future yield).
        return (
            utility.get("redemption_value", 0.0)
            * (1.0 if balance > 0 else 0.05)
        )
    if action == ActionKind.STAKE:
        return (
            utility.get("holding_yield", 0.0) * 0.8
            + utility.get("risk_aversion", 0.0) * 0.3
        )
    if action == ActionKind.VOTE:
        return utility.get("governance_payoff", 0.0) * (
            1.0 if balance > 0 else 0.1
        )
    return 0.0


# ---------------------------------------------------------------------------
# Softmax action selection
# ---------------------------------------------------------------------------


def pick_action(
    agent: dict[str, Any],
    agent_type,
    state: dict[str, Any],
    sampler: Sampler,
    period: int,
) -> ActionKind:
    """Softmax-sample one action from this agent's allowed set.

    ``β = 1 / action_temperature``. As ``action_temperature → 0``,
    selection becomes deterministic (always argmax); as it grows
    larger, selection approaches uniform.
    """
    actions = resolve_action_set(agent_type)
    if not actions:
        return ActionKind.HOLD
    utility = resolve_utility(agent_type)
    temperature = max(0.01, utility.get("action_temperature", 1.0))
    beta = 1.0 / temperature

    scores = [score_action(a, agent, utility, state, period) for a in actions]
    # Stable softmax: subtract max before exp.
    max_score = max(scores)
    exps = [math.exp(beta * (s - max_score)) for s in scores]
    total = sum(exps)
    if total == 0.0:
        return sampler.rng.choice(actions)
    probs = [e / total for e in exps]
    # Sample.
    r = sampler.rng.random()
    cum = 0.0
    for action, p in zip(actions, probs):
        cum += p
        if r <= cum:
            return action
    return actions[-1]


# ---------------------------------------------------------------------------
# Phase E3 — reputation accumulation and decay
# ---------------------------------------------------------------------------

# Per-action reputation gain. EARN and VOTE are the contribution-style
# actions in the ABM; HOLD/TRANSFER/REDEEM/STAKE don't accrue
# reputation. Tunable here rather than via UtilityWeights to keep the
# schema compact — these are population-level constants, not per-type.
REPUTATION_GAIN_EARN = 1.0
REPUTATION_GAIN_VOTE = 0.5


def apply_reputation_decay(
    agents: list[dict[str, Any]],
    type_cache_by_id: dict[str, dict[str, Any]],
) -> None:
    """Multiplicatively decay each agent's reputation in place.

    Per-type decay rate is read from the type cache (built once from
    ``UtilityWeights.reputation_decay``). Decay of 0 leaves reputation
    unchanged; decay of 1 wipes it every period. Agents without a
    reputation field are skipped — they have no state to decay.
    """
    for agent in agents:
        cache = type_cache_by_id.get(agent.get("type"))
        if cache is None:
            continue
        decay = cache.get("reputation_decay", 0.0)
        if decay <= 0.0:
            continue
        rep = agent.get("reputation", 0.0)
        if rep <= 0.0:
            continue
        agent["reputation"] = rep * (1.0 - decay)


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------


def execute_action(
    action: ActionKind,
    agent: dict[str, Any],
    state: dict[str, Any],
    pools: dict[str, dict[str, float]],
    sampler: Sampler,
    *,
    realized: dict[str, dict[str, float]],
    period: int,
    primary_token_id: str | None = None,
    neighbor_graph: dict[int, tuple[int, ...]] | None = None,
    agents_by_id: dict[int, dict[str, Any]] | None = None,
) -> None:
    """Mutate state to reflect the chosen action.

    ``pools[token_id]['E']`` is the remaining emission budget for
    this period; ``pools[token_id]['B']`` is the burn budget.
    ``realized[token_id]['E'|'B']`` accumulates what actually got
    minted / burned this period (sum over all agents).
    """
    if action == ActionKind.HOLD:
        # No state mutation. Holding time accumulates via the
        # last_action field, which stays put.
        return

    # Pick the agent's "primary" token — for v1 we route EARN/REDEEM
    # to the first token the IR declares. Future: per-agent-type
    # token preference (a UI affordance).
    token_id = primary_token_id
    if token_id is None:
        token_id = next(iter(state["tokens"].keys()), None)
    if token_id is None:
        return

    if action == ActionKind.EARN:
        # Each EARN-ing agent gets an equal share of the remaining
        # emission pool. We don't know the final population of
        # earners until all agents have decided, so the engine
        # pre-computes the count and we draw `pool / count`.
        share = pools[token_id].get("_earn_share", 0.0)
        if share > 0:
            agent["balance"] = agent.get("balance", 0.0) + share
            state["tokens"][token_id]["M"] += share
            realized[token_id]["E"] += share
            agent["last_action"] = period
            # Phase E3: contribution-style action — accrues reputation.
            agent["reputation"] = agent.get("reputation", 0.0) + REPUTATION_GAIN_EARN

    elif action == ActionKind.TRANSFER:
        # Peer-to-peer: pick a peer to receive 10 % of balance. Phase B
        # restricts the peer pick to graph neighbors when a
        # neighbor_graph is supplied; otherwise fall back to the full
        # population (the WELL_MIXED case).
        bal = agent.get("balance", 0.0)
        if bal <= 0:
            return
        target = _pick_peer(agent, state, sampler, neighbor_graph, agents_by_id)
        if target is None:
            return
        amount = bal * 0.1
        agent["balance"] = bal - amount
        target["balance"] = target.get("balance", 0.0) + amount
        agent["last_action"] = period
        # Track transfer for live trade-graph analytics (Phase B).
        edges = state.setdefault("trade_edges", {})
        key = (min(agent["id"], target["id"]), max(agent["id"], target["id"]))
        edges[key] = edges.get(key, 0.0) + amount

    elif action == ActionKind.REDEEM:
        # Spend balance to acquire a good. We model this as a draw
        # from the per-period burn pool: the agent's balance
        # decreases by `min(B_pool / count, agent.balance)`, and the
        # realized burn flow accumulates by that same amount.
        share = pools[token_id].get("_redeem_share", 0.0)
        bal = agent.get("balance", 0.0)
        if share > 0 and bal > 0:
            spent = min(share, bal)
            agent["balance"] = bal - spent
            state["tokens"][token_id]["M"] = max(
                0.0, state["tokens"][token_id]["M"] - spent
            )
            realized[token_id]["B"] += spent
            agent["last_action"] = period

    elif action == ActionKind.STAKE:
        # Mark agent as staking — don't transfer/redeem until unlock.
        # The next ``stake_periods`` periods the agent stays in
        # STAKE/HOLD effectively. For v1 we just flag the agent.
        agent["staking_until"] = period + 8  # ~2 months default
        agent["last_action"] = period

    elif action == ActionKind.VOTE:
        # Contribute weight to a live governance count. Phase B
        # routes the vote through the agent's delegate (defaults to
        # self for non-DELEGATED weightings).
        weight = agent.get("balance", 0.0)
        state.setdefault("votes_this_period", 0.0)
        state["votes_this_period"] += weight
        delegate_id = agent.get("delegate_of", agent["id"])
        per_delegate = state.setdefault("votes_by_delegate", {})
        per_delegate[delegate_id] = per_delegate.get(delegate_id, 0.0) + weight
        agent["last_action"] = period
        # Phase E3: governance participation accrues reputation,
        # weighted half as much as EARN — voting is cheaper than
        # contributing fresh tokens.
        agent["reputation"] = agent.get("reputation", 0.0) + REPUTATION_GAIN_VOTE


def is_staked(agent: dict[str, Any], period: int) -> bool:
    """Whether an agent is currently locked under a STAKE."""
    until = agent.get("staking_until", 0)
    return until > period


def _pick_peer(
    agent: dict[str, Any],
    state: dict[str, Any],
    sampler: Sampler,
    neighbor_graph: dict[int, tuple[int, ...]] | None,
    agents_by_id: dict[int, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Sample one peer for TRANSFER.

    Decision order:
      • ``neighbor_graph`` is set ⇒ pick from the agent's neighbor
        tuple (NETWORK / SPATIAL). Returns ``None`` if isolated.
      • Otherwise ⇒ pick any other agent from ``state['agents']``
        (WELL_MIXED fallback).

    Returns ``None`` when no peer is available (single agent, isolated
    node). The action then no-ops rather than transferring to self.
    """
    if neighbor_graph is not None:
        neighbors = neighbor_graph.get(agent["id"])
        if not neighbors:
            return None
        peer_id = sampler.rng.choice(neighbors)
        if agents_by_id is not None:
            return agents_by_id.get(peer_id)
        # Fallback to linear scan (should not normally fire).
        for peer in state.get("agents", []):
            if peer["id"] == peer_id:
                return peer
        return None
    # WELL_MIXED — pick from the full population.
    peers = state.get("agents", [])
    if len(peers) <= 1:
        return None
    for _ in range(8):
        candidate = sampler.rng.choice(peers)
        if candidate["id"] != agent["id"]:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Pool preparation
# ---------------------------------------------------------------------------


def prepare_pools(
    state: dict[str, Any],
    static_rates: dict[str, dict[str, float]],
    stochastic_rules: list[tuple[str, str, Any, Any, Any]],
    sampler: Sampler,
    agent_types_by_id: dict[str, Any],
) -> dict[str, dict[str, float]]:
    """Build the per-token emission/burn pools for this period.

    ``static_rates`` is the once-per-run baseline. Stochastic rules
    contribute additional samples drawn each period.

    The pools also carry pre-computed ``_earn_share`` and
    ``_redeem_share`` — what each EARN-ing / REDEEM-ing agent will
    get. We compute these after all agents decide so the distribution
    is exact. So this function returns pools without the shares;
    the caller fills them in.
    """
    pools: dict[str, dict[str, float]] = {}
    for token_id, rates in static_rates.items():
        pools[token_id] = {"E": rates.get("E", 0.0), "B": rates.get("B", 0.0)}
    for token_id, side, rule, freq_ac, freq_dist in stochastic_rules:
        # Frequency sources were resolved through the events catalog at
        # run setup (see engine._build_initial_state) — no trigger
        # reads here. The sampling semantics live in ONE place:
        # engine._sample_stochastic_rule_value.
        from verifier.abm.engine import _sample_stochastic_rule_value  # local to avoid cycle

        value = _sample_stochastic_rule_value(rule, freq_ac, freq_dist, sampler)
        pools[token_id][side] = pools[token_id].get(side, 0.0) + value
    return pools


def compute_pool_shares(
    pools: dict[str, dict[str, float]],
    earn_count: int,
    redeem_count: int,
) -> None:
    """Fill in ``_earn_share`` and ``_redeem_share`` per token pool.

    Distribution policy:
      - EARN: equal share of E pool across all earning agents.
      - REDEEM: equal share of B pool across all redeeming agents.

    If no agent picked the action, the pool goes unspent — that's the
    realized rate falling below the target.
    """
    for token_id, p in pools.items():
        p["_earn_share"] = p.get("E", 0.0) / earn_count if earn_count > 0 else 0.0
        p["_redeem_share"] = p.get("B", 0.0) / redeem_count if redeem_count > 0 else 0.0
