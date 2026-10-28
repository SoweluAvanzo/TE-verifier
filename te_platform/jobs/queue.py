## =============================================================================
## te_platform/jobs/queue.py — put jobs on the queue, read, cancel and settle them
## =============================================================================
## GUIDE STEP   6.1 (enqueue_job, get_job, cancel_job, settle_job, reuse),
##              6.2 (the jobs table), 6.3 (quota counting)
## PURPOSE      The interface between the tools and the workers:
##              - enqueue_job(kind, payload, principal, verification_ref,
##                correlation_id=None) -> job_id
##              - get_job(job_id, principal) -> JobInfo
##              - cancel_job(job_id, principal) -> JobInfo
##              - settle_job(job_id, principal_id, status, result=None):
##                records that a job ENDED, whatever the way (see LIFECYCLE)
##              JobInfo is the typed status a client sees (queued / running /
##              finished / failed / cancelled, progress, result, error).
## USED BY      tools/sim_monte_carlo.py, tools/sim_trajectory.py,
##              tools/report_render_pdf.py (enqueue_job);
##              tools/jobs_status.py (get_job); tools/jobs_cancel.py
##              (cancel_job); jobs/tasks.py and jobs/worker.py (settle_job).
## DEPENDS ON   rq, redis (sync client: RQ is synchronous), config.py,
##              errors.py (NotFound), hashing.py (job ids),
##              registry/context.py (Principal), db/repo.py + db/session.py
##              (6.2), security/quotas.py (6.3). The tasks are named by their
##              dotted path ("te_platform.jobs.tasks.run_monte_carlo",
##              "te_platform.jobs.report_task.render_report"), so this file
##              imports neither jobs/tasks.py nor jobs/report_task.py.
## WHY          D12. RQ stores each job (function name, arguments, status,
##              result) in Redis; any worker process can pick it up.
## RESULT REUSE (caching)
##              A SEEDED simulation's id is derived from its content: kind +
##              verification_ref + parameters (including the seed) + WHO
##              asked. The same request from the same user therefore always
##              gets the SAME id. If a queued, running or finished job with
##              that id exists, we return it instead of computing again:
##              identical simulations cost nothing the second time
##              (architecture §3.3 "an identical request is answered from
##              cache"). Never reused: unseeded runs (random by design) and
##              reports (each one has its own id, download link and expiry,
##              chosen by tools/report_render_pdf.py): both get a random id.
## OWNERSHIP    Each job records its owner (principal id) in job.meta. A caller
##              asking for someone else's job gets NotFound — the same answer as
##              for a job that does not exist, so job ids cannot be probed.
##              Results are NOT shared between users, deliberately: the
##              principal is part of the job id. Sharing would save a little
##              computation but would need a list of owners kept in step in
##              Redis AND the database (the session state reads the jobs table);
##              at research scale, computing twice is cheaper than that
##              complexity, and it guarantees no result ever crosses users.
## LIFECYCLE    A job ends in exactly one of these ways, and each one calls
##              settle_job, which writes the outcome to the jobs table (6.2)
##              and gives the owner's "running jobs" quota slot back (6.3):
##              - it returns           -> tasks.on_job_success  (callback)
##              - it raises, or runs past its job_timeout
##                                     -> tasks.on_job_failure  (callback)
##              - a user stops it while it runs (cancel_job)
##                                     -> tasks.on_job_stopped  (callback)
##              - a user cancels it while it is queued (it never runs)
##                                     -> cancel_job itself
##              - its process dies (out of memory, killed)
##                                     -> worker.py's work-horse-killed handler
##              - the worker container itself dies: RQ's registry cleanup
##                                     -> tasks.on_job_failure  (callback)
##              The callbacks run in the worker, OUTSIDE the task function, so
##              they also run when the task is killed half-way (a `finally`
##              inside the task would not). settle_job is safe to call twice
##              for the same job: the first outcome is kept.
## ACTIVATE     6.1: uncomment everything single-commented.
##              6.2 and 6.3: the blocks commented twice under their labels.
##              Tests: test_platform_jobs.py.
##              Note: these functions are synchronous (RQ is); async callers
##              (tool handlers) run them with anyio.to_thread.run_sync.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the public names
## exactly as written here: other files import them (te_platform/README.md,
## contracts table).
##
## Guide 6.1 (first: hashing.py, config.py, errors.py and
## registry/context.py active; Redis running)
## [ ] 1. Imports at the top: contextlib, logging, lru_cache, Any and
##        Literal, uuid4,
##        BaseModel, Redis; Callback and Queue (rq), send_stop_job_command
##        (rq.command), InvalidJobOperation and NoSuchJobError
##        (rq.exceptions), Job and JobStatus (rq.job); then hashing,
##        get_settings, NotFound, Principal. Then
##          | log = logging.getLogger(__name__)
## [ ] 2. Two type aliases: JobKind = Literal["monte_carlo", "trajectory",
##        "report"] and JobStatusName (queued, running, finished, failed,
##        cancelled).
## [ ] 3. `class JobInfo(BaseModel)`: job_id, kind, status, then progress,
##        retry_after_s, result and error, all optional with default None.
##        Keep this name exactly.
## [ ] 4. `_redis()`, cached with @lru_cache(maxsize=1), returning
##        Redis.from_url(get_settings().redis_url).
## [ ] 5. The dicts _QUEUE_OF (monte_carlo and trajectory -> "simulations",
##        report -> "reports"), _TIMEOUT_S (15, 10 and 5 minutes, in
##        seconds) and _TASK_OF (kind -> dotted task name), the constant
##        _KEEP_S (one week), then `_queue_for(kind)`:
##          | return Queue(_QUEUE_OF[kind], connection=_redis())
## [ ] 6. `_job_id(kind, verification_ref, payload, principal_id)`: drop
##        "spec" from the payload, hash the canonical JSON of kind, vref,
##        params and principal with hashing.sha256_hex, and return "job-" +
##        the hex digest.
## [ ] 7. `_owners(job)` (the set of job.meta["owners"]), `_status(job)`
##        (RQ's statuses mapped to our five, see its docstring) and
##        `_info(job)` (a JobInfo: result only when finished, error only
##        when failed, retry_after_s=5 while queued or running).
## [ ] 8. `settle_job(job_id, principal_id, status, result=None)`: for now
##        one log line "job ended" with the job id, owner, status and
##        whether there is a result (header LIFECYCLE).
## [ ] 9. `enqueue_job(kind, payload, principal, verification_ref,
##        correlation_id=None) -> str`, keep this name exactly. In order: a
##        seeded simulation gets a content-based id; if a job with that id
##        is queued, running or finished, return its id; if it failed or
##        was cancelled, delete it (it runs again under the same id);
##        otherwise ("job-" + uuid4().hex) is the id. Then enqueue the task
##        by its dotted name with job_id, job_timeout, result_ttl and
##        failure_ttl of _KEEP_S, meta {"kind", "owners", "progress"} and
##        the three callbacks of jobs/tasks.py:
##          | on_success=Callback("te_platform.jobs.tasks.on_job_success")
##        If enqueue raises, settle the job as "failed" and re-raise.
## [ ] 10. `get_job(job_id, principal) -> JobInfo`: Job.fetch it; a missing
##         job AND a job whose owners lack principal.id both raise
##         NotFound("No such job.") (same message: ids cannot be probed).
## [ ] 11. `cancel_job(job_id, principal) -> JobInfo`: get_job first (it
##         checks ownership); a queued job: job.cancel() and settle_job(...,
##         "cancelled") (it will never run, so no callback will); a running
##         job: send_stop_job_command(_redis(), job_id) inside
##         contextlib.suppress(InvalidJobOperation) (it ended meanwhile).
##         Return the _info of a freshly fetched job.
## [ ] 12. Check: activate the guide 6.1 tests of
##         tests/platform_tests/test_platform_jobs.py (real Redis, a real
##         RQ worker run in the test), then
##          | uv run pytest tests/platform_tests/test_platform_jobs.py -q
##          | uv run mypy te_platform
##
## Guide 6.2 (first: the jobs table, db/models.py, and the job methods of
## db/repo.py)
## [ ] 13. Import Repository and session_scope (labelled block at the top).
## [ ] 14. In enqueue_job, BEFORE the enqueue call: record_job(job_id, kind,
##         verification_ref, params, session_id=payload.get("session_id"))
##         in a session_scope (the `##` note there explains why first).
## [ ] 15. In settle_job: update_job(job_id, status, result) in a
##         session_scope, as the job's owner.
## [ ] 16. Check: step 12 again with the guide 6.2 tests (they need the
##         database too), and the guide 6.2 "Done when".
##
## Guide 6.3 (first: security/quotas.py)
## [ ] 17. Import job_finished_sync and job_started_sync (labelled block at
##         the top); add `_released_key(job_id)` ("te:jobs:released:" + id).
## [ ] 18. In enqueue_job, still BEFORE the enqueue call: delete the
##         released marker, then job_started_sync(principal.id).
## [ ] 19. In settle_job: release the quota slot ONCE per run, using the
##         marker as a guard:
##          | if _redis().set(_released_key(job_id), 1, nx=True, ex=_KEEP_S):
##          |     job_finished_sync(principal_id)
## [ ] 20. Check: step 12 again with the guide 6.3 tests.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import contextlib
import logging
from functools import lru_cache
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel
from redis import Redis
from rq import Callback, Queue
from rq.command import send_stop_job_command
from rq.exceptions import InvalidJobOperation, NoSuchJobError
from rq.job import Job, JobStatus

