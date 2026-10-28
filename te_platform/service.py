## =============================================================================
## te_platform/service.py — the service layer: the ONLY bridge to the verifier
## =============================================================================
## GUIDE STEP   1.3 (validate), 1.4 (verify), 1.5 (the rest), 1.6 (Flask uses it)
## PURPOSE      A handful of plain functions that wrap the existing packages
##              `schema/` and `verifier/`:
##                validate, verify, merged_verdicts, minimal, simulate,
##                trajectory, flow_graph, export_cadcad
##              Each takes a spec (YAML text or dict) and returns a typed
##              Pydantic result or plain JSON data. They do no network or
##              database I/O.
## USED BY      tools/*.py (every MCP tool handler calls exactly one of these),
##              jobs/tasks.py (the simulations the worker runs),
##              elicitation/ranking.py (verify on partial specs),
##              webapp/app.py after guide step 1.6 (the Flask routes call these
##              instead of the verifier directly).
## DEPENDS ON   schema (TokenEconomy), verifier (verify, minimal_verdicts,
##              coherence_violations, abm.*), te_platform.hashing.
## WHY          Architecture D2: one place where the rules live, so the form,
##              the chat and external agents always get identical answers for
##              the same spec. Pure functions are easy to test (golden tests
##              against examples/*.yaml) and easy to reason about.
## ACTIVATE     1.3: uncomment the file (imports, models, helpers, validate).
##              1.4 and 1.5: their code is commented twice under "## Guide
##              1.4" / "## Guide 1.5" lines; toggle it again at that step.
##              Each with its golden tests in test_platform_service.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the public names
## and keyword arguments exactly as written here: tools, jobs and the web
## app call them (te_platform/README.md, contracts table). Activate
## hashing.py (guide 1.2) first.
##
## Guide 1.3
## [ ] 1. Before the first verifier import, add the mypy override for the
##        existing code (pyproject_additions.toml, "Type checking"), or
##        `uv run mypy te_platform` reports the old code's own problems.
## [ ] 2. Imports at the top: `Any`; `yaml`; `BaseModel`, `Field`,
##        `ValidationError` (pydantic); `TokenEconomy` (schema);
##        `coherence_violations` (verifier.elicitation); and
##          | from te_platform import hashing
##        This is the ONLY te_platform file that imports `verifier`.
## [ ] 3. Result models, each with a one-line docstring: `SchemaProblem`
##        (location: str, message: str) and `ValidationResult` (valid:
##        bool; errors: list[SchemaProblem] and coherence_issues:
##        list[dict[str, Any]], both default empty; then spec_hash,
##        normalised_spec, yaml, all optional, default None).
## [ ] 4. Private helpers: `_parse(spec)` (YAML text -> dict with
##        yaml.safe_load, never yaml.load; ValueError if the top level is
##        not a mapping; a dict is returned as it is), `_to_model(spec)`
##        (TokenEconomy.model_validate of _parse) and `_dump_yaml(te)`:
##          | yaml.safe_dump(te.model_dump(mode="json", exclude_none=True),
##          |                sort_keys=False, allow_unicode=True)
##        (the same dump as webapp/app.py ir_to_yaml_endpoint).
## [ ] 5. `validate(spec) -> ValidationResult`. It never raises: catch
##        ValidationError, ValueError and yaml.YAMLError and return
##        valid=False with one SchemaProblem per Pydantic error (location =
##        the "loc" parts joined with ".", built with a list comprehension)
##        or one with location "" for the other two. When valid: dump the
##        model (mode="json", exclude_none=True) and hash THAT normalised
##        dict with hashing.spec_hash; also fill coherence_issues and yaml.
## [ ] 6. Check: activate the guide 1.3 tests of
##        tests/platform_tests/test_platform_service.py, then
##          | uv run pytest tests/platform_tests/test_platform_service.py -q
##          | uv run mypy te_platform
##
## Guide 1.4
## [ ] 7. Imports, as MODULES, at the start of the third-party group:
##          | import verifier
##          | import verifier.config
##          | import verifier.minimal
##        The code then says verifier.verify(...),
##        verifier.minimal.minimal_verdicts(...): it is always clear which
##        call goes to the verifier, and the service's own functions
##        `verify` and `minimal` need no renamed imports.
## [ ] 8. `VerificationResult` model, after ValidationResult:
##        verification_ref: str, spec_hash: str, report: dict[str, Any],
##        triage: list[dict[str, Any]].
## [ ] 9. `fm_id(failure_mode: str) -> str`: the text before the first ":",
##        stripped ("FM1: Token Oversupply / Inflation" -> "FM1").
## [ ] 10. `verify(spec, config: verifier.config.VerifierConfig | None =
##        None)`: it raises on an invalid spec (callers validate first).
##        Hash the normalised spec as in validate, call
##        verifier.verify(te, config=config) and
##        verifier.minimal.minimal_verdicts(te, config=config), build the ref:
##          | hashing.verification_ref(s_hash, hashing.verifier_version(),
##          |                          hashing.config_hash(config))
## [ ] 11. `merged_verdicts(result)`: index the triage by (failure_mode,
##        subject); for each report verdict add failure_mode (short id),
##        failure_mode_name (full name), structural_status and
##        minimum_param_shift. See its docstring.
## [ ] 12. Check: activate the guide 1.4 tests in test_platform_service.py
##        and run the same two commands as in step 6.
##
## Guide 1.5
## [ ] 13. Imports, between `from schema ...` and `from verifier.elicitation
##        ...` (where isort puts them): `SimulationConfig`,
##        `export_cadcad_config`, `run_explore`, `run_simulation`
##        (verifier.abm) and `build_flow_graph` (verifier.abm.flow_graph).
## [ ] 14. The bounds, at the start of the 1.5 section: MAX_MC_RUNS = 200,
##        MAX_MC_HORIZON = 500, MAX_TRAJECTORY_HORIZON = 10_000,
##        MAX_AGENTS = 200 (moved from webapp/app.py), MAX_CADCAD_RUNS =
##        5000 and MAX_CADCAD_HORIZON = 5000 (see the `##` note there).
## [ ] 15. `minimal(spec, config=None)`: minimal_verdicts, dumped to dicts.
## [ ] 16. `simulate(spec, *, n_runs, horizon, seed, failure_modes=None,
##        skip_non_fragile=True, record_trajectories=False)`: clamp every
##        number into [1, MAX_...] when building the SimulationConfig,
##          | n_runs=min(max(1, n_runs), MAX_MC_RUNS),
##        pass the two flags into it unchanged (the web form sets them,
##        guide 1.6), compute the triage with
##        verifier.minimal.minimal_verdicts(te) (paper defaults, like every
##        platform verification: see the `##` note above simulate), keep
##        only the verdicts whose failure_mode is in failure_modes (when
##        given), then run_simulation(te, verdicts=..., config=cfg).
## [ ] 17. `trajectory(spec, *, horizon, seed, max_agents)`: n_runs=1,
##        clamped horizon and max_agents (None stays None), run_explore.
## [ ] 18. `flow_graph(spec)`: build_flow_graph of the model.
##        `export_cadcad(spec, *, n_runs=500, horizon=260, seed=None)`:
##        n_runs clamped into [1, MAX_CADCAD_RUNS], horizon into
##        [1, MAX_CADCAD_HORIZON], export_cadcad_config.
## [ ] 19. Check: activate the guide 1.5 tests and run the commands of
##        step 6. ABM tests must stay under 60 s.
##
## Guide 1.6
## [ ] 20. Nothing more to write here: change the Flask routes to call
##        these functions, following webapp/service_adapter_notes.md.
##        Check: the existing webapp tests pass unchanged:
##          | uv run pytest tests/test_webapp_routes.py -q
##          | uv run pytest tests/test_expr_webapp.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

