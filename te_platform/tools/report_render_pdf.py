## =============================================================================
## te_platform/tools/report_render_pdf.py — tool `report.render_pdf.v1`
## =============================================================================
## GUIDE STEP   10.3 (uses 10.2's number check)
## PURPOSE      Produces the downloadable PDF report for a VERIFIED spec.
##              The handler does the quick, safety-critical part itself:
##                1. loads the stored verification and, if requested, the
##                   latest finished simulation for the verification_ref;
##                2. checks the agent's narrative: every number it contains
##                   must appear in that data, verification OR simulation
##                   (architecture P1: the LLM never invents a number);
##                3. enqueues a "report" job (rendering with WeasyPrint takes
##                   seconds and runs in the worker, jobs/report_task.py ->
##                   reports/render.py);
##                4. returns the report_id and a signed, expiring download URL.
## USED BY      registry/loader.py (entry point "report.render_pdf.v1"),
##              pipeline.py; suggested by predicates.py `all_decided` and
##              `simulation_job_finished`.
## DEPENDS ON   te_platform.reports.numbers_check (check_narrative,
##              collect_numbers), te_platform.db.repo.Repository
##              (get_verification, latest_finished_simulation),
##              te_platform.db.session.session_scope,
##              te_platform.jobs.queue.enqueue_job,
##              te_platform.security.signed_urls.sign_download,
##              te_platform.config (report_link_ttl_s).
## RULES        policy -> report.render_pdf.v1: preconditions verified_spec,
##              verification_ref_matches_spec (enforced by the pipeline);
##              cost "moderate"; returns {report_id, job_id, status,
##              download_url, expires_at}. The PDF exists only once the job
##              has finished (follow it with jobs.status.v1); until then the
##              download link answers "not found".
## WHY          Architecture D14: fixed sections are filled from data by the
##              template; only the narrative comes from the model, and it is
##              checked here BEFORE any work is queued, so the agent gets an
##              immediate, actionable error ("the number 0.37 is not in the
##              results") and can correct itself.
## ACTIVATE     Uncomment with guide 10.3; tests ("Guide 10.3" part of
##              test_platform_tools.py): invented number ->
##              validation_error listing it; a number taken from the
##              simulation is accepted; valid narrative -> report_id + URL;
##              a ref with no stored verification -> not_found. (Verifications
##              are content-addressed and shared between users, see
##              db/repo.py, so there is no "foreign" verification.)
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Every tool module has the
## same four sections (tools/__init__.py; verify_run.py is the template).
## Keep `TOOL`, the tool id and the model field names exactly as written
## here: te_platform/README.md (contracts table) and the policy rely on them.
##
## Guide 10.3 (activate reports/numbers_check.py (10.2),
## security/signed_urls.py, jobs/ and db/ first)
## [ ] 1. Imports at the top: `UTC`, `datetime`, `timedelta`; `Any`;
##        `uuid4`; `anyio`; `BaseModel`, `Field`; then from te_platform:
##        `get_settings`, `Repository`, `session_scope`, `InvalidInput` and
##        `NotFound`, `queue`, `CallContext`, `ToolSpec`, `check_narrative`
##        and `collect_numbers`, `sign_download`.
## [ ] 2. `ReportRenderInput(BaseModel)`: `session_id`, `spec`
##        (dict | str | None) and `verification_ref`, all default None;
##        `narrative: dict[str, str]` (default_factory=dict); `audience: str`
##        (default "designer"); `include_simulations: bool` (default True);
##        `citations: list[dict[str, Any]]` (default_factory=list).
##        One-line docstrings on every class and public function (D1).
## [ ] 3. `ReportRenderOutput(BaseModel)`: report_id, download_url (str),
##        `expires_at: datetime`, `status: str = "rendering"`, job_id (str).
##        Together they are the policy's `returns`.
## [ ] 4. A module constant `ALLOWED_SECTIONS = {"executive_summary",
##        "explanation"}`: the sections the report template prints.
## [ ] 5. Sync helper `_load_results(ctx, vref, *, include_simulations:
##        bool) -> dict[str, Any]` (a keyword-only flag: ruff's FBT rules
##        refuse a bare True/False argument whose meaning is invisible at
##        the call). In session_scope, Repository.get_verification(vref)
##        (raise NotFound when None) and, if requested,
##        latest_finished_simulation(vref); return
##        {"verification": ..., "simulation": ...}.
## [ ] 6. `async def handle(inp, ctx) -> ReportRenderOutput`, part 1:
##        `vref = ctx.facts.verification_ref` (InvalidInput when None), and
##        refuse unknown narrative sections with InvalidInput:
##          | unknown = set(inp.narrative) - ALLOWED_SECTIONS
## [ ] 7. Part 2, BEFORE queueing anything: load the results in a thread,
##        then `problems = check_narrative(inp.narrative,
##        collect_numbers(results))`; if any, raise InvalidInput starting
##        "The narrative contains numbers not found in the results: ".
## [ ] 8. Part 3: `report_id = uuid4().hex` (every call makes a NEW
##        report: the policy says idempotentHint false); expires_at = now
##        (UTC) plus
##        get_settings().report_link_ttl_s seconds; a payload with
##        report_id, narrative, audience, include_simulations, session_id,
##        expires_at (as .isoformat()) and citations; enqueue the kind
##        "report" in a thread, as in sim_monte_carlo.py.
## [ ] 9. Part 4: return ReportRenderOutput with
##        download_url=sign_download(report_id, expires_at), expires_at and
##        job_id.
## [ ] 10. `TOOL = ToolSpec(id="report.render_pdf.v1", title="Render a PDF
##         report", ...)` with the two models and handle.
## [ ] 11. Remove "report.render_pdf.v1" from `planned:` in
##         policy/tool_policy.yaml.
## [ ] 12. Check: activate the "Guide 10.3" part of
##         tests/platform_tests/test_platform_tools.py (header, ACTIVATE);
##         it needs PostgreSQL and Redis (TE_DATABASE_URL, TE_REDIS_URL).
##           | uv run pytest tests/platform_tests/test_platform_tools.py -q
##           | uv run pytest tests/platform_tests/test_platform_reports.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import anyio
from pydantic import BaseModel, Field

