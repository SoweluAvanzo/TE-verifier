## =============================================================================
## te_platform/literature/enrich.py — a context sentence and labels per passage
## =============================================================================
## PURPOSE      enrich(...) asks a language model, once per passage, for
##              - `context`: one English sentence that places the passage in
##                its paper ("From Collom 2012, a study of US time banks,
##                results section: active members per quarter..."), with the
##                words a searcher would use, including synonyms;
##              - `failure_modes`: which of FM1..FM6 the passage informs;
##              - `parameters`: which framework parameters it informs
##                (PARAMETERS below, the paper's symbols in words);
##              - `kind`: what the passage offers (KINDS below).
##              The search index covers section + context + text (migration
##              c3f1a8d26e57), so a passage that never names its subject is
##              still found by it, and lit.search.v1 can filter by the labels.
## USED BY      cli.py (`te-platform lit enrich`).
## DEPENDS ON   httpx2 (extra "agent"), db/repo.py (LiteratureRepository),
##              db/session.py, config.py (llm_base_url, llm_api_key).
## WHY          "Contextual retrieval" (Anthropic, 2024): prefixing each
##              passage with a short model-written context cut failed
##              retrievals by 35% (49% with hybrid search). The labels let the
##              agent ask for, e.g., typical values of the holding time.
## MODEL        Any OpenAI-compatible chat endpoint (Utopia by default). The
##              model only labels passages; its output is validated, unknown
##              labels are dropped, and nothing it writes is shown to users as
##              a quotation (search returns the passage text itself).
## =============================================================================

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx2
from pydantic import BaseModel, Field, field_validator

from te_platform.config import get_settings
from te_platform.db.repo import LiteratureRepository
from te_platform.db.session import session_scope
from te_platform.literature.chunking import cite_as

FAILURE_MODES = {
    "FM1": "token oversupply / inflation (emission outpaces real activity)",
    "FM2": "velocity trap (tokens have no reason to be held and are spent at once: velocity "
    "too high, wealth-weighted holding time near one period; NOT hoarding, which is the "
    "opposite)",
    "FM3": "burn/emission imbalance (sinks do not offset issuance)",
    "FM4": "free-rider / contribution collapse (verification, monitoring, sanctions, rewards)",
    "FM5": "insufficient critical mass (too few participants or offers for exchange)",
    "FM6": "governance capture (concentrated decision power or token holdings)",
}

PARAMETERS = {
    "emission_rate": "E(t), tokens issued per period",
    "burn_rate": "B(t), tokens destroyed per period, burn mechanisms",
    "burn_coverage": "rho = B/E",
    "money_supply": "M, tokens in circulation",
    "velocity": "V, velocity of circulation",
    "holding_time": "tau, how long tokens are held",
    "activity_volume": "Q, real transactions or output",
    "growth_rate": "g, growth of activity or members",
    "participants": "N, number of (active) participants",
    "offer_variety": "K, number of distinct goods or services offered",
    "demand": "d, needs per participant per period",
    "contribution_share": "phi, share of participants who contribute",
    "monitoring": "gamma, probability that a violation is detected",
    "sanction": "S, penalty for a detected violation",
    "reward": "reward or incentive for contributing",
    "topology": "who can interact with whom (network structure)",
    "centralization": "Gamma, share of decisions taken unilaterally",
    "wealth_inequality": "Gini or concentration of holdings",
    "initial_distribution": "who receives tokens at launch",
    "redemption": "conversion into national currency, exit fees",
}

KINDS = {
    "empirical_value": "a measured number, range or observed fact from data",
    "mechanism": "how something works or why it happens",
    "remedy": "a design change or policy that prevents or fixes a problem",
    "case_study": "the description of a specific real system",
    "legal_rule": "a provision of law or regulation, or its interpretation",
    "method": "a modelling, simulation, estimation or evaluation method",
    "definition": "a definition or classification",
    "other": "anything else (front matter, references, acknowledgements)",
}

