"""Single-trajectory exploration mode.

The Monte Carlo simulator (``run_simulation``) is the right tool for
likelihood / time-to-violation statistics. It is not the right tool
for *watching* a single token economy evolve — averaging across
hundreds of runs throws away the per-period state that makes a
trajectory legible.

``run_explore`` runs ONE seeded trajectory and records a rich snapshot
per period (agent balances, trade edges, action mix, live Gini /
delegate Gini, φ, τ̄). The /explore page consumes this and renders
the time series + force-directed network so users can scrub through.

Why a separate function (rather than a flag on ``run_simulation``)?
Recording per-period agent-level state is O(periods × agents) — fine
for n_runs=1 / horizon ≤ 200, prohibitive for the Monte Carlo path.
Keeping them apart avoids tempting users to record snapshots across
500 runs and OOM the browser.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from schema import TokenEconomy
from verifier.abm.agents import (
    effective_max_agents,
    spawn_agents,
    tau_bar_from_agents,
)
from verifier.abm.analytics import contributor_fraction, gini
from verifier.abm.delegation import (
    assign_delegates,
    delegate_concentration_gini,
    delegated_weights,
)
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.report import SimulationConfig
from verifier.abm.samplers import Sampler
from verifier.abm.topology import build_neighbor_graph, graph_density


# ---------------------------------------------------------------------------
# Report schema
# ---------------------------------------------------------------------------


class TypeStats(BaseModel):
    """Per-agent-type summary for one period.

    The /explore page draws one chart line per type using these — the
    average-balance trajectory, the action mix per type, etc. All
    aggregates are means over the agents of that type at that period.
    """

    model_config = ConfigDict(extra="forbid")

    type_id: str
    count: int
    avg_balance: float
    median_balance: float
    balance_share_of_total: float  # this type's total balance / population total
    avg_periods_since_action: float  # surrogate for holding time
    avg_degree: float  # mean network degree (0 if WELL_MIXED)
    action_counts: dict[str, int] = Field(default_factory=dict)
    # Phase E3: mean reputation per role at this period. Zero unless the
    # type's UtilityWeights opt into reputation accumulation.
    avg_reputation: float = 0.0


class PeriodSnapshot(BaseModel):
    """One period of trajectory state in the explore mode."""

    model_config = ConfigDict(extra="forbid")

    t: int
    # Live token aggregates.
    M_by_token: dict[str, float] = Field(default_factory=dict)
    E_by_token: dict[str, float] = Field(default_factory=dict)
    B_by_token: dict[str, float] = Field(default_factory=dict)
    # Per-token τ̄ — the coherence panel needs the dict, not just the
    # population-weighted scalar.
    tau_bar_by_token: dict[str, float] = Field(default_factory=dict)
    # Demand / population.
    N: float = 0.0
    Q: float = 0.0
    average_degree: float = 0.0
    # Live participation / concentration.
    phi: float = 0.0
    tau_bar: float = 0.0
    effective_gini: float = 0.0
    delegate_gini: float = 0.0
    # Per-agent balances at this period (length-N).
    balances: list[float] = Field(default_factory=list)
    # Cumulative trade edges at this period: [src_id, dst_id, weight].
    # The /explore page slides the scrubber and only renders edges
    # whose first appearance ≤ scrubber t.
    trade_edges: list[tuple[int, int, float]] = Field(default_factory=list)
    # Action histogram (action_name → fraction of agents this period).
    action_mix: dict[str, float] = Field(default_factory=dict)
    # Vote weight aggregated by delegate this period.
    votes_by_delegate: dict[int, float] = Field(default_factory=dict)
    # Per-agent-type breakdown for this period — the /explore page
    # builds per-role charts from this.
    by_type: list[TypeStats] = Field(default_factory=list)
    # Phase E2/E3 — live observability of new state variables.
    # ``live_agent_count`` is len(agents) directly (separate from the
    # scaled ``N`` since exits drive divergence). ``mean_reputation``
    # is the population mean reputation right after this period's
    # actions executed and before decay kicks in for the next period.
    live_agent_count: int = 0
    mean_reputation: float = 0.0
    # Phase-J enrichment — make the ABM layer's output strictly the
    # most-informative of the three. All optional / defaulted so older
    # consumers stay compatible.
    events_realized: dict[str, float] = Field(default_factory=dict)
    assets: dict[str, dict[str, float]] = Field(default_factory=dict)
    reputation_p10: float = 0.0
    reputation_p50: float = 0.0
    reputation_p90: float = 0.0
    exits_this_period: int = 0
    exits_by_type: dict[str, int] = Field(default_factory=dict)


class HubAgent(BaseModel):
    """One row in the top-hubs table — agents with the largest total
    transfer flow over the horizon."""

    model_config = ConfigDict(extra="forbid")

    agent_id: int
    type: str
    total_flow: float    # sum of transfer weights (in+out)
    final_balance: float


class ExploreSummary(BaseModel):
    """Synthesized findings from one trajectory.

    Computed once at run end so the page doesn't recompute from raw
    snapshots client-side. Surfaces:

    * Per-token cumulative E, B, ΔM and net realized flows.
    * Final-period per-type stats (count, balance share, action profile).
    * Top-N agents by trade-flow (hubs).
    * Human-readable headlines (concentration shift, who dominated, etc.).
    """

    model_config = ConfigDict(extra="forbid")

    horizon: int
    final_n_agents: int
    final_M_by_token: dict[str, float] = Field(default_factory=dict)
    cumulative_E_by_token: dict[str, float] = Field(default_factory=dict)
    cumulative_B_by_token: dict[str, float] = Field(default_factory=dict)
    initial_gini: float = 0.0
    final_gini: float = 0.0
    initial_delegate_gini: float = 0.0
    final_delegate_gini: float = 0.0
    initial_phi: float = 0.0
    final_phi: float = 0.0
    final_tau_bar: float = 0.0
    final_by_type: list[TypeStats] = Field(default_factory=list)
    total_trade_count: int = 0
    total_trade_volume: float = 0.0
    top_hubs: list[HubAgent] = Field(default_factory=list)
    headlines: list[str] = Field(default_factory=list)
    # Phase E summaries — surfaced as tiles + headline on the /explore
    # page. Zero/no-op when Phase E features are off for the run.
    initial_agent_count: int = 0
    final_agent_count: int = 0
    agents_exited: int = 0
    final_mean_reputation: float = 0.0
    peak_mean_reputation: float = 0.0


class AgentInfo(BaseModel):
    """Static agent metadata — declared once per run, referenced by
    every snapshot via ``id``."""

    model_config = ConfigDict(extra="forbid")

    id: int
    type: str
    role: str | None = None
    delegate_of: int
    is_delegate: bool


class ExploreReport(BaseModel):
    """Single-trajectory output for the /explore page."""

    model_config = ConfigDict(extra="forbid")

    te_name: str
    config: SimulationConfig
    n_agents: int
    topology: str
    graph_density: float
    agents: list[AgentInfo] = Field(default_factory=list)
    # Adjacency of the initial interaction graph. Empty for WELL_MIXED
    # (which the client renders as a complete-graph hint instead).
    neighbor_graph: dict[int, list[int]] = Field(default_factory=dict)
    snapshots: list[PeriodSnapshot] = Field(default_factory=list)
    # Type ids declared on the spec (preserves declaration order so the
    # frontend can assign a stable color per role).
    type_ids: list[str] = Field(default_factory=list)
    # Synthesized run-level findings — populated at the end of
    # ``run_explore``.
    summary: ExploreSummary | None = None
    # Phase L1 — network analytics (centralities, correlations, null-model
    # z-scores). Populated post-trajectory by
    # :func:`verifier.abm.network_metrics.compute_network_metrics`.
    network_metrics: Any | None = None
    # Phase L1 — coherence panel: verifier verdicts × ABM-realized
    # trajectories per FM.
    fm_coherence: list[dict[str, Any]] = Field(default_factory=list)
    # Phase M.18 — flow-graph payload (spec + realised overlay).
    # Built post-trajectory so /explore can render the visualisation
    # directly from the report without a second round-trip.
    flow_graph: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_explore(
    te: TokenEconomy,
    sim_config: SimulationConfig | None = None,
    verifier_config: Any = None,
) -> ExploreReport:
    """Run one seeded trajectory and return the per-period snapshot
    series. The simulator's ``n_runs`` field is ignored — explore is
    always single-trajectory by design."""
    cfg = sim_config or SimulationConfig(horizon_periods=200)
    sampler = Sampler(seed=cfg.seed)
    cap = effective_max_agents(1, cfg.horizon_periods, override=cfg.max_agents)

    state, params = _build_initial_state(
        te, sampler, verifier_config, effective_agent_cap=cap
    )
    if te.participants.agent_types:
        state["agents"] = spawn_agents(te, sampler, max_agents=cap)
        params["neighbor_graph"] = build_neighbor_graph(
            te.participants, state["agents"], sampler
        )
        assign_delegates(
            state["agents"], te.governance.vote_weighting, sampler
        )

    agents = state.get("agents", [])
    n_agents = len(agents)
    delegate_ids = {a["id"] for a in agents if a.get("delegate_of") == a["id"]}
    agent_infos = [
        AgentInfo(
            id=a["id"],
            type=a["type"],
            role=(
                params.get("agent_types_by_id", {})
                .get(a["type"])
                .role.value
                if params.get("agent_types_by_id", {}).get(a["type"])
                and params.get("agent_types_by_id", {}).get(a["type"]).role
                else None
            ),
            delegate_of=a.get("delegate_of", a["id"]),
            is_delegate=a["id"] in delegate_ids,
        )
        for a in agents
    ]

    neighbor_graph = params.get("neighbor_graph")
    if neighbor_graph is None:
        neighbor_dict: dict[int, list[int]] = {}
    else:
        neighbor_dict = {aid: list(neigh) for aid, neigh in neighbor_graph.items()}

    snapshots: list[PeriodSnapshot] = []
    snapshots.append(_snapshot(state, t=0, neighbor_graph=neighbor_graph))

    for _ in range(cfg.horizon_periods):
        state = _step_state(state, params)
        snapshots.append(
            _snapshot(
                state,
                t=state["t"],
                # Phase B may have rebuilt the graph mid-run (population
                # events). Pull the current graph from params each step.
                neighbor_graph=params.get("neighbor_graph"),
                last_action_counts_by_type=state.get(
                    "last_action_counts_by_type"
                ),
            )
        )

    summary = _build_summary(snapshots, agent_infos)

    report = ExploreReport(
        te_name=te.meta.name,
        config=cfg,
        n_agents=n_agents,
        topology=te.participants.topology.value,
        graph_density=graph_density(neighbor_graph, n_agents),
        agents=agent_infos,
        neighbor_graph=neighbor_dict,
        snapshots=snapshots,
        type_ids=[at.id for at in te.participants.agent_types],
        summary=summary,
    )
    # Phase L1: post-trajectory analytics. Wrapped in a try/except so a
    # downstream library hiccup never breaks the page — a missing
    # network_metrics block is benign for the existing charts.
    try:
        from verifier.abm.network_metrics import compute_network_metrics
        report = report.model_copy(update={
            "network_metrics": compute_network_metrics(report),
        })
    except Exception:
        pass
    try:
        from verifier.abm.coherence import compute_fm_coherence
        report = report.model_copy(update={
            "fm_coherence": compute_fm_coherence(te, report, verifier_config),
        })
    except Exception:
        pass
    # Phase M.18 — flow-graph spec + realised overlay.
    try:
        from verifier.abm.flow_graph import build_flow_graph, annotate_with_realised
        spec_graph = build_flow_graph(te)
        flow_payload = annotate_with_realised(spec_graph, report)
        report = report.model_copy(update={"flow_graph": flow_payload})
    except Exception:
        pass
    return report


def _snapshot(
    state: dict[str, Any],
    t: int,
    neighbor_graph: dict[int, tuple[int, ...]] | None = None,
    last_action_counts_by_type: dict[str, dict[str, int]] | None = None,
) -> PeriodSnapshot:
    """Snapshot the current state into a PeriodSnapshot record.

    Trade edges are emitted as a flat list — the /explore page handles
    cumulative-vs-period rendering on the client side."""
    agents = state.get("agents", [])
    balances = [float(a.get("balance", 0.0)) for a in agents]

    trade_dict = state.get("trade_edges", {}) or {}
    trade_edges = [
        (int(src), int(dst), float(w))
        for (src, dst), w in trade_dict.items()
    ]

    tokens = state.get("tokens", {})
    M_by_token = {tid: float(tok.get("M", 0.0)) for tid, tok in tokens.items()}
    E_by_token = {tid: float(tok.get("E", 0.0)) for tid, tok in tokens.items()}
    B_by_token = {tid: float(tok.get("B", 0.0)) for tid, tok in tokens.items()}

    # tau_bar in state is per-token — surface the population-weighted
    # average for the chart.
    tau_per_token = state.get("tau_bar", {}) or {}
    if tau_per_token:
        tau_bar_value = sum(tau_per_token.values()) / len(tau_per_token)
    else:
        tau_bar_value = 0.0

    # action_mix at this period (recorded by the engine).
    am = state.get("last_action_mix", {}) or {}

    # votes_by_delegate is reset only when we explicitly clear it;
    # we surface what the engine accumulated. The /explore page treats
    # zero values as inactive delegates.
    vbd_raw = state.get("votes_by_delegate", {}) or {}
    vbd = {int(k): float(v) for k, v in vbd_raw.items()}

    by_type = _per_type_stats(
        agents, t, neighbor_graph, last_action_counts_by_type
    )

    # Phase-J enrichment — reputation quantiles + per-event firings +
    # asset state + exit cohort.
    reps = sorted(float(a.get("reputation", 0.0)) for a in agents)
    def _q(p: float) -> float:
        if not reps:
            return 0.0
        idx = min(len(reps) - 1, int(p * len(reps)))
        return reps[idx]
    events_realized = {
        str(k): float(v) for k, v in (state.get("events_realized") or {}).items()
    }
    asset_state = {}
    for aid, entry in (state.get("assets") or {}).items():
        asset_state[str(aid)] = {
            "count": float(entry.get("count", 0.0)),
            "created": float(entry.get("created", 0.0)),
            "consumed": float(entry.get("consumed", 0.0)),
        }
    exits_this = int(state.get("_exits_this_period", 0))
    exits_by_type = {
        str(k): int(v) for k, v in (state.get("_exits_by_type") or {}).items()
    }

    return PeriodSnapshot(
        t=t,
        M_by_token=M_by_token,
        E_by_token=E_by_token,
        B_by_token=B_by_token,
        tau_bar_by_token={
            str(k): float(v) for k, v in tau_per_token.items()
        },
        N=float(state.get("N", 0.0)),
        Q=float(state.get("Q", 0.0)),
        average_degree=float(state.get("average_degree", 0.0)),
        phi=float(state.get("phi", contributor_fraction(agents, t))),
        tau_bar=float(tau_bar_value),
        effective_gini=float(state.get("effective_gini", 0.0)),
        delegate_gini=float(state.get("delegate_gini", 0.0)),
        balances=balances,
        trade_edges=trade_edges,
        action_mix={str(k): float(v) for k, v in am.items()},
        votes_by_delegate=vbd,
        by_type=by_type,
        live_agent_count=len(agents),
        mean_reputation=float(state.get("mean_reputation", 0.0)),
        events_realized=events_realized,
        assets=asset_state,
        reputation_p10=_q(0.10),
        reputation_p50=_q(0.50),
        reputation_p90=_q(0.90),
        exits_this_period=exits_this,
        exits_by_type=exits_by_type,
    )


def _per_type_stats(
    agents: list[dict[str, Any]],
    t: int,
    neighbor_graph: dict[int, tuple[int, ...]] | None,
    last_action_counts_by_type: dict[str, dict[str, int]] | None,
) -> list[TypeStats]:
    """Compute per-AgentType.id averages over the current population.

    ``last_action_counts_by_type[type_id][action]`` is the engine's
    histogram of how many agents of each type chose each action this
    period. Built by ``run_explore`` and threaded in so the snapshot
    doesn't need to re-derive it.
    """
    if not agents:
        return []
    # Bucket agents by type.
    buckets: dict[str, list[dict[str, Any]]] = {}
    for a in agents:
        buckets.setdefault(a["type"], []).append(a)
    total_balance = sum(a.get("balance", 0.0) for a in agents) or 1.0

    out: list[TypeStats] = []
    for type_id, members in buckets.items():
        bals = [float(a.get("balance", 0.0)) for a in members]
        n = len(members)
        avg_balance = sum(bals) / n
        median_balance = _median(bals)
        type_total = sum(bals)
        balance_share = type_total / total_balance
        avg_since = sum(
            max(0, t - int(a.get("last_action", 0))) for a in members
        ) / n
        if neighbor_graph is not None:
            degrees = [len(neighbor_graph.get(a["id"], ())) for a in members]
            avg_degree = sum(degrees) / n
        else:
            # WELL_MIXED → no graph; effectively every agent connects to
            # every other one.
            avg_degree = float(len(agents) - 1)
        ac = dict((last_action_counts_by_type or {}).get(type_id, {}))
        reps = [float(a.get("reputation", 0.0)) for a in members]
        avg_rep = sum(reps) / n if n > 0 else 0.0
        out.append(
            TypeStats(
                type_id=type_id,
                count=n,
                avg_balance=avg_balance,
                median_balance=median_balance,
                balance_share_of_total=balance_share,
                avg_periods_since_action=avg_since,
                avg_degree=avg_degree,
                action_counts=ac,
                avg_reputation=avg_rep,
            )
        )
    return out


def _build_summary(
    snapshots: list[PeriodSnapshot],
    agents_meta: list[AgentInfo],
) -> ExploreSummary:
    """Synthesize a textual + structured run summary the /explore page
    surfaces above the charts.

    Cumulative E / B per token are integrated from per-period state;
    headlines are short text lines a reader can scan in 5 seconds.
    """
    if not snapshots:
        return ExploreSummary(horizon=0, final_n_agents=0)

    first = snapshots[0]
    last = snapshots[-1]

    token_ids = list(last.M_by_token.keys())
    cumulative_E = {tid: 0.0 for tid in token_ids}
    cumulative_B = {tid: 0.0 for tid in token_ids}
    for snap in snapshots:
        for tid in token_ids:
            cumulative_E[tid] += snap.E_by_token.get(tid, 0.0)
            cumulative_B[tid] += snap.B_by_token.get(tid, 0.0)

    total_trade_volume = sum(w for _, _, w in last.trade_edges)
    total_trade_count = len(last.trade_edges)

    # Aggregate hub flow from the final cumulative trade edges. The
    # /explore page's trade graph is undirected, so we credit both ends.
    flow_by_agent: dict[int, float] = {}
    type_by_id = {a.id: a.type for a in agents_meta}
    final_balance_by_id = {
        aid: last.balances[idx]
        for idx, aid in enumerate(a.id for a in agents_meta)
        if idx < len(last.balances)
    }
    for src, dst, w in last.trade_edges:
        flow_by_agent[src] = flow_by_agent.get(src, 0.0) + w
        flow_by_agent[dst] = flow_by_agent.get(dst, 0.0) + w
    top_hubs_raw = sorted(flow_by_agent.items(), key=lambda kv: -kv[1])[:5]
    top_hubs = [
        HubAgent(
            agent_id=aid,
            type=type_by_id.get(aid, "?"),
            total_flow=flow,
            final_balance=final_balance_by_id.get(aid, 0.0),
        )
        for aid, flow in top_hubs_raw
    ]

    # Phase E summary aggregates: track exits + peak reputation across
    # the run. Peak helps surface "reputation grew then collapsed"
    # patterns the final snapshot alone would hide.
    initial_count = first.live_agent_count or len(first.balances)
    final_count = last.live_agent_count or len(last.balances)
    agents_exited = max(0, initial_count - final_count)
    peak_reputation = max((s.mean_reputation for s in snapshots), default=0.0)

    headlines = _headlines(
        first, last, cumulative_E, cumulative_B, top_hubs,
        agents_exited=agents_exited,
        peak_reputation=peak_reputation,
        final_reputation=last.mean_reputation,
    )

    return ExploreSummary(
        horizon=last.t,
        final_n_agents=len(last.balances),
        final_M_by_token=last.M_by_token,
        cumulative_E_by_token=cumulative_E,
        cumulative_B_by_token=cumulative_B,
        initial_gini=first.effective_gini,
        final_gini=last.effective_gini,
        initial_delegate_gini=first.delegate_gini,
        final_delegate_gini=last.delegate_gini,
        initial_phi=first.phi,
        final_phi=last.phi,
        final_tau_bar=last.tau_bar,
        final_by_type=last.by_type,
        total_trade_count=total_trade_count,
        total_trade_volume=total_trade_volume,
        top_hubs=top_hubs,
        headlines=headlines,
        initial_agent_count=initial_count,
        final_agent_count=final_count,
        agents_exited=agents_exited,
        final_mean_reputation=last.mean_reputation,
        peak_mean_reputation=peak_reputation,
    )


def _headlines(
    first: PeriodSnapshot,
    last: PeriodSnapshot,
    cumulative_E: dict[str, float],
    cumulative_B: dict[str, float],
    top_hubs: list[HubAgent],
    *,
    agents_exited: int = 0,
    peak_reputation: float = 0.0,
    final_reputation: float = 0.0,
) -> list[str]:
    """Five-second-readable bullet lines summarizing what happened."""
    lines: list[str] = []

    # Token supply change.
    for tid, m1 in last.M_by_token.items():
        m0 = first.M_by_token.get(tid, m1)
        delta = m1 - m0
        e = cumulative_E.get(tid, 0.0)
        b = cumulative_B.get(tid, 0.0)
        if abs(delta) >= 1.0:
            pct = (delta / m0 * 100) if m0 else 0.0
            sign = "+" if delta >= 0 else "-"
            lines.append(
                f"Supply of {tid}: {m0:,.0f} → {m1:,.0f} "
                f"({sign}{abs(delta):,.0f}, {sign}{abs(pct):.1f}%). "
                f"Cumulative emission {e:,.0f}, burn {b:,.0f}."
            )

    # Concentration.
    if abs(last.effective_gini - first.effective_gini) >= 0.02:
        direction = "rose" if last.effective_gini > first.effective_gini else "fell"
        lines.append(
            f"Balance Gini {direction}: "
            f"{first.effective_gini:.3f} → {last.effective_gini:.3f} "
            f"(higher = more concentration)."
        )
    else:
        lines.append(
            f"Balance Gini ≈ {last.effective_gini:.3f} "
            f"(stable throughout the run)."
        )
    if abs(last.delegate_gini - last.effective_gini) >= 0.02:
        lines.append(
            f"Delegate-power Gini = {last.delegate_gini:.3f} vs "
            f"balance Gini {last.effective_gini:.3f}: delegation "
            f"{'amplified' if last.delegate_gini > last.effective_gini else 'softened'} "
            "voting concentration."
        )

    # Participation φ.
    if abs(last.phi - first.phi) >= 0.05:
        d = "rose" if last.phi > first.phi else "fell"
        lines.append(
            f"Active contributor fraction φ {d}: "
            f"{first.phi:.2f} → {last.phi:.2f}."
        )

    # Per-type final standings.
    if last.by_type:
        sorted_types = sorted(
            last.by_type, key=lambda t: -t.balance_share_of_total
        )
        top = sorted_types[0]
        lines.append(
            f"At end, type '{top.type_id}' (count {top.count}) holds "
            f"{top.balance_share_of_total * 100:.1f}% of balances; "
            f"avg balance {top.avg_balance:,.2f}."
        )

    # Trade activity.
    if top_hubs:
        h = top_hubs[0]
        lines.append(
            f"Most-connected agent: #{h.agent_id} (type '{h.type}', "
            f"total flow {h.total_flow:,.2f}, final balance "
            f"{h.final_balance:,.2f})."
        )

    # Phase E — exits and reputation. Only emit when the run actually
    # exercised the feature (count > 0 / reputation > 0); otherwise
    # the headline strip stays focused on what changed.
    if agents_exited > 0:
        lines.append(
            f"{agents_exited} agent(s) exited the system during the run. "
            f"Live population shrank from "
            f"{first.live_agent_count or len(first.balances)} to "
            f"{last.live_agent_count or len(last.balances)}."
        )
    if peak_reputation > 0.0:
        peaked = peak_reputation > final_reputation * 1.1
        if peaked:
            lines.append(
                f"Mean reputation peaked at {peak_reputation:.2f} and "
                f"ended at {final_reputation:.2f} — late-run decay or "
                f"churn outpaced new contributions."
            )
        else:
            lines.append(
                f"Mean reputation grew to {final_reputation:.2f} by run end "
                f"(peak {peak_reputation:.2f})."
            )

    return lines


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])
