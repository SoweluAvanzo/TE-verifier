/* Simulator page — drives /api/simulate and /api/cadcad-export.
 *
 * No mocked data. Every chart renders from the JSON the backend
 * returns. Chart.js is loaded from a CDN; everything else is plain
 * DOM. */

(function () {
  "use strict";

  const yamlInput     = document.getElementById("spec-yaml");
  const runBtn        = document.getElementById("run-btn");
  const exportBtn     = document.getElementById("export-btn");
  const statusLine    = document.getElementById("status");
  const summaryPane   = document.getElementById("summary");
  const summaryTableW = document.getElementById("summary-table-wrapper");
  const headlineList  = document.getElementById("headline-list");
  const cardsPane     = document.getElementById("per-fm-cards");
  const emptyMsg      = document.getElementById("empty-msg");

  /** Chart instances — kept so we can destroy them on rerun. */
  const charts = [];

  /** Example loaders. */
  document.querySelectorAll(".example-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.example;
      setStatus(`Loading example: ${name}…`);
      try {
        const r = await fetch(`/api/example/${encodeURIComponent(name)}`);
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || "load failed");
        yamlInput.value = data.yaml;
        setStatus(`Example loaded: ${name}.`, "success");
      } catch (e) {
        setStatus(`Failed to load: ${e.message}`, "error");
      }
    });
  });

  /** Run simulation. */
  runBtn.addEventListener("click", async () => {
    const yaml = yamlInput.value.trim();
    if (!yaml) {
      setStatus("Please paste a YAML spec or load an example first.", "error");
      return;
    }
    const body = {
      yaml,
      n_runs:          int(document.getElementById("cfg-runs").value, 300),
      horizon_periods: int(document.getElementById("cfg-horizon").value, 260),
      seed:            (document.getElementById("cfg-seed").value || null),
      skip_non_fragile: document.getElementById("cfg-skip").checked,
      record_trajectories: document.getElementById("cfg-trajectories").checked,
    };

    runBtn.disabled = true;
    exportBtn.disabled = true;
    setStatus(`Running ${body.n_runs} replicates × ${body.horizon_periods} periods…`);

    try {
      const t0 = performance.now();
      const r = await fetch("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "simulation failed");
      const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
      setStatus(`Done in ${elapsed}s — ${data.per_fm_results.length} verdicts.`, "success");
      renderReport(data);
      exportBtn.disabled = false;
    } catch (e) {
      setStatus(`Simulation failed: ${e.message}`, "error");
    } finally {
      runBtn.disabled = false;
    }
  });

  /** Export cadCAD config. */
  exportBtn.addEventListener("click", async () => {
    const yaml = yamlInput.value.trim();
    if (!yaml) {
      setStatus("Cannot export — load a spec first.", "error");
      return;
    }
    const body = {
      yaml,
      n_runs:          int(document.getElementById("cfg-runs").value, 500),
      horizon_periods: int(document.getElementById("cfg-horizon").value, 260),
      seed:            (document.getElementById("cfg-seed").value || null),
    };
    setStatus("Building cadCAD config…");
    try {
      const r = await fetch("/api/cadcad-export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "export failed");
      const teName = data.metadata && data.metadata.te_name
        ? data.metadata.te_name.replace(/[^a-z0-9]+/gi, "_").toLowerCase()
        : "te";
      downloadJSON(`${teName}_cadcad_config.json`, data);
      setStatus(`Exported cadCAD config for ${data.metadata.te_name}.`, "success");
    } catch (e) {
      setStatus(`Export failed: ${e.message}`, "error");
    }
  });

  // -----------------------------------------------------------------
  // Rendering
  // -----------------------------------------------------------------

  function renderReport(report) {
    emptyMsg.classList.add("hidden");
    summaryPane.classList.remove("hidden");
    cardsPane.classList.remove("hidden");

    // Destroy prior charts.
    while (charts.length) charts.pop().destroy();

    renderSummaryTable(report);
    renderHeadlines(report);
    renderPerFMCards(report);
  }

  function renderSummaryTable(report) {
    const rows = report.per_fm_results.map((r) => {
      const status = r.structural_status;
      const pDeploy = r.simulated && r.n_runs > 0
        ? pct(r.n_violations_at_deployment / r.n_runs) : "—";
      const pDyn = r.simulated && r.n_runs > 0
        ? pct(r.n_violations_dynamic / r.n_runs) : "—";
      const tMed = (r.simulated && r.time_to_violation_median != null && r.time_to_violation_median > 0)
        ? r.time_to_violation_median.toFixed(0) : "—";
      return `<tr>
        <td>${r.failure_mode}</td>
        <td>${escape(r.subject)}</td>
        <td><span class="status-cell status-${status}">${status}</span></td>
        <td>${pDeploy}</td>
        <td>${pDyn}</td>
        <td>${tMed}</td>
      </tr>`;
    }).join("");
    summaryTableW.innerHTML = `
      <table class="summary-table">
        <thead><tr>
          <th>FM</th><th>Subject</th><th>Status</th>
          <th>P(deploy)</th><th>P(dynamic)</th><th>t_med</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function renderHeadlines(report) {
    /* Reproduce the engine's narrative client-side from structured
     * report fields. Same logic as report.py _narrative — kept here
     * so the HTML output matches what te-simulate prints. */
    headlineList.innerHTML = "";
    report.per_fm_results.forEach((r) => {
      const text = narrativeFor(r);
      if (text) {
        const li = document.createElement("li");
        li.textContent = text;
        headlineList.appendChild(li);
      }
    });
    if (!headlineList.children.length) {
      headlineList.innerHTML = "<li>All simulated FMs cleared without violations in the declared parameter envelope.</li>";
    }
  }

  function narrativeFor(r) {
    const subj = `${r.failure_mode}[${r.subject}]`;
    if (!r.simulated) {
      if (r.structural_status === "broken") {
        return `${subj}: verifier says BROKEN — no parameter assignment in the box satisfies the FM. The ABM cannot rescue a structurally-broken design; redesign first.`;
      }
      return "";
    }
    const n = Math.max(r.n_runs, 1);
    const pDeploy = r.n_violations_at_deployment / n;
    const pDyn = r.n_violations_dynamic / n;
    if (r.p_violation === 0) {
      return `${subj}: verifier flagged as ${r.structural_status}, but 0/${r.n_runs} sampled runs violated. The verifier's flagged corner is in the box but the declared distribution rarely reaches it.`;
    }
    if (pDeploy >= 0.5 && pDyn < 0.05) {
      return `${subj}: violates AT DEPLOYMENT in ${pct(pDeploy)} of runs — the sampled parameters often land in the unsafe region from the start. Configuration problem (tighten the declared parameter ranges).`;
    }
    if (pDyn >= 0.5) {
      const t = r.time_to_violation_median ? r.time_to_violation_median.toFixed(0) : "?";
      return `${subj}: violates DYNAMICALLY in ${pct(pDyn)} of runs (initially safe, becomes unsafe by period ${t} on median). Drift problem — add a corrective mechanism.`;
    }
    if (pDeploy >= 0.05 && pDyn >= 0.05) {
      return `${subj}: mixed — ${pct(pDeploy)} of runs unsafe at deployment, ${pct(pDyn)} drift in during operation.`;
    }
    return `${subj}: violates in ${pct(r.p_violation)} of runs. Possible but not dominant.`;
  }

  function renderPerFMCards(report) {
    cardsPane.innerHTML = "";
    report.per_fm_results.forEach((r) => {
      const card = document.createElement("div");
      card.className = "fm-card" + (r.simulated ? "" : " skipped");

      const title = document.createElement("h4");
      title.innerHTML = `${r.failure_mode} <small>· ${escape(r.subject)}</small>
        <span class="status-cell status-${r.structural_status}">${r.structural_status}</span>`;
      card.appendChild(title);

      // Predicates
      if (r.predicates && r.predicates.length) {
        r.predicates.forEach((p) => {
          const div = document.createElement("div");
          div.className = "predicate";
          div.textContent = `${p.variable} ${p.operator} ${formatNum(p.threshold)}`;
          card.appendChild(div);
        });
      }

      // Narrative
      const narrative = narrativeFor(r);
      if (narrative) {
        const div = document.createElement("p");
        div.className = "narrative";
        div.textContent = narrative;
        card.appendChild(div);
      }

      if (!r.simulated) {
        const note = document.createElement("p");
        note.className = "narrative";
        note.textContent = "Skipped: " + (r.skip_reason || "not simulated");
        card.appendChild(note);
        cardsPane.appendChild(card);
        return;
      }

      // Stats row
      const stats = document.createElement("div");
      stats.className = "stats-row";
      const n = Math.max(r.n_runs, 1);
      const ci = r.p_violation_ci || [0, 0];
      stats.innerHTML = `
        <div class="stat"><span class="label">runs</span><span class="val">${r.n_runs}</span></div>
        <div class="stat"><span class="label">P(violation)</span><span class="val">${pct(r.p_violation)}</span></div>
        <div class="stat"><span class="label">95% CI</span><span class="val">${pct(ci[0])}–${pct(ci[1])}</span></div>
        <div class="stat"><span class="label">violations</span><span class="val">${r.n_violations}/${r.n_runs}</span></div>
      `;
      card.appendChild(stats);

      // Charts row — outcome bar + time-to-violation quartiles.
      const chartsRow = document.createElement("div");
      chartsRow.className = "charts";
      const pBarCanvas = document.createElement("canvas");
      const histCanvas = document.createElement("canvas");
      chartsRow.appendChild(pBarCanvas);
      chartsRow.appendChild(histCanvas);
      card.appendChild(chartsRow);

      // Per-predicate trajectory charts (one per safety predicate)
      // when trajectory recording was enabled. Each chart shows the
      // median + p25/p75 envelope + a horizontal threshold line.
      if (r.predicate_trajectories && r.predicate_trajectories.length) {
        const trajRow = document.createElement("div");
        trajRow.className = "charts charts-trajectory";
        r.predicate_trajectories.forEach((traj) => {
          const wrap = document.createElement("div");
          wrap.className = "traj-wrap";
          const cap = document.createElement("div");
          cap.className = "traj-caption";
          cap.textContent = `${traj.variable} (threshold = ${formatNum(traj.threshold)})`;
          wrap.appendChild(cap);
          const cvs = document.createElement("canvas");
          wrap.appendChild(cvs);
          trajRow.appendChild(wrap);
          // Defer chart instantiation until cvs is in the DOM.
          setTimeout(() => {
            charts.push(buildTrajectoryChart(cvs, traj));
          }, 0);
        });
        card.appendChild(trajRow);
      }

      cardsPane.appendChild(card);

      // P(deploy) vs P(dynamic) vs P(safe) stacked bar.
      const safe = 1 - (r.n_violations_at_deployment / n) - (r.n_violations_dynamic / n);
      const pBar = new Chart(pBarCanvas, {
        type: "bar",
        data: {
          labels: ["P(deploy)", "P(dynamic)", "P(safe)"],
          datasets: [{
            data: [
              r.n_violations_at_deployment / n,
              r.n_violations_dynamic / n,
              Math.max(0, safe),
            ],
            backgroundColor: ["#ef4444", "#f59e0b", "#10b981"],
          }],
        },
        options: {
          plugins: { legend: { display: false }, title: { display: true, text: "Outcome distribution" } },
          scales: { y: { beginAtZero: true, max: 1, ticks: { callback: (v) => (v * 100).toFixed(0) + "%" } } },
        },
      });
      charts.push(pBar);

      // Time-to-violation histogram (only for dynamic violations, if any)
      const quartiles = [
        r.time_to_violation_p25,
        r.time_to_violation_median,
        r.time_to_violation_p75,
        r.time_to_violation_p95,
      ];
      if (r.n_violations_dynamic > 0 && quartiles.every((v) => v != null && v > 0)) {
        const labels = ["P25", "Median", "P75", "P95"];
        const hist = new Chart(histCanvas, {
          type: "bar",
          data: {
            labels,
            datasets: [{
              data: quartiles,
              backgroundColor: "#1d4ed8",
            }],
          },
          options: {
            plugins: { legend: { display: false }, title: { display: true, text: "Time to violation (periods)" } },
            scales: { y: { beginAtZero: true } },
          },
        });
        charts.push(hist);
      } else {
        // Render an empty placeholder so the canvas size stays consistent.
        const ctx = histCanvas.getContext("2d");
        ctx.font = "0.8rem sans-serif";
        ctx.fillStyle = "#666";
        ctx.textAlign = "center";
        ctx.fillText("All violations at deployment", histCanvas.width / 2 || 100, histCanvas.height / 2 || 60);
      }
    });
  }

  // -----------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------

  function setStatus(text, kind) {
    statusLine.className = "status-line" + (kind ? " " + kind : "");
    statusLine.textContent = text || "";
  }

  function int(s, fallback) {
    const n = parseInt(s, 10);
    return isNaN(n) ? fallback : n;
  }

  function pct(x) {
    if (x == null || isNaN(x)) return "—";
    return (x * 100).toFixed(0) + "%";
  }

  function formatNum(n) {
    if (n == null || isNaN(n)) return "—";
    if (Math.abs(n) >= 1e6 || (n !== 0 && Math.abs(n) < 0.01)) return n.toExponential(2);
    return Number.isInteger(n) ? String(n) : n.toFixed(3);
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  /**
   * Build the predicate-trajectory line chart.
   *
   * Layers:
   *   1. p25-p75 fill envelope (light)
   *   2. p5-p95 fill envelope (lighter, when available)  -- omitted
   *      since the report only carries p95 explicitly
   *   3. median (p50) line — heavy
   *   4. horizontal threshold reference line
   *
   * The vertical axis adapts to the trajectory's scale. The
   * threshold line tells the user whether the median crosses the
   * safety boundary anywhere in the horizon.
   */
  function buildTrajectoryChart(canvas, traj) {
    const points = traj.points || [];
    const labels = points.map((p) => p.t);
    const median = points.map((p) => p.p50);
    const p25    = points.map((p) => p.p25);
    const p75    = points.map((p) => p.p75);
    const p95    = points.map((p) => p.p95);
    const thresholdLine = points.map(() => traj.threshold);

    return new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          // p25 lower band (will be filled to p75 above it)
          {
            label: "p25",
            data: p25,
            borderColor: "rgba(29, 78, 216, 0)",
            backgroundColor: "rgba(29, 78, 216, 0.18)",
            pointRadius: 0,
            fill: "+1", // fill toward the next dataset (p75)
            tension: 0.15,
          },
          {
            label: "p75",
            data: p75,
            borderColor: "rgba(29, 78, 216, 0)",
            backgroundColor: "rgba(29, 78, 216, 0.18)",
            pointRadius: 0,
            fill: false,
            tension: 0.15,
          },
          {
            label: "p95",
            data: p95,
            borderColor: "rgba(29, 78, 216, 0.45)",
            borderDash: [3, 3],
            borderWidth: 1.2,
            pointRadius: 0,
            fill: false,
            tension: 0.15,
          },
          {
            label: "median",
            data: median,
            borderColor: "#1d4ed8",
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            tension: 0.15,
          },
          {
            label: `threshold (${traj.operator} ${formatNum(traj.threshold)})`,
            data: thresholdLine,
            borderColor: "#dc2626",
            borderDash: [6, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: true,
            position: "bottom",
            labels: { boxWidth: 12, font: { size: 10 } },
          },
          tooltip: { mode: "index", intersect: false },
          title: {
            display: false,
          },
        },
        scales: {
          x: { title: { display: true, text: "period" }, ticks: { maxTicksLimit: 8 } },
          y: { beginAtZero: false },
        },
      },
    });
  }

  function downloadJSON(filename, obj) {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
})();
