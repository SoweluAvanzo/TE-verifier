## =============================================================================
## te_platform/literature/chunking.py — split a paper into short, citable passages
## =============================================================================
## GUIDE STEP   11.1
## PURPOSE      split_into_chunks(pages) turns the extracted text of a PDF
##              (one string per page) into a list of Chunk objects: short
##              passages that keep their page number and the section heading
##              they belong to. Search results (search.py) are chunks, so a
##              chunk is the unit a user reads and the agent cites.
## USED BY      literature/ingest.py.
## DEPENDS ON   Python standard library (re, dataclasses). Pure function.
## WHY          Short passages make search precise (a hit points to the
##              relevant paragraph, not the whole paper), keep what the public
##              endpoint returns short (copyright, D15), and keep page numbers
##              so citations can say "p. 12".
## HEURISTICS   PDF text has no reliable structure, so we use simple rules:
##              - a paragraph ends at an empty line; inside it, line breaks
##                and repeated spaces (from the PDF layout) become one space;
##              - a heading is a paragraph of at most 90 characters (a
##                heading may wrap over two lines in the PDF), without a
##                final period, that is numbered ("3.2 Results",
##                "4. Discussion"), or in UPPER CASE ("RELATED WORK"), or in
##                Title Case ("Related Work", "Governance of the Commons":
##                it starts with a capital and every word is capitalised
##                except short words like "of");
##              - paragraphs are joined until MAX_CHARS; a longer paragraph is
##                cut at sentence ends, a longer sentence at spaces, and a
##                word longer than MAX_CHARS (rare: URLs, broken text layers)
##                inside the word;
##              - a chunk shorter than MIN_CHARS is merged with the next text
##                when it fits, even across a page break (tiny fragments such
##                as captions are not worth a search result of their own).
##              Improve them on real papers; the tests pin the behaviour.
## GUARANTEES   (tested in test_platform_literature.py, partly with
##              Hypothesis, which tries many generated inputs)
##              - no chunk is longer than MAX_CHARS;
##              - no text is lost or invented: the chunks' texts, in order,
##                equal the input text without its heading lines, modulo
##                whitespace (spaces and line breaks may differ);
##              - each chunk keeps the page where it starts and the heading
##                above it.
## ACTIVATE     Uncomment; tests: section 1 of test_platform_literature.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|"
## are short illustrations, not the full code. Keep Chunk, MAX_CHARS and
## split_into_chunks exactly: ingest.py and the tests import them.
##
## Guide 11.1 (a pure function: nothing else needs to be active)
## [ ] 1. Imports at the top: re and dataclass.
## [ ] 2. Constants MAX_CHARS = 1200, MIN_CHARS = 200, HEADING_MAX_CHARS
##        = 90 and MIN_UPPER_LETTERS = 3; the patterns _NUMBERED ("3.2
##        Results"), _WORDS_ONLY (letters, spaces, commas, colons,
##        apostrophes and dashes) and _SENTENCE_END (spaces after . ! or ?):
##          | _SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
##        and _MINOR_WORDS, the short words Title Case leaves lower-case.
## [ ] 3. `@dataclass(frozen=True) class Chunk` with text, page (1-based,
##        where the chunk starts) and section ("" before any heading).
## [ ] 4. `_is_heading(line) -> bool`, the header HEURISTICS rule: 1-90
##        characters, no final ".", and numbered, or starting with a
##        capital and in UPPER CASE or Title Case.
## [ ] 5. `_cut(text) -> list[str]`: pieces of at most MAX_CHARS, cut at the
##        last space before the limit, or at the limit when there is none.
## [ ] 6. `_split_long(paragraph) -> list[str]`: [paragraph] when it fits;
##        otherwise walk its sentences (each one _cut), adding them to
##        `current` until the next would pass MAX_CHARS, then start a new
##        part.
## [ ] 7. `_paragraphs(page_text) -> list[str]`: split at empty lines,
##        join each block's words with single spaces, drop empty ones.
## [ ] 8. `split_into_chunks(pages: list[str]) -> list[Chunk]`: keep
##        `chunks`, `section`, a `buffer` and its start page, and an inner
##        flush() that appends the buffer as a Chunk and empties it (it
##        needs `nonlocal buffer`). For each page (enumerate from 1): flush
##        if the buffer has >= MIN_CHARS (a chunk is cited by its page);
##        then for each paragraph: a heading flushes and becomes the
##        section; any other paragraph is cut with _split_long and each
##        piece added to the buffer, flushing first when it would not fit.
##        Flush once more after the loop.
## [ ] 9. Check: activate sections 1 and 2 of
##        tests/platform_tests/test_platform_literature.py, then
##          | uv run pytest tests/platform_tests/test_platform_literature.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import re
from dataclasses import dataclass

MAX_CHARS = 1200  # about 200 words: one or two paragraphs
MIN_CHARS = 200  # merge tiny fragments (captions, page furniture) into neighbours
HEADING_MAX_CHARS = 90
MIN_UPPER_LETTERS = 3  # "RELATED WORK" is a heading, a stray "A" is not

_NUMBERED = re.compile(r"\d+(\.\d+)*\.?\s+\S")  # "3.2 Results", "4. Discussion"
_WORDS_ONLY = re.compile(r"[A-Za-z][A-Za-z ,:'-]*")  # no digits, no sentence punctuation
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_MINOR_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "via",
        "vs",
        "with",
    }
)


@dataclass(frozen=True)
class Chunk:
    """A short passage of a paper, with where it comes from."""

    text: str
    page: int  # 1-based page number where the chunk starts
    section: str  # nearest heading above it ("" if none yet)


