"""ABM reference engine — Monte Carlo correctness, triage rules,
deployment-vs-dynamic split, CLI integration.

These tests pin the verifier↔ABM contract: ABM consumes the verifier's
minimal output, simulates only what's worth simulating, produces
likelihood + time-to-violation in a stable JSON shape.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from schema import load_te, v2
from verifier.abm import SimulationConfig, run_simulation
from verifier.abm.report import (
    FMSimulationResult,
    SimulationConfig as ConfigInReport,
    SimulationReport,
)
from verifier.abm.predicates import evaluate
from verifier.abm.state import State, derived_variable, initial_state
from verifier.minimal import StructuralStatus, minimal_verdicts
from verifier.safety_predicate import SafetyPredicate

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


# ---------------------------------------------------------------------------
# State + predicate evaluation
# ---------------------------------------------------------------------------


def test_state_resolves_per_token_variable() -> None:
    state = initial_state(token_ids=["TKN"])
    state["tokens"]["TKN"]["E"] = 100.0
    state["tokens"]["TKN"]["B"] = 40.0
    state["tokens"]["TKN"]["M"] = 5000.0
    assert derived_variable(state, "net_emission_per_period[TKN]") == 60.0
    assert derived_variable(state, "rho[TKN]") == pytest.approx(0.4)
    assert derived_variable(state, "M[TKN]") == 5000.0


def test_state_resolves_flat_variable() -> None:
    state = initial_state(token_ids=["TKN"])
    state["phi"] = 0.3
    state["gamma"] = 0.8
    state["S"] = 0.5
    state["K"]["TKN"] = 50.0
    state["Gamma_central"] = 0.4
    state["effective_gini"] = 0.55
    assert derived_variable(state, "phi_times_K") == pytest.approx(0.3 * 50.0)
    assert derived_variable(state, "gamma_times_S") == pytest.approx(0.4)
    assert derived_variable(state, "Gamma") == 0.4
    assert derived_variable(state, "effective_gini") == 0.55


def test_predicate_evaluation_operators() -> None:
    state = initial_state(token_ids=["TKN"])
    state["tokens"]["TKN"]["E"] = 100.0
    state["tokens"]["TKN"]["B"] = 50.0
    p_ge = SafetyPredicate(variable="rho[TKN]", operator=">=", threshold=0.4)
    p_lt = SafetyPredicate(variable="rho[TKN]", operator="<", threshold=0.6)
    p_gt = SafetyPredicate(variable="rho[TKN]", operator=">", threshold=0.5)
    p_le = SafetyPredicate(variable="rho[TKN]", operator="<=", threshold=0.5)
    p_eq = SafetyPredicate(variable="rho[TKN]", operator="==", threshold=0.5)
    assert evaluate(p_ge, state) is True
    assert evaluate(p_lt, state) is True
    assert evaluate(p_gt, state) is False  # rho = 0.5 is not > 0.5
    assert evaluate(p_le, state) is True
    assert evaluate(p_eq, state) is True


# ---------------------------------------------------------------------------
# Triage rules
# ---------------------------------------------------------------------------


def test_sound_fms_are_skipped_by_default() -> None:
    """The default config skips SOUND verdicts — no point Monte-Carloing
    a design the verifier proved safe."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    report = run_simulation(te, config=SimulationConfig(n_runs=50, seed=1))
    for r in report.per_fm_results:
        if r.structural_status == "sound":
            assert r.simulated is False
            assert "skipped" in (r.skip_reason or "")


