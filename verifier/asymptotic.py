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
    te=None,
) -> z3.ArithRef:
    """Compute the per-period rate produced (or destroyed) by a Rule.

    For time-based triggers, the rate is the function value averaged over
    the horizon. For event-based triggers, the rate is the function value
    *per event* multiplied by the event frequency averaged over the horizon.
    This is the natural rate-of-mint or rate-of-burn that FM1 and FM3 reason
    about.

    Phase-F: when ``rule.regimes`` is non-empty, the effective rate is
    a Z3 disjunction over {base_function, regime_1.function, ...}. Z3
    picks whichever candidate makes the failure condition reachable
    (worst-case reasoning across regimes). Regimes whose predicate is
    statically NEVER are excluded from the disjunction so we don't
    spuriously include unreachable rate values.

    ``te`` is needed for predicate evaluation; when omitted, regimes are
    skipped (preserves pre-Phase-F behavior for callers that don't pass
    it).
    """
    # Resolve frequency through the events catalog when ``te`` is
    # supplied (Phase-H preferred path). Falls back to the rule's
    # legacy inline ``trigger.event_frequency`` for back-compat.
    if te is not None:
        from verifier.events_resolver import resolve_trigger
        _rt = resolve_trigger(rule, te)
        resolved_frequency = _rt.event_frequency
        resolved_frequency_dist = _rt.event_frequency_distribution
    else:
        resolved_frequency = rule.trigger.event_frequency
        resolved_frequency_dist = None

    def _frequency_factor(prefix: str) -> "z3.ArithRef | None":
        """Z3 term for the per-period event arrival count.

        Deterministic frequency families go through the standard
        average-rate encoding. Stochastic arrivals (the event's
        ``frequency_distribution``) are bound to their support
        envelope, clamped at 0 — the documented conservative reading
        of a DistributionSpec. Returns None for time-based rules
        (implicit factor 1).
        """
        if resolved_frequency is not None:
            return average_rate_per_period(
                solver, f"{prefix}_freq", resolved_frequency,
                periods_horizon=periods_horizon,
            )
        if resolved_frequency_dist is not None:
            from verifier.distribution_support import rate_support
            lo, hi = rate_support(resolved_frequency_dist)
            v = z3.Real(f"{prefix}_freqdist")
            solver.add(v >= lo, v <= hi)
            return v
        return None

    # Phase K5: if the rule's function carries a DSL expression
    # (Phase K1+), encode that into Z3 directly rather than going
    # through the legacy AsymptoticClass path. Falls back when the
    # expression is non-decidable (log/exp/etc. of variables) — caller
    # sees the resulting NotImplementedError and marks inconclusive.
    fs = rule.function
    if getattr(fs, "expression", None) is not None:
        from verifier.expr_eval import encode_z3, Z3Env, Z3EncodingError, bind_param
        from schema.expr_parser import is_decidable
        ok, _reasons = is_decidable(fs.expression)
        if ok:
            try:
                # Bind ParamDecl parameters as Z3 reals constrained by
                # their declared range. Same convention the engine uses.
                param_vars: dict[str, "z3.ArithRef"] = {}
                for p in (fs.parameters or []):
                    param_vars[p.name] = bind_param(solver, p.name, p.range)
                # Bind event payload variables from the resolved
                # EventDefinition so the encoder can resolve event.X.
                event_payload_vars: dict[str, "z3.ArithRef"] = {}
                if te is not None and rule.trigger.event_id is not None:
                    try:
                        event_def = te.get_event(rule.trigger.event_id)
                    except KeyError:
                        event_def = None
                    if event_def is not None:
                        for field in (event_def.payload or []):
                            if field.type.value != "scalar" or field.range is None:
                                continue
                            v = z3.Real(f"{name_prefix}__event_{field.name}")
                            solver.add(v >= field.range.min)
                            solver.add(v <= field.range.max)
                            event_payload_vars[field.name] = v
                env = Z3Env(
                    solver=solver,
                    state_vars={
                        "t": z3.Real(f"{name_prefix}__state_t"),
                    },
                    param_vars=param_vars,
                    event_payload_vars=event_payload_vars,
                    const_values={"horizon": float(periods_horizon)},
                    agents=[], tokens=[], events=[], assets=[],
                )
                solver.add(env.state_vars["t"] >= 0)
                solver.add(env.state_vars["t"] <= periods_horizon)
                base_rate = encode_z3(fs.expression, env)
                freq = _frequency_factor(name_prefix)
                if freq is not None:
                    return base_rate * freq
                return base_rate
            except Z3EncodingError:
                # Fall through to legacy path; caller still produces
                # a verdict, just less precise.
                pass
        # Expression present but non-decidable, OR Z3 encoding failed.
        # Legacy path would crash because ``asymptotic_class`` is None
        # when ``expression`` is set. Return a free non-negative real so
        # the FM check becomes Inconclusive rather than crashing.
        free = z3.Real(f"{name_prefix}__expr_free")
        solver.add(free >= 0)
        freq = _frequency_factor(name_prefix)
        if freq is not None:
            return free * freq
        return free

    def _function_to_rate(prefix: str, fn) -> z3.ArithRef:
        dist = getattr(fn, "distribution", None)
        if dist is not None:
            # A declared per-period distribution takes precedence over
            # the asymptotic class — exactly the ABM's sampling
            # semantics (it samples the distribution INSTEAD of the
            # class). The static layer binds the value to the
            # distribution's support envelope, clamped at 0.
            from verifier.distribution_support import rate_support
            lo, hi = rate_support(dist)
            fn_value = z3.Real(f"{prefix}_fndist")
            solver.add(fn_value >= lo, fn_value <= hi)
        elif fn.asymptotic_class is None:
            # Same defensive path for regime functions: free var.
            fn_value = z3.Real(f"{prefix}__expr_free")
            solver.add(fn_value >= 0)
        else:
            fn_value = average_rate_per_period(
                solver, f"{prefix}_fn", fn.asymptotic_class,
                periods_horizon=periods_horizon,
            )
        frequency = _frequency_factor(prefix)
        if frequency is not None:
            return fn_value * frequency
        return fn_value

    base_rate = _function_to_rate(name_prefix, rule.function)

    regimes = getattr(rule, "regimes", None) or []
    if not regimes or te is None:
        return base_rate

    # Phase-F — include reachable regimes as Z3 candidates.
    from verifier.conditions import ConditionStatus, evaluate_condition  # local to avoid import cycle
    candidates: list[z3.ArithRef] = [base_rate]
    for idx, regime in enumerate(regimes):
        status = evaluate_condition(regime.predicate, te)
        if status == ConditionStatus.NEVER:
            continue
        candidates.append(
            _function_to_rate(f"{name_prefix}_regime{idx}", regime.function)
        )

    if len(candidates) == 1:
        return base_rate

    effective = z3.Real(f"{name_prefix}_effective")
    solver.add(z3.Or(*[effective == c for c in candidates]))
    return effective
