## =============================================================================
## tests/platform_tests/test_platform_service.py — golden tests for te_platform/service.py
## =============================================================================
## GUIDE STEP   1.3 (validate), 1.4 (verify), 1.5 (bounds); activate each test
##              together with the matching function.
## PURPOSE      Golden tests: every case study in examples/ goes through the
##              service layer, and the result must equal what the existing,
##              trusted command-line tool `te-verify --json` produces. This
##              proves the new layer is a faithful wrapper of the verifier.
## DEPENDS ON   te_platform/service.py, te_platform/hashing.py, the existing
##              CLI (run as `python -m verifier.cli`, the module behind the
##              te-verify command, so the test does not depend on PATH),
##              examples/*.yaml.
## WHY          Architecture D2 / P1: the service layer must add nothing to and
##              lose nothing from the verifier's verdicts.
## ACTIVATE     1.3: uncomment the file (the validate tests). The 1.4 and 1.5
##              tests are commented twice under "## Guide 1.4" / "## Guide
##              1.5" lines: toggle them again with the matching functions.
##              The verify tests run Z3 on every example: a few seconds each.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
##
## Guide 1.3
## [ ] 1. Imports: `Path` (pathlib), `pytest`, and `service` from
##        te_platform.
## [ ] 2. Constant EXAMPLES: the sorted Path("examples").glob("*.yaml")
##        (paths are relative: run pytest from the repository root).
## [ ] 3. test_validate_accepts_every_example: one case per example with
##          | @pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
##        validate(path.read_text()) is valid (show r.errors on failure)
##        and has spec_hash and yaml set.
## [ ] 4. One test per kind of invalid input, none of which may raise:
##        test_validate_reports_schema_errors_instead_of_raising (YAML with
##        wrong types, "tokens: not-a-list": valid False, errors not
##        empty), test_validate_rejects_non_mapping_yaml (a YAML list) and
##        test_validate_reports_yaml_syntax_errors (unclosed "[": valid
##        False, one error with location "").
## [ ] 5. test_normalised_yaml_round_trips_to_the_same_hash: validate
##        EXAMPLES[0], then validate its .yaml; both spec_hash are equal.
## [ ] 6. Check:
##          | uv run pytest tests/platform_tests/test_platform_service.py -q
##
## Guide 1.4
## [ ] 7. Imports at the top: `json`, `subprocess`, `sys`.
## [ ] 8. Helper `_cli_report(path: Path) -> dict`: run the existing CLI
##        with subprocess.run([sys.executable, "-m", "verifier.cli",
##        str(path), "--json"], capture_output=True, text=True,
##        check=False) and json.loads its stdout. sys.executable is the
##        Python running pytest, so no PATH lookup is involved.
## [ ] 9. test_verify_matches_the_cli (parametrized like step 3): the
##        sorted (failure_mode, subject, status) tuples of
##        service.verify(...).report["verdicts"] equal the CLI's, and both
##        "severity" values are equal.
## [ ] 10. test_verify_attaches_triage_for_every_verdict: on EXAMPLES[0],
##        the (service.fm_id(failure_mode), subject) pairs of the report
##        verdicts are a subset of the (failure_mode, subject) pairs of
##        r.triage, and r.verification_ref starts with "vref:".
## [ ] 11. test_merged_verdicts_carry_short_id_and_status: every merged
##        verdict of EXAMPLES[0] has a short failure_mode ("FM" + digit),
##        its full failure_mode_name, and a structural_status.
## [ ] 12. Check: the step 6 command (Z3 runs: a few seconds per example).
##
## Guide 1.5
## [ ] 13. test_simulation_bounds_cannot_be_exceeded: service.simulate on
##        EXAMPLES[0] with n_runs=10_000, horizon=10, seed=1, then
##          | assert r["config"]["n_runs"] <= service.MAX_MC_RUNS
## [ ] 14. test_trajectory_bounds_cannot_be_exceeded: service.trajectory
##        on EXAMPLES[0] with horizon=5, seed=1, max_agents=10**6: the
##        config it ran with has max_agents == service.MAX_AGENTS, and
##        r["n_agents"] <= service.MAX_AGENTS.
## [ ] 15. test_simulation_options_reach_the_simulator: on
##        examples/axie_infinity.yaml (its FM6 is broken), n_runs=5,
##        horizon=10, seed=1: by default FM6 is not simulated and no
##        per-period values are recorded; with skip_non_fragile=False and
##        record_trajectories=True, FM6 is simulated and some result has
##        predicate_trajectories (the web form relies on both, guide 1.6).
## [ ] 16. Check: the step 6 command. ABM tests must stay under 60 s.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## Guide 1.4: json, subprocess and sys run the existing CLI (_cli_report).
import json
import subprocess
import sys
from pathlib import Path

import pytest

