"""Monte Carlo engine — sample × evolve × evaluate.

The reference ABM. Per run:

  1. Sample all NumberRange-typed inputs from their declared ranges
     (uniform by default).
  2. Build an initial state from the IR plus the sampled values.
  3. For ``horizon`` periods, evolve state per period using the
     per-FM evolution rules (see ``_step_state``).
  4. Evaluate each FM's safety predicates per period.
  5. Record: did the FM violate? at which period?

Aggregate over ``n_runs`` to produce:

  - P(violation) per FM with Wilson 95% confidence interval
  - Time-to-first-violation distribution (median, p25, p75, p95)
  - Cross-reference with the verifier's reachability verdict

The engine consumes ``ReachabilityVerdict`` objects from
``verifier.minimal`` and only simulates FMs whose structural_status
is FRAGILE — SOUND can be skipped (verifier proved unreachability),
BROKEN should not be simulated (no parameter assignment passes),
NOT_APPLICABLE / INCONCLUSIVE are surfaced in the report but not run.

Structure is cadCAD-shaped:

  - State is a plain dict (see ``verifier.abm.state``).
  - Per-period evolution is a pure function
    ``step(state, params, t) -> state``.
  - Predicates evaluate against state without touching the engine.

Migrating to real cadCAD = translating this loop into PSUBs; the
contract (state shape, predicate evaluation, report shape) doesn't
change.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from schema import (
    AgentRole,
    AsymptoticClass,
    AsymptoticFamily,
    CrossTokenAction,
    NumberRange,
    Token,
    TokenEconomy,
    Topology,
    VoteWeighting,
)
from verifier import elicitation
from verifier.abm.agents import (
    spawn_agents,
    step_agents,
    tau_bar_from_agents,
)
from verifier.abm.predicates import evaluate as eval_predicate
from verifier.abm.samplers import Sampler
from verifier.abm.state import State, initial_state
from verifier.abm.report import (
    FMSimulationResult,
    PredicateOutcome,
    PredicateTrajectory,
    SimulationConfig,
    SimulationReport,
    TrajectoryPoint,
)
from verifier.abm.state import derived_variable
from verifier.config import VerifierConfig
from verifier.constants import (
    GAMMA_CAPTURE_THRESHOLD,
    GINI_SECONDARY_THRESHOLD,
)
from verifier.failure_modes.fm6_governance import (
    UNILATERAL_ACTORS,
    _effective_gini_range,
)
from verifier.minimal import (
    ReachabilityVerdict,
    StructuralStatus,
    minimal_verdicts,
)
from verifier.safety_predicate import SafetyPredicate


_DEFAULT_HORIZON = 260


# ---------------------------------------------------------------------------
# Sampling: from IR per-run
# ---------------------------------------------------------------------------


def _sample_ac(ac: AsymptoticClass, sampler: Sampler) -> float:
    """Sample one representative value from an asymptotic class.

    For ABM we want a *typical-period* per-period rate. We use a
    horizon-averaged form: same convention the trajectory simulator
    uses for midpoints, but sampled from the declared parameter
    ranges instead of frozen at midpoint.
    """
    fam = ac.family
    if fam == AsymptoticFamily.CONSTANT:
        c = ac.parameter_ranges.get("c")
        return sampler.sample_range(c) if c else 0.0
    if fam == AsymptoticFamily.BOUNDED_RANGE:
        if ac.bounds is None:
            return 0.0
        return sampler.rng.uniform(ac.bounds.min, ac.bounds.max)
    if fam == AsymptoticFamily.LINEAR:
        a = sampler.sample_range(ac.parameter_ranges["a"]) if "a" in ac.parameter_ranges else 0.0
        b = sampler.sample_range(ac.parameter_ranges["b"]) if "b" in ac.parameter_ranges else 0.0
        # average over horizon — here we use horizon midpoint
        return a * (_DEFAULT_HORIZON / 2.0) + b
    if fam == AsymptoticFamily.POLYNOMIAL:
        k = ac.degree or 2
        a = sampler.sample_range(ac.parameter_ranges["a"]) if "a" in ac.parameter_ranges else 0.0
        b = sampler.sample_range(ac.parameter_ranges["b"]) if "b" in ac.parameter_ranges else 0.0
        return a * (_DEFAULT_HORIZON ** k / (k + 1)) + b
    if fam == AsymptoticFamily.SUBLINEAR_ROOT:
        d = ac.degree or 2
        a = sampler.sample_range(ac.parameter_ranges["a"]) if "a" in ac.parameter_ranges else 0.0
        b = sampler.sample_range(ac.parameter_ranges["b"]) if "b" in ac.parameter_ranges else 0.0
        factor = (d / (d + 1.0)) * (_DEFAULT_HORIZON ** (1.0 / d))
        return a * factor + b
    if fam == AsymptoticFamily.LOG:
        a = sampler.sample_range(ac.parameter_ranges["a"]) if "a" in ac.parameter_ranges else 0.0
        b = sampler.sample_range(ac.parameter_ranges["b"]) if "b" in ac.parameter_ranges else 0.0
        return a * (math.log(_DEFAULT_HORIZON + 1) - 1) + b
    if fam == AsymptoticFamily.EXPONENTIAL:
        a = sampler.sample_range(ac.parameter_ranges["a"]) if "a" in ac.parameter_ranges else 0.0
        b = sampler.sample_range(ac.parameter_ranges.get("b", NumberRange(min=1.0, max=1.0)))
        steps = max(1, int(_DEFAULT_HORIZON / 4))
        v = a
        for _ in range(steps):
            v *= b
        return v
    if fam == AsymptoticFamily.UNSPECIFIED:
        if "value" in ac.parameter_ranges:
            return sampler.sample_range(ac.parameter_ranges["value"])
        return 0.0
    return 0.0


def _sample_rule_rate(rule, sampler: Sampler) -> float:
    """Per-period rate (function × frequency if event-based)."""
    base = _sample_ac(rule.function.asymptotic_class, sampler)
    if rule.trigger.event_frequency is not None:
        freq = _sample_ac(rule.trigger.event_frequency, sampler)
        base *= freq
    return base


# ---------------------------------------------------------------------------
# Initial state from IR
# ---------------------------------------------------------------------------


def _initial_supply(token: Token) -> float:
    if token.initial_distribution.amount is not None:
        return (
            token.initial_distribution.amount.min
            + token.initial_distribution.amount.max
        ) / 2.0
    return 0.0


def _Gamma_from_governance(te: TokenEconomy) -> float:
    rules = te.governance.rule_structure
    if not rules:
        return 0.0
    unilateral = sum(1 for a in rules.values() if a in UNILATERAL_ACTORS)
    return unilateral / len(rules)


def _build_initial_state(
    te: TokenEconomy,
    sampler: Sampler,
    config: VerifierConfig | None,
) -> tuple[State, dict[str, Any]]:
    """Sample once per run, build the initial state + frozen params dict
    (which the per-period step function reuses)."""
    token_ids = [t.id for t in te.tokens]
    state = initial_state(token_ids=token_ids, t=0)

    # Initial M per token
    for t in te.tokens:
        state["tokens"][t.id]["M"] = _initial_supply(t)

    # Sample participants block
    state["N"] = sampler.sample_range(te.participants.count_N)
    state["d"] = sampler.sample_range(te.participants.average_demand_d)
    # v1 has expected_Q (always set); v2 has expected_Q_override (optional).
    q_range = getattr(te.participants, "expected_Q", None) or getattr(
        te.participants, "expected_Q_override", None
    )
    state["Q"] = sampler.sample_range(q_range) if q_range is not None else 0.0

    # Per-token K
    for t in te.tokens:
        if t.offer_variety_K is not None:
            state["K"][t.id] = sampler.sample_range(t.offer_variety_K)

    # Growth rate (one sample, applied per period)
    g_value = te.participants.growth_g.parameter_ranges.get("value")
    growth_g = sampler.sample_range(g_value) if g_value else 0.0

    # Per-token emission/burn rates. Rules without a declared
    # FunctionShape.distribution are sampled once per run from their
    # NumberRange (static-per-run). Rules WITH a distribution are
    # resampled per period — see ``_step_state`` for the per-period
    # path. We collect the rule sources here for both branches.
    static_rates = {tid: {"E": 0.0, "B": 0.0} for tid in token_ids}
    stochastic_rules: list[tuple[str, str, Any]] = []  # (token_id, side, rule)
    for token in te.tokens:
        for rule in token.emission_rules:
            if getattr(rule.function, "distribution", None) is not None:
                stochastic_rules.append((token.id, "E", rule))
            else:
                static_rates[token.id]["E"] += _sample_rule_rate(rule, sampler)
        for rule in token.burn_rules:
            if getattr(rule.function, "distribution", None) is not None:
                stochastic_rules.append((token.id, "B", rule))
            else:
                static_rates[token.id]["B"] += _sample_rule_rate(rule, sampler)
    # Cross-token flows — always static-per-run (their amount is
    # an AsymptoticClass, not a FunctionShape with a distribution).
    for flow in te.cross_token_flows:
        amount = _sample_ac(flow.amount, sampler)
        if flow.target_action == CrossTokenAction.MINT:
            static_rates[flow.target_token]["E"] += amount
        elif flow.target_action == CrossTokenAction.BURN:
            static_rates[flow.target_token]["B"] += amount

    for tid in token_ids:
        state["tokens"][tid]["E"] = static_rates[tid]["E"]
        state["tokens"][tid]["B"] = static_rates[tid]["B"]

    # Per-agent state — initialized once per run; evolves per period.
    # The aggregate tau_bar still lives in state["tau_bar"] for
    # predicate-resolver compatibility, but its value is now computed
    # from per-agent holdings each period rather than fixed at run start.
    # Spawn is gated on FM2 being among the simulated FMs (see engine
    # entrypoint) — populated lazily by the caller.
    state["agents"] = []
    # Static fallback for tau_bar (used when agents list is empty or
    # the token is non-transferable). Same calculation as the v0
    # aggregate sample.
    for token in te.tokens:
        if not token.transferable or not te.participants.agent_types:
            state["tau_bar"][token.id] = 0.0
            continue
        tau_bar_static = 0.0
        for ag in te.participants.agent_types:
            w = ag.balance_share if ag.balance_share is not None else ag.fraction
            tau = sampler.sample_range(ag.expected_holding_time.expected_periods)
            tau_bar_static += w * tau
        state["tau_bar"][token.id] = tau_bar_static

    # FM4 quantities
    cfg = config or VerifierConfig.paper_defaults()
    state["gamma"] = sampler.sample_range(te.governance.monitoring_capacity_gamma)
    s_range = elicitation.s_normalized_from(te.governance.sanction_structure)
    state["S"] = sampler.sample_range(s_range)
    # phi from agent roles + verification strength
    strongest_verif = None
    best_mult = -1.0
    table = cfg.phi_verification_floor_multiplier_table
    for token in te.tokens:
        if token.contribution_verification is None:
            continue
        m = table.get(token.contribution_verification.value, 0.0)
        if m > best_mult:
            best_mult = m
            strongest_verif = token.contribution_verification
    phi_lo, phi_hi = elicitation.contributor_fraction_from(
        te.participants.agent_types,
        contribution_verification=strongest_verif,
        config=cfg,
    )
    state["phi"] = sampler.rng.uniform(phi_lo, phi_hi)

    # FM5 average_degree (NETWORK topology)
    avg_deg = te.participants.topology_params.get("average_degree")
    if avg_deg is not None:
        state["average_degree"] = sampler.sample_range(avg_deg)
    else:
        state["average_degree"] = 0.0

    # FM6 quantities
    state["Gamma_central"] = _Gamma_from_governance(te)
    eff_range, _note = _effective_gini_range(te.governance, config)
    if eff_range is not None:
        state["effective_gini"] = sampler.sample_range(eff_range)
    else:
        state["effective_gini"] = 0.0

    params = {
        "growth_g": growth_g,
        # Per-token static rate baselines (won't change between
        # periods). Stochastic rules add noise on top each period.
        "static_rates": static_rates,
        # (token_id, "E"/"B", rule) tuples for rules that opted into
        # per-period resampling via FunctionShape.distribution.
        "stochastic_rules": stochastic_rules,
        # Keep the sampler reference so ``_step_state`` can draw noise.
        "_sampler": sampler,
    }
    return state, params


# ---------------------------------------------------------------------------
# Per-period state evolution
# ---------------------------------------------------------------------------


def _step_state(state: State, params: dict[str, Any]) -> State:
    """Evolve the state by one period.

    Two-layer update:

    * Static baseline (sampled once per run) — emission, burn, growth
      held constant for the duration of the run.
    * Per-period noise — for any rule that carries a
      ``FunctionShape.distribution`` field, resample the per-period
      contribution from that distribution and override the static
      baseline for this period only.

    Updates:
      • M_t = M_{t-1} + (E_t - B_t) per token   (capped at 0)
      • Q_t = Q_{t-1} × (1 + growth_g)
      • N_t = N_{t-1} × (1 + growth_g)

    Stochastic rules let the simulator observe genuinely time-evolving
    dynamics — drifts that the verifier's range-based reasoning cannot
    see by construction.
    """
    state["t"] = state["t"] + 1

    # Evolve per-agent state. Each agent's clock advances; agents
    # whose holding time has elapsed "act" (reset). This produces a
    # live tau_bar trajectory below.
    agents = state.get("agents") or []
    if agents:
        step_agents(agents, state["t"])
        # Update tau_bar per token from per-agent state. Use the same
        # value across tokens (v1: one population, not per-token
        # agent partitions). Honors the existing fallback when no
        # agents are present.
        live_tau = tau_bar_from_agents(
            agents, state["t"], fallback=0.0
        )
        # Only update transferable-token tau_bar entries; non-
        # transferable tokens kept the v0 zero from initial_state.
        for tid in state["tau_bar"]:
            # If the static fallback was 0 (e.g. non-transferable),
            # leave it alone.
            if state["tau_bar"][tid] > 0:
                state["tau_bar"][tid] = live_tau

    # Per-period stochastic resampling (overrides for this period).
    sampler = params.get("_sampler")
    stochastic = params.get("stochastic_rules", [])
    static = params.get("static_rates", {})
    if stochastic and sampler is not None:
        # Start each period from the static baseline.
        per_period_E = {tid: static.get(tid, {}).get("E", 0.0) for tid in state["tokens"]}
        per_period_B = {tid: static.get(tid, {}).get("B", 0.0) for tid in state["tokens"]}
        for token_id, side, rule in stochastic:
            dist = rule.function.distribution
            # Sample one value from the declared distribution. Clamp
            # below 0 — rate-like quantities are non-negative.
            v = max(0.0, sampler.sample_distribution(dist))
            # If the rule has an event_frequency, multiply by an
            # averaged frequency sample (kept static-per-run for now).
            if rule.trigger.event_frequency is not None:
                v *= _sample_ac(rule.trigger.event_frequency, sampler)
            if side == "E":
                per_period_E[token_id] += v
            else:
                per_period_B[token_id] += v
        for tid in state["tokens"]:
            state["tokens"][tid]["E"] = per_period_E[tid]
            state["tokens"][tid]["B"] = per_period_B[tid]

    growth = params.get("growth_g", 0.0)
    for tid, tok in state["tokens"].items():
        dM = tok["E"] - tok["B"]
        tok["M"] = max(0.0, tok["M"] + dM)
    state["Q"] = state["Q"] * (1.0 + growth) if growth > -1.0 else 0.0
    state["N"] = state["N"] * (1.0 + growth) if growth > -1.0 else 0.0
    return state


# ---------------------------------------------------------------------------
# Per-run loop
# ---------------------------------------------------------------------------


def _run_once(
    te: TokenEconomy,
    sampler: Sampler,
    horizon: int,
    config: VerifierConfig | None,
    fm_predicates: dict[tuple[str, str], list[SafetyPredicate]],
    record_trajectories: bool = False,
) -> tuple[
    dict[tuple[str, str], int | None],
    dict[tuple[str, str], list[list[float]]] | None,
]:
    """Run one trajectory.

    Returns:
      • ``first_violation``: period of first violation per (FM, subject)
        pair — None if never violated.
      • ``trajectories``: when ``record_trajectories=True``, a dict
        keyed by (FM, subject) → list-of-per-predicate per-period
        values. Each inner list is length (horizon + 1). ``None``
        when recording is off (so the caller pays no per-period cost).
    """
    state, params = _build_initial_state(te, sampler, config)
    if any(fm_id == "FM2" for fm_id, _ in fm_predicates):
        state["agents"] = spawn_agents(te, sampler)
    first_violation: dict[tuple[str, str], int | None] = {
        k: None for k in fm_predicates
    }
    # Per-predicate trajectory storage. ``trajectories[key][pidx]``
    # is the time series of predicate ``pidx``'s variable for this
    # run. Pre-allocated to avoid append overhead.
    trajectories: dict[tuple[str, str], list[list[float]]] | None = None
    if record_trajectories:
        trajectories = {
            key: [[0.0] * (horizon + 1) for _ in range(len(preds))]
            for key, preds in fm_predicates.items()
        }

    for t in range(horizon + 1):
        for key, preds in fm_predicates.items():
            for pidx, p in enumerate(preds):
                try:
                    value = derived_variable(state, p.variable)
                except (KeyError, ZeroDivisionError):
                    value = float("nan")
                if trajectories is not None:
                    trajectories[key][pidx][t] = value
                if first_violation[key] is None and not _check_safety(p, value):
                    first_violation[key] = t
        state = _step_state(state, params)

    return first_violation, trajectories


def _check_safety(predicate: SafetyPredicate, value: float) -> bool:
    """Same comparison the predicates module uses, but on a
    pre-computed value (so we evaluate once per period when both
    recording the trajectory and checking violation)."""
    import math

    if math.isnan(value):
        return True  # can't evaluate → assume safe
    op = predicate.operator
    t = predicate.threshold
    return (
        (op == ">=" and value >= t)
        or (op == "<=" and value <= t)
        or (op == ">" and value > t)
        or (op == "<" and value < t)
        or (op == "==" and value == t)
    )


# ---------------------------------------------------------------------------
# Wilson confidence interval
# ---------------------------------------------------------------------------


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% confidence interval for proportion k/n.

    Better than normal-approximation when p is near 0 or 1, which is
    exactly the case for typical ABM violation rates."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt((p * (1 - p) / n) + (z * z / (4 * n * n)))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _aggregate_trajectories(
    predicates: list[SafetyPredicate],
    samples_per_predicate: list[list[list[float]]],
    horizon: int,
) -> list[PredicateTrajectory]:
    """Build one ``PredicateTrajectory`` per safety predicate from the
    raw per-run values recorded by ``_run_once``.

    ``samples_per_predicate[pidx]`` is a list of per-run series for
    predicate ``pidx``; each inner series is length (horizon + 1).
    We transpose to per-period samples, then compute mean and
    quartiles per period.
    """
    if not samples_per_predicate:
        return []
    out: list[PredicateTrajectory] = []
    for pidx, predicate in enumerate(predicates):
        if pidx >= len(samples_per_predicate):
            continue
        runs = samples_per_predicate[pidx]
        if not runs:
            continue
        n_runs = len(runs)
        points: list[TrajectoryPoint] = []
        for t in range(horizon + 1):
            # Gather per-period samples and skip NaNs.
            values = [runs[r][t] for r in range(n_runs)]
            clean = [v for v in values if not math.isnan(v)]
            if not clean:
                continue
            mean = sum(clean) / len(clean)
            points.append(
                TrajectoryPoint(
                    t=t,
                    mean=mean,
                    p25=_quantile_float(clean, 0.25),
                    p50=_quantile_float(clean, 0.5),
                    p75=_quantile_float(clean, 0.75),
                    p95=_quantile_float(clean, 0.95),
                )
            )
        out.append(
            PredicateTrajectory(
                variable=predicate.variable,
                operator=predicate.operator,
                threshold=predicate.threshold,
                points=points,
            )
        )
    return out


def _quantile_float(values: list[float], q: float) -> float:
    """Linear-interpolated quantile for a list of floats (vs the
    int-only ``_quantile`` used for time-to-violation periods)."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n == 1:
        return s[0]
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return s[lo] + frac * (s[hi] - s[lo])


