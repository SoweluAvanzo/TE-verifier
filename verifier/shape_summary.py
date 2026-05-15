"""Derive human-readable shape labels for each Rule (Phase G/Task 3).

After the verifier has the IR in hand, we can describe each emission /
burn rule in plain English without the user having declared anything
beyond the asymptotic family + coefficient ranges:

* monotonicity   — increasing, decreasing, constant
* convexity      — convex, concave, linear
* time bounds    — values at t=0 and t=H (the worst-case corners)

Surfaced on the Report so the verdict card can echo back what the
user actually specified (helps catch the case where they picked a
family but mis-set coefficients).
"""

from __future__ import annotations

from dataclasses import dataclass

from schema import AsymptoticFamily, Rule, TokenEconomy


@dataclass(frozen=True)
class ShapeDescription:
    token_id: str
    rule_kind: str       # "emission" | "burn"
    rule_index: int
    family: str
    degree: int | None
    monotonicity: str    # "increasing" | "decreasing" | "constant" | "mixed"
    convexity: str       # "convex" | "concave" | "linear" | "varies"
    summary: str         # one-line plain-English description


def _coef_sign(ac, key: str) -> str:
    """Return 'zero' / 'positive' / 'negative' / 'mixed' based on the
    declared range of coefficient ``key``. Missing keys treated as
    'zero' (the coefficient is not specified ⇒ effectively absent).
    A range whose min and max are both ≈ 0 is also 'zero' — the
    user has pinned that term off, so the family collapses one degree
    (e.g. linear with a ≡ 0 is effectively constant at b)."""
    rng = ac.parameter_ranges.get(key)
    if rng is None:
        return "zero"
    if abs(rng.min) < 1e-9 and abs(rng.max) < 1e-9:
        return "zero"
    if rng.min >= 0 and rng.max >= 0:
        return "positive"
    if rng.min <= 0 and rng.max <= 0:
        return "negative"
    return "mixed"


def _shape_for_class(ac, a_sign: str | None = None) -> tuple[str, str, str]:
    """Pure-function variant of _describe_rule operating on a single
    AsymptoticClass (not a Rule). Used internally for composition."""
    if ac is None:
        return "constant", "linear", "absent"
    fam = ac.family
    a_sign = a_sign if a_sign is not None else _coef_sign(ac, "a")
    b_sign_for_exp = _coef_sign(ac, "b") if fam == AsymptoticFamily.EXPONENTIAL else None
    if fam == AsymptoticFamily.CONSTANT:
        return "constant", "linear", "flat"
    if fam == AsymptoticFamily.BOUNDED_RANGE:
        return "constant", "linear", "bounded scalar"
    if fam == AsymptoticFamily.LINEAR:
        if a_sign == "zero":      return "constant", "linear", "linear with slope ≈ 0 ⇒ constant at b"
        if a_sign == "positive":  return "increasing", "linear", "linear (rising)"
        if a_sign == "negative":  return "decreasing", "linear", "linear (falling)"
        return "mixed", "linear", "linear (slope sign uncertain)"
    if fam == AsymptoticFamily.POLYNOMIAL:
        k = ac.degree or 2
        if a_sign == "zero":      return "constant", "linear", f"polynomial degree {k} with leading coef ≡ 0 ⇒ constant at b"
        if a_sign == "positive":  return "increasing", "convex", f"polynomial t^{k}"
        if a_sign == "negative":  return "decreasing", "concave", f"polynomial −t^{k}"
        return "mixed", "varies", f"polynomial degree {k} (leading coef mixed)"
    if fam == AsymptoticFamily.SUBLINEAR_ROOT:
        d = ac.degree or 2
        if a_sign == "zero":      return "constant", "linear", f"sublinear-root degree {d} with coef ≡ 0 ⇒ constant at b"
        if a_sign == "positive":  return "increasing", "concave", f"t^(1/{d})"
        if a_sign == "negative":  return "decreasing", "convex", f"−t^(1/{d})"
        return "mixed", "varies", f"sublinear-root degree {d} (coef mixed)"
    if fam == AsymptoticFamily.LOG:
        if a_sign == "zero":      return "constant", "linear", "log with coef ≡ 0 ⇒ constant at b"
        if a_sign == "positive":  return "increasing", "concave", "log growth"
        if a_sign == "negative":  return "decreasing", "convex", "log decay"
        return "mixed", "varies", "log (coef sign mixed)"
    if fam == AsymptoticFamily.EXPONENTIAL:
        if a_sign == "positive" and b_sign_for_exp == "positive":
            return "increasing", "convex", "exponential growth"
        if a_sign == "negative":
            return "decreasing", "convex", "exponential decay"
        return "mixed", "varies", "exponential (coef sign mixed)"
    if fam == AsymptoticFamily.UNSPECIFIED:
        return "mixed", "varies", "unspecified"
    return "mixed", "varies", str(fam)


