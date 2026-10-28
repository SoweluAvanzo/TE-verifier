## =============================================================================
## tests/platform_tests/test_platform_pipeline.py — one test per branch of registry/pipeline.py
## =============================================================================
## GUIDE STEP   2.4 (activate together with pipeline.py and facts.py); 2.5,
##              5.5, 6.3 (labelled blocks, commented twice)
## PURPOSE      The pipeline is the single path every tool call takes, so each
##              of its outcomes gets an explicit test:
##                unknown tool            -> not_found
##                missing scope           -> forbidden
##                bad input               -> validation_error (with details)
##                step 3b + ref mismatch  -> precondition_failed + do_first
##                overridable rule + reason -> runs
##                non-overridable rule + reason -> still refused
##                slow handler            -> timeout
##                handler raises InvalidInput -> validation_error
##                handler crashes         -> internal_error (no stack trace leaked)
##                invalid output          -> internal_error
##                success                 -> ok + suggested_next (policy
##                                           rules; planned tools never)
##                ref issued by verification -> accepted (facts.py's
##                                           expected ref = the real one)
##                from 5.5: an audit_log row for every outcome (real DB);
##                from 6.3: rate limit and job quota (real Redis)
## DEPENDS ON   te_platform/registry/* (pipeline, facts, loader.Registry,
##              policy, spec, context), te_platform/hashing.py,
##              te_platform/service.py (facts.py validates real examples),
##              anyio's pytest plugin (installed with anyio) for async tests;
##              from 2.5 tools/verify_run.py, from 5.5 a real PostgreSQL
##              (TE_DATABASE_URL), from 6.3 a real Redis (TE_REDIS_URL).
## HOW          A Registry is built DIRECTLY from the real policy and a few
##              test ToolSpecs under real tool ids (no entry points; small
##              handlers written here), so each branch of OUR pipeline code
##              runs for real, in isolation and in milliseconds. Nothing of
##              te_platform is replaced: the handlers are tools, not mocks.
## WHY          Architecture D4/D7 and guide §2.1: rules enforced in one place,
##              errors as values; this file proves both.
## ACTIVATE     Uncomment with pipeline.py + facts.py; the blocks labelled
##              Guide 2.5, 5.5 and 6.3 at those steps (commented twice).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
##
## Guide 2.4
## [ ] 1. Imports: Path, Any, uuid4, anyio, pytest, BaseModel, and from
##        te_platform: hashing, service, config.get_settings,
##        errors.InvalidInput, registry.context (CallContext, Principal,
##        SessionFacts), registry.loader.Registry, registry.pipeline.call,
##        registry.policy (Policy, load_policy), registry.spec.ToolSpec.
## [ ] 2. Fixture `anyio_backend()` returning "asyncio" (see its `##`
##        note). Mark every async test with @pytest.mark.anyio.
## [ ] 3. Fixture `settings_env(monkeypatch)`: yields a function that sets
##        TE_* variables and clears get_settings' cache; after the test it
##        clears the cache again, so changed settings never leak.
## [ ] 4. Constants POLICY (load_policy of the real file), BUILT (POLICY
##        with `planned` emptied: every tool counts as built), BITCOIN and
##        TIME_BANK (the text of examples/bitcoin.yaml, time_bank.yaml).
## [ ] 5. Test models: `In` (spec: str | None = None, verification_ref:
##        str | None = None, n: int = 0), `Out` (value: int) and
##        `VerdictsOut` (verification_ref: str, verdicts: list of dicts).
##        Keep the names `spec` and `verification_ref`: facts.py reads them.
## [ ] 6. Six small async handlers `(inp: In, ctx: CallContext)`:
##        ok_handler returns Out(value=inp.n); slow_handler awaits
##        anyio.sleep(5); bad_output_handler returns a wrongly shaped dict;
##        crashing_handler raises RuntimeError("secret internal detail");
##        invalid_input_handler raises InvalidInput("Pass a spec.");
##        verdicts_handler returns VerdictsOut with one failing FM5 verdict.
## [ ] 7. Helper `make_registry(policy=POLICY, out=Out, **handlers)`: a
##        Registry of the policy plus ToolSpec(id=tid, input_model=In,
##        output_model=out, handler=h) per keyword. Tool ids contain dots:
##          | make_registry(**{"graph.flow.v1": ok_handler})
## [ ] 8. Helper `make_ctx(tool_id, *, scopes=frozenset(), session=None,
##        override=None) -> CallContext` with a NEW principal id per call
##        (uuid4), so per-caller limits (6.3) never mix tests.
## [ ] 9. Refusals, one test per branch (header PURPOSE), each awaiting
##        call(reg, tool_id, raw_input, make_ctx(...)):
##        - test_unknown_tool_is_not_found: "nope.v1" -> "not_found";
##        - test_missing_scope_is_forbidden: scopes {"verify"} calling
##          graph.flow.v1 -> "forbidden";
##        - test_bad_input_is_validation_error_with_details: n is a string
##          -> "validation_error" with error.details set;
##        - test_simulation_with_ref_from_another_spec_is_refused: a ref
##          built with hashing from another spec -> precondition
##          "verification_ref_matches_spec", do_first ["verify.run.v1"];
##        - test_simulation_without_verification_is_refused_with_do_first:
##          TIME_BANK and no ref -> precondition "verified_spec" + do_first.
## [ ] 10. test_ref_issued_by_verification_is_accepted: the ref of
##        service.verify(BITCOIN) lets a sim.monte_carlo.v1 call run.
## [ ] 11. Overrides:
##        - test_override_skips_an_overridable_precondition: a session
##          with an open decisive slot plus an override reason -> out.ok;
##        - test_override_cannot_skip_a_non_overridable_precondition: a
##          wrong ref plus override -> still "verification_ref_matches_spec".
## [ ] 12. test_slow_handler_times_out(settings_env): TE_TOOL_TIMEOUT_S =
##        "0.05" -> "timeout".
## [ ] 13. Handler failures:
##        - test_invalid_input_from_handler_is_validation_error: code
##          "validation_error" and message "Pass a spec.";
##        - test_crash_is_internal_error_without_leaking_details: code
##          "internal_error", the RuntimeError text is not in the message,
##          error.correlation_id == out.correlation_id;
##        - test_invalid_output_is_internal_error.
## [ ] 14. Success:
##        - test_success_returns_result_and_correlation_id: n=7 gives
##          | assert out.ok and out.result == {"value": 7}
##          a non-empty correlation_id and suggested_next == [] (no policy
##          rule follows graph.flow.v1);
##        - test_suggestions_follow_the_policy_rules: verdicts_handler as
##          verify.run.v1 with BUILT -> lit.search.v1 (query names FM5)
##          and report.render_pdf.v1, in policy order;
##        - test_planned_tool_is_never_suggested: the same with
##          lit.search.v1 planned -> only report.render_pdf.v1.
## [ ] 15. Check:
##          | uv run pytest tests/platform_tests/test_platform_pipeline.py -q
##
## Guide 2.5 (later: the "# # " block under its label)
## [ ] 16. test_real_verification_ref_is_accepted: the REAL verify.run.v1
##        tool has no `config` input, its ref equals the one facts.py
##        expects, and a simulation call with that ref passes step 3b+4.
##
## Guide 5.5 (later: the "# # " block under its label)
## [ ] 17. test_every_outcome_writes_an_audit_row (marked db): a refused
##        call leaves one audit_log row with its correlation_id, outcome
##        "precondition_failed" and the hash of its input, read back
##        with session_scope and a select on db.models.AuditEntry.
##
## Guide 6.3 (later: the "# # " blocks under their labels)
## [ ] 18. test_rate_limit_refuses_the_call_over_the_limit: with
##        TE_MAX_TOOL_CALLS_PER_MINUTE=2 the third call of one principal
##        is "quota_exceeded" (real Redis).
## [ ] 19. test_job_quota_is_a_precondition_of_job_tools: with
##        TE_MAX_JOBS_PER_DAY=0 a verified simulation call is refused by
##        "job_quota_available".
## [ ] 20. Check: the step 15 command, with TE_DATABASE_URL (5.5) and
##        TE_REDIS_URL (6.3) pointing at the running services.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from pathlib import Path
from typing import Any
from uuid import uuid4

