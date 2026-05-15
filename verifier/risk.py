"""Risk stratification layer (Simulator.pdf §4–§6).

Complementary to the SMT pass/fail surface. Each verdict is augmented
with a `RiskLevel` evaluated at the midpoint of the declared parameter
ranges. The whole report is summarized with an `OverallRiskScore`
weighted per Simulator.pdf §6.

The midpoint evaluation is pure Python — no Z3. This is deliberate:
the formal layer answers "does there exist a violation in the box";
the risk layer answers "at typical parameter values, how bad is it".
Both surfaces are useful and they are reported side by side.

Computation order (Simulator.pdf §7.1):

1. Per-token midpoint rates (E_own, B_own, plus cross-token contributions).
2. Per-FM risk band from those midpoint values.
3. Overall weighted score.
"""

from __future__ import annotations

import math
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from schema import (
    AsymptoticClass,
    AsymptoticFamily,
    CrossTokenAction,
    FlowCoupling,
    NumberRange,
    Token,
    TokenEconomy,
)
from verifier.elicitation import CoherenceIssue
from verifier.failure_modes.base import RiskLevel, Status, Verdict


# ---------------------------------------------------------------------------
# Midpoint helpers (pure Python, no Z3)
# ---------------------------------------------------------------------------


def _mid(rng: NumberRange | None, *, default: float = 0.0) -> float:
    if rng is None:
        return default
    return (rng.min + rng.max) / 2.0


def _ac_midpoint_rate(ac: AsymptoticClass | None, *, periods_horizon: float = 52.0) -> float:
    """Pure-Python midpoint rate for an AsymptoticClass.

    Mirrors `verifier.asymptotic.average_rate_per_period` but returns a
    float instead of a Z3 expression. Used by the risk-stratification
    layer which evaluates conditions at typical parameter values.
    """
    if ac is None:
        return 0.0
    H = periods_horizon
    fam = ac.family
    if fam == AsymptoticFamily.CONSTANT:
        return _mid(ac.parameter_ranges.get("c"))
    if fam == AsymptoticFamily.BOUNDED_RANGE:
        return _mid(ac.bounds)
    if fam == AsymptoticFamily.LINEAR:
        a = _mid(ac.parameter_ranges.get("a"))
        b = _mid(ac.parameter_ranges.get("b"))
        return a * (H / 2.0) + b
    if fam == AsymptoticFamily.POLYNOMIAL:
        k = ac.degree if ac.degree is not None else 2
        a = _mid(ac.parameter_ranges.get("a"))
        b = _mid(ac.parameter_ranges.get("b"))
        return a * (H ** k / (k + 1)) + b
    if fam == AsymptoticFamily.LOG:
        a = _mid(ac.parameter_ranges.get("a"))
        b = _mid(ac.parameter_ranges.get("b"))
        return a * (math.log(H + 1) - 1) + b
    if fam == AsymptoticFamily.EXPONENTIAL:
        a = _mid(ac.parameter_ranges.get("a"))
        b = _mid(ac.parameter_ranges.get("b", NumberRange(min=1.0, max=1.0)))
        steps = max(1, int(H / 4))
        return a * (b ** steps)
    if fam == AsymptoticFamily.UNSPECIFIED:
        return _mid(ac.parameter_ranges.get("value"))
    return 0.0


def _rule_midpoint_rate(rule, *, periods_horizon: float = 52.0) -> float:
    # K5: DSL-only rules — use a deterministic mid-of-range evaluation
    # by binding each ParamDecl to the midpoint of its declared range.
    if getattr(rule.function, "expression", None) is not None:
        from verifier.expr_eval import EvalEnv, evaluate
        params = {}
        for p in (rule.function.parameters or []):
            params[p.name] = (p.range.min + p.range.max) / 2.0
        env = EvalEnv(
            state={"t": periods_horizon / 2.0},
            params=params,
            consts={"horizon": periods_horizon},
            agents=[], tokens=[], events=[], assets=[],
        )
        try:
            fn = float(evaluate(rule.function.expression, env))
        except Exception:
            fn = 0.0
        if not math.isfinite(fn):
            fn = 0.0
    else:
        fn = _ac_midpoint_rate(rule.function.asymptotic_class, periods_horizon=periods_horizon)
    if rule.trigger.event_frequency is not None:
        freq = _ac_midpoint_rate(rule.trigger.event_frequency, periods_horizon=periods_horizon)
        return fn * freq
    return fn


def _own_E_midpoint(token: Token) -> float:
    return sum(_rule_midpoint_rate(r) for r in token.emission_rules)


def _own_B_midpoint(token: Token) -> float:
    return sum(_rule_midpoint_rate(r) for r in token.burn_rules)