def _family_rank(fam: str, degree: int | None, a_sign: str | None = None) -> float:
    """Numeric rank for composing two shapes. Higher = grows faster as
    t → ∞. Composition (multiplication of two rates) adds the ranks of
    the factors — except exponential / unspecified short-circuit.

    When the family's leading coefficient is identically zero
    (``a_sign == "zero"``), the family collapses to ``constant`` for
    composition purposes (e.g. linear-with-a≡0 contributes rank 0)."""
    if a_sign == "zero":
        return 0.0
    if fam == "constant" or fam == "bounded_range":
        return 0.0
    if fam == "log":
        return 0.0   # log is dominated by any polynomial term; treat as 0 for additive composition
    if fam == "sublinear_root":
        d = degree or 2
        return 1.0 / d
    if fam == "linear":
        return 1.0
    if fam == "polynomial":
        return float(degree or 2)
    if fam == "exponential":
        return 1e6   # sentinel — exponential dominates everything
    if fam == "unspecified":
        return -1.0  # sentinel — uncertainty propagates
    return 0.0


def _compose_class(fn_ac, fn_a_sign, freq_ac, freq_a_sign) -> tuple[str, str, str]:
    """Combine the function class with the event-frequency class to get
    the effective per-period rate shape. Composition is multiplicative:
    rate(t) = function(t) × frequency(t).

    Special cases short-circuit: if either factor is exponential, the
    composition is exponential; if either is unspecified, the
    composition is unspecified.
    """
    if freq_ac is None:
        # No frequency — function class is the rate directly (time_based).
        return _shape_for_class(fn_ac, fn_a_sign)
    fn_fam = fn_ac.family.value
    freq_fam = freq_ac.family.value
    # Short-circuit cases.
    if "unspecified" in (fn_fam, freq_fam):
        return "mixed", "varies", "unspecified — at least one factor has no declared shape"
    if "exponential" in (fn_fam, freq_fam):
        # Exponential * anything ≈ exponential. Direction is the sign
        # of the product of leading coefficients.
        signs = []
        if fn_fam == "exponential":     signs.append(fn_a_sign or "positive")
        else:                            signs.append(fn_a_sign or "positive")
        if freq_fam == "exponential":   signs.append(freq_a_sign or "positive")
        else:                            signs.append(freq_a_sign or "positive")
        neg = sum(1 for s in signs if s == "negative") % 2 == 1
        mono = "decreasing" if neg else "increasing"
        return mono, "convex", "exponential (one factor)"
    # Additive degree composition for polynomial-like shapes.
    fn_deg = fn_ac.degree
    freq_deg = freq_ac.degree
    total = _family_rank(fn_fam, fn_deg, fn_a_sign) + _family_rank(freq_fam, freq_deg, freq_a_sign)
    # Sign of product determines direction. A "zero" leading coef on
    # either side reduces that factor to its constant base term — treat
    # as positive for sign-product purposes (constant base ≥ 0).
    if fn_a_sign == "mixed" or freq_a_sign == "mixed":
        product_sign = "mixed"
    elif fn_a_sign == "negative" and freq_a_sign == "negative":
        product_sign = "positive"
    elif "negative" in (fn_a_sign, freq_a_sign):
        product_sign = "negative"
    else:
        product_sign = "positive"
    # Label.
    if total < 1e-6:
        return "constant", "linear", "constant (both factors flat)"
    if abs(total - 1.0) < 1e-6:
        if product_sign == "negative":  return "decreasing", "linear", "linear (effective)"
        if product_sign == "mixed":     return "mixed", "linear", "linear (sign mixed)"
        return "increasing", "linear", "linear (effective)"
    if total < 1.0:
        # Both sublinear_root or log + sublinear_root.
        if product_sign == "negative":  return "decreasing", "convex", f"sublinear t^{total:.2f}"
        return "increasing", "concave", f"sublinear t^{total:.2f}"
    # total > 1 — polynomial-like.
    if total > 1.0:
        approx_k = max(2, int(round(total)))
        if product_sign == "negative":  return "decreasing", "concave", f"polynomial −t^{approx_k}"
        if product_sign == "mixed":     return "mixed", "varies", f"polynomial degree ~{approx_k}"
        return "increasing", "convex", f"polynomial t^{approx_k}"
    return "mixed", "varies", "composed shape"


