## =============================================================================
## te_platform/registry/loader.py — discover tools and check them against the policy
## =============================================================================
## GUIDE STEP   2.3
## PURPOSE      At startup:
##              1. load the policy (policy.py);
##              2. find every tool advertised under the entry-point group
##                 "te_platform.tools" (see pyproject_additions.toml);
##              3. check that tools and policy agree EXACTLY: every rule name
##                 used by the policy exists in predicates.py and every
##                 registered rule is used; every tool id or state mentioned
##                 anywhere in the policy exists; built tools are not
##                 `planned`;
##              4. return a Registry object holding both.
##              Any mismatch stops the server: it must never run with a tool
##              that has no rules, or rules that point at nothing.
## USED BY      mcp_server/app.py (calls build_registry() once at startup),
##              pipeline.py (receives the Registry), tests (consistency test).
##              The Flask web app would call it too if its REST routes ever go
##              through the pipeline; today they call service.py directly.
## DEPENDS ON   importlib.metadata (standard library), policy.py, spec.py,
##              predicates.py.
## WHY          D6/P6: adding a tool = adding a module + an entry point + a
##              policy entry; nothing else in the server changes. The startup
##              checks turn "forgot to add the policy entry" into an immediate,
##              clear error.
## ACTIVATE     Uncomment; test_platform_registry.py asserts the real policy
##              and the real tools are consistent.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep `Registry` and
## `build_registry` exactly as written (te_platform/README.md, contracts
## table). Activate policy.py, spec.py and predicates.py first. No tool is
## needed yet: until guide 2.5 every policy tool is still `planned`.
##
## Guide 2.3
## [ ] 1. Imports at the top: `dataclass`, `entry_points` from
##        importlib.metadata, `Path`, the module `predicates` (import the
##        module, not its dicts), `Policy`, `load_policy` and `ToolSpec`.
## [ ] 2. `Registry`: a frozen dataclass with `policy: Policy` and
##        `tools: dict[str, ToolSpec]` (tool id -> ToolSpec).
## [ ] 3. `class RegistryError(RuntimeError)` with a one-line docstring.
## [ ] 4. `discover_tools() -> dict[str, ToolSpec]`: loop over
##          | for ep in entry_points(group="te_platform.tools"):
##          |     tool = ep.load()
##        raise RegistryError if tool is not a ToolSpec or if tool.id differs
##        from ep.name; otherwise store it under tool.id.
## [ ] 5. Three private checks, each returning a list of problem strings
##        (never raising), in the order of the SOLUTION:
##        a) `_check_tools_and_rule_names(policy, tools)`: tool ids declared
##           vs registered vs planned (four set differences), unknown
##           preconditions and cost classes, unknown predicates in states,
##           unknown predicates/args_from in suggested_next;
##        b) `_check_mentions(policy)`: every tool id or state MENTIONED in
##           the policy exists, and every precondition used has an entry
##           under `preconditions`;
##        c) `_check_unused_rules(policy)`: the other direction, every
##           registered rule is used.
##        Then `check_consistency(policy, tools) -> list[str]` returns
##        a + b + c. Copy the message texts exactly: the tests match them.
## [ ] 6. `build_registry(policy_path) -> Registry`: load the policy, discover
##        the tools, check; raise RegistryError listing all problems if any.
## [ ] 7. Check: activate tests/platform_tests/test_platform_registry.py, then
##          | uv run pytest tests/platform_tests/test_platform_registry.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path

from te_platform.registry import predicates
from te_platform.registry.policy import Policy, load_policy
from te_platform.registry.spec import ToolSpec


@dataclass(frozen=True)
class Registry:
    """The loaded policy and the discovered tools, checked to agree."""

    policy: Policy
    tools: dict[str, ToolSpec]     # tool id -> ToolSpec


class RegistryError(RuntimeError):
    """The tools and the policy disagree. Raised at startup only."""


def discover_tools() -> dict[str, ToolSpec]:
    """Load every object advertised in the "te_platform.tools" group.

    ep.load() imports the module and returns the object after the colon
    ("te_platform.tools.verify_run:TOOL" -> the TOOL object).
    """
    found: dict[str, ToolSpec] = {}
    for ep in entry_points(group="te_platform.tools"):
        tool = ep.load()
        if not isinstance(tool, ToolSpec):
            raise RegistryError(f"entry point {ep.name} does not point to a ToolSpec")
        if tool.id != ep.name:
            raise RegistryError(f"entry point name {ep.name} != tool id {tool.id}")
        found[tool.id] = tool
    return found


