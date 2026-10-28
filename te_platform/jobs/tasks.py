## =============================================================================
## te_platform/jobs/tasks.py — the functions the worker actually runs
## =============================================================================
## GUIDE STEP   6.1
## PURPOSE      Each task receives one JSON-like `payload` dict (built by
##              queue.enqueue_job) and returns a JSON-like dict, which RQ
##              stores as the job's result. Tasks are thin: they call the
##              service layer and report progress.
##              The on_job_* callbacks (and on_work_horse_killed, used by
##              worker.py) run when a job ENDS and hand the outcome to
##              queue.settle_job (jobs table, quota slot; queue.py header
##              LIFECYCLE).
## USED BY      worker.py (RQ imports the tasks and callbacks by their dotted
##              name, e.g. "te_platform.jobs.tasks.run_monte_carlo", as given
##              in queue.py), jobs/report_task.py (bind_job_logging), tests.
##              The report task (guide 10.3) lives in jobs/report_task.py, so
##              that this module, which every worker imports, never loads
##              WeasyPrint.
## DEPENDS ON   rq (get_current_job, Job), redis (types), structlog
##              (contextvars), service.py, jobs/queue.py (settle_job).
## WHY          Keeping tasks as plain functions of a dict makes them easy to
##              test (call them directly in a test, no worker needed) and
##              keeps RQ details in queue.py/worker.py. Recording the END of a
##              job in callbacks, not in a `finally` inside the task, is what
##              makes it reliable: a job stopped by the user or by its
##              job_timeout is interrupted before its own `finally` could
##              run, but RQ still runs the callbacks.
## PAYLOAD      Keys written by the tool handlers + queue.enqueue_job:
##                verification_ref, principal_id, session_id,
##                correlation_id                                  (always)
##                spec, n_runs, horizon, seed, failure_modes      (monte_carlo)
##                spec, horizon, seed, max_agents                 (trajectory)
##              (the report payload: jobs/report_task.py)
## LOGGING      Each task first binds the payload's correlation_id with
##              structlog.contextvars (bind_job_logging below), so every log
##              line written while the job runs carries it (observability.py).
## ACTIVATE     Uncomment at guide 6.1. Tests: test_platform_jobs.py (tasks
##              called directly, and through a real worker).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the task and
## callback names exactly: queue.py names them as
## "te_platform.jobs.tasks.<name>".
##
## Guide 6.1 (first: service.py and jobs/queue.py active)
## [ ] 1. Imports at the top: TracebackType, Any, structlog, Redis,
##        get_current_job (rq), Job (rq.job), `from te_platform import
##        service` and settle_job from te_platform.jobs.queue.
## [ ] 2. `_progress(fraction)`: if get_current_job() is not None, store
##        round(fraction, 3) in job.meta["progress"] and call save_meta().
## [ ] 3. `bind_job_logging(kind, payload)`: clear structlog's
##        contextvars, then bind correlation_id (from the payload) and
##        job_kind=kind.
## [ ] 4. `run_monte_carlo(payload) -> dict[str, Any]`: bind_job_logging,
##        _progress(0), service.simulate(payload["spec"], n_runs, horizon,
##        seed, failure_modes as keywords, defaults 200 and 260),
##        _progress(1),
##        then return
##          | {"kind": "monte_carlo",
##          |  "verification_ref": payload["verification_ref"], **result}
## [ ] 5. `run_trajectory(payload)`: the same shape with service.trajectory
##        (horizon default 120, seed, max_agents) and kind "trajectory".
## [ ] 6. `_owner(job)`: the first id of job.meta["owners"] (queue.py).
## [ ] 7. The callbacks RQ calls when a job ends (queue.py header
##        LIFECYCLE); arguments RQ passes but we do not need start with "_":
##        on_job_success(job, _connection, result) -> settle "finished"
##        with the result; on_job_failure(job, _connection, exc_type,
##        exc_value, _traceback) -> store a short message (never a stack
##        trace) in job.meta["error_message"], save_meta(), settle
##        "failed"; on_job_stopped(job, _connection) -> settle
##        "cancelled"; on_work_horse_killed(job, _retpid, _ret_val,
##        _rusage) -> settle "failed" (worker.py passes it to the Worker).
## [ ] 8. Check: activate the guide 6.1 tests of
##        tests/platform_tests/test_platform_jobs.py, then
##          | uv run pytest tests/platform_tests/test_platform_jobs.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from types import TracebackType
from typing import Any

