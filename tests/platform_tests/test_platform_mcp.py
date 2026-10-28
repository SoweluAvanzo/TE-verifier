## =============================================================================
## tests/platform_tests/test_platform_mcp.py — tests for te_platform/mcp_server/
## =============================================================================
## GUIDE STEP   3.3 (in-process protocol tests), 4.1 (Host check), 4.2 (API
##              keys), 5.5 (sessions), 6.2 (simulation refused), 7.6 (interview
##              prompt and protocol resource)
## PURPOSE      Prove that the MCP server publishes exactly the registry's tools,
##              that a tool call goes through the pipeline (preconditions
##              enforced), that resources/prompts work and refuse bad requests
##              cleanly, and that the HTTP app rejects missing keys and foreign
##              Host headers.
## HOW          - Protocol tests use `mcp.Client(server)`: given a server OBJECT
##                (not a URL), the SDK connects in-process — the full MCP
##                protocol, no network, fast and deterministic.
##              - HTTP tests use Starlette's TestClient on create_app()
##                (mcp_server/http_app.py): real HTTP requests handled in
##                memory.
##              Async tests need the anyio pytest plugin (installed with anyio):
##              mark them with @pytest.mark.anyio.
## ACTIVATE     The single-commented tests at 3.3 (mcp_server/app.py,
##              resources.py and prompts.py are active since 3.1-3.2); each
##              labelled twice-commented block at its own step.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Async tests need
## @pytest.mark.anyio (header, HOW).
##
## Guide 3.3
## [ ] 1. Imports: json, Path, pytest, `Client` and `MCPError` from mcp,
##        INVALID_PARAMS (mcp.types), build_server (mcp_server.app),
##        build_registry (registry.loader). Constants:
##        REPO = Path(__file__).resolve().parents[2] and BITCOIN = the
##        text of REPO / "examples" / "bitcoin.yaml".
## [ ] 2. Fixture `server()`: build_server(build_registry(REPO / "policy" /
##        "tool_policy.yaml")). Each test then connects in-process:
##          | async with Client(server) as client:
## [ ] 3. test_lists_exactly_the_policy_tools: the names from
##        client.list_tools() equal the policy tools minus the deprecated
##        and the planned ones.
## [ ] 4. test_verify_returns_ref_and_suggestions: call verify.run.v1;
##        res.is_error is false; json.loads(res.content[0].text) is the
##        whole ToolOutcome: ok is True, result's verification_ref starts
##        with "vref:", and it has a "suggested_next" key.
## [ ] 5. test_example_resource_rejects_path_traversal: reading
##        "te://examples/../../.env" raises MCPError with code
##        INVALID_PARAMS; test_example_resource_is_served: "te://examples/
##        bitcoin" returns the file's text.
## [ ] 6. test_prompt_without_required_argument_is_invalid_params:
##        get_prompt("design_review", {}) raises MCPError INVALID_PARAMS
##        naming "spec"; with {"spec": BITCOIN} the message contains the spec.
## [ ] 7. Check:
##          | uv run pytest tests/platform_tests/test_platform_mcp.py -q
##
## Guide 4.1 (twice-commented, labelled)
## [ ] 8. Imports under their labels: os, TestClient
##        (starlette.testclient), NOT_SETTINGS and Settings (config.py) and
##        create_app (mcp_server.http_app). Fixture `current_step_env`:
##        delete (monkeypatch.delenv) the TE_* variables that
##        check_environment would refuse at this step (variables of later
##        phases on a test machine), so create_app() can start.
## [ ] 9. test_foreign_host_header_is_rejected: the Host check is the SDK's
##        layer, BELOW authentication (http_app.py, LAYERS). Test it on
##        `create_app().router`, the app without its middleware, so the
##        test does not depend on how keys are stored (Settings at 4.2, the
##        database from 5.4); `with TestClient(...)` starts the app's
##        lifespan (the session manager). A foreign Host gets 421, an
##        allowed one (localhost:8000) does not.
##
## Guide 4.2 (twice-commented, labelled)
## [ ] 10. test_http_without_key_is_401: POST /mcp with no key -> 401 and
##        header "www-authenticate" equal to "Bearer".
## [ ] 11. test_http_with_wrong_key_is_401_with_same_body: no key and
##        "Authorization: Bearer te_wrong" both get 401 and the same JSON.
##        From guide 5.4 the wrong key is looked up in the database, so the
##        test then needs PostgreSQL running.
##
## Guide 5.5 (twice-commented, labelled)
## [ ] 12. test_unknown_session_is_not_found, marked @pytest.mark.db and
##        anyio: graph.flow.v1 with session_id "no-such-session" ->
##        res.is_error and outcome error "not_found", not a crash.
##
## Guide 6.2 (twice-commented, labelled)
## [ ] 13. test_simulation_before_verification_is_refused:
##        sim.monte_carlo.v1 with spec and seed -> res.is_error, outcome ok
##        False, error "precondition_failed", "verify.run.v1" in do_first.
##
## Guide 7.6 (twice-commented, labelled)
## [ ] 14. test_interview_prompt_is_served: listed, and its text holds the
##        method (no "<!--" left) and the start instructions.
##        test_protocol_resource_is_served: te://protocol/elicitation is the
##        protocol file's text.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import json

