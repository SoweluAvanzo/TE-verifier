"""Dynamic regime-switch evaluation for the ABM trajectory.

The static verifier in ``verifier/conditions.py`` evaluates each
``Condition`` statically against the IR's parameter box (returns
ALWAYS / EVER / NEVER). For the ABM we need a *concrete* truth value
given the current period's state — at t=5, with M=12345, does the
condition `M >= 10000` hold? That's what this module computes.

Used to plumb ``Rule.regimes`` into the per-period rate calculation:
once the predicate fires, the rule's function shape switches from the
base ``Rule.function`` to ``regime.function`` for the remainder of the
trajectory. Sticky switches mirror real-world halvings and supply
caps — once activated, the regime stays activated.
"""

from __future__ import annotations

from typing import Any

from schema import (
    Condition,
    EventOccurrence,
    FunctionShape,
    ThresholdCondition,
    ThresholdOp,
    ThresholdVar,
    TimeWindow,
)


def _resolve_var(var: ThresholdVar, state: dict[str, Any]) -> float | None:
    """Map a ThresholdVar enum onto the current state's scalar value."""
    if var == ThresholdVar.T:
        return float(state.get("t", 0))
    if var == ThresholdVar.M:
        # Aggregate over all tokens — the IR allows per-token thresholds
        # via duplicate rules, but the schema's ThresholdVar.M is system-
        # wide. Sum across tokens for the most conservative reading.
        tokens = state.get("tokens", {}) or {}
        return float(sum(tok.get("M", 0.0) for tok in tokens.values()))
    if var == ThresholdVar.Q:
        return float(state.get("Q", 0.0))
    if var == ThresholdVar.N:
        return float(state.get("N", 0.0))
    if var == ThresholdVar.K:
        ks = state.get("K", {}) or {}
        if isinstance(ks, dict):
            return float(max(ks.values()) if ks else 0.0)
        return float(ks)
    return None


def _compare(op: ThresholdOp, lhs: float, rhs: float) -> bool:
    if op == ThresholdOp.GT:  return lhs > rhs
    if op == ThresholdOp.GTE: return lhs >= rhs
    if op == ThresholdOp.LT:  return lhs < rhs
    if op == ThresholdOp.LTE: return lhs <= rhs
    if op == ThresholdOp.EQ:  return lhs == rhs
    return False


def is_condition_active(
    condition: Condition,
    state: dict[str, Any],
) -> bool:
    """True iff the structured condition currently holds against the
    period state. Conservative on unknown / unresolvable predicates —
    returns False (we'd rather miss a regime than spuriously trigger it)."""
    if isinstance(condition, ThresholdCondition):
        lhs = _resolve_var(condition.var, state)
        if lhs is None:
            return False
        return _compare(condition.op, lhs, condition.value)
    if isinstance(condition, TimeWindow):
        t = float(state.get("t", 0))
        if t < condition.start_period:
            return False
        if condition.end_period is not None and t > condition.end_period:
            return False
        return True
    if isinstance(condition, EventOccurrence):
        # Phase-H preferred path: event_id resolves against the realized
        # event firings tracked per period in state["events_realized"].
        if condition.event_id is not None:
            realized = state.get("events_realized", {}) or {}
            return float(realized.get(condition.event_id, 0.0)) > 0.0
        # Legacy fallback: event "fires" when the named source token's
        # realized burn is non-zero this period.
        tokens = state.get("tokens", {}) or {}
        src = tokens.get(condition.source_token)
        if src is None:
            return False
        return float(src.get("B", 0.0)) > 0.0
    return False


def active_function_for_rule(
    rule,
    state: dict[str, Any],
    activated_regime_idx: dict[int, int] | None = None,
    rule_id: int | None = None,
) -> FunctionShape:
    """Return the FunctionShape that should drive this rule's rate this
    period. Walks the rule's regimes in declaration order; the first
    regime whose predicate has fired (now or earlier — sticky) wins.

    ``activated_regime_idx`` is an optional cache keyed by rule id —
    when a regime fires for the first time we remember its index so the
    switch stays active for the remainder of the trajectory even if
    the predicate stops holding (e.g. a TimeWindow that closes).
    """
    regimes = getattr(rule, "regimes", []) or []
    if not regimes:
        return rule.function

    # Sticky lookup — if a regime already fired for this rule, use it.
    if (
        activated_regime_idx is not None
        and rule_id is not None
        and rule_id in activated_regime_idx
    ):
        idx = activated_regime_idx[rule_id]
        if 0 <= idx < len(regimes):
            return regimes[idx].function

    # Otherwise scan for the first newly-active regime.
    for idx, regime in enumerate(regimes):
        if is_condition_active(regime.predicate, state):
            if activated_regime_idx is not None and rule_id is not None:
                activated_regime_idx[rule_id] = idx
            return regime.function

    return rule.function