import anyio
import pytest
from pydantic import BaseModel

from te_platform import hashing, service
from te_platform.config import get_settings
from te_platform.errors import InvalidInput
from te_platform.registry.context import CallContext, Principal, SessionFacts
from te_platform.registry.loader import Registry
from te_platform.registry.pipeline import call
from te_platform.registry.policy import Policy, load_policy
from te_platform.registry.spec import ToolSpec


## anyio's pytest plugin runs `async def` tests marked with @pytest.mark.anyio;
## this fixture chooses the asyncio event loop for them.
@pytest.fixture
def anyio_backend():
    return "asyncio"


## Settings are read once and cached (config.get_settings). A test that
## changes a TE_* variable must clear the cache before AND after, or the
## change would leak into later tests. Teardown order: this fixture clears
## the cache first, then monkeypatch restores the variables.
@pytest.fixture
def settings_env(monkeypatch):
    def set_env(**env: str) -> None:
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield set_env
    get_settings.cache_clear()


POLICY = load_policy(Path("policy/tool_policy.yaml"))
## The same rules with every tool counted as built: suggestion tests must
## not depend on how far the guide has got (planned tools are never
## suggested, see test_planned_tool_is_never_suggested).
BUILT = POLICY.model_copy(update={"planned": []})
BITCOIN = Path("examples/bitcoin.yaml").read_text()
TIME_BANK = Path("examples/time_bank.yaml").read_text()


