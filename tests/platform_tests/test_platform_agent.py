## =============================================================================
## tests/platform_tests/test_platform_agent.py — tests of the agent service
## =============================================================================
## GUIDE STEP   8.1-10.3 (each group is labelled with its guide step)
## PURPOSE      Specifies the agent service. The model is the SCRIPTED provider
##              (te_platform/agent/providers/fake.py: no network, no cost,
##              deterministic); everything else is real: the MCP server runs
##              over HTTP in a background thread of the test process, with a
##              real service API key, the real pipeline, PostgreSQL and Redis.
##              Covered, by guide step:
##                8.1  health endpoint; cookie session + Origin dependencies;
##                8.2  the scripted provider (and that production never uses it);
##                8.3  the real Anthropic provider (integration test, skipped
##                     unless TE_ANTHROPIC_API_KEY is set);
##                8.4  tool-name mapping; the loop: every limit (session token
##                     budget, tool calls per turn, seconds per turn), the
##                     confirmation flow, self-correction after
##                     precondition_failed, one user message for all results,
##                     session id injection, usage stored per request;
##                8.5  SSE formatting; the session and message endpoints;
##                9.0  login (401, 429) and logout;
##                9.3  the form <-> chat round trip;
##                10.3 the report download (owner 200, bad link 403, other
##                     user 404).
## USED BY      pytest.
## DEPENDS ON   pytest, anyio's pytest plugin (installed with anyio: mark async
##              tests with @pytest.mark.anyio), uvicorn, te_platform.agent.*;
##              from 8.4: TE_DATABASE_URL and TE_REDIS_URL (tests marked `db`).
## WHY          Guide 8.2/8.4: the loop's logic must be proven without the real
##              model, and without replacing any of OUR code: the scripted
##              provider replaces only the paid external API (the documented
##              exception). The real model has its own marked test (8.3).
## ACTIVATE     Each group together with the code it tests; later groups are
##              commented twice under their "## Guide X.Y" labels. Run:
##              `uv run pytest tests/platform_tests/test_platform_agent.py -q`.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each group
## together with the code it tests (header, ACTIVATE). Every import a group
## needs is listed at the top of the SOLUTION under that group's label.
##
## Guide 8.1
## [ ] 1. Imports: SimpleCookie (http.cookies), anyio, pytest, HTTPException
##        and Response (fastapi), TestClient (fastapi.testclient), Request
##        (starlette.requests), app (agent/app.py), create_web_session,
##        get_current_principal, require_same_origin (agent/auth.py),
##        get_settings.
## [ ] 2. Helpers: `_request(headers)` builds a starlette Request from a
##        minimal ASGI scope; `_cookie_for(principal_id)` runs
##        create_web_session with anyio.run and returns the cookie value
##        parsed from the Set-Cookie header.
## [ ] 3. test_health_answers_ok: TestClient(app).get("/agent/health") is
##        200 with {"status": "ok"}.
## [ ] 4. Async auth tests (@pytest.mark.anyio; they use Redis): no cookie
##        -> HTTPException 401; an unknown cookie -> 401; a stored session
##        -> that principal (kind "user"); a foreign Origin -> 403, our own
##        origin passes.
## [ ] 5. Check: uv run pytest tests/platform_tests/test_platform_agent.py -q
##
## Guide 8.2
## [ ] 6. test_fake_provider_replays_its_script: two scripted turns; the
##        first stream yields TextDelta, then Usage, then Stop("end_turn");
##        the second ends with Stop("tool_use"); provider.requests records
##        the tool names sent.
## [ ] 7. test_fake_provider_is_never_imported_by_production_code: no
##        active (non-comment) line of te_platform/**/*.py outside
##        providers/fake.py contains "providers.fake".
##
## Guide 8.3
## [ ] 8. test_integration_anthropic_verify_turn, skipped unless
##        TE_ANTHROPIC_API_KEY is set: offer the registry's tools, ask the
##        real model to verify examples/bitcoin.yaml, run its verify.run.v1
##        call through registry.pipeline.call, send the result back; the
##        second request ends with end_turn and reads from the prompt cache:
##          | assert usage2.cache_read_input_tokens > 0
##
## Guide 8.4
## [ ] 9. test_tool_name_mapping_round_trip (parametrized over the policy's
##        tools) and test_tool_id_with_double_underscore_is_rejected.
## [ ] 10. Module fixture `mcp_url`: a service API key stored in the
##        database, TE_AGENT_MCP_URL / TE_AGENT_MCP_API_KEY /
##        TE_MCP_ALLOWED_HOSTS set with pytest.MonkeyPatch.context() (and
##        get_settings.cache_clear()), then uvicorn serving
##        mcp_server/http_app.create_app() in a daemon thread on a free port.
## [ ] 11. Helpers: `_user()` (a fresh user principal), `_new_session(p)`,
##        the fixture `limits` (sets TE_* variables for one test through
##        monkeypatch and clears the settings cache), `_loop(provider,
##        bridge, user, sid, used=0)` (the persist callback appends (kind,
##        payload) to a `saved` list), `_run(...)` collecting every event of
##        loop.run_turn, `_bridge(user)` and `_validate(tool_use_id)` (a
##        spec.validate.v1 call on examples/bitcoin.yaml).
## [ ] 12. The loop tests (@pytest.mark.db, @pytest.mark.anyio), each opening
##        `async with McpBridge(on_behalf_of=user.id, ...)`: final answer;
##        token budget (no model request); tool-call limit (every call
##        answered with an error); time limit (a slow scripted turn);
##        refusal; precondition_failed then self-correction; confirmation
##        approved (the call runs in the next turn WITH tool_started /
##        tool_finished) and declined; all results in one user message;
##        session id injected; usage stored per request, not as a total.
## [ ] 13. Check: the step 5 command (now with the database and Redis).
##
## Guide 8.5
## [ ] 14. test_sse_text_with_newlines_stays_one_event: to_sse(TextDelta(
##        text="line one\nline two")) starts with "event: text_delta\n",
##        contains exactly one "\n\n", at its end, and its data JSON has
##        type "text_delta" and the full text.
## [ ] 15. Fixture `client` (TestClient on https://testserver, so the Secure
##        cookie is kept) and a helper `_use_script(turns)` that puts a
##        FakeProvider into app.dependency_overrides[get_provider].
## [ ] 16. Endpoint tests: a message streams text_delta ... done and the
##        transcript (user, assistant, usage rows) is stored; another user
##        gets 404 for the session; a POST without our Origin gets 403.
##
## Guide 9.0
## [ ] 17. Login tests with a user created by AuthRepository.create_user:
##        a wrong code -> 401; the 11th attempt -> 429 (clear the
##        "login-attempts:testclient" key first); login, then logout: the old
##        cookie gets 401.
##
## Guide 9.3
## [ ] 18. test_form_edit_is_visible_to_the_agent_on_its_next_turn: POST the
##        bitcoin YAML to .../spec, GET it back, then a scripted
##        graph.flow.v1 call (which needs the session's spec) succeeds.
##        test_form_refuses_an_invalid_spec: broken YAML -> 422.
##
## Guide 10.3
## [ ] 19. Download tests with a report row (Repository.save_report with a
##        ReportRecord) and a file in tmp_path, under a signing key set with
##        the `limits` fixture: the signed link works for its owner (the PDF
##        bytes); an altered or expired link gives 403; another user, even
##        with the link, gets 404.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## --- Imports, per guide step -----------------------------------------------------------
from http.cookies import SimpleCookie

