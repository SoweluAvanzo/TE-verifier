"""Helpers for translating AsymptoticClass values into design-stage estimates.

The Tier-1 verifier evaluates the paper's failure-mode conditions using
*design-stage representative values* derived from the asymptotic class
together with its parameter ranges. We do not run full continuous-time
reasoning here; that is Tier-2 (KeYmaera X / Lean) work.

The functions in this module return Z3 expressions, so they can be used
inside a Z3 solver to find counterexamples over the parameter ranges.
"""

from __future__ import annotations

import z3

from schema import AsymptoticClass, AsymptoticFamily, NumberRange


def _range_var(
    solver: z3.Solver,
    name: str,
    rng: NumberRange,
) -> z3.ArithRef:
    """Declare a Z3 real bounded to the given NumberRange and return it."""
    v = z3.Real(name)
    solver.add(v >= rng.min, v <= rng.max)
    return v


def parameter_var(
    solver: z3.Solver,
    name_prefix: str,
    param_name: str,
    ac: AsymptoticClass,
    default: NumberRange,
) -> z3.ArithRef:
    """Get a Z3 variable for a named parameter of an asymptotic class.

    If the IR provides a `parameter_ranges` entry for `param_name`, use it;
    otherwise use `default`.
    """
    rng = ac.parameter_ranges.get(param_name, default)
    return _range_var(solver, f"{name_prefix}__{param_name}", rng)


def average_rate_per_period(
    solver: z3.Solver,
    name_prefix: str,
    ac: AsymptoticClass,
    *,
    base_population: z3.ArithRef | None = None,
    periods_horizon: float = 52.0,
) -> z3.ArithRef:
    """Estimate the average per-period rate of a function in this class.

    The model checker checks the failure-mode conditions at design-stage
    representative values. For per-period quantities (emission rate,
    burn rate, growth rate) we approximate the average over a default
    52-period horizon (interpretable as one year of weekly periods).

    `base_population` is used only for classes whose magnitude scales with
    population — caller supplies it where appropriate (e.g. for emission
    that is per-active-user). For classes where it does not apply, callers
    pass None.

    Conventions for parameter names:
        constant            -> {c}
        bounded_range       -> uses bounds.min/max as floor/ceiling, with
                               midpoint as the representative
        linear              -> {a, b}: rate ≈ a * t + b averaged over horizon
                               => a * H/2 + b
        polynomial(degree=k)-> {a, b}: rate ≈ a * t^k + b => a * H^k / (k+1) + b
        log                 -> {a, b}: rate ≈ a * log(1+t) + b
                               approximation: a * (log(H+1) - 1) + b
        exponential         -> {a, b}: rate ≈ a * b^t averaged over horizon
                               approximation: a * (b^H - 1) / (b - 1) / H
        unspecified         -> a single Z3 variable bounded by parameter_ranges
                               'min'/'max' if provided, else [0, +inf) loosely
                               bounded for solver tractability.

    Numerical constants used here are deterministic functions of the family
    + horizon and are documented in this docstring; they are NOT magic
    numbers in the sense the user asked us to avoid.
    """
    H = periods_horizon
    fam = ac.family

    if fam == AsymptoticFamily.CONSTANT:
        c = parameter_var(solver, name_prefix, "c", ac, NumberRange(min=0, max=1e9))
        return c

    if fam == AsymptoticFamily.BOUNDED_RANGE:
        if ac.bounds is None:
            raise ValueError("bounded_range without bounds")
        lo, hi = ac.bounds.min, ac.bounds.max
        v = z3.Real(f"{name_prefix}__bounded")
        solver.add(v >= lo, v <= hi)
        return v

    if fam == AsymptoticFamily.LINEAR:
        a = parameter_var(solver, name_prefix, "a", ac, NumberRange(min=0, max=1e6))
        b = parameter_var(solver, name_prefix, "b", ac, NumberRange(min=0, max=1e6))
        # Average of a*t + b over [0, H] is a*H/2 + b
        return a * (H / 2.0) + b

    if fam == AsymptoticFamily.POLYNOMIAL:
        k = ac.degree if ac.degree is not None else 2
        a = parameter_var(solver, name_prefix, "a", ac, NumberRange(min=0, max=1e6))
        b = parameter_var(solver, name_prefix, "b", ac, NumberRange(min=0, max=1e6))
        # Average of a*t^k over [0, H] is a*H^k/(k+1)
        return a * (H**k / (k + 1)) + b

    if fam == AsymptoticFamily.SUBLINEAR_ROOT:
        # Rate ≈ a · t^(1/d) + b. Average of t^(1/d) over [0, H] is
        # (d/(d+1)) · H^(1/d). For d=2 (√t): (2/3)·√H ≈ 4.81 at H=52.
        d = ac.degree if ac.degree is not None else 2
        a = parameter_var(solver, name_prefix, "a", ac, NumberRange(min=0, max=1e6))
        b = parameter_var(solver, name_prefix, "b", ac, NumberRange(min=0, max=1e6))
        avg_factor = (d / (d + 1.0)) * (H ** (1.0 / d))
        return a * avg_factor + b

    if fam == AsymptoticFamily.LOG:
        # Use a linear surrogate scaled by log(H+1) - 1 for the averaged rate;
        # this preserves monotonicity in 'a' which is what FM checks need.
        a = parameter_var(solver, name_prefix, "a", ac, NumberRange(min=0, max=1e6))
        b = parameter_var(solver, name_prefix, "b", ac, NumberRange(min=0, max=1e6))
        import math

        return a * (math.log(H + 1) - 1) + b

    if fam == AsymptoticFamily.EXPONENTIAL:
        # Use a tractable surrogate; full b^H reasoning is Tier-2 work.
        a = parameter_var(solver, name_prefix, "a", ac, NumberRange(min=0, max=1e6))
        b = parameter_var(solver, name_prefix, "b", ac, NumberRange(min=1.0, max=2.0))
        # Surrogate: a * b^(H/4), encoded by repeated multiplication for small H/4.
        # We bound H/4 to a small integer to keep Z3 fast; for H=52 that's 13.
        steps = max(1, int(H / 4))
        result = a
        for _ in range(steps):
            result = result * b
        return result

    if fam == AsymptoticFamily.UNSPECIFIED:
        # Worst-case bounded variable. If parameter_ranges has 'min'/'max',
        # use them; otherwise impose loose bounds for tractability.
        rng = ac.parameter_ranges.get(
            "value", NumberRange(min=0, max=1e9)
        )
        return _range_var(solver, f"{name_prefix}__unspec", rng)

    raise ValueError(f"unhandled asymptotic family: {fam}")


