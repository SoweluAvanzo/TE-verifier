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


def all_safe(predicates: Iterable[SafetyPredicate], state: State) -> bool:
    """Conjunctive: all predicates must hold. FM4 and FM6 emit two
    predicates whose joint satisfaction is the FM's safety condition."""
    return all(evaluate(p, state) for p in predicates)
