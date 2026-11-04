## =============================================================================
## te_platform/literature/embed.py — meaning vectors for search across wording and languages
## =============================================================================
## PURPOSE      embed_missing() stores a vector for every passage that has none
##              (`te-platform lit embed`); nearest(query, n) returns the ids of
##              the passages whose vectors are closest to the query's. search.py
##              merges that ranking with the keyword ranking (hybrid search).
## MODEL        MODEL below, run locally with fastembed (ONNX, CPU): multilingual,
##              so an Italian or French question finds English passages and the
##              other way round. No external service: search keeps working when
##              the department's model server is down. If fastembed or the
##              model files are missing, available() is False and search uses
##              keywords only.
## MEMORY       The vectors (float32, 384 numbers each: about 15 MB for 10,000
##              passages) are loaded once per process and reloaded when the
##              set of embedded passages changes.
## DEPENDS ON   fastembed + numpy (extra "literature"), db/repo.py, db/session.py.
## =============================================================================

from __future__ import annotations

import os
import threading
from functools import cache
from typing import TYPE_CHECKING, Any

import numpy as np

from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope

if TYPE_CHECKING:
    from collections.abc import Sequence

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
## Where the model files are: fastembed's own FASTEMBED_CACHE_PATH (set in
## Dockerfile.platform, where the model is downloaded at build time; not a
## TE_* variable, which config.py would refuse as unknown), else fastembed's
## default cache, downloaded on first use.
BATCH = 64


@cache
def _model() -> Any:
    """Load the embedding model once per process."""
    from fastembed import TextEmbedding  # noqa: PLC0415 - optional dependency, loaded on use

    return TextEmbedding(MODEL, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH") or None)


def available() -> bool:
    """Return True when the embedding model can be loaded."""
    try:
        _model()
    except Exception:  # noqa: BLE001 - any failure means: search without vectors
        return False
    return True


def passage_text(section: str, text: str) -> str:
    """Return what is embedded for a passage: its section heading and text."""
    return f"{section}. {text}" if section else text


def embed(texts: Sequence[str]) -> np.ndarray:
    """Return unit-length float32 vectors, one row per text."""
    vectors = np.array(list(_model().embed(list(texts), batch_size=BATCH)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def embed_missing(limit: int | None = None, progress: Any = print) -> int:
    """Store a vector for every passage without one of MODEL; return how many were stored."""
    with session_scope() as db:
        rows = LiteratureRepository(db).passages_without_embedding(MODEL, limit=limit)
    progress(f"{len(rows)} passages to embed")
    done = 0
    for start in range(0, len(rows), 512):
        part = rows[start : start + 512]
        vectors = embed([passage_text(r["section"], r["text"]) for r in part])
        with session_scope() as db:
            LiteratureRepository(db).save_embeddings(
                [(r["id"], v.tobytes()) for r, v in zip(part, vectors, strict=True)], MODEL
            )
        done += len(part)
        progress(f"{done}/{len(rows)} embedded")
    return done


class _Index:
    """The passages' vectors in memory, reloaded when the set of passages changes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = np.zeros(0, dtype=np.int64)
        self._matrix = np.zeros((0, 0), dtype=np.float32)
        self._fingerprint = (0, 0)

    def get(self) -> tuple[np.ndarray, np.ndarray]:
        with session_scope() as db:
            fingerprint = LiteratureRepository(db).embeddings_fingerprint(MODEL)
        with self._lock:
            if fingerprint != self._fingerprint:
                self._fingerprint = fingerprint
                with session_scope() as db:
                    rows = LiteratureRepository(db).embeddings(MODEL)
                self._ids = np.array([i for i, _ in rows], dtype=np.int64)
                self._matrix = (
                    np.frombuffer(b"".join(v for _, v in rows), dtype=np.float32).reshape(
                        len(rows), -1
                    )
                    if rows
                    else np.zeros((0, 0), dtype=np.float32)
                )
            return self._ids, self._matrix


_INDEX = _Index()


def nearest(query: str, n: int) -> list[int]:
    """Return the ids of the n passages closest in meaning to the query, closest first."""
    ids, matrix = _INDEX.get()
    if len(ids) == 0:
        return []
    scores = matrix @ embed([query])[0]
    n = min(n, len(ids))
    top = np.argpartition(-scores, n - 1)[:n]
    return [int(ids[i]) for i in top[np.argsort(-scores[top])]]
