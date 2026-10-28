## =============================================================================
## tests/platform_tests/test_platform_security.py — tests for te_platform/security/
## =============================================================================
## GUIDE STEP   4.2 (api_keys), 6.3 (quotas), 9.0 (access codes),
##              9.2 (the chat pages' Content-Security-Policy), 10.3
##              (signed_urls)
## PURPOSE      Security code must be proven, not assumed. These tests check:
##              keys are random, prefixed and hashed; the plain key is not in
##              its hash; quotas count per principal and per window, against
##              a real Redis; signed links work, expire, and break when
##              altered.
## REDIS        The quota tests talk to the real Redis named by TE_REDIS_URL
##              (from guide 6.1 on it runs in Compose: `docker compose up -d
##              redis`, and TE_REDIS_URL=redis://localhost:6379/0 if you run
##              pytest on the host). No imitation of Redis: what is tested is
##              exactly what runs in production (atomic INCR, EXPIRE NX).
##              Each test uses its own random principal id, so tests never
##              see each other's counters, and deletes its keys afterwards.
## ACTIVATE     4.2: uncomment the file. Each later block (imports at the top
##              and tests below) is commented twice under a "## Guide X.Y"
##              line: toggle it again together with the module it tests.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE). Each step's imports
## go at the top of the file (Python wants imports first), each group under
## its own "Guide X.Y" comment, in step order (the tests' lint rules do not
## sort imports, so the groups can stay as they are).
##
## Guide 4.2
## [ ] 1. Import KEY_PREFIX, generate_api_key, hash_api_key from
##        te_platform.security.api_keys.
## [ ] 2. test_keys_are_unique_prefixed_and_hash_matches: two generated
##        keys differ, the first starts with KEY_PREFIX, hash_api_key of it
##        equals its returned hash, and the plain key is not in the hash.
## [ ] 3. Check:
##          | uv run pytest tests/platform_tests/test_platform_security.py -q
##
## Guide 6.3 (Redis running, TE_REDIS_URL set: header, REDIS)
## [ ] 4. Imports: `time`, `uuid`, `pytest`, `redis`, get_settings
##        (te_platform.config), Principal (te_platform.registry.context)
##        and `quotas` (te_platform.security).
## [ ] 5. Fixture `limits(monkeypatch)`: set TE_MAX_TOOL_CALLS_PER_MINUTE
##        "3", TE_MAX_CONCURRENT_JOBS "2", TE_MAX_JOBS_PER_DAY "3"; clear
##        the settings cache; `yield`; clear it again. monkeypatch restores
##        the variables, and the code after `yield` always runs, so the
##        limits cannot leak into other tests.
## [ ] 6. Fixture `new_principal()`: a factory that returns
##        Principal(id="test-" + uuid4 hex, kind="api_key") and remembers
##        the ids; after `yield`, delete every "te:*<id>*" key in Redis
##        (redis.Redis.from_url(get_settings().redis_url).scan_iter).
## [ ] 7. test_rate_limit_allows_up_to_limit_then_refuses (anyio): four
##        check_rate_limit calls give [True, True, True, False]. Before
##        them, if fewer than 5 s are left in the current minute, sleep
##        until the next one (the window is the clock minute).
## [ ] 8. test_rate_limits_are_per_principal: after alice is refused, bob
##        is still allowed.
## [ ] 9. test_job_quota_counts_running_jobs: available; two
##        job_started_sync -> not available; one job_finished_sync ->
##        available again.
## [ ] 10. test_job_quota_counts_jobs_per_day: three started-and-finished
##        jobs -> not available, although none is running.
## [ ] 11. test_running_counter_never_goes_below_zero: job_finished_sync
##        twice on a new principal, then two job_started_sync -> not
##        available (a counter at -1 would still allow a job).
## [ ] 12. Check: activate conftest.py too, then the step 3 command.
##
## Guide 9.0
## [ ] 13. Import generate_access_code; test_access_codes_are_prefixed_and_
##        hashed: starts with "tu_", hash_api_key of it equals its hash.
##
## Guide 9.2 (webapp/chat_routes.py's 9.2 block active, and the blueprint
## registered in webapp/app.py at 9.0)
## [ ] 14. Import `app as web_app` from webapp.app.
##        test_chat_pages_forbid_inline_scripts, parametrized over "/login"
##        and "/chat": the page answers 200, the script-src directive of
##        its Content-Security-Policy has no 'unsafe-inline', and the
##        policy contains "frame-ancestors 'none'". The form page "/" has
##        no such header (it gets the site-wide one from Caddy at 12.3).
##
## Guide 10.3
## [ ] 15. Imports: UTC, datetime, timedelta (datetime), parse_qs and
##        urlparse (urllib.parse), and `signed_urls` (te_platform.security).
## [ ] 16. Fixture `signing_key(monkeypatch)`: set TE_REPORT_SIGNING_KEY to
##        a long test value, clear the settings cache, `yield`, clear it
##        again.
## [ ] 17. Helper `_parse(url) -> tuple[str, int, str]`: with urlparse and
##        parse_qs, return (last path part = report id, int(exp), sig).
## [ ] 18. test_valid_link_verifies: sign "r1" for one hour from now; the
##        URL starts with "/agent/reports/r1?" and
##        verify_download(*_parse(url)) is true.
## [ ] 19. test_expired_link_fails: an expiry one second ago -> false.
## [ ] 20. test_tampered_link_fails: report id "r2", or exp + 3600, with
##        the same sig -> false.
## [ ] 21. Check: the step 3 command.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from te_platform.security.api_keys import KEY_PREFIX, generate_api_key, hash_api_key

