// Form-driven UI orchestration.
//
// Strategy:
// - Read the form, build a JS object mirroring the Pydantic IR shape.
// - POST as JSON to /api/build-and-verify.
// - On response, render the verdict in the right pane (verdict.js).
// - "Load example" buttons hit /api/yaml-to-ir to fetch a hydrated dict
//   and populate the form fields from it.

const ENUMS = JSON.parse(document.getElementById("enums-data").textContent);

const form = document.getElementById("te-form");
const verifyBtn = document.getElementById("verify-btn");
const verifyStatus = document.getElementById("verify-status");
const downloadBtn = document.getElementById("download-btn");
const resetBtn = document.getElementById("reset-btn");
const uploadBtn = document.getElementById("upload-btn");
const uploadInput = document.getElementById("upload-yaml");
const verdictEmpty = document.getElementById("verdict-empty");
const verdictContent = document.getElementById("verdict-content");
const agentContainer = document.getElementById("agent-types-container");
const addAgentBtn = document.getElementById("add-agent-btn");
const topologyDegree = document.getElementById("topology-degree");

// Track the most recent verified YAML for download.
let lastVerifiedYaml = "";

// =====================================================================
// Agent-type rows (variable count)
// =====================================================================

let agentCounter = 0;

function addAgentRow(prefill = {}) {
  agentCounter++;
  const idx = agentCounter;
  const div = document.createElement("div");
  div.className = "agent-row";
  div.dataset.idx = idx;
  div.innerHTML = `
    <div class="agent-row-head">
      <h4>Agent type #${idx}</h4>
      <button type="button" class="remove-agent">remove</button>
    </div>
    <div class="agent-grid">
      <div class="field">
        <label>ID</label>
        <input type="text" name="agent-${idx}-id" placeholder="e.g. contributor"
               value="${escapeAttr(prefill.id || "")}" />
      </div>
      <div class="field">
        <label>Fraction (0–1)</label>
        <input type="number" name="agent-${idx}-fraction" min="0" max="1" step="0.01"
               value="${prefill.fraction ?? ""}" />
      </div>
      <div class="field">
        <label>Role</label>
        <select name="agent-${idx}-role">
          <option value="">— unspecified —</option>
          ${ENUMS.agent_roles.map(
            (r) => `<option value="${r}" ${prefill.role === r ? "selected" : ""}>${r}</option>`
          ).join("")}
        </select>
      </div>
      <div class="field">
        <label>Balance share (optional, 0–1)</label>
        <input type="number" name="agent-${idx}-balance" min="0" max="1" step="0.01"
               value="${prefill.balance_share ?? ""}" />
      </div>
    </div>
    <div class="field range-field">
      <label>Expected holding time (periods)</label>
      <div class="range">
        <input type="number" name="agent-${idx}-tau-min" min="0" step="any" placeholder="min"
               value="${prefill.expected_holding_time?.expected_periods?.min ?? ""}" />
        <span>to</span>
        <input type="number" name="agent-${idx}-tau-max" min="0" step="any" placeholder="max"
               value="${prefill.expected_holding_time?.expected_periods?.max ?? ""}" />
      </div>
    </div>
  `;
  div.querySelector(".remove-agent").addEventListener("click", () => div.remove());
  agentContainer.appendChild(div);
}

addAgentBtn.addEventListener("click", () => addAgentRow());

// Seed with one row
addAgentRow({ id: "user", fraction: 1.0, expected_holding_time: { expected_periods: { min: 5, max: 5 } } });

// Show topology_degree fields when topology = network
const topologySelect = document.getElementById("part-topology");
topologySelect.addEventListener("change", () => {
  topologyDegree.hidden = topologySelect.value !== "network";
});

// =====================================================================
// Form → IR object
// =====================================================================