def test_broken_fms_are_skipped_by_default() -> None:
    """BROKEN verdicts are likewise skipped — the ABM cannot rescue
    a structurally-broken design."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    report = run_simulation(te, config=SimulationConfig(n_runs=50, seed=1))
    fm6 = next(r for r in report.per_fm_results if r.failure_mode == "FM6")
    assert fm6.structural_status == "broken"
    assert fm6.simulated is False


def test_simulate_all_overrides_triage() -> None:
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    report = run_simulation(
        te, config=SimulationConfig(n_runs=20, seed=1, skip_non_fragile=False)
    )
    # FM5 is SOUND. With skip_non_fragile=False, it should still be
    # simulated (it has safety_predicates).
    fm5 = next(r for r in report.per_fm_results if r.failure_mode == "FM5")
    assert fm5.simulated is True


def test_fragile_fms_are_simulated() -> None:
    """FRAGILE FMs are exactly what the ABM should run — the verifier
    has shown they fail in some corners; the ABM tells us in how many."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    report = run_simulation(te, config=SimulationConfig(n_runs=100, seed=1))
    fm1_slp = next(
        r
        for r in report.per_fm_results
        if r.failure_mode == "FM1" and r.subject == "SLP"
    )
    assert fm1_slp.structural_status == "fragile"
    assert fm1_slp.simulated is True
    assert fm1_slp.n_runs == 100
    # Axie SLP should violate in a substantial fraction of runs.
    assert fm1_slp.p_violation > 0.5


# ---------------------------------------------------------------------------
# Deployment vs dynamic split
# ---------------------------------------------------------------------------


def test_deployment_and_dynamic_violations_sum_to_total() -> None:
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    report = run_simulation(te, config=SimulationConfig(n_runs=100, seed=1))
    for r in report.per_fm_results:
        if r.simulated:
            assert (
                r.n_violations_at_deployment + r.n_violations_dynamic
                == r.n_violations
            )


