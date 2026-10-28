## =============================================================================
## tests/platform_tests/conftest.py — shared test setup for the platform tests
## =============================================================================
## GUIDE STEP   6.3 (first needed when the quota code in the pipeline is active)
## PURPOSE      pytest automatically loads a file named conftest.py and makes
##              its fixtures available to every test in this folder. A
##              *fixture* is a function that prepares something for a test
##              and cleans it up afterwards; `autouse=True` applies it to every
##              test without being requested.
## WHY          Async Redis clients are bound to the event loop they were first
##              used in. A server process has one loop, so te_platform caches
##              one client per process (security/quotas.py). pytest-anyio runs
##              a NEW loop for each async test, so a cached client from an
##              earlier test would fail with "Event loop is closed". Clearing
##              the cache after each test gives every test its own client.
##              (Found by running the scaffold: 14 tests failed without it.)
## ACTIVATE     Uncomment together with security/quotas.py (guide 6.3).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Lines
## starting with "|" are short illustrations, not the full code. Activate
## this file only together with security/quotas.py (header, ACTIVATE): the
## fixture reads quotas._redis, which exists only from guide 6.3.
##
## Guide 6.3
## [ ] 1. Top imports: `pytest`, and `quotas` from te_platform.security.
## [ ] 2. A fixture `_fresh_async_clients()` (no arguments), decorated with
##        @pytest.fixture(autouse=True) so it applies to every test. It does
##        nothing before the test: its body starts with `yield`.
## [ ] 3. After the `yield` (cleanup, runs when the test ends), clear the
##        cached Redis client of quotas.py:
##          | quotas._redis.cache_clear()
##        This is the "Event loop is closed" fix the header's WHY explains.
## [ ] 4. Check: run the quota tests, then the whole platform folder:
##          | uv run pytest tests/platform_tests/test_platform_security.py -q
##          | uv run pytest tests/platform_tests -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import pytest

from te_platform.security import quotas


@pytest.fixture(autouse=True)
def _fresh_async_clients():
    yield
    quotas._redis.cache_clear()
