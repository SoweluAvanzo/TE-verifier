## =============================================================================
## tests/platform_tests/test_platform_reports.py — tests for te_platform/reports/
## =============================================================================
## GUIDE STEP   10.1 (charts + render golden tests), 10.2 (number check),
##              10.3 (the report task)
## PURPOSE      1. charts.py and render.py: GOLDEN tests. Render a report for
##                 each example spec, extract the PDF's text with pypdf, and
##                 check that the key sections and values are present.
##                 (Comparing PDF bytes would break on every font or library
##                 update.) The charts' SVG must contain their labels.
##              2. numbers_check.py: PROPERTY tests with hypothesis. Instead
##                 of a few hand-picked examples, hypothesis generates hundreds
##                 of numbers and texts and searches for one that breaks a
##                 rule; when it finds one, it shrinks it to the simplest
##                 failing example. The rules below ARE the specification.
##                 Plus: the renderer refuses an invented number.
##              3. jobs/report_task.py: render_report, called with the payload
##                 the report tool queues, writes the PDF (with its
##                 provenance) to the reports folder and stores its record.
##                 The worker runs exactly this function; the queue around
##                 it is tested in test_platform_jobs.py.
## DEPENDS ON   hypothesis, pypdf, weasyprint (render tests only: they are
##              skipped, with the reason, where WeasyPrint's system library
##              Pango is missing; the Docker image and CI have it).
##              Section 3 also needs the real PostgreSQL of
##              test_platform_db.py (marker `db`, same HOW TO RUN there).
## ACTIVATE     Section 1 with guide 10.1, section 2 (commented twice) with
##              guide 10.2, section 3 (commented twice) with guide 10.3.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
##
## Guide 10.1
## [ ] 1. Imports: BytesIO, Path, Any, types.ModuleType, pytest, PdfReader
##        (pypdf), service (te_platform) and charts (te_platform.reports).
## [ ] 2. Helper `_render_module()`: import te_platform.reports.render inside
##        a try; on OSError (WeasyPrint cannot load Pango) call pytest.skip
##        with the error as the reason; return the module.
## [ ] 3. Helper `_verification(example)`: service.verify the example's YAML
##        and return (result, a dict shaped like verify.run.v1's stored
##        output: verification_ref, severity, service.merged_verdicts(result)).
## [ ] 4. test_charts_contain_their_labels: verdict_summary_svg of two
##        verdicts ("pass", "fail") contains "<svg", "pass", "fail" and the
##        axis label; violation_probability_svg of one simulated item
##        contains its failure mode, both legend labels and the axis label.
## [ ] 5. test_report_contains_key_sections(example), parametrized over
##        bitcoin, axie_infinity and makerdao: render_pdf with a fixed
##        narrative and provenance, simulation=None, citations=[]; read the
##        text with PdfReader(BytesIO(pdf)); assert "Verdicts", "Provenance"
##        and "Written by the AI assistant" are in it, plus the first 20
##        characters of verification_ref.
## [ ] 6. test_citation_without_venue_or_year_prints_no_none: a citation
##        with only authors and title; the PDF text has no "None".
## [ ] 7. Check:
##          | uv run pytest tests/platform_tests/test_platform_reports.py -q
##
## Guide 10.2 (later: the "# # " lines in the SOLUTION)
## [ ] 8. Imports: `given` and `strategies as st` (hypothesis),
##        check_narrative, collect_numbers, extract_numbers and InvalidInput.
## [ ] 9. test_integers_round_trip_with_thousands_separators: @given an
##        integer n between -10**9 and 10**9; extract_numbers(f"value
##        {n:,} here") == [float(n)].
## [ ] 10. test_a_number_from_the_data_is_always_allowed: @given a float
##        rounded to 3 decimals; a narrative quoting it gives no problems
##        against collect_numbers({"v": x}).
## [ ] 11. test_rounding_is_accepted: with data 0.2731, the text "about
##        0.27, i.e. 27%" gives no problems.
## [ ] 12. test_invented_number_is_rejected: "37% per year" against data
##        0.05 gives exactly one problem that names it:
##          | assert len(problems) == 1 and "37" in problems[0]
## [ ] 13. test_identifiers_and_citation_years_are_ignored: parametrized
##        over "FM3 fails", "see v1.2" and "Ostrom (1990) argues"; each
##        passes with an empty allowed set.
## [ ] 14. test_unicode_minus_and_exponent: "between −2.5 and 1e6" (with a
##        Unicode minus sign) gives [-2.5, 1e6].
## [ ] 15. test_render_refuses_an_invented_number: render_pdf with the
##        narrative "Supply grows by 987654321.5 a year." (a number in no
##        example) raises InvalidInput.
## [ ] 16. Check: the step 7 command.
##
## Guide 10.3 (later: the "# # " lines in the SOLUTION; first:
## jobs/report_task.py and the reports table)
## [ ] 17. Imports: Iterator, UTC/datetime/timedelta, uuid4, get_settings,
##         Repository, session_scope, load_protocol, verifier_version,
##         Principal and load_policy.
## [ ] 18. Fixture `report_dir(tmp_path, monkeypatch)`: set
##         TE_REPORT_STORAGE_DIR to tmp_path, get_settings.cache_clear(),
##         yield tmp_path, clear the cache again.
## [ ] 19. test_report_task_writes_the_pdf_and_its_record (marker db):
##         skip without Pango (_render_module), then import render_report
##         inside the test; store the bitcoin verification as verify.run.v1
##         does (save_verification, with spec_hash and te_name); call
##         render_report with a full payload (header of report_task.py);
##         assert its return value, that <report_dir>/<report_id>.pdf
##         carries the provenance (name, spec hash, verifier, policy and
##         protocol versions), and that the owner's get_report gives the
##         path, the verification_ref and expires_at.
## [ ] 20. Check (a PostgreSQL running, test_platform_db.py HOW TO RUN):
##          | uv run pytest tests/platform_tests/test_platform_reports.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from io import BytesIO
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pypdf import PdfReader

