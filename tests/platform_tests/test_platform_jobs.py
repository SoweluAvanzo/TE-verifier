## =============================================================================
## tests/platform_tests/test_platform_jobs.py — tests for te_platform/jobs/
## =============================================================================
## GUIDE STEP   6.1 (tasks, queue, worker), 6.2 (the jobs table),
##              6.3 (quota slots)
## PURPOSE      Check that tasks compute results, that queued jobs are run by
##              a real worker and their results read back, that jobs are owned
##              (someone else's job looks like a missing job), that identical
##              seeded requests reuse one job, that cancelling and stopping
##              work, and that EVERY way a job can end is recorded (jobs
##              table, guide 6.2) and gives its quota slot back (guide 6.3).
## HOW          Real services, no fakes:
##              - tasks.py functions are plain functions of a dict: some tests
##                call them DIRECTLY;
##              - queue.py tests use the real Redis of TE_REDIS_URL and a real
##                RQ worker: rq.SimpleWorker run in burst mode inside the test
##                (it runs every queued job, then returns), or, for stopping a
##                running job, the real `te-worker` process (worker.py) started
##                by the test;
##              - from guide 6.2 the queue also writes the jobs table, so the
##                file is marked `db` and needs TE_DATABASE_URL as well.
##              Start Redis WITHOUT the compose `worker` service (it would
##              take the tests' jobs), plus its debug port, and from 6.2 the
##              database as for test_platform_db.py:
##                docker compose up -d redis redis-port
##                docker compose up -d postgres migrate postgres-port   (6.2)
##                TE_REDIS_URL=redis://127.0.0.1:6379/0 TE_DATABASE_URL=... \
##                  uv run pytest tests/platform_tests/test_platform_jobs.py
##              The tests empty the "reports" and "simulations" queues before
##              each test.
## ACTIVATE     With jobs/tasks.py and jobs/queue.py (6.1); then each labelled
##              block with its guide step.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
## Redis must be running (header, HOW).
##
## Guide 6.1
## [ ] 1. Imports: os, subprocess, sys, time, Path, uuid4, pytest, Redis,
##        Queue and SimpleWorker (rq), get_settings, NotFound, `queue` and
##        `tasks` from te_platform.jobs, Principal. Constants: REPO,
##        BITCOIN (text of examples/bitcoin.yaml), QUEUES.
## [ ] 2. Helpers: `_user()` (a Principal with a fresh random id, so tests
##        never see each other's jobs), `_run_worker(conn)` (a SimpleWorker
##        on the QUEUES, `.work(burst=True, with_scheduler=False)`) and
##        `_wait_for(check, timeout_s)` (poll until check() is true).
## [ ] 3. Fixture `redis_conn()`: Redis.from_url(get_settings().redis_url),
##        empty both queues, return the connection.
## [ ] 4. test_run_trajectory_returns_periods: tasks.run_trajectory called
##        directly; kind "trajectory" and one snapshot per period.
## [ ] 5. Through the queue: a job is queued, a worker runs it, the result
##        is readable; another user's job is NotFound; seeded requests are
##        reused, unseeded and report requests never; a queued job can be
##        cancelled (and never runs); a failing job is "failed" with a short
##        error message; a running job can be stopped (te-worker process).
## [ ] 6. Check (header, HOW: Redis up, no compose worker):
##          | uv run pytest tests/platform_tests/test_platform_jobs.py -q
##
## Guide 6.2 (the jobs table)
## [ ] 7. Mark the file `db` (labelled block) and check, through
##        Repository.get_job, that finished, failed and cancelled jobs are
##        stored with their status (and the result when finished).
##
## Guide 6.3 (quotas)
## [ ] 8. The running-jobs counter (security/quotas.py _running_key) goes
##        up when a job is queued and back to 0 however the job ends, and a
##        job settled twice gives its slot back only once.
## [ ] 9. Check: the step 6 command.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from redis import Redis
from rq import Queue, SimpleWorker

from te_platform.config import get_settings
from te_platform.errors import NotFound
from te_platform.jobs import queue, tasks
from te_platform.registry.context import Principal

## Guide 6.2: the jobs table, read through the repository.
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope

## Guide 6.3: the quota counters.
from te_platform.security.quotas import _running_key

REPO = Path(__file__).resolve().parents[2]
BITCOIN = (REPO / "examples" / "bitcoin.yaml").read_text(encoding="utf-8")
QUEUES = ("reports", "simulations")

## Guide 6.2: from now on enqueue_job writes the jobs table, so every test
## that queues a job needs PostgreSQL too.
pytestmark = pytest.mark.db


## --- Helpers ---------------------------------------------------------------------------------
def _user() -> Principal:
    """A fresh user per test: its jobs, ids and quota counters are its own."""
    return Principal(id="u-" + uuid4().hex[:12], kind="user")


