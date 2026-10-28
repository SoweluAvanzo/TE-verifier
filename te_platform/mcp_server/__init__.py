## =============================================================================
## te_platform/mcp_server/__init__.py — the public MCP surface of the platform
## =============================================================================
## GUIDE STEP   3.1-3.4 (local, stdio), 4.1-4.2 (HTTP + API keys), 12.6 (OAuth)
## PURPOSE      Marks mcp_server/ as a package. It turns the tool registry into
##              an MCP server that MCP clients (Claude Desktop, Claude Code,
##              our own agent service, partner programs) can connect to.
##
##              How the files relate (arrows = "uses"):
##
##                app.py ──► registry/ (build_registry, pipeline.call, describe)
##                  │   ├──► resources.py  (te://... read-only data, 3.2)
##                  │   ├──► prompts.py    (reusable conversation templates, 3.2)
##                  │   └──► db/repo.py    (session facts, 5.5)
##                http_app.py ──► app.py (build_server; HTTP transport, 4.1)
##                  └──► auth.py       (API-key middleware, HTTP only, 4.2)
##                         └──► security/api_keys.py, db/repo.py (5.4)
##
##              The MCP server contains NO business logic: every tool call is
##              handed to registry/pipeline.py, which applies the policy.
## WHY          Architecture §3.3; D4 (rules enforced in the pipeline, so the MCP
##              transport cannot bypass them); D8 (our agent is an MCP client
##              of this server, exactly like any external client).
## ACTIVATE     Nothing to uncomment here; keep the file (it makes the package).
## =============================================================================
