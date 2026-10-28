## =============================================================================
## te_platform/agent/loop.py — the agent loop: model ⇄ tools until an answer
## =============================================================================
## GUIDE STEP   8.4 (10.3: the report job's download link, commented twice)
## PURPOSE      Runs ONE turn of the conversation: the user said something;
##              the model answers, possibly asking for tools; the loop runs the
##              tools through MCP, gives the results back to the model, and
##              repeats until the model gives a final answer, a limit is
##              reached, or the user's confirmation is needed. While doing so
##              it yields events (events.py) that app.py streams to the browser.
##
##              One turn, step by step:
##                1. Build the user message: any tool results still owed to the
##                   model (from a confirmation round), then the user's text.
##                2. Work out the session state and offer the model ONLY the
##                   tools allowed in that state (registry/state.py).
##                3. Ask the model (provider.stream); forward its text.
##                4. If it asked for tools:
##                   - expensive tools (policy: ask_user_first) are NOT run:
##                     the turn pauses with a `confirmation_required` event;
##                   - all other tools run in parallel through MCP;
##                   - errors (e.g. precondition_failed with do_first) are sent
##                     back to the model as error results, so it can correct
##                     itself (D4).
##                5. Send ALL results back in ONE user message; go to 2.
##
## USED BY      agent/chat_api.py (one AgentLoop per POST /agent/sessions/{id}/messages).
## DEPENDS ON   providers/base.py (ChatProvider), mcp_bridge.py, events.py,
##              registry/state.py + registry/policy.py (tools per state, cost
##              classes), registry/context.py, config.py (limits).
##              It does NOT touch the database: app.py loads the history and
##              persists what the loop reports through the `persist` callback.
##              That keeps the loop testable with the fake provider alone.
## WHY          Architecture §3.4, D8 (our own loop: state-filtered tools,
##              identity injection, budgets, confirmation, streaming), D7
##              (suggested_next is in each tool result; the system prompt tells
##              the model to follow it).
## ACTIVATE     Uncomment with providers/fake.py; fake-provider tests must cover
##              every limit, the confirmation flow, and a precondition error
##              followed by the model correcting itself (guide 8.4).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Read the
## "HOW CONFIRMATION WORKS" note right below the SOLUTION marker first. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the names AgentLoop,
## PendingCalls, TurnInput and run_turn exactly: agent/chat_api.py and the tests
## use them. Activate providers/base.py, providers/fake.py, events.py and
## mcp_bridge.py first.
##
## Guide 8.4
## [ ] 1. Imports at the top (list in the SOLUTION). Two classes are called
##        TextDelta, so rename the UI one on import:
##          | from te_platform.agent.events import (...,
##          |     TextDelta as TextEvent, ...)
## [ ] 2. `@dataclass class PendingCalls`: ready_results and awaiting, both
##        lists of dicts with field(default_factory=list).
## [ ] 3. `@dataclass class TurnInput`: text: str, and confirmations:
##        dict[str, bool] (tool_use_id -> approved?), default empty.
## [ ] 4. The type alias `Persist = Callable[[str, Any], Awaitable[None]]`.
## [ ] 5. `@dataclass class _ModelReply` (private): what one model request
##        produced: calls (list of ToolCall), stop (Stop | None) and usage
##        (the Usage of THIS request, default Usage()).
## [ ] 6. `class AgentLoop` with an `__init__` taking ONLY keyword arguments
##        (provider, policy, system_prompt, principal, session_id,
##        load_facts, bridge, persist, tokens_used_so_far, and the optional
##        load_slots=None). Store them as self.p, self.policy, self.system,
##        self.principal, self.session_id, self.load_facts, self.mcp,
##        self.persist, self.tokens_used, self.load_slots, plus
##        self.s = get_settings().
## [ ] 7. Small helpers: `_needs_confirmation(tool_id) -> bool` (the tool's
##        cost class has ask_user_first; False for an unknown tool),
##        `async _allowed_tools()` (load the facts, build a CallContext,
##        compute_state, return `await self.mcp.tool_defs(tools_for_state(
##        state, self.policy))`) and `async _append(history, message)`
##        (append to history AND persist("message", message)).
## [ ] 8. `async _run_tool(call)`: copy the arguments, set
##          | args["session_id"] = self.session_id
##        (WE choose the session, never the model), call self.mcp.call, and
##        return (self.p.tool_result(id, outcome["text"], is_error=not ok),
##        outcome).
## [ ] 9. `async _ui_events_for(outcome) -> list[AgentEvent]`: nothing for a
##        failed outcome; SpecUpdated for elicit.record_answer.v1 (slots from
##        `await self.load_slots()` when given), VerdictUpdated for
##        verify.run.v1, JobProgress for sim.monte_carlo.v1,
##        sim.trajectory.v1 and jobs.status.v1 when the result has a job_id.
## [ ] 10. `async _run_calls(calls, results)`, an async generator: yield
##        ToolStarted for every call, run them all in parallel, storing the
##        results by index so their order matches the model's calls:
##          | async with anyio.create_task_group() as tg:
##          |     for i, c in enumerate(calls):
##          |         tg.start_soon(_one, i, c)
##        then yield ToolFinished and the UI events per call, and append the
##        result blocks to `results`. EVERY tool run goes through here, so
##        the browser always sees started/finished, also for calls the user
##        approved in a confirmation round.
## [ ] 11. `async _settle_pending(pending, confirmations, owed)`, an async
##        generator: owed += ready_results; the approved awaiting calls run
##        through _run_calls; declined ones become error results ("The user
##        declined to run this tool."); then persist("pending", None).
## [ ] 12. `async _ask_model(history, reply)`, an async generator: stream
##        from self.p with tools=await self._allowed_tools(); yield TextEvent
##        for text, collect ToolCalls into reply.calls, keep the Usage and
##        the Stop in reply.
## [ ] 13. Two more helpers: `_account(reply, turn_usage) -> dict` adds the
##        request's Usage to turn_usage and self.tokens_used and returns THIS
##        request's counts alone; `async _pause(results, to_confirm)`, an
##        async generator, persists a PendingCalls and yields one
##        ConfirmationRequired per call (the question uses the cost class's
##        `typical`).
## [ ] 14. The turn, in two methods (one long method would be hard to read;
##        ruff's complexity rule C901 says the same):
##        a) `@dataclass class _Turn`: usage (the three token counters at
##           0), tool_calls = 0, done: Done | None = None; and
##           `_END_REASONS = {"end_turn": "final_answer", "refusal":
##           "refusal"}` (any other stop ends with "limit_reached");
##        b) `async _step(history, turn)`, an async generator for ONE model
##           request: _ask_model (no Stop -> RuntimeError); _append
##           stop.assistant_message UNCHANGED; persist("usage",
##           self._account(...)): THIS request's counts only (the database
##           sums the rows: a running total would count twice). No tool use
##           -> turn.done = Done(_END_REASONS...). Over
##           agent_max_tool_calls_per_turn -> answer every call with an
##           error result in one user message, turn.done = limit_reached.
##           Else run the calls that need no confirmation (_run_calls);
##           if some need it -> _pause, turn.done = awaiting_confirmation;
##           else send ALL results in ONE user message;
##        c) `async def run_turn(self, inp, pending, history)`: settle
##           `pending`; ONE user message with the owed results and inp.text;
##           deadline = anyio.current_time() + agent_max_seconds_per_turn
##           (the SOLUTION comment explains why not move_on_after); then
##           `while True:` yield Done("limit_reached") and return when the
##           session token budget or the deadline is passed; yield the
##           events of _step; when turn.done is set, yield it and return.
## [ ] 15. Check: activate the guide 8.4 tests of
##        tests/platform_tests/test_platform_agent.py (every limit, the
##        confirmation flow, precondition self-correction, one user message,
##        session id injection; they run the real MCP server over HTTP and
##        need the database and Redis), then
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##          | uv run mypy te_platform
##
## Guide 10.3 (later: the "# # " lines in the SOLUTION)
## [ ] 16. In _ui_events_for, toggle the report.render_pdf.v1 branch: a
##        JobProgress with the job id, status and download_url (needs
##        JobProgress.download_url in events.py).
##
## Forms extension (structured questions; agent/forms.py, not in the guide yet)
## [ ] 17. PendingCalls gets `forms` (list of {tool_use_id, form}) and
##        TurnInput `form_answers` (tool_use_id -> the browser's answers),
##        both empty by default, so stored pending rows stay readable.
## [ ] 18. _allowed_tools appends ASK_USER_TOOL LAST (a stable tool order
##        keeps the prompt cache).
## [ ] 19. In _step, ask_user calls are set apart: parse_form() each; an
##        invalid form becomes an error result at once (the model fixes it
##        in the same turn); valid forms pause the turn like confirmations
##        (_pause persists them and yields FormRequested), and the turn ends
##        with "awaiting_input" (when a confirmation is also open, the
##        confirmation reason wins: both are shown).
## [ ] 20. In _settle_pending, each pending form becomes ONE tool result:
##        answers_result(validate_answers(form, answers)) when answered,
##        else skipped_result() (the designer typed instead).
## [ ] 21. Check: the forms tests of test_platform_agent.py.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## HOW CONFIRMATION WORKS ACROSS TURNS (read before activating)
## The API requires that every tool_use in an assistant message is answered by
## a tool_result in the NEXT user message. When the model asks for an
## expensive tool, we therefore:
##   a) run the non-expensive calls of the same message right away;
##   b) store their results plus the list of calls awaiting approval as the
##      session's "pending tool calls" (persist callback, kind="pending");
##   c) end the turn with `confirmation_required` + `done(awaiting_confirmation)`.
## The browser shows Yes/No. The next POST carries `confirmations`
## {tool_use_id: true/false}. The new turn starts by running the approved
## calls, turning declined ones into error results ("The user declined…"),
## and sends ALL owed results, followed by any new user text, in one message.
## Forms (tool ask_user, agent/forms.py) use the same pause: the form is
## stored with the pending calls, the browser shows it (`form_requested`),
## the next POST carries `form_answers`, and the new turn turns them into the
## ask_user call's tool result (or a "not submitted" result when the designer
## typed a message instead).

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import anyio

