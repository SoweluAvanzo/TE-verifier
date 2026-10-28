## =============================================================================
## te_platform/tools/elicit_record_answer.py — tool `elicit.record_answer.v1`
## =============================================================================
## GUIDE STEP   7.4
## PURPOSE      Records the user's answer to ONE protocol slot: the value, its
##              status (committed / unknown / default) and the user's own
##              words as provenance. Applying the answer creates a NEW spec
##              version (spec versions are append-only, architecture §3.8);
##              the result returns the new version, its hash, any coherence
##              issues and the session's new state.
## USED BY      registry/loader.py (entry point "elicit.record_answer.v1"),
##              pipeline.py; called by the model through MCP after the user
##              confirmed a restatement of their answer. (Edits made in the
##              web form do NOT use this tool: they arrive as whole spec
##              versions through agent/spec_api.py POST /agent/sessions/{id}/spec,
##              guide 9.3.)
##              Its result drives predicates.py: `elicitation_complete` ->
##              suggest verify.run.v1; `elicitation_incomplete` -> suggest
##              elicit.next_questions.v1.
## DEPENDS ON   te_platform.elicitation.protocol (current_protocol),
##              te_platform.elicitation.answers (apply_answer),
##              te_platform.service.validate, te_platform.db.repo.Repository,
##              te_platform.db.session.session_scope, te_platform.registry.state
##              (compute_state) and registry/policy.py (load_policy, Policy);
##              functools.lru_cache (the policy is read once per process).
## RULES        policy -> elicit.record_answer.v1: no preconditions; cost
##              "trivial"; side_effects creates_spec_version. do_not_use_when:
##              the user did not actually state the value (the model must
##              never invent answers, architecture P4) or it is ambiguous.
## WHY          The user's quote is stored next to every value, so every
##              number in a spec can be traced back to what the user said
##              (architecture P5, provenance).
## ACTIVATE     Uncomment with guide 7.4; tests: each call adds exactly one
##              spec version and an unknown slot_id -> validation_error
##              ("Guide 7.4" part of test_platform_tools.py); an "unknown"
##              answer becomes a swept range (test_platform_elicitation.py,
##              test_unknown_becomes_swept_range, tests apply_answer).
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
## Guide 7.4 (activate elicitation/protocol.py and answers.py, db/ and
## registry/state.py first)
## [ ] 1. Imports at the top: `lru_cache`, `Any` and `Literal`, `anyio`,
##        `BaseModel`, `Field`, then from te_platform: `service`,
##        `get_settings`, `Repository`, `session_scope`, `apply_answer`,
##        `current_protocol` (elicitation.protocol), `InvalidInput`,
##        `CallContext`, `Policy` and `load_policy`, `ToolSpec`,
##        `compute_state` (see the SOLUTION for each module path).
## [ ] 2. `RecordAnswerInput(BaseModel)`: `session_id: str`, `slot_id: str`,
##        `value: Any | None` (default None), a required `status`
##          | status: Literal["committed", "unknown", "default"] = Field(
##        `indices: list[int]` (default_factory=list) and `user_quote: str`
##        (min_length=1, max_length=2000). Copy the descriptions: the model
##        reads them to know what to pass. One-line docstrings on every
##        class and public function (ruff D1).
## [ ] 3. `RecordAnswerOutput(BaseModel)`: `spec_version: int`,
##        `spec_hash: str | None`, `coherence_issues` (list[dict[str, Any]],
##        default empty) and `state: str` (the policy's `returns`).
## [ ] 4. A cached reader of the policy, read once per process (the "##"
##        note in the SOLUTION says why):
##          | @lru_cache(maxsize=1)
##          | def _policy() -> Policy:
##          |     return load_policy(get_settings().policy_dir
##          |                        / "tool_policy.yaml")
## [ ] 5. A sync helper `_record(ctx, inp) -> RecordAnswerOutput`. Start
##        with the slot checks, before touching the database:
##        `slot = current_protocol().slot(inp.slot_id)` (the protocol,
##        cached by elicitation/protocol.py), and raise InvalidInput
##        when the slot is unknown, when status is "unknown" but not
##        slot.allow_unknown, or when status is "default" but slot.default
##        is None.
## [ ] 6. Then ONE `with session_scope() as db:` block (one transaction):
##        Repository(db, ctx.principal); repo.lock_session(inp.session_id)
##        FIRST (parallel answers then apply one after the other, see
##        db/repo.py); get_session_facts; apply_answer on
##        `facts.current_spec or {}` with indices=tuple(inp.indices);
##        service.validate(new_spec); add_spec_version(..., v.spec_hash or
##        "", author="agent"); record_answer(..., version,
##        indices=list(inp.indices)); finally re-read get_session_facts.
## [ ] 7. After the block: derive the state from the refreshed facts
##          | state = compute_state(
##          |     ctx.model_copy(update={"session": new_state}), _policy())
##        then return the output (spec_hash=v.spec_hash, may be None).
## [ ] 8. `async def handle(inp, ctx)`: raise InvalidInput when ctx.session
##        is None, else `return await anyio.to_thread.run_sync(lambda:
##        _record(ctx, inp))`.
## [ ] 9. `TOOL = ToolSpec(id="elicit.record_answer.v1", title="Record an
##        interview answer", ...)` with the two models and handle.
## [ ] 10. Remove "elicit.record_answer.v1" from `planned:` in
##         policy/tool_policy.yaml.
## [ ] 10b. (Extension, short interview) status "estimated": the agent's
##        estimate, shown pre-filled in a form and kept unchanged by the
##        designer. Written into the spec like "committed"; the stored status
##        keeps the provenance (elicitation/answers.py).
## [ ] 11. Check: activate the "Guide 7.4" part of
##         tests/platform_tests/test_platform_tools.py (one spec version
##         per call, unknown slot_id -> validation_error), then
##          | uv run pytest tests/platform_tests/test_platform_tools.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from functools import lru_cache
from typing import Any, Literal