from te_platform.config import get_settings
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.errors import InvalidInput, NotFound
from te_platform.jobs import queue
from te_platform.registry.context import CallContext
from te_platform.registry.spec import ToolSpec
from te_platform.reports.design import NARRATIVE_SECTIONS, design_context
from te_platform.reports.method import figure_ids
from te_platform.reports.numbers_check import check_narrative, collect_numbers
from te_platform.reports.plain import jargon


class ReportRenderInput(BaseModel):
    """What a caller sends to report.render_pdf.v1."""

    session_id: str | None = Field(default=None, description="The design session, if any.")
    spec: dict[str, Any] | str | None = Field(
        default=None, description="The verified spec (stateless calls)."
    )
    verification_ref: str | None = Field(
        default=None,
        description="verification_ref of the verification to report on (stateless calls).",
    )
    # Section name -> text written by the agent. Allowed sections are fixed by
    # the template (reports/templates/report.html); unknown ones are refused
    # below so the template never silently drops text.
    narrative: dict[str, str] = Field(
        default_factory=dict,
        description="Plain-language sections written for the user, keyed by section: "
        + ", ".join(NARRATIVE_SECTIONS)
        + ". Use only numbers present in the tool results, the designer's own words and "
        "answers, the estimates shown to them, or the cited sources.",
    )
    audience: str = Field(
        default="designer", description="Who the report is for, e.g. 'designer', 'board'."
    )
    include_simulations: bool = Field(
        default=True, description="Include finished simulation results."
    )
    # Literature the narrative relies on: pass the hits returned by
    # lit.search.v1 unchanged; the report prints them as references.
    citations: list[dict[str, Any]] = Field(
        default_factory=list,
        description="lit.search.v1 hits cited in the narrative "
        "(citation_key, title, authors, year, venue, doi).",
    )
    # Every chart of the report needs the agent's reading of it: the tool
    # refuses the call and lists the missing ids (reports/method.py,
    # figure_ids), with each chart's title.
    figure_notes: dict[str, str] = Field(
        default_factory=dict,
        description="Chart id -> 1-4 sentences interpreting that chart for the designer "
        "(what it shows about their design). Ids: 'flow', 'simulation', "
        "'experiment<N>-supply-<TOKEN>', 'experiment<N>-violations'; the tool lists any "
        "that are missing. Same number rules as the narrative.",
    )


class ReportRenderOutput(BaseModel):
    """The new report's id and its rendering job (a draft: no link before the review)."""

    report_id: str
    expires_at: datetime
    status: str = "rendering"
    job_id: str
    next_step: str = (
        "Call jobs.status.v1 with this job_id and wait_s 30. Read the result's review_text "
        "and check it; if anything is wrong, render again with corrected text; when it is "
        "correct, call report.publish.v1 with this report_id to get the download link."
    )


ALLOWED_SECTIONS = set(NARRATIVE_SECTIONS)