function buildIR() {
  const fd = new FormData(form);
  const ir = { meta: {}, tokens: [{}], participants: {}, governance: {} };

  // ---------- Meta ----------
  ir.meta.name = fd.get("meta-name") || "Untitled";
  const desc = fd.get("meta-description");
  if (desc) ir.meta.description = desc;
  ir.meta.archetype = fd.get("meta-archetype") || "other";
  ir.meta.nfrs = {
    resilience: parseInt(fd.get("nfr-resilience") || "3"),
    adaptability: parseInt(fd.get("nfr-adaptability") || "3"),
    accessibility: parseInt(fd.get("nfr-accessibility") || "3"),
    transparency: parseInt(fd.get("nfr-transparency") || "3"),
    proportionality: parseInt(fd.get("nfr-proportionality") || "3"),
    circulation_speed: fd.get("nfr-circulation") || "balanced",
    governance_maturity: fd.get("nfr-maturity") || "medium_term",
  };

  // ---------- Token (single) ----------
  const tok = ir.tokens[0];
  tok.id = fd.get("token-id") || "T";
  tok.function = fd.getAll("token-function");
  if (tok.function.length === 0) tok.function = ["medium_of_exchange"];
  const earning = fd.getAll("token-earning");
  if (earning.length) tok.earning_mechanisms = earning;
  tok.value_anchor = fd.get("token-anchor") || "none";
  const holding = fd.getAll("token-holding");
  if (holding.length) {
    tok.holding_incentives = holding;
    tok.holding_incentive_present = holding.some((h) => h !== "none");
  }
  const cv = fd.get("token-verification");
  if (cv) tok.contribution_verification = cv;
  const rm = fd.get("token-redemption");
  if (rm) tok.redemption_mechanism = rm;

  const kRange = readRange(fd, "token-K-min", "token-K-max");
  if (kRange) tok.offer_variety_K = kRange;

  // Emission rule
  const emitTrigger = fd.get("emit-trigger");
  if (emitTrigger && emitTrigger !== "none") {
    const freq = readAsymptoticFromForm(fd, "emit-frequency", "emit-freq-min", "emit-freq-max");
    const fnClass = readAsymptoticFromForm(fd, "emit-class", "emit-fn-min", "emit-fn-max");
    tok.emission_rules = [
      {
        trigger: { kind: emitTrigger, ...(freq && { event_frequency: freq }) },
        function: {
          sign: fd.get("emit-sign") || "always_positive",
          asymptotic_class: fnClass || { family: "constant", parameter_ranges: { c: { min: 1, max: 1 } } },
        },
      },
    ];
  } else {
    tok.emission_rules = [];
  }

  // Burn rule
  const burnTrigger = fd.get("burn-trigger");
  if (burnTrigger && burnTrigger !== "none") {
    const freq = readAsymptoticFromForm(fd, null, "burn-freq-min", "burn-freq-max");
    const fnClass = readAsymptoticFromForm(fd, null, "burn-fn-min", "burn-fn-max");
    tok.burn_rules = [
      {
        trigger: { kind: burnTrigger, ...(freq && { event_frequency: freq }) },
        function: {
          sign: "always_negative",
          asymptotic_class: fnClass || { family: "constant", parameter_ranges: { c: { min: 1, max: 1 } } },
        },
      },
    ];
  } else {
    tok.burn_rules = [];
  }

  // ---------- Participants ----------
  ir.participants.count_N = readRange(fd, "part-N-min", "part-N-max") || { min: 1, max: 1 };
  ir.participants.expected_Q = readRange(fd, "part-Q-min", "part-Q-max") || { min: 0, max: 0 };
  ir.participants.average_demand_d = readRange(fd, "part-d-min", "part-d-max") || { min: 0, max: 0 };
  const growthFamily = fd.get("part-growth") || "constant";
  const growthRange = readRange(fd, "part-growth-min", "part-growth-max");
  ir.participants.growth_g = {
    family: growthFamily,
    parameter_ranges: growthRange ? { value: growthRange } : {},
  };
  ir.participants.topology = fd.get("part-topology") || "well_mixed";
  if (ir.participants.topology === "network") {
    const deg = readRange(fd, "part-degree-min", "part-degree-max");
    if (deg) ir.participants.topology_params = { average_degree: deg };
  }

  // Agent types
  const agents = [];
  agentContainer.querySelectorAll(".agent-row").forEach((row) => {
    const idx = row.dataset.idx;
    const id = fd.get(`agent-${idx}-id`);
    if (!id) return;
    const fraction = parseFloat(fd.get(`agent-${idx}-fraction`) || "0");
    if (fraction <= 0) return;
    const ag = {
      id,
      fraction,
      expected_holding_time: {
        expected_periods: readRange(fd, `agent-${idx}-tau-min`, `agent-${idx}-tau-max`) || {
          min: 1,
          max: 1,
        },
      },
    };
    const role = fd.get(`agent-${idx}-role`);
    if (role) ag.role = role;
    const bal = fd.get(`agent-${idx}-balance`);
    if (bal && bal !== "") ag.balance_share = parseFloat(bal);
    agents.push(ag);
  });
  if (agents.length) ir.participants.agent_types = agents;

  // ---------- Governance ----------
  ir.governance.type = fd.get("gov-type") || "dao";
  const ruleStruct = {};
  const decisions = [
    "emission_rate_adjustment",
    "burn_rate_adjustment",
    "participant_eligibility",
    "provider_onboarding",
    "exchange_ratios",
    "reward_structure_modification",
    "system_rule_modification",
  ];
  for (const d of decisions) {
    const val = fd.get(`gov-rule-${d}`);
    if (val) ruleStruct[d] = val;
  }
  if (Object.keys(ruleStruct).length) ir.governance.rule_structure = ruleStruct;

  const gammaRange = readRange(fd, "gov-gamma-min", "gov-gamma-max");
  if (gammaRange) ir.governance.monitoring_capacity_gamma = gammaRange;

  const sanctionKind = fd.get("gov-sanction-kind") || "warning";
  const sanctionStruct = { kind: sanctionKind };
  const sRange = readRange(fd, "gov-S-min", "gov-S-max");
  if (sRange) sanctionStruct.S_normalized = sRange;
  ir.governance.sanction_structure = sanctionStruct;

  const giniRange = readRange(fd, "gov-gini-min", "gov-gini-max");
  if (giniRange) ir.governance.token_balance_gini = giniRange;

  return ir;
}

