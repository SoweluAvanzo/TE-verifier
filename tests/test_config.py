"""Tests for verifier/config.py — paper-default configuration with overrides.

These tests guard:
- defaults match the values previously hardcoded in `constants.py`,
- override loading from a dict and from YAML works,
- `override_allowed=False` fields refuse override,
- every `ConfigValue` carries non-empty justification,
- shim re-exports in `verifier/constants.py` track the config defaults.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from verifier import config as cfg
from verifier import constants


# ---------------------------------------------------------------------------
# Default values lock
# ---------------------------------------------------------------------------


def test_paper_defaults_match_legacy_constants() -> None:
    """The shim values must equal the VerifierConfig defaults — this is what
    keeps existing FM modules behaviour-identical during the transition.
    """
    defaults = cfg.VerifierConfig.paper_defaults()
    assert defaults.tau_bar_ceiling == constants.TAU_BAR_VELOCITY_TRAP_CEILING
    assert defaults.rho_floor == constants.RHO_BURN_COVERAGE_FLOOR
    assert defaults.gamma_threshold == constants.GAMMA_CAPTURE_THRESHOLD
    assert defaults.gini_threshold == constants.GINI_SECONDARY_THRESHOLD
    assert (
        defaults.temptation_gap_default
        == constants.DEFAULT_TEMPTATION_GAP_NORMALIZED
    )
    assert defaults.epsilon == constants.NUMERIC_EPSILON
    assert defaults.sanction_table == constants.SANCTION_KIND_TO_S_NORMALIZED


def test_paper_defaults_specific_values() -> None:
    """Lock the specific defaults so a typo in `config.py` is caught."""
    d = cfg.VerifierConfig.paper_defaults()
    assert d.tau_bar_ceiling == 1.5
    assert d.rho_floor == 1.0
    assert d.gamma_threshold == 0.5
    assert d.gini_threshold == 0.6
    assert d.temptation_gap_default == 0.5
    assert d.epsilon == 1e-9
    assert d.sanction_table == {
        "none": 0.0,
        "warning": 0.1,
        "token_penalty": 0.5,
        "exclusion": 0.9,
        "graduated": 0.7,
        "economic": 0.8,
    }


# ---------------------------------------------------------------------------
# Provenance fields
# ---------------------------------------------------------------------------


def test_every_config_value_has_provenance() -> None:
    d = cfg.VerifierConfig.paper_defaults()
    for field_name in cfg.VerifierConfig.model_fields:
        cv = getattr(d, field_name)
        # Every justification is non-empty
        assert cv.default_justification, field_name
        assert len(cv.default_justification) > 30, field_name
        # paper_section / paper_equation may legitimately be empty
        # for calibrations the paper does not pin down — but the
        # justification field must explain it then.
        if cv.paper_section == "":
            assert (
                "calibration" in cv.default_justification.lower()
                or "paper does not" in cv.default_justification.lower()
                or "paper is qualitative" in cv.default_justification.lower()
                or "method constant" in cv.default_justification.lower()
                or "numerical" in cv.default_justification.lower()
            ), (
                f"{field_name}: empty paper_section requires justification "
                f"to mention 'calibration' or note paper silence; got: "
                f"{cv.default_justification[:80]!r}"
            )


def test_all_paper_citations_audit() -> None:
    d = cfg.VerifierConfig.paper_defaults()
    rows = d.all_paper_citations()
    keys = {row[0] for row in rows}
    assert keys == set(cfg.VerifierConfig.model_fields.keys())


# ---------------------------------------------------------------------------
# Override semantics
# ---------------------------------------------------------------------------


def test_override_allowed_field_accepts_override() -> None:
    overridden = cfg.VerifierConfig.with_overrides(
        {"tau_bar_velocity_trap_ceiling": 1.2}
    )
    assert overridden.tau_bar_ceiling == 1.2
    # The provenance reflects the override
    cv = overridden.tau_bar_velocity_trap_ceiling
    assert cv.value == 1.2
    assert "USER OVERRIDE" in cv.default_justification


def test_override_disallowed_field_raises() -> None:
    with pytest.raises(ValueError, match="override_allowed=False"):
        cfg.VerifierConfig.with_overrides({"numeric_epsilon": 1e-3})


def test_override_unknown_field_raises() -> None:
    with pytest.raises(ValueError, match="Unknown config key"):
        cfg.VerifierConfig.with_overrides({"made_up_key": 0})


def test_override_table_field() -> None:
    new_table = {
        "none": 0.0,
        "warning": 0.05,
        "token_penalty": 0.4,
        "exclusion": 1.0,
        "graduated": 0.65,
        "economic": 0.75,
    }
    overridden = cfg.VerifierConfig.with_overrides(
        {"sanction_kind_to_S_normalized": new_table}
    )
    assert overridden.sanction_table == new_table


def test_override_preserves_non_overridden_fields() -> None:
    overridden = cfg.VerifierConfig.with_overrides(
        {"tau_bar_velocity_trap_ceiling": 1.2}
    )
    # Other fields unchanged
    assert overridden.rho_floor == 1.0
    assert overridden.gamma_threshold == 0.5


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def test_from_yaml_loads_overrides(tmp_path: Path) -> None:
    yaml_path = tmp_path / "overrides.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            tau_bar_velocity_trap_ceiling: 1.2
            gamma_capture_threshold: 0.33
            """
        ).strip()
    )
    loaded = cfg.VerifierConfig.from_yaml(yaml_path)
    assert loaded.tau_bar_ceiling == 1.2
    assert loaded.gamma_threshold == 0.33
    # Non-overridden fields untouched
    assert loaded.rho_floor == 1.0


def test_from_yaml_empty_file_returns_defaults(tmp_path: Path) -> None:
    yaml_path = tmp_path / "empty.yaml"
    yaml_path.write_text("")
    loaded = cfg.VerifierConfig.from_yaml(yaml_path)
    assert loaded.tau_bar_ceiling == 1.5


def test_from_yaml_rejects_disallowed_override(tmp_path: Path) -> None:
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text("numeric_epsilon: 0.01\n")
    with pytest.raises(ValueError, match="override_allowed=False"):
        cfg.VerifierConfig.from_yaml(yaml_path)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_config_is_frozen() -> None:
    d = cfg.VerifierConfig.paper_defaults()
    # Pydantic v2 frozen models raise ValidationError on attempted assignment.
    with pytest.raises(Exception):
        d.tau_bar_velocity_trap_ceiling = cfg.ConfigValue(  # type: ignore[misc]
            value=99.0,
            paper_section="",
            paper_equation="",
            default_justification="oops",
        )