def test_time_to_violation_quartiles_only_use_dynamic_runs() -> None:
    """If all violations are at t=0, the quartiles should report None
    or 0 (no dynamic violations to compute quartiles over)."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    report = run_simulation(te, config=SimulationConfig(n_runs=100, seed=1))
    fm1_slp = next(
        r
        for r in report.per_fm_results
        if r.failure_mode == "FM1" and r.subject == "SLP"
    )
    if fm1_slp.n_violations_dynamic == 0:
        assert fm1_slp.time_to_violation_median is None


# ---------------------------------------------------------------------------
# Bitcoin capped-supply suppression
# ---------------------------------------------------------------------------


def test_bitcoin_fm3_emits_no_safety_predicate() -> None:
    """Bitcoin's FM3 has supply_cap on its emission rule → no ρ
    predicate. The ABM defers to the verifier's pass_as_intended
    rather than evaluating ρ = 0/E and reporting 100% deployment
    violation."""
    from verifier.failure_modes.fm3_burn_emission import FM3BurnEmission

    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    preds = FM3BurnEmission().safety_predicates(te, None, "BTC")
    assert preds == [], (
        "Capped-supply tokens should not emit a ρ predicate — the "
        "verifier's pass_as_intended captures the design intent."
    )


def test_bitcoin_fm3_simulation_is_not_active_risk() -> None:
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    report = run_simulation(te, config=SimulationConfig(n_runs=100, seed=1))
    fm3 = next(r for r in report.per_fm_results if r.failure_mode == "FM3")
    # Either skipped (no predicates) or 0% violation — never falsely
    # reporting Bitcoin's FM3 as deployment-failing.
    if fm3.simulated:
        assert fm3.p_violation == 0.0


# ---------------------------------------------------------------------------
# Wilson confidence interval
# ---------------------------------------------------------------------------


def test_wilson_ci_brackets_proportion() -> None:
    from verifier.abm.engine import _wilson_ci

    lo, hi = _wilson_ci(50, 100)
    assert 0 < lo < 0.5 < hi < 1
    assert lo < hi


def test_wilson_ci_is_valid_at_extremes() -> None:
    from verifier.abm.engine import _wilson_ci

    # P = 0
    lo, hi = _wilson_ci(0, 100)
    assert lo == 0.0
    assert hi > 0  # CI extends upward even with 0 observed violations
    # P = 1
    lo, hi = _wilson_ci(100, 100)
    assert hi == pytest.approx(1.0)
    assert lo < 1


# ---------------------------------------------------------------------------
# JSON contract
# ---------------------------------------------------------------------------


def test_simulation_report_is_json_serializable() -> None:
    te = load_te(EXAMPLES_DIR / "curve_vecrv.yaml")
    report = run_simulation(te, config=SimulationConfig(n_runs=20, seed=1))
    payload = report.model_dump(mode="json")
    # Round-trip
    serialized = json.dumps(payload)
    parsed = json.loads(serialized)
    assert parsed["te_name"] == "Curve / veCRV"
    assert isinstance(parsed["per_fm_results"], list)


def test_report_round_trip_via_pydantic() -> None:
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    report = run_simulation(te, config=SimulationConfig(n_runs=20, seed=1))
    payload = report.model_dump(mode="json")
    reloaded = SimulationReport.model_validate(payload)
    assert reloaded.te_name == report.te_name
    assert len(reloaded.per_fm_results) == len(report.per_fm_results)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_seed_produces_same_results() -> None:
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    r1 = run_simulation(te, config=SimulationConfig(n_runs=30, seed=999))
    r2 = run_simulation(te, config=SimulationConfig(n_runs=30, seed=999))
    for a, b in zip(r1.per_fm_results, r2.per_fm_results):
        assert a.n_violations == b.n_violations
        assert a.p_violation == b.p_violation


# ---------------------------------------------------------------------------
# Verifier → ABM handoff via JSON
# ---------------------------------------------------------------------------


def test_abm_consumes_verifier_json_verdicts() -> None:
    """The whole point of the contract: verifier emits JSON, ABM
    reads it back as ReachabilityVerdict objects."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    verdicts = minimal_verdicts(te)
    # Round-trip through JSON.
    payload = [v.model_dump(mode="json") for v in verdicts]
    serialized = json.dumps(payload)
    parsed = json.loads(serialized)
    from verifier.minimal import ReachabilityVerdict

    reloaded = [ReachabilityVerdict.model_validate(v) for v in parsed]
    report = run_simulation(
        te, verdicts=reloaded, config=SimulationConfig(n_runs=20, seed=1)
    )
    assert len(report.per_fm_results) == len(reloaded)


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_te_simulate_basic_invocation() -> None:
    result = subprocess.run(
        [
            "te-simulate",
            "examples/axie_infinity.yaml",
            "--runs",
            "30",
            "--seed",
            "42",
        ],
        capture_output=True,
        text=True,
        cwd=str(EXAMPLES_DIR.parent),
    )
    assert result.returncode in (0, 1)
    assert "ABM simulation report" in result.stdout
    assert "Headline" in result.stdout


def test_cli_te_simulate_json_output() -> None:
    result = subprocess.run(
        [
            "te-simulate",
            "examples/curve_vecrv.yaml",
            "--runs",
            "20",
            "--seed",
            "42",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(EXAMPLES_DIR.parent),
    )
    assert result.returncode in (0, 1)
    payload = json.loads(result.stdout)
    assert payload["te_name"] == "Curve / veCRV"


def test_cli_te_simulate_consumes_verdicts_file(tmp_path: Path) -> None:
    # Step 1: emit minimal verdicts via te-verify
    verdicts_path = tmp_path / "verdicts.json"
    result = subprocess.run(
        [
            "te-verify",
            "examples/axie_infinity.yaml",
            "--minimal",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(EXAMPLES_DIR.parent),
    )
    verdicts_path.write_text(result.stdout)
    # Step 2: feed them into te-simulate
    result = subprocess.run(
        [
            "te-simulate",
            "examples/axie_infinity.yaml",
            "--verdicts",
            str(verdicts_path),
            "--runs",
            "20",
            "--seed",
            "42",
        ],
        capture_output=True,
        text=True,
        cwd=str(EXAMPLES_DIR.parent),
    )
    assert result.returncode in (0, 1), result.stderr
    assert "ABM simulation report" in result.stdout
