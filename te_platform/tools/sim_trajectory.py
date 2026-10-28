## =============================================================================
## te_platform/tools/sim_trajectory.py — tool `sim.trajectory.v1`
## =============================================================================
## GUIDE STEP   6.2
## PURPOSE      Starts ONE seeded agent-based run as a background job and
##              returns its job_id. When finished (jobs.status.v1), the result
##              is the simulator's ExploreReport (checked against the real
##              verifier): te_name, config, n_agents, topology, agents,
##              snapshots (one per period: supply, balances per role, Gini,
##              action mix, trades), summary, network_metrics, fm_coherence,
##              flow_graph. Used when the user asks "show me
##              what happens over time" or to illustrate a counterexample.
## USED BY      registry/loader.py (entry point "sim.trajectory.v1"),
##              pipeline.py; called by the model through MCP. (The same report
##              shape is what the web app's /explore page draws; the chat page
##              does not draw trajectories yet.)
## DEPENDS ON   te_platform.jobs.queue.enqueue_job; in the worker,
##              jobs/tasks.py run_trajectory -> service.trajectory;
##              te_platform.service only for its bounds (MAX_AGENTS,
##              MAX_TRAJECTORY_HORIZON).
## RULES        policy -> sim.trajectory.v1: same preconditions as
##              sim.monte_carlo.v1 (verified first, quota); cost "expensive".
##              Difference from Monte Carlo: one run with detail, versus many
##              runs aggregated into probabilities.
## WHY          Architecture D12 (jobs). A seed makes the run reproducible:
##              the same spec + seed always shows the same story, which is
##              essential when the trajectory is quoted in a report.
## ACTIVATE     Uncomment with guide 6.2; tests in the "Guide 6.2" part of
##              test_platform_tools.py (the job tools queue a trajectory).
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
## [ ] 1. Imports at the top: the same as sim_monte_carlo.py (`Any`,
##        `anyio`, `BaseModel`, `Field`, `InvalidInput`, `queue`,
##        `CallContext`, `ToolSpec`), but the bounds MAX_AGENTS and
##        MAX_TRAJECTORY_HORIZON from te_platform.service.
## [ ] 2. `SimTrajectoryInput(BaseModel)`: `spec`, `session_id`,
##        `verification_ref` and `override_reason` (optional, default None);
##        `horizon: int` (default 120, ge=10, le=MAX_TRAJECTORY_HORIZON);
##        `seed: int` with a default of 42, NOT None (the "##" comment
##        explains why); `max_agents: int | None` (default None, ge=5,
##        le=MAX_AGENTS). One-line docstrings on classes and handle.
## [ ] 3. `SimTrajectoryOutput(BaseModel)`: `job_id: str` and `next_step: str`
##        with the same default text as in sim_monte_carlo.py.
## [ ] 4. `async def handle(inp, ctx) -> SimTrajectoryOutput`: spec and
##        `vref = ctx.facts.verification_ref` exactly as in
##        sim_monte_carlo.py (InvalidInput when either is None).
## [ ] 5. Payload keys read by jobs/tasks.py run_trajectory: "spec",
##        "horizon", "seed", "max_agents", "session_id". Enqueue it in a
##        thread like sim_monte_carlo.py, but with the kind "trajectory":
##          | queue.enqueue_job("trajectory", payload, ctx.principal, vref,
##          |                   correlation_id=ctx.correlation_id)
##        and return SimTrajectoryOutput(job_id=job_id).
## [ ] 6. `TOOL = ToolSpec(id="sim.trajectory.v1", title="Single seeded
##        trajectory (background job)", ...)` with the models and handle.
## [ ] 7. Remove "sim.trajectory.v1" from `planned:` in
##        policy/tool_policy.yaml.
## [ ] 8. Check: the "Guide 6.2" part of test_platform_tools.py (its
##        cancel test queues a trajectory) and test_platform_jobs.py:
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
from te_platform.service import MAX_AGENTS, MAX_TRAJECTORY_HORIZON


class SimTrajectoryInput(BaseModel):
    """What a caller sends to sim.trajectory.v1."""

    spec: str | dict[str, Any] | None = Field(
        default=None, description="The TE-IR spec (YAML text or JSON). Omit inside a session."
    )
    session_id: str | None = Field(default=None, description="The design session, if any.")
    verification_ref: str | None = Field(
        default=None,
        description="verification_ref from verify.run.v1 for THIS spec (stateless calls).",
    )
    horizon: int = Field(
        default=120, ge=10, le=MAX_TRAJECTORY_HORIZON, description="Number of periods to simulate."
    )
    # A default seed (not None): a trajectory is usually shown to a person,
    # and showing a different random story each time would be confusing.
    seed: int = Field(default=42, description="Random seed; same seed = same trajectory.")
    max_agents: int | None = Field(
        default=None,
        ge=5,
        le=MAX_AGENTS,
        description="Cap on simulated participants; omit for automatic.",
    )
    override_reason: str | None = Field(
        default=None,
        description="Only if the USER explicitly asked to skip an overridable rule; say why.",
    )


class SimTrajectoryOutput(BaseModel):
    """The id of the queued job, and what to do with it."""

    job_id: str
    next_step: str = "Call jobs.status.v1 with this job_id; respect its retry_after_s."


async def handle(inp: SimTrajectoryInput, ctx: CallContext) -> SimTrajectoryOutput:
    """Queue one seeded trajectory of a verified spec; return its job id."""
    spec = inp.spec if inp.spec is not None else (ctx.session.current_spec if ctx.session else None)
    vref = ctx.facts.verification_ref
    if spec is None or vref is None:
        raise InvalidInput("A verified spec is required.")
    payload = {
        "spec": spec,
        "horizon": inp.horizon,
        "seed": inp.seed,
        "max_agents": inp.max_agents,
        "session_id": inp.session_id,
    }
    # As in sim_monte_carlo.py: RQ is blocking, so enqueue in a thread.
    job_id = await anyio.to_thread.run_sync(
        lambda: queue.enqueue_job(
            "trajectory", payload, ctx.principal, vref, correlation_id=ctx.correlation_id
        )
    )
    return SimTrajectoryOutput(job_id=job_id)


TOOL = ToolSpec(
    id="sim.trajectory.v1",
    title="Single seeded trajectory (background job)",
    input_model=SimTrajectoryInput,
    output_model=SimTrajectoryOutput,
    handler=handle,
)