# --- Imports -----------------------------------------------------------------
# The `schema` and `verifier` imports are the reason this file exists: no
# other file in te_platform imports from `verifier` directly.
from typing import Any

# Guide 1.4: the verifier modules used by verify() and minimal(). Imported
# as modules: calls read verifier.verify(...), so they never clash with this
# file's own verify() and minimal().
import verifier
import verifier.config
import verifier.minimal
import yaml
from pydantic import BaseModel, Field, ValidationError
from schema import TokenEconomy

# Guide 1.5: the agent-based simulator (verifier/abm) for the remaining
# functions.
from verifier.abm import SimulationConfig, export_cadcad_config, run_explore, run_simulation
from verifier.abm.flow_graph import build_flow_graph
from verifier.elicitation import coherence_violations

from te_platform import hashing


# --- Result models -------------------------------------------------------------
# Every function returns one of these (or plain JSON data). Tools put them
# (or parts of them) into their output models; the database stores them as
# JSONB.
class SchemaProblem(BaseModel):
    """One schema validation problem, simplified from Pydantic's error list."""

    location: str      # e.g. "tokens.0.emission_rules.1.function"
    message: str
class ValidationResult(BaseModel):
    """Outcome of validate(): schema errors, or the normalised spec."""

    valid: bool
    errors: list[SchemaProblem] = Field(default_factory=list)
    # Coherence issues from verifier.elicitation (severity, location, message, suggestion).
    coherence_issues: list[dict[str, Any]] = Field(default_factory=list)
    # Only set when valid:
    spec_hash: str | None = None
    normalised_spec: dict[str, Any] | None = None
    yaml: str | None = None
