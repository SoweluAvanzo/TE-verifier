## =============================================================================
## te_platform/mcp_server/resources.py — read-only data offered to MCP clients
## =============================================================================
## GUIDE STEP   3.2 (schema, conditions, examples, policy), 7.6 (protocol)
## PURPOSE      MCP *resources* are documents a client or model can read, each
##              identified by a URI. We publish five, all from existing files of
##              the repository (nothing is copied or duplicated):
##                te://schema/te-ir           JSON Schema of the TE-IR (schema/)
##                te://paper/conditions       the six failure-mode conditions,
##                                            plain-language explanations
##                                            (verifier/paper.py)
##                te://examples/{name}        a case-study spec (examples/*.yaml)
##                te://policy/tools           policy/tool_policy.yaml
##                te://protocol/elicitation   policy/elicitation_protocol.yaml
##                                            (guide 7.6)
##              `{name}` makes te://examples/{name} a *resource template*: one
##              entry standing for many URIs.
## USED BY      mcp_server/app.py passes the three on_* handlers below to the
##              low-level Server. Read by MCP clients and by our agent
##              (agent/loop.py may read the schema and the protocol).
## DEPENDS ON   mcp (types, MCPError), schema.TokenEconomy,
##              verifier.paper.ALL_CONDITIONS, config.py (policy_dir), the
##              files listed above.
## WHY          Architecture §3.3 and D16: every MCP client gets the SAME rules
##              (policy, protocol) and the same definitions as our own agent.
##              Single source of truth (P3): resources are generated from the
##              files the code uses, never maintained by hand.
## SECURITY     Only the fixed URIs below are served. The {name} of an example
##              is checked against the actual list of example files, so a URI
##              like te://examples/../../.env can never read another file
##              (path traversal). Any other URI is refused with
##              MCPError(INVALID_PARAMS): a clean JSON-RPC error for the client.
## ACTIVATE     3.2: uncomment (single-commented code); in the MCP Inspector,
##              the Resources tab lists them. 7.6: the twice-commented
##              protocol lines (the protocol file exists from guide 7.1-7.2).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the three handler
## names (on_list_resources, on_list_resource_templates, on_read_resource)
## and every te:// URI exactly: app.py and the clients use them.
##
## Guide 3.2
## [ ] 1. Imports at the top: dataclasses, json, Path, Any, MCPError and
##        `types` (from mcp), INVALID_PARAMS (mcp.types),
##        ServerRequestContext (mcp.server), TokenEconomy (schema),
##        get_settings, ALL_CONDITIONS (verifier.paper).
## [ ] 2. `_REPO_ROOT` (this file's path, three levels up) and
##        `_EXAMPLES_DIR = _REPO_ROOT / "examples"`.
## [ ] 3. `_STATIC`: a list of types.Resource (uri, name, mime_type,
##        description) for te://schema/te-ir, te://paper/conditions and
##        te://policy/tools.
## [ ] 4. `async on_list_resources(_ctx, _params)`: return
##        ListResourcesResult(resources=_STATIC).
## [ ] 5. `async on_list_resource_templates(...)`: one ResourceTemplate with
##        uri_template "te://examples/{name}", listing the example names
##        (the .yaml stems) in its description.
## [ ] 6. `_text(uri, text, mime)`: a ReadResourceResult with one
##        TextResourceContents. `_conditions_json()`: ALL_CONDITIONS as JSON,
##        each condition converted with dataclasses.asdict.
## [ ] 7. `async on_read_resource(_ctx, params)`: compare str(uri) with each
##        fixed URI and return the matching text (schema from
##        TokenEconomy.model_json_schema(), policy file from
##        Settings.policy_dir). For te://examples/<name>, serve the file only
##        if <name> is in the allow-list of existing stems:
##          | allowed = {p.stem: p for p in _EXAMPLES_DIR.glob("*.yaml")}
##        Anything else: raise MCPError(code=INVALID_PARAMS, message=...).
## [ ] 8. Check: toggle the 3.2 lines in app.py. The resource tests come
##        with guide 3.3 (test_example_resource_rejects_path_traversal in
##        tests/platform_tests/test_platform_mcp.py); for now, see the
##        Resources tab in the MCP Inspector.
##
## Guide 7.6 (the "# # " lines under the Phase/Guide 7.6 labels)
## [ ] 9. Toggle te://protocol/elicitation: the Resource at the end of
##        _STATIC and its branch in on_read_resource, reading
##        policy_dir / "elicitation_protocol.yaml". Check: activate
##        test_protocol_resource_is_served, then the Inspector shows and
##        reads it.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import dataclasses
import json
from pathlib import Path
from typing import Any

