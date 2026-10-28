"""Flask app entry point.

Run:
    pip install -e ".[webapp]"
    python -m webapp.app

then open http://127.0.0.1:5000.
"""

## =============================================================================
## Implementation guide, steps 1.6, 9.0, 12.3 (docs/agent-implementation-guide.md)
## =============================================================================
## Existing, working code. Guide 1.6 is done; the commented blocks that
## remain are later steps, to uncomment when you reach them:
##
## Guide 1.6 (done): the routes call te_platform.service instead of schema/
##   and verifier/ directly (webapp/service_adapter_notes.md has the
##   route-by-route table); validation, verification and the input bounds
##   live in the service.
##   What stays the same: URLs, request fields, JSON answers, status codes
##   and the error prefixes the pages show ("failed to parse TE-IR", ...).
##   What changes, on purpose (explained where it happens):
##   - error texts list each problem as "location: message" instead of
##     Pydantic's multi-line dump;
##   - a request whose "yaml" is not text, whose "ir" is not a JSON object,
##     or whose body is not a JSON object gets 400 (before: a 500, or a
##     JSON object sent as "yaml" was even accepted);
##   - /api/verify and /api/build-and-verify also compute the structural
##     triage (service.verify always does): a little more work per request
##     (under 0.3 s on the examples), same answer.
##
## Guide 9.0 (lines commented TWICE, `# # `): register the login and chat
##   pages of webapp/chat_routes.py. Leave them until you reach step 9.0.
##
## Guide 12.3 (lines commented TWICE): behind Caddy, read the client's real
##   address from X-Forwarded-For (ProxyFix), so the per-IP rate limiter
##   below counts each user, not Caddy. Leave them until step 12.3.
## =============================================================================

from __future__ import annotations

import time as _time
from collections import defaultdict as _defaultdict
from pathlib import Path
from typing import Any, NoReturn

from flask import Flask, abort, jsonify, make_response, render_template, request
from flask.typing import ResponseReturnValue

## Guide 12.3: ProxyFix, used right after `app` is created.
from werkzeug.middleware.proxy_fix import ProxyFix

from schema import (
    ActionKind,
    AsymptoticFamily,
    Archetype,
    BurnTriggerKind,
    CirculationSpeed,
    ContributionVerification,
    ControllingActor,
    EmissionTriggerKind,
    FunctionSign,
    GovernanceMaturity,
    GovernanceType,
    HoldingIncentiveMechanism,
    PopulationEventKind,
    RedemptionMechanism,
    SanctionKind,
    ThresholdOp,
    ThresholdVar,
    TokenEarningMechanism,
    TokenFunction,
    Topology,
    ValueAnchor,
    VoteWeighting,
)
from verifier.paper import ALL_CONDITIONS

# Guide 1.6: the service layer (te_platform/service.py, guide 1.3-1.5). The
# routes call it instead of schema/ and verifier/ directly.
from te_platform import service

## Guide 9.0: the blueprint with the login (9.0) and chat (9.1) pages.
from webapp.chat_routes import chat_bp


app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

## Guide 9.0: attach the pages of webapp/chat_routes.py (GET /login, and from
## 9.1 GET /chat) to this app. They use this app's templates/ and static/.
app.register_blueprint(chat_bp)

## Guide 12.3: behind Caddy every request comes from Caddy's address, so
## request.remote_addr would be the same for all users and they would share
## one rate-limit bucket (_rate_limit below). ProxyFix (from Werkzeug, the
## library Flask is built on) replaces it with the address Caddy writes into
## X-Forwarded-For. x_for=1: trust exactly ONE proxy hop, the last one,
## which is Caddy; anything a client wrote into the header itself sits
## further left and is ignored. gunicorn listens only on the edge network
## behind Caddy (compose.yml), so no other hop can reach the app.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)  # type: ignore[method-assign]

# --- Hardening for public deployment ---------------------------------------
# Cap request bodies — token-economy models are a few KB; reject anything big.
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024  # 512 KB

