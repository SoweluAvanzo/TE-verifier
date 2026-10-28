## =============================================================================
## te_platform/mcp_server/auth.py — API-key authentication for the HTTP MCP server
## =============================================================================
## GUIDE STEP   4.2 (keys from Settings), 5.4 (keys from the database),
##              12.6 (OAuth alternative, see the end of this file)
## PURPOSE      An ASGI *middleware*: code that sees every HTTP request before
##              the MCP app does. It reads `Authorization: Bearer <key>`,
##              hashes the key, looks the hash up, and either
##                - stores the matching Principal in the request's `state`
##                  (app.py reads it as request.state.principal), or
##                - answers 401 itself, so the MCP app never sees the request.
## USED BY      mcp_server/http_app.py create_app() wraps the Streamable HTTP
##              app with it. Only HTTP mode: stdio has no headers (app.py
##              explains why stdio is still safe).
## DEPENDS ON   starlette (installed with mcp), security/api_keys.py,
##              config.py (phase 4: api_key_hashes); from phase 5:
##              db/repo.py AuthRepository, db/session.py session_scope.
## WHY          Guide 4.2: the simplest secure option for a first set of known
##              users. Authentication lives in ONE place, before any tool code
##              (guide §2.2 "AuthN/AuthZ in one place").
## SECURITY     - Only the SHA-256 HASH of each key is stored; a leaked database
##                or .env does not reveal usable keys.
##              - Phase 4 compares hashes in Python with hmac.compare_digest,
##                which takes the same time whether or not the values match,
##                so an attacker cannot guess a hash byte by byte by timing
##                responses.
##              - Phase 5 looks the hash up in the database (an index lookup on
##                the hash). Timing differences there could at most reveal
##                hash prefixes, which do not help to forge a key (that would
##                require reversing SHA-256), so this is acceptable.
##              - The 401 body is the same for "no key", "wrong key" and
##                "revoked key": attackers learn nothing about which keys exist.
## ACTIVATE     4.2: uncomment (single-commented code): the imports,
##              _lookup_phase4, `_lookup = _lookup_phase4` and
##              ApiKeyMiddleware. Test: test_platform_mcp.py (401 without key
##              and with a wrong key).
##              5.4: the twice-commented lines: _lookup_phase5 and the line
##              `_lookup = _lookup_phase5`, which makes the database the only
##              source of keys (nothing to delete).
## =============================================================================


## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the class name
## `ApiKeyMiddleware` and its `exempt_paths` argument exactly: http_app.py
## uses them. Activate security/api_keys.py and config.py first.
##
## Guide 4.2
## [ ] 1. Imports at the top: hmac, Callable (collections.abc), Literal,
##        anyio, starlette's Headers, JSONResponse and the ASGI types
##        (ASGIApp, Receive, Scope, Send), get_settings, Principal,
##        hash_api_key.
## [ ] 2. `_lookup_phase4(key_hash) -> Principal | None`: loop over
##        get_settings().api_key_hashes ({hash: principal_id}) and compare
##        with hmac.compare_digest (constant time, see SECURITY). On a match
##        the kind is "service" when the id starts with "service:", else
##        "api_key".
## [ ] 3. The lookup the middleware uses, chosen once at import:
##          | _lookup: Callable[[str], Principal | None] = _lookup_phase4
## [ ] 4. `class ApiKeyMiddleware` (pure ASGI, not BaseHTTPMiddleware, so
##        streaming keeps working): __init__(self, app, exempt_paths=None)
##        stores both (default empty set).
## [ ] 5. `async __call__(self, scope, receive, send)`:
##        a) pass non-HTTP scopes and exempt paths straight to self.app;
##        b) read "authorization", split "Bearer <key>", hash the stripped
##           key and look it up in a worker thread:
##          | await anyio.to_thread.run_sync(_lookup, key_hash)
##        c) no principal -> JSONResponse 401 with the same body every time
##           and the header WWW-Authenticate: Bearer;
##        d) X-TE-On-Behalf-Of present: 403 unless the key is a service key,
##           otherwise act as Principal(id=<header>, kind="user");
##        e) store the principal in scope["state"]["principal"] and call
##           self.app.
## [ ] 6. Check: in http_app.py toggle the 4.2 lines; activate the 401 tests
##        of tests/platform_tests/test_platform_mcp.py, then
##          | uv run pytest tests/platform_tests/test_platform_mcp.py -q
##          | uv run mypy te_platform
##
## Guide 5.4 (the "# # " lines under the Phase 5.4 labels)
## [ ] 7. Toggle the AuthRepository and session_scope imports,
##        `_lookup_phase5` and the line `_lookup = _lookup_phase5` below
##        `_lookup = _lookup_phase4`: from now on the middleware asks the
##        database, and keys listed in TE_API_KEY_HASHES are no longer
##        accepted (create keys with `te-platform keys create`).
##        Check: the same tests, with PostgreSQL running (the wrong-key
##        test now queries the api_keys table).
##
## Guide 12.6 is only a sketch in "##" lines at the end: nothing to write
## until third parties need OAuth.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import hmac
from collections.abc import Callable
from typing import Literal

