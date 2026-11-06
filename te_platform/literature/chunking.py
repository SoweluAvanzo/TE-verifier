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
from dataclasses import dataclass, field

MAX_CHARS = 1200  # about 200 words: one or two paragraphs
MIN_CHARS = 200  # merge tiny fragments (captions, page furniture) into neighbours
HEADING_MAX_CHARS = 90
MIN_UPPER_LETTERS = 3  # "RELATED WORK" is a heading, a stray "A" is not

HEADING_MAX_WORDS = 14
LEAF_DEPTH = 9  # an unnumbered sub-heading: it never replaces a numbered parent
PATH_SEPARATOR = " › "  # noqa: RUF001 (a typographic separator, shown to readers)
MIN_MATH_SYMBOLS = 8
MIN_MATH_SHARE = 0.012
MAX_ARTICLE_JUMP = 40  # a line "Article 900" after Article 12 is a reference, not a heading
LAW_PACK_CHARS = 800  # start a new passage at a paragraph once this much is collected
LEVEL_ARTICLE = 4
MAX_TITLE_LINES = 3
MIN_ARTICLES = 3
MIN_LEAF_HEADING_CHARS = 8  # "TION" is a broken line, "Summary" is not a heading alone

_LINE_END_HYPHENS = ("-", "\u00ad", "\u2010", "\u2011")
_STRICT_NUMBERED = re.compile(r"(\d+(?:\.\d+)*)\.?\s+(.+)")
_ROMANS = frozenset({"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"})
_BOOK_PART = re.compile(r"(?:CHAPTER|PART|APPENDIX)\s+[IVXLC\d]+\.?(?:\s.*)?")
_ROMAN_OR_LETTER = re.compile(r"([IVX]+|[A-Z])\.\s+(.+)")
_NAMED_HEADING = re.compile(
    r"(?:\d+(?:\.\d+)*\.?\s+)?(?:abstract|introduction|background|related work|literature review"
    r"|methods?|methodology|data|results|discussion|conclusions?|references|bibliography"
    r"|works cited|acknowledge?ments?|appendix(?: [a-z0-9]+)?)",
    re.IGNORECASE,
)
_REFERENCES = re.compile(r"(?:\d+\.?\s+)?(?:references|bibliography|works cited)", re.IGNORECASE)
_FORMAL_ELEMENT = re.compile(
    r"(?:^|(?<=[.:;]\s))(Theorem|Lemma|Proposition|Corollary|Definition|Axiom|Assumption|Proof)"
    r"(?:\s+\d+(?:\.\d+)*)?\s*[.:(]"
)
_NUMBERED_EQUATION = re.compile(r"=[^.]{1,120}\(\d{1,3}(?:\.\d{1,3})?\)(?:\s|$)")
_MATH_SYMBOLS = frozenset("=≤≥≠≈∑∏∫∂√∞∈∉∀∃→⇒±×αβγδεθλμπρστφψωΓΔΛΣΦΨΩ")  # noqa: RUF001

_LEGAL_LEVELS = {"PART": 0, "TITLE": 1, "ANNEX": 1, "CHAPTER": 2, "SECTION": 3}
_LEGAL_PART = re.compile(r"(PART|TITLE|ANNEX|CHAPTER|SECTION|Section)(?:\s+[IVXLC\d]+[A-Z]?)?")
_TITLED_SECTION = re.compile(r"(Section)\s*-?\s*\d+\w?\s+\S.*")
_SPACED_LETTERS = re.compile(r"\b[A-Za-z](?: [a-z]){3,}\b")
_ARTICLE = re.compile(r"Article\s+(\d+)[a-z]?")
_ARTICLE_WITH_TITLE = re.compile(r"(?:Art\.|Articolo)\s*(\d+)\b\s*\(.*\)\.?")
_LEGAL_PARAGRAPH = re.compile(r"(\d{1,3})\.\s+\S")
_RECITAL = re.compile(r"\((\d{1,3})\)\s+\S")
_CONSOLIDATION_MARK = re.compile(r"▼[A-Z]\d*|M\d+|▼[A-Z]\d*\s.*")

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
    section: str  # path of headings above it ("2 Model > 2.2 Tokens"; "" if none yet)
    locator: str = ""  # the citable element: "Article 19(1)-(3)", "Recital 12", "Theorem 3"
    formal: bool = False  # states a formula, theorem, definition or proof (is_formal)


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