## --- Test tools ------------------------------------------------------------------------------
## The input model uses the conventional field names facts.py looks for
## (`spec`, `verification_ref`), like the real tools do.
class In(BaseModel):
    spec: str | None = None
    verification_ref: str | None = None
    n: int = 0


class Out(BaseModel):
    value: int


class VerdictsOut(BaseModel):
    verification_ref: str
    verdicts: list[dict[str, Any]]


async def ok_handler(inp: In, ctx: CallContext) -> Out:
    return Out(value=inp.n)


async def slow_handler(inp: In, ctx: CallContext) -> Out:
    await anyio.sleep(5)
    return Out(value=0)


async def bad_output_handler(inp: In, ctx: CallContext) -> Any:
    return {"wrong": "shape"}


async def crashing_handler(inp: In, ctx: CallContext) -> Out:
    raise RuntimeError("secret internal detail")


async def invalid_input_handler(inp: In, ctx: CallContext) -> Out:
    raise InvalidInput("Pass a spec.")


async def verdicts_handler(inp: In, ctx: CallContext) -> VerdictsOut:
    return VerdictsOut(
        verification_ref="vref:1",
        verdicts=[{"failure_mode": "FM5", "status": "fail", "structural_status": "broken"}],
    )


def make_registry(policy: Policy = POLICY, out: type[BaseModel] = Out, **handlers) -> Registry:
    """The given policy + test ToolSpecs under real tool ids (so the real
    preconditions and suggestion rules apply)."""
    tools = {
        tid: ToolSpec(id=tid, input_model=In, output_model=out, handler=h)
        for tid, h in handlers.items()
    }
    return Registry(policy=policy, tools=tools)


def make_ctx(tool_id: str, *, scopes=frozenset(), session=None, override=None) -> CallContext:
    # A new caller per context: per-principal limits (guide 6.3) never mix tests.
    principal = Principal(id=f"test-{uuid4().hex[:12]}", kind="user", scopes=scopes)
    return CallContext(
        principal=principal,
        tool_id=tool_id,
        tool_input={},
        session=session,
        override_reason=override,
    )


## --- Refusals -------------------------------------------------------------------------------
@pytest.mark.anyio
async def test_unknown_tool_is_not_found():
    out = await call(make_registry(), "nope.v1", {}, make_ctx("nope.v1"))
    assert not out.ok and out.error.error == "not_found"


@pytest.mark.anyio
async def test_missing_scope_is_forbidden():
    reg = make_registry(**{"graph.flow.v1": ok_handler})
    ctx = make_ctx("graph.flow.v1", scopes=frozenset({"verify"}))
    out = await call(reg, "graph.flow.v1", {"spec": BITCOIN}, ctx)
    assert out.error.error == "forbidden"


@pytest.mark.anyio
async def test_bad_input_is_validation_error_with_details():
    reg = make_registry(**{"graph.flow.v1": ok_handler})
    out = await call(reg, "graph.flow.v1", {"n": "not-a-number"}, make_ctx("graph.flow.v1"))
    assert out.error.error == "validation_error" and out.error.details


@pytest.mark.anyio
async def test_simulation_with_ref_from_another_spec_is_refused():
    # Step 3b recomputes the ref from THIS spec; a ref computed from a
    # different spec cannot match (architecture D5).
    other = hashing.verification_ref(
        hashing.spec_hash({"other": "spec"}), hashing.verifier_version(), hashing.config_hash(None)
    )
    reg = make_registry(**{"sim.monte_carlo.v1": ok_handler})
    out = await call(
        reg,
        "sim.monte_carlo.v1",
        {"spec": BITCOIN, "verification_ref": other},
        make_ctx("sim.monte_carlo.v1"),
    )
    assert out.error.error == "precondition_failed"
    assert out.error.precondition == "verification_ref_matches_spec"
    assert out.error.do_first == ["verify.run.v1"]


