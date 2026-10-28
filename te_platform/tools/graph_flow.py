## =============================================================================
## te_platform/tools/graph_flow.py — tool `graph.flow.v1`
## =============================================================================
## GUIDE STEP   2.5
## PURPOSE      Builds the DECLARED flow graph of a spec, without simulating
##              anything: nodes for mint pools, burn sinks, role wallets,
##              non-tokenized assets and events; edges for emission, burn,
##              redemption and cross-token flows. The result is Cytoscape JSON
##              (the format of the Cytoscape.js graph library the web app
##              already uses on /explore and in the form preview).
##              The agent uses it to SHOW the user what they described and ask
##              "is this right?" before verifying.
## USED BY      registry/loader.py (entry point "graph.flow.v1"), pipeline.py;
##              the agent calls it through MCP to describe the structure to
##              the user. (The chat page does not draw it yet; /explore and
##              the form preview draw the same payload from the web app.)
## DEPENDS ON   te_platform.service.flow_graph (wraps
##              verifier.abm.flow_graph.build_flow_graph).
## RULES        policy -> graph.flow.v1: precondition valid_spec; cost "cheap";
##              offered in every session state (it refuses, via valid_spec,
##              while no valid spec exists).
## WHY          Confirming structure with the user BEFORE verification catches
##              misunderstandings early, when they are cheap to fix.
## SHAPE       build_flow_graph returns (checked against the real verifier)
##              {"elements": {"nodes": [...], "edges": [...]},
##               "diagnostics": [...], "summary": {...}}; the tool flattens
##              elements and keeps diagnostics and summary.
## ACTIVATE     Uncomment; golden test (test_platform_tools.py): for each
##              example, nodes, edges, diagnostics and summary equal what
##              POST /api/flow-graph of the existing web app returns (called
##              with Flask's test client, no server needed).
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
## [ ] 2. `GraphFlowInput(BaseModel)`: `spec` (str | dict[str, Any] | None)
##        and `session_id` (str | None), both Field(default=None, ...).
##        One-line docstrings on every class and on handle (ruff D1).
## [ ] 3. `GraphFlowOutput(BaseModel)`: `nodes` and `edges` as
##        list[dict[str, Any]] (required), `diagnostics: list[Any]` and
##        `summary: dict[str, Any]`, both with an empty default_factory.
##        Typed loosely on purpose (see the "##" comment in the SOLUTION).
## [ ] 4. `async def handle(inp, ctx) -> GraphFlowOutput`: pick the spec as
##        in verify_run.py (InvalidInput when missing), run
##        service.flow_graph in a thread, then unpack the SHAPE described in
##        the header (nodes and edges sit under "elements"):
##          | elements = payload.get("elements", {})
##        and fill diagnostics and summary from payload with .get defaults.
## [ ] 5. `TOOL = ToolSpec(id="graph.flow.v1", title="Declared flow graph",
##        ...)` with the two models and handle.
## [ ] 6. Remove "graph.flow.v1" from `planned:` in policy/tool_policy.yaml.
## [ ] 7. Check: test_flow_graph_matches_web_api in the "Guide 2.5" part
##        of tests/platform_tests/test_platform_tools.py (header, ACTIVATE).
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


class GraphFlowInput(BaseModel):
    """What a caller sends to graph.flow.v1."""

    spec: str | dict[str, Any] | None = Field(
        default=None, description="The TE-IR spec (YAML text or JSON). Omit inside a session."
    )
    session_id: str | None = Field(default=None, description="The design session, if any.")


class GraphFlowOutput(BaseModel):
    """The declared flow graph as Cytoscape JSON, with its diagnostics."""

    # Cytoscape JSON: {"nodes": [{"data": {...}}], "edges": [{"data": {...}}]}.
    # Typed loosely on purpose: the shape is owned by verifier/abm/flow_graph.py
    # and documented there; re-typing it here would duplicate that contract.
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    # Warnings about the declared structure, and counts per node kind.
    diagnostics: list[Any] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


async def handle(inp: GraphFlowInput, ctx: CallContext) -> GraphFlowOutput:
    """Build the declared flow graph of the spec (no simulation)."""
    spec = inp.spec if inp.spec is not None else (ctx.session.current_spec if ctx.session else None)
    if spec is None:
        raise InvalidInput("Pass a spec, or a session_id whose session already has a spec.")
    payload = await anyio.to_thread.run_sync(service.flow_graph, spec)
    # Nodes and edges sit under "elements" (Cytoscape's convention); see SHAPE.
    elements = payload.get("elements", {})
    return GraphFlowOutput(
        nodes=elements.get("nodes", []),
        edges=elements.get("edges", []),
        diagnostics=payload.get("diagnostics", []),
        summary=payload.get("summary", {}),
    )


TOOL = ToolSpec(
    id="graph.flow.v1",
    title="Declared flow graph",
    input_model=GraphFlowInput,
    output_model=GraphFlowOutput,
    handler=handle,
)
