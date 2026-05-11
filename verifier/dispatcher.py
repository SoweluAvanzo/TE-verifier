"""Dispatcher — runs all registered failure-mode checks and aggregates results."""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from schema import TokenEconomy
from verifier.config import VerifierConfig
from verifier.counterexample import prettify_verdicts
from verifier.elicitation import CoherenceIssue, coherence_violations
from verifier.failure_modes import ALL_FAILURE_MODES
from verifier.failure_modes.base import FailureMode, Status, Verdict
from verifier.risk import OverallRiskScore, attach_risk_levels, compute_overall_score
from verifier.simulate import refine_verdicts
from verifier.token_role import apply_role_applicability


class Severity(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


class Report(BaseModel):
    """Aggregated verifier output for a single TokenEconomy."""

    model_config = ConfigDict(extra="forbid")

    te_name: str
    verdicts: list[Verdict] = Field(default_factory=list)
    severity: Severity
    summary: dict[str, int] = Field(default_factory=dict)
    coherence_issues: list[CoherenceIssue] = Field(default_factory=list)
    overall_risk: OverallRiskScore | None = None

    def failures(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.status == Status.FAIL]

    def passes(self) -> list[Verdict]:
        return [
            v
            for v in self.verdicts
            if v.status in (Status.PASS, Status.PASS_AS_INTENDED)
        ]

    def by_failure_mode(self) -> dict[str, list[Verdict]]:
        out: dict[str, list[Verdict]] = {}
        for v in self.verdicts:
            out.setdefault(v.failure_mode, []).append(v)
        return out

    def render_text(self) -> str:
        """Plain-text rendering suitable for CLI output."""
        lines = [f"# Verification report for: {self.te_name}", ""]
        lines.append(f"Severity: {self.severity.value}")
        lines.append(
            "  "
            + "  ".join(
                f"{k}={v}" for k, v in self.summary.items() if v > 0
            )
        )
        lines.append("")
        if self.coherence_issues:
            lines.append("## Coherence issues")
            for ci in self.coherence_issues:
                lines.append(f"  [{ci.severity}] {ci.location}")
                lines.append(f"    {ci.message}")
                lines.append(f"    → {ci.suggestion}")
            lines.append("")
        for fm_name, group in self.by_failure_mode().items():
            lines.append(f"## {fm_name}")
            for v in group:
                lines.append(f"  · subject: {v.subject}")
                lines.append(f"    status: {v.status.value}")
                lines.append(f"    condition: {v.formal_condition}")
                # Wrap long explanations to ~78 cols
                expl = v.explanation.replace("\n", " ")
                lines.append(f"    explanation: {expl}")
                if v.counterexample is not None:
                    pv = v.counterexample.parameter_values
                    short_pv = ", ".join(
                        f"{k}={val:.4g}"
                        for k, val in list(pv.items())[:6]
                    )
                    lines.append(f"    counterexample params: {short_pv}")
                    if v.counterexample.narrative:
                        lines.append(
                            f"    counterexample: {v.counterexample.narrative}"
                        )
                if v.critical_values:
                    lines.append("    critical values:")
                    for cv in v.critical_values:
                        lines.append(
                            f"      - {cv.parameter} {cv.direction} "
                            f"{cv.value:.4g}  ({cv.formula})"
                        )
                if v.recommendation is not None:
                    rec = v.recommendation
                    lines.append(
                        f"    recommendation: {rec.parameter} {rec.direction} "
                        f"{rec.safe_threshold:.4g}"
                    )
                    lines.append(f"      → {rec.narrative}")
                    if rec.mechanism_mappings:
                        lines.append("      mechanism options:")
                        for m in rec.mechanism_mappings:
                            lines.append(f"        · {m}")
                if v.suggestions:
                    lines.append("    suggestions:")
                    for s in v.suggestions:
                        lines.append(f"      - {s}")
                if v.swept_fields:
                    lines.append(
                        f"    swept (range search): "
                        f"{', '.join(v.swept_fields[:3])}"
                        + (f" +{len(v.swept_fields) - 3} more"
                           if len(v.swept_fields) > 3 else "")
                    )
                lines.append("")
        return "\n".join(lines)


def verify(
    te: TokenEconomy,
    *,
    failure_modes: Iterable[type[FailureMode]] | None = None,
    config: VerifierConfig | None = None,
) -> Report:
    """Run all registered failure-mode checks on `te` and return a Report.

    `failure_modes` lets callers (notably tests) restrict the set of checks
    run — useful for unit testing one FM at a time.

    `config` overrides paper defaults; when None, `VerifierConfig.paper_defaults()`
    is used. Phase 5: the dispatcher consults `config.archetype_skip_table`
    to mark FMs as N/A based on the declared archetype before running them.
    """
    cfg = config or VerifierConfig.paper_defaults()
    fms = list(failure_modes) if failure_modes is not None else list(ALL_FAILURE_MODES)
    archetype_skip: set[str] = set(
        cfg.archetype_skip_table.get(te.meta.archetype.value, [])
    )
    verdicts: list[Verdict] = []
    for fm_cls in fms:
        fm = fm_cls()
        # Archetype-based N/A: skip FMs the archetype declares
        # structurally inapplicable. Construct a stub Verdict so the
        # report still mentions the FM was considered.
        fm_id_match = fm.name.split(":")[0].strip()  # "FM4"
        if fm_id_match in archetype_skip:
            verdicts.append(
                Verdict(
                    failure_mode=fm.name,
                    subject="system",
                    status=Status.NOT_APPLICABLE,
                    formal_condition=f"N/A by archetype ({te.meta.archetype.value})",
                    explanation=(
                        f"{fm.name} is marked structurally inapplicable for "
                        f"archetype '{te.meta.archetype.value}' in the active "
                        f"VerifierConfig. The default archetype_fm_applicability "
                        f"table can be overridden per run."
                    ),
                )
            )
            continue
        # Pass config through; FMs that don't consume it ignore the kwarg.
        try:
            verdicts.extend(fm.check(te, config=cfg))
        except TypeError:
            # Back-compat for FMs that haven't migrated to config-aware check()
            verdicts.extend(fm.check(te))

    # Phase D4 — role-based applicability override BEFORE summarising.
    # A token's role (governance / reputation / resource / utility)
    # may make some per-token FM verdicts structurally inapplicable.
    apply_role_applicability(te, verdicts)
    # P1 — rewrite Z3 internal variable names in counterexamples to
    # IR-path-style names users can decode. Drops the precompute
    # duplicates from the proportional-coupling helper.
    prettify_verdicts(verdicts)
    summary = _summarize(verdicts)
    # Phase D — attach risk_level to each verdict (midpoint evaluation)
    # *before* coherence so the verdict-aware C7 check has data.
    attach_risk_levels(te, verdicts)
    # Sprint 1+3 — attach the dynamic refined-diagnosis block
    # (trajectory + sensitivity) to actionable verdicts. Skipped on
    # PASS / NOT_APPLICABLE.
    refine_verdicts(te, verdicts)
    issues = coherence_violations(te, verdicts=verdicts)
    # Coherence errors escalate the report to FAIL severity even if
    # every FM individually passed — the IR is internally inconsistent.
    severity = _severity_of(summary)
    if any(i.severity == "error" for i in issues) and severity == Severity.OK:
        severity = Severity.WARN
    overall = compute_overall_score(verdicts, issues)
    return Report(
        te_name=te.meta.name,
        verdicts=verdicts,
        severity=severity,
        summary=summary,
        coherence_issues=issues,
        overall_risk=overall,
    )


def _summarize(verdicts: list[Verdict]) -> dict[str, int]:
    counter: Counter[str] = Counter(v.status.value for v in verdicts)
    return dict(counter)


def _severity_of(summary: dict[str, int]) -> Severity:
    if summary.get(Status.FAIL.value, 0) > 0:
        return Severity.FAIL
    if summary.get(Status.INCONCLUSIVE.value, 0) > 0:
        return Severity.WARN
    return Severity.OK