@pytest.mark.anyio
async def test_simulation_without_verification_is_refused_with_do_first():
    reg = make_registry(**{"sim.monte_carlo.v1": ok_handler})
    out = await call(reg, "sim.monte_carlo.v1", {"spec": TIME_BANK}, make_ctx("sim.monte_carlo.v1"))
    assert out.error.precondition == "verified_spec" and out.error.do_first == ["verify.run.v1"]


## The other direction: a ref really issued for this spec passes step 3b
## and every precondition (facts.py recomputes exactly the verifier's ref).
@pytest.mark.anyio
async def test_ref_issued_by_verification_is_accepted():
    ref = service.verify(BITCOIN).verification_ref
    reg = make_registry(**{"sim.monte_carlo.v1": ok_handler})
    out = await call(
        reg,
        "sim.monte_carlo.v1",
        {"spec": BITCOIN, "verification_ref": ref, "n": 3},
        make_ctx("sim.monte_carlo.v1"),
    )
    assert out.ok and out.result == {"value": 3}


## --- Overrides ------------------------------------------------------------------------------
@pytest.mark.anyio
async def test_override_skips_an_overridable_precondition():
    # decisive_slots_resolved is overridable: with a reason, verification runs
    # although the interview still has an open decisive question.
    reg = make_registry(**{"verify.run.v1": ok_handler})
    s = SessionFacts(session_id="s1", owner_id="u1", open_decisive_slots=["participants.N"])
    out = await call(
        reg,
        "verify.run.v1",
        {"spec": BITCOIN, "n": 1},
        make_ctx("verify.run.v1", session=s, override="user wants a first look"),
    )
    assert out.ok


@pytest.mark.anyio
async def test_override_cannot_skip_a_non_overridable_precondition():
    reg = make_registry(**{"sim.monte_carlo.v1": ok_handler})
    other = hashing.verification_ref(
        "spec:x", hashing.verifier_version(), hashing.config_hash(None)
    )
    out = await call(
        reg,
        "sim.monte_carlo.v1",
        {"spec": BITCOIN, "verification_ref": other},
        make_ctx("sim.monte_carlo.v1", override="please"),
    )
    assert out.error.precondition == "verification_ref_matches_spec"


## --- Handler failures -----------------------------------------------------------------------
@pytest.mark.anyio
async def test_slow_handler_times_out(settings_env):
    settings_env(TE_TOOL_TIMEOUT_S="0.05")
    reg = make_registry(**{"graph.flow.v1": slow_handler})
    out = await call(reg, "graph.flow.v1", {"spec": BITCOIN}, make_ctx("graph.flow.v1"))
    assert out.error.error == "timeout"


@pytest.mark.anyio
async def test_invalid_input_from_handler_is_validation_error():
    reg = make_registry(**{"graph.flow.v1": invalid_input_handler})
    out = await call(reg, "graph.flow.v1", {"spec": BITCOIN}, make_ctx("graph.flow.v1"))
    assert out.error.error == "validation_error" and out.error.message == "Pass a spec."


@pytest.mark.anyio
async def test_crash_is_internal_error_without_leaking_details():
    reg = make_registry(**{"graph.flow.v1": crashing_handler})
    out = await call(reg, "graph.flow.v1", {"spec": BITCOIN}, make_ctx("graph.flow.v1"))
    assert out.error.error == "internal_error"
    assert "secret internal detail" not in out.error.message
    assert out.error.correlation_id == out.correlation_id


@pytest.mark.anyio
async def test_invalid_output_is_internal_error():
    reg = make_registry(**{"graph.flow.v1": bad_output_handler})
    out = await call(reg, "graph.flow.v1", {"spec": BITCOIN}, make_ctx("graph.flow.v1"))
    assert out.error.error == "internal_error"


## --- Success and suggested_next -------------------------------------------------------------
@pytest.mark.anyio
async def test_success_returns_result_and_correlation_id():
    reg = make_registry(**{"graph.flow.v1": ok_handler})
    out = await call(reg, "graph.flow.v1", {"spec": BITCOIN, "n": 7}, make_ctx("graph.flow.v1"))
    assert out.ok and out.result == {"value": 7} and out.correlation_id
    assert out.suggested_next == []  # no policy rule follows graph.flow.v1


@pytest.mark.anyio
async def test_suggestions_follow_the_policy_rules():
    # One failing verdict: the policy suggests literature (any_fail, with
    # arguments) and a report (all_decided), in the order of its rules.
    reg = make_registry(BUILT, VerdictsOut, **{"verify.run.v1": verdicts_handler})
    out = await call(reg, "verify.run.v1", {"spec": BITCOIN}, make_ctx("verify.run.v1"))
    assert [s.tool for s in out.suggested_next] == ["lit.search.v1", "report.render_pdf.v1"]
    assert "FM5" in out.suggested_next[0].args["query"]
    assert out.suggested_next[1].args == {}