from mcp import MCPError, types
from mcp.server import ServerRequestContext
from mcp.types import INVALID_PARAMS
from schema import TokenEconomy
from verifier.paper import ALL_CONDITIONS

from te_platform.config import get_settings

## The repository root, computed from this file's location
## (te_platform/mcp_server/resources.py -> three levels up). In the Docker
## image the source sits in /app, so this still points at /app.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES_DIR = _REPO_ROOT / "examples"


## --- Static resources --------------------------------------------------------
_STATIC = [
    types.Resource(
        uri="te://schema/te-ir",
        name="te-ir-schema",
        mime_type="application/json",
        description="JSON Schema of a token economy spec (TE-IR).",
    ),
    types.Resource(
        uri="te://paper/conditions",
        name="failure-mode-conditions",
        mime_type="application/json",
        description="The six failure modes: formal conditions, plain explanations, design knobs.",
    ),
    types.Resource(
        uri="te://policy/tools",
        name="tool-policy",
        mime_type="application/yaml",
        description="When to use each tool, preconditions, session states.",
    ),
    ## Guide 7.6: the elicitation protocol.
    types.Resource(
        uri="te://protocol/elicitation",
        name="elicitation-protocol",
        mime_type="application/yaml",
        description="Questions the interview must cover, with routing and criticality.",
    ),
]


async def on_list_resources(
    _ctx: ServerRequestContext[Any, Any],
    _params: types.PaginatedRequestParams | None,
) -> types.ListResourcesResult:
    """List the fixed resources."""
    return types.ListResourcesResult(resources=_STATIC)


async def on_list_resource_templates(
    _ctx: ServerRequestContext[Any, Any],
    _params: types.PaginatedRequestParams | None,
) -> types.ListResourceTemplatesResult:
    """List the resource templates (one: the case-study specs)."""
    names = ", ".join(sorted(p.stem for p in _EXAMPLES_DIR.glob("*.yaml")))
    return types.ListResourceTemplatesResult(
        resource_templates=[
            types.ResourceTemplate(
                uri_template="te://examples/{name}",
                name="example-spec",
                mime_type="application/yaml",
                description=f"A case-study spec. Names: {names}",
            ),
        ]
    )


## --- Reading one resource ----------------------------------------------------
def _text(uri: str, text: str, mime: str) -> types.ReadResourceResult:
    """Wrap one text document as a resource result."""
    return types.ReadResourceResult(
        contents=[types.TextResourceContents(uri=uri, mime_type=mime, text=text)]
    )


def _conditions_json() -> str:
    """Return ALL_CONDITIONS ("FM1".."FM6" -> PaperCondition) as JSON.

    dataclasses.asdict converts the frozen dataclasses, including nested
    ones, into plain dicts that json can write.
    """
    conditions = {fm: dataclasses.asdict(c) for fm, c in ALL_CONDITIONS.items()}
    return json.dumps(conditions, ensure_ascii=False)


async def on_read_resource(
    _ctx: ServerRequestContext[Any, Any], params: types.ReadResourceRequestParams
) -> types.ReadResourceResult:
    """Return the resource `params.uri`, or refuse an unknown URI."""
    uri = str(params.uri)
    policy_dir = get_settings().policy_dir

    if uri == "te://schema/te-ir":
        return _text(uri, json.dumps(TokenEconomy.model_json_schema()), "application/json")
    if uri == "te://paper/conditions":
        return _text(uri, _conditions_json(), "application/json")
    if uri == "te://policy/tools":
        policy = (policy_dir / "tool_policy.yaml").read_text(encoding="utf-8")
        return _text(uri, policy, "application/yaml")
    ## Guide 7.6: the elicitation protocol.
    if uri == "te://protocol/elicitation":
        protocol = (policy_dir / "elicitation_protocol.yaml").read_text(encoding="utf-8")
        return _text(uri, protocol, "application/yaml")
    if uri.startswith("te://examples/"):
        name = uri.removeprefix("te://examples/")
        # Allow-list check: only names of files that actually exist.
        allowed = {p.stem: p for p in _EXAMPLES_DIR.glob("*.yaml")}
        if name in allowed:
            return _text(uri, allowed[name].read_text(encoding="utf-8"), "application/yaml")
    raise MCPError(code=INVALID_PARAMS, message=f"Unknown resource {uri}")
