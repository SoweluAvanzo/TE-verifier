## =============================================================================
## tests/platform_tests/test_platform_state.py — tests for registry/state.py
## =============================================================================
## GUIDE STEP   2.2 (activate together with state.py)
## PURPOSE      Proves that the session state is derived correctly from the
##              stored facts (one test per state), that editing a verified spec
##              falls back to `spec_ready`, and that the tool list per state is
##              stable, contains the always-available tools exactly once and
##              never offers a tool that is still `planned`.
## DEPENDS ON   te_platform/registry/state.py, policy.py, predicates.py,
##              context.py, the real policy/tool_policy.yaml.
## WHY          The agent offers the model only the tools of the current state
##              (architecture §3.4); a wrong state means wrong tools.
## ACTIVATE     Uncomment with state.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
##
## Guide 2.2
## [ ] 1. Imports: `Path`, `pytest`, `CallContext, Principal,
##        SessionFacts` from registry.context, `load_policy` from
##        registry.policy, `compute_state, tools_for_state` from
##        registry.state (all under te_platform).
## [ ] 2. Fixture `policy()` with scope="module": load_policy of the REAL
##        Path("policy/tool_policy.yaml").
## [ ] 3. Helper `_ctx(**facts) -> CallContext`: principal u1 (kind
##        "user"), tool_id "spec.validate.v1", empty tool_input, and
##        session=SessionFacts(session_id="s1", owner_id="u1", **facts).
## [ ] 4. test_state_is_derived_from_facts(policy, facts, expected): one
##        parametrized (facts, expected) case per state, e.g. {} ->
##        "eliciting", only current_spec_hash -> "spec_ready"; copy the
##        six cases from the solution. The test body is one line:
##          | assert compute_state(_ctx(**facts), policy) == expected
## [ ] 5. test_editing_a_verified_spec_falls_back_to_spec_ready: current
##        hash "spec:b" but verified_spec_hash "spec:a" -> "spec_ready".
## [ ] 6. test_tool_list_contains_always_available_once_and_is_stable: for
##        "verified" the list has no duplicates, contains every
##        always_available tool that is not planned or deprecated, contains
##        no planned or deprecated tool, and is equal on a second call. (It
##        must hold at every guide step: early on, every tool is planned.)
## [ ] 7. The next tests use a copy of the policy with every tool built:
##          | built = policy.model_copy(update={"planned": []})
##        - test_tool_list_order_once_every_tool_is_built: always_available
##          comes first, in its order, then the rest of the state's list;
##        - test_planned_tools_are_never_offered: with only
##          "sim.monte_carlo.v1" planned, it is missing from "verified" and
##          "sim.trajectory.v1" is there;
##        - test_no_simulation_tools_before_verification: in "eliciting"
##          and "spec_ready" no tool id starts with "sim.".
## [ ] 8. Check:
##          | uv run pytest tests/platform_tests/test_platform_state.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from pathlib import Path

import pytest

from te_platform.registry.context import CallContext, Principal, SessionFacts
from te_platform.registry.policy import load_policy
from te_platform.registry.state import compute_state, tools_for_state


@pytest.fixture(scope="module")
def policy():
    return load_policy(Path("policy/tool_policy.yaml"))


def _ctx(**facts) -> CallContext:
    return CallContext(
        principal=Principal(id="u1", kind="user"),
        tool_id="spec.validate.v1",
        tool_input={},
        session=SessionFacts(session_id="s1", owner_id="u1", **facts),
    )


@pytest.mark.parametrize(
    "facts, expected",
    [
        ({}, "eliciting"),
        ({"current_spec_hash": "spec:a", "open_decisive_slots": ["participants.N"]}, "eliciting"),
        ({"current_spec_hash": "spec:a"}, "spec_ready"),
        (
            {
                "current_spec_hash": "spec:a",
                "verification_ref": "vref:1",
                "verified_spec_hash": "spec:a",
            },
            "verified",
        ),
        (
            {
                "current_spec_hash": "spec:a",
                "verification_ref": "vref:1",
                "verified_spec_hash": "spec:a",
                "finished_simulation_for_current_ref": True,
            },
            "simulated",
        ),
        (
            {
                "current_spec_hash": "spec:a",
                "verification_ref": "vref:1",
                "verified_spec_hash": "spec:a",
                "report_for_current_ref": True,
            },
            "reported",
        ),
    ],
)
def test_state_is_derived_from_facts(policy, facts, expected):
    assert compute_state(_ctx(**facts), policy) == expected


def test_editing_a_verified_spec_falls_back_to_spec_ready(policy):
    edited = _ctx(
        current_spec_hash="spec:b", verification_ref="vref:1", verified_spec_hash="spec:a"
    )
    assert compute_state(edited, policy) == "spec_ready"


def test_tool_list_contains_always_available_once_and_is_stable(policy):
    # Holds at every guide step: tools not built yet (`planned`) and
    # retired ones are never offered, every other always-available tool
    # is. In the early steps every tool is planned and the list is empty.
    tools = tools_for_state("verified", policy)
    hidden = set(policy.planned) | set(policy.deprecated)
    assert len(tools) == len(set(tools))
    assert set(policy.always_available) - hidden <= set(tools)
    assert not set(tools) & hidden
    # Stable order keeps the prompt cache valid between turns.
    assert tools == tools_for_state("verified", policy)


## The same rules with every tool built (the end state of the guide), so
## the order and the per-state lists are tested whatever step you are at.
def test_tool_list_order_once_every_tool_is_built(policy):
    built = policy.model_copy(update={"planned": []})
    tools = tools_for_state("verified", built)
    n = len(built.always_available)
    assert tools[:n] == built.always_available
    rest = [t for t in built.tools_by_state["verified"] if t not in built.always_available]
    assert tools[n:] == rest


def test_planned_tools_are_never_offered(policy):
    built = policy.model_copy(update={"planned": ["sim.monte_carlo.v1"]})
    assert "sim.monte_carlo.v1" not in tools_for_state("verified", built)
    assert "sim.trajectory.v1" in tools_for_state("verified", built)


def test_no_simulation_tools_before_verification(policy):
    built = policy.model_copy(update={"planned": []})
    for state in ("eliciting", "spec_ready"):
        assert not any(t.startswith("sim.") for t in tools_for_state(state, built))
