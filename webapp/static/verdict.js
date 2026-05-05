// Shared verdict-rendering helpers used by both the form-driven UI
// (/) and the YAML editor (/yaml).
//
// Exposes window.renderReport(report) which populates these elements
// (created in either index.html or form.html):
//   #report-summary      — severity pill + summary counts
//   #coherence-issues    — coherence warnings (top of report)
//   #verdict-cards       — one card per failure mode

(function () {
  function renderReport(report) {
    const reportSummary = document.getElementById("report-summary");
    const coherenceContainer = document.getElementById("coherence-issues");
    const verdictCards = document.getElementById("verdict-cards");
    if (!reportSummary || !verdictCards) return;

    // ---- Summary ----
    reportSummary.innerHTML = "";
    const sevPill = document.createElement("span");
    sevPill.className = `severity-pill severity-${report.severity}`;
    sevPill.textContent = `Severity: ${report.severity.toUpperCase()}`;
    reportSummary.appendChild(sevPill);
    const counts = document.createElement("span");
    counts.style.fontFamily = "var(--font-mono)";
    counts.style.color = "var(--color-muted)";
    counts.textContent = Object.entries(report.summary || {})
      .filter(([_, v]) => v > 0)
      .map(([k, v]) => `${k}=${v}`)
      .join(" · ");
    reportSummary.appendChild(counts);

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
  }

  function renderVerdict(v) {
    const card = document.createElement("article");
    card.className = `verdict-card status-${v.status}`;

    const header = document.createElement("header");
    const pill = document.createElement("span");
    pill.className = `status-pill ${v.status}`;
    pill.textContent = v.status.replace("_", " ");
    const title = document.createElement("h3");
    title.textContent = v.failure_mode;
    const subject = document.createElement("span");
    subject.className = "subject-tag";
    subject.textContent = v.subject;
    header.appendChild(pill);
    header.appendChild(title);
    header.appendChild(subject);
    card.appendChild(header);

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
