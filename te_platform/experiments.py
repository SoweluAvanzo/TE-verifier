## =============================================================================
## te_platform/experiments.py — what-if experiments on a verified design
## =============================================================================
## GUIDE STEP   none yet (custom-experiment extension; tool sim.experiment.v1)
## PURPOSE      The agent tests ideas about a design ("what if repayment were
##              90%?", "how does the verdict change as the credit limit
##              grows?") without writing code. An experiment is DECLARATIVE:
##              the current design plus named variants, each a few field
##              changes, or a sweep of one field over a list of values. Every
##              variant runs through the SAME verified pipeline as the design
##              itself, so its results are consistent with the proofs:
##                1. formal verification (service.verify: the six checks);
##                2. the deterministic trajectory of each token
##                   (verifier/simulate/trajectory.py, at the midpoints);
##                3. optionally, an agent-based Monte Carlo (service.simulate,
##                   seeded, every failure mode simulated).
##              Bounded: at most MAX_VARIANTS variants (base included),
##              MAX_RUNS Monte Carlo runs each, MAX_HORIZON periods.
## USED BY      tools/sim_experiment.py (validate_design before queueing),
##              jobs/tasks.py (run_experiment), reports (charts, captions).
## DEPENDS ON   service.py, schema (TokenEconomy), verifier.simulate.trajectory.
## WHY          Agent-written code would bypass the verified semantics (an
##              experiment chart could then contradict a proven verdict) and
##              is unsafe to run; a declarative request cannot.
## =============================================================================

import copy
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, model_validator
from schema import TokenEconomy
from verifier.simulate.trajectory import simulate_token_trajectory

from te_platform import service
from te_platform.errors import InvalidInput

MAX_VARIANTS = 6  # the current design included
MAX_RUNS = 100  # Monte Carlo runs per variant
MAX_HORIZON = 520  # periods (10 years of weeks)
BASE_NAME = "Current design"


class Change(BaseModel):
    """One field of the design set to a new value."""

    path: str = Field(
        min_length=1,
        max_length=200,
        description="Field path in the design, e.g. 'participants.count_N' or "
        "'tokens[CR].burn_rules[0].function.asymptotic_class.parameter_ranges.c'. "
        "A list element is selected by its id (tokens[CR]) or position (burn_rules[0]).",
    )
    value: Any = Field(
        description="The new value. A number where the field is a range becomes that "
        "exact value (min = max)."
    )


class Variant(BaseModel):
    """A named alternative to the current design."""

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300, description="What it represents.")
    changes: list[Change] = Field(min_length=1, max_length=10)


class Sweep(BaseModel):
    """One field set to each of a list of values in turn."""

    path: str = Field(min_length=1, max_length=200, description="As in Change.path.")
    label: str = Field(min_length=1, max_length=60, description="What the field is, in words.")
    values: list[Any] = Field(min_length=2, max_length=MAX_VARIANTS - 1)


class ExperimentDesign(BaseModel):
    """What the agent asks for: variants or a sweep, compared with the current design."""

    title: str = Field(min_length=1, max_length=120)
    question: str = Field(
        min_length=1,
        max_length=500,
        description="The question or hypothesis the experiment tests, in plain words.",
    )
    variants: list[Variant] = Field(default_factory=list, max_length=MAX_VARIANTS - 1)
    sweep: Sweep | None = None
    horizon: int = Field(default=104, ge=4, le=MAX_HORIZON, description="Periods simulated.")
    monte_carlo_runs: int = Field(
        default=0,
        ge=0,
        le=MAX_RUNS,
        description="Agent-based Monte Carlo runs per variant (0 = formal checks and "
        "trajectories only).",
    )
    seed: int = Field(default=1, description="Random seed of the Monte Carlo runs.")

    @model_validator(mode="after")
    def _one_kind(self) -> "ExperimentDesign":
        if bool(self.variants) == (self.sweep is not None):
            raise ValueError("give either variants or a sweep, not both and not neither")
        names = [v.name for v in self.variants]
        if BASE_NAME in names or len(set(names)) != len(names):
            raise ValueError(f"variant names must be unique and not {BASE_NAME!r}")
        return self


# --- Paths ---------------------------------------------------------------------------

_STEP = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<sel>[^\]]+)\])?$")


def _select(items: list[Any], sel: str, path: str) -> int:
    if sel.isdigit():
        i = int(sel)
        if i < len(items):
            return i
    else:
        for i, item in enumerate(items):
            if isinstance(item, dict) and item.get("id") == sel:
                return i
    raise InvalidInput(f"{path}: no element [{sel}].")


