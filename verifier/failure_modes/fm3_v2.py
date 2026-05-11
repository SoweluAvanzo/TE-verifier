"""FM3 — v2 entry point.

Phase B of the v2 migration: an FM3 implementation whose input type is
``schema.te_ir_v2.TokenEconomyV2``. Behavior is provably identical to
v1 FM3 because we adapt v2 → v1 via the shared adapter and delegate to
the existing FM3 helpers.

See ``verifier/failure_modes/_v2_compat.py`` for the adapter; see
``tests/test_fm3_v2_equivalence.py`` for the byte-equality contract.

Phase C will replace the adapter with v2-native helpers that reason
about multi-phase Functions, goods, redemptions, and events directly.
"""

from __future__ import annotations

from schema import te_ir_v2 as v2
from verifier.config import VerifierConfig
from verifier.failure_modes._v2_compat import to_v1_for_fm
from verifier.failure_modes.base import FailureMode, Verdict
from verifier.failure_modes.fm3_burn_emission import FM3BurnEmission


class FM3BurnEmissionV2(FailureMode):
    """FM3 wired against ``TokenEconomyV2``.

    Internally adapts v2 → v1 (via ``_v2_compat.to_v1_for_fm``) and
    delegates to ``FM3BurnEmission`` so the verdict text,
    counterexample structure, and recommendation narrative match v1
    byte-for-byte. Phase C will read v2 fields directly.
    """

    name = FM3BurnEmission.name
    description = FM3BurnEmission.description

    def check(
        self,
        te: v2.TokenEconomyV2,
        config: VerifierConfig | None = None,
    ) -> list[Verdict]:
        te_v1 = to_v1_for_fm(te)
        return FM3BurnEmission().check(te_v1, config=config)