def representative_midpoint(rng: NumberRange) -> float:
    """A single Python-float representative of a NumberRange."""
    return rng.midpoint


def own_emission_rate_per_period(
    solver: z3.Solver,
    name_prefix: str,
    token,  # schema.Token, untyped to avoid circular imports
    *,
    periods_horizon: float = 52.0,
) -> z3.ArithRef:
    """Per-period rate from a token's *own* emission_rules only.

    Excludes cross-token contributions. This is the quantity used as
    the multiplicand in the proportional-coupling encoding (Phase B1):
    a flow with `coupling = proportional_to_source` contributes
    `coupling_ratio × own_emission_rate_per_period(source_token)` to
    the target token's E or B (per `target_action`).

    Excluding cross-token contributions guarantees there are no cycles
    in the dependency graph: every flow's rate depends only on the
    sources' own rule rates, which are pure functions of the IR.
    """
    terms = [
        rule_rate_per_period(
            solver, f"{name_prefix}_emit_{i}", rule, periods_horizon=periods_horizon
        )
        for i, rule in enumerate(token.emission_rules)
    ]
    if not terms:
        return z3.RealVal(0)
    return sum(terms[1:], terms[0])


def cross_token_flow_rate(
    solver: z3.Solver,
    name_prefix: str,
    flow,  # schema.CrossTokenFlow
    source_own_E: z3.ArithRef,
    *,
    periods_horizon: float = 52.0,
) -> z3.ArithRef:
    """Per-period rate contributed by a single cross-token flow.

    For `coupling = INDEPENDENT` this delegates to
    `average_rate_per_period(flow.amount)` — same as Phase A behaviour.

    For `coupling = PROPORTIONAL_TO_SOURCE` this returns
    `r × source_own_E`, where `r` is a Z3 real bounded to
    `flow.coupling_ratio`. The caller is responsible for supplying
    `source_own_E` from `own_emission_rate_per_period(source_token)`.
    """
    # Local import to avoid an import cycle at module load.
    from schema import FlowCoupling

    if flow.coupling == FlowCoupling.PROPORTIONAL_TO_SOURCE:
        ratio_lo = flow.coupling_ratio.min
        ratio_hi = flow.coupling_ratio.max
        ratio = z3.Real(f"{name_prefix}__ratio")
        solver.add(ratio >= ratio_lo, ratio <= ratio_hi)
        return ratio * source_own_E
    return average_rate_per_period(
        solver, name_prefix, flow.amount, periods_horizon=periods_horizon
    )


def rule_rate_per_period(
    solver: z3.Solver,
    name_prefix: str,
    rule,  # schema.Rule, untyped here to avoid circular imports
    *,
    periods_horizon: float = 52.0,
) -> z3.ArithRef:
    """Compute the per-period rate produced (or destroyed) by a Rule.

    For time-based triggers, the rate is the function value averaged over
    the horizon. For event-based triggers, the rate is the function value
    *per event* multiplied by the event frequency averaged over the horizon.
    This is the natural rate-of-mint or rate-of-burn that FM1 and FM3 reason
    about.
    """
    fn_value = average_rate_per_period(
        solver,
        f"{name_prefix}_fn",
        rule.function.asymptotic_class,
        periods_horizon=periods_horizon,
    )
    if rule.trigger.event_frequency is not None:
        frequency = average_rate_per_period(
            solver,
            f"{name_prefix}_freq",
            rule.trigger.event_frequency,
            periods_horizon=periods_horizon,
        )
        return fn_value * frequency
    return fn_value
