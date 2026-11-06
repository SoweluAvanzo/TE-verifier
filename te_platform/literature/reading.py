## =============================================================================
## te_platform/literature/reading.py — how to read a passage, and how to link it
## =============================================================================
## GUIDE STEP   extension of 11.2 (critical reading of sources)
## PURPOSE      describe() names what kind of evidence a passage is and what its
##              source's distance from token systems means for using it.
##              cite_text() and cite_markdown() give the citation and the link
##              that opens the passage in the source viewer.
## USED BY      tools/lit_search.py, tools/lit_read.py, agent/literature_api.py.
## WHY          A passage of Fisher (1911) and a measurement on an Ethereum DAO
##              are not evidence in the same way. Saying so next to each passage
##              puts the question in front of the model when it needs it; what
##              the passage is worth for THIS design remains the model's judgement.
## =============================================================================

from typing import Any

from te_platform.literature.chunking import cite_as

EVIDENCE_TYPES = {
    "empirical_value": "empirical: a measured value or observed fact",
    "case_study": "use case: how one real system worked",
    "mechanism": "theory: how and why something happens",
    "definition": "conceptual: a definition or classification",
    "method": "methodological: how to model, simulate, estimate or evaluate",
    "remedy": "design remedy: a proposed or tested fix",
    "legal_rule": "legal: a provision or its interpretation",
    "other": "background: not direct evidence",
}
FORMAL_EVIDENCE = "formal: formulas, theorems or definitions usable for modelling"
UNLABELLED_EVIDENCE = "not classified yet: judge it from the text"

TIER_LABELS = {
    0: "law or method",
    1: "blockchain-based systems",
    2: "related, not blockchain-based",
    3: "foundational theory",
}
_TIER_READING = {
    0: "Applies by subject: check that it covers this kind of system and jurisdiction.",
    1: "About blockchain-based systems: check that it is the same kind of system and scale.",
    2: "Not blockchain-based: say what changes on-chain (cost, transparency, who can join, "
    "exit to speculation) before transferring it.",
    3: "Written for other settings: state its assumptions, say which hold here, and mark "
    "your adaptation as your own reasoning.",
}


def describe(row: dict[str, Any]) -> tuple[str, str]:
    """Return (evidence type, how to read it) for a passage row."""
    if row.get("formal"):
        evidence = FORMAL_EVIDENCE
    else:
        evidence = EVIDENCE_TYPES.get(row.get("kind") or "", UNLABELLED_EVIDENCE)
    return evidence, _TIER_READING[row.get("tier", 0)]


def cite_text(row: dict[str, Any]) -> str:
    """Return 'Collom 2012, p. 4' or 'MiCA ... 2023, Article 19(1)': what a reader sees."""
    where = row.get("locator") or (f"p. {row['page']}" if row.get("page") else "")
    base = short_name(row)
    return f"{base}, {where}" if where else base


def short_name(row: dict[str, Any]) -> str:
    """Return the work's short name, from its authors and year."""
    if row.get("tier") == 0 and "law" in row.get("systems", ()):
        return row["citation_key"]
    return cite_as(row["authors"], row.get("year"))


def passage_link(passage_id: int) -> str:
    """Return the address of a passage in the source viewer (webapp/chat_routes.py)."""
    return f"/literature/passage/{passage_id}"


def cite_markdown(row: dict[str, Any]) -> str:
    """Return the citation as a Markdown link to the passage."""
    return f"[{cite_text(row)}]({passage_link(row['id'])})"


def original_url(row: dict[str, Any]) -> str | None:
    """Return where a reader finds the original: the curated link, else the DOI."""
    if row.get("source_url"):
        return row["source_url"]
    return f"https://doi.org/{row['doi']}" if row.get("doi") else None


def source_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Return the fields every passage carries to the agent and to the browser."""
    evidence, how = describe(row)
    return {
        "passage_id": row["id"],
        "cite": cite_text(row),
        "cite_markdown": cite_markdown(row),
        "link": passage_link(row["id"]),
        "original_url": original_url(row),
        "evidence_type": evidence,
        "source_tier": row.get("tier", 0),
        "source_group": TIER_LABELS[row.get("tier", 0)],
        "how_to_read": how,
    }
