## =============================================================================
## te_platform/errors.py — structured errors ("errors are values")
## =============================================================================
## GUIDE STEP   1.1 (used from phase 2 onwards)
## PURPOSE      Defines the closed list of error codes a tool may return, and
##              the error objects that carry them. A tool never sends a Python
##              stack trace to a client; it returns one of these instead, with
##              a message a person (or an LLM) can act on, and a correlation ID
##              that links it to the full trace in the server log.
## USED BY      registry/pipeline.py (turns the exceptions below into
##              ToolErrors and returns them), tools/*.py (raise InvalidInput /
##              NotFound / PreconditionFailed), db/repo.py and jobs/queue.py
##              (NotFound for foreign or unknown ids), elicitation/answers.py,
##              reports/render.py, mcp_server/ (errors raised before the
##              pipeline runs), agent/app.py (NotFound -> HTTP 404).
##              The ToolError JSON then reaches the model through MCP (the
##              agent passes it back verbatim, agent/mcp_bridge.py), so it can
##              correct itself using `do_first`.
## DEPENDS ON   pydantic.
## WHY          Guide §2.1 "errors are values at boundaries"; architecture D4
##              (structured `precondition_failed` with `do_first` lets any
##              model correct itself in one step). A closed list of codes
##              means clients can handle every case explicitly.
## ACTIVATE     Uncomment everything; test: test_platform_errors.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the public names
## exactly as written here: other files import them (te_platform/README.md,
## contracts table).
##
## Guide 1.1
## [ ] 1. Imports at the top: `StrEnum` from enum; `Any` from typing;
##        `BaseModel` and `Field` from pydantic.
## [ ] 2. `class ErrorCode(StrEnum)` (keep this name exactly), with a
##        docstring, and seven members, each value being the member name in
##        lower case:
##          | VALIDATION_ERROR = "validation_error"
##        then PRECONDITION_FAILED, QUOTA_EXCEEDED, TIMEOUT, FORBIDDEN,
##        NOT_FOUND, INTERNAL_ERROR. No more, no less: it is a closed list
##        (the tests check the exact set). Copy the short end-of-line
##        comment of each member from the SOLUTION.
## [ ] 3. `class ToolError(BaseModel)` (keep this name exactly) with the
##        fields, in this order: error: ErrorCode; message: str;
##        precondition: str | None = None; do_first: list[str] and
##        details: list[dict[str, Any]], both with Field(default_factory=list);
##        correlation_id: str (required, no default).
## [ ] 4. `class PreconditionFailed(Exception)` (keep this name exactly),
##        with a docstring. Its __init__(self, precondition: str,
##        message: str, do_first: list[str]) -> None calls
##        super().__init__(message) and stores the three arguments as
##        attributes of the same names. ruff's N818 wants exception names
##        to end in "Error"; these names are a contract (README §2), so
##        silence N818 on the class line with a `noqa` comment that gives
##        the reason (copy it from the SOLUTION).
## [ ] 5. `class InvalidInput(Exception)` and `class NotFound(Exception)`
##        (keep these names exactly, same noqa): their body is only a
##        docstring saying when to raise them (copy the SOLUTION's
##        wording).
## [ ] 6. Check: activate tests/platform_tests/test_platform_errors.py, then
##          | uv run pytest tests/platform_tests/test_platform_errors.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


## --- Error codes ---------------------------------------------------------------
## StrEnum: each member is also a plain string, so it serialises to JSON as
## "precondition_failed" rather than as an object, and str(member) is its
## value too.
class ErrorCode(StrEnum):
    """The closed list of error codes a tool call can end with."""

    VALIDATION_ERROR = "validation_error"  # input does not match the tool's schema
    PRECONDITION_FAILED = "precondition_failed"  # policy says: do something else first
    QUOTA_EXCEEDED = "quota_exceeded"  # caller used up their allowance
    TIMEOUT = "timeout"  # handler ran longer than allowed
    FORBIDDEN = "forbidden"  # authenticated, but not allowed
    NOT_FOUND = "not_found"  # e.g. unknown job_id or session
    INTERNAL_ERROR = "internal_error"  # a bug: details only in the server log


## --- The error object returned to clients --------------------------------------
class ToolError(BaseModel):
    """What a client receives when a tool call does not succeed."""

    error: ErrorCode
    # Human-readable explanation. Written for the end user and for the LLM:
    # say what went wrong and what to do, never internal details.
    message: str
    # Only for PRECONDITION_FAILED: which precondition, and which tools to
    # run first (copied from policy/tool_policy.yaml -> preconditions).
    precondition: str | None = None
    do_first: list[str] = Field(default_factory=list)
    # Only for VALIDATION_ERROR: Pydantic's list of field problems.
    details: list[dict[str, Any]] = Field(default_factory=list)
    # Matches the server log entry that holds the full stack trace.
    correlation_id: str


## --- Exception used *inside* the server ----------------------------------------
## Preconditions and handlers may raise these; the pipeline catches them and
## converts them into ToolErrors. They never leave the server as exceptions.
## `noqa: N818`: ruff wants exception names to end in "Error", but these
## names are part of the shared contracts (te_platform/README.md §2).
class PreconditionFailed(Exception):  # noqa: N818  contract name, see above
    """A policy precondition does not hold; `do_first` says what to run first."""

    def __init__(self, precondition: str, message: str, do_first: list[str]) -> None:
        super().__init__(message)
        self.precondition = precondition
        self.message = message
        self.do_first = do_first


class InvalidInput(Exception):  # noqa: N818  contract name, see above
    """The input passed schema validation but is still unusable.

    Example: neither a spec nor a session was given. Becomes a
    VALIDATION_ERROR; the message is shown to the caller, so keep it helpful.
    """


class NotFound(Exception):  # noqa: N818  contract name, see above
    """A referenced object (job, session) does not exist or is not the caller's.

    Both cases deliberately look the same to the client, so nobody can
    probe which IDs exist.
    """