## Phase 4.1: the environment of the HTTP tests.
import os
from pathlib import Path

import pytest
from mcp import Client, MCPError
from mcp.types import INVALID_PARAMS

## Phase 4.1: HTTP requests handled in memory.
from starlette.testclient import TestClient

## Phase 4.1: which TE_* variables the current step knows.
from te_platform.config import NOT_SETTINGS, Settings
from te_platform.mcp_server.app import build_server

## Phase 4.1: the HTTP application.
from te_platform.mcp_server.http_app import create_app
from te_platform.registry.loader import build_registry

REPO = Path(__file__).resolve().parents[2]
BITCOIN = (REPO / "examples" / "bitcoin.yaml").read_text(encoding="utf-8")


@pytest.fixture
def server():
    return build_server(build_registry(REPO / "policy" / "tool_policy.yaml"))


## --- 3.3 protocol tests -------------------------------------------------------
@pytest.mark.anyio
async def test_lists_exactly_the_policy_tools(server):
    async with Client(server) as client:
        listed = {t.name for t in (await client.list_tools()).tools}
    policy = build_registry(REPO / "policy" / "tool_policy.yaml").policy
    # Built tools only: not the deprecated ones, nor those still `planned`.
    assert listed == set(policy.tools) - set(policy.deprecated) - set(policy.planned)


@pytest.mark.anyio
async def test_verify_returns_ref_and_suggestions(server):
    async with Client(server) as client:
        res = await client.call_tool("verify.run.v1", {"spec": BITCOIN})
    assert not res.is_error
    payload = json.loads(res.content[0].text)  # the full ToolOutcome (mcp_server/app.py)
    assert payload["ok"] is True
    assert payload["result"]["verification_ref"].startswith("vref:")
    # Only the key: until guide 6.2 every suggested tool is still planned,
    # so the list is empty here.
    assert "suggested_next" in payload


@pytest.mark.anyio
async def test_example_resource_rejects_path_traversal(server):
    async with Client(server) as client:
        with pytest.raises(MCPError) as caught:
            await client.read_resource("te://examples/../../.env")
    assert caught.value.code == INVALID_PARAMS


@pytest.mark.anyio
async def test_example_resource_is_served(server):
    async with Client(server) as client:
        res = await client.read_resource("te://examples/bitcoin")
    assert res.contents[0].text == BITCOIN


@pytest.mark.anyio
async def test_prompt_without_required_argument_is_invalid_params(server):
    async with Client(server) as client:
        with pytest.raises(MCPError) as caught:
            await client.get_prompt("design_review", {})
        res = await client.get_prompt("design_review", {"spec": BITCOIN})
    # A clean error that names the missing argument, not an internal error.
    assert caught.value.code == INVALID_PARAMS
    assert "spec" in caught.value.message
    assert BITCOIN in res.messages[0].content.text