from te_platform.agent.events import (
    AgentEvent,
    ConfirmationRequired,
    Done,
    FormRequested,
    JobProgress,
    SpecUpdated,
    ToolFinished,
    ToolStarted,
    VerdictUpdated,
)
from te_platform.agent.events import TextDelta as TextEvent
from te_platform.agent.forms import (
    ASK_USER,
    ASK_USER_TOOL,
    AskUserInput,
    FormError,
    answers_result,
    parse_form,
    skipped_result,
    validate_answers,
)
from te_platform.agent.mcp_bridge import McpBridge, from_provider_name
from te_platform.agent.providers.base import ChatProvider, Stop, TextDelta, ToolCall, Usage
from te_platform.config import get_settings
from te_platform.registry.context import CallContext, Principal, SessionFacts
from te_platform.registry.policy import Policy
from te_platform.registry.state import compute_state, tools_for_state


@dataclass
class PendingCalls:
    """Tool results owed to the model, saved between turns (see note above)."""

    ready_results: list[dict[str, Any]] = field(default_factory=list)  # tool_result blocks
    # The calls waiting for the user's yes: {tool_use_id, name, arguments}.
    awaiting: list[dict[str, Any]] = field(default_factory=list)
    # The forms waiting for answers: {tool_use_id, form} (agent/forms.py).
    forms: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TurnInput:
    """What the user sent: text, answers to confirmations, answers to forms."""

    text: str
    confirmations: dict[str, bool] = field(default_factory=dict)  # tool_use_id -> approved?
    # tool_use_id -> {question_id: answer}, checked against the stored form.
    form_answers: dict[str, Any] = field(default_factory=dict)