# In-memory per-IP rate limit on the compute (POST) endpoints, so one client
# cannot flood the Z3 solver. Fixed 60 s window. (gunicorn --timeout is the
# backstop for any single long-running request.)
## Guide 1.6 / 6.3: this limiter STAYS. Its counts live in one process (each
## gunicorn worker counts separately, and they reset on restart), so it is a
## per-worker backstop. The Redis quotas of guide 6.3 count per principal
## (an API key or a logged-in user) for MCP and agent calls; the web form
## has no principal. The per-IP limit across all processes comes from Caddy
## (deploy/caddy/Caddyfile, rate_limit; in development from guide 9.0).
_RL_WINDOW = 60   # seconds
_RL_MAX = 30      # POST requests per window per IP
_rl_hits: dict[str, list[float]] = _defaultdict(list)


@app.before_request
def _rate_limit():  # type: ignore[no-untyped-def]
    if request.method != "POST":
        return None
    ip = request.remote_addr or "unknown"
    now = _time.monotonic()
    hits = [t for t in _rl_hits[ip] if now - t < _RL_WINDOW]
    hits.append(now)
    _rl_hits[ip] = hits
    if len(hits) > _RL_MAX:
        return jsonify(error="rate_limited"), 429
    return None


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


# Guide 1.6: helpers shared by the converted routes. -------------------------
# The request fields that carry a spec: what type each must have, and the
# error prefix the old routes used. The pages show these texts, and a test
# checks that an invalid "ir" mentions "validate". `kind()` is the default
# when the field is missing: str() is "" and dict() is {}, as before.
_SPEC_FIELDS: dict[str, tuple[type, str]] = {
    "yaml": (str, "failed to parse TE-IR"),
    "ir": (dict, "failed to validate TE-IR"),
}


def _bad_request(message: str) -> NoReturn:
    """Stop the request with HTTP 400 and {"error": message}.

    The pages' JavaScript (form.js, app.js, explore.js) reads the `error`
    key. abort() raises, so the route's remaining code never runs.
    """
    abort(make_response(jsonify(error=message), 400))


def _valid_spec(body: Any, key: str) -> tuple[str | dict[str, Any], service.ValidationResult]:
    """Return the spec in body[key] and its validation, or stop with HTTP 400.

    service.validate accepts YAML text OR a parsed dict, so the type is
    checked first: without that, a JSON object sent as "yaml" would be
    accepted, and a text sent as "ir" would be parsed as YAML.
    """
    kind, prefix = _SPEC_FIELDS[key]
    spec = body.get(key, kind()) if isinstance(body, dict) else None
    if not isinstance(spec, kind):
        wanted = "text" if kind is str else "a JSON object"
        _bad_request(f"{prefix}: the request body must be a JSON object "
                     f"whose '{key}' field is {wanted}")
    result = service.validate(spec)
    if not result.valid:
        problems = "; ".join(
            f"{e.location}: {e.message}" if e.location else e.message for e in result.errors
        )
        _bad_request(f"{prefix}: {problems}")
    return spec, result


def _optional_int(body: dict[str, Any], key: str) -> int | None:
    """Read an optional integer field; a missing field, null and "" mean None.

    int() raises ValueError/TypeError on anything else that is not a
    number; the routes turn that into HTTP 400 "invalid config".
    """
    value = body.get(key)
    return None if value in (None, "") else int(value)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index() -> str:
    """Render the form-driven questionnaire (default landing page).

    Walks the user through the Roadmap docx Groups 1–5 + NFRs as a
    structured form, with "why we ask" copy pulled from `paper.py`
    next to each question. The verdict panel stays visible after the
    first Verify so the user can iteratively tweak a field and
    re-verify without losing context.
    """
    examples = sorted(p.stem for p in EXAMPLES_DIR.glob("*.yaml"))
    return render_template(
        "form.html",
        examples=examples,
        conditions=ALL_CONDITIONS,
        token_functions=[e.value for e in TokenFunction],
        value_anchors=[e.value for e in ValueAnchor],
        earning_mechanisms=[e.value for e in TokenEarningMechanism],
        holding_incentives=[e.value for e in HoldingIncentiveMechanism],
        verification_choices=[e.value for e in ContributionVerification],
        redemption_choices=[e.value for e in RedemptionMechanism],
        emission_triggers=[e.value for e in EmissionTriggerKind],
        burn_triggers=[e.value for e in BurnTriggerKind],
        function_signs=[e.value for e in FunctionSign],
        # Mint rules can only adopt non-negative signs. always_negative is
        # a burn-side convention; allowing it on a mint dropdown lets the
        # user describe a mathematically impossible design.
        mint_signs=[
            e.value for e in FunctionSign if e.value != "always_negative"
        ],
        # Condition predicate enums — used by both Rule.regimes and
        # RuleTrigger.conditions form blocks.
        threshold_vars=[e.value for e in ThresholdVar],
        threshold_ops=[e.value for e in ThresholdOp],
        asymptotic_families=[e.value for e in AsymptoticFamily],
        archetypes=[e.value for e in Archetype],
        circulation_speeds=[e.value for e in CirculationSpeed],
        governance_maturities=[e.value for e in GovernanceMaturity],
        topologies=[e.value for e in Topology],
        sanction_kinds=[e.value for e in SanctionKind],
        governance_types=[e.value for e in GovernanceType],
        controlling_actors=[e.value for e in ControllingActor],
        agent_roles=["contributor", "consumer", "governance_only", "observer"],
        vote_weightings=[e.value for e in VoteWeighting],
        action_kinds=[e.value for e in ActionKind],
        population_event_kinds=[e.value for e in PopulationEventKind],
        distribution_kinds=[
            "uniform", "normal", "lognormal", "bernoulli", "poisson", "beta",
        ],
    )


