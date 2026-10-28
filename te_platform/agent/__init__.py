## =============================================================================
## te_platform/agent/__init__.py — the interviewing agent service (package)
## =============================================================================
## GUIDE STEP   8.1-8.5 (phase 8); prompts/interview.md at 7.6; the routers
##              login_api.py (9.0), spec_api.py (9.3), user_reports_api.py (10.3)
## PURPOSE      Marks agent/ as a package and documents how its files fit
##              together. The agent service is a FastAPI web service that:
##              receives a user's chat message, runs the agent loop (the LLM
##              decides, calls MCP tools, reads results, decides again), and
##              streams everything back to the browser as server-sent events.
##
##              How the files relate (arrows = "uses"):
##
##                 browser (webapp/static/chat.js)
##                    │  POST /agent/sessions/{id}/messages   (same origin, via Caddy)
##                    ▼
##                 app.py   the FastAPI app; includes one router per guide step:
##                    │       chat_api.py (8.5), login_api.py (9.0), spec_api.py (9.3),
##                    │       user_reports_api.py (10.3)
##                 chat_api.py ──► auth.py       who is the user? (cookie session + Origin check)
##                    │
##                    ├──► db/repo.py            load history, session facts; store messages
##                    ▼
##                 loop.py  (AgentLoop: one "turn" = model ⇄ tools until a final answer)
##                    │   ├──► providers/base.py      the ChatProvider interface
##                    │   │      ├── providers/anthropic.py   real model (Anthropic API)
##                    │   │      └── providers/fake.py        scripted model (tests only)
##                    │   ├──► mcp_bridge.py          MCP client → mcp service (tools)
##                    │   │                            → registry/pipeline.py on the MCP side
##                    │   └──► registry/state.py      which tools this session state allows
##                    ▼
##                 events.py ──► SSE text  ──► StreamingResponse ──► browser
##
##              The agent NEVER imports the verifier or the service layer: it
##              reaches every capability through MCP, exactly like an external
##              client would. That is what keeps P1 and P2 true for the chat:
##              the same server-side preconditions apply (architecture D4, D8).
## WHY          Architecture §3.4; D8 (own loop, MCP client, provider adapter),
##              D9 (model, streaming, prompt caching), D10 (FastAPI, async).
## ACTIVATE     Nothing to uncomment here; keep the file (it makes the package).
## =============================================================================