def _join_lines(lines: list[str]) -> str:
    """Join wrapped lines into one line, mending words hyphenated at a line end."""
    text = ""
    for raw in lines:
        line = " ".join(raw.split())
        if not line:
            continue
        if text.endswith(_LINE_END_HYPHENS) and line[0].islower():
            text = text.rstrip("".join(_LINE_END_HYPHENS)) + line
        else:
            text = f"{text} {line}" if text else line
    return text


def is_formal(text: str) -> bool:
    """Return True when a passage states a formula, theorem, definition or proof.

    Named results are recognised by their label; equations by a numbered
    equation, or by a share of mathematical symbols no prose reaches. PDF
    text often garbles the formula itself, but this finds where it is.
    """
    if _FORMAL_ELEMENT.search(text):
        return True
    if _NUMBERED_EQUATION.search(text):
        return True
    symbols = sum(ch in _MATH_SYMBOLS for ch in text)
    return symbols >= MIN_MATH_SYMBOLS and symbols / max(1, len(text)) >= MIN_MATH_SHARE


def _title_after_number(text: str) -> bool:
    """Return True when the words after a heading's number read like a title."""
    words = text.split()
    return (
        0 < len(words) <= HEADING_MAX_WORDS
        and words[0][0].isupper()
        and not words[-1][-1].isdigit()
        and "=" not in text
    )


def _number_follows(number: str, last: tuple[int, ...]) -> bool:
    """Return True when a heading number continues the numbering seen so far.

    "3" after "2.4", "2.5" after "2.4" and "2.1" after "2" continue it; a list
    item "1." inside section 4 does not. Sequence is a stronger sign than fonts.
    """
    parts = tuple(int(n) for n in number.split("."))
    if not last:
        return parts in ((0,), (1,))
    for depth in range(len(last)):
        if parts == (*last[:depth], last[depth] + 1):
            return True
    return parts == (*last, 1)


def _heading_depth(  # noqa: PLR0911 (one rule per return)
    line: str, *, strong: bool, has_fonts: bool, after_sentence: bool, last: tuple[int, ...]
) -> int | None:
    """Return the depth of a heading found inside a block of lines, else None.

    Inside wrapped text a looser rule would take table rows and author lists
    for headings, so a heading must follow the numbering or stand out by font,
    and an unnumbered one must also come after a finished sentence.
    """
    if not 0 < len(line) <= HEADING_MAX_CHARS or line[-1] in ".,;:":
        return None
    numbered = _STRICT_NUMBERED.fullmatch(line)
    if numbered and _title_after_number(numbered.group(2)):
        if strong or not has_fonts or _number_follows(numbered.group(1), last):
            return numbered.group(1).count(".") + 1
        return None
    if not after_sentence or not line[0].isupper():
        return None
    if _NAMED_HEADING.fullmatch(line) or _BOOK_PART.fullmatch(line):
        return 1
    lettered = _ROMAN_OR_LETTER.fullmatch(line)
    if lettered and _title_after_number(lettered.group(2)) and (strong or line.isupper()):
        return 2 if lettered.group(1) not in _ROMANS else 1
    long_enough = len(line) >= MIN_LEAF_HEADING_CHARS or " " in line
    if strong and long_enough and _is_heading(line):
        return LEAF_DEPTH
    return None


@dataclass
class _Packer:
    """Collects text into passages; never mixes two sections in one passage."""

    formal_labels: bool  # label formal passages (papers), not provisions (laws)
    chunks: list[Chunk] = field(default_factory=list)
    section: str = ""
    locator: str = ""
    keep_locator: bool = False  # a provision's locator also covers its next passages
    skipping: bool = False  # inside a reference list: its entries are not passages
    buffer: str = ""
    page: int = 1
    span_end: str = ""  # last element joined into this passage: "(3)" in "Article 19(1)-(3)"

    def flush(self) -> None:
        if self.buffer:
            locator = self.locator + (f"-{self.span_end}" if self.span_end else "")
            formal = self.formal_labels and is_formal(self.buffer)
            self.chunks.append(Chunk(self.buffer, self.page, self.section, locator, formal))
        self.buffer, self.span_end = "", ""
        if not self.keep_locator:
            self.locator = ""

    def add(self, text: str, page: int) -> None:
        if self.skipping:
            return
        for piece in _split_long(text):
            if self.buffer and len(self.buffer) + 1 + len(piece) > MAX_CHARS:
                self.flush()
            if not self.buffer:
                self.page = page
            self.buffer = f"{self.buffer} {piece}" if self.buffer else piece

    def new_page(self) -> None:
        # A chunk is cited by its page, so avoid chunks that start on one
        # page and continue on the next, unless it is a tiny fragment.
        if len(self.buffer) >= MIN_CHARS:
            self.flush()