## --- 4.1 / 4.2 HTTP tests -----------------------------------------------------
## Phase 4.1: create_app() calls check_environment(), which refuses TE_*
## variables that no setting of the CURRENT step knows. A test machine may
## export variables of later phases (e.g. TE_REDIS_URL for 6.x); hide only
## those, exactly the ones check_environment would refuse.
@pytest.fixture
def current_step_env(monkeypatch):
    known = {"TE_" + name.upper() for name in Settings.model_fields} | NOT_SETTINGS
    for name in [k for k in os.environ if k.startswith("TE_") and k not in known]:
        monkeypatch.delenv(name)


## Phase 4.1: DNS-rebinding protection (guide 4.1).
def test_foreign_host_header_is_rejected(current_step_env):
    # `.router` is the app WITHOUT its middleware: the Host check belongs
    # to the SDK layer under authentication (http_app.py, LAYERS).
    # `with` runs the app's lifespan, which starts the MCP session manager.
    with TestClient(create_app().router) as client:
        foreign = client.post("/mcp", json={}, headers={"Host": "evil.example"})
        allowed = client.post("/mcp", json={}, headers={"Host": "localhost:8000"})
    assert foreign.status_code == 421
    assert allowed.status_code != 421


## Phase 4.2: API keys (guide 4.2).
def test_http_without_key_is_401(current_step_env):
    client = TestClient(create_app())
    r = client.post("/mcp", json={})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


## Phase 4.2: the same refusal for every failure (from guide 5.4 the wrong
## key is looked up in the database: PostgreSQL must be running).
def test_http_with_wrong_key_is_401_with_same_body(current_step_env):
    client = TestClient(create_app())
    a = client.post("/mcp", json={})
    b = client.post("/mcp", json={}, headers={"Authorization": "Bearer te_wrong"})
    # Same answer for "no key" and "wrong key": nothing to learn for attackers.
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


## --- 5.5 sessions -------------------------------------------------------------
## Phase 5.5: an unknown (or someone else's) session_id is found while
## BUILDING the call context, before the pipeline runs; it must still come
## back as a normal not_found outcome, not as a crash.
@pytest.mark.db
@pytest.mark.anyio
async def test_unknown_session_is_not_found(server):
    async with Client(server) as client:
        res = await client.call_tool("graph.flow.v1", {"session_id": "no-such-session"})
    assert res.is_error
    outcome = json.loads(res.content[0].text)
    assert outcome["ok"] is False
    assert outcome["error"]["error"] == "not_found"


## --- 6.2 formal methods first -------------------------------------------------
## Phase 6.2: needs the tool sim.monte_carlo.v1. The core rule of the project
## (formal methods first, P2), enforced by the server whatever the client's
## prompt says.
@pytest.mark.anyio
async def test_simulation_before_verification_is_refused(server):
    async with Client(server) as client:
        res = await client.call_tool("sim.monte_carlo.v1", {"spec": BITCOIN, "seed": 1})
    assert res.is_error
    outcome = json.loads(res.content[0].text)  # the full ToolOutcome, with ok=False
    assert outcome["ok"] is False
    assert outcome["error"]["error"] == "precondition_failed"
    assert "verify.run.v1" in outcome["error"]["do_first"]


## --- 7.6 interview ------------------------------------------------------------
## Phase 7.6: the interview prompt (after interview.md's DRAFT markers are gone).
@pytest.mark.anyio
async def test_interview_prompt_is_served(server):
    async with Client(server) as client:
        names = {p.name for p in (await client.list_prompts()).prompts}
        res = await client.get_prompt("interview_token_economy", {"language": "Italian"})
    text = res.messages[0].content.text
    assert "interview_token_economy" in names
    assert "<!--" not in text  # developer notes are stripped
    assert "Italian" in text
    assert "elicit.next_questions.v1" in text


## Phase 7.6: the protocol resource.
@pytest.mark.anyio
async def test_protocol_resource_is_served(server):
    async with Client(server) as client:
        res = await client.read_resource("te://protocol/elicitation")
    protocol = (REPO / "policy" / "elicitation_protocol.yaml").read_text(encoding="utf-8")
    assert res.contents[0].text == protocol
