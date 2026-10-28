## =============================================================================
## te_platform/tools/verify_run.py — tool `verify.run.v1` (the reference example)
## =============================================================================
## GUIDE STEP   2.5 (the tool); 5.5 (the store of verifications: the lines
##              commented twice, under "Phase 5.5" labels)
## PURPOSE      Runs the formal verifier (Z3) and the structural triage on a
##              spec and returns verdicts, counterexamples, recommendations and
##              a verification_ref. ALWAYS the first analysis (architecture P2).
##              This module is the template every other tool copies.
## USED BY      registry/loader.py (via the entry point "verify.run.v1"),
##              registry/pipeline.py (validates input/output, calls handle()).
##              Its result feeds: predicates.py (suggested_next: simulate
##              inconclusive/fragile FMs, search literature for failures),
##              db/repo.py (stored under verification_ref, phase 5.5),
##              reports/render.py (the report's verdict table).
## DEPENDS ON   te_platform.service (verify, merged_verdicts), registry/spec.py,
##              registry/context.py; from 5.5 hashing.py, db/repo.py,
##              db/session.py; the standard-library `logging`.
## RULES        policy/tool_policy.yaml -> tools -> verify.run.v1:
##              preconditions valid_spec, decisive_slots_resolved; cost
##              "moderate". Coherence issues are returned, never blocking.
## CONFIG       This tool ALWAYS verifies with the paper's default
##              VerifierConfig (service.verify(spec), no config argument), so
##              its verification_ref uses hashing.config_hash(None).
##              registry/facts.py relies on that when it recomputes the
##              expected ref of a spec; test_platform_tools.py checks it.
## ACTIVATE     Uncomment (2.5); golden test: for each examples/*.yaml the
##              verdicts equal those of the existing CLI
##              (`python -m verifier.cli <example> --json`, the code behind
##              `te-verify`), in test_platform_tools.py. At 5.5 toggle the
##              "Phase 5.5" blocks a second time and activate the 5.5 test.
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
## Guide 2.5 (activate te_platform/service.py and registry/ first)
## [ ] 1. Imports at the top: `logging`, `Any` from typing, `anyio`,
##        `BaseModel` and `Field` from pydantic, then `service` from
##        te_platform, `InvalidInput` (te_platform.errors), `CallContext`
##        (registry.context) and `ToolSpec` (registry.spec). Below them a
##        module logger:
##          | log = logging.getLogger("te_platform.tools.verify_run")
## [ ] 2. Section 1: `VerifyRunInput(BaseModel)` with three optional fields,
##        each `Field(default=None, description=...)`: `spec`
##        (str | dict[str, Any] | None), `session_id` and `override_reason`
##        (both str | None). Write the descriptions for the model to read,
##        and give the class a one-line docstring (as every class and
##        public function: ruff's D1 rules).
## [ ] 3. Section 2: `VerifyRunOutput(BaseModel)` with verification_ref,
##        spec_hash, te_name and severity (all str), `verdicts:
##        list[dict[str, Any]]` and `coherence_issues` (same type, default
##        `Field(default_factory=list)`). These are the policy's `returns`.
## [ ] 4. Section 3: `async def handle(inp: VerifyRunInput, ctx: CallContext)
##        -> VerifyRunOutput`. First pick the spec, and raise InvalidInput
##        when there is none:
##          | spec = inp.spec if inp.spec is not None else (
##          |     ctx.session.current_spec if ctx.session else None)
## [ ] 5. Still in handle: run Z3 in a worker thread, then flatten the
##        verdicts (each one gets its structural status). Pass NO config:
##        the header's CONFIG note says why.
##          | result = await anyio.to_thread.run_sync(service.verify, spec)
##          | verdicts = service.merged_verdicts(result)
## [ ] 6. Build `output = VerifyRunOutput(...)` from result.verification_ref,
##        result.spec_hash, result.report["te_name"],
##        result.report["severity"], the verdicts and
##        result.report.get("coherence_issues", []); log "verification
##        computed" (extra: verification_ref and ctx.correlation_id), then
##        return it.
## [ ] 7. Section 4: module-level `TOOL = ToolSpec(id="verify.run.v1",
##        title="Verify a token economy", input_model=..., output_model=...,
##        handler=handle)`. Keep the name `TOOL` and the id exactly.
## [ ] 8. In the same change, remove "verify.run.v1" from `planned:` in
##        policy/tool_policy.yaml (the registry refuses to start otherwise).
## [ ] 9. Check: activate the "Guide 2.5" part of
##        tests/platform_tests/test_platform_tools.py, then
##          | uv run pytest tests/platform_tests/test_platform_tools.py -q
##          | uv run mypy te_platform
##
## Guide 5.5 (later: the "# # " lines in the SOLUTION; db/ must be active)
## [ ] 10. Imports, each in its sorted place: `Repository`
##         (te_platform.db.repo) and `session_scope` (te_platform.db.session)
##         after `service`, and
##           | from te_platform.hashing import (config_hash,
##           |     verification_ref, verifier_version)
##         after `InvalidInput`.
## [ ] 11. In handle, right after the spec check: when ctx.facts.spec_hash
##         is set, compute the expected ref BEFORE any Z3 work
##           | ref = verification_ref(ctx.facts.spec_hash,
##           |                        verifier_version(), config_hash(None))
##         then a small sync `_lookup()` that opens session_scope() and calls
##         Repository(db, ctx.principal).get_verification(ref), run in a
##         thread; if found, log it and return
##         VerifyRunOutput.model_validate(stored).
## [ ] 12. Just before `return output`: a sync `_save()` calling
##         save_verification(output.verification_ref, output.spec_hash,
##         output.model_dump(mode="json")), run with anyio.to_thread.run_sync.
## [ ] 13. Check: activate the "Guide 5.5" test of test_platform_tools.py
##         (a second identical call is answered from the store, both calls
##         are in the audit log); rerun the pytest and mypy commands above.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import logging
from typing import Any

