## =============================================================================
## te_platform/agent/login_api.py — login and logout endpoints
## =============================================================================
## GUIDE STEP   9.0
## PURPOSE      The two endpoints of the login page (webapp/templates/login.html
##              + webapp/static/login.js):
##                POST /agent/login    exchange a personal access code for a
##                                     session cookie
##                POST /agent/logout   delete the session (server side) and
##                                     the cookie
##              They are grouped in an APIRouter that agent/app.py includes.
## USED BY      agent/app.py (include_router), webapp/static/login.js,
##              webapp/static/chat.js (logout), the tests.
## DEPENDS ON   fastapi, anyio, pydantic; agent/auth.py (session store, rate
##              limit, Origin check), db/repo.py (AuthRepository) +
##              db/session.py, security/api_keys.py (hash_api_key: access
##              codes are hashed exactly like API keys), registry/context.py.
## WHY          Guide 9.0: browsers must never hold API keys, so people log in
##              with an access code and then hold only an HttpOnly cookie
##              (agent/auth.py WHY). University single sign-on (guide 12.6)
##              can replace the code check later: it only has to end by
##              calling create_web_session().
## ACTIVATE     Uncomment, then toggle the login_api lines in agent/app.py and
##              the twice-commented 9.0 helpers in agent/auth.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|"
## are short illustrations, not the full code. Keep the paths /agent/login
## and /agent/logout and the field name access_code exactly: login.js and
## chat.js use them. Activate the 9.0 helpers of agent/auth.py first.
##
## Guide 9.0
## [ ] 1. Imports at the top: anyio, APIRouter, HTTPException, Request and
##        Response from fastapi, BaseModel and Field from pydantic, then
##        SameOrigin, create_web_session, end_web_session and
##        login_attempt_allowed (agent/auth.py), AuthRepository
##        (db/repo.py), session_scope (db/session.py), Principal
##        (registry/context.py) and hash_api_key (security/api_keys.py).
##        Then `router = APIRouter()`.
## [ ] 2. `class LoginIn(BaseModel)` with a docstring: access_code with
##        Field(min_length=10, max_length=200).
## [ ] 3. POST /agent/login `login(body, request, response)` with
##        dependencies=SameOrigin: client IP from request.client (or
##        "unknown"); 429 when login_attempt_allowed(ip) is False;
##        hash_api_key(code.strip()); AuthRepository(db)
##        .find_user_by_access_code_hash in a worker thread; None -> 401
##        "Unknown access code." (ONE answer for unknown AND disabled);
##        else `await create_web_session(response, principal.id)` and
##        return {"status": "ok"}.
## [ ] 4. POST /agent/logout (dependencies=SameOrigin): `await
##        end_web_session(request, response)`, return {"status": "ok"}.
## [ ] 5. Toggle the login_api lines of agent/app.py.
## [ ] 6. Check: activate the guide 9.0 tests of
##        tests/platform_tests/test_platform_agent.py (a wrong code gives
##        401; the 11th attempt within 15 minutes gives 429; after logging
##        out the old cookie gives 401), then
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import anyio
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from te_platform.agent.auth import (
    SameOrigin,
    create_web_session,
    end_web_session,
    login_attempt_allowed,
)
from te_platform.db.repo import AuthRepository
from te_platform.db.session import session_scope
from te_platform.registry.context import Principal
from te_platform.security.api_keys import hash_api_key

router = APIRouter()


class LoginIn(BaseModel):
    """The access code typed on the login page."""

    access_code: str = Field(min_length=10, max_length=200)


@router.post("/agent/login", dependencies=SameOrigin)
async def login(body: LoginIn, request: Request, response: Response) -> dict[str, str]:
    """Exchange a personal access code for a session cookie.

    The same answer for "unknown code" and "disabled user" on purpose, so
    the endpoint does not reveal which codes exist.
    """
    # The real client IP: Caddy forwards it and uvicorn runs with
    # --proxy-headers (compose.yml), so request.client is the browser.
    client_ip = request.client.host if request.client else "unknown"
    if not await login_attempt_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts; wait 15 minutes.")
    code_hash = hash_api_key(body.access_code.strip())

    def _find() -> Principal | None:
        with session_scope() as db:
            return AuthRepository(db).find_user_by_access_code_hash(code_hash)

    principal = await anyio.to_thread.run_sync(_find)
    if principal is None:
        raise HTTPException(status_code=401, detail="Unknown access code.")
    await create_web_session(response, principal.id)
    return {"status": "ok"}


@router.post("/agent/logout", dependencies=SameOrigin)
async def logout(request: Request, response: Response) -> dict[str, str]:
    """Log out: the server forgets the session, so even a copied cookie stops working."""
    await end_web_session(request, response)
    return {"status": "ok"}
