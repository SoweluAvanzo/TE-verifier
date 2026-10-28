## =============================================================================
## te_platform/tools/export_cadcad.py — tool `export.cadcad.v1`
## =============================================================================
## GUIDE STEP   2.5
## PURPOSE      Produces a cadCAD-compatible configuration (cadCAD = an
##              open-source Python framework for simulating token economies)
##              from a spec, so a technical user can continue the analysis in
##              their own cadCAD pipeline.
## USED BY      registry/loader.py (entry point "export.cadcad.v1"), pipeline.py.
## DEPENDS ON   te_platform.service.export_cadcad (wraps
##              verifier.abm.cadcad_export.export_cadcad_config).
## RULES        policy -> export.cadcad.v1: precondition valid_spec; cost
##              "cheap"; use ONLY on explicit user request (do_not_use_when:
##              "in any other situation"). The generated description tells
##              the model this; nothing in the handler needs to enforce it.
## WHY          Interoperability with the cadCAD ecosystem without making the
##              agent push a technical export on non-technical users.
## ACTIVATE     Uncomment; golden test (test_platform_tools.py): for each
##              example, the same dict as POST /api/cadcad-export of the
##              existing web app (Flask's test client) with the same n_runs,
##              horizon and seed.
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
## [ ] 2. `ExportCadcadInput(BaseModel)`: `spec` and `session_id` as in the
##        other tools, plus three bounded numbers (ge/le give clear errors):
##          | n_runs: int = Field(default=500, ge=1, le=5000, description=...)
##        `horizon: int` (default 260, ge=1, le=5000) and
##        `seed: int | None` (default None): the web app's defaults and
##        bounds. One-line docstrings on every class and on handle.
## [ ] 3. `ExportCadcadOutput(BaseModel)` with one field,
##        `cadcad_config: dict[str, Any]` (the policy's `returns`).
## [ ] 4. `async def handle(inp, ctx) -> ExportCadcadOutput`: pick the spec as
##        in verify_run.py (InvalidInput when missing). run_sync only passes
##        positional arguments, so bind the keywords in a lambda:
##          | lambda: service.export_cadcad(spec, n_runs=inp.n_runs,
##          |                               horizon=inp.horizon, seed=inp.seed)
##        and return ExportCadcadOutput(cadcad_config=config).
## [ ] 5. `TOOL = ToolSpec(id="export.cadcad.v1", title="Export a cadCAD
##        configuration", ...)` with the two models and handle.
## [ ] 6. Remove "export.cadcad.v1" from `planned:` in policy/tool_policy.yaml.
## [ ] 7. Check: test_cadcad_export_matches_web_api in the "Guide 2.5"
##        part of tests/platform_tests/test_platform_tools.py.
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


class ExportCadcadInput(BaseModel):
    """What a caller sends to export.cadcad.v1."""

    spec: str | dict[str, Any] | None = Field(
        default=None, description="The TE-IR spec (YAML text or JSON). Omit inside a session."
    )
    session_id: str | None = Field(default=None, description="The design session, if any.")
    # ge/le make Pydantic reject out-of-range values with a clear message;
    # service.export_cadcad clamps again (defence in depth). The defaults
    # and the 5000 bounds are those of the web app's /api/cadcad-export.
    # 500 runs is more than MAX_MC_RUNS on purpose: nothing runs here, the
    # numbers are only written into a config that runs on the user's side.
    n_runs: int = Field(
        default=500, ge=1, le=5000, description="Monte Carlo runs in the exported config."
    )
    horizon: int = Field(default=260, ge=1, le=5000, description="Simulation length in periods.")
    seed: int | None = Field(default=None, description="Random seed for reproducibility.")


class ExportCadcadOutput(BaseModel):
    """The cadCAD configuration, ready to save as JSON."""

    cadcad_config: dict[str, Any]


async def handle(inp: ExportCadcadInput, ctx: CallContext) -> ExportCadcadOutput:
    """Build the cadCAD configuration of the spec."""
    spec = inp.spec if inp.spec is not None else (ctx.session.current_spec if ctx.session else None)
    if spec is None:
        raise InvalidInput("Pass a spec, or a session_id whose session already has a spec.")
    # anyio.to_thread.run_sync only forwards positional arguments, so keyword
    # arguments are bound first with a small lambda.
    config = await anyio.to_thread.run_sync(
        lambda: service.export_cadcad(spec, n_runs=inp.n_runs, horizon=inp.horizon, seed=inp.seed)
    )
    return ExportCadcadOutput(cadcad_config=config)


TOOL = ToolSpec(
    id="export.cadcad.v1",
    title="Export a cadCAD configuration",
    input_model=ExportCadcadInput,
    output_model=ExportCadcadOutput,
    handler=handle,
)
