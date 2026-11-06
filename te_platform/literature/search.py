## =============================================================================
## te_platform/literature/search.py — find passages for a question
## =============================================================================
## GUIDE STEP   11.2 (full-text search); 11.3 (optional hybrid search)
## PURPOSE      search(query, limit) returns the best-matching passages of the
##              curated collection, each with its bibliographic data, as Hit
##              objects. It uses PostgreSQL full-text search:
##              - websearch_to_tsquery turns the user's words into a query
##                (it understands "quoted phrases", OR, and -excluded words,
##                and never raises on odd input, unlike to_tsquery);
##              - the `tsv` column of chunks (generated, GIN-indexed, see
##                db/models.py) finds matching passages fast;
##              - ts_rank_cd ranks them ("cover density": passages where the
##                query words appear close together rank higher).
##              The query itself lives in db/repo.py
##              (LiteratureRepository.search_passages), the only code that
##              queries the database; this file bounds the request, shortens
##              the passages and types the result.
## USED BY      tools/lit_search.py (tool lit.search.v1), evals (recall test).
## DEPENDS ON   db/session.py, db/repo.py (LiteratureRepository), pydantic.
## WHY          D15: keyword search inside the existing database first, no
##              extra service or embedding model until the evaluation shows a
##              need. Passages are truncated to PASSAGE_MAX_CHARS: the public
##              endpoint returns short quotations, never whole copyrighted
##              texts (architecture §3.7).
## SECURITY     The query is passed as a bound parameter, never pasted into
##              SQL text, so it cannot inject SQL (db/repo.py). Results are DATA for
##              the agent, never instructions (tool policy usage_rules).
## ACTIVATE     Uncomment after 11.1; test_platform_literature.py has the
##              recall test set (top-3 recall >= 0.8, guide 11.2).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|"
## are short illustrations, not the full code. Keep Hit and search exactly:
## tools/lit_search.py and the tests use them.
##
## Guide 11.2 (first: the tsv column and its GIN index, db/models.py, and
## LiteratureRepository.search_passages, db/repo.py)
## [ ] 1. Imports at the top: BaseModel; LiteratureRepository and
##        session_scope.
## [ ] 2. PASSAGE_MAX_CHARS = 600 and `class Hit(BaseModel)`: citation_key,
##        title, authors, year, venue, doi, passage, score.
## [ ] 3. `_shorten(text)`: unchanged when short enough, else cut at the
##        last space before the limit and add " …".
## [ ] 4. `search(query, limit=5) -> list[Hit]`: clamp limit to 1..20; in a
##        session_scope, LiteratureRepository(db).search_passages(query,
##        limit); return one Hit per row, with the passage shortened:
##          | Hit(passage=_shorten(row.pop("text")), **row)
## [ ] 5. Check: test_search_finds_the_ingested_passage, then write the
##        ~20 real questions and activate test_top3_recall in
##        tests/platform_tests/test_platform_literature.py (it needs the
##        ingested seed collection), then
##          | uv run pytest tests/platform_tests/test_platform_literature.py -q
##
## Guide 11.3 (optional, later)
## [ ] 6. Only if top-3 recall stays below 0.8: follow the hybrid search
##        sketch at the end of the SOLUTION (explanation only, no code).
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from typing import Any

from pydantic import BaseModel

from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope
from te_platform.literature import embed, rerank
from te_platform.literature.reading import source_fields

PASSAGE_MAX_CHARS = 600
## At most this many passages per paper in one result list: otherwise one
## long paper that uses the query's words often fills every place, and the
## other papers on the topic are never seen. One per paper finds more
## papers (retrieval test set: 80% vs 76% top-5), but in the grounded A/B
## (evals/grounded_qa.py) it cost answers their key numbers: the agent saw
## Centola 2018's introduction but not the page with the 25% tipping point.
## Two per paper gave 79% correct and cited answers.
MAX_PER_WORK = 2