def _is_heading(line: str) -> bool:
    """Return True for a numbered, UPPER CASE or Title Case heading (header HEURISTICS)."""
    if not 0 < len(line) <= HEADING_MAX_CHARS or line.endswith("."):
        return False
    if _NUMBERED.match(line):
        return True
    if not _WORDS_ONLY.fullmatch(line):
        return False
    if not line[0].isupper():
        return False  # Title and UPPER case both start with a capital
    letters = [ch for ch in line if ch.isalpha()]
    if all(ch.isupper() for ch in letters):
        return len(letters) >= MIN_UPPER_LETTERS
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", line)
    return all(w[0].isupper() or w.lower() in _MINOR_WORDS for w in words)


def _cut(text: str) -> list[str]:
    """Cut a text into pieces of at most MAX_CHARS, at spaces where possible.

    The text has single spaces only (split_into_chunks normalises it). A
    piece is cut inside a word only when the word alone is too long.
    """
    pieces: list[str] = []
    while len(text) > MAX_CHARS:
        cut = text.rfind(" ", 0, MAX_CHARS + 1)
        if cut <= 0:  # no space: cut inside the word
            pieces.append(text[:MAX_CHARS])
            text = text[MAX_CHARS:]
        else:
            pieces.append(text[:cut])
            text = text[cut + 1 :]
    if text:
        pieces.append(text)
    return pieces


def _split_long(paragraph: str) -> list[str]:
    """Cut a paragraph into parts of at most MAX_CHARS, at sentence ends where possible."""
    if len(paragraph) <= MAX_CHARS:
        return [paragraph]
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(paragraph):
        for piece in _cut(sentence):
            if current and len(current) + 1 + len(piece) > MAX_CHARS:
                parts.append(current)
                current = piece
            else:
                current = f"{current} {piece}" if current else piece
    if current:
        parts.append(current)
    return parts


def _paragraphs(page_text: str) -> list[str]:
    """Return the paragraphs of a page (text between empty lines), each on one line.

    Line breaks and repeated spaces from the PDF layout become one space.
    """
    paragraphs = (" ".join(block.split()) for block in re.split(r"\n\s*\n", page_text))
    return [p for p in paragraphs if p]


def split_into_chunks(pages: list[str]) -> list[Chunk]:
    """Split the pages of a paper into passages (header HEURISTICS and GUARANTEES)."""
    chunks: list[Chunk] = []
    section = ""
    buffer, buffer_page = "", 1

    def flush() -> None:
        nonlocal buffer
        if buffer:
            chunks.append(Chunk(text=buffer, page=buffer_page, section=section))
        buffer = ""

    for page_no, page_text in enumerate(pages, start=1):
        # A chunk is cited by its page, so avoid chunks that start on one
        # page and continue on the next: at a page break, close the current
        # chunk unless it is a tiny fragment (then it is merged, see below).
        if len(buffer) >= MIN_CHARS:
            flush()
        for paragraph in _paragraphs(page_text):
            if _is_heading(paragraph):
                flush()
                section = paragraph
                continue
            for piece in _split_long(paragraph):
                # MAX_CHARS is a hard limit, MIN_CHARS only a preference:
                # when the piece does not fit, flush even a short buffer.
                if buffer and len(buffer) + 1 + len(piece) > MAX_CHARS:
                    flush()
                if not buffer:
                    buffer_page = page_no
                buffer = f"{buffer} {piece}" if buffer else piece
    flush()
    return chunks


def cite_as(authors: str, year: int | None) -> str:
    """Return 'Collom 2012' or 'Fehr et al. 2000' from BibTeX authors ('Last, First and ...')."""
    names = [a.strip() for a in authors.split(" and ") if a.strip()]
    if not names:
        return str(year or "n.d.")
    first = names[0].split(",")[0].strip() if "," in names[0] else names[0].split()[-1]
    return f"{first}{' et al.' if len(names) > 1 else ''} {year or 'n.d.'}"


def passage_header(authors: str, year: int | None, title: str) -> str:
    """Return the context a passage has until it is labelled: 'Collom 2012, <title>'.

    Stored in chunks.context and indexed with the passage, so every passage is
    found by its paper's title too; `te-platform lit enrich` replaces it with a
    model-written sentence (literature/enrich.py).
    """
    return f"{cite_as(authors, year)}, {title}"


## Frequent function words of the languages the search index knows. The
## language whose words are most frequent in a text is the text's language.
_FUNCTION_WORDS = {
    "en": frozenset(
        [
            "the",
            "of",
            "and",
            "to",
            "in",
            "is",
            "that",
            "for",
            "are",
            "with",
            "as",
            "this",
            "by",
            "on",
            "be",
            "which",
            "from",
        ]
    ),
    "it": frozenset(
        [
            "il",
            "di",
            "che",
            "la",
            "per",
            "non",
            "una",
            "sono",
            "della",
            "del",
            "con",
            "gli",
            "delle",
            "nel",
            "alla",
        ]
    ),
    "fr": frozenset(
        [
            "le",
            "les",
            "des",
            "est",
            "une",
            "dans",
            "pour",
            "que",
            "qui",
            "sur",
            "par",
            "pas",
            "aux",
            "du",
            "ces",
        ]
    ),
}
_WORD = re.compile(r"[a-zàâçéèêëîïôûùüÿœæ]+")


def detect_language(text: str) -> str:
    """Return "en", "it" or "fr": the language whose function words are most frequent."""
    words = _WORD.findall(text.lower())
    counts = {lang: sum(w in fw for w in words) for lang, fw in _FUNCTION_WORDS.items()}
    best = max(counts, key=lambda lang: counts[lang])
    return best if counts[best] > 0 else "en"
