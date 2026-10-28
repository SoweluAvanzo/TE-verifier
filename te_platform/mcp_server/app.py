## =============================================================================
## te_platform/mcp_server/app.py — build the MCP server and run it (`te-mcp`)
## =============================================================================
## GUIDE STEP   3.1 (build_server + stdio main), 3.2 (resources/prompts wired),
##              4.1 (`te-mcp --http`: serves http_app.create_app),
##              5.5 (session facts loaded from the database)
## PURPOSE      Two public functions:
##              - build_server(registry): an MCP server object whose tools are
##                exactly the registry's tools, with descriptions generated
##                from the policy;
##              - main(): the `te-mcp` command. Without arguments it speaks MCP
##                over stdio (for Claude Desktop/Code on your machine); from
##                guide 4.1, `--http` serves http_app.create_app() (the same
##                server over Streamable HTTP, protected by API keys) on port
##                8000.
## USED BY      pyproject.toml [project.scripts] te-mcp (main);
##              compose.yml service `mcp` (runs `te-mcp --http`);
##              mcp_server/http_app.py (build_server);
##              tests/platform_tests/test_platform_mcp.py (build_server in-process).
## DEPENDS ON   mcp (the official SDK, >= 2.3), registry/ (loader, pipeline,
##              describe, context), config.py, errors.py, observability.py
##              (JSON log lines on stderr, activated at 3.1 too);
##              mcp_server/resources.py and prompts.py from 3.2; uvicorn and
##              mcp_server/http_app.py from 4.1; db/ from 5.5.
## CORRELATION  A client may send X-Correlation-ID (our agent does: one id per
##              chat turn). If it looks like an id (letters, digits, - or _,
##              at most 64 characters) it becomes ctx.correlation_id, so the
##              turn can be followed through every log line and job; anything
##              else is ignored and a fresh id is used (never trust a client
##              to put arbitrary text into our logs).
## LOGGING      configure_logging (observability.py) writes JSON lines to
##              stderr, never to stdout, which carries the MCP messages in
##              stdio mode.
## WHY          Architecture §3.3, D4, D6, D8.
##
## WHY THE LOW-LEVEL `Server` AND NOT `MCPServer`
##              The SDK offers two layers. `MCPServer` (the one used in the
##              weather tutorial) builds each tool's input schema from a
##              Python function signature and validates the arguments itself.
##              Our tools already have Pydantic input models, and our pipeline
##              must be the ONE place that validates input (D4), so that MCP,
##              REST and the agent get identical errors. The low-level
##              `mcp.server.Server` lets us (a) publish each tool's schema
##              straight from `input_model.model_json_schema()`, and (b)
##              receive the raw arguments as a dict and pass them to
##              pipeline.call() untouched. The cost is that resources and
##              prompts are also registered as plain handler functions
##              (resources.py, prompts.py) instead of decorators — which is
##              more explicit, and easy to read.
## ACTIVATE     3.1: uncomment the single-commented code: the imports,
##              LOCAL_STDIO_PRINCIPAL, _CORRELATION_ID, _tool_definitions,
##              _to_call_result, _make_context, build_server and main. Check
##              with the MCP Inspector:
##              `npx @modelcontextprotocol/inspector uv run te-mcp`.
##              3.2: the twice-commented resources/prompts lines.
##              4.1: the twice-commented argparse/uvicorn lines and
##              _serve_http_if_asked (together with http_app.py).
##              5.5: the twice-commented session-facts lines.
##              (Later-phase lines are commented twice, README §1.1, so each
##              step works on its own.)
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the public names
## `build_server` and `main` exactly: pyproject (te-mcp), http_app.py and
## the tests use them. Activate first: the registry (guide 2.x), config.py,
## errors.py, and the te-mcp entry point from pyproject_additions.toml.
##
## Guide 3.1 (observability.py, also guide 3.1, first)
## [ ] 1. Imports at the top (the SOLUTION's single-commented ones): json,
##        re, Any, uuid4, anyio, `types` (from mcp), Server and
##        ServerRequestContext (mcp.server), stdio_server, and our
##        check_environment, get_settings, ErrorCode, NotFound, ToolError,
##        configure_logging, CallContext, Principal, SessionFacts,
##        describe, Registry, build_registry, ToolOutcome, call.
## [ ] 2. Constants: `LOCAL_STDIO_PRINCIPAL = Principal(id="local-stdio",
##        kind="service")` and `_CORRELATION_ID`, a compiled regex for 1-64
##        letters, digits, "-" or "_" (see CORRELATION in the header).
## [ ] 3. `_tool_definitions(registry)`: one types.Tool per tool id in
##        sorted order (stable order helps prompt caching), skipping
##        registry.policy.deprecated. Fill name, title, description (from
##        describe()), input_schema and annotations:
##          | input_schema=spec.input_model.model_json_schema(),
##        No output_schema (the SOLUTION explains why).
## [ ] 4. `_to_call_result(outcome)`: dump the whole ToolOutcome
##        (mode="json", exclude_none=True) and return a CallToolResult with
##        it as JSON text in `content`, as `structured_content`, and
##        is_error=not outcome.ok.
## [ ] 5. `async _make_context(request_ctx, tool_id, arguments)`: no HTTP
##        request -> LOCAL_STDIO_PRINCIPAL; with one -> request.state's
##        principal (PermissionError if missing) and the X-Correlation-ID
##        header. `session: SessionFacts | None = None` (filled from 5.5),
##        then the CallContext (principal, tool_id, tool_input, session,
##        override_reason); set ctx.correlation_id only if the header fully
##        matches _CORRELATION_ID.
## [ ] 6. `build_server(registry)`: two inner async handlers,
##        on_list_tools (returns the precomputed definitions) and
##        on_call_tool: build the context, turning NotFound/PermissionError
##        into a not_found/forbidden ToolOutcome, else `await call(...)` and
##        convert the outcome. Return Server("token-economy-verifier",
##        instructions=..., on_list_tools=..., on_call_tool=...).
## [ ] 7. `main()`: check_environment, settings, configure_logging(settings),
##        build the server, then run it inside `async with stdio_server()`
##        via anyio.run. Never print to stdout: in stdio mode it carries the
##        MCP messages.
## [ ] 8. Check: the Inspector lists the tools and verify.run.v1 works on
##        examples/bitcoin.yaml:
##          | npx @modelcontextprotocol/inspector uv run te-mcp
##          | uv run mypy te_platform
##        The automated tests come with guide 3.3
##        (tests/platform_tests/test_platform_mcp.py).
##
## Guide 3.2 (the "# # " lines under the Phase/Guide 3.2 labels)
## [ ] 9. Toggle the import of prompts and resources, and inside
##        build_server the five on_* keyword arguments of Server(...).
##        Check: the Inspector shows the resources and the prompts.
##
## Guide 4.1 (the "# # " lines under the Phase/Guide 4.1 labels)
## [ ] 10. Toggle the argparse and uvicorn imports and
##        `_serve_http_if_asked()`: options --http, --host (default
##        127.0.0.1) and --port (8000); with --http it runs uvicorn on
##        "te_platform.mcp_server.http_app:create_app" (factory=True,
##        proxy_headers=True, forwarded_allow_ips from Settings) and returns
##        True. Then toggle its call at the start of main(). Write
##        http_app.py (guide 4.1) first.
##        Check: `uv run te-mcp --http`, then the Inspector connects to
##        http://localhost:8000/mcp.
##
## Guide 5.5 (the "# # " lines under the Phase/Guide 5.5 labels)
## [ ] 11. Toggle the Repository and session_scope imports,
##        `_stored_session_facts` and the session block in _make_context
##        (database read in a worker thread). Check: activate
##        test_unknown_session_is_not_found (db) and run
##          | uv run pytest tests/platform_tests/test_platform_mcp.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## --- Imports -----------------------------------------------------------------
## Later-step imports sit in their sorted place, each under its label, so
## the import block stays sorted (ruff I001) at every step.
## Phase 4.1: command-line options of `te-mcp --http`.
import argparse
import json
import re
from typing import Any
from uuid import uuid4