@app.route("/yaml")
def yaml_editor() -> str:
    """Advanced mode: paste/edit a TE-IR YAML directly.

    Original first-iteration UI; preserved for users who want full
    control over the IR (e.g. for multi-token systems, regime switches,
    or rare asymptotic families the form doesn't surface).
    """
    examples = sorted(p.stem for p in EXAMPLES_DIR.glob("*.yaml"))
    return render_template(
        "index.html",
        examples=examples,
        conditions=ALL_CONDITIONS,
        # Enums for the UI to render dropdowns
        token_functions=[e.value for e in TokenFunction],
        value_anchors=[e.value for e in ValueAnchor],
        earning_mechanisms=[e.value for e in TokenEarningMechanism],
        holding_incentives=[e.value for e in HoldingIncentiveMechanism],
        verification_choices=[e.value for e in ContributionVerification],
        redemption_choices=[e.value for e in RedemptionMechanism],
        emission_triggers=[e.value for e in EmissionTriggerKind],
        burn_triggers=[e.value for e in BurnTriggerKind],
        function_signs=[e.value for e in FunctionSign],
        # Mint rules can only adopt non-negative signs. always_negative is
        # a burn-side convention; allowing it on a mint dropdown lets the
        # user describe a mathematically impossible design.
        mint_signs=[
            e.value for e in FunctionSign if e.value != "always_negative"
        ],
        # Condition predicate enums — used by both Rule.regimes and
        # RuleTrigger.conditions form blocks.
        threshold_vars=[e.value for e in ThresholdVar],
        threshold_ops=[e.value for e in ThresholdOp],
        asymptotic_families=[e.value for e in AsymptoticFamily],
        archetypes=[e.value for e in Archetype],
        circulation_speeds=[e.value for e in CirculationSpeed],
        governance_maturities=[e.value for e in GovernanceMaturity],
        topologies=[e.value for e in Topology],
        sanction_kinds=[e.value for e in SanctionKind],
        governance_types=[e.value for e in GovernanceType],
        controlling_actors=[e.value for e in ControllingActor],
    )


@app.route("/api/example/<name>")
def example(name: str) -> dict:
    """Return the YAML text of an example."""
    p = EXAMPLES_DIR / f"{name}.yaml"
    if not p.exists():
        return jsonify(error=f"example '{name}' not found"), 404
    return jsonify(yaml=p.read_text(encoding="utf-8"))


# Guide 1.6: /api/verify through the service. Validation first (a 400 with
# the problems), then service.verify, which runs the same verifier.verify
# and also the triage; the page receives the same Report JSON as before.
# The ORIGINAL text is verified (not the normalised copy), exactly what the
# CLI `te-verify` would read.
@app.route("/api/verify", methods=["POST"])
def verify_endpoint() -> ResponseReturnValue:
    """Accept a YAML body, validate it, run the verifier, return the Report."""
    spec, _ = _valid_spec(request.get_json(force=True), "yaml")
    return jsonify(service.verify(spec).report)


