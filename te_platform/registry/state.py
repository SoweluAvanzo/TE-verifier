## =============================================================================
## te_platform/registry/state.py — the session state machine
## =============================================================================
## GUIDE STEP   2.2 (rules), used by 5.5 and 8.4
## PURPOSE      Computes a session's state (eliciting, spec_ready, verified,
##              simulated, reported) from its stored facts, and lists the
##              tools allowed in that state.
## USED BY      agent/loop.py (offers the model only the allowed tools),
##              agent/chat_api.py (GET /agent/sessions/{id} returns the state, which
##              the chat page shows in the spec panel),
##              tools/elicit_record_answer.py (returns the state after an answer).
## DEPENDS ON   registry/policy.py, registry/predicates.py, registry/context.py.
## WHY          The state is DERIVED, never stored, so it can never disagree
##              with the facts (e.g. a spec edited after verification
##              automatically falls back from `verified` to `spec_ready`).
##              Fewer visible tools per state = better tool choice by the
##              model (architecture D6).
## ACTIVATE     Uncomment; test with SessionFacts fixtures for every state.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep `compute_state` and
## `tools_for_state` exactly as written (te_platform/README.md, contracts
## table). Activate context.py, policy.py and predicates.py first.
##
## Guide 2.2
## [ ] 1. Imports at the top: `CallContext`, `Policy`, and `PREDICATES` from
##        te_platform.registry.predicates.
## [ ] 2. The private list `_ORDER` of state names, most advanced first:
##          | _ORDER = ["reported", "simulated", "verified", "spec_ready",
##        then "eliciting" last.
## [ ] 3. `compute_state(ctx, policy) -> str`: for each name in _ORDER, look
##        up the predicate named by policy.states[name].enter_when in
##        PREDICATES and return the first state whose rule holds; return
##        "eliciting" if none does. One-line docstring.
## [ ] 4. `tools_for_state(state, policy) -> list[str]`: always_available
##        first, then tools_by_state.get(state, []). Skip duplicates and any
##        id in policy.deprecated or policy.planned; keep the order stable
##        (use a list, not a set: the docstring explains why). While every
##        tool is still `planned` (guide 2.2-2.4) the list is empty.
## [ ] 5. Check: activate tests/platform_tests/test_platform_state.py, then
##          | uv run pytest tests/platform_tests/test_platform_state.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from te_platform.registry.context import CallContext
from te_platform.registry.policy import Policy
from te_platform.registry.predicates import PREDICATES

# The states are checked from the MOST advanced to the least: the first whose
# `enter_when` predicate holds is the current state. The order is fixed here
# because the YAML mapping order is not meant to carry meaning.
_ORDER = ["reported", "simulated", "verified", "spec_ready", "eliciting"]


def compute_state(ctx: CallContext, policy: Policy) -> str:
    """Return the most advanced state whose `enter_when` predicate holds."""
    for name in _ORDER:
        rule = PREDICATES[policy.states[name].enter_when]
        if rule(ctx):
            return name
    return "eliciting"


def tools_for_state(state: str, policy: Policy) -> list[str]:
    """Return the tool ids the agent may offer the model in `state`.

    No duplicates, and a stable order: a stable tool list keeps the prompt
    cache valid (agent/providers/anthropic.py). Tools that are deprecated
    or still `planned` (not built yet) are left out, so in the early guide
    steps, when every tool is planned, the list is empty.
    """
    ids = list(policy.always_available) + list(policy.tools_by_state.get(state, []))
    result: list[str] = []
    for tool_id in ids:
        if tool_id in result or tool_id in policy.deprecated or tool_id in policy.planned:
            continue   # duplicates, retired tools and not-yet-built tools are never offered
        result.append(tool_id)
    return result