def _split_paper(  # noqa: C901 (one line-by-line state machine, read in order)
    pages: list[str], strong: list[set[str]] | None
) -> list[Chunk]:
    """Split a paper: heading paths, formal elements on their own, no reference lists."""
    packer = _Packer(formal_labels=True)
    has_fonts = bool(strong) and any(strong or ())
    stack: list[tuple[int, str]] = []
    last_number: tuple[int, ...] = ()

    def open_section(line: str, depth: int) -> None:
        nonlocal last_number
        number = re.match(r"\d+(?:\.\d+)*", line)
        if number:
            last_number = tuple(int(n) for n in number.group(0).split("."))
        packer.flush()
        if packer.skipping:  # what follows a reference list is not part of it
            stack.clear()
        while stack and stack[-1][0] >= depth:
            stack.pop()
        stack.append((depth, line))
        packer.section = PATH_SEPARATOR.join(label for _, label in stack)
        packer.skipping = bool(_REFERENCES.fullmatch(line))

    for page_no, page_text in enumerate(pages, start=1):
        packer.new_page()
        bold = strong[page_no - 1] if strong else set()
        for block in re.split(r"\n\s*\n", page_text):
            lines = [" ".join(ln.split()) for ln in block.splitlines()]
            lines = [ln for ln in lines if ln]
            if not lines:
                continue
            # A whole block that is one short line: the classic heading rule.
            whole = " ".join(lines)
            if not has_fonts and _is_heading(whole):
                open_section(whole, _depth_of_number(whole))
                continue
            run: list[str] = []
            previous = ""
            for index, line in enumerate(lines):
                following = lines[index + 1] if index + 1 < len(lines) else ""
                after_sentence = not previous or previous[-1] in ".?!:" or previous in bold
                # A line continued in lower case is a wrapped sentence, not a heading.
                wrapped = bool(following) and following[0].islower()
                depth = (
                    None
                    if wrapped
                    else _heading_depth(
                        line,
                        strong=line in bold,
                        has_fonts=has_fonts,
                        after_sentence=after_sentence,
                        last=last_number,
                    )
                )
                previous = line
                element = _FORMAL_ELEMENT.match(line)
                if depth is not None or element:
                    if run:
                        packer.add(_join_lines(run), page_no)
                    run = []
                if depth is not None:
                    open_section(line, depth)
                    continue
                if element and not element.group(1).startswith("Proof"):
                    packer.flush()
                    packer.locator = " ".join(element.group(0).rstrip(" .:(").split())
                run.append(line)
            if run:
                packer.add(_join_lines(run), page_no)
    packer.flush()
    return packer.chunks


def _depth_of_number(heading: str) -> int:
    """Return how deep a numbered heading sits ("3.2 Results" is 2); others are top level."""
    number = re.match(r"\d+(?:\.\d+)*", heading)
    return number.group(0).count(".") + 1 if number else 1


