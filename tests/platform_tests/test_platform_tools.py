## =============================================================================
## tests/platform_tests/test_platform_tools.py — contract and golden tests for te_platform/tools/
## =============================================================================
## GUIDE STEP   2.5 (first tools), 5.5 (the store of verify.run.v1),
##              6.2 (job tools), 7.4-7.5 (elicitation tools),
##              10.3 (report tool), 11.2 (literature tool)
## PURPOSE      Three kinds of tests, explained once here:
##              - CONTRACT tests: every tool module exports a ToolSpec whose
##                id matches its entry point and its module name, and every
##                input and output survives a round trip (model -> JSON ->
##                model) in every call these tests make;
##              - GOLDEN tests: running a tool on each examples/*.yaml gives
##                the same result as the existing CLI / web API, so the new
##                platform cannot silently change the verifier's answers;
##              - BEHAVIOUR tests: one per rule of the tool (e.g. "simulation
##                before verification is refused").
##              Tools are called THROUGH the pipeline (registry.pipeline.call),
##              exactly as MCP clients call them, so the preconditions are
##              tested too.
## SERVICES     No mocks: from guide 5.5 the tests use the real PostgreSQL
##              (TE_DATABASE_URL, tests marked `db`), from 6.2 the real Redis
##              (TE_REDIS_URL). Background jobs are run by RQ's SimpleWorker,
##              the real worker class running the jobs inside the test process
##              instead of in a separate `te-worker` container.
##              Each test acts as its own new principal (a random id), so
##              per-user quotas and job reuse never leak between tests.
## RUN          uv run pytest tests/platform_tests/test_platform_tools.py -v
## NOTE         0 tests are collected while everything is commented out.
##              Later steps are commented twice under "Guide X.Y" labels:
##              toggle them a second time when you reach that step.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
## Header PURPOSE explains contract, golden and behaviour tests.
##
## Guide 2.5
## [ ] 1. Imports: json, subprocess, sys, entry_points (importlib.metadata),
##        Path, Any, uuid4, pytest, `hashing` and `service` from
##        te_platform, CallContext, Principal and SessionFacts
##        (registry.context), Registry and build_registry (registry.loader),
##        ToolOutcome and call (registry.pipeline), and the Flask app:
##          | from webapp.app import app as web_app
##        Constants: REPO (the repository root, from __file__), EXAMPLES
##        (sorted examples/*.yaml) and POLICY (policy/tool_policy.yaml).
## [ ] 2. Fixture `registry()` with scope="module": build_registry(POLICY),
##        the same startup work the MCP server does.
## [ ] 3. Helpers: `_new_principal()` (a Principal with a random id),
##        `_round_trip(model_cls, data)` (validate, dump to JSON, read back,
##        compare) and `async def _call(registry, tool_id, tool_input, *,
##        principal=None, session=None) -> ToolOutcome`, which awaits the
##        pipeline's call() as MCP clients do and round-trips the input and
##        the result of every successful call. `_cli(*args)` runs the
##        existing CLI with `sys.executable -m verifier.cli` (not the
##        `te-verify` script: the test must not depend on PATH).
## [ ] 4. test_every_tool_matches_its_entry_point: the entry points equal
##        the registry's tools; each points to that TOOL, in the module
##          | "te_platform.tools." + "_".join(tool_id.split(".")[:-1])
##        and both JSON schemas are generable.
## [ ] 5. test_examples_are_valid (@pytest.mark.anyio, parametrized over
##        EXAMPLES): spec.validate.v1 -> ok and valid; its normalised YAML
##        validates again to the same spec_hash.
## [ ] 6. test_validate_reports_broken_spec_without_error (parametrized:
##        a schema error, broken YAML, YAML that is not a mapping): ok,
##        valid false and errors set.
## [ ] 7. test_verify_matches_cli: run `_cli(path, "--json")`, call
##        verify.run.v1 and compare te_name, severity, coherence issues
##        and every verdict field; the tool uses short ids ("FM1"):
##          | key = (service.fm_id(v["failure_mode"]), v["subject"])
## [ ] 8. test_verification_ref_uses_paper_defaults: the ref equals
##          | hashing.verification_ref(spec_hash,
##          |     hashing.verifier_version(), hashing.config_hash(None))
##        (registry/facts.py recomputes it that way).
## [ ] 9. test_minimal_matches_cli: `_cli(path, "--minimal", "--json")`
##        equals verify.minimal.v1's verdicts.
## [ ] 10. test_flow_graph_matches_web_api and
##         test_cadcad_export_matches_web_api: the same result as
##         POST /api/flow-graph and POST /api/cadcad-export through
##         `web_app.test_client()` (no server needed).
## [ ] 11. Check (remove the five tools from `planned:` first):
##          | uv run pytest tests/platform_tests/test_platform_tools.py -v
##
## Guide 5.5 (db/ active; a PostgreSQL in TE_DATABASE_URL)
## [ ] 12. Imports, in their own labelled block: logging, yaml, func and
##         select (sqlalchemy), `models as m` (te_platform.db), Repository,
##         session_scope. Helpers: `_unique_spec(path)`, the example as a
##         dict whose meta.name ends with a random suffix (a spec nobody
##         verified yet), and `_as_floats(x)`, every int turned into a
##         float (JSONB returns large floats as ints: the "##" note).
## [ ] 13. test_identical_verification_is_answered_from_the_store (marked
##         db): the first call stores the result (Repository
##         .get_verification), the second returns it and logs "verification
##         served from the store" (pytest's caplog), and both calls are in
##         the audit_log table.
##
## Guide 6.2 (jobs/ active; a Redis in TE_REDIS_URL)
## [ ] 14. Imports: SimpleWorker (rq) and `queue` (te_platform.jobs).
##         Helper `_run_queued_simulations()`: a SimpleWorker on
##         queue._queue_for("monte_carlo"), `.work(burst=True)` (run every
##         queued job, then return).
## [ ] 15. test_simulation_before_verification_is_refused: sim.monte_carlo.v1
##         with only a spec -> not ok, "precondition_failed", and
##         "verify.run.v1" in error.do_first.
## [ ] 16. test_verification_ref_of_another_spec_is_refused: verify
##         EXAMPLES[0], pass its ref with EXAMPLES[1]'s spec -> precondition
##         "verification_ref_matches_spec".
## [ ] 17. test_simulation_job_finishes_and_status_carries_result: queued
##         job visible to its owner, not_found for another principal, then
##         (worker run) finished with the result.
## [ ] 18. test_cancel_job: cancel a queued trajectory -> "cancelled";
##         twice -> same answer; another principal -> not_found.
##
## Guide 7.4 (elicitation/protocol.py, answers.py and the tool active)
## [ ] 19. Imports: load_protocol. Helpers: `_new_session(principal)`
##         (Repository.create_session) and `_unknown_slot()`: the first
##         protocol slot that allows "unknown" and has no "[]" in its path.
## [ ] 20. test_record_answer_adds_one_spec_version_per_call (db): two
##         answers -> spec_version 1 then 2; one answer row per slot.
## [ ] 21. test_record_answer_unknown_slot_is_a_validation_error.
##
## Guide 7.5
## [ ] 22. test_next_questions_starts_and_continues_a_session (db): no
##         session_id -> a new session_id and questions; the same session
##         continues; another principal -> not_found; after one answer the
##         state is still "eliciting" (open decisive slots, ranking.py).
##
## Guide 10.3 (security/signed_urls.py, reports/ and the tool active)
## [ ] 23. Imports: get_settings, check_narrative, collect_numbers,
##         verify_download. Fixture `signing_key(monkeypatch)`: set
##         TE_REPORT_SIGNING_KEY and clear the settings cache before and
##         after the test.
## [ ] 24. test_report_rejects_invented_numbers: a narrative containing
##         "424242.4242" -> validation_error naming 424242.
## [ ] 25. test_report_accepts_numbers_from_the_simulation: a number that
##         only the finished simulation contains is refused with
##         include_simulations=False, accepted with True -> report_id, job
##         and a download URL whose signature verifies.
## [ ] 26. test_report_without_stored_verification_is_not_found: a valid,
##         never verified spec with its correct ref -> not_found.
##
## Guide 11.2
## [ ] 27. test_lit_search_returns_passages_with_citation_keys: store one
##         work and one chunk with an invented word, search it: our key is
##         found and every hit has a citation_key; delete the rows after.
## [ ] 28. Check: the step 11 command.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import json
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from te_platform import hashing, service
from te_platform.registry.context import CallContext, Principal, SessionFacts
from te_platform.registry.loader import Registry, build_registry
from te_platform.registry.pipeline import ToolOutcome, call
from webapp.app import app as web_app