import anyio
import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from te_platform.agent.app import app
from te_platform.agent.auth import create_web_session, get_current_principal, require_same_origin
from te_platform.config import get_settings

## Phase 8.2: the scripted provider.
from pathlib import Path
from te_platform.agent.providers.base import Stop, TextDelta, ToolCall, ToolDef, Usage
from te_platform.agent.providers.fake import FakeProvider, ScriptedTurn

## Phase 8.3: the real provider (its test is skipped without an API key).
import os
from te_platform.agent.providers.anthropic import AnthropicProvider
from te_platform.registry.context import CallContext, Principal
from te_platform.registry.describe import describe
from te_platform.registry.loader import build_registry
from te_platform.registry.pipeline import call

## Phase 8.4: the loop against the real MCP server.
import secrets
import socket
import threading
import time
from typing import Any
from uuid import uuid4
import uvicorn
from te_platform.agent.events import ConfirmationRequired, Done, ToolFinished, ToolStarted
from te_platform.agent.events import TextDelta as TextEvent
from te_platform.agent.loop import AgentLoop, PendingCalls, TurnInput
from te_platform.agent.mcp_bridge import McpBridge, from_provider_name, to_provider_name
from te_platform.db.repo import AuthRepository, Repository
from te_platform.db.session import session_scope
from te_platform.mcp_server.http_app import create_app
from te_platform.registry.context import SessionFacts
from te_platform.registry.policy import load_policy
from te_platform.security.api_keys import hash_api_key

## Phase 8.5: SSE and the chat endpoints.
import json
from te_platform.agent.chat_api import get_provider
from te_platform.agent.events import to_sse

## Phase 9.0: login (Redis holds the attempt counter).
import redis

## Phase 10.3: report download links.
from datetime import UTC, datetime, timedelta
from te_platform.db.repo import ReportRecord
from te_platform.security.signed_urls import sign_download

## Forms extension (te_platform/agent/forms.py): ask_user in the loop and the endpoint.
from te_platform.agent.events import FormRequested
from te_platform.agent.forms import ASK_USER


## --- Guide 8.1: health and the auth dependencies -------------------------------------------
def _request(headers: dict[str, str]) -> Request:
    """A minimal HTTP request carrying `headers` (enough for the dependencies)."""
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


def _cookie_for(principal_id: str) -> str:
    """Store a web session for `principal_id` (Redis); return the cookie value."""
    response = Response()
    anyio.run(create_web_session, response, principal_id)
    cookie = SimpleCookie(response.headers["set-cookie"])
    return cookie[get_settings().web_session_cookie].value


