"""The standard report: fixed structure, at most 12 pages, nothing outside the page."""

import copy
import io
import re
from pathlib import Path
from typing import Any

import pdfplumber
import pytest
import yaml
from pypdf import PdfReader

from te_platform import service
from te_platform.reports.design import (
    DESIGN_SECTIONS,
    FIGURE_NOTE_WORDS,
    MAX_PAGES,
    WORD_LIMITS,
    design_context,
    over_word_limit,
)
from te_platform.reports.method import figure_ids
from te_platform.reports.method import test_matrix as matrix_of
from te_platform.reports.plain import describe, rule_words
from te_platform.reports.render import render_pdf

ROOT = Path(__file__).parents[2]


def _spec() -> dict[str, Any]:
    text = (ROOT / "te_platform" / "agent" / "prompts" / "interview.md").read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    assert match
    return yaml.safe_load(match.group(1))


def _words(n: int) -> str:
    """Return n plain words without figures, in paragraphs, as a longest allowed section."""
    words = ["members", "tokens", "design", "community", "rules", "supply", "activity", "space"]
    return " ".join(words[i % len(words)] for i in range(n))


def _longest_narrative() -> dict[str, str]:
    return {key: _words(limit) for key, limit in WORD_LIMITS.items()}


def _experiment(n: int, spec: dict[str, Any], verdicts: list[dict], variants: int) -> dict[str, Any]:
    points = [{"t": t, "M": 10.0 * t} for t in range(0, 104, 8)]
    rows = [
        {
            "name": "current",
            "changes": [],
            "verdicts": verdicts,
            "trajectories": {"CREDIT": points},
        }
    ]
    rows += [
        {
            "name": f"a_quite_long_variant_name_{i}",
            "description": "A description of what this variant represents for the design",
            "changes": [{"path": "events[use].payload[0].range", "value": 8 + i}],
            "verdicts": verdicts,
            "trajectories": {"CREDIT": points},
        }
        for i in range(variants)
    ]
    return {
        "job_id": f"job-{n}",
        "title": f"Experiment number {n} with a fairly long title about what it tests",
        "question": "Does this change the answers?",
        "design": {"horizon": 104, "seed": 1, "monte_carlo_runs": 0},
        "variants": rows,
    }


@pytest.fixture(scope="module")
def full_report() -> dict[str, Any]:
    """The longest report the standard allows: every section at its limit, many tests."""
    spec = _spec()
    result = service.verify(spec)
    verification = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    verification["verdicts"] = service.merged_verdicts(result)
    simulation = service.simulate(spec, n_runs=10, horizon=30, seed=1)
    answers = [
        {
            "slot_id": "governance.gamma",
            "indices": [],
            "value": 0.5,
            "status": "estimated",
            "user_quote": "x",
            "spec_version": 1,
        }
    ] * 25
    messages = [{"role": "user", "content": {"content": [{"type": "text", "text": _words(150)}]}}]
    design = design_context(spec, answers, messages)
    experiments = [_experiment(n, spec, verification["verdicts"], 5) for n in range(1, 4)]
    citations = [
        {
            "citation_key": f"source{n}",
            "authors": "Author, One and Author, Two",
            "year": 2020,
            "title": "A long title of a paper in the research library " * 2,
            "venue": "A Journal",
            "original_url": "https://doi.org/10.1000/a-rather-long-identifier-of-this-paper",
        }
        for n in range(12)
    ]
    ids = figure_ids(design, simulation, experiments)
    pdf = render_pdf(
        verification=verification,
        simulation=simulation,
        narrative=_longest_narrative(),
        provenance={
            "spec_name": "The longest report",
            "spec_hash": verification.get("spec_hash", ""),
            "verification_ref": verification.get("verification_ref", ""),
            "verifier_version": "v",
            "policy_version": "p",
            "protocol_version": "p",
            "generated_at": "2026-11-06T00:00:00+00:00",
            "overrides": [],
            "spec_summary": [],
        },
        citations=citations,
        design=design,
        experiments=experiments,
        figure_notes={i: _words(FIGURE_NOTE_WORDS) for i in ids},
    )
    return {"pdf": pdf, "ids": ids, "experiments": experiments, "spec": spec}


def test_the_longest_allowed_report_fits_the_page_limit(full_report: dict) -> None:
    assert len(PdfReader(io.BytesIO(full_report["pdf"])).pages) <= MAX_PAGES


def test_nothing_runs_outside_the_page(full_report: dict) -> None:
    with pdfplumber.open(io.BytesIO(full_report["pdf"])) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            outside = [w["text"] for w in page.extract_words() if w["x1"] > page.width - 20]
            assert not outside, f"page {number}: {outside[:5]}"


