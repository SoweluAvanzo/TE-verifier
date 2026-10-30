## =============================================================================
## te_platform/agent/chat_api.py — chat endpoints: sessions and messages (SSE)
## =============================================================================
## GUIDE STEP   8.5
## PURPOSE      The endpoints the chat page (webapp/static/chat.js) calls:
##                POST /agent/sessions                   start a design session
##                GET  /agent/sessions/{id}              state, spec hash, open decisive
##                                                       questions, transcript
##                POST /agent/sessions/{id}/messages     send a message; the answer
##                                                       streams back as SSE events
##              (The spec endpoints of the form round trip are in
##              agent/spec_api.py, guide 9.3.)
##              They are grouped in an APIRouter that agent/app.py includes.
## USED BY      agent/app.py (include_router), webapp/static/chat.js, the tests
##              (they replace get_provider with the scripted provider through
##              FastAPI's app.dependency_overrides).
## DEPENDS ON   fastapi, anyio; agent/auth.py, agent/events.py, agent/loop.py,
##              agent/mcp_bridge.py, agent/providers/ (base + anthropic),
##              agent/prompts/*.md, db/session.py + db/repo.py,
##              elicitation/protocol.py (protocol version), registry/policy.py,
##              registry/state.py, registry/context.py, config.py.
## WHY          Architecture §3.4-3.5, D8 (the turn logic lives in loop.py; this
##              file only does HTTP, auth, loading and saving), D9 (a fixed
##              system prompt, so the prompt cache works).
## ACTIVATE     Uncomment, then toggle the chat_api lines in agent/app.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do only
## the group of the step you are on and run its "Check" before moving on.
## Lines starting with "|" are short illustrations, not the full code. Keep
## every route path, function name and field name exactly as written:
## chat.js, the tests and the evals depend on them.
##
## Guide 8.5
## [ ] 1. Imports at the top: the full list is the first block of the
##        SOLUTION (standard library, anyio, fastapi, pydantic, then the
##        te_platform modules of DEPENDS ON). Then
##        `log = logging.getLogger("te_platform.agent")` and
##        `router = APIRouter()`.
## [ ] 2. The objects loaded ONCE per process, at import:
##        POLICY = load_policy(policy_dir / "tool_policy.yaml") and
##        PROTOCOL_VERSION = load_protocol(... "elicitation_protocol.yaml")
##        .version, where policy_dir comes from get_settings().
## [ ] 3. `_load_prompt(name: str) -> str`: read prompts/<name>, raise
##        RuntimeError while the file still holds the DRAFT marker, remove
##        the YAML front-matter and EVERY HTML comment with re.sub
##        (flags=re.DOTALL): the header, TODO list and SOLUTION marker are
##        for developers, not the model. Return the stripped text. Then
##          | SYSTEM_PROMPT = (_load_prompt("system.md") + "\n\n"
##          |                  + _load_prompt("interview.md"))
##        so the service refuses to start until both prompts are reviewed.
## [ ] 4. `get_provider() -> ChatProvider`, decorated with @lru_cache(
##        maxsize=1): return AnthropicProvider(). Endpoints receive it as a
##        dependency, so it is created on first use (not at import) and the
##        tests can swap in the scripted provider.
## [ ] 5. Request/response models, each with a docstring: MessageIn (text:
##        str, default "", max_length=8000; confirmations: dict[str, bool])
##        and SessionOut (session_id, state, spec_hash, open_decisive_slots,
##        messages).
## [ ] 6. POST /agent/sessions `create_session(principal: CurrentUser)`,
##        with dependencies=SameOrigin (both from agent/auth.py). Do the
##        database work in a small sync inner function run in a worker
##        thread:
##          | return {"session_id": await anyio.to_thread.run_sync(_create)}
##        It calls Repository(db, principal).create_session(
##        protocol_version=PROTOCOL_VERSION,
##        policy_version=POLICY.policy_version).
## [ ] 7. GET /agent/sessions/{session_id} `get_session` -> SessionOut: load
##        the session facts, build CallContext(principal=..., tool_id="",
##        tool_input={}, session=facts), state = compute_state(ctx, POLICY),
##        messages = repo.list_messages(session_id). Same thread pattern.
## [ ] 8. Helpers for the message endpoint (they keep it short):
##        `_load_turn(principal, session_id)` (sync: ownership check via
##        get_session_facts, history = the "content" of the user/assistant
##        rows, pending = PendingCalls(**raw) or None, repo.tokens_used),
##        `_facts_loader(principal, session_id)`, `_slots_loader(...)`
##        (the answered slots {slot_id, indices, status, value}, from
##        repo.get_answers) and `_persister(principal, session_id)`, which
##        return the async callbacks the loop needs (persist handles
##        "message", "usage" and "pending"; the kinds are in loop.py).
## [ ] 9. POST /agent/sessions/{session_id}/messages `post_message(
##        session_id, body: MessageIn, principal: CurrentUser, provider:
##        Annotated[ChatProvider, Depends(get_provider)])` ->
##        StreamingResponse: run _load_turn in a thread, then define
##        `event_stream()`, an async generator: correlation_id =
##        uuid4().hex; open `McpBridge(on_behalf_of=principal.id,
##        correlation_id=...)` with `async with`; build AgentLoop with
##        keyword arguments; `yield to_sse(event)` for every event of
##        loop.run_turn(TurnInput(body.text, body.confirmations), pending,
##        history). On ProviderError: log a warning, yield an ErrorEvent with
##        exc.user_message; on any other Exception: log.exception(...) with
##        the correlation_id, then an ErrorEvent with a generic message
##        (never internals). Return StreamingResponse(event_stream(),
##        media_type="text/event-stream") with the headers
##        Cache-Control: no-cache and X-Accel-Buffering: no.
## [ ] 10. Check: toggle the chat_api lines of agent/app.py, activate the
##        guide 8.5 tests of tests/platform_tests/test_platform_agent.py,
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##          | uv run mypy te_platform
##        and by hand (guide 8.5): `curl -N` on the messages endpoint shows
##        the events as they arrive (send the session cookie and an Origin
##        header equal to TE_PUBLIC_ORIGIN), and GET /agent/sessions/{id}
##        lists the stored transcript.
##
## Forms extension (structured questions; agent/forms.py, not in the guide yet)
## [ ] 11. MessageIn gets `form_answers` (tool_use_id -> {question_id:
##        answer}, at most MAX_FORMS_PER_MESSAGE forms). post_message checks
##        them with forms.validate_all against the forms stored in the
##        session's pending calls BEFORE the stream starts: an invalid
##        answer is a 422 whose detail has a message and the question_id
##        (chat.js shows it next to that question), and no model call is
##        paid for. TurnInput then carries them to the loop.
## [ ] 12. SessionOut gets `pending_forms` (the forms of the stored pending
##        calls, [] when none): get_session returns them through
##        `_open_forms`, each validated and complete (defaults filled in;
##        one that no longer validates is left out), so the chat page shows
##        an unanswered form again after a reload.
##
## Conversation history extension (agent/transcript.py, not in the guide yet)
## [ ] 13. GET /agent/sessions `list_conversations`: the user's conversations
##        (Repository.list_sessions), each with its title (transcript.
##        conversation_title of its first message) and times.
## [ ] 14. SessionOut gets `transcript` (transcript.display_transcript of the
##        stored messages: what the person saw, no thinking blocks),
##        `slots` (the recorded answers) and `verdicts` (the latest
##        verification of the current spec), so the page can rebuild the
##        conversation and the panel.
## [ ] 15. A turn that fails is undone when its only stored message is the
##        user's text (_discard_unanswered: the persist callback collects
##        this turn's rows): otherwise every failed attempt would reach the
##        model with the next one. ErrorEvent.message_discarded tells the
##        page, which offers the text back.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from te_platform.agent.auth import CurrentUser, SameOrigin
from te_platform.agent.events import ErrorEvent, to_sse
from te_platform.agent.forms import (
    MAX_FORMS_PER_MESSAGE,
    AskUserInput,
    FormAnswerError,
    validate_all,
)
from te_platform.agent.loop import AgentLoop, PendingCalls, Persist, TurnInput
from te_platform.agent.mcp_bridge import McpBridge
from te_platform.agent.notes import spec_from_form_note
from te_platform.agent.providers.anthropic import AnthropicProvider
from te_platform.agent.providers.base import ChatProvider, ProviderError
from te_platform.agent.providers.openai_compatible import OpenAICompatibleProvider
from te_platform.agent.transcript import conversation_title, display_transcript
from te_platform.config import get_settings
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.elicitation.protocol import load_protocol
from te_platform.registry.context import CallContext, Principal, SessionFacts
from te_platform.registry.policy import load_policy
from te_platform.registry.state import compute_state

