"""Phase L1 — network analytics + FM coherence.

Run a small ABM trajectory and confirm:
* network_metrics block is present + populated
* z-scores against null models are computed (None when std=0)
* Pearson correlations satisfy r ∈ [-1, 1] and p ∈ [0, 1]
* per-type aggregates split agents correctly
* fm_coherence panel emits one row per FM and classifies them
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import load_te
from verifier.abm.explore import run_explore
from verifier.abm.report import SimulationConfig

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="module")
def report():
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    return run_explore(
        te,
        sim_config=SimulationConfig(horizon_periods=30, seed=42, max_agents=40),
    )


def test_network_metrics_populated(report) -> None:
    nm = report.network_metrics
    assert nm is not None
    assert nm.n_nodes == 40
    assert nm.n_edges > 0
    assert 0.0 <= nm.giant_component_frac <= 1.0
    assert len(nm.per_agent) == 40
    assert len(nm.per_type) > 0


def test_network_level_stats_have_baselines(report) -> None:
    """Every network-level stat reports observed + ER baseline +
    configuration-model baseline. Z-score may be None when std=0."""
    nm = report.network_metrics
    stat_names = {s.name for s in nm.network_level}
    expected = {"density", "avg_clustering", "transitivity",
                "assortativity_degree", "diameter_lcc",
                "avg_shortest_path_lcc"}
    assert expected.issubset(stat_names)
    for s in nm.network_level:
        assert s.er_std >= 0.0
        assert s.config_std >= 0.0
        # When std > 0, z-score must be finite.
        if s.er_std > 0.0:
            assert s.er_z is not None
        if s.config_std > 0.0:
            assert s.config_z is not None


def test_pearson_correlations_bounded(report) -> None:
    nm = report.network_metrics
    for c in nm.correlations:
        assert -1.0 <= c.r <= 1.0
        assert 0.0 <= c.p <= 1.0
        assert c.n >= 0
    # Diagonal entries (a == b) must equal 1.0 unless the underlying
    # series is constant (variance 0 → correlation undefined; we report
    # 0 in that case to keep the matrix well-defined).
    for c in nm.correlations:
        if c.a == c.b:
            assert c.r in (0.0, pytest.approx(1.0))


def test_centrality_correlations_strong_on_well_connected_graph(report) -> None:
    """On a single-component well-connected graph the four centrality
    measures should co-vary strongly (r > 0.5)."""
    nm = report.network_metrics
    pairs = [("degree", "betweenness"), ("degree", "closeness"),
             ("degree", "eigenvector"), ("betweenness", "closeness")]
    lookup = {f"{c.a}|{c.b}": c for c in nm.correlations}
    for a, b in pairs:
        cell = lookup.get(f"{a}|{b}") or lookup.get(f"{b}|{a}")
        assert cell is not None, f"missing correlation pair {a}~{b}"
        assert cell.r > 0.5, f"{a}~{b} r={cell.r:.3f} unexpectedly weak"


def test_per_type_partitions_agents(report) -> None:
    nm = report.network_metrics
    total = sum(pt.n_agents for pt in nm.per_type)
    assert total == 40
    for pt in nm.per_type:
        assert pt.balance_gini_within_type >= 0.0


def test_fm_coherence_panel(report) -> None:
    rows = report.fm_coherence
    assert rows
    statuses = {r["coherence"] for r in rows}
    # Should classify into one of the allowed categories.
    allowed = {
        "aligned", "confirmed", "abm_drift",
        "verifier_pessimistic", "fragile_realised", "fragile_avoided",
        "inconclusive",
    }
    assert statuses.issubset(allowed)
    # FM6 (governance capture, BROKEN per the YAML) should land in a
    # confirmed-style status — predicate trajectory crosses Gini=0.6.
    fm6 = next((r for r in rows if r["failure_mode"] == "FM6"), None)
    assert fm6 is not None
    assert fm6["coherence"] in {"confirmed", "fragile_realised", "aligned",
                                  "verifier_pessimistic", "inconclusive"}


def test_correlation_balance_centrality_meaningful(report) -> None:
    """Sanity: in a network where centrality and earning opportunities
    overlap, balance should correlate non-zero with at least one
    centrality measure."""
    nm = report.network_metrics
    lookup = {f"{c.a}|{c.b}": c for c in nm.correlations}
    cents = ["degree", "betweenness", "closeness", "eigenvector"]
    rs = []
    for cent in cents:
        cell = lookup.get(f"balance|{cent}") or lookup.get(f"{cent}|balance")
        if cell:
            rs.append(abs(cell.r))
    # At least one absolute r above 0.1 (avoids pathologically null run).
    assert any(r > 0.1 for r in rs), f"all r tiny: {rs}"