def test_the_sections_come_in_the_standard_order(full_report: dict) -> None:
    text = " ".join(
        p.extract_text() or "" for p in PdfReader(io.BytesIO(full_report["pdf"])).pages
    )
    order = [
        "The six questions at a glance",
        "1. Your design",
        "2. Results, question by question",
        "3. What was tested",
        "4. What to change",
        "5. Limits and legal orientation",
        "Annex",
        "Provenance",
    ]
    positions = [text.index(heading) for heading in order]
    assert positions == sorted(positions)


def test_no_raw_identifiers_or_data_reach_the_reader(full_report: dict) -> None:
    text = " ".join(
        p.extract_text() or "" for p in PdfReader(io.BytesIO(full_report["pdf"])).pages
    )
    for raw in ('{"min"', "_auto_", "payload[", "events[", "a_quite_long"):
        assert raw not in text, raw


def test_a_report_has_one_chart_per_kind(full_report: dict) -> None:
    assert sum(i.startswith("experiment") for i in full_report["ids"]) == 1


def test_a_chart_with_no_data_is_left_out() -> None:
    empty = _experiment(1, _spec(), [], 1)
    for variant in empty["variants"]:
        variant["trajectories"] = {"CREDIT": [{"t": t, "M": 0.0} for t in range(5)]}
    assert figure_ids(None, None, [empty]) == []


def test_the_tested_ideas_table_has_one_row_per_variant_and_one_baseline() -> None:
    verdicts = [
        {"failure_mode": "FM3: Burn", "subject": "A", "status": "pass"},
        {"failure_mode": "FM3: Burn", "subject": "B", "status": "fail"},
    ]
    experiments = [_experiment(n, _spec(), verdicts, 2) for n in (1, 2)]
    matrix = matrix_of(experiments, _spec())
    names = [row["name"] for g in matrix["groups"] for row in g["rows"]]
    assert names.count("Your design") == 1
    assert len(names) == 5
    # Over several tokens a question shows its worst answer.
    assert matrix["groups"][0]["rows"][0]["cells"][2] == "fail"
    assert len(matrix["columns"]) == 6


def test_word_limits_are_reported_per_section() -> None:
    too_long = over_word_limit(
        {"executive_summary": _words(WORD_LIMITS["executive_summary"] + 1), "limitations": "fine"},
        {"flow": _words(FIGURE_NOTE_WORDS + 1)},
    )
    assert len(too_long) == 2
    assert "executive_summary" in too_long[0] and "figure flow" in too_long[1]
    assert over_word_limit(_longest_narrative(), {}) == []


def test_only_the_standard_sections_exist() -> None:
    assert DESIGN_SECTIONS == ("design_overview",)
    assert "explanation" not in WORD_LIMITS


## --- Rules in plain words -----------------------------------------------------------
def test_a_rule_on_an_event_amount_states_the_amount_and_how_often() -> None:
    event = {
        "id": "use",
        "payload": [{"name": "amount", "range": {"min": 5, "max": 5}}],
        "frequency": {"family": "linear", "parameter_ranges": {"b": {"min": 10, "max": 400}}},
    }
    rule = {
        "trigger": {"event_id": "use"},
        "function": {"expression": {"var": {"ns": "event", "path": ["amount"]}, "args": []}},
    }
    words = rule_words(rule, {"use": event}, "CUE")
    assert words.startswith("5 CUE each time")
    assert "10 to 400 times a week" in words


def test_an_expiry_rule_is_stated_in_words() -> None:
    event = {"id": "_auto_CUE_burn_rules_1", "kind": "time_based"}
    rule = {
        "trigger": {"event_id": "_auto_CUE_burn_rules_1"},
        "function": {
            "expression": "state.M['CUE'] / param.expiry_periods",
            "parameters": [{"name": "expiry_periods", "range": {"min": 52, "max": 52}}],
        },
    }
    words = rule_words(rule, {"_auto_CUE_burn_rules_1": event}, "CUE")
    assert "share of the tokens in circulation" in words and "52" in words
    assert "_auto_" not in words


def test_values_stored_as_text_are_shown_as_values() -> None:
    answer = {
        "slot_id": "participants.Q",
        "indices": [],
        "value": '{"min": 100, "max": 4000}',
        "status": "estimated",
        "user_quote": "",
    }
    spec = copy.deepcopy(_spec())
    del spec["participants"]["expected_Q"]
    row = design_context(spec, [answer], [])["inputs"][0]
    assert "{" not in row["value"] and "100" in row["value"]
    assert describe("meta.name", "Name", spec, None) == "Name"