def _quantile(values: list[int], q: float) -> float:
    """Linear-interpolated quantile. q ∈ [0, 1]. Returns 0 when empty."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n == 1:
        return float(s[0])
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return s[lo] + frac * (s[hi] - s[lo])


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_simulation(
    te: TokenEconomy,
    verdicts: Sequence[ReachabilityVerdict] | None = None,
    config: SimulationConfig | None = None,
    verifier_config: VerifierConfig | None = None,
) -> SimulationReport:
    """Run the Monte Carlo simulation.

    ``verdicts`` — the verifier's minimal output. Defaults to running
    ``minimal_verdicts(te)`` if not provided.

    Triage rule:
      • SOUND → skipped (verifier proved safe)
      • BROKEN → skipped (no parameter shift can satisfy)
      • NOT_APPLICABLE → skipped
      • INCONCLUSIVE → simulated, but reported with caveat
      • FRAGILE → simulated, full likelihood + time stats

    ``skip_non_fragile=False`` overrides this and simulates everything
    (useful as a sanity check on the verifier's verdicts).
    """
    sim_cfg = config or SimulationConfig()
    sampler = Sampler(seed=sim_cfg.seed)
    if verdicts is None:
        verdicts = minimal_verdicts(te, config=verifier_config)

    # Pick which (FM, subject) pairs to simulate.
    fm_predicates: dict[tuple[str, str], list[SafetyPredicate]] = {}
    skipped: dict[tuple[str, str], str] = {}
    for v in verdicts:
        key = (v.failure_mode, v.subject)
        status = v.structural_status
        if (
            sim_cfg.skip_non_fragile
            and status != StructuralStatus.FRAGILE
            and status != StructuralStatus.INCONCLUSIVE
        ):
            skipped[key] = f"structural_status={status.value} — skipped per triage"
            continue
        if not v.safety_predicates:
            skipped[key] = "no safety_predicates emitted — not simulable"
            continue
        fm_predicates[key] = list(v.safety_predicates)

    # Run N replicates.
    per_run_first_violation: dict[tuple[str, str], list[int]] = {
        k: [] for k in fm_predicates
    }
    per_run_no_violation: dict[tuple[str, str], int] = {k: 0 for k in fm_predicates}
    # Track deployment-time vs dynamic violations separately.
    per_run_violations_at_deploy: dict[tuple[str, str], int] = {
        k: 0 for k in fm_predicates
    }
    per_run_violations_dynamic: dict[tuple[str, str], int] = {
        k: 0 for k in fm_predicates
    }

    # Trajectory sampling cap — at most this many runs contribute to
    # the per-period quantile envelopes. Aggregating quantiles over
    # many runs × many periods × multiple predicates dominates CPU
    # time; capping at 50 keeps the chart's source data fast to
    # produce without hurting envelope quality (50-sample p25/p75
    # estimates are accurate to ±0.05 for any underlying distribution).
    TRAJECTORY_SAMPLE_CAP = 50
    samples_per_key: dict[tuple[str, str], int] = {k: 0 for k in fm_predicates}
    # ``trajectory_samples[key][pidx]`` accumulates per-period-value
    # lists across recorded runs. After the simulation, each list is
    # length ``n_sampled_runs``; we then transpose per period to
    # compute quantiles.
    trajectory_samples: dict[
        tuple[str, str], list[list[list[float]]]
    ] = {
        k: [[] for _ in fm_predicates[k]] for k in fm_predicates
    } if sim_cfg.record_trajectories else {}

    for _ in range(sim_cfg.n_runs):
        # Decide whether THIS run contributes to the trajectory sample.
        do_record = (
            sim_cfg.record_trajectories
            and any(samples_per_key[k] < TRAJECTORY_SAMPLE_CAP for k in samples_per_key)
        )
        result, run_traj = _run_once(
            te,
            sampler,
            sim_cfg.horizon_periods,
            verifier_config,
            fm_predicates,
            record_trajectories=do_record,
        )
        for k, t in result.items():
            if t is None:
                per_run_no_violation[k] += 1
            else:
                per_run_first_violation[k].append(t)
                if t == 0:
                    per_run_violations_at_deploy[k] += 1
                else:
                    per_run_violations_dynamic[k] += 1
        # Accumulate trajectory samples for keys not yet at the cap.
        if run_traj is not None:
            for k, pidx_lists in run_traj.items():
                if samples_per_key[k] >= TRAJECTORY_SAMPLE_CAP:
                    continue
                for pidx, values in enumerate(pidx_lists):
                    trajectory_samples[k][pidx].append(values)
                samples_per_key[k] += 1

    # Aggregate into FMSimulationResult.
    per_fm_results: list[FMSimulationResult] = []
    for v in verdicts:
        key = (v.failure_mode, v.subject)
        if key in skipped:
            per_fm_results.append(
                FMSimulationResult(
                    failure_mode=v.failure_mode,
                    subject=v.subject,
                    structural_status=v.structural_status.value,
                    simulated=False,
                    skip_reason=skipped[key],
                    n_runs=0,
                    n_violations=0,
                    p_violation=0.0,
                    p_violation_ci=(0.0, 0.0),
                    time_to_violation_median=None,
                    time_to_violation_p25=None,
                    time_to_violation_p75=None,
                    time_to_violation_p95=None,
                    predicates=[
                        PredicateOutcome(
                            variable=p.variable,
                            operator=p.operator,
                            threshold=p.threshold,
                        )
                        for p in v.safety_predicates
                    ],
                )
            )
            continue
        if key not in per_run_first_violation:
            continue
        violations = per_run_first_violation[key]
        n_violations = len(violations)
        p_violation = n_violations / sim_cfg.n_runs
        ci = _wilson_ci(n_violations, sim_cfg.n_runs)
        # Restrict time-to-violation to *dynamic* violations (t > 0)
        # so the quartiles describe drift behavior, not deployment-time
        # configuration. Deployment violations are counted separately.
        dynamic_violations = [t for t in violations if t > 0]
        per_fm_results.append(
            FMSimulationResult(
                failure_mode=v.failure_mode,
                subject=v.subject,
                structural_status=v.structural_status.value,
                simulated=True,
                n_runs=sim_cfg.n_runs,
                n_violations=n_violations,
                p_violation=p_violation,
                p_violation_ci=ci,
                n_violations_at_deployment=per_run_violations_at_deploy[key],
                n_violations_dynamic=per_run_violations_dynamic[key],
                time_to_violation_median=(
                    _quantile(dynamic_violations, 0.5)
                    if dynamic_violations
                    else None
                ),
                time_to_violation_p25=(
                    _quantile(dynamic_violations, 0.25)
                    if dynamic_violations
                    else None
                ),
                time_to_violation_p75=(
                    _quantile(dynamic_violations, 0.75)
                    if dynamic_violations
                    else None
                ),
                time_to_violation_p95=(
                    _quantile(dynamic_violations, 0.95)
                    if dynamic_violations
                    else None
                ),
                predicates=[
                    PredicateOutcome(
                        variable=p.variable,
                        operator=p.operator,
                        threshold=p.threshold,
                    )
                    for p in v.safety_predicates
                ],
                predicate_trajectories=(
                    _aggregate_trajectories(
                        v.safety_predicates,
                        trajectory_samples.get(key, []),
                        sim_cfg.horizon_periods,
                    )
                    if sim_cfg.record_trajectories
                    else []
                ),
            )
        )

    return SimulationReport(
        te_name=te.meta.name,
        config=sim_cfg,
        per_fm_results=per_fm_results,
    )
