## =============================================================================
## te_platform/reports/charts.py — the report's charts, as SVG text
## =============================================================================
## GUIDE STEP   10.1
## PURPOSE      Small functions that take result data and return a chart as an
##              SVG string, ready to be placed inside the report HTML:
##              - verdict_summary_svg(verdicts): one bar per verdict status;
##              - violation_probability_svg(per_fm_results): Monte Carlo probability
##                of violation per failure mode (deploy vs dynamic).
## USED BY      reports/render.py (passes the SVG strings to the template).
## DEPENDS ON   matplotlib (with the "Agg" backend, see below), io.
## WHY          D14: charts drawn on the server from the same data as the
##              tables, so the PDF is deterministic and offline. SVG is a
##              vector format: sharp at any zoom and when printed, and
##              WeasyPrint embeds it directly.
## ACTIVATE     Uncomment; golden test: the SVG of a fixed input contains the
##              expected labels (exact pixel comparison would be too brittle).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the two public function
## names exactly: reports/render.py calls them.
##
## Guide 10.1
## [ ] 1. Imports at the top: io, Counter, Any; then matplotlib (as mpl),
##        selecting the "Agg" backend BEFORE pyplot is imported (see the
##        `##` note):
##          | import matplotlib as mpl
##          | mpl.use("Agg")
##          | import matplotlib.pyplot as plt
## [ ] 2. Two rcParams for deterministic SVG: "svg.hashsalt" = "te-report"
##        and "svg.fonttype" = "none".
## [ ] 3. Private helper `_to_svg(fig) -> str`: savefig into an io.StringIO
##        with format="svg", bbox_inches="tight", metadata={"Date": None};
##        plt.close(fig) to free memory; return the text.
## [ ] 4. `verdict_summary_svg(verdicts) -> str`: count the "status" values
##        (missing -> "unknown"), keep the statuses of the fixed order
##        pass, pass_as_intended, inconclusive, fail, not_applicable that
##        occur, draw a horizontal bar chart (figsize=(5, 2.2)), label the x
##        axis, invert the y axis, return _to_svg(fig).
## [ ] 5. `violation_probability_svg(per_fm_results) -> str`: keep the rows
##        that are simulated and have n_runs; one stacked horizontal bar per
##        row: n_violations_at_deployment / n_runs, then
##        n_violations_dynamic / n_runs drawn with left= the first part.
##        x limits 0..1, axis label, legend, inverted y axis.
## [ ] 6. Check: activate test_charts_contain_their_labels in
##        tests/platform_tests/test_platform_reports.py (the SVG of a fixed
##        input contains the expected labels), then
##          | uv run pytest tests/platform_tests/test_platform_reports.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import io
from collections import Counter
from typing import Any

## matplotlib can draw to a screen window or to files. On a server there is
## no screen, so we select the "Agg" backend (file output only) BEFORE pyplot
## is imported; otherwise matplotlib may try to open a window and crash.
## (`mpl` is matplotlib's customary short name; ruff expects it. ruff also
## knows that the pyplot import must follow mpl.use, so it does not flag it.)
import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from te_platform.reports.plain import check_name

## SVG text is deterministic only if matplotlib does not embed random ids or
## dates; these settings make the same input produce the same bytes (useful
## for golden tests and for content-addressed caching of reports).
plt.rcParams["svg.hashsalt"] = "te-report"
plt.rcParams["svg.fonttype"] = "none"  # keep text as text (searchable, smaller)


def _to_svg(fig: Any) -> str:
    """Return the figure as SVG text and free it."""
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", metadata={"Date": None})
    plt.close(fig)  # free memory: the worker renders many reports
    return buf.getvalue()


def verdict_summary_svg(verdicts: list[dict[str, Any]]) -> str:
    """Draw one horizontal bar per verdict status (how many checks have it)."""
    counts = Counter(v.get("status", "unknown") for v in verdicts)
    order = ["pass", "pass_as_intended", "inconclusive", "fail", "not_applicable"]
    labels = [s for s in order if counts.get(s)]
    fig, ax = plt.subplots(figsize=(5, 2.2))
    ax.barh(labels, [counts[s] for s in labels])
    ax.set_xlabel("number of failure-mode checks")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))  # counts: no 0.5 ticks
    ax.invert_yaxis()  # first status at the top, like a table
    return _to_svg(fig)


