## =============================================================================
## te_platform/literature/ingest.py — add one curated paper to the collection
## =============================================================================
## GUIDE STEP   11.1
## PURPOSE      ingest_pdf(pdf_path, bib_path, licence, *, full_text_allowed)
##              1. reads the paper's BibTeX entry (title, authors, year,
##                 venue, DOI, citation key);
##              2. extracts the text of each page with pypdf;
##              3. splits it into passages (chunking.py);
##              4. stores one `works` row and its `chunks` rows, through
##                 db/repo.py LiteratureRepository (the only code that
##                 queries the database).
##              If full_text_allowed is False (the licence does not permit
##              storing the full text), only the abstract is stored as a chunk.
##              Returns the new work's id.
## USED BY      cli.py (`te-platform lit ingest <pdf> --bib <entry.bib>
##              --licence <id> [--full-text-allowed]`). The curator runs it and reviews
##              the printed summary; end users can never upload papers (D15).
## DEPENDS ON   pypdf, literature/chunking.py, db/session.py, db/repo.py
##              (LiteratureRepository).
## WHY          D15: a curated, reviewed collection is the point of the
##              feature; recording the licence per work lets search.py and the
##              public endpoint respect it.
## BIBTEX       The parser below handles ONE simple entry (`@article{key,
##              field = {value}, ...}`), which is what you export per paper
##              from a reference manager. For messy files, use a library such
##              as `bibtexparser` instead and replace _parse_bibtex.
## ACTIVATE     Uncomment after phase 5 (database) and the `literature` extra;
##              test with a small, openly licensed PDF fixture.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|"
## are short illustrations, not the full code. Keep ingest_pdf and its
## arguments exactly: cli.py calls it.
##
## Guide 11.1 (first: chunking.py, the works and chunks tables of
## db/models.py, LiteratureRepository in db/repo.py, and the `literature`
## extra for pypdf)
## [ ] 1. Imports at the top: re, Path, PdfReader (pypdf),
##        LiteratureRepository, session_scope, and Chunk and
##        split_into_chunks from chunking.py.
## [ ] 2. Two patterns for ONE simple BibTeX entry (header BIBTEX): _ENTRY
##        captures the citation key and the body of `@type{key, ...}`;
##        _FIELD captures each `name = {value}` or `name = "value"` pair.
## [ ] 3. `_parse_bibtex(text) -> dict[str, str]`: raise ValueError("Not a
##        single BibTeX entry.") if _ENTRY does not match; else lower-case
##        the field names, collapse the spaces in values, and add
##        "citation_key".
## [ ] 4. `ingest_pdf(pdf_path, bib_path, licence, *, full_text_allowed)
##        -> str` (a keyword-only flag: a bare True in a call says
##        nothing). Parse the .bib file (UTF-8); extract each page's text
##          | page.extract_text() or ""
##        from PdfReader(str(pdf_path)).pages, and raise ValueError when no
##        page has any text (scanned PDF); chunk the pages. If
##        full_text_allowed is False, keep only a Chunk with the BibTeX
##        abstract (page 1, section "Abstract"), or else the first chunk.
## [ ] 5. Still in ingest_pdf, in ONE session_scope: LiteratureRepository(
##        db).add_work(metadata, chunks) with the Work columns (year only
##        when it is all digits, venue from journal or booktitle); return
##        the work id.
## [ ] 6. Check: test_ingest_stores_work_and_passages in
##         tests/platform_tests/test_platform_literature.py (it makes a
##         small PDF and ingests it into the test database), then ingest a
##         real, openly licensed paper and review the printed summary:
##          | uv run te-platform lit ingest PAPER.pdf --bib ENTRY.bib
##          |     --licence "CC-BY-4.0"
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import re
from pathlib import Path

from pypdf import PdfReader

from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope
from te_platform.literature.chunking import Chunk, detect_language, split_into_chunks

_ENTRY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*)\}\s*$", re.DOTALL)
_FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*(?:,|$)", re.DOTALL)


def _parse_bibtex(text: str) -> dict[str, str]:
    """Return {"citation_key": ..., "title": ..., "author": ..., ...}."""
    match = _ENTRY.search(text.strip())
    if not match:
        raise ValueError("Not a single BibTeX entry.")
    fields = {k.lower(): " ".join(v.split()) for k, v in _FIELD.findall(match.group(2))}
    fields["citation_key"] = match.group(1)
    return fields


def ingest_pdf(pdf_path: Path, bib_path: Path, licence: str, *, full_text_allowed: bool) -> str:
    """Add one paper (PDF + BibTeX entry) to the collection; return the new work id."""
    bib = _parse_bibtex(bib_path.read_text(encoding="utf-8"))

    # extract_text() returns the text layer of each page. Scanned PDFs have
    # no text layer (OCR would be needed): fail loudly rather than store
    # an empty paper.
    # Some PDFs put NUL characters in their text layer; PostgreSQL text
    # columns refuse them, and they carry no meaning, so they are dropped.
    pages = [
        (page.extract_text() or "").replace("\x00", "") for page in PdfReader(str(pdf_path)).pages
    ]
    if not any(p.strip() for p in pages):
        raise ValueError(f"{pdf_path} has no extractable text (scanned PDF?).")

    chunks = split_into_chunks(pages)
    if not full_text_allowed:
        # Keep only what the licence allows: the abstract from BibTeX if
        # present, otherwise the first chunk (usually the abstract).
        abstract = bib.get("abstract")
        chunks = [Chunk(text=abstract, page=1, section="Abstract")] if abstract else chunks[:1]

    metadata = {
        "citation_key": bib["citation_key"],
        "title": bib.get("title", ""),
        "authors": bib.get("author", ""),
        "year": int(bib["year"]) if bib.get("year", "").isdigit() else None,
        "venue": bib.get("journal") or bib.get("booktitle"),
        "doi": bib.get("doi"),
        "licence": licence,
        "full_text_allowed": full_text_allowed,
        "language": detect_language(" ".join(pages)),
    }
    with session_scope() as db:
        return LiteratureRepository(db).add_work(metadata, chunks)
