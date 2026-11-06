## =============================================================================
## te_platform/reports/render.py — data + template -> PDF bytes
## =============================================================================
## GUIDE STEP   10.1 (render), 10.2 (narrative check, commented twice)
## PURPOSE      render_pdf(...) builds the report:
##              1. checks the narrative against the data (numbers_check.py);
##              2. draws the charts (charts.py);
##              3. fills templates/report.html with Jinja2;
##              4. converts the HTML + templates/report.css to PDF with
##                 WeasyPrint and returns the PDF as bytes.
##              It does not store anything: the caller decides where the bytes go.
## USED BY      jobs/report_task.py (the `report` job runs this in the worker),
##              tools/report_render_pdf.py (through the job), tests.
## DEPENDS ON   jinja2, weasyprint (needs system libraries Pango/HarfBuzz; the
##              Dockerfile installs them), reports/charts.py,
##              reports/numbers_check.py (from 10.2). Provenance values
##              (versions, hashes) arrive ready-made in `provenance`.
## WHY          D14: fixed sections filled from data are deterministic and
##              auditable; only labelled narrative comes from the LLM, and it
##              is checked (P1). Rendering runs in the worker because it can
##              take seconds and must not block a web request.
## ACTIVATE     10.1: uncomment after the `reports` extra is installed (the
##              number check lines stay commented). Golden test: render each
##              examples/*.yaml verification, extract the PDF text (pypdf) and
##              check key sections (test_platform_reports.py). 10.2: toggle
##              the twice-commented number-check lines, after
##              numbers_check.py.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep `render_pdf` and its
## keyword-only arguments exactly: jobs/report_task.py and the tests call it.
## Activate numbers_check.py, charts.py and templates/report.html first.
##
## Guide 10.1 (render)
## [ ] 1. Imports at the top: Path, Any, Environment, FileSystemLoader,
##        StrictUndefined and select_autoescape from jinja2, HTML from
##        weasyprint (with the `type: ignore` of the SOLUTION: WeasyPrint
##        has no type hints) and the charts module.
## [ ] 2. `_TEMPLATES = Path(__file__).parent / "templates"`.
## [ ] 3. `_ENV`, the Jinja2 Environment created once:
##          | loader=FileSystemLoader(_TEMPLATES),
##          | autoescape=select_autoescape(["html"]),
##          | undefined=StrictUndefined,
##        (the `##` note above it explains both choices).
## [ ] 4. `render_pdf(*, verification, simulation, narrative, provenance,
##        citations) -> bytes`, in numbered parts:
##        2. verdict_chart = charts.verdict_summary_svg(the verdicts);
##           sim_chart = charts.violation_probability_svg(per_fm_results)
##           only if some item is simulated, else None;
##        3. render "report.html" from _ENV with all five inputs plus the
##           two charts as keyword arguments;
##        4. return HTML(string=html, base_url=str(_TEMPLATES)).write_pdf()
##           (base_url lets the template find report.css).
##        Part 1 (the number check) comes at guide 10.2.
## [ ] 5. Check: install the `reports` extra (WeasyPrint also needs the
##        Pango system library, which the Docker image installs), activate
##        the guide 10.1 tests of tests/platform_tests/test_platform_reports.py,
##          | uv run pytest tests/platform_tests/test_platform_reports.py -q
##          | uv run mypy te_platform
##
## Guide 10.2 (later: the "# # " lines in the SOLUTION)
## [ ] 6. Write reports/numbers_check.py first. Then toggle the import of
##        ensure_supported (it comes last among the imports).
## [ ] 7. Part 1 of render_pdf, before the charts: one line,
##          | ensure_supported(narrative, verification, simulation or {})
##        which raises InvalidInput if the narrative has an invented
##        number.
## [ ] 8. Check: test_render_refuses_an_invented_number in
##        test_platform_reports.py, with the step 5 commands.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from weasyprint import HTML  # type: ignore[import-untyped]  # WeasyPrint publishes no type hints

from te_platform.reports import method, plain

## Phase 10.2: the number check (reports/numbers_check.py). The import comes
## last because it sorts after the charts import (ruff checks the order).
from te_platform.reports.design import (
    DESIGN_SECTIONS,
    EVALUATION_SECTIONS,
    NARRATIVE_SECTIONS,
    fmt_value,
    change_words,
    humanize_name,
    path_label,
)
from te_platform.reports.numbers_check import ensure_supported

_TEMPLATES = Path(__file__).parent / "templates"

