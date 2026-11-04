## =============================================================================
## te_platform/literature/rerank.py — reorder the best candidates by reading them
## =============================================================================
## PURPOSE      order(query, docs) scores each (question, passage) pair with a
##              cross-encoder, a model that reads both together, and returns the
##              passages' order by that score. search.py applies it to the top
##              POOL candidates of the hybrid ranking.
## MODEL        MODEL below (English, about 0.12 GB, run locally with fastembed).
##              On the retrieval test set it raised the right paper first from
##              61% to 66% and the mean reciprocal rank from 0.68 to 0.73, for
##              about 3-4 s per search on the search container's CPU. The
##              multilingual bge-reranker-v2-m3 was measured too: 3-6 s more
##              per search, too slow for a chat. LIT_RERANK_MODEL="" turns it
##              off (not a TE_* variable: config.py refuses unknown ones).
## =============================================================================

from __future__ import annotations

import os
from functools import cache
from typing import Any

MODEL = os.environ.get("LIT_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-12-v2")
POOL = 20  # candidates reread; more costs time, few right papers sit lower
CHARS = 600  # of each passage's text: about 150 tokens, with its context first


@cache
def _model() -> Any:
    """Load the cross-encoder once per process (one thread: see embed.py)."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: PLC0415 - optional

    return TextCrossEncoder(
        MODEL, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH") or None, threads=1
    )


def available() -> bool:
    """Return True when reranking is on and its model can be loaded."""
    if not MODEL:
        return False
    try:
        _model()
    except Exception:  # noqa: BLE001 - any failure means: no reranking
        return False
    return True


def order(query: str, docs: list[str]) -> list[int]:
    """Return the indices of docs, best match for the query first."""
    scores = list(_model().rerank(query, docs, batch_size=POOL))
    return sorted(range(len(docs)), key=lambda i: -scores[i])
