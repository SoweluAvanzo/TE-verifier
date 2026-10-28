## =============================================================================
## te_platform/tools/jobs_cancel.py — tool `jobs.cancel.v1`
## =============================================================================
## GUIDE STEP   6.2
## PURPOSE      Cancels a queued or running background job owned by the caller,
##              e.g. when the user changes their mind or edits the spec while
##              a simulation of the OLD spec is still running.
## USED BY      registry/loader.py (entry point "jobs.cancel.v1"), pipeline.py,
##              and the model through MCP (when the user changes their mind
##              or the spec changed while a job was running, as the policy's
##              use_when says).
## DEPENDS ON   te_platform.jobs.queue.cancel_job.
## RULES        policy -> jobs.cancel.v1: always available, no preconditions,
##              cost "trivial", side_effects cancels_job; annotations
##              idempotentHint=true (cancelling twice is harmless) and
##              destructiveHint=false (nothing the user made is deleted).
## WHY          Cancelling frees the caller's concurrent-job quota
##              (security/quotas.py) and worker capacity for useful work.
## ACTIVATE     Uncomment with guide 6.2; tests ("Guide 6.2" part of
##              test_platform_tools.py): cancel own queued job -> status
##              cancelled; cancel twice -> same answer; foreign job ->
##              not_found.
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
## [ ] 1. Imports at the top: `anyio`, `BaseModel`, `Field`, `queue`
##        (from te_platform.jobs import queue), `CallContext`, `ToolSpec`.
##        (No `Any`: nothing here is loosely typed.)
## [ ] 2. `JobsCancelInput(BaseModel)` with one required field,
##        `job_id: str`, plus a Field description.
## [ ] 3. `JobsCancelOutput(BaseModel)`: `job_id: str` and `status: str`
##        (the policy's `returns`: "cancelled", or the final status).
##        One-line docstrings on both classes and on handle (ruff D1).
## [ ] 4. `async def handle(inp, ctx) -> JobsCancelOutput`: call
##        queue.cancel_job(inp.job_id, ctx.principal) in a thread (lambda)
##        and return JobsCancelOutput(job_id=info.job_id, status=info.status).
## [ ] 5. `TOOL = ToolSpec(id="jobs.cancel.v1", title="Cancel a background
##        job", ...)` with the two models and handle.
## [ ] 6. Remove "jobs.cancel.v1" from `planned:` in policy/tool_policy.yaml.
## [ ] 7. Check: the "Guide 6.2" part of test_platform_tools.py (cancel
##        own queued job, cancel twice, foreign job -> not_found), with
##        Redis running (TE_REDIS_URL):
##          | uv run pytest tests/platform_tests/test_platform_tools.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import anyio
from pydantic import BaseModel, Field

from te_platform.jobs import queue
from te_platform.registry.context import CallContext
from te_platform.registry.spec import ToolSpec


class JobsCancelInput(BaseModel):
    """What a caller sends to jobs.cancel.v1."""

    job_id: str = Field(description="The job to cancel.")


class JobsCancelOutput(BaseModel):
    """The job and its status after the cancel request."""

    job_id: str
    status: str  # "cancelled", or the final status if the job had already ended


async def handle(inp: JobsCancelInput, ctx: CallContext) -> JobsCancelOutput:
    """Cancel the caller's job; someone else's job is not_found."""
    info = await anyio.to_thread.run_sync(lambda: queue.cancel_job(inp.job_id, ctx.principal))
    return JobsCancelOutput(job_id=info.job_id, status=info.status)


TOOL = ToolSpec(
    id="jobs.cancel.v1",
    title="Cancel a background job",
    input_model=JobsCancelInput,
    output_model=JobsCancelOutput,
    handler=handle,
)
