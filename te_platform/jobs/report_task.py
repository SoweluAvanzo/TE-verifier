## =============================================================================
## te_platform/jobs/report_task.py — the report-rendering task the worker runs
## =============================================================================
## GUIDE STEP   10.3
## PURPOSE      render_report(payload) renders the PDF report of a
##              verification, writes the file to the reports volume and
##              stores its record (reports table). It is the job queued by
##              tools/report_render_pdf.py (queue.py names it
##              "te_platform.jobs.report_task.render_report").
## USED BY      worker.py, through RQ (by its dotted name);
##              tests/platform_tests/test_platform_reports.py (section 3).
## DEPENDS ON   reports/render.py (WeasyPrint), db/repo.py + db/session.py,
##              elicitation/protocol.py, registry/policy.py, hashing.py,
##              config.py, jobs/tasks.py (bind_job_logging).
## WHY          A separate module from jobs/tasks.py on purpose: WeasyPrint
##              needs system libraries (Pango) that only the worker image
##              installs. Every worker imports tasks.py (the simulations and
##              the end-of-job callbacks); only a report job imports this
##              module, so simulations keep working where Pango is missing
##              (e.g. a developer's laptop), and the import stays at the top
##              of the file like every other import.
##              The END of a report job is recorded exactly like a
##              simulation's: by the callbacks of jobs/tasks.py, which call
##              queue.settle_job (queue.py header LIFECYCLE).
## PAYLOAD      Keys written by tools/report_render_pdf.py + queue.enqueue_job:
##                verification_ref, principal_id, session_id, correlation_id,
##                report_id, narrative, audience, include_simulations,
##                expires_at, citations
## ACTIVATE     Uncomment at guide 10.3, with tools/report_render_pdf.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|"
## are short illustrations, not the full code. Keep the name render_report:
## queue.py names it as "te_platform.jobs.report_task.render_report".
##
## Guide 10.3 (first: reports/render.py, the report methods of db/repo.py
## and the reports table of db/models.py)
## [ ] 1. Imports at the top: UTC and datetime, Any; get_settings,
##        ReportRecord and Repository, session_scope, load_protocol,
##        verifier_version, bind_job_logging, Principal, load_policy and
##        render_pdf.
## [ ] 2. `render_report(payload) -> dict[str, Any]`: bind_job_logging,
##        then 1. read the verification (and, if include_simulations,
##        latest_finished_simulation) in a short session_scope, RuntimeError
##        if it is missing; 2. render_pdf(...) outside any transaction, with
##        the provenance dict as in the SOLUTION; 3. write the PDF to
##        settings.report_storage_dir as "<report_id>.pdf" and save_report
##        (a ReportRecord) in a second session_scope; return
##          | {"kind": "report", "report_id": payload["report_id"]}
## [ ] 3. Check: test_report_task_writes_the_pdf_and_its_record (the
##        "Guide 10.3" section of test_platform_reports.py) calls
##        render_report with a real payload; it needs the PostgreSQL of
##        test_platform_db.py (HOW TO RUN there):
##          | uv run pytest tests/platform_tests/test_platform_reports.py -q \
##          |     -k report_task
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from pypdf import PdfReader

from te_platform.config import get_settings
from te_platform.db.repo import ReportRecord, Repository
from te_platform.db.session import session_scope
from te_platform.elicitation.protocol import load_protocol
from te_platform.hashing import verifier_version
from te_platform.jobs.tasks import bind_job_logging
from te_platform.registry.context import Principal
from te_platform.registry.policy import load_policy
from te_platform.reports.design import design_context
from te_platform.reports.render import render_pdf


