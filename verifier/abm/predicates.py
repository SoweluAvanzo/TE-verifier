"""Evaluate ``SafetyPredicate`` objects against simulation state.

Decouples predicate semantics from the FM that emitted them: the ABM
sees only the (variable, operator, threshold) triple and evaluates it
mechanically. This is what makes the cadCAD bridge stable — adding
new predicates to a FM doesn't require ABM-side changes.
"""

from __future__ import annotations

from typing import Iterable

from verifier.abm.state import State, derived_variable
from verifier.safety_predicate import SafetyPredicate


_OP_FN = {
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
    ">": lambda v, t: v > t,
    "<": lambda v, t: v < t,
    "==": lambda v, t: v == t,
}


def evaluate(predicate: SafetyPredicate, state: State) -> bool:
    """Return True iff the predicate's *safety* condition holds in
    the given state. The ABM records violation as ``not evaluate(...)``."""
    value = derived_variable(state, predicate.variable)
    return _OP_FN[predicate.operator](value, predicate.threshold)


def fm_safe(predicates: Iterable[SafetyPredicate], holds: Iterable[bool]) -> bool:
    """Combine per-predicate results into the failure mode's safety condition.

    Ungrouped predicates are conjoined (FM4 and FM6 emit two predicates
    whose joint satisfaction is the condition); predicates sharing an
    ``alternative_group`` are disjoined first (FM5: well-mixed N OR network
    degree). Same rule wherever predicates are evaluated.
    """
    groups: dict[str, bool] = {}
    for p, ok in zip(predicates, holds, strict=True):
        if p.alternative_group is None:
            if not ok:
                return False
        else:
            groups[p.alternative_group] = groups.get(p.alternative_group, False) or ok
    return all(groups.values())


def all_safe(predicates: Iterable[SafetyPredicate], state: State) -> bool:
    """Return True iff the failure mode's safety condition holds (see fm_safe)."""
    preds = list(predicates)
    return fm_safe(preds, [evaluate(p, state) for p in preds])
