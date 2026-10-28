## =============================================================================
## tests/platform_tests/test_platform_registry.py — tools vs policy consistency (registry/loader.py)
## =============================================================================
## GUIDE STEP   2.3 (activate together with registry/loader.py); 2.5, 2.6
##              (labelled blocks, commented twice)
## PURPOSE      - check_consistency() finds every kind of mismatch (tested with
##                small artificial inputs);
##              - the REAL registered tools and the REAL policy agree, apart
##                from the tools whose phase has not been activated yet;
##              - build_registry() refuses an inconsistent policy;
##              - (guide 2.5) the first five tools are discovered;
##              - (guide 2.6) describe() renders every tool exactly as the
##                reviewed snapshot snapshots/tool_descriptions.txt.
## DEPENDS ON   te_platform/registry/loader.py, policy.py, predicates.py,
##              spec.py; the entry points in pyproject.toml (copied from
##              te_platform/pyproject_additions.toml); from 2.6 describe.py
##              and snapshots/tool_descriptions.txt.
## WHY          Architecture D6/P6: a tool exists only if it has BOTH code and
##              rules. This test turns "forgot one of the two" into a red CI.
## INCREMENTAL ACTIVATION
##              The policy lists all 13 tools from the start, but tools are
##              implemented phase by phase (2.5, 6.2, 7.4-7.5, 10.3, 11.2).
##              Tools not built yet are listed under `planned:` in
##              policy/tool_policy.yaml; the registry tolerates exactly those.
##              Remove an id from `planned` when you activate its tool: the
##              consistency check fails if a built tool is still planned, so
##              the list cannot go stale.
## ACTIVATE     Uncomment with loader.py (guide 2.3). The tests do not need
##              any built tool: they build a small ToolSpec themselves. The
##              blocks labelled Guide 2.5 and 2.6 (commented twice) follow
##              at those steps.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
##
## Guide 2.3
## [ ] 1. Imports: `Path`, `pytest`, `yaml`, `BaseModel` from pydantic,
##        `RegistryError, build_registry, check_consistency, discover_tools`
##        from te_platform.registry.loader, `load_policy` from
##        te_platform.registry.policy, `ToolSpec` from
##        te_platform.registry.spec.
## [ ] 2. Fixture `policy()` with scope="module" loading the real
##        policy/tool_policy.yaml.
## [ ] 3. A tiny tool for the artificial inputs: models `_In`, `_Out` and
##        `_tool(tool_id) -> ToolSpec` with an async handler returning
##        _Out(). It is data for check_consistency, never run.
## [ ] 4. test_real_tools_and_policy_agree: check_consistency(policy,
##        discover_tools()) == [] (true only while `planned` is up to date,
##        header INCREMENTAL ACTIVATION).
## [ ] 5. test_built_tool_still_planned_is_reported: a copy of the policy
##        with "verify.run.v1" in `planned`, tools {"verify.run.v1":
##        _tool(...)}; expect "tool registered but still listed as
##        planned: verify.run.v1".
##          | stale = policy.model_copy(update={"planned": [...]})
## [ ] 6. test_registered_tool_missing_from_policy_is_reported: tools
##        {"made.up.v1": _tool("made.up.v1")}; expect "tool registered but
##        missing from policy: made.up.v1".
## [ ] 7. test_entry_point_names_equal_tool_ids: for each (tid, spec) of
##        discover_tools(), spec.id == tid.
## [ ] 8. test_unknown_tool_in_a_state_list_is_reported: add
##        "verify.run.v2" to always_available; expect "always_available:
##        unknown tool verify.run.v2".
## [ ] 9. test_unused_registered_rule_is_reported(policy, monkeypatch):
##        monkeypatch.setitem a "never_used" entry into
##        predicates.PREDICATES (a temporary extra entry, removed after the
##        test); expect "registered rule never used: predicate never_used".
##        Expected messages must match loader.py's text exactly.
## [ ] 10. test_build_registry_refuses_an_inconsistent_policy(tmp_path):
##        the real file with "made.up.v1" added to `planned`, written to
##        tmp_path; build_registry raises RegistryError naming
##        "planned tool missing from policy tools: made.up.v1".
## [ ] 11. Check:
##          | uv run pytest tests/platform_tests/test_platform_registry.py -q
##
## Guide 2.5 (later: the "# # " block under its label)
## [ ] 12. test_first_tools_are_discovered: the five tools of guide 2.5
##        (spec.validate, verify.run, verify.minimal, graph.flow,
##        export.cadcad, all .v1) are in discover_tools(): their entry
##        points are installed.
##
## Guide 2.6 (later: the "# # " block under its label)
## [ ] 13. test_tool_descriptions_match_the_snapshot: render
##        "### <id>\n<describe(id, policy)>\n\n" for every policy tool,
##        sorted by id, and compare with snapshots/tool_descriptions.txt
##        next to this file. With TE_UPDATE_SNAPSHOTS=1 the test rewrites
##        the file first (after a deliberate policy change; review the diff).
##        Keep the block free of blank lines: each run of "# # " lines
##        needs its own label.
## [ ] 14. Check: the step 11 command.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from te_platform.registry.loader import (
    RegistryError,
    build_registry,
    check_consistency,
    discover_tools,
)
from te_platform.registry.policy import load_policy
from te_platform.registry.spec import ToolSpec

