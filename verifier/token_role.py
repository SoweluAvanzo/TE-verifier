"""Phase D4 — multi-token role derivation and per-FM applicability.

Simulator.pdf §4 ("Multi-Token Systems") prescribes role-specific
applicability rules:

- Governance tokens skip FM2 entirely (high τ̄ is the design goal,
  not a risk) and relax FM3 (ρ = 0 is acceptable).
- Reputation tokens skip FM1, FM2, FM3 (they are non-fungible
  signals, not transactional supply).
- Resource tokens carry an FM1 mitigation note (the physical anchor
  structurally limits oversupply).
- Utility tokens use the default applicability (no override).

The role is derived from the Token's existing fields (`function`,
`transferable`, `value_anchor`) — no schema change. The dispatcher
applies the table after the FMs have run, overriding per-token FM
verdicts to `NOT_APPLICABLE` (with a role-specific explanation) where
the role's skip table includes that FM. System-level FMs (FM4, FM5,
FM6) are unaffected, except that FM5's per-token-K aggregation in
the FM module continues to ignore reputation-token K (which is
typically None anyway).
"""

from __future__ import annotations

from enum import Enum

from schema import Token, TokenEconomy, TokenFunction, ValueAnchor
from verifier.failure_modes.base import Status, Verdict


class TokenRole(str, Enum):
    UTILITY = "utility"
    GOVERNANCE = "governance"
    REPUTATION = "reputation"
    RESOURCE = "resource"


def derive_token_role(token: Token) -> TokenRole:
    """Map a Token to one of the four Simulator.pdf roles.

    Decision rules (first match wins):

    1. ``function == [REPUTATION_MARKER]`` → REPUTATION
       (only-reputation token; non-fungible by design).
    2. ``GOVERNANCE_RIGHT in function`` AND every other function is
       in ``{STORE_OF_VALUE}`` (or token is non-transferable) →
       GOVERNANCE. Captures pure vote-bearing assets like MKR
       (``[governance_right, store_of_value]``) and veCRV
       (``[governance_right]`` non-transferable). A token that is
       *also* a medium_of_exchange (e.g. ETH) is **not** a governance
       token by this rule — it is a utility token that happens to
       carry governance rights.
    3. ``value_anchor == PHYSICAL_QUANTITY`` → RESOURCE
       (anchored to a measurable physical claim).
    4. otherwise → UTILITY.
    """
    if (
        len(token.function) == 1
        and TokenFunction.REPUTATION_MARKER in token.function
    ):
        return TokenRole.REPUTATION
    if TokenFunction.GOVERNANCE_RIGHT in token.function:
        other_funcs = set(token.function) - {
            TokenFunction.GOVERNANCE_RIGHT,
            TokenFunction.STORE_OF_VALUE,
        }
        # Non-transferable (stake/lock) → governance regardless of
        # what other functions are listed.
        if not token.transferable:
            return TokenRole.GOVERNANCE
        # Transferable but pure vote-bearing — only govt + (optional) SoV.
        if not other_funcs:
            return TokenRole.GOVERNANCE
    if token.value_anchor == ValueAnchor.PHYSICAL_QUANTITY:
        return TokenRole.RESOURCE
    return TokenRole.UTILITY


# ---------------------------------------------------------------------------
# Per-role applicability table (Simulator.pdf §4)
# ---------------------------------------------------------------------------


# FM IDs that the role marks NOT_APPLICABLE for the corresponding
# token-id. System-level FMs (FM4, FM5, FM6) are not in any list
# — they are evaluated at the system level regardless of per-token
# role and the existing FM-level applicability gates handle their
# null cases.
_ROLE_SKIP_TABLE: dict[TokenRole, set[str]] = {
    TokenRole.GOVERNANCE: {"FM2"},
    TokenRole.REPUTATION: {"FM1", "FM2", "FM3"},
    TokenRole.RESOURCE: set(),
    TokenRole.UTILITY: set(),
}


# FMs whose FAIL verdict is "relaxed" to PASS_AS_INTENDED for this
# role (Simulator.pdf §4 relax rules — a vote-bearing asset that
# does not self-deplete is consistent with its role).
_ROLE_RELAX_TABLE: dict[TokenRole, set[str]] = {
    TokenRole.GOVERNANCE: {"FM3"},
}


