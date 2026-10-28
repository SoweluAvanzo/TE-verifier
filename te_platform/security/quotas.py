## =============================================================================
## te_platform/security/quotas.py — rate limits and job quotas, counted in Redis
## =============================================================================
## GUIDE STEP   6.3
## PURPOSE      Two checks, both per principal (per caller):
##              - check_rate_limit(principal): at most
##                Settings.max_tool_calls_per_minute tool calls per minute.
##                The pipeline (step 2) refuses the call with
##                `quota_exceeded` when this returns False.
##              - job_quota_available(principal): may this caller start another
##                simulation job? (fewer than max_concurrent_jobs running, and
##                fewer than max_jobs_per_day started today). The pipeline
##                stores the answer in ctx.facts.quota_ok; the policy's
##                precondition `job_quota_available` then enforces it.
##              Plus the counting functions called when a job really starts
##              (jobs/queue.py: job_started_sync) and ends (jobs/queue.py
##              settle_job, which the callbacks of jobs/tasks.py call:
##              job_finished_sync).
## USED BY      registry/pipeline.py (step 2), jobs/queue.py (job_started_sync
##              and, in settle_job, job_finished_sync).
## DEPENDS ON   redis (the redis-py package, async client), config.py.
## WHY          Guide 6.3. A counter in a process's memory (like the per-IP
##              limiter of webapp/app.py) is counted separately by every
##              worker and vanishes on restart. Redis is shared by all
##              processes and containers and survives restarts, so limits
##              hold globally. (The web form's limiter stays: the form has no
##              principal; Caddy limits per IP from guide 12.3.)
## ATOMICITY    "Read the count, add one, write it back" done in three steps
##              would lose updates when two requests arrive at the same moment
##              (both read 5, both write 6). Redis's INCR does the read-add-write
##              as ONE atomic operation, so concurrent requests are always
##              counted correctly. The key's expiry (EXPIRE) makes old counts
##              disappear by themselves, so no clean-up job is needed.
## WINDOW       A "fixed window": the count for "principal P, minute 12:34"
##              lives in its own key that expires after 60 s. Simple and
##              predictable; a burst at the end of one minute and the start of
##              the next can briefly allow up to twice the limit, which is
##              acceptable here (the edge rate limit in Caddy, guide 12.3, and
##              the job quotas protect against heavy abuse).
## ACTIVATE     Uncomment; then uncomment the quota lines in pipeline.py step 2.
##              Tests: test_platform_security.py, against the real Redis
##              given by TE_REDIS_URL (e.g. `docker compose up -d redis`).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the public names
## exactly as written here: pipeline.py and jobs/queue.py call them. Needs
## config.py (redis_url and the three limits), registry/context.py
## (Principal) and the `jobs` extra (redis).
##
## Guide 6.3
## [ ] 1. Imports at the top: `time`, `lru_cache` (functools), `redis`
##        (the sync client, step 6), `Redis` (redis.asyncio),
##        `get_settings` (te_platform.config) and `Principal`
##        (te_platform.registry.context).
## [ ] 2. `_redis() -> Redis`, decorated with @lru_cache(maxsize=1),
##        returning Redis.from_url(get_settings().redis_url). Read its
##        docstring: conftest.py clears this cache after each test.
## [ ] 3. Three key helpers, each taking a principal id (str) and
##        returning a str, so the async checks (which get a Principal)
##        and the sync counters (which get an id) build the SAME keys:
##          | f"te:rate:{principal_id}:{int(time.time() // 60)}"
##        `_minute_key` (above), `_day_key` ("te:jobs:day:<id>:<YYYYMMDD>",
##        UTC date via time.gmtime()) and `_running_key`
##        ("te:jobs:running:<id>").
## [ ] 4. `async def check_rate_limit(principal) -> bool`: in ONE
##        transactional pipeline, INCR the minute key and EXPIRE it after
##        60 s with nx=True; return count <= max_tool_calls_per_minute.
## [ ] 5. `async def job_quota_available(principal) -> bool`: only READ the
##        running and day counters (a missing key counts as 0) and compare
##        them with max_concurrent_jobs and max_jobs_per_day. No counting.
## [ ] 6. `_sync_redis() -> redis.Redis`: a synchronous client,
##        redis.Redis.from_url(...). RQ code is synchronous.
## [ ] 7. `job_started_sync(principal_id: str) -> None`: in one transaction
##        INCR the day key (expire after 2 days, nx=True) and the running
##        key (expire after 1 day, the safety net explained there).
## [ ] 8. `job_finished_sync(principal_id: str) -> None`: DECR the running
##        key and set it back to 0 if the result is below zero.
## [ ] 9. Uncomment the quota lines in registry/pipeline.py step 2.
## [ ] 10. Check: activate tests/platform_tests/conftest.py and the guide
##        6.3 block of test_platform_security.py; with Redis running and
##        TE_REDIS_URL pointing at it:
##          | uv run pytest tests/platform_tests/test_platform_security.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import time
from functools import lru_cache

