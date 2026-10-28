## =============================================================================
## te_platform/registry/pipeline.py — the one path every tool call takes
## =============================================================================
## GUIDE STEP   2.4 (steps 1-8 below); the audit row in the database at 5.5,
##              the quotas at 6.3
## PURPOSE      call(registry, tool_id, raw_input, ctx) runs one tool call
##              through eight steps, always in this order:
##                1. authorise   — may this principal use this tool?
##                2. quota       — has the principal allowance left?
##                3. validate    — does the input match the tool's model?
##               3b. derive facts— spec hash, validity, verification match (facts.py)
##                4. precondition— does the policy allow it now?
##                5. run         — call the handler, with a timeout
##                6. check output— does the result match the output model?
##                7. suggest     — compute suggested_next from the policy
##                8. audit       — record who called what and the outcome
##                                 (a log line always; from 5.5 also an
##                                 audit_log row, for EVERY outcome, errors
##                                 included: see call() at the end)
##              It returns a ToolOutcome: either a result + suggestions, or a
##              ToolError. It never raises to the caller.
## USED BY      mcp_server/app.py (every MCP tool call), webapp REST routes
##              (after step 1.6/9.x), tests.
## DEPENDS ON   registry/* (incl. facts.py), errors.py, config.py; from 5.5
##              hashing.py (input hash), db/repo.py (write_audit) and
##              db/session.py; from 6.3 security/quotas.py (step 2).
##              Session facts are NOT loaded here: the transport does that
##              (mcp_server/app.py) before calling.
## WHY          D4: rules enforced in ONE place cannot be bypassed by any
##              transport (MCP, REST, agent). D7: suggestions computed by code.
##              Guide §2.1: errors are values; stack traces stay in the log.
## ACTIVATE     Uncomment the skeleton, then each step; test_platform_pipeline.py
##              has one test per branch (validation error, precondition
##              failure with do_first, override, timeout, invalid output, ok
##              with suggested_next), plus the audit row (5.5) and the rate
##              limit (6.3).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep `call` and
## `ToolOutcome` (and its fields) exactly as written: MCP clients receive
## this shape (te_platform/README.md, contracts table). Activate the other
## registry/* files, errors.py and config.py first.
##
## Guide 2.4
## [ ] 1. Imports at the top: logging, time, Any, anyio; BaseModel, Field,
##        ValidationError from pydantic; get_settings; ErrorCode,
##        InvalidInput, NotFound, PreconditionFailed, ToolError; CallContext;
##        derive_facts; Registry; and ARGS_FROM, PRECONDITIONS, PREDICATES.
##        (`hashing`, the db imports and `quotas` come at 5.5 and 6.3: an
##        import nothing uses yet is an error for ruff.) Then the logger:
##          | log = logging.getLogger("te_platform.pipeline")
## [ ] 2. Models, each with a docstring: `Suggestion` (tool, reason, args
##        dict defaulting to empty) and `ToolOutcome` (ok, result=None,
##        error=None, suggested_next list, correlation_id).
## [ ] 3. `_fail(ctx, code, message, **extra) -> ToolOutcome`: ok=False with
##        a ToolError carrying the code, message, ctx.correlation_id and
##        the extra fields (details, precondition, do_first).
## [ ] 4. `_check_preconditions(registry, ctx)` (step 4): loop over the tool's
##        policy preconditions; skip a passing rule; skip a failing one only
##        if ctx.override_reason is set AND the rule is overridable (log a
##        warning); else raise PreconditionFailed(name, message, do_first).
## [ ] 5. `_suggestions(registry, ctx)` (step 7): for each suggested_next rule
##        whose `after` is this tool and whose predicate holds, add a
##        Suggestion (args from ARGS_FROM if the rule names one). Skip rules
##        that suggest a `planned` tool.
## [ ] 6. `async def _run_steps(registry, tool_id, raw_input, ctx)`: unknown
##        or deprecated tool -> NOT_FOUND; then steps 1, 3, 3b, 4, 5, 6, 7 in
##        the order of the SOLUTION's numbered comments. Step 2 is only its
##        explanation for now (no quota yet). For step 5 add a timeout:
##          | with anyio.fail_after(get_settings().tool_timeout_s):
##          |     output = await tool.handler(validated, ctx)
##        and turn each exception into its ErrorCode; any other Exception is
##        logged with log.exception and becomes INTERNAL_ERROR. One return
##        per step exceeds ruff's complexity limits: keep the noqa comment
##        on the def line (the `##` lines above it say why).
## [ ] 7. `async def call(...)`: time _run_steps with time.monotonic() and
##        wrap it in try/except Exception (log.exception, INTERNAL_ERROR), so
##        call() never raises; compute result_code ("ok" or the error code
##        value), write the "tool call" log line (step 8: tool, principal,
##        outcome, latency_ms, correlation_id, override_reason), return
##        outcome.
## [ ] 8. Check: activate tests/platform_tests/test_platform_pipeline.py
##        (with facts.py), then
##          | uv run pytest tests/platform_tests/test_platform_pipeline.py -q
##          | uv run mypy te_platform
##
## Guide 5.5 (the "# # " lines under the `Guide 5.5` labels)
## [ ] 9. Uncomment the three imports (hashing, Repository, session_scope)
##        and, at the end of call(), the audit_log block: input_hash (a hash,
##        never the raw input), the inner _write(), and the try/except
##        around anyio.to_thread.run_sync(_write) (a failed write is logged,
##        the result is still returned).
## [ ] 10. Check: activate the Guide 5.5 test of test_platform_pipeline.py
##        (an audit row for a refused call), rerun the file, then
##          | uv run mypy te_platform
##
## Guide 6.3 (the "# # " lines under the `Guide 6.3` labels)
## [ ] 11. Uncomment the `quotas` import and, in step 2 of _run_steps, the
##        four quota lines (rate limit for every call; quota_ok for
##        "expensive" tools).
## [ ] 12. Check: activate the Guide 6.3 tests of test_platform_pipeline.py
##        (rate limit, job quota), rerun the file and `uv run mypy te_platform`.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import logging
import time
from typing import Any