log = logging.getLogger("te_platform.agent")
router = APIRouter()


## --- Loaded once per process ----------------------------------------------------------
## The policy (read-only) and the protocol version, recorded in every new
## session (architecture P5: which rules governed it).
_policy_dir = get_settings().policy_dir
POLICY = load_policy(_policy_dir / "tool_policy.yaml")
PROTOCOL_VERSION = load_protocol(_policy_dir / "elicitation_protocol.yaml").version


## The system prompt is a FIXED text (prompt caching needs identical bytes).
## Prompt files have: optional YAML front-matter (--- ... ---, Agent Skills
## format), then HTML comments (<!-- ... -->: the developer header, the TODO
## list, the SOLUTION marker), then the prompt. While a prompt is still a
## draft it sits between "<!-- DRAFT" and "DRAFT -->" lines; _load_prompt
## REFUSES drafts, so a prompt is only used after someone reviewed it and
## deleted the two marker lines. Loading at import means the service does not
## start at all with an unreviewed prompt.
def _load_prompt(name: str) -> str:
    text = (Path(__file__).parent / "prompts" / name).read_text(encoding="utf-8")
    if "<!-- DRAFT" in text:
        raise RuntimeError(f"prompts/{name} is still a draft: review it, remove the DRAFT markers")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)  # front-matter
    # Every HTML comment: none of them is meant for the model.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return text.strip()