function readRange(fd, minKey, maxKey) {
  const minRaw = fd.get(minKey);
  const maxRaw = fd.get(maxKey);
  if (minRaw == null || minRaw === "") return null;
  if (maxRaw == null || maxRaw === "") return null;
  const min = parseFloat(minRaw);
  const max = parseFloat(maxRaw);
  if (Number.isNaN(min) || Number.isNaN(max)) return null;
  return { min, max };
}

function readAsymptoticFromForm(fd, familyKey, minKey, maxKey) {
  const family = familyKey ? fd.get(familyKey) || "constant" : "constant";
  const range = readRange(fd, minKey, maxKey);
  if (!range && family === "unspecified") {
    return { family: "unspecified", parameter_ranges: { value: { min: 0, max: 1e9 } } };
  }
  if (!range) return null;
  if (family === "bounded_range") {
    return { family, bounds: { min: range.min, max: range.max } };
  }
  // For constant / linear / unspecified — use parameter range under "c" or "value"
  const paramKey = family === "linear" ? "a" : family === "unspecified" ? "value" : "c";
  return { family, parameter_ranges: { [paramKey]: range } };
}

// =====================================================================
// Form ← IR object (hydrate from a loaded example)
// =====================================================================

function hydrateForm(ir) {
  // Reset multi-select checkboxes first
  form.querySelectorAll('input[type="checkbox"]').forEach((cb) => (cb.checked = false));

  // Meta
  setVal("meta-name", ir.meta?.name);
  setVal("meta-description", ir.meta?.description);
  setVal("meta-archetype", ir.meta?.archetype);
  setVal("nfr-resilience", ir.meta?.nfrs?.resilience, "radio");
  setVal("nfr-adaptability", ir.meta?.nfrs?.adaptability, "radio");
  setVal("nfr-accessibility", ir.meta?.nfrs?.accessibility, "radio");
  setVal("nfr-transparency", ir.meta?.nfrs?.transparency, "radio");
  setVal("nfr-proportionality", ir.meta?.nfrs?.proportionality, "radio");
  setVal("nfr-circulation", ir.meta?.nfrs?.circulation_speed);
  setVal("nfr-maturity", ir.meta?.nfrs?.governance_maturity);

  // Token (just the first one — multi-token requires advanced YAML)
  const tok = (ir.tokens || [])[0] || {};
  setVal("token-id", tok.id);
  setMultiCheck("token-function", tok.function);
  setMultiCheck("token-earning", tok.earning_mechanisms);
  setVal("token-anchor", tok.value_anchor);
  setMultiCheck("token-holding", tok.holding_incentives);
  setVal("token-verification", tok.contribution_verification ?? "");
  setVal("token-redemption", tok.redemption_mechanism ?? "");
  setRange("token-K-min", "token-K-max", tok.offer_variety_K);

  // Emission rule
  const emit = (tok.emission_rules || [])[0];
  if (emit) {
    setVal("emit-trigger", emit.trigger?.kind || "behavioral_event");
    const ef = emit.trigger?.event_frequency;
    if (ef) {
      setVal("emit-frequency", ef.family);
      setRange(
        "emit-freq-min",
        "emit-freq-max",
        ef.bounds || ef.parameter_ranges?.c || ef.parameter_ranges?.a || ef.parameter_ranges?.value
      );
    }
    setVal("emit-sign", emit.function?.sign);
    const ac = emit.function?.asymptotic_class;
    if (ac) {
      setVal("emit-class", ac.family);
      setRange(
        "emit-fn-min",
        "emit-fn-max",
        ac.bounds || ac.parameter_ranges?.c || ac.parameter_ranges?.a || ac.parameter_ranges?.value
      );
    }
  } else {
    setVal("emit-trigger", "none");
  }

  // Burn rule
  const burn = (tok.burn_rules || [])[0];
  if (burn) {
    setVal("burn-trigger", burn.trigger?.kind || "demand_driven");
    const bf = burn.trigger?.event_frequency;
    if (bf)
      setRange(
        "burn-freq-min",
        "burn-freq-max",
        bf.bounds || bf.parameter_ranges?.c || bf.parameter_ranges?.a || bf.parameter_ranges?.value
      );
    const ac = burn.function?.asymptotic_class;
    if (ac)
      setRange(
        "burn-fn-min",
        "burn-fn-max",
        ac.bounds || ac.parameter_ranges?.c || ac.parameter_ranges?.a || ac.parameter_ranges?.value
      );
  } else {
    setVal("burn-trigger", "none");
  }

  // Participants
  setRange("part-N-min", "part-N-max", ir.participants?.count_N);
  setRange("part-Q-min", "part-Q-max", ir.participants?.expected_Q);
  setRange("part-d-min", "part-d-max", ir.participants?.average_demand_d);
  const g = ir.participants?.growth_g;
  if (g) {
    setVal("part-growth", g.family);
    setRange("part-growth-min", "part-growth-max", g.parameter_ranges?.value);
  }
  setVal("part-topology", ir.participants?.topology);
  topologyDegree.hidden = ir.participants?.topology !== "network";
  if (ir.participants?.topology === "network") {
    setRange("part-degree-min", "part-degree-max", ir.participants?.topology_params?.average_degree);
  }

  // Agents — clear existing rows and rebuild
  agentContainer.innerHTML = "";
  agentCounter = 0;
  for (const ag of ir.participants?.agent_types || []) {
    addAgentRow(ag);
  }

  // Governance
  setVal("gov-type", ir.governance?.type);
  for (const d of [
    "emission_rate_adjustment",
    "burn_rate_adjustment",
    "participant_eligibility",
    "provider_onboarding",
    "exchange_ratios",
    "reward_structure_modification",
    "system_rule_modification",
  ]) {
    setVal(`gov-rule-${d}`, ir.governance?.rule_structure?.[d] || "");
  }
  setRange("gov-gamma-min", "gov-gamma-max", ir.governance?.monitoring_capacity_gamma);
  setVal("gov-sanction-kind", ir.governance?.sanction_structure?.kind);
  setRange("gov-S-min", "gov-S-max", ir.governance?.sanction_structure?.S_normalized);
  setRange("gov-gini-min", "gov-gini-max", ir.governance?.token_balance_gini);
}

