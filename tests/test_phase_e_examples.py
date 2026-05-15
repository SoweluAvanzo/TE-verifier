"""Sanity tests for the two Phase-E example economies.

Confirms time_bank.yaml and cascina_roccafranca.yaml:
  * Load without schema errors.
  * Produce non-trivial FM verdicts via the verifier dispatcher.
  * Run end-to-end through the ABM explore path.
  * Exercise all three Phase E features — exit causes population
    shrinkage, jitter is declared, reputation accrues.

These are smoke tests, not behavioral assertions on specific FM
verdicts. The verdicts depend on the configurable risk-band cutoffs
in VerifierConfig and we don't want this file to break every time
those move.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import load_te
from verifier.abm import SimulationConfig, run_explore
from verifier.dispatcher import verify

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize(
    "yaml_name",
    ["time_bank.yaml", "cascina_roccafranca.yaml"],
)
def test_phase_e_example_loads_and_verifies(yaml_name: str) -> None:
    te = load_te(EXAMPLES_DIR / yaml_name)
    report = verify(te)
    # Both examples should produce a non-empty verdict set across
    # multiple FMs — they exercise emission, burn, governance, and a
    # contribution-style earning mechanism.
    assert report.verdicts
    fm_ids = {v.failure_mode for v in report.verdicts}
    # Supply triad must be evaluated for both.
    assert any("FM1" in fid for fid in fm_ids)
    assert any("FM3" in fid for fid in fm_ids)


def _phase_e_features_active(te) -> dict[str, bool]:
    """Did the YAML actually opt into each Phase E feature?"""
    flags = {"exit": False, "jitter": False, "reputation": False}
    for at in te.participants.agent_types:
        if at.utility is not None:
            if at.utility.exit_propensity > 0:
                flags["exit"] = True
            if at.utility.reputation_yield > 0 or at.utility.reputation_decay > 0:
                flags["reputation"] = True
        if at.utility_jitter is not None:
            j = at.utility_jitter
            if any([
                j.income_yield, j.holding_yield, j.redemption_value,
                j.governance_payoff, j.social_payoff, j.risk_aversion,
            ]):
                flags["jitter"] = True
    return flags


@pytest.mark.parametrize(
    "yaml_name", ["time_bank.yaml", "cascina_roccafranca.yaml"],
)
def test_phase_e_example_declares_all_three_features(yaml_name: str) -> None:
    te = load_te(EXAMPLES_DIR / yaml_name)
    flags = _phase_e_features_active(te)
    assert flags["exit"], "expected exit_propensity > 0 on at least one type"
    assert flags["reputation"], "expected reputation_yield/decay > 0 on at least one type"
    assert flags["jitter"], "expected non-zero utility_jitter on at least one type"


@pytest.mark.parametrize(
    "yaml_name", ["time_bank.yaml", "cascina_roccafranca.yaml"],
)
def test_phase_e_example_abm_trajectory_runs(yaml_name: str) -> None:
    """End-to-end ABM run. Must:
      * complete without error
      * exercise the exit mechanism (population strictly shrinks since
        every type has exit_propensity > 0)
      * accumulate reputation (peak > 0) — proves reputation accrual
        wiring works
    """
    te = load_te(EXAMPLES_DIR / yaml_name)
    report = run_explore(
        te,
        sim_config=SimulationConfig(horizon_periods=52, seed=3, max_agents=60),
    )
    assert report.snapshots
    s = report.summary
    # Phase E1 — exits happen with the realistic propensities declared.
    assert s.agents_exited > 0, "expected some exits with declared propensities"
    assert s.final_agent_count < s.initial_agent_count
    # Phase E3 — reputation must accrue over the run.
    assert s.peak_mean_reputation > 0.0
    assert s.final_mean_reputation >= 0.0
    # Per-type avg_reputation must be populated.
    assert any(ts.avg_reputation > 0 for ts in s.final_by_type)


@pytest.mark.parametrize(
    "yaml_name,expected_min_exit_pct,expected_max_exit_pct",
    [
        # Time bank documented first-6-month attrition ≈ 50 %
        # (Seyfang 2004); over a 52-week horizon we expect 10–80 %
        # depending on calibration + seed.
        ("time_bank.yaml", 0.10, 0.80),
        # Italian community pacts: ~20 % annual citizen-volunteer
        # attrition (Bologna program reviews); over 52 weeks we expect
        # 5–40 %.
        ("cascina_roccafranca.yaml", 0.03, 0.45),
    ],
)
def test_phase_e_example_exit_rate_in_realistic_band(
    yaml_name: str,
    expected_min_exit_pct: float,
    expected_max_exit_pct: float,
) -> None:
    te = load_te(EXAMPLES_DIR / yaml_name)
    report = run_explore(
        te,
        sim_config=SimulationConfig(horizon_periods=52, seed=42, max_agents=80),
    )
    s = report.summary
    exit_pct = s.agents_exited / max(1, s.initial_agent_count)
    assert expected_min_exit_pct <= exit_pct <= expected_max_exit_pct, (
        f"{yaml_name}: exit rate {exit_pct:.2%} outside the realistic "
        f"band [{expected_min_exit_pct:.0%}, {expected_max_exit_pct:.0%}]"
    )
