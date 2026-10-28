## =============================================================================
## te_platform/jobs/worker.py — the `te-worker` process
## =============================================================================
## GUIDE STEP   6.1
## PURPOSE      Starts an RQ worker: a process that waits for jobs on the
##              queues "simulations" and "reports", runs them one at a time
##              (functions in tasks.py), and stores their results in Redis.
##              The `worker` service in compose.yml runs this command; to
##              process more jobs in parallel, run more worker containers
##              (`docker compose up --scale worker=3`), not more threads.
## USED BY      compose.yml service `worker` (command: te-worker).
##              Declared in pyproject.toml [project.scripts] as te-worker.
## DEPENDS ON   rq, redis, config.py, observability.py (JSON logs),
##              jobs/tasks.py (on_work_horse_killed, see queue.py header
##              LIFECYCLE).
## WHY          D12. A separate process means a crashing or slow simulation can
##              never take the MCP server or the web app down with it, and the
##              container's CPU/memory limits apply to simulations alone.
## QUEUE ORDER  The worker always takes from the FIRST queue in its list that
##              has work. "reports" comes first: rendering is short and the user
##              is waiting for a download, while simulations are long anyway.
## ACTIVATE     Uncomment; `uv run te-worker` with Redis running, then enqueue a
##              small job from a test or a Python shell.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|"
## are short illustrations, not the full code.
##
## Guide 6.1 (first: config.py, observability.py and jobs/tasks.py active)
## [ ] 1. Imports at the top: Redis; Queue and Worker from rq;
##        check_environment and get_settings; on_work_horse_killed from
##        te_platform.jobs.tasks; configure_logging.
## [ ] 2. `main() -> None`, keep this name: pyproject's te-worker script
##        points to te_platform.jobs.worker:main. In it: check_environment(),
##        settings = get_settings(), configure_logging(settings) and
##        connection = Redis.from_url(settings.redis_url).
## [ ] 3. The queues, "reports" FIRST (header QUEUE ORDER):
##          | [Queue(name, connection=connection)
##          |  for name in ("reports", "simulations")]
## [ ] 4. Create the Worker with work_horse_killed_handler=
##        on_work_horse_killed (a job whose process dies is settled too),
##        then start working (this call blocks forever):
##          | worker.work(with_scheduler=False)
## [ ] 5. At the bottom: `if __name__ == "__main__":` calling main().
## [ ] 6. Check: with Redis running, `uv run te-worker`, then enqueue a small
##        job from a test or a Python shell (header ACTIVATE).
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from redis import Redis
from rq import Queue, Worker

from te_platform.config import check_environment, get_settings
from te_platform.jobs.tasks import on_work_horse_killed
from te_platform.observability import configure_logging


def main() -> None:
    """Run an RQ worker on the "reports" and "simulations" queues until stopped."""
    check_environment()  # fail fast on misspelled TE_* variables (config.py)
    settings = get_settings()
    configure_logging(settings)
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in ("reports", "simulations")]
    # work_horse_killed_handler: RQ runs each job in a child process (the
    # "work horse"); if that process dies (killed, out of memory), no
    # callback of the job runs, so this handler settles it instead
    # (queue.py header LIFECYCLE).
    worker = Worker(queues, connection=connection, work_horse_killed_handler=on_work_horse_killed)
    # with_scheduler=False: we schedule nothing for later; jobs run as soon
    # as a worker is free. work() blocks forever, processing jobs until the
    # container stops (it finishes the current job on a polite shutdown).
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