import anyio

## Phase 4.1: uvicorn serves the HTTP app (installed with mcp).
import uvicorn
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from te_platform.config import check_environment, get_settings

## Phase 5.5: session facts from the database.
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.errors import ErrorCode, NotFound, ToolError

## Phase 3.2: resources and prompts.
from te_platform.mcp_server import prompts, resources
from te_platform.observability import configure_logging
from te_platform.registry.context import CallContext, Principal, SessionFacts
from te_platform.registry.describe import describe
from te_platform.registry.loader import Registry, build_registry
from te_platform.registry.pipeline import ToolOutcome, call

## --- Who is calling over stdio? ----------------------------------------------
## Over stdio there is no HTTP request and no API key: the server is a child
## process of the client program on YOUR machine, so only you can talk to it.
## We give such calls a fixed local principal. Never expose stdio over a
## network (e.g. via socat): this principal is trusted without a key.
LOCAL_STDIO_PRINCIPAL = Principal(id="local-stdio", kind="service")

## What a client-chosen correlation id may look like (see CORRELATION above).
_CORRELATION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


## --- Tool definitions published to clients -----------------------------------
def _tool_definitions(registry: Registry) -> list[types.Tool]:
    """Build one MCP `Tool` per registered tool, in a STABLE order (by id).

    A stable order matters: clients (and our agent) put the tool list at the
    start of every model request, and prompt caching only works when that
    prefix is byte-for-byte identical between requests.
    """
    defs: list[types.Tool] = []
    for tool_id in sorted(registry.tools):
        if tool_id in registry.policy.deprecated:
            continue  # kept for old clients, never advertised
        spec = registry.tools[tool_id]
        tp = registry.policy.tools[tool_id]
        defs.append(
            types.Tool(
                name=tool_id,
                title=spec.title or None,
                # The description IS the policy, rendered (registry/describe.py).
                description=describe(tool_id, registry.policy),
                # JSON Schema straight from the tool's Pydantic input model.
                input_schema=spec.input_model.model_json_schema(),
                # The policy writes MCP's hint names in camelCase (readOnlyHint, ...);
                # ToolAnnotations accepts those names directly.
                annotations=types.ToolAnnotations.model_validate(tp.annotations),
            )
        )
        # No output_schema: our result is wrapped together with
        # suggested_next and correlation_id (see _to_call_result), so the
        # tool's own output model is not the whole answer.
    return defs


