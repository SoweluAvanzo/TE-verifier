## =============================================================================
## te_platform/tools/__init__.py — one module per tool
## =============================================================================
## GUIDE STEP   2.5 (first tools), then 6.2, 7.4-7.5, 10.3, 11.2
## PURPOSE      Marks tools/ as a package. Every module here follows the same
##              shape, so once you understand verify_run.py you understand all:
##
##                1. Input model   — what the caller sends (becomes the MCP
##                                   input schema the model sees);
##                2. Output model  — what the tool returns;
##                3. handler       — async function: validated input + context
##                                   -> output. It calls the service layer (or
##                                   the job queue, or the database) and
##                                   NOTHING ELSE contains business logic;
##                4. TOOL          — the ToolSpec tying the three together.
##
##              The module name is the tool id with dots replaced by
##              underscores and the version dropped (verify.run.v1 ->
##              verify_run.py). A breaking change makes a new id (v2) and a new
##              module (verify_run_v2.py); the old one stays until deprecated.
##
##              Every tool is registered as an entry point (see
##              ../pyproject_additions.toml) and described in
##              ../../policy/tool_policy.yaml. The registry refuses to start if
##              either is missing.
## ACTIVATE     Nothing to uncomment here.
## =============================================================================