from te_platform import hashing
from te_platform.config import get_settings

## Guide 6.2: the jobs table.
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.errors import NotFound
from te_platform.registry.context import Principal

## Guide 6.3: the quota counters.
from te_platform.security.quotas import job_finished_sync, job_started_sync

log = logging.getLogger(__name__)

JobKind = Literal["monte_carlo", "trajectory", "experiment", "report"]
JobStatusName = Literal["queued", "running", "finished", "failed", "cancelled"]


class JobInfo(BaseModel):
    """The status of one job, as a client sees it."""

    job_id: str
    kind: JobKind
    status: JobStatusName
    progress: float | None = None  # 0.0-1.0, reported by tasks.py
    retry_after_s: int | None = None  # how long the client should wait before asking again
    result: dict[str, Any] | None = None  # only when finished
    error: str | None = None  # only when failed; a short message, no stack trace


## --- Connections and queues ------------------------------------------------------------
@lru_cache(maxsize=1)
def _redis() -> Redis:
    """Return the process's Redis client (one connection pool per process)."""
    return Redis.from_url(get_settings().redis_url)


## Two queues so a long simulation can never delay a short report rendering:
## the worker listens to both (worker.py); you could also run dedicated
## workers per queue when load grows.
_QUEUE_OF: dict[str, str] = {
    "monte_carlo": "simulations",
    "trajectory": "simulations",
    "experiment": "simulations",
    "report": "reports",
}

