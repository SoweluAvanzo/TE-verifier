## =============================================================================
## te_platform/tools/report_publish.py — tool report.publish.v1
## =============================================================================
## GUIDE STEP   none yet (report review extension of phase 10)
## PURPOSE      A rendered report is a DRAFT: its download link refuses it
##              (agent/user_reports_api.py). The agent reads the report's text
##              (the review_text in the finished report job, jobs.status.v1),
##              checks it against the conversation and the results, and calls
##              this tool with what it checked. The review is stored with the
##              report (reports.review, reviewed_at) and the tool returns the
##              signed download link, which now works.
## USED BY      the agent (via MCP).
## DEPENDS ON   db/repo.py (publish_report), security/signed_urls.py.
## WHY          The person asked that the assistant verify every report
##              before it can be downloaded; a link that works only after the
##              review makes that a rule, not a request.
## =============================================================================

from datetime import datetime
from typing import Any

import anyio
from pydantic import BaseModel, Field

from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.errors import InvalidInput
from te_platform.jobs import queue
from te_platform.registry.context import CallContext
from te_platform.registry.spec import ToolSpec
from te_platform.security.signed_urls import sign_download


class ReportPublishInput(BaseModel):
    """What a caller sends to report.publish.v1."""

    session_id: str | None = Field(default=None, description="The design session, if any.")
    job_id: str = Field(description="The job_id that report.render_pdf.v1 returned.")
    review: str = Field(
        min_length=80,
        max_length=3000,
        description="What you checked in the review_text, and the outcome: every number "
        "against the results and the designer's answers; each of the six answers and its "
        "reasons; the design description against the conversation; the recommendations "
        "against the tests; plain language for a non-specialist. State that no errors remain.",
    )
    correct: bool = Field(
        description="True only if the report is correct and readable as rendered. If not, "
        "do not publish: render it again with corrected text."
    )


class ReportPublishOutput(BaseModel):
    """The download link, which works from now on."""

    report_id: str
    job_id: str
    download_url: str
    expires_at: datetime


def _publish(ctx: CallContext, job_id: str, review: str) -> dict[str, Any]:
    """Find the finished report job, then record the review on its report."""
    job = queue.get_job(job_id, ctx.principal)
    if job.kind != "report":
        raise InvalidInput("This job is not a report.")
    if job.status != "finished" or not job.result:
        raise InvalidInput(
            "The report is not rendered yet: call jobs.status.v1 with wait_s 30, read its "
            "review_text, then publish."
        )
    report_id = str(job.result["report_id"])
    with session_scope() as db:
        return Repository(db, ctx.principal).publish_report(report_id, review)


async def handle(inp: ReportPublishInput, ctx: CallContext) -> ReportPublishOutput:
    """Record the agent's review of a rendered report and return its download link."""
    if not inp.correct:
        raise InvalidInput(
            "A report with errors is not published. Render it again with corrected text "
            "(report.render_pdf.v1), review the new one, then publish that."
        )
    record = await anyio.to_thread.run_sync(lambda: _publish(ctx, inp.job_id, inp.review))
    expires_at = record["expires_at"]
    return ReportPublishOutput(
        report_id=record["report_id"],
        job_id=inp.job_id,
        download_url=sign_download(record["report_id"], expires_at),
        expires_at=expires_at,
    )


TOOL = ToolSpec(
    id="report.publish.v1",
    title="Publish a reviewed report",
    input_model=ReportPublishInput,
    output_model=ReportPublishOutput,
    handler=handle,
)
