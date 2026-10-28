## =============================================================================
## te_platform/registry/__init__.py — the tool registry package
## =============================================================================
## GUIDE STEP   2.1-2.6
## PURPOSE      Marks registry/ as a package. The registry is the heart of the
##              platform's rules: it knows every tool (spec.py, loader.py),
##              loads the tool policy (policy.py), resolves the named
##              preconditions/predicates (predicates.py), derives the session
##              state (state.py), and runs every tool call through the same
##              checks (pipeline.py). describe.py generates what the model reads.
##
##              How the files relate (arrows = "uses"):
##
##                pipeline.py ──► loader.py ──► spec.py, policy.py
##                    │               └──────► predicates.py ──► context.py
##                    ├──► facts.py ──► context.py, service.py, hashing.py
##                    └──► errors.py, config.py (outside registry/)
##                state.py ──► policy.py, predicates.py
##                describe.py ──► policy.py
##
##              Callers outside: mcp_server/app.py calls pipeline.call() for
##              every MCP tool call; our agent reaches it through MCP;
##              agent/chat_api.py and agent/loop.py use state.py directly.
## WHY          Architecture §3.2, D3, D4, D6, D7.
## ACTIVATE     Nothing to uncomment here; keep the file (it makes the package).
## =============================================================================
