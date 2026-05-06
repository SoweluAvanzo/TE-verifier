// Form-driven UI orchestration (Phase C).
//
// Strategy:
// - Token cards, rule rows, and cross-token flow cards are cloned from
//   <template> elements and managed in JS — supporting multi-token
//   systems with multi-mechanism mint/burn and inter-token flows.
// - buildIR() walks the DOM and emits the Pydantic IR shape.
// - hydrateForm() rebuilds the dynamic structures from a server-validated IR.

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
const tokensContainer = document.getElementById("tokens-container");
const addTokenBtn = document.getElementById("add-token-btn");
const xtflowsContainer = document.getElementById("xtflows-container");
const addXtflowBtn = document.getElementById("add-xtflow-btn");

const TOKEN_TPL = document.getElementById("token-card-tpl");
const MINT_TPL = document.getElementById("mint-rule-tpl");
const BURN_TPL = document.getElementById("burn-rule-tpl");
const XTFLOW_TPL = document.getElementById("xtflow-card-tpl");

let lastVerifiedYaml = "";

// =====================================================================
// Cloning helpers
// =====================================================================

function cloneTemplate(tpl, replacements) {
  // Substitute __IDX__/__RIDX__/__FIDX__ in attribute names and text.
  // Templates use these placeholders so we get unique form-field names.
  let html = tpl.innerHTML;
  for (const [key, val] of Object.entries(replacements)) {
    html = html.split(key).join(val);
  }
  const wrapper = document.createElement("div");
  wrapper.innerHTML = html.trim();
  return wrapper.firstElementChild;
}

// =====================================================================
// Token cards (multi-token, multi-mechanism)
// =====================================================================

let tokenCounter = 0;

function addTokenCard(prefill = {}) {
  tokenCounter++;
  const tidx = tokenCounter;
  const card = cloneTemplate(TOKEN_TPL, { __IDX__: String(tidx) });
  card.dataset.tidx = String(tidx);

  const removeBtn = card.querySelector(".remove-token");
  removeBtn.addEventListener("click", () => {
    if (tokensContainer.querySelectorAll(".token-card").length === 1) {
      verifyStatus.textContent = "At least one token is required.";
      return;
    }
    card.remove();
  });

  const addMintBtn = card.querySelector(".add-mint-rule");
  const addBurnBtn = card.querySelector(".add-burn-rule");
  const mintList = card.querySelector(".mint-rules");
  const burnList = card.querySelector(".burn-rules");
  addMintBtn.addEventListener("click", () => addRuleRow(mintList, "mint"));
  addBurnBtn.addEventListener("click", () => addRuleRow(burnList, "burn"));

  // Live composition preview — updates on any input change inside the card.
  const updatePreviews = () => updateCompositionPreviews(card);
  card.addEventListener("input", updatePreviews);
  card.addEventListener("change", updatePreviews);

  // Token-id input lifts the card title.
  const idInput = card.querySelector(`[name="tok-${tidx}-id"]`);
  const display = card.querySelector(".tok-name-display");
  idInput.addEventListener("input", () => {
    display.textContent = idInput.value || `#${tidx}`;
  });

  tokensContainer.appendChild(card);

  // Apply prefill or seed defaults
  if (prefill.id) idInput.value = prefill.id;
  display.textContent = prefill.id || `#${tidx}`;
  // transferable: explicit false unchecks the box; missing = default true.
  const transferableInput = card.querySelector(`[name="tok-${tidx}-transferable"]`);
  if (transferableInput) {
    transferableInput.checked = prefill.transferable !== false;
  }
  setMultiCheckIn(card, `tok-${tidx}-function`, prefill.function);
  setMultiCheckIn(card, `tok-${tidx}-earning`, prefill.earning_mechanisms);
  setValIn(card, `tok-${tidx}-anchor`, prefill.value_anchor);
  setMultiCheckIn(card, `tok-${tidx}-holding`, prefill.holding_incentives);
  setValIn(card, `tok-${tidx}-verification`, prefill.contribution_verification ?? "");
  setValIn(card, `tok-${tidx}-redemption`, prefill.redemption_mechanism ?? "");
  setRangeIn(card, `tok-${tidx}-K-min`, `tok-${tidx}-K-max`, prefill.offer_variety_K);

  const mintRules = prefill.emission_rules || [];
  const burnRules = prefill.burn_rules || [];
  if (mintRules.length === 0) {
    addRuleRow(mintList, "mint");
  } else {
    for (const r of mintRules) addRuleRow(mintList, "mint", r);
  }
  if (burnRules.length === 0) {
    // Empty burn list is valid — token may have no burn mechanism.
  } else {
    for (const r of burnRules) addRuleRow(burnList, "burn", r);
  }

  updateCompositionPreviews(card);
  return card;
}

