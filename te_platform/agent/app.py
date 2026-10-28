## =============================================================================
## te_platform/agent/app.py — the agent web service (FastAPI application)
## =============================================================================
## GUIDE STEP   8.1 (app + health), 8.5 (chat endpoints), 9.0 (login/logout),
##              9.3 (spec endpoints), 10.3 (report download): each later
##              step adds one router
## PURPOSE      Creates the FastAPI application that uvicorn serves, and
##              plugs in the endpoint groups, each written in its own file
##              (README §4 rule 1: one responsibility per file). All paths
##              are under /agent, which Caddy routes to this service:
##                GET  /agent/health                     here: liveness check for Docker
##                /agent/sessions, .../{id}, .../messages agent/chat_api.py (8.5)
##                POST /agent/login, /agent/logout       agent/login_api.py (9.0)
##                /agent/sessions/{id}/spec              agent/spec_api.py (9.3)
##                GET  /agent/reports/{id}?exp=&sig=     agent/user_reports_api.py (10.3)
## USED BY      compose.yml (`uvicorn te_platform.agent.app:app`), Docker health
##              checks, Caddy (reverse proxy), the tests.
## DEPENDS ON   fastapi, uvicorn; config.py, errors.py, observability.py; the
##              routers chat_api.py (8.5), login_api.py (9.0), spec_api.py
##              (9.3), user_reports_api.py (10.3).
## WHY          Architecture D10: a chat turn is mostly WAITING (model stream,
##              MCP calls, open browser connection); async FastAPI serves many
##              such turns per process. D8: the turn logic lives in loop.py;
##              the routers only do HTTP, auth, loading and saving.
##              One router per guide step keeps every step's code (and its
##              imports) in one place, so each step works on its own.
## FASTAPI IN ONE PARAGRAPH
##              Each endpoint is an `async def` decorated with @router.get /
##              @router.post (an APIRouter is a group of endpoints that
##              app.include_router() adds to the app). Parameters typed as
##              Pydantic models are read from the JSON body and validated (bad
##              input -> 422 automatically). Parameters written as
##              `Annotated[T, Depends(fn)]` are *dependencies*: FastAPI calls fn
##              first and passes its result in; we use them for authentication,
##              so no endpoint can forget it.
## ACTIVATE     8.1: uncomment; run `uvicorn te_platform.agent.app:app` in
##              Compose; GET /agent/health must return 200 through Compose.
##              8.5, 9.0, 9.3, 10.3: toggle that step's twice-commented import
##              and include_router line, together with the router file.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do only
## the group of the step you are on and run its "Check" before moving on.
## Lines starting with "|" are short illustrations, not the full code. Keep
## the name `app` and the path /agent/health exactly: compose.yml and the
## Docker health check use them.
##
## Guide 8.1 (skeleton + health)
## [ ] 1. Imports at the top: FastAPI and Request from fastapi, JSONResponse
##        from fastapi.responses, check_environment and get_settings
##        (config.py), NotFound (errors.py) and configure_logging
##        (observability.py).
## [ ] 2. App creation: call check_environment(), then
##        `_s = get_settings()`, configure_logging(_s), and
##        `_dev = _s.environment != "production"`. Create `app = FastAPI(...)`
##        with title "Token Economy agent", redoc_url=None, and the docs
##        URLs only in development:
##          |     docs_url="/agent/docs" if _dev else None,
##          |     openapi_url="/agent/openapi.json" if _dev else None,
## [ ] 3. Below it, an exception handler that turns errors.NotFound into
##        JSONResponse({"detail": "Not found."}, status_code=404), registered
##        with @app.exception_handler(NotFound). Why: see its `##` note.
## [ ] 4. GET /agent/health: `async def health() -> dict[str, str]` returning
##        {"status": "ok"}. It checks nothing external, on purpose.
## [ ] 5. Check: activate test_health_answers_ok in
##        tests/platform_tests/test_platform_agent.py and run
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##        then start the agent service in Compose (compose.yml runs
##        `uvicorn te_platform.agent.app:app`); GET /agent/health must
##        return 200 through Compose (its health check curls that URL).
##
## Guide 8.5 (later: the "# # " lines in the SOLUTION)
## [ ] 6. Write agent/chat_api.py first. Then add its router: at the END of
##        the imports, after a blank line, a RELATIVE import (the `##` note
##        in the SOLUTION explains why)
##          | from .chat_api import router as chat_router
##        and, after the exception handler, app.include_router(chat_router).
##        Check: see the Check of chat_api.py.
##
## Guide 9.0 (later: the "# # " lines in the SOLUTION)
## [ ] 7. Same for agent/login_api.py: append its import (router as
##        login_router) and include it. Check: login_api.py.
##
## Guide 9.3 (later: the "# # " lines in the SOLUTION)
## [ ] 8. Same for agent/spec_api.py (router as spec_router). Check:
##        spec_api.py.
##
## Guide 10.3 (later: the "# # " lines in the SOLUTION)
## [ ] 9. Same for agent/user_reports_api.py (router as report_router).
##        Check: user_reports_api.py.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from te_platform.config import check_environment, get_settings
from te_platform.errors import NotFound
from te_platform.observability import configure_logging

## Each later step adds one router (a file of its own). Their imports are
## RELATIVE ("from .chat_api", i.e. from this same folder): ruff sorts them
## after all other imports, so each step only appends one line at the end
## (the files are named so that this order is also alphabetical: chat_api,
## login_api, spec_api, user_reports_api). Keep a blank line before each
## label: ruff wants one after every import.
## Phase 8.5: sessions and the streaming message endpoint (agent/chat_api.py).
from .chat_api import router as chat_router

## Phase 9.0: login and logout (agent/login_api.py).
from .login_api import router as login_router

## Phase 9.3: the spec endpoints of the form <-> chat round trip (agent/spec_api.py).
from .spec_api import router as spec_router

## Phase 10.3: report download (agent/user_reports_api.py).
from .user_reports_api import router as report_router

## --- App creation ----------------------------------------------------------------------
## The interactive API docs (/docs, /redoc, /openapi.json) are useful in
## development but would show attackers the whole API in production, so they
## are switched off there (architecture §6).
check_environment()  # fail fast on misspelled TE_* variables (config.py)
_s = get_settings()
configure_logging(_s)  # JSON log lines with correlation ids (observability.py)
_dev = _s.environment != "production"
app = FastAPI(
    title="Token Economy agent",
    docs_url="/agent/docs" if _dev else None,
    redoc_url=None,
    openapi_url="/agent/openapi.json" if _dev else None,
)


## Repository methods raise errors.NotFound for sessions (and reports) that do
## not exist OR belong to someone else; both become the same 404, so nobody
## can probe ids.
@app.exception_handler(NotFound)
async def _not_found(_: Request, __: NotFound) -> JSONResponse:
    return JSONResponse({"detail": "Not found."}, status_code=404)


## Phase 8.5: the chat endpoints.
app.include_router(chat_router)
## Phase 9.0: login and logout.
app.include_router(login_router)
## Phase 9.3: the form <-> chat round trip.
app.include_router(spec_router)
## Phase 10.3: report download.
app.include_router(report_router)


## --- Endpoints ---------------------------------------------------------------------------
@app.get("/agent/health")
async def health() -> dict[str, str]:
    """Answer "ok" for Docker's health check.

    It deliberately checks nothing external, so a slow model API never
    makes Docker restart this container.
    """
    return {"status": "ok"}