from te_platform import service

## Guide 10.3: the report task's database, settings and provenance sources.
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from te_platform.config import get_settings
from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.elicitation.protocol import load_protocol
from te_platform.hashing import verifier_version
from te_platform.registry.context import Principal
from te_platform.registry.policy import load_policy
from te_platform.reports import charts

## Phase 10.2: the number check.
from hypothesis import given
from hypothesis import strategies as st
from te_platform.errors import InvalidInput
from te_platform.reports.numbers_check import check_narrative, collect_numbers, extract_numbers


## --- Helpers --------------------------------------------------------------------------
def _render_module() -> ModuleType:
    """Import reports/render.py, or skip the test where Pango is missing."""
    try:
        from te_platform.reports import render
    except OSError as exc:  # "cannot load library 'libpango...'": a host without Pango
        pytest.skip(f"WeasyPrint's system libraries are missing: {exc}")
    return render


def _verification(example: str) -> tuple[Any, dict[str, Any]]:
    """Verify examples/<example>.yaml; return the result and the stored-output shape."""
    result = service.verify((Path("examples") / f"{example}.yaml").read_text())
    # Same shape as the stored output of verify.run.v1 (what the worker renders).
    verification = {
        "verification_ref": result.verification_ref,
        "severity": result.report["severity"],
        "verdicts": service.merged_verdicts(result),
    }
    return result, verification


def _provenance(name: str, spec_hash: str) -> dict[str, Any]:
    return {
        "spec_name": name,
        "spec_hash": spec_hash,
        "verifier_version": "test",
        "policy_version": "0.1.0",
        "protocol_version": "0.1.0",
        "generated_at": "fixed",
        "overrides": [],
        "spec_summary": [],
    }


def _pdf_text(pdf: bytes) -> str:
    return "".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)


## --- 1. Charts and rendering (golden) -----------------------------------------------------
def test_charts_contain_their_labels() -> None:
    svg = charts.verdict_summary_svg([{"status": "pass"}, {"status": "fail"}])
    assert svg.lstrip().startswith(("<?xml", "<svg")) and "<svg" in svg
    # svg.fonttype = none keeps text as text, so the labels are searchable.
    assert "pass" in svg and "fail" in svg and "number of failure-mode checks" in svg
    svg = charts.violation_probability_svg(
        [
            {
                "failure_mode": "FM3",
                "subject": "TOK",
                "simulated": True,
                "n_runs": 10,
                "p_violation": 0.3,
                "n_violations_at_deployment": 1,
                "n_violations_dynamic": 2,
            }
        ]
    )
    assert "More tokens created than removed (TOK)" in svg  # plain name, not FM3
    assert "already at launch" in svg and "appeared later" in svg
    assert "share of simulated runs in which the problem appeared" in svg


@pytest.mark.parametrize("example", ["bitcoin", "axie_infinity", "makerdao"])
def test_report_contains_key_sections(example: str) -> None:
    render = _render_module()
    result, verification = _verification(example)
    pdf = render.render_pdf(
        verification=verification,
        simulation=None,
        narrative={"summary": "See the table."},
        provenance=_provenance(example, result.spec_hash),
        citations=[],
    )
    text = _pdf_text(pdf)
    assert "The six questions at a glance" in text and "Provenance" in text
    assert "written by the AI design assistant" in " ".join(text.split())
    assert result.verification_ref[:20] in text.replace("\n", "")


def test_citation_without_venue_or_year_prints_no_none() -> None:
    render = _render_module()
    result, verification = _verification("bitcoin")
    pdf = render.render_pdf(
        verification=verification,
        simulation=None,
        narrative={"summary": "See the table."},
        provenance=_provenance("bitcoin", result.spec_hash),
        citations=[{"authors": "Ostrom, E.", "title": "Governing the Commons"}],
    )
    text = _pdf_text(pdf)
    assert "Governing the Commons" in text
    assert "None" not in text