import anyio
from pydantic import BaseModel, Field, ValidationError

## Guide 5.5: the audit_log row at the end of call() (commented twice).
from te_platform import hashing
from te_platform.config import get_settings

## Guide 5.5: the audit_log row, as above.
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.errors import ErrorCode, InvalidInput, NotFound, PreconditionFailed, ToolError
from te_platform.registry.context import CallContext
from te_platform.registry.facts import derive_facts
from te_platform.registry.loader import Registry
from te_platform.registry.predicates import ARGS_FROM, PRECONDITIONS, PREDICATES

## Guide 6.3: the quota lines in step 2 of _run_steps (commented twice).
from te_platform.security import quotas

## Standard-library logger; observability.py (from guide 3.1, configured by
## each server process at startup) writes it as structured JSON with the
## correlation ID.
log = logging.getLogger("te_platform.pipeline")

## The only message a client sees for a bug: details stay in the server log.
_INTERNAL = "Internal error. Please report the correlation ID."


class Suggestion(BaseModel):
    """One suggested next tool call, computed from the policy (step 7)."""

    tool: str
    reason: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolOutcome(BaseModel):
    """What every caller gets back. Exactly one of result / error is set."""

    ok: bool
    result: dict[str, Any] | None = None
    error: ToolError | None = None
    suggested_next: list[Suggestion] = Field(default_factory=list)
    correlation_id: str


def _fail(ctx: CallContext, code: ErrorCode, message: str, **extra: Any) -> ToolOutcome:
    """Build a refusal: ok=False with a ToolError carrying the call's correlation ID."""
    error = ToolError(error=code, message=message, correlation_id=ctx.correlation_id, **extra)
    return ToolOutcome(ok=False, error=error, correlation_id=ctx.correlation_id)


