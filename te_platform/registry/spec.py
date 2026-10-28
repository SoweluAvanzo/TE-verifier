## =============================================================================
## te_platform/registry/spec.py — ToolSpec: the definition of one tool
## =============================================================================
## GUIDE STEP   2.3
## PURPOSE      A ToolSpec bundles what the server needs to run a tool:
##              its id (matching policy/tool_policy.yaml), the Pydantic models
##              of its input and output, and its handler function.
##              Every module in tools/ creates exactly one ToolSpec named TOOL.
## USED BY      tools/*.py (create one each), loader.py (discovers them),
##              pipeline.py (validates input/output with the models, calls
##              the handler), mcp_server/app.py (publishes the input schema).
## DEPENDS ON   pydantic, registry/context.py.
## WHY          D6/P6: a tool is a small, self-describing unit. Anything that
##              can produce a ToolSpec (even another package) can add a tool.
##              The *rules* about the tool (when to use it, preconditions,
##              cost) are deliberately NOT here but in the policy YAML, so
##              domain experts can review them without reading Python.
## ACTIVATE     Uncomment; test via test_platform_registry.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the name `ToolSpec`
## and its field names exactly: every tools/*.py module builds one
## (te_platform/README.md, contracts table). Activate context.py first.
##
## Guide 2.3
## [ ] 1. Imports at the top: `Awaitable`, `Callable` from collections.abc,
##        `dataclass` from dataclasses, `Any` from typing, `BaseModel` from
##        pydantic and `CallContext` from te_platform.registry.context.
## [ ] 2. The type alias `Handler`: an async function taking (input, ctx) and
##        returning a Pydantic model. The input is typed Any on purpose; the
##        `##` lines above it in the SOLUTION explain why.
##          | Handler = Callable[[Any, CallContext], Awaitable[BaseModel]]
## [ ] 3. `ToolSpec` as a frozen dataclass (@dataclass(frozen=True)), with the
##        fields in this order: id (str), input_model and output_model (both
##        type[BaseModel]), handler (Handler), and last title (str, default
##        ""), because a field with a default must come after those without.
##        Give the class a one-line docstring.
##        No cost or preconditions here: they live in the policy YAML.
## [ ] 4. Check: run `uv run mypy te_platform`. The real test is
##        test_platform_registry.py, activated with loader.py (guide 2.3).
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from te_platform.registry.context import CallContext

## A handler takes the validated input model and the call context and returns
## the output model. It is `async` because handlers often wait (database,
## Redis); CPU-heavy work inside must be moved to a thread
## (anyio.to_thread.run_sync) so it does not block other requests.
## The first parameter is typed `Any` on purpose: each handler accepts its OWN
## input class (VerifyRunInput, ...). A type checker would reject those
## handlers against `BaseModel` (a function that only accepts VerifyRunInput
## cannot stand in for one that accepts every BaseModel). The pipeline
## guarantees the right class at runtime: it validates the raw input with
## tool.input_model before calling the handler.
Handler = Callable[[Any, CallContext], Awaitable[BaseModel]]


# A dataclass (not a Pydantic model) because it holds classes and functions,
# which Pydantic would try to validate. frozen=True: a tool definition never
# changes after creation.
@dataclass(frozen=True)
class ToolSpec:
    """One tool: its id, its input and output models, and its handler."""

    id: str                         # e.g. "verify.run.v1"; must exist in the policy
    input_model: type[BaseModel]    # schema the MCP client sees and the pipeline validates
    output_model: type[BaseModel]   # the pipeline validates the handler's result against it
    handler: Handler
    title: str = ""                 # short human name shown in MCP clients