addTokenBtn.addEventListener("click", () => addTokenCard());

// =====================================================================
// Rule rows
// =====================================================================

let ruleCounter = 0;

function addRuleRow(container, side, prefill) {
  ruleCounter++;
  const ridx = ruleCounter;
  const tpl = side === "mint" ? MINT_TPL : BURN_TPL;
  const row = cloneTemplate(tpl, { __RIDX__: String(ridx) });
  row.dataset.side = side;

  row.querySelector(".remove-rule").addEventListener("click", () => row.remove());
  container.appendChild(row);

  if (prefill) {
    const triggerKind = prefill.trigger?.kind;
    if (triggerKind) row.querySelector(".rule-trigger").value = triggerKind;
    if (side === "mint") {
      const sign = prefill.function?.sign;
      if (sign) row.querySelector(".rule-sign").value = sign;
    }
    const ef = prefill.trigger?.event_frequency;
    if (ef) {
      row.querySelector(".rule-freq-family").value = ef.family;
      const r = ef.bounds || ef.parameter_ranges?.c || ef.parameter_ranges?.a || ef.parameter_ranges?.value;
      if (r) {
        row.querySelector(".rule-freq-min").value = r.min ?? "";
        row.querySelector(".rule-freq-max").value = r.max ?? "";
      }
    }
    const ac = prefill.function?.asymptotic_class;
    if (ac) {
      row.querySelector(".rule-fn-family").value = ac.family;
      const r = ac.bounds || ac.parameter_ranges?.c || ac.parameter_ranges?.a || ac.parameter_ranges?.value;
      if (r) {
        row.querySelector(".rule-fn-min").value = r.min ?? "";
        row.querySelector(".rule-fn-max").value = r.max ?? "";
      }
    }
  }

  return row;
}

function readRuleRow(row, side) {
  const family = row.querySelector(".rule-fn-family").value || "constant";
  const fnMin = parseFloat(row.querySelector(".rule-fn-min").value);
  const fnMax = parseFloat(row.querySelector(".rule-fn-max").value);
  const ac = makeAsymptoticClass(family, fnMin, fnMax);
  const trigger = { kind: row.querySelector(".rule-trigger").value };

  const freqFamily = row.querySelector(".rule-freq-family").value || "constant";
  const freqMin = parseFloat(row.querySelector(".rule-freq-min").value);
  const freqMax = parseFloat(row.querySelector(".rule-freq-max").value);
  if (!Number.isNaN(freqMin) || freqFamily === "unspecified") {
    const freqClass = makeAsymptoticClass(freqFamily, freqMin, freqMax);
    if (freqClass) trigger.event_frequency = freqClass;
  }

  const sign = side === "mint"
    ? row.querySelector(".rule-sign").value || "always_positive"
    : "always_negative";

  return {
    trigger,
    function: {
      sign,
      asymptotic_class: ac || { family: "constant", parameter_ranges: { c: { min: 0, max: 0 } } },
    },
  };
}

function makeAsymptoticClass(family, min, max) {
  if (family === "unspecified") {
    const lo = Number.isNaN(min) ? 0 : min;
    const hi = Number.isNaN(max) ? 1e9 : max;
    return { family: "unspecified", parameter_ranges: { value: { min: lo, max: hi } } };
  }
  if (Number.isNaN(min) || Number.isNaN(max)) return null;
  if (family === "bounded_range") {
    return { family, bounds: { min, max } };
  }
  const paramKey = family === "linear" ? "a" : "c";
  return { family, parameter_ranges: { [paramKey]: { min, max } } };
}

// =====================================================================
// Cross-token flow cards
// =====================================================================

let xtflowCounter = 0;

function addXtflowCard(prefill = {}) {
  xtflowCounter++;
  const fidx = xtflowCounter;
  const card = cloneTemplate(XTFLOW_TPL, { __FIDX__: String(fidx) });

  card.querySelector(".remove-xtflow").addEventListener("click", () => card.remove());

  // Coupling toggle: show/hide ratio vs amount block.
  const couplingSel = card.querySelector(".xt-coupling");
  const ratioField = card.querySelector(".xt-ratio-field");
  const amountBlock = card.querySelector(".xt-amount-block");
  const updateCouplingUI = () => {
    const proportional = couplingSel.value === "proportional_to_source";
    ratioField.hidden = !proportional;
    amountBlock.hidden = proportional;
  };
  couplingSel.addEventListener("change", updateCouplingUI);

  xtflowsContainer.appendChild(card);

  if (prefill.source_token) card.querySelector(".xt-source").value = prefill.source_token;
  if (prefill.source_event) card.querySelector(".xt-event").value = prefill.source_event;
  if (prefill.target_token) card.querySelector(".xt-target").value = prefill.target_token;
  if (prefill.target_action) card.querySelector(".xt-action").value = prefill.target_action;
  if (prefill.coupling) couplingSel.value = prefill.coupling;
  if (prefill.coupling_ratio) {
    card.querySelector(".xt-ratio-min").value = prefill.coupling_ratio.min ?? "";
    card.querySelector(".xt-ratio-max").value = prefill.coupling_ratio.max ?? "";
  }
  if (prefill.amount) {
    card.querySelector(".xt-amount-family").value = prefill.amount.family || "constant";
    const r = prefill.amount.bounds || prefill.amount.parameter_ranges?.c || prefill.amount.parameter_ranges?.a;
    if (r) {
      card.querySelector(".xt-amount-min").value = r.min ?? "";
      card.querySelector(".xt-amount-max").value = r.max ?? "";
    }
  }
  updateCouplingUI();

  return card;
}