## Guide 6.3: imports of the quota tests.
import time
import uuid
import pytest
import redis
from te_platform.config import get_settings
from te_platform.registry.context import Principal
from te_platform.security import quotas

## Guide 9.0: access codes.
from te_platform.security.api_keys import generate_access_code

## Guide 9.2: the Flask web app, for its chat pages' security header.
from webapp.app import app as web_app

## Guide 10.3: imports of the signed-link tests.
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from te_platform.security import signed_urls


## --- api_keys (guide 4.2) --------------------------------------------------------
def test_keys_are_unique_prefixed_and_hash_matches():
    a_plain, a_hash = generate_api_key()
    b_plain, _ = generate_api_key()
    assert a_plain != b_plain
    assert a_plain.startswith(KEY_PREFIX)
    assert hash_api_key(a_plain) == a_hash
    assert a_plain not in a_hash  # the hash does not contain the key


## --- quotas (guide 6.3) ----------------------------------------------------------
## Guide 6.3: small limits for the tests, always restored afterwards.
@pytest.fixture
def limits(monkeypatch):
    monkeypatch.setenv("TE_MAX_TOOL_CALLS_PER_MINUTE", "3")
    monkeypatch.setenv("TE_MAX_CONCURRENT_JOBS", "2")
    monkeypatch.setenv("TE_MAX_JOBS_PER_DAY", "3")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


## Guide 6.3: a fresh principal per call, so tests never share counters; the
## keys of every principal created are deleted when the test ends.
@pytest.fixture
def new_principal():
    ids = []

    def make():
        ids.append("test-" + uuid.uuid4().hex)
        return Principal(id=ids[-1], kind="api_key")

    yield make
    r = redis.Redis.from_url(get_settings().redis_url)
    for pid in ids:
        for key in r.scan_iter(match=f"te:*{pid}*"):
            r.delete(key)
    r.close()


## Guide 6.3: the rate-limit window is the clock minute; four calls must not
## straddle two minutes, or the fourth would start a new count.
def _wait_for_room_in_this_minute():
    left = 60 - time.time() % 60
    if left < 5:
        time.sleep(left + 0.1)


## Guide 6.3: the rate limit.
@pytest.mark.anyio
async def test_rate_limit_allows_up_to_limit_then_refuses(limits, new_principal):
    p = new_principal()
    _wait_for_room_in_this_minute()
    results = [await quotas.check_rate_limit(p) for _ in range(4)]
    assert results == [True, True, True, False]


## Guide 6.3: Bob's counter is separate from Alice's.
@pytest.mark.anyio
async def test_rate_limits_are_per_principal(limits, new_principal):
    alice, bob = new_principal(), new_principal()
    _wait_for_room_in_this_minute()
    for _ in range(4):
        await quotas.check_rate_limit(alice)
    assert not await quotas.check_rate_limit(alice)
    assert await quotas.check_rate_limit(bob)