function setVal(name, value, kind) {
  if (value == null) return;
  if (kind === "radio") {
    const el = form.querySelector(`input[name="${name}"][value="${value}"]`);
    if (el) el.checked = true;
    return;
  }
  const el = form.querySelector(`[name="${name}"]`);
  if (!el) return;
  el.value = value;
}

function setMultiCheck(name, values) {
  if (!values) return;
  const set = new Set(values);
  form.querySelectorAll(`input[name="${name}"]`).forEach((cb) => {
    cb.checked = set.has(cb.value);
  });
}

function setRange(minName, maxName, range) {
  if (!range) return;
  const minEl = form.querySelector(`[name="${minName}"]`);
  const maxEl = form.querySelector(`[name="${maxName}"]`);
  if (minEl && range.min != null) minEl.value = range.min;
  if (maxEl && range.max != null) maxEl.value = range.max;
}

function escapeAttr(s) {
  return String(s).replace(/"/g, "&quot;");
}

// =====================================================================
// Verify
// =====================================================================

verifyBtn.addEventListener("click", async () => {
  verifyStatus.classList.remove("error");
  verifyStatus.textContent = "Verifying…";
  let ir;
  try {
    ir = buildIR();
  } catch (e) {
    verifyStatus.classList.add("error");
    verifyStatus.textContent = `Form error: ${e.message}`;
    return;
  }
  try {
    const res = await fetch("/api/build-and-verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir }),
    });
    const data = await res.json();
    if (data.error) {
      verifyStatus.classList.add("error");
      verifyStatus.textContent = `Error: ${data.error}`;
      return;
    }
    lastVerifiedYaml = data.yaml || "";
    verdictEmpty.hidden = true;
    verdictContent.hidden = false;
    renderReport(data.report); // from verdict.js
    verifyStatus.textContent = `Done — severity: ${data.report.severity}`;
  } catch (e) {
    verifyStatus.classList.add("error");
    verifyStatus.textContent = `Error: ${e.message || e}`;
  }
});

