## =============================================================================
## te_platform/registry/context.py — who is calling, and what is known
## =============================================================================
## GUIDE STEP   2.2
## PURPOSE      Four small data classes passed to every precondition,
##              predicate and tool handler:
##              - Principal: the authenticated caller;
##              - SessionFacts: what is stored about the session (if any);
##              - CallFacts: what the pipeline derived about THIS call (facts.py);
##              - CallContext: one tool call = principal + session facts +
##                input + derived CallFacts (+ result, once the handler ran).
##              Everything a rule needs to decide is in the CallContext, so
##              rules are pure functions: easy to test without a database.
## USED BY      predicates.py (every rule receives a CallContext),
##              pipeline.py (builds it), facts.py (fills CallFacts),
##              tools/*.py (handlers receive it),
##              mcp_server/auth.py (creates the Principal from the API key),
##              db/repo.py (filters every query by Principal.id).
## DEPENDS ON   pydantic.
## WHY          Guide §2.1 "pure core, impure edges": the pipeline loads the
##              facts from the database ONCE, then the rules only read them.
## ACTIVATE     Uncomment; no test of its own (exercised by predicate tests).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the four class names
## exactly as written here: every rule and tool imports them
## (te_platform/README.md, contracts table).
##
## Guide 2.2
## [ ] 1. Imports at the top: `Any` and `Literal` from typing, `uuid4` from
##        uuid, and `BaseModel`, `ConfigDict`, `Field` from pydantic.
## [ ] 2. Each class below gets a docstring (what it holds), then a blank
##        line before its first field (ruff's D101 and D204).
##        `class Principal(BaseModel)`: make it read-only with
##          | model_config = ConfigDict(frozen=True)
##        then the fields `id: str`, `kind` (a Literal of "user", "api_key",
##        "service") and `scopes: frozenset[str]` defaulting to frozenset().
## [ ] 3. `class SessionFacts(BaseModel)`: `session_id`, `owner_id` (str),
##        then optional facts that default to None, False or 0:
##        current_spec_hash, current_spec, verification_ref,
##        verified_spec_hash, finished_simulation_for_current_ref,
##        report_for_current_ref, running_jobs, plus open_decisive_slots
##        (a list; use Field(default_factory=list), never a bare []).
##        No `state` field: state.py computes it (see the docstring).
## [ ] 4. `class CallFacts(BaseModel)`: spec_present=False, spec_valid=True,
##        spec_hash=None, verification_ref=None,
##        verification_matches_spec=False, quota_ok=True. The defaults mean
##        "nothing known yet"; facts.py fills in the real values.
## [ ] 5. `class CallContext(BaseModel)`: principal, tool_id, tool_input
##        (dict), session=None, override_reason=None, then three fields with
##        defaults: correlation_id (a fresh random hex id per call),
##          | correlation_id: str = Field(default_factory=lambda: uuid4().hex)
##        facts (default_factory=CallFacts) and result=None.
## [ ] 6. Check: this file has no test of its own; the predicate tests use it
##        later (test_platform_predicates.py). For now run
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Principal(BaseModel):
    """The authenticated caller of a tool.

    kind:
      "user"     a person logged in to the web app (phase 9);
      "api_key"  an external program using the MCP server (phase 4.2);
      "service"  our own agent service calling the MCP server.
    scopes: permissions; empty means "all tools" for now. With OAuth
    (guide 12.6) scopes like "verify" or "simulate" restrict tools.
    """

    # frozen: a principal never changes during a call; prevents accidents.
    model_config = ConfigDict(frozen=True)

    id: str
    kind: Literal["user", "api_key", "service"]
    scopes: frozenset[str] = frozenset()


class SessionFacts(BaseModel):
    """Facts stored about one session, loaded by the pipeline from the database.

    The session STATE (eliciting, spec_ready, ...) is not stored: it is
    computed from these facts by registry/state.py, so it can never be out
    of date.
    """

    session_id: str
    owner_id: str
    current_spec_hash: str | None = None          # hash of the latest spec version
    current_spec: dict[str, Any] | None = None    # the latest spec itself
    verification_ref: str | None = None           # latest verification of the CURRENT spec
    verified_spec_hash: str | None = None         # which spec that verification belongs to
    open_decisive_slots: list[str] = Field(default_factory=list)  # from elicitation/
    finished_simulation_for_current_ref: bool = False
    report_for_current_ref: bool = False
    running_jobs: int = 0


class CallFacts(BaseModel):
    """Facts DERIVED by the pipeline (registry/facts.py) for one call.

    They are computed before the preconditions run, so that every rule
    reads typed fields instead of recomputing anything. The defaults
    describe "nothing known yet".
    """

    spec_present: bool = False                 # the call refers to some spec
    spec_valid: bool = True                    # schema validation passed (True if no spec)
    spec_hash: str | None = None               # hash of the NORMALISED spec of this call
    verification_ref: str | None = None        # given by the caller or taken from the session
    verification_matches_spec: bool = False    # that ref was computed from THIS spec
    quota_ok: bool = True                      # set by security/quotas.py (phase 6.3)


class CallContext(BaseModel):
    """Everything known about one tool call."""

    principal: Principal
    tool_id: str
    tool_input: dict[str, Any]
    session: SessionFacts | None = None    # None for stateless MCP clients
    # Set when the user explicitly asks to skip an overridable rule.
    override_reason: str | None = None
    # A random ID for this call, written to every log line and returned in
    # errors, so a user's report can be matched to the server log.
    correlation_id: str = Field(default_factory=lambda: uuid4().hex)
    # Filled in by the pipeline (step 3b, registry/facts.py).
    facts: CallFacts = Field(default_factory=CallFacts)
    # Filled in by the pipeline after the handler succeeds; predicates for
    # suggested_next read it.
    result: dict[str, Any] | None = None
