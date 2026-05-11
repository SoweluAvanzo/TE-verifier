"""Minimal verifier output — point-5 redesign tests.

The minimal API exposes only what the verifier can honestly guarantee
at the formal layer: reachability of violation, reachability of
satisfaction (heuristic in Phase B; formal in Phase C), structural
classification, and a single threshold number. No narrative, no NFR
reframings, no role gating.

These tests pin:

1. Per-status mapping (PASS → SOUND, FAIL → FRAGILE/BROKEN/INCONCLUSIVE
   depending on satisfaction reachability, PASS_AS_INTENDED →
   FRAGILE, NOT_APPLICABLE preserves).
2. Threshold extraction from the existing recommendation field.
3. Witness extraction from the existing counterexample.
4. The five case-study outputs (sanity-pin the structural distribution).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import load_te
from verifier.minimal import (
    ReachabilityVerdict,
    StructuralStatus,
    _classify,
    minimal_report_text,
    minimal_verdicts,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------


def test_classify_sound_when_violation_unreachable() -> None:
    """Violation false → SOUND regardless of satisfaction."""
    assert _classify("false", "true", "pass") == StructuralStatus.SOUND
    assert _classify("false", "false", "pass") == StructuralStatus.SOUND


def test_classify_fragile_when_both_reachable() -> None:
    assert _classify("true", "true", "fail") == StructuralStatus.FRAGILE


def test_classify_broken_when_satisfaction_unreachable() -> None:
    assert _classify("true", "false", "fail") == StructuralStatus.BROKEN


def test_classify_not_applicable_preserves() -> None:
    assert (
        _classify("unknown", "unknown", "not_applicable")
        == StructuralStatus.NOT_APPLICABLE
    )


def test_classify_inconclusive_when_any_unknown() -> None:
    assert _classify("true", "unknown", "fail") == StructuralStatus.INCONCLUSIVE
    assert _classify("unknown", "true", "inconclusive") == StructuralStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# End-to-end on a tiny TE
# ---------------------------------------------------------------------------


def test_minimal_verdicts_on_a_passing_design() -> None:
    """A clean design (Bitcoin) produces several SOUND verdicts."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    verdicts = minimal_verdicts(te)
    by_fm = {v.failure_mode: v for v in verdicts}

    # FM1 BTC is currently PASS → SOUND
    assert by_fm["FM1"].structural_status == StructuralStatus.SOUND
    assert by_fm["FM1"].violation_reachable == "false"

    # FM5 system PASS → SOUND
    assert by_fm["FM5"].structural_status == StructuralStatus.SOUND

    # FM4 N/A for Bitcoin
    assert by_fm["FM4"].structural_status == StructuralStatus.NOT_APPLICABLE


def test_minimal_verdicts_on_a_failing_design() -> None:
    """Axie's FM1 SLP is the canonical FAIL — must report violation
    reachable and a witness."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    verdicts = minimal_verdicts(te)

    fm1_slp = next(
        v for v in verdicts if v.failure_mode == "FM1" and v.subject == "SLP"
    )
    assert fm1_slp.violation_reachable == "true"
    assert fm1_slp.witness is not None
    assert "SLP__Q" in fm1_slp.witness or len(fm1_slp.witness) > 0


def test_minimal_verdicts_carry_threshold_when_recommended() -> None:
    """When the underlying FM produced a NumericRecommendation, the
    minimal output carries the safe_threshold value."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    verdicts = minimal_verdicts(te)

    # FM1 SLP has a recommendation (net_emission ≤ Q)
    fm1_slp = next(
        v for v in verdicts if v.failure_mode == "FM1" and v.subject == "SLP"
    )
    assert fm1_slp.minimum_param_shift is not None
    assert len(fm1_slp.minimum_param_shift) == 1
    # Single parameter, single number — no narrative.


def test_minimal_verdicts_carry_no_threshold_when_passing() -> None:
    """A passing FM produces no threshold (nothing to fix)."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    verdicts = minimal_verdicts(te)
    fm5 = next(v for v in verdicts if v.failure_mode == "FM5")
    assert fm5.violation_reachable == "false"
    assert fm5.minimum_param_shift is None
    assert fm5.witness is None


def test_minimal_verdicts_emit_one_per_subject() -> None:
    """Same count as the standard verify() report."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    from verifier.dispatcher import verify

    standard = verify(te).verdicts
    minimal = minimal_verdicts(te)
    assert len(minimal) == len(standard)


# ---------------------------------------------------------------------------
# Structural classification on the five case studies — sanity pins
# ---------------------------------------------------------------------------


def test_axie_has_at_least_one_inconclusive_or_fragile() -> None:
    """Axie's design is structurally broken in multiple FMs — the
    minimal output should reflect this with a substantial number of
    non-SOUND verdicts."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    verdicts = minimal_verdicts(te)
    non_sound = [
        v
        for v in verdicts
        if v.structural_status
        not in (StructuralStatus.SOUND, StructuralStatus.NOT_APPLICABLE)
    ]
    assert len(non_sound) >= 4, (
        f"Axie should have ≥4 problematic FMs; got {len(non_sound)}: "
        f"{[(v.failure_mode, v.subject, v.structural_status.value) for v in non_sound]}"
    )


def test_bitcoin_passes_most_fms() -> None:
    """Bitcoin should be SOUND on FM1, FM2, FM5 (the cleanly passing ones)."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    verdicts = minimal_verdicts(te)
    by_fm = {v.failure_mode: v for v in verdicts}
    assert by_fm["FM1"].structural_status == StructuralStatus.SOUND
    assert by_fm["FM2"].structural_status == StructuralStatus.SOUND
    assert by_fm["FM5"].structural_status == StructuralStatus.SOUND


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_minimal_report_text_is_compact() -> None:
    """The rendered table is one line per verdict + 2 header lines.
    No multi-paragraph narrative."""
    te = load_te(EXAMPLES_DIR / "curve_vecrv.yaml")
    verdicts = minimal_verdicts(te)
    text = minimal_report_text(verdicts)
    lines = text.splitlines()
    # Header + separator + one line per verdict
    assert len(lines) == 2 + len(verdicts)
    # Each line short enough to read at a glance
    for line in lines:
        assert len(line) < 120, f"line too long: {line!r}"


def test_minimal_output_drops_pass_as_intended_label() -> None:
    """The minimal output uses StructuralStatus, not the multi-valued
    pass_as_intended / not_applicable / inconclusive mix. The five
    statuses are the only labels."""
    valid = {s.value for s in StructuralStatus}
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    verdicts = minimal_verdicts(te)
    for v in verdicts:
        assert v.structural_status.value in valid


# ---------------------------------------------------------------------------
# ABM-handoff shape
# ---------------------------------------------------------------------------


def test_minimal_verdicts_are_json_serializable() -> None:
    """The minimal output is the ABM handoff format — it must
    serialize to plain JSON with no Python-specific objects."""
    import json

    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    verdicts = minimal_verdicts(te)
    payload = [v.model_dump(mode="json") for v in verdicts]
    # Must round-trip through json.dumps without TypeError
    serialized = json.dumps(payload)
    parsed = json.loads(serialized)
    assert len(parsed) == len(verdicts)
    # First entry has the contract fields
    sample = parsed[0]
    assert "failure_mode" in sample
    assert "subject" in sample
    assert "violation_reachable" in sample
    assert "satisfaction_reachable" in sample
    assert "structural_status" in sample
