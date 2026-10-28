## =============================================================================
## te_platform/tools/sim_monte_carlo.py — tool `sim.monte_carlo.v1`
## =============================================================================
## GUIDE STEP   6.2
## PURPOSE      Starts a Monte Carlo agent-based simulation as a BACKGROUND
##              JOB and immediately returns its job_id. The simulation itself
##              (probability of violation and time-to-violation per failure
##              mode) runs later in the worker process; the caller polls
##              jobs.status.v1 for the result.
## USED BY      registry/loader.py (entry point "sim.monte_carlo.v1"),
##              pipeline.py. Suggested by predicates.py
##              `any_inconclusive_or_fragile` after verify.run.v1, with
##              arguments from `inconclusive_or_fragile_failure_modes`.
## DEPENDS ON   te_platform.jobs.queue.enqueue_job (puts the job on the Redis
##              queue), and indirectly jobs/tasks.py (run_monte_carlo, which
##              calls service.simulate in the worker); te_platform.service
##              only for its bounds MAX_MC_RUNS and MAX_MC_HORIZON.
## RULES        policy -> sim.monte_carlo.v1: preconditions valid_spec,
##              verified_spec, verification_ref_matches_spec,
##              job_quota_available; cost "expensive" (the agent asks the user
##              first). The pipeline enforces all of these BEFORE this handler
##              runs: formal verification first (architecture P2) is
##              guaranteed by `verified_spec` + `verification_ref_matches_spec`.
## WHY          Architecture D12: simulations exceed request timeouts, so they
##              run as jobs. Results are stored per (verification_ref,
##              parameters, seed), so a repeated identical request can be
##              answered from the store (implemented in jobs/queue.py).
## ACTIVATE     Uncomment with guide 6.2; tests ("Guide 6.2" part of
##              test_platform_tools.py, real Redis via TE_REDIS_URL):
##              before verification -> precondition_failed; after -> job_id;
##              the job finishes (run by an in-process RQ worker).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Every tool module has the
## same four sections (tools/__init__.py; verify_run.py is the template).
## Keep `TOOL`, the tool id and the model field names exactly as written
## here: te_platform/README.md (contracts table) and the policy rely on them.
##
## Guide 6.2 (activate jobs/queue.py and jobs/tasks.py, guide 6.1, first)
## [ ] 1. Imports at the top: `Any`, `anyio`, `BaseModel`, `Field`,
##        `InvalidInput`, `queue` (from te_platform.jobs import queue),
##        `CallContext`, `ToolSpec`, and only the bounds MAX_MC_HORIZON and
##        MAX_MC_RUNS from te_platform.service: the worker calls
##        service.simulate later (jobs/tasks.py run_monte_carlo).
## [ ] 2. `SimMonteCarloInput(BaseModel)`: `spec`, `session_id`,
##        `verification_ref` and `override_reason` (all optional, default
##        None); `failure_modes: list[str]` (default_factory=list, empty =
##        all); `n_runs: int` (default 200, ge=1, le=MAX_MC_RUNS);
##        `horizon: int` (default 260, ge=1, le=MAX_MC_HORIZON); `seed:
##        int | None` (default None). One-line docstrings on every class
##        and on handle (ruff D1).
## [ ] 3. `SimMonteCarloOutput(BaseModel)`: `job_id: str` and `next_step: str`
##        whose default text tells the model to call jobs.status.v1 and
##        respect retry_after_s (copy it from the SOLUTION).
## [ ] 4. `async def handle(inp, ctx) -> SimMonteCarloOutput`: pick the spec
##        as in verify_run.py, take `vref = ctx.facts.verification_ref`
##        (filled by registry/facts.py) and raise InvalidInput("A verified
##        spec is required.") when either is None. Do not re-check the
##        preconditions: the pipeline already did.
## [ ] 5. Build `payload`, a dict of plain JSON data (it travels through
##        Redis to the worker) with the keys jobs/tasks.py reads: "spec",
##        "failure_modes", "n_runs", "horizon", "seed", "session_id".
## [ ] 6. Enqueue in a thread (RQ is blocking) and return the job id:
##          | job_id = await anyio.to_thread.run_sync(
##          |     lambda: queue.enqueue_job("monte_carlo", payload,
##          |         ctx.principal, vref, correlation_id=ctx.correlation_id))
## [ ] 7. `TOOL = ToolSpec(id="sim.monte_carlo.v1", title="Monte Carlo
##        simulation (background job)", ...)` with the models and handle.
## [ ] 8. Remove "sim.monte_carlo.v1" from `planned:` in
##        policy/tool_policy.yaml.
## [ ] 9. Check: activate the "Guide 6.2" part of
##        tests/platform_tests/test_platform_tools.py (before verification
##        -> precondition_failed; a ref of another spec is refused; after
##        verification -> job_id, and the job finishes with a result).
##          | uv run pytest tests/platform_tests/test_platform_tools.py -q
##          | uv run pytest tests/platform_tests/test_platform_jobs.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from typing import Any