# Guide 1.6: /api/build-and-verify through the service. The YAML offered for
# download is validate()'s, made with the same dump as before (service.py,
# _dump_yaml), so it is byte-identical.
@app.route("/api/build-and-verify", methods=["POST"])
def build_and_verify() -> ResponseReturnValue:
    """Accept the form's JSON IR, validate it, verify it, return Report + YAML."""
    spec, checked = _valid_spec(request.get_json(force=True), "ir")
    return jsonify(report=service.verify(spec).report, yaml=checked.yaml)


# Guide 1.6: /api/yaml-to-ir through the service. normalised_spec is the
# same model_dump(mode="json", exclude_none=True) the old route returned.
@app.route("/api/yaml-to-ir", methods=["POST"])
def yaml_to_ir() -> ResponseReturnValue:
    """Convert a YAML TE-IR into the validated JSON dict the form loads."""
    _, checked = _valid_spec(request.get_json(force=True), "yaml")
    return jsonify(ir=checked.normalised_spec)


@app.route("/api/conditions")
def conditions() -> dict:
    """Return the paper-canonical FM explanations as JSON.

    Used by the UI to render "why we ask" tooltips and verdict
    annotations. Each condition includes plain_statement,
    why_it_matters, real_world_signal, design_knobs, elicitation_questions.
    """
    out: dict[str, dict] = {}
    for fm_id, cond in ALL_CONDITIONS.items():
        out[fm_id] = {
            "fm_id": cond.fm_id,
            "name": cond.name,
            "paper_section": cond.paper_section,
            "paper_equations": list(cond.paper_equations),
            "sustainability_ascii": cond.sustainability_ascii,
            "violation_ascii": cond.violation_ascii,
            "plain_statement": cond.plain_statement,
            "why_it_matters": cond.why_it_matters,
            "real_world_signal": cond.real_world_signal,
            "design_knobs": [list(t) for t in cond.design_knobs],
            "elicitation_questions": list(cond.elicitation_questions),
            "nfr_reweightings": [list(t) for t in cond.nfr_reweightings],
            # Fix C — variable glossary fed to the verdict card so every
            # symbol used in the formal condition has an inline plain-
            # English gloss.
            "variables": [
                {
                    "symbol": v.symbol,
                    "name": v.name,
                    "description": v.description,
                    "units": v.units,
                    "domain": v.domain,
                }
                for v in cond.variables
            ],
            "critical_values": [
                {
                    "parameter": cv.parameter,
                    "formula_ascii": cv.formula_ascii,
                    "direction": cv.direction,
                    "explanation": cv.explanation,
                }
                for cv in cond.critical_values
            ],
        }
    return jsonify(out)


# Phase L2: the /simulate page was removed from the UI to simplify the
# pipeline to two steps (verifier + ABM trajectory). The JSON
# ``/api/simulate`` endpoint below is retained — the explore page and
# the cadCAD export still consume it under the hood.


# Guide 1.6: /api/minimal-verdicts through the service (service.minimal
# returns the same ReachabilityVerdict dicts).
@app.route("/api/minimal-verdicts", methods=["POST"])
def minimal_verdicts_endpoint() -> ResponseReturnValue:
    """Return the minimal (reachability) verifier output for a YAML spec."""
    spec, _ = _valid_spec(request.get_json(force=True), "yaml")
    return jsonify(verdicts=service.minimal(spec))


# Guide 1.6: /api/simulate through the service. The route only reads the
# request: the BOUNDS (n_runs <= 200, horizon <= 500) now live in
# service.simulate, so they also hold for MCP clients and the agent. The
# two flags are passed through (service.simulate has them since guide 1.5).
# A number that isn't a number is still 400 "invalid config"; a failure
# inside the simulator is still 500 "simulation failed".
@app.route("/api/simulate", methods=["POST"])
def simulate_endpoint() -> ResponseReturnValue:
    """Run the reference ABM and return the simulation report.

    Body: yaml; n_runs (default 200), horizon_periods (default 260), seed,
    skip_non_fragile (default true), record_trajectories (default false).
    The service clamps the numbers.
    """
    body = request.get_json(force=True)
    spec, _ = _valid_spec(body, "yaml")
    try:
        n_runs = int(body.get("n_runs", 200))
        horizon = int(body.get("horizon_periods", 260))
        seed = _optional_int(body, "seed")
    except (ValueError, TypeError) as e:
        return jsonify(error=f"invalid config: {e}"), 400
    try:
        report = service.simulate(
            spec,
            n_runs=n_runs,
            horizon=horizon,
            seed=seed,
            skip_non_fragile=bool(body.get("skip_non_fragile", True)),
            record_trajectories=bool(body.get("record_trajectories", False)),
        )
    except Exception as e:
        return jsonify(error=f"simulation failed: {e}"), 500
    return jsonify(report)