class Hit(BaseModel):
    """One search result: a short passage and the paper it comes from."""

    citation_key: str
    title: str
    authors: str
    year: int | None
    venue: str | None
    doi: str | None
    page: int | None = None  # where the passage starts, for "p. 12" in citations
    section: str = ""
    passage: str
    score: float
    locator: str = ""  # "Article 19(1)-(3)", "Theorem 3"
    formal: bool = False
    kind: str | None = None
    context: str = ""  # one sentence placing the passage in its document
    systems: list[str] = []
    # literature/reading.py source_fields: citation, links, how to read it
    passage_id: int
    cite: str
    cite_markdown: str
    link: str
    original_url: str | None = None
    evidence_type: str
    source_tier: int
    source_group: str
    how_to_read: str


def _shorten(text: str) -> str:
    """Return the passage, cut to PASSAGE_MAX_CHARS at a word boundary."""
    if len(text) <= PASSAGE_MAX_CHARS:
        return text
    # Cut at the last space before the limit, so no word is broken.
    return text[:PASSAGE_MAX_CHARS].rsplit(" ", 1)[0] + " …"


## Hybrid search (literature/embed.py): the keyword ranking and the ranking
## by meaning are merged with weighted Reciprocal Rank Fusion: a passage
## scores sum(weight / (RRF_K + rank)) over the rankings it appears in. The
## weights were chosen on the retrieval test set (evals/retrieval.py).
RRF_K = 60
KEYWORD_WEIGHT = 1.0
MEANING_WEIGHT = 1.0
MEANING_POOL = 60  # passages taken from the ranking by meaning


RANK_K = 5  # how quickly relevance falls with rank, against the source priority below
# Priority of a source, by how close it is to the system being designed. It
# reorders passages that are similarly relevant; a far better passage from a
# farther tier still comes first. Law and methods apply by subject: never moved.
SAME_SYSTEM = 1.3
OTHER_BLOCKCHAIN = 1.15
RELATED_NOT_BLOCKCHAIN = 1.0
FOUNDATIONS = 0.85
NEUTRAL = 1.0
TIER_FOUNDATIONS = 3
RECENT_FROM = 2018  # a year's advantage from here on, for sources about real systems
PER_RECENT_YEAR = 0.01
MAX_RECENCY = 0.08
NON_BLOCKCHAIN = frozenset({"local_currency", "mutual_credit", "time_bank"})


def source_priority(row: dict[str, Any], system_type: str | None) -> float:
    """Return how much to favour a passage for its source, whatever the words matched."""
    tier = row.get("tier", 0)
    if tier == 0:
        return NEUTRAL
    if tier == TIER_FOUNDATIONS:
        return FOUNDATIONS
    same = system_type is not None and system_type in row.get("systems", ())
    if same:
        base = SAME_SYSTEM
    elif tier == 1:
        # For a non-blockchain design, tokens are a neighbour rather than the same thing.
        base = RELATED_NOT_BLOCKCHAIN if system_type in NON_BLOCKCHAIN else OTHER_BLOCKCHAIN
    else:
        base = OTHER_BLOCKCHAIN if system_type in NON_BLOCKCHAIN else RELATED_NOT_BLOCKCHAIN
    years = max(0, (row.get("year") or 0) - RECENT_FROM)
    return base + min(MAX_RECENCY, years * PER_RECENT_YEAR)


def _prioritised(
    order: dict[int, float], rows: dict[int, dict[str, Any]], system_type: str | None
) -> dict[int, float]:
    """Reorder a ranking by relevance rank times source priority, best first."""
    scored = {
        chunk_id: source_priority(rows[chunk_id], system_type) / (RANK_K + rank)
        for rank, chunk_id in enumerate(order, start=1)
    }
    return dict(sorted(scored.items(), key=lambda kv: -kv[1]))


