## =============================================================================
## te_platform/mcp_server/http_app.py — the MCP server as an HTTP application
## =============================================================================
## GUIDE STEP   4.1 (create_app: Streamable HTTP + DNS-rebinding protection +
##              /health), 4.2 (API-key middleware)
## PURPOSE      create_app() returns the server of app.py as an ASGI web
##              application (Streamable HTTP transport): the endpoint /mcp,
##              protected by API keys from guide 4.2, plus GET /health for
##              Docker. uvicorn serves it inside the `mcp` container
##              (`te-mcp --http`, app.py).
## USED BY      mcp_server/app.py (`te-mcp --http` loads
##              "te_platform.mcp_server.http_app:create_app" through uvicorn);
##              tests/platform_tests/test_platform_mcp.py (HTTP tests).
## DEPENDS ON   mcp (Streamable HTTP, TransportSecuritySettings), starlette
##              (installed with mcp), mcp_server/app.py (build_server),
##              registry/loader.py, config.py, observability.py;
##              mcp_server/auth.py from 4.2.
## WHY          A file of its own (not a function in app.py) because each
##              guide step must work on its own: create_app appears at 4.1 and
##              gains its authentication line at 4.2, two steps that both come
##              after app.py's own first step (3.1). Architecture §3.3, D13.
## LAYERS       From the outside in:
##                ApiKeyMiddleware  rejects requests without a valid key (401)
##                Starlette app     the SDK's Streamable HTTP endpoint at /mcp,
##                                  which also checks the Host and Origin
##                                  headers (DNS rebinding, guide 4.1)
##                Server            our tools, resources, prompts (app.py)
## ACTIVATE     4.1: uncomment (single-commented code). 4.2: the twice-
##              commented ApiKeyMiddleware lines.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the name
## `create_app` exactly: app.py (te-mcp --http) and the tests use it.
## Activate app.py (guide 3.1) first.
##
## Guide 4.1
## [ ] 1. Imports at the top: TransportSecuritySettings, Starlette,
##        Request, PlainTextResponse, Route, and our check_environment,
##        get_settings, build_server (mcp_server.app), configure_logging,
##        build_registry.
## [ ] 2. `async _health(_request)`: return PlainTextResponse("ok"). It
##        touches neither the database nor Redis, so a slow dependency never
##        makes Docker restart the container.
## [ ] 3. `create_app() -> Starlette`: check_environment, settings,
##        configure_logging(settings), the server (build_server(build_registry(...))), then
##          | app = server.streamable_http_app(streamable_http_path="/mcp",
##          |     transport_security=TransportSecuritySettings(...))
##        with enable_dns_rebinding_protection=True and the allowed hosts
##        and origins from Settings (mcp_allowed_hosts/_origins); then
##        append Route("/health", _health, methods=["GET"]) to
##        app.router.routes and return app.
## [ ] 4. In app.py, toggle the 4.1 lines (te-mcp --http).
## [ ] 5. Check: activate test_foreign_host_header_is_rejected in
##        tests/platform_tests/test_platform_mcp.py, then
##          | uv run pytest tests/platform_tests/test_platform_mcp.py -q
##          | uv run te-mcp --http
##        and connect the Inspector to http://localhost:8000/mcp. Tool
##        calls are refused as "forbidden" until 4.2: nobody is
##        authenticated yet.
##
## Guide 4.2 (the "# # " lines under the Phase/Guide 4.2 labels)
## [ ] 6. Toggle the ApiKeyMiddleware import and the add_middleware line
##        (/health stays exempt). Check: activate the 401 tests, then
##          | uv run pytest tests/platform_tests/test_platform_mcp.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from te_platform.config import check_environment, get_settings
from te_platform.mcp_server.app import build_server

## Phase 4.2: API-key authentication.
from te_platform.mcp_server.auth import ApiKeyMiddleware
from te_platform.observability import configure_logging
from te_platform.registry.loader import build_registry


## GET /health: used by Docker's health check (compose.yml). It answers "ok"
## without touching the database or Redis, so a slow dependency never makes
## Docker restart this container; it is the only path that needs no API key
## (exempt below) and it reveals nothing.
async def _health(_request: Request) -> PlainTextResponse:
    """Answer Docker's health check."""
    return PlainTextResponse("ok")


def create_app() -> Starlette:
    """Build the ASGI app that uvicorn serves in the `mcp` container."""
    check_environment()  # fail fast on misspelled TE_* variables (config.py)
    settings = get_settings()
    configure_logging(settings)  # JSON log lines (observability.py)
    server = build_server(build_registry(settings.policy_dir / "tool_policy.yaml"))
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        # Only these Host / Origin header values are accepted; any other
        # Host gets HTTP 421. Behind Caddy (guide 12.3) the Host is your
        # public domain; the agent service reaches us as "mcp:8000" on the
        # internal Docker network.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_hosts,
            allowed_origins=settings.mcp_allowed_origins,
        ),
    )
    # GET /health next to /mcp (see _health above).
    app.router.routes.append(Route("/health", _health, methods=["GET"]))
    ## Guide 4.2: wrap the whole app, so authentication happens before the
    ## SDK sees anything (the outermost layer, see LAYERS in the header).
    app.add_middleware(ApiKeyMiddleware, exempt_paths={"/health"})
    return app