@pytest.mark.anyio
async def test_planned_tool_is_never_suggested():
    policy = BUILT.model_copy(update={"planned": ["lit.search.v1"]})
    reg = make_registry(policy, VerdictsOut, **{"verify.run.v1": verdicts_handler})
    out = await call(reg, "verify.run.v1", {"spec": BITCOIN}, make_ctx("verify.run.v1"))
    assert [s.tool for s in out.suggested_next] == ["report.render_pdf.v1"]


## Guide 2.5: the REAL verify.run.v1 tool (commented twice until then).
## facts.py assumes that verify.run.v1 always verifies with the paper
## defaults (config_hash(None)); this test fails if that ever changes.
@pytest.mark.anyio
async def test_real_verification_ref_is_accepted():
    from te_platform.tools.verify_run import TOOL as VERIFY_RUN

    assert "config" not in VERIFY_RUN.input_model.model_fields
    reg = Registry(policy=POLICY, tools={"verify.run.v1": VERIFY_RUN})
    out = await call(reg, "verify.run.v1", {"spec": BITCOIN}, make_ctx("verify.run.v1"))
    assert out.ok
    spec_hash = service.validate(BITCOIN).spec_hash
    expected = hashing.verification_ref(
        spec_hash, hashing.verifier_version(), hashing.config_hash(None)
    )
    assert out.result["verification_ref"] == expected
    sim = make_registry(**{"sim.monte_carlo.v1": ok_handler})
    args = {"spec": BITCOIN, "verification_ref": out.result["verification_ref"]}
    assert (await call(sim, "sim.monte_carlo.v1", args, make_ctx("sim.monte_carlo.v1"))).ok


## Guide 5.5: the audit_log row (commented twice until then). Needs the
## real PostgreSQL of TE_DATABASE_URL, like test_platform_db.py.
@pytest.mark.db
@pytest.mark.anyio
async def test_every_outcome_writes_an_audit_row():
    from sqlalchemy import select
    from te_platform.db import models as m
    from te_platform.db.session import session_scope

    reg = make_registry(**{"sim.monte_carlo.v1": ok_handler})
    ctx = make_ctx("sim.monte_carlo.v1")
    out = await call(reg, "sim.monte_carlo.v1", {"spec": TIME_BANK}, ctx)
    assert out.error.error == "precondition_failed"  # refusals are audited too
    with session_scope() as db:
        rows = db.scalars(
            select(m.AuditEntry).where(m.AuditEntry.correlation_id == ctx.correlation_id)
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert (row.principal_id, row.tool_id) == (ctx.principal.id, "sim.monte_carlo.v1")
        assert row.outcome == "precondition_failed"
        # The input is stored only as its hash, never as text.
        raw = {"spec": TIME_BANK}
        assert row.input_hash == "in:" + hashing.sha256_hex(hashing.canonical_json(raw))


## Guide 6.3: the rate limit of step 2 (commented twice until then). Uses
## the real Redis of TE_REDIS_URL; the principal is new, so its counter is.
@pytest.mark.anyio
async def test_rate_limit_refuses_the_call_over_the_limit(settings_env):
    settings_env(TE_MAX_TOOL_CALLS_PER_MINUTE="2")
    reg = make_registry(**{"graph.flow.v1": ok_handler})
    ctx = make_ctx("graph.flow.v1")
    codes = []
    for _ in range(3):
        c = ctx.model_copy(update={"correlation_id": uuid4().hex})
        out = await call(reg, "graph.flow.v1", {"spec": BITCOIN}, c)
        codes.append("ok" if out.ok else out.error.error)
    assert codes == ["ok", "ok", "quota_exceeded"]


## Guide 6.3: the job quota of step 2, enforced as a precondition.
@pytest.mark.anyio
async def test_job_quota_is_a_precondition_of_job_tools(settings_env):
    settings_env(TE_MAX_JOBS_PER_DAY="0")
    ref = service.verify(BITCOIN).verification_ref
    reg = make_registry(**{"sim.monte_carlo.v1": ok_handler})
    out = await call(
        reg,
        "sim.monte_carlo.v1",
        {"spec": BITCOIN, "verification_ref": ref},
        make_ctx("sim.monte_carlo.v1"),
    )
    assert out.error.precondition == "job_quota_available"
    assert out.error.do_first == ["jobs.status.v1"]
