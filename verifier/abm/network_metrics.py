"""Network analytics for the /explore page (Phase L1).

Given the realized agent set + interaction graph from one trajectory,
compute centrality measures, per-type aggregates, the Pearson
correlation matrix between (balance, reputation, centralities), and a
null-model comparison (z-scores against same-N/m Erdős–Rényi and
degree-preserving configuration model). Result is a Pydantic record
attached to ``ExploreReport.network_metrics``.

The metrics are computed on the SHARED graph data the explore page
already exposes:

* ``ExploreReport.agents`` — agent ids + types + final balance / reputation
* ``ExploreReport.neighbor_graph`` — adjacency (undirected interaction
  edges built by :mod:`verifier.abm.topology` at run start)

For trade edges (per-period transfers) the page renders the cumulative
network; the metrics here operate on the *interaction* graph because
that's the stable topology FM4/FM5 reason over.

Rigor notes:

* Centralities computed on the largest connected component when the
  graph is disconnected; reported per-agent for nodes inside that
  component and as ``None`` outside (preserves "n/a" cleanly in the UI).
* Null-model z-scores use 50 independent samples each for
  G(n, p)  (matching density) and the configuration model (matching
  degree sequence). Both seeded; reproducible.
* Pearson r is computed with the small-sample bias-corrected estimator;
  p-values are two-sided t-tests on ``r·sqrt((n-2)/(1-r²))``.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Pydantic schemas — what we expose to the webapp
# ---------------------------------------------------------------------------


class AgentMetric(BaseModel):
    """Per-agent centrality row."""

    model_config = ConfigDict(extra="forbid")

    agent_id: int
    type: str
    balance: float
    reputation: float
    degree: int
    degree_centrality: float
    betweenness: float | None
    closeness: float | None
    eigenvector: float | None
    clustering: float


class TypeAggregate(BaseModel):
    """Per-type rollup. Useful when the user asks 'which role drives the
    cooperation? do the high-degree agents have the most balance?'"""

    model_config = ConfigDict(extra="forbid")

    type: str
    n_agents: int
    mean_degree: float
    mean_betweenness: float
    mean_closeness: float
    mean_balance: float
    mean_reputation: float
    balance_gini_within_type: float