def set_path(spec: dict[str, Any], path: str, value: Any) -> None:
    """Set `path` in `spec` (in place); the path must lead to an existing place."""
    steps = path.split(".")
    node: Any = spec
    for n, step in enumerate(steps):
        m = _STEP.match(step)
        if m is None or not isinstance(node, dict):
            raise InvalidInput(f"{path}: cannot read '{step}'.")
        key, sel, last = m["key"], m["sel"], n == len(steps) - 1
        if sel is None:
            if last:
                old = node.get(key)
                is_range = isinstance(old, dict) and {"min", "max"} <= old.keys()
                if is_range and isinstance(value, (int, float)) and not isinstance(value, bool):
                    value = {"min": value, "max": value}
                node[key] = value
                return
            if key not in node or not isinstance(node[key], (dict, list)):
                raise InvalidInput(f"{path}: the design has no '{key}' here.")
            node = node[key]
            continue
        items = node.get(key)
        if not isinstance(items, list):
            raise InvalidInput(f"{path}: '{key}' is not a list.")
        i = _select(items, sel, path)
        if last:
            items[i] = value
            return
        node = items[i]


def variants_of(spec: dict[str, Any], design: ExperimentDesign) -> list[dict[str, Any]]:
    """Build the current design and each variant: {name, description, changes, spec}."""
    out: list[dict[str, Any]] = [
        {"name": BASE_NAME, "description": "", "changes": [], "spec": spec}
    ]
    if design.sweep is not None:
        s = design.sweep
        asked = [
            Variant(name=f"{s.label} = {_short(v)}"[:60], changes=[Change(path=s.path, value=v)])
            for v in s.values
        ]
    else:
        asked = design.variants
    for v in asked:
        changed = copy.deepcopy(spec)
        for c in v.changes:
            set_path(changed, c.path, c.value)
        checked = service.validate(changed)
        if not checked.valid:
            errors = "; ".join(f"{e.location}: {e.message}" for e in checked.errors[:3])
            raise InvalidInput(f"Variant {v.name!r} is not a valid design: {errors}")
        out.append(
            {
                "name": v.name,
                "description": v.description,
                "changes": [c.model_dump() for c in v.changes],
                "spec": changed,
            }
        )
    return out


def _short(value: Any) -> str:
    if isinstance(value, dict) and {"min", "max"} <= value.keys():
        lo, hi = value["min"], value["max"]
        return f"{lo:g}" if lo == hi else f"{lo:g} to {hi:g}"
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


# --- Running --------------------------------------------------------------------------


def _trajectories(spec: dict[str, Any], horizon: int) -> dict[str, list[dict[str, float]]]:
    te = TokenEconomy.model_validate(spec)
    return {
        tok.id: [
            {"t": s.t, "M": s.M, "E": s.E, "B": s.B, "Q": s.Q}
            for s in simulate_token_trajectory(te, tok, horizon=horizon).samples
        ]
        for tok in te.tokens
    }


def _monte_carlo(spec: dict[str, Any], design: ExperimentDesign) -> list[dict[str, Any]]:
    result = service.simulate(
        spec,
        n_runs=design.monte_carlo_runs,
        horizon=min(design.horizon, service.MAX_MC_HORIZON),
        seed=design.seed,
        # The same triage as sim.monte_carlo.v1: a failure mode the formal
        # check already decided (sound / broken) is not simulated, so a
        # simulated figure never contradicts a proven verdict.
    )
    return [
        {
            "failure_mode": r["failure_mode"],
            "subject": r["subject"],
            "simulated": r["simulated"],
            "skip_reason": r.get("skip_reason"),
            "n_runs": r["n_runs"],
            "p_violation": r["p_violation"],
            "p_violation_ci": list(r["p_violation_ci"]),
        }
        for r in result["per_fm_results"]
    ]


def run_experiment(
    spec: dict[str, Any],
    design: ExperimentDesign,
    progress: Callable[[float], None] = lambda _f: None,
) -> dict[str, Any]:
    """Run every variant through verification, trajectories and (optionally) Monte Carlo."""
    variants = variants_of(spec, design)
    rows = []
    for n, v in enumerate(variants):
        result = service.verify(v["spec"])
        rows.append(
            {
                "name": v["name"],
                "description": v["description"],
                "changes": v["changes"],
                "verification_ref": result.verification_ref,
                "verdicts": [
                    {
                        "failure_mode": d["failure_mode"],
                        "subject": d["subject"],
                        "status": d["status"],
                        "risk_level": d.get("risk_level"),
                    }
                    for d in service.merged_verdicts(result)
                ],
                "trajectories": _trajectories(v["spec"], design.horizon),
                "monte_carlo": _monte_carlo(v["spec"], design) if design.monte_carlo_runs else [],
            }
        )
        progress((n + 1) / len(variants))
    return {
        "title": design.title,
        "question": design.question,
        "design": design.model_dump(),
        "variants": rows,
    }
