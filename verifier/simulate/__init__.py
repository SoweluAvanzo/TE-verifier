"""Simulation layer (Sprint 1+3) — complementary to the static SMT verifier.

The static verifier answers `∃ x ∈ Box. ¬sustainability(x)` — does any
parameter assignment violate the inequality? This package answers a
different family of questions:

- **Trajectory** — what does M(t)/E(t)/B(t)/Q(t) look like under typical
  parameter values over T periods? Does it saturate, diverge, or
  oscillate? (`verifier.simulate.trajectory`)

- **Sensitivity** — which declared input dominates a FAIL verdict?
  Which lever flips it to PASS? (`verifier.simulate.sensitivity`)

- **Refinement** — synthesises both into a short user-facing block
  attached to FAIL / INCONCLUSIVE / PASS_AS_INTENDED verdicts.
  (`verifier.simulate.refinement`)

Pure Python, no new dependencies. All three modules feed the existing
``Verdict.refined_diagnosis`` field and are read by the CLI text
rendering and the webapp's verdict.js sparkline + binding-input list.
"""

from verifier.simulate.refinement import RefinedDiagnosis, refine_verdicts
from verifier.simulate.sensitivity import (
    InputElasticity,
    PairElasticity,
    compute_pairwise_sensitivity,
    compute_sensitivity,
)
from verifier.simulate.trajectory import (
    Trajectory,
    TrajectoryMetrics,
    TrajectorySample,
    simulate_token_trajectory,
)

__all__ = [
    "InputElasticity",
    "PairElasticity",
    "RefinedDiagnosis",
    "Trajectory",
    "TrajectoryMetrics",
    "TrajectorySample",
    "compute_pairwise_sensitivity",
    "compute_sensitivity",
    "refine_verdicts",
    "simulate_token_trajectory",
]