addXtflowBtn.addEventListener("click", () => addXtflowCard());

function readXtflowCard(card) {
  const source_token = card.querySelector(".xt-source").value.trim();
  const target_token = card.querySelector(".xt-target").value.trim();
  if (!source_token || !target_token) return null;
  const flow = {
    source_token,
    source_event: card.querySelector(".xt-event").value.trim() || "event",
    target_token,
    target_action: card.querySelector(".xt-action").value,
    coupling: card.querySelector(".xt-coupling").value,
  };
  if (flow.coupling === "proportional_to_source") {
    const min = parseFloat(card.querySelector(".xt-ratio-min").value);
    const max = parseFloat(card.querySelector(".xt-ratio-max").value);
    if (Number.isNaN(min) || Number.isNaN(max)) return null;
    flow.coupling_ratio = { min, max };
    // Pydantic still requires `amount`; supply a placeholder constant 0.
    flow.amount = { family: "constant", parameter_ranges: { c: { min: 0, max: 0 } } };
  } else {
    const family = card.querySelector(".xt-amount-family").value || "constant";
    const min = parseFloat(card.querySelector(".xt-amount-min").value);
    const max = parseFloat(card.querySelector(".xt-amount-max").value);
    const ac = makeAsymptoticClass(family, min, max);
    if (!ac) return null;
    flow.amount = ac;
  }
  return flow;
}

// =====================================================================
// Live composition preview
// =====================================================================

function updateCompositionPreviews(card) {
  for (const side of ["mint", "burn"]) {
    const pre = card.querySelector(`.composition-preview[data-side="${side}"]`);
    const rules = card.querySelectorAll(`.${side}-rule`);
    if (rules.length === 0) {
      pre.textContent = side === "mint" ? "No mint mechanisms yet." : "No burn mechanisms (FM3 will flag).";
      continue;
    }
    const parts = [];
    rules.forEach((row, i) => {
      const family = row.querySelector(".rule-fn-family").value || "constant";
      const min = row.querySelector(".rule-fn-min").value;
      const max = row.querySelector(".rule-fn-max").value;
      const freqFamily = row.querySelector(".rule-freq-family").value || "constant";
      const freqMin = row.querySelector(".rule-freq-min").value;
      const freqMax = row.querySelector(".rule-freq-max").value;
      const fnDesc = `${family}[${min || "?"}..${max || "?"}]`;
      const freqDesc = freqMin || freqMax ? ` × ${freqFamily}[${freqMin || "?"}..${freqMax || "?"}]` : "";
      parts.push(`${fnDesc}${freqDesc}`);
    });
    pre.textContent = `${side === "mint" ? "E(t)" : "B(t)"} ≈ ${parts.join("  +  ")}`;
  }
}

// =====================================================================
// Agent rows (unchanged from Phase B)
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
      <button type="button" class="remove-agent ghost-danger">remove</button>
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
addAgentRow({ id: "user", fraction: 1.0, expected_holding_time: { expected_periods: { min: 5, max: 5 } } });

// Topology degree visibility toggle
const topologySelect = document.getElementById("part-topology");
topologySelect.addEventListener("change", () => {
  topologyDegree.hidden = topologySelect.value !== "network";
});

// Seed one default token card so the form isn't empty.
addTokenCard({
  id: "T",
  function: ["medium_of_exchange"],
});

// =====================================================================
// Form → IR
// =====================================================================

