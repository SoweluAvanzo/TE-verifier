"""Integration tests: each of the five public case studies should produce
the verdicts predicted analytically in docs/case-studies.md.

These tests double as a regression suite for the verifier. When a future
change shifts a verdict on a famous case (e.g. Axie SLP unexpectedly
passes FM1), the test signals it loudly.
"""

from __future__ import annotations

import pytest

from tests.conftest import lookup_status, report_for


# ---------------------------------------------------------------------------
# Bitcoin — fixed-supply native asset; FM3 flagged for no burn, FM6 flagged
# on Gini secondary signal; otherwise clean.
# ---------------------------------------------------------------------------


def test_bitcoin_overall():
    r = report_for("bitcoin")
    assert r.severity.value == "fail"  # FM3 (no burn) + FM6 (Gini)


@pytest.mark.parametrize(
    "fm,subject,expected",
    [
        ("FM1", "BTC", "pass"),
        ("FM2", "BTC", "pass"),
        ("FM3", "BTC", "fail"),  # no burn at all
        ("FM4", "system", "not_applicable"),
        ("FM5", "system", "pass"),
        ("FM6", "system", "fail"),  # Gini high enough to flag
    ],
)
def test_bitcoin_per_failure_mode(fm: str, subject: str, expected: str):
    r = report_for("bitcoin")
    assert lookup_status(r, fm, subject) == expected


# ---------------------------------------------------------------------------
# Ethereum — demand-burning fee economy; structurally clean except for the
# Gini-based FM6 secondary signal.
# ---------------------------------------------------------------------------


def test_ethereum_overall():
    r = report_for("ethereum")
    # ETH should pass the supply-side modes; the only flag is FM6 on Gini.
    failures = {(v.failure_mode, v.subject) for v in r.failures()}
    # Allow FM6 system flag; everything else must NOT fail.
    for fm, subj in failures:
        assert "FM6" in fm and subj == "system", (
            f"unexpected failure: {fm} on {subj}"
        )


@pytest.mark.parametrize(
    "fm,subject,expected",
    [
        ("FM1", "ETH", "pass"),
        ("FM2", "ETH", "pass"),
        ("FM3", "ETH", "pass"),  # demand-driven burn earns its credit
        ("FM4", "system", "not_applicable"),
        ("FM5", "system", "pass"),
    ],
)
def test_ethereum_per_failure_mode(fm: str, subject: str, expected: str):
    r = report_for("ethereum")
    assert lookup_status(r, fm, subject) == expected


# ---------------------------------------------------------------------------
# MakerDAO — multi-token, wide ranges, and tier-1 conservatism produces
# multiple flags. Explicit tests document the Tier-1 sharpness trade-off.
# ---------------------------------------------------------------------------


def test_makerdao_mkr_burn_passes():
    """MKR has demand-driven burn (surplus auctions) and no scheduled
    emission, so its FM3 should pass at Tier-1."""
    r = report_for("makerdao")
    assert lookup_status(r, "FM3", "MKR") == "pass"


def test_makerdao_mkr_passes_fm1():
    """MKR has no scheduled emission, so it passes FM1."""
    r = report_for("makerdao")
    assert lookup_status(r, "FM1", "MKR") == "pass"


def test_makerdao_governance_capture_flagged_via_gini():
    """MakerDAO's nominal Γ is low (DAO votes), but token Gini concentration
    is enough to flag FM6 on the secondary signal."""
    r = report_for("makerdao")
    assert lookup_status(r, "FM6", "system") == "fail"


# ---------------------------------------------------------------------------
# Curve / veCRV — non-transferable veCRV correctly skipped for FM1/FM2;
# CRV flagged for missing burn; FM6 flagged via concentrated Gini.
# ---------------------------------------------------------------------------


def test_curve_vecrv_fm1_not_applicable():
    """veCRV is non-transferable; FM1 must be N/A, not pass/fail."""
    r = report_for("curve_vecrv")
    assert lookup_status(r, "FM1", "veCRV") == "not_applicable"


def test_curve_vecrv_fm2_not_applicable():
    r = report_for("curve_vecrv")
    assert lookup_status(r, "FM2", "veCRV") == "not_applicable"


def test_curve_crv_no_burn_flagged():
    """CRV has no protocol-level burn → FM3 must FAIL (ρ = 0)."""
    r = report_for("curve_vecrv")
    assert lookup_status(r, "FM3", "CRV") == "fail"


def test_curve_governance_capture_flagged():
    r = report_for("curve_vecrv")
    assert lookup_status(r, "FM6", "system") == "fail"


# ---------------------------------------------------------------------------
# Axie Infinity — the headline test. The verifier should predict the 2022
# collapse from public design parameters alone.
# ---------------------------------------------------------------------------


def test_axie_slp_oversupply_predicted():
    """SLP emission scales linearly with player base × constant per-event
    payout, with no demand-driven cap; FM1 must FAIL."""
    r = report_for("axie_infinity")
    assert lookup_status(r, "FM1", "SLP") == "fail"


def test_axie_slp_burn_emission_imbalance_predicted():
    """SLP burn comes only from breeding, whose demand collapses when
    growth slows. With unspecified frequency including zero, FM3 must FAIL."""
    r = report_for("axie_infinity")
    assert lookup_status(r, "FM3", "SLP") == "fail"


def test_axie_freerider_collapse_predicted():
    """Most agents are scholars (earners), few breeders (contributors);
    FM4 must FAIL on Ostrom proportionality."""
    r = report_for("axie_infinity")
    assert lookup_status(r, "FM4", "system") == "fail"


def test_axie_governance_capture_flagged():
    """Sky Mavis controls all economic levers → Γ = 1 → FM6 must FAIL."""
    r = report_for("axie_infinity")
    assert lookup_status(r, "FM6", "system") == "fail"


def test_axie_overall_severity_is_fail():
    r = report_for("axie_infinity")
    assert r.severity.value == "fail"
    # And it must flag *multiple* supply-side failure modes, not just one
    fail_names = {v.failure_mode for v in r.failures()}
    supply_side = {f for f in fail_names if "FM1" in f or "FM3" in f}
    assert len(supply_side) >= 2, (
        f"Expected at least two of FM1/FM3 to flag for Axie; got {supply_side}"
    )
