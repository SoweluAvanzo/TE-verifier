## =============================================================================
## te_platform/agent/user_reports_api.py — download a rendered PDF report
## =============================================================================
## GUIDE STEP   10.3
## PURPOSE      GET /agent/reports/{report_id}?exp=...&sig=...: the signed link
##              returned by the report tool (tools/report_render_pdf.py)
##              points here. It streams the PDF from the reports volume.
##              The router is included by agent/app.py.
## USED BY      agent/app.py (include_router), the browser (the link in the
##              chat), the tests.
## DEPENDS ON   fastapi, anyio; agent/auth.py (CurrentUser),
##              security/signed_urls.py (verify_download), db/repo.py +
##              db/session.py (Repository.get_report), config.py (the signing
##              key, through signed_urls.py).
## WHY          Two independent checks, both required (defence in depth):
##                1. the signature and expiry (security/signed_urls.py): the
##                   link was issued by us and has not expired or been
##                   altered -> otherwise 403;
##                2. the logged-in user owns the report (Repository.get_report
##                   raises NotFound otherwise, which agent/app.py turns into
##                   the same 404 as an unknown id, so nobody can probe ids).
##              The file is read from the reports volume, which compose.yml
##              mounts read-only into this container (the worker writes it).
## ACTIVATE     Uncomment, then toggle the report_api lines in agent/app.py.
##              The signing key (TE_REPORT_SIGNING_KEY, a Docker secret) must
##              be given to both the mcp service (signs) and the agent
##              service (verifies).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|"
## are short illustrations, not the full code. Keep the path and the query
## parameter names exp and sig exactly: security/signed_urls.py builds the
## links with them. Activate security/signed_urls.py first.
##
## Guide 10.3
## [ ] 1. Imports at the top: Path, Any, anyio, APIRouter and HTTPException,
##        FileResponse, CurrentUser (agent/auth.py), Repository,
##        session_scope and verify_download (security/signed_urls.py). Then
##        `router = APIRouter()`.
## [ ] 2. GET /agent/reports/{report_id} `download_report(report_id, exp:
##        int, sig: str, principal: CurrentUser)` -> FileResponse:
##        verify_download false -> 403 "This link is invalid or has
##        expired."; Repository(db, principal).get_report(report_id) in a
##        worker thread (a NotFound becomes 404 through agent/app.py);
##        the file not there yet -> 404 "not ready"; else
##          | return FileResponse(path, media_type="application/pdf",
##          |                     filename=f"report-{report_id}.pdf")
##        Check `is_file()` in the worker thread too: it touches the disk,
##        and async code must not block (ruff's ASYNC rules check it).
## [ ] 3. Toggle the report_api lines of agent/app.py.
## [ ] 4. Check (guide 10.3): activate the guide 10.3 tests of
##        tests/platform_tests/test_platform_agent.py (the link works for
##        its owner; an expired or altered link gives 403; another user, even
##        with the link, gets 404), then
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from pathlib import Path
from typing import Any

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from te_platform.agent.auth import CurrentUser
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.security.signed_urls import verify_download

router = APIRouter()


@router.get("/agent/reports/{report_id}")
async def download_report(
    report_id: str, exp: int, sig: str, principal: CurrentUser
) -> FileResponse:
    """Stream the PDF if the link is valid AND the logged-in user owns the report."""
    if not verify_download(report_id, exp, sig):
        raise HTTPException(status_code=403, detail="This link is invalid or has expired.")

    def _find() -> tuple[dict[str, Any], bool]:
        with session_scope() as db:
            report = Repository(db, principal).get_report(report_id)  # NotFound -> 404
        return report, Path(report["path"]).is_file()

    report, ready = await anyio.to_thread.run_sync(_find)
    if report.get("reviewed_at") is None:
        # A draft: the assistant has not yet checked it (report.publish.v1).
        raise HTTPException(
            status_code=404,
            detail="The assistant is still checking this report; it will be available shortly.",
        )
    if not ready:
        # The record exists but the worker has not finished writing the PDF.
        raise HTTPException(
            status_code=404, detail="The report is not ready yet; try again shortly."
        )
    # inline: the browser shows the PDF (its viewer can still save it);
    # "attachment" saved it silently to the downloads folder, which looked
    # like nothing happening.
    return FileResponse(
        report["path"],
        media_type="application/pdf",
        filename=f"report-{report_id}.pdf",
        content_disposition_type="inline",
    )
