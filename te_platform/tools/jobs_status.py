## =============================================================================
## te_platform/tools/jobs_status.py — tool `jobs.status.v1`
## =============================================================================
## GUIDE STEP   6.2
## PURPOSE      Returns the status of a background job (queued, running,
##              finished, failed, cancelled), its progress, how long to wait
##              before asking again (retry_after_s) and, when finished, its
##              result.
## USED BY      registry/loader.py (entry point "jobs.status.v1"), pipeline.py,
##              and the model through MCP (it asks for progress, respecting
##              retry_after_s); agent/loop.py turns the result into a
##              `job_progress` event for the browser. After a finished
##              simulation, predicates.py `simulation_job_finished` suggests
##              report.render_pdf.v1.
## DEPENDS ON   te_platform.jobs.queue.get_job (reads RQ / the jobs table and
##              checks ownership).
## RULES        policy -> jobs.status.v1: always available, no preconditions,
##              cost "trivial". do_not_use_when: polling in a tight loop.
## WHY          Jobs are owned: get_job raises NotFound both for unknown IDs
##              and for other people's jobs, so a caller cannot discover which
##              job IDs exist (errors.py NotFound).
## ACTIVATE     Uncomment with guide 6.2; tests ("Guide 6.2" part of
##              test_platform_tools.py): own job visible, foreign job ->
##              not_found, finished job carries the result.
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
## Guide 6.2 (activate jobs/queue.py, guide 6.1, first)
## [ ] 1. Imports at the top: `Any`, `anyio`, `BaseModel`, `Field`, `queue`
##        (from te_platform.jobs import queue), `CallContext`, `ToolSpec`.
## [ ] 2. `JobsStatusInput(BaseModel)` with one required field,
##        `job_id: str`, plus a Field description.
## [ ] 3. `JobsStatusOutput(BaseModel)`: the same fields as JobInfo in
##        jobs/queue.py, so it can be filled by copying: `job_id`, `kind`,
##        `status` (str); `progress` (float | None), `retry_after_s`
##        (int | None), `result` (dict[str, Any] | None), `error`
##        (str | None), all four defaulting to None. Keep `kind`:
##        predicates.py `simulation_job_finished` reads it. One-line
##        docstrings on both classes and on handle (ruff D1).
## [ ] 4. `async def handle(inp, ctx) -> JobsStatusOutput`: call
##        queue.get_job(inp.job_id, ctx.principal) in a thread (lambda) and
##        return `JobsStatusOutput(**info.model_dump())`. Do NOT catch
##        NotFound: the pipeline turns it into a `not_found` error.
## [ ] 5. `TOOL = ToolSpec(id="jobs.status.v1", title="Background job
##        status", ...)` with the two models and handle.
## [ ] 6. Remove "jobs.status.v1" from `planned:` in policy/tool_policy.yaml.
## [ ] 6b. (Extension) `wait_s` (0-30): poll every second until the job is
##        finished, failed or cancelled, or the time is up, so a short
##        simulation's result arrives in the same turn.
## [ ] 7. Check: the "Guide 6.2" part of test_platform_tools.py (own job
##        visible, foreign job -> not_found, finished job carries the
##        result), with Redis running (TE_REDIS_URL):
##          | uv run pytest tests/platform_tests/test_platform_tools.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from typing import Any

import anyio
from pydantic import BaseModel, Field

from te_platform.jobs import queue
from te_platform.registry.context import CallContext
from te_platform.registry.spec import ToolSpec

MAX_WAIT_S = 30  # below the pipeline's tool timeout (config.tool_timeout_s)
_DONE = {"finished", "failed", "cancelled"}


class JobsStatusInput(BaseModel):
    """What a caller sends to jobs.status.v1."""

    job_id: str = Field(description="The job_id returned by a simulation or report tool.")
    # Most simulations finish in seconds: waiting here gives the result in
    # the same turn instead of a "still running" the designer must chase.
    wait_s: int = Field(
        default=0,
        ge=0,
        le=MAX_WAIT_S,
        description="Wait up to this many seconds for the job to finish before answering "
        "(use 30 right after starting a job).",
    )


class JobsStatusOutput(BaseModel):
    """The status of one job, and its result once finished."""

    job_id: str
    # `kind` is part of the output because predicates.py
    # (simulation_job_finished) reads it from ctx.result to decide whether
    # to suggest a report.
    kind: str
    status: str
    progress: float | None = None
    retry_after_s: int | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


async def handle(inp: JobsStatusInput, ctx: CallContext) -> JobsStatusOutput:
    """Return the caller's job; someone else's job is not_found."""
    # get_job raises NotFound for unknown/foreign jobs; the pipeline turns
    # that into a `not_found` ToolError.
    info = await anyio.to_thread.run_sync(lambda: queue.get_job(inp.job_id, ctx.principal))
    with anyio.move_on_after(inp.wait_s):
        while info.status not in _DONE and inp.wait_s:
            await anyio.sleep(1)
            info = await anyio.to_thread.run_sync(
                lambda: queue.get_job(inp.job_id, ctx.principal)
            )
    # JobInfo and JobsStatusOutput have the same fields: copy them over.
    return JobsStatusOutput(**info.model_dump())


TOOL = ToolSpec(
    id="jobs.status.v1",
    title="Background job status",
    input_model=JobsStatusInput,
    output_model=JobsStatusOutput,
    handler=handle,
)
