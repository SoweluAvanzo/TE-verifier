## =============================================================================
## tests/platform_tests/test_platform_literature.py — tests for te_platform/literature/
## =============================================================================
## GUIDE STEP   11.1 (chunking, ingestion), 11.2 (search, recall)
## PURPOSE      1. chunking.py: unit tests on small fake "pages" (no PDF, no
##                 database) and a Hypothesis property test (Hypothesis
##                 generates many random inputs and shrinks a failing one to
##                 the smallest example): headings become sections, page
##                 numbers are kept, no chunk exceeds MAX_CHARS, no text is
##                 lost or invented (the chunks equal the input without its
##                 heading lines, modulo whitespace).
##              2. ingest.py: a small PDF, made by the test with pypdf, is
##                 ingested into the real database and read back.
##              3. search.py: a passage of an ingested paper is found; odd
##                 queries cannot break the SQL; and the RECALL test set from
##                 guide 11.2. Each line pairs a question someone might ask
##                 with the citation key of the paper that should be found.
##                 Top-3 recall = the share of questions whose paper appears
##                 among the first 3 hits; the target is >= 0.8.
## DEPENDS ON   Sections 2-3: a real PostgreSQL with the schema migrated
##              (marker `db`, like test_platform_db.py). The tests delete the
##              papers they ingest, so the recall test only sees the real
##              collection.
## ACTIVATE     Section 1 and 2 with guide 11.1; section 3 with guide 11.2.
##              The recall questions are placeholders: replace them with ~20
##              real questions for the seed collection (architecture §4.4);
##              the test is skipped while the collection is empty.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
##
## Guide 11.1
## [ ] 1. Imports: Path, uuid4, pytest, `given, settings, strategies as st`
##        (hypothesis), pypdf's PdfWriter and the generic objects of the
##        SOLUTION, MAX_CHARS and split_into_chunks, ingest_pdf, `models as
##        m` and session_scope.
## [ ] 2. Constant PAGES: two fake page texts; page 1 holds the headings
##        "1 Introduction" and "2 Related work" (with a long repeated
##        paragraph), page 2 one short sentence.
## [ ] 3. test_sections_and_pages; test_heading_rules (parametrised over
##        lines that are and are not headings); test_example_text_is_kept
##        (the words of PAGES without the two heading lines equal the words
##        of the chunks, in order); test_overlong_sentence_and_word_are_cut.
## [ ] 4. test_chunks_are_short_and_keep_all_text: a Hypothesis property:
##          | @given(st.lists(_PAGE, min_size=1, max_size=3))
##        every chunk <= MAX_CHARS, the concatenation equals the input
##        modulo whitespace, page numbers never go back.
## [ ] 5. Helper `_make_pdf(pages, path)` (one Helvetica text line per
##        line, pypdf) and the fixture `ingested` (ingests with a unique
##        citation key, deletes the rows afterwards).
## [ ] 6. test_ingest_stores_work_and_passages and
##        test_licence_without_full_text_keeps_only_the_abstract (marked
##        db).
## [ ] 7. Check:
##          | uv run pytest tests/platform_tests/test_platform_literature.py -q
##
## Guide 11.2
## [ ] 8. test_search_finds_the_ingested_passage and
##        test_odd_queries_are_just_text (marked db).
## [ ] 9. Constant RECALL_SET: about 20 (question, citation key) pairs; the
##        three in the SOLUTION are placeholders (header, ACTIVATE).
## [ ] 10. test_top3_recall, marked db: pytest.skip when count_works() is 0;
##         otherwise count the questions whose key is among the
##         citation_key of search(q, limit=3), then
##          | assert found / len(RECALL_SET) >= 0.8
## [ ] 11. Check: the step 7 command, with the database running and the
##         seed collection ingested (guide 11.1).
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pypdf import PdfWriter
from pypdf.generic import ContentStream, DecodedStreamObject, DictionaryObject, NameObject

from te_platform.db import models as m
from te_platform.db.session import session_scope
from te_platform.literature.chunking import MAX_CHARS, split_into_chunks
from te_platform.literature.ingest import ingest_pdf

## Guide 11.2: search and the collection size.
from te_platform.db.repo import LiteratureRepository
from te_platform.literature.search import PASSAGE_MAX_CHARS, search


## --- 1. Chunking ---------------------------------------------------------------------
PAGES = [
    "1 Introduction\n\nTokens can coordinate communities.\nThey also fail.\n\n"
    "2 Related work\n\n" + "Ostrom studied commons. " * 80,
    "More text on page two.",
]


def _words_without(lines_to_drop: set[str], pages: list[str]) -> list[str]:
    kept = [ln for page in pages for ln in page.splitlines() if ln.strip() not in lines_to_drop]
    return " ".join(kept).split()


