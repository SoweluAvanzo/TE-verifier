## =============================================================================
## te_platform/tools/spec_validate.py — tool `spec.validate.v1`
## =============================================================================
## GUIDE STEP   2.5
## PURPOSE      Checks a spec (YAML text or JSON object) against the TE-IR
##              schema AND the coherence rules, and returns the normalised
##              spec, its YAML form, its spec_hash and every problem found.
##              It is the cheapest tool and is available in every session
##              state: the agent calls it after every answer or form edit.
## USED BY      registry/loader.py (entry point "spec.validate.v1"),
##              registry/pipeline.py (runs it). Its result feeds:
##              - predicates.py `has_error_level_coherence_issue` (suggests
##                elicit.record_answer.v1: explain the contradiction and ask
##                whether to change an answer). Coherence issues never BLOCK
##                verification: a contradiction may be intended, and then
##                verification shows its consequences (several case studies,
##                e.g. examples/bitcoin.yaml, have error-level issues that ARE
##                the finding);
##              - agent/spec_api.py (_validate_via_mcp: the form <-> chat spec
##                endpoints validate and normalise specs with this tool);
##              - the model, which explains coherence issues to the user.
##              Its YAML is the same as the web form's "Download YAML".
## DEPENDS ON   te_platform.service.validate (the only bridge to schema/ and
##              verifier/elicitation.py), registry/spec.py, registry/context.py.
## RULES        policy/tool_policy.yaml -> tools -> spec.validate.v1:
##              no preconditions (it must work on BROKEN specs, that is its
##              job); cost "trivial"; side_effects none.
## WHY          Architecture D6: validation, coherence and YAML normalisation
##              always go together, so they are ONE coarse tool instead of
##              three small ones the model would have to sequence.
## ACTIVATE     Uncomment; tests in test_platform_tools.py: every
##              examples/*.yaml is valid and its hash is stable (the YAML
##              it returns validates to the same hash); a broken spec and
##              text that is not YAML both return valid=False with readable
##              errors, never a ToolError.
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
## [ ] 1. Imports at the top: the same as verify_run.py (`Any`, `anyio`,
##        `BaseModel`, `Field`, `service`, `InvalidInput`, `CallContext`,
##        `ToolSpec`).
## [ ] 2. Section 1: `SpecValidateInput(BaseModel)` with `spec`
##        (str | dict[str, Any] | None) and `session_id` (str | None), both
##        `Field(default=None, description=...)`. Every class and public
##        function gets a one-line docstring (ruff's D1 rules).
## [ ] 3. Section 2: `SpecValidateOutput(BaseModel)`, field by field like
##        service.ValidationResult (the "##" note there says why it is
##        re-declared): `valid: bool`; `errors` and `coherence_issues` as
##        list[dict[str, Any]] with Field(default_factory=list); `spec_hash`
##        and `yaml` (str | None) and `normalised_spec`
##        (dict[str, Any] | None), all defaulting to None.
## [ ] 4. Section 3: `async def handle(inp: SpecValidateInput, ctx:
##        CallContext) -> SpecValidateOutput`. Pick the spec from the input
##        or the session exactly as in verify_run.py; raise InvalidInput when
##        there is none. Then run the CPU work in a thread:
##          | result = await anyio.to_thread.run_sync(service.validate, spec)
## [ ] 5. Return SpecValidateOutput copying each field of `result`; turn each
##        error into a dict with `e.model_dump()`. An invalid spec is a
##        NORMAL result (valid=False), never a raised error.
## [ ] 6. Section 4: `TOOL = ToolSpec(id="spec.validate.v1", title="Validate
##        a token economy spec", ...)` with the two models and handle.
## [ ] 7. Remove "spec.validate.v1" from `planned:` in policy/tool_policy.yaml.
## [ ] 8. Check: activate the "Guide 2.5" part of
##        tests/platform_tests/test_platform_tools.py (it tests the five
##        tools of this step together), then
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

from te_platform import service
from te_platform.errors import InvalidInput
from te_platform.registry.context import CallContext
from te_platform.registry.spec import ToolSpec


## --- 1. Input model --------------------------------------------------------------
class SpecValidateInput(BaseModel):
    """What a caller sends to spec.validate.v1."""

    spec: str | dict[str, Any] | None = Field(
        default=None,
        description="The TE-IR spec as YAML text or JSON object. Omit inside a session "
        "to validate the session's current spec.",
    )
    session_id: str | None = Field(default=None, description="The design session, if any.")


## --- 2. Output model ---------------------------------------------------------------
## Mirrors service.ValidationResult field by field. We re-declare it instead
## of reusing ValidationResult directly so the tool's public schema (what MCP
## clients see) cannot change by accident when the service layer evolves:
## the tool output is a public contract, the service result an internal one.
class SpecValidateOutput(BaseModel):
    """Validity, problems, hash and normalised forms of one spec."""

    valid: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)
    coherence_issues: list[dict[str, Any]] = Field(default_factory=list)
    spec_hash: str | None = None
    yaml: str | None = None
    normalised_spec: dict[str, Any] | None = None


## --- 3. Handler ---------------------------------------------------------------------
async def handle(inp: SpecValidateInput, ctx: CallContext) -> SpecValidateOutput:
    """Validate the spec; an invalid spec is a normal result, not an error."""
    spec = inp.spec if inp.spec is not None else (ctx.session.current_spec if ctx.session else None)
    if spec is None:
        raise InvalidInput("Pass a spec, or a session_id whose session already has a spec.")

    # Validation parses YAML and builds Pydantic models: CPU work, so it runs
    # in a worker thread and does not block the async server.
    result = await anyio.to_thread.run_sync(service.validate, spec)

    # NOTE: an invalid spec is a NORMAL outcome here, not an error: we return
    # ok with valid=False. Errors (ToolError) are reserved for calls that
    # could not be carried out at all.
    return SpecValidateOutput(
        valid=result.valid,
        errors=[e.model_dump() for e in result.errors],
        coherence_issues=result.coherence_issues,
        spec_hash=result.spec_hash,
        yaml=result.yaml,
        normalised_spec=result.normalised_spec,
    )


## --- 4. The ToolSpec the registry discovers -------------------------------------------
TOOL = ToolSpec(
    id="spec.validate.v1",
    title="Validate a token economy spec",
    input_model=SpecValidateInput,
    output_model=SpecValidateOutput,
    handler=handle,
)