def _load_results(
    ctx: CallContext, vref: str, *, include_simulations: bool, session_id: str | None
) -> dict[str, Any]:
    """Return everything the narrative may quote numbers from.

    That is the stored verification and, when the report will include it,
    the caller's latest finished simulation (the same data the worker will
    put in the PDF), plus the design itself when there is a session: the
    spec, the answers, the designer's messages and the estimates shown to
    them (reports/design.py, design_evidence). Synchronous database work,
    run in a thread by the handler.
    """
    with session_scope() as db:
        repo = Repository(db, ctx.principal)
        verification = repo.get_verification(vref)
        if verification is None:
            raise NotFound("No stored verification for this verification_ref.")
        simulation = repo.latest_finished_simulation(vref) if include_simulations else None
        design = None
        if session_id:
            design = design_context(
                repo.get_session_facts(session_id).current_spec,
                repo.get_answers(session_id),
                repo.list_messages(session_id),
            )
        return {
            "verification": verification,
            "simulation": simulation,
            "design": design,
            "experiments": repo.finished_experiments(vref),
        }


async def handle(inp: ReportRenderInput, ctx: CallContext) -> ReportRenderOutput:
    """Check the narrative's numbers, then queue the PDF rendering."""
    vref = ctx.facts.verification_ref
    if vref is None:
        raise InvalidInput("A verification_ref is required.")
    unknown = set(inp.narrative) - ALLOWED_SECTIONS
    if unknown:
        raise InvalidInput(
            f"Unknown narrative sections: {sorted(unknown)}. Allowed: {sorted(ALLOWED_SECTIONS)}."
        )

    # 1. Data the report is about: the verification and (optionally) the
    #    latest finished simulation, keyed by the same verification_ref.
    results = await anyio.to_thread.run_sync(
        lambda: _load_results(
            ctx, vref, include_simulations=inp.include_simulations, session_id=inp.session_id
        )
    )

    # 2. Every chart needs a note, and no note may name a chart that is not
    #    in the report.
    ids = figure_ids(results["design"], results["simulation"], results["experiments"])
    missing = [i for i in ids if not inp.figure_notes.get(i, "").strip()]
    extra = sorted(set(inp.figure_notes) - set(ids))
    if missing or extra:
        raise InvalidInput(
            "figure_notes must interpret every chart of the report. "
            + (f"Missing: {', '.join(missing)}. " if missing else "")
            + (f"Not in this report: {', '.join(extra)}. " if extra else "")
            + f"The report's charts are: {', '.join(ids)}."
        )

    # 3. The narrative and the notes may only use numbers that occur in the
    #    data, the design, the experiments or the cited sources (a
    #    regulation's number, an article).
    evidence = {
        "verification": results["verification"],
        "simulation": results["simulation"],
        "design": (results["design"] or {}).get("evidence"),
        "experiments": results["experiments"],
    }
    texts = {**inp.narrative, **{f"figure {k}": v for k, v in inp.figure_notes.items()}}
    # The report is read by people who know their community, not the
    # research vocabulary: specialist terms belong in the technical
    # appendix, which the report generates itself (reports/plain.py).
    wordy = {k: jargon(v) for k, v in texts.items() if jargon(v)}
    if wordy:
        raise InvalidInput(
            "Write for a reader who does not know the research or its vocabulary. Replace: "
            + "; ".join(f"in {k}: {', '.join(terms)}" for k, terms in wordy.items())
        )
    problems = check_narrative(texts, collect_numbers([evidence, inp.citations]))
    if problems:
        # InvalidInput -> VALIDATION_ERROR with this message: the agent sees
        # exactly which numbers to remove or correct.
        raise InvalidInput(
            "The narrative contains numbers not found in the results: " + "; ".join(problems)
        )

    # 4. Queue the rendering. report_id is chosen here so the download URL
    #    can be signed now, before the PDF exists. Every call makes a NEW
    #    report (the policy marks this tool idempotentHint: false), so the
    #    id is random and a report job is never reused (jobs/queue.py reuses
    #    seeded simulations only).
    #    The expiry is decided here too and passed to the worker, so the
    #    signed link and the stored report record expire at the same moment.
    report_id = uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(seconds=get_settings().report_link_ttl_s)
    payload = {
        "report_id": report_id,
        "narrative": inp.narrative,
        "audience": inp.audience,
        "include_simulations": inp.include_simulations,
        "session_id": inp.session_id,
        "expires_at": expires_at.isoformat(),
        "citations": inp.citations,
        "figure_notes": inp.figure_notes,
    }
    job_id = await anyio.to_thread.run_sync(
        lambda: queue.enqueue_job(
            "report", payload, ctx.principal, vref, correlation_id=ctx.correlation_id
        )
    )

    # 5. Signed, expiring link (security/signed_urls.py, HMAC).
    return ReportRenderOutput(report_id=report_id, expires_at=expires_at, job_id=job_id)


TOOL = ToolSpec(
    id="report.render_pdf.v1",
    title="Render a PDF report",
    input_model=ReportRenderInput,
    output_model=ReportRenderOutput,
    handler=handle,
)