## Maximum run time per kind; RQ stops a job that exceeds it (it then shows
## as failed, and tasks.on_job_failure settles it).
_TIMEOUT_S: dict[str, int] = {
    "monte_carlo": 15 * 60,
    "trajectory": 10 * 60,
    "experiment": 20 * 60,  # up to six variants, each verified and simulated
    "report": 5 * 60,
}

## The function the worker runs for each kind, given as a dotted name: the
## worker imports it, this process never needs to.
_TASK_OF: dict[str, str] = {
    "monte_carlo": "te_platform.jobs.tasks.run_monte_carlo",
    "trajectory": "te_platform.jobs.tasks.run_trajectory",
    "experiment": "te_platform.jobs.tasks.run_experiment",
    "report": "te_platform.jobs.report_task.render_report",
}

## How long Redis keeps a job's result or error (they are also stored in the
## jobs table from guide 6.2 on).
_KEEP_S = 7 * 24 * 3600


def _queue_for(kind: JobKind) -> Queue:
    """Return the queue that runs jobs of this kind."""
    return Queue(_QUEUE_OF[kind], connection=_redis())


## --- Helpers ------------------------------------------------------------------------------
def _job_id(kind: str, verification_ref: str, payload: dict[str, Any], principal_id: str) -> str:
    """Return the content-based id of a seeded simulation (header RESULT REUSE).

    The spec itself is NOT part of the hash: the verification_ref already
    identifies it.
    """
    params = {k: v for k, v in payload.items() if k != "spec"}
    canonical = hashing.canonical_json(
        {"kind": kind, "vref": verification_ref, "params": params, "principal": principal_id}
    )
    return "job-" + hashing.sha256_hex(canonical)


