"""Tests of literature/embed.py and the hybrid search in literature/search.py.

They run the real embedding model (fastembed, downloaded on first use) and
skip when it cannot be loaded.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import numpy as np
import pytest

from te_platform.db import models as m
from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope
from te_platform.literature import embed
from te_platform.literature.chunking import Chunk
from te_platform.literature.search import _fuse, search

needs_model = pytest.mark.skipif(not embed.available(), reason="embedding model not available")


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
