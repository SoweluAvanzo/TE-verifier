## =============================================================================
## te_platform/tools/verify_minimal.py — tool `verify.minimal.v1`
## =============================================================================
## GUIDE STEP   2.5
## PURPOSE      Returns ONLY the machine-readable reachability triage per
##              failure mode: violation_reachable, satisfaction_reachable,
##              structural_status (sound / fragile / broken / ...),
##              minimum_param_shift and safety_predicates. No narrative, no
##              counterexample text, no recommendations.
##              It exists for EXTERNAL machine consumers (cadCAD-class
##              simulators, partner pipelines), not for explaining results to
##              a person: verify.run.v1 already includes this triage.
## USED BY      registry/loader.py (entry point "verify.minimal.v1"),
##              registry/pipeline.py. Typical next tool: export.cadcad.v1.
## DEPENDS ON   te_platform.service.minimal (wraps verifier.minimal.minimal_verdicts).
## RULES        policy/tool_policy.yaml -> verify.minimal.v1: precondition
##              valid_spec; cost "moderate"; offered from state `verified` on.
## WHY          Architecture D6: kept separate from verify.run.v1 ONLY because
##              its consumers are programs that want a small, stable shape
##              (the same shape as `te-verify --minimal --json`, see
##              docs/abm-bridge.md).
## ACTIVATE     Uncomment; golden test (test_platform_tools.py): for every
##              example the verdicts equal the JSON printed by the existing
##              CLI, `python -m verifier.cli <example> --minimal --json`.
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
## [ ] 2. `VerifyMinimalInput(BaseModel)`: `spec` (str | dict[str, Any] |
##        None) and `session_id` (str | None), both Field(default=None, ...).
##        One-line docstrings on every class and on handle (ruff D1).
## [ ] 3. `VerifyMinimalOutput(BaseModel)` with ONE field,
##        `verdicts: list[dict[str, Any]]` (the ReachabilityVerdict fields of
##        verifier/minimal.py as plain JSON).
## [ ] 4. `async def handle(inp, ctx) -> VerifyMinimalOutput`: pick the spec
##        as in verify_run.py (InvalidInput when missing), then (paper
##        defaults, no config, like `te-verify --minimal` without --config)
##          | verdicts = await anyio.to_thread.run_sync(service.minimal, spec)
##        and return VerifyMinimalOutput(verdicts=verdicts).
## [ ] 5. `TOOL = ToolSpec(id="verify.minimal.v1", title="Reachability triage
##        (machine-readable)", ...)` with the two models and handle.
## [ ] 6. Remove "verify.minimal.v1" from `planned:` in policy/tool_policy.yaml.
## [ ] 7. Check: test_minimal_matches_cli in the "Guide 2.5" part of
##        tests/platform_tests/test_platform_tools.py (header, ACTIVATE).
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


class VerifyMinimalInput(BaseModel):
    """What a caller sends to verify.minimal.v1."""

    spec: str | dict[str, Any] | None = Field(
        default=None, description="The TE-IR spec (YAML text or JSON). Omit inside a session."
    )
    session_id: str | None = Field(default=None, description="The design session, if any.")


class VerifyMinimalOutput(BaseModel):
    """The reachability triage, one entry per failure mode and subject."""

    # One entry per (failure_mode, subject): the ReachabilityVerdict fields
    # from verifier/minimal.py, serialised as plain JSON.
    verdicts: list[dict[str, Any]]


async def handle(inp: VerifyMinimalInput, ctx: CallContext) -> VerifyMinimalOutput:
    """Run only the reachability triage on the spec."""
    spec = inp.spec if inp.spec is not None else (ctx.session.current_spec if ctx.session else None)
    if spec is None:
        raise InvalidInput("Pass a spec, or a session_id whose session already has a spec.")
    # Z3 work: in a thread (see verify_run.py for the reasoning).
    verdicts = await anyio.to_thread.run_sync(service.minimal, spec)
    return VerifyMinimalOutput(verdicts=verdicts)


TOOL = ToolSpec(
    id="verify.minimal.v1",
    title="Reachability triage (machine-readable)",
    input_model=VerifyMinimalInput,
    output_model=VerifyMinimalOutput,
    handler=handle,
)
