"""ABM simulation report — the per-FM likelihood + time-to-violation
output, plus a human-readable renderer.

The report is the second half of the verifier ↔ ABM bridge: where the
verifier produces categorical reachability (SOUND / FRAGILE / BROKEN),
the ABM produces frequentist statistics (P(violation), Wilson CIs,
time-to-violation quartiles). Both are intended to be read together —
the verifier tells you whether the cliff exists, the ABM tells you
how often you walk off it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SimulationConfig(BaseModel):
    """Tuning knobs for the Monte Carlo loop. Defined here (alongside
    the report) so the report can reference it cleanly without a
    circular import with the engine module."""

    model_config = ConfigDict(extra="forbid")

    n_runs: int = Field(default=500, ge=1, le=100_000)
    horizon_periods: int = Field(default=260, ge=1, le=10_000)
    seed: int | None = None
    # Cap per-FM simulation when the verdict is SOUND / BROKEN. The
    # default is True — sound FMs are proved safe by the verifier and
    # broken ones can't pass; both waste cycles. Override to False
    # for exhaustive sanity-check runs.
    skip_non_fragile: bool = True
    # Opt-in: record per-period values of each safety predicate's
    # variable across runs, then aggregate into p25/p50/p75/p95/mean
    # per period for the trajectory chart. Off by default — recording
    # roughly doubles simulation time and inflates report size.
    record_trajectories: bool = False
    # Phase-A ABM agent count cap. ``None`` ⇒ derive from
    # ``DEFAULT_MAX_AGENTS`` capped by the workload budget (so very
    # large n_runs × horizon doesn't push the inner loop into hours).
    # Pass an explicit value to override entirely (useful for tests).
    max_agents: int | None = Field(default=None, ge=1, le=10_000)


class TrajectoryPoint(BaseModel):
    """One time-slice of a predicate-variable trajectory.

    The ABM evaluates each safety predicate's ``variable`` per
    period across many runs; ``TrajectoryPoint`` summarizes the
    distribution of values at one period (mean + percentiles)."""

    model_config = ConfigDict(extra="forbid")

    t: int
    mean: float
    p25: float
    p50: float
    p75: float
    p95: float


class PredicateTrajectory(BaseModel):
    """Time series of one safety predicate's variable + the threshold
    it's compared against. Rendered as a line chart with a fill
    envelope between p25 and p75, p5/p95 outer bands, and a
    horizontal threshold reference."""

    model_config = ConfigDict(extra="forbid")

    variable: str
    operator: str
    threshold: float
    points: list[TrajectoryPoint] = Field(default_factory=list)


class PredicateOutcome(BaseModel):
    """Snapshot of a predicate exposed in the report. Lets the user
    see which safety conditions the simulation actually evaluated."""

    model_config = ConfigDict(extra="forbid")

    variable: str
    operator: str
    threshold: float


class FMSimulationResult(BaseModel):
    """Per-FM × per-subject result.

    When ``simulated=False``, the FM was skipped (SOUND / BROKEN /
    NOT_APPLICABLE / no predicates). ``skip_reason`` says why. The
    other numeric fields are zero / None.

    When ``simulated=True``:

      • ``p_violation`` ∈ [0, 1] — fraction of runs where the FM
        violated at some point in the horizon.
      • ``p_violation_ci`` — Wilson 95% confidence interval.
      • ``time_to_violation_*`` — distribution stats over the subset
        of runs that did violate. None when the FM never violated.
    """

    model_config = ConfigDict(extra="forbid")

    failure_mode: str
    subject: str
    # Echoed from the verifier's verdict so the user reads both layers.
    structural_status: str

    simulated: bool
    skip_reason: str | None = None

    n_runs: int = 0
    n_violations: int = 0
    p_violation: float = 0.0
    p_violation_ci: tuple[float, float] = (0.0, 0.0)

    time_to_violation_median: float | None = None
    time_to_violation_p25: float | None = None
    time_to_violation_p75: float | None = None
    time_to_violation_p95: float | None = None

    # Distinguish "the sampled parameters already violate at
    # deployment" (t=0) from "violation emerges during operation"
    # (t > 0). The first is a *sampling* signal; the second is a
    # *dynamics* signal. Reported separately so users can tell whether
    # the FM is a launch-time configuration problem or a long-run
    # drift problem.
    n_violations_at_deployment: int = 0  # violated at t = 0
    n_violations_dynamic: int = 0  # violated at t > 0

    predicates: list[PredicateOutcome] = Field(default_factory=list)

    # One per safety predicate; populated only when
    # ``SimulationConfig.record_trajectories`` is set. Each entry holds
    # quantile envelopes per period — the chart's source data.
    predicate_trajectories: list[PredicateTrajectory] = Field(default_factory=list)


class SimulationReport(BaseModel):
    """Whole-system report. Includes the config the run used so a
    reader can reproduce."""

    model_config = ConfigDict(extra="forbid")

    te_name: str
    config: SimulationConfig
    per_fm_results: list[FMSimulationResult] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_text(self) -> str:
        """A compact, scannable table + per-FM block. Designed to be
        useful in a terminal without further tooling.

        Two violation columns:
          P(deploy) — fraction of runs that violate at t=0 (sampled
                      parameters already violate the predicate).
          P(dynamic) — fraction of runs that *become* unsafe during
                      the horizon (initially safe → violation by t>0).
        """
        lines = []
        lines.append(f"ABM simulation report for: {self.te_name}")
        lines.append(
            f"  config: n_runs={self.config.n_runs}, "
            f"horizon={self.config.horizon_periods} periods, "
            f"seed={self.config.seed}"
        )
        lines.append("")
        header = (
            f"{'FM':<5}{'subject':<12}{'verifier':<16}"
            f"{'P(deploy)':<12}{'P(dynamic)':<13}{'t_med':<7}{'t_p95':<7}"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for r in self.per_fm_results:
            if not r.simulated:
                p_deploy = "—"
                p_dyn = "—"
                t_med = "—"
                t_p95 = "—"
            else:
                p_deploy_v = r.n_violations_at_deployment / max(r.n_runs, 1)
                p_dyn_v = r.n_violations_dynamic / max(r.n_runs, 1)
                p_deploy = f"{p_deploy_v:.0%}"
                p_dyn = f"{p_dyn_v:.0%}"
                t_med = (
                    f"{r.time_to_violation_median:.0f}"
                    if r.time_to_violation_median is not None
                    and r.time_to_violation_median > 0
                    else "—"
                )
                t_p95 = (
                    f"{r.time_to_violation_p95:.0f}"
                    if r.time_to_violation_p95 is not None
                    and r.time_to_violation_p95 > 0
                    else "—"
                )
            lines.append(
                f"{r.failure_mode:<5}"
                f"{r.subject:<12}"
                f"{r.structural_status:<16}"
                f"{p_deploy:<12}"
                f"{p_dyn:<13}"
                f"{t_med:<7}"
                f"{t_p95:<7}"
            )

        # Narrative block — what the user should read.
        narrative = self._narrative()
        if narrative:
            lines.append("")
            lines.append("Headline:")
            for line in narrative:
                lines.append(f"  • {line}")

        return "\n".join(lines)

    def _narrative(self) -> list[str]:
        """One-line takeaway per FM. Surfaces the *complementarity*
        between layers: each line names what the ABM added on top of
        the verifier's categorical verdict, framed around the
        deployment-vs-dynamic split."""
        out = []
        for r in self.per_fm_results:
            if not r.simulated:
                if r.structural_status == "broken":
                    out.append(
                        f"{r.failure_mode}[{r.subject}]: verifier says "
                        f"BROKEN — no parameter assignment in the box "
                        f"satisfies the FM. The ABM cannot rescue a "
                        f"structurally-broken design; redesign first."
                    )
                continue
            n = max(r.n_runs, 1)
            p_deploy = r.n_violations_at_deployment / n
            p_dynamic = r.n_violations_dynamic / n
            if r.p_violation == 0.0:
                out.append(
                    f"{r.failure_mode}[{r.subject}]: verifier flagged "
                    f"as {r.structural_status}, but 0/{r.n_runs} "
                    f"sampled runs violated. The verifier's flagged "
                    f"corner is in the box but the declared "
                    f"distribution rarely reaches it."
                )
            elif p_deploy >= 0.5 and p_dynamic < 0.05:
                out.append(
                    f"{r.failure_mode}[{r.subject}]: violates "
                    f"AT DEPLOYMENT in {p_deploy:.0%} of runs — the "
                    f"sampled parameters often land in the unsafe "
                    f"region from the start. This is a configuration "
                    f"problem, not a dynamics one: tighten the "
                    f"declared parameter ranges to exclude the unsafe "
                    f"corner."
                )
            elif p_dynamic >= 0.5:
                out.append(
                    f"{r.failure_mode}[{r.subject}]: violates "
                    f"DYNAMICALLY in {p_dynamic:.0%} of runs "
                    f"(initially safe, becomes unsafe by period "
                    f"{r.time_to_violation_median:.0f} on median). "
                    f"This is a drift problem — the system enters the "
                    f"unsafe region during operation. Likely fix: "
                    f"add a corrective mechanism that triggers before "
                    f"the drift escalates."
                )
            elif p_deploy >= 0.05 and p_dynamic >= 0.05:
                out.append(
                    f"{r.failure_mode}[{r.subject}]: mixed — "
                    f"{p_deploy:.0%} of runs unsafe at deployment, "
                    f"{p_dynamic:.0%} drift into the unsafe region "
                    f"during operation. Both the configuration and "
                    f"dynamics are contributing factors."
                )
            else:
                out.append(
                    f"{r.failure_mode}[{r.subject}]: violates in "
                    f"{r.p_violation:.0%} of runs. Possible but not "
                    f"dominant; the design fails in specific corners "
                    f"of the parameter box."
                )
        return out


