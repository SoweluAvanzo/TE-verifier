## =============================================================================
## te_platform/literature/rechunk.py — re-split stored works, keeping their labels
## =============================================================================
## GUIDE STEP   extension of 11.1 (structure-aware passages)
## PURPOSE      rechunk_work(work, pdf) splits a stored work again with the
##              current chunker, and gives each new passage the labels of the
##              old passage it overlaps most. Passages with no good match stay
##              unlabelled for `lit enrich`; every new passage needs a new vector.
## USED BY      cli.py (`te-platform lit rechunk`).
## WHY          Labelling costs a model call per passage (20 hours for the whole
##              collection), while most text only moves to a different boundary.
## =============================================================================

import re
from itertools import pairwise
from pathlib import Path
from typing import Any

from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope
from te_platform.literature.catalog import is_legal, lookup
from te_platform.literature.chunking import Chunk, split_into_chunks
from te_platform.literature.extract import extract_pages

MIN_OVERLAP = 0.5  # share of a new passage's word pairs found in the old one
_WORD = re.compile(r"\w+")


def _word_pairs(text: str) -> set[tuple[str, str]]:
    words = _WORD.findall(text.lower())
    return set(pairwise(words))


def transfer_labels(new: list[Chunk], old: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """Return, per new passage, the old passage holding most of its text, or None."""
    index: dict[tuple[str, str], list[int]] = {}
    for i, row in enumerate(old):
        for pair in _word_pairs(row["text"]):
            index.setdefault(pair, []).append(i)
    matches: list[dict[str, Any] | None] = []
    for chunk in new:
        pairs = _word_pairs(chunk.text)
        votes: dict[int, int] = {}
        for pair in pairs:
            for i in index.get(pair, ()):
                votes[i] = votes.get(i, 0) + 1
        best = max(votes, key=lambda i: votes[i], default=None)
        good = best is not None and votes[best] >= MIN_OVERLAP * max(1, len(pairs))
        matches.append(old[best] if good else None)
    return matches


def rechunk_work(citation_key: str, pdf: Path) -> dict[str, int]:
    """Replace a work's passages; return how many there are and how many kept labels."""
    entry = lookup(citation_key)
    if entry is None:
        raise ValueError(f"{citation_key} is not in literature/catalog.yaml.")
    legal = is_legal(entry["systems"])
    pages, strong = extract_pages(pdf, legal=legal)
    chunks = split_into_chunks(pages, legal=legal, strong=strong)
    if not chunks:
        raise ValueError(f"{pdf} gave no passages: keeping the old ones.")
    with session_scope() as db:
        repo = LiteratureRepository(db)
        old = repo.labelled_passages(citation_key)
        matches = transfer_labels(chunks, old)
        repo.replace_passages(citation_key, chunks, matches, entry)
    return {
        "before": len(old),
        "after": len(chunks),
        "labels_kept": sum(m is not None for m in matches),
    }
