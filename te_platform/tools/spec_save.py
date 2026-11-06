## =============================================================================
## te_platform/tools/spec_save.py — spec.save.v1: make a complete design the session's spec
## =============================================================================
## GUIDE STEP   extension of 7 (a spec may arrive whole, as from the form)
## PURPOSE      spec.validate.v1 only checks the spec it is given. This tool also
##              stores it as the session's new version, as saving from the form
##              does (agent/spec_api.py). A complete spec answers its own
##              questions (elicitation/ranking.py), so the session can move on
##              to verification.
## USED BY      the agent, through the pipeline (policy/tool_policy.yaml).
## WHY          Found in a real conversation: the agent built a valid spec with
##              spec.validate.v1, the session stayed `eliciting`, verify.run.v1
##              was never offered, and the agent told the user it was not connected.
## =============================================================================

from functools import lru_cache
from typing import Any

import anyio
from pydantic import BaseModel, Field

from te_platform import service
from te_platform.config import get_settings
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.registry.context import CallContext
from te_platform.registry.policy import Policy, load_policy
from te_platform.registry.spec import ToolSpec
from te_platform.registry.state import compute_state


class SpecSaveInput(BaseModel):
    """What a caller sends to spec.save.v1."""

    session_id: str = Field(description="The design session.")
    spec: str | dict[str, Any] = Field(description="The complete TE-IR spec, as YAML or JSON.")


class SpecSaveOutput(BaseModel):
    """Whether the spec was stored, and what the session can do next."""

    saved: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)  # why it was not stored
    coherence_issues: list[dict[str, Any]] = Field(default_factory=list)
    spec_version: int | None = None
    spec_hash: str | None = None
    state: str  # session state now: from spec_ready on, verify.run.v1 is offered
    open_decisive_slots: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def _policy() -> Policy:
    return load_policy(get_settings().policy_dir / "tool_policy.yaml")


def _save(ctx: CallContext, inp: SpecSaveInput) -> SpecSaveOutput:
    checked = service.validate(inp.spec)
    version = None
    with session_scope() as db:
        repo = Repository(db, ctx.principal)
        repo.lock_session(inp.session_id)
        if checked.valid:
            version = repo.add_spec_version(
                inp.session_id, checked.normalised_spec, checked.spec_hash or "", author="agent"
            )
        facts = repo.get_session_facts(inp.session_id)
    return SpecSaveOutput(
        saved=checked.valid,
        errors=[e.model_dump() for e in checked.errors],
        coherence_issues=checked.coherence_issues,
        spec_version=version,
        spec_hash=checked.spec_hash,
        state=compute_state(ctx.model_copy(update={"session": facts}), _policy()),
        open_decisive_slots=list(facts.open_decisive_slots),
    )


async def handle(inp: SpecSaveInput, ctx: CallContext) -> SpecSaveOutput:
    """Validate the spec and, if valid, store it as the session's new version."""
    return await anyio.to_thread.run_sync(lambda: _save(ctx, inp))


TOOL = ToolSpec(
    id="spec.save.v1",
    title="Save a complete design as the session's spec",
    input_model=SpecSaveInput,
    output_model=SpecSaveOutput,
    handler=handle,
)
