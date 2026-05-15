"""Tests for the Phase-D /explore page + run_explore engine path."""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import load_te
from verifier.abm import SimulationConfig, run_explore

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def test_run_explore_returns_per_period_snapshots() -> None:
    """One snapshot per period (plus t=0). All required fields are
    populated for each."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    report = run_explore(
        te, sim_config=SimulationConfig(horizon_periods=10, seed=1, max_agents=30)
    )
    assert len(report.snapshots) == 11  # 0..10 inclusive
    for snap in report.snapshots:
        assert "BTC" in snap.M_by_token
        assert snap.M_by_token["BTC"] > 0
        assert 0.0 <= snap.effective_gini <= 1.0
        assert 0.0 <= snap.phi <= 1.0


def test_run_explore_emits_agent_metadata() -> None:
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    report = run_explore(
        te, sim_config=SimulationConfig(horizon_periods=5, seed=2, max_agents=20)
    )
    assert report.n_agents > 0
    assert len(report.agents) == report.n_agents
    for a in report.agents:
        assert isinstance(a.id, int)
        assert a.type
        # Every agent has a delegate (self for non-DELEGATED).
        assert a.delegate_of == a.id  # Bitcoin uses LINEAR vote_weighting


def test_run_explore_emits_neighbor_graph_for_network_topology() -> None:
    """A NETWORK-topology spec produces an adjacency dict; WELL_MIXED
    leaves it empty (client renders a complete-graph hint)."""
    # Bitcoin uses WELL_MIXED in the example.
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    report = run_explore(
        te, sim_config=SimulationConfig(horizon_periods=2, seed=3, max_agents=10)
    )
    if report.topology == "well_mixed":
        assert report.neighbor_graph == {}
    else:
        assert report.neighbor_graph


def test_run_explore_trade_edges_grow_over_time() -> None:
    """As the trajectory advances, the cumulative trade-edge count is
    non-decreasing — TRANSFERs only add edges, never remove them."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    report = run_explore(
        te, sim_config=SimulationConfig(horizon_periods=20, seed=4, max_agents=20)
    )
    sizes = [len(s.trade_edges) for s in report.snapshots]
    for i in range(1, len(sizes)):
        assert sizes[i] >= sizes[i - 1]


# ---------------------------------------------------------------------------
# Phase E surfaces — population + reputation snapshot fields
# ---------------------------------------------------------------------------


def test_explore_phase_e_fields_default_no_exits() -> None:
    """Pre-Phase-E examples produce no agent exits (the gate is opt-in
    via UtilityWeights.exit_propensity > 0). The reputation analytic is
    populated regardless — accumulation is a passive bookkeeping
    effect, not behavioral — so we only assert exit absence + field
    presence here."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    report = run_explore(
        te, sim_config=SimulationConfig(horizon_periods=5, seed=11, max_agents=20)
    )
    for snap in report.snapshots:
        assert snap.live_agent_count == len(snap.balances)
        assert snap.mean_reputation >= 0.0
        for ts in snap.by_type:
            assert ts.avg_reputation >= 0.0
    s = report.summary
    assert s.initial_agent_count == s.final_agent_count
    assert s.agents_exited == 0


def test_explore_phase_e_fields_react_to_enabled_features() -> None:
    """A TE with reputation_yield > 0 should accumulate non-zero mean
    reputation by the end of the run."""
    from schema import (
        ActionKind, AgentRole, AgentType, Archetype, AsymptoticClass,
        AsymptoticFamily, BurnTriggerKind, EmissionTriggerKind, FunctionShape,
        FunctionSign, GovernanceSpec, GovernanceType, HoldingTimeDistribution,
        Meta, NFRs, NumberRange, ParticipantsSpec, Rule, RuleTrigger, Token,
        TokenEconomy, TokenFunction, Topology, UtilityWeights,
    )
    te = TokenEconomy(
        meta=Meta(name="phase-e-explore", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[Rule(
                trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                function=FunctionShape(
                    sign=FunctionSign.ALWAYS_POSITIVE,
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(100.0)},
                    ),
                ),
            )],
            burn_rules=[Rule(
                trigger=RuleTrigger(kind=BurnTriggerKind.DEMAND_DRIVEN),
                function=FunctionShape(
                    sign=FunctionSign.ALWAYS_NEGATIVE,
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(20.0)},
                    ),
                ),
            )],
            offer_variety_K=NumberRange.point(5),
        )],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(15),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[AgentType(
                id="A", fraction=1.0, balance_share=1.0,
                role=AgentRole.CONTRIBUTOR,
                utility=UtilityWeights(
                    income_yield=10.0,
                    action_temperature=0.1,
                    reputation_yield=0.5,
                    reputation_decay=0.05,
                ),
                action_set=[ActionKind.EARN, ActionKind.HOLD],
                expected_holding_time=HoldingTimeDistribution(
                    expected_periods=NumberRange.point(5)
                ),
            )],
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )
    report = run_explore(te, sim_config=SimulationConfig(horizon_periods=10, seed=1, max_agents=15))
    last = report.snapshots[-1]
    assert last.mean_reputation > 0.0
    assert any(ts.avg_reputation > 0.0 for ts in last.by_type)
    assert report.summary.peak_mean_reputation > 0.0
    assert report.summary.final_mean_reputation > 0.0


# ---------------------------------------------------------------------------
# /api/explore route
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from webapp.app import app

    app.testing = True
    return app.test_client()


def test_api_explore_returns_200(client) -> None:
    yaml_text = client.get("/api/example/bitcoin").get_json()["yaml"]
    r = client.post(
        "/api/explore",
        json={"yaml": yaml_text, "horizon_periods": 10, "seed": 1, "max_agents": 20},
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["te_name"] == "Bitcoin"
    assert j["snapshots"]
    assert len(j["snapshots"]) == 11


def test_api_explore_clamps_horizon(client) -> None:
    """Clamp at SimulationConfig's schema cap (10 000). Anything bigger
    is silently truncated; anything ≤ 10 000 is honored — including
    Bitcoin-scale horizons (~9 000 weeks)."""
    yaml_text = client.get("/api/example/bitcoin").get_json()["yaml"]
    r = client.post(
        "/api/explore",
        json={"yaml": yaml_text, "horizon_periods": 999_999, "seed": 1, "max_agents": 5},
    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["config"]["horizon_periods"] <= 10_000
    # And a 500-period request, previously clamped at 300, now honored.
    r2 = client.post(
        "/api/explore",
        json={"yaml": yaml_text, "horizon_periods": 500, "seed": 1, "max_agents": 5},
    )
    assert r2.status_code == 200
    j2 = r2.get_json()
    assert j2["config"]["horizon_periods"] == 500


def test_explore_page_renders(client) -> None:
    r = client.get("/explore")
    assert r.status_code == 200
    assert b"Trajectory Explorer" in r.data