## --- 2. numbers_check properties (guide 10.2) ------------------------------------------------
## Phase 10.2: whatever integer we write as "1,234,567", it is read back exactly.
@given(st.integers(min_value=-(10**9), max_value=10**9))
def test_integers_round_trip_with_thousands_separators(n: int) -> None:
    assert extract_numbers(f"value {n:,} here") == [float(n)]


## Phase 10.2: a number quoted from the data always passes.
@given(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False).map(lambda x: round(x, 3)))
def test_a_number_from_the_data_is_always_allowed(x: float) -> None:
    text = f"The threshold is {x}."
    assert check_narrative({"summary": text}, collect_numbers({"v": x})) == []


## Phase 10.2: the data says 0.2731; writing "0.27" or "27%" is a faithful rounding.
def test_rounding_is_accepted() -> None:
    allowed = collect_numbers({"p": 0.2731})
    assert check_narrative({"s": "about 0.27, i.e. 27%"}, allowed) == []


## Phase 10.2: an invented number is reported, naming the number.
def test_invented_number_is_rejected() -> None:
    problems = check_narrative(
        {"summary": "Supply grows by 37% per year."}, collect_numbers({"g": 0.05})
    )
    assert len(problems) == 1 and "37" in problems[0]


## Phase 10.2: identifiers and citation years are not results.
@pytest.mark.parametrize("text", ["FM3 fails", "see v1.2", "Ostrom (1990) argues"])
def test_identifiers_and_citation_years_are_ignored(text: str) -> None:
    assert check_narrative({"s": text}, set()) == []


## Phase 10.2: the Unicode minus sign and exponents are read correctly.
def test_unicode_minus_and_exponent() -> None:
    assert extract_numbers("between −2.5 and 1e6") == [-2.5, 1e6]


## Phase 10.2: the renderer is the second line of defence (render.py, part 1).
def test_render_refuses_an_invented_number() -> None:
    render = _render_module()
    result, verification = _verification("bitcoin")
    with pytest.raises(InvalidInput):
        render.render_pdf(
            verification=verification,
            simulation=None,
            narrative={"summary": "Supply grows by 987654321.5 a year."},
            provenance=_provenance("bitcoin", result.spec_hash),
            citations=[],
        )


## --- 3. The report task (guide 10.3) -------------------------------------------------------
## Guide 10.3: the task writes under Settings.report_storage_dir; use a temporary folder.
@pytest.fixture
def report_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TE_REPORT_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


## Guide 10.3: the worker's report job, from the payload the report tool queues to the
## file and its record (the download tests start from a row they insert themselves).
@pytest.mark.db
def test_report_task_writes_the_pdf_and_its_record(report_dir: Path) -> None:
    _render_module()
    # Imported here, after the Pango check: report_task imports WeasyPrint.
    from te_platform.jobs.report_task import render_report

    result, verification = _verification("bitcoin")
    te_name = result.report["te_name"]
    owner = Principal(id="u-" + uuid4().hex, kind="user")
    # The task reads the verification from the database, as verify.run.v1 stored it.
    # Under a reference of its own: the store is shared and insert-only, so a
    # partial row under bitcoin's real reference would be served to later
    # verify.run.v1 calls (test_platform_tools.py, test_verify_matches_cli).
    vref = "test-report-" + uuid4().hex
    with session_scope() as db:
        Repository(db, owner).save_verification(
            vref,
            result.spec_hash,
            {**verification, "spec_hash": result.spec_hash, "te_name": te_name},
        )
    report_id = uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    out = render_report(
        {
            "verification_ref": vref,
            "principal_id": owner.id,
            "session_id": None,
            "correlation_id": "test-" + report_id,
            "report_id": report_id,
            "narrative": {"summary": "See the table."},
            "audience": "designer",
            "include_simulations": False,
            "expires_at": expires_at.isoformat(),
            "citations": [],
        }
    )
    # A draft: the agent gets the report's text to review before publishing it.
    assert out["kind"] == "report" and out["report_id"] == report_id
    assert out["state"].startswith("draft") and out["pages"] >= 1
    assert te_name in out["review_text"] and "[page 1]" in out["review_text"]
    path = report_dir / f"{report_id}.pdf"
    text = _pdf_text(path.read_bytes())
    # The provenance the task adds (reports print where their numbers come from).
    policy_dir = get_settings().policy_dir
    versions = (
        f"{load_policy(policy_dir / 'tool_policy.yaml').policy_version} / "
        f"{load_protocol(policy_dir / 'elicitation_protocol.yaml').version}"
    )
    assert te_name in text and versions in text and verifier_version() in text
    assert result.spec_hash[:20] in text.replace("\n", "")
    with session_scope() as db:
        record = Repository(db, owner).get_report(report_id)
    assert record["path"] == str(path)
    assert record["verification_ref"] == vref
    assert record["expires_at"] == expires_at
