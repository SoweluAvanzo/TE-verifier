"""Tests of literature/enrich.py: labels for every passage of the collection.

1. Parsing and validating the model's answer (pure functions).
2. Storing labels and searching by the context sentence (needs PostgreSQL).
3. One real call to the configured model (skipped without TE_LLM_API_KEY).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from uuid import uuid4

import pytest

from te_platform.db import models as m
from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope
from te_platform.literature.chunking import Chunk
from te_platform.literature.enrich import (
    MAX_CONTEXT_CHARS,
    Label,
    Labeller,
    _batches,
    cite_as,
    parse_labels,
    user_prompt,
)
from te_platform.literature.search import search

## --- 1. The model's answer ---------------------------------------------------------------


def test_answer_in_a_code_fence_is_parsed() -> None:
    answer = (
        '```json\n{"passages": [{"id": 7, "context": "From Collom 2012 on US time banks.",'
        ' "failure_modes": ["fm5", "FM9"], "parameters": ["participants", "colour"],'
        ' "kind": "empirical_value"}]}\n```'
    )
    labels = parse_labels(answer, [7])
    assert labels[7].context == "From Collom 2012 on US time banks."
    assert labels[7].failure_modes == ["FM5"]  # upper-cased; unknown FM9 dropped
    assert labels[7].parameters == ["participants"]  # unknown "colour" dropped
    assert labels[7].kind == "empirical_value"


def test_labels_for_passages_not_asked_for_are_dropped() -> None:
    answer = '{"passages": [{"id": 1, "context": "a"}, {"id": 2, "context": "b"}]}'
    assert set(parse_labels(answer, [2])) == {2}


@pytest.mark.parametrize(
    "answer",
    ["", "no json here", '{"passages": [', '{"passages": [{"id": 1}]}', '["not", "an object"]'],
)
def test_unusable_answers_give_no_labels(answer: str) -> None:
    assert parse_labels(answer, [1]) == {}


def test_unknown_kind_becomes_other_and_context_is_one_short_line() -> None:
    label = Label(id=1, context="word\n  " * 200, kind="opinion")
    assert label.kind == "other"
    assert "\n" not in label.context
    assert len(label.context) <= MAX_CONTEXT_CHARS


@pytest.mark.parametrize(
    ("authors", "year", "expected"),
    [
        ("Collom, Ed", 2012, "Collom 2012"),
        ('Fehr, Ernst and G{\\"a}chter, Simon', 2000, "Fehr et al. 2000"),
        ("Irving Fisher", 1911, "Fisher 1911"),
        ("", None, "n.d."),
    ],
)
def test_citation_form(authors: str, year: int | None, expected: str) -> None:
    assert cite_as(authors, year) == expected


def test_batches_never_mix_works() -> None:
    rows = [{"id": i, "citation_key": "a" if i < 5 else "b"} for i in range(8)]
    batches = _batches(rows, 3)
    assert [[r["id"] for r in b] for b in batches] == [[0, 1, 2], [3, 4], [5, 6, 7]]


def test_prompt_names_the_document_and_every_passage() -> None:
    passages = [
        {
            "id": 3,
            "page": 2,
            "section": "Results",
            "text": "Members traded 40 hours.",
            "title": "Time banks",
            "authors": "Doe, Jane",
            "year": 2012,
            "venue": "IJCCR",
        },
        {
            "id": 4,
            "page": 3,
            "section": "",
            "text": "Second passage.",
            "title": "Time banks",
            "authors": "Doe, Jane",
            "year": 2012,
            "venue": "IJCCR",
        },
    ]
    prompt = user_prompt(passages)
    assert prompt.startswith("Document: Time banks (cite as: Doe 2012), IJCCR")
    assert "passage id 3 (page 2, section: Results)" in prompt
    assert "passage id 4 (page 3, section: -)" in prompt


## --- 2. Storing labels -------------------------------------------------------------------


@pytest.fixture
def work() -> Iterator[str]:
    """A work with two passages whose text never says what it is about."""
    key = "test" + uuid4().hex[:12]
    meta = {
        "citation_key": key,
        "title": "T",
        "authors": "Doe, Jane",
        "year": 2024,
        "venue": None,
        "doi": None,
        "licence": "CC-BY-4.0",
        "full_text_allowed": True,
    }
    chunks = [
        Chunk("Table 3 shows the figures for each quarter.", 4, "Results"),
        Chunk("We thank the reviewers.", 9, "Acknowledgements"),
    ]
    with session_scope() as db:
        work_id = LiteratureRepository(db).add_work(meta, chunks)
    yield key
    with session_scope() as db:
        db.query(m.Chunk).filter_by(work_id=work_id).delete()
        db.query(m.Work).filter_by(id=work_id).delete()


@pytest.mark.db
def test_labels_are_stored_and_the_context_is_searchable(work: str) -> None:
    with session_scope() as db:
        rows = LiteratureRepository(db).unlabelled_passages(citation_key=work)
    assert [(r["page"], r["section"]) for r in rows] == [(4, "Results"), (9, "Acknowledgements")]
    first = rows[0]["id"]
    with session_scope() as db:
        LiteratureRepository(db).save_labels(
            [
                {
                    "id": first,
                    "context": "Quarterly zorbleflux of hypothetical currencies.",
                    "failure_modes": ["FM2"],
                    "parameters": ["velocity"],
                    "kind": "empirical_value",
                    "enriched_by": "test-model",
                }
            ]
        )
    with session_scope() as db:
        left = LiteratureRepository(db).unlabelled_passages(citation_key=work)
        chunk = db.get(m.Chunk, first)
        assert chunk is not None
        assert (chunk.failure_modes, chunk.parameters, chunk.kind, chunk.enriched_by) == (
            ["FM2"],
            ["velocity"],
            "empirical_value",
            "test-model",
        )
    assert [r["id"] for r in left] == [rows[1]["id"]]
    # The word appears only in the context sentence, never in the passage.
    hits = search("zorbleflux", limit=5)
    assert [h.citation_key for h in hits] == [work]
    assert hits[0].passage == "Table 3 shows the figures for each quarter."


## --- 3. A real call ----------------------------------------------------------------------


@pytest.mark.skipif(not os.environ.get("TE_LLM_API_KEY"), reason="needs TE_LLM_API_KEY")
def test_the_configured_model_labels_a_passage() -> None:
    model = os.environ.get("TE_AGENT_MODEL", "SLURM.utopia/qwen3.8:27b")
    base_url = os.environ.get("TE_LLM_BASE_URL", "https://utopia.hpc4ai.unito.it/api")
    labeller = Labeller(
        model,
        base_url=base_url,
        api_key=os.environ["TE_LLM_API_KEY"],
        extra={"chat_template_kwargs": {"enable_thinking": False}},
    )
    passage = {
        "id": 1,
        "page": 5,
        "section": "Results",
        "title": "Key indicators of time bank participation",
        "authors": "Collom, Ed",
        "year": 2012,
        "venue": "IJCCR",
        "text": "Only 58% of registered members made at least one exchange in the "
        "quarter; the rest were inactive.",
    }

    async def run() -> dict[int, Label]:
        try:
            return await labeller.label([passage])
        finally:
            await labeller.close()

    labels = asyncio.run(run())
    assert set(labels) == {1}
    assert labels[1].context
    assert labels[1].kind in {"empirical_value", "case_study", "mechanism"}


## --- 4. Searching with labels ------------------------------------------------------------


@pytest.fixture
def labelled_works() -> Iterator[tuple[str, str]]:
    """Two works on 'quibblecoin': one with three labelled passages, one with one."""
    keys, work_ids = [], []
    for n in (3, 1):
        key = "test" + uuid4().hex[:12]
        meta = {
            "citation_key": key,
            "title": "Q",
            "authors": "Doe, Jane",
            "year": 2024,
            "venue": None,
            "doi": None,
            "licence": "CC-BY-4.0",
            "full_text_allowed": True,
        }
        chunks = [Chunk(f"Quibblecoin passage {i} of {key}.", i + 1, "Results") for i in range(n)]
        with session_scope() as db:
            work_ids.append(LiteratureRepository(db).add_work(meta, chunks))
        keys.append(key)
    with session_scope() as db:
        rows = [
            r for k in keys for r in LiteratureRepository(db).unlabelled_passages(citation_key=k)
        ]
        first = rows[0]["id"]
        LiteratureRepository(db).save_labels(
            [
                {
                    "id": r["id"],
                    "context": "",
                    "enriched_by": "test",
                    "failure_modes": ["FM2"] if r["id"] == first else [],
                    "parameters": ["holding_time"] if r["id"] == first else [],
                    "kind": "empirical_value" if r["id"] == first else "mechanism",
                }
                for r in rows
            ]
        )
    yield keys[0], keys[1]
    with session_scope() as db:
        for work_id in work_ids:
            db.query(m.Chunk).filter_by(work_id=work_id).delete()
            db.query(m.Work).filter_by(id=work_id).delete()


@pytest.mark.db
def test_no_paper_fills_the_results(labelled_works: tuple[str, str]) -> None:
    big, small = labelled_works
    from te_platform.literature.search import MAX_PER_WORK

    keys = [h.citation_key for h in search("quibblecoin", limit=5)]
    assert keys.count(big) == MAX_PER_WORK < 3  # although it has three matching passages
    assert small in keys


@pytest.mark.db
def test_hits_carry_page_and_section(labelled_works: tuple[str, str]) -> None:
    hits = search("quibblecoin", limit=5)
    assert all(h.section == "Results" and h.page is not None for h in hits)


@pytest.mark.db
@pytest.mark.parametrize(
    "filters",
    [{"failure_mode": "FM2"}, {"parameter": "holding_time"}, {"kind": "empirical_value"}],
)
def test_filters_keep_only_labelled_passages(
    labelled_works: tuple[str, str], filters: dict[str, str]
) -> None:
    big, _ = labelled_works
    hits = search("quibblecoin", limit=5, **filters)
    assert [(h.citation_key, h.page) for h in hits] == [(big, 1)]


## --- 5. The tool -------------------------------------------------------------------------


def test_tool_rejects_unknown_filter_values() -> None:
    from pydantic import ValidationError

    from te_platform.tools.lit_search import LitSearchInput

    for bad in ({"parameter": "colour"}, {"kind": "opinion"}, {"failure_mode": "FM7"}):
        with pytest.raises(ValidationError):
            LitSearchInput.model_validate({"query": "velocity", **bad})


@pytest.mark.db
def test_tool_searches_without_filters_when_they_match_nothing(
    labelled_works: tuple[str, str],
) -> None:
    from te_platform.tools.lit_search import LitSearchInput, handle

    async def call(**filters: str) -> object:
        return await handle(LitSearchInput(query="quibblecoin", **filters), None)  # type: ignore[arg-type]

    hit = asyncio.run(call(failure_mode="FM2"))
    assert hit.filters_applied and len(hit.hits) == 1  # type: ignore[attr-defined]
    fallback = asyncio.run(call(failure_mode="FM6"))
    from te_platform.literature.search import MAX_PER_WORK

    expected = min(3, MAX_PER_WORK) + 1  # the big work (capped) and the small one
    assert not fallback.filters_applied and len(fallback.hits) == expected  # type: ignore[attr-defined]
    assert all(h.page is not None for h in fallback.hits)  # type: ignore[attr-defined]


@pytest.mark.db
def test_new_passages_carry_their_paper_header(work: str) -> None:
    with session_scope() as db:
        contexts = {
            c.context for c in db.query(m.Chunk).join(m.Work).filter(m.Work.citation_key == work)
        }
    assert contexts == {"Doe 2024, T"}


## While labelling is incomplete, a filter must not hide the passages not
## labelled yet (found by the grounded A/B test: kind=legal_rule hid the
## unlabelled MiCA articles from the agent).
@pytest.mark.db
def test_unlabelled_passages_pass_every_filter(work: str) -> None:
    hits = search("figures quarter", limit=5, kind="legal_rule", failure_mode="FM6")
    assert [(h.citation_key, h.page) for h in hits] == [(work, 4)]


## The tool's Literal types and the labeller's vocabularies must not drift.
def test_tool_filter_types_match_the_label_vocabularies() -> None:
    import typing

    from te_platform.literature.enrich import KINDS, PARAMETERS, Kind, Parameter

    assert typing.get_args(Parameter) == tuple(PARAMETERS)
    assert typing.get_args(Kind) == tuple(KINDS)


## A rejected filter value must give an error that serialises to JSON: a
## ValueError object inside the error details crashed the MCP server (seen live).
def test_filter_errors_are_plain_json() -> None:
    import json

    from pydantic import ValidationError

    from te_platform.tools.lit_search import LitSearchInput

    for bad in ({"parameter": "colour"}, {"kind": "opinion"}, {"failure_mode": "FM7"}):
        with pytest.raises(ValidationError) as exc:
            LitSearchInput.model_validate({"query": "velocity", **bad})
        json.dumps(exc.value.errors(include_url=False))
