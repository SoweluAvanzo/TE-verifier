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
        plugins: { legend: { display: true, position: "top" },
                   tooltip: { mode: "index", intersect: false } },
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
        plugins: { legend: { display: true, position: "top" },
                   tooltip: { mode: "index", intersect: false } },
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