# --- Helpers (private: names start with "_") ------------------------------------
def _parse(spec: str | dict[str, Any]) -> dict[str, Any]:
    """Accept YAML text or an already-parsed dict.

    yaml.safe_load builds only plain data (dicts, lists, strings, numbers):
    it can never create arbitrary Python objects (guide §2.2).
    """
    if isinstance(spec, str):
        data = yaml.safe_load(spec)
        if not isinstance(data, dict):
            # ValueError, not TypeError: a YAML list is bad USER INPUT, which
            # validate() reports like any other validation problem.
            raise ValueError("A spec must be a YAML mapping at the top level.")  # noqa: TRY004
        return data
    return spec
def _to_model(spec: str | dict[str, Any]) -> TokenEconomy:
    """Parse and validate into the TE-IR model.

    Raises on invalid input; only call it after validate() said the spec
    is valid.
    """
    return TokenEconomy.model_validate(_parse(spec))


def _dump_yaml(te: TokenEconomy) -> str:
    """Serialise like the web app does (webapp/app.py, ir_to_yaml_endpoint).

    So YAML downloaded from the form and from the chat is identical.
    """
    data = te.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


# --- 1.3 validate --------------------------------------------------------------
def validate(spec: str | dict[str, Any]) -> ValidationResult:
    """Check a spec against the schema and the coherence rules.

    Never raises for bad input: problems are returned in the result, because
    an invalid spec is a normal situation during an interview, not a bug.
    """
    try:
        te = _to_model(spec)
    except (ValidationError, ValueError, yaml.YAMLError) as exc:
        if isinstance(exc, ValidationError):
            problems = [
                SchemaProblem(location=".".join(str(p) for p in err["loc"]), message=err["msg"])
                for err in exc.errors()
            ]
        else:
            problems = [SchemaProblem(location="", message=str(exc))]
        return ValidationResult(valid=False, errors=problems)

    normalised = te.model_dump(mode="json", exclude_none=True)
    return ValidationResult(
        valid=True,
        coherence_issues=[i.model_dump(mode="json") for i in coherence_violations(te)],
        spec_hash=hashing.spec_hash(normalised),
        normalised_spec=normalised,
        yaml=_dump_yaml(te),
    )


#--- 1.4 verify ----------------------------------------------------------------
#Guide 1.4: the result of verify().
class VerificationResult(BaseModel):
    """Outcome of verify(): the full report plus the structural triage."""

