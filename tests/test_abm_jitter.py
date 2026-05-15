"""Phase E2 — per-agent utility jitter.

Verifies:
  * sample_agent_utility_offsets returns None for zero-sigma jitter
    (no-op fast path).
  * Non-zero sigma yields agent dicts with utility_offsets fields.
  * Per-action offset mapping matches build_type_cache's recipe — a
    jittered EARN weight equals base + offset_iy; HOLD = base + (off_hy
    + 0.5·off_ra); STAKE = base + (0.8·off_hy + 0.3·off_ra); etc.
  * Zero jitter agents are pick_action-identical to pre-Phase-E2.
  * High-jitter cohorts pick a wider distribution of actions even when
    type weights are degenerate.
  * Mid-run SPAWN_AGENTS events inherit jitter.
"""

from __future__ import annotations

import statistics

import pytest

from schema import (
    ActionKind,
    AgentRole,
    AgentType,
    HoldingTimeDistribution,
    NumberRange,
    PopulationEvent,
    PopulationEventKind,
    UtilityJitter,
    UtilityWeights,
)
from verifier.abm.actions import (
    build_type_cache,
    pick_action_cached,
    sample_agent_utility_offsets,
)
from verifier.abm.samplers import Sampler


# ---------------------------------------------------------------------------
# Direct sample_agent_utility_offsets
# ---------------------------------------------------------------------------


def _bare_type(
    jitter: UtilityJitter | None = None,
    utility: UtilityWeights | None = None,
    actions: list[ActionKind] | None = None,
) -> AgentType:
    return AgentType(
        id="A",
        fraction=1.0,
        role=AgentRole.CONTRIBUTOR,
        utility=utility,
        utility_jitter=jitter,
        action_set=actions
        or [ActionKind.HOLD, ActionKind.EARN, ActionKind.REDEEM],
        expected_holding_time=HoldingTimeDistribution(
            expected_periods=NumberRange.point(5)
        ),
    )


def test_sample_offsets_returns_none_without_jitter() -> None:
    assert sample_agent_utility_offsets(_bare_type(), Sampler(seed=1)) is None


def test_sample_offsets_returns_none_when_all_sigmas_zero() -> None:
    jitter = UtilityJitter()  # all zeros
    assert sample_agent_utility_offsets(_bare_type(jitter=jitter), Sampler(seed=1)) is None


def test_sample_offsets_shape_matches_action_set() -> None:
    jitter = UtilityJitter(income_yield=0.5, holding_yield=0.5)
    actions = [
        ActionKind.HOLD,
        ActionKind.EARN,
        ActionKind.TRANSFER,
        ActionKind.REDEEM,
        ActionKind.STAKE,
        ActionKind.VOTE,
    ]
    offsets = sample_agent_utility_offsets(
        _bare_type(jitter=jitter, actions=actions), Sampler(seed=42)
    )
    assert offsets is not None
    assert len(offsets["utility_offsets"]) == len(actions)
    assert len(offsets["utility_offsets_no_balance"]) == len(actions)
    assert isinstance(offsets["hy_held_offset"], float)


def test_sample_offsets_zero_sigma_components_are_exactly_zero() -> None:
    """Only the non-zero sigma components draw — others stay 0."""
    jitter = UtilityJitter(income_yield=2.0)  # only iy nonzero
    actions = [ActionKind.HOLD, ActionKind.EARN, ActionKind.VOTE]
    offsets = sample_agent_utility_offsets(
        _bare_type(jitter=jitter, actions=actions), Sampler(seed=7)
    )
    assert offsets is not None
    # HOLD offset = off_hy + 0.5·off_ra = 0 + 0 = 0 (only iy is jittered).
    assert offsets["utility_offsets"][0] == 0.0
    # EARN offset = off_iy ≠ 0 almost surely.
    assert offsets["utility_offsets"][1] != 0.0
    # VOTE offset = off_gp = 0.
    assert offsets["utility_offsets"][2] == 0.0
    # hy_held_offset = 0.01·off_hy = 0.
    assert offsets["hy_held_offset"] == 0.0