import redis
from redis.asyncio import Redis

from te_platform.config import get_settings
from te_platform.registry.context import Principal


@lru_cache(maxsize=1)
def _redis() -> Redis:
    """Return the process's shared async client (one connection pool).

    redis-py pools connections internally; creating a client per request
    would be slow. An asyncio Redis client belongs to the event loop it was
    first used in. A server process has exactly one loop, so caching is
    right there. Tests run one loop PER TEST: tests/platform_tests/
    conftest.py clears this cache after each test (_redis.cache_clear()),
    otherwise the second test would reuse a client bound to a closed loop.
    """
    return Redis.from_url(get_settings().redis_url)


## Key names: a fixed prefix (so our keys never clash with RQ's own keys in
## the same Redis) + what is counted + who + the time window. The helpers
## take the principal's id, because job_started_sync/job_finished_sync only
## have the id (from the job payload), and every counter must be built in
## exactly one place.
def _minute_key(principal_id: str) -> str:
    return f"te:rate:{principal_id}:{int(time.time() // 60)}"


def _day_key(principal_id: str) -> str:
    return f"te:jobs:day:{principal_id}:{time.strftime('%Y%m%d', time.gmtime())}"


def _running_key(principal_id: str) -> str:
    return f"te:jobs:running:{principal_id}"


async def check_rate_limit(principal: Principal) -> bool:
    """Count this call; return True if the caller is still within the limit."""
    key = _minute_key(principal.id)
    # A pipeline with transaction=True sends both commands together and runs
    # them as one unit (MULTI/EXEC). nx=True: set the expiry only when the
    # key is new, so later calls in the same minute don't extend it.
    async with _redis().pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, 60, nx=True)
        count, _ = await pipe.execute()
    return int(count) <= get_settings().max_tool_calls_per_minute


async def job_quota_available(principal: Principal) -> bool:
    """Return True if the caller may start another job. Only CHECKS.

    A call refused by another precondition must not use up the caller's
    quota, so counting happens in job_started_sync(), when a job really
    starts.
    """
    s = get_settings()
    r = _redis()
    running = int(await r.get(_running_key(principal.id)) or 0)
    today = int(await r.get(_day_key(principal.id)) or 0)
    return running < s.max_concurrent_jobs and today < s.max_jobs_per_day


## Counting runs in jobs/queue.py and jobs/tasks.py, which are synchronous
## (RQ is synchronous), so these use redis.Redis, the sync client.
def _sync_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url)


def job_started_sync(principal_id: str) -> None:
    """Count one started job; called by jobs/queue.enqueue_job for a NEW job."""
    day_key = _day_key(principal_id)
    running_key = _running_key(principal_id)
    with _sync_redis().pipeline(transaction=True) as pipe:
        pipe.incr(day_key)
        pipe.expire(day_key, 2 * 24 * 3600, nx=True)
        pipe.incr(running_key)
        # Safety net: if a job ends without job_finished_sync being called
        # (e.g. the worker machine dies), the running counter resets after
        # a day instead of blocking the user forever.
        pipe.expire(running_key, 24 * 3600)
        pipe.execute()


def job_finished_sync(principal_id: str) -> None:
    """Release one running slot; called when a job ends (any outcome)."""
    r = _sync_redis()
    key = _running_key(principal_id)
    # Never go below zero, even if job_finished_sync runs twice for one job.
    if int(r.decr(key)) < 0:
        r.set(key, 0)