from te_platform import service

## Every case study becomes one test case (pytest "parametrize").
EXAMPLES = sorted(Path("examples").glob("*.yaml"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_validate_accepts_every_example(path):
    r = service.validate(path.read_text())
    assert r.valid, r.errors
    assert r.spec_hash and r.yaml


def test_validate_reports_schema_errors_instead_of_raising():
    r = service.validate("meta: {name: 3}\ntokens: not-a-list\n")
    assert not r.valid
    assert r.errors


def test_validate_rejects_non_mapping_yaml():
    r = service.validate("- just\n- a list\n")
    assert not r.valid


def test_validate_reports_yaml_syntax_errors():
    r = service.validate("tokens: [1, 2\n")
    assert not r.valid
    assert [e.location for e in r.errors] == [""]


def test_normalised_yaml_round_trips_to_the_same_hash():
    # validate(yaml of a normalised spec) must give the same hash: the YAML
    # downloaded from the form or chat describes exactly the same economy.
    first = service.validate(EXAMPLES[0].read_text())
    again = service.validate(first.yaml)
    assert again.spec_hash == first.spec_hash


## Guide 1.4: run the existing CLI in a subprocess, exactly as a user would
## (sys.executable: the same Python that runs pytest, no PATH lookup).
def _cli_report(path: Path) -> dict:
    out = subprocess.run(
        [sys.executable, "-m", "verifier.cli", str(path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(out.stdout)


## Guide 1.4: the golden test.
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_verify_matches_the_cli(path):
    ours = service.verify(path.read_text())
    cli = _cli_report(path)
    fields = ("failure_mode", "subject", "status")
    ours_keys = sorted(tuple(v[f] for f in fields) for v in ours.report["verdicts"])
    cli_keys = sorted(tuple(v[f] for f in fields) for v in cli["verdicts"])
    assert ours_keys == cli_keys
    assert ours.report["severity"] == cli["severity"]


## Guide 1.4: the report uses full names ("FM1: Token Oversupply /
## Inflation"), the triage short ids ("FM1"); service.fm_id bridges them.
## minimal_verdicts produces one entry per verdict the dispatcher produces,
## so every verdict can be merged with its structural status.
def test_verify_attaches_triage_for_every_verdict():
    r = service.verify(EXAMPLES[0].read_text())
    verdict_keys = {(service.fm_id(v["failure_mode"]), v["subject"]) for v in r.report["verdicts"]}
    triage_keys = {(t["failure_mode"], t["subject"]) for t in r.triage}
    assert verdict_keys <= triage_keys
    assert r.verification_ref.startswith("vref:")


## Guide 1.4: what tools/verify_run.py returns to users and the agent.
def test_merged_verdicts_carry_short_id_and_status():
    merged = service.merged_verdicts(service.verify(EXAMPLES[0].read_text()))
    assert merged
    for v in merged:
        assert v["failure_mode"].startswith("FM") and v["failure_mode"][2:].isdigit()
        assert v["failure_mode_name"].startswith(v["failure_mode"] + ":")
        assert v["structural_status"] is not None


## Guide 1.5: bounds live in the service, so no caller can bypass them.
def test_simulation_bounds_cannot_be_exceeded():
    r = service.simulate(EXAMPLES[0].read_text(), n_runs=10_000, horizon=10, seed=1)
    assert r["config"]["n_runs"] <= service.MAX_MC_RUNS


## Guide 1.5: an absurd agent count is clamped too. A short horizon keeps
## the test fast (the horizon clamp is the same min/max pattern).
def test_trajectory_bounds_cannot_be_exceeded():
    r = service.trajectory(EXAMPLES[0].read_text(), horizon=5, seed=1, max_agents=10**6)
    assert r["config"]["max_agents"] == service.MAX_AGENTS
    assert r["n_agents"] <= service.MAX_AGENTS


## Guide 1.5: the web form's two simulation options reach the simulator
## (the converted /api/simulate route of guide 1.6 passes them through).
## Axie Infinity's FM6 is structurally broken: skipped by default, simulated
## when skip_non_fragile is False. Tiny runs keep the test fast.
def test_simulation_options_reach_the_simulator():
    axie = Path("examples/axie_infinity.yaml").read_text()
    default = service.simulate(axie, n_runs=5, horizon=10, seed=1)
    every = service.simulate(
        axie, n_runs=5, horizon=10, seed=1, skip_non_fragile=False, record_trajectories=True
    )
    fm6 = [
        next(x for x in r["per_fm_results"] if x["failure_mode"] == "FM6") for r in (default, every)
    ]
    assert not fm6[0]["simulated"]
    assert fm6[1]["simulated"]
    assert not any(x["predicate_trajectories"] for x in default["per_fm_results"])
    assert any(x["predicate_trajectories"] for x in every["per_fm_results"])