import anyio
from pydantic import BaseModel, Field

from te_platform import service

## Phase 5.5: the store of verifications (the lookup and _save in handle()).
## (The blank line above each label keeps ruff's import sorting happy both
## before and after you toggle the block.)
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.errors import InvalidInput

## Phase 5.5: content addressing, to know the ref before any Z3 work.
from te_platform.hashing import config_hash, verification_ref, verifier_version
from te_platform.registry.context import CallContext
from te_platform.registry.spec import ToolSpec

## One logger per module, named after it; observability.py (from guide 3.1)
## decides how its lines are written.
log = logging.getLogger("te_platform.tools.verify_run")


## --- 1. Input model --------------------------------------------------------------
## Field descriptions become part of the JSON Schema the model reads, so write
## them for the model: what to pass and in which form.
class VerifyRunInput(BaseModel):
    """What a caller sends to verify.run.v1."""

    spec: str | dict[str, Any] | None = Field(
        default=None,
        description="The TE-IR spec as YAML text or JSON object. Omit when working in a "
        "session: the session's current spec is used.",
    )
    session_id: str | None = Field(default=None, description="The design session, if any.")
    override_reason: str | None = Field(
        default=None,
        description="Only if the USER explicitly asked to skip an overridable rule; say why.",
    )


## --- 2. Output model ---------------------------------------------------------------
class VerifyRunOutput(BaseModel):
    """The verdicts of one verification and the ref that identifies it."""

    verification_ref: str
    spec_hash: str
    te_name: str  # the economy's name, printed on reports
    severity: str
    # One entry per failure mode and subject, flattened from the report and
    # the triage so the model reads one list instead of two.
    verdicts: list[dict[str, Any]]
    coherence_issues: list[dict[str, Any]] = Field(default_factory=list)


## --- 3. Handler ---------------------------------------------------------------------
async def handle(inp: VerifyRunInput, ctx: CallContext) -> VerifyRunOutput:
    """Verify the spec (or answer from the store, from guide 5.5)."""
    spec = inp.spec if inp.spec is not None else (ctx.session.current_spec if ctx.session else None)
    if spec is None:
        # Not a precondition in the policy sense: the call is simply
        # incomplete. (In practice the `valid_spec` precondition already
        # stops this case; the check keeps the handler safe on its own.)
        raise InvalidInput("Pass a spec, or a session_id whose session has a spec.")

    ## Phase 5.5: answer an identical request from the store. The pipeline
    ## already computed the spec's hash (ctx.facts, registry/facts.py); the
    ## ref of THIS spec + verifier version + default config is therefore
    ## known before any Z3 work (content addressing, D5). Verifications are
    ## shared between users on purpose (see db/repo.py save_verification).
    if ctx.facts.spec_hash is not None:
        ref = verification_ref(ctx.facts.spec_hash, verifier_version(), config_hash(None))

        def _lookup() -> dict[str, Any] | None:
            with session_scope() as db:
                return Repository(db, ctx.principal).get_verification(ref)

        stored = await anyio.to_thread.run_sync(_lookup)
        if stored is not None:
            log.info(
                "verification served from the store",
                extra={"verification_ref": ref, "correlation_id": ctx.correlation_id},
            )
            return VerifyRunOutput.model_validate(stored)

    # Z3 is CPU-bound: run it in a worker thread, so this async server keeps
    # answering other requests (and the pipeline's timeout still works).
    # No config argument: always the paper's defaults (header, CONFIG).
    result = await anyio.to_thread.run_sync(service.verify, spec)

    # Each verdict merged with its structural status (service.merged_verdicts
    # explains the matching of full names and short ids).
    verdicts = service.merged_verdicts(result)

    output = VerifyRunOutput(
        verification_ref=result.verification_ref,
        spec_hash=result.spec_hash,
        te_name=result.report["te_name"],
        severity=result.report["severity"],
        verdicts=verdicts,
        coherence_issues=result.report.get("coherence_issues", []),
    )
    log.info(
        "verification computed",
        extra={"verification_ref": output.verification_ref, "correlation_id": ctx.correlation_id},
    )

    ## Phase 5.5: store the result under its verification_ref, so identical
    ## requests are answered from the store (block above), the session state
    ## can see that the current spec is verified, and reports can be rendered
    ## from it.
    def _save() -> None:
        with session_scope() as db:
            Repository(db, ctx.principal).save_verification(
                output.verification_ref, output.spec_hash, output.model_dump(mode="json")
            )

    await anyio.to_thread.run_sync(_save)
    return output


## --- 4. The ToolSpec the registry discovers -------------------------------------------
TOOL = ToolSpec(
    id="verify.run.v1",
    title="Verify a token economy",
    input_model=VerifyRunInput,
    output_model=VerifyRunOutput,
    handler=handle,
)