def render_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Render a PDF report and store it (tool report.render_pdf.v1).

    The report tool already chose report_id and expires_at and signed the
    download link, so the user had a link immediately; this task makes the
    link work. Inputs come from the database, not from the payload: the
    stored verification (by verification_ref) and, if requested, the latest
    finished Monte Carlo run. The agent only contributes the `narrative`
    sections, which the renderer checks number by number
    (reports/numbers_check.py, P1).
    """
    bind_job_logging("report", payload)
    settings = get_settings()
    # The Repository only compares principal ids, so the kind does not matter.
    principal = Principal(id=payload["principal_id"], kind="user")
    vref = payload["verification_ref"]

    # 1. Read the data (short transaction).
    with session_scope() as db:
        repo = Repository(db, principal)
        verification = repo.get_verification(vref)
        simulation = (
            repo.latest_finished_simulation(vref) if payload.get("include_simulations") else None
        )
        # The design part of the report (reports/design.py): only a report
        # made inside a design session has a spec, answers and messages.
        sid = payload.get("session_id")
        design = (
            design_context(
                repo.get_session_facts(sid).current_spec,
                repo.get_answers(sid),
                repo.list_messages(sid),
            )
            if sid
            else None
        )
        experiments = repo.finished_experiments(vref)
    if verification is None:
        # The tool checked this before queueing; reaching here means the
        # row disappeared meanwhile. Fail loudly (on_job_failure records it).
        raise RuntimeError(f"verification {vref} not found")

    # 2. Render (slow, outside any database transaction).
    pdf_bytes = render_pdf(
        verification=verification,
        simulation=simulation,
        narrative=payload.get("narrative", {}),
        provenance={
            "spec_name": verification.get("te_name", ""),
            "spec_hash": verification.get("spec_hash", ""),
            "verification_ref": vref,
            "verifier_version": verifier_version(),
            # Versions of the rulebooks in force when the report was made
            # (read from the files).
            "policy_version": load_policy(settings.policy_dir / "tool_policy.yaml").policy_version,
            "protocol_version": load_protocol(
                settings.policy_dir / "elicitation_protocol.yaml"
            ).version,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            # Overrides of policy rules are recorded per tool call in the
            # audit log (registry/pipeline.py). Printing the relevant ones
            # here is a possible extension (it needs a link from audit rows
            # to sessions, which audit_log does not have yet). Empty until
            # then.
            "overrides": [],
            "spec_summary": [],
        },
        citations=payload.get("citations", []),
        design=design,
        experiments=experiments,
        figure_notes=payload.get("figure_notes", {}),
    )

    # 3. Store the file on the reports volume, then its record. expires_at
    # is an ISO 8601 time WITH its time zone (the tool writes UTC), so it
    # fits the timestamptz column (db/models.py, header TIME).
    path = settings.report_storage_dir / f"{payload['report_id']}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes)
    record = ReportRecord(
        report_id=payload["report_id"],
        verification_ref=vref,
        narrative=payload.get("narrative", {}),
        path=str(path),
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        session_id=payload.get("session_id"),
    )
    with session_scope() as db:
        Repository(db, principal).save_report(record)
    # The report is a DRAFT until the agent has read it and confirmed it is
    # correct (tool report.publish.v1); the download link refuses it until
    # then. The agent reads the text exactly as the PDF shows it.
    text = review_text(pdf_bytes)
    return {
        "kind": "report",
        "report_id": payload["report_id"],
        "state": "draft: read review_text, then call report.publish.v1",
        "pages": text["pages"],
        "review_text": text["text"],
    }


## The text of the rendered PDF, page by page, for the agent's review. Long
## reports are cut at REVIEW_MAX characters; the technical appendix (last)
## is what gets cut first.
REVIEW_MAX = 60_000


def review_text(pdf_bytes: bytes) -> dict[str, Any]:
    """Return the rendered report's text (and its page count) for the agent's review."""
    reader = PdfReader(BytesIO(pdf_bytes))
    pages = [p.extract_text() or "" for p in reader.pages]
    joined = "\n\n".join(f"[page {n}]\n{t}" for n, t in enumerate(pages, start=1))
    if len(joined) > REVIEW_MAX:
        joined = joined[:REVIEW_MAX] + "\n[... the rest of the technical appendix is cut ...]"
    return {"pages": len(pages), "text": joined}
