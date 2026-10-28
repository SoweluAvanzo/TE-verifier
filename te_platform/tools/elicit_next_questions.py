## =============================================================================
## te_platform/tools/elicit_next_questions.py — tool `elicit.next_questions.v1`
## =============================================================================
## GUIDE STEP   7.5
## PURPOSE      Tells the interviewing agent what to ask next: the 1-3 open
##              protocol slots whose answers could most change a failure-mode
##              verdict, plus a `complete` flag that says the interview can
##              stop. The ranking itself lives in elicitation/ranking.py; this
##              module only loads the session's data and calls it.
## USED BY      registry/loader.py (entry point "elicit.next_questions.v1"),
##              pipeline.py. Called by the interviewing MODEL through MCP (our
##              agent, whose loop executes the calls, or any external MCP
##              client following the interview_token_economy prompt): at the
##              start of a session and after every recorded answer. Suggested
##              by the policy after elicit.record_answer.v1 while elicitation
##              is incomplete, and after verify.run.v1 when an inconclusive
##              verdict depends on an unknown input.
## DEPENDS ON   te_platform.elicitation.ranking (next_questions, NextQuestions),
##              te_platform.elicitation.protocol (current_protocol),
##              te_platform.db.repo.Repository (create_session,
##              get_session_facts, get_answers), te_platform.db.session,
##              te_platform.registry.policy (policy version for new sessions),
##              te_platform.config (policy_dir).
## RULES        policy -> elicit.next_questions.v1: no preconditions, cost
##              "cheap", offered in states eliciting and spec_ready.
## STARTING     Without session_id the tool STARTS a new session for the
##              caller and returns its session_id; reuse it in every later
##              call (elicit.record_answer.v1 requires it). This is how
##              external MCP clients begin an interview: no other endpoint is
##              needed (architecture D16, every client interviews the same way).
## WHY          Architecture §4.3: the verifier chooses the next question, so
##              interviews stay short for each specific design; the stopping
##              rule ("nothing still unknown can change a verdict") is
##              computed, not guessed by the model.
## ACTIVATE     Uncomment with guide 7.5; ranking tests in
##              test_platform_elicitation.py (a decisive slot removed from a
##              case study is ranked first; complete spec -> complete=true);
##              the tool itself in test_platform_tools.py ("Guide 7.5").
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Every tool module has the
## same four sections (tools/__init__.py; verify_run.py is the template).
## Keep `TOOL`, the tool id and the model field names exactly as written
## here: te_platform/README.md (contracts table) and the policy rely on them.
##
## Guide 7.5 (activate elicitation/ranking.py and db/ first)
## [ ] 1. Imports at the top: `Any` (typing), `anyio`, `BaseModel`,
##        `Field`, then from te_platform: `get_settings`, `Repository`,
##        `session_scope`,
##        `current_protocol` (elicitation.protocol), `NextQuestions` and
##        `next_questions` (elicitation.ranking), `CallContext`,
##        `load_policy`, `ToolSpec`.
## [ ] 2. `NextQuestionsInput(BaseModel)`: `session_id: str | None`
##        (default None; omitting it STARTS a session, see the header) and
##        `max_questions: int` (default 3, ge=1, le=3; short-interview
##        extension: default 6, le=6, the "ask" questions fit one form).
## [ ] 3. `NextQuestionsOutput(NextQuestions)`: a SUBCLASS of the ranking
##        result that only adds `session_id: str`, so the output carries
##        questions, complete, open_decisive_slots, not_needed and
##        ranking_basis without re-declaring them. One-line docstrings on
##        both classes and on handle (ruff D1).
## [ ] 4. A sync helper `_load(ctx, session_id) -> tuple[str,
##        dict[str, Any], list[dict[str, Any]]]`; inside
##        `with session_scope() as db:` use Repository(db, ctx.principal).
##        No session_id: create one with
##          | repo.create_session(protocol_version=current_protocol().version,
##          |                     policy_version=policy_version)
##        (policy_version from load_policy(get_settings().policy_dir /
##        "tool_policy.yaml")) and return (new id, {}, []). Otherwise return
##        (session_id, facts.current_spec or {}, repo.get_answers(...)).
## [ ] 5. `async def handle(inp, ctx) -> NextQuestionsOutput`: run _load in a
##        thread, take `protocol = current_protocol()`, run
##        next_questions(protocol, spec, answers,
##        max_questions=inp.max_questions) in a thread (it runs the minimal
##        verifier), and return
##          | NextQuestionsOutput(**result.model_dump(), session_id=session_id)
## [ ] 6. `TOOL = ToolSpec(id="elicit.next_questions.v1", title="Next
##        interview questions", ...)` with the two models and handle.
## [ ] 7. Remove "elicit.next_questions.v1" from `planned:` in
##        policy/tool_policy.yaml.
## [ ] 8. Check: activate the 7.5 ranking tests in
##        tests/platform_tests/test_platform_elicitation.py and the
##        "Guide 7.5" part of test_platform_tools.py (a call without
##        session_id starts a session; the session can be continued), then
##          | uv run pytest tests/platform_tests/test_platform_elicitation.py -q
##          | uv run pytest tests/platform_tests/test_platform_tools.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from typing import Any

