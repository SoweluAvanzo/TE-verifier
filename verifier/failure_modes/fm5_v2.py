"""FM5 — v2 entry point.

Phase B of the v2 migration. Accepts ``TokenEconomyV2``, adapts via the
shared ``_v2_compat.to_v1_for_fm`` adapter, delegates to
``FM5CriticalMass``. Reads N, K (per-token), d, topology, and
topology_params (e.g. average_degree for network). All preserved by
the adapter.
"""

from __future__ import annotations

from schema import te_ir_v2 as v2
from verifier.config import VerifierConfig
from verifier.failure_modes._v2_compat import to_v1_for_fm
from verifier.failure_modes.base import FailureMode, Verdict
from verifier.failure_modes.fm5_critical_mass import FM5CriticalMass


class FM5CriticalMassV2(FailureMode):
    name = FM5CriticalMass.name
    description = FM5CriticalMass.description

    def check(
        self,
        te: v2.TokenEconomyV2,
        config: VerifierConfig | None = None,
    ) -> list[Verdict]:
        te_v1 = to_v1_for_fm(te)
        return FM5CriticalMass().check(te_v1, config=config)