def _fuse(rankings: list[tuple[float, list[int]]]) -> dict[int, float]:
    """Merge rankings of passage ids by weighted Reciprocal Rank Fusion, best first."""
    scores: dict[int, float] = {}
    for weight, ids in rankings:
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (RRF_K + rank)
    return dict(sorted(scores.items(), key=lambda kv: -kv[1]))


def _reranked(
    query: str, order: dict[int, float], rows: dict[int, dict[str, Any]]
) -> dict[int, float]:
    """Reorder the top rerank.POOL candidates by the cross-encoder (rerank.py), if on."""
    if not order or not rerank.available():
        return order
    top = list(order)[: rerank.POOL]
    docs = [
        embed.passage_text(
            rows[i]["section"], rows[i]["text"][: rerank.CHARS], rows[i].get("context", "")
        )
        for i in top
    ]
    new = [top[j] for j in rerank.order(query, docs)]
    return {i: order[i] for i in new} | {i: s for i, s in order.items() if i not in set(top)}


def _meaning_ids(query: str) -> list[int]:
    """Return the passages closest in meaning, or [] when the model is unavailable."""
    if not embed.available():
        return []
    return embed.nearest(query, MEANING_POOL)


def search(  # noqa: PLR0913 (keyword-only filters of one query)
    query: str,
    limit: int = 5,
    *,
    failure_mode: str | None = None,
    parameter: str | None = None,
    kind: str | None = None,
    formal: bool | None = None,
    system_type: str | None = None,
) -> list[Hit]:
    """Return the passages that best match the query, best first.

    Keyword and meaning rankings are merged (hybrid search); failure_mode,
    parameter and kind keep only passages with that label
    (literature/enrich.py); no paper appears more than MAX_PER_WORK times.
    """
    limit = max(1, min(limit, 20))  # bound the work per call
    filters = {
        "failure_mode": failure_mode,
        "parameter": parameter,
        "kind": kind,
        "formal": formal,
    }
    meaning = _meaning_ids(query)
    with session_scope() as db:
        repo = LiteratureRepository(db)
        # Spare rows, so the per-paper cap still leaves `limit`.
        keyword_rows = repo.search_passages(query, limit * 4, **filters)
        rows = {r["id"]: r for r in keyword_rows}
        for r in repo.passages_by_ids([i for i in meaning if i not in rows], **filters):
            rows[r["id"]] = r
    order = _fuse(
        [
            (KEYWORD_WEIGHT, [r["id"] for r in keyword_rows]),
            (MEANING_WEIGHT, [i for i in meaning if i in rows]),
        ]
    )
    order = _prioritised(_reranked(query, order, rows), rows, system_type)
    per_work: dict[str, int] = {}
    hits: list[Hit] = []
    for chunk_id, fused in order.items():
        row = {**rows[chunk_id], "score": round(fused, 6)}
        key = row["citation_key"]
        if per_work.get(key, 0) >= MAX_PER_WORK:
            continue
        per_work[key] = per_work.get(key, 0) + 1
        fields = source_fields(row)
        for internal in ("id", "position", "tier", "source_url"):
            row.pop(internal)
        hits.append(Hit(passage=_shorten(row.pop("text")), **row, **fields))
        if len(hits) == limit:
            break
    return hits


## --- Phase 11.3 (optional): hybrid search ---------------------------------------
## Only if the recall test shows keyword search misses passages that match in
## MEANING but not in words. Sketch:
##   1. add the pgvector extension and an `embedding` column (db/models.py);
##   2. compute embeddings at ingestion with a small local embedding model;
##   3. in LiteratureRepository (db/repo.py), a second query for the top-k
##      by vector distance (`m.Chunk.embedding.cosine_distance(query_vec)`);
##      here, merge it with the keyword top-k using Reciprocal Rank Fusion:
##      score = Σ 1 / (60 + rank_i).
## Keep keyword search as the fallback when the embedding service is down.
