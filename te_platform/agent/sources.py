## =============================================================================
## te_platform/agent/sources.py — the passages a literature tool returned, for the browser
## =============================================================================
## GUIDE STEP   extension of 9.3 (clickable sources)
## PURPOSE      sources_in(tool, result) picks from a lit.search.v1 or lit.read.v1
##              result what the browser needs to list a passage and link it.
## USED BY      agent/loop.py (live), agent/transcript.py (reopened conversations).
## WHY          So every source consulted is clickable whatever the model wrote:
##              the list comes from the tool results, not from the model's text.
## =============================================================================

from typing import Any

LITERATURE_TOOLS = frozenset({"lit.search.v1", "lit.read.v1"})
_FIELDS = (
    "passage_id",
    "cite_markdown",
    "evidence_type",
    "source_group",
    "citation_key",
    "title",
    "section",
)


def sources_in(tool: str, result: Any) -> list[dict[str, Any]]:
    """Return the passages of a literature tool's result, one entry per passage."""
    if tool not in LITERATURE_TOOLS or not isinstance(result, dict):
        return []
    entries = result.get("hits") or result.get("passages") or []
    shared = {k: result[k] for k in ("citation_key", "title") if k in result}
    return [
        {k: v for k, v in {**shared, **e}.items() if k in _FIELDS}
        for e in entries
        if isinstance(e, dict) and "passage_id" in e
    ]