## Guide 5.5: the database, to look at what the tools stored.
import logging
import yaml
from sqlalchemy import func, select
from te_platform.db import models as m
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope

## Guide 6.2: RQ's in-process worker and the queue module.
from rq import SimpleWorker
from te_platform.jobs import queue

## Guide 7.4: the elicitation protocol.
from te_platform.elicitation.protocol import load_protocol

## Guide 10.3: settings, the number check and the signed links.
from te_platform.config import get_settings
from te_platform.reports.method import figure_ids
from te_platform.reports.numbers_check import check_narrative, collect_numbers
from te_platform.security.signed_urls import verify_download

## Parallel answers (db/repo.py lock_session): several calls at once.
import os
import time

import anyio

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = sorted((REPO / "examples").glob("*.yaml"))
POLICY = REPO / "policy" / "tool_policy.yaml"


@pytest.fixture(scope="module")
def registry() -> Registry:
    # Built once per module: loading the policy and discovering tools is the
    # same work the MCP server does at startup.
    return build_registry(POLICY)


def _new_principal() -> Principal:
    # A new caller per test: quotas, job reuse and ownership are per
    # principal, so tests never see each other's jobs or counters.
    return Principal(id="test-" + uuid4().hex, kind="api_key")


def _round_trip(model_cls: Any, data: dict[str, Any]) -> None:
    # model -> JSON text -> model must give back the same model: what an
    # MCP client sends or receives survives serialisation unchanged.
    model = model_cls.model_validate(data)
    assert model_cls.model_validate_json(model.model_dump_json()) == model