def _check_preconditions(registry: Registry, ctx: CallContext) -> None:
    """Step 4. Raise PreconditionFailed for the FIRST failing rule.

    An overridable rule is skipped only when the caller gave a reason; the
    reason is logged (step 8) and printed in reports (provenance).
    """
    policy = registry.policy
    for name in policy.tools[ctx.tool_id].preconditions:
        if PRECONDITIONS[name](ctx):
            continue
        if ctx.override_reason and name in policy.overridable_preconditions:
            log.warning(
                "precondition overridden",
                extra={
                    "precondition": name,
                    "reason": ctx.override_reason,
                    "correlation_id": ctx.correlation_id,
                },
            )
            continue
        spec = policy.preconditions[name]
        raise PreconditionFailed(name, spec.message, spec.do_first)


def _suggestions(registry: Registry, ctx: CallContext) -> list[Suggestion]:
    """Step 7: every policy rule `after` this tool whose predicate holds."""
    out: list[Suggestion] = []
    for rule in registry.policy.suggested_next:
        if rule.suggest in registry.policy.planned:
            continue  # never suggest a tool that is not built yet
        if rule.after == ctx.tool_id and PREDICATES[rule.when](ctx):
            args = ARGS_FROM[rule.args_from](ctx) if rule.args_from else {}
            out.append(Suggestion(tool=rule.suggest, reason=rule.reason, args=args))
    return out


## One `return` per refusal keeps the steps in the order they run, readable
## top to bottom; splitting them into helpers would hide that order. Hence
## the two complexity rules are switched off for this one function.
async def _run_steps(  # noqa: C901, PLR0911  one exit per pipeline step, see above
    registry: Registry,
    tool_id: str,
    raw_input: dict[str, Any],
    ctx: CallContext,
) -> ToolOutcome:
    """Run steps 1-7. Every exit returns a ToolOutcome; call() below adds step 8."""
    tool = registry.tools.get(tool_id)
    if tool is None or tool_id in registry.policy.deprecated:
        return _fail(ctx, ErrorCode.NOT_FOUND, f"Unknown tool {tool_id!r}.")

    # 1. authorise. Empty scopes = all tools (phase 4). With OAuth scopes
    #    (12.6), the tool's namespace ("verify", "sim", ...) must be granted.
    namespace = tool_id.partition(".")[0]  # "verify.run.v1" -> "verify"
    if ctx.principal.scopes and namespace not in ctx.principal.scopes:
        return _fail(ctx, ErrorCode.FORBIDDEN, f"Your credentials do not allow {tool_id}.")

    # 2. quota. Until guide 6.3 every call is allowed. Two different limits,
    #    from security/quotas.py:
    #    - a rate limit on ALL tool calls (calls per minute): refuse now;
    #    - a limit on simulation jobs: only recorded in ctx.facts.quota_ok,
    #      because the policy expresses it as the precondition
    #      `job_quota_available` of the job tools (step 4 enforces it).
    ## Guide 6.3: the quota checks (commented twice until then).
    if not await quotas.check_rate_limit(ctx.principal):
        return _fail(ctx, ErrorCode.QUOTA_EXCEEDED, "Too many requests; wait a minute and retry.")
    if registry.policy.tools[tool_id].cost == "expensive":
        ctx.facts.quota_ok = await quotas.job_quota_available(ctx.principal)

    # 3. validate input against the tool's Pydantic model.
    try:
        validated = tool.input_model.model_validate(raw_input)
    except ValidationError as exc:
        return _fail(
            ctx,
            ErrorCode.VALIDATION_ERROR,
            "The input does not match the tool's schema.",
            details=exc.errors(include_url=False),
        )

    # 3b. derive the facts the preconditions read (spec hash, validity,
    #     whether the given verification_ref matches this spec).
    #     Validation of the spec runs in a thread: it can take a moment.
    ctx.facts = await derive_facts(validated, ctx, quota_ok=ctx.facts.quota_ok)

    # 4. preconditions.
    try:
        _check_preconditions(registry, ctx)
    except PreconditionFailed as exc:
        return _fail(
            ctx,
            ErrorCode.PRECONDITION_FAILED,
            exc.message,
            precondition=exc.precondition,
            do_first=exc.do_first,
        )

    # 5. run with a timeout. fail_after cancels the handler if it takes too
    #    long. Handlers run CPU-heavy work in a thread (anyio.to_thread),
    #    so the timeout and other requests are not blocked meanwhile.
    try:
        with anyio.fail_after(get_settings().tool_timeout_s):
            output = await tool.handler(validated, ctx)
    except TimeoutError:
        return _fail(
            ctx,
            ErrorCode.TIMEOUT,
            "The tool took too long. Try a smaller input, or the job-based variant.",
        )
    except InvalidInput as exc:
        return _fail(ctx, ErrorCode.VALIDATION_ERROR, str(exc))
    except NotFound as exc:
        return _fail(ctx, ErrorCode.NOT_FOUND, str(exc) or "Not found.")
    except PreconditionFailed as exc:  # handlers may detect late preconditions
        return _fail(
            ctx,
            ErrorCode.PRECONDITION_FAILED,
            exc.message,
            precondition=exc.precondition,
            do_first=exc.do_first,
        )
    except Exception:
        # A bug. log.exception writes the full stack trace to the server log;
        # the client only gets the correlation ID to report it.
        log.exception(
            "tool handler crashed", extra={"tool": tool_id, "correlation_id": ctx.correlation_id}
        )
        return _fail(ctx, ErrorCode.INTERNAL_ERROR, _INTERNAL)

    # 6. check the output really matches the declared model.
    try:
        result = tool.output_model.model_validate(output).model_dump(mode="json")
    except ValidationError:
        log.exception(
            "tool returned invalid output",
            extra={"tool": tool_id, "correlation_id": ctx.correlation_id},
        )
        return _fail(ctx, ErrorCode.INTERNAL_ERROR, _INTERNAL)

    # 7. suggestions (predicates read ctx.result).
    ctx.result = result
    suggestions = _suggestions(registry, ctx)

    return ToolOutcome(
        ok=True, result=result, suggested_next=suggestions, correlation_id=ctx.correlation_id
    )