## persist(kind, payload): app.py stores it. kinds: "message" (a provider
## message to append to the history), "usage" (the token counts of ONE model
## request; the database sums them), "pending" (PendingCalls or None).
Persist = Callable[[str, Any], Awaitable[None]]


@dataclass
class _ModelReply:
    """What one model request produced (filled by AgentLoop._ask_model)."""

    calls: list[ToolCall] = field(default_factory=list)
    stop: Stop | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass
class _Turn:
    """The running state of one turn (shared by run_turn and _step)."""

    usage: dict[str, int] = field(
        default_factory=lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    )
    tool_calls: int = 0
    done: Done | None = None  # set when the turn ends


## How a model stop without tool calls ends the turn (any other: limit_reached).
_END_REASONS: dict[str, Literal["final_answer", "refusal"]] = {
    "end_turn": "final_answer",
    "refusal": "refusal",
}


class AgentLoop:
    """Runs one conversation turn: model, tools, model, ... until an answer or a limit."""

    # The dependencies are passed explicitly, keyword-only, so tests can build
    # the loop with the fake provider and no web framework.
    def __init__(  # noqa: PLR0913  explicit deps
        self,
        *,
        provider: ChatProvider,
        policy: Policy,
        system_prompt: str,
        principal: Principal,
        session_id: str,
        load_facts: Callable[[], Awaitable[SessionFacts]],
        bridge: McpBridge,
        persist: Persist,
        tokens_used_so_far: int,
        load_slots: Callable[[], Awaitable[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self.p = provider
        self.policy = policy
        # Fixed text: never add per-request data to it (that breaks the prompt cache).
        self.system = system_prompt
        self.principal = principal
        self.session_id = session_id
        self.load_facts = load_facts  # re-read before every model request
        self.mcp = bridge
        self.persist = persist
        self.tokens_used = tokens_used_so_far
        # The session's answered slots for the spec panel (app: from the
        # database); None: spec_updated events carry no slot list.
        self.load_slots = load_slots
        self.s = get_settings()

    # --- helpers -----------------------------------------------------------------
    def _needs_confirmation(self, tool_id: str) -> bool:
        tp = self.policy.tools.get(tool_id)
        return bool(tp and self.policy.cost_classes[tp.cost].ask_user_first)

    async def _allowed_tools(self) -> list[Any]:
        facts = await self.load_facts()
        ctx = CallContext(principal=self.principal, tool_id="", tool_input={}, session=facts)
        state = compute_state(ctx, self.policy)
        # NOTE: the tool list is the first part of the prompt. It changes only
        # when the session state changes (a handful of times per interview),
        # so the prompt cache is invalidated rarely. Do not reorder tools.
        mcp_tools = await self.mcp.tool_defs(tools_for_state(state, self.policy))
        # ask_user (agent/forms.py) runs here, in the agent, in every state;
        # always LAST, so the order of the MCP tools never shifts.
        return [*mcp_tools, ASK_USER_TOOL]

    async def _append(self, history: list[dict[str, Any]], message: dict[str, Any]) -> None:
        history.append(message)
        await self.persist("message", message)

    async def _run_tool(self, call: ToolCall) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run one call; return (provider tool_result block, bridge outcome)."""
        args = dict(call.arguments)
        # Identity injection: the session is decided by US, never by the
        # model, so a confused (or manipulated) model cannot touch another
        # session. The MCP side checks ownership again (defence in depth).
        args["session_id"] = self.session_id
        outcome = await self.mcp.call(call.name, args)
        block = self.p.tool_result(call.tool_use_id, outcome["text"], is_error=not outcome["ok"])
        return block, outcome

    async def _ui_events_for(self, outcome: dict[str, Any]) -> list[AgentEvent]:
        """Panel updates derived from successful tool results."""
        if not outcome["ok"]:
            return []
        r = outcome["payload"].get("result", {})
        tool = outcome["tool"]
        if tool == "elicit.record_answer.v1":
            slots = await self.load_slots() if self.load_slots else []
            return [
                SpecUpdated(
                    spec_hash=r.get("spec_hash") or "", state=r.get("state", ""), slots=slots
                )
            ]
        ## Guide 10.3: a report job: its status. The signed download link
        ## arrives only with report.publish.v1, after the agent's review.
        if tool in ("report.render_pdf.v1", "report.publish.v1"):
            return [
                JobProgress(
                    job_id=r["job_id"],
                    # A rendered report is a draft; a published one is finished.
                    status=r.get("status", "finished"),
                    download_url=r.get("download_url"),  # only report.publish.v1 has one
                    kind="report",
                )
            ]
        if tool == "verify.run.v1":
            return [VerdictUpdated(verification_ref=r["verification_ref"], verdicts=r["verdicts"])]
        job_tools = (
            "sim.monte_carlo.v1",
            "sim.trajectory.v1",
            "sim.experiment.v1",
            "jobs.status.v1",
        )
        if tool in job_tools and "job_id" in r:
            kinds = {
                "sim.monte_carlo.v1": "monte_carlo",
                "sim.trajectory.v1": "trajectory",
                "sim.experiment.v1": "experiment",
            }
            return [
                JobProgress(
                    job_id=r["job_id"],
                    status=r.get("status", "queued"),
                    progress=r.get("progress"),
                    kind=r.get("kind") or kinds.get(tool),
                )
            ]
        return []

    async def _run_calls(
        self, calls: list[ToolCall], results: list[dict[str, Any]]
    ) -> AsyncIterator[AgentEvent]:
        """Run calls in PARALLEL through MCP; append their result blocks to `results`.

        Every tool run goes through here, so the browser sees tool_started /
        tool_finished for each one (also for calls approved in a confirmation
        round). A task group starts the calls together and waits until every
        one has finished; results are stored by index so their order matches
        the model's calls.
        """
        blocks: list[dict[str, Any] | None] = [None] * len(calls)
        outcomes: list[dict[str, Any] | None] = [None] * len(calls)
        for c in calls:
            yield ToolStarted(tool_use_id=c.tool_use_id, tool=from_provider_name(c.name))

        async def _one(i: int, c: ToolCall) -> None:
            blocks[i], outcomes[i] = await self._run_tool(c)

        async with anyio.create_task_group() as tg:
            for i, c in enumerate(calls):
                tg.start_soon(_one, i, c)

        for c, block, o in zip(calls, blocks, outcomes, strict=True):
            if block is None or o is None:  # cannot happen: every task has finished
                raise RuntimeError("a tool call produced no result")
            error = o["payload"].get("error") or {}
            yield ToolFinished(
                tool_use_id=c.tool_use_id, tool=o["tool"], ok=o["ok"], error_code=error.get("error")
            )
            for ev in await self._ui_events_for(o):
                yield ev
            results.append(block)

    async def _settle_pending(
        self, pending: PendingCalls, inp: TurnInput, owed: list[dict[str, Any]]
    ) -> AsyncIterator[AgentEvent]:
        """Turn the calls paused in the previous turn into results (see note above)."""
        owed += pending.ready_results
        for f in pending.forms:
            # agent/chat_api.py already rejected invalid answers with 422;
            # checking again here keeps the loop safe on its own.
            answers = inp.form_answers.get(f["tool_use_id"])
            text = (
                answers_result(validate_answers(AskUserInput.model_validate(f["form"]), answers))
                if answers is not None
                else skipped_result()
            )
            owed.append(self.p.tool_result(f["tool_use_id"], text, is_error=False))
        approved: list[ToolCall] = []
        for waiting in pending.awaiting:
            call = ToolCall(waiting["tool_use_id"], waiting["name"], waiting["arguments"])
            if inp.confirmations.get(call.tool_use_id):
                approved.append(call)
            else:
                owed.append(
                    self.p.tool_result(
                        call.tool_use_id, "The user declined to run this tool.", is_error=True
                    )
                )
        async for ev in self._run_calls(approved, owed):
            yield ev
        await self.persist("pending", None)

    def _forms_of(
        self, calls: list[ToolCall], results: list[dict[str, Any]]
    ) -> list[tuple[str, AskUserInput]]:
        """Return the valid ask_user forms; an invalid one gets an error result at once."""
        forms: list[tuple[str, AskUserInput]] = []
        for c in calls:
            if c.name != ASK_USER:
                continue
            try:
                forms.append((c.tool_use_id, parse_form(c.arguments)))
            except FormError as exc:
                results.append(self.p.tool_result(c.tool_use_id, str(exc), is_error=True))
        return forms

    async def _ask_model(
        self, history: list[dict[str, Any]], reply: _ModelReply
    ) -> AsyncIterator[AgentEvent]:
        """Send one request with the tools of the current state; forward its text."""
        # `pev` = PROVIDER event (providers/base.py), not to be confused
        # with the agent's own UI events (events.py) yielded to the browser.
        async for pev in self.p.stream(
            system=self.system, messages=history, tools=await self._allowed_tools()
        ):
            if isinstance(pev, TextDelta):
                yield TextEvent(text=pev.text)
            elif isinstance(pev, ToolCall):
                reply.calls.append(pev)
            elif isinstance(pev, Usage):
                reply.usage = pev
            else:
                reply.stop = pev

    def _account(self, reply: _ModelReply, turn_usage: dict[str, int]) -> dict[str, int]:
        """Add this request's usage to the turn and session totals; return it alone."""
        u = reply.usage
        turn_usage["input_tokens"] += u.input_tokens
        turn_usage["output_tokens"] += u.output_tokens
        turn_usage["cache_read_input_tokens"] += u.cache_read_input_tokens
        self.tokens_used += u.input_tokens + u.output_tokens
        return {
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cache_read_input_tokens": u.cache_read_input_tokens,
        }

    async def _pause(
        self,
        results: list[dict[str, Any]],
        to_confirm: list[ToolCall],
        forms: list[tuple[str, AskUserInput]],
    ) -> AsyncIterator[AgentEvent]:
        """Save what we have; ask about expensive calls and show the forms (note at top)."""
        await self.persist(
            "pending",
            PendingCalls(
                ready_results=results,
                awaiting=[
                    {"tool_use_id": c.tool_use_id, "name": c.name, "arguments": c.arguments}
                    for c in to_confirm
                ],
                forms=[
                    {"tool_use_id": tid, "form": form.model_dump(mode="json")}
                    for tid, form in forms
                ],
            ),
        )
        for tid, form in forms:
            yield FormRequested(tool_use_id=tid, form=form.model_dump(mode="json"))
        for c in to_confirm:
            tool_id = from_provider_name(c.name)
            typical = self.policy.cost_classes[self.policy.tools[tool_id].cost].typical
            yield ConfirmationRequired(
                tool_use_id=c.tool_use_id,
                tool=tool_id,
                question=f"This step ({tool_id}) usually takes {typical}. Run it?",
            )

    # --- the turn ------------------------------------------------------------------
    async def run_turn(
        self, inp: TurnInput, pending: PendingCalls | None, history: list[dict[str, Any]]
    ) -> AsyncIterator[AgentEvent]:
        """Run one turn and yield its events; the last one is always a Done."""
        turn = _Turn()
        # Step 1: settle pending calls from the previous turn, if any; then
        # ONE user message with the owed results and the user's text.
        owed: list[dict[str, Any]] = []
        if pending:
            async for ev in self._settle_pending(pending, inp, owed):
                yield ev
        await self._append(history, self.p.user_message(inp.text, owed))

        # The whole turn has a wall-clock limit. We check a DEADLINE between
        # steps instead of wrapping the body in anyio.move_on_after: this
        # function is an async generator (it yields events), and yielding
        # from inside a cancel scope is fragile in async generators. The
        # cost: one model request or tool call already running is allowed
        # to finish (each has its own timeout: the SDK's and the pipeline's).
        deadline = anyio.current_time() + self.s.agent_max_seconds_per_turn
        while True:
            if (
                self.tokens_used >= self.s.agent_session_token_budget
                or anyio.current_time() > deadline
            ):
                yield Done(reason="limit_reached", usage=turn.usage)
                return
            async for ev in self._step(history, turn):
                yield ev
            if turn.done is not None:
                yield turn.done
                return

    async def _step(
        self,
        history: list[dict[str, Any]],
        turn: _Turn,
    ) -> AsyncIterator[AgentEvent]:
        """One model request and its tool calls; sets turn.done when the turn ends."""
        # Steps 2-3: ask the model with the tools of the current state.
        reply = _ModelReply()
        async for ev in self._ask_model(history, reply):
            yield ev
        stop = reply.stop
        if stop is None:
            raise RuntimeError("the provider must end every request with a Stop event")
        # Append the assistant message EXACTLY as returned (thinking blocks
        # included); never edit it later.
        await self._append(history, stop.assistant_message)
        # THIS request's counts only: Repository.tokens_used sums the rows.
        await self.persist("usage", self._account(reply, turn.usage))
        if stop.reason != "tool_use" or not reply.calls:
            # end_turn is the final answer; refusal, max_tokens or other also end it.
            turn.done = Done(
                reason=_END_REASONS.get(stop.reason, "limit_reached"), usage=turn.usage
            )
            return

        # Step 4: tool calls.
        turn.tool_calls += len(reply.calls)
        if turn.tool_calls > self.s.agent_max_tool_calls_per_turn:
            # Still answer every tool_use (API rule), but with an error.
            refusals = [
                self.p.tool_result(c.tool_use_id, "Tool-call limit for this turn.", is_error=True)
                for c in reply.calls
            ]
            await self._append(history, self.p.user_message("", refusals))
            turn.done = Done(reason="limit_reached", usage=turn.usage)
            return
        results: list[dict[str, Any]] = []
        forms = self._forms_of(reply.calls, results)
        mcp_calls = [c for c in reply.calls if c.name != ASK_USER]
        to_confirm = [c for c in mcp_calls if self._needs_confirmation(from_provider_name(c.name))]
        async for ev in self._run_calls([c for c in mcp_calls if c not in to_confirm], results):
            yield ev
        if to_confirm or forms:
            async for ev in self._pause(results, to_confirm, forms):
                yield ev
            reason = "awaiting_confirmation" if to_confirm else "awaiting_input"
            turn.done = Done(reason=reason, usage=turn.usage)
            return
        # Step 5: ALL results in ONE user message; the caller loops.
        await self._append(history, self.p.user_message("", results))