import anyio
from pydantic import BaseModel, Field

from te_platform.config import get_settings
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.elicitation.protocol import current_protocol
from te_platform.elicitation.ranking import NextQuestions, next_questions
from te_platform.registry.context import CallContext
from te_platform.registry.policy import load_policy
from te_platform.registry.spec import ToolSpec


class NextQuestionsInput(BaseModel):
    """What a caller sends to elicit.next_questions.v1."""

    session_id: str | None = Field(
        default=None,
        description="The design session being interviewed. Omit it to START a new session; "
        "the output then contains the new session_id, to pass in every later call.",
    )
    # Short interview: the few "ask" questions go in one form, so up to 6.
    max_questions: int = Field(
        default=6,
        ge=1,
        le=6,
        description="Return at most this many questions to ask (one form holds them all).",
    )


## The output is the ranking result (elicitation/ranking.py NextQuestions:
## questions[...], complete, open_decisive_slots, not_needed, ranking_basis)
## plus the session_id, so a newly started session can be continued.
class NextQuestionsOutput(NextQuestions):
    """The ranked questions, plus the session they belong to."""

    session_id: str


def _load(
    ctx: CallContext, session_id: str | None
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Return (session_id, current spec, answers) from the database.

    Synchronous, so the handler runs it in a thread. Creates the session
    first when none was given (see STARTING in the header).
    """
    with session_scope() as db:
        repo = Repository(db, ctx.principal)  # ownership is checked inside
        if session_id is None:
            # Read only when a session starts (rare), so the policy file is
            # not cached here; the protocol is (current_protocol()).
            policy = load_policy(get_settings().policy_dir / "tool_policy.yaml")
            session_id = repo.create_session(
                protocol_version=current_protocol().version, policy_version=policy.policy_version
            )
            return session_id, {}, []
        facts = repo.get_session_facts(session_id)
        return session_id, facts.current_spec or {}, repo.get_answers(session_id)


async def handle(inp: NextQuestionsInput, ctx: CallContext) -> NextQuestionsOutput:
    """Rank the open questions of the session (starting one if needed)."""
    session_id, spec, answers = await anyio.to_thread.run_sync(lambda: _load(ctx, inp.session_id))
    # The protocol is loaded once per process and shared (protocol.current_protocol).
    protocol = current_protocol()
    # Ranking runs the minimal verifier on the partial spec: CPU work -> thread.
    result = await anyio.to_thread.run_sync(
        lambda: next_questions(protocol, spec, answers, max_questions=inp.max_questions)
    )
    return NextQuestionsOutput(**result.model_dump(), session_id=session_id)


TOOL = ToolSpec(
    id="elicit.next_questions.v1",
    title="Next interview questions",
    input_model=NextQuestionsInput,
    output_model=NextQuestionsOutput,
    handler=handle,
)