_ROLE_RELAX_REASONS: dict[TokenRole, dict[str, str]] = {
    TokenRole.GOVERNANCE: {
        "FM3": (
            "ρ = 0 (or ρ < 1) is acceptable by design — a "
            "vote-bearing asset that does not self-deplete is "
            "consistent with its role."
        ),
    },
}


# FMs whose verdict gets a role-specific *note* appended without
# changing status (Simulator §4 notes — e.g. resource tokens have FM1
# risk "structurally reduced by the physical emission anchor").
_ROLE_NOTE_TABLE: dict[TokenRole, dict[str, str]] = {
    TokenRole.RESOURCE: {
        "FM1": (
            " [Phase D4] Physical-quantity value anchor reduces FM1 "
            "risk: emission is constrained by the physical resource "
            "claim, so oversupply is structurally bounded."
        ),
    },
}


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


def apply_role_applicability(
    te: TokenEconomy, verdicts: list[Verdict]
) -> None:
    """Mutate `verdicts` in place to apply role-based applicability.

    For each per-token verdict, look up the token's role and either:
    - mark NOT_APPLICABLE (with a role-aware explanation) if the role's
      skip table includes the FM (Simulator.pdf §4 "skip");
    - reclassify a FAIL verdict to PASS_AS_INTENDED if the role's
      relax table includes the FM (Simulator.pdf §4 "relax" — a
      governance token whose ρ falls below 1.0 is consistent with its
      role, not a failure);
    - append a role-aware note to the verdict's explanation if the
      role's note table includes the FM;
    - otherwise leave the verdict untouched.

    Skips system-level verdicts (subject == "system") because role
    is per-token. The function is idempotent.
    """
    by_id = {t.id: derive_token_role(t) for t in te.tokens}
    for v in verdicts:
        if v.subject == "system" or v.subject not in by_id:
            continue
        role = by_id[v.subject]
        fm_id = v.failure_mode.split(":")[0].strip()
        if fm_id in _ROLE_SKIP_TABLE[role]:
            v.status = Status.NOT_APPLICABLE
            v.formal_condition = (
                f"N/A by token role ({role.value}; "
                f"Simulator.pdf §4 multi-token table)"
            )
            v.explanation = (
                f"Token {v.subject} has role '{role.value}'. "
                f"{fm_id} is structurally inapplicable for this role: "
                + _ROLE_SKIP_REASONS[role][fm_id]
            )
            v.counterexample = None
            v.recommendation = None
            continue
        if fm_id in _ROLE_RELAX_TABLE.get(role, set()) and v.status == Status.FAIL:
            # Simulator.pdf §4 "relax": a FAIL verdict on this FM for
            # this role is reclassified as design-intended, not a
            # failure. Fix E: drop the recommendation too — the
            # original recommendation contradicts the new headline.
            v.status = Status.PASS_AS_INTENDED
            v.explanation = (
                f"Token {v.subject} has role '{role.value}'. "
                f"The standard {fm_id} check would FAIL, but "
                f"{_ROLE_RELAX_REASONS[role][fm_id]} No design action "
                f"required for this token's role."
            )
            v.recommendation = None
            continue
        note = _ROLE_NOTE_TABLE.get(role, {}).get(fm_id)
        if note:
            v.explanation = v.explanation.rstrip() + note


_ROLE_SKIP_REASONS: dict[TokenRole, dict[str, str]] = {
    TokenRole.GOVERNANCE: {
        "FM2": (
            "high holding time τ̄ is the design goal of a governance "
            "token (long-term locking is what gives the vote weight)."
        ),
    },
    TokenRole.REPUTATION: {
        "FM1": (
            "reputation tokens are non-fungible signals, not a "
            "transactional medium — Fisher consistency does not apply."
        ),
        "FM2": (
            "reputation tokens have no transactional velocity by design."
        ),
        "FM3": (
            "reputation tokens are not a sink/source supply — burn "
            "coverage is structurally undefined."
        ),
    },
}
