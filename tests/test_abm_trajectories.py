"""Per-period predicate-trajectory recording — engine + report shape +
webapp endpoint coverage.

The trajectory feature is opt-in via ``SimulationConfig.record_trajectories``.
When on, the engine records per-period values of each safety predicate's
variable across up to 50 sampled runs, then aggregates into
mean / p25 / p50 / p75 / p95 per period — the data source for the
trajectory line chart on the /simulate page.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import load_te
from verifier.abm import SimulationConfig, run_simulation
from verifier.abm.report import PredicateTrajectory, TrajectoryPoint

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _run(name: str, **kwargs):
    te = load_te(EXAMPLES_DIR / f"{name}.yaml")
    kwargs.setdefault("seed", 42)
    cfg = SimulationConfig(**kwargs)
    return run_simulation(te, config=cfg)


# ---------------------------------------------------------------------------
# Recording is opt-in
# ---------------------------------------------------------------------------


def test_trajectories_off_by_default() -> None:
    report = _run("axie_infinity", n_runs=20, horizon_periods=30)
    for r in report.per_fm_results:
        assert r.predicate_trajectories == []


def test_trajectories_on_when_requested() -> None:
    report = _run(
        "axie_infinity",
        n_runs=20,
        horizon_periods=30,
        record_trajectories=True,
    )
    has_traj = [r for r in report.per_fm_results if r.predicate_trajectories]
    assert has_traj  # at least one simulable FM emits trajectories


def test_trajectory_horizon_matches_config() -> None:
    """The trajectory has one point per period from t=0 through
    t=horizon (inclusive)."""
    report = _run(
        "axie_infinity",
        n_runs=10,
        horizon_periods=20,
        record_trajectories=True,
    )
    for r in report.per_fm_results:
        for traj in r.predicate_trajectories:
            assert len(traj.points) == 21  # 0..20 inclusive
            assert traj.points[0].t == 0
            assert traj.points[-1].t == 20


def test_trajectory_quantile_ordering() -> None:
    """For every period, p25 ≤ p50 ≤ p75 ≤ p95 by construction."""
    report = _run(
        "axie_infinity",
        n_runs=30,
        horizon_periods=30,
        record_trajectories=True,
    )
    for r in report.per_fm_results:
        for traj in r.predicate_trajectories:
            for pt in traj.points:
                assert pt.p25 <= pt.p50 <= pt.p75 <= pt.p95


def test_trajectory_one_entry_per_predicate() -> None:
    """FM4 has two safety predicates (φ-clause + γ-clause). Both
    should get a trajectory series."""
    report = _run(
        "axie_infinity",
        n_runs=10,
        horizon_periods=20,
        record_trajectories=True,
    )
    fm4 = next(
        r for r in report.per_fm_results if r.failure_mode == "FM4"
    )
    if fm4.simulated and fm4.predicate_trajectories:
        # FM4 has 2 predicates; both should be recorded.
        assert len(fm4.predicate_trajectories) == 2
        vars_set = {t.variable for t in fm4.predicate_trajectories}
        assert "phi_times_K" in vars_set
        assert "gamma_times_S" in vars_set


def test_trajectory_threshold_matches_predicate() -> None:
    report = _run(
        "axie_infinity",
        n_runs=10,
        horizon_periods=20,
        record_trajectories=True,
    )
    for r in report.per_fm_results:
        for traj in r.predicate_trajectories:
            # The trajectory's threshold matches the predicate's threshold —
            # used for the chart's reference line.
            matching_pred = next(
                (p for p in r.predicates if p.variable == traj.variable),
                None,
            )
            assert matching_pred is not None
            assert matching_pred.threshold == traj.threshold
            assert matching_pred.operator == traj.operator


# ---------------------------------------------------------------------------
# Time-evolving signal — FM2 with per-agent clocks
# ---------------------------------------------------------------------------


def test_fm2_tau_bar_evolves_over_time() -> None:
    """FM2's tau_bar should change between t=0 and t=horizon because
    per-agent clocks fire periodically. This is the test that proves
    trajectory recording captures real dynamics, not a flat line."""
    report = _run(
        "axie_infinity",
        n_runs=30,
        horizon_periods=80,
        record_trajectories=True,
    )
    fm2 = next(
        r for r in report.per_fm_results
        if r.failure_mode == "FM2" and r.subject == "AXS"
    )
    if not fm2.simulated or not fm2.predicate_trajectories:
        pytest.skip("FM2 was skipped under the verifier's triage")
    traj = fm2.predicate_trajectories[0]
    initial = traj.points[0].p50
    final = traj.points[-1].p50
    # tau_bar should decrease over time as agent clocks reset —
    # require a meaningful change (>10%) to confirm real dynamics.
    assert abs(initial - final) / max(abs(initial), 1e-9) > 0.1, (
        f"tau_bar trajectory looks static: initial={initial}, final={final}. "
        f"The per-agent clock should be moving the median."
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_seed_produces_same_trajectories() -> None:
    r1 = _run(
        "axie_infinity",
        n_runs=20,
        horizon_periods=30,
        seed=999,
        record_trajectories=True,
    )
    r2 = _run(
        "axie_infinity",
        n_runs=20,
        horizon_periods=30,
        seed=999,
        record_trajectories=True,
    )
    for a, b in zip(r1.per_fm_results, r2.per_fm_results):
        for ta, tb in zip(a.predicate_trajectories, b.predicate_trajectories):
            for pa, pb in zip(ta.points, tb.points):
                assert pa.p50 == pb.p50
                assert pa.mean == pb.mean


# ---------------------------------------------------------------------------
# JSON shape
# ---------------------------------------------------------------------------


def test_report_with_trajectories_is_json_serializable() -> None:
    import json

    report = _run(
        "axie_infinity",
        n_runs=5,
        horizon_periods=10,
        record_trajectories=True,
    )
    payload = report.model_dump(mode="json")
    serialized = json.dumps(payload)
    assert "predicate_trajectories" in serialized


def test_round_trip_through_pydantic() -> None:
    from verifier.abm.report import SimulationReport

    report = _run(
        "axie_infinity",
        n_runs=5,
        horizon_periods=10,
        record_trajectories=True,
    )
    payload = report.model_dump(mode="json")
    reloaded = SimulationReport.model_validate(payload)
    assert reloaded.te_name == report.te_name
    # Trajectories round-trip too.
    for a, b in zip(reloaded.per_fm_results, report.per_fm_results):
        assert len(a.predicate_trajectories) == len(b.predicate_trajectories)


# ---------------------------------------------------------------------------
# Webapp endpoint coverage
# ---------------------------------------------------------------------------


def test_simulate_endpoint_accepts_trajectories_flag() -> None:
    pytest.importorskip("flask")
    from webapp.app import app
    client = app.test_client()
    yaml_text = client.get("/api/example/axie_infinity").get_json()["yaml"]
    r = client.post(
        "/api/simulate",
        json={
            "yaml": yaml_text,
            "n_runs": 20,
            "horizon_periods": 30,
            "seed": 42,
            "record_trajectories": True,
        },
    )
    assert r.status_code == 200
    report = r.get_json()
    has_traj = [r for r in report["per_fm_results"] if r["predicate_trajectories"]]
    assert has_traj
    # Spot-check shape.
    traj = has_traj[0]["predicate_trajectories"][0]
    assert "variable" in traj
    assert "threshold" in traj
    assert "points" in traj
    if traj["points"]:
        pt = traj["points"][0]
        for key in ("t", "mean", "p25", "p50", "p75", "p95"):
            assert key in pt


def test_simulate_endpoint_defaults_trajectories_off() -> None:
    pytest.importorskip("flask")
    from webapp.app import app
    client = app.test_client()
    yaml_text = client.get("/api/example/bitcoin").get_json()["yaml"]
    r = client.post(
        "/api/simulate",
        json={"yaml": yaml_text, "n_runs": 20, "seed": 1},
    )
    report = r.get_json()
    # Default: trajectory list is empty everywhere.
    for r in report["per_fm_results"]:
        assert r["predicate_trajectories"] == []
