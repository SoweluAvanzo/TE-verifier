"""FM2 — v2 entry point.

Phase B of the v2 migration. Accepts ``TokenEconomyV2``, adapts via the
shared ``_v2_compat.to_v1_for_fm`` adapter, delegates to the existing
``FM2VelocityTrap`` so verdict / counterexample / recommendation output
is byte-identical.

See ``tests/test_fm2_v2_equivalence.py`` for the byte-equality contract.
"""

from __future__ import annotations

from schema import te_ir_v2 as v2
from verifier.config import VerifierConfig
from verifier.failure_modes._v2_compat import to_v1_for_fm
from verifier.failure_modes.base import FailureMode, Verdict
from verifier.failure_modes.fm2_velocity import FM2VelocityTrap


class FM2VelocityTrapV2(FailureMode):
    """FM2 wired against ``TokenEconomyV2``.

    Reads agent holding times, balance shares, and NFR6 circulation
    speed — all available through the shared adapter. Delegates to
    ``FM2VelocityTrap`` for the τ̄ computation and verdict assembly.
    """

    name = FM2VelocityTrap.name
    description = FM2VelocityTrap.description

    def check(
        self,
        te: v2.TokenEconomyV2,
        config: VerifierConfig | None = None,
    ) -> list[Verdict]:
        te_v1 = to_v1_for_fm(te)
        return FM2VelocityTrap().check(te_v1, config=config)
