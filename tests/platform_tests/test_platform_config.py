## =============================================================================
## tests/platform_tests/test_platform_config.py — tests for te_platform/config.py
## =============================================================================
## GUIDE STEP   1.1 (activate together with config.py), 5.2 (the secret
##              database_url setting, commented twice)
## PURPOSE      Proves that Settings reads TE_* environment variables, rejects
##              unknown ones (typos), and never prints secrets.
## USED BY      pytest (collected automatically once the code is uncommented).
## DEPENDS ON   te_platform/config.py, pytest's `monkeypatch` fixture (sets
##              environment variables for one test only, then restores them).
## WHY          Guide §2.1: configuration is validated once at startup; these
##              tests pin that behaviour so a later change cannot silently
##              break it.
## ACTIVATE     Uncomment with config.py (guide 1.1); the secret test is
##              commented twice: toggle it again at guide 5.2, together with
##              the first secret setting. Run
##              `uv run pytest tests/platform_tests/test_platform_config.py -q`.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
##
## Guide 1.1
## [ ] 1. Imports at the top: `os`, `Path` (pathlib), `pytest`,
##        `ValidationError` from pydantic, and `Settings,
##        check_environment, get_settings` from te_platform.config.
## [ ] 2. Fixture `_fresh_settings(monkeypatch)` with autouse=True: delete
##        every TE_* variable of os.environ with monkeypatch.delenv, call
##        get_settings.cache_clear(), `yield`, then clear the cache again.
##        Why: see the solution's `##` notes above the fixture.
## [ ] 3. test_defaults_are_safe_for_development: Settings() with no TE_*
##        variables has environment "development" and policy_dir
##        Path("policy").
## [ ] 4. test_environment_variable_overrides_default(monkeypatch): setenv
##        TE_POLICY_DIR to "/etc/te-policy"; get_settings().policy_dir ==
##        Path("/etc/te-policy") (the text is converted to a Path).
## [ ] 5. test_invalid_environment_value_is_rejected: TE_ENVIRONMENT set to
##        "staging" makes Settings() raise:
##          | with pytest.raises(ValidationError):
## [ ] 6. test_misspelled_variable_is_reported: check_environment(
##        {"TE_ENVIRONEMNT": "x"}) raises RuntimeError naming the variable
##        (pytest.raises(RuntimeError, match="TE_ENVIRONEMNT")).
## [ ] 7. test_known_and_non_settings_variables_pass: check_environment with
##        TE_POLICY_DIR, TE_IMAGE_TAG and PATH raises nothing (no assert
##        needed: an exception would fail the test).
## [ ] 8. Check:
##          | uv run pytest tests/platform_tests/test_platform_config.py -q
##
## Guide 5.2 (with the first secret setting, database_url)
## [ ] 9. test_secrets_are_not_printed(monkeypatch): set TE_DATABASE_URL to
##        a URL containing the password "very-secret"; "very-secret" is in
##        neither repr(s) nor str(s.database_url), but
##        s.database_url.get_secret_value() returns the whole URL.
## [ ] 10. Check: the step 8 command.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from te_platform.config import Settings, check_environment, get_settings


## get_settings() caches its result; clear the cache around every test so
## each test sees the environment it set up. `autouse=True` applies this
## fixture to every test in the file automatically.
## Every test starts from a clean environment: TE_* variables set in the
## developer's shell (or in CI) must not change what "the defaults" are.
## monkeypatch undoes every change after the test.
@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    for name in list(os.environ):
        if name.startswith("TE_"):
            monkeypatch.delenv(name)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_are_safe_for_development():
    s = Settings()
    assert s.environment == "development"
    assert s.policy_dir == Path("policy")


def test_environment_variable_overrides_default(monkeypatch):
    monkeypatch.setenv("TE_POLICY_DIR", "/etc/te-policy")
    assert get_settings().policy_dir == Path("/etc/te-policy")


def test_invalid_environment_value_is_rejected(monkeypatch):
    monkeypatch.setenv("TE_ENVIRONMENT", "staging")
    with pytest.raises(ValidationError):
        Settings()


## check_environment() is what really catches a misspelled variable:
## pydantic-settings itself silently ignores unknown TE_* names.
def test_misspelled_variable_is_reported():
    with pytest.raises(RuntimeError, match="TE_ENVIRONEMNT"):
        check_environment({"TE_ENVIRONEMNT": "x"})


def test_known_and_non_settings_variables_pass():
    check_environment({"TE_POLICY_DIR": "p", "TE_IMAGE_TAG": "abc", "PATH": "/bin"})


## Guide 5.2: the first secret setting (database_url) exists from here on.
def test_secrets_are_not_printed(monkeypatch):
    monkeypatch.setenv("TE_DATABASE_URL", "postgresql+psycopg://te_app:very-secret@db:5432/te")
    s = Settings()
    # repr/str (what ends up in logs and error messages) hide the value...
    assert "very-secret" not in repr(s)
    assert "very-secret" not in str(s.database_url)
    # ...while the code that needs it can still read it explicitly.
    assert "very-secret" in s.database_url.get_secret_value()