# Guide 1.4: the fields. `report` is the full verifier report
# (verdicts, counterexamples, recommendations...); `triage` the
# structural triage per failure mode/subject, from minimal_verdicts.
    verification_ref: str
    spec_hash: str
    report: dict[str, Any]
    triage: list[dict[str, Any]]


# Guide 1.4: failure-mode ids. Checked against the real verifier: the full
# report names failure modes in full ("FM1: Token Oversupply / Inflation"),
# while the triage (minimal_verdicts) and the simulator use the short id
# ("FM1"). Everything in te_platform uses the short id; tools keep the full
# name in a separate field for display.

def fm_id(failure_mode: str) -> str:
    """Return the short id of a failure mode: "FM1: Token Oversupply" -> "FM1"."""
    return failure_mode.split(":", 1)[0].strip()

# Guide 1.4: run the formal verifier AND the structural triage on one spec.
# Two calls into the verifier:
# - verifier.verify(): the full report the users see (verdict,
#   counterexample, recommendations, risk band) per failure mode;
# - minimal_verdicts(): sound / fragile / broken per failure mode, which
#   drives `suggested_next` (simulate only fragile/inconclusive ones).
# Both are CPU-bound (Z3). Callers in async code must run this function in a
# worker thread (registry/pipeline.py does that), never directly. It raises
# on an invalid spec: callers validate() first.
def verify(
    spec: str | dict[str, Any], config: verifier.config.VerifierConfig | None = None,
) -> VerificationResult:
    """Verify one spec; see the comment above for what is computed."""
    te = _to_model(spec)
    normalised = te.model_dump(mode="json", exclude_none=True)
    s_hash = hashing.spec_hash(normalised)
    report: verifier.Report = verifier.verify(te, config=config)
    triage = verifier.minimal.minimal_verdicts(te, config=config)
    ref = hashing.verification_ref(
        s_hash, hashing.verifier_version(), hashing.config_hash(config),
    )
    return VerificationResult(
        verification_ref=ref,
        spec_hash=s_hash,
        report=report.model_dump(mode="json"),
        triage=[t.model_dump(mode="json") for t in triage],
    )


# Guide 1.4: one list the users (and the agent) read: each verdict of the
# full report, merged with its structural status from the triage. The
# report names failure modes in full ("FM1: Token Oversupply / Inflation"),
# the triage by short id ("FM1"): they are matched on (fm_id, subject), and
# the merged verdict carries the SHORT id (the simulator and suggested_next
# use it) plus failure_mode_name for people. Used by tools/verify_run.py
# (its output, which is also what is stored and rendered in reports) and by
# the report tests.
def merged_verdicts(result: VerificationResult) -> list[dict[str, Any]]:
    """Merge each verdict of the full report with its structural status."""
    triage = {(t["failure_mode"], t["subject"]): t for t in result.triage}
    merged = []
    for v in result.report["verdicts"]:
        short = fm_id(v["failure_mode"])
        t = triage.get((short, v["subject"]), {})
        merged.append({
            **v,
            "failure_mode": short,
            "failure_mode_name": v["failure_mode"],
            "structural_status": t.get("structural_status"),
            "minimum_param_shift": t.get("minimum_param_shift"),
        })
    return merged


## --- 1.5 the remaining functions ------------------------------------------------

## Guide 1.5: input bounds, moved here from webapp/app.py so EVERY caller gets
## them: the web form, MCP clients, and the agent. They protect the server
## from requests that would run for hours. Keep them in sync with the ABM
## workload budget (ABM-heavy tests must stay under 60 s).
## The cadCAD bounds are larger (and its default of 500 runs exceeds
## MAX_MC_RUNS) on purpose, as in the web app: export_cadcad() runs nothing,
## it only WRITES these numbers into a configuration that the user runs on
## their own machine with cadCAD.
MAX_MC_RUNS = 200
MAX_MC_HORIZON = 500
MAX_TRAJECTORY_HORIZON = 10_000
MAX_AGENTS = 200
MAX_CADCAD_RUNS = 5000
MAX_CADCAD_HORIZON = 5000