def _describe_rule(rule: Rule, te: "TokenEconomy | None" = None) -> tuple[str, str, str]:
    """Return (monotonicity, convexity, summary) for the rule's effective
    rate. ``rate(t) = function(t) × frequency(t)`` — composition done
    here so the user sees the TRUE per-period shape, not just the
    per-trigger function shape."""
    # K5: DSL-only rules don't have an asymptotic_class — render a
    # generic DSL label and let downstream layers reason from the AST.
    if getattr(rule.function, "expression", None) is not None:
        return ("data-dependent", "varies",
                "DSL expression — shape depends on event/agent/state inputs")
    ac = rule.function.asymptotic_class
    fam = ac.family
    a_sign = _coef_sign(ac, "a")
    b_sign_for_exp = _coef_sign(ac, "b") if fam == AsymptoticFamily.EXPONENTIAL else None

    # Resolve event frequency: through events catalog if event_id set,
    # else via legacy event_frequency on the rule trigger.
    freq_ac = None
    if te is not None and rule.trigger.event_id is not None:
        try:
            freq_ac = te.get_event(rule.trigger.event_id).frequency
        except Exception:
            freq_ac = None
    if freq_ac is None:
        freq_ac = rule.trigger.event_frequency

    if freq_ac is not None:
        # Compose function × frequency.
        freq_a_sign = _coef_sign(freq_ac, "a")
        mono, conv, _comp_label = _compose_class(ac, a_sign, freq_ac, freq_a_sign)
        fn_label = _shape_for_class(ac, a_sign)[2]
        freq_label = _shape_for_class(freq_ac, freq_a_sign)[2]
        summary = (
            f"effective rate = function ({fn_label}) × frequency ({freq_label})"
        )
        return mono, conv, summary

    # No frequency → fall through to the legacy per-class description.

    if fam == AsymptoticFamily.CONSTANT:
        return "constant", "linear", "flat rate over the horizon"
    if fam == AsymptoticFamily.BOUNDED_RANGE:
        return "constant", "linear", "scalar bounded by user-supplied [lo, hi]"
    if fam == AsymptoticFamily.LINEAR:
        if a_sign == "positive":
            return "increasing", "linear", "linear ramp up over time"
        if a_sign == "negative":
            return "decreasing", "linear", "linear ramp down over time"
        return "mixed", "linear", "linear; slope sign uncertain (a spans 0)"
    if fam == AsymptoticFamily.POLYNOMIAL:
        k = ac.degree or 2
        if a_sign == "positive":
            return "increasing", "convex", f"polynomial degree {k}, rises faster as t grows"
        if a_sign == "negative":
            return "decreasing", "concave", f"polynomial degree {k}, falls faster as t grows"
        return "mixed", "varies", f"polynomial degree {k}; leading coefficient spans 0"
    if fam == AsymptoticFamily.SUBLINEAR_ROOT:
        d = ac.degree or 2
        if a_sign == "positive":
            return "increasing", "concave", f"t^(1/{d}) growth, saturating curve"
        if a_sign == "negative":
            return "decreasing", "convex", f"t^(1/{d}) decay (rare; check intent)"
        return "mixed", "varies", f"sublinear-root degree {d}; coefficient spans 0"
    if fam == AsymptoticFamily.LOG:
        if a_sign == "positive":
            return "increasing", "concave", "logarithmic growth (saturating)"
        if a_sign == "negative":
            return "decreasing", "convex", "logarithmic decay"
        return "mixed", "varies", "logarithmic; coefficient spans 0"
    if fam == AsymptoticFamily.EXPONENTIAL:
        # rate = a · b^t. Direction depends on sign of (a)(b-1).
        if a_sign == "positive" and b_sign_for_exp == "positive":
            # Convention: schema bounds b ≥ 1 elsewhere; treat as growth.
            return "increasing", "convex", "exponential growth (compounding)"
        if a_sign == "negative":
            return "decreasing", "convex", "exponential decay (compounding the other way)"
        return "mixed", "varies", "exponential; direction depends on coefficient ranges"
    if fam == AsymptoticFamily.UNSPECIFIED:
        return "mixed", "varies", "unspecified shape — verifier sweeps over all plausibles"
    return "mixed", "varies", str(fam)