import anyio
from pydantic import BaseModel, Field

from te_platform import service
from te_platform.config import get_settings
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.elicitation.answers import apply_answer
from te_platform.elicitation.protocol import current_protocol
from te_platform.errors import InvalidInput
from te_platform.registry.context import CallContext
from te_platform.registry.policy import Policy, load_policy
from te_platform.registry.spec import ToolSpec
from te_platform.registry.state import compute_state


class RecordAnswerInput(BaseModel):
    """What a caller sends to elicit.record_answer.v1: one answer to one slot."""

    session_id: str = Field(description="The design session.")
    slot_id: str = Field(
        description="The protocol slot being answered (from elicit.next_questions.v1)."
    )
    # The value's JSON shape depends on the slot's answer_type: a string (or
    # list of strings) for enum, a number, {"min": .., "max": ..} for range,
    # a string for text, one value per item for list (e.g. token names), the
    # schema's JSON shape for table and dsl_expression (the rule list).
    # apply_answer (elicitation/answers.py) checks it against the schema.
    value: Any | None = Field(
        default=None, description="The answer; omit when status is 'unknown'."
    )
    status: Literal["committed", "estimated", "unknown", "default"] = Field(
        description="'committed' = the user gave this value; 'estimated' = your estimate, "
        "shown to the user in a form and kept unchanged (estimate_accepted true); 'unknown' "
        "= the user does not know (the verifier will sweep the plausible range); 'default' "
        "= use the slot's archetype default, only when the user explicitly accepts it."
    )
    # Per-token (or per-agent-type) slots have "[]" in their ir_path, e.g.
    # "tokens[].offer_variety_K"; `indices` says which list element each
    # "[]" refers to, in order (e.g. [0] = the first token).
    indices: list[int] = Field(
        default_factory=list,
        description="Which token / list element each '[]' in the slot path means.",
    )
    user_quote: str = Field(
        min_length=1, max_length=2000, description="The user's own words this answer is based on."
    )


class RecordAnswerOutput(BaseModel):
    """The spec version the answer created, and the session's new state."""

    spec_version: int
    spec_hash: str | None  # None while the partial spec is not yet schema-valid
    coherence_issues: list[dict[str, Any]] = Field(default_factory=list)
    state: str  # session state after this answer (registry/state.py)


## The protocol and the policy are read-only configuration, so they are read
## ONCE per process instead of on every answer: changing them means
## deploying a new version, which restarts the process. The protocol comes
## from elicitation/protocol.py current_protocol() (cached there and shared
## with ranking.py and elicit.next_questions.v1); the policy is cached here
## with lru_cache in the same way.
@lru_cache(maxsize=1)
def _policy() -> Policy:
    return load_policy(get_settings().policy_dir / "tool_policy.yaml")


def _record(ctx: CallContext, inp: RecordAnswerInput) -> RecordAnswerOutput:
    """Check the slot, then save the answer and the new spec version.

    All synchronous work in one function, run in a thread by the handler,
    inside ONE database transaction: the answer and the new spec version
    are saved together or not at all.
    """
    slot = current_protocol().slot(inp.slot_id)
    if slot is None:
        raise InvalidInput(f"Unknown slot {inp.slot_id!r}.")
    if inp.status == "unknown" and not slot.allow_unknown:
        raise InvalidInput(
            f"Slot {inp.slot_id!r} needs an answer; offer the user examples or a range."
        )
    if inp.status == "default" and slot.default is None:
        raise InvalidInput(f"Slot {inp.slot_id!r} has no default; ask the user.")
    with session_scope() as db:
        repo = Repository(db, ctx.principal)
        # Lock first: parallel answers to the same session (the agent runs a
        # reply's tool calls together) then apply one after the other, each
        # on top of the previous one (db/repo.py lock_session).
        repo.lock_session(inp.session_id)
        facts = repo.get_session_facts(inp.session_id)
        new_spec = apply_answer(
            facts.current_spec or {}, slot, inp.value, inp.status, indices=tuple(inp.indices)
        )
        # A partial spec is usually NOT schema-valid until late in the
        # interview; we still store it, and only hash it once it validates.
        v = service.validate(new_spec)
        version = repo.add_spec_version(inp.session_id, new_spec, v.spec_hash or "", author="agent")
        # indices are stored too: elicitation/ranking.py needs them to know
        # WHICH token a per-token answer belongs to.
        repo.record_answer(
            inp.session_id,
            slot.id,
            inp.value,
            inp.status,
            inp.user_quote,
            version,
            indices=list(inp.indices),
        )
        new_state = repo.get_session_facts(inp.session_id)
    # The state is never stored: it is derived from the refreshed facts
    # (registry/state.py), here so the agent learns at once whether the
    # interview may move on to verification.
    state = compute_state(ctx.model_copy(update={"session": new_state}), _policy())
    return RecordAnswerOutput(
        spec_version=version,
        spec_hash=v.spec_hash,
        coherence_issues=v.coherence_issues,
        state=state,
    )


async def handle(inp: RecordAnswerInput, ctx: CallContext) -> RecordAnswerOutput:
    """Record one answer in the caller's session (a new spec version)."""
    if ctx.session is None:
        raise InvalidInput("Answers are recorded inside a session (pass session_id).")
    return await anyio.to_thread.run_sync(lambda: _record(ctx, inp))


TOOL = ToolSpec(
    id="elicit.record_answer.v1",
    title="Record an interview answer",
    input_model=RecordAnswerInput,
    output_model=RecordAnswerOutput,
    handler=handle,
)
