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
# Bitcoin — fixed-supply native asset. With the supply_cap schedule
# modifier declared on the emission rule, FM3 is `pass_as_intended`
# (capped supply replaces the need for burn). FM6 flagged on the Gini
# secondary signal (top 0.01% holds ~50% of supply).
# ---------------------------------------------------------------------------


def test_bitcoin_overall():
    r = report_for("bitcoin")
    assert r.severity.value == "fail"  # FM6 (Gini) drives severity


@pytest.mark.parametrize(
    "fm,subject,expected",
    [
        ("FM1", "BTC", "pass"),
        ("FM2", "BTC", "pass"),
        # FM3 is `pass_as_intended` — supply is capped via Rule.schedule.
        # Sustainability becomes an FM1 question (does Q absorb the
        # bounded supply?) which it does.
        ("FM3", "BTC", "pass_as_intended"),
        ("FM4", "system", "not_applicable"),
        ("FM5", "system", "pass"),
        ("FM6", "system", "fail"),  # Gini 0.85-0.95 in mid-2026 calibration
    ],
)
def test_bitcoin_per_failure_mode(fm: str, subject: str, expected: str):
    r = report_for("bitcoin")
    assert lookup_status(r, fm, subject) == expected


# ---------------------------------------------------------------------------
# Ethereum — post-Merge, post-Dencun (Mar 2024). EIP-1559 burn dropped
# sharply once L2s migrated to blobs, so weekly burn (~500-50000 ETH) is
# now usually below issuance (~13000-17500 ETH/week). The verifier
# correctly flags FM3 under this calibration; this is a real concern,
# not a verifier artifact. FM6 still flags on Gini.
# ---------------------------------------------------------------------------


def test_ethereum_overall():
    r = report_for("ethereum")
    failures = {(v.failure_mode, v.subject) for v in r.failures()}
    # Post-Dencun: FM3 (burn coverage) and FM6 (Gini) both flag.
    allowed = {"FM3", "FM6"}
    for fm, _subj in failures:
        head = fm.split(":")[0].strip()
        assert head in allowed, f"unexpected failure: {fm}"


@pytest.mark.parametrize(
    "fm,subject,expected",
    [
        ("FM1", "ETH", "pass"),
        ("FM2", "ETH", "pass"),
        # Post-Dencun: burn is structurally below issuance most weeks.
        ("FM3", "ETH", "fail"),
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


def test_curve_crv_supply_cap_intended():
    """CRV has no protocol-level burn but declares a supply_cap (3.03B)
    via Rule.schedule, so FM3 resolves to pass_as_intended — supply
    stability is achieved by termination, not by burn."""
    r = report_for("curve_vecrv")
    assert lookup_status(r, "FM3", "CRV") == "pass_as_intended"


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


# ---------------------------------------------------------------------------
# Catalog-style (Phase-H) case studies — community economies authored
# through the events catalog, the webapp's native output format. These
# were historically EXCLUDED from the regression suite, which is how
# the FM4 catalog-blindness bug survived: every spec below is a
# contribution-reward economy, and all of them silently received
# FM4 = not_applicable until the resolver migration.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fm,subject,expected",
    [
        ("FM1", "ROCCA", "fail"),
        ("FM1", "BUONO", "fail"),
        ("FM2", "ROCCA", "pass"),
        ("FM2", "BUONO", "pass"),
        ("FM3", "ROCCA", "fail"),
        ("FM3", "BUONO", "fail"),
        # Volunteers earn ROCCA through verified behavioral events →
        # FM4 applies (and fails: contributor share vs d/K).
        ("FM4", "system", "fail"),
        ("FM5", "system", "pass"),
        ("FM6", "system", "fail"),
    ],
)
def test_cascina_per_failure_mode(fm: str, subject: str, expected: str):
    r = report_for("cascina_roccafranca")
    assert lookup_status(r, fm, subject) == expected


@pytest.mark.parametrize(
    "fm,subject,expected",
    [
        ("FM1", "HOUR", "fail"),
        ("FM2", "HOUR", "pass"),
        ("FM3", "HOUR", "fail"),
        # HOUR is earned via behavioral service delivery with peer
        # verification — the textbook FM4-applicable economy.
        ("FM4", "system", "fail"),
        ("FM5", "system", "pass"),
        ("FM6", "system", "pass"),
    ],
)
def test_time_bank_per_failure_mode(fm: str, subject: str, expected: str):
    r = report_for("time_bank")
    assert lookup_status(r, fm, subject) == expected


def test_curve_dsl_matches_legacy_curve_verdicts():
    """curve_vecrv_dsl is the DSL/catalog re-authoring of curve_vecrv;
    the two forms must agree verdict-for-verdict (dual-form invariant
    on a real case study)."""
    r_legacy = report_for("curve_vecrv")
    r_dsl = report_for("curve_vecrv_dsl")
    legacy = {(v.failure_mode, v.subject): v.status for v in r_legacy.verdicts}
    dsl = {(v.failure_mode, v.subject): v.status for v in r_dsl.verdicts}
    assert legacy == dsl
