## =============================================================================
## tests/platform_tests/test_platform_policy.py — tests for registry/policy.py and the policy file
## =============================================================================
## GUIDE STEP   2.1 (activate together with registry/policy.py)
## PURPOSE      - the REAL policy/tool_policy.yaml loads into the typed models;
##              - a policy with an unknown key is rejected (typos cannot
##                silently disable a rule);
##              - internal cross-references of the file are consistent (every
##                tool named anywhere is defined, every precondition used is
##                declared, every state has a tool list).
##              This file is also run by the pre-commit hook
##              `policy-consistency` whenever policy/ or registry/ changes.
## DEPENDS ON   te_platform/registry/policy.py, policy/tool_policy.yaml, PyYAML.
## WHY          Architecture D3: the policy is reviewed data; these tests make
##              review mistakes fail fast.
## ACTIVATE     Uncomment with policy.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
##
## Guide 2.1
## [ ] 1. Imports: `Path`, `pytest`, `yaml`, `ValidationError` from
##        pydantic, `Policy, load_policy` from te_platform.registry.policy.
##        Constant POLICY_PATH = Path("policy/tool_policy.yaml").
## [ ] 2. Fixture `policy() -> Policy` with scope="module" (loaded once
##        for the file) returning load_policy(POLICY_PATH).
## [ ] 3. test_real_policy_loads: policy_version is set and
##        "verify.run.v1" is in policy.tools.
## [ ] 4. test_unknown_key_is_rejected(tmp_path): yaml.safe_load the real
##        file, add a misspelled key to one tool, write it to tmp_path, and
##        expect ValidationError from load_policy:
##          | raw["tools"]["verify.run.v1"]["precondtions"] = []
## [ ] 5. test_every_referenced_tool_is_defined: collect every tool id the
##        policy mentions (always_available, tools_by_state, the `after`
##        and `suggest` of suggested_next, typical_next, preconditions'
##        do_first); none may be missing from policy.tools.
## [ ] 6. test_every_tool_is_offered_in_some_state: every policy tool is in
##        always_available or in some tools_by_state list.
## [ ] 7. test_preconditions_used_are_declared: every precondition a tool
##        uses, and every overridable_preconditions entry, is declared
##        under policy.preconditions.
## [ ] 8. test_states_and_tool_lists_match: set(policy.states) ==
##        set(policy.tools_by_state).
## [ ] 9. test_verification_is_never_blocked_by_coherence_issues: the
##        preconditions of verify.run.v1 are exactly ["valid_spec",
##        "decisive_slots_resolved"] (why: the solution's comment).
## [ ] 10. test_simulation_requires_verification_of_this_spec: for
##        sim.monte_carlo.v1 and sim.trajectory.v1 the preconditions
##        include "verified_spec" and "verification_ref_matches_spec".
## [ ] 11. Check (the pre-commit hook `policy-consistency` runs it too):
##          | uv run pytest tests/platform_tests/test_platform_policy.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from te_platform.registry.policy import Policy, load_policy

POLICY_PATH = Path("policy/tool_policy.yaml")


@pytest.fixture(scope="module")
def policy() -> Policy:
    return load_policy(POLICY_PATH)


def test_real_policy_loads(policy):
    assert policy.policy_version
    assert "verify.run.v1" in policy.tools


def test_unknown_key_is_rejected(tmp_path):
    raw = yaml.safe_load(POLICY_PATH.read_text())
    raw["tools"]["verify.run.v1"]["precondtions"] = []  # deliberate typo
    bad = tmp_path / "policy.yaml"
    bad.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValidationError):
        load_policy(bad)


def test_every_referenced_tool_is_defined(policy):
    tools = set(policy.tools)
    referenced = set(policy.always_available)
    referenced |= {t for ids in policy.tools_by_state.values() for t in ids}
    referenced |= {r.after for r in policy.suggested_next} | {
        r.suggest for r in policy.suggested_next
    }
    referenced |= {n for t in policy.tools.values() for n in t.typical_next}
    referenced |= {d for p in policy.preconditions.values() for d in p.do_first}
    assert referenced - tools == set()


def test_every_tool_is_offered_in_some_state(policy):
    offered = set(policy.always_available) | {
        t for ids in policy.tools_by_state.values() for t in ids
    }
    assert set(policy.tools) - offered == set()


def test_preconditions_used_are_declared(policy):
    declared = set(policy.preconditions)
    used = {p for t in policy.tools.values() for p in t.preconditions}
    assert used - declared == set()
    assert set(policy.overridable_preconditions) <= declared


def test_states_and_tool_lists_match(policy):
    assert set(policy.states) == set(policy.tools_by_state)


def test_verification_is_never_blocked_by_coherence_issues(policy):
    # Coherence issues are findings to discuss, not blockers: some case
    # studies (e.g. examples/bitcoin.yaml) carry error-level issues and must
    # still be verifiable.
    assert policy.tools["verify.run.v1"].preconditions == ["valid_spec", "decisive_slots_resolved"]


def test_simulation_requires_verification_of_this_spec(policy):
    # Formal methods first (architecture P2), enforced by the server (D4).
    for tid in ("sim.monte_carlo.v1", "sim.trajectory.v1"):
        pre = policy.tools[tid].preconditions
        assert "verified_spec" in pre and "verification_ref_matches_spec" in pre
