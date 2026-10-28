## =============================================================================
## te_platform/agent/auth.py — who is the browser user? (cookie session + Origin check)
## =============================================================================
## GUIDE STEP   8.1 (dependencies + the session store), 9.0 (login helpers)
## PURPOSE      Two FastAPI *dependencies* used by every chat endpoint (and
##              their shortcuts CurrentUser and SameOrigin):
##              - get_current_principal: reads the session cookie, looks it up,
##                returns the logged-in user's Principal (or answers 401);
##              - require_same_origin: for requests that change something
##                (POST), checks the Origin header equals our own site.
##              Plus create_web_session() (8.1), which stores a server-side
##              session and sets its cookie, and the login helpers used by
##              POST /agent/login and /agent/logout (agent/login_api.py, 9.0):
##              login_attempt_allowed(), end_web_session().
##              LOGIN (guide 9.0): each person gets a personal ACCESS CODE
##              from `te-platform users create` (a long random secret, stored
##              only as a hash, like API keys). They type it once on /login;
##              the server then sets the session cookie. Simple, needs no
##              e-mail or identity provider, and is enough for a research
##              tool with invited users. University single sign-on (OAuth /
##              OpenID Connect, guide 12.6) can replace the code check later
##              without changing anything else: it only has to end by calling
##              create_web_session().
## USED BY      agent/chat_api.py, agent/spec_api.py and
##              agent/user_reports_api.py (via Depends), agent/login_api.py
##              (the login endpoints),
##              webapp/chat_routes.py + templates/login.html (the login page;
##              same cookie, because Flask and FastAPI share one origin
##              behind Caddy).
## DEPENDS ON   fastapi, redis (redis.asyncio), config.py, registry/context.py.
## WHY          Browsers must never hold API keys (any injected script could
##              steal them), so people authenticate with a cookie that is:
##                Secure    sent over HTTPS only;
##                HttpOnly  unreadable by JavaScript (XSS cannot steal it);
##                SameSite=Lax  not sent on cross-site POSTs, the main defence
##                          against CSRF (another site submitting requests in
##                          the user's name).
##              The Origin check is defence in depth on top of SameSite.
##              Only a HASH of the cookie value is stored server-side, so a
##              leaked Redis dump cannot be replayed as cookies.
## ACTIVATE     8.1: uncomment (the 9.0 helpers are commented twice).
##              9.0: the twice-commented login helpers. Tests in
##              test_platform_agent.py: no cookie -> 401; unknown cookie ->
##              401; a stored session -> its principal; a foreign Origin ->
##              403 (8.1); wrong access code -> 401; 11th attempt -> 429;
##              logout -> the old cookie no longer works (9.0).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the five public
## function names exactly as written: the agent/*_api.py routers import them.
##
## Guide 8.1 (the two dependencies and the session store)
## [ ] 1. Imports at the top: hashlib, secrets, Annotated (typing),
##        `redis.asyncio as aioredis`, Depends, HTTPException, Request and
##        Response from fastapi, get_settings (config.py) and Principal
##        (registry/context.py).
## [ ] 2. `_redis() -> aioredis.Redis`: aioredis.from_url(settings.redis_url,
##        decode_responses=True), so values come back as str, not bytes.
##        Use it as `async with _redis() as r:` so the connection is closed.
## [ ] 3. `_key(token: str) -> str`: "websession:" + the sha256 hex digest of
##        the token. Only this hash is stored (see WHY in the header).
## [ ] 4. `async def create_web_session(response, principal_id: str) -> None`:
##        token = secrets.token_urlsafe(32); store _key(token) -> principal_id
##        in Redis with ex=settings.web_session_ttl_s; set the cookie with
##        max_age=ttl, secure=True, httponly=True, samesite="lax", path="/".
##        The login endpoint (9.0) calls it; the tests use it from 8.1 to
##        create a session without a login page.
## [ ] 5. `async def get_current_principal(request) -> Principal`: read the
##        cookie named settings.web_session_cookie; missing -> 401; look up
##        _key(token) in Redis; nothing found -> 401 ("expired"); else
##          | return Principal(id=str(principal_id), kind="user")
## [ ] 6. `async def require_same_origin(request) -> None`: if the "origin"
##        header is not settings.public_origin, raise HTTPException 403.
##        Then two shortcuts the routers use in their signatures:
##          | CurrentUser = Annotated[Principal,
##          |                         Depends(get_current_principal)]
##        and SameOrigin = [Depends(require_same_origin)].
## [ ] 7. Check: activate the guide 8.1 auth tests of
##        tests/platform_tests/test_platform_agent.py (no cookie -> 401;
##        unknown cookie -> 401; stored session -> principal; foreign
##        Origin -> 403), then
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##          | uv run mypy te_platform
##
## Guide 9.0 (later: the "# # " lines in the SOLUTION)
## [ ] 8. Constants _LOGIN_WINDOW_S = 15 * 60 and _LOGIN_MAX_ATTEMPTS = 10.
## [ ] 9. `async def login_attempt_allowed(client_ip: str) -> bool`: count
##        attempts under the key "login-attempts:" + client_ip, a fixed
##        window:
##          | count = await r.incr(key)
##          | if count == 1:
##          |     await r.expire(key, _LOGIN_WINDOW_S)
##        then return count <= _LOGIN_MAX_ATTEMPTS.
## [ ] 10. `async def end_web_session(request, response) -> None`: if the
##        cookie is present, delete its Redis key; then
##        response.delete_cookie(cookie name, path="/").
## [ ] 11. Check (with the login endpoints of agent/login_api.py): the guide 9.0
##        tests (wrong access code -> 401; 11th attempt -> 429; after logout
##        the old cookie no longer works).
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import hashlib
import secrets
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, Response

