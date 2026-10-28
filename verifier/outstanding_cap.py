"""Outstanding supply cap: the Z3 terms FM1 and FM3 share.

A token with ``outstanding_supply_cap`` keeps its supply M(t) at or below
a bound C (credit limits, a debt ceiling): creation beyond it is refused.
docs/proofs/outstanding_cap.md proves what that does to the two checks:

* FM1 (Lemma 2): realized net creation per period is at most
  min(E − B, C), so the violation needs ``C > Q`` as well as ``E − B > Q``.
* FM3 (Lemma 3): in steady state the realized creation is
  E∞ = min(E, B), so burn coverage is checked against E∞.

With no cap both helpers leave the query unchanged (None / E itself).
"""

from __future__ import annotations

import z3

from schema import Token


def cap_var(solver: z3.Solver, name: str, token: Token) -> z3.ArithRef | None:
    """Declare C in the token's cap range, or return None if it has no cap."""
    cap = token.outstanding_supply_cap
    if cap is None:
        return None
    c = z3.Real(name)
    solver.add(c >= cap.min, c <= cap.max)
    return c


def steady_state_creation(
    E: z3.ArithRef, B: z3.ArithRef, cap: z3.ArithRef | None
) -> z3.ArithRef:
    """E∞: the long-run realized creation (E itself when there is no cap)."""
    if cap is None:
        return E
    return z3.If(E < B, E, B)