import anyio
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from te_platform.config import get_settings

## Phase 5.4: API keys live in the database.
from te_platform.db.repo import AuthRepository
from te_platform.db.session import session_scope
from te_platform.registry.context import Principal
from te_platform.security.api_keys import hash_api_key


## --- Looking up a key hash ---------------------------------------------------
def _lookup_phase4(key_hash: str) -> Principal | None:
    """Find the principal of a key hash among Settings.api_key_hashes.

    Phase 4: the known keys are listed as {hash: principal_id}, filled from
    .env / Docker secrets. `te-platform keys create` prints the hash to add
    there.
    """
    for known_hash, principal_id in get_settings().api_key_hashes.items():
        if hmac.compare_digest(known_hash, key_hash):
            # Convention for phase 4 (no database yet): principal ids that
            # start with "service:" (e.g. "service:agent", our own agent
            # service) are service principals; all others are external
            # programs. From phase 5 the kind is a column of api_keys.
            kind: Literal["service", "api_key"] = (
                "service" if principal_id.startswith("service:") else "api_key"
            )
            return Principal(id=principal_id, kind=kind)
    return None


## Phase 5.4: keys live in the api_keys table; revocation = flagging a row.
def _lookup_phase5(key_hash: str) -> Principal | None:
    """Find the principal of a key hash in the api_keys table."""
    with session_scope() as db:
        return AuthRepository(db).find_principal_by_key_hash(key_hash)


## The lookup the middleware uses, chosen once when the module is imported
## and never changed afterwards (README §4 rule 5).
_lookup: Callable[[str], Principal | None] = _lookup_phase4
## Phase 5.4: from now on the database is the only source of keys. This
## line rebinds _lookup, so nothing above has to be deleted.
_lookup = _lookup_phase5


## --- The middleware ----------------------------------------------------------
## A "pure ASGI" middleware: a class whose instances are called with
## (scope, receive, send) for every request. `scope` is a dict describing the
## request (type, path, headers, ...). Writing it this way (instead of
## Starlette's BaseHTTPMiddleware) keeps streaming responses working: MCP's
## Streamable HTTP keeps responses open and sends pieces over time.
class ApiKeyMiddleware:
    """Authenticate every HTTP request by its `Authorization: Bearer` key."""

    def __init__(self, app: ASGIApp, exempt_paths: set[str] | None = None) -> None:
        self.app = app
        # Paths that need no key: the health check used by Docker, which
        # reveals nothing.
        self.exempt_paths = exempt_paths or set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Let the request through with its Principal, or answer 401/403."""
        # Non-HTTP events (e.g. "lifespan" startup/shutdown) pass straight through.
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        scheme, _, key = headers.get("authorization", "").partition(" ")
        principal = None
        if scheme.lower() == "bearer" and key:
            key_hash = hash_api_key(key.strip())
            # The lookup may hit the database (blocking I/O): run it in a
            # worker thread so the event loop keeps serving other requests.
            principal = await anyio.to_thread.run_sync(_lookup, key_hash)

        if principal is None:
            # WWW-Authenticate tells clients which scheme is expected (HTTP standard).
            response = JSONResponse(
                {"error": "unauthenticated", "message": "Missing or invalid API key."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        # The agent service calls tools FOR a logged-in user and says which
        # one in X-TE-On-Behalf-Of (agent/mcp_bridge.py). Only a SERVICE key
        # may do that: otherwise any external key could impersonate any
        # user. The request then runs as that user, so ownership checks
        # (db/repo.py) and quotas apply to the user, not to the agent.
        on_behalf_of = headers.get("x-te-on-behalf-of")
        if on_behalf_of:
            if principal.kind != "service":
                response = JSONResponse(
                    {
                        "error": "forbidden",
                        "message": "Only the agent service may act on behalf of a user.",
                    },
                    status_code=403,
                )
                await response(scope, receive, send)
                return
            principal = Principal(id=on_behalf_of, kind="user")

        # Starlette's `request.state` reads scope["state"]; app.py reads
        # request.state.principal from there.
        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)


## --- Guide 12.6: OAuth 2.1 instead of (or next to) API keys -------------------
## When third parties need delegated access, the SDK can validate OAuth access
## tokens itself. Sketch (check the MCP Python SDK README for the current API):
##   - implement a class with `async def verify_token(self, token) -> AccessToken | None`
##     (protocol mcp.server.auth.provider.TokenVerifier) that validates the
##     token with your authorisation server (e.g. the university's identity
##     provider or Keycloak) and returns its scopes and subject;
##   - pass `token_verifier=...` and
##     `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])`
##     to server.streamable_http_app(...) in http_app.py;
##   - map AccessToken.subject/scopes to our Principal (kind="user", scopes=...),
##     so registry/pipeline.py step 1 enforces scopes per tool namespace.
