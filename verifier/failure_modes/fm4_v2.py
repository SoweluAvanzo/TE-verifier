"""FM4 — v2 entry point.

Phase B of the v2 migration. Accepts ``TokenEconomyV2``, adapts via the
shared ``_v2_compat.to_v1_for_fm`` adapter, delegates to
``FM4FreeRider``. Reads agent roles, monitoring/sanction governance,
per-token offer variety and contribution-verification, value_anchor
(for stablecoin exemption), and the (verification, redemption)
temptation-gap derivation. All preserved by the adapter.
"""

from __future__ import annotations

from schema import te_ir_v2 as v2
from verifier.config import VerifierConfig
from verifier.failure_modes._v2_compat import to_v1_for_fm
from verifier.failure_modes.base import FailureMode, Verdict
from verifier.failure_modes.fm4_freerider import FM4FreeRider


class FM4FreeRiderV2(FailureMode):
    name = FM4FreeRider.name
    description = FM4FreeRider.description

    def check(
        self,
        te: v2.TokenEconomyV2,
        config: VerifierConfig | None = None,
    ) -> list[Verdict]:
        te_v1 = to_v1_for_fm(te)
        return FM4FreeRider().check(te_v1, config=config)