from te_platform.config import get_settings
from te_platform.registry.context import Principal


def _redis() -> aioredis.Redis:
    # A client per call, used as `async with _redis() as r:` so its
    # connection is closed afterwards. decode_responses=True returns str
    # instead of bytes. (Async clients are bound to one event loop, which is
    # why this module does not cache one; see tests/platform_tests/conftest.py.)
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


def _key(token: str) -> str:
    return "websession:" + hashlib.sha256(token.encode()).hexdigest()


async def create_web_session(response: Response, principal_id: str) -> None:
    """Store a server-side session for `principal_id` and set its cookie on `response`.

    Called by POST /agent/login (agent/login_api.py, guide 9.0) after the user
    proved who they are with their access code.
    """
    s = get_settings()
    token = secrets.token_urlsafe(32)  # 256 random bits: unguessable
    async with _redis() as r:
        await r.set(_key(token), principal_id, ex=s.web_session_ttl_s)
    # secure=True: the cookie travels over HTTPS only. Browsers make one
    # exception, http://localhost (treated as a secure context), so the
    # local development setup works in Chrome and Firefox; any other
    # plain-http address would silently drop the cookie.
    response.set_cookie(
        s.web_session_cookie,
        token,
        max_age=s.web_session_ttl_s,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )


async def get_current_principal(request: Request) -> Principal:
    """Return the logged-in user, or answer 401 (a FastAPI dependency).

    Used as `principal: Annotated[Principal, Depends(get_current_principal)]`.
    FastAPI calls it before the endpoint; if it raises HTTPException, the
    endpoint never runs.
    """
    token = request.cookies.get(get_settings().web_session_cookie)
    if not token:
        raise HTTPException(status_code=401, detail="Please log in.")
    async with _redis() as r:
        principal_id = await r.get(_key(token))
    if principal_id is None:
        raise HTTPException(
            status_code=401, detail="Your session has expired; please log in again."
        )
    # str(): the Redis client was created with decode_responses=True, so
    # this is already a str at runtime; the type stubs cannot know that.
    return Principal(id=str(principal_id), kind="user")


async def require_same_origin(request: Request) -> None:
    """Refuse a request whose Origin is not our own site (a FastAPI dependency for POSTs)."""
    origin = request.headers.get("origin")
    if origin != get_settings().public_origin:
        raise HTTPException(status_code=403, detail="Cross-origin request refused.")


## Shortcuts for the endpoint signatures (agent/chat_api.py and the other
## routers): `principal: CurrentUser` gives the logged-in user (401 if there
## is none), and `dependencies=SameOrigin` adds the Origin check to a POST.
CurrentUser = Annotated[Principal, Depends(get_current_principal)]
SameOrigin = [Depends(require_same_origin)]


## Phase 9.0: login rate limit. At most 10 login attempts per IP address per
## 15 minutes. Access codes are long random strings, so guessing is hopeless
## anyway; the limit also stops a flood of attempts from costing database
## lookups. INCR + EXPIRE is the same fixed-window pattern as
## security/quotas.py.
_LOGIN_WINDOW_S = 15 * 60
_LOGIN_MAX_ATTEMPTS = 10


## Phase 9.0: the login helpers used by agent/login_api.py.
async def login_attempt_allowed(client_ip: str) -> bool:
    """Count one login attempt from `client_ip`; False once the limit is exceeded."""
    key = "login-attempts:" + client_ip
    async with _redis() as r:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, _LOGIN_WINDOW_S)
    return int(count) <= _LOGIN_MAX_ATTEMPTS


## Phase 9.0: logout deletes the Redis entry too, so a copied cookie stops
## working immediately.
async def end_web_session(request: Request, response: Response) -> None:
    """Log out: delete the server-side session and the cookie."""
    token = request.cookies.get(get_settings().web_session_cookie)
    if token:
        async with _redis() as r:
            await r.delete(_key(token))
    response.delete_cookie(get_settings().web_session_cookie, path="/")