## The same values as types, for tool inputs (lit.search.v1): a Literal's
## validation error is plain text, so it serialises like any other.
Parameter = Literal[
    "emission_rate",
    "burn_rate",
    "burn_coverage",
    "money_supply",
    "velocity",
    "holding_time",
    "activity_volume",
    "growth_rate",
    "participants",
    "offer_variety",
    "demand",
    "contribution_share",
    "monitoring",
    "sanction",
    "reward",
    "topology",
    "centralization",
    "wealth_inequality",
    "initial_distribution",
    "redemption",
]
Kind = Literal[
    "empirical_value",
    "mechanism",
    "remedy",
    "case_study",
    "legal_rule",
    "method",
    "definition",
    "other",
]

MAX_CONTEXT_CHARS = 400
ATTEMPTS = 3  # tries per request: network errors and busy servers are usually brief

SYSTEM = (
    "You label passages of research papers and legal texts for a search index used by an "
    "assistant that helps people design token economies and community currencies. "
    "For each passage return:\n"
    "- context: ONE English sentence (at most 50 words) that places the passage in its "
    "document: name the document (first author and year, or the act), the part it comes "
    "from, and what the passage is about, using the words someone searching for it would "
    "use, including common synonyms (e.g. community / complementary / local currency). "
    "Write in English even if the passage is not. Use only what the title, section and "
    "passage say: add no facts or numbers of your own.\n"
    "- failure_modes: the ids among "
    + "; ".join(f"{k} = {v}" for k, v in FAILURE_MODES.items())
    + " that the passage gives evidence, mechanisms or remedies about. Usually zero to two; "
    "empty if none.\n"
    "- parameters: the ids among "
    + "; ".join(f"{k} = {v}" for k, v in PARAMETERS.items())
    + " that the passage informs. Empty if none.\n"
    "- kind: one of " + "; ".join(f"{k} = {v}" for k, v in KINDS.items()) + ".\n"
    'Answer with JSON only: {"passages": [{"id": <id>, "context": "...", '
    '"failure_modes": [...], "parameters": [...], "kind": "..."}, ...]} with one entry '
    "per passage, in the same order."
)


class Label(BaseModel):
    """The labels of one passage, as validated from the model's answer."""

    id: int
    context: str = Field(min_length=1)
    failure_modes: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    kind: str = "other"

    @field_validator("context")
    @classmethod
    def _one_short_line(cls, v: str) -> str:
        v = " ".join(v.split())
        return v if len(v) <= MAX_CONTEXT_CHARS else v[:MAX_CONTEXT_CHARS].rsplit(" ", 1)[0]

    @field_validator("failure_modes")
    @classmethod
    def _known_failure_modes(cls, v: list[str]) -> list[str]:
        out = [s.strip().upper() for s in v]
        return sorted({s for s in out if s in FAILURE_MODES})

    @field_validator("parameters")
    @classmethod
    def _known_parameters(cls, v: list[str]) -> list[str]:
        return sorted({s.strip().lower() for s in v if s.strip().lower() in PARAMETERS})

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        v = v.strip().lower()
        return v if v in KINDS else "other"


def user_prompt(passages: list[dict[str, Any]]) -> str:
    """Describe the passages of ONE work to the model."""
    w = passages[0]
    head = f"Document: {w['title']} (cite as: {cite_as(w['authors'], w['year'])})"
    if w.get("venue"):
        head += f", {w['venue']}"
    parts = [head, ""]
    for p in passages:
        parts.append(f"--- passage id {p['id']} (page {p['page']}, section: {p['section'] or '-'})")
        parts.append(p["text"])
    return "\n".join(parts)


