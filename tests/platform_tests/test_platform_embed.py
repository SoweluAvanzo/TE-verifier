"""Tests of literature/embed.py and the hybrid search in literature/search.py.

They run the real embedding model (fastembed, downloaded on first use) and
skip when it cannot be loaded.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from te_platform.db import models as m
from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope
from te_platform.literature import embed, rerank
from te_platform.literature.chunking import Chunk
from te_platform.literature.search import _fuse, search

needs_model = pytest.mark.skipif(not embed.available(), reason="embedding model not available")


## These tests add passages and search at once: check the stored vectors on
## every search instead of every RECHECK_S seconds.
@pytest.fixture(autouse=True)
def _recheck_always(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed, "RECHECK_S", 0.0)


## --- Pure parts ---------------------------------------------------------------------------


def test_fusion_rewards_passages_found_by_both_rankings() -> None:
    order = list(_fuse([(1.0, [1, 2, 3]), (1.0, [3, 4])]))
    assert order[0] == 3  # second and first: 1/62 + 1/61 beats 1/61 alone
    assert set(order) == {1, 2, 3, 4}


def test_fusion_weights_scale_a_ranking() -> None:
    order = list(_fuse([(0.1, [1]), (1.0, [2])]))
    assert order == [2, 1]


@needs_model
def test_vectors_have_unit_length_and_meaning() -> None:
    v = embed.embed(["banca del tempo", "time bank exchange of hours", "nuclear reactor cooling"])
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)
    # The Italian phrase is closer to its English meaning than to an unrelated one.
    assert v[0] @ v[1] > v[0] @ v[2]


## --- Stored vectors and hybrid search -----------------------------------------------------


@pytest.fixture
def embedded_work() -> Iterator[tuple[str, list[int]]]:
    """A work whose passages have vectors; removed afterwards."""
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
        Chunk(
            "In a time bank, members exchange services such as babysitting and gardening, and are paid in hours.",
            1,
            "Cases",
        ),
        Chunk("Quarterly accounts of the cooperative bakery were audited.", 2, "Finance"),
    ]
    with session_scope() as db:
        work_id = LiteratureRepository(db).add_work(meta, chunks)
    with session_scope() as db:
        ids = [c.id for c in db.query(m.Chunk).filter_by(work_id=work_id).order_by(m.Chunk.id)]
    with session_scope() as db:
        rows = [{"id": i, "section": "", "text": t.text} for i, t in zip(ids, chunks, strict=True)]
        vectors = embed.embed([r["text"] for r in rows])
        LiteratureRepository(db).save_embeddings(
            [(i, v.tobytes()) for i, v in zip(ids, vectors, strict=True)], embed.MODEL
        )
        LiteratureRepository(db).save_labels(
            [
                {
                    "id": ids[0],
                    "context": "Doe 2024, T",
                    "failure_modes": ["FM5"],
                    "parameters": ["participants"],
                    "kind": "case_study",
                    "enriched_by": "test",
                },
                {
                    "id": ids[1],
                    "context": "Doe 2024, T",
                    "failure_modes": [],
                    "parameters": [],
                    "kind": "mechanism",
                    "enriched_by": "test",
                },
            ]
        )
    yield key, ids
    with session_scope() as db:
        db.query(m.Chunk).filter_by(work_id=work_id).delete()
        db.query(m.Work).filter_by(id=work_id).delete()


@needs_model
@pytest.mark.db
def test_stored_vectors_are_found_by_meaning(embedded_work: tuple[str, list[int]]) -> None:
    _, ids = embedded_work
    near = embed.nearest("time banking: trading services for hours", 50)
    assert ids[0] in near
    assert near.index(ids[0]) < near.index(ids[1])


@needs_model
@pytest.mark.db
def test_italian_question_finds_english_passage_without_shared_words(
    embedded_work: tuple[str, list[int]],
) -> None:
    key, _ = embedded_work
    # No word of the query occurs in the passage, so keyword search alone misses it.
    hits = search("banca del tempo scambio di servizi tra vicini", limit=20)
    assert any(h.citation_key == key and h.page == 1 for h in hits)


@needs_model
@pytest.mark.db
def test_filters_apply_to_passages_found_by_meaning(
    embedded_work: tuple[str, list[int]],
) -> None:
    key, _ = embedded_work
    hits = search("banca del tempo scambio di servizi tra vicini", limit=20, kind="case_study")
    mine = [h for h in hits if h.citation_key == key]
    assert [h.page for h in mine] == [1]
    # The bakery passage matches the query but has no FM5 label: filtered out.
    pages = [
        h.page
        for h in search("cooperative bakery accounts", limit=20, failure_mode="FM5")
        if h.citation_key == key
    ]
    assert 2 not in pages


@needs_model
@pytest.mark.db
def test_replaced_passages_are_reloaded_even_when_their_number_is_unchanged() -> None:
    def add(text: str) -> tuple[str, int]:
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
        with session_scope() as db:
            work_id = LiteratureRepository(db).add_work(meta, [Chunk(text, 1, "")])
        with session_scope() as db:
            chunk_id = db.query(m.Chunk.id).filter_by(work_id=work_id).scalar()
            LiteratureRepository(db).save_embeddings(
                [(chunk_id, embed.embed([text])[0].tobytes())], embed.MODEL
            )
        return work_id, chunk_id

    def remove(work_id: str) -> None:
        with session_scope() as db:
            db.query(m.Chunk).filter_by(work_id=work_id).delete()
            db.query(m.Work).filter_by(id=work_id).delete()

    first_work, first = add("Demurrage makes money lose value over time.")
    assert first in embed.nearest("demurrage", 100)
    remove(first_work)
    second_work, second = add("Demurrage makes idle balances shrink every month.")
    try:
        near = embed.nearest("demurrage", 100)
        assert second in near
        assert first not in near
    finally:
        remove(second_work)


## Between checks the index answers from memory (a check scans the table);
## after RECHECK_S it sees new passages.
@needs_model
@pytest.mark.db
def test_the_index_rechecks_only_after_the_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    index = embed._Index()
    monkeypatch.setattr(embed, "RECHECK_S", 3600.0)
    index.get()  # loads (the first get always checks)
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
    with session_scope() as db:
        work_id = LiteratureRepository(db).add_work(meta, [Chunk("Fresh passage.", 1, "")])
    try:
        with session_scope() as db:
            chunk_id = db.query(m.Chunk.id).filter_by(work_id=work_id).scalar()
            LiteratureRepository(db).save_embeddings(
                [(chunk_id, embed.embed(["Fresh passage."])[0].tobytes())], embed.MODEL
            )
        ids, _ = index.get()
        assert chunk_id not in ids  # within the interval: not checked again
        monkeypatch.setattr(embed, "RECHECK_S", 0.0)
        ids, _ = index.get()
        assert chunk_id in ids
    finally:
        with session_scope() as db:
            db.query(m.Chunk).filter_by(work_id=work_id).delete()
            db.query(m.Work).filter_by(id=work_id).delete()


## `te-platform lit add` (cli.py): ingest + (labels) + vectors in one command,
## then a summary. Labelling needs the model; --no-label tests the rest.
@needs_model
@pytest.mark.db
def test_lit_add_ingests_embeds_and_summarises(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from te_platform.cli import main
    from tests.platform_tests.test_platform_literature import _make_pdf

    key = "test" + uuid4().hex[:12]
    _make_pdf(
        [["1 Introduction", "", "Una banca del tempo scambia servizi tra i soci del quartiere."]],
        tmp_path / "p.pdf",
    )
    (tmp_path / "p.bib").write_text(
        f"@article{{{key},\n  title = {{Banche del tempo}},\n  author = {{Rossi, Anna}},\n"
        "  year = {2024}\n}\n",
        encoding="utf-8",
    )
    code = main(
        [
            "lit",
            "add",
            str(tmp_path / "p.pdf"),
            "--bib",
            str(tmp_path / "p.bib"),
            "--licence",
            "CC-BY-4.0",
            "--full-text-allowed",
            "--no-label",
        ]
    )
    out = capsys.readouterr().out
    try:
        assert code == 0
        assert f"Ingested {key} (it): 1 passages, full text." in out
        assert "Rossi 2024, Banche del tempo" in out  # the header, until labelled
        with session_scope() as db:
            chunk = db.query(m.Chunk).join(m.Work).filter(m.Work.citation_key == key).one()
            assert chunk.language == "it" and chunk.embedding_model == embed.MODEL
    finally:
        with session_scope() as db:
            work = db.query(m.Work).filter_by(citation_key=key).one()
            db.query(m.Chunk).filter_by(work_id=work.id).delete()
            db.delete(work)


## --- Reranking (literature/rerank.py) -----------------------------------------------------

needs_reranker = pytest.mark.skipif(not rerank.available(), reason="reranker not available")


@needs_reranker
def test_the_reranker_puts_the_answering_passage_first() -> None:
    docs = [
        "The bakery's quarterly accounts were audited by the cooperative.",
        "In a time bank, members trade services and are paid in hours of time.",
        "Ethereum burns the base fee of every transaction.",
    ]
    assert rerank.order("how do time banks pay their members?", docs)[0] == 1


def test_reranking_can_be_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rerank, "MODEL", "")
    assert rerank.available() is False