def test_sample_offsets_no_balance_scaling() -> None:
    """No-balance offsets for TRANSFER/REDEEM/VOTE follow the same
    scaling as build_type_cache's no_balance_weights: 0.05, 0.05, 0.1."""
    jitter = UtilityJitter(
        social_payoff=1.0,
        redemption_value=1.0,
        governance_payoff=1.0,
    )
    actions = [ActionKind.TRANSFER, ActionKind.REDEEM, ActionKind.VOTE]
    offsets = sample_agent_utility_offsets(
        _bare_type(jitter=jitter, actions=actions), Sampler(seed=11)
    )
    assert offsets is not None
    w = offsets["utility_offsets"]
    no_bal = offsets["utility_offsets_no_balance"]
    assert no_bal[0] == pytest.approx(w[0] * 0.05)
    assert no_bal[1] == pytest.approx(w[1] * 0.05)
    assert no_bal[2] == pytest.approx(w[2] * 0.1)


# ---------------------------------------------------------------------------
# Backward compatibility — no jitter = pre-Phase-E2 behavior
# ---------------------------------------------------------------------------


def test_pick_action_cached_unchanged_without_offsets() -> None:
    """Agent without utility_offsets keys produces identical samples to
    a pre-Phase-E2 run with the same seed."""
    ag_type = _bare_type(
        utility=UtilityWeights(income_yield=1.0, action_temperature=0.5),
        actions=[ActionKind.EARN, ActionKind.HOLD],
    )
    cache = build_type_cache(ag_type)
    sampler1 = Sampler(seed=999)
    sampler2 = Sampler(seed=999)
    agent_plain = {"id": 0, "balance": 1.0, "last_action": 0}
    agent_with_none = {
        "id": 0,
        "balance": 1.0,
        "last_action": 0,
        "utility_offsets": None,
        "utility_offsets_no_balance": None,
    }
    a1 = pick_action_cached(agent_plain, cache, sampler1, period=1)
    a2 = pick_action_cached(agent_with_none, cache, sampler2, period=1)
    assert a1 == a2


# ---------------------------------------------------------------------------
# Behavioral heterogeneity — population spread under jitter
# ---------------------------------------------------------------------------


def test_jitter_breaks_uniform_action_choice() -> None:
    """Type weights identical across HOLD/EARN/REDEEM + high temperature
    → without jitter the population picks each ~uniformly. With strong
    jitter, individual agents bias toward their drawn favorite — the
    cohort's per-agent EARN frequency variance rises significantly."""
    actions = [ActionKind.HOLD, ActionKind.EARN, ActionKind.REDEEM]

    def _earn_freq(jitter: UtilityJitter | None, n_agents: int = 60, n_periods: int = 60) -> list[float]:
        ag_type = AgentType(
            id="A",
            fraction=1.0,
            role=AgentRole.CONTRIBUTOR,
            utility=UtilityWeights(
                income_yield=1.0,
                holding_yield=1.0,
                redemption_value=1.0,
                action_temperature=0.4,
            ),
            utility_jitter=jitter,
            action_set=actions,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange.point(5)
            ),
        )
        cache = build_type_cache(ag_type)
        sampler = Sampler(seed=2024)
        freqs = []
        for aid in range(n_agents):
            offsets = sample_agent_utility_offsets(ag_type, sampler) or {}
            agent = {"id": aid, "balance": 1.0, "last_action": 0}
            agent.update(offsets)
            picks = 0
            for t in range(1, n_periods + 1):
                if pick_action_cached(agent, cache, sampler, period=t) == ActionKind.EARN:
                    picks += 1
            freqs.append(picks / n_periods)
        return freqs

    flat_freqs = _earn_freq(None)
    jittered_freqs = _earn_freq(
        UtilityJitter(
            income_yield=4.0,
            holding_yield=4.0,
            redemption_value=4.0,
        )
    )
    # Jittered cohort: per-agent EARN frequency should span a wider
    # range than the no-jitter cohort. Compare standard deviation.
    flat_sd = statistics.pstdev(flat_freqs)
    jitter_sd = statistics.pstdev(jittered_freqs)
    assert jitter_sd > flat_sd, (flat_sd, jitter_sd)


