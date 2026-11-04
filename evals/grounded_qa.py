"""Grounded answers: does the agent answer research questions correctly, from sources?

Each question in evals/scenarios/grounded_qa.yaml goes to a NEW session of a
running agent (one turn, no design loaded). For each answer the script checks:
- searched: the agent called lit.search.v1;
- facts: every gold fact (a regular expression) appears in the answer;
- cites_source: the answer names one of the question's sources, by citation
  key or by first author and year;
- invented: citation keys the answer names that none of its searches returned
  (should always be empty: the agent may cite only returned passages).
It writes every answer and the keys its searches returned, for reading.

    uv run python -m evals.grounded_qa --base-url http://127.0.0.1:8002 \
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

SCENARIOS = pathlib.Path(__file__).parent / "scenarios" / "grounded_qa.yaml"
KEY = re.compile(r"\b([a-z][a-z_]*\d{4}[a-z0-9_]*)\b")


def cite_patterns(key: str) -> list[str]:
    """Return ways an answer may name a work: its key, or 'Author ... year'."""
    m = re.match(r"([a-z]+?)(\d{4})", key.replace("_", ""))
    if not m:
        return [re.escape(key)]
    name, year = m.groups()
    return [re.escape(key), rf"{name}[^\n]{{0,40}}{year}"]


def returned_keys(messages: list[dict[str, Any]]) -> set[str]:
    """Return the citation keys in the session's tool results.

    A tool result's content is stored as a JSON string inside the message,
    so its quotes appear escaped once serialised; the pattern allows that.
    Only lit.search.v1 results carry citation_key fields.
    """
    text = json.dumps(messages)
    return set(re.findall(r'citation_key\\*"\s*:\s*\\*"([^"\\]+)', text))


def grade(q: dict[str, Any], answer: str, tools: list[str], returned: set[str]) -> dict[str, Any]:
    """Score one answer."""
    facts = [bool(re.search(f, answer, re.IGNORECASE | re.DOTALL)) for f in q["facts"]]
    # Also match with spaces removed: "ten Broeke 2016" names tenbroeke2016which.
    squeezed = answer.replace(" ", "")
    cites = any(
        re.search(p, text, re.IGNORECASE)
        for text in (answer, squeezed)
        for k in q["sources"]
        for p in cite_patterns(k)
    )
    named = set(KEY.findall(answer))
    return {
        "searched": "lit.search.v1" in tools,
        "facts_ok": all(facts),
        "facts": facts,
        "cites_source": cites,
        "invented": sorted(named - returned),
    }


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
            returned = returned_keys(session.get("messages", []))
            tools = [t["tool"] for t in turn["tools"]]
            row = {
                "id": q["id"],
                "seconds": round(turn["seconds"], 1),
                "tools": tools,
                "returned": sorted(returned),
                "answer": turn["text"],
            }
            row.update(grade(q, turn["text"], tools, returned))
            print(
                f"{q['id']:<24} searched={row['searched']!s:<5} facts={row['facts_ok']!s:<5} "
                f"cites={row['cites_source']!s:<5} invented={row['invented']} {row['seconds']}s"
            )
            out.append(row)
    return out


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the share of answers that searched, were correct, cited a source, invented none."""
    n = len(rows) or 1
    return {
        "n": len(rows),
        "searched": round(sum(r["searched"] for r in rows) / n, 3),
        "facts_ok": round(sum(r["facts_ok"] for r in rows) / n, 3),
        "cites_source": round(sum(r["cites_source"] for r in rows) / n, 3),
        "correct_and_cited": round(sum(r["facts_ok"] and r["cites_source"] for r in rows) / n, 3),
        "no_invented_citation": round(sum(not r["invented"] for r in rows) / n, 3),
        "mean_seconds": round(sum(r["seconds"] for r in rows) / n, 1),
    }


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
    result = {"summary": summary(rows), "answers": rows}
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(result["summary"])


if __name__ == "__main__":
    main()
