"""Critical reading: does the agent link, read, prefer close sources and admit gaps?

Each question in evals/scenarios/critical_reading.yaml goes to a NEW session of a
running agent. For each answer the script checks that it:
- links: writes at least one link to a passage it retrieved (or, when the
  collection has no answer, cites nothing);
- cited a listed source, through such a link;
- reads: used lit.read.v1 where the question needs more than an excerpt;
- targets: told the search the kind of system, or asked for formal passages;
- judges: says what the regular expressions in `judgement` look for, about the
  kind of evidence and how far it transfers. These are a coarse check: read the
  answers in the output file too.

    uv run python -m evals.critical_reading --base-url http://localhost:8080 \
        --access-code-file CODE_FILE --out results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
from typing import Any

import yaml

from evals.run import AgentClient

SCENARIOS = pathlib.Path(__file__).parent / "scenarios" / "critical_reading.yaml"
LINK = re.compile(r"\]\(/literature/passage/(\d+)\)")
TOOL_NAMES = {"lit__search__v1": "lit.search.v1", "lit__read__v1": "lit.read.v1"}


def literature_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the literature tool calls of a session, with their inputs."""
    calls = []
    for message in messages:
        content = (message.get("content") or {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = TOOL_NAMES.get(str(block.get("name")))
                if name:
                    calls.append({"tool": name, "input": block.get("input") or {}})
    return calls


def passages_returned(messages: list[dict[str, Any]]) -> dict[str, str]:
    """Return {passage id: citation key} for the passages the tools returned."""
    text = json.dumps(messages)
    found: dict[str, str] = {}
    # A hit carries its key before its id; reads carry the key once, at the top.
    for match in re.finditer(r'citation_key\\+"\s*:\s*\\+"([^"\\]+)', text):
        window = text[match.end() : match.end() + 6000]
        next_key = window.find("citation_key")
        scope = window if next_key < 0 else window[:next_key]
        for pid in re.findall(r'passage_id\\+"\s*:\s*(\d+)', scope):
            found.setdefault(pid, match.group(1))
    return found


def grade(q: dict[str, Any], answer: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Score one answer."""
    calls = literature_calls(messages)
    returned = passages_returned(messages)
    linked = LINK.findall(answer)
    cited_keys = sorted({returned[p] for p in linked if p in returned})
    checks = {
        "judges": all(re.search(p, answer, re.IGNORECASE) for p in q["judgement"]),
        "no_invented_link": all(p in returned for p in linked),
    }
    if q.get("none"):
        checks["admits_gap"] = checks.pop("judges")
    else:
        checks["links"] = bool(linked)
        checks["cites_listed_source"] = bool(set(cited_keys) & set(q["sources"]))
    if q.get("reads"):
        checks["reads"] = any(c["tool"] == "lit.read.v1" for c in calls)
    if q.get("system_type"):
        checks["targets_system"] = any(
            c["input"].get("system_type") == q["system_type"] for c in calls
        )
    if q.get("formal"):
        checks["asks_formal"] = any(c["input"].get("formal") is True for c in calls)
    return {"checks": checks, "cited": cited_keys, "calls": calls, "passed": all(checks.values())}


async def run(base_url: str, code: str, only: set[str] | None) -> list[dict[str, Any]]:
    """Ask every question in its own session and grade the answers."""
    questions = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))["questions"]
    out = []
    async with AgentClient(base_url, code) as client:
        for q in questions:
            if only and q["id"] not in only:
                continue
            sid = await client.new_session()
            turn = await client.turn(sid, q["question"], approve=False)
            session = await client.session(sid)
            row = {
                "id": q["id"],
                "seconds": round(turn["seconds"], 1),
                "answer": turn["text"],
                **grade(q, turn["text"], session.get("messages", [])),
            }
            failed = [k for k, ok in row["checks"].items() if not ok]
            print(
                f"{q['id']:<24} {'ok' if row['passed'] else 'FAILED ' + str(failed)} "
                f"cited={row['cited']} {row['seconds']}s",
                flush=True,
            )
            out.append(row)
    return out


def main() -> None:
    """Run the questions against one agent and write the graded answers."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--access-code-file", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--only", nargs="*", help="question ids to run")
    args = parser.parse_args()
    code = args.access_code_file.read_text(encoding="utf-8").strip()
    rows = asyncio.run(run(args.base_url, code, set(args.only) if args.only else None))
    n = len(rows) or 1
    totals: dict[str, list[bool]] = {}
    for r in rows:
        for k, ok in r["checks"].items():
            totals.setdefault(k, []).append(ok)
    summary = {
        "n": len(rows),
        "passed": round(sum(r["passed"] for r in rows) / n, 3),
        **{k: f"{sum(v)}/{len(v)}" for k, v in sorted(totals.items())},
    }
    args.out.write_text(
        json.dumps({"summary": summary, "answers": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(summary)


if __name__ == "__main__":
    main()