def _token_E_midpoint(te: TokenEconomy, token: Token) -> float:
    """E(t) at midpoint, including cross-token MINT contributions."""
    e = _own_E_midpoint(token)
    for flow in te.cross_token_flows:
        if flow.target_token != token.id or flow.target_action != CrossTokenAction.MINT:
            continue
        e += _flow_midpoint_rate(te, flow)
    return e


def _token_B_midpoint(te: TokenEconomy, token: Token) -> float:
    b = _own_B_midpoint(token)
    for flow in te.cross_token_flows:
        if flow.target_token != token.id or flow.target_action != CrossTokenAction.BURN:
            continue
        b += _flow_midpoint_rate(te, flow)
    return b


def _flow_midpoint_rate(te: TokenEconomy, flow) -> float:
    if flow.coupling == FlowCoupling.PROPORTIONAL_TO_SOURCE:
        ratio = _mid(flow.coupling_ratio)
        src = next((t for t in te.tokens if t.id == flow.source_token), None)
        if src is None:
            return 0.0
        return ratio * _own_E_midpoint(src)
    return _ac_midpoint_rate(flow.amount)


def _tau_bar_midpoint(te: TokenEconomy) -> float | None:
    if not te.participants.agent_types:
        return None
    total = 0.0
    weight_sum = 0.0
    for ag in te.participants.agent_types:
        w = ag.balance_share if ag.balance_share is not None else ag.fraction
        tau = _mid(ag.expected_holding_time.expected_periods)
        total += w * tau
        weight_sum += w
    return total / weight_sum if weight_sum > 0 else None


def _aggregate_K(te: TokenEconomy) -> float | None:
    ks = [t.offer_variety_K for t in te.tokens if t.offer_variety_K is not None]
    if not ks:
        return None
    return sum(_mid(k) for k in ks) / len(ks)


# ---------------------------------------------------------------------------
# Per-FM risk-band evaluators
# ---------------------------------------------------------------------------


def _risk_for_fm1(te: TokenEconomy, verdict: Verdict) -> RiskLevel:
    """FM1 ros = (E - B) / Q at midpoint. Bands per Simulator.pdf §4.1."""
    if verdict.status in (Status.NOT_APPLICABLE, Status.INCONCLUSIVE):
        return RiskLevel.NOT_APPLICABLE
    token = next((t for t in te.tokens if t.id == verdict.subject), None)
    if token is None:
        return RiskLevel.NOT_APPLICABLE
    E = _token_E_midpoint(te, token)
    B = _token_B_midpoint(te, token)
    Q = _mid(te.participants.expected_Q)
    if Q <= 0:
        return RiskLevel.RED_CRITICAL  # no transaction volume
    if E <= 0:
        return RiskLevel.GREEN  # no emission
    ros = max(0.0, (E - B) / Q)
    if ros <= 1.0:
        return RiskLevel.GREEN
    if ros <= 1.5:
        return RiskLevel.AMBER
    if ros <= 2.5:
        return RiskLevel.RED
    return RiskLevel.RED_CRITICAL


def _risk_for_fm2(te: TokenEconomy, verdict: Verdict) -> RiskLevel:
    """FM2 τ̄ at midpoint. Bands per Simulator.pdf §4.2.

    The Simulator uses days; our IR uses periods (1 period ≈ 1 week).
    Convert: τ̄_days = τ̄_periods × 7. Bands then carry over as in §4.2.
    """
    if verdict.status in (Status.NOT_APPLICABLE, Status.INCONCLUSIVE):
        return RiskLevel.NOT_APPLICABLE
    if verdict.status == Status.PASS_AS_INTENDED:
        # NFR6 = circulate_fast — the user has marked low τ̄ as intended.
        return RiskLevel.GREEN
    tau_bar = _tau_bar_midpoint(te)
    if tau_bar is None:
        return RiskLevel.NOT_APPLICABLE
    tau_days = tau_bar * 7.0
    if tau_days > 14.0:
        return RiskLevel.GREEN
    if tau_days > 7.0:
        return RiskLevel.GREEN_BORDERLINE
    if tau_days > 3.0:
        return RiskLevel.AMBER
    if tau_days > 1.0:
        return RiskLevel.RED
    return RiskLevel.RED_CRITICAL


