"""Trajectory simulation — forward-Euler stepping of M(t), E(t), B(t), Q(t).

The core question this module answers: under typical parameter values
(midpoint of every declared range), what does the system actually do
over time? Does the supply saturate, diverge, oscillate? When does ρ
fall below 1?

This complements (does not replace) the static SMT layer:

- Static verdict says "there exists a parameter assignment in the box
  that violates ρ ≥ 1" → FAIL.
- Trajectory says "at midpoint values, ρ averages 1.18 over 260
  periods, M grows 4% then plateaus" → useful refinement.

Both layers are reported side by side. The trajectory metrics flow
into ``verifier.simulate.refinement`` which composes a short
user-facing note.

Implementation notes:

- Forward Euler at period granularity (no sub-period adaptive stepping).
- Per-period E, B computed from each rule's asymptotic class evaluated
  at time t with parameter midpoints.
- Q evolves with growth_g (midpoint multiplier per period).
- ``decreasing_positive`` sign hint: see `_evaluate_emission_at` —
  conservative interpretation, with a note in the metrics if the user
  declared this sign without a piecewise rule structure.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from schema import (
    AsymptoticClass,
    AsymptoticFamily,
    CrossTokenAction,
    FlowCoupling,
    FunctionSign,
    NumberRange,
    Token,
    TokenEconomy,
)


# Default horizon: 260 periods ≈ 5 years if 1 period = 1 week.
_DEFAULT_HORIZON = 260
# Number of condensed samples surfaced for chart display.
_SAMPLE_COUNT = 30


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TrajectorySample(BaseModel):
    """A single condensed snapshot of the simulated state at time t.

    Only ~30 samples are surfaced (down-sampled from the full per-period
    integration) so the JSON payload stays small and the inline
    sparkline can be rendered without aggregation logic in the client.
    """

    model_config = ConfigDict(extra="forbid")

    t: int  # period (0 = launch / now)
    M: float  # circulating supply at time t
    E: float  # emission rate at time t (tokens/period)
    B: float  # burn rate at time t (tokens/period)
    Q: float  # transaction volume at time t (transactions/period)


class TrajectoryMetrics(BaseModel):
    """Headline numbers extracted from the simulated trajectory.

    These are what the user actually reads — the per-sample table is
    only for the chart. Keep this surface minimal: the verdict cards
    must stay synthetic.

    Attributes
    ----------
    horizon_periods:
        How many periods the simulation covered.
    M_initial / M_terminal:
        Supply at t=0 and t=horizon. The growth percentage tells the
        user "how much does supply expand over the horizon".
    M_growth_pct:
        ``(M_terminal − M_initial) / max(M_initial, ε) × 100``. Capped
        at 9999 for very small initial supplies.
    rho_avg:
        Mean of B_t / E_t over periods where E_t > 0. ``None`` when
        emission is zero throughout (ρ undefined).
    rho_below_one_at_period:
        First period where the *cumulative* ρ falls below 1, or
        ``None`` if it never does. Useful for FM3 refinement.
    saturates_at:
        Earliest period where ``dM/dt`` shrinks below 1% of the
        initial dM/dt — a heuristic for "the system has plateaued".
        ``None`` if M is still growing meaningfully at horizon.
    diverges:
        True iff M_terminal / max(M_initial, 1) > 100 — supply blew up.
    notes:
        One-line caveats produced during simulation (e.g. user
        declared `decreasing_positive` but no halving schedule, so the
        simulation treated emission as constant).
    """

    model_config = ConfigDict(extra="forbid")

    horizon_periods: int
    M_initial: float
    M_terminal: float
    M_growth_pct: float
    rho_avg: Optional[float] = None
    rho_below_one_at_period: Optional[int] = None
    saturates_at: Optional[int] = None
    diverges: bool = False
    notes: list[str] = Field(default_factory=list)


class Trajectory(BaseModel):
    """A simulated trajectory plus the metrics extracted from it."""

    model_config = ConfigDict(extra="forbid")

    token_id: str
    samples: list[TrajectorySample]
    metrics: TrajectoryMetrics


# ---------------------------------------------------------------------------
# Time-evaluated asymptotic-class helpers (vs midpoint helpers in risk.py)
# ---------------------------------------------------------------------------


def _mid(rng: NumberRange | None, default: float = 0.0) -> float:
    if rng is None:
        return default
    return (rng.min + rng.max) / 2.0


def _ac_at_time(ac: AsymptoticClass | None, t: float) -> float:
    """Evaluate an asymptotic class's per-period rate at time t.

    Mirror of `verifier.asymptotic.average_rate_per_period` but
    time-pointwise rather than averaged over the horizon. Uses
    parameter midpoints — the static verifier handles the existential
    over the box; the simulation gives the user the typical-value
    trajectory.
    """
    if ac is None:
        return 0.0
    fam = ac.family
    if fam == AsymptoticFamily.CONSTANT:
        return _mid(ac.parameter_ranges.get("c"))
    if fam == AsymptoticFamily.BOUNDED_RANGE:
        return _mid(ac.bounds)
    if fam == AsymptoticFamily.LINEAR:
        a = _mid(ac.parameter_ranges.get("a"))
        b = _mid(ac.parameter_ranges.get("b"))
        return max(0.0, a * t + b)
    if fam == AsymptoticFamily.POLYNOMIAL:
        k = ac.degree if ac.degree is not None else 2
        a = _mid(ac.parameter_ranges.get("a"))
        b = _mid(ac.parameter_ranges.get("b"))
        return max(0.0, a * (t ** k) + b)
    if fam == AsymptoticFamily.SUBLINEAR_ROOT:
        d = ac.degree if ac.degree is not None else 2
        a = _mid(ac.parameter_ranges.get("a"))
        b = _mid(ac.parameter_ranges.get("b"))
        return max(0.0, a * (max(t, 0.0) ** (1.0 / d)) + b)
    if fam == AsymptoticFamily.LOG:
        a = _mid(ac.parameter_ranges.get("a"))
        b = _mid(ac.parameter_ranges.get("b"))
        return max(0.0, a * math.log(1.0 + max(t, 0.0)) + b)
    if fam == AsymptoticFamily.EXPONENTIAL:
        a = _mid(ac.parameter_ranges.get("a"))
        b = _mid(ac.parameter_ranges.get("b", NumberRange(min=1.0, max=1.0)))
        return max(0.0, a * (b ** t))
    if fam == AsymptoticFamily.UNSPECIFIED:
        return _mid(ac.parameter_ranges.get("value"))
    return 0.0


def _rule_base_rate_at(rule, t: float, te=None) -> float:
    if getattr(rule.function, "distribution", None) is not None:
        # Distribution precedence (ABM sampling semantics): the
        # deterministic trajectory uses the analytic mean, clamped at 0.
        from verifier.distribution_support import mean as _dist_mean
        fn = max(0.0, _dist_mean(rule.function.distribution))
        return fn * _freq_factor_at(rule, t, te)
    """Per-period rate from a Rule at time t (midpoint params),
    *before* schedule modifiers are applied. Use this only for the
    schedule-aware path inside trajectory simulation; everywhere else,
    `_rule_rate_at` is the right entry point.
    """
    # K5: DSL expression — midpoint-evaluate against (state.t, midpoint
    # params, midpoint event payload). Conservative — gives the
    # trajectory layer a deterministic point estimate.
    if getattr(rule.function, "expression", None) is not None:
        from verifier.expr_eval import EvalEnv, evaluate as _ev
        params = {}
        for p in (rule.function.parameters or []):
            params[p.name] = (p.range.min + p.range.max) / 2.0
        event_payload = {}
        # Event payload not threadable from this layer without a TE
        # handle. _ac_at_time path below is the legacy fallback when
        # the expression references only state/param.
        try:
            fn = float(_ev(
                rule.function.expression,
                EvalEnv(
                    state={"t": float(t)},
                    params=params,
                    consts={"horizon": 52.0},
                    event=event_payload or None,
                    agents=[], tokens=[], events=[], assets=[],
                ),
            ))
        except Exception:
            fn = 0.0
        import math as _math
        if not _math.isfinite(fn):
            fn = 0.0
    else:
        fn = _ac_at_time(rule.function.asymptotic_class, t)
    return fn * _freq_factor_at(rule, t, te)


def _freq_factor_at(rule, t: float, te=None) -> float:
    """Event-arrival multiplier at time t (1.0 for time-based rules).

    Resolved through the events catalog (Phase-H) when a TE handle is
    available; stochastic arrivals use their analytic mean, clamped
    at 0 — the deterministic-trajectory reading of a distribution.
    """
    if te is not None:
        from verifier.events_resolver import resolve_trigger
        rt = resolve_trigger(rule, te)
        freq_ac = rt.event_frequency
        freq_dist = rt.event_frequency_distribution
    else:
        freq_ac = rule.trigger.event_frequency
        freq_dist = None
    if freq_ac is not None:
        return _ac_at_time(freq_ac, t)
    if freq_dist is not None:
        from verifier.distribution_support import mean as _dist_mean
        return max(0.0, _dist_mean(freq_dist))
    return 1.0


def _schedule_multiplier(rule, t: int, cumulative_emitted: float) -> float:
    """Apply the rule's schedule modifiers at time t.

    Returns a multiplier in [0, 1] that scales the base rate. Stops at
    0 when the supply cap is reached. Captures halving and vesting.
    """
    sched = getattr(rule, "schedule", None)
    if sched is None:
        return 1.0
    mult = 1.0
    # Cap: if cumulative emitted has hit the cap, emit nothing more.
    if sched.supply_cap is not None and cumulative_emitted >= sched.supply_cap:
        return 0.0
    # Halving: multiply by halving_factor^⌊(t + halving_offset) / halving_period⌋.
    # halving_offset shifts the schedule so the first halving aligns with
    # real-world calendar time (e.g. Bitcoin's ~110 weeks since the
    # April-2024 halving when t=0 represents mid-2026).
    if sched.halving_period is not None and sched.halving_period > 0:
        n_halvings = (t + sched.halving_offset) // sched.halving_period
        mult *= sched.halving_factor ** n_halvings
    # Vesting: linear ramp from 0 to 1 over vesting_periods.
    if sched.vesting_periods is not None and sched.vesting_periods > 0:
        ramp = min(1.0, t / sched.vesting_periods)
        mult *= ramp
    return mult


def _rule_rate_at(rule, t: float, te=None) -> float:
    """Per-period rate from a Rule at time t — schedule-unaware entry
    point used by FMs and the static layer. The schedule-aware path
    in trajectory uses `_rule_base_rate_at` plus `_schedule_multiplier`
    so that cap-driven shut-off can incorporate cumulative state.
    """
    return _rule_base_rate_at(rule, t, te=te)


def _own_rate_at(rules: list, t: float, te=None) -> float:
    return sum(_rule_rate_at(r, t, te=te) for r in rules)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def _initial_supply(token: Token) -> float:
    """Best-effort initial M from the IR; defaults to 0."""
    init = token.initial_distribution
    if init.amount is not None:
        return _mid(init.amount)
    return 0.0


def _xt_inflow_for(te: TokenEconomy, token: Token, t: float, action: CrossTokenAction,
                   own_E_by_token: dict[str, float]) -> float:
    """Sum of cross-token contributions on the given side at time t.

    Proportional flows multiply by the source token's own E *at time t*.
    Independent flows use the flow's own amount class.
    """
    total = 0.0
    for flow in te.cross_token_flows:
        if flow.target_token != token.id:
            continue
        if flow.target_action != action:
            continue
        if flow.coupling == FlowCoupling.PROPORTIONAL_TO_SOURCE:
            ratio = _mid(flow.coupling_ratio) if flow.coupling_ratio else 0.0
            total += ratio * own_E_by_token.get(flow.source_token, 0.0)
        else:
            total += _ac_at_time(flow.amount, t)
    return total


def simulate_token_trajectory(
    te: TokenEconomy, token: Token, *, horizon: int | None = None
) -> Trajectory:
    """Forward-Euler simulation of M(t), E(t), B(t), Q(t) for one token.

    Q evolves multiplicatively per `participants.growth_g` midpoint.
    The simulation is intentionally simple — Sprint 1 — and uses
    parameter midpoints throughout. Sprints 2+ add stochasticity and
    shock injection.

    Horizon resolution order: explicit `horizon` arg → `te.meta.simulation_horizon`
    → `_DEFAULT_HORIZON` (260). Bounded by the schema's [1, 10000].
    """
    if horizon is None:
        horizon = te.meta.simulation_horizon or _DEFAULT_HORIZON
    notes: list[str] = []

    # Detect declared but un-modelled regime hints. Suppress the
    # warning when the user has already declared a schedule modifier
    # (halving / cap / vesting) — the trajectory then *does* model
    # the decay accurately.
    for rule in token.emission_rules:
        if rule.function.sign != FunctionSign.DECREASING_POSITIVE:
            continue
        sched = getattr(rule, "schedule", None)
        if sched is not None and (
            sched.halving_period is not None or sched.supply_cap is not None
        ):
            continue  # declared explicitly — trajectory uses it
        notes.append(
            f"Token {token.id} declared emission as `decreasing_positive` "
            f"but no schedule modifier (halving_period / supply_cap / "
            f"vesting_periods) is set. The simulation treats emission as "
            f"time-constant per the asymptotic class. To capture an "
            f"actual halving or capped supply, set the rule's `schedule` "
            f"field — the trajectory will then model it exactly."
        )

    # Q growth: midpoint of growth_g
    g_mid = _mid(te.participants.growth_g.parameter_ranges.get("value"), 0.0)
    Q_0 = _mid(te.participants.expected_Q)

    # Initial supply
    M = _initial_supply(token)
    M_initial = M

    # We collect every period for accurate metrics, then down-sample
    # for the surfaced `samples` list.
    full: list[TrajectorySample] = []
    cum_E = 0.0
    cum_B = 0.0
    rho_below_one_at: int | None = None
    initial_dMdt: float | None = None
    saturates_at: int | None = None

    # Per-rule cumulative emitted (for supply_cap shut-off).
    rule_cumulative: dict[int, float] = {}

    for t in range(horizon + 1):
        # Compute every token's own_E at this t (needed for proportional flows).
        # Schedule modifiers apply per-rule using the *cumulative*
        # state of that rule, so cap-driven shut-off is faithful to
        # the design (Bitcoin: emission stops at 21M cumulative).
        # We accumulate only for t > 0 — t=0 is the boundary sample
        # (initial supply at launch) and shouldn't double-count.
        own_E_by_token: dict[str, float] = {}
        for tok in te.tokens:
            tok_E = 0.0
            for ridx, rule in enumerate(tok.emission_rules):
                key = id(rule)
                base = _rule_base_rate_at(rule, t, te=te)
                mult = _schedule_multiplier(rule, t, rule_cumulative.get(key, 0.0))
                contribution = base * mult
                tok_E += contribution
                if t > 0 and tok.id == token.id:
                    rule_cumulative[key] = rule_cumulative.get(key, 0.0) + contribution
            own_E_by_token[tok.id] = tok_E

        # Burn rules: same schedule path (caps and decays on the burn
        # side are uncommon but we keep the symmetry for correctness).
        B_own = 0.0
        for ridx, rule in enumerate(token.burn_rules):
            key = id(rule)
            base = _rule_base_rate_at(rule, t, te=te)
            mult = _schedule_multiplier(rule, t, rule_cumulative.get(key, 0.0))
            contrib = base * mult
            B_own += contrib
            if t > 0:
                rule_cumulative[key] = rule_cumulative.get(key, 0.0) + contrib

        E_own = own_E_by_token.get(token.id, 0.0)
        E_xt = _xt_inflow_for(te, token, t, CrossTokenAction.MINT, own_E_by_token)
        B_xt = _xt_inflow_for(te, token, t, CrossTokenAction.BURN, own_E_by_token)
        E = E_own + E_xt
        B = B_own + B_xt
        Q = Q_0 * ((1.0 + g_mid) ** t) if g_mid > -1.0 else 0.0

        if t > 0:
            dMdt = E - B
            M = max(0.0, M + dMdt)
            cum_E += E
            cum_B += B
            if cum_E > 0 and cum_B / cum_E < 1.0 and rho_below_one_at is None:
                rho_below_one_at = t
            if initial_dMdt is None and abs(dMdt) > 1e-9:
                initial_dMdt = dMdt
            elif (
                initial_dMdt is not None
                and abs(initial_dMdt) > 1e-9
                and abs(dMdt) < 0.01 * abs(initial_dMdt)
                and saturates_at is None
            ):
                saturates_at = t

        full.append(TrajectorySample(t=t, M=M, E=E, B=B, Q=Q))

    # Down-sample to ~30 points evenly distributed
    if len(full) <= _SAMPLE_COUNT:
        samples = full
    else:
        stride = max(1, len(full) // _SAMPLE_COUNT)
        samples = [full[i] for i in range(0, len(full), stride)]
        # Always include the last sample
        if samples[-1].t != full[-1].t:
            samples.append(full[-1])

    # Metrics
    M_terminal = full[-1].M
    growth_denominator = max(M_initial, 1.0)
    M_growth_pct = (M_terminal - M_initial) / growth_denominator * 100.0
    M_growth_pct = min(M_growth_pct, 9999.0)
    rho_avg: float | None = None
    if cum_E > 0:
        rho_avg = cum_B / cum_E
    diverges = M_terminal / max(M_initial, 1.0) > 100.0

    # If a supply_cap is declared but the rule's cumulative emission
    # is far below it at horizon end, the user may want a longer
    # simulation_horizon to actually witness the cap binding.
    for rule in token.emission_rules:
        sched = getattr(rule, "schedule", None)
        if sched is None or sched.supply_cap is None:
            continue
        emitted = rule_cumulative.get(id(rule), 0.0)
        approach_ratio = emitted / sched.supply_cap if sched.supply_cap else 0.0
        if approach_ratio < 0.95:
            notes.append(
                f"Token {token.id}: supply_cap = {sched.supply_cap:g}, but "
                f"only {approach_ratio*100:.1f}% reached at horizon t = "
                f"{horizon}. The cap won't bind within this window — "
                f"set `meta.simulation_horizon` to a larger value (e.g. "
                f"{int(horizon * (1.0 / max(approach_ratio, 0.05)))}) to "
                f"witness it."
            )

    metrics = TrajectoryMetrics(
        horizon_periods=horizon,
        M_initial=M_initial,
        M_terminal=M_terminal,
        M_growth_pct=M_growth_pct,
        rho_avg=rho_avg,
        rho_below_one_at_period=rho_below_one_at,
        saturates_at=saturates_at,
        diverges=diverges,
        notes=notes,
    )

    return Trajectory(token_id=token.id, samples=samples, metrics=metrics)