## --- ToolOutcome -> MCP result -----------------------------------------------
def _to_call_result(outcome: ToolOutcome) -> types.CallToolResult:
    """Convert the pipeline's outcome into what MCP clients understand.

    MCP results carry two views of the same data:
    - `content`: a list of content blocks; we put the JSON as text, which
      every client (and every model) can read;
    - `structured_content`: the same data as a JSON object, for clients that
      process results programmatically.
    `is_error=True` tells the client (and the model) the call did not
    succeed.

    The payload is ALWAYS the pipeline's whole ToolOutcome, success or not:
      {"ok": true,  "result": {...}, "suggested_next": [...], "correlation_id": "..."}
      {"ok": false, "error": {"error": "precondition_failed", "message": ...,
                              "do_first": [...], ...}, "correlation_id": "..."}
    One self-describing shape for every consumer (our agent's mcp_bridge,
    the evals, external clients): nobody has to guess the shape from
    is_error. The error part includes `do_first`, so a model can correct
    itself in one step (D4).
    """
    payload: dict[str, Any] = outcome.model_dump(mode="json", exclude_none=True)
    text = json.dumps(payload, ensure_ascii=False)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content=payload,
        is_error=not outcome.ok,
    )


## --- Building the CallContext for one call -----------------------------------
## Phase 5.5: the database read behind _make_context's session block.
## Repository filters by the principal, so a session_id belonging to
## someone else raises NotFound, exactly like an unknown one.
def _stored_session_facts(principal: Principal, session_id: str) -> SessionFacts:
    """Load one session's facts (synchronous: run it in a worker thread)."""
    with session_scope() as db:
        return Repository(db, principal).get_session_facts(session_id)


async def _make_context(
    request_ctx: ServerRequestContext[Any, Any], tool_id: str, arguments: dict[str, Any]
) -> CallContext:
    """Work out who is calling, about which session, with which override.

    `request_ctx.request` is the HTTP request (a Starlette Request) when the
    call came over Streamable HTTP, and None over stdio or in-process. The
    auth middleware (auth.py, guide 4.2) stored the authenticated Principal
    in the request's `state`.
    """
    http_request = request_ctx.request
    client_id: str | None = None
    if http_request is None:
        principal = LOCAL_STDIO_PRINCIPAL
    else:
        found: Principal | None = getattr(http_request.state, "principal", None)
        if found is None:
            # Over HTTP WITHOUT the auth middleware (guide 4.1, before 4.2):
            # refuse rather than trust an anonymous caller.
            raise PermissionError("Authentication is not configured yet (guide 4.2).")
        principal = found
        client_id = http_request.headers.get("x-correlation-id")

    # Stateless calls (no session_id) have no stored facts.
    session: SessionFacts | None = None
    ## Guide 5.5: load the session's stored facts. NotFound (unknown or
    ## foreign session) is turned into a `not_found` outcome by
    ## on_call_tool: this runs BEFORE the pipeline. The database is
    ## synchronous (SQLAlchemy), so it runs in a worker thread.
    session_id = arguments.get("session_id")
    if session_id:
        session = await anyio.to_thread.run_sync(_stored_session_facts, principal, str(session_id))

    ctx = CallContext(
        principal=principal,
        tool_id=tool_id,
        tool_input=arguments,
        session=session,
        override_reason=arguments.get("override_reason"),
    )
    if client_id and _CORRELATION_ID.fullmatch(client_id):
        ctx.correlation_id = client_id  # see CORRELATION in the header
    return ctx