def _risk_for_fm3(te: TokenEconomy, verdict: Verdict) -> RiskLevel:
    """FM3 ρ = B/E at midpoint. Bands per Simulator.pdf §4.3."""
    if verdict.status in (Status.NOT_APPLICABLE, Status.INCONCLUSIVE):
        return RiskLevel.NOT_APPLICABLE
    token = next((t for t in te.tokens if t.id == verdict.subject), None)
    if token is None:
        return RiskLevel.NOT_APPLICABLE
    E = _token_E_midpoint(te, token)
    B = _token_B_midpoint(te, token)
    if E <= 0:
        return RiskLevel.GREEN  # no emission, ρ undefined → safe
    if B <= 0:
        return RiskLevel.RED_CRITICAL  # no burn at all
    rho = B / E
    if rho >= 1.0:
        return RiskLevel.GREEN
    if rho >= 0.5:
        return RiskLevel.AMBER
    return RiskLevel.RED


def _risk_for_fm4(te: TokenEconomy, verdict: Verdict) -> RiskLevel:
    """FM4 — band on whether each clause holds at midpoint."""
    if verdict.status in (Status.NOT_APPLICABLE, Status.INCONCLUSIVE):
        return RiskLevel.NOT_APPLICABLE
    if verdict.status == Status.PASS:
        return RiskLevel.GREEN
    # Use the counterexample if the verdict is FAIL.
    if verdict.counterexample is None:
        return RiskLevel.AMBER
    pv = verdict.counterexample.parameter_values
    contrib_failed = pv.get("phi_K", 1.0) < pv.get("d", 0.0)
    monitor_failed = pv.get("gamma_S", 1.0) <= pv.get("T_minus_R_normalized", 0.0)
    phi_required = pv.get("d", 0.0) / pv.get("K", 1.0) if pv.get("K", 0.0) > 0 else 0.0
    if phi_required > 0.80:
        return RiskLevel.RED_CRITICAL
    if contrib_failed and monitor_failed:
        return RiskLevel.RED
    if contrib_failed or monitor_failed:
        return RiskLevel.AMBER
    return RiskLevel.GREEN


def _risk_for_fm5(te: TokenEconomy, verdict: Verdict) -> RiskLevel:
    """FM5 rcm = N / N* at midpoint. Bands per Simulator.pdf §4.5."""
    if verdict.status in (Status.NOT_APPLICABLE, Status.INCONCLUSIVE):
        return RiskLevel.NOT_APPLICABLE
    N = _mid(te.participants.count_N)
    K = _aggregate_K(te)
    d = _mid(te.participants.average_demand_d)
    if K is None or N <= 0:
        return RiskLevel.NOT_APPLICABLE
    n_star = 2 * K * d + 1
    if n_star <= 0:
        return RiskLevel.GREEN
    rcm = N / n_star
    if rcm < 0.5:
        return RiskLevel.RED_CRITICAL
    if rcm < 1.0:
        return RiskLevel.RED
    if rcm < 1.2:
        return RiskLevel.AMBER
    if rcm < 2.0:
        return RiskLevel.GREEN_BORDERLINE
    return RiskLevel.GREEN


def _risk_for_fm6(te: TokenEconomy, verdict: Verdict) -> RiskLevel:
    """FM6 Γ at midpoint. Bands per Simulator.pdf §4.6."""
    if verdict.status in (Status.NOT_APPLICABLE, Status.INCONCLUSIVE):
        return RiskLevel.NOT_APPLICABLE
    if verdict.status == Status.PASS_AS_INTENDED:
        return RiskLevel.GREEN
    rules = te.governance.rule_structure
    if not rules:
        return RiskLevel.NOT_APPLICABLE
    # Same unilateral set as the FM6 module
    from schema import ControllingActor

    UNILATERAL = {ControllingActor.SINGLE_ENTITY, ControllingActor.COMMITTEE}
    unilateral = sum(1 for actor in rules.values() if actor in UNILATERAL)
    total = len(rules)
    gamma = unilateral / total
    if gamma <= 0.30:
        return RiskLevel.GREEN
    if gamma <= 0.50:
        return RiskLevel.GREEN_BORDERLINE
    if gamma <= 0.80:
        return RiskLevel.AMBER
    return RiskLevel.RED


_FM_RISK_FUNCS = {
    "FM1": _risk_for_fm1,
    "FM2": _risk_for_fm2,
    "FM3": _risk_for_fm3,
    "FM4": _risk_for_fm4,
    "FM5": _risk_for_fm5,
    "FM6": _risk_for_fm6,
}


def attach_risk_levels(te: TokenEconomy, verdicts: list[Verdict]) -> None:
    """Mutate `verdicts` in place to populate `risk_level` for each."""
    for v in verdicts:
        fm_id = v.failure_mode.split(":")[0].strip()
        func = _FM_RISK_FUNCS.get(fm_id)
        if func is None:
            continue
        try:
            v.risk_level = func(te, v)
        except Exception:
            v.risk_level = RiskLevel.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Overall risk score (Simulator.pdf §6)