def parse_labels(answer: str, ids: list[int]) -> dict[int, Label]:
    """Return the valid labels in the model's answer, by passage id (others are dropped)."""
    text = re.sub(r"^```(?:json)?|```$", "", answer.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    items = data.get("passages", []) if isinstance(data, dict) else []
    wanted, out = set(ids), {}
    for item in items:
        try:
            label = Label.model_validate(item)
        except ValueError:
            continue
        if label.id in wanted:
            out[label.id] = label
    return out


@dataclass
class Stats:
    """What a run did."""

    labelled: int = 0
    failed: int = 0
    calls: int = 0


class Labeller:
    """Calls an OpenAI-compatible chat endpoint to label batches of passages."""

    def __init__(self, model: str, *, base_url: str, api_key: str, extra: dict[str, Any]) -> None:
        self.model = model
        self.extra = extra
        self._client = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx2.Timeout(connect=10.0, read=300.0, write=30.0, pool=60.0),
        )

    async def close(self) -> None:
        """Close the HTTP connections."""
        await self._client.aclose()

    async def label(self, passages: list[dict[str, Any]]) -> dict[int, Label]:
        """Label passages of one work; retry transient errors twice."""
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_prompt(passages)},
            ],
            "temperature": 0,
            # Room for the answer (about 120 tokens per passage) and for the
            # reasoning some models do before it even when asked not to
            # (Utopia's qwen3.8 still reasons for 300-700 tokens).
            "max_tokens": 1500 + 250 * len(passages),
            **self.extra,
        }
        for attempt in range(ATTEMPTS):
            try:
                answer = await self._post(body)
            except (httpx2.TransportError, httpx2.HTTPStatusError):
                if attempt == ATTEMPTS - 1:
                    raise
                await asyncio.sleep(5 * (attempt + 1))
            else:
                return parse_labels(answer, [p["id"] for p in passages])
        return {}

    async def _post(self, body: dict[str, Any]) -> str:
        """Send one request; return the answer text (HTTPStatusError on any error status)."""
        resp = await self._client.post("/chat/completions", json=body)
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"].get("content") or "")


def _batches(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    """Group passages by work, then cut each work's passages into batches."""
    by_work: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_work.setdefault(r["citation_key"], []).append(r)
    return [ps[i : i + size] for ps in by_work.values() for i in range(0, len(ps), size)]


async def enrich(  # noqa: PLR0913 - the keyword-only options of `te-platform lit enrich`
    *,
    model: str,
    base_url: str | None = None,
    batch_size: int = 6,
    concurrency: int = 4,
    limit: int | None = None,
    citation_key: str | None = None,
    extra: dict[str, Any] | None = None,
    progress: Any = print,
) -> Stats:
    """Label every passage that has no labels yet (or only those of one work)."""
    s = get_settings()
    if s.llm_api_key is None:
        raise RuntimeError("No model API key: set the te_llm_api_key secret (TE_LLM_API_KEY).")
    with session_scope() as db:
        rows = LiteratureRepository(db).unlabelled_passages(limit=limit, citation_key=citation_key)
    batches = _batches(rows, batch_size)
    progress(f"{len(rows)} passages to label in {len(batches)} calls")
    labeller = Labeller(
        model,
        base_url=base_url or s.llm_base_url,
        api_key=s.llm_api_key.get_secret_value(),
        extra=extra or {},
    )
    stats, gate = Stats(), asyncio.Semaphore(concurrency)

    async def one(batch: list[dict[str, Any]]) -> None:
        async with gate:
            try:
                labels = await labeller.label(batch)
            except (httpx2.TransportError, httpx2.HTTPStatusError) as exc:
                labels = {}
                progress(f"call failed for {batch[0]['citation_key']}: {exc}")
            if len(batch) > 1 and len(labels) < len(batch):
                # A long batch is the usual cause of a truncated or malformed
                # answer: label the missing passages one at a time.
                for p in batch:
                    if p["id"] not in labels:
                        with contextlib.suppress(httpx2.TransportError, httpx2.HTTPStatusError):
                            labels.update(await labeller.label([p]))
            stats.calls += 1
            if labels:
                with session_scope() as db:
                    LiteratureRepository(db).save_labels(
                        [{**lb.model_dump(), "enriched_by": model} for lb in labels.values()]
                    )
            stats.labelled += len(labels)
            stats.failed += len(batch) - len(labels)
            if stats.calls % 50 == 0:
                progress(f"{stats.calls}/{len(batches)} calls, {stats.labelled} labelled")

    try:
        await asyncio.gather(*(one(b) for b in batches))
    finally:
        await labeller.close()
    return stats
