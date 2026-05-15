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

    // Headline: pass/fail counts only.
    // The weighted "risk score: X.Y %" was dropped per user feedback —
    // a single normalized percentage over 6 heterogeneous FMs implies
    // a precision the underlying score cannot deliver. The verdict
    // cards plus the pass/fail counts below are the honest summary.

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
      // Task 3 — derived function-shape labels. Surfaces what the
      // verifier inferred about each rule's monotonicity / convexity
      // so the user can sanity-check their coefficient ranges.
      if (report.function_shapes && report.function_shapes.length > 0) {
        const h = document.createElement("h3");
        h.textContent = "Function shapes (derived)";
        h.style.marginTop = "1rem";
        coherenceContainer.appendChild(h);
        const list = document.createElement("ul");
        list.className = "shape-list";
        report.function_shapes.forEach((s) => {
          const li = document.createElement("li");
          const deg = s.degree != null ? ` (degree=${s.degree})` : "";
          const idx = s.rule_kind.includes("regime")
            ? "" : `[${s.rule_index}]`;
          li.innerHTML =
            `<code>${escapeHtml(s.token_id)}.${escapeHtml(s.rule_kind)}${idx}</code> ` +
            `→ <strong>${escapeHtml(s.family)}${escapeHtml(deg)}</strong>` +
            ` &middot; ${escapeHtml(s.monotonicity)}, ${escapeHtml(s.convexity)}` +
            `<br/><em>${escapeHtml(s.summary)}</em>`;
          list.appendChild(li);
        });
        coherenceContainer.appendChild(list);
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

  // ===================================================================
  // Sprint 1+3 — refined diagnosis (trajectory + sensitivity)
  // ===================================================================

  function renderRefinedDiagnosis(rd) {
    const div = document.createElement("div");
    div.className = "refined-diagnosis";

    const heading = document.createElement("h4");
    heading.textContent = "Refined diagnosis (dynamic)";
    div.appendChild(heading);

    if (rd.headline) {
      const p = document.createElement("p");
      p.className = "refined-headline";
      p.textContent = rd.headline;
      div.appendChild(p);
    }

    // Inline sparkline — only when M actually changes meaningfully.
    if (rd.trajectory && rd.trajectory.samples && rd.trajectory.samples.length > 1) {
      const samples = rd.trajectory.samples;
      const M_values = samples.map((s) => s.M);
      const M_min = Math.min.apply(null, M_values);
      const M_max = Math.max.apply(null, M_values);
      const range = M_max - M_min;
      const meaningful = M_max > 0 && range / Math.max(M_max, 1) > 0.01;
      if (meaningful) {
        div.appendChild(renderSparkline(samples, rd.trajectory.metrics));
      }
    }

    // Notes from the trajectory (un-modeled regime hints, etc.).
    if (rd.trajectory && rd.trajectory.metrics && rd.trajectory.metrics.notes) {
      rd.trajectory.metrics.notes.forEach((n) => {
        const note = document.createElement("p");
        note.className = "refined-note";
        note.textContent = n;
        div.appendChild(note);
      });
    }

    // Binding inputs — only the ones that flip the verdict.
    const flippers = (rd.binding_inputs || []).filter((b) => b.flips_verdict);
    if (flippers.length > 0) {
      const label = document.createElement("h5");
      label.className = "refined-section-label";
      label.textContent = "Binding inputs (flip the verdict at extreme)";
      div.appendChild(label);
      const ul = document.createElement("ul");
      ul.className = "binding-inputs";
      flippers.forEach((b) => {
        const li = document.createElement("li");
        const arrow =
          b.verdict_at_min === b.verdict_at_max
            ? `${b.verdict_at_min}`
            : `${b.verdict_at_min} ↔ ${b.verdict_at_max}`;
        li.innerHTML =
          `<code>${escapeHtml(b.field)}</code> ` +
          `<span class="bi-range">[${formatNum(b.current_min)} … ${formatNum(b.current_max)}]</span> ` +
          `<span class="bi-arrow">${escapeHtml(arrow)}</span>`;
        ul.appendChild(li);
      });
      div.appendChild(ul);
    }

    return div;
  }

  function renderSparkline(samples, metrics) {
    const w = 220;
    const h = 56;
    const pad = 6;
    const M_values = samples.map((s) => s.M);
    const M_min = Math.min.apply(null, M_values);
    const M_max = Math.max.apply(null, M_values);
    const tMax = Math.max.apply(
      null,
      samples.map((s) => s.t)
    );
    const xScale = (t) => pad + (w - 2 * pad) * (tMax === 0 ? 0 : t / tMax);
    const yScale = (m) => {
      if (M_max - M_min === 0) return h - pad - (h - 2 * pad) * 0.5;
      return h - pad - (h - 2 * pad) * ((m - M_min) / (M_max - M_min));
    };
    const points = samples
      .map((s) => `${xScale(s.t).toFixed(1)},${yScale(s.M).toFixed(1)}`)
      .join(" ");

    // Mark the saturation point (if any) with a small vertical tick.
    let satTick = "";
    if (metrics && metrics.saturates_at != null) {
      const x = xScale(metrics.saturates_at).toFixed(1);
      satTick = `<line x1="${x}" y1="${pad}" x2="${x}" y2="${h - pad}" stroke="#5fa173" stroke-width="0.8" stroke-dasharray="2,2" />`;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "sparkline-wrapper";
    wrapper.innerHTML =
      `<svg class="sparkline" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="M(t) trajectory">` +
      `<polyline points="${points}" fill="none" stroke="#5b8bb5" stroke-width="1.5" />` +
      satTick +
      `</svg>` +
      `<div class="sparkline-caption">` +
      `<span>M(t): ${formatNum(M_min)} → ${formatNum(M_max)}</span>` +
      `<span class="sparkline-range">over ${tMax} periods</span>` +
      `</div>`;
    return wrapper;
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

    // Sprint 1+3 — refined diagnosis (trajectory + sensitivity).
    if (v.refined_diagnosis) {
      card.appendChild(renderRefinedDiagnosis(v.refined_diagnosis));
    }

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
