"""Phase M — declared-flow graph (Cytoscape JSON builder).

Pure read of the TE-IR: no simulation needed. The /api/flow-graph
endpoint serves this; the form's Stage-3.2 preview and the /explore
page's flow-graph card both consume the same payload.

Design priorities (in order):

1. **Compact**. Every wallet × token combination would explode the
   graph on real TEs (5 roles × 3 tokens × 4 edge kinds = 60 edges
   per token), so we aggregate:

   * One ``MintPool`` per token, one ``BurnSink`` per token — never
     per-rule.
   * One ``RoleWallet`` per (agent_type × token), but a wallet is
     emitted only when that role is *eligible* to hold the token
     (i.e. it can EARN, REDEEM, TRANSFER, or VOTE on it).
   * Per-rule labels collapse into a single edge label with the
     count, e.g. ``Emission · 2 rules · const 2-5 + linear 0-1000``.

2. **Readable**. Edge labels are short (≤ 30 chars). Long rate
   spec / DSL source lives in ``tooltip`` for hover. Edge style
   encodes whether the rule is unconditional (solid), conditional
   (dashed), DSL-driven (double), or peg-defensive (dotted).

3. **Core info only**. We don't draw an edge for every theoretical
   pathway — only those the schema actually declares. Empty paths
   (no burn rule → no Burn edge) are silent, not stubbed out.

The graph is a NetworkX ``DiGraph`` internally and serialised to
Cytoscape's ``{"elements": {"nodes": [...], "edges": [...]}}`` shape
on the way out.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from schema import (
    AsymptoticClass,
    AsymptoticFamily,
    CrossTokenAction,
)


# ---------------------------------------------------------------------------
# Compact rate-label rendering
# ---------------------------------------------------------------------------


def _fmt_range(r) -> str:
    if r is None:
        return "?"
    if r.min == r.max:
        return f"{r.min:g}"
    return f"{r.min:g}–{r.max:g}"


def _ac_label(ac: AsymptoticClass | None) -> str:
    """One-line short rate label. Truncated to ≤ 30 chars."""
    if ac is None:
        return "—"
    fam = ac.family
    pr = ac.parameter_ranges or {}
    if fam == AsymptoticFamily.CONSTANT:
        return f"const {_fmt_range(pr.get('c'))}"
    if fam == AsymptoticFamily.BOUNDED_RANGE:
        return f"bnd {_fmt_range(ac.bounds)}"
    if fam == AsymptoticFamily.LINEAR:
        a = pr.get("a"); b = pr.get("b")
        return f"a·t+b (a={_fmt_range(a)}, b={_fmt_range(b)})"[:30]
    if fam == AsymptoticFamily.POLYNOMIAL:
        return f"poly^{ac.degree or 2}"
    if fam == AsymptoticFamily.SUBLINEAR_ROOT:
        return f"√[{ac.degree or 2}]t"
    if fam == AsymptoticFamily.LOG:
        return "log"
    if fam == AsymptoticFamily.EXPONENTIAL:
        return "exp"
    if fam == AsymptoticFamily.UNSPECIFIED:
        return "unspec"
    return fam.value


def _rule_label(rule) -> str:
    """One-line label for a Rule. Picks expression hint when DSL is used."""
    fs = rule.function
    if getattr(fs, "expression", None) is not None:
        return "DSL expr"
    return _ac_label(fs.asymptotic_class)


def _rule_style(rule) -> str:
    """Visual edge style key. solid · dashed · double · dotted."""
    has_cond = bool(getattr(rule.trigger, "conditions", None)) \
               or bool(getattr(rule, "regimes", None))
    if getattr(rule.function, "expression", None) is not None:
        return "double"
    if has_cond:
        return "dashed"
    return "solid"


def _aggregate_rule_label(rules: list, max_rules: int = 2) -> str:
    """Collapse N rules into ``N rules · summary``. Compact for cards."""
    if not rules:
        return ""
    if len(rules) == 1:
        return _rule_label(rules[0])
    head = "+".join(_rule_label(r) for r in rules[:max_rules])
    if len(rules) > max_rules:
        head += f" +{len(rules) - max_rules}"
    return f"{len(rules)}× ({head})"


def _aggregate_rule_style(rules: list) -> str:
    """If any rule is DSL → double; any conditional → dashed; else solid."""
    styles = {_rule_style(r) for r in rules}
    if "double" in styles:
        return "double"
    if "dashed" in styles:
        return "dashed"
    return "solid"


# ---------------------------------------------------------------------------
# Eligibility — which role-wallets to draw
# ---------------------------------------------------------------------------


def _agent_can_earn(at) -> bool:
    if not at.action_set:
        return True   # role defaults include EARN
    return any(a.value == "earn" for a in at.action_set)


def _agent_can_redeem(at) -> bool:
    if not at.action_set:
        return True
    return any(a.value == "redeem" for a in at.action_set)


def _agent_is_governance(at) -> bool:
    return at.role is not None and at.role.value == "governance_only"


# ---------------------------------------------------------------------------
# Diagnostics — silent surfaces of declared-vs-realisable inconsistencies
# ---------------------------------------------------------------------------


def _diagnostics(te, g: nx.DiGraph) -> list[dict]:
    """Return a small list of structured issues. Each item has
    ``kind``, ``severity`` (info / warn / error), ``message``, and
    optional ``node_id`` / ``edge_id`` for hover-highlighting on the
    UI side."""
    out: list[dict] = []
    known_events = {e.id for e in te.events}

    # Event references must resolve.
    for t in te.tokens:
        for i, r in enumerate(t.emission_rules):
            eid = r.trigger.event_id
            if eid is not None and eid not in known_events:
                out.append({
                    "kind": "dangling_event",
                    "severity": "error",
                    "message": (
                        f"Token {t.id} emission rule #{i} references "
                        f"event '{eid}' which is not in the events catalog."
                    ),
                })

    # Sink-only tokens (have burn rules but no mint path).
    for t in te.tokens:
        has_own_mint = bool(t.emission_rules)
        has_xt_mint = any(
            f.target_token == t.id and f.target_action == CrossTokenAction.MINT
            for f in te.cross_token_flows
        )
        if t.burn_rules and not (has_own_mint or has_xt_mint):
            out.append({
                "kind": "sink_only_token",
                "severity": "warn",
                "message": (
                    f"Token {t.id} declares burn rules but no mint path "
                    f"(neither own emission_rules nor an incoming "
                    f"cross_token_flow MINT). Supply will drain to zero."
                ),
                "node_id": f"burn:{t.id}",
            })

    # Source-only tokens (have emission but no burn / cross-token sink).
    for t in te.tokens:
        has_own_burn = bool(t.burn_rules)
        has_xt_burn = any(
            f.target_token == t.id and f.target_action == CrossTokenAction.BURN
            for f in te.cross_token_flows
        )
        if t.emission_rules and not (has_own_burn or has_xt_burn):
            out.append({
                "kind": "source_only_token",
                "severity": "warn",
                "message": (
                    f"Token {t.id} mints but never burns — FM1/FM3 will "
                    f"flag this. Add a burn rule or a cross_token_flow "
                    f"BURN sink."
                ),
                "node_id": f"mint:{t.id}",
            })

    # Assets without any payment path.
    for a in te.non_tokenized_assets:
        if not a.referenced_tokens:
            out.append({
                "kind": "unfundable_asset",
                "severity": "warn",
                "message": (
                    f"Asset '{a.id}' has no referenced_tokens — agents "
                    f"have nothing to redeem it with."
                ),
                "node_id": f"asset:{a.id}",
            })

    # Isolated components.
    if g.number_of_nodes() > 0:
        comps = list(nx.weakly_connected_components(g))
        if len(comps) > 1:
            # Sort by size, surface only the smaller ones as "isolated".
            comps_sorted = sorted(comps, key=len, reverse=True)
            for c in comps_sorted[1:]:
                if not c:
                    continue
                sample = sorted(c)[:3]
                out.append({
                    "kind": "isolated_component",
                    "severity": "info",
                    "message": (
                        f"Disconnected sub-graph of {len(c)} node(s): "
                        f"{', '.join(sample)}{'…' if len(c) > 3 else ''}. "
                        f"No flow path connects it to the main economy."
                    ),
                })
    return out


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_flow_graph(te) -> dict[str, Any]:
    """Build the Cytoscape JSON payload for the declared flow graph.

    Returns a dict with:

    * ``elements`` → ``{"nodes": [...], "edges": [...]}`` (Cytoscape format)
    * ``diagnostics`` → list of declared-spec issues
    * ``summary`` → counts (n_nodes, n_edges, components, tokens, assets)
    """
    g = nx.DiGraph()

    # --- Nodes ---------------------------------------------------------------
    for t in te.tokens:
        g.add_node(f"mint:{t.id}", kind="MintPool", label=f"⊕ mint {t.id}",
                   token=t.id)
        g.add_node(f"burn:{t.id}", kind="BurnSink", label=f"⊖ burn {t.id}",
                   token=t.id)

    # Wallet nodes only when the role is eligible to interact with the
    # token. Drops the "every role × every token" combinatorial blow-up.
    for t in te.tokens:
        for at in te.participants.agent_types:
            eligible = (
                _agent_can_earn(at) or _agent_can_redeem(at)
                or _agent_is_governance(at)
            )
            if not eligible:
                continue
            kind = "AdminWallet" if _agent_is_governance(at) else "RoleWallet"
            g.add_node(
                f"wallet:{at.id}@{t.id}",
                kind=kind, role=at.id, token=t.id,
                label=f"{at.id}",
            )

    for a in te.non_tokenized_assets:
        g.add_node(f"asset:{a.id}", kind="AssetInventory",
                   asset=a.id, label=f"◆ {a.id}")

    # Event nodes only for events actually referenced by ≥ 1 rule.
    referenced_events: set[str] = set()
    for t in te.tokens:
        for r in (t.emission_rules + t.burn_rules):
            eid = r.trigger.event_id
            if eid:
                referenced_events.add(eid)
    for ev in te.events:
        if ev.id in referenced_events:
            g.add_node(f"event:{ev.id}", kind="Event", event=ev.id,
                       label=f"◇ {ev.id}",
                       conditions=[c.model_dump() for c in ev.conditions])

    # --- Edges ---------------------------------------------------------------

    # Emission: mint:T → each eligible wallet, aggregated per wallet.
    for t in te.tokens:
        if not t.emission_rules:
            continue
        label = _aggregate_rule_label(t.emission_rules)
        style = _aggregate_rule_style(t.emission_rules)
        for at in te.participants.agent_types:
            if not _agent_can_earn(at):
                continue
            wallet = f"wallet:{at.id}@{t.id}"
            if not g.has_node(wallet):
                continue
            g.add_edge(
                f"mint:{t.id}", wallet,
                kind="Emission", style=style,
                label=label,
                tooltip=_full_rules_tooltip(t.emission_rules, t.id),
                rules=len(t.emission_rules),
            )

    # Burn: each eligible wallet → burn:T, aggregated per wallet.
    for t in te.tokens:
        if not t.burn_rules:
            continue
        label = _aggregate_rule_label(t.burn_rules)
        style = _aggregate_rule_style(t.burn_rules)
        for at in te.participants.agent_types:
            if not _agent_can_redeem(at):
                continue
            wallet = f"wallet:{at.id}@{t.id}"
            if not g.has_node(wallet):
                continue
            g.add_edge(
                wallet, f"burn:{t.id}",
                kind="Burn", style=style,
                label=label,
                tooltip=_full_rules_tooltip(t.burn_rules, t.id),
                rules=len(t.burn_rules),
            )

    # CrossTokenFlow: burn:src → mint:tgt (or burn:tgt for BURN action).
    for f in te.cross_token_flows:
        rate_label = _ac_label(f.amount)
        if f.target_action == CrossTokenAction.MINT:
            src = f"burn:{f.source_token}"
            tgt = f"mint:{f.target_token}"
        elif f.target_action == CrossTokenAction.BURN:
            src = f"burn:{f.source_token}"
            tgt = f"burn:{f.target_token}"
        else:
            # TRANSFER: source wallet → target wallet (any). Aggregate at
            # mint:tgt as a single representative arrow for compactness.
            src = f"mint:{f.source_token}"
            tgt = f"mint:{f.target_token}"
        if g.has_node(src) and g.has_node(tgt):
            g.add_edge(
                src, tgt,
                kind="CrossTokenFlow",
                style="solid" if f.coupling.value == "independent" else "dashed",
                label=f"× {rate_label}",
                tooltip=(
                    f"{f.source_token} → {f.target_token} "
                    f"({f.target_action.value}); "
                    f"coupling={f.coupling.value}; "
                    f"rate={rate_label}"
                ),
            )

    # Redemption: each wallet eligible to redeem the asset's
    # referenced_tokens → asset, plus the token leg to burn:T.
    for a in te.non_tokenized_assets:
        cost = _fmt_range(a.redemption_cost) if a.redemption_cost else "—"
        for tok in a.referenced_tokens:
            for at in te.participants.agent_types:
                if not _agent_can_redeem(at):
                    continue
                wallet = f"wallet:{at.id}@{tok}"
                if not g.has_node(wallet):
                    continue
                # Asset leg.
                g.add_edge(
                    wallet, f"asset:{a.id}",
                    kind="Redemption-AssetLeg", style="solid",
                    label=f"cost {cost}",
                    tooltip=(
                        f"Agents of type '{at.id}' spend {tok} to acquire "
                        f"'{a.id}' at cost {cost}/unit."
                    ),
                )

    # Event-drives edges: event → emission/burn rule pool. Drawn as
    # subtle annotation edges (style=dotted) so they don't drown the
    # main flow paths. Only emit when the event actually drives ≥ 1
    # rule.
    for t in te.tokens:
        for r in t.emission_rules:
            eid = r.trigger.event_id
            if eid and g.has_node(f"event:{eid}") and g.has_node(f"mint:{t.id}"):
                g.add_edge(
                    f"event:{eid}", f"mint:{t.id}",
                    kind="EventDrives", style="dotted",
                    label="drives",
                )
        for r in t.burn_rules:
            eid = r.trigger.event_id
            if eid and g.has_node(f"event:{eid}") and g.has_node(f"burn:{t.id}"):
                g.add_edge(
                    f"event:{eid}", f"burn:{t.id}",
                    kind="EventDrives", style="dotted",
                    label="drives",
                )

    # --- Prune dangling wallets (compactness). A wallet with zero
    # in-degree AND zero out-degree adds visual noise without
    # information. Keep mint / burn / asset / event nodes even when
    # isolated — they signal "declared but unused" which is itself a
    # diagnostic worth seeing.
    to_remove = [
        n for n in g.nodes
        if g.nodes[n].get("kind") in {"RoleWallet", "AdminWallet"}
        and g.in_degree(n) == 0 and g.out_degree(n) == 0
    ]
    g.remove_nodes_from(to_remove)

    # --- Diagnostics (must run after graph build for component check) ----
    diagnostics = _diagnostics(te, g)

    # --- Serialise to Cytoscape JSON -------------------------------------
    elements_nodes = [
        {"data": {"id": n, **g.nodes[n]}}
        for n in sorted(g.nodes)
    ]
    elements_edges = [
        {"data": {
            "id": f"{u}->{v}",
            "source": u, "target": v,
            **g.edges[u, v],
        }}
        for u, v in g.edges
    ]
    return {
        "elements": {"nodes": elements_nodes, "edges": elements_edges},
        "diagnostics": diagnostics,
        "summary": {
            "n_nodes": g.number_of_nodes(),
            "n_edges": g.number_of_edges(),
            "components": nx.number_weakly_connected_components(g),
            "tokens": [t.id for t in te.tokens],
            "assets": [a.id for a in te.non_tokenized_assets],
            "events": sorted(referenced_events),
        },
    }


def annotate_with_realised(spec_payload: dict, report: Any) -> dict:
    """Phase M.18 — overlay realised ABM flow magnitudes on the spec
    graph.

    Each edge in the returned payload gets:

    * ``realised`` — cumulative magnitude over the trajectory
    * ``realised_label`` — short string for the edge label
    * ``expected`` — declared rate × horizon (mean point estimate)
    * ``diff_class`` — one of:

        - ``"unused"``: realised ≈ 0; edge never fired
        - ``"matched"``: within ½×–2× of expected
        - ``"under"`` : realised < ½ × expected
        - ``"over"``  : realised > 2 × expected

    Attribution heuristics (transparent, intentionally coarse):

    * **Emission**: cumulative emission per token, split equally among
      eligible wallets. Crude but consistent.
    * **Burn**: cumulative burn per token, split equally among
      redeeming wallets.
    * **CrossTokenFlow**: cumulative source-side burn × declared rate
      midpoint.
    * **Redemption-AssetLeg**: per-asset cumulative ``consumed`` split
      equally among redeeming wallets for that token.
    * **EventDrives**: realised firings (sum of ``events_realized`` per
      period).

    The function is pure: takes a spec payload + report, returns a new
    payload. Doesn't mutate ``spec_payload``.
    """
    snapshots = list(getattr(report, "snapshots", []) or [])
    if not snapshots:
        return spec_payload
    horizon = max(1, len(snapshots) - 1)
    # Build per-token cumulative emission / burn from the M, B series.
    # M[end] - M[0] + cum_burn ≈ cum_emission; cum_burn comes from
    # B_by_token at end (since engine accumulates B over the run).
    initial_M = snapshots[0].M_by_token or {}
    final_M = snapshots[-1].M_by_token or {}
    final_B = snapshots[-1].B_by_token or {}
    cum_burn = {tid: float(final_B.get(tid, 0.0)) for tid in final_B}
    cum_emission = {
        tid: max(0.0, float(final_M.get(tid, 0.0))
                       - float(initial_M.get(tid, 0.0))
                       + cum_burn.get(tid, 0.0))
        for tid in (final_M.keys() | initial_M.keys())
    }
    # Per-event realised firings (total over the run).
    event_total: dict[str, float] = {}
    for snap in snapshots:
        for eid, v in (snap.events_realized or {}).items():
            event_total[eid] = event_total.get(eid, 0.0) + float(v)
    # Per-asset cumulative consumed.
    asset_consumed: dict[str, float] = {}
    if snapshots[-1].assets:
        for aid, entry in snapshots[-1].assets.items():
            asset_consumed[aid] = float(entry.get("consumed", 0.0))

    # Count edges per (token, kind) for equal splits.
    edges = list(spec_payload.get("elements", {}).get("edges", []))
    emission_per_tok: dict[str, int] = {}
    burn_per_tok: dict[str, int] = {}
    redem_per_tok_asset: dict[tuple[str, str], int] = {}
    for e in edges:
        d = e["data"]
        if d["kind"] == "Emission":
            tok = d["target"].split("@")[-1]
            emission_per_tok[tok] = emission_per_tok.get(tok, 0) + 1
        elif d["kind"] == "Burn":
            tok = d["source"].split("@")[-1]
            burn_per_tok[tok] = burn_per_tok.get(tok, 0) + 1
        elif d["kind"] == "Redemption-AssetLeg":
            tok = d["source"].split("@")[-1]
            aid = d["target"].split("asset:", 1)[-1]
            redem_per_tok_asset[(tok, aid)] = \
                redem_per_tok_asset.get((tok, aid), 0) + 1

    # Build the annotated payload.
    new_edges = []
    for e in edges:
        d = dict(e["data"])
        kind = d["kind"]
        realised = 0.0
        if kind == "Emission":
            tok = d["target"].split("@")[-1]
            n = max(1, emission_per_tok.get(tok, 1))
            realised = cum_emission.get(tok, 0.0) / n
        elif kind == "Burn":
            tok = d["source"].split("@")[-1]
            n = max(1, burn_per_tok.get(tok, 1))
            realised = cum_burn.get(tok, 0.0) / n
        elif kind == "CrossTokenFlow":
            # Source side is burn:X (or mint:X for TRANSFER). The
            # realised flow ≈ cumulative source burn × declared label
            # rate isn't easily back-solved from the report alone, so
            # use cumulative target emission attributable to the cross
            # flow: target's total emission minus its own emission rules.
            tgt = (d["target"].split("mint:", 1)[-1]
                   if d["target"].startswith("mint:")
                   else d["target"].split("burn:", 1)[-1])
            realised = cum_emission.get(tgt, 0.0) if d["target"].startswith("mint:") \
                       else cum_burn.get(tgt, 0.0)
            # Approximation: share the realised mass with own-token
            # emission rules; cross-token contribution is at most this.
        elif kind == "Redemption-AssetLeg":
            tok = d["source"].split("@")[-1]
            aid = d["target"].split("asset:", 1)[-1]
            n = max(1, redem_per_tok_asset.get((tok, aid), 1))
            realised = asset_consumed.get(aid, 0.0) / n
        elif kind == "EventDrives":
            eid = d["source"].split("event:", 1)[-1]
            realised = event_total.get(eid, 0.0)
        # Estimate expected. Pull off the label heuristic: "const 2-5"
        # mean ≈ 3.5; "linear" rough mean over horizon ≈ midpoint × H/2.
        expected = _expected_estimate(d.get("label", ""), horizon)
        # Diff classification.
        diff_class = _diff_class(realised, expected)
        d["realised"] = realised
        d["expected"] = expected
        d["realised_label"] = _short_num(realised)
        d["diff_class"] = diff_class
        new_edges.append({"data": d})

    out = dict(spec_payload)
    out["elements"] = {
        "nodes": spec_payload["elements"]["nodes"],
        "edges": new_edges,
    }
    out["realised_summary"] = {
        "horizon": horizon,
        "cumulative_emission_by_token": cum_emission,
        "cumulative_burn_by_token": cum_burn,
        "event_firings": event_total,
        "asset_consumed": asset_consumed,
    }
    return out


def _short_num(x: float) -> str:
    if x is None:
        return "—"
    ax = abs(x)
    if ax >= 1_000_000:
        return f"{x/1_000_000:.1f}M"
    if ax >= 1_000:
        return f"{x/1_000:.1f}k"
    if ax >= 10:
        return f"{x:.0f}"
    return f"{x:.2f}"


def _expected_estimate(label: str, horizon: float) -> float:
    """Cheap point-estimate of expected cumulative flow from the edge
    label string. Used only to bucket diff_class — order-of-magnitude
    is sufficient."""
    import re
    if not label:
        return 0.0
    # const 2-5  →  3.5
    m = re.search(r"const\s+([\-\d.]+)(?:[–\-]([\-\d.]+))?", label)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else lo
        return ((lo + hi) / 2.0) * horizon
    # × const 2-5  → 3.5 × horizon
    m = re.search(r"×\s*const\s+([\-\d.]+)(?:[–\-]([\-\d.]+))?", label)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else lo
        return ((lo + hi) / 2.0) * horizon
    # Linear "a·t+b (a=..,b=..)"
    m = re.search(r"a=([\-\d.]+)(?:[–\-]([\-\d.]+))?[^b]*b=([\-\d.]+)(?:[–\-]([\-\d.]+))?",
                  label)
    if m:
        a = (float(m.group(1)) + float(m.group(2) or m.group(1))) / 2.0
        b = (float(m.group(3)) + float(m.group(4) or m.group(3))) / 2.0
        # Integrated linear over horizon: a·H²/2 + b·H
        return a * horizon * horizon / 2.0 + b * horizon
    return 0.0


def _diff_class(realised: float, expected: float) -> str:
    """Diff bucket for the realised overlay.

    The expected estimate is intentionally coarse (it reads only the
    edge's per-event rate label, not the rule × frequency product),
    so the window is wide — only truly anomalous edges show up red
    or amber. Order-of-magnitude bucketing:

      unused  : realised ≈ 0
      matched : within ±1 order of magnitude (most edges)
      under   : realised < 0.1 × expected
      over    : realised > 10  × expected   (only when expected > 0)
    """
    if realised <= 1e-9:
        if expected <= 1e-9:
            return "matched"          # both zero — consistent silence
        return "unused"
    if expected <= 1e-9:
        return "matched"               # no spec rate to compare to
    ratio = realised / expected
    if 0.1 <= ratio <= 10.0:
        return "matched"
    if ratio < 0.1:
        return "under"
    return "over"


def _full_rules_tooltip(rules: list, token_id: str) -> str:
    """Multi-line tooltip text expanding the per-rule details."""
    lines = [f"Token {token_id} — {len(rules)} rule(s):"]
    for i, r in enumerate(rules):
        ev = r.trigger.event_id or "(legacy inline)"
        lines.append(f"  #{i}  event={ev}  rate={_rule_label(r)}")
        if getattr(r.trigger, "conditions", None):
            lines.append(f"        conditions: {len(r.trigger.conditions)}")
        if getattr(r, "regimes", None):
            lines.append(f"        regimes: {len(r.regimes)}")
    return "\n".join(lines)
