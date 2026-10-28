## =============================================================================
## te_platform/registry/policy.py — typed view of policy/tool_policy.yaml
## =============================================================================
## GUIDE STEP   2.1
## PURPOSE      Pydantic models that mirror the structure of
##              policy/tool_policy.yaml, and load_policy() that reads the file
##              into them. After loading, the rest of the code works with
##              typed objects (policy.tools["verify.run.v1"].preconditions)
##              instead of raw dictionaries.
## USED BY      loader.py (checks tools against the policy), state.py (state
##              machine), pipeline.py (preconditions, suggested_next),
##              describe.py (descriptions), mcp_server/resources.py (publishes
##              the file), agent/loop.py (tools_by_state).
## DEPENDS ON   pydantic, PyYAML, ../../policy/tool_policy.yaml.
## WHY          D3: the policy is data, reviewed by humans; this file makes it
##              safe to use from code. extra="forbid" everywhere means a typo
##              in the YAML (e.g. "precondtions") fails at startup instead of
##              silently disabling a rule.
## ACTIVATE     Uncomment; test: loading the real file works and a file with
##              an unknown key fails (test_platform_policy.py).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep `Policy` and
## `load_policy` exactly as written (te_platform/README.md, contracts table).
## Open policy/tool_policy.yaml next to this file: each class mirrors one
## part of it, and each field name must equal the YAML key.
##
## Guide 2.1
## [ ] 1. Imports at the top: `Path` from pathlib, `Literal` from typing,
##        `yaml`, and `BaseModel`, `ConfigDict`, `Field` from pydantic.
## [ ] 2. A private base class `_Strict(BaseModel)` that rejects unknown keys
##        and makes objects read-only:
##          | model_config = ConfigDict(extra="forbid", frozen=True)
##        Every class below inherits from _Strict, not from BaseModel, and
##        has a one-line docstring (ruff's D101 asks for it).
## [ ] 3. The small parts: `StateDef` (description, enter_when),
##        `PreconditionDef` (message, do_first: list[str]) and `CostClass`
##        (typical, execution: Literal["sync", "sync_with_timeout", "job"],
##        ask_user_first: bool).
## [ ] 4. `ToolPolicy`: one tool entry. Required fields summary, use_when,
##        do_not_use_when, preconditions, cost, side_effects,
##        annotations (dict[str, bool]), returns, typical_next; optional
##        input_notes (None) and usage_rules (empty list via Field).
## [ ] 5. `SuggestionRule`: after, when, suggest, reason, and args_from
##        (str | None, default None).
## [ ] 6. `Policy`: the whole file. Same key names as the YAML top level
##        (policy_version, states, transitions_on_spec_change, ...,
##        suggested_next); `deprecated` and `planned` default to empty.
## [ ] 7. `load_policy(path: Path) -> Policy` (with a docstring): open the
##        file as UTF-8, read it
##        with yaml.safe_load (never yaml.load) and return
##        Policy.model_validate(raw). Let errors propagate on purpose.
## [ ] 8. Check: activate tests/platform_tests/test_platform_policy.py, then
##          | uv run pytest tests/platform_tests/test_platform_policy.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    """Base class: reject unknown keys and make loaded objects read-only."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class StateDef(_Strict):
    """One session state (policy -> states)."""

    description: str
    enter_when: str          # name of a predicate in predicates.py


class PreconditionDef(_Strict):
    """What the caller is told when a precondition fails (policy -> preconditions)."""

    message: str             # shown to the caller when it fails
    do_first: list[str]      # tool ids to run first


class CostClass(_Strict):
    """How expensive a tool is and how it runs (policy -> cost_classes)."""

    typical: str
    execution: Literal["sync", "sync_with_timeout", "job"]
    ask_user_first: bool


class ToolPolicy(_Strict):
    """The rules and the description of one tool (policy -> tools)."""

    summary: str
    use_when: list[str]
    do_not_use_when: list[str]
    preconditions: list[str]
    cost: str                # key into Policy.cost_classes
    side_effects: str
    # MCP's standard hint names are camelCase in the YAML (readOnlyHint...).
    annotations: dict[str, bool]
    returns: str
    typical_next: list[str]
    input_notes: str | None = None
    usage_rules: list[str] = Field(default_factory=list)


class SuggestionRule(_Strict):
    """One deterministic next-step suggestion (policy -> suggested_next)."""

    after: str               # tool id whose success triggers the rule
    when: str                # predicate name
    suggest: str             # tool id to suggest
    reason: str
    args_from: str | None = None   # name of an args function in predicates.py


class Policy(_Strict):
    """The whole policy file, typed."""

    policy_version: str
    states: dict[str, StateDef]
    transitions_on_spec_change: str
    always_available: list[str]
    tools_by_state: dict[str, list[str]]
    preconditions: dict[str, PreconditionDef]
    overridable_preconditions: list[str]
    cost_classes: dict[str, CostClass]
    tools: dict[str, ToolPolicy]
    suggested_next: list[SuggestionRule]
    deprecated: dict[str, dict[str, str]] = Field(default_factory=dict)
    # Tools described here but not built yet (see `planned` in the YAML).
    planned: list[str] = Field(default_factory=list)


def load_policy(path: Path) -> Policy:
    """Read and validate the policy file.

    Raises on any problem (missing file, bad YAML, unknown key): a server
    must not start with a broken rulebook.
    """
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Policy.model_validate(raw)
