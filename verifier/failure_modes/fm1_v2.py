"""FM1 — v2 entry point.

Phase B of the v2 migration. Accepts ``TokenEconomyV2``, adapts via the
shared ``_v2_compat.to_v1_for_fm`` adapter, delegates to the existing
``FM1Oversupply`` so verdict / counterexample / recommendation
output is byte-identical.

See ``tests/test_fm1_v2_equivalence.py`` for the byte-equality contract.
"""

from __future__ import annotations

from schema import te_ir_v2 as v2
from verifier.config import VerifierConfig
from verifier.failure_modes._v2_compat import to_v1_for_fm
from verifier.failure_modes.base import FailureMode, Verdict
from verifier.failure_modes.fm1_oversupply import FM1Oversupply


class FM1OversupplyV2(FailureMode):
    """FM1 wired against ``TokenEconomyV2``.

    Internally adapts v2 → v1 and delegates to ``FM1Oversupply``.
    Reads exactly the v1 fields FM1 needs (token emission/burn rules,
    cross-token flows, participants.expected_Q). Goods, redemptions,
    and events are dropped by the adapter — FM1 doesn't use them.
    """

    name = FM1Oversupply.name
    description = FM1Oversupply.description

    def check(
        self,
        te: v2.TokenEconomyV2,
        config: VerifierConfig | None = None,
    ) -> list[Verdict]:
        te_v1 = to_v1_for_fm(te)
        return FM1Oversupply().check(te_v1, config=config)