async def call(
    registry: Registry, tool_id: str, raw_input: dict[str, Any], ctx: CallContext
) -> ToolOutcome:
    """Run one tool call: steps 1-7, then step 8 (audit) for EVERY outcome.

    Successes and refusals alike are audited: a refused call (wrong key
    scope, precondition, quota) is exactly what an incident review needs
    to see. call() never raises: an unexpected error in any step (a bug,
    or Redis/PostgreSQL down) becomes an internal_error outcome, with the
    stack trace in the server log only.
    """
    started = time.monotonic()
    try:
        outcome = await _run_steps(registry, tool_id, raw_input, ctx)
    except Exception:
        log.exception(
            "pipeline step crashed", extra={"tool": tool_id, "correlation_id": ctx.correlation_id}
        )
        outcome = _fail(ctx, ErrorCode.INTERNAL_ERROR, _INTERNAL)
    latency_ms = int((time.monotonic() - started) * 1000)
    result_code = "ok" if outcome.ok else outcome.error.error.value if outcome.error else "error"

    # 8. audit: always a log line ...
    log.info(
        "tool call",
        extra={
            "tool": tool_id,
            "principal": ctx.principal.id,
            "outcome": result_code,
            "latency_ms": latency_ms,
            "correlation_id": ctx.correlation_id,
            "override_reason": ctx.override_reason,
        },
    )

    ## Guide 5.5: ... and a permanent audit_log row (commented twice until
    ## then). The input is stored as a HASH only: enough to match two
    ## identical calls, without keeping user content in the audit table.
    ## A failed write is logged with its stack trace (monitoring sees it)
    ## but does not hide the result: the tool has already run.
    input_hash = "in:" + hashing.sha256_hex(hashing.canonical_json(raw_input))

    def _write() -> None:
        with session_scope() as db:
            Repository(db, ctx.principal).write_audit(
                tool_id,
                input_hash,
                result_code,
                latency_ms,
                override_reason=ctx.override_reason,
                correlation_id=ctx.correlation_id,
            )

    try:
        await anyio.to_thread.run_sync(_write)
    except Exception:
        log.exception(
            "audit write failed", extra={"tool": tool_id, "correlation_id": ctx.correlation_id}
        )
    return outcome
