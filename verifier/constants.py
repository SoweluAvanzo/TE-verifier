"""Deprecated shim — paper-derived numeric values now live in `verifier.config`.

This module is preserved so existing FM-module imports (``from
verifier.constants import RHO_BURN_COVERAGE_FLOOR``, etc.) continue to
work without behavior change during the Phase 0 → Phase 3 transition.
The values exported here are read from the default `VerifierConfig`,
which carries paper citations and override semantics.

After Phase 3 wires `VerifierConfig` through the dispatcher, FM modules
will read thresholds from a per-run config object instead of these
module-level constants. This shim is scheduled for removal at the end
of Phase 3.

Do not add new constants here. Add them to `verifier.config.VerifierConfig`
with full paper-citation metadata.
"""

from __future__ import annotations

from verifier.config import VerifierConfig

_defaults = VerifierConfig.paper_defaults()

# FM2 — see VerifierConfig.tau_bar_velocity_trap_ceiling.
TAU_BAR_VELOCITY_TRAP_CEILING: float = _defaults.tau_bar_ceiling

# FM3 — see VerifierConfig.rho_burn_coverage_floor.
RHO_BURN_COVERAGE_FLOOR: float = _defaults.rho_floor

# FM6 — see VerifierConfig.gamma_capture_threshold.
GAMMA_CAPTURE_THRESHOLD: float = _defaults.gamma_threshold

# FM6 — see VerifierConfig.gini_secondary_threshold.
GINI_SECONDARY_THRESHOLD: float = _defaults.gini_threshold

# FM4 — see VerifierConfig.default_temptation_gap_normalized.
DEFAULT_TEMPTATION_GAP_NORMALIZED: float = _defaults.temptation_gap_default

# Numerical tolerance — see VerifierConfig.numeric_epsilon.
NUMERIC_EPSILON: float = _defaults.epsilon

# FM4 — see VerifierConfig.sanction_kind_to_S_normalized.
SANCTION_KIND_TO_S_NORMALIZED: dict[str, float] = dict(_defaults.sanction_table)