def _owners(job: Job) -> set[str]:
    """Return the ids of the principals allowed to see this job."""
    return set(job.meta.get("owners", []))


def _status(job: Job) -> JobStatusName:
    """Map RQ's statuses to our five.

    RQ has more (deferred, scheduled, stopped, canceled...); clients should
    not need to know them.
    """
    s = job.get_status()
    if s in (JobStatus.QUEUED, JobStatus.DEFERRED, JobStatus.SCHEDULED):
        return "queued"
    if s == JobStatus.STARTED:
        return "running"
    if s == JobStatus.FINISHED:
        return "finished"
    if s in (JobStatus.CANCELED, JobStatus.STOPPED):
        return "cancelled"
    return "failed"


def _info(job: Job) -> JobInfo:
    """Build the client's view of a job."""
    status = _status(job)
    return JobInfo(
        job_id=job.id,
        kind=job.meta["kind"],
        status=status,
        progress=job.meta.get("progress"),
        # Ask again soon while running, never after a final state.
        retry_after_s=5 if status in ("queued", "running") else None,
        result=job.return_value() if status == "finished" else None,
        error=job.meta.get("error_message") if status == "failed" else None,
    )


## Guide 6.3: marks that a run of a job has given its quota slot back, so a
## job reported as ended twice releases only one slot.
def _released_key(job_id: str) -> str:
    """Return the Redis key marking that this job's quota slot was released."""
    return f"te:jobs:released:{job_id}"


## --- Public functions ----------------------------------------------------------------------
def settle_job(
    job_id: str, principal_id: str, status: JobStatusName, result: dict[str, Any] | None = None
) -> None:
    """Record that a job ended (finished, failed or cancelled); safe to call twice.

    Every way a job can end calls this (header LIFECYCLE).
    """
    log.info(
        "job ended",
        extra={
            "job_id": job_id,
            "principal": principal_id,
            "status": status,
            "has_result": result is not None,
        },
    )
    ## Guide 6.2: the outcome goes to the jobs table (the session state and
    ## the reports read it). The Repository only compares principal ids, so
    ## the kind given here does not matter.
    with session_scope() as db:
        owner = Principal(id=principal_id, kind="user")
        Repository(db, owner).update_job(job_id, status, result)
    ## Guide 6.3: give the owner's "running jobs" slot back, once per run:
    ## SET ... NX succeeds only for the first caller.
    if _redis().set(_released_key(job_id), 1, nx=True, ex=_KEEP_S):
        job_finished_sync(principal_id)


