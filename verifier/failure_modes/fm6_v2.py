"""FM6 — v2 entry point.

Phase B of the v2 migration. Accepts ``TokenEconomyV2``, adapts via the
shared ``_v2_compat.to_v1_for_fm`` adapter, delegates to
``FM6GovernanceCapture``. Reads governance.rule_structure (for the Γ
centralization index), token_balance_gini (secondary signal), and
meta.nfrs.governance_maturity (for the indefinite-centralization
reframing). All preserved by the adapter.
"""

from __future__ import annotations

from schema import te_ir_v2 as v2
from verifier.config import VerifierConfig
from verifier.failure_modes._v2_compat import to_v1_for_fm
from verifier.failure_modes.base import FailureMode, Verdict
from verifier.failure_modes.fm6_governance import FM6GovernanceCapture


class FM6GovernanceCaptureV2(FailureMode):
    name = FM6GovernanceCapture.name
    description = FM6GovernanceCapture.description

    def check(
        self,
        te: v2.TokenEconomyV2,
        config: VerifierConfig | None = None,
    ) -> list[Verdict]:
        te_v1 = to_v1_for_fm(te)
        return FM6GovernanceCapture().check(te_v1, config=config)