# check_consistency() is split into three parts (a, b, c below), each a
# plain list of problem strings, so every part stays short to read.
def _check_tools_and_rule_names(policy: Policy, tools: dict[str, ToolSpec]) -> list[str]:
    """Part a: tool ids (declared / registered / planned) and rule names."""
    problems: list[str] = []
    declared = set(policy.tools)
    registered = set(tools)
    planned = set(policy.planned)
    # A tool may be described before it is built only if it is listed as
    # `planned`; a built tool must be removed from `planned` (otherwise
    # agents would never be offered it).
    problems += [f"tool in policy but not registered (and not planned): {t}"
                 for t in sorted(declared - registered - planned)]
    problems += [f"tool registered but still listed as planned: {t}"
                 for t in sorted(registered & planned)]
    problems += [f"planned tool missing from policy tools: {t}"
                 for t in sorted(planned - declared)]
    problems += [f"tool registered but missing from policy: {t}"
                 for t in sorted(registered - declared)]
    for tid, tp in policy.tools.items():
        problems += [f"{tid}: unknown precondition {p}"
                     for p in tp.preconditions if p not in predicates.PRECONDITIONS]
        if tp.cost not in policy.cost_classes:
            problems.append(f"{tid}: unknown cost class {tp.cost}")
    for name, state in policy.states.items():
        if state.enter_when not in predicates.PREDICATES:
            problems.append(f"state {name}: unknown predicate {state.enter_when}")
    for rule in policy.suggested_next:
        if rule.when not in predicates.PREDICATES:
            problems.append(f"suggestion after {rule.after}: unknown predicate {rule.when}")
        if rule.args_from and rule.args_from not in predicates.ARGS_FROM:
            problems.append(f"suggestion after {rule.after}: unknown args_from {rule.args_from}")
    return problems


def _check_mentions(policy: Policy) -> list[str]:
    """Part b: every tool id, state and precondition MENTIONED in the policy exists.

    A typo such as "verify.run.v2" would otherwise silently offer or
    suggest nothing.
    """
    declared = set(policy.tools)
    mentioned: list[tuple[str, str]] = []
    mentioned += [("always_available", t) for t in policy.always_available]
    mentioned += [(f"tools_by_state.{s}", t)
                  for s, ids in policy.tools_by_state.items() for t in ids]
    mentioned += [("suggested_next", t)
                  for r in policy.suggested_next for t in (r.after, r.suggest)]
    mentioned += [(f"{tid}.typical_next", t)
                  for tid, tp in policy.tools.items() for t in tp.typical_next]
    mentioned += [(f"preconditions.{n}.do_first", t)
                  for n, pc in policy.preconditions.items() for t in pc.do_first]
    problems = [f"{where}: unknown tool {t}" for where, t in mentioned if t not in declared]
    problems += [f"tools_by_state: unknown state {s}"
                 for s in policy.tools_by_state if s not in policy.states]
    problems += [f"state {s} has no tools_by_state entry"
                 for s in policy.states if s not in policy.tools_by_state]
    problems += [f"{tid}: precondition {p} has no entry under `preconditions`"
                 for tid, tp in policy.tools.items() for p in tp.preconditions
                 if p not in policy.preconditions]
    problems += [f"overridable_preconditions: unknown precondition {p}"
                 for p in policy.overridable_preconditions if p not in policy.preconditions]
    return problems


def _check_unused_rules(policy: Policy) -> list[str]:
    """Part c: every rule registered in predicates.py is used by the policy.

    An unused rule is dead code, or a sign that the policy lost a rule.
    """
    used_pre = {p for tp in policy.tools.values() for p in tp.preconditions}
    used_pred = ({s.enter_when for s in policy.states.values()}
                 | {r.when for r in policy.suggested_next})
    used_args = {r.args_from for r in policy.suggested_next if r.args_from}
    unused = [("precondition", n) for n in sorted(set(predicates.PRECONDITIONS) - used_pre)]
    unused += [("predicate", n) for n in sorted(set(predicates.PREDICATES) - used_pred)]
    unused += [("args_from", n) for n in sorted(set(predicates.ARGS_FROM) - used_args)]
    return [f"registered rule never used: {kind} {n}" for kind, n in unused]


def check_consistency(policy: Policy, tools: dict[str, ToolSpec]) -> list[str]:
    """Return every disagreement between the policy and the tools (empty = consistent).

    Separate from build_registry, and never raising, so tests can show
    every problem at once.
    """
    return (_check_tools_and_rule_names(policy, tools)
            + _check_mentions(policy)
            + _check_unused_rules(policy))


def build_registry(policy_path: Path) -> Registry:
    """Load the policy, discover the tools and refuse to start if they disagree."""
    policy = load_policy(policy_path)
    tools = discover_tools()
    problems = check_consistency(policy, tools)
    if problems:
        raise RegistryError("tool policy and registered tools disagree:\n  "
                            + "\n  ".join(problems))
    return Registry(policy=policy, tools=tools)