## Guide 1.5: the triage alone (tool verify.minimal.v1).
def minimal(
    spec: str | dict[str, Any], config: verifier.config.VerifierConfig | None = None,
) -> list[dict[str, Any]]:
    """Return only the reachability triage, as plain JSON data."""
    verdicts = verifier.minimal.minimal_verdicts(_to_model(spec), config=config)
    return [v.model_dump(mode="json") for v in verdicts]


## Guide 1.5: Monte Carlo agent-based simulation (tool sim.monte_carlo.v1).
## Slow: only ever called from the job worker (jobs/tasks.py). The bounds
## are applied here, so no caller can bypass them. The triage that decides
## which failure modes to simulate is recomputed here with the paper's
## default configuration, the same one every platform verification uses
## (tools/verify_run.py calls verify(spec) without a config, so its
## verification_ref carries config_hash(None)): the simulation and the
## verification the user saw always agree on which modes are fragile.
## `failure_modes` then restricts the work to the ones the caller asks for
## (the policy suggests the inconclusive/fragile ones).
## The two flags exist for the web form (webapp/app.py, /api/simulate, guide
## 1.6), which has always offered them: skip_non_fragile=False also simulates
## the failure modes the verifier proved sound or broken (a sanity check of
## the verifier), and record_trajectories=True keeps each safety predicate's
## value per period, for the charts. Their defaults are what the platform
## uses: the MCP tool and the job worker don't pass them.
def simulate(
    spec: str | dict[str, Any],
    *,
    n_runs: int,
    horizon: int,
    seed: int | None,
    failure_modes: list[str] | None = None,
    skip_non_fragile: bool = True,
    record_trajectories: bool = False,
) -> dict[str, Any]:
    """Run the Monte Carlo simulation; see the comment above."""
    te = _to_model(spec)
    cfg = SimulationConfig(
        n_runs=min(max(1, n_runs), MAX_MC_RUNS),
        horizon_periods=min(max(1, horizon), MAX_MC_HORIZON),
        seed=seed,
        skip_non_fragile=skip_non_fragile,
        record_trajectories=record_trajectories,
    )
    verdicts = verifier.minimal.minimal_verdicts(te)
    if failure_modes:
        wanted = set(failure_modes)
        verdicts = [v for v in verdicts if v.failure_mode in wanted]
    report = run_simulation(te, verdicts=verdicts, config=cfg)
    return report.model_dump(mode="json")


## Guide 1.5: one seeded run, period by period (tool sim.trajectory.v1).
## max_agents=None lets the simulator choose the number of agents.
def trajectory(
    spec: str | dict[str, Any], *, horizon: int, seed: int | None, max_agents: int | None,
) -> dict[str, Any]:
    """Run one seeded simulation and return every period's snapshot."""
    te = _to_model(spec)
    cfg = SimulationConfig(
        n_runs=1,
        horizon_periods=min(max(1, horizon), MAX_TRAJECTORY_HORIZON),
        seed=seed,
        max_agents=None if max_agents is None else min(max(1, max_agents), MAX_AGENTS),
    )
    return run_explore(te, sim_config=cfg).model_dump(mode="json")


## Guide 1.5: the declared flow graph (tool graph.flow.v1). Fast: nothing
## is simulated.
def flow_graph(spec: str | dict[str, Any]) -> dict[str, Any]:
    """Return the declared flow graph of the spec."""
    return build_flow_graph(_to_model(spec))


## Guide 1.5: cadCAD export (tool export.cadcad.v1).
def export_cadcad(
    spec: str | dict[str, Any],
    *,
    n_runs: int = 500,
    horizon: int = 260,
    seed: int | None = None,
) -> dict[str, Any]:
    """Return a cadCAD configuration for the spec."""
    cfg = SimulationConfig(
        n_runs=min(max(1, n_runs), MAX_CADCAD_RUNS),
        horizon_periods=min(max(1, horizon), MAX_CADCAD_HORIZON),
        seed=seed,
    )
    return export_cadcad_config(_to_model(spec), sim_config=cfg)