def _label(failure_mode: str, subject: str) -> str:
    """Return a check's plain name, with its token (none for system-wide checks)."""
    name = check_name(failure_mode)
    return name if subject in ("", "system") else f"{name} ({subject})"


def violation_probability_svg(per_fm_results: list[dict[str, Any]]) -> str:
    """Draw one bar per simulated failure mode: violations at deployment + later.

    Each bar is split into violations already present at deployment and
    violations that develop during operation.

    Input: `per_fm_results` of the Monte Carlo report (sim.monte_carlo.v1,
    verifier/abm). Each item has (checked against the real simulator):
    failure_mode, subject, simulated, n_runs, p_violation,
    n_violations_at_deployment, n_violations_dynamic. The two shares are
    counts divided by n_runs; together they add up to p_violation.
    Failure modes the triage skipped (simulated == False) are left out.
    """
    rows = [x for x in per_fm_results if x.get("simulated") and x.get("n_runs")]
    names = [_label(x["failure_mode"], x.get("subject", "")) for x in rows]
    deploy = [x["n_violations_at_deployment"] / x["n_runs"] for x in rows]
    dynamic = [x["n_violations_dynamic"] / x["n_runs"] for x in rows]
    fig, ax = plt.subplots(figsize=(6, 0.4 * len(names) + 1))
    ax.barh(names, deploy, label="already at launch")
    ax.barh(names, dynamic, left=deploy, label="appeared later")
    ax.set_xlim(0, 1)
    ax.set_xlabel("share of simulated runs in which the problem appeared")
    # Below the axes: a long bar reaches the right edge, and a legend there would hide it.
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=2, frameon=False)
    ax.invert_yaxis()
    return _to_svg(fig)


## Experiments (tool sim.experiment.v1, te_platform/experiments.py). The
## variants are the series; their names are the legend, so the chart reads
## like the variants table next to it.
def experiment_supply_svg(experiment: dict[str, Any], token: str) -> str:
    """Draw tokens in circulation over time, one line per variant."""
    fig, ax = plt.subplots(figsize=(6, 2.4))
    for v in experiment.get("variants", []):
        points = (v.get("trajectories") or {}).get(token) or []
        ax.plot(
            [p["t"] for p in points],
            [p["M"] for p in points],
            label=str(v["name"]).replace("_", " "),
        )
    ax.set_xlabel("week")
    ax.set_ylabel(f"{token} in circulation")
    ax.set_ylim(bottom=0)  # a count of tokens: never below zero
    ax.legend(fontsize=7, loc="best")
    return _to_svg(fig)


def experiment_violation_svg(experiment: dict[str, Any]) -> str:
    """Draw P(violation) per failure mode, one bar group per failure mode, a bar per variant.

    A variant whose triage decided a failure mode (not simulated) has no bar.
    """
    variants = experiment.get("variants", [])
    keys: list[str] = []
    for v in variants:
        for r in v.get("monte_carlo", []):
            key = _label(r["failure_mode"], r["subject"])
            if r.get("simulated") and key not in keys:
                keys.append(key)
    fig, ax = plt.subplots(figsize=(6, 0.5 * max(len(keys), 1) * max(len(variants), 1) / 2 + 1.2))
    height = 0.8 / max(len(variants), 1)
    for i, v in enumerate(variants):
        p = {
            _label(r["failure_mode"], r["subject"]): r["p_violation"]
            for r in v.get("monte_carlo", [])
            if r.get("simulated")
        }
        ys = [k + i * height for k in range(len(keys)) if keys[k] in p]
        ax.barh(ys, [p[k] for k in keys if k in p], height=height, label=v["name"])
    ax.set_yticks([k + 0.4 - height / 2 for k in range(len(keys))], keys)
    ax.set_xlim(0, 1)
    ax.set_xlabel("share of simulated runs in which the problem appeared")
    ax.legend(fontsize=7, loc="lower right")
    ax.invert_yaxis()
    return _to_svg(fig)
