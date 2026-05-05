"""Tests for verifier/paper.py — the paper-canonical truth source.

These tests guard the contract between the source paper and the
implementation:

- every FM has a PaperCondition,
- every PaperCondition has the required fields populated,
- every variable used by a condition has a paper section and a
  documented domain,
- every critical-value formula is well-formed,
- every elicitation hook references a real Roadmap docx question.

Tests do not check the *correctness* of the math here — that's the
proofs document's job. They check structural completeness so that no
PR can land that strips paper provenance.
"""

from __future__ import annotations

import re

import pytest

from verifier.paper import (
    ALL_CONDITIONS,
    CriticalValueFormula,
    PaperCondition,
    PaperVariable,
    get_condition,
    variables_used,
)


# ---------------------------------------------------------------------------
# Structural coverage
# ---------------------------------------------------------------------------


def test_all_six_fms_present() -> None:
    expected = {"FM1", "FM2", "FM3", "FM4", "FM5", "FM6"}
    assert set(ALL_CONDITIONS) == expected


@pytest.mark.parametrize("fm_id", sorted(ALL_CONDITIONS))
def test_condition_required_fields_populated(fm_id: str) -> None:
    cond = get_condition(fm_id)
    # Identity and provenance
    assert cond.fm_id == fm_id
    assert cond.name and len(cond.name) > 5
    assert cond.paper_section.startswith("§")
    assert len(cond.paper_equations) >= 1
    # Formal statement (both LaTeX and ASCII)
    assert cond.sustainability_latex
    assert cond.sustainability_ascii
    assert cond.violation_ascii
    # Variables
    assert len(cond.variables) >= 1
    # Critical values are required for every FM in Phase 1+
    assert len(cond.critical_values) >= 1
    # Plain-English layer (used by the webapp)
    assert len(cond.plain_statement) > 50
    assert len(cond.why_it_matters) > 100
    assert len(cond.real_world_signal) > 50
    # Design knobs
    assert len(cond.design_knobs) >= 1
    # Elicitation hooks
    assert len(cond.elicitation_questions) >= 1


# ---------------------------------------------------------------------------
# Variable invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fm_id", sorted(ALL_CONDITIONS))
def test_every_variable_has_paper_section(fm_id: str) -> None:
    cond = get_condition(fm_id)
    for v in cond.variables:
        assert isinstance(v, PaperVariable)
        assert v.symbol
        assert v.name
        assert v.description
        assert v.domain
        # `units` may legitimately be empty for normalized dimensionless
        # quantities (T − R, S, φ, Γ, G); description still mentions
        # the unit semantics in prose.
        assert v.paper_section.startswith("§")


def test_variables_used_consistent_with_registry() -> None:
    used = variables_used()
    # Every condition's variables must contribute to `variables_used`.
    direct: set[str] = set()
    for cond in ALL_CONDITIONS.values():
        for v in cond.variables:
            direct.add(v.symbol)
    assert used == direct


# ---------------------------------------------------------------------------
# Critical-value invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fm_id", sorted(ALL_CONDITIONS))
def test_critical_values_well_formed(fm_id: str) -> None:
    cond = get_condition(fm_id)
    parameters_seen: set[str] = set()
    for cv in cond.critical_values:
        assert isinstance(cv, CriticalValueFormula)
        assert cv.parameter
        assert cv.formula_latex
        assert cv.formula_ascii
        assert cv.direction in {">=", "<="}
        assert len(cv.explanation) > 30
        # Critical values must not duplicate parameters within one FM.
        assert cv.parameter not in parameters_seen
        parameters_seen.add(cv.parameter)


# ---------------------------------------------------------------------------
# Elicitation hooks
# ---------------------------------------------------------------------------


_ROADMAP_QID_RE = re.compile(r"^[1-5]\.\d+$|^NFR[1-7]$")


@pytest.mark.parametrize("fm_id", sorted(ALL_CONDITIONS))
def test_elicitation_questions_reference_roadmap_format(fm_id: str) -> None:
    """Every elicitation question identifier matches the Roadmap docx
    numbering format (Group.Subgroup or NFRn).
    """
    cond = get_condition(fm_id)
    for qid in cond.elicitation_questions:
        assert _ROADMAP_QID_RE.match(qid), (
            f"FM {fm_id} elicitation hook '{qid}' is not a valid "
            f"Roadmap docx question identifier (expected 'X.Y' or 'NFRn')"
        )


# ---------------------------------------------------------------------------
# NFR reweightings well-formed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fm_id", sorted(ALL_CONDITIONS))
def test_nfr_reweightings_have_explanation(fm_id: str) -> None:
    cond = get_condition(fm_id)
    for nfr_id, effect in cond.nfr_reweightings:
        assert nfr_id
        assert "NFR" in nfr_id
        assert len(effect) > 20


# ---------------------------------------------------------------------------
# Get/lookup helpers
# ---------------------------------------------------------------------------


def test_get_condition_round_trip() -> None:
    for fm_id, cond in ALL_CONDITIONS.items():
        assert get_condition(fm_id) is cond


def test_get_condition_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_condition("FM7")