def _apply_schedule_modifiers(rule, mono: str, conv: str, summary: str) -> tuple[str, str, str]:
    """Fold ``Rule.schedule`` modifiers (halving, vesting, supply cap)
    into the derived shape. When the schedule overrides the per-class
    monotonicity (halving makes a constant rate decay; vesting makes a
    flat rate ramp up), the prose is REPLACED rather than appended to —
    otherwise the summary contradicts the label.
    """
    sched = getattr(rule, "schedule", None)
    if sched is None:
        return mono, conv, summary
    schedule_parts: list[str] = []
    schedule_overrides = False
    if sched.halving_period is not None:
        mono = "decreasing"
        conv = "convex"
        factor = sched.halving_factor if sched.halving_factor is not None else 0.5
        schedule_parts.append(
            f"halving schedule: rate × {factor:.2f} every {sched.halving_period} period(s) "
            f"(geometric decay)"
        )
        schedule_overrides = True
    if sched.vesting_periods is not None and sched.vesting_periods > 0:
        if sched.halving_period is None:
            mono = "increasing"
            conv = "linear"
        else:
            mono = "mixed"
            conv = "varies"
        schedule_parts.append(
            f"linear vesting ramp over the first {sched.vesting_periods} period(s)"
        )
        schedule_overrides = True
    if sched.supply_cap is not None:
        schedule_parts.append(
            f"hard cap: emission stops once cumulative mint ≥ {sched.supply_cap:,.0f}"
        )
    if not schedule_parts:
        return mono, conv, summary
    if schedule_overrides:
        # The schedule fundamentally redefines the shape — replace the
        # base summary so the prose doesn't contradict the label.
        return mono, conv, " · ".join(schedule_parts)
    # Cap-only / no-monotonicity-override: keep the base summary +
    # append the cap note.
    return mono, conv, summary + " · " + " · ".join(schedule_parts)


def describe_shapes(te: TokenEconomy) -> list[ShapeDescription]:
    """Walk every rule + regime and produce a list of shape labels."""
    out: list[ShapeDescription] = []
    for token in te.tokens:
        for i, rule in enumerate(token.emission_rules):
            mono, conv, summary = _describe_rule(rule, te)
            mono, conv, summary = _apply_schedule_modifiers(rule, mono, conv, summary)
            _fam = (
                "dsl_expression" if rule.function.asymptotic_class is None
                else rule.function.asymptotic_class.family.value
            )
            _deg = (
                None if rule.function.asymptotic_class is None
                else rule.function.asymptotic_class.degree
            )
            out.append(ShapeDescription(
                token_id=token.id,
                rule_kind="emission",
                rule_index=i,
                family=_fam,
                degree=_deg,
                monotonicity=mono,
                convexity=conv,
                summary=summary,
            ))
            # Surface each regime as its own shape line so the user
            # can verify the piecewise spec matches their intent.
            for j, regime in enumerate(getattr(rule, "regimes", []) or []):
                mono_r, conv_r, summ_r = _describe_rule(
                    Rule.model_construct(
                        trigger=rule.trigger,
                        function=regime.function,
                    ),
                    te,
                )
                _rfam = (
                    "dsl_expression" if regime.function.asymptotic_class is None
                    else regime.function.asymptotic_class.family.value
                )
                _rdeg = (
                    None if regime.function.asymptotic_class is None
                    else regime.function.asymptotic_class.degree
                )
                out.append(ShapeDescription(
                    token_id=token.id,
                    rule_kind=f"emission.regime[{j}]",
                    rule_index=i,
                    family=_rfam,
                    degree=_rdeg,
                    monotonicity=mono_r,
                    convexity=conv_r,
                    summary=f"regime: {summ_r}",
                ))
        for i, rule in enumerate(token.burn_rules):
            mono, conv, summary = _describe_rule(rule, te)
            mono, conv, summary = _apply_schedule_modifiers(rule, mono, conv, summary)
            _fam = (
                "dsl_expression" if rule.function.asymptotic_class is None
                else rule.function.asymptotic_class.family.value
            )
            _deg = (
                None if rule.function.asymptotic_class is None
                else rule.function.asymptotic_class.degree
            )
            out.append(ShapeDescription(
                token_id=token.id,
                rule_kind="burn",
                rule_index=i,
                family=_fam,
                degree=_deg,
                monotonicity=mono,
                convexity=conv,
                summary=summary,
            ))
    return out
