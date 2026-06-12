"""Phase B2+B3 — structured Condition evaluation.

A `Rule.trigger.conditions` list is a conjunction (AND) of structured
predicates. Each predicate evaluates to one of three states over the
declared box:

    ALWAYS — the predicate holds for every assignment in the box
    EVER   — the predicate holds for at least one assignment
    NEVER  — the predicate holds for no assignment

The verifier uses these states to gate per-rule contributions to E
and B with **side-correct conservatism** (see
`docs/proofs/conditional_rules.md`):

- An emission rule contributes if its conditions are NOT NEVER, i.e.
  if the rule may fire at least once. Including the rule's full rate
  in that case over-counts emission, which makes FM1/FM3 sustainability
  *harder* to prove — the verifier remains sound.

- A burn rule contributes only if its conditions are ALWAYS-satisfied.
  Including only when guaranteed under-counts burn, which makes FM3
  *harder* to prove — sound on the burn side.

Conjunction (multiple conditions on one rule):

    ALWAYS = all subconditions ALWAYS
    NEVER  = any subcondition NEVER
    EVER   = otherwise

The evaluator is **purely static** (no Z3) — its result feeds into
the existing Z3 encoding by deciding whether to add a rule's term to
the symbolic E/B sum at all. This keeps the Z3 query simple and
preserves the existential semantics of the SMT layer.
"""

from __future__ import annotations

from enum import Enum

from schema import (
    Condition,
    EventOccurrence,
    ThresholdCondition,
    ThresholdOp,
    ThresholdVar,
    TimeWindow,
    Token,
    TokenEconomy,
)


# Default verification horizon (matches verifier.asymptotic). Time-window
# and `t`-threshold conditions are evaluated against [0, _HORIZON].
_HORIZON = 52.0


class ConditionStatus(str, Enum):
    ALWAYS = "always"
    EVER = "ever"
    NEVER = "never"


# ---------------------------------------------------------------------------
# Variable bounds
# ---------------------------------------------------------------------------


def _var_bounds(var: ThresholdVar, te: TokenEconomy) -> tuple[float, float] | None:
    """Numerical bounds for `var` derived from the IR.

    Returns (lo, hi) or None when the variable is unbounded (or
    unrecognized). None forces the conservative ConditionStatus.EVER
    in `_eval_threshold` — the verifier prefers including a rule it
    can't statically rule out.
    """
    if var == ThresholdVar.T:
        return (0.0, _HORIZON)
    if var == ThresholdVar.Q:
        r = te.participants.expected_Q
        return (r.min, r.max)
    if var == ThresholdVar.N:
        r = te.participants.count_N
        return (r.min, r.max)
    if var == ThresholdVar.D:
        r = te.participants.average_demand_d
        return (r.min, r.max)
    if var == ThresholdVar.K:
        ks = [t.offer_variety_K for t in te.tokens if t.offer_variety_K is not None]
        if not ks:
            return None
        return (min(k.min for k in ks), max(k.max for k in ks))
    # ThresholdVar.M — circulating supply has no a-priori bound at
    # design stage; we treat it as unbounded (None → EVER).
    return None


# ---------------------------------------------------------------------------
# Per-condition evaluators
# ---------------------------------------------------------------------------


def _eval_threshold(c: ThresholdCondition, te: TokenEconomy) -> ConditionStatus:
    """Three-valued evaluation of `var op value` over the declared box.

    Examples (var ∈ [lo, hi]):
        var > value   ALWAYS iff lo > value;  NEVER iff hi <= value
        var >= value  ALWAYS iff lo >= value; NEVER iff hi < value
        var < value   ALWAYS iff hi < value;  NEVER iff lo >= value
        var <= value  ALWAYS iff hi <= value; NEVER iff lo > value
        var == value  ALWAYS iff lo == value == hi;  NEVER iff value < lo or value > hi
    """
    bounds = _var_bounds(c.var, te)
    if bounds is None:
        return ConditionStatus.EVER  # unbounded → conservative
    lo, hi = bounds
    v = c.value
    if c.op == ThresholdOp.GT:
        if lo > v:
            return ConditionStatus.ALWAYS
        if hi <= v:
            return ConditionStatus.NEVER
        return ConditionStatus.EVER
    if c.op == ThresholdOp.GTE:
        if lo >= v:
            return ConditionStatus.ALWAYS
        if hi < v:
            return ConditionStatus.NEVER
        return ConditionStatus.EVER
    if c.op == ThresholdOp.LT:
        if hi < v:
            return ConditionStatus.ALWAYS
        if lo >= v:
            return ConditionStatus.NEVER
        return ConditionStatus.EVER
    if c.op == ThresholdOp.LTE:
        if hi <= v:
            return ConditionStatus.ALWAYS
        if lo > v:
            return ConditionStatus.NEVER
        return ConditionStatus.EVER
    if c.op == ThresholdOp.EQ:
        if lo == v and hi == v:
            return ConditionStatus.ALWAYS
        if v < lo or v > hi:
            return ConditionStatus.NEVER
        return ConditionStatus.EVER
    return ConditionStatus.EVER


