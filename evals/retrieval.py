"""Measure literature search against a test set of questions with known sources.

Each question in evals/scenarios/retrieval.yaml is phrased the way the agent
queries lit.search.v1 at one of the moments it needs research (the interview,
explaining a check, designing an experiment, writing the report) and lists
the works that answer it. A question with no listed work marks a gap: nothing
in the collection answers it yet, and it counts as a miss.

The score is per work: a question is answered at k when one of its works is
among the first k passages returned.

Run where the literature database is reachable, e.g. inside the mcp container:
    docker compose run --rm --no-deps -T -v "$PWD/evals:/app/evals:ro" \
        --entrypoint python mcp -m evals.retrieval --out /tmp/r.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
from collections import defaultdict
from typing import Any

import yaml

from te_platform.literature.search import search

SCENARIOS = pathlib.Path(__file__).parent / "scenarios" / "retrieval.yaml"
DEPTH = 10  # passages fetched per question
KS = (1, 3, 5, 10)


def rank_of_first_relevant(keys: list[str], relevant: set[str]) -> int | None:
    """Return the 1-based rank of the first passage from a relevant work, if any."""
    for i, key in enumerate(keys, start=1):
        if key in relevant:
            return i
    return None


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return hit rates at each k and the mean reciprocal rank for a group of questions."""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    out: dict[str, Any] = {"n": n, "answerable": sum(1 for r in rows if r["relevant"])}
    for k in KS:
        out[f"hit@{k}"] = round(sum(1 for r in rows if r["rank"] and r["rank"] <= k) / n, 3)
    out["mrr@10"] = round(sum(1 / r["rank"] for r in rows if r["rank"]) / n, 3)
    return out


def run(path: pathlib.Path) -> dict[str, Any]:
    """Search every question and return per-question results and grouped scores."""
    questions = yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]
    rows = []
    for q in questions:
        keys = [h.citation_key for h in search(q["query"], limit=DEPTH)]
        relevant = set(q.get("relevant") or [])
        rows.append(
            {
                "id": q["id"],
                "moment": q["moment"],
                "area": q["area"],
                "lang": q.get("lang", "en"),
                "query": q["query"],
                "relevant": sorted(relevant),
                "rank": rank_of_first_relevant(keys, relevant),
                "top5": keys[:5],
            }
        )
    groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for field in ("moment", "area", "lang"):
            groups[field][r[field]].append(r)
    return {
        "overall": summarise(rows),
        "answerable_only": summarise([r for r in rows if r["relevant"]]),
        "by": {f: {g: summarise(rs) for g, rs in sorted(gs.items())} for f, gs in groups.items()},
        "questions": rows,
    }


def main() -> None:
    """Print the scores and optionally write the full results as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenarios", type=pathlib.Path, default=SCENARIOS)
    parser.add_argument("--out", type=pathlib.Path, help="write full results as JSON here")
    args = parser.parse_args()
    result = run(args.scenarios)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("overall        ", result["overall"])
    print("answerable only", result["answerable_only"])
    for field, groups in result["by"].items():
        for name, s in groups.items():
            print(f"{field:<7} {name:<14}", s)
    misses = [
        r for r in result["questions"] if r["relevant"] and not (r["rank"] and r["rank"] <= 5)
    ]
    print(f"\nanswerable questions missed in the top 5: {len(misses)}")
    for r in misses:
        print(f"  {r['id']:<26} {r['query']!r} -> {r['top5']}")


if __name__ == "__main__":
    main()