## Guide 6.3: at most max_concurrent_jobs (2 here) running at once.
@pytest.mark.anyio
async def test_job_quota_counts_running_jobs(limits, new_principal):
    p = new_principal()
    assert await quotas.job_quota_available(p)
    quotas.job_started_sync(p.id)
    quotas.job_started_sync(p.id)
    assert not await quotas.job_quota_available(p)
    quotas.job_finished_sync(p.id)
    assert await quotas.job_quota_available(p)


## Guide 6.3: at most max_jobs_per_day (3 here), even if all have finished.
@pytest.mark.anyio
async def test_job_quota_counts_jobs_per_day(limits, new_principal):
    p = new_principal()
    for _ in range(3):
        quotas.job_started_sync(p.id)
        quotas.job_finished_sync(p.id)
    assert not await quotas.job_quota_available(p)


## Guide 6.3: a duplicate "finished" (e.g. a retried clean-up) must not
## give the caller an extra slot.
@pytest.mark.anyio
async def test_running_counter_never_goes_below_zero(limits, new_principal):
    p = new_principal()
    quotas.job_finished_sync(p.id)
    quotas.job_finished_sync(p.id)
    quotas.job_started_sync(p.id)
    quotas.job_started_sync(p.id)
    assert not await quotas.job_quota_available(p)


## --- access codes (guide 9.0) ------------------------------------------------------
## Guide 9.0: a person's login code has its own prefix and the same hash.
def test_access_codes_are_prefixed_and_hashed():
    plain, code_hash = generate_access_code()
    assert plain.startswith("tu_")
    assert hash_api_key(plain) == code_hash


## --- signed_urls (guide 10.3) -------------------------------------------------------
## Guide 9.2: the login and chat pages may run scripts only from this site
## and the pinned CDN, never inline code (webapp/chat_routes.py, 9.2 block).
## The form page is not covered by it (its policy comes from Caddy, 12.3).
@pytest.mark.parametrize("path", ["/login", "/chat"])
def test_chat_pages_forbid_inline_scripts(path):
    client = web_app.test_client()
    r = client.get(path)
    assert r.status_code == 200
    csp = r.headers["Content-Security-Policy"]
    script_src = next(d for d in csp.split("; ") if d.startswith("script-src "))
    assert "'unsafe-inline'" not in script_src
    assert "frame-ancestors 'none'" in csp
    assert "Content-Security-Policy" not in client.get("/").headers


## Guide 10.3: Settings are read from environment variables; set the signing
## key for the test and clear the cached Settings so it is read again.
@pytest.fixture
def signing_key(monkeypatch):
    monkeypatch.setenv("TE_REPORT_SIGNING_KEY", "test-key-" + "x" * 40)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


## Guide 10.3: split a signed link into the three values verify_download takes.
def _parse(url: str) -> tuple[str, int, str]:
    u = urlparse(url)
    q = parse_qs(u.query)
    return u.path.rsplit("/", 1)[1], int(q["exp"][0]), q["sig"][0]


## Guide 10.3: the link is served by the agent service (agent/user_reports_api.py).
def test_valid_link_verifies(signing_key):
    url = signed_urls.sign_download("r1", datetime.now(UTC) + timedelta(hours=1))
    assert url.startswith("/agent/reports/r1?")
    assert signed_urls.verify_download(*_parse(url))


## Guide 10.3: expired links fail even with a correct signature.
def test_expired_link_fails(signing_key):
    url = signed_urls.sign_download("r1", datetime.now(UTC) - timedelta(seconds=1))
    assert not signed_urls.verify_download(*_parse(url))


## Guide 10.3: the signature binds the report id AND the expiry.
def test_tampered_link_fails(signing_key):
    rid, exp, sig = _parse(signed_urls.sign_download("r1", datetime.now(UTC) + timedelta(hours=1)))
    assert not signed_urls.verify_download("r2", exp, sig)  # other report
    assert not signed_urls.verify_download(rid, exp + 3600, sig)  # extended expiry
