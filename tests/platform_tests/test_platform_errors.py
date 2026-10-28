## =============================================================================
## tests/platform_tests/test_platform_errors.py — tests for te_platform/errors.py
## =============================================================================
## GUIDE STEP   1.1 (activate together with errors.py)
## PURPOSE      Proves that error codes serialise as plain strings (what MCP
##              clients and the agent read) and that a precondition failure
##              carries its `do_first` list.
## DEPENDS ON   te_platform/errors.py.
## WHY          Guide §2.1 "errors are values": the JSON shape of an error is a
##              contract with every client; these tests pin it.
## ACTIVATE     Uncomment with errors.py.
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
## [ ] 1. Imports: `json`, and `ErrorCode, PreconditionFailed, ToolError`
##        from te_platform.errors.
## [ ] 2. test_error_code_serialises_as_plain_string: build a ToolError with
##        error=ErrorCode.PRECONDITION_FAILED, a message and a
##        correlation_id; json.loads its model_dump_json(), then
##          | assert data["error"] == "precondition_failed"
##        and str(ErrorCode.TIMEOUT) == "timeout" (a StrEnum member IS its
##        value, also in f-strings and log lines).
## [ ] 3. test_error_codes_are_a_closed_known_set: {c.value for c in
##        ErrorCode} equals exactly the seven codes validation_error,
##        precondition_failed, quota_exceeded, timeout, forbidden,
##        not_found and internal_error.
## [ ] 4. test_precondition_failed_keeps_do_first: PreconditionFailed(
##        "verified_spec", "verify first", ["verify.run.v1"]) keeps that
##        list in .do_first, and str(exc) is the message "verify first".
## [ ] 5. Check:
##          | uv run pytest tests/platform_tests/test_platform_errors.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import json

from te_platform.errors import ErrorCode, PreconditionFailed, ToolError


def test_error_code_serialises_as_plain_string():
    err = ToolError(error=ErrorCode.PRECONDITION_FAILED, message="m", correlation_id="c")
    data = json.loads(err.model_dump_json())
    assert data["error"] == "precondition_failed"
    assert str(ErrorCode.TIMEOUT) == "timeout"


def test_error_codes_are_a_closed_known_set():
    # Adding a code is a contract change for clients: update this list
    # deliberately (and docs/api-contract.md) when you do.
    assert {c.value for c in ErrorCode} == {
        "validation_error",
        "precondition_failed",
        "quota_exceeded",
        "timeout",
        "forbidden",
        "not_found",
        "internal_error",
    }


def test_precondition_failed_keeps_do_first():
    exc = PreconditionFailed("verified_spec", "verify first", ["verify.run.v1"])
    assert exc.do_first == ["verify.run.v1"]
    assert str(exc) == "verify first"