def test_sections_and_pages() -> None:
    chunks = split_into_chunks(PAGES)
    assert chunks[0].section == "1 Introduction" and chunks[0].page == 1
    assert any(c.section == "2 Related work" for c in chunks)
    assert chunks[-1].page == 2


@pytest.mark.parametrize(
    ("line", "is_heading"),
    [
        ("3.2 Results", True),
        ("4. Discussion", True),
        ("RELATED WORK", True),
        ("Governance of the Commons", True),
        ("Introduction", True),
        ("Tokens can coordinate communities", False),  # not Title Case
        ("This sentence ends with a period.", False),
        ("Figure 3: Supply Over Time", False),  # digits outside a section number
        ("of the", False),  # starts lower-case
    ],
)
def test_heading_rules(line: str, is_heading: bool) -> None:
    chunks = split_into_chunks([f"{line}\n\nsome text that follows the line."])
    assert (chunks[0].section == line) is is_heading


def test_example_text_is_kept() -> None:
    chunks = split_into_chunks(PAGES)
    words_in = _words_without({"1 Introduction", "2 Related work"}, PAGES)
    words_out = " ".join(c.text for c in chunks).split()
    assert words_out == words_in  # nothing lost, nothing invented, same order


def test_overlong_sentence_and_word_are_cut() -> None:
    sentence = "word " * 600  # one sentence of 3000 characters
    word = "x" * (2 * MAX_CHARS + 5)  # one "word" longer than two chunks
    chunks = split_into_chunks([sentence + "\n\n" + word])
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    assert "".join(c.text for c in chunks).replace(" ", "") == (sentence + word).replace(" ", "")


## Generated pages: lower-case words (so no line is ever a heading),
## sentence ends, line breaks, empty lines, and now and then a word longer
## than MAX_CHARS.
_TOKEN = st.one_of(
    st.text(alphabet="abcdefgh", min_size=1, max_size=12),
    st.sampled_from([".", "!", "?", ",", "\n", "\n\n", "  "]),
    st.just("y" * (MAX_CHARS + 30)),
)
_PAGE = st.lists(_TOKEN, max_size=300).map(" ".join)


@settings(max_examples=200, deadline=None)
@given(st.lists(_PAGE, min_size=1, max_size=3))
def test_chunks_are_short_and_keep_all_text(pages: list[str]) -> None:
    chunks = split_into_chunks(pages)
    assert all(0 < len(c.text) <= MAX_CHARS for c in chunks)
    assert "".join("".join(c.text for c in chunks).split()) == "".join("".join(pages).split())
    page_numbers = [c.page for c in chunks]
    assert page_numbers == sorted(page_numbers)
    assert all(1 <= p <= len(pages) for p in page_numbers)


## --- 2. Ingestion (integration) ------------------------------------------------------------
def _make_pdf(pages: list[list[str]], path: Path) -> None:
    """Write a PDF with one line of Helvetica text per string ("" = empty line)."""
    writer = PdfWriter()
    for lines in pages:
        page = writer.add_blank_page(612, 792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        # BT/ET: begin/end text; Tf: font and size; TL: line spacing; Td:
        # start position; Tj: show a string; T*: next line. A line holding
        # one space reads back as an empty line (a paragraph break).
        ops = ["BT", "/F1 11 Tf", "14 TL", "72 720 Td"]
        ops += [f"({line or ' '}) Tj T*" for line in lines]
        ops.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(ops).encode("latin-1"))
        page.replace_contents(ContentStream(stream, writer))
    writer.write(path)


PAPER = [
    [
        "1 Introduction",
        "",
        "Graduated sanctions keep a commons alive.",
        "Monitoring by the users themselves matters.",
    ],
    ["2 Results", "", "Quadrilateral escrow vouchers lowered free riding."],
]


@pytest.fixture
def ingested(tmp_path: Path) -> Iterator[Callable[..., tuple[str, str]]]:
    """Ingest PAPER under a unique citation key; delete it after the test."""
    work_ids: list[str] = []

    def _ingest(*, full_text_allowed: bool, abstract: str = "") -> tuple[str, str]:
        key = "test" + uuid4().hex[:12]
        _make_pdf(PAPER, tmp_path / "paper.pdf")
        extra = f",\n  abstract = {{{abstract}}}" if abstract else ""
        (tmp_path / "paper.bib").write_text(
            f"@article{{{key},\n  title = {{Commons and Tokens}},\n  author = {{Doe, Jane}},\n"
            f"  year = {{2024}},\n  journal = {{Journal of Tests}}{extra}\n}}\n",
            encoding="utf-8",
        )
        work_id = ingest_pdf(
            tmp_path / "paper.pdf",
            tmp_path / "paper.bib",
            "CC-BY-4.0",
            full_text_allowed=full_text_allowed,
        )
        work_ids.append(work_id)
        return work_id, key

    yield _ingest
    with session_scope() as db:
        for work_id in work_ids:
            db.query(m.Chunk).filter_by(work_id=work_id).delete()
            db.query(m.Work).filter_by(id=work_id).delete()


