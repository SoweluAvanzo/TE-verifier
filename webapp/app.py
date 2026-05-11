"""Flask app entry point.

Run:
    pip install -e ".[webapp]"
    python -m webapp.app

then open http://127.0.0.1:5000.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request

from schema import (
    AsymptoticClass,
    AsymptoticFamily,
    AgentType,
    Archetype,
    BurnTriggerKind,
    CirculationSpeed,
    ContributionVerification,
    ControllingActor,
    DistributionSpec,
    EmissionTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceMaturity,
    GovernanceSpec,
    GovernanceType,
    HoldingIncentiveMechanism,
    HoldingTimeDistribution,
    Meta,
    NFRs,
    NumberRange,
    ParticipantsSpec,
    RedemptionMechanism,
    Rule,
    RuleTrigger,
    SanctionKind,
    SanctionStructure,
    Token,
    TokenEarningMechanism,
    TokenEconomy,
    TokenFunction,
    Topology,
    ValueAnchor,
    VoteWeighting,
    load_te,
)
from verifier import verify
from verifier.abm import (
    SimulationConfig,
    export_cadcad_config,
    run_simulation,
)
from verifier.minimal import minimal_verdicts
from verifier.paper import ALL_CONDITIONS


app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


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


@app.route("/api/verify", methods=["POST"])
def verify_endpoint() -> dict:
    """Accept a YAML body, parse to TE-IR, run verifier, return Report.

    The webapp posts the user's edited YAML (built from the
    questionnaire form). We reuse `schema.load_te` so the validation
    errors are the same the user would see from the CLI.
    """
    body = request.get_json(force=True)
    yaml_text = body.get("yaml", "")
    try:
        raw = yaml.safe_load(yaml_text)
        te = TokenEconomy.model_validate(raw)
    except Exception as e:
        return jsonify(error=f"failed to parse TE-IR: {e}"), 400
    report = verify(te)
    return jsonify(report.model_dump(mode="json"))


@app.route("/api/build-and-verify", methods=["POST"])
def build_and_verify() -> dict:
    """Accept a JSON IR object (form-built), validate, run verifier.

    The form-driven UI sends a nested dict matching the Pydantic model
    shape directly. We validate via `TokenEconomy.model_validate` so
    the user sees the same Pydantic error messages they'd get from
    the CLI; on success we run the verifier and return the Report
    plus a YAML serialization the UI can offer for download.
    """
    body = request.get_json(force=True)
    raw = body.get("ir", {})
    try:
        te = TokenEconomy.model_validate(raw)
    except Exception as e:
        return jsonify(error=f"failed to validate TE-IR: {e}"), 400
    report = verify(te)
    yaml_text = yaml.safe_dump(
        te.model_dump(mode="json", exclude_none=True),
        sort_keys=False,
        allow_unicode=True,
    )
    return jsonify(
        report=report.model_dump(mode="json"),
        yaml=yaml_text,
    )


@app.route("/api/yaml-to-ir", methods=["POST"])
def yaml_to_ir() -> dict:
    """Convert a YAML TE-IR into a JSON dict the form can hydrate from.

    Used by the form's "Load example" buttons: backend parses the YAML,
    validates, and returns the validated dict. Frontend then populates
    each form field from the dict.
    """
    body = request.get_json(force=True)
    yaml_text = body.get("yaml", "")
    try:
        raw = yaml.safe_load(yaml_text)
        te = TokenEconomy.model_validate(raw)
    except Exception as e:
        return jsonify(error=f"failed to parse TE-IR: {e}"), 400
    return jsonify(ir=te.model_dump(mode="json", exclude_none=True))


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


@app.route("/simulate")
def simulate_page() -> str:
    """Render the ABM simulator page.

    The simulator drives ``verifier.abm.run_simulation`` against a
    user-supplied YAML (or a loaded example) and renders charts of
    P(violation), deployment-vs-dynamic split, and time-to-violation
    distributions per failure mode. The page also offers a download
    of the cadCAD-compatible export.
    """
    examples = sorted(p.stem for p in EXAMPLES_DIR.glob("*.yaml"))
    return render_template("simulate.html", examples=examples)


@app.route("/api/minimal-verdicts", methods=["POST"])
def minimal_verdicts_endpoint() -> dict:
    """Return the minimal (reachability) verifier output.

    Accepts a YAML body; emits the list of ``ReachabilityVerdict``
    dicts (failure_mode, subject, structural_status, violation_reachable,
    satisfaction_reachable, minimum_param_shift, witness,
    safety_predicates).
    """
    body = request.get_json(force=True)
    yaml_text = body.get("yaml", "")
    try:
        raw = yaml.safe_load(yaml_text)
        te = TokenEconomy.model_validate(raw)
    except Exception as e:
        return jsonify(error=f"failed to parse TE-IR: {e}"), 400
    verdicts = minimal_verdicts(te)
    return jsonify(verdicts=[v.model_dump(mode="json") for v in verdicts])


@app.route("/api/simulate", methods=["POST"])
def simulate_endpoint() -> dict:
    """Run the reference ABM and return the simulation report.

    Body:
      - yaml: the TE-IR YAML text
      - n_runs (int, default 200, max 5000): Monte Carlo replicates
      - horizon_periods (int, default 260, max 5000): simulation length
      - seed (int|None): determinism control
      - skip_non_fragile (bool, default True): triage SOUND/BROKEN FMs
    """
    body = request.get_json(force=True)
    yaml_text = body.get("yaml", "")
    try:
        raw = yaml.safe_load(yaml_text)
        te = TokenEconomy.model_validate(raw)
    except Exception as e:
        return jsonify(error=f"failed to parse TE-IR: {e}"), 400

    # Bound the inputs to prevent the browser from triggering an
    # arbitrarily-long server-side simulation.
    try:
        cfg = SimulationConfig(
            n_runs=min(max(1, int(body.get("n_runs", 200))), 5000),
            horizon_periods=min(max(1, int(body.get("horizon_periods", 260))), 5000),
            seed=(int(body["seed"]) if body.get("seed") not in (None, "") else None),
            skip_non_fragile=bool(body.get("skip_non_fragile", True)),
            record_trajectories=bool(body.get("record_trajectories", False)),
        )
    except (ValueError, TypeError) as e:
        return jsonify(error=f"invalid config: {e}"), 400

    try:
        report = run_simulation(te, config=cfg)
    except Exception as e:
        return jsonify(error=f"simulation failed: {e}"), 500
    return jsonify(report.model_dump(mode="json"))


@app.route("/api/cadcad-export", methods=["POST"])
def cadcad_export_endpoint() -> dict:
    """Return the cadCAD-compatible config dict for the given spec.

    Same body shape as /api/simulate (n_runs, horizon_periods are
    surfaced into the export's sim_config). The returned JSON is
    intended to be saved to disk and consumed by a cadCAD pipeline
    outside this app.
    """
    body = request.get_json(force=True)
    yaml_text = body.get("yaml", "")
    try:
        raw = yaml.safe_load(yaml_text)
        te = TokenEconomy.model_validate(raw)
    except Exception as e:
        return jsonify(error=f"failed to parse TE-IR: {e}"), 400
    try:
        cfg = SimulationConfig(
            n_runs=min(max(1, int(body.get("n_runs", 500))), 5000),
            horizon_periods=min(max(1, int(body.get("horizon_periods", 260))), 5000),
            seed=(int(body["seed"]) if body.get("seed") not in (None, "") else None),
        )
    except (ValueError, TypeError) as e:
        return jsonify(error=f"invalid config: {e}"), 400
    config = export_cadcad_config(te, sim_config=cfg)
    return jsonify(config)


def main() -> None:  # pragma: no cover
    app.run(host="127.0.0.1", port=5000, debug=True)


if __name__ == "__main__":  # pragma: no cover
    main()