import anyio
from pydantic import BaseModel, Field

from te_platform.errors import InvalidInput
from te_platform.jobs import queue
from te_platform.registry.context import CallContext
from te_platform.registry.spec import ToolSpec
from te_platform.service import MAX_MC_HORIZON, MAX_MC_RUNS


## The bounds come from service.py, the one place that defines them (guide
## 1.5): the schema the model sees and the clamping in service.simulate can
## never disagree.
class SimMonteCarloInput(BaseModel):
    """What a caller sends to sim.monte_carlo.v1."""

    spec: str | dict[str, Any] | None = Field(
        default=None, description="The TE-IR spec (YAML text or JSON). Omit inside a session."
    )
    session_id: str | None = Field(default=None, description="The design session, if any.")
    verification_ref: str | None = Field(
        default=None,
        description="The verification_ref returned by verify.run.v1 for THIS spec. "
        "Required for stateless calls; sessions provide it automatically.",
    )
    failure_modes: list[str] = Field(
        default_factory=list,
        description="Restrict to these failure modes (e.g. ['FM3']). Pass the inconclusive "
        "or fragile ones unless the user asked for all.",
    )
    n_runs: int = Field(default=200, ge=1, le=MAX_MC_RUNS, description="Monte Carlo replicates.")
    horizon: int = Field(default=260, ge=1, le=MAX_MC_HORIZON, description="Periods per run.")
    seed: int | None = Field(
        default=None, description="Random seed; pass one for reproducible results."
    )
    override_reason: str | None = Field(
        default=None,
        description="Only if the USER explicitly asked to skip an overridable rule; say why.",
    )


class SimMonteCarloOutput(BaseModel):
    """The id of the queued job, and what to do with it."""

    job_id: str
    # Repeats the policy's advice so the model knows what to do next
    # without re-reading the tool description.
    next_step: str = "Call jobs.status.v1 with this job_id; respect its retry_after_s."


async def handle(inp: SimMonteCarloInput, ctx: CallContext) -> SimMonteCarloOutput:
    """Queue a Monte Carlo simulation of a verified spec; return its job id."""
    spec = inp.spec if inp.spec is not None else (ctx.session.current_spec if ctx.session else None)
    # ctx.facts.verification_ref was filled by registry/facts.py from the
    # input or the session; the preconditions already checked it matches.
    vref = ctx.facts.verification_ref
    if spec is None or vref is None:
        raise InvalidInput("A verified spec is required.")

    # The payload must be plain JSON data: it is stored in Redis and read by
    # another process (the worker), which cannot receive Python objects.
    payload = {
        "spec": spec,
        "failure_modes": inp.failure_modes,
        "n_runs": inp.n_runs,
        "horizon": inp.horizon,
        "seed": inp.seed,
        "session_id": inp.session_id,
    }
    # enqueue_job is synchronous (RQ talks to Redis with blocking calls), so
    # it runs in a thread to keep the async server responsive. The
    # correlation id is logged by the job too (observability.py).
    job_id = await anyio.to_thread.run_sync(
        lambda: queue.enqueue_job(
            "monte_carlo", payload, ctx.principal, vref, correlation_id=ctx.correlation_id
        )
    )
    return SimMonteCarloOutput(job_id=job_id)


TOOL = ToolSpec(
    id="sim.monte_carlo.v1",
    title="Monte Carlo simulation (background job)",
    input_model=SimMonteCarloInput,
    output_model=SimMonteCarloOutput,
    handler=handle,
)