function buildIR() {
  const fd = new FormData(form);
  const ir = { meta: {}, tokens: [], participants: {}, governance: {}, cross_token_flows: [] };

  // Meta
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

  // Tokens
  tokensContainer.querySelectorAll(".token-card").forEach((card) => {
    const tidx = card.dataset.tidx;
    const tok = {};
    tok.id = fd.get(`tok-${tidx}-id`) || `T${tidx}`;
    // Transferable: schema default is true; emit explicit false when
    // the user unchecks the box (HTML checkboxes only POST when checked).
    tok.transferable = fd.get(`tok-${tidx}-transferable`) === "true";
    tok.function = fd.getAll(`tok-${tidx}-function`);
    if (tok.function.length === 0) tok.function = ["medium_of_exchange"];
    const earning = fd.getAll(`tok-${tidx}-earning`);
    if (earning.length) tok.earning_mechanisms = earning;
    tok.value_anchor = fd.get(`tok-${tidx}-anchor`) || "none";
    const holding = fd.getAll(`tok-${tidx}-holding`);
    if (holding.length) {
      tok.holding_incentives = holding;
      tok.holding_incentive_present = holding.some((h) => h !== "none");
    }
    const cv = fd.get(`tok-${tidx}-verification`);
    if (cv) tok.contribution_verification = cv;
    const rm = fd.get(`tok-${tidx}-redemption`);
    if (rm) tok.redemption_mechanism = rm;
    const kRange = readRange(fd, `tok-${tidx}-K-min`, `tok-${tidx}-K-max`);
    if (kRange) tok.offer_variety_K = kRange;

    // Mint rules
    tok.emission_rules = [];
    card.querySelectorAll(".mint-rule").forEach((row) => {
      tok.emission_rules.push(readRuleRow(row, "mint"));
    });

    // Burn rules
    tok.burn_rules = [];
    card.querySelectorAll(".burn-rule").forEach((row) => {
      tok.burn_rules.push(readRuleRow(row, "burn"));
    });

    ir.tokens.push(tok);
  });

  // Cross-token flows
  xtflowsContainer.querySelectorAll(".xtflow-card").forEach((card) => {
    const flow = readXtflowCard(card);
    if (flow) ir.cross_token_flows.push(flow);
  });

  // Participants
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

  // Agents
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
        expected_periods: readRange(fd, `agent-${idx}-tau-min`, `agent-${idx}-tau-max`) || { min: 1, max: 1 },
      },
    };
    const role = fd.get(`agent-${idx}-role`);
    if (role) ag.role = role;
    const bal = fd.get(`agent-${idx}-balance`);
    if (bal && bal !== "") ag.balance_share = parseFloat(bal);
    agents.push(ag);
  });
  if (agents.length) ir.participants.agent_types = agents;

  // Governance
  ir.governance.type = fd.get("gov-type") || "dao";
  const ruleStruct = {};
  for (const d of [
    "emission_rate_adjustment",
    "burn_rate_adjustment",
    "participant_eligibility",
    "provider_onboarding",
    "exchange_ratios",
    "reward_structure_modification",
    "system_rule_modification",
  ]) {
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

// =====================================================================
// IR → Form (hydrate)
// =====================================================================

function hydrateForm(ir) {
  // Reset top-level checkboxes
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

  // Tokens — clear and rebuild
  tokensContainer.innerHTML = "";
  tokenCounter = 0;
  ruleCounter = 0;
  const tokens = ir.tokens || [];
  if (tokens.length === 0) {
    addTokenCard({ id: "T", function: ["medium_of_exchange"] });
  } else {
    for (const t of tokens) addTokenCard(t);
  }

  // Cross-token flows — clear and rebuild
  xtflowsContainer.innerHTML = "";
  xtflowCounter = 0;
  for (const f of ir.cross_token_flows || []) addXtflowCard(f);

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

  // Agents — clear and rebuild
  agentContainer.innerHTML = "";
  agentCounter = 0;
  for (const ag of ir.participants?.agent_types || []) addAgentRow(ag);

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

function setValIn(scope, name, value) {
  if (value == null) return;
  const el = scope.querySelector(`[name="${name}"]`);
  if (el) el.value = value;
}

function setMultiCheckIn(scope, name, values) {
  if (!values) return;
  const set = new Set(values);
  scope.querySelectorAll(`input[name="${name}"]`).forEach((cb) => {
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

function setRangeIn(scope, minName, maxName, range) {
  if (!range) return;
  const minEl = scope.querySelector(`[name="${minName}"]`);
  const maxEl = scope.querySelector(`[name="${maxName}"]`);
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
    renderReport(data.report);
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
  tokensContainer.innerHTML = "";
  tokenCounter = 0;
  ruleCounter = 0;
  addTokenCard({ id: "T", function: ["medium_of_exchange"] });
  xtflowsContainer.innerHTML = "";
  xtflowCounter = 0;
  agentContainer.innerHTML = "";
  agentCounter = 0;
  addAgentRow({ id: "user", fraction: 1.0, expected_holding_time: { expected_periods: { min: 5, max: 5 } } });
  topologyDegree.hidden = true;
  verdictEmpty.hidden = false;
  verdictContent.hidden = true;
  verifyStatus.textContent = "";
  lastVerifiedYaml = "";
});
