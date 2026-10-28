## =============================================================================
## te_platform/tools/sim_experiment.py — tool sim.experiment.v1
## =============================================================================
## GUIDE STEP   none yet (custom-experiment extension)
## PURPOSE      Queue a what-if experiment on the verified design: named
##              variants (a few field changes each) or a sweep of one field,
##              each compared with the current design by formal verification,
##              deterministic trajectories and optionally a seeded Monte Carlo
##              (te_platform/experiments.py). The variants are built and
##              validated HERE, before queueing, so a wrong path or an invalid
##              value comes back at once as a validation error naming it.
## USED BY      the agent (via MCP); the report prints every finished
##              experiment of the verification with its charts.
## DEPENDS ON   experiments.py, jobs/queue.py.
## =============================================================================

from typing import Any

import anyio
from pydantic import BaseModel, Field

from te_platform.errors import InvalidInput
from te_platform.experiments import ExperimentDesign, variants_of
from te_platform.jobs import queue
from te_platform.registry.context import CallContext
from te_platform.registry.spec import ToolSpec
from te_platform.service import _parse as parse_spec


class SimExperimentInput(ExperimentDesign):
    """What a caller sends to sim.experiment.v1: the experiment, plus the usual ids."""

    spec: str | dict[str, Any] | None = Field(
        default=None, description="The TE-IR spec (YAML text or JSON). Omit inside a session."
    )
    session_id: str | None = Field(default=None, description="The design session, if any.")
    verification_ref: str | None = Field(
        default=None,
        description="The verification_ref of the CURRENT design (verify.run.v1). "
        "Sessions provide it automatically.",
    )
    override_reason: str | None = Field(
        default=None,
        description="Only if the USER explicitly asked to skip an overridable rule; say why.",
    )


class SimExperimentOutput(BaseModel):
    """The id of the queued job, and what to do with it."""

    job_id: str
    variants: list[str] = Field(description="The variants that will run, current design first.")
    next_step: str = "Call jobs.status.v1 with this job_id and wait_s 30."


async def handle(inp: SimExperimentInput, ctx: CallContext) -> SimExperimentOutput:
    """Validate every variant, then queue the experiment; return its job id."""
    spec = inp.spec if inp.spec is not None else (ctx.session.current_spec if ctx.session else None)
    vref = ctx.facts.verification_ref
    if spec is None or vref is None:
        raise InvalidInput("A verified spec is required.")
    if isinstance(spec, str):
        spec = parse_spec(spec)  # YAML text -> dict, as everywhere
    design = ExperimentDesign.model_validate(
        inp.model_dump(include=set(ExperimentDesign.model_fields))
    )
    # Builds and validates every variant (InvalidInput names the bad one).
    names = [v["name"] for v in await anyio.to_thread.run_sync(lambda: variants_of(spec, design))]
    payload = {
        "spec": spec,
        "design": design.model_dump(),
        "seed": design.seed,  # seeded: a repeat of the same experiment reuses its job
        "session_id": inp.session_id,
    }
    job_id = await anyio.to_thread.run_sync(
        lambda: queue.enqueue_job(
            "experiment", payload, ctx.principal, vref, correlation_id=ctx.correlation_id
        )
    )
    return SimExperimentOutput(job_id=job_id, variants=names)


TOOL = ToolSpec(
    id="sim.experiment.v1",
    title="What-if experiment on the design (background job)",
    input_model=SimExperimentInput,
    output_model=SimExperimentOutput,
    handler=handle,
)