def _run_worker(conn: Redis) -> None:
    """Run a real RQ worker in this process until the queues are empty.
    SimpleWorker runs each job in this process (no fork), so the test sees
    everything it does; burst=True makes work() return when nothing is left."""
    worker = SimpleWorker([Queue(name, connection=conn) for name in QUEUES], connection=conn)
    worker.work(burst=True, with_scheduler=False)


def _wait_for(check: Callable[[], bool], timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError(f"condition not reached within {timeout_s} s")
        time.sleep(0.1)


@pytest.fixture
def redis_conn() -> Redis:
    conn = Redis.from_url(get_settings().redis_url)
    for name in QUEUES:
        Queue(name, connection=conn).empty()  # no leftovers from other tests
    return conn


## --- tasks.py: direct calls ------------------------------------------------------------------
def test_run_trajectory_returns_periods() -> None:
    result = tasks.run_trajectory(
        {
            "spec": BITCOIN,
            "horizon": 10,
            "seed": 1,
            "principal_id": "alice",
            "verification_ref": "vref:x",
        }
    )
    assert result["kind"] == "trajectory"
    assert result["verification_ref"] == "vref:x"
    # The initial state (t = 0), then one snapshot per period.
    assert [s["t"] for s in result["snapshots"]] == list(range(11))


## --- queue.py + a real worker -----------------------------------------------------------------
def test_queued_job_runs_and_its_result_is_readable(redis_conn: Redis) -> None:
    user = _user()
    job_id = queue.enqueue_job(
        "trajectory",
        {"spec": BITCOIN, "horizon": 10, "seed": None},
        user,
        "vref:x",
        correlation_id="c-1",
    )
    assert queue.get_job(job_id, user).status == "queued"
    _run_worker(redis_conn)
    info = queue.get_job(job_id, user)
    assert (info.status, info.progress, info.retry_after_s) == ("finished", 1.0, None)
    assert info.result is not None and info.result["kind"] == "trajectory"


def test_other_users_job_is_not_found(redis_conn: Redis) -> None:
    alice, bob = _user(), _user()
    job_id = queue.enqueue_job(
        "trajectory", {"spec": BITCOIN, "horizon": 10, "seed": 1}, alice, "vref:x"
    )
    _run_worker(redis_conn)
    assert queue.get_job(job_id, alice).status == "finished"
    with pytest.raises(NotFound):
        queue.get_job(job_id, bob)
    with pytest.raises(NotFound):
        queue.cancel_job(job_id, bob)
    with pytest.raises(NotFound):
        queue.get_job("job-does-not-exist", alice)


def test_identical_seeded_request_reuses_job(redis_conn: Redis) -> None:
    user = _user()
    payload = {"spec": BITCOIN, "horizon": 10, "seed": 7}
    a = queue.enqueue_job("trajectory", payload, user, "vref:x")
    _run_worker(redis_conn)
    b = queue.enqueue_job("trajectory", payload, user, "vref:x")
    assert a == b
    assert len(Queue("simulations", connection=redis_conn)) == 0  # nothing new was queued


def test_unseeded_and_report_requests_are_never_reused(redis_conn: Redis) -> None:
    user = _user()
    a = queue.enqueue_job(
        "trajectory", {"spec": BITCOIN, "horizon": 10, "seed": None}, user, "vref:x"
    )
    b = queue.enqueue_job(
        "trajectory", {"spec": BITCOIN, "horizon": 10, "seed": None}, user, "vref:x"
    )
    r1 = queue.enqueue_job("report", {"narrative": {}}, user, "vref:x")
    r2 = queue.enqueue_job("report", {"narrative": {}}, user, "vref:x")
    assert a != b
    assert r1 != r2
    for job_id in (a, b, r1, r2):  # leave nothing queued behind
        queue.cancel_job(job_id, user)


def test_cancelled_queued_job_never_runs(redis_conn: Redis) -> None:
    user = _user()
    job_id = queue.enqueue_job(
        "trajectory", {"spec": BITCOIN, "horizon": 10, "seed": 3}, user, "vref:x"
    )
    assert queue.cancel_job(job_id, user).status == "cancelled"
    _run_worker(redis_conn)
    info = queue.get_job(job_id, user)
    assert (info.status, info.result) == ("cancelled", None)


def test_failing_job_reports_a_short_error(redis_conn: Redis) -> None:
    user = _user()
    job_id = queue.enqueue_job(
        "trajectory", {"spec": "not: [a token economy", "seed": None}, user, "vref:x"
    )
    _run_worker(redis_conn)
    info = queue.get_job(job_id, user)
    assert info.status == "failed"
    assert info.error and "Traceback" not in info.error and len(info.error) <= 300


def test_running_job_can_be_stopped(redis_conn: Redis, tmp_path: Path) -> None:
    """A real `te-worker` process (worker.py) runs the job in a child
    process; cancel_job sends it the stop command, and RQ calls
    tasks.on_job_stopped in the worker."""
    user = _user()
    log = (tmp_path / "worker.log").open("w")
    worker = subprocess.Popen(
        [sys.executable, "-m", "te_platform.jobs.worker"],
        env=os.environ.copy(),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        # A long run (a large horizon), so it is still running when we stop it.
        job_id = queue.enqueue_job(
            "trajectory",
            {"spec": BITCOIN, "horizon": 10_000, "seed": None, "max_agents": 200},
            user,
            "vref:x",
        )
        _wait_for(lambda: queue.get_job(job_id, user).status == "running")
        queue.cancel_job(job_id, user)
        _wait_for(lambda: queue.get_job(job_id, user).status == "cancelled")
        ## Guide 6.2: the worker's on_job_stopped callback updated the table.
        _wait_for(lambda: _stored(job_id, user)["status"] == "cancelled")
    finally:
        worker.terminate()
        worker.wait(timeout=60)
        log.close()


## --- The jobs table (guide 6.2) -----------------------------------------------------------------
## Guide 6.2: read a job's row as its owner.
def _stored(job_id: str, user: Principal) -> dict:
    with session_scope() as db:
        return Repository(db, user).get_job(job_id)


## Guide 6.2: each way of ending a job is written to the jobs table.
def test_every_outcome_is_stored(redis_conn: Redis) -> None:
    user = _user()
    done = queue.enqueue_job(
        "trajectory", {"spec": BITCOIN, "horizon": 10, "seed": 11}, user, "vref:x"
    )
    broken = queue.enqueue_job("trajectory", {"spec": "not: [valid", "seed": None}, user, "vref:x")
    cancelled = queue.enqueue_job(
        "trajectory", {"spec": BITCOIN, "horizon": 10, "seed": 12}, user, "vref:x"
    )
    assert _stored(done, user)["status"] == "queued"  # written BEFORE the job was queued
    queue.cancel_job(cancelled, user)
    _run_worker(redis_conn)
    row = _stored(done, user)
    assert row["status"] == "finished"
    assert row["result"] == queue.get_job(done, user).result
    assert row["params"] == {"horizon": 10, "seed": 11}  # the spec is not copied
    assert _stored(broken, user)["status"] == "failed"
    assert _stored(cancelled, user)["status"] == "cancelled"


## Guide 6.2: a failed seeded job is retried under the same id.
def test_failed_seeded_job_runs_again(redis_conn: Redis) -> None:
    user = _user()
    payload = {"spec": "not: [valid", "seed": 5}
    first = queue.enqueue_job("trajectory", payload, user, "vref:x")
    _run_worker(redis_conn)
    assert queue.get_job(first, user).status == "failed"
    again = queue.enqueue_job("trajectory", payload, user, "vref:x")
    assert again == first
    assert queue.get_job(again, user).status == "queued"
    assert _stored(again, user)["status"] == "queued"
    queue.cancel_job(again, user)


## --- Quota slots (guide 6.3) ---------------------------------------------------------------------
## Guide 6.3: the number of this user's jobs that have not ended yet.
def _running(conn: Redis, user: Principal) -> int:
    return int(conn.get(_running_key(user.id)) or 0)


## Guide 6.3: however a job ends, its slot comes back, and only once.
def test_quota_slot_is_released_however_the_job_ends(redis_conn: Redis) -> None:
    user = _user()
    done = queue.enqueue_job(
        "trajectory", {"spec": BITCOIN, "horizon": 10, "seed": None}, user, "vref:x"
    )
    queue.enqueue_job("trajectory", {"spec": "not: [valid", "seed": None}, user, "vref:x")
    cancelled = queue.enqueue_job(
        "trajectory", {"spec": BITCOIN, "horizon": 10, "seed": None}, user, "vref:x"
    )
    assert _running(redis_conn, user) == 3
    queue.cancel_job(cancelled, user)
    assert _running(redis_conn, user) == 2
    _run_worker(redis_conn)  # one finishes, one fails
    assert _running(redis_conn, user) == 0
    # A second report of the same end must not give a slot back again:
    # with one job running, the counter must stay at 1.
    queue.enqueue_job("trajectory", {"spec": BITCOIN, "horizon": 10, "seed": None}, user, "vref:x")
    queue.settle_job(done, user.id, "finished")
    assert _running(redis_conn, user) == 1
    _run_worker(redis_conn)
    assert _running(redis_conn, user) == 0
