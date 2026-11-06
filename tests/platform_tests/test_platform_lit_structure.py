"""Document structure, source tiers, reading tool, source links and viewer data."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import anyio
import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from te_platform.agent.sources import sources_in
from te_platform.agent.transcript import display_transcript
from te_platform.db import models as m
from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope
from te_platform.literature import reading
from te_platform.literature.catalog import SYSTEM_TYPES, all_entries, lookup
from te_platform.literature.chunking import Chunk, is_formal, split_into_chunks
from te_platform.literature.extract import _without_furniture
from te_platform.literature.rechunk import transfer_labels
from te_platform.literature.search import (
    FOUNDATIONS,
    OTHER_BLOCKCHAIN,
    SAME_SYSTEM,
    _prioritised,
    search,
    source_priority,
)
from te_platform.tools.lit_read import LitReadInput, handle

LONG = "This provision applies to every issuer established in the Union. " * 3


## --- Papers ---------------------------------------------------------------------------
def test_section_paths_follow_the_numbering() -> None:
    pages = [
        "1 Introduction\nTokens coordinate communities.\n"
        "2 Model\nThe model has agents.\n2.1 Agents\nAgents hold tokens.\n"
        "2.2 Prices\nPrices move.\n3 Results\nResults follow."
    ]
    sections = [c.section for c in split_into_chunks(pages, strong=[set()])]
    assert "2 Model › 2.1 Agents" in sections  # noqa: RUF001
    assert "2 Model › 2.2 Prices" in sections  # noqa: RUF001
    assert "3 Results" in sections


def test_a_wrapped_numbered_line_is_not_a_heading() -> None:
    pages = ["1 Introduction\nFirst point.\n2. Deposit currency expands relatively to\nmoney in use."]
    assert {c.section for c in split_into_chunks(pages, strong=[set()])} == {"1 Introduction"}


def test_a_list_item_out_of_sequence_is_not_a_heading_when_fonts_exist() -> None:
    pages = ["4 Results\nSomething.\n1 Bitcoin Holders\nMore text."]
    chunks = split_into_chunks(pages, strong=[{"4 Results"}])
    assert {c.section for c in chunks} == {"4 Results"}


def test_reference_lists_are_not_passages_but_text_after_them_is() -> None:
    pages = [
        "1 Introduction\nReal content here.\nReferences\n[1] Someone (2001). A title.\n"
        "Appendix A\nThe appendix content."
    ]
    text = " ".join(c.text for c in split_into_chunks(pages, strong=[set()]))
    assert "Real content" in text and "appendix content" in text
    assert "Someone" not in text
    sections = [c.section for c in split_into_chunks(pages, strong=[set()])]
    assert not any("References" in s for s in sections)


def test_a_theorem_starts_its_own_named_passage() -> None:
    pages = ["1 Model\nSome prose before the result.\nTheorem 3. The fee is stable when x > 0."]
    chunks = split_into_chunks(pages, strong=[set()])
    theorem = next(c for c in chunks if c.locator)
    assert theorem.locator == "Theorem 3"
    assert theorem.text.startswith("Theorem 3.")
    assert theorem.formal


@pytest.mark.parametrize(
    ("text", "formal"),
    [
        ("Proposition 2: the equilibrium is unique.", True),
        ("Hence y = a x + b (12) holds for all periods considered here.", True),
        ("Community currencies were studied in twelve towns in Italy.", False),
        ("Article 3 defines 12 terms and the fee equals 2 percent.", False),
    ],
)
def test_formal_passages_are_recognised(text: str, formal: bool) -> None:  # noqa: FBT001
    assert is_formal(text) is formal


def test_hyphenated_line_ends_are_mended() -> None:
    chunks = split_into_chunks(["1 Intro\nThe transac-\ntion cost is low."], strong=[set()])
    assert "transaction cost" in chunks[0].text


def test_page_furniture_is_removed() -> None:
    pages = [
        [f"Journal Name, vol. 3, p. {i}", "a" * (i + 1), "Body line one", "m" * (i + 1), "z" * (i + 1), f"{i + 1}"]
        for i in range(8)
    ]
    cleaned = _without_furniture(pages)
    assert all(not any(ln.startswith("Journal Name") for ln in p) for p in cleaned)
    assert all("Body line one" in p for p in cleaned)  # repeated, but not at the page's edge
    assert all(p[-1].startswith("z") for p in cleaned)  # the page number went too


## --- Laws -----------------------------------------------------------------------------
LAW = [
    "TITLE I\nSUBJECT MATTER\nArticle 1\nSubject matter\n"
    f"1. {LONG}\n2. {LONG}\nTITLE II\nOFFERS\nCHAPTER 1\nGeneral rules\nArticle 2\nScope\n"
    f"1. {LONG}\n(a) a sub-point of paragraph one;\n2. {LONG}\n3. {LONG}\n4. {LONG}\nArticle 3\nDefinitions\n{LONG}"
]
LAW_STRONG = [
    {
        "TITLE I",
        "SUBJECT MATTER",
        "Article 1",
        "Subject matter",
        "TITLE II",
        "OFFERS",
        "CHAPTER 1",
        "General rules",
        "Article 2",
        "Scope",
        "Article 3",
        "Definitions",
    }
]


def test_a_law_is_split_by_title_chapter_article_and_paragraph() -> None:
    chunks = split_into_chunks(LAW, legal=True, strong=LAW_STRONG)
    assert chunks[0].section == "TITLE I SUBJECT MATTER › Article 1 Subject matter"  # noqa: RUF001
    assert chunks[0].locator.startswith("Article 1(1)")
    scope = [c for c in chunks if "Article 2" in c.section]
    assert scope[0].section.startswith("TITLE II OFFERS › CHAPTER 1 General rules › Article 2")  # noqa: RUF001
    assert {c.section for c in scope} == {scope[0].section}  # one article, one section
    assert any(c.locator == "Article 3" for c in chunks)


def test_neighbouring_paragraphs_share_a_passage_with_a_range() -> None:
    short = "A short rule of the article."
    pages = [f"Article 1\nTitle\n1. {short}\n2. {short}\n3. {short}\nArticle 2\nTitle\nArticle 3\nTitle\n"]
    first = split_into_chunks(pages, legal=True, strong=[{"Article 1", "Title", "Article 2", "Article 3"}])[0]
    assert first.locator == "Article 1(1)-(3)"


def test_a_cross_reference_on_its_own_line_is_not_an_article() -> None:
    pages = [f"Article 5\nTitle\n{LONG}\nArticle 900\nmore text\nArticle 6\nNext\nArticle 7\nNext\n"]
    chunks = split_into_chunks(pages, legal=True, strong=[{"Article 5", "Title", "Article 6", "Article 7", "Next"}])
    assert not any("Article 900" in c.section for c in chunks)


def test_recitals_are_named_before_the_first_article() -> None:
    pages = [f"Whereas:\n(1) First reason. {LONG}\n(2) Second reason. {LONG}\nArticle 1\nT\nArticle 2\nT\nArticle 3\nT\n"]
    chunks = split_into_chunks(pages, legal=True, strong=[{"Article 1", "Article 2", "Article 3", "T"}])
    assert [c.locator for c in chunks if c.locator.startswith("Recital")] == ["Recital 1", "Recital 2"]


def test_a_legal_text_without_articles_is_split_like_a_paper() -> None:
    pages = ["III. CLASSIFICATION OF CRYPTO ASSETS\nSome guidance here.\nA. Digital Commodities\nMore."]
    chunks = split_into_chunks(pages, legal=True, strong=[{"A. Digital Commodities"}])
    assert chunks[0].section == "III. CLASSIFICATION OF CRYPTO ASSETS"


## --- Carrying labels over -------------------------------------------------------------
def test_labels_follow_the_text_and_new_text_stays_unlabelled() -> None:
    old = [
        {"text": "graduated sanctions keep a commons alive in many fisheries", "kind": "mechanism"},
        {"text": "the velocity of money rises with spending in small towns", "kind": "empirical_value"},
    ]
    new = [
        Chunk("the velocity of money rises with spending in small towns today", 1, ""),
        Chunk("an entirely different passage about something never seen", 1, ""),
    ]
    matches = transfer_labels(new, old)
    assert matches[0] is not None and matches[0]["kind"] == "empirical_value"
    assert matches[1] is None


## --- Catalog and priority -------------------------------------------------------------
def test_every_catalog_entry_is_valid() -> None:
    entries = all_entries()
    assert len(entries) >= 83
    assert all(set(e["systems"]) <= SYSTEM_TYPES and e["tier"] in (0, 1, 2, 3) for e in entries.values())
    assert lookup("mica2023")["systems"] == ["law"]
    assert lookup("no-such-work") is None


def _row(tier: int, systems: list[str], year: int = 2015) -> dict:
    return {"tier": tier, "systems": systems, "year": year}


def test_priority_follows_closeness_to_the_design() -> None:
    community = "community_token"
    same = source_priority(_row(1, [community]), community)
    other = source_priority(_row(1, ["defi"]), community)
    related = source_priority(_row(2, ["local_currency"]), community)
    theory = source_priority(_row(3, ["foundations"]), community)
    assert same == SAME_SYSTEM and other == OTHER_BLOCKCHAIN and theory == FOUNDATIONS
    assert same > other > related > theory


def test_for_a_paper_currency_its_own_literature_comes_before_tokens() -> None:
    design = "time_bank"
    own = source_priority(_row(2, [design]), design)
    token = source_priority(_row(1, ["defi"]), design)
    assert own > token


def test_recent_sources_about_real_systems_rank_higher() -> None:
    assert source_priority(_row(1, ["defi"], 2025), "defi") > source_priority(_row(1, ["defi"], 2016), "defi")
    assert source_priority(_row(3, ["foundations"], 2025), None) == FOUNDATIONS


def test_law_and_methods_are_never_moved() -> None:
    assert source_priority(_row(0, ["law"]), "defi") == source_priority(_row(0, ["methods"]), None) == 1.0


def test_a_much_more_relevant_foundational_source_stays_first() -> None:
    rows = {1: _row(3, ["foundations"]), **{i: _row(1, ["defi"]) for i in range(2, 12)}}
    # Ranked first by relevance, with ties among others well below it only from rank 4.
    order = _prioritised({i: 0.0 for i in [1, *range(2, 12)]}, rows, None)
    assert list(order).index(1) <= 2  # still among the first three


## --- Reading aids ---------------------------------------------------------------------
def test_evidence_type_and_reading_depend_on_the_passage() -> None:
    assert reading.describe({"kind": "empirical_value", "tier": 2})[0].startswith("empirical")
    assert reading.describe({"kind": "mechanism", "formal": True, "tier": 1})[0].startswith("formal")
    assert "assumptions" in reading.describe({"kind": "mechanism", "tier": 3})[1]
    assert "on-chain" in reading.describe({"kind": "case_study", "tier": 2})[1]


def test_citations_name_the_element_and_link_the_passage() -> None:
    row = {
        "id": 7,
        "authors": "Collom, Ed",
        "year": 2012,
        "page": 4,
        "locator": "",
        "tier": 2,
        "systems": ["time_bank"],
        "citation_key": "collom2012key",
        "doi": "10.1/x",
    }
    assert reading.cite_markdown(row) == "[Collom 2012, p. 4](/literature/passage/7)"
    assert reading.original_url(row) == "https://doi.org/10.1/x"
    law = {**row, "locator": "Article 19(1)", "tier": 0, "systems": ["law"], "citation_key": "mica2023"}
    assert reading.cite_text(law) == "mica2023, Article 19(1)"
    assert reading.original_url({**row, "source_url": "https://x"}) == "https://x"


def test_sources_come_from_tool_results_only() -> None:
    hit = {"passage_id": 1, "cite_markdown": "[a](/literature/passage/1)", "passage": "long text"}
    found = sources_in("lit.search.v1", {"hits": [hit]})
    assert found == [{"passage_id": 1, "cite_markdown": "[a](/literature/passage/1)"}]
    assert sources_in("verify.run.v1", {"hits": [hit]}) == []
    assert sources_in("lit.search.v1", "not a dict") == []


def test_a_reopened_conversation_lists_its_sources() -> None:
    import json  # noqa: PLC0415

    hit = {"passage_id": 1, "cite_markdown": "[a](/literature/passage/1)"}
    rows = [
        {"role": "assistant", "content": {"content": [{"type": "tool_use", "id": "t1", "name": "lit__search__v1"}]}},
        {
            "role": "user",
            "content": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": json.dumps({"ok": True, "result": {"hits": [hit]}}),
                    }
                ]
            },
        },
    ]
    item = display_transcript(rows)[0]
    assert item["tool"] == "lit.search.v1"
    assert item["sources"] == [hit]


## --- Against the database -------------------------------------------------------------
@pytest.fixture
def stored_work() -> Iterator[str]:
    key = f"structtest{uuid4().hex[:8]}"
    chunks = [
        Chunk("Definitions of quokkaland terms.", 1, "Title I › Article 1", "Article 1"),  # noqa: RUF001
        Chunk("Scope of quokkaland rules.", 1, "Title I › Article 2", "Article 2(1)"),  # noqa: RUF001
        Chunk("Exemptions from quokkaland rules.", 2, "Title I › Article 2", "Article 2(2)"),  # noqa: RUF001
        Chunk("Theorem 1. The quokkaland fee is stable.", 3, "2 Model", "Theorem 1", True),
    ]
    with session_scope() as db:
        LiteratureRepository(db).add_work(
            {
                "citation_key": key,
                "title": "Quokkaland Act",
                "authors": "Parliament of Quokkaland",
                "year": 2024,
                "venue": None,
                "doi": None,
                "licence": "test",
                "full_text_allowed": True,
                "tier": 0,
                "systems": ["law"],
                "source_url": "https://example.org/act",
            },
            chunks,
        )
    yield key
    # The collection must end as it began: an empty test database skips the recall test.
    with session_scope() as db:
        work = db.query(m.Work).filter(m.Work.citation_key == key).one()
        db.query(m.Chunk).filter(m.Chunk.work_id == work.id).delete()
        db.delete(work)


@pytest.mark.db
def test_outline_lists_sections_in_reading_order(stored_work: str) -> None:
    with session_scope() as db:
        outline = LiteratureRepository(db).work_outline(stored_work)
    assert [s["section"] for s in outline["sections"]] == [
        "Title I › Article 1",  # noqa: RUF001
        "Title I › Article 2",  # noqa: RUF001
        "2 Model",
    ]
    assert outline["sections"][1]["passages"] == 2
    assert outline["sections"][2]["formal_passages"] == 1


@pytest.mark.db
def test_the_read_tool_reads_a_whole_article_and_around_a_passage(stored_work: str) -> None:
    async def read(**kw: object) -> object:
        return await handle(LitReadInput(**kw), None)  # the tool uses no context

    article = anyio.run(lambda: read(what="section", citation_key=stored_work, section="Article 2"))
    assert [p.locator for p in article.passages] == ["Article 2(1)", "Article 2(2)"]
    assert article.passages[0].cite_markdown.endswith(f"(/literature/passage/{article.passages[0].passage_id})")
    assert article.original_url == "https://example.org/act"
    around = anyio.run(lambda: read(what="around", passage_id=article.passages[0].passage_id))
    assert len(around.passages) == 4


@pytest.mark.db
def test_an_unknown_section_says_where_to_look(stored_work: str) -> None:
    with pytest.raises(Exception, match="outline"):
        anyio.run(
            lambda: handle(LitReadInput(what="section", citation_key=stored_work, section="Article 99"), None)
        )


def test_read_input_needs_what_it_reads() -> None:
    with pytest.raises(ValueError, match="passage_id"):
        LitReadInput(what="around")
    with pytest.raises(ValueError, match="section"):
        LitReadInput(what="section", citation_key="x")


@pytest.mark.db
def test_the_viewer_shows_the_section_and_where_to_go_next(stored_work: str) -> None:
    with session_scope() as db:
        repo = LiteratureRepository(db)
        first = repo.section_passages(stored_work, "Article 2")[0]
        view = repo.passage_view(first["id"])
    assert [r["locator"] for r in view["section_passages"]] == ["Article 2(1)", "Article 2(2)"]
    assert view["previous_id"] and view["next_id"]


@pytest.mark.db
def test_search_filters_formal_passages_and_gives_links(stored_work: str) -> None:
    hits = search("quokkaland", limit=5, formal=True)
    assert hits and all(h.formal for h in hits)
    assert hits[0].locator == "Theorem 1"
    assert hits[0].cite_markdown.endswith(f"(/literature/passage/{hits[0].passage_id})")
    assert hits[0].evidence_type.startswith("formal")


def test_a_real_pdf_goes_through_extraction(tmp_path: Path) -> None:
    from te_platform.literature.extract import extract_pages  # noqa: PLC0415

    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 11 Tf 14 TL 72 720 Td (Article 1) Tj T* (A rule of the act.) Tj ET")
    page.replace_contents(ContentStream(stream, writer))
    path = tmp_path / "law.pdf"
    writer.write(path)
    for legal in (False, True):
        pages, _strong = extract_pages(path, legal=legal)
        assert "A rule of the act." in pages[0]