def test_jitter_alters_score_in_expected_direction() -> None:
    """Hand-crafted offsets push an agent toward HOLD; verify the cache
    + offsets path picks HOLD overwhelmingly."""
    ag_type = _bare_type(
        utility=UtilityWeights(
            income_yield=1.0,
            holding_yield=0.1,
            action_temperature=0.05,
        ),
        actions=[ActionKind.EARN, ActionKind.HOLD],
    )
    cache = build_type_cache(ag_type)
    # Without offsets EARN wins (income_yield > holding_yield).
    sampler = Sampler(seed=10)
    agent_plain = {"id": 0, "balance": 1.0, "last_action": 0}
    earn_picks = sum(
        1
        for _ in range(200)
        if pick_action_cached(agent_plain, cache, sampler, period=1) == ActionKind.EARN
    )
    assert earn_picks > 180

    # Now plant per-agent offsets that flip the ordering: HOLD weight
    # offset = +10.0; EARN offset = 0.
    biased_agent = {
        "id": 1,
        "balance": 1.0,
        "last_action": 0,
        "utility_offsets": (0.0, 10.0),  # (EARN, HOLD) per action_set order
        "utility_offsets_no_balance": (0.0, 10.0),
        "hy_held_offset": 0.0,
    }
    sampler2 = Sampler(seed=11)
    hold_picks = sum(
        1
        for _ in range(200)
        if pick_action_cached(biased_agent, cache, sampler2, period=1) == ActionKind.HOLD
    )
    assert hold_picks > 180


# ---------------------------------------------------------------------------
# Integration: spawn_agents and SPAWN_AGENTS event inherit jitter
# ---------------------------------------------------------------------------


def test_spawn_agents_attaches_offsets_when_jitter_set() -> None:
    from verifier.abm.agents import spawn_agents
    from tests.test_abm_exit import _te  # reuse the single-token fixture

    # Build a TE then patch agent_types to inject jitter.
    te = _te()
    base_type = te.participants.agent_types[0]
    jittered_type = base_type.model_copy(
        update={
            "utility_jitter": UtilityJitter(
                income_yield=1.0,
                holding_yield=1.0,
                redemption_value=1.0,
            )
        }
    )
    te = te.model_copy(
        update={
            "participants": te.participants.model_copy(
                update={"agent_types": [jittered_type]}
            )
        }
    )
    agents = spawn_agents(te, Sampler(seed=1), max_agents=10)
    assert agents
    for a in agents:
        assert "utility_offsets" in a
        assert "utility_offsets_no_balance" in a
        assert "hy_held_offset" in a


def test_population_spawn_event_inherits_jitter() -> None:
    """A SPAWN_AGENTS event mid-run also attaches offsets when the
    target type declares jitter."""
    from verifier.abm.engine import _build_initial_state, _step_state
    from verifier.abm.agents import spawn_agents
    from tests.test_abm_exit import _te

    te = _te()
    base_type = te.participants.agent_types[0]
    jittered_type = base_type.model_copy(
        update={"utility_jitter": UtilityJitter(income_yield=3.0)}
    )
    te = te.model_copy(
        update={
            "participants": te.participants.model_copy(
                update={
                    "agent_types": [jittered_type],
                    "population_events": [
                        PopulationEvent(
                            kind=PopulationEventKind.SPAWN_AGENTS,
                            at_period=2,
                            agent_type_id="A",
                            count=5,
                            balance_per_agent=0.1,
                        ),
                    ],
                }
            )
        }
    )
    sampler = Sampler(seed=22)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=10)
    state["agents"] = spawn_agents(te, sampler, max_agents=10)
    initial_count = len(state["agents"])
    for _ in range(3):
        state = _step_state(state, params)
    assert len(state["agents"]) == initial_count + 5
    # Newly spawned agents should also carry offsets.
    for a in state["agents"][-5:]:
        assert "utility_offsets" in a
