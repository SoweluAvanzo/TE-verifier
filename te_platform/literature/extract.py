## =============================================================================
## te_platform/literature/extract.py — read a PDF's text and find what stands out
## =============================================================================
## GUIDE STEP   extension of 11.1 (structure-aware passages)
## PURPOSE      extract_pages(path, legal=...) returns (pages, strong): the text
##              of each page, without the repeated page furniture, and per page
##              the lines the PDF sets apart by font (bold, italic or larger
##              than the body text), which chunking.py uses to find headings.
## USED BY      literature/ingest.py.
## DEPENDS ON   pypdf (papers), pdfplumber (legal texts).
## WHY          Two extractors, because each fails where the other works,
##              measured on the collection: pypdf splits words inside lines of
##              EUR-Lex PDFs ("sha ll", "ref erred"), which hides them from
##              keyword search; pdfplumber reads those correctly but merges the
##              columns of two-column papers and scatters equations. Legal
##              texts here are single-column and have no equations.
## =============================================================================

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pdfplumber
from pypdf import PdfReader

FURNITURE_LINES = 2  # lines at each end of a page that may be a running header or footer
FURNITURE_SHARE = 0.25  # of the pages: a line repeated this often is not content
FURNITURE_MIN_PAGES = 5
MIN_PLUMBER_SHARE = 0.7
LARGER_THAN_BODY = 1.08  # a line this much larger than the body text stands out
_EMPHASIS = re.compile(
    r"bold|black|heavy|semibold|demi|italic|oblique|cmbx|cmti|cmsl|cmcsc|smallcaps", re.IGNORECASE
)
_DIGITS = re.compile(r"\d+")


def _without_furniture(pages: list[list[str]]) -> list[list[str]]:
    """Drop running headers and footers: edge lines that repeat, whatever their page number."""

    def shape(line: str) -> str:
        return _DIGITS.sub("#", " ".join(line.split()))

    def edges(lines: list[str]) -> list[str]:
        return lines[:FURNITURE_LINES] + lines[-FURNITURE_LINES:]

    if len(pages) < FURNITURE_MIN_PAGES:
        return pages
    counts = Counter(s for lines in pages for s in {shape(ln) for ln in edges(lines)})
    limit = max(3, FURNITURE_SHARE * len(pages))
    cleaned = []
    for lines in pages:
        edge = {shape(ln) for ln in edges(lines)}
        repeated = {s for s in edge if s == "#" or (s and counts[s] >= limit)}
        kept = [
            ln
            for i, ln in enumerate(lines)
            if not (
                (i < FURNITURE_LINES or i >= len(lines) - FURNITURE_LINES) and shape(ln) in repeated
            )
        ]
        cleaned.append(kept)
    return cleaned


def _body_size(sizes: Counter[float]) -> float:
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _read_paper(path: Path) -> tuple[list[list[str]], list[set[str]]]:
    """Read with pypdf; a visitor collects each text fragment's font and size."""
    pages: list[list[str]] = []
    fragments: list[list[tuple[str, float, str]]] = []
    sizes: Counter[float] = Counter()
    for page in PdfReader(str(path)).pages:
        seen: list[tuple[str, float, str]] = []

        def visit(
            text: str,
            _cm: Any,
            tm: Any,
            font: Any,
            size: float,
            seen: list[tuple[str, float, str]] = seen,
        ) -> None:
            clean = " ".join(text.split())
            if not clean:
                return
            scale = abs(tm[3]) if tm[3] else 1.0
            height = round(size * scale, 1)
            name = str(font.get("/BaseFont", "")) if font else ""
            seen.append((clean, height, name))
            sizes[height] += len(clean)

        text = (page.extract_text(visitor_text=visit) or "").replace("\x00", "")
        pages.append(text.splitlines())
        fragments.append(seen)
    body = _body_size(sizes)
    strong: list[set[str]] = []
    for seen in fragments:
        marked = set()
        for clean, height, name in seen:
            if height > body * LARGER_THAN_BODY or _EMPHASIS.search(name):
                marked.add(clean)
        strong.append(marked)
    return pages, strong


def _read_law(path: Path) -> tuple[list[list[str]], list[set[str]]]:
    """Read with pdfplumber, line by line, with each line's main font."""
    pages: list[list[str]] = []
    styles: list[list[tuple[str, float, str]]] = []
    sizes: Counter[float] = Counter()
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            lines, seen = [], []
            for line in page.extract_text_lines(return_chars=True):
                chars = line["chars"]
                height = Counter(round(c["size"], 1) for c in chars).most_common(1)[0][0]
                name = Counter(c["fontname"] for c in chars).most_common(1)[0][0]
                text = " ".join(line["text"].split())
                lines.append(text)
                seen.append((text, height, name))
                sizes[height] += len(text)
            pages.append(lines)
            styles.append(seen)
    body = _body_size(sizes)
    strong = [
        {t for t, h, n in seen if h > body * LARGER_THAN_BODY or _EMPHASIS.search(n)}
        for seen in styles
    ]
    return pages, strong


def _chars(pages: list[list[str]]) -> int:
    return sum(len(line) for lines in pages for line in lines)


def extract_pages(path: Path, *, legal: bool) -> tuple[list[str], list[set[str]]]:
    """Return the text of each page without furniture, and each page's stand-out lines."""
    pages, strong = _read_paper(path)
    if legal:
        law_pages, law_strong = _read_law(path)
        # A few PDFs use fonts pdfplumber cannot decode (Regulation 2023/1113:
        # 1 line on most pages); then pypdf's text, with split words, is better.
        if _chars(law_pages) >= MIN_PLUMBER_SHARE * _chars(pages):
            pages, strong = law_pages, law_strong
    return ["\n".join(lines) for lines in _without_furniture(pages)], strong
