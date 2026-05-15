"""Phase J — ABM-trajectory enrichment.

The third verification layer must carry the most-information-dense
output of the three (formal proves possibility; MC quantifies likelihood;
ABM reveals dynamics). Confirms the new fields are populated end-to-end."""

from __future__ import annotations

from pathlib import Path

from schema import load_te
from verifier.abm import SimulationConfig, run_explore

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def test_snapshots_carry_events_realized_and_assets() -> None:
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    report = run_explore(
        te, sim_config=SimulationConfig(horizon_periods=10, seed=2, max_agents=20),
    )
    for snap in report.snapshots:
        # Every event in the catalog appears in every snapshot.
        for ev in te.events:
            assert ev.id in snap.events_realized
        # cascina_roccafranca has one asset.
        if te.non_tokenized_assets:
            for asset in te.non_tokenized_assets:
                assert asset.id in snap.assets


def test_reputation_quantiles_present_and_ordered() -> None:
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    report = run_explore(
        te, sim_config=SimulationConfig(horizon_periods=12, seed=4, max_agents=30),
    )
    last = report.snapshots[-1]
    # p10 ≤ p50 ≤ p90 holds in any sample.
    assert last.reputation_p10 <= last.reputation_p50 <= last.reputation_p90
    # By the end, p90 ≥ mean (heavy-tailed accumulation pattern).
    assert last.reputation_p90 >= last.mean_reputation - 1e-9


def test_exit_cohort_breakdown_populated_when_exits_fire() -> None:
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    report = run_explore(
        te, sim_config=SimulationConfig(horizon_periods=52, seed=42, max_agents=80),
    )
    total_exits = sum(s.exits_this_period for s in report.snapshots)
    summary_exits = report.summary.agents_exited
    # Cumulative per-period exits should match the summary count.
    assert abs(total_exits - summary_exits) <= 1   # off-by-one tolerance
    # At least some periods recorded per-type exit attribution.
    saw_per_type = any(s.exits_by_type for s in report.snapshots)
    assert saw_per_type


def test_event_firing_count_matches_catalog_frequency_ballpark() -> None:
    """Event firings should reflect declared frequency on average."""
    te = load_te(EXAMPLES_DIR / "time_bank.yaml")
    report = run_explore(
        te, sim_config=SimulationConfig(horizon_periods=20, seed=7, max_agents=50),
    )
    # service_delivered frequency: linear with b in [20, 180] → midpoint 100.
    fires = [s.events_realized.get("service_delivered", 0.0) for s in report.snapshots[1:]]
    avg = sum(fires) / max(1, len(fires))
    # Sampled within run from [20, 180] uniform → expect avg in [20, 180].
    assert 15.0 <= avg <= 200.0