@pytest.mark.db
def test_ingest_stores_work_and_passages(ingested: Callable[..., tuple[str, str]]) -> None:
    work_id, key = ingested(full_text_allowed=True)
    with session_scope() as db:
        work = db.get(m.Work, work_id)
        chunks = db.query(m.Chunk).filter_by(work_id=work_id).order_by(m.Chunk.id).all()
        assert work is not None
        assert (work.citation_key, work.title, work.year, work.venue, work.licence) == (
            key,
            "Commons and Tokens",
            2024,
            "Journal of Tests",
            "CC-BY-4.0",
        )
        assert [(c.section, c.page) for c in chunks] == [("1 Introduction", 1), ("2 Results", 2)]
        assert "Graduated sanctions" in chunks[0].text


@pytest.mark.db
def test_licence_without_full_text_keeps_only_the_abstract(
    ingested: Callable[..., tuple[str, str]],
) -> None:
    work_id, _ = ingested(full_text_allowed=False, abstract="Sanctions and monitoring.")
    with session_scope() as db:
        chunks = db.query(m.Chunk).filter_by(work_id=work_id).all()
        assert [(c.section, c.text) for c in chunks] == [("Abstract", "Sanctions and monitoring.")]


## --- 3. Search (integration) -----------------------------------------------------------------
## Guide 11.2: an ingested passage is found by its words (stemmed: "voucher"
## finds "vouchers").
@pytest.mark.db
def test_search_finds_the_ingested_passage(ingested: Callable[..., tuple[str, str]]) -> None:
    _, key = ingested(full_text_allowed=True)
    hits = search("quadrilateral escrow voucher", limit=3)
    assert hits and hits[0].citation_key == key
    assert "Quadrilateral escrow vouchers" in hits[0].passage
    assert hits[0].score > 0 and len(hits[0].passage) <= PASSAGE_MAX_CHARS + 2


## Extension: when no passage has ALL the words, passages with ANY of them are
## returned, best first (a long question from the agent still finds something).
@pytest.mark.db
def test_a_partly_matching_query_still_finds_the_passage(
    ingested: Callable[..., tuple[str, str]],
) -> None:
    _, key = ingested(full_text_allowed=True)
    hits = search("quadrilateral escrow remedies zygomorphic", limit=3)
    assert hits and hits[0].citation_key == key


## Guide 11.2: the query is a bound parameter: SQL in it is just words.
@pytest.mark.db
def test_odd_queries_are_just_text() -> None:
    for query in ["'; DROP TABLE works; --", '"unclosed phrase', "-", ""]:
        assert isinstance(search(query), list)


## Guide 11.2: one question per seed work (literature/, ingested 2026-10-24),
## worded as the agent would ask, with the work it should find in the top 3.
RECALL_SET = [
    ("mutual credit credit limit", "littera2017sardex"),
    ("mutual credit systems and the commons problem", "schraven2001mutual"),
    ("demurrage on a complementary currency", "godschalk2012demurrage"),
    ("moneyless exchange credit clearing at scale", "greco2013scale"),
    ("time banking reciprocity", "ozanne2010time"),
    ("diffusion of community currency niches", "seyfang2016diffusion"),
    ("WIR bank countercyclical credit", "stodder2016macro"),
    ("token design and management", "lesavre2021nist"),
    ("token adoption and valuation", "cong2020tokenomics"),
    ("on-chain governance of DAOs", "feichtinger2023hidden"),
    ("voting power concentration in governance tokens", "fritsch2022voting"),
    ("decentralized finance decentralization", "barbereau2022defi"),
    ("polycentric governance of commons", "ostrom2009beyond"),
    ("design principles for community-based natural resource management", "cox2010review"),
    ("ambiguity in requirements elicitation interviews", "ferrari2016ambiguity"),
    ("how to elicit uncertain quantities from experts", "epa2011expert"),
    ("e-money token asset-referenced token authorisation", "mica2023"),
    ("limited network exclusion payment services", "psd2_2015"),
    ("electronic money institution", "emd2_2009"),
    ("qualification of crypto-assets as financial instruments", "esma2024qualification"),
    ("banca dei tempi", "it_l53_2000"),
    ("investment contract analysis crypto assets", "sec2026interpretation"),
    ("barter supply of goods taxable amount", "vat2006"),
]


## Guide 11.2: recall is only meaningful once the seed collection is
## ingested (guide 11.1); on an empty collection the test is skipped.
@pytest.mark.db
def test_top3_recall() -> None:
    with session_scope() as db:
        if LiteratureRepository(db).count_works() == 0:
            pytest.skip("literature collection is empty: ingest the seed papers (guide 11.1)")
    found = sum(1 for q, key in RECALL_SET if key in [h.citation_key for h in search(q, limit=3)])
    assert found / len(RECALL_SET) >= 0.8