async def _call(
    registry: Registry,
    tool_id: str,
    tool_input: dict[str, Any],
    *,
    principal: Principal | None = None,
    session: SessionFacts | None = None,
) -> ToolOutcome:
    ctx = CallContext(
        principal=principal or _new_principal(),
        tool_id=tool_id,
        tool_input=tool_input,
        session=session,
    )
    out = await call(registry, tool_id, tool_input, ctx)
    if out.ok:
        tool = registry.tools[tool_id]
        _round_trip(tool.input_model, tool_input)
        assert out.result is not None
        _round_trip(tool.output_model, out.result)
    return out


def _cli(*args: str) -> Any:
    # The existing CLI is the reference implementation. `python -m
    # verifier.cli` runs the same code as the `te-verify` script without
    # depending on PATH. check=False: --minimal exits 1 on a broken FM.
    done = subprocess.run(
        [sys.executable, "-m", "verifier.cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    return json.loads(done.stdout)


## --- 2.5 contract ---------------------------------------------------------------------


def test_every_tool_matches_its_entry_point(registry):
    eps = {ep.name: ep for ep in entry_points(group="te_platform.tools")}
    assert set(eps) == set(registry.tools)
    for tool_id, tool in registry.tools.items():
        assert eps[tool_id].load() is tool
        # verify.run.v1 -> te_platform.tools.verify_run (tools/__init__.py)
        module = eps[tool_id].value.split(":")[0]
        assert module == "te_platform.tools." + "_".join(tool_id.split(".")[:-1])
        assert tool.title
        # model_json_schema() is what MCP clients see; it must be generable.
        assert json.loads(json.dumps(tool.input_model.model_json_schema()))
        assert json.loads(json.dumps(tool.output_model.model_json_schema()))


## --- 2.5 golden: spec.validate.v1 and verify.run.v1 -------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
async def test_examples_are_valid(registry, path):
    out = await _call(registry, "spec.validate.v1", {"spec": path.read_text()})
    assert out.ok and out.result["valid"], out
    # The normalised YAML describes exactly the same economy: same hash.
    again = await _call(registry, "spec.validate.v1", {"spec": out.result["yaml"]})
    assert again.result["spec_hash"] == out.result["spec_hash"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "text",
    ["meta: {name: x}\n", "meta: [unclosed\n", "- a\n- b\n"],
    ids=["schema_error", "broken_yaml", "not_a_mapping"],
)
async def test_validate_reports_broken_spec_without_error(registry, text):
    # An invalid spec is a normal result (valid=False), not a ToolError.
    out = await _call(registry, "spec.validate.v1", {"spec": text})
    assert out.ok and not out.result["valid"] and out.result["errors"]
    assert all(e["message"] for e in out.result["errors"])


@pytest.mark.anyio
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
async def test_verify_matches_cli(registry, path):
    cli = _cli(str(path), "--json")
    out = await _call(registry, "verify.run.v1", {"spec": path.read_text()})
    assert out.ok, out
    assert out.result["te_name"] == cli["te_name"]
    assert out.result["severity"] == cli["severity"]
    assert out.result["coherence_issues"] == cli["coherence_issues"]
    # The tool outputs short ids ("FM1") plus the full name; the CLI prints
    # full names ("FM1: Token Oversupply / Inflation"). Every other field of
    # each verdict must be identical.
    got = {(v["failure_mode"], v["subject"]): v for v in out.result["verdicts"]}
    assert len(got) == len(cli["verdicts"])
    for want in cli["verdicts"]:
        mine = got[(service.fm_id(want["failure_mode"]), want["subject"])]
        assert mine["failure_mode_name"] == want["failure_mode"]
        assert {k: mine[k] for k in want if k != "failure_mode"} == {
            k: v for k, v in want.items() if k != "failure_mode"
        }


@pytest.mark.anyio
async def test_verification_ref_uses_paper_defaults(registry):
    # registry/facts.py recomputes the expected ref with config_hash(None):
    # that is only right because verify.run.v1 never passes a config.
    out = await _call(registry, "verify.run.v1", {"spec": EXAMPLES[0].read_text()})
    expected = hashing.verification_ref(
        out.result["spec_hash"], hashing.verifier_version(), hashing.config_hash(None)
    )
    assert out.result["verification_ref"] == expected


## --- 2.5 golden: verify.minimal.v1, graph.flow.v1, export.cadcad.v1 -----------------------


@pytest.mark.anyio
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
async def test_minimal_matches_cli(registry, path):
    cli = _cli(str(path), "--minimal", "--json")
    out = await _call(registry, "verify.minimal.v1", {"spec": path.read_text()})
    assert out.ok, out
    assert out.result["verdicts"] == cli


@pytest.mark.anyio
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
async def test_flow_graph_matches_web_api(registry, path):
    web = web_app.test_client().post("/api/flow-graph", json={"yaml": path.read_text()})
    assert web.status_code == 200
    want = web.get_json()
    out = await _call(registry, "graph.flow.v1", {"spec": path.read_text()})
    assert out.ok, out
    got = json.loads(json.dumps(out.result))  # same JSON types as the web answer
    assert got == {
        "nodes": want["elements"]["nodes"],
        "edges": want["elements"]["edges"],
        "diagnostics": want["diagnostics"],
        "summary": want["summary"],
    }


@pytest.mark.anyio
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
async def test_cadcad_export_matches_web_api(registry, path):
    web = web_app.test_client().post(
        "/api/cadcad-export",
        json={"yaml": path.read_text(), "n_runs": 100, "horizon_periods": 200, "seed": 7},
    )
    assert web.status_code == 200
    out = await _call(
        registry,
        "export.cadcad.v1",
        {"spec": path.read_text(), "n_runs": 100, "horizon": 200, "seed": 7},
    )
    assert out.ok, out
    assert json.loads(json.dumps(out.result["cadcad_config"])) == web.get_json()


## --- 5.5 the store of verifications -----------------------------------------------------


## Guide 5.5: a spec nobody verified yet (the store is shared between tests).
def _unique_spec(path: Path) -> dict[str, Any]:
    spec: dict[str, Any] = yaml.safe_load(path.read_text())
    spec["meta"]["name"] = f"{spec['meta']['name']} {uuid4().hex}"
    return spec


## Guide 5.5: numbers compared by value. PostgreSQL's JSONB stores every
## number as an exact decimal, so a large float such as 5.457e+31 comes back
## as the integer 54572594818810995000000000000000: same value, other type.
def _as_floats(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _as_floats(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_as_floats(v) for v in x]
    return float(x) if isinstance(x, int) and not isinstance(x, bool) else x


## Guide 5.5: verify.run.v1 answers an identical request from the store.
@pytest.mark.db
@pytest.mark.anyio
async def test_identical_verification_is_answered_from_the_store(registry, caplog):
    caplog.set_level(logging.INFO, logger="te_platform.tools.verify_run")
    principal = _new_principal()
    spec = _unique_spec(EXAMPLES[0])
    first = await _call(registry, "verify.run.v1", {"spec": spec}, principal=principal)
    assert first.ok, first
    ref = first.result["verification_ref"]
    with session_scope() as db:
        stored = Repository(db, principal).get_verification(ref)
    assert _as_floats(stored) == _as_floats(first.result)
    assert "verification served from the store" not in caplog.messages
    second = await _call(registry, "verify.run.v1", {"spec": spec}, principal=principal)
    assert _as_floats(second.result) == _as_floats(first.result)
    assert "verification served from the store" in caplog.messages
    # Both calls, the computed one and the stored one, are audited.
    with session_scope() as db:
        n = db.scalar(
            select(func.count())
            .select_from(m.AuditEntry)
            .where(
                m.AuditEntry.principal_id == principal.id, m.AuditEntry.tool_id == "verify.run.v1"
            )
        )
    assert n == 2


## --- 6.2 jobs: formal verification first, then a background job ---------------------------


## Guide 6.2: run every queued simulation job now, in this process.
def _run_queued_simulations() -> None:
    sims = queue._queue_for("monte_carlo")
    SimpleWorker([sims], connection=sims.connection).work(burst=True)


## Guide 6.2: no simulation before verification (architecture P2).
@pytest.mark.anyio
async def test_simulation_before_verification_is_refused(registry):
    out = await _call(registry, "sim.monte_carlo.v1", {"spec": EXAMPLES[0].read_text()})
    assert not out.ok
    assert out.error.error == "precondition_failed"
    assert "verify.run.v1" in out.error.do_first


## Guide 6.2: a verification_ref only works for the spec it was computed from.
@pytest.mark.anyio
async def test_verification_ref_of_another_spec_is_refused(registry):
    a, b = EXAMPLES[0].read_text(), EXAMPLES[1].read_text()
    ref_a = (await _call(registry, "verify.run.v1", {"spec": a})).result["verification_ref"]
    out = await _call(registry, "sim.monte_carlo.v1", {"spec": b, "verification_ref": ref_a})
    assert not out.ok
    assert out.error.precondition == "verification_ref_matches_spec"


## Guide 6.2: after verification -> job_id; the job finishes; owners only.
@pytest.mark.anyio
async def test_simulation_job_finishes_and_status_carries_result(registry):
    alice, bob = _new_principal(), _new_principal()
    spec = (REPO / "examples" / "axie_infinity.yaml").read_text()
    ref = (await _call(registry, "verify.run.v1", {"spec": spec})).result["verification_ref"]
    started = await _call(
        registry,
        "sim.monte_carlo.v1",
        {"spec": spec, "verification_ref": ref, "n_runs": 3, "horizon": 10, "seed": 1},
        principal=alice,
    )
    assert started.ok, started
    job_id = started.result["job_id"]
    queued = await _call(registry, "jobs.status.v1", {"job_id": job_id}, principal=alice)
    assert queued.result["status"] == "queued" and queued.result["kind"] == "monte_carlo"
    assert queued.result["retry_after_s"] and queued.result["result"] is None
    foreign = await _call(registry, "jobs.status.v1", {"job_id": job_id}, principal=bob)
    assert foreign.error.error == "not_found"
    _run_queued_simulations()
    done = await _call(registry, "jobs.status.v1", {"job_id": job_id}, principal=alice)
    assert done.result["status"] == "finished", done.result
    assert done.result["retry_after_s"] is None
    assert done.result["result"]["kind"] == "monte_carlo"
    assert done.result["result"]["verification_ref"] == ref
    assert any(r["simulated"] for r in done.result["result"]["per_fm_results"])


## Extension: jobs.status.v1 can wait for the job (wait_s), so a short
## simulation's result arrives in the same turn.
@pytest.mark.anyio
async def test_status_waits_for_the_job_to_finish(registry):
    alice = _new_principal()
    spec = (REPO / "examples" / "axie_infinity.yaml").read_text()
    ref = (await _call(registry, "verify.run.v1", {"spec": spec})).result["verification_ref"]
    args = {"spec": spec, "verification_ref": ref, "n_runs": 3, "horizon": 10}
    started = await _call(registry, "sim.monte_carlo.v1", {**args, "seed": 7}, principal=alice)
    job_id = started.result["job_id"]
    # No worker yet: the wait ends after wait_s with the job still queued.
    begin = time.monotonic()
    still = await _call(
        registry, "jobs.status.v1", {"job_id": job_id, "wait_s": 1}, principal=alice
    )
    assert still.result["status"] == "queued" and time.monotonic() - begin >= 1
    # A worker process starts while the status call waits: the call returns
    # the result (rq's worker needs its own main thread, as in production).
    worker = subprocess.Popen(  # noqa: S603  a fixed command, no user input
        [
            sys.executable,
            "-c",
            "from rq import SimpleWorker\n"
            "from te_platform.jobs import queue\n"
            "q = queue._queue_for('monte_carlo')\n"
            "SimpleWorker([q], connection=q.connection).work(burst=True)",
        ],
        env=os.environ.copy(),
    )
    try:
        args = {"job_id": job_id, "wait_s": 30}
        done = await _call(registry, "jobs.status.v1", args, principal=alice)
    finally:
        worker.wait(timeout=60)
    assert done.result["status"] == "finished", done.result


## Guide 6.2: jobs.cancel.v1 cancels, is idempotent, and only for the owner.
@pytest.mark.anyio
async def test_cancel_job(registry):
    alice, bob = _new_principal(), _new_principal()
    spec = EXAMPLES[0].read_text()
    ref = (await _call(registry, "verify.run.v1", {"spec": spec})).result["verification_ref"]
    started = await _call(
        registry,
        "sim.trajectory.v1",
        {"spec": spec, "verification_ref": ref, "horizon": 10},
        principal=alice,
    )
    job_id = started.result["job_id"]
    foreign = await _call(registry, "jobs.cancel.v1", {"job_id": job_id}, principal=bob)
    assert foreign.error.error == "not_found"
    for _ in range(2):  # cancelling twice gives the same answer
        out = await _call(registry, "jobs.cancel.v1", {"job_id": job_id}, principal=alice)
        assert out.ok and out.result == {"job_id": job_id, "status": "cancelled"}
    status = await _call(registry, "jobs.status.v1", {"job_id": job_id}, principal=alice)
    assert status.result["status"] == "cancelled"


## --- 7.4 / 7.5 elicitation tools ---------------------------------------------------------------


## Guide 7.4: a new design session owned by `principal`, and its facts.
def _new_session(principal: Principal) -> SessionFacts:
    with session_scope() as db:
        session_id = Repository(db, principal).create_session()
    return SessionFacts(session_id=session_id, owner_id=principal.id)


## Guide 7.4: a slot any session can answer with "unknown" (no list index).
def _unknown_slot() -> str:
    protocol = load_protocol(REPO / "policy" / "elicitation_protocol.yaml")
    return next(
        slot.id
        for _, slot in protocol.ordered_slots()
        if slot.allow_unknown and "[]" not in slot.ir_path
    )


## Guide 7.4: each answer is one new spec version (append-only).
@pytest.mark.db
@pytest.mark.anyio
async def test_record_answer_adds_one_spec_version_per_call(registry):
    principal = _new_principal()
    session = _new_session(principal)
    answer = {
        "session_id": session.session_id,
        "slot_id": _unknown_slot(),
        "status": "unknown",
        "user_quote": "I really don't know.",
    }
    for expected_version in (1, 2):
        out = await _call(
            registry, "elicit.record_answer.v1", answer, principal=principal, session=session
        )
        assert out.ok, out
        assert out.result["spec_version"] == expected_version
    with session_scope() as db:
        versions = db.scalar(
            select(func.count())
            .select_from(m.SpecVersion)
            .where(m.SpecVersion.session_id == session.session_id)
        )
        answers = Repository(db, principal).get_answers(session.session_id)
    assert versions == 2
    # get_answers keeps the latest answer per slot; the quote is stored.
    assert [a["user_quote"] for a in answers] == ["I really don't know."]


## Answers recorded IN PARALLEL (the agent runs a reply's tool calls together,
## e.g. after a form) are all kept: each applies on top of the previous one
## (db/repo.py lock_session), with distinct spec versions.
@pytest.mark.db
@pytest.mark.anyio
async def test_parallel_answers_to_one_session_are_all_kept(registry):
    principal = _new_principal()
    session = _new_session(principal)
    slots = [
        slot.id
        for _, slot in load_protocol(REPO / "policy/elicitation_protocol.yaml").ordered_slots()
        if slot.allow_unknown and "[]" not in slot.ir_path
    ][:4]
    outcomes: list[Any] = []

    async def _answer(slot_id: str) -> None:
        answer = {
            "session_id": session.session_id,
            "slot_id": slot_id,
            "status": "unknown",
            "user_quote": "I don't know",
        }
        outcomes.append(
            await _call(
                registry, "elicit.record_answer.v1", answer, principal=principal, session=session
            )
        )

    async with anyio.create_task_group() as tg:
        for slot_id in slots:
            tg.start_soon(_answer, slot_id)
    assert all(o.ok for o in outcomes), outcomes
    assert sorted(o.result["spec_version"] for o in outcomes) == list(range(1, len(slots) + 1))
    with session_scope() as db:
        answers = Repository(db, principal).get_answers(session.session_id)
    assert sorted(a["slot_id"] for a in answers) == sorted(slots)


## Guide 7.4: an unknown slot is refused before anything is stored.
@pytest.mark.db
@pytest.mark.anyio
async def test_record_answer_unknown_slot_is_a_validation_error(registry):
    principal = _new_principal()
    session = _new_session(principal)
    out = await _call(
        registry,
        "elicit.record_answer.v1",
        {
            "session_id": session.session_id,
            "slot_id": "no.such.slot",
            "status": "unknown",
            "user_quote": "whatever",
        },
        principal=principal,
        session=session,
    )
    assert out.error.error == "validation_error"
    assert "no.such.slot" in out.error.message


## Guide 7.5: next_questions starts a session, continues it, and owns it.
@pytest.mark.db
@pytest.mark.anyio
async def test_next_questions_starts_and_continues_a_session(registry):
    alice, bob = _new_principal(), _new_principal()
    first = await _call(registry, "elicit.next_questions.v1", {}, principal=alice)
    assert first.ok, first
    assert first.result["questions"] and not first.result["complete"]
    session_id = first.result["session_id"]
    session = SessionFacts(session_id=session_id, owner_id=alice.id)
    again = await _call(
        registry,
        "elicit.next_questions.v1",
        {"session_id": session_id},
        principal=alice,
        session=session,
    )
    assert again.result["session_id"] == session_id
    foreign = await _call(
        registry, "elicit.next_questions.v1", {"session_id": session_id}, principal=bob
    )
    assert foreign.error.error == "not_found"
    # One answer does not finish an interview: decisive slots stay open.
    recorded = await _call(
        registry,
        "elicit.record_answer.v1",
        {
            "session_id": session_id,
            "slot_id": _unknown_slot(),
            "status": "unknown",
            "user_quote": "No idea.",
        },
        principal=alice,
        session=session,
    )
    assert recorded.result["state"] == "eliciting"


## --- 10.3 report: the number check ---------------------------------------------------------


## Guide 10.3: download links are signed, so the tests need a signing key.
@pytest.fixture
def signing_key(monkeypatch):
    monkeypatch.setenv("TE_REPORT_SIGNING_KEY", "test-signing-key-" + "x" * 32)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


## Guide 10.3: an invented number is refused before anything is queued.
@pytest.mark.db
@pytest.mark.anyio
async def test_report_rejects_invented_numbers(registry, signing_key):
    principal = _new_principal()
    spec = EXAMPLES[0].read_text()
    ref = (await _call(registry, "verify.run.v1", {"spec": spec}, principal=principal)).result[
        "verification_ref"
    ]
    out = await _call(
        registry,
        "report.render_pdf.v1",
        {
            "spec": spec,
            "verification_ref": ref,
            "narrative": {"executive_summary": "About 424242.4242 tokens leak."},
        },
        principal=principal,
    )
    assert out.error.error == "validation_error"
    assert "424242" in out.error.message


## Report extension: notes may only interpret charts the report has; the text
## must be plain (no failure-mode codes or specialist terms); invented numbers
## in a note are refused like in the narrative.
@pytest.mark.db
@pytest.mark.anyio
async def test_report_text_is_checked_for_charts_jargon_and_numbers(registry, signing_key):
    principal = _new_principal()
    spec = _unique_spec(EXAMPLES[0])
    ref = (await _call(registry, "verify.run.v1", {"spec": spec}, principal=principal)).result[
        "verification_ref"
    ]
    base = {"spec": spec, "verification_ref": ref, "narrative": {"executive_summary": "Fine."}}

    async def error(**extra: Any) -> str:
        out = await _call(registry, "report.render_pdf.v1", {**base, **extra}, principal=principal)
        assert out.error.error == "validation_error"
        return out.error.message

    assert "Not in this report: verdicts" in await error(figure_notes={"verdicts": "Fine."})
    wordy = await error(narrative={"executive_summary": "FM3 fails: burn is too low."})
    assert "FM1-FM6" in wordy and "burn" in wordy
    assert "313131" in await error(narrative={"executive_summary": "There are 313131 members."})


## Guide 10.3: numbers of the finished simulation are allowed; the link works.
@pytest.mark.db
@pytest.mark.anyio
async def test_report_accepts_numbers_from_the_simulation(
    registry, signing_key, tmp_path, monkeypatch
):
    principal = _new_principal()
    spec = (REPO / "examples" / "axie_infinity.yaml").read_text()
    ref = (await _call(registry, "verify.run.v1", {"spec": spec}, principal=principal)).result[
        "verification_ref"
    ]
    await _call(
        registry,
        "sim.monte_carlo.v1",
        {"spec": spec, "verification_ref": ref, "n_runs": 3, "horizon": 10, "seed": 1},
        principal=principal,
    )
    _run_queued_simulations()
    with session_scope() as db:
        repo = Repository(db, principal)
        verification = repo.get_verification(ref)
        simulation = repo.latest_finished_simulation(ref)
    assert simulation is not None
    # A number that only the simulation contains, written as people do.
    only_verification = collect_numbers({"verification": verification})
    both = collect_numbers({"verification": verification, "simulation": simulation})
    written = next(
        f"{n:g}"
        for n in sorted(collect_numbers(simulation))
        if check_narrative({"s": f"{n:g}"}, only_verification)
        and not check_narrative({"s": f"{n:g}"}, both)
    )
    request = {
        "spec": spec,
        "verification_ref": ref,
        "narrative": {"explanation": f"In the simulation the value was {written}."},
        # One note per chart: with the simulation, its chart is in the report too.
        "figure_notes": {i: "See the table." for i in figure_ids(None, simulation, [])},
    }
    refused = await _call(
        registry,
        "report.render_pdf.v1",
        {**request, "include_simulations": False, "figure_notes": {}},
        principal=principal,
    )
    assert refused.error.error == "validation_error"
    out = await _call(registry, "report.render_pdf.v1", request, principal=principal)
    assert out.ok, out
    report_id, job_id = out.result["report_id"], out.result["job_id"]
    assert out.result["status"] == "rendering" and "download_url" not in out.result
    review = {"job_id": job_id, "review": "Checked every number and answer. " * 4, "correct": True}
    # Not rendered yet: nothing to publish.
    early = await _call(registry, "report.publish.v1", review, principal=principal)
    assert early.error.error == "validation_error" and "not rendered" in early.error.message
    # The worker renders the draft; the agent reviews it and publishes it.
    monkeypatch.setenv("TE_REPORT_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    reports = queue._queue_for("report")
    SimpleWorker([reports], connection=reports.connection).work(burst=True)
    wrong = await _call(
        registry, "report.publish.v1", {**review, "correct": False}, principal=principal
    )
    assert wrong.error.error == "validation_error"
    published = await _call(registry, "report.publish.v1", review, principal=principal)
    assert published.ok, published
    path, query = published.result["download_url"].split("?")
    assert path == f"/agent/reports/{report_id}"
    params = dict(p.split("=", 1) for p in query.split("&"))
    assert verify_download(report_id, int(params["exp"]), params["sig"])
    get_settings.cache_clear()


## Guide 10.3: a correct ref whose verification was never stored -> not_found.
@pytest.mark.db
@pytest.mark.anyio
async def test_report_without_stored_verification_is_not_found(registry, signing_key):
    spec = _unique_spec(EXAMPLES[0])
    spec_hash = service.validate(spec).spec_hash
    ref = hashing.verification_ref(spec_hash, hashing.verifier_version(), hashing.config_hash(None))
    out = await _call(registry, "report.render_pdf.v1", {"spec": spec, "verification_ref": ref})
    assert out.error.error == "not_found"


## --- 11.2 literature ---------------------------------------------------------------------------


## Guide 11.2: every hit carries the key the agent must cite.
@pytest.mark.db
@pytest.mark.anyio
async def test_lit_search_returns_passages_with_citation_keys(registry):
    work_id, key = uuid4().hex, "test" + uuid4().hex[:12]
    with session_scope() as db:
        db.add(
            m.Work(
                id=work_id,
                citation_key=key,
                title="Quokkanomics",
                authors="Test, A.",
                year=2026,
                venue=None,
                doi=None,
                licence="CC-BY-4.0",
                full_text_allowed=True,
            )
        )
        db.flush()  # the work must exist before its chunk (foreign key)
        db.add(
            m.Chunk(
                work_id=work_id,
                section="1 Introduction",
                page=1,
                text="Quokkanomics studies token economies run by quokkas.",
            )
        )
    try:
        out = await _call(registry, "lit.search.v1", {"query": "quokkanomics"})
        assert out.ok, out
        hits = out.result["hits"]
        assert key in [h["citation_key"] for h in hits]
        assert all(h["citation_key"] and h["passage"] for h in hits)
        assert "not instructions" in out.result["note"]
    finally:
        with session_scope() as db:
            db.execute(m.Chunk.__table__.delete().where(m.Chunk.work_id == work_id))
            db.execute(m.Work.__table__.delete().where(m.Work.id == work_id))


## Experiment extension (sim.experiment.v1): a bad variant is refused before
## queueing, naming it; a good one runs in the worker, and its result is what
## the report reads (Repository.finished_experiments).
@pytest.mark.db
@pytest.mark.anyio
async def test_experiment_refuses_a_bad_variant_and_runs_a_good_one(registry):
    principal = _new_principal()
    spec = _unique_spec(REPO / "examples" / "time_bank.yaml")
    ref = (await _call(registry, "verify.run.v1", {"spec": spec}, principal=principal)).result[
        "verification_ref"
    ]
    base = {"spec": spec, "verification_ref": ref, "title": "More members", "question": "N?"}
    bad = await _call(
        registry,
        "sim.experiment.v1",
        {
            **base,
            "variants": [{"name": "Big", "changes": [{"path": "participants.nope", "value": 1}]}],
        },
        principal=principal,
    )
    assert bad.error.error == "validation_error" and "participants.nope" in bad.error.message
    out = await _call(
        registry,
        "sim.experiment.v1",
        {**base, "sweep": {"path": "participants.count_N", "label": "Members", "values": [20, 80]}},
        principal=principal,
    )
    assert out.ok, out
    assert out.result["variants"] == ["Current design", "Members = 20", "Members = 80"]
    _run_queued_simulations()  # experiments share the simulations queue
    with session_scope() as db:
        (exp,) = Repository(db, principal).finished_experiments(ref)
    assert exp["kind"] == "experiment" and exp["job_id"] == out.result["job_id"]
    assert [v["name"] for v in exp["variants"]] == out.result["variants"]