def _split_law(  # noqa: C901, PLR0912, PLR0915 (one line-by-line state machine, read in order)
    pages: list[str], strong: list[set[str]] | None
) -> list[Chunk]:
    """Split a legal text by its structure: titles, chapters, articles, paragraphs, recitals.

    One passage holds neighbouring paragraphs of ONE article while they fit,
    and its locator names them, so that it can be cited ("Article 19(1)-(3)").
    """
    packer = _Packer(formal_labels=False, keep_locator=True)
    has_fonts = bool(strong) and any(strong or ())
    parts: dict[int, str] = {}
    article_no, paragraph_no, recital_no = 0, 0, 0
    pending_title: tuple[int, int] | None = None  # level, title lines so far
    run: list[str] = []
    run_page = 1

    def end_run() -> None:
        nonlocal run
        if run:
            packer.add(_join_lines(run), run_page)
        run = []

    def set_section() -> None:
        packer.section = PATH_SEPARATOR.join(parts[level] for level in sorted(parts))

    def open_part(level: int, label: str) -> None:
        nonlocal paragraph_no, pending_title
        end_run()
        packer.flush()
        for deeper in [k for k in parts if k >= level]:
            del parts[deeper]
        parts[level] = label
        set_section()
        paragraph_no = 0
        pending_title = (level, 0)

    def article_number(line: str) -> int | None:
        match = _ARTICLE.fullmatch(line)
        return int(match.group(1)) if match else None

    for page_no, page_text in enumerate(pages, start=1):
        end_run()
        packer.new_page()
        run_page = page_no
        bold = strong[page_no - 1] if strong else set()
        for raw in page_text.splitlines():
            line = _SPACED_LETTERS.sub(lambda m: m.group(0).replace(" ", ""), " ".join(raw.split()))
            if not line or _CONSOLIDATION_MARK.fullmatch(line):
                continue
            structural = (
                _LEGAL_PART.fullmatch(line)
                or _ARTICLE.fullmatch(line)
                or _ARTICLE_WITH_TITLE.match(line)
            )
            if pending_title is not None:
                level, title_lines = pending_title
                is_title = (
                    not structural
                    and title_lines < MAX_TITLE_LINES
                    and (line in bold or (not has_fonts and title_lines == 0))
                    and not _LEGAL_PARAGRAPH.match(line)
                    and not _RECITAL.match(line)
                )
                if is_title:
                    parts[level] = f"{parts[level]} {line}"
                    set_section()
                    pending_title = (level, title_lines + 1)
                    continue
                pending_title = None
            part = _LEGAL_PART.fullmatch(line) or (
                (line in bold or None) and _TITLED_SECTION.fullmatch(line)
            )
            if part:
                open_part(_LEGAL_LEVELS[part.group(1).upper()], line)
                packer.locator = ""
                continue
            number = article_number(line)
            if number is not None and article_no <= number <= article_no + MAX_ARTICLE_JUMP:
                article_no = number
                open_part(LEVEL_ARTICLE, line)
                packer.locator = f"Article {number}"
                continue
            inline = _ARTICLE_WITH_TITLE.match(line)
            if inline:
                article_no = int(inline.group(1))
                open_part(LEVEL_ARTICLE, line)
                pending_title = None
                packer.locator = f"Article {article_no}"
                continue
            if article_no == 0:
                recital = _RECITAL.match(line)
                if recital and int(recital.group(1)) == recital_no + 1:
                    recital_no += 1
                    end_run()
                    packer.flush()
                    parts.setdefault(LEVEL_ARTICLE, "Recitals")
                    set_section()
                    packer.locator = f"Recital {recital_no}"
                    run_page = page_no
            else:
                paragraph = _LEGAL_PARAGRAPH.match(line)
                if paragraph and int(paragraph.group(1)) == paragraph_no + 1:
                    paragraph_no += 1
                    end_run()
                    run_page = page_no
                    element = f"({paragraph_no})"
                    if paragraph_no == 1 or not packer.buffer:
                        packer.flush()
                        packer.locator = f"Article {article_no}{element}"
                    else:
                        packer.span_end = element
                    if len(packer.buffer) > LAW_PACK_CHARS:
                        packer.flush()
                        packer.locator = f"Article {article_no}{element}"
            run.append(line)
    end_run()
    packer.flush()
    return packer.chunks


def _has_articles(pages: list[str]) -> bool:
    """Return True when a legal text is built of articles (a guideline may not be)."""
    lines = [" ".join(ln.split()) for page in pages for ln in page.splitlines()]
    named = sum(1 for ln in lines if _ARTICLE.fullmatch(ln))
    return named >= MIN_ARTICLES or any(_ARTICLE_WITH_TITLE.fullmatch(ln) for ln in lines)


def split_into_chunks(
    pages: list[str], *, legal: bool = False, strong: list[set[str]] | None = None
) -> list[Chunk]:
    """Split a document into passages (header HEURISTICS and GUARANTEES).

    strong: per page, the lines the PDF sets apart by font (literature/extract.py).
    legal: the document is a law or guideline, split by article and paragraph.
    """
    return (
        _split_law(pages, strong) if legal and _has_articles(pages) else _split_paper(pages, strong)
    )


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