import structlog
from redis import Redis
from rq import get_current_job
from rq.job import Job

from te_platform import service
from te_platform.experiments import ExperimentDesign
from te_platform.experiments import run_experiment as run_experiment_variants
from te_platform.jobs.queue import settle_job


## --- Small helpers -------------------------------------------------------------------------
def _progress(fraction: float) -> None:
    """Store progress in the job's meta; jobs.status.v1 shows it.

    get_current_job() returns None when the function is called outside a
    worker (e.g. directly in a test); then progress is simply not recorded.
    """
    job = get_current_job()
    if job is not None:
        job.meta["progress"] = round(fraction, 3)
        job.save_meta()  # type: ignore[no-untyped-call]  # RQ leaves this method unannotated


def bind_job_logging(kind: str, payload: dict[str, Any]) -> None:
    """Attach this job's correlation id to every log line it writes.

    Clear first: a worker process runs many jobs one after the other, and
    the previous job's id must not leak into this one's lines.
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        correlation_id=payload.get("correlation_id"), job_kind=kind
    )


## --- Simulations ----------------------------------------------------------------------------
def run_monte_carlo(payload: dict[str, Any]) -> dict[str, Any]:
    """Run a Monte Carlo simulation (tool sim.monte_carlo.v1)."""
    bind_job_logging("monte_carlo", payload)
    _progress(0.0)
    result = service.simulate(
        payload["spec"],
        n_runs=payload.get("n_runs", 200),
        horizon=payload.get("horizon", 260),
        seed=payload.get("seed"),
        failure_modes=payload.get("failure_modes"),
    )
    _progress(1.0)
    return {"kind": "monte_carlo", "verification_ref": payload["verification_ref"], **result}


def run_trajectory(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one seeded trajectory, period by period (tool sim.trajectory.v1)."""
    bind_job_logging("trajectory", payload)
    _progress(0.0)
    result = service.trajectory(
        payload["spec"],
        horizon=payload.get("horizon", 120),
        seed=payload.get("seed"),
        max_agents=payload.get("max_agents"),
    )
    _progress(1.0)
    return {"kind": "trajectory", "verification_ref": payload["verification_ref"], **result}


def run_experiment(payload: dict[str, Any]) -> dict[str, Any]:
    """Run a what-if experiment on the design (tool sim.experiment.v1)."""
    bind_job_logging("experiment", payload)
    _progress(0.0)
    design = ExperimentDesign.model_validate(payload["design"])
    result = run_experiment_variants(payload["spec"], design, progress=_progress)
    return {"kind": "experiment", "verification_ref": payload["verification_ref"], **result}


## --- When a job ends (queue.py header LIFECYCLE) ----------------------------------------------
## RQ calls these with fixed positional arguments; the ones we do not need
## start with "_" (the usual Python sign for "unused").
def _owner(job: Job) -> str:
    """Return the id of the principal who queued the job (queue.py meta)."""
    return str(job.meta["owners"][0])


def on_job_success(job: Job, _connection: Redis, result: Any) -> None:
    """Record a job that returned normally."""
    settle_job(job.id, _owner(job), "finished", result if isinstance(result, dict) else None)


def on_job_failure(
    job: Job,
    _connection: Redis,
    exc_type: type[BaseException],
    exc_value: BaseException,
    _traceback: TracebackType | None,
) -> None:
    """Record a job that raised, or that ran past its job_timeout."""
    # A short message for jobs.status.v1 (JobInfo.error), never a stack
    # trace: the full trace stays in the worker's log.
    job.meta["error_message"] = f"{exc_type.__name__}: {exc_value}"[:300]
    job.save_meta()  # type: ignore[no-untyped-call]  # RQ leaves this method unannotated
    settle_job(job.id, _owner(job), "failed")


def on_job_stopped(job: Job, _connection: Redis) -> None:
    """Record a running job that was stopped on request (queue.cancel_job)."""
    settle_job(job.id, _owner(job), "cancelled")


def on_work_horse_killed(job: Job, _retpid: int, _ret_val: int, _rusage: Any) -> None:
    """Record a job whose process died (killed, out of memory); worker.py uses it."""
    settle_job(job.id, _owner(job), "failed")