## --- The server --------------------------------------------------------------
def build_server(registry: Registry) -> Server:
    """Create the MCP server for `registry`.

    No I/O happens here; the server starts doing work only when a transport
    (stdio, HTTP or an in-process test client) runs it.
    """
    tool_defs = _tool_definitions(registry)

    # Each handler receives (request context, request params). These small
    # functions are "closures": they capture `registry` and `tool_defs` from
    # build_server, so no global variables are needed. A leading "_" marks
    # a parameter the SDK passes but the handler does not need.
    async def on_list_tools(
        _ctx: ServerRequestContext[Any, Any],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tool_defs)

    async def on_call_tool(
        request_ctx: ServerRequestContext[Any, Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        arguments = dict(params.arguments or {})
        try:
            ctx = await _make_context(request_ctx, params.name, arguments)
        except (NotFound, PermissionError) as exc:
            # Building the context happens BEFORE the pipeline, so its errors
            # are converted here, into the same outcome shape the pipeline
            # uses (an unknown or foreign session_id looks like "not found").
            code = ErrorCode.NOT_FOUND if isinstance(exc, NotFound) else ErrorCode.FORBIDDEN
            cid = uuid4().hex
            error = ToolError(error=code, message=str(exc) or "Not found.", correlation_id=cid)
            return _to_call_result(ToolOutcome(ok=False, correlation_id=cid, error=error))
        # THE central line: every MCP tool call goes through the pipeline.
        outcome = await call(registry, params.name, arguments, ctx)
        return _to_call_result(outcome)

    return Server(
        "token-economy-verifier",
        instructions=(
            "Tools to design and verify token economies against six failure modes. "
            "Always verify (verify.run.v1) before simulating. Follow `suggested_next` "
            "in results and `do_first` in errors. Never invent numbers: report only "
            "values returned by the tools."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        ## Guide 3.2: read-only resources and conversation templates.
        on_list_resources=resources.on_list_resources,
        on_list_resource_templates=resources.on_list_resource_templates,
        on_read_resource=resources.on_read_resource,
        on_list_prompts=prompts.on_list_prompts,
        on_get_prompt=prompts.on_get_prompt,
    )


## --- `te-mcp --http` (guide 4.1) ---------------------------------------------
## Phase 4.1: the HTTP transport. uvicorn loads http_app.create_app by its
## import string ("module:function", factory=True), so this module never
## imports http_app.py, which itself imports build_server from here: a
## direct import would be circular.
def _serve_http_if_asked() -> bool:
    """Serve Streamable HTTP when `--http` is given; return False otherwise."""
    parser = argparse.ArgumentParser(prog="te-mcp", description="Token Economy Verifier MCP server")
    parser.add_argument(
        "--http", action="store_true", help="Serve Streamable HTTP instead of stdio."
    )
    # 127.0.0.1 by default: started by hand on your machine, the server is
    # reachable only from that machine. Inside a container, Compose passes
    # --host 0.0.0.0 (the container's own interfaces; Compose networks then
    # decide who can reach it, guide 4.6).
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not args.http:
        return False
    # proxy_headers: read the real client address from X-Forwarded-For,
    # but ONLY when the request comes from a trusted proxy (Caddy):
    # otherwise any client could fake its address and dodge per-IP
    # limits (guide 12.3). The trusted addresses are a setting.
    uvicorn.run(
        "te_platform.mcp_server.http_app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips=get_settings().forwarded_allow_ips,
    )
    return True


## --- Command-line entry point `te-mcp` ---------------------------------------
def main() -> None:
    """Run the `te-mcp` command: MCP over stdio for a local client."""
    ## Guide 4.1: `te-mcp --http` serves Streamable HTTP instead.
    if _serve_http_if_asked():
        return

    # stdio: the client (Claude Desktop/Code) starts this process and talks
    # through its standard input/output. Nothing is printed to stdout except
    # MCP messages — a stray print() would corrupt the protocol stream.
    check_environment()  # fail fast on misspelled TE_* variables (config.py)
    settings = get_settings()
    configure_logging(settings)  # JSON lines on stderr: stdout belongs to MCP
    server = build_server(build_registry(settings.policy_dir / "tool_policy.yaml"))

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(_run)