// =====================================================================
// Examples
// =====================================================================

document.querySelectorAll(".example-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const name = btn.dataset.example;
    verifyStatus.textContent = `Loading "${name}"…`;
    try {
      const r1 = await fetch(`/api/example/${encodeURIComponent(name)}`);
      const data1 = await r1.json();
      if (data1.error) throw new Error(data1.error);
      const r2 = await fetch("/api/yaml-to-ir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml: data1.yaml }),
      });
      const data2 = await r2.json();
      if (data2.error) throw new Error(data2.error);
      hydrateForm(data2.ir);
      verifyStatus.textContent = `Loaded "${name}". Click Verify.`;
      // Auto-verify so user immediately sees a worked example
      verifyBtn.click();
    } catch (e) {
      verifyStatus.classList.add("error");
      verifyStatus.textContent = `Error loading example: ${e.message}`;
    }
  });
});

// =====================================================================
// Download / upload
// =====================================================================

downloadBtn.addEventListener("click", () => {
  if (!lastVerifiedYaml) {
    verifyStatus.classList.add("error");
    verifyStatus.textContent = "Verify first to generate a YAML to download.";
    return;
  }
  const blob = new Blob([lastVerifiedYaml], { type: "text/yaml" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "te.yaml";
  a.click();
  URL.revokeObjectURL(url);
});

uploadBtn.addEventListener("click", () => uploadInput.click());

uploadInput.addEventListener("change", async () => {
  const file = uploadInput.files[0];
  if (!file) return;
  const text = await file.text();
  try {
    const r = await fetch("/api/yaml-to-ir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml: text }),
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    hydrateForm(data.ir);
    verifyStatus.textContent = `Loaded "${file.name}". Click Verify.`;
  } catch (e) {
    verifyStatus.classList.add("error");
    verifyStatus.textContent = `Error: ${e.message}`;
  }
  uploadInput.value = "";
});

// =====================================================================
// Reset
// =====================================================================

resetBtn.addEventListener("click", () => {
  if (!confirm("Reset all form fields to defaults?")) return;
  form.reset();
  agentContainer.innerHTML = "";
  agentCounter = 0;
  addAgentRow({ id: "user", fraction: 1.0, expected_holding_time: { expected_periods: { min: 5, max: 5 } } });
  topologyDegree.hidden = true;
  verdictEmpty.hidden = false;
  verdictContent.hidden = true;
  verifyStatus.textContent = "";
  lastVerifiedYaml = "";
});