# ---------------------------------------------------------------------------


_RISK_SCORE = {
    RiskLevel.GREEN: 0,
    RiskLevel.GREEN_BORDERLINE: 1,
    RiskLevel.AMBER: 2,
    RiskLevel.RED: 3,
    RiskLevel.RED_CRITICAL: 4,
    RiskLevel.NOT_APPLICABLE: 0,
}

_FM_WEIGHTS = {
    "FM1": 1.5,
    "FM2": 1.0,
    "FM3": 1.5,
    "FM4": 1.0,
    "FM5": 1.0,
    "FM6": 0.5,
}

# Smax: 4 (RED_CRITICAL) × sum-of-weights + 7 (max contradictions) ≈ 33
_S_MAX = 4 * sum(_FM_WEIGHTS.values()) + 7.0


class OverallRiskBand(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


# Fix B — the prose labels ("broadly sound", "redesign required",
# etc.) over-claim relative to the underlying score's reliability.
# We keep the band enum for clients that key on it, but the report
# message is now empty by default — the verdict cards plus the
# pass/fail counts are the honest summary.
_OVERALL_BAND_MESSAGES = {
    OverallRiskBand.LOW: "",
    OverallRiskBand.MODERATE: "",
    OverallRiskBand.HIGH: "",
    OverallRiskBand.CRITICAL: "",
}


class OverallRiskScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weighted: float
    normalized_pct: float
    band: OverallRiskBand
    message: str
    per_fm_max: dict[str, str] = Field(default_factory=dict)
    contradiction_penalty: float = 0.0


def _effective_band(v: Verdict) -> RiskLevel:
    """Combine the formal `status` with the midpoint `risk_level`.

    The midpoint band alone (Simulator.pdf §4) misses the SMT layer's
    finding: a FAIL verdict means **there exists** a parameter assignment
    in the box that violates the condition. That is a real concern even
    when the *typical* value passes, so we floor a FAIL at AMBER.

    INCONCLUSIVE = "we cannot decide" → at least GREEN_BORDERLINE.
    PASS_AS_INTENDED + GREEN midpoint = the user has explicitly opted in
    via NFR or role; report it as GREEN.
    """
    midpoint = v.risk_level
    if v.status == Status.FAIL:
        # Floor at AMBER; if midpoint is already worse, keep that.
        if _RISK_SCORE[midpoint] < _RISK_SCORE[RiskLevel.AMBER]:
            return RiskLevel.AMBER
        return midpoint
    if v.status == Status.INCONCLUSIVE:
        if _RISK_SCORE[midpoint] < _RISK_SCORE[RiskLevel.GREEN_BORDERLINE]:
            return RiskLevel.GREEN_BORDERLINE
        return midpoint
    return midpoint


def compute_overall_score(
    verdicts: list[Verdict], coherence: list[CoherenceIssue]
) -> OverallRiskScore:
    """Compute the weighted overall risk score per Simulator.pdf §6.

    Per-FM band: take the **worst** band across all verdicts for that
    FM. The band combines `status` and `risk_level` via
    `_effective_band` so a FAIL never reads as "low risk" just because
    its midpoint happens to be GREEN.
    """
    per_fm_band: dict[str, RiskLevel] = {}
    for v in verdicts:
        fm_id = v.failure_mode.split(":")[0].strip()
        if fm_id not in _FM_WEIGHTS:
            continue
        eff = _effective_band(v)
        cur = per_fm_band.get(fm_id, RiskLevel.GREEN)
        if _RISK_SCORE[eff] > _RISK_SCORE[cur]:
            per_fm_band[fm_id] = eff
    weighted = 0.0
    for fm_id, band in per_fm_band.items():
        weighted += _RISK_SCORE[band] * _FM_WEIGHTS[fm_id]
    contra = sum(1.0 if i.severity == "error" else 0.5 for i in coherence)
    weighted += contra
    pct = min(100.0, (weighted / _S_MAX) * 100.0) if _S_MAX > 0 else 0.0
    if pct <= 20:
        band = OverallRiskBand.LOW
    elif pct <= 40:
        band = OverallRiskBand.MODERATE
    elif pct <= 60:
        band = OverallRiskBand.HIGH
    else:
        band = OverallRiskBand.CRITICAL
    return OverallRiskScore(
        weighted=round(weighted, 4),
        normalized_pct=round(pct, 2),
        band=band,
        message=_OVERALL_BAND_MESSAGES[band],
        per_fm_max={k: v.value for k, v in per_fm_band.items()},
        contradiction_penalty=round(contra, 2),
    )