## The Jinja2 environment, created once.
## - autoescape: every {{ value }} is HTML-escaped (`<` becomes `&lt;`).
##   The narrative comes from an LLM and spec names come from users; without
##   escaping, text like "<img src=x onerror=...>" or "<style>" would become
##   real markup in the report (an injection, like XSS in a browser).
##   SVG charts are the only values marked safe, explicitly (| safe), because
##   we generated them ourselves.
## - StrictUndefined: a misspelled variable in the template raises an error
##   instead of silently printing nothing (a missing section would otherwise
##   go unnoticed). Optional fields are read with `.get(...)` in the template.
_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATES),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
)


def render_pdf(  # noqa: PLR0913  one argument per report part
    *,
    verification: dict[str, Any],
    simulation: dict[str, Any] | None,
    narrative: dict[str, str],
    provenance: dict[str, Any],
    citations: list[dict[str, Any]],
    design: dict[str, Any] | None = None,
    experiments: list[dict[str, Any]] | None = None,
    figure_notes: dict[str, str] | None = None,
) -> bytes:
    """Build the PDF and return its bytes.

    verification: the verify.run.v1 output (verdicts, severity, ref, ...).
    simulation:   the finished sim.monte_carlo.v1 result, or None.
    narrative:    {"executive_summary": "...", "explanation": "..."} written by
                  the agent (the sections tools/report_render_pdf.py allows).
    provenance:   spec_hash, verification_ref, verifier/policy/protocol
                  versions, generated_at, spec_name, spec_summary, and
                  overrides: a list of {tool, precondition, reason}, which
                  jobs/report_task.py passes empty for now (overrides are in the
                  audit log; see the note there).
    citations:    lit.search.v1 hits the narrative cites.
    design:       reports/design.py design_context(): the designer's
                  description, the inputs table, the rules, the flow
                  diagram, the steps taken and the evidence numbers; None
                  outside a session.
    experiments:  finished sim.experiment.v1 results on this verification.
    figure_notes: figure id (reports/method.py figure_ids) -> the agent's
                  interpretation of that chart, number-checked like the
                  narrative.
    """
    ## Guide 10.2: 1. P1, every number in the narrative must come from the
    ## data. This is the second line of defence: the report tool already ran
    ## the same check on the same data BEFORE queueing the job, and returned
    ## a VALIDATION_ERROR the agent could act on. Here, in the worker, the
    ## InvalidInput fails the job (visible in jobs.status.v1), and no
    ## unchecked PDF is ever written.
    experiments = experiments or []
    notes = figure_notes or {}
    ensure_supported(
        {**narrative, **{f"figure {k}": v for k, v in notes.items()}},
        verification,
        simulation or {},
        (design or {}).get("evidence", {}),
        citations,
        experiments,
    )

    # 2. Charts: every figure with its caption (reports/method.py) and the
    #    agent's note; the models of each failure mode; the terms to define.
    figs = method.figures(design, simulation, experiments)
    models = method.models(verification)
    main_texts = [*narrative.values(), *notes.values(), *(f["caption"] for f in figs.values())]
    technical_texts = [
        *(m["statement"] for m in models),
        *(v.get("explanation", "") for v in verification.get("verdicts", [])),
    ]

    # 3. Fill the template.
    html = _ENV.get_template("report.html").render(
        verification=verification,
        simulation=simulation,
        narrative=narrative,
        provenance=provenance,
        citations=citations,
        figures=figs,
        notes=notes,
        models=models,
        terms=method.plain_terms(main_texts),
        technical_terms=method.glossary(technical_texts),
        assessment=plain.assessment(verification, simulation),
        check_name=plain.check_name,
        verdict_words=plain.VERDICT_WORDS,
        experiments=experiments,
        matrix=method.test_matrix(experiments, (design or {}).get("spec") or {}),
        design=design or {},
        sections=NARRATIVE_SECTIONS,
        design_sections=DESIGN_SECTIONS,
        evaluation_sections=EVALUATION_SECTIONS,
        humanize=humanize_name,
        path_label=path_label,
        change_words=change_words,
        fmt=fmt_value,
    )

    # 4. HTML -> PDF. base_url lets the HTML refer to report.css by a
    #    relative path. WeasyPrint does not run JavaScript and we give it no
    #    remote URLs, so rendering never fetches anything from the internet.
    pdf: bytes = HTML(string=html, base_url=str(_TEMPLATES)).write_pdf()
    return pdf
