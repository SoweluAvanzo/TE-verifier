// Shared verdict-rendering helpers used by both the form-driven UI
// (/) and the YAML editor (/yaml).
//
// Exposes window.renderReport(report) which populates these elements
// (created in either index.html or form.html):
//   #report-summary      — severity pill + summary counts
//   #coherence-issues    — coherence warnings (top of report)
//   #verdict-cards       — one card per failure mode

(function () {
  // Fix C — glossary cache. Fetched once on first renderReport and
  // memoized; subsequent renders reuse the same data without
  // re-hitting the server.
  let _conditionsCache = null;
  let _conditionsPromise = null;

  function fetchConditions() {
    if (_conditionsCache) return Promise.resolve(_conditionsCache);
    if (_conditionsPromise) return _conditionsPromise;
    _conditionsPromise = fetch("/api/conditions")
      .then((r) => r.json())
      .then((data) => {
        _conditionsCache = data;
        return data;
      })
      .catch(() => {
        _conditionsCache = {};
        return {};
      });
    return _conditionsPromise;
  }

  function fmIdOf(verdict) {
    return verdict.failure_mode.split(":")[0].trim();
  }

  function renderReport(report) {
    const reportSummary = document.getElementById("report-summary");
    const coherenceContainer = document.getElementById("coherence-issues");
    const verdictCards = document.getElementById("verdict-cards");
    if (!reportSummary || !verdictCards) return;

    // ---- Summary ----
    reportSummary.innerHTML = "";

    // Headline: counts + a numeric percentage.
    // Per user feedback, we deliberately drop the "low / moderate /
    // high / critical" band label and the prose ("broadly sound",
    // "redesign required") — those over-claim relative to what the
    // weighted score can actually distinguish. The verdict cards plus
    // the pass/fail counts below are the honest summary.
    if (report.overall_risk) {
      const o = report.overall_risk;
      const overall = document.createElement("div");
      overall.className = "overall-risk";
      overall.dataset.band = o.band;
      overall.innerHTML =
        `<div class="overall-risk-headline">` +
        `<span class="overall-risk-dot" data-band="${o.band}"></span>` +
        `<span class="pct">Risk score: ${o.normalized_pct.toFixed(1)}%</span>` +
        `</div>`;
      reportSummary.appendChild(overall);
    }

    const meta = document.createElement("div");
    meta.className = "report-meta";
    const severityDot = document.createElement("span");
    severityDot.className = "severity-dot";
    severityDot.dataset.severity = report.severity;
    severityDot.title = `Severity: ${report.severity}`;
    meta.appendChild(severityDot);
    const counts = document.createElement("span");
    counts.className = "summary-counts";
    counts.textContent = Object.entries(report.summary || {})
      .filter(([_, v]) => v > 0)
      .map(([k, v]) => `${k.replace("_", " ")} ${v}`)
      .join(" · ");
    meta.appendChild(counts);
    reportSummary.appendChild(meta);

    // ---- Coherence issues ----
    if (coherenceContainer) {
      coherenceContainer.innerHTML = "";
      if (report.coherence_issues && report.coherence_issues.length > 0) {
        const h = document.createElement("h3");
        h.textContent = "Coherence issues";
        h.style.marginTop = "0";
        coherenceContainer.appendChild(h);
        report.coherence_issues.forEach((ci) => {
          const div = document.createElement("div");
          div.className = `coherence-issue coherence-${ci.severity}`;
          div.innerHTML =
            `<strong>[${escapeHtml(ci.severity)}]</strong> <code>${escapeHtml(ci.location)}</code><br/>` +
            `${escapeHtml(ci.message)}<br/>` +
            `<em>→ ${escapeHtml(ci.suggestion)}</em>`;
          coherenceContainer.appendChild(div);
        });
      }
    }

    // ---- Verdict cards ----
    verdictCards.innerHTML = "";
    (report.verdicts || []).forEach((v) => verdictCards.appendChild(renderVerdict(v)));

    // Fix C — once the cards are in the DOM, fetch the glossary and
    // hydrate the "Variables in this check" section on each card.
    fetchConditions().then((conditions) => {
      verdictCards.querySelectorAll("[data-fm-id]").forEach((card) => {
        const fmId = card.dataset.fmId;
        const cond = conditions[fmId];
        if (!cond || !cond.variables || cond.variables.length === 0) return;
        const slot = card.querySelector(".variable-glossary");
        if (!slot || slot.dataset.hydrated === "true") return;
        slot.innerHTML = renderGlossary(cond);
        slot.dataset.hydrated = "true";
      });
    });
  }

  function renderGlossary(cond) {
    const items = cond.variables
      .map(
        (v) =>
          `<dt><code>${escapeHtml(v.symbol)}</code> · <em>${escapeHtml(
            v.name
          )}</em>${v.units ? ` <span class="unit">[${escapeHtml(v.units)}]</span>` : ""}</dt>` +
          `<dd>${escapeHtml(v.description)}</dd>`
      )
      .join("");
    return (
      `<details class="glossary"><summary>Variables in this check</summary>` +
      `<dl>${items}</dl></details>`
    );
  }

  function renderVerdict(v) {
    const card = document.createElement("article");
    // Card surface itself is colour-coded; data attributes drive the
    // CSS palette (status × risk_level). No textual "pass / fail /
    // amber / red_critical" pills — the colour is the signal.
    card.className = "verdict-card";
    card.dataset.status = v.status;
    card.dataset.risk = v.risk_level || "not_applicable";
    card.dataset.fmId = fmIdOf(v);

    const header = document.createElement("header");
    const title = document.createElement("h3");
    title.textContent = v.failure_mode;
    header.appendChild(title);
    if (v.subject && v.subject !== "system") {
      const subject = document.createElement("span");
      subject.className = "subject-tag";
      subject.textContent = v.subject;
      header.appendChild(subject);
    }
    card.appendChild(header);

    // Fix C — glossary slot. Hydrated asynchronously after fetchConditions.
    const glossarySlot = document.createElement("div");
    glossarySlot.className = "variable-glossary";
    card.appendChild(glossarySlot);

    const cond = document.createElement("div");
    cond.className = "formal-condition";
    cond.textContent = v.formal_condition;
    card.appendChild(cond);

    const expl = document.createElement("p");
    expl.className = "verdict-explanation";
    expl.textContent = v.explanation;
    card.appendChild(expl);

    if (v.critical_values && v.critical_values.length > 0) {
      const cvLabel = document.createElement("h4");
      cvLabel.textContent = "Critical values";
      card.appendChild(cvLabel);
      const ul = document.createElement("ul");
      ul.className = "cv-list";
      v.critical_values.forEach((cv) => {
        const li = document.createElement("li");
        li.innerHTML =
          `<strong>${escapeHtml(cv.parameter)}</strong> ${escapeHtml(cv.direction)} ${formatNum(cv.value)}<br/>` +
          `<span class="cv-formula">${escapeHtml(cv.formula)}</span><br/>` +
          `<small>${escapeHtml(cv.explanation)}</small>`;
        ul.appendChild(li);
      });
      card.appendChild(ul);
    }

    if (v.recommendation) {
      const rec = v.recommendation;
      const recDiv = document.createElement("div");
      recDiv.className = "recommendation";
      const headline = document.createElement("div");
      headline.className = "recommendation-headline";
      headline.textContent = `Recommendation: ${rec.parameter} ${rec.direction} ${formatNum(rec.safe_threshold)}`;
      recDiv.appendChild(headline);
      const narr = document.createElement("p");
      narr.className = "recommendation-narrative";
      narr.textContent = rec.narrative;
      recDiv.appendChild(narr);
      if (rec.mechanism_mappings && rec.mechanism_mappings.length > 0) {
        const table = document.createElement("table");
        table.className = "mechanism-table";
        table.innerHTML =
          "<thead><tr><th>Mechanism</th><th>Range</th><th>Status</th></tr></thead>";
        const tbody = document.createElement("tbody");
        rec.mechanism_mappings.forEach((m) => {
          const match = m.match(/^(.+?):\s*(.+?)\s*—\s*(.+)$/);
          if (!match) return;
          const [_, name, range, tag] = match;
          let cls = "safe";
          if (tag.includes("partially")) cls = "partially";
          else if (tag.includes("unsafe")) cls = "unsafe";
          const tr = document.createElement("tr");
          tr.className = cls;
          tr.innerHTML =
            `<td><code>${escapeHtml(name)}</code></td>` +
            `<td>${escapeHtml(range)}</td>` +
            `<td><span class="mechanism-tag ${cls}">${escapeHtml(tag)}</span></td>`;
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        recDiv.appendChild(table);
      }
      card.appendChild(recDiv);
    }

    if (v.counterexample) {
      const ce = v.counterexample;
      const ceDiv = document.createElement("div");
      ceDiv.className = "counterexample";
      const det = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Show counterexample";
      det.appendChild(summary);
      if (ce.binding_constraint) {
        const bc = document.createElement("div");
        bc.className = "binding-constraint";
        bc.textContent = `Binding: ${ce.binding_constraint}`;
        det.appendChild(bc);
      }
      const narr = document.createElement("p");
      narr.textContent = ce.narrative;
      det.appendChild(narr);
      if (ce.parameter_values) {
        const table = document.createElement("table");
        const tbody = document.createElement("tbody");
        Object.entries(ce.parameter_values).forEach(([k, val]) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `<td>${escapeHtml(k)}</td><td>${formatNum(val)}</td>`;
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        det.appendChild(table);
      }
      ceDiv.appendChild(det);
      card.appendChild(ceDiv);
    }

    if (
      (v.swept_fields && v.swept_fields.length) ||
      (v.committed_fields && v.committed_fields.length)
    ) {
      const sf = document.createElement("div");
      sf.style.marginTop = "0.6em";
      if (v.swept_fields && v.swept_fields.length) {
        const label = document.createElement("h4");
        label.style.margin = "0.3em 0 0.15em";
        label.textContent = "Searched (range / unspecified)";
        sf.appendChild(label);
        v.swept_fields.forEach((f) => {
          const pill = document.createElement("span");
          pill.className = "swept-pill";
          pill.textContent = f;
          sf.appendChild(pill);
        });
      }
      if (v.committed_fields && v.committed_fields.length) {
        const label = document.createElement("h4");
        label.style.margin = "0.5em 0 0.15em";
        label.textContent = "Committed (point value)";
        sf.appendChild(label);
        v.committed_fields.forEach((f) => {
          const pill = document.createElement("span");
          pill.className = "committed-pill";
          pill.textContent = f;
          sf.appendChild(pill);
        });
      }
      card.appendChild(sf);
    }

    if (v.suggestions && v.suggestions.length) {
      const sg = document.createElement("div");
      sg.className = "suggestions";
      const label = document.createElement("h4");
      label.textContent = "Other levers";
      sg.appendChild(label);
      const ul = document.createElement("ul");
      v.suggestions.forEach((s) => {
        const li = document.createElement("li");
        li.textContent = s;
        ul.appendChild(li);
      });
      sg.appendChild(ul);
      card.appendChild(sg);
    }

    return card;
  }

  function formatNum(n) {
    if (typeof n !== "number") return String(n);
    if (n === 0) return "0";
    const abs = Math.abs(n);
    if (abs >= 1e6 || (abs < 1e-3 && abs > 0)) return n.toExponential(3);
    if (Number.isInteger(n)) return n.toString();
    return n.toFixed(4).replace(/\.?0+$/, "");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Expose globally
  window.renderReport = renderReport;
  window.renderVerdict = renderVerdict;
})();