@app.route("/explore")
def explore_page() -> str:
    """Render the single-trajectory explore page.

    Unlike /simulate (Monte Carlo aggregates), /explore runs one
    seeded trajectory and renders per-period detail — agent balances,
    trade graph, action mix, live Gini — with a period scrubber so
    the user can watch the system evolve.
    """
    examples = sorted(p.stem for p in EXAMPLES_DIR.glob("*.yaml"))
    return render_template("explore.html", examples=examples)


# Guide 1.6: /api/explore through the service (service.trajectory). The
# horizon bound (10 000) and the max_agents bound (200) now live in the
# service.
@app.route("/api/explore", methods=["POST"])
def explore_endpoint() -> ResponseReturnValue:
    """Run one trajectory and return the per-period snapshot series.

    Body: yaml; horizon_periods (default 100, at most 10 000), seed,
    max_agents (at most 200; missing means: chosen by the simulator).
    """
    body = request.get_json(force=True)
    spec, _ = _valid_spec(body, "yaml")
    try:
        horizon = int(body.get("horizon_periods", 100))
        seed = _optional_int(body, "seed")
        max_agents = _optional_int(body, "max_agents")
    except (ValueError, TypeError) as e:
        return jsonify(error=f"invalid config: {e}"), 400
    try:
        report = service.trajectory(spec, horizon=horizon, seed=seed, max_agents=max_agents)
    except Exception as e:
        return jsonify(error=f"explore failed: {e}"), 500
    return jsonify(report)


# Guide 1.6: /api/ir-to-yaml through the service. It runs on every keystroke
# of the form's preview: validate() adds the coherence checks and the hash,
# a few milliseconds, and its `yaml` is the same dump as before.
@app.route("/api/ir-to-yaml", methods=["POST"])
def ir_to_yaml_endpoint() -> ResponseReturnValue:
    """Validate the form's JSON IR and return it as YAML (no verification)."""
    _, checked = _valid_spec(request.get_json(force=True), "ir")
    return jsonify(yaml=checked.yaml)


# Guide 1.6: /api/flow-graph through the service (service.flow_graph calls
# the same build_flow_graph; the import inside the old function goes away).
@app.route("/api/flow-graph", methods=["POST"])
def flow_graph_endpoint() -> ResponseReturnValue:
    """Return the declared-flow graph (Cytoscape JSON) of a YAML spec."""
    spec, _ = _valid_spec(request.get_json(force=True), "yaml")
    try:
        payload = service.flow_graph(spec)
    except Exception as e:
        return jsonify(error=f"flow-graph build failed: {e}"), 500
    return jsonify(payload)


# Guide 1.6: /api/cadcad-export through the service. Its bounds (5000 runs,
# 5000 periods) are larger than the simulation's on purpose: nothing runs
# here, the numbers are only written into the exported configuration
# (service.py, the note above MAX_MC_RUNS).
@app.route("/api/cadcad-export", methods=["POST"])
def cadcad_export_endpoint() -> ResponseReturnValue:
    """Return the cadCAD-compatible configuration for a YAML spec.

    Body: yaml; n_runs (default 500), horizon_periods (default 260), seed.
    """
    body = request.get_json(force=True)
    spec, _ = _valid_spec(body, "yaml")
    try:
        n_runs = int(body.get("n_runs", 500))
        horizon = int(body.get("horizon_periods", 260))
        seed = _optional_int(body, "seed")
    except (ValueError, TypeError) as e:
        return jsonify(error=f"invalid config: {e}"), 400
    return jsonify(service.export_cadcad(spec, n_runs=n_runs, horizon=horizon, seed=seed))


def main() -> None:  # pragma: no cover
    app.run(host="127.0.0.1", port=5000, debug=True)


if __name__ == "__main__":  # pragma: no cover
    main()
