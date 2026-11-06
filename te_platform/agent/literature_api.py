## =============================================================================
## te_platform/agent/literature_api.py — a passage and its surroundings, for the source viewer
## =============================================================================
## GUIDE STEP   extension of 9.3 (clickable sources)
## PURPOSE      GET /agent/literature/passages/{id}: the data of the source viewer
##              (webapp/templates/passage.html): the passage, the rest of its
##              section nearby, its neighbours, and the link to the original.
## USED BY      webapp/static/passage.js.
## WHY          Logged-in users only, a window of passages at a time, never the PDF:
##              works are stored for research under their own licences
##              (works.licence), so the viewer shows the passage in its context
##              and sends the reader to the publisher for the full document.
## =============================================================================

from typing import Any

import anyio
from fastapi import APIRouter

from te_platform.agent.auth import CurrentUser
from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope
from te_platform.literature.reading import TIER_LABELS, cite_text, describe, original_url

router = APIRouter()


@router.get("/agent/literature/passages/{passage_id}")
async def passage(passage_id: int, principal: CurrentUser) -> dict[str, Any]:  # noqa: ARG001
    """Return a passage for reading (NotFound -> 404)."""

    def _load() -> dict[str, Any]:
        with session_scope() as db:
            return LiteratureRepository(db).passage_view(passage_id)

    view = await anyio.to_thread.run_sync(_load)
    row = view["passage"]
    evidence, how = describe(row)
    return {
        "passage_id": row["id"],
        "cite": cite_text(row),
        "citation_key": row["citation_key"],
        "title": row["title"],
        "authors": row["authors"],
        "year": row["year"],
        "venue": row["venue"],
        "page": row["page"],
        "section": row["section"],
        "locator": row["locator"],
        "context": row["context"],
        "evidence_type": evidence,
        "source_group": TIER_LABELS[row["tier"]],
        "how_to_read": how,
        "original_url": original_url(row),
        "section_passages": [
            {"passage_id": r["id"], "page": r["page"], "locator": r["locator"], "text": r["text"]}
            for r in view["section_passages"]
        ],
        "previous_id": view["previous_id"],
        "next_id": view["next_id"],
    }
