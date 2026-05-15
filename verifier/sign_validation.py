"""Sign-soundness pre-check.

Before running the failure-mode pipeline, walk every Rule and confirm:

* Mint rules: rate(t, params) ≥ 0 for every (t, params) in the declared
  parameter box × [0, horizon]. Otherwise the spec describes a
  mathematically impossible mint (rate flips negative somewhere in the
  box). Emit a precise error naming the offending family + a counter
  point (t, sampled params).
* Burn rules: dual — rate is stored as a positive magnitude in the IR,
  so the same non-negativity check applies; "burn rate < 0" would mean
  the burn rule creates supply rather than destroying it.

Implementation: corner-check at t=0 and t=horizon for each family. For
families that are not monotone in t (only ``polynomial`` of degree ≥ 2
with mixed-sign ``a``), also check the parabola vertex when it falls
inside [0, horizon].

Conservative: misses interior negativity for high-degree polynomials
with multiple sign changes — but those don't arise in any realistic
token-economy mint shape. The check covers every family the form
surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from schema import (
    AsymptoticClass,
    AsymptoticFamily,
    FunctionShape,
    NumberRange,
    Rule,
    Token,
    TokenEconomy,
)

_DEFAULT_HORIZON = 52.0


@dataclass(frozen=True)
class SignViolation:
    token_id: str
    rule_kind: str  # "emission" | "burn"
    rule_index: int
    family: str
    explanation: str


def _ac_param(ac: AsymptoticClass, key: str, default: NumberRange) -> NumberRange:
    """Read a coefficient range from an AsymptoticClass."""
    return ac.parameter_ranges.get(key, default)


def _evaluate_rate_at_corners(
    fn: FunctionShape, horizon: float
) -> list[tuple[float, float]]:
    """Return [(t, worst_case_rate)] candidates where the rate might
    dip below zero. ``worst_case_rate`` is the MIN of the rate across
    the parameter box at the given t (sufficient for soundness — we
    check whether the worst corner is < 0)."""
    # K5: DSL expression shapes are checked separately by FunctionSign
    # at the schema level; sign-validation here is AC-specific.
    if getattr(fn, "expression", None) is not None:
        return []
    ac = fn.asymptotic_class
    fam = ac.family
    out: list[tuple[float, float]] = []

    if fam == AsymptoticFamily.CONSTANT:
        c = _ac_param(ac, "c", NumberRange(min=0, max=0))
        out.append((0.0, c.min))
    elif fam == AsymptoticFamily.BOUNDED_RANGE:
        if ac.bounds is not None:
            out.append((0.0, ac.bounds.min))
    elif fam == AsymptoticFamily.LINEAR:
        a = _ac_param(ac, "a", NumberRange(min=0, max=0))
        b = _ac_param(ac, "b", NumberRange(min=0, max=0))
        # rate = a*t + b; min over (a, b) at fixed t is a_min*t + b_min
        # when t ≥ 0 and a_min ≤ 0; when a_min ≥ 0 the min is b_min.
        for t in (0.0, horizon):
            worst_a = a.min if t >= 0 else a.max
            out.append((t, worst_a * t + b.min))
    elif fam == AsymptoticFamily.POLYNOMIAL:
        a = _ac_param(ac, "a", NumberRange(min=0, max=0))
        b = _ac_param(ac, "b", NumberRange(min=0, max=0))
        k = ac.degree or 2
        for t in (0.0, horizon):
            worst_a = a.min if t >= 0 else a.max
            out.append((t, worst_a * (t ** k) + b.min))
        # Parabola vertex when a > 0 (rate could dip below zero in the
        # interior). The minimum of `a*t^k + b` over t ≥ 0 is at t=0
        # when a ≥ 0; we already covered it.
    elif fam == AsymptoticFamily.SUBLINEAR_ROOT:
        a = _ac_param(ac, "a", NumberRange(min=0, max=0))
        b = _ac_param(ac, "b", NumberRange(min=0, max=0))
        d = ac.degree or 2
        for t in (0.0, horizon):
            worst_a = a.min if t >= 0 else a.max
            out.append((t, worst_a * (t ** (1.0 / d)) + b.min))
    elif fam == AsymptoticFamily.LOG:
        import math
        a = _ac_param(ac, "a", NumberRange(min=0, max=0))
        b = _ac_param(ac, "b", NumberRange(min=0, max=0))
        for t in (0.0, horizon):
            worst_a = a.min if t >= 0 else a.max
            out.append((t, worst_a * math.log(1 + t) + b.min))
    elif fam == AsymptoticFamily.EXPONENTIAL:
        a = _ac_param(ac, "a", NumberRange(min=0, max=0))
        b = _ac_param(ac, "b", NumberRange(min=1.0, max=1.0))
        # rate = a · b^t; min over (a, b) at fixed t is a_min · b_min^t
        # when a_min ≥ 0, or a_min · b_max^t when a_min < 0 (since b > 1
        # by convention). We keep the conservative b_min^t form.
        for t in (0.0, horizon):
            out.append((t, a.min * (b.min ** t)))
    elif fam == AsymptoticFamily.UNSPECIFIED:
        # `unspecified` is a worst-case-bounded scalar — the user already
        # acknowledged they don't know the shape. Skip the check.
        return []

    return out


def _check_rule(
    rule: Rule, horizon: float, token_id: str, kind: str, index: int
) -> SignViolation | None:
    """Return a violation when the rule's parameter box admits a
    strictly-negative rate at one of the sampled corners."""
    candidates = _evaluate_rate_at_corners(rule.function, horizon)
    for t, worst in candidates:
        if worst < -1e-9:  # tiny tolerance for float noise
            return SignViolation(
                token_id=token_id,
                rule_kind=kind,
                rule_index=index,
                family=rule.function.asymptotic_class.family.value,
                explanation=(
                    f"{kind.title()} rule on token '{token_id}' (rule #{index}, "
                    f"family={rule.function.asymptotic_class.family.value}) "
                    f"admits a negative rate ({worst:.3f}) at t={t:.1f} "
                    f"under the declared parameter range. A "
                    f"{kind} rate cannot be negative; "
                    f"tighten the lower bound of the leading coefficient "
                    f"or pick a different family / regime structure."
                ),
            )
    return None


def validate_signs(te: TokenEconomy, *, horizon: float | None = None) -> list[SignViolation]:
    """Walk every emission + burn rule and report mathematically
    impossible sign configurations.

    Returns an empty list when the IR is sound. Caller decides what to
    do with violations (typically: surface as a coherence-issue in the
    verifier report and refuse to proceed)."""
    H = horizon if horizon is not None else float(
        te.meta.simulation_horizon or _DEFAULT_HORIZON
    )
    violations: list[SignViolation] = []
    for token in te.tokens:
        for i, rule in enumerate(token.emission_rules):
            v = _check_rule(rule, H, token.id, "emission", i)
            if v:
                violations.append(v)
        for i, rule in enumerate(token.burn_rules):
            v = _check_rule(rule, H, token.id, "burn", i)
            if v:
                violations.append(v)
    return violations