def _eval_time_window(c: TimeWindow, te: TokenEconomy) -> ConditionStatus:
    """Three-valued evaluation of `t ∈ [start_period, end_period]`."""
    start = c.start_period
    end = c.end_period if c.end_period is not None else float("inf")
    horizon_lo, horizon_hi = 0.0, _HORIZON
    # Window completely covers horizon → ALWAYS
    if start <= horizon_lo and end >= horizon_hi:
        return ConditionStatus.ALWAYS
    # Window completely misses horizon → NEVER
    if start > horizon_hi or end < horizon_lo:
        return ConditionStatus.NEVER
    # Otherwise the window overlaps but doesn't cover → EVER
    return ConditionStatus.EVER


def _eval_event_occurrence(
    c: EventOccurrence, te: TokenEconomy
) -> ConditionStatus:
    """Phase-H: route through the events catalog when event_id is set.

    * ``event_id`` set → return ALWAYS if the catalog contains it (the
      event exists in the IR, so the condition is structurally true).
      NEVER if the id is dangling.
    * Legacy ``source_token + source_event`` path: original behavior —
      check that the named token has an emission rule with a matching
      event predicate / kind value. EVER (conservative) on partial match.
    """
    if c.event_id is not None:
        return (
            ConditionStatus.ALWAYS
            if any(e.id == c.event_id for e in te.events)
            else ConditionStatus.NEVER
        )
    src = next((t for t in te.tokens if t.id == c.source_token), None)
    if src is None:
        return ConditionStatus.NEVER
    # Match the named source_event against each source emission rule's
    # *resolved* trigger (Phase-H): label (event_predicate for legacy
    # inline rules, catalog label otherwise), kind value, or catalog
    # event id. Resolution keeps legacy and catalog rules symmetric.
    from verifier.events_resolver import resolve_trigger

    for r in src.emission_rules:
        rt = resolve_trigger(r, te)
        if c.source_event is not None and c.source_event in (
            rt.event_label,
            rt.kind,
            rt.event_id,
        ):
            return ConditionStatus.ALWAYS
    # Source token exists but no matching event → conservative EVER
    # (we don't know exactly when the named event would fire).
    return ConditionStatus.EVER


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def evaluate_condition(c: Condition, te: TokenEconomy) -> ConditionStatus:
    """Static three-valued evaluation of one Condition over the IR's box."""
    if isinstance(c, ThresholdCondition):
        return _eval_threshold(c, te)
    if isinstance(c, TimeWindow):
        return _eval_time_window(c, te)
    if isinstance(c, EventOccurrence):
        return _eval_event_occurrence(c, te)
    return ConditionStatus.EVER  # unknown → conservative


def conjunction_status(
    conditions: list[Condition], te: TokenEconomy
) -> ConditionStatus:
    """Combine multiple conditions on a single rule (AND)."""
    if not conditions:
        return ConditionStatus.ALWAYS
    statuses = [evaluate_condition(c, te) for c in conditions]
    if any(s == ConditionStatus.NEVER for s in statuses):
        return ConditionStatus.NEVER
    if all(s == ConditionStatus.ALWAYS for s in statuses):
        return ConditionStatus.ALWAYS
    return ConditionStatus.EVER


def rule_contributes(
    rule, te: TokenEconomy, *, side: str
) -> bool:
    """Whether the rule's rate is included in the symbolic E / B sum.

    Parameters
    ----------
    rule:
        Either an `emission_rules[i]` or `burn_rules[i]` entry.
    te:
        The TokenEconomy.
    side:
        ``"emission"`` (over-conservative — include if EVER) or
        ``"burn"`` (under-conservative — include only if ALWAYS).
    """
    s = conjunction_status(rule.trigger.conditions, te)
    if side == "burn":
        return s == ConditionStatus.ALWAYS
    # Default ("emission"): include unless statically NEVER
    return s != ConditionStatus.NEVER