SYSTEM_PROMPT = _load_prompt("system.md") + "\n\n" + _load_prompt("interview.md")


## The model provider, created on first use and then shared by all requests
## (it holds a connection pool to the Anthropic API). As a dependency it can
## be replaced in tests: app.dependency_overrides[get_provider] = ... (the
## scripted provider: the one documented exception to "no fakes", because it
## replaces a paid external API, not our code).
@lru_cache(maxsize=1)
def get_provider() -> ChatProvider:
    """Return the process-wide model provider (TE_LLM_PROVIDER)."""
    if get_settings().llm_provider == "openai_compatible":
        return OpenAICompatibleProvider()
    return AnthropicProvider()


## --- Request/response models -------------------------------------------------------------
class MessageIn(BaseModel):
    """One chat message from the browser."""

    text: str = Field(default="", max_length=8000)  # bounded: guide §2.2
    # Answers to confirmation_required events: {tool_use_id: approved?}
    confirmations: dict[str, bool] = Field(default_factory=dict)
    # Answers to form_requested events: {tool_use_id: {question_id: answer}};
    # each is checked against the stored form (agent/forms.py).
    form_answers: dict[str, dict[str, Any]] = Field(
        default_factory=dict, max_length=MAX_FORMS_PER_MESSAGE
    )


class SessionOut(BaseModel):
    """A session as the chat page shows it."""

    session_id: str
    state: str
    spec_hash: str | None
    open_decisive_slots: list[str]
    messages: list[dict[str, Any]]
    # Forms still waiting for answers ({tool_use_id, form}), so the chat page
    # can show them again after a reload (forms extension, agent/forms.py).
    pending_forms: list[dict[str, Any]] = Field(default_factory=list)
    # The conversation as the person saw it (agent/transcript.py), and the
    # panel's content: the recorded answers and the latest verdicts.
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    slots: list[dict[str, Any]] = Field(default_factory=list)
    verdicts: list[dict[str, Any]] = Field(default_factory=list)


class ConversationOut(BaseModel):
    """One entry of the conversation list (the chat page's sidebar)."""

    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime


## --- Sessions ---------------------------------------------------------------------------
@router.post("/agent/sessions", dependencies=SameOrigin)
async def create_session(principal: CurrentUser) -> dict[str, str]:
    """Start a new design session owned by the logged-in user."""

    # Database access is synchronous (SQLAlchemy); run it in a worker
    # thread so the event loop keeps serving other users meanwhile.
    def _create() -> str:
        with session_scope() as db:
            return Repository(db, principal).create_session(
                protocol_version=PROTOCOL_VERSION, policy_version=POLICY.policy_version
            )

    return {"session_id": await anyio.to_thread.run_sync(_create)}


