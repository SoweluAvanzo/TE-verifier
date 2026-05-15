// Trajectory explorer — one seeded ABM run, period-by-period.
//
// Reads the ExploreReport JSON once per /api/explore call, then drives:
//   - Results synthesis panel (tiles, headlines, per-role rows, top hubs)
//   - Per-role line charts (avg balance, balance share, action mix)
//   - Population aggregates over time (Gini, delegate Gini, φ)
//   - Snapshot views at the scrubber position (network, balance histogram,
//     action mix this period)
//
// Every chart has a legend; the per-role views use a stable color per
// agent_type based on declaration order.

(function () {
  "use strict";

  const dom = {
    yaml: document.getElementById("spec-yaml"),
    horizon: document.getElementById("cfg-horizon"),
    seed: document.getElementById("cfg-seed"),
    maxAgents: document.getElementById("cfg-max-agents"),
    runBtn: document.getElementById("run-btn"),
    status: document.getElementById("status"),

    synthCard:   document.getElementById("synth-card"),
    tileSupply:  document.getElementById("tile-supply"),
    tileEmit:    document.getElementById("tile-emit"),
    tileBurn:    document.getElementById("tile-burn"),
    tileTrades:  document.getElementById("tile-trades"),
    tileGini:    document.getElementById("tile-gini"),
    tileDelGini: document.getElementById("tile-delgini"),
    tilePhi:     document.getElementById("tile-phi"),
    tileTau:     document.getElementById("tile-tau"),
    tilePop:     document.getElementById("tile-pop"),
    tileExited:  document.getElementById("tile-exited"),
    tileRep:     document.getElementById("tile-rep"),
    headlineList: document.getElementById("headline-list"),
    roleTableBody: document.querySelector("#role-table tbody"),
    hubTableBody:  document.querySelector("#hub-table tbody"),

    scrubberRow:    document.getElementById("scrubber-row"),
    scrubber:       document.getElementById("scrubber"),
    scrubberLabel:  document.getElementById("scrubber-label"),
    playBtn:        document.getElementById("play-btn"),

    perRoleGrid:     document.getElementById("per-role-grid"),
    snapshotGrid:    document.getElementById("snapshot-grid"),

    roleBalChart:    document.getElementById("role-balance-chart"),
    roleShareChart:  document.getElementById("role-share-chart"),
    actionMixChart:  document.getElementById("action-mix-chart"),
    aggregatesChart: document.getElementById("aggregates-chart"),
    populationChart: document.getElementById("population-chart"),
    reputationChart: document.getElementById("reputation-chart"),
    eventsChart:     document.getElementById("events-chart"),
    eventsCard:      document.getElementById("events-card"),
    assetsChart:     document.getElementById("assets-chart"),
    assetsCard:      document.getElementById("assets-card"),
    coherenceCard:   document.getElementById("coherence-card"),
    coherenceWrap:   document.getElementById("coherence-table-wrap"),
    netMetricsCard:  document.getElementById("network-metrics-card"),
    netMetricsWrap:  document.getElementById("network-metrics-wrap"),
    balanceChart:    document.getElementById("balance-chart"),
    actionsChart:    document.getElementById("actions-chart"),

    netCanvas:      document.getElementById("network-canvas"),
    netLegend:      document.getElementById("net-legend"),
    netPeriod:      document.getElementById("net-period"),
    edgeMode:       document.getElementById("edge-mode"),
    edgeLimit:      document.getElementById("edge-limit"),
    nodeColorMode:  document.getElementById("node-color-mode"),
  };

  let report = null;
  let cy = null;
  let roleBalChartObj = null;
  let roleShareChartObj = null;
  let actionMixChartObj = null;
  let aggregatesChartObj = null;
  let populationChartObj = null;
  let reputationChartObj = null;
  let eventsChartObj = null;
  let assetsChartObj = null;
  let balanceChartObj = null;
  let actionsChartObj = null;
  let playTimer = null;

  // Stable color palette per type id (assigned by declaration order).
  const ROLE_PALETTE = [
    "#305ed3", "#d0524a", "#3b8a3b", "#c98410", "#65498f", "#1ea7a3",
    "#a3a3ab", "#7d4f50", "#347eb3",
  ];
  const ACTION_COLORS = {
    hold: "#a3a3ab", earn: "#3b8a3b", transfer: "#305ed3",
    redeem: "#d0524a", stake: "#c98410", vote: "#65498f",
  };
  let typeColor = {};      // populated per run

  // --- session-storage handoff from the form's "Explore" button -----
  try {
    const stashed = sessionStorage.getItem("te_form_yaml");
    if (stashed) {
      dom.yaml.value = stashed;
      sessionStorage.removeItem("te_form_yaml");
    }
  } catch (_) {}

  // --- example loader buttons ---------------------------------------
  document.querySelectorAll(".example-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.example;
      try {
        const r = await fetch(`/api/example/${name}`);
        const j = await r.json();
        dom.yaml.value = j.yaml || "";
        dom.status.textContent = `Loaded example: ${name}`;
      } catch (e) {
        dom.status.textContent = `Failed to load: ${e}`;
      }
    });
  });

  // --- run trajectory ----------------------------------------------
  dom.runBtn.addEventListener("click", runTrajectory);

  async function runTrajectory() {
    const yamlText = dom.yaml.value.trim();
    if (!yamlText) {
      dom.status.textContent = "Paste a YAML spec or load an example first.";
      return;
    }
    dom.runBtn.disabled = true;
    dom.status.textContent = "Running trajectory…";

    const body = {
      yaml: yamlText,
      horizon_periods: parseInt(dom.horizon.value, 10) || 120,
      seed: dom.seed.value === "" ? null : parseInt(dom.seed.value, 10),
      max_agents: dom.maxAgents.value === "" ? null : parseInt(dom.maxAgents.value, 10),
    };

    let resp, json;
    try {
      resp = await fetch("/api/explore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      json = await resp.json();
    } catch (e) {
      dom.status.textContent = `Network error: ${e}`;
      dom.runBtn.disabled = false;
      return;
    }
    if (!resp.ok || json.error) {
      dom.status.textContent = `Error: ${json.error || resp.statusText}`;
      dom.runBtn.disabled = false;
      return;
    }
    report = json;
    dom.runBtn.disabled = false;
    dom.status.textContent =
      `Done — ${report.snapshots.length} snapshots, ${report.n_agents} agents, ` +
      `topology ${report.topology}.`;
    assignTypeColors();
    renderSynthesis();
    // Reveal the grids FIRST — Chart.js + cytoscape need their
    // containers visible (non-zero width/height) before init or they
    // render to a zero-sized canvas and never recover.
    dom.synthCard.hidden = false;
    dom.scrubberRow.hidden = false;
    dom.perRoleGrid.hidden = false;
    dom.snapshotGrid.hidden = false;
    // Give the browser a tick to lay out the now-visible containers
    // (offsetWidth populates after the next style/layout flush).
    requestAnimationFrame(() => {
      renderPerRoleCharts();
      initNetwork();
      initBalanceChart();
      initActionsChart();
      setScrubberMax(report.snapshots.length - 1);
      renderAtPeriod(currentT());
    });
  }

  // --- color assignment per agent_type id ---------------------------
  function assignTypeColors() {
    typeColor = {};
    (report.type_ids || []).forEach((id, idx) => {
      typeColor[id] = ROLE_PALETTE[idx % ROLE_PALETTE.length];
    });
    // Catch-all for any type seen in snapshots but not in type_ids
    // (e.g. dynamically spawned types).
    const seen = new Set();
    for (const s of report.snapshots) for (const t of s.by_type) seen.add(t.type_id);
    let next = (report.type_ids || []).length;
    for (const id of seen) {
      if (!(id in typeColor)) {
        typeColor[id] = ROLE_PALETTE[next++ % ROLE_PALETTE.length];
      }
    }
  }

  // =====================================================================
  // Results synthesis
  // =====================================================================
  function renderSynthesis() {
    const s = report.summary || {};
    dom.tileSupply.textContent = fmtTokenMap(s.final_M_by_token);
    dom.tileEmit.textContent   = fmtTokenMap(s.cumulative_E_by_token);
    dom.tileBurn.textContent   = fmtTokenMap(s.cumulative_B_by_token);
    dom.tileTrades.textContent = `${(s.total_trade_count ?? 0).toLocaleString()} · vol ${fmtNum(s.total_trade_volume)}`;
    dom.tileGini.textContent   = fmtGiniDelta(s.initial_gini, s.final_gini);
    dom.tileDelGini.textContent = (s.final_delegate_gini ?? 0).toFixed(3);
    dom.tilePhi.textContent    = fmtGiniDelta(s.initial_phi, s.final_phi);
    dom.tileTau.textContent    = (s.final_tau_bar ?? 0).toFixed(2);
    // Phase E surface — only show non-trivial tiles. When Phase E
    // features are off the tile reads as "—" / "0".
    const popStart = s.initial_agent_count ?? 0;
    const popEnd = s.final_agent_count ?? 0;
    dom.tilePop.textContent = popStart || popEnd
      ? `${popStart} → ${popEnd}` : "—";
    dom.tileExited.textContent = (s.agents_exited ?? 0).toLocaleString();
    const repPeak = s.peak_mean_reputation ?? 0;
    const repFinal = s.final_mean_reputation ?? 0;
    dom.tileRep.textContent = (repPeak || repFinal)
      ? `${repPeak.toFixed(2)} / ${repFinal.toFixed(2)}` : "—";

    // Headlines
    dom.headlineList.innerHTML = "";
    for (const h of (s.headlines || [])) {
      const li = document.createElement("li");
      li.textContent = h;
      dom.headlineList.appendChild(li);
    }

    // Per-role table
    dom.roleTableBody.innerHTML = "";
    for (const t of (s.final_by_type || [])) {
      const tr = document.createElement("tr");
      const dominant = topKey(t.action_counts) || "—";
      tr.innerHTML = `
        <td><span class="role-swatch" style="background:${typeColor[t.type_id] || "#888"}"></span>${escapeHTML(t.type_id)}</td>
        <td>${t.count}</td>
        <td>${fmtNum(t.avg_balance)}</td>
        <td>${fmtNum(t.median_balance)}</td>
        <td>${(t.balance_share_of_total * 100).toFixed(1)}%</td>
        <td>${t.avg_periods_since_action.toFixed(1)}</td>
        <td>${t.avg_degree.toFixed(1)}</td>
        <td>${(t.avg_reputation ?? 0).toFixed(2)}</td>
        <td>${escapeHTML(dominant)}</td>
      `;
      dom.roleTableBody.appendChild(tr);
    }

    // Top-hubs table
    dom.hubTableBody.innerHTML = "";
    for (const h of (s.top_hubs || [])) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>#${h.agent_id}</td>
        <td><span class="role-swatch" style="background:${typeColor[h.type] || "#888"}"></span>${escapeHTML(h.type)}</td>
        <td>${fmtNum(h.total_flow)}</td>
        <td>${fmtNum(h.final_balance)}</td>
      `;
      dom.hubTableBody.appendChild(tr);
    }
  }

  // =====================================================================
  // Per-role time series + aggregates + stacked action mix
  // =====================================================================
  function renderPerRoleCharts() {
    const labels = report.snapshots.map((s) => s.t);
    const typeIds = Object.keys(typeColor);

    // (1) Average balance per role over time
    const balDatasets = typeIds.map((tid) => ({
      label: tid,
      borderColor: typeColor[tid],
      backgroundColor: typeColor[tid] + "33",
      tension: 0.2,
      data: report.snapshots.map((s) => {
        const t = s.by_type.find((x) => x.type_id === tid);
        return t ? t.avg_balance : null;
      }),
    }));
    if (roleBalChartObj) roleBalChartObj.destroy();
    roleBalChartObj = new Chart(dom.roleBalChart, {
      type: "line",
      data: { labels, datasets: balDatasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "top" },
                   tooltip: { mode: "index", intersect: false } },
        scales: { x: { title: { display: true, text: "period" } },
                  y: { title: { display: true, text: "avg balance per agent" } } },
      },
    });

    // (2) Balance share per role
    const shareDatasets = typeIds.map((tid) => ({
      label: tid,
      borderColor: typeColor[tid],
      backgroundColor: typeColor[tid] + "55",
      tension: 0.2,
      fill: "stack",
      data: report.snapshots.map((s) => {
        const t = s.by_type.find((x) => x.type_id === tid);
        return t ? t.balance_share_of_total : 0;
      }),
    }));
    if (roleShareChartObj) roleShareChartObj.destroy();
    roleShareChartObj = new Chart(dom.roleShareChart, {
      type: "line",
      data: { labels, datasets: shareDatasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "top" },
                   tooltip: { mode: "index", intersect: false } },
        scales: {
          x: { title: { display: true, text: "period" } },
          y: {
            stacked: true, min: 0, max: 1,
            title: { display: true, text: "fraction of total balance" },
            ticks: { callback: (v) => (v * 100).toFixed(0) + "%" },
          },
        },
      },
    });

    // (3) Population aggregates (Gini, delegate Gini, φ)
    if (aggregatesChartObj) aggregatesChartObj.destroy();
    aggregatesChartObj = new Chart(dom.aggregatesChart, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Gini (balance)",  borderColor: "#305ed3",
            data: report.snapshots.map((s) => s.effective_gini), tension: 0.2 },
          { label: "Gini (delegate)", borderColor: "#d0524a",
            data: report.snapshots.map((s) => s.delegate_gini),  tension: 0.2 },
          { label: "φ (active contributors)", borderColor: "#3b8a3b",
            data: report.snapshots.map((s) => s.phi),            tension: 0.2 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: "top" },
          tooltip: { mode: "index", intersect: false },
          thresholdLines: {
            lines: [
              // FM6 secondary signal threshold (paper §3.6).
              { y: 0.6, color: "#d0524a", label: "Gini = 0.6 (FM6 secondary)" },
              // FM6 primary centralization threshold (Γ ≤ 0.5).
              { y: 0.5, color: "#b07f1f", label: "Γ = 0.5 (FM6 primary)" },
            ],
          },
        },
        scales: { y: { min: 0, max: 1 } },
      },
    });

    // (4) Stacked action mix over time
    const actionKinds = ["hold", "earn", "transfer", "redeem", "stake", "vote"];
    const amDatasets = actionKinds.map((ak) => ({
      label: ak,
      borderColor: ACTION_COLORS[ak],
      backgroundColor: ACTION_COLORS[ak] + "AA",
      fill: "stack",
      tension: 0.0,
      data: report.snapshots.map((s) => s.action_mix?.[ak] || 0),
    }));
    if (actionMixChartObj) actionMixChartObj.destroy();
    actionMixChartObj = new Chart(dom.actionMixChart, {
      type: "line",
      data: { labels, datasets: amDatasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "top" },
                   tooltip: { mode: "index", intersect: false } },
        scales: {
          x: { title: { display: true, text: "period" } },
          y: {
            stacked: true, min: 0, max: 1,
            title: { display: true, text: "fraction of agents" },
            ticks: { callback: (v) => (v * 100).toFixed(0) + "%" },
          },
        },
      },
    });

    // (5) Live population per period (Phase E1).
    // Falls back to count of balances when ``live_agent_count`` is
    // absent (older runs / API consumers).
    const popData = report.snapshots.map((s) =>
      s.live_agent_count != null ? s.live_agent_count : (s.balances?.length ?? 0)
    );
    if (populationChartObj) populationChartObj.destroy();
    // FM5 threshold N_crit = 2·K·d + 1 (well-mixed Kandori bound).
    // K is per-token offer variety; conservatively pick the MAX K across
    // tokens — that's the most binding constraint. ``d`` is sampled into
    // state["d"] at run-time; carried in snapshot's optional 'd' or
    // 'demand_d' field if present.
    const fmCoh = report.fm_coherence || [];
    const fm5Pred = ((fmCoh.find((c) => c.failure_mode === "FM5") || {}).predicates || [])
      .find((p) => p.variable === "N" || p.variable === "live_agent_count");
    const popThresholds = fm5Pred && Number.isFinite(fm5Pred.threshold)
      ? [{ y: fm5Pred.threshold, color: "#d0524a",
           label: `N_crit = ${fm5Pred.threshold} (FM5: N ≥ 2Kd+1)` }]
      : [];
    populationChartObj = new Chart(dom.populationChart, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "live agent count",
          borderColor: "#d0524a",
          backgroundColor: "#d0524a55",
          tension: 0.1,
          fill: true,
          data: popData,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: "top" },
          tooltip: { mode: "index", intersect: false },
          thresholdLines: { lines: popThresholds },
        },
        scales: {
          x: { title: { display: true, text: "period" } },
          y: { title: { display: true, text: "agents" }, beginAtZero: true },
        },
      },
    });

    // (6) Reputation per period (Phase E3) — population mean plus per-
    // role lines when at least one type accumulates reputation.
    const typeIds6 = Object.keys(typeColor);
    const meanRepData = report.snapshots.map((s) => s.mean_reputation ?? 0);
    const repDatasets = [{
      label: "mean (population)",
      borderColor: "#1ea7a3",
      backgroundColor: "#1ea7a333",
      borderWidth: 2.5,
      tension: 0.15,
      data: meanRepData,
    }];
    // Per-role lines — only add when at least one type reports
    // non-zero reputation at some point in the run.
    for (const tid of typeIds6) {
      const series = report.snapshots.map((s) => {
        const t = s.by_type.find((x) => x.type_id === tid);
        return t && t.avg_reputation != null ? t.avg_reputation : 0;
      });
      if (series.some((v) => v > 0)) {
        repDatasets.push({
          label: tid,
          borderColor: typeColor[tid],
          backgroundColor: typeColor[tid] + "22",
          borderDash: [4, 4],
          tension: 0.15,
          data: series,
        });
      }
    }
    if (reputationChartObj) reputationChartObj.destroy();
    reputationChartObj = new Chart(dom.reputationChart, {
      type: "line",
      data: { labels, datasets: repDatasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "top" },
                   tooltip: { mode: "index", intersect: false } },
        scales: {
          x: { title: { display: true, text: "period" } },
          y: { title: { display: true, text: "reputation" }, beginAtZero: true },
        },
      },
    });

    // (7) Event-occurrence series — one line per event id. Hidden when
    // the TE has no events declared. Reads PeriodSnapshot.events_realized
    // (count of firings *this* period, not cumulative).
    drawEventsChart(report, labels);
    // (8) Non-tokenized asset flows — count / created / consumed per
    // asset over time. Hidden when the TE has no assets declared.
    drawAssetsChart(report, labels);
    // (9) FM-coherence panel — verifier verdicts vs ABM-realized.
    drawCoherenceTable(report);
    // (10) Network analytics — centralities, correlations, null-model
    // z-scores.
    drawNetworkMetrics(report);
    // (11) Declared flow graph — Phase M + M.18 realised overlay.
    // The report carries both the spec graph and the realised
    // annotations on its edges; the view selector swaps the label /
    // colour scheme without a second round-trip.
    drawFlowGraphFromReport(report);
  }

  function drawFlowGraphFromReport(report) {
    const payload = report.flow_graph;
    const card = document.getElementById("flow-graph-card");
    const canvas = document.getElementById("flow-graph-canvas");
    const legend = document.getElementById("flow-graph-legend");
    const summary = document.getElementById("flow-graph-summary");
    const diag = document.getElementById("flow-graph-diagnostics");
    if (!card || !canvas || !payload) {
      if (card) card.hidden = true;
      return;
    }
    card.hidden = false;
    const layoutSel = document.getElementById("flow-graph-layout");
    const viewSel = document.getElementById("flow-graph-view");
    function render() {
      if (typeof window.renderFlowGraph !== "function") return;
      window.renderFlowGraph(
        canvas, legend, summary, diag, payload,
        layoutSel?.value || "cose",
        viewSel?.value || "spec",
      );
    }
    if (layoutSel) layoutSel.onchange = render;
    if (viewSel)   viewSel.onchange   = render;
    render();
  }

  // =====================================================================
  // FM-coherence rendering
  // =====================================================================
  function drawCoherenceTable(report) {
    const rows = report.fm_coherence || [];
    if (!rows.length || !dom.coherenceWrap) {
      if (dom.coherenceCard) dom.coherenceCard.hidden = true;
      return;
    }
    dom.coherenceCard.hidden = false;
    const wrap = dom.coherenceWrap;
    wrap.innerHTML = "";
    // Legend explaining the consistency colour scheme.
    const legend = document.createElement("p");
    legend.className = "muted";
    legend.innerHTML = `
      <strong>How to read:</strong>
      <span class="consistency-ok">✓ consistent</span> — ABM agrees with the verifier
      (both safe, or both surface the same violation).
      <span class="consistency-warn">◐ partial</span> — verifier was conservative
      or ABM stayed in the safe subset of a fragile box.
      <span class="consistency-bad">⚠ inconsistent</span> — ABM violated where the
      verifier proved safety; investigate.`;
    wrap.appendChild(legend);

    const tbl = document.createElement("table");
    tbl.className = "metrics-table coherence-table";
    const head = document.createElement("thead");
    head.innerHTML = `
      <tr>
        <th>FM</th><th>subject</th><th>verifier</th>
        <th>consistent?</th><th>coherence</th>
        <th>predicate (var op threshold)</th>
        <th>ABM min · median · max</th>
        <th>violations / periods</th>
      </tr>`;
    tbl.appendChild(head);
    const body = document.createElement("tbody");
    for (const r of rows) {
      const preds = r.predicates || [];
      const note = (r.notes || "").trim();
      const consistency = classifyConsistency(r.coherence);
      const consBadge =
        `<span class="${consistency.cls}" title="${escapeHTML(consistency.tip)}">${consistency.icon} ${consistency.label}</span>`;
      if (preds.length === 0) {
        const tr = document.createElement("tr");
        tr.className = `coherence-row coherence-${r.coherence}`;
        tr.innerHTML = `
          <td>${r.failure_mode}</td><td>${r.subject}</td>
          <td>${r.structural_status}</td>
          <td>${consBadge}</td>
          <td><span class="cohbadge cohbadge-${r.coherence}">${r.coherence}</span></td>
          <td colspan="3" class="muted">${escapeHTML(note || "(no predicates emitted)")}</td>`;
        body.appendChild(tr);
        continue;
      }
      preds.forEach((p, i) => {
        const tr = document.createElement("tr");
        tr.className = `coherence-row coherence-${r.coherence}`;
        const fmCell    = i === 0 ? `<td rowspan="${preds.length}">${r.failure_mode}</td>` : "";
        const subCell   = i === 0 ? `<td rowspan="${preds.length}">${r.subject}</td>` : "";
        const vCell     = i === 0 ? `<td rowspan="${preds.length}">${r.structural_status}</td>` : "";
        const cnsCell   = i === 0 ? `<td rowspan="${preds.length}">${consBadge}</td>` : "";
        const cCell     = i === 0 ? `<td rowspan="${preds.length}"><span class="cohbadge cohbadge-${r.coherence}">${r.coherence}</span></td>` : "";
        const obsCell = (p.observed_min == null)
          ? `<td class="muted">(no data)</td>`
          : `<td>${fmtNum(p.observed_min)} · ${fmtNum(p.observed_median)} · ${fmtNum(p.observed_max)}</td>`;
        tr.innerHTML = `${fmCell}${subCell}${vCell}${cnsCell}${cCell}
          <td><code>${escapeHTML(p.variable)} ${escapeHTML(p.operator)} ${fmtNum(p.threshold)}</code></td>
          ${obsCell}
          <td>${p.violation_periods ?? 0}</td>`;
        body.appendChild(tr);
      });
      if (note) {
        const tr = document.createElement("tr");
        tr.className = `coherence-row-note coherence-${r.coherence}`;
        tr.innerHTML = `<td colspan="8" class="muted">${escapeHTML(note)}</td>`;
        body.appendChild(tr);
      }
    }
    tbl.appendChild(body);
    wrap.appendChild(tbl);
  }

  /** Map a coherence verdict to a consistency badge.
   *  - consistent: verifier prediction matches ABM observation
   *    (aligned / confirmed / fragile_realised).
   *  - partial:    verifier was conservative or ABM stayed in the
   *    safe subset of a fragile box (verifier_pessimistic /
   *    fragile_avoided).
   *  - inconsistent: ABM violated inside a region the verifier
   *    proved safe (abm_drift).
   *  - muted: nothing to compare (inconclusive). */
  function classifyConsistency(coh) {
    if (coh === "aligned" || coh === "confirmed" || coh === "fragile_realised") {
      return {
        cls: "consistency-ok", icon: "✓", label: "consistent",
        tip: "Verifier prediction agrees with ABM observation."
      };
    }
    if (coh === "fragile_avoided" || coh === "verifier_pessimistic") {
      return {
        cls: "consistency-warn", icon: "◐", label: "partial",
        tip: "Verifier and ABM partially agree — investigate the box."
      };
    }
    if (coh === "abm_drift") {
      return {
        cls: "consistency-bad", icon: "⚠", label: "inconsistent",
        tip: "ABM violated where the verifier proved safety. Investigate."
      };
    }
    return {
      cls: "consistency-muted", icon: "—", label: "n/a",
      tip: "No comparison possible (inconclusive)."
    };
  }

  // =====================================================================
  // Network analytics rendering
  // =====================================================================
  function drawNetworkMetrics(report) {
    const nm = report.network_metrics;
    if (!nm || !dom.netMetricsWrap) {
      if (dom.netMetricsCard) dom.netMetricsCard.hidden = true;
      return;
    }
    dom.netMetricsCard.hidden = false;
    const wrap = dom.netMetricsWrap;
    wrap.innerHTML = "";

    // (a) Summary line.
    const summary = document.createElement("p");
    summary.className = "muted";
    summary.innerHTML = `
      <strong>n = ${nm.n_nodes}</strong> nodes ·
      <strong>m = ${nm.n_edges}</strong> edges ·
      ${nm.components} component(s) ·
      giant-component fraction ${fmtNum(nm.giant_component_frac)}
    `;
    wrap.appendChild(summary);

    // (b) Network-level table with null-model comparison.
    const h1 = document.createElement("h4");
    h1.textContent = "Network-level statistics + null-model z-scores";
    wrap.appendChild(h1);
    const nlt = document.createElement("table");
    nlt.className = "metrics-table";
    nlt.innerHTML = `
      <thead><tr>
        <th>statistic</th><th>observed</th>
        <th>Erdős–Rényi μ ± σ</th><th>z<sub>ER</sub></th>
        <th>configuration model μ ± σ</th><th>z<sub>cfg</sub></th>
        <th>interpretation</th>
      </tr></thead>
      <tbody>
        ${nm.network_level.map((s) => `
          <tr>
            <td><code>${escapeHTML(s.name)}</code></td>
            <td>${fmtNum(s.observed, 4)}</td>
            <td>${fmtNum(s.er_mean, 4)} ± ${fmtNum(s.er_std, 4)}</td>
            <td class="${zClass(s.er_z)}">${fmtZ(s.er_z)}</td>
            <td>${fmtNum(s.config_mean, 4)} ± ${fmtNum(s.config_std, 4)}</td>
            <td class="${zClass(s.config_z)}">${fmtZ(s.config_z)}</td>
            <td class="muted">${escapeHTML(s.interpretation)}</td>
          </tr>`).join("")}
      </tbody>`;
    wrap.appendChild(nlt);

    // (c) Per-type aggregates.
    const h2 = document.createElement("h4");
    h2.textContent = "Per-type aggregates";
    wrap.appendChild(h2);
    const ptt = document.createElement("table");
    ptt.className = "metrics-table";
    ptt.innerHTML = `
      <thead><tr>
        <th>type</th><th>n</th><th>mean degree</th>
        <th>mean betweenness</th><th>mean closeness</th>
        <th>mean balance</th><th>mean reputation</th>
        <th>Gini (balance within type)</th>
      </tr></thead>
      <tbody>
        ${nm.per_type.map((pt) => `
          <tr>
            <td>${escapeHTML(pt.type)}</td>
            <td>${pt.n_agents}</td>
            <td>${fmtNum(pt.mean_degree, 2)}</td>
            <td>${fmtNum(pt.mean_betweenness, 4)}</td>
            <td>${fmtNum(pt.mean_closeness, 4)}</td>
            <td>${fmtNum(pt.mean_balance, 2)}</td>
            <td>${fmtNum(pt.mean_reputation, 2)}</td>
            <td>${fmtNum(pt.balance_gini_within_type, 3)}</td>
          </tr>`).join("")}
      </tbody>`;
    wrap.appendChild(ptt);

    // (d) Correlation heatmap (Pearson r between numeric attributes).
    const h3 = document.createElement("h4");
    h3.textContent = "Pearson correlations (r [p-value · n])";
    wrap.appendChild(h3);
    const corrKeys = [
      "balance", "reputation",
      "degree", "betweenness", "closeness", "eigenvector",
    ];
    const lookup = {};
    for (const c of nm.correlations) {
      lookup[`${c.a}|${c.b}`] = c;
      lookup[`${c.b}|${c.a}`] = c;
    }
    const ctab = document.createElement("table");
    ctab.className = "metrics-table correlation-table";
    const header =
      `<tr><th></th>${corrKeys.map((k) => `<th>${k}</th>`).join("")}</tr>`;
    const bodyRows = corrKeys.map((a) => {
      const cells = corrKeys.map((b) => {
        const cell = lookup[`${a}|${b}`];
        if (!cell) return `<td class="muted">—</td>`;
        const r = cell.r;
        const sig = cell.p < 0.001 ? "***"
                  : cell.p < 0.01  ? "**"
                  : cell.p < 0.05  ? "*"  : "";
        const bg = corrBg(r);
        return `<td style="background:${bg}" title="r=${r.toFixed(3)} p=${cell.p.toExponential(2)} n=${cell.n}">${r.toFixed(2)}<sup>${sig}</sup></td>`;
      }).join("");
      return `<tr><th>${a}</th>${cells}</tr>`;
    }).join("");
    ctab.innerHTML = `<thead>${header}</thead><tbody>${bodyRows}</tbody>`;
    wrap.appendChild(ctab);

    // (e) Per-agent table (paginated to top 50 by degree to stay tractable).
    const h4 = document.createElement("h4");
    h4.textContent = `Top agents by degree (showing ${Math.min(50, nm.per_agent.length)} of ${nm.per_agent.length})`;
    wrap.appendChild(h4);
    const sorted = [...nm.per_agent].sort((a, b) => b.degree - a.degree).slice(0, 50);
    const pat = document.createElement("table");
    pat.className = "metrics-table";
    pat.innerHTML = `
      <thead><tr>
        <th>id</th><th>type</th><th>balance</th><th>reputation</th>
        <th>degree</th><th>degree_centrality</th>
        <th>betweenness</th><th>closeness</th>
        <th>eigenvector</th><th>clustering</th>
      </tr></thead>
      <tbody>
        ${sorted.map((a) => `
          <tr>
            <td>${a.agent_id}</td><td>${escapeHTML(a.type)}</td>
            <td>${fmtNum(a.balance, 2)}</td>
            <td>${fmtNum(a.reputation, 2)}</td>
            <td>${a.degree}</td>
            <td>${fmtNum(a.degree_centrality, 3)}</td>
            <td>${a.betweenness == null ? "—" : fmtNum(a.betweenness, 4)}</td>
            <td>${a.closeness == null ? "—" : fmtNum(a.closeness, 4)}</td>
            <td>${a.eigenvector == null ? "—" : fmtNum(a.eigenvector, 4)}</td>
            <td>${fmtNum(a.clustering, 3)}</td>
          </tr>`).join("")}
      </tbody>`;
    wrap.appendChild(pat);
  }

  function fmtNum(x, d = 3) {
    if (x == null || Number.isNaN(x)) return "—";
    return Number(x).toFixed(d);
  }
  function fmtZ(z) {
    if (z == null) return "—";
    return (z >= 0 ? "+" : "") + z.toFixed(2);
  }
  function zClass(z) {
    if (z == null) return "muted";
    if (Math.abs(z) >= 2.0) return "z-significant";
    return "";
  }
  function corrBg(r) {
    // Blue for negative, red for positive, white for ~0.
    const v = Math.max(-1, Math.min(1, r));
    if (v > 0) {
      const a = (v * 0.75).toFixed(2);
      return `rgba(208,82,74,${a})`;
    }
    const a = (-v * 0.75).toFixed(2);
    return `rgba(48,94,211,${a})`;
  }
  function escapeHTML(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;",
      '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function drawEventsChart(report, labels) {
    const eventIds = new Set();
    for (const s of report.snapshots) {
      for (const k of Object.keys(s.events_realized || {})) eventIds.add(k);
    }
    if (!eventIds.size) {
      if (dom.eventsCard) dom.eventsCard.hidden = true;
      return;
    }
    if (dom.eventsCard) dom.eventsCard.hidden = false;
    const palette = ["#305ed3", "#d0524a", "#3b8a3b", "#b07f1f", "#7a4dcf",
                     "#198a8a", "#cc4488", "#666"];
    const datasets = [...eventIds].map((eid, i) => ({
      label: eid,
      borderColor: palette[i % palette.length],
      backgroundColor: palette[i % palette.length] + "22",
      tension: 0.15,
      data: report.snapshots.map((s) => s.events_realized?.[eid] ?? 0),
    }));
    if (eventsChartObj) eventsChartObj.destroy();
    eventsChartObj = new Chart(dom.eventsChart, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "top" },
                   tooltip: { mode: "index", intersect: false } },
        scales: {
          x: { title: { display: true, text: "period" } },
          y: { title: { display: true, text: "firings per period" }, beginAtZero: true },
        },
      },
    });
  }

  function drawAssetsChart(report, labels) {
    const assetIds = new Set();
    for (const s of report.snapshots) {
      for (const k of Object.keys(s.assets || {})) assetIds.add(k);
    }
    if (!assetIds.size) {
      if (dom.assetsCard) dom.assetsCard.hidden = true;
      return;
    }
    if (dom.assetsCard) dom.assetsCard.hidden = false;
    const palette = ["#305ed3", "#d0524a", "#3b8a3b", "#b07f1f", "#7a4dcf",
                     "#198a8a", "#cc4488"];
    const metricDash = { count: [], created: [4, 4], consumed: [2, 6] };
    const datasets = [];
    let i = 0;
    for (const aid of assetIds) {
      const color = palette[i % palette.length];
      for (const metric of ["count", "created", "consumed"]) {
        datasets.push({
          label: `${aid} · ${metric}`,
          borderColor: color,
          backgroundColor: color + "22",
          borderDash: metricDash[metric],
          tension: 0.15,
          data: report.snapshots.map((s) => s.assets?.[aid]?.[metric] ?? 0),
        });
      }
      i++;
    }
    if (assetsChartObj) assetsChartObj.destroy();
    assetsChartObj = new Chart(dom.assetsChart, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "top" },
                   tooltip: { mode: "index", intersect: false } },
        scales: {
          x: { title: { display: true, text: "period" } },
          y: { title: { display: true, text: "units" }, beginAtZero: true },
        },
      },
    });
  }

  // =====================================================================
  // Snapshot views (network, balance histogram, action donut)
  // =====================================================================
  function initNetwork() {
    if (cy) cy.destroy();
    const nodes = report.agents.map((a) => ({
      data: {
        id: String(a.id),
        type: a.type,
        is_delegate: a.is_delegate,
      },
    }));
    cy = cytoscape({
      container: dom.netCanvas,
      elements: nodes,
      style: [
        { selector: "node", style: {
            "background-color": (n) => nodeColor(n),
            label: (n) => n.data("type"),
            color: "#fff",
            "font-size": 8,
            "text-valign": "center",
            "text-halign": "center",
            width: "data(size)",
            height: "data(size)",
            "border-width": 1,
            "border-color": "#244",
        }},
        { selector: 'edge[kind = "trade"]', style: {
            "line-color": "#3b8a3b",
            width: "mapData(weight, 0, 10, 1, 6)",
            "curve-style": "haystack",
            opacity: 0.8,
        }},
      ],
      layout: { name: "cose", animate: false, randomize: true, padding: 12 },
    });
    renderNetworkLegend();
  }

  function nodeColor(n) {
    const mode = dom.nodeColorMode.value;
    if (mode === "delegate") {
      return n.data("is_delegate") ? "#d0524a" : "#7892d1";
    }
    return typeColor[n.data("type")] || "#888";
  }

  function renderNetworkLegend() {
    const mode = dom.nodeColorMode.value;
    dom.netLegend.innerHTML = "";
    const items = [];
    if (mode === "delegate") {
      items.push(["#d0524a", "delegate"], ["#7892d1", "non-delegate"]);
    } else {
      for (const tid of (report.type_ids || Object.keys(typeColor))) {
        items.push([typeColor[tid], tid]);
      }
    }
    items.push(["#3b8a3b", "trade edge"]);
    for (const [color, label] of items) {
      const span = document.createElement("span");
      span.className = "legend-item";
      span.innerHTML = `<span class="legend-swatch" style="background:${color}"></span>${escapeHTML(label)}`;
      dom.netLegend.appendChild(span);
    }
  }

  dom.edgeMode.addEventListener("change", () => renderAtPeriod(currentT()));
  dom.edgeLimit.addEventListener("change", () => renderAtPeriod(currentT()));
  dom.nodeColorMode.addEventListener("change", () => {
    cy.style().selector("node")
      .style("background-color", (n) => nodeColor(n))
      .update();
    renderNetworkLegend();
  });

  function initBalanceChart() {
    if (balanceChartObj) balanceChartObj.destroy();
    balanceChartObj = new Chart(dom.balanceChart, {
      type: "bar",
      data: { labels: [], datasets: [{ label: "agents in bucket", data: [], backgroundColor: "#3b8a3b" }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "top" } },
        scales: {
          y: { title: { display: true, text: "agents" } },
          x: { title: { display: true, text: "balance (bucket start)" } },
        },
      },
    });
  }

  function initActionsChart() {
    if (actionsChartObj) actionsChartObj.destroy();
    actionsChartObj = new Chart(dom.actionsChart, {
      type: "doughnut",
      data: {
        labels: [],
        datasets: [{
          data: [],
          backgroundColor: [],
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "right" } },
      },
    });
  }

  // =====================================================================
  // Scrubber + playback
  // =====================================================================
  dom.scrubber.addEventListener("input", () => renderAtPeriod(currentT()));
  dom.playBtn.addEventListener("click", () => {
    if (playTimer) {
      clearInterval(playTimer);
      playTimer = null;
      dom.playBtn.textContent = "▶ Play";
      return;
    }
    dom.playBtn.textContent = "⏸ Pause";
    playTimer = setInterval(() => {
      const t = currentT();
      const max = parseInt(dom.scrubber.max, 10);
      if (t >= max) {
        clearInterval(playTimer);
        playTimer = null;
        dom.playBtn.textContent = "▶ Play";
        return;
      }
      dom.scrubber.value = t + 1;
      renderAtPeriod(t + 1);
    }, 120);
  });

  function currentT() { return parseInt(dom.scrubber.value, 10) || 0; }

  function setScrubberMax(maxT) {
    dom.scrubber.max = maxT;
    // Start at the final period so the network shows the cumulative
    // trade graph immediately on run completion. The user can scrub
    // back to t=0 (empty graph) to watch it build up.
    dom.scrubber.value = maxT;
  }

  function renderAtPeriod(t) {
    if (!report) return;
    const snap = report.snapshots[t];
    if (!snap) return;
    dom.scrubberLabel.textContent = `t = ${snap.t} / ${report.snapshots.length - 1}`;
    dom.netPeriod.textContent = snap.t;
    updateNetwork(t, snap);
    updateBalanceHist(snap);
    updateActionsDonut(snap);
    // Phase-L1: redraw the period-cursor on every time-series chart.
    // Single source of truth for "current period" — the scrubber.
    syncCursorOnAllCharts(t);
  }

  // ---------------------------------------------------------------------
  // Period-cursor plugin (Phase L1)
  //
  // Draws a vertical line at the current scrubber index on every
  // time-series chart so the user can read the same period across
  // all charts without re-aligning by eye.
  // ---------------------------------------------------------------------
  const periodCursorPlugin = {
    id: "periodCursor",
    afterDraw(chart) {
      const t = chart.options.plugins?.periodCursor?.tIndex;
      if (t == null || t < 0) return;
      const xScale = chart.scales.x;
      if (!xScale) return;
      const labels = chart.data.labels || [];
      if (!labels.length) return;
      // Use category index → pixel.
      const xPx = xScale.getPixelForValue(t);
      const { top, bottom } = chart.chartArea;
      const ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = "#d0524a";
      ctx.lineWidth = 1.4;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(xPx, top);
      ctx.lineTo(xPx, bottom);
      ctx.stroke();
      // Label.
      ctx.fillStyle = "#d0524a";
      ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
      ctx.fillText(`t=${t}`, xPx + 3, top + 10);
      ctx.restore();
    },
  };

  // Register once.
  if (window.Chart && !Chart.registry.plugins.get("periodCursor")) {
    Chart.register(periodCursorPlugin);
  }

  // ---------------------------------------------------------------------
  // Threshold reference-line plugin
  //
  // Draws horizontal reference lines (paper thresholds, e.g.
  // Gini ≤ 0.6 for FM6 secondary). Lines: [{y, color, label}].
  // ---------------------------------------------------------------------
  const thresholdLinesPlugin = {
    id: "thresholdLines",
    afterDraw(chart) {
      const lines = chart.options.plugins?.thresholdLines?.lines || [];
      if (!lines.length) return;
      const yScale = chart.scales.y;
      if (!yScale) return;
      const { left, right } = chart.chartArea;
      const ctx = chart.ctx;
      for (const ln of lines) {
        const yPx = yScale.getPixelForValue(ln.y);
        if (Number.isNaN(yPx)) continue;
        ctx.save();
        ctx.strokeStyle = ln.color || "#888";
        ctx.lineWidth = 1.2;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(left, yPx);
        ctx.lineTo(right, yPx);
        ctx.stroke();
        if (ln.label) {
          ctx.fillStyle = ln.color || "#888";
          ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
          ctx.fillText(ln.label, left + 6, yPx - 3);
        }
        ctx.restore();
      }
    },
  };
  if (window.Chart && !Chart.registry.plugins.get("thresholdLines")) {
    Chart.register(thresholdLinesPlugin);
  }

  function syncCursorOnAllCharts(t) {
    const all = [
      roleBalChartObj, roleShareChartObj, actionMixChartObj,
      aggregatesChartObj, populationChartObj, reputationChartObj,
      eventsChartObj, assetsChartObj,
    ];
    for (const ch of all) {
      if (!ch) continue;
      ch.options.plugins ||= {};
      ch.options.plugins.periodCursor = { tIndex: t };
      ch.update("none");
    }
  }

  function updateNetwork(tIdx, snap) {
    if (!cy) return;
    cy.batch(() => {
      cy.edges('[kind = "trade"]').remove();

      // 1) Node size by current balance (relative scale).
      const balances = snap.balances || [];
      const maxBal = Math.max(1, ...balances);
      report.agents.forEach((a, i) => {
        const n = cy.getElementById(String(a.id));
        if (!n.length) return;
        const bal = balances[i] || 0;
        const size = 8 + 22 * Math.sqrt(bal / maxBal);
        n.data("size", size);
      });

      // 2) Edges according to filter.
      const mode = dom.edgeMode.value;
      const limit = Math.max(5, parseInt(dom.edgeLimit.value, 10) || 60);
      let edges;
      if (mode === "window") {
        const startT = Math.max(0, tIdx - limit);
        const baseline = new Set(
          (report.snapshots[startT - 1]?.trade_edges || []).map(
            ([s, d]) => `${s}-${d}`
          )
        );
        edges = (snap.trade_edges || []).filter(
          ([s, d]) => !baseline.has(`${s}-${d}`)
        );
      } else if (mode === "all") {
        edges = snap.trade_edges || [];
      } else {
        // topk
        edges = [...(snap.trade_edges || [])]
          .sort((a, b) => b[2] - a[2])
          .slice(0, limit);
      }

      for (const [s, d, w] of edges) {
        cy.add({
          group: "edges",
          data: {
            id: `trade-${s}-${d}`,
            source: String(s),
            target: String(d),
            kind: "trade",
            weight: Math.min(10, Math.max(0.1, Math.log10(w + 1) * 2)),
          },
        });
      }
    });
  }

  function updateBalanceHist(snap) {
    if (!balanceChartObj) return;
    const balances = snap.balances || [];
    if (balances.length === 0) return;
    const max = Math.max(...balances, 1);
    const buckets = 12;
    const step = max / buckets;
    const counts = new Array(buckets).fill(0);
    for (const v of balances) {
      let i = Math.floor(v / step);
      if (i >= buckets) i = buckets - 1;
      counts[i] += 1;
    }
    balanceChartObj.data.labels = counts.map((_, i) => fmtNum(i * step));
    balanceChartObj.data.datasets[0].data = counts;
    balanceChartObj.update("none");
  }

  function updateActionsDonut(snap) {
    if (!actionsChartObj) return;
    const mix = snap.action_mix || {};
    const labels = Object.keys(mix);
    actionsChartObj.data.labels = labels;
    actionsChartObj.data.datasets[0].data = labels.map((k) => mix[k]);
    actionsChartObj.data.datasets[0].backgroundColor =
      labels.map((k) => ACTION_COLORS[k] || "#888");
    actionsChartObj.update("none");
  }

  // =====================================================================
  // Helpers
  // =====================================================================
  function fmtTokenMap(m) {
    if (!m) return "—";
    return Object.entries(m)
      .map(([k, v]) => `${k}: ${fmtNum(v)}`)
      .join("\n");
  }
  function fmtNum(v) {
    if (v == null || Number.isNaN(v)) return "—";
    const a = Math.abs(v);
    if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return (v / 1e3).toFixed(2) + "k";
    return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  function fmtGiniDelta(a, b) {
    if (a == null || b == null) return (b ?? 0).toFixed(3);
    if (Math.abs(a - b) < 0.005) return b.toFixed(3);
    return `${a.toFixed(3)} → ${b.toFixed(3)}`;
  }
  function topKey(obj) {
    if (!obj) return null;
    let best = null, bestV = -Infinity;
    for (const [k, v] of Object.entries(obj)) {
      if (v > bestV) { bestV = v; best = k; }
    }
    return best;
  }
  function escapeHTML(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }
})();
