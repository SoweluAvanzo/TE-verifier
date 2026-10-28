## =============================================================================
## te_platform/agent/spec_api.py — the form <-> chat round trip (spec endpoints)
## =============================================================================
## GUIDE STEP   9.3
## PURPOSE      The form and the chat edit the SAME session spec
##              (architecture §3.5):
##                GET  /agent/sessions/{id}/spec   current spec as YAML
##                                                 ("Open in form" in chat.js)
##                POST /agent/sessions/{id}/spec   store a spec edited in the
##                                                 form as a new version
##              The agent sees a form edit on its next turn, because the loop
##              re-reads the session facts before every model request. A
##              question counts as answered when the spec already has a value
##              at its field (guide 7.5), so a complete spec from the form
##              lets the session move on to verification.
## USED BY      agent/app.py (include_router), webapp/static/chat.js ("Open in
##              form"), the form page (saving), the tests.
## DEPENDS ON   fastapi, anyio, pydantic; agent/auth.py, agent/mcp_bridge.py,
##              db/repo.py + db/session.py, registry/context.py.
## WHY          The agent service never imports the verifier or the service
##              layer (see agent/__init__.py): even this small validation and
##              YAML conversion goes through the MCP tool spec.validate.v1,
##              so it follows the same rules, quotas and audit as everything
##              else. Invalid specs are refused with the validation problems,
##              so the session never holds a spec the verifier cannot read.
## ACTIVATE     Uncomment, then toggle the spec_api lines in agent/app.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|"
## are short illustrations, not the full code. Keep the paths and the JSON
## field names (yaml, spec_hash, version) exactly: chat.js and the form use
## them.
##
## Guide 9.3
## [ ] 1. Imports at the top: Any, uuid4, anyio, APIRouter and HTTPException,
##        BaseModel and Field, then CurrentUser and SameOrigin
##        (agent/auth.py), McpBridge, Repository, session_scope, Principal
##        and SessionFacts. Then `router = APIRouter()`.
## [ ] 2. `class SpecIn(BaseModel)` with a docstring: `yaml: str` with
##        max_length=200_000.
## [ ] 3. `async def _validate_via_mcp(principal, spec) -> dict[str, Any]`:
##        open an McpBridge and call the tool by its PROVIDER name:
##          | out = await bridge.call("spec__validate__v1", {"spec": spec})
##        not out["ok"] -> HTTPException 502; else return
##        out["payload"]["result"] ({valid, errors, spec_hash, yaml,
##        normalised_spec, ...}).
## [ ] 4. GET /agent/sessions/{session_id}/spec `get_spec(session_id,
##        principal: CurrentUser)`: load the session facts in a worker
##        thread; no current spec -> {"yaml": None, "spec_hash": None}; else
##        validate it (that gives the canonical YAML) and return
##        {"yaml": ..., "spec_hash": ...}. During an interview the spec is
##        usually still incomplete, so not schema-valid: then validate gives
##        no YAML, and the answer is {"yaml": None, "spec_hash": <its hash>}
##        (chat.js says "not complete yet": the form can only load a valid
##        spec).
## [ ] 5. POST /agent/sessions/{session_id}/spec `put_spec(session_id, body:
##        SpecIn, principal: CurrentUser)` with dependencies=SameOrigin:
##        validate; not valid -> 422 with v["errors"]; else
##        add_spec_version(session_id, v["normalised_spec"], v["spec_hash"],
##        "form") in a worker thread; return {"version", "spec_hash"}.
## [ ] 6. Toggle the spec_api lines of agent/app.py.
## [ ] 7. Check (guide 9.3): activate
##        test_form_edit_is_visible_to_the_agent_on_its_next_turn in
##        tests/platform_tests/test_platform_agent.py (an end-to-end test
##        with the scripted provider), then
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from typing import Any
from uuid import uuid4

import anyio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from te_platform.agent.auth import CurrentUser, SameOrigin
from te_platform.agent.mcp_bridge import McpBridge
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.registry.context import Principal, SessionFacts

router = APIRouter()


class SpecIn(BaseModel):
    """A spec edited in the form, as YAML text."""

    yaml: str = Field(max_length=200_000)


async def _validate_via_mcp(principal: Principal, spec: Any) -> dict[str, Any]:
    """Return spec.validate.v1's result for `spec` (HTTP 502 if the tool call failed)."""
    async with McpBridge(on_behalf_of=principal.id, correlation_id=uuid4().hex) as bridge:
        out = await bridge.call("spec__validate__v1", {"spec": spec})
    if not out["ok"]:
        raise HTTPException(status_code=502, detail="Validation service unavailable.")
    result: dict[str, Any] = out["payload"]["result"]
    return result


@router.get("/agent/sessions/{session_id}/spec")
async def get_spec(session_id: str, principal: CurrentUser) -> dict[str, str | None]:
    """Return the session's current spec as canonical YAML, with its hash."""

    def _facts() -> SessionFacts:
        with session_scope() as db:
            return Repository(db, principal).get_session_facts(session_id)

    facts = await anyio.to_thread.run_sync(_facts)
    if facts.current_spec is None:
        return {"yaml": None, "spec_hash": None}
    # An incomplete spec (the usual case mid-interview) is not schema-valid:
    # v["yaml"] is then None, and chat.js says the design is not complete
    # yet. The form could not load it anyway (/api/yaml-to-ir validates).
    v = await _validate_via_mcp(principal, facts.current_spec)
    return {"yaml": v["yaml"], "spec_hash": facts.current_spec_hash}


@router.post("/agent/sessions/{session_id}/spec", dependencies=SameOrigin)
async def put_spec(session_id: str, body: SpecIn, principal: CurrentUser) -> dict[str, Any]:
    """Store a spec edited in the form as a new version (author "form")."""
    v = await _validate_via_mcp(principal, body.yaml)
    if not v["valid"]:
        raise HTTPException(status_code=422, detail=v["errors"])

    def _save() -> int:
        with session_scope() as db:
            return Repository(db, principal).add_spec_version(
                session_id, v["normalised_spec"], v["spec_hash"], "form"
            )

    return {"version": await anyio.to_thread.run_sync(_save), "spec_hash": v["spec_hash"]}
