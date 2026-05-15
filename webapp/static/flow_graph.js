/* Phase M — Cytoscape flow-graph renderer.
 *
 * Two entry points:
 *
 *   window.renderFlowGraph(canvasEl, legendEl, summaryEl, diagEl, payload, layout)
 *     — pure renderer; payload is the /api/flow-graph response.
 *
 *   window.bindFormFlowGraph(buildYamlFn)
 *     — wires the form's Stage-3.2 controls; debounce-fetches /api/flow-graph
 *       on every form mutation using ``buildYamlFn()`` to obtain the
 *       current YAML.
 *
 * Compact-by-design rules baked in here:
 *
 *   * Node styling by kind (single shape + colour per kind, no overrides).
 *   * Edge styling by ``style`` field on the data ('solid' / 'dashed' /
 *     'double' / 'dotted').
 *   * Edge labels are the short ``label`` string the backend produced;
 *     full detail lives in the ``tooltip`` (shown as a tippy on hover —
 *     gracefully degrades to title attribute when tippy not loaded).
 */

(function () {
  if (typeof window === "undefined") return;

  // -------------------------------------------------------------------
  // Stable colour per node kind. Keep the palette small to avoid the
  // "rainbow vomit" effect; reuse explore.js's typeColor pattern.
  // -------------------------------------------------------------------
  const KIND_STYLE = {
    MintPool:        { shape: "ellipse",   bg: "#3b8a3b", border: "#1f5a1f", color: "#fff" },
    BurnSink:        { shape: "ellipse",   bg: "#d0524a", border: "#7e2922", color: "#fff" },
    RoleWallet:      { shape: "round-rectangle", bg: "#7892d1", border: "#3a539b", color: "#fff" },
    AdminWallet:     { shape: "round-rectangle", bg: "#b07f1f", border: "#6f4e0a", color: "#fff" },
    AssetInventory:  { shape: "hexagon",   bg: "#cc7ab8", border: "#7b3567", color: "#fff" },
    Event:           { shape: "diamond",   bg: "#5fb9c4", border: "#2b6970", color: "#fff" },
    Peg:             { shape: "pentagon",  bg: "#444",    border: "#222",    color: "#fff" },
    External:        { shape: "octagon",   bg: "#888",    border: "#444",    color: "#fff" },
  };

  function styleFor(kind) {
    return KIND_STYLE[kind] || KIND_STYLE.RoleWallet;
  }

  // Edge style → Cytoscape line-style + width
  function edgeLineStyle(s) {
    return s === "dashed" ? "dashed"
         : s === "dotted" ? "dotted"
         : "solid";   // 'double' is rendered with a thicker solid stroke
  }
  function edgeWidth(d) {
    if (d.style === "double") return 4;
    if (d.kind === "EventDrives") return 1;
    return 2;
  }
  function edgeColor(d, view) {
    // M.18 — diff view recolours edges by realised-vs-spec class.
    if (view === "diff" && d.diff_class) {
      if (d.diff_class === "unused")  return "#bbb";
      if (d.diff_class === "matched") return "#3b8a3b";
      if (d.diff_class === "under")   return "#b07f1f";
      if (d.diff_class === "over")    return "#d0524a";
    }
    if (d.kind === "EventDrives") return "#aab";
    if (d.kind === "Emission") return "#3b8a3b";
    if (d.kind === "Burn") return "#d0524a";
    if (d.kind === "CrossTokenFlow") return "#305ed3";
    if (d.kind && d.kind.startsWith("Redemption")) return "#cc7ab8";
    if (d.kind === "PegDefence") return "#666";
    return "#666";
  }

  function edgeLabel(d, view) {
    if (view === "realised" && d.realised_label !== undefined) {
      return d.realised_label;
    }
    if (view === "diff" && d.realised_label !== undefined) {
      // Diff view shows realised + (×ratio vs expected) when both > 0.
      if (d.expected && d.realised) {
        const ratio = d.realised / d.expected;
        return `${d.realised_label} (×${ratio.toFixed(1)})`;
      }
      return d.realised_label;
    }
    return d.label || "";
  }

  // -------------------------------------------------------------------
  // Renderer
  // -------------------------------------------------------------------

  let _cy = null;

  function renderFlowGraph(canvasEl, legendEl, summaryEl, diagEl, payload, layout, view) {
    if (!canvasEl || !payload) return;
    view = view || "spec";
    const elements = payload.elements || { nodes: [], edges: [] };
    // Empty state: useful when the form is still being filled out.
    if (!elements.nodes.length) {
      canvasEl.innerHTML =
        `<div class="flow-empty-state">` +
        `Add at least one token (and optionally an event / asset / agent type) to see the flow diagram.` +
        `</div>`;
      if (legendEl) legendEl.innerHTML = "";
      if (summaryEl) summaryEl.textContent = "0 nodes · 0 edges";
      if (diagEl) diagEl.innerHTML = "";
      if (_cy) { _cy.destroy(); _cy = null; }
      return;
    } else {
      // Reset placeholder before Cytoscape mounts (it needs an empty div).
      canvasEl.innerHTML = "";
    }
    if (_cy) {
      _cy.destroy();
      _cy = null;
    }
    _cy = cytoscape({
      container: canvasEl,
      elements,
      style: [
        { selector: "node", style: {
            "background-color": (n) => styleFor(n.data("kind")).bg,
            "border-color":     (n) => styleFor(n.data("kind")).border,
            "border-width": 1.5,
            "shape":            (n) => styleFor(n.data("kind")).shape,
            // Phase M.19 — readability: black label text, white halo
            // so it stays legible against dark or coloured node fills.
            "color": "#111",
            "label": (n) => n.data("label") || n.data("id"),
            "font-size": 11,
            "font-weight": 600,
            "text-outline-color": "#fff",
            "text-outline-width": 2,
            "text-outline-opacity": 0.9,
            "text-valign": "center",
            "text-halign": "center",
            "text-wrap": "wrap",
            "text-max-width": 110,
            "width":  (n) => (n.data("kind") === "Event" ? 36 : 70),
            "height": (n) => (n.data("kind") === "Event" ? 36 : 34),
        }},
        { selector: "edge", style: {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "width": (e) => edgeWidth(e.data()),
            "line-color": (e) => edgeColor(e.data(), view),
            "target-arrow-color": (e) => edgeColor(e.data(), view),
            "line-style": (e) => edgeLineStyle(e.data("style")),
            "label": (e) => edgeLabel(e.data(), view),
            // Phase M.19 — readability: bigger black label on a white
            // background so the rate text is readable across edge
            // colours.
            "font-size": 11,
            "font-weight": 500,
            "color": "#111",
            "text-background-color": "#fff",
            "text-background-opacity": 0.92,
            "text-background-padding": 2,
            "text-border-color": "#d6dde6",
            "text-border-width": 0.5,
            "text-border-opacity": 0.7,
            "text-rotation": "autorotate",
            "opacity": (e) =>
              (view === "diff" && e.data("diff_class") === "unused") ? 0.4 : 1.0,
        }},
      ],
      layout: {
        name: layout || "cose",
        animate: false,
        padding: 16,
        randomize: false,
        nodeRepulsion: 8000,
        idealEdgeLength: 90,
      },
      wheelSensitivity: 0.25,
    });

    // Hover tooltip via title attribute on the canvas (poor-man's tippy).
    _cy.on("mouseover", "edge, node", (ev) => {
      const d = ev.target.data();
      canvasEl.title = d.tooltip || d.label || d.id || "";
    });
    _cy.on("mouseout", "edge, node", () => { canvasEl.title = ""; });

    // Summary + legend + diagnostics.
    if (summaryEl) {
      const s = payload.summary || {};
      const rs = payload.realised_summary;
      let extra = "";
      if (view !== "spec" && rs) {
        extra = ` · realised horizon=${rs.horizon}`;
      }
      summaryEl.textContent =
        `${s.n_nodes || 0} nodes · ${s.n_edges || 0} edges · ` +
        `${s.components || 0} component(s) · ` +
        `${(s.tokens || []).length} token(s)${extra}`;
    }
    if (legendEl) renderLegend(legendEl, payload, view);
    if (diagEl)   renderDiagnostics(diagEl, payload);
  }

  // Phase M.19 — richer, explicitly-categorised legend. Each visual
  // dimension (node kind, edge kind, edge style, diff class) gets its
  // own row with a label so the user can decode the graph without
  // referring to docs.
  const NODE_KIND_DESC = {
    MintPool:       "mint pool · where the token is minted from",
    BurnSink:       "burn sink · where the token is destroyed",
    RoleWallet:     "per-role wallet · agent holdings",
    AdminWallet:    "admin / governance-only wallet",
    AssetInventory: "non-tokenized asset inventory",
    Event:          "event · drives ≥ 1 rule",
    Peg:            "peg anchor",
    External:       "external value reference (fiat, off-system)",
  };
  const EDGE_KIND_DESC = {
    Emission:               "mint pool → wallet (token issued to a role)",
    Burn:                   "wallet → burn sink (token destroyed)",
    CrossTokenFlow:         "burning one token mints / burns another",
    "Redemption-AssetLeg":  "wallet spends tokens to acquire an asset",
    "Redemption-TokenLeg":  "tokens burnt as part of an asset redemption",
    EventDrives:            "event triggers an emission / burn rule",
    PegDefence:             "defensive mint or burn to maintain a peg",
  };
  const EDGE_STYLE_DESC = {
    solid:  "unconditional rule (always fires)",
    dashed: "condition-gated rule (predicate must hold)",
    double: "DSL-expression-driven rule (state-dependent)",
    dotted: "event-drives annotation (not a value flow)",
  };

  function renderLegend(el, payload, view) {
    const seenNodeKinds = new Set();
    const seenEdgeKinds = new Set();
    const seenStyles = new Set();
    for (const n of (payload.elements?.nodes || [])) {
      seenNodeKinds.add(n.data.kind);
    }
    for (const e of (payload.elements?.edges || [])) {
      seenEdgeKinds.add(e.data.kind);
      if (e.data.style) seenStyles.add(e.data.style);
    }

    function nodeLegendItem(k) {
      const st = styleFor(k);
      const shape = `border-radius:${st.shape === "ellipse" ? 50 : 3}px`;
      return `<span class="flow-legend-item">
        <span class="flow-legend-dot" style="background:${st.bg};border-color:${st.border};${shape}"></span>
        <span class="flow-legend-label"><strong>${escapeHtml(k)}</strong> — ${escapeHtml(NODE_KIND_DESC[k] || "")}</span>
      </span>`;
    }
    function edgeLegendItem(k) {
      const col = edgeColor({ kind: k });
      return `<span class="flow-legend-item">
        <span class="flow-legend-line" style="background:${col}"></span>
        <span class="flow-legend-label"><strong>${escapeHtml(k)}</strong> — ${escapeHtml(EDGE_KIND_DESC[k] || "")}</span>
      </span>`;
    }
    function styleLegendItem(s) {
      const lineCss = s === "dashed" ? "border-top:2px dashed #444"
                    : s === "dotted" ? "border-top:2px dotted #444"
                    : s === "double" ? "border-top:4px double #444"
                    : "background:#444;height:2px";
      return `<span class="flow-legend-item">
        <span class="flow-legend-line-styled" style="${lineCss}"></span>
        <span class="flow-legend-label"><strong>${escapeHtml(s)}</strong> — ${escapeHtml(EDGE_STYLE_DESC[s] || "")}</span>
      </span>`;
    }

    const nodeRow = [...seenNodeKinds].sort().map(nodeLegendItem).join("");
    const edgeRow = [...seenEdgeKinds].sort().map(edgeLegendItem).join("");
    const styleRow = [...seenStyles].sort().map(styleLegendItem).join("");
    const diffRow = (view === "diff") ? `
      <div class="flow-legend-row">
        <span class="flow-legend-section">Diff class:</span>
        <span class="flow-legend-item"><span class="flow-legend-line" style="background:#3b8a3b"></span>
          <span class="flow-legend-label"><strong>matched</strong> — realised within ±1 order of magnitude of spec</span></span>
        <span class="flow-legend-item"><span class="flow-legend-line" style="background:#b07f1f"></span>
          <span class="flow-legend-label"><strong>under</strong> — realised &lt; 0.1× spec</span></span>
        <span class="flow-legend-item"><span class="flow-legend-line" style="background:#d0524a"></span>
          <span class="flow-legend-label"><strong>over</strong> — realised &gt; 10× spec</span></span>
        <span class="flow-legend-item"><span class="flow-legend-line" style="background:#bbb"></span>
          <span class="flow-legend-label"><strong>unused</strong> — realised ≈ 0 (spec edge never fired)</span></span>
      </div>` : "";

    el.innerHTML = `
      <details class="flow-legend-details" open>
        <summary>How to read this diagram</summary>
        <div class="flow-legend-row">
          <span class="flow-legend-section">Node types:</span>${nodeRow}
        </div>
        ${ view === "diff"
            ? diffRow
            : `<div class="flow-legend-row">
                 <span class="flow-legend-section">Edge kinds:</span>${edgeRow}
               </div>` }
        ${ styleRow ? `<div class="flow-legend-row">
                         <span class="flow-legend-section">Edge styles:</span>${styleRow}
                       </div>` : "" }
        <div class="flow-legend-row flow-legend-note">
          Label inside a node = the role / token / asset / event id. Hover any
          edge to see the full rate spec + conditions in the tooltip.
        </div>
      </details>
    `;
  }

  function renderDiagnostics(el, payload) {
    const diag = payload.diagnostics || [];
    if (!diag.length) {
      el.innerHTML = `<p class="flow-diag-ok">✓ No spec-graph inconsistencies detected.</p>`;
      return;
    }
    el.innerHTML = `<h4>Spec-graph diagnostics</h4><ul class="flow-diag-list">` +
      diag.map((d) => {
        const sevCls = d.severity === "error" ? "flow-diag-error"
                     : d.severity === "warn"  ? "flow-diag-warn"
                     : "flow-diag-info";
        const icon = d.severity === "error" ? "✕"
                   : d.severity === "warn"  ? "⚠"
                   : "ℹ";
        return `<li class="${sevCls}">${icon} <code>${escapeHtml(d.kind)}</code> — ${escapeHtml(d.message)}</li>`;
      }).join("") + `</ul>`;
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;",
      '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // -------------------------------------------------------------------
  // Form integration — debounced fetch on form change
  // -------------------------------------------------------------------

  function bindFormFlowGraph(buildYamlFn) {
    const canvas = document.getElementById("flow-graph-canvas");
    const legend = document.getElementById("flow-graph-legend");
    const summary = document.getElementById("flow-graph-summary");
    const diag = document.getElementById("flow-graph-diagnostics");
    const layoutSel = document.getElementById("flow-graph-layout");
    const refreshBtn = document.getElementById("flow-graph-refresh");
    if (!canvas) return;

    let lastYaml = "";
    let timer = null;

    async function refresh(force) {
      let yaml;
      try {
        yaml = await buildYamlFn();
      } catch (e) {
        summary.textContent = `Form error: ${e.message || e}`;
        return;
      }
      if (!yaml) return;
      if (!force && yaml === lastYaml) return;
      lastYaml = yaml;
      try {
        const r = await fetch("/api/flow-graph", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ yaml }),
        });
        const body = await r.json();
        if (!r.ok || body.error) {
          summary.textContent = `Graph error: ${body.error || r.statusText}`;
          return;
        }
        renderFlowGraph(canvas, legend, summary, diag, body, layoutSel?.value);
      } catch (e) {
        summary.textContent = `Network error: ${e.message || e}`;
      }
    }

    function scheduleRefresh() {
      clearTimeout(timer);
      timer = setTimeout(refresh, 350);
    }
    document.addEventListener("input",  scheduleRefresh);
    document.addEventListener("change", scheduleRefresh);
    if (refreshBtn) refreshBtn.addEventListener("click", () => refresh(true));
    if (layoutSel)  layoutSel.addEventListener("change", () => refresh(true));

    // Initial draw after the form has had a chance to seed defaults.
    setTimeout(() => refresh(true), 600);
  }

  window.renderFlowGraph = renderFlowGraph;
  window.bindFormFlowGraph = bindFormFlowGraph;
})();