def test_health_answers_ok() -> None:
    response = TestClient(app).get("/agent/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_no_cookie_is_401() -> None:
    with pytest.raises(HTTPException) as err:
        await get_current_principal(_request({}))
    assert err.value.status_code == 401


@pytest.mark.anyio
async def test_unknown_cookie_is_401() -> None:
    name = get_settings().web_session_cookie
    with pytest.raises(HTTPException) as err:
        await get_current_principal(_request({"cookie": f"{name}=not-a-session"}))
    assert err.value.status_code == 401


def test_stored_session_gives_its_principal() -> None:
    name = get_settings().web_session_cookie
    token = _cookie_for("alice-8-1")
    principal = anyio.run(get_current_principal, _request({"cookie": f"{name}={token}"}))
    assert principal.id == "alice-8-1" and principal.kind == "user"


@pytest.mark.anyio
async def test_foreign_origin_is_403_and_our_origin_passes() -> None:
    with pytest.raises(HTTPException) as err:
        await require_same_origin(_request({"origin": "https://evil.example"}))
    assert err.value.status_code == 403
    await require_same_origin(_request({"origin": get_settings().public_origin}))


## --- Guide 8.2: the scripted provider ------------------------------------------------------
## Phase 8.2: the fake replays its turns in order, in the same event shape
## as a real provider, and records what it was sent.
## Guide 8.2
@pytest.mark.anyio
async def test_fake_provider_replays_its_script() -> None:
    provider = FakeProvider(
        [
            ScriptedTurn(text="Hello"),
            ScriptedTurn(tool_calls=[ToolCall("t1", "spec__validate__v1", {})]),
        ]
    )
    tools = [ToolDef(name="spec__validate__v1", description="", input_schema={})]
    first = [ev async for ev in provider.stream(system="s", messages=[], tools=tools)]
    assert isinstance(first[0], TextDelta) and first[0].text == "Hello"
    assert isinstance(first[1], Usage)
    assert isinstance(first[-1], Stop) and first[-1].reason == "end_turn"
    second = [ev async for ev in provider.stream(system="s", messages=[], tools=tools)]
    assert isinstance(second[0], ToolCall) and second[-1].reason == "tool_use"
    assert provider.requests[1]["tools"] == ["spec__validate__v1"]


## Phase 8.2: production code never imports the scripted provider.
def test_fake_provider_is_never_imported_by_production_code() -> None:
    for path in Path("te_platform").rglob("*.py"):
        if path.as_posix().endswith("providers/fake.py"):
            continue
        text = path.read_text(encoding="utf-8")
        active = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        assert "providers.fake" not in active, f"{path} imports the fake provider"


## --- Guide 8.3: the real model (integration test) -------------------------------------------
## Phase 8.3: runs only with TE_ANTHROPIC_API_KEY set (it costs credits). The
## tool list (all registry tools, as the MCP server describes them) and the
## system prompt form a prefix long enough to be cached; the second request
## must read it from the cache. The provider-side tool name is the id with
## "." replaced by "__" (agent/mcp_bridge.py does this from guide 8.4 on).
## Guide 8.3
@pytest.mark.skipif(not os.environ.get("TE_ANTHROPIC_API_KEY"), reason="needs TE_ANTHROPIC_API_KEY")
@pytest.mark.anyio
async def test_integration_anthropic_verify_turn() -> None:
    registry = build_registry(Path("policy/tool_policy.yaml"))
    tools = [
        ToolDef(
            name=t.replace(".", "__"),
            description=describe(t, registry.policy),
            input_schema=registry.tools[t].input_model.model_json_schema(),
        )
        for t in sorted(registry.tools)
    ]
    provider = AnthropicProvider()
    system = "You verify token economy designs with the tools provided. Be brief."
    spec = Path("examples/bitcoin.yaml").read_text()
    history = [provider.user_message(f"Verify this spec with verify.run.v1:\n\n{spec}")]
    events = [ev async for ev in provider.stream(system=system, messages=history, tools=tools)]
    stop = events[-1]
    assert isinstance(stop, Stop) and stop.reason == "tool_use"
    calls = [ev for ev in events if isinstance(ev, ToolCall)]
    assert calls and calls[0].name == "verify__run__v1"
    history.append(stop.assistant_message)
    results = []
    for c in calls:
        tool_id = c.name.replace("__", ".")
        ctx = CallContext(
            principal=Principal(id="integration-test", kind="api_key"),
            tool_id=tool_id,
            tool_input=c.arguments,
        )
        outcome = await call(registry, tool_id, c.arguments, ctx)
        results.append(
            provider.tool_result(c.tool_use_id, outcome.model_dump_json(), is_error=not outcome.ok)
        )
    history.append(provider.user_message("", results))
    events2 = [ev async for ev in provider.stream(system=system, messages=history, tools=tools)]
    usage2 = next(ev for ev in events2 if isinstance(ev, Usage))
    assert isinstance(events2[-1], Stop) and events2[-1].reason == "end_turn"
    assert usage2.cache_read_input_tokens > 0


## --- Guide 8.4: name mapping, the MCP server, the loop ---------------------------------------
## Phase 8.4: every policy tool id maps to a provider name and back.
POLICY = load_policy(Path("policy/tool_policy.yaml"))
BITCOIN = Path("examples/bitcoin.yaml").read_text()


## Phase 8.4: name mapping.
@pytest.mark.parametrize("tool_id", list(POLICY.tools))
def test_tool_name_mapping_round_trip(tool_id: str) -> None:
    name = to_provider_name(tool_id)
    assert "." not in name
    assert from_provider_name(name) == tool_id


## Phase 8.4: "__" is reserved for the mapping.
def test_tool_id_with_double_underscore_is_rejected() -> None:
    with pytest.raises(ValueError, match="__"):
        to_provider_name("bad__name.v1")


## Phase 8.4: the REAL MCP server (mcp_server/http_app.py), served by uvicorn
## in a background thread on a free port, with a service API key stored in
## the database: exactly what the agent container talks to in Compose.
## Guide 8.4
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


## Phase 8.4: the module fixture (one server for all the tests below).
@pytest.fixture(scope="module")
def mcp_url() -> Any:
    key = "te_test_" + secrets.token_urlsafe(24)
    with session_scope() as db:
        AuthRepository(db).create_api_key(
            owner=f"service:agent-test-{uuid4().hex[:8]}",
            kind="service",
            key_hash=hash_api_key(key),
        )
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TE_AGENT_MCP_URL", url)
        mp.setenv("TE_AGENT_MCP_API_KEY", key)
        mp.setenv("TE_MCP_ALLOWED_HOSTS", '["127.0.0.1:*"]')
        get_settings.cache_clear()
        server = uvicorn.Server(
            uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not server.started:
            assert time.monotonic() < deadline, "the MCP server did not start"
            time.sleep(0.05)
        yield url
        server.should_exit = True
        thread.join(timeout=10)
    get_settings.cache_clear()


## Phase 8.4: helpers for the loop tests.
def _user() -> Principal:
    return Principal(id=f"u-{uuid4().hex[:12]}", kind="user")


## Guide 8.4
def _new_session(principal: Principal) -> str:
    with session_scope() as db:
        return Repository(db, principal).create_session()


## Phase 8.4: per-test limits through the environment (monkeypatch restores it).
@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _set(**env: str) -> None:
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield _set
    monkeypatch.undo()
    get_settings.cache_clear()


## Guide 8.4
def _loop(
    provider: FakeProvider, bridge: McpBridge, user: Principal, sid: str, used: int = 0
) -> tuple[AgentLoop, list[tuple[str, Any]]]:
    saved: list[tuple[str, Any]] = []

    async def persist(kind: str, payload: Any) -> None:
        saved.append((kind, payload))

    async def load_facts() -> SessionFacts:
        def _f() -> SessionFacts:
            with session_scope() as db:
                return Repository(db, user).get_session_facts(sid)

        return await anyio.to_thread.run_sync(_f)

    loop = AgentLoop(
        provider=provider,
        policy=POLICY,
        system_prompt="test",
        principal=user,
        session_id=sid,
        load_facts=load_facts,
        bridge=bridge,
        persist=persist,
        tokens_used_so_far=used,
    )
    return loop, saved


## Guide 8.4
async def _run(
    loop: AgentLoop,
    inp: TurnInput,
    pending: PendingCalls | None = None,
    history: list[dict[str, Any]] | None = None,
) -> list[Any]:
    return [ev async for ev in loop.run_turn(inp, pending, history if history is not None else [])]


## Guide 8.4
def _bridge(user: Principal) -> McpBridge:
    return McpBridge(on_behalf_of=user.id, correlation_id=uuid4().hex)


## Guide 8.4
def _validate(tool_use_id: str, **args: Any) -> ToolCall:
    return ToolCall(tool_use_id, to_provider_name("spec.validate.v1"), {"spec": BITCOIN, **args})


## Phase 8.4: a plain answer ends the turn; only state-allowed tools are offered.
@pytest.mark.db
@pytest.mark.anyio
async def test_final_answer_without_tools_ends_turn(mcp_url: str) -> None:
    user = _user()
    provider = FakeProvider([ScriptedTurn(text="Hello")])
    async with _bridge(user) as bridge:
        loop, _ = _loop(provider, bridge, user, _new_session(user))
        events = await _run(loop, TurnInput("hi"))
    assert isinstance(events[0], TextEvent) and events[0].text == "Hello"
    assert isinstance(events[-1], Done) and events[-1].reason == "final_answer"
    offered = provider.requests[0]["tools"]
    assert "spec__validate__v1" in offered  # always available
    assert "verify__run__v1" not in offered  # a new session is still eliciting


## Phase 8.4: the session token budget stops the turn before any model request.
@pytest.mark.db
@pytest.mark.anyio
async def test_session_token_budget_stops_before_calling_model(mcp_url: str) -> None:
    user = _user()
    provider = FakeProvider([ScriptedTurn(text="never sent")])
    async with _bridge(user) as bridge:
        loop, _ = _loop(provider, bridge, user, _new_session(user), used=10**9)
        events = await _run(loop, TurnInput("hi"))
    assert isinstance(events[-1], Done) and events[-1].reason == "limit_reached"
    assert provider.requests == []  # no model call was paid for


## Phase 8.4: over the tool-call limit, every call is answered with an error
## (the API requires an answer for each tool_use) and nothing runs.
## Guide 8.4
@pytest.mark.db
@pytest.mark.anyio
async def test_tool_call_limit_answers_every_call_with_an_error(mcp_url: str, limits: Any) -> None:
    limits(TE_AGENT_MAX_TOOL_CALLS_PER_TURN="2")
    user = _user()
    provider = FakeProvider(
        [ScriptedTurn(tool_calls=[_validate("t1"), _validate("t2"), _validate("t3")])]
    )
    history: list[dict[str, Any]] = []
    async with _bridge(user) as bridge:
        loop, _ = _loop(provider, bridge, user, _new_session(user))
        events = await _run(loop, TurnInput("check"), history=history)
    assert not [ev for ev in events if isinstance(ev, ToolStarted)]
    assert isinstance(events[-1], Done) and events[-1].reason == "limit_reached"
    last = history[-1]
    assert last["role"] == "user"
    assert [b["tool_use_id"] for b in last["content"]] == ["t1", "t2", "t3"]
    assert all(b["is_error"] for b in last["content"])


## Phase 8.4: the per-turn time limit is checked between steps: a slow model
## request may finish, but no further request starts after the deadline.
## Guide 8.4
@pytest.mark.db
@pytest.mark.anyio
async def test_turn_time_limit_stops_between_steps(mcp_url: str, limits: Any) -> None:
    limits(TE_AGENT_MAX_SECONDS_PER_TURN="0.5")
    user = _user()
    provider = FakeProvider(
        [ScriptedTurn(tool_calls=[_validate("t1")], delay_s=0.7), ScriptedTurn(text="never sent")]
    )
    async with _bridge(user) as bridge:
        loop, _ = _loop(provider, bridge, user, _new_session(user))
        events = await _run(loop, TurnInput("check"))
    assert [type(ev) for ev in events if isinstance(ev, (ToolStarted, ToolFinished))] == [
        ToolStarted,
        ToolFinished,
    ]
    assert isinstance(events[-1], Done) and events[-1].reason == "limit_reached"
    assert len(provider.requests) == 1


## Phase 8.4: a refusal ends the turn with done(refusal).
@pytest.mark.db
@pytest.mark.anyio
async def test_refusal_ends_turn(mcp_url: str) -> None:
    user = _user()
    async with _bridge(user) as bridge:
        loop, _ = _loop(
            FakeProvider([ScriptedTurn(stop_reason="refusal")]), bridge, user, _new_session(user)
        )
        events = await _run(loop, TurnInput("hi"))
    assert isinstance(events[-1], Done) and events[-1].reason == "refusal"


## Phase 8.4: graph.flow.v1 needs a valid spec and the new session has none:
## the REAL pipeline answers precondition_failed with do_first, the model
## sees it as an error result and corrects itself.
## Guide 8.4
@pytest.mark.db
@pytest.mark.anyio
async def test_precondition_error_is_returned_and_model_self_corrects(mcp_url: str) -> None:
    user = _user()
    provider = FakeProvider(
        [
            ScriptedTurn(tool_calls=[ToolCall("t1", to_provider_name("graph.flow.v1"), {})]),
            ScriptedTurn(tool_calls=[_validate("t2")]),
            ScriptedTurn(text="Validated."),
        ]
    )
    async with _bridge(user) as bridge:
        loop, _ = _loop(provider, bridge, user, _new_session(user))
        events = await _run(loop, TurnInput("show me the flow graph"))
    finished = [ev for ev in events if isinstance(ev, ToolFinished)]
    assert [(f.tool, f.ok) for f in finished] == [
        ("graph.flow.v1", False),
        ("spec.validate.v1", True),
    ]
    assert finished[0].error_code == "precondition_failed"
    result = provider.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "do_first" in result["content"] and "spec.validate.v1" in result["content"]
    assert isinstance(events[-1], Done) and events[-1].reason == "final_answer"


## Phase 8.4: an expensive tool pauses the turn; once approved it runs at the
## start of the next turn, with tool_started / tool_finished like any call.
## Guide 8.4
@pytest.mark.db
@pytest.mark.anyio
async def test_expensive_tool_pauses_then_runs_after_confirmation(mcp_url: str) -> None:
    user = _user()
    sim = ToolCall("t1", to_provider_name("sim.monte_carlo.v1"), {"n_runs": 10})
    provider = FakeProvider([ScriptedTurn(tool_calls=[sim]), ScriptedTurn(text="Done.")])
    history: list[dict[str, Any]] = []
    async with _bridge(user) as bridge:
        loop, saved = _loop(provider, bridge, user, _new_session(user))
        first = await _run(loop, TurnInput("run a simulation"), history=history)
        assert not [ev for ev in first if isinstance(ev, ToolStarted)]  # nothing ran yet
        assert [ev.tool for ev in first if isinstance(ev, ConfirmationRequired)] == [
            "sim.monte_carlo.v1"
        ]
        assert isinstance(first[-1], Done) and first[-1].reason == "awaiting_confirmation"
        pending = next(p for k, p in saved if k == "pending" and p is not None)
        second = await _run(loop, TurnInput("", {"t1": True}), pending, history)
    assert [
        (type(ev), ev.tool_use_id) for ev in second if isinstance(ev, (ToolStarted, ToolFinished))
    ] == [(ToolStarted, "t1"), (ToolFinished, "t1")]
    assert provider.requests[1]["messages"][-1]["content"][0]["tool_use_id"] == "t1"
    assert ("pending", None) in saved
    assert isinstance(second[-1], Done) and second[-1].reason == "final_answer"


## Phase 8.4: a declined call never runs and becomes an error result.
@pytest.mark.db
@pytest.mark.anyio
async def test_declined_confirmation_becomes_an_error_result(mcp_url: str) -> None:
    user = _user()
    sim = ToolCall("t1", to_provider_name("sim.monte_carlo.v1"), {"n_runs": 10})
    provider = FakeProvider([ScriptedTurn(tool_calls=[sim]), ScriptedTurn(text="Fine.")])
    history: list[dict[str, Any]] = []
    async with _bridge(user) as bridge:
        loop, saved = _loop(provider, bridge, user, _new_session(user))
        await _run(loop, TurnInput("run a simulation"), history=history)
        pending = next(p for k, p in saved if k == "pending" and p is not None)
        second = await _run(loop, TurnInput("", {"t1": False}), pending, history)
    assert not [ev for ev in second if isinstance(ev, ToolStarted)]
    result = provider.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "declined" in result["content"]


## Phase 8.4: all results of one assistant message go back in ONE user message.
@pytest.mark.db
@pytest.mark.anyio
async def test_all_tool_results_go_back_in_one_user_message(mcp_url: str) -> None:
    user = _user()
    provider = FakeProvider(
        [ScriptedTurn(tool_calls=[_validate("t1"), _validate("t2")]), ScriptedTurn(text="ok")]
    )
    async with _bridge(user) as bridge:
        loop, _ = _loop(provider, bridge, user, _new_session(user))
        await _run(loop, TurnInput("check"))
    last_user = provider.requests[1]["messages"][-1]
    assert last_user["role"] == "user"
    assert [blk["tool_use_id"] for blk in last_user["content"]] == ["t1", "t2"]


## Phase 8.4: the model's session_id is replaced by the loop's. Left as the
## model wrote it, the MCP server would answer not_found (no such session).
## Guide 8.4
@pytest.mark.db
@pytest.mark.anyio
async def test_session_id_is_injected_by_the_loop_not_the_model(mcp_url: str) -> None:
    user = _user()
    provider = FakeProvider(
        [
            ScriptedTurn(tool_calls=[_validate("t1", session_id="someone-else")]),
            ScriptedTurn(text="ok"),
        ]
    )
    async with _bridge(user) as bridge:
        loop, _ = _loop(provider, bridge, user, _new_session(user))
        events = await _run(loop, TurnInput("check"))
    finished = [ev for ev in events if isinstance(ev, ToolFinished)]
    assert finished and finished[0].ok, finished


## Phase 8.4: usage is stored per model request (the database sums the rows).
@pytest.mark.db
@pytest.mark.anyio
async def test_usage_is_persisted_per_request_not_as_a_running_total(mcp_url: str) -> None:
    user = _user()
    provider = FakeProvider([ScriptedTurn(tool_calls=[_validate("t1")]), ScriptedTurn(text="ok")])
    async with _bridge(user) as bridge:
        loop, saved = _loop(provider, bridge, user, _new_session(user))
        events = await _run(loop, TurnInput("check"))
    usages = [p for k, p in saved if k == "usage"]
    assert [(u["input_tokens"], u["output_tokens"]) for u in usages] == [(100, 10), (100, 10)]
    assert isinstance(events[-1], Done) and events[-1].usage["input_tokens"] == 200


## --- Guide 8.5: SSE and the chat endpoints -----------------------------------------------------
## Phase 8.5: text with line breaks stays inside one SSE event.
def test_sse_text_with_newlines_stays_one_event() -> None:
    out = to_sse(TextEvent(text="line one\nline two"))
    assert out.startswith("event: text_delta\n")
    assert out.endswith("\n\n") and out.count("\n\n") == 1  # exactly one event boundary
    data = json.loads(out.split("data: ", 1)[1])
    assert data["type"] == "text_delta" and data["text"] == "line one\nline two"


## Phase 8.5: a client on https (the cookie is Secure) and helpers for the
## endpoint tests. The scripted provider replaces get_provider through
## FastAPI's dependency_overrides.
## Guide 8.5
@pytest.fixture
def client(mcp_url: str) -> Any:
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


## Guide 8.5
def _use_script(turns: list[ScriptedTurn]) -> FakeProvider:
    provider = FakeProvider(turns)
    app.dependency_overrides[get_provider] = lambda: provider
    return provider


## Guide 8.5
def _headers(user: Principal) -> dict[str, str]:
    name = get_settings().web_session_cookie
    return {"Cookie": f"{name}={_cookie_for(user.id)}", "Origin": get_settings().public_origin}


## Guide 8.5
def _sse_events(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


## Phase 8.5: a message streams its events and the transcript is stored.
@pytest.mark.db
def test_message_streams_events_and_stores_transcript(client: TestClient) -> None:
    user = _user()
    headers = _headers(user)
    sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
    _use_script([ScriptedTurn(text="Hello there")])
    response = client.post(f"/agent/sessions/{sid}/messages", json={"text": "hi"}, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response.text)
    assert events[0] == {"type": "text_delta", "text": "Hello there"}
    assert events[-1]["type"] == "done" and events[-1]["reason"] == "final_answer"
    session = client.get(f"/agent/sessions/{sid}", headers=headers).json()
    assert [m["role"] for m in session["messages"]] == ["user", "assistant", "usage"]
    assert session["state"] == "eliciting"


## Phase 8.5: another user's session looks exactly like a missing one.
@pytest.mark.db
def test_other_users_session_is_404(client: TestClient) -> None:
    owner, other = _user(), _user()
    sid = client.post("/agent/sessions", headers=_headers(owner)).json()["session_id"]
    assert client.get(f"/agent/sessions/{sid}", headers=_headers(other)).status_code == 404
    _use_script([])
    response = client.post(
        f"/agent/sessions/{sid}/messages", json={"text": "hi"}, headers=_headers(other)
    )
    assert response.status_code == 404


## Phase 8.5: POSTs need our Origin (CSRF defence) and a session cookie.
@pytest.mark.db
def test_post_needs_our_origin_and_a_cookie(client: TestClient) -> None:
    headers = _headers(_user())
    foreign = {**headers, "Origin": "https://evil.example"}
    assert client.post("/agent/sessions", headers=foreign).status_code == 403
    no_cookie = {"Origin": headers["Origin"]}
    assert client.post("/agent/sessions", headers=no_cookie).status_code == 401


## --- Guide 9.0: login and logout --------------------------------------------------------------
## Phase 9.0: a user with a known access code, and a clean attempt counter.
@pytest.fixture
def login_user(client: TestClient) -> Any:
    code = "tu_" + secrets.token_urlsafe(24)
    with session_scope() as db:
        AuthRepository(db).create_user(f"{uuid4().hex[:8]}@example.org", hash_api_key(code))
    redis.Redis.from_url(get_settings().redis_url).delete("login-attempts:testclient")
    return code


## Phase 9.0: a wrong code gives 401, the 11th attempt within 15 minutes 429.
@pytest.mark.db
def test_wrong_code_is_401_and_the_eleventh_attempt_429(
    client: TestClient, login_user: str
) -> None:
    origin = {"Origin": get_settings().public_origin}
    for _ in range(10):
        r = client.post("/agent/login", json={"access_code": "tu_wrong-code-123"}, headers=origin)
        assert r.status_code == 401
    r = client.post("/agent/login", json={"access_code": login_user}, headers=origin)
    assert r.status_code == 429  # even the right code: wait 15 minutes


## Phase 9.0: after logout, the old cookie no longer works.
@pytest.mark.db
def test_logout_makes_the_old_cookie_useless(client: TestClient, login_user: str) -> None:
    origin = {"Origin": get_settings().public_origin}
    r = client.post("/agent/login", json={"access_code": login_user}, headers=origin)
    assert r.status_code == 200
    name = get_settings().web_session_cookie
    old = {**origin, "Cookie": f"{name}={r.cookies[name]}"}
    client.cookies.clear()
    assert client.post("/agent/sessions", headers=old).status_code == 200
    assert client.post("/agent/logout", headers=old).status_code == 200
    assert client.post("/agent/sessions", headers=old).status_code == 401


## --- Guide 9.3: the form <-> chat round trip ----------------------------------------------------
## Phase 9.3: an edit made in the form is visible to the agent on its next
## turn: graph.flow.v1 without a spec argument uses the session's spec, so it
## succeeds only if the form's spec reached the session.
## Guide 9.3
@pytest.mark.db
def test_form_edit_is_visible_to_the_agent_on_its_next_turn(client: TestClient) -> None:
    headers = _headers(_user())
    sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
    assert client.get(f"/agent/sessions/{sid}/spec", headers=headers).json()["yaml"] is None
    saved = client.post(f"/agent/sessions/{sid}/spec", json={"yaml": BITCOIN}, headers=headers)
    assert saved.status_code == 200 and saved.json()["version"] == 1
    back = client.get(f"/agent/sessions/{sid}/spec", headers=headers).json()
    assert back["yaml"] and back["spec_hash"] == saved.json()["spec_hash"]
    _use_script(
        [
            ScriptedTurn(tool_calls=[ToolCall("t1", to_provider_name("graph.flow.v1"), {})]),
            ScriptedTurn(text="Here is the graph."),
        ]
    )
    body = client.post(
        f"/agent/sessions/{sid}/messages", json={"text": "graph?"}, headers=headers
    ).text
    finished = [e for e in _sse_events(body) if e["type"] == "tool_finished"]
    assert finished == [
        {
            "type": "tool_finished",
            "tool_use_id": "t1",
            "tool": "graph.flow.v1",
            "ok": True,
            "error_code": None,
        }
    ]


## Phase 9.3: an invalid spec is refused with the validation problems.
@pytest.mark.db
def test_form_refuses_an_invalid_spec(client: TestClient) -> None:
    headers = _headers(_user())
    sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
    r = client.post(f"/agent/sessions/{sid}/spec", json={"yaml": "not: [a, spec"}, headers=headers)
    assert r.status_code == 422


## --- Guide 10.3: report download ------------------------------------------------------------------
## Phase 10.3: the key that signs and verifies download links (a Docker
## secret in production), set for each download test.
## Guide 10.3
SIGNING_KEY = "test-signing-key-" + "x" * 32


## Phase 10.3: a stored report (row + file) and its signed link.
def _report(owner: Principal, folder: Path, *, reviewed: bool = True) -> tuple[str, bytes]:
    report_id = uuid4().hex
    pdf = b"%PDF-1.4 test report"
    path = folder / f"{report_id}.pdf"
    path.write_bytes(pdf)
    with session_scope() as db:
        Repository(db, owner).save_report(
            ReportRecord(
                report_id=report_id,
                verification_ref="vref:test",
                narrative={},
                path=str(path),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    if reviewed:  # the agent's review (report.publish.v1) makes the link work
        with session_scope() as db:
            Repository(db, owner).publish_report(report_id, "Checked every number. " * 5)
    return report_id, pdf


## Report review: a draft (not yet reviewed by the agent) cannot be downloaded,
## even by its owner with a valid link.
@pytest.mark.db
def test_a_draft_report_cannot_be_downloaded(
    client: TestClient, tmp_path: Path, limits: Any
) -> None:
    limits(TE_REPORT_SIGNING_KEY=SIGNING_KEY)
    owner = _user()
    report_id, _ = _report(owner, tmp_path, reviewed=False)
    r = client.get(
        sign_download(report_id, datetime.now(UTC) + timedelta(hours=1)), headers=_headers(owner)
    )
    assert r.status_code == 404 and "still checking" in r.json()["detail"]


## Phase 10.3: the link works for its owner.
@pytest.mark.db
def test_signed_link_works_for_its_owner(client: TestClient, tmp_path: Path, limits: Any) -> None:
    limits(TE_REPORT_SIGNING_KEY=SIGNING_KEY)
    owner = _user()
    report_id, pdf = _report(owner, tmp_path)
    link = sign_download(report_id, datetime.now(UTC) + timedelta(hours=1))
    r = client.get(link, headers=_headers(owner))
    assert r.status_code == 200 and r.content == pdf
    assert r.headers["content-type"] == "application/pdf"


## Phase 10.3: an altered or expired link gives 403.
@pytest.mark.db
def test_altered_or_expired_link_is_403(client: TestClient, tmp_path: Path, limits: Any) -> None:
    limits(TE_REPORT_SIGNING_KEY=SIGNING_KEY)
    owner = _user()
    report_id, _ = _report(owner, tmp_path)
    link = sign_download(report_id, datetime.now(UTC) + timedelta(hours=1))
    assert client.get(link[:-2] + "xx", headers=_headers(owner)).status_code == 403
    expired = sign_download(report_id, datetime.now(UTC) - timedelta(seconds=5))
    assert client.get(expired, headers=_headers(owner)).status_code == 403


## Phase 10.3: another user gets 404, even with a valid link.
@pytest.mark.db
def test_other_user_gets_404_even_with_the_link(
    client: TestClient, tmp_path: Path, limits: Any
) -> None:
    limits(TE_REPORT_SIGNING_KEY=SIGNING_KEY)
    report_id, _ = _report(_user(), tmp_path)
    link = sign_download(report_id, datetime.now(UTC) + timedelta(hours=1))
    assert client.get(link, headers=_headers(_user())).status_code == 404


## --- Forms extension (te_platform/agent/forms.py): the loop and the endpoint -------------
## The pure checks of forms and answers are in test_platform_forms.py.

ASK_FORM: dict[str, Any] = {
    "title": "Who takes part",
    "questions": [
        {
            "id": "participants.N",
            "label": "How many people take part?",
            "kind": "number",
            "min": 1,
        },
        {
            "id": "meta.archetype",
            "label": "What is the exchange mainly for?",
            "kind": "single_choice",
            "options": [
                {"value": "community_reward", "label": "Rewarding contributions"},
                {"value": "marketplace", "label": "Buying and selling"},
            ],
        },
    ],
}
ASK_ANSWERS: dict[str, Any] = {
    "participants.N": {"status": "answered", "value": 30},
    "meta.archetype": {"status": "answered", "value": "community_reward"},
}


def _ask(tool_use_id: str, form: dict[str, Any] | None = None) -> ToolCall:
    return ToolCall(tool_use_id, ASK_USER, form if form is not None else ASK_FORM)


## Forms: ask_user is offered in every state, always LAST (stable prompt cache).
@pytest.mark.db
@pytest.mark.anyio
async def test_ask_user_is_offered_last(mcp_url: str) -> None:
    user = _user()
    provider = FakeProvider([ScriptedTurn(text="Hello")])
    async with _bridge(user) as bridge:
        loop, _ = _loop(provider, bridge, user, _new_session(user))
        await _run(loop, TurnInput("hi"))
    assert provider.requests[0]["tools"][-1] == ASK_USER


## Forms: a form pauses the turn; its answers come back as the tool result.
@pytest.mark.db
@pytest.mark.anyio
async def test_form_pauses_the_turn_and_its_answers_become_the_tool_result(mcp_url: str) -> None:
    user = _user()
    provider = FakeProvider(
        [
            ScriptedTurn(text="Two quick questions.", tool_calls=[_ask("f1")]),
            ScriptedTurn(text="Thanks."),
        ]
    )
    history: list[dict[str, Any]] = []
    async with _bridge(user) as bridge:
        loop, saved = _loop(provider, bridge, user, _new_session(user))
        first = await _run(loop, TurnInput("hi"), history=history)
        forms = [ev for ev in first if isinstance(ev, FormRequested)]
        assert [f.tool_use_id for f in forms] == ["f1"]
        assert forms[0].form["questions"][1]["options"][0]["label"] == "Rewarding contributions"
        assert not [ev for ev in first if isinstance(ev, ToolStarted)]  # nothing ran via MCP
        assert isinstance(first[-1], Done) and first[-1].reason == "awaiting_input"
        pending = next(p for k, p in saved if k == "pending" and p is not None)
        assert [f["tool_use_id"] for f in pending.forms] == ["f1"]
        second = await _run(loop, TurnInput("", form_answers={"f1": ASK_ANSWERS}), pending, history)
    result = provider.requests[1]["messages"][-1]["content"][0]
    assert result["tool_use_id"] == "f1" and result["is_error"] is False
    payload = json.loads(result["content"])
    assert payload["form"] == "submitted"
    assert [(a["question_id"], a["display"]) for a in payload["answers"]] == [
        ("participants.N", "30"),
        ("meta.archetype", "Rewarding contributions"),
    ]
    assert ("pending", None) in saved
    assert isinstance(second[-1], Done) and second[-1].reason == "final_answer"


## Forms: typing a message instead of filling in the form skips it; the text follows.
@pytest.mark.db
@pytest.mark.anyio
async def test_typing_instead_of_answering_skips_the_form(mcp_url: str) -> None:
    user = _user()
    provider = FakeProvider([ScriptedTurn(tool_calls=[_ask("f1")]), ScriptedTurn(text="I see.")])
    history: list[dict[str, Any]] = []
    async with _bridge(user) as bridge:
        loop, saved = _loop(provider, bridge, user, _new_session(user))
        await _run(loop, TurnInput("hi"), history=history)
        pending = next(p for k, p in saved if k == "pending" and p is not None)
        await _run(loop, TurnInput("About thirty people"), pending, history)
    content = provider.requests[1]["messages"][-1]["content"]
    assert content[0]["tool_use_id"] == "f1"
    assert json.loads(content[0]["content"])["form"] == "not_submitted"
    assert content[1] == {"type": "text", "text": "About thirty people"}


## Forms: an invalid form is never shown; the model gets the problem at once.
@pytest.mark.db
@pytest.mark.anyio
async def test_invalid_form_is_returned_to_the_model_in_the_same_turn(mcp_url: str) -> None:
    user = _user()
    bad = {"questions": [{"id": "q", "label": "Q?", "kind": "single_choice", "options": []}]}
    provider = FakeProvider(
        [ScriptedTurn(tool_calls=[_ask("f1", bad)]), ScriptedTurn(text="Sorry.")]
    )
    async with _bridge(user) as bridge:
        loop, saved = _loop(provider, bridge, user, _new_session(user))
        events = await _run(loop, TurnInput("hi"))
    assert not [ev for ev in events if isinstance(ev, FormRequested)]
    result = provider.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "2 options" in result["content"]
    assert not [p for k, p in saved if k == "pending" and p is not None]
    assert isinstance(events[-1], Done) and events[-1].reason == "final_answer"


## Forms: a form and an expensive tool in one message: both are shown, both settle.
@pytest.mark.db
@pytest.mark.anyio
async def test_form_and_confirmation_together(mcp_url: str) -> None:
    user = _user()
    sim = ToolCall("t1", to_provider_name("sim.monte_carlo.v1"), {"n_runs": 10})
    provider = FakeProvider([ScriptedTurn(tool_calls=[_ask("f1"), sim]), ScriptedTurn(text="ok")])
    history: list[dict[str, Any]] = []
    async with _bridge(user) as bridge:
        loop, saved = _loop(provider, bridge, user, _new_session(user))
        first = await _run(loop, TurnInput("hi"), history=history)
        assert {type(ev) for ev in first} >= {FormRequested, ConfirmationRequired}
        assert isinstance(first[-1], Done) and first[-1].reason == "awaiting_confirmation"
        pending = next(p for k, p in saved if k == "pending" and p is not None)
        await _run(loop, TurnInput("", {"t1": False}, {"f1": ASK_ANSWERS}), pending, history)
    ids = [b["tool_use_id"] for b in provider.requests[1]["messages"][-1]["content"]]
    assert sorted(ids) == ["f1", "t1"]  # every tool_use answered in ONE message


## Forms: the endpoint refuses an answer that does not fit, before any model call.
@pytest.mark.db
def test_invalid_form_answer_is_422_and_costs_no_model_call(client: TestClient) -> None:
    user = _user()
    headers = _headers(user)
    sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
    _use_script([ScriptedTurn(text="A form:", tool_calls=[_ask("f1")])])
    events = _sse_events(
        client.post(f"/agent/sessions/{sid}/messages", json={"text": "hi"}, headers=headers).text
    )
    assert [e["type"] for e in events if e["type"] == "form_requested"] == ["form_requested"]
    provider = _use_script([ScriptedTurn(text="Thanks.")])
    bad = {"f1": {**ASK_ANSWERS, "meta.archetype": {"status": "answered", "value": "admin"}}}
    r = client.post(
        f"/agent/sessions/{sid}/messages", json={"text": "", "form_answers": bad}, headers=headers
    )
    assert r.status_code == 422
    assert r.json()["detail"]["question_id"] == "meta.archetype"
    stray = {"f9": ASK_ANSWERS}  # a form that was never shown
    r = client.post(
        f"/agent/sessions/{sid}/messages", json={"text": "", "form_answers": stray}, headers=headers
    )
    assert r.status_code == 422
    assert provider.requests == []  # nothing was sent to the model
    ok = client.post(
        f"/agent/sessions/{sid}/messages",
        json={"text": "", "form_answers": {"f1": ASK_ANSWERS}},
        headers=headers,
    )
    assert ok.status_code == 200 and _sse_events(ok.text)[-1]["type"] == "done"
    assert json.loads(provider.requests[0]["messages"][-1]["content"][0]["content"])["form"] == (
        "submitted"
    )


## Forms: the session lists its open forms (the chat page restores them after a
## reload) until they are answered.
@pytest.mark.db
def test_session_lists_its_open_forms_until_answered(client: TestClient) -> None:
    user = _user()
    headers = _headers(user)
    sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
    assert client.get(f"/agent/sessions/{sid}", headers=headers).json()["pending_forms"] == []
    _use_script([ScriptedTurn(text="A form:", tool_calls=[_ask("f1")])])
    client.post(f"/agent/sessions/{sid}/messages", json={"text": "hi"}, headers=headers)
    pending = client.get(f"/agent/sessions/{sid}", headers=headers).json()["pending_forms"]
    assert [f["tool_use_id"] for f in pending] == ["f1"]
    assert pending[0]["form"]["questions"][0]["id"] == "participants.N"
    # Another user sees nothing of it (the session itself is a 404 for them).
    assert client.get(f"/agent/sessions/{sid}", headers=_headers(_user())).status_code == 404
    _use_script([ScriptedTurn(text="Thanks.")])
    client.post(
        f"/agent/sessions/{sid}/messages",
        json={"text": "", "form_answers": {"f1": ASK_ANSWERS}},
        headers=headers,
    )
    assert client.get(f"/agent/sessions/{sid}", headers=headers).json()["pending_forms"] == []


## Forms: the open forms come back complete (defaults filled in); a stored form
## that no longer validates is left out instead of breaking the page.
@pytest.mark.db
def test_open_forms_are_returned_complete_and_invalid_ones_left_out(client: TestClient) -> None:
    user = _user()
    headers = _headers(user)
    sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
    minimal = {"questions": [{"id": "notes", "label": "Anything else?", "kind": "text"}]}
    broken = {"questions": [{"id": "q", "label": "Q?", "kind": "slider"}]}
    with session_scope() as db:
        Repository(db, user).set_pending_tool_calls(
            sid,
            {
                "ready_results": [],
                "awaiting": [],
                "forms": [
                    {"tool_use_id": "f1", "form": minimal},
                    {"tool_use_id": "f2", "form": broken},
                ],
            },
        )
    forms = client.get(f"/agent/sessions/{sid}", headers=headers).json()["pending_forms"]
    assert [f["tool_use_id"] for f in forms] == ["f1"]
    question = forms[0]["form"]["questions"][0]
    assert question["required"] is True and question["allow_unknown"] is True


## --- Conversation history extension (te_platform/agent/transcript.py) ---------------------
## The user's conversations are listed (only theirs, newest first, titled by
## their first message); sessions without any message are left out.
@pytest.mark.db
def test_conversations_are_listed_newest_first_and_only_the_owners(client: TestClient) -> None:
    user = _user()
    headers = _headers(user)
    ids = []
    for text in ("First idea: a garden", "Second idea: a shoe network"):
        sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
        _use_script([ScriptedTurn(text="Noted.")])
        client.post(f"/agent/sessions/{sid}/messages", json={"text": text}, headers=headers)
        ids.append(sid)
    client.post("/agent/sessions", headers=headers)  # never used: not listed
    listed = client.get("/agent/sessions", headers=headers).json()["conversations"]
    assert [c["session_id"] for c in listed] == ids[::-1]
    assert [c["title"] for c in listed] == ["Second idea: a shoe network", "First idea: a garden"]
    assert client.get("/agent/sessions", headers=_headers(_user())).json()["conversations"] == []


## The session returns its transcript (what the person saw, no thinking) and
## the panel's content.
@pytest.mark.db
def test_session_returns_its_transcript(client: TestClient) -> None:
    user = _user()
    headers = _headers(user)
    sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
    _use_script([ScriptedTurn(text="Two questions.", tool_calls=[_ask("f1")])])
    client.post(f"/agent/sessions/{sid}/messages", json={"text": "hi"}, headers=headers)
    session = client.get(f"/agent/sessions/{sid}", headers=headers).json()
    assert [i["kind"] for i in session["transcript"]] == [
        "user_text",
        "assistant_text",
        "form_asked",
    ]
    assert session["slots"] == [] and session["verdicts"] == []


## A turn that fails before any answer is undone: the user's text is not kept
## (so it never reaches the model with the next message), and the page is told.
@pytest.mark.db
def test_failed_turn_discards_the_unanswered_message(client: TestClient) -> None:
    user = _user()
    headers = _headers(user)
    sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
    _use_script([])  # the provider fails at once
    events = _sse_events(
        client.post(f"/agent/sessions/{sid}/messages", json={"text": "hello"}, headers=headers).text
    )
    assert events[-1]["type"] == "error" and events[-1]["message_discarded"] is True
    session = client.get(f"/agent/sessions/{sid}", headers=headers).json()
    assert session["messages"] == []
    # The next message is the only one the model sees.
    provider = _use_script([ScriptedTurn(text="Hi!")])
    client.post(f"/agent/sessions/{sid}/messages", json={"text": "hello again"}, headers=headers)
    assert provider.requests[0]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hello again"}]}
    ]


## A failed turn that carried form answers keeps them: they answer the
## assistant's earlier ask_user call, which must not be left without a result.
@pytest.mark.db
def test_failed_turn_keeps_a_message_with_tool_results(client: TestClient) -> None:
    user = _user()
    headers = _headers(user)
    sid = client.post("/agent/sessions", headers=headers).json()["session_id"]
    _use_script([ScriptedTurn(text="A form:", tool_calls=[_ask("f1")])])
    client.post(f"/agent/sessions/{sid}/messages", json={"text": "hi"}, headers=headers)
    _use_script([])  # fails after the answers were stored
    events = _sse_events(
        client.post(
            f"/agent/sessions/{sid}/messages",
            json={"text": "", "form_answers": {"f1": ASK_ANSWERS}},
            headers=headers,
        ).text
    )
    assert events[-1]["type"] == "error" and events[-1]["message_discarded"] is False
    kinds = [
        i["kind"]
        for i in client.get(f"/agent/sessions/{sid}", headers=headers).json()["transcript"]
    ]
    assert kinds[-1] == "form_answers"


## An exhausted API account is named as such: retrying cannot help.
def test_out_of_credit_error_tells_what_to_do():
    # The SDK is installed with the agent extra (the agent container).
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx2")  # the SDK's HTTP client (anthropic 2.x)
    from te_platform.agent.providers.anthropic import _provider_error

    body = {"type": "error", "error": {"type": "invalid_request_error"}}
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com"))
    exc = anthropic.BadRequestError(
        "Your credit balance is too low to access the Anthropic API.", response=response, body=body
    )
    err = _provider_error(exc)
    assert "run out of credits" in str(err) and not err.retryable
    other = anthropic.BadRequestError("tools.0: invalid", response=response, body=body)
    assert "could not answer" in str(_provider_error(other))