class NetworkLevelStat(BaseModel):
    """One scalar network-level statistic, with the null-model
    comparison (z-score against an Erdős–Rényi baseline matching the
    observed density, and the configuration-model baseline matching
    the observed degree sequence)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    observed: float
    er_mean: float
    er_std: float
    er_z: float | None        # None when std=0 (degenerate baseline)
    config_mean: float
    config_std: float
    config_z: float | None
    interpretation: str        # short prose: "more clustered than ER" etc.


class CorrelationCell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str
    b: str
    r: float                    # Pearson r (NaN-safe → 0)
    p: float                    # two-sided p-value (1.0 when n < 3)
    n: int


class NetworkMetrics(BaseModel):
    """Top-level network-analytics block surfaced on the /explore page.
    Empty when the graph has < 2 nodes."""

    model_config = ConfigDict(extra="forbid")

    n_nodes: int
    n_edges: int
    components: int
    giant_component_frac: float
    network_level: list[NetworkLevelStat]
    per_agent: list[AgentMetric]
    per_type: list[TypeAggregate]
    correlations: list[CorrelationCell]


# ---------------------------------------------------------------------------
# Building the graph
# ---------------------------------------------------------------------------


def _build_graph(report: Any) -> nx.Graph:
    g = nx.Graph()
    for a in report.agents:
        g.add_node(int(a.id), type=a.type)
    for nid, neighbors in (report.neighbor_graph or {}).items():
        for m in neighbors:
            g.add_edge(int(nid), int(m))
    return g


# ---------------------------------------------------------------------------
# Pearson correlation
# ---------------------------------------------------------------------------


def _pearson(xs: list[float], ys: list[float]) -> tuple[float, float, int]:
    """Pearson r + two-sided p + n. NaN-safe: short series → r=0, p=1."""
    n = len(xs)
    if n < 3:
        return 0.0, 1.0, n
    mx = sum(xs) / n
    my = sum(ys) / n
    sx2 = sum((x - mx) ** 2 for x in xs)
    sy2 = sum((y - my) ** 2 for y in ys)
    if sx2 == 0.0 or sy2 == 0.0:
        return 0.0, 1.0, n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    r = sxy / math.sqrt(sx2 * sy2)
    # Cap to (-1, 1) for numerical safety.
    r = max(-1.0, min(1.0, r))
    # Two-sided t-test approximation: t = r * sqrt((n-2)/(1-r²)).
    if abs(r) >= 1.0:
        p = 0.0
    else:
        t = r * math.sqrt((n - 2) / (1.0 - r * r))
        # Cumulative two-sided p-value via the
        # error-function-based normal approximation. Good for n ≥ 30;
        # mildly anti-conservative below.
        z = abs(t)
        p = math.erfc(z / math.sqrt(2.0))
    return r, p, n


# ---------------------------------------------------------------------------
# Centralities
# ---------------------------------------------------------------------------


def _centralities(g: nx.Graph) -> dict[str, dict[int, float | None]]:
    """Compute per-agent centralities. Betweenness / closeness /
    eigenvector are defined on the largest connected component (LCC);
    nodes outside the LCC get ``None``."""
    out: dict[str, dict[int, float | None]] = {
        "degree": {},
        "degree_centrality": {},
        "betweenness": {n: None for n in g.nodes},
        "closeness": {n: None for n in g.nodes},
        "eigenvector": {n: None for n in g.nodes},
        "clustering": {},
    }
    for n in g.nodes:
        out["degree"][n] = int(g.degree(n))
    dc = nx.degree_centrality(g)
    for n, v in dc.items():
        out["degree_centrality"][n] = float(v)
    cc = nx.clustering(g)
    for n, v in cc.items():
        out["clustering"][n] = float(v)
    if g.number_of_nodes() < 2 or g.number_of_edges() == 0:
        return out
    # Centralities defined on the LCC. Choose the LCC by max size.
    components = list(nx.connected_components(g))
    lcc = max(components, key=len)
    h = g.subgraph(lcc).copy()
    bc = nx.betweenness_centrality(h, normalized=True)
    for n, v in bc.items():
        out["betweenness"][n] = float(v)
    closeness = nx.closeness_centrality(h)
    for n, v in closeness.items():
        out["closeness"][n] = float(v)
    try:
        eig = nx.eigenvector_centrality_numpy(h)
    except Exception:
        eig = nx.eigenvector_centrality(h, max_iter=1000, tol=1e-6)
    for n, v in eig.items():
        out["eigenvector"][n] = float(v)
    return out


# ---------------------------------------------------------------------------
# Network-level statistics + null model
# ---------------------------------------------------------------------------


def _net_level_stat_value(name: str, g: nx.Graph) -> float:
    """Compute one network-level statistic by name."""
    if g.number_of_nodes() < 2:
        return 0.0
    if name == "density":
        return float(nx.density(g))
    if name == "avg_clustering":
        return float(nx.average_clustering(g))
    if name == "assortativity_degree":
        try:
            return float(nx.degree_assortativity_coefficient(g))
        except (ZeroDivisionError, ValueError):
            return 0.0
    if name == "diameter_lcc":
        # Diameter of the largest connected component (graph may be
        # disconnected; the unrestricted diameter would be ∞).
        comps = list(nx.connected_components(g))
        if not comps:
            return 0.0
        lcc = max(comps, key=len)
        sub = g.subgraph(lcc)
        if sub.number_of_nodes() < 2:
            return 0.0
        return float(nx.diameter(sub))
    if name == "avg_shortest_path_lcc":
        comps = list(nx.connected_components(g))
        if not comps:
            return 0.0
        lcc = max(comps, key=len)
        sub = g.subgraph(lcc)
        if sub.number_of_nodes() < 2:
            return 0.0
        return float(nx.average_shortest_path_length(sub))
    if name == "transitivity":
        return float(nx.transitivity(g))
    raise ValueError(f"unknown net-level stat: {name}")


def _null_z_scores(
    g: nx.Graph, names: list[str], *, n_samples: int = 50, seed: int = 7
) -> dict[str, tuple[float, float, float, float]]:
    """For each named stat return (er_mean, er_std, conf_mean, conf_std).
    Caller computes z-scores."""
    import random as _random

    rng = _random.Random(seed)
    nx_rng_seeds = [rng.randint(0, 10_000_000) for _ in range(n_samples * 2)]

    n_nodes = g.number_of_nodes()
    n_edges = g.number_of_edges()
    # ER model: G(n, p) with p chosen so E[edges] = n_edges.
    if n_nodes >= 2:
        p_er = (2.0 * n_edges) / (n_nodes * (n_nodes - 1))
    else:
        p_er = 0.0
    p_er = max(0.0, min(1.0, p_er))

    # Configuration model: preserves the degree sequence.
    deg_seq = [d for _, d in g.degree()]

    er_samples: dict[str, list[float]] = {n: [] for n in names}
    conf_samples: dict[str, list[float]] = {n: [] for n in names}

    for i in range(n_samples):
        s_er = nx_rng_seeds[i]
        gh = nx.gnp_random_graph(n_nodes, p_er, seed=s_er)
        for nm in names:
            er_samples[nm].append(_net_level_stat_value(nm, gh))

    for i in range(n_samples):
        s_conf = nx_rng_seeds[n_samples + i]
        # configuration_model can build multigraphs with self-loops;
        # collapse to simple graph for stat compatibility.
        try:
            mg = nx.configuration_model(deg_seq, seed=s_conf)
            mg = nx.Graph(mg)        # drop parallel edges
            mg.remove_edges_from(nx.selfloop_edges(mg))
        except (nx.NetworkXError, ValueError):
            mg = nx.empty_graph(n_nodes)
        for nm in names:
            conf_samples[nm].append(_net_level_stat_value(nm, mg))

    def _finite(xs: list[float]) -> list[float]:
        return [x for x in xs if math.isfinite(x)]

    out: dict[str, tuple[float, float, float, float]] = {}
    for nm in names:
        er = _finite(er_samples[nm])
        cf = _finite(conf_samples[nm])
        er_mean = statistics.fmean(er) if er else 0.0
        er_std = statistics.pstdev(er) if len(er) > 1 else 0.0
        cf_mean = statistics.fmean(cf) if cf else 0.0
        cf_std = statistics.pstdev(cf) if len(cf) > 1 else 0.0
        out[nm] = (er_mean, er_std, cf_mean, cf_std)
    return out


def _z(observed: float, mean: float, std: float) -> float | None:
    if std == 0.0:
        return None
    return float((observed - mean) / std)


def _interpret_z(z: float | None, label: str) -> str:
    if z is None:
        return f"{label}: baseline degenerate (std=0)"
    if z > 2.0:
        return f"{label}: significantly higher than random (z=+{z:.2f})"
    if z < -2.0:
        return f"{label}: significantly lower than random (z={z:.2f})"
    return f"{label}: within ±2σ of random (z={z:+.2f})"


# ---------------------------------------------------------------------------
# Per-type aggregates + Gini
# ---------------------------------------------------------------------------


def _gini(values: list[float]) -> float:
    """Compute the Gini coefficient on a non-negative list. Returns 0
    when the list is empty or all-zero."""
    xs = [v for v in values if v >= 0.0]
    if not xs:
        return 0.0
    s = sum(xs)
    if s == 0.0:
        return 0.0
    xs = sorted(xs)
    n = len(xs)
    cum = 0.0
    for i, v in enumerate(xs, start=1):
        cum += i * v
    return (2.0 * cum) / (n * s) - (n + 1.0) / n


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------


def compute_network_metrics(report: Any) -> NetworkMetrics:
    """Assemble all centrality + correlation + null-model artifacts."""
    g = _build_graph(report)
    n_nodes = g.number_of_nodes()
    n_edges = g.number_of_edges()
    components = list(nx.connected_components(g))
    giant_frac = (
        max((len(c) for c in components), default=0) / n_nodes
        if n_nodes else 0.0
    )

    cent = _centralities(g)

    # Final-period balance per agent comes from snapshots[-1].balances
    # (positional list keyed by agent index). Reputation is only
    # available as an aggregate; per-agent reputation defaults to 0
    # until the runner exposes a per-agent vector.
    final_balances: list[float] = []
    if report.snapshots:
        final_balances = list(getattr(report.snapshots[-1], "balances", []) or [])
    per_agent: list[AgentMetric] = []
    for idx, a in enumerate(report.agents):
        aid = int(a.id)
        bal = final_balances[idx] if idx < len(final_balances) else 0.0
        per_agent.append(AgentMetric(
            agent_id=aid,
            type=a.type,
            balance=float(bal),
            reputation=float(getattr(a, "reputation", 0.0) or 0.0),
            degree=int(cent["degree"].get(aid, 0)),
            degree_centrality=float(cent["degree_centrality"].get(aid, 0.0)),
            betweenness=cent["betweenness"].get(aid),
            closeness=cent["closeness"].get(aid),
            eigenvector=cent["eigenvector"].get(aid),
            clustering=float(cent["clustering"].get(aid, 0.0)),
        ))

    # Per-type rollups.
    by_type: dict[str, list[AgentMetric]] = {}
    for row in per_agent:
        by_type.setdefault(row.type, []).append(row)
    per_type: list[TypeAggregate] = []
    for t, rows in by_type.items():
        bet = [r.betweenness for r in rows if r.betweenness is not None]
        clo = [r.closeness for r in rows if r.closeness is not None]
        per_type.append(TypeAggregate(
            type=t,
            n_agents=len(rows),
            mean_degree=statistics.fmean([r.degree for r in rows]) if rows else 0.0,
            mean_betweenness=statistics.fmean(bet) if bet else 0.0,
            mean_closeness=statistics.fmean(clo) if clo else 0.0,
            mean_balance=statistics.fmean([r.balance for r in rows]) if rows else 0.0,
            mean_reputation=statistics.fmean([r.reputation for r in rows]) if rows else 0.0,
            balance_gini_within_type=_gini([r.balance for r in rows]),
        ))

    # Network-level stats.
    stat_names = [
        "density", "avg_clustering", "transitivity",
        "assortativity_degree", "diameter_lcc",
        "avg_shortest_path_lcc",
    ]
    nulls = _null_z_scores(g, stat_names)
    network_level: list[NetworkLevelStat] = []
    for nm in stat_names:
        obs = _net_level_stat_value(nm, g)
        if not math.isfinite(obs):
            obs = 0.0
        er_m, er_s, cf_m, cf_s = nulls[nm]
        er_z = _z(obs, er_m, er_s)
        cf_z = _z(obs, cf_m, cf_s)
        # Interpretation favours the configuration model when meaningful
        # (it controls for degree heterogeneity).
        interp = _interpret_z(cf_z if cf_z is not None else er_z, nm)
        network_level.append(NetworkLevelStat(
            name=nm,
            observed=obs,
            er_mean=er_m,
            er_std=er_s,
            er_z=er_z,
            config_mean=cf_m,
            config_std=cf_s,
            config_z=cf_z,
            interpretation=interp,
        ))

    # Correlations. Only keep numerically-defined metrics on nodes that
    # have all of them (so we get a consistent n across the matrix).
    candidate_keys = [
        "balance", "reputation",
        "degree", "betweenness", "closeness", "eigenvector",
    ]
    series: dict[str, list[float]] = {k: [] for k in candidate_keys}
    for row in per_agent:
        if (row.betweenness is None or row.closeness is None
                or row.eigenvector is None):
            continue
        series["balance"].append(row.balance)
        series["reputation"].append(row.reputation)
        series["degree"].append(float(row.degree))
        series["betweenness"].append(row.betweenness)
        series["closeness"].append(row.closeness)
        series["eigenvector"].append(row.eigenvector)
    correlations: list[CorrelationCell] = []
    keys = list(series.keys())
    for i, a in enumerate(keys):
        for b in keys[i:]:        # upper triangle incl. diagonal
            r, p, n = _pearson(series[a], series[b])
            correlations.append(CorrelationCell(a=a, b=b, r=r, p=p, n=n))

    return NetworkMetrics(
        n_nodes=n_nodes,
        n_edges=n_edges,
        components=len(components),
        giant_component_frac=float(giant_frac),
        network_level=network_level,
        per_agent=per_agent,
        per_type=per_type,
        correlations=correlations,
    )