def _open_forms(pending: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the stored open forms, validated and complete (every default filled in).

    The browser renders exactly what it gets, so it is always the form as
    agent/forms.py defines it. A stored form that no longer validates (e.g.
    written by an older version) is left out: typing a message then settles
    it as not submitted.
    """
    out: list[dict[str, Any]] = []
    for f in pending.get("forms", []):
        try:
            form = AskUserInput.model_validate(f["form"])
        except (ValidationError, KeyError, TypeError):
            log.warning("stored form no longer valid", extra={"tool_use_id": f.get("tool_use_id")})
            continue
        out.append({"tool_use_id": f["tool_use_id"], "form": form.model_dump(mode="json")})
    return out


@router.get("/agent/sessions")
async def list_conversations(principal: CurrentUser) -> dict[str, list[ConversationOut]]:
    """List the logged-in user's conversations, most recent activity first."""

    def _list() -> list[ConversationOut]:
        with session_scope() as db:
            rows = Repository(db, principal).list_sessions()
        return [
            ConversationOut(
                session_id=r["id"],
                title=conversation_title(
                    [r["first_user_message"]] if r["first_user_message"] else []
                ),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    return {"conversations": await anyio.to_thread.run_sync(_list)}


@router.get("/agent/sessions/{session_id}")
async def get_session(session_id: str, principal: CurrentUser) -> SessionOut:
    """Return the session's state, spec hash, open decisive questions and transcript."""

    def _load() -> SessionOut:
        with session_scope() as db:
            repo = Repository(db, principal)  # filters by owner: someone else's id -> NotFound
            facts = repo.get_session_facts(session_id)
            ctx = CallContext(principal=principal, tool_id="", tool_input={}, session=facts)
            pending = repo.get_pending_tool_calls(session_id) or {}
            messages = repo.list_messages(session_id)
            verification = (
                repo.get_verification(facts.verification_ref) if facts.verification_ref else None
            )
            return SessionOut(
                session_id=session_id,
                state=compute_state(ctx, POLICY),
                spec_hash=facts.current_spec_hash,
                open_decisive_slots=facts.open_decisive_slots,
                messages=messages,
                pending_forms=_open_forms(pending),
                transcript=display_transcript(messages),
                slots=[
                    {k: a[k] for k in ("slot_id", "indices", "status", "value")}
                    for a in repo.get_answers(session_id)
                ],
                verdicts=(verification or {}).get("verdicts", []),
            )

    return await anyio.to_thread.run_sync(_load)


## --- One chat turn --------------------------------------------------------------------------
def _load_turn(
    principal: Principal, session_id: str
) -> tuple[list[dict[str, Any]], PendingCalls | None, int, str]:
    """Load history, pending calls, tokens used and a platform note (raises NotFound if not owned).

    The note (agent/notes.py) is non-empty when the designer saved the design
    in the form since the last message.

    Loading BEFORE the stream starts also proves the session belongs to this
    user before any model call is paid for.
    """
    with session_scope() as db:
        repo = Repository(db, principal)
        repo.get_session_facts(session_id)  # raises NotFound if not owned
        # Each stored "message" row holds the FULL provider message
        # ({"role": ..., "content": [...]}) exactly as sent/received.
        history = [
            m["content"]
            for m in repo.list_messages(session_id)
            if m["role"] in ("user", "assistant")
        ]
        pending_raw = repo.get_pending_tool_calls(session_id)
        pending = PendingCalls(**pending_raw) if pending_raw else None
        from_form = repo.spec_from_form_unseen(session_id)
        note = spec_from_form_note(from_form) if from_form else ""
        return history, pending, repo.tokens_used(session_id), note


def _facts_loader(principal: Principal, session_id: str) -> Callable[[], Awaitable[SessionFacts]]:
    """Return the loop's load_facts callback (reads the session facts in a thread)."""

    async def load_facts() -> SessionFacts:
        def _f() -> SessionFacts:
            with session_scope() as db:
                return Repository(db, principal).get_session_facts(session_id)

        return await anyio.to_thread.run_sync(_f)

    return load_facts


def _slots_loader(
    principal: Principal, session_id: str
) -> Callable[[], Awaitable[list[dict[str, Any]]]]:
    """Return the loop's load_slots callback: every answered slot, for the panel."""

    async def load_slots() -> list[dict[str, Any]]:
        def _a() -> list[dict[str, Any]]:
            with session_scope() as db:
                answers = Repository(db, principal).get_answers(session_id)
            return [
                {
                    "slot_id": a["slot_id"],
                    "indices": a["indices"],
                    "status": a["status"],
                    "value": a["value"],
                }
                for a in answers
            ]

        return await anyio.to_thread.run_sync(_a)

    return load_slots


def _persister(
    principal: Principal, session_id: str, stored: list[tuple[int, dict[str, Any]]] | None = None
) -> Persist:
    """Return the loop's persist callback (writes in a thread; kinds: see loop.py).

    `stored`, when given, collects (row id, message) of every chat message
    written in this turn, so a failed turn can be undone (_discard_unanswered).
    """

    async def persist(kind: str, payload: Any) -> None:
        def _p() -> None:
            with session_scope() as db:
                repo = Repository(db, principal)
                if kind == "message":
                    row_id = repo.append_message(session_id, payload["role"], payload, None)
                    if stored is not None:
                        stored.append((row_id, payload))
                elif kind == "usage":
                    repo.append_message(session_id, "usage", {}, payload)
                elif kind == "pending":
                    repo.set_pending_tool_calls(session_id, asdict(payload) if payload else None)

        await anyio.to_thread.run_sync(_p)

    return persist


def _discard_unanswered(
    principal: Principal, session_id: str, stored: list[tuple[int, dict[str, Any]]]
) -> bool:
    """Undo a failed turn whose only stored message is the user's text; True if done.

    Without this, every failed attempt would stay in the history, and the
    next successful turn would send the model all of them at once (the API
    joins consecutive user messages). Only a text-only message is removed:
    one that carries tool results answers an earlier tool call and must stay.
    """
    if len(stored) != 1:
        return False
    row_id, message = stored[0]
    content = message.get("content", [])
    if message.get("role") != "user" or any(b.get("type") != "text" for b in content):
        return False
    with session_scope() as db:
        Repository(db, principal).delete_message(session_id, row_id)
    return True


@router.post("/agent/sessions/{session_id}/messages", dependencies=SameOrigin)
async def post_message(
    session_id: str,
    body: MessageIn,
    principal: CurrentUser,
    provider: Annotated[ChatProvider, Depends(get_provider)],
) -> StreamingResponse:
    """Run one turn and stream its events as text/event-stream."""
    history, pending, used, note = await anyio.to_thread.run_sync(
        _load_turn, principal, session_id
    )
    if body.form_answers:
        # Checked against the forms WE stored, before any model call is paid for.
        open_forms = {
            f["tool_use_id"]: AskUserInput.model_validate(f["form"])
            for f in (pending.forms if pending else [])
        }
        try:
            validate_all(open_forms, body.form_answers)
        except FormAnswerError as exc:
            raise HTTPException(
                status_code=422, detail={"message": exc.message, "question_id": exc.question_id}
            ) from exc

    async def event_stream() -> AsyncIterator[str]:
        # One id for the whole turn: sent to the MCP server with every tool
        # call (mcp_bridge.py), so the turn can be followed through all logs.
        correlation_id = uuid4().hex
        stored: list[tuple[int, dict[str, Any]]] = []  # this turn's messages
        try:
            async with McpBridge(
                on_behalf_of=principal.id, correlation_id=correlation_id
            ) as bridge:
                loop = AgentLoop(
                    provider=provider,
                    policy=POLICY,
                    system_prompt=SYSTEM_PROMPT,
                    principal=principal,
                    session_id=session_id,
                    load_facts=_facts_loader(principal, session_id),
                    bridge=bridge,
                    persist=_persister(principal, session_id, stored),
                    tokens_used_so_far=used,
                    load_slots=_slots_loader(principal, session_id),
                )
                inp = TurnInput(body.text, body.confirmations, body.form_answers, note)
                async for event in loop.run_turn(inp, pending, history):
                    yield to_sse(event)
        except ProviderError as exc:
            # The model API failed (providers/anthropic.py): its message is
            # written for the user; the technical cause goes to the log.
            log.warning("model API failed", exc_info=True, extra={"correlation_id": correlation_id})
            discarded = await anyio.to_thread.run_sync(
                _discard_unanswered, principal, session_id, stored
            )
            yield to_sse(
                ErrorEvent(
                    message=exc.user_message,
                    correlation_id=correlation_id,
                    message_discarded=discarded,
                )
            )
        except Exception:
            # Never show internals to the browser: log the trace, send the ID.
            log.exception("agent turn failed", extra={"correlation_id": correlation_id})
            discarded = await anyio.to_thread.run_sync(
                _discard_unanswered, principal, session_id, stored
            )
            yield to_sse(
                ErrorEvent(
                    message="Something went wrong. Please try again.",
                    correlation_id=correlation_id,
                    message_discarded=discarded,
                )
            )

    # X-Accel-Buffering: no — tells proxies not to buffer the stream (Caddy
    # flushes event streams anyway; the header protects against other proxies).
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