POLICY_PATH = Path("policy/tool_policy.yaml")


@pytest.fixture(scope="module")
def policy():
    return load_policy(POLICY_PATH)


## A tiny tool used as DATA for check_consistency (never run): the checks
## must work before any real tool is built (guide 2.3).
class _In(BaseModel):
    pass


class _Out(BaseModel):
    pass


async def _handler(inp: _In, ctx) -> _Out:
    return _Out()


def _tool(tool_id: str) -> ToolSpec:
    return ToolSpec(id=tool_id, input_model=_In, output_model=_Out, handler=_handler)


def test_real_tools_and_policy_agree(policy):
    # With `planned` kept up to date, the real tools and policy agree exactly.
    assert check_consistency(policy, discover_tools()) == []


def test_built_tool_still_planned_is_reported(policy):
    stale = policy.model_copy(update={"planned": [*policy.planned, "verify.run.v1"]})
    problems = check_consistency(stale, {"verify.run.v1": _tool("verify.run.v1")})
    assert "tool registered but still listed as planned: verify.run.v1" in problems


def test_registered_tool_missing_from_policy_is_reported(policy):
    problems = check_consistency(policy, {"made.up.v1": _tool("made.up.v1")})
    assert "tool registered but missing from policy: made.up.v1" in problems


def test_entry_point_names_equal_tool_ids():
    # discover_tools() raises if an entry point's name differs from the
    # ToolSpec.id it points to; reaching here means all names match.
    for tid, spec in discover_tools().items():
        assert spec.id == tid


## A misspelled tool id anywhere in the policy is reported at startup.
def test_unknown_tool_in_a_state_list_is_reported(policy):
    typo = policy.model_copy(
        update={"always_available": [*policy.always_available, "verify.run.v2"]}
    )
    assert "always_available: unknown tool verify.run.v2" in check_consistency(
        typo, discover_tools()
    )


## A rule registered in predicates.py but used nowhere is reported too.
## monkeypatch.setitem adds a temporary entry to the real table and removes
## it after the test; no code of ours is replaced.
def test_unused_registered_rule_is_reported(policy, monkeypatch):
    from te_platform.registry import predicates

    monkeypatch.setitem(predicates.PREDICATES, "never_used", lambda ctx: True)
    assert "registered rule never used: predicate never_used" in check_consistency(
        policy, discover_tools()
    )


## build_registry() is what the servers call at startup: a broken policy
## file must stop them with every problem listed.
def test_build_registry_refuses_an_inconsistent_policy(tmp_path):
    raw = yaml.safe_load(POLICY_PATH.read_text())
    raw["planned"] = [*raw["planned"], "made.up.v1"]
    bad = tmp_path / "policy.yaml"
    bad.write_text(yaml.safe_dump(raw))
    with pytest.raises(RegistryError, match="planned tool missing from policy tools: made.up.v1"):
        build_registry(bad)


## Guide 2.5: the first five tools and their entry points (commented twice).
def test_first_tools_are_discovered():
    first = {
        "spec.validate.v1",
        "verify.run.v1",
        "verify.minimal.v1",
        "graph.flow.v1",
        "export.cadcad.v1",
    }
    assert first <= set(discover_tools())


## Guide 2.6: describe.py's snapshot (commented twice until then). The file
## is reviewed like code: a changed description changes what the model
## reads, so the diff must show up in the pull request.
def test_tool_descriptions_match_the_snapshot(policy):
    import os
    from te_platform.registry.describe import describe

    snapshot = Path(__file__).parent / "snapshots" / "tool_descriptions.txt"
    text = "".join(f"### {tid}\n{describe(tid, policy)}\n\n" for tid in sorted(policy.tools))
    if os.environ.get("TE_UPDATE_SNAPSHOTS") == "1":
        snapshot.parent.mkdir(exist_ok=True)
        snapshot.write_text(text, encoding="utf-8")
    assert snapshot.read_text(encoding="utf-8") == text, (
        "tool descriptions changed: review them, then regenerate with TE_UPDATE_SNAPSHOTS=1"
    )