def enqueue_job(
    kind: JobKind,
    payload: dict[str, Any],
    principal: Principal,
    verification_ref: str,
    correlation_id: str | None = None,
) -> str:
    """Queue a job and return its id (or the id of an identical earlier one).

    The quota PRECONDITION was already checked by the pipeline; here we only
    COUNT the job once it is really going to be queued (guide 6.3).
    correlation_id: the tool call's id (ctx.correlation_id); the worker logs
    it with every line of the job (observability.py). It is NOT part of the
    job id, so the same seeded request from a later chat turn is reused.
    """
    job_id: str | None = None
    if kind != "report" and payload.get("seed") is not None:
        job_id = _job_id(kind, verification_ref, payload, principal.id)
        try:
            existing: Job | None = Job.fetch(job_id, connection=_redis())
        except NoSuchJobError:
            existing = None  # not computed yet (or its result expired)
        if existing is not None:
            if _status(existing) in ("queued", "running", "finished"):
                # Same computation (same user) already done or under way: reuse it.
                return job_id
            # It failed or was cancelled: run it again under the same id.
            existing.delete()

    # Unseeded runs and reports get a fresh random id. Choosing the id HERE
    # (not letting RQ choose) lets us record the job in the database
    # before any worker can see it (guide 6.2 block below).
    if job_id is None:
        job_id = "job-" + uuid4().hex

    ## Guide 6.2: record the job in the database FIRST, linked to the
    ## session, so the session state ("simulated") and reports can find it
    ## after RQ has expired the result; settle_job updates the row when the
    ## job ends. It must happen BEFORE enqueue: a fast worker could
    ## otherwise finish the job and try to update a row that does not exist
    ## yet (a race condition found by running the tests with a real worker).
    with session_scope() as db:
        params = {k: v for k, v in payload.items() if k != "spec"}
        Repository(db, principal).record_job(
            job_id, kind, verification_ref, params, session_id=payload.get("session_id")
        )
    ## Guide 6.3: count the job for the quotas, also BEFORE enqueue: counting
    ## after it would let a fast job give its slot back before taking it.
    ## Deleting the released marker re-arms settle_job for this run (a
    ## failed seeded job runs again under the same id).
    _redis().delete(_released_key(job_id))
    job_started_sync(principal.id)

    try:
        _queue_for(kind).enqueue(
            _TASK_OF[kind],
            {
                **payload,
                "principal_id": principal.id,
                "verification_ref": verification_ref,
                "correlation_id": correlation_id,
            },
            job_id=job_id,
            job_timeout=_TIMEOUT_S[kind],
            result_ttl=_KEEP_S,
            failure_ttl=_KEEP_S,
            meta={"kind": kind, "owners": [principal.id], "progress": 0.0},
            # Header LIFECYCLE: the worker calls these when the job ends.
            on_success=Callback("te_platform.jobs.tasks.on_job_success"),
            on_failure=Callback("te_platform.jobs.tasks.on_job_failure"),
            on_stopped=Callback("te_platform.jobs.tasks.on_job_stopped"),
        )
    except Exception:
        # Redis refused the job: it will never run, so settle it here.
        settle_job(job_id, principal.id, "failed")
        raise
    return job_id


def get_job(job_id: str, principal: Principal) -> JobInfo:
    """Return the caller's job; NotFound for a missing job or someone else's."""
    try:
        job = Job.fetch(job_id, connection=_redis())
    except NoSuchJobError:
        raise NotFound("No such job.") from None
    if principal.id not in _owners(job):
        raise NotFound("No such job.")  # same message: no probing
    return _info(job)


def cancel_job(job_id: str, principal: Principal) -> JobInfo:
    """Cancel the caller's job and return its status.

    A queued job is removed from the queue and settled here (it will never
    run, so no callback will settle it). A running job is stopped by a
    command to the worker executing it; the worker then calls
    tasks.on_job_stopped, so the returned status may still say "running"
    for a moment.
    """
    info = get_job(job_id, principal)  # also checks ownership
    job = Job.fetch(job_id, connection=_redis())
    if info.status == "queued":
        job.cancel()
        settle_job(job_id, principal.id, "cancelled")
    elif info.status == "running":
        # InvalidJobOperation: it ended meanwhile, so there is nothing to stop.
        with contextlib.suppress(InvalidJobOperation):
            send_stop_job_command(_redis(), job_id)
    return _info(Job.fetch(job_id, connection=_redis()))
