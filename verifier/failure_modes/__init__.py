"""Failure-mode evaluators.

Each module implements one of the six failure modes from §3 of the paper.
The dispatcher discovers them via the ALL_FAILURE_MODES registry below;
adding a new failure mode is a one-line registration here plus a new module.
"""

from verifier.failure_modes.base import (
    Counterexample,
    FailureMode,
    Status,
    Verdict,
)
from verifier.failure_modes.fm1_oversupply import FM1Oversupply
from verifier.failure_modes.fm2_velocity import FM2VelocityTrap
from verifier.failure_modes.fm3_burn_emission import FM3BurnEmission
from verifier.failure_modes.fm4_freerider import FM4FreeRider
from verifier.failure_modes.fm5_critical_mass import FM5CriticalMass
from verifier.failure_modes.fm6_governance import FM6GovernanceCapture

ALL_FAILURE_MODES: list[type[FailureMode]] = [
    FM1Oversupply,
    FM2VelocityTrap,
    FM3BurnEmission,
    FM4FreeRider,
    FM5CriticalMass,
    FM6GovernanceCapture,
]

__all__ = [
    "ALL_FAILURE_MODES",
    "Counterexample",
    "FailureMode",
    "FM1Oversupply",
    "FM2VelocityTrap",
    "FM3BurnEmission",
    "FM4FreeRider",
    "FM5CriticalMass",
    "FM6GovernanceCapture",
    "Status",
    "Verdict",
]
