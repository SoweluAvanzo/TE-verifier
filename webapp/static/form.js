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
// Phase L2 — MC page removed from the UI. Backend kept; no front-end button.
const simulateDirectBtn = null;
const exploreDirectBtn = document.getElementById("explore-direct-btn");
const resetBtn = document.getElementById("reset-btn");
const uploadBtn = document.getElementById("upload-btn");
const uploadInput = document.getElementById("upload-yaml");
const verdictEmpty = document.getElementById("verdict-empty");
const verdictContent = document.getElementById("verdict-content");
const agentContainer = document.getElementById("agent-types-container");
const addAgentBtn = document.getElementById("add-agent-btn");
const popEventsContainer = document.getElementById("pop-events-container");
const addPopEventBtn = document.getElementById("add-pop-event-btn");
const topologyDegree = document.getElementById("topology-degree");
const tokensContainer = document.getElementById("tokens-container");
const addTokenBtn = document.getElementById("add-token-btn");
const xtflowsContainer = document.getElementById("xtflows-container");
const addXtflowBtn = document.getElementById("add-xtflow-btn");

const TOKEN_TPL = document.getElementById("token-card-tpl");
const MINT_TPL = document.getElementById("mint-rule-tpl");
const BURN_TPL = document.getElementById("burn-rule-tpl");
const XTFLOW_TPL = document.getElementById("xtflow-card-tpl");
const EVENT_TPL = document.getElementById("event-row-tpl");
const ASSET_TPL = document.getElementById("asset-row-tpl");

const eventsContainer = document.getElementById("events-container");
const addEventBtn = document.getElementById("add-event-btn");
const assetsContainer = document.getElementById("assets-container");
const addAssetBtn = document.getElementById("add-asset-btn");

let lastVerifiedYaml = "";
let eventCounter = 0;
let assetCounter = 0;

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

  // Token-id input lifts the card title + retriggers K-auto-derive
  // (assets reference tokens by id, so a changing id changes
  // which assets count).
  const idInput = card.querySelector(`[name="tok-${tidx}-id"]`);
  const display = card.querySelector(".tok-name-display");
  idInput.addEventListener("input", () => {
    display.textContent = idInput.value || `#${tidx}`;
    syncTokenKBlocks();
  });

  tokensContainer.appendChild(card);
  // Phase L3: initial K-source-hint label population — empty until
  // the first asset references this id.
  if (typeof syncTokenKBlocks === "function") syncTokenKBlocks();

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

  // Schedule modifiers (mint-side only — the form template has them
  // on mint-rule-tpl; burn rules ignore them).
  wireScheduleToggles(row);
  // Distribution envelope (both mint and burn) — opts the rule into
  // per-period sampling during ABM simulation.
  wireDistributionToggle(row);

  if (prefill) {
    // Phase-H: prefer event_id; fall back silently when missing so
    // legacy IRs (with inline kind) still hydrate fields gracefully.
    if (prefill.trigger?.event_id) {
      const sel = row.querySelector(".rule-event-id");
      if (sel) {
        // Dropdown may not yet contain the option if events haven't
        // been hydrated; we'll re-sync after the events stage populates.
        const opt = document.createElement("option");
        opt.value = prefill.trigger.event_id;
        opt.textContent = prefill.trigger.event_id;
        opt.selected = true;
        sel.appendChild(opt);
      }
    }
    if (side === "mint") {
      // Mint sign is intrinsic (always_positive); the dropdown was
      // removed but the prefill payload may still carry the legacy
      // field — silently accept and ignore.
      // Schedule prefill (only meaningful for mint rules at the moment).
      if (prefill.schedule) {
        applySchedulePrefill(row, prefill.schedule);
      }
    }
    if (prefill.function?.distribution) {
      applyDistributionPrefill(row, prefill.function.distribution);
    }
    const ef = prefill.trigger?.event_frequency;
    if (ef) {
      row.querySelector(".rule-freq-family").value = encodeFamilyValue(ef);
      const r = _preferredRange(ef);
      if (r) {
        row.querySelector(".rule-freq-min").value = r.min ?? "";
        row.querySelector(".rule-freq-max").value = r.max ?? "";
      }
    }
    const ac = prefill.function?.asymptotic_class;
    if (ac) {
      row.querySelector(".rule-fn-family").value = encodeFamilyValue(ac);
      const r = _preferredRange(ac);
      if (r) {
        row.querySelector(".rule-fn-min").value = r.min ?? "";
        row.querySelector(".rule-fn-max").value = r.max ?? "";
      }
    }
    // Phase-K: DSL expression prefill. When the rule's FunctionShape
    // carries an ``expression`` (either as a parsed AST or the original
    // source string echoed back by the round-trip), surface it in the
    // textarea + parameter list and switch the family dropdown to
    // ``expression`` so visibility flips correctly.
    const expr = prefill.function?.expression;
    if (expr !== undefined && expr !== null) {
      row.querySelector(".rule-fn-family").value = "expression";
      const ta = row.querySelector(".rule-fn-expression");
      if (ta) {
        // Round-tripped from server: an AST object. Author-edited form
        // preserves the source verbatim (textarea content). When we
        // receive only the AST, show a placeholder pointing the user
        // to /yaml for verbatim editing.
        if (typeof expr === "string") {
          ta.value = expr;
        } else {
          ta.value = (prefill.function._expression_source || "");
          if (!ta.value) {
            ta.placeholder = "(DSL AST — edit in /yaml for verbatim source)";
          }
        }
      }
      const params = prefill.function?.parameters || [];
      const list = row.querySelector(".rule-fn-params-list");
      for (const p of params) {
        appendDslParamRow(list, p);
      }
    }
    // Sync DSL block visibility now that family value is set.
    syncDslVisibility(row);
    // Phase-F prefill: event_predicate label + structured conditions
    // + regime switches. All three are optional.
    const ep = prefill.trigger?.event_predicate;
    if (ep) row.querySelector(".rule-event-predicate").value = ep;
    const conds = prefill.trigger?.conditions || [];
    const condList = row.querySelector(".rule-conditions-list");
    for (const c of conds) appendConditionRow(condList, c);
    const regimes = prefill.regimes || [];
    const regimeList = row.querySelector(".rule-regimes-list");
    for (const r of regimes) appendRegimeRow(regimeList, r);
  }

  // Wire the "+ Add condition" + "+ Add regime" buttons each row carries.
  row.querySelector(".add-rule-condition")?.addEventListener("click", () => {
    appendConditionRow(row.querySelector(".rule-conditions-list"));
  });
  row.querySelector(".add-rule-regime")?.addEventListener("click", () => {
    appendRegimeRow(row.querySelector(".rule-regimes-list"));
  });
  // Phase-K: DSL visibility — toggled by the family dropdown.
  row.querySelector(".rule-fn-family")?.addEventListener("change", () => {
    syncDslVisibility(row);
  });
  row.querySelector(".add-rule-fn-param")?.addEventListener("click", () => {
    appendDslParamRow(row.querySelector(".rule-fn-params-list"));
  });
  syncDslVisibility(row);

  // Phase-H: rules link to a top-level event by id (Stage 4 catalog).
  // Per-rule frequency block + trigger-based label tuning are obsolete —
  // the event carries kind + frequency; the rule only carries the
  // tokens-per-event function shape. The .rule-freq-block markup is
  // hidden by default and left in place for back-compat (read paths
  // skip it). Make sure the dropdown gets current event options.
  populateAllEventDropdowns();
  const fnFamilyUnit = row.querySelector(".rule-fn-family-unit");
  if (fnFamilyUnit) fnFamilyUnit.textContent = "(tokens per event)";
  const fnRangeLabel = row.querySelector(".rule-fn-range-label");
  if (fnRangeLabel) fnRangeLabel.textContent = "Tokens-per-event range";

  return row;
}

function readRuleRow(row, side) {
  const family = row.querySelector(".rule-fn-family").value || "constant";
  // Phase-H: rules link to a top-level event by id. Kind + frequency
  // are carried by the EventDefinition, not the rule. The form omits
  // kind / event_frequency entirely.
  const eventId = row.querySelector(".rule-event-id")?.value || "";
  const trigger = {};
  if (eventId) {
    trigger.event_id = eventId;
  } else {
    // Fallback for partially-filled rules: keep a legacy time_based
    // trigger so Pydantic doesn't reject the schema. The verifier will
    // ignore the rate when no event_id is set anyway.
    trigger.kind = side === "mint" ? "time_based" : "rule_driven";
  }

  // Mint sign is intrinsic — rate ≥ 0 by construction. Burn sign is
  // its dual. The schema retains a FunctionSign enum for backward
  // compatibility but the form no longer surfaces it as a user choice.
  const sign = side === "mint" ? "always_positive" : "always_negative";

  // Phase-K: DSL branch — emit ``expression`` + ``parameters`` instead
  // of ``asymptotic_class``. Server-side validators reject mixed forms.
  let fn;
  if (family === "expression") {
    const expr = (row.querySelector(".rule-fn-expression")?.value || "").trim();
    const params = readDslParamList(row.querySelector(".rule-fn-params-list"));
    fn = { sign, expression: expr, parameters: params };
  } else {
    const fnMin = parseFloat(row.querySelector(".rule-fn-min").value);
    const fnMax = parseFloat(row.querySelector(".rule-fn-max").value);
    const ac = makeAsymptoticClass(family, fnMin, fnMax);
    fn = {
      sign,
      asymptotic_class: ac || { family: "constant", parameter_ranges: { c: { min: 0, max: 0 } } },
    };
  }

  const rule = { trigger, function: fn };
  if (side === "mint") {
    const schedule = readScheduleFromRow(row);
    if (schedule) rule.schedule = schedule;
  }
  const distribution = readDistributionFromRow(row);
  if (distribution) rule.function.distribution = distribution;

  // Phase-F: event_predicate label, structured conditions, regime
  // switches. All optional — only emit when the user supplied them.
  const ep = row.querySelector(".rule-event-predicate")?.value.trim();
  if (ep) trigger.event_predicate = ep;
  const conditions = readConditionList(row.querySelector(".rule-conditions-list"));
  if (conditions.length) trigger.conditions = conditions;
  const regimes = readRegimeList(row.querySelector(".rule-regimes-list"));
  if (regimes.length) rule.regimes = regimes;
  return rule;
}

// =====================================================================
// Phase-K DSL helpers — visibility toggle + parameter list
// =====================================================================

function syncDslVisibility(row) {
  const family = row.querySelector(".rule-fn-family")?.value;
  const isDsl = family === "expression";
  const dsl = row.querySelector(".rule-fn-dsl");
  // Target the FN-side range field specifically — the freq-side range
  // lives inside .rule-freq-block (Phase-H hides it by default).
  const range = row.querySelector(
    ".range-field:not(.rule-freq-block)"
  );
  if (dsl) dsl.hidden = !isDsl;
  if (range) range.hidden = isDsl;
}

function appendDslParamRow(listEl, prefill) {
  if (!listEl) return;
  const node = document.createElement("div");
  node.className = "rule-fn-param-row";
  node.innerHTML = `
    <input type="text" class="rule-fn-param-name" placeholder="param name" />
    <input type="number" class="rule-fn-param-min" step="any" placeholder="min" />
    <span>to</span>
    <input type="number" class="rule-fn-param-max" step="any" placeholder="max" />
    <button type="button" class="remove-rule-fn-param ghost" aria-label="remove">×</button>
  `;
  if (prefill) {
    node.querySelector(".rule-fn-param-name").value = prefill.name ?? "";
    node.querySelector(".rule-fn-param-min").value = prefill.range?.min ?? "";
    node.querySelector(".rule-fn-param-max").value = prefill.range?.max ?? "";
  }
  node.querySelector(".remove-rule-fn-param").addEventListener("click", () => node.remove());
  listEl.appendChild(node);
}

function readDslParamList(listEl) {
  if (!listEl) return [];
  const rows = listEl.querySelectorAll(".rule-fn-param-row");
  const out = [];
  for (const r of rows) {
    const name = r.querySelector(".rule-fn-param-name").value.trim();
    if (!name) continue;
    const min = parseFloat(r.querySelector(".rule-fn-param-min").value);
    const max = parseFloat(r.querySelector(".rule-fn-param-max").value);
    if (Number.isNaN(min) || Number.isNaN(max)) continue;
    out.push({ name, range: { min, max } });
  }
  return out;
}

// =====================================================================
// Structured conditions + regime switches (Phase F)
// =====================================================================

function appendConditionRow(listEl, prefill) {
  if (!listEl) return;
  const tpl = document.getElementById("condition-row-tpl");
  const node = tpl.content.firstElementChild.cloneNode(true);
  const kindSel = node.querySelector(".cond-kind");
  const thrBlock = node.querySelector(".cond-threshold");
  const timeBlock = node.querySelector(".cond-time");
  const eventBlock = node.querySelector(".cond-event");
  function syncVisibility() {
    const v = kindSel.value;
    thrBlock.hidden   = v !== "threshold";
    timeBlock.hidden  = v !== "time_window";
    eventBlock.hidden = v !== "event_occurrence";
  }
  kindSel.addEventListener("change", syncVisibility);
  node.querySelector(".remove-condition").addEventListener("click", () => node.remove());
  if (prefill && prefill.type) {
    kindSel.value = prefill.type;
    if (prefill.type === "threshold") {
      node.querySelector(".cond-thr-var").value = prefill.var ?? "t";
      node.querySelector(".cond-thr-op").value = prefill.op ?? ">=";
      node.querySelector(".cond-thr-value").value = prefill.value ?? "";
    } else if (prefill.type === "time_window") {
      node.querySelector(".cond-time-start").value = prefill.start_period ?? "";
      node.querySelector(".cond-time-end").value = prefill.end_period ?? "";
    } else if (prefill.type === "event_occurrence") {
      // Phase-I2 preferred: event_id dropdown. Fall back to legacy
      // source_token/source_event inputs only when event_id is absent.
      if (prefill.event_id) {
        const sel = node.querySelector(".cond-event-id");
        if (sel) {
          // Append the id as a stub option if not yet hydrated.
          const opt = document.createElement("option");
          opt.value = prefill.event_id;
          opt.textContent = prefill.event_id;
          opt.selected = true;
          sel.appendChild(opt);
        }
      } else if (prefill.source_token || prefill.source_event) {
        const tok = node.querySelector(".cond-event-token");
        const evt = node.querySelector(".cond-event-evt");
        tok.hidden = false;
        evt.hidden = false;
        tok.value = prefill.source_token ?? "";
        evt.value = prefill.source_event ?? "";
      }
    }
  }
  syncVisibility();
  // Re-sync event dropdown so newly added condition rows see current events.
  populateAllEventDropdowns();
  listEl.appendChild(node);
  return node;
}

function readConditionRow(rowEl) {
  const kind = rowEl.querySelector(".cond-kind").value;
  if (kind === "threshold") {
    const valueRaw = rowEl.querySelector(".cond-thr-value").value;
    if (valueRaw === "") return null;
    const v = parseFloat(valueRaw);
    if (!Number.isFinite(v)) return null;
    return {
      type: "threshold",
      var: rowEl.querySelector(".cond-thr-var").value,
      op: rowEl.querySelector(".cond-thr-op").value,
      value: v,
    };
  }
  if (kind === "time_window") {
    const start = parseFloat(rowEl.querySelector(".cond-time-start").value);
    if (!Number.isFinite(start)) return null;
    const endRaw = rowEl.querySelector(".cond-time-end").value;
    const out = { type: "time_window", start_period: start };
    if (endRaw !== "") {
      const e = parseFloat(endRaw);
      if (Number.isFinite(e)) out.end_period = e;
    }
    return out;
  }
  if (kind === "event_occurrence") {
    // Phase-I2 preferred: event_id dropdown. Falls back to legacy
    // source_token + source_event when both inputs are populated.
    const eid = rowEl.querySelector(".cond-event-id")?.value.trim();
    if (eid) return { type: "event_occurrence", event_id: eid };
    const tok = rowEl.querySelector(".cond-event-token").value.trim();
    const evt = rowEl.querySelector(".cond-event-evt").value.trim();
    if (!tok || !evt) return null;
    return { type: "event_occurrence", source_token: tok, source_event: evt };
  }
  return null;
}

function readConditionList(listEl) {
  if (!listEl) return [];
  const out = [];
  listEl.querySelectorAll(".condition-row").forEach((row) => {
    const c = readConditionRow(row);
    if (c) out.push(c);
  });
  return out;
}

function appendRegimeRow(listEl, prefill) {
  if (!listEl) return;
  const tpl = document.getElementById("regime-row-tpl");
  const node = tpl.content.firstElementChild.cloneNode(true);
  node.querySelector(".remove-regime").addEventListener("click", () => node.remove());
  // Each regime carries a SINGLE predicate condition (matches schema
  // RegimeSwitch.predicate: Condition).
  const predicateContainer = node.querySelector(".regime-predicate");
  const predicateRow = appendConditionRow(predicateContainer, prefill?.predicate);
  // No remove button on the embedded predicate row — it's required.
  predicateRow?.querySelector(".remove-condition")?.remove();
  if (prefill?.function) {
    // Regime sign inherits parent rule's sign convention; not user-pickable.
    const ac = prefill.function.asymptotic_class;
    if (ac) {
      node.querySelector(".regime-fn-family").value = encodeFamilyValue(ac);
      const r = ac.bounds || ac.parameter_ranges?.c || ac.parameter_ranges?.a || ac.parameter_ranges?.value;
      if (r) {
        node.querySelector(".regime-fn-min").value = r.min ?? "";
        node.querySelector(".regime-fn-max").value = r.max ?? "";
      }
    }
  }
  listEl.appendChild(node);
  return node;
}

function readRegimeList(listEl) {
  if (!listEl) return [];
  const out = [];
  listEl.querySelectorAll(".regime-row").forEach((row) => {
    const condRow = row.querySelector(".regime-predicate .condition-row");
    const predicate = condRow ? readConditionRow(condRow) : null;
    if (!predicate) return;
    const family = row.querySelector(".regime-fn-family").value || "constant";
    const min = parseFloat(row.querySelector(".regime-fn-min").value);
    const max = parseFloat(row.querySelector(".regime-fn-max").value);
    const ac = makeAsymptoticClass(family, min, max);
    if (!ac) return;
    out.push({
      predicate,
      function: {
        // Schema defaults sign to always_positive; regimes inherit the
        // parent rule's direction conceptually. No user input needed.
        asymptotic_class: ac,
      },
    });
  });
  return out;
}

// =====================================================================
// DistributionSpec on rules — per-period noise envelope for ABM.
// =====================================================================
//
// The verifier still sees only the support of the distribution
// (μ±3σ for Normal, [low, high] for Uniform). The ABM resamples per
// period from the declared family. Two numeric inputs cover every
// supported family:
//   uniform:    low, high
//   normal:     mu, sigma
//   lognormal:  mu, sigma
//   bernoulli:  p          (second input ignored)
//   poisson:    lambda     (second input ignored)
//   beta:       alpha, beta

const DIST_PARAMS = {
  uniform:   ["low", "high"],
  normal:    ["mu", "sigma"],
  lognormal: ["mu", "sigma"],
  bernoulli: ["p"],
  poisson:   ["lambda"],
  beta:      ["alpha", "beta"],
};

function wireDistributionToggle(row) {
  const toggle = row.querySelector(".dist-toggle");
  const grid = row.querySelector(".dist-grid");
  if (!toggle || !grid) return;
  const sync = () => (grid.hidden = !toggle.checked);
  toggle.addEventListener("change", sync);
  sync();
}

function readDistributionFromRow(row) {
  const toggle = row.querySelector(".dist-toggle");
  if (!toggle || !toggle.checked) return null;
  const kind = row.querySelector(".dist-kind")?.value || "uniform";
  const p1 = parseFloat(row.querySelector(".dist-p1")?.value);
  const p2 = parseFloat(row.querySelector(".dist-p2")?.value);
  const names = DIST_PARAMS[kind] || [];
  const parameters = {};
  if (names.length >= 1 && !Number.isNaN(p1)) parameters[names[0]] = p1;
  if (names.length >= 2 && !Number.isNaN(p2)) parameters[names[1]] = p2;
  if (Object.keys(parameters).length !== names.length) {
    // Incomplete — don't emit a partial DistributionSpec that Pydantic
    // will reject. Surface as a quiet no-op rather than a hard error;
    // the user can fix it after they see the verdict ignore the spec.
    return null;
  }
  return { kind, parameters };
}

function applyDistributionPrefill(row, distribution) {
  if (!distribution) return;
  const toggle = row.querySelector(".dist-toggle");
  if (!toggle) return;
  toggle.checked = true;
  const grid = row.querySelector(".dist-grid");
  if (grid) grid.hidden = false;
  const kindSel = row.querySelector(".dist-kind");
  if (kindSel) kindSel.value = distribution.kind;
  const names = DIST_PARAMS[distribution.kind] || [];
  if (names.length >= 1) {
    row.querySelector(".dist-p1").value = distribution.parameters?.[names[0]] ?? "";
  }
  if (names.length >= 2) {
    row.querySelector(".dist-p2").value = distribution.parameters?.[names[1]] ?? "";
  }
  const details = row.querySelector("details.rule-distribution");
  if (details) details.open = true;
}

// =====================================================================
// Schedule modifiers (cap / halving / vesting)
// =====================================================================

function wireScheduleToggles(row) {
  // Each "Advanced" disclosure has 3 toggles; show their numeric
  // inputs only when the toggle is checked.
  const pairs = [
    [".schedule-cap-toggle", ".schedule-cap-value"],
    [".schedule-halving-toggle", ".halving-grid"],
    [".schedule-vesting-toggle", ".schedule-vesting-periods"],
  ];
  for (const [toggleSel, fieldSel] of pairs) {
    const toggle = row.querySelector(toggleSel);
    const field = row.querySelector(fieldSel);
    if (!toggle || !field) continue;
    const sync = () => (field.hidden = !toggle.checked);
    toggle.addEventListener("change", sync);
    sync();
  }
}

function applySchedulePrefill(row, schedule) {
  const details = row.querySelector("details.rule-schedule");
  let opened = false;
  if (schedule.supply_cap != null) {
    row.querySelector(".schedule-cap-toggle").checked = true;
    row.querySelector(".schedule-cap-value").value = schedule.supply_cap;
    opened = true;
  }
  if (schedule.halving_period != null) {
    row.querySelector(".schedule-halving-toggle").checked = true;
    row.querySelector(".schedule-halving-period").value = schedule.halving_period;
    if (schedule.halving_factor != null) {
      row.querySelector(".schedule-halving-factor").value = schedule.halving_factor;
    }
    opened = true;
  }
  if (schedule.vesting_periods != null) {
    row.querySelector(".schedule-vesting-toggle").checked = true;
    row.querySelector(".schedule-vesting-periods").value = schedule.vesting_periods;
    opened = true;
  }
  if (opened && details) details.open = true;
  // Re-trigger the visibility sync now that checkboxes are set.
  wireScheduleToggles(row);
}

function readScheduleFromRow(row) {
  const out = {};
  const capOn = row.querySelector(".schedule-cap-toggle")?.checked;
  const capVal = parseFloat(row.querySelector(".schedule-cap-value")?.value);
  if (capOn && !Number.isNaN(capVal) && capVal > 0) out.supply_cap = capVal;

  const halvOn = row.querySelector(".schedule-halving-toggle")?.checked;
  const period = parseInt(row.querySelector(".schedule-halving-period")?.value, 10);
  const factor = parseFloat(row.querySelector(".schedule-halving-factor")?.value);
  if (halvOn && !Number.isNaN(period) && period >= 1) {
    out.halving_period = period;
    if (!Number.isNaN(factor) && factor > 0 && factor < 1) {
      out.halving_factor = factor;
    }
  }

  const vestOn = row.querySelector(".schedule-vesting-toggle")?.checked;
  const vestPeriods = parseInt(
    row.querySelector(".schedule-vesting-periods")?.value,
    10
  );
  if (vestOn && !Number.isNaN(vestPeriods) && vestPeriods >= 1) {
    out.vesting_periods = vestPeriods;
  }
  return Object.keys(out).length > 0 ? out : null;
}

// =====================================================================
// Events catalog (Phase H4)
// =====================================================================
//
// One row per EventDefinition. Mint / burn / regime / condition
// dropdowns all source their event-id options from this list. Whenever
// the list mutates (add / remove / id change), we re-populate every
// ``.rule-event-id`` and ``.cond-event-id`` select on the page so the
// dropdown options stay in sync.

function addEventRow(prefill = {}) {
  eventCounter++;
  const node = EVENT_TPL.content.firstElementChild.cloneNode(true);
  node.dataset.eidx = String(eventCounter);
  node.querySelector(".event-row-head h4").textContent = `Event #${eventCounter}`;
  if (prefill.id) node.querySelector(".event-id").value = prefill.id;
  if (prefill.label) node.querySelector(".event-label").value = prefill.label;
  if (prefill.kind) node.querySelector(".event-kind").value = prefill.kind;
  if (prefill.frequency) {
    node.querySelector(".event-freq-family").value = encodeFamilyValue(prefill.frequency);
    const r = _preferredRange(prefill.frequency);
    if (r) {
      node.querySelector(".event-freq-min").value = r.min ?? "";
      node.querySelector(".event-freq-max").value = r.max ?? "";
    }
  }
  // Phase L2: stochastic frequency distribution prefill.
  if (prefill.frequency_distribution) {
    const d = prefill.frequency_distribution;
    const kindSel = node.querySelector(".event-dist-kind");
    if (kindSel) kindSel.value = d.kind || "";
    const paramsBlock = node.querySelector(".event-dist-params");
    if (paramsBlock) paramsBlock.hidden = !d.kind;
    const p1 = node.querySelector(".event-dist-p1");
    const p2 = node.querySelector(".event-dist-p2");
    const params = d.parameters || {};
    if (d.kind === "normal" || d.kind === "lognormal") {
      if (p1) p1.value = params.mu ?? "";
      if (p2) p2.value = params.sigma ?? "";
    } else if (d.kind === "bernoulli") {
      if (p1) p1.value = params.p ?? "";
    } else if (d.kind === "poisson") {
      if (p1) p1.value = params.lambda ?? "";
    }
  }
  // Toggle the params block when the dist kind changes.
  // Phase L3: distribution and frequency family are MUTUALLY EXCLUSIVE.
  // When the distribution kind is non-empty, lock the frequency-family
  // controls and surface a horizon-aware preview of expected firings.
  const distKind = node.querySelector(".event-dist-kind");
  const famSel = node.querySelector(".event-freq-family");
  const famMin = node.querySelector(".event-freq-min");
  const famMax = node.querySelector(".event-freq-max");
  const distP1 = node.querySelector(".event-dist-p1");
  const distP2 = node.querySelector(".event-dist-p2");
  const distHint = node.querySelector(".event-dist-hint");
  function syncMutualExclusion() {
    const params = node.querySelector(".event-dist-params");
    const distOn = !!(distKind && distKind.value);
    if (params) params.hidden = !distOn;
    // Lock the freq family + range when a distribution is active.
    [famSel, famMin, famMax].forEach((el) => {
      if (!el) return;
      el.disabled = distOn;
      if (distOn) el.value = "";
    });
    // Lock the distribution controls when a freq family is active.
    const famOn = !!(famSel && famSel.value);
    if (distKind) {
      distKind.disabled = famOn && !distOn;
      if (famOn && !distOn) {
        distKind.value = "";
        if (params) params.hidden = true;
      }
    }
    updateFiringsPreview();
  }
  function updateFiringsPreview() {
    if (!distKind || !distHint) return;
    const kind = distKind.value;
    if (!kind) {
      distHint.textContent =
        "Normal/lognormal: (μ, σ). Bernoulli: p ∈ [0, 1]. " +
        "Poisson: λ (≥ 0). Per-period firings get clamped to ≥ 0.";
      return;
    }
    const p1 = parseFloat(distP1?.value);
    const p2 = parseFloat(distP2?.value);
    // Use the current explore-horizon hint if visible, otherwise 100.
    const H = 100;
    let mean = NaN;
    let detail = "";
    if (kind === "normal" || kind === "lognormal") {
      if (Number.isFinite(p1)) {
        mean = kind === "lognormal" ? Math.exp(p1 + (Number.isFinite(p2) ? p2 * p2 / 2 : 0)) : p1;
        detail = `μ=${p1}${Number.isFinite(p2) ? `, σ=${p2}` : ""}`;
      }
    } else if (kind === "bernoulli") {
      if (Number.isFinite(p1)) {
        mean = p1;
        detail = `p=${p1}`;
      }
    } else if (kind === "poisson") {
      if (Number.isFinite(p1)) {
        mean = p1;
        detail = `λ=${p1}`;
      }
    }
    if (Number.isFinite(mean)) {
      const expected = Math.max(0, mean) * H;
      distHint.innerHTML =
        `<strong>Preview:</strong> ${detail}. ` +
        `Expected mean firings per period ≈ ${mean.toFixed(3)}. ` +
        `Over a 100-period horizon ≈ ${expected.toFixed(1)} firings ` +
        `(clamped to ≥ 0 each period). ` +
        (kind === "bernoulli"
          ? `Bernoulli fires at most once per period.`
          : `Use Bernoulli if you want a 0/1 per period instead.`);
    }
  }
  if (distKind) distKind.addEventListener("change", syncMutualExclusion);
  if (famSel)   famSel.addEventListener("change", syncMutualExclusion);
  if (distP1)   distP1.addEventListener("input", updateFiringsPreview);
  if (distP2)   distP2.addEventListener("input", updateFiringsPreview);
  syncMutualExclusion();

  // Phase L3 — per-kind contextual hint + visibility.
  // Each kind explains what "frequency" means in its context and hides
  // fields that don't make semantic sense.
  const EVENT_KIND_INFO = {
    time_based: {
      hint: "Scheduled events. Leave frequency family empty for the implicit '1 firing per period'; set it to declare a different rate per period.",
      frequency: "optional", distribution: "optional", conditions: "rare",
    },
    behavioral: {
      hint: "Fires when agents EARN. The frequency you set here is the AGGREGATE per-period rate the verifier reasons over — the ABM's realised count comes from the agent action loop.",
      frequency: "required", distribution: "optional", conditions: "rare",
    },
    physical_resource_flow: {
      hint: "Models real-world resource arrival (mining output, deliveries). Use the frequency family or a Poisson distribution.",
      frequency: "required", distribution: "optional", conditions: "rare",
    },
    algorithmic: {
      hint: "Programmatic / smart-contract trigger. Use a deterministic frequency for fixed rates, or a stochastic distribution for randomised oracles / shocks.",
      frequency: "optional", distribution: "optional", conditions: "rare",
    },
    demand_driven: {
      hint: "Fires when agents REDEEM (burn-side counterpart of behavioral). Same rule as behavioral: declared frequency is the aggregate the verifier sees; ABM derives counts from REDEEM action mix.",
      frequency: "required", distribution: "optional", conditions: "rare",
    },
    rule_driven: {
      hint: "Governance / policy-driven event. The conditions block (below) typically holds the firing rule (e.g. 'when token_holder_vote passes'). Frequency is the verifier-side aggregate estimate.",
      frequency: "optional", distribution: "optional", conditions: "primary",
    },
    threshold_driven: {
      hint: "Fires once a state quantity crosses a threshold. Use the conditions block (below) to declare the threshold predicate. Frequency family / distribution are not the natural fit — leave empty unless modelling repeated crossings.",
      frequency: "discouraged", distribution: "discouraged", conditions: "primary",
    },
    expiry: {
      hint: "Fires when something times out (e.g. veCRV lock unlock). Effective frequency is the rate at which lockings reach their lifespan. Use a Poisson distribution to model staggered expirations.",
      frequency: "optional", distribution: "optional", conditions: "rare",
    },
    none: {
      hint: "Sentinel: this event never fires. Use as a placeholder. Frequency / distribution / conditions are all forbidden in this kind.",
      frequency: "forbidden", distribution: "forbidden", conditions: "forbidden",
    },
  };
  const kindSel = node.querySelector(".event-kind");
  const kindHint = node.querySelector(".event-kind-hint");
  const freqBlock = node.querySelectorAll(".event-freq-block");
  const distBlock = node.querySelector(".event-dist-block");
  const condDetails = node.querySelector(".event-conditions");
  function applyKindUI() {
    const k = kindSel.value || "time_based";
    const info = EVENT_KIND_INFO[k] || EVENT_KIND_INFO.time_based;
    if (kindHint) kindHint.textContent = info.hint;
    const isNone = k === "none";
    // Hide frequency + distribution entirely when kind=none.
    freqBlock.forEach((el) => el.hidden = isNone);
    if (distBlock) distBlock.hidden = isNone;
    if (condDetails) condDetails.hidden = isNone;
    // Auto-open the conditions section for kinds where it's the
    // primary trigger surface (threshold / rule).
    if (condDetails && (info.conditions === "primary")) {
      condDetails.open = true;
    }
  }
  if (kindSel) kindSel.addEventListener("change", applyKindUI);
  applyKindUI();

  // Wire the "+ Add condition" button for event-level gating.
  node.querySelector(".add-event-condition")?.addEventListener("click", () => {
    appendConditionRow(node.querySelector(".event-conditions-list"));
  });
  // Prefill conditions if YAML supplied them.
  const initConds = prefill.conditions || [];
  const initCondList = node.querySelector(".event-conditions-list");
  for (const c of initConds) appendConditionRow(initCondList, c);

  node.querySelector(".remove-event").addEventListener("click", () => {
    node.remove();
    populateAllEventDropdowns();
  });
  // Re-sync dropdowns whenever id/label changes so users see updates.
  node.querySelector(".event-id").addEventListener("input", populateAllEventDropdowns);
  node.querySelector(".event-label").addEventListener("input", populateAllEventDropdowns);
  eventsContainer.appendChild(node);
  populateAllEventDropdowns();
  return node;
}

function readEventsList() {
  if (!eventsContainer) return [];
  const out = [];
  eventsContainer.querySelectorAll(".event-row").forEach((row) => {
    const id = row.querySelector(".event-id").value.trim();
    if (!id) return;
    const label = row.querySelector(".event-label").value.trim() || id;
    const kind = row.querySelector(".event-kind").value || "time_based";
    const ev = { id, label, kind };
    const famRaw = row.querySelector(".event-freq-family").value;
    if (famRaw) {
      const min = parseFloat(row.querySelector(".event-freq-min").value);
      const max = parseFloat(row.querySelector(".event-freq-max").value);
      const ac = makeAsymptoticClass(famRaw, min, max);
      if (ac) ev.frequency = ac;
    }
    // Phase L2: stochastic per-period firings — serialise as
    // DistributionSpec. Mutually exclusive with the AC family only at
    // ABM evaluation time; the verifier still consumes ``frequency``
    // for its static surface.
    const distKindV = row.querySelector(".event-dist-kind")?.value || "";
    if (distKindV) {
      const p1 = parseFloat(row.querySelector(".event-dist-p1")?.value);
      const p2 = parseFloat(row.querySelector(".event-dist-p2")?.value);
      const dist = { kind: distKindV, parameters: {} };
      if (distKindV === "normal" || distKindV === "lognormal") {
        if (Number.isFinite(p1)) dist.parameters.mu = p1;
        if (Number.isFinite(p2)) dist.parameters.sigma = p2;
      } else if (distKindV === "bernoulli") {
        if (Number.isFinite(p1)) dist.parameters.p = p1;
      } else if (distKindV === "poisson") {
        if (Number.isFinite(p1)) dist.parameters.lambda = p1;
      }
      ev.frequency_distribution = dist;
    }
    // Phase L3: event-level gating conditions. Reuses
    // readConditionList from the rule-trigger code path.
    const condList = row.querySelector(".event-conditions-list");
    if (condList) {
      const conds = readConditionList(condList);
      if (conds.length) ev.conditions = conds;
    }
    out.push(ev);
  });
  return out;
}

function currentEventOptions() {
  return readEventsList().map((e) => ({
    value: e.id,
    label: `${e.id} — ${e.label} (${e.kind})`,
  }));
}

function populateAllEventDropdowns() {
  const options = currentEventOptions();
  const apply = (sel) => {
    if (!sel) return;
    const prior = sel.value;
    sel.innerHTML = '<option value="">— pick an event —</option>'
      + options.map((o) =>
        `<option value="${escapeAttr(o.value)}">${escapeAttr(o.label)}</option>`
      ).join("");
    if (options.some((o) => o.value === prior)) sel.value = prior;
  };
  document.querySelectorAll(".rule-event-id").forEach(apply);
  document.querySelectorAll(".cond-event-id").forEach(apply);
}

if (addEventBtn) {
  addEventBtn.addEventListener("click", () => addEventRow());
}

// =====================================================================
// Non-tokenized assets (Phase I1)
// =====================================================================

function addAssetRow(prefill = {}) {
  if (!ASSET_TPL || !assetsContainer) return null;
  assetCounter++;
  const node = ASSET_TPL.content.firstElementChild.cloneNode(true);
  node.dataset.aidx = String(assetCounter);
  node.querySelector(".asset-row-head h4").textContent = `Asset #${assetCounter}`;
  if (prefill.id) node.querySelector(".asset-id").value = prefill.id;
  if (prefill.label) node.querySelector(".asset-label").value = prefill.label;
  if (prefill.kind) node.querySelector(".asset-kind").value = prefill.kind;
  if (prefill.unique) node.querySelector(".asset-unique").checked = true;
  if (prefill.creation) {
    const fn = prefill.creation;
    node.querySelector(".asset-create-family").value = encodeFamilyValue(fn.asymptotic_class);
    const r = _preferredRange(fn.asymptotic_class);
    if (r) {
      node.querySelector(".asset-create-min").value = r.min ?? "";
      node.querySelector(".asset-create-max").value = r.max ?? "";
    }
  }
  if (prefill.consumption) {
    const fn = prefill.consumption;
    node.querySelector(".asset-consume-family").value = encodeFamilyValue(fn.asymptotic_class);
    const r = _preferredRange(fn.asymptotic_class);
    if (r) {
      node.querySelector(".asset-consume-min").value = r.min ?? "";
      node.querySelector(".asset-consume-max").value = r.max ?? "";
    }
  }
  if (prefill.redemption_cost) {
    node.querySelector(".asset-cost-min").value = prefill.redemption_cost.min ?? "";
    node.querySelector(".asset-cost-max").value = prefill.redemption_cost.max ?? "";
  }
  if (prefill.referenced_tokens?.length) {
    node.querySelector(".asset-referenced-tokens").value = prefill.referenced_tokens.join(", ");
  }
  // Phase-I3: Likert variety contribution. Invert the schema-side
  // mapping so the dropdown lands on the same step a YAML author wrote
  // (or schema default 1 → Likert 1).
  const likertSel = node.querySelector(".asset-variety-likert");
  if (likertSel) {
    const VARIETY_TO_LIKERT = { 1: 1, 3: 2, 5: 3, 10: 4, 20: 5 };
    const vc = prefill.variety_contribution ?? 1;
    likertSel.value = String(VARIETY_TO_LIKERT[vc] ?? 1);
  }
  node.querySelector(".remove-asset").addEventListener("click", () => {
    node.remove();
    syncTokenKBlocks();
  });
  assetsContainer.appendChild(node);
  return node;
}

function _readAssetFunctionShape(row, prefix) {
  const fam = row.querySelector(`.asset-${prefix}-family`).value;
  if (!fam) return null;
  const min = parseFloat(row.querySelector(`.asset-${prefix}-min`).value);
  const max = parseFloat(row.querySelector(`.asset-${prefix}-max`).value);
  const ac = makeAsymptoticClass(fam, min, max);
  if (!ac) return null;
  return { asymptotic_class: ac };
}

function readAssetsList() {
  if (!assetsContainer) return [];
  const out = [];
  assetsContainer.querySelectorAll(".asset-row").forEach((row) => {
    const id = row.querySelector(".asset-id").value.trim();
    if (!id) return;
    const asset = {
      id,
      label: row.querySelector(".asset-label").value.trim() || id,
      kind: row.querySelector(".asset-kind").value || "good",
      unique: row.querySelector(".asset-unique").checked,
    };
    const create = _readAssetFunctionShape(row, "create");
    if (create) asset.creation = create;
    const consume = _readAssetFunctionShape(row, "consume");
    if (consume) asset.consumption = consume;
    const costMin = parseFloat(row.querySelector(".asset-cost-min").value);
    const costMax = parseFloat(row.querySelector(".asset-cost-max").value);
    if (Number.isFinite(costMin) && Number.isFinite(costMax)) {
      asset.redemption_cost = { min: costMin, max: costMax };
    }
    const tokRaw = row.querySelector(".asset-referenced-tokens").value.trim();
    if (tokRaw) {
      asset.referenced_tokens = tokRaw.split(",").map((s) => s.trim()).filter(Boolean);
    }
    // Phase-I3: Likert → variety_contribution. Keep the table in sync
    // with schema.te_ir._LIKERT_TO_VARIETY.
    const LIKERT_TO_VARIETY = { 1: 1, 2: 3, 3: 5, 4: 10, 5: 20 };
    const likert = parseInt(row.querySelector(".asset-variety-likert")?.value || "1", 10);
    asset.variety_contribution = LIKERT_TO_VARIETY[likert] ?? 1;
    out.push(asset);
  });
  return out;
}

if (addAssetBtn) {
  addAssetBtn.addEventListener("click", () => {
    addAssetRow();
    syncTokenKBlocks();
  });
}

/** Phase L1 sync — K is auto-derived from the asset catalog when ≥ 1
 *  asset references a token. Disables the manual K range inputs and
 *  surfaces the derived value next to the label. Manual K stays
 *  editable only for tokens with zero asset references.
 *
 *  Called whenever:
 *    - an asset is added or removed
 *    - an asset's referenced_tokens or variety_contribution changes
 *    - a token id changes (assets reference by id)
 */
function syncTokenKBlocks() {
  if (!tokensContainer) return;
  // Count Σ variety_contribution per token id from the asset list.
  const assets = readAssetsList();
  const tally = new Map();
  for (const a of assets) {
    const vc = Math.max(1, Math.floor(a.variety_contribution || 1));
    for (const tid of (a.referenced_tokens || [])) {
      tally.set(tid, (tally.get(tid) || 0) + vc);
    }
  }
  // Apply to each token card.
  tokensContainer.querySelectorAll(".token-card").forEach((card) => {
    const tidx = card.dataset.tidx;
    const idInput = card.querySelector(`[name="tok-${tidx}-id"]`);
    const tokenId = (idInput?.value || "").trim();
    const derived = tally.get(tokenId);
    const block = card.querySelector(".token-K-block");
    if (!block) return;
    const minIn = block.querySelector(".token-K-min");
    const maxIn = block.querySelector(".token-K-max");
    const hint = block.querySelector(".K-source-hint");
    if (derived && derived > 0) {
      if (minIn) {
        minIn.value = derived;
        minIn.disabled = true;
      }
      if (maxIn) {
        maxIn.value = derived;
        maxIn.disabled = true;
      }
      if (hint) {
        hint.textContent = `— auto-derived from asset catalog: Σ variety_contribution = ${derived}`;
        hint.style.color = "#3b8a3b";
      }
    } else {
      if (minIn) minIn.disabled = false;
      if (maxIn) maxIn.disabled = false;
      if (hint) {
        hint.textContent = "— no asset references this token; set manual range";
        hint.style.color = "#666";
      }
    }
  });
}

// Re-run on every form mutation that could touch the asset catalog or
// a token id. Bound at the container level so dynamically-added rows
// are covered automatically.
if (assetsContainer) {
  assetsContainer.addEventListener("input", syncTokenKBlocks);
  assetsContainer.addEventListener("change", syncTokenKBlocks);
}

/** Decode a select value of shape ``family`` or ``family:degree`` into
 *  a {family, degree} pair. Used by every asymptotic-class dropdown
 *  (rule fn, rule freq, cross-token amount, participants growth). The
 *  ``family:degree`` encoding lets the form expose user-friendly names
 *  ("quadratic", "√t") without separate degree inputs.
 */
function parseFamilyValue(raw) {
  const value = raw || "constant";
  const [family, degreeStr] = value.split(":");
  const degree = degreeStr ? parseInt(degreeStr, 10) : null;
  return { family, degree: Number.isNaN(degree) ? null : degree };
}

/** Pick the coefficient range that best represents the user-visible
 *  "min/max" field given an AsymptoticClass. Mirrors makeAsymptoticClass:
 *
 *  - constant → c
 *  - exponential → a (per-period multiplier)
 *  - bounded_range → bounds
 *  - linear / polynomial / sublinear_root / log → b (base rate /
 *    constant offset). Fallback to ``a`` then ``value`` for older
 *    YAMLs that used the previous convention.
 *
 *  The preference order keeps round-trips faithful while still
 *  hydrating legacy IRs (e.g. axie's ``a={20, 100}`` slope encoding)
 *  with sensible defaults. */
function _preferredRange(ac) {
  if (!ac) return null;
  if (ac.bounds) return ac.bounds;
  const pr = ac.parameter_ranges || {};
  if (ac.family === "constant") return pr.c || pr.b || pr.a || pr.value;
  if (ac.family === "exponential") return pr.a || pr.b || pr.value;
  if (ac.family === "unspecified") return pr.value || pr.a || pr.b;
  // linear / polynomial / sublinear_root / log — prefer ``b`` (base
  // rate); fall back to ``a`` (legacy slope encoding) and ``value``.
  return pr.b || pr.a || pr.c || pr.value;
}

/** Inverse of parseFamilyValue — encode an AsymptoticClass back into
 *  the dropdown value, so prefilling existing IRs / examples preserves
 *  the user's polynomial degree. */
function encodeFamilyValue(ac) {
  if (!ac) return "constant";
  if ((ac.family === "polynomial" || ac.family === "sublinear_root") && ac.degree != null) {
    return `${ac.family}:${ac.degree}`;
  }
  return ac.family;
}

function makeAsymptoticClass(rawFamily, min, max) {
  const { family, degree } = parseFamilyValue(rawFamily);

  if (family === "unspecified") {
    const lo = Number.isNaN(min) ? 0 : min;
    const hi = Number.isNaN(max) ? 1e9 : max;
    return { family: "unspecified", parameter_ranges: { value: { min: lo, max: hi } } };
  }
  if (Number.isNaN(min) || Number.isNaN(max)) return null;

  if (family === "bounded_range") {
    return { family, bounds: { min, max } };
  }
  if (family === "constant") {
    return { family, parameter_ranges: { c: { min, max } } };
  }
  if (family === "exponential") {
    // exponential rate = a · b^t; ``a`` is the natural per-period
    // multiplier the user types. ``b`` defaults to 1 (no compounding)
    // via the verifier's parameter_var fallback.
    return { family, parameter_ranges: { a: { min, max } } };
  }
  // linear / polynomial / sublinear_root / log: the single user-supplied
  // range maps to ``b`` (the constant offset / base rate). ``a`` (the
  // time-dependent leading coefficient) is implicitly 0 — meaning "X
  // per period, no time growth". This matches what users intuitively
  // mean when they type "20 events per period" with family=linear.
  //
  // To express time growth, declare a polynomial / sublinear_root /
  // log family explicitly with an ``a`` override via raw YAML (the
  // form's single range field is intentionally low-friction). All
  // shipped example YAMLs adopt this convention.
  const ac = { family, parameter_ranges: { b: { min, max } } };
  if (family === "polynomial" || family === "sublinear_root") {
    ac.degree = degree ?? 2;
  }
  return ac;
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

  // Target action toggle: transfer reveals the recipient input.
  const actionSel = card.querySelector(".xt-action");
  const recipientField = card.querySelector(".xt-recipient-field");
  const transferHint = card.querySelector(".xt-transfer-hint");
  const updateActionUI = () => {
    const isTransfer = actionSel.value === "transfer";
    if (recipientField) recipientField.hidden = !isTransfer;
    if (transferHint) transferHint.hidden = !isTransfer;
  };
  actionSel.addEventListener("change", updateActionUI);

  // Amount-family toggle: constant uses a single `value` input, others
  // use a min/max range.
  const amountFamSel = card.querySelector(".xt-amount-family");
  const constantBlock = card.querySelector(".xt-amount-constant-block");
  const rangeBlock = card.querySelector(".xt-amount-range-block");
  const updateAmountUI = () => {
    const isConstant = (amountFamSel.value || "constant") === "constant";
    if (constantBlock) constantBlock.hidden = !isConstant;
    if (rangeBlock) rangeBlock.hidden = isConstant;
  };
  amountFamSel.addEventListener("change", updateAmountUI);

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
    card.querySelector(".xt-amount-family").value = encodeFamilyValue(prefill.amount);
    const r = prefill.amount.bounds || prefill.amount.parameter_ranges?.c || prefill.amount.parameter_ranges?.a;
    if (r) {
      card.querySelector(".xt-amount-min").value = r.min ?? "";
      card.querySelector(".xt-amount-max").value = r.max ?? "";
      // Round-trip min == max into the single-value input as a
      // convenience: lets the user re-edit a "fixed 3" without
      // typing both fields again.
      if (r.min === r.max) {
        const v = card.querySelector(".xt-amount-value");
        if (v) v.value = r.min ?? "";
      }
    }
  }
  if (prefill.recipient_type) {
    card.querySelector(".xt-recipient").value = prefill.recipient_type;
  }
  updateCouplingUI();
  updateActionUI();
  updateAmountUI();

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
    let min, max;
    if (family === "constant") {
      // Single-value path: read .xt-amount-value first; fall back to
      // min/max if user wrote a range there instead.
      const v = parseFloat(card.querySelector(".xt-amount-value")?.value);
      if (Number.isFinite(v)) {
        min = v;
        max = v;
      } else {
        min = parseFloat(card.querySelector(".xt-amount-min").value);
        max = parseFloat(card.querySelector(".xt-amount-max").value);
      }
    } else {
      min = parseFloat(card.querySelector(".xt-amount-min").value);
      max = parseFloat(card.querySelector(".xt-amount-max").value);
    }
    const ac = makeAsymptoticClass(family, min, max);
    if (!ac) return null;
    flow.amount = ac;
  }
  // Recipient type only meaningful when target_action == transfer.
  if (flow.target_action === "transfer") {
    const rcp = card.querySelector(".xt-recipient")?.value.trim();
    if (rcp) flow.recipient_type = rcp;
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
  const utility = prefill.utility || {};
  const jitter = prefill.utility_jitter || {};
  const checkedActions = new Set(prefill.action_set || []);
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

    <details class="agent-advanced">
      <summary>Action set (override role-based defaults)</summary>
      <p class="hint">Which actions this agent type can pick from each
        period in the ABM. Leave empty to inherit the role default.</p>
      <div class="action-set-grid">
        ${ENUMS.action_kinds.map(
          (a) => `<label class="checkbox-inline">
            <input type="checkbox" name="agent-${idx}-action" value="${a}"
              ${checkedActions.has(a) ? "checked" : ""} /> ${a}
          </label>`
        ).join("")}
      </div>
    </details>

    <details class="agent-advanced">
      <summary>Utility weights (ABM softmax — leave empty to use role defaults)</summary>
      <p class="hint">Per-action drivers used by softmax action selection.
        Higher = more attractive. <code>action_temperature</code> controls
        sharpness: &lt;1 nearly-deterministic, &gt;1 nearly-uniform.</p>
      <div class="utility-grid">
        <div class="field">
          <label>income_yield</label>
          <input type="number" name="agent-${idx}-u-income" step="0.05"
                 value="${utility.income_yield ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>holding_yield</label>
          <input type="number" name="agent-${idx}-u-holding" step="0.05"
                 value="${utility.holding_yield ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>redemption_value</label>
          <input type="number" name="agent-${idx}-u-redemption" step="0.05"
                 value="${utility.redemption_value ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>governance_payoff</label>
          <input type="number" name="agent-${idx}-u-governance" step="0.05"
                 value="${utility.governance_payoff ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>social_payoff</label>
          <input type="number" name="agent-${idx}-u-social" step="0.05"
                 value="${utility.social_payoff ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>risk_aversion</label>
          <input type="number" name="agent-${idx}-u-risk" step="0.05"
                 value="${utility.risk_aversion ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>action_temperature</label>
          <input type="number" name="agent-${idx}-u-temp" step="0.05" min="0.01"
                 value="${utility.action_temperature ?? ""}" placeholder="1.0" />
        </div>
        <div class="field">
          <label>exit_propensity (0–1)</label>
          <input type="number" name="agent-${idx}-u-exit-prop" step="0.01" min="0" max="1"
                 value="${utility.exit_propensity ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>social_comparison_delta</label>
          <input type="number" name="agent-${idx}-u-exit-delta" step="0.05" min="0"
                 value="${utility.social_comparison_delta ?? ""}" placeholder="0.3" />
        </div>
        <div class="field">
          <label>reputation_yield</label>
          <input type="number" name="agent-${idx}-u-rep-yield" step="0.05" min="0"
                 value="${utility.reputation_yield ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>reputation_decay (0–1)</label>
          <input type="number" name="agent-${idx}-u-rep-decay" step="0.01" min="0" max="1"
                 value="${utility.reputation_decay ?? ""}" placeholder="0.0" />
        </div>
      </div>
    </details>

    <details class="agent-advanced">
      <summary>Per-agent utility jitter (Phase E2 — leave empty for homogeneous cohort)</summary>
      <p class="hint">Standard deviations for per-agent Gaussian offsets
        on each utility component. At spawn time every agent draws
        <code>N(0, σ)</code> per field; cache stays per-type but agents
        differ within a role. Defaults to 0 (no jitter).</p>
      <div class="utility-grid">
        <div class="field">
          <label>σ income_yield</label>
          <input type="number" name="agent-${idx}-j-income" step="0.05" min="0"
                 value="${jitter.income_yield ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>σ holding_yield</label>
          <input type="number" name="agent-${idx}-j-holding" step="0.05" min="0"
                 value="${jitter.holding_yield ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>σ redemption_value</label>
          <input type="number" name="agent-${idx}-j-redemption" step="0.05" min="0"
                 value="${jitter.redemption_value ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>σ governance_payoff</label>
          <input type="number" name="agent-${idx}-j-governance" step="0.05" min="0"
                 value="${jitter.governance_payoff ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>σ social_payoff</label>
          <input type="number" name="agent-${idx}-j-social" step="0.05" min="0"
                 value="${jitter.social_payoff ?? ""}" placeholder="0.0" />
        </div>
        <div class="field">
          <label>σ risk_aversion</label>
          <input type="number" name="agent-${idx}-j-risk" step="0.05" min="0"
                 value="${jitter.risk_aversion ?? ""}" placeholder="0.0" />
        </div>
      </div>
    </details>
  `;
  div.querySelector(".remove-agent").addEventListener("click", () => div.remove());
  agentContainer.appendChild(div);
}

addAgentBtn.addEventListener("click", () => addAgentRow());
addAgentRow({ id: "user", fraction: 1.0, expected_holding_time: { expected_periods: { min: 5, max: 5 } } });

let popEventCounter = 0;

function addPopEventRow(prefill = {}) {
  popEventCounter++;
  const idx = popEventCounter;
  const div = document.createElement("div");
  div.className = "pop-event-row";
  div.dataset.idx = idx;
  const utility = prefill.new_utility || {};
  div.innerHTML = `
    <div class="pop-event-row-head">
      <h4>Event #${idx}</h4>
      <button type="button" class="remove-pop-event ghost-danger">remove</button>
    </div>
    <div class="pop-event-grid">
      <div class="field">
        <label>Kind</label>
        <select name="popev-${idx}-kind" class="pop-event-kind">
          ${ENUMS.population_event_kinds.map(
            (k) => `<option value="${k}" ${prefill.kind === k ? "selected" : ""}>${k}</option>`
          ).join("")}
        </select>
      </div>
      <div class="field">
        <label>At period</label>
        <input type="number" name="popev-${idx}-at" min="0" step="1"
               value="${prefill.at_period ?? ""}" placeholder="e.g. 50" />
      </div>
      <div class="field">
        <label>Agent type id</label>
        <input type="text" name="popev-${idx}-type"
               value="${escapeAttr(prefill.agent_type_id || "")}" placeholder="must match an agent_type" />
      </div>
      <div class="field pop-event-count">
        <label>Count (spawn/despawn)</label>
        <input type="number" name="popev-${idx}-count" min="0" step="1"
               value="${prefill.count ?? ""}" placeholder="e.g. 20" />
      </div>
      <div class="field pop-event-balance">
        <label>Balance per agent (spawn)</label>
        <input type="number" name="popev-${idx}-balance" min="0" step="any"
               value="${prefill.balance_per_agent ?? ""}" placeholder="0.0" />
      </div>
    </div>
    <details class="pop-event-utility" ${prefill.kind === "shift_utility" ? "open" : ""}>
      <summary>New utility (shift_utility)</summary>
      <div class="utility-grid">
        ${[
          ["income_yield", "u-income"],
          ["holding_yield", "u-holding"],
          ["redemption_value", "u-redemption"],
          ["governance_payoff", "u-governance"],
          ["social_payoff", "u-social"],
          ["risk_aversion", "u-risk"],
          ["action_temperature", "u-temp"],
          ["exit_propensity", "u-exit-prop"],
          ["social_comparison_delta", "u-exit-delta"],
          ["reputation_yield", "u-rep-yield"],
          ["reputation_decay", "u-rep-decay"],
        ].map(([key, slug]) => `
          <div class="field">
            <label>${key}</label>
            <input type="number" name="popev-${idx}-${slug}" step="0.05"
                   value="${utility[key] ?? ""}" placeholder="" />
          </div>
        `).join("")}
      </div>
    </details>
    <details class="rule-conditions">
      <summary>Conditional trigger (instead of / in addition to "at period")</summary>
      <p class="hint">
        Fire this event the first period these conditions all hold.
        Leaves "at period" blank ⇒ pure condition-driven. Both supplied ⇒
        condition path takes precedence; ``at period`` ignored.
      </p>
      <div class="pop-event-conditions-list rule-conditions-list"></div>
      <button type="button" class="add-pop-event-condition ghost">+ Add condition</button>
    </details>
  `;
  div.querySelector(".remove-pop-event").addEventListener("click", () => div.remove());
  const kindSel = div.querySelector(".pop-event-kind");
  const utilityBlock = div.querySelector(".pop-event-utility");
  kindSel.addEventListener("change", () => {
    if (kindSel.value === "shift_utility") {
      utilityBlock.open = true;
    } else {
      utilityBlock.open = false;
    }
  });
  // Pop-event conditions: prefill + add-button.
  const condList = div.querySelector(".pop-event-conditions-list");
  (prefill.conditions || []).forEach((c) => appendConditionRow(condList, c));
  div.querySelector(".add-pop-event-condition").addEventListener("click", () => {
    appendConditionRow(condList);
  });
  popEventsContainer.appendChild(div);
}

addPopEventBtn.addEventListener("click", () => addPopEventRow());

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
  // Phase-H: events catalog. Emitted only when at least one event row
  // has a non-empty id, so legacy YAMLs without events stay schema-valid.
  const events = readEventsList();
  if (events.length) ir.events = events;
  // Phase-I1: non-tokenized assets.
  const assets = readAssetsList();
  if (assets.length) ir.non_tokenized_assets = assets;

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
  const { family: growthFamily, degree: growthDegree } =
    parseFamilyValue(fd.get("part-growth") || "constant");
  const growthRange = readRange(fd, "part-growth-min", "part-growth-max");
  ir.participants.growth_g = {
    family: growthFamily,
    parameter_ranges: growthRange ? { value: growthRange } : {},
  };
  if (growthDegree != null) ir.participants.growth_g.degree = growthDegree;
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
    // Phase-A: action_set — only emit when at least one checkbox is
    // ticked, otherwise let the schema's role-based default apply.
    const actions = fd.getAll(`agent-${idx}-action`);
    if (actions.length) ag.action_set = actions;
    // Phase-A: utility weights — only emit fields the user actually
    // populated. action_temperature defaults to 1.0 if other fields
    // are set but it isn't.
    const utility = readUtility(fd, idx);
    if (utility) ag.utility = utility;
    // Phase E2 — per-agent utility jitter. Only emitted when at least
    // one sigma is positive; otherwise the schema default (None) keeps
    // the cohort homogeneous.
    const jitter = readJitter(fd, idx);
    if (jitter) ag.utility_jitter = jitter;
    agents.push(ag);
  });
  if (agents.length) ir.participants.agent_types = agents;

  // Phase-C + Phase-F: population_events
  const popEvents = [];
  popEventsContainer.querySelectorAll(".pop-event-row").forEach((row) => {
    const idx = row.dataset.idx;
    const kind = fd.get(`popev-${idx}-kind`);
    const typeId = fd.get(`popev-${idx}-type`);
    if (!kind || !typeId) return;
    const ev = { kind, agent_type_id: typeId };
    // Optional at_period — Phase-F lets the user drop it in favor of
    // condition-driven triggers.
    const periodRaw = fd.get(`popev-${idx}-at`);
    if (periodRaw != null && periodRaw !== "") {
      const at_period = parseInt(periodRaw, 10);
      if (!Number.isNaN(at_period)) ev.at_period = at_period;
    }
    const countRaw = fd.get(`popev-${idx}-count`);
    if (countRaw != null && countRaw !== "") {
      const c = parseInt(countRaw, 10);
      if (!Number.isNaN(c)) ev.count = c;
    }
    const balRaw = fd.get(`popev-${idx}-balance`);
    if (balRaw != null && balRaw !== "") {
      const b = parseFloat(balRaw);
      if (!Number.isNaN(b)) ev.balance_per_agent = b;
    }
    if (kind === "shift_utility") {
      const newUtil = readPopEventUtility(fd, idx);
      if (newUtil) ev.new_utility = newUtil;
    }
    const conds = readConditionList(row.querySelector(".pop-event-conditions-list"));
    if (conds.length) ev.conditions = conds;
    // Skip events with no trigger at all — server-side pydantic
    // validator would reject them with a less actionable error.
    if (ev.at_period === undefined && (!ev.conditions || !ev.conditions.length)) {
      return;
    }
    popEvents.push(ev);
  });
  if (popEvents.length) {
    ir.participants.population_events = popEvents;
  }

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

  // FM6 vote_weighting — defaults to LINEAR. The conditional
  // vote_weighting_params block writes the relevant NumberRange
  // (cap_fraction / avg_lock_fraction / delegate_concentration_gini
  // / reputation_gini). Non-LINEAR weightings with no matching param
  // fall back to LINEAR semantics at FM6 evaluation time.
  const voteWeighting = fd.get("gov-vote-weighting") || "linear";
  if (voteWeighting && voteWeighting !== "linear") {
    ir.governance.vote_weighting = voteWeighting;
    const VW_PARAM_BY_KIND = {
      capped: "cap_fraction",
      time_locked: "avg_lock_fraction",
      delegated: "delegate_concentration_gini",
      reputation_weighted: "reputation_gini",
    };
    const key = VW_PARAM_BY_KIND[voteWeighting];
    if (key) {
      const r = readRange(fd, `vw-${key}-min`, `vw-${key}-max`);
      if (r) ir.governance.vote_weighting_params = { [key]: r };
    }
  }
  // Note: 'linear' is the schema default; omitting the field is
  // equivalent. We omit it to keep the YAML clean.

  return ir;
}

function readUtility(fd, idx) {
  const FIELDS = {
    income_yield: `agent-${idx}-u-income`,
    holding_yield: `agent-${idx}-u-holding`,
    redemption_value: `agent-${idx}-u-redemption`,
    governance_payoff: `agent-${idx}-u-governance`,
    social_payoff: `agent-${idx}-u-social`,
    risk_aversion: `agent-${idx}-u-risk`,
    action_temperature: `agent-${idx}-u-temp`,
    exit_propensity: `agent-${idx}-u-exit-prop`,
    social_comparison_delta: `agent-${idx}-u-exit-delta`,
    reputation_yield: `agent-${idx}-u-rep-yield`,
    reputation_decay: `agent-${idx}-u-rep-decay`,
  };
  const out = {};
  let any = false;
  for (const [key, name] of Object.entries(FIELDS)) {
    const raw = fd.get(name);
    if (raw == null || raw === "") continue;
    const v = parseFloat(raw);
    if (Number.isNaN(v)) continue;
    out[key] = v;
    any = true;
  }
  if (!any) return null;
  // Schema requires action_temperature > 0; default to 1.0 if the
  // user didn't set it but did set other weights.
  if (out.action_temperature === undefined) out.action_temperature = 1.0;
  return out;
}

function readJitter(fd, idx) {
  const FIELDS = {
    income_yield: `agent-${idx}-j-income`,
    holding_yield: `agent-${idx}-j-holding`,
    redemption_value: `agent-${idx}-j-redemption`,
    governance_payoff: `agent-${idx}-j-governance`,
    social_payoff: `agent-${idx}-j-social`,
    risk_aversion: `agent-${idx}-j-risk`,
  };
  const out = {};
  let any = false;
  for (const [key, name] of Object.entries(FIELDS)) {
    const raw = fd.get(name);
    if (raw == null || raw === "") continue;
    const v = parseFloat(raw);
    if (Number.isNaN(v) || v <= 0) continue;
    out[key] = v;
    any = true;
  }
  return any ? out : null;
}

function readPopEventUtility(fd, idx) {
  const FIELDS = {
    income_yield: `popev-${idx}-u-income`,
    holding_yield: `popev-${idx}-u-holding`,
    redemption_value: `popev-${idx}-u-redemption`,
    governance_payoff: `popev-${idx}-u-governance`,
    social_payoff: `popev-${idx}-u-social`,
    risk_aversion: `popev-${idx}-u-risk`,
    action_temperature: `popev-${idx}-u-temp`,
    exit_propensity: `popev-${idx}-u-exit-prop`,
    social_comparison_delta: `popev-${idx}-u-exit-delta`,
    reputation_yield: `popev-${idx}-u-rep-yield`,
    reputation_decay: `popev-${idx}-u-rep-decay`,
  };
  const out = {};
  let any = false;
  for (const [key, name] of Object.entries(FIELDS)) {
    const raw = fd.get(name);
    if (raw == null || raw === "") continue;
    const v = parseFloat(raw);
    if (Number.isNaN(v)) continue;
    out[key] = v;
    any = true;
  }
  if (!any) return null;
  if (out.action_temperature === undefined) out.action_temperature = 1.0;
  return out;
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
  // Phase-H: rehydrate the events catalog BEFORE tokens so rule
  // dropdowns find their referenced ids.
  if (eventsContainer) eventsContainer.innerHTML = "";
  eventCounter = 0;
  for (const e of ir.events || []) addEventRow(e);
  // Phase-I1: assets.
  if (assetsContainer) assetsContainer.innerHTML = "";
  assetCounter = 0;
  for (const a of ir.non_tokenized_assets || []) addAssetRow(a);
  const tokens = ir.tokens || [];
  if (tokens.length === 0) {
    addTokenCard({ id: "T", function: ["medium_of_exchange"] });
  } else {
    for (const t of tokens) addTokenCard(t);
  }
  populateAllEventDropdowns();

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
    setVal("part-growth", encodeFamilyValue(g));
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

  // Population events — clear and rebuild
  popEventsContainer.innerHTML = "";
  popEventCounter = 0;
  for (const ev of ir.participants?.population_events || []) addPopEventRow(ev);

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

  // FM6 vote_weighting + params
  const vw = ir.governance?.vote_weighting || "linear";
  setVal("gov-vote-weighting", vw);
  const params = ir.governance?.vote_weighting_params || {};
  if (params.cap_fraction)               setRange("vw-cap_fraction-min", "vw-cap_fraction-max", params.cap_fraction);
  if (params.avg_lock_fraction)          setRange("vw-avg_lock_fraction-min", "vw-avg_lock_fraction-max", params.avg_lock_fraction);
  if (params.delegate_concentration_gini) setRange("vw-delegate_concentration_gini-min", "vw-delegate_concentration_gini-max", params.delegate_concentration_gini);
  if (params.reputation_gini)            setRange("vw-reputation_gini-min", "vw-reputation_gini-max", params.reputation_gini);
  syncVoteWeightingParamVisibility();
}

// Toggle which vote_weighting_params block is visible based on the
// selected weighting kind. The user only sees the input the chosen
// kind needs; others stay hidden to keep the form clean.
function syncVoteWeightingParamVisibility() {
  const sel = document.getElementById("gov-vote-weighting");
  if (!sel) return;
  const kind = sel.value;
  const KIND_TO_BLOCK = {
    capped: "vw-cap_fraction",
    time_locked: "vw-avg_lock_fraction",
    delegated: "vw-delegate_concentration_gini",
    reputation_weighted: "vw-reputation_gini",
  };
  const visible = KIND_TO_BLOCK[kind] || null;
  document.querySelectorAll(".vw-param").forEach((el) => {
    el.hidden = el.id !== visible;
  });
}
// Wire the change handler at module init (after DOM is ready).
document.addEventListener("DOMContentLoaded", () => {
  const sel = document.getElementById("gov-vote-weighting");
  if (sel) {
    sel.addEventListener("change", syncVoteWeightingParamVisibility);
    syncVoteWeightingParamVisibility();
  }
});

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
// Pre-flight validation
// =====================================================================
//
// Pydantic catches structural errors on the server, but the round-trip
// surfaces them as opaque "validation error" blobs. We catch the most
// common UI-level mistakes (min > max, agent fractions ≠ 1.0, negative
// magnitudes) locally so the user sees precise error messages.

/** Walk every {min, max} number-input pair on the form and confirm
 *  min ≤ max. Returns null on success or a human-readable error. */
function validateRanges() {
  const minInputs = document.querySelectorAll('input[type="number"]');
  // Group by "stem" — i.e. the name/class with -min/-max stripped — so
  // we can pair the two inputs.
  const pairs = new Map();
  minInputs.forEach((el) => {
    const key = (el.name || el.className).trim();
    if (!key) return;
    let stem = null;
    let side = null;
    if (key.endsWith("-min")) { stem = key.slice(0, -4); side = "min"; }
    else if (key.endsWith("-max")) { stem = key.slice(0, -4); side = "max"; }
    else if (key.endsWith("min")) { stem = key.slice(0, -3); side = "min"; }
    else if (key.endsWith("max")) { stem = key.slice(0, -3); side = "max"; }
    if (!stem) return;
    const bucket = pairs.get(stem) || {};
    bucket[side] = el;
    pairs.set(stem, bucket);
  });
  for (const [stem, { min, max }] of pairs.entries()) {
    if (!min || !max) continue;
    if (min.value === "" || max.value === "") continue;
    const lo = parseFloat(min.value);
    const hi = parseFloat(max.value);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) continue;
    if (lo > hi) {
      min.focus();
      return `Range ${prettyStem(stem)} has min (${lo}) greater than max (${hi}).`;
    }
  }
  return null;
}

function prettyStem(stem) {
  return stem
    .replace(/^vw-/, "")
    .replace(/^gov-/, "")
    .replace(/^part-/, "")
    .replace(/^agent-\d+-/, "agent.")
    .replace(/^popev-\d+-/, "event.")
    .replace(/^tok-[^-]+-/, "token.")
    .replace(/^xt-/, "cross-token.")
    .replace(/^rule-/, "rule.")
    .replace(/[-_]/g, " ")
    .trim();
}

/** Sum agent_type fractions across all rendered rows. Pydantic enforces
 *  sum ≈ 1.0 at validation time; we surface the same check live so the
 *  user can correct it without round-tripping. */
function agentFractionSum() {
  let sum = 0;
  agentContainer.querySelectorAll(".agent-row").forEach((row) => {
    const idx = row.dataset.idx;
    const el = row.querySelector(`[name="agent-${idx}-fraction"]`);
    const v = parseFloat(el?.value || "0");
    if (Number.isFinite(v)) sum += v;
  });
  return sum;
}

/** Render a status pill next to the agent-types header showing the
 *  live fraction sum. Green when ≈1.0, amber otherwise. */
function updateAgentFractionIndicator() {
  let pill = document.getElementById("agent-fraction-pill");
  if (!pill) {
    const heading = document.querySelector("#stage-pop .agent-types-header") ||
      agentContainer?.parentElement?.querySelector("h3, h4");
    if (!heading) return;
    pill = document.createElement("span");
    pill.id = "agent-fraction-pill";
    pill.className = "fraction-pill";
    heading.appendChild(pill);
  }
  const sum = agentFractionSum();
  const ok = sum >= 0.99 && sum <= 1.01;
  pill.textContent = `Σ fractions = ${sum.toFixed(2)}${ok ? " ✓" : " (must ≈ 1.0)"}`;
  pill.classList.toggle("ok", ok);
  pill.classList.toggle("bad", !ok);
}

// Re-run the indicator whenever an agent fraction changes or rows are
// added/removed.
agentContainer?.addEventListener("input", (e) => {
  if (e.target.matches('input[name^="agent-"][name$="-fraction"]')) {
    updateAgentFractionIndicator();
  }
});
new MutationObserver(updateAgentFractionIndicator).observe(
  agentContainer || document.body, { childList: true, subtree: false },
);

/** Top-level validator. Returns null when the form is ready to submit,
 *  or a precise error message naming the offending field. */
function validateForm() {
  const rangeErr = validateRanges();
  if (rangeErr) return rangeErr;
  if (agentContainer.querySelectorAll(".agent-row").length) {
    const sum = agentFractionSum();
    if (sum < 0.99 || sum > 1.01) {
      return `Agent-type fractions sum to ${sum.toFixed(2)} but must total ~1.0.`;
    }
  }
  return null;
}

// =====================================================================
// Verify
// =====================================================================

verifyBtn.addEventListener("click", async () => {
  verifyStatus.classList.remove("error");
  // Front-load sanity checks the server would also catch, but with
  // line-of-sight error messages so the user knows which input is bad.
  const formError = validateForm();
  if (formError) {
    verifyStatus.classList.add("error");
    verifyStatus.textContent = `Form error: ${formError}`;
    return;
  }
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
    // Populate the hidden rich containers (coherence-issues lives there
    // and is still surfaced; report-summary + verdict-cards are kept as
    // hidden stubs so renderReport can populate them without erroring).
    renderReport(data.report);
    // Minimal reachability table is now the only verdict surface. Fetch
    // it eagerly on every verify so the user sees a populated table
    // straight away.
    invalidateMinimalCache();
    showMinimalView();
    verifyStatus.textContent = `Done — severity: ${data.report.severity}`;
  } catch (e) {
    verifyStatus.classList.add("error");
    verifyStatus.textContent = `Error: ${e.message || e}`;
  }
});

// =====================================================================
// Direct simulate / explore (skip the manual paste step)
// =====================================================================
//
// Both buttons:
//   1. Build the IR from form state.
//   2. Round-trip through /api/yaml-to-ir to canonicalize as YAML.
//   3. Hand off to /simulate or /explore via sessionStorage — the
//      target page reads it on load and pre-fills its YAML textarea.
//
// The sessionStorage handoff lets us cross page boundaries without
// shoving the entire YAML through the URL.

async function buildAndStashYaml() {
  let ir;
  try {
    ir = buildIR();
  } catch (e) {
    verifyStatus.classList.add("error");
    verifyStatus.textContent = `Form error: ${e.message}`;
    return null;
  }
  const res = await fetch("/api/build-and-verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ir }),
  });
  const data = await res.json();
  if (!res.ok || data.error) {
    verifyStatus.classList.add("error");
    verifyStatus.textContent = `Error: ${data.error || res.statusText}`;
    return null;
  }
  return data.yaml || "";
}

// Phase M — Flow-graph preview (Stage 3.2).
// Light-weight YAML builder for the preview: uses /api/ir-to-yaml so
// every keystroke skips the verifier pass that build-and-verify
// otherwise runs. Silent on errors — partial forms shouldn't surface
// FM-level diagnostics into the preview lane.
async function buildYamlForPreview() {
  let ir;
  try {
    ir = buildIR();
  } catch {
    return "";
  }
  try {
    const r = await fetch("/api/ir-to-yaml", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir }),
    });
    if (!r.ok) return "";
    const data = await r.json();
    return data.yaml || "";
  } catch {
    return "";
  }
}
if (typeof bindFormFlowGraph === "function") {
  bindFormFlowGraph(buildYamlForPreview);
}

// Phase L2 — MC handoff button removed; the ABM-explorer button below
// is the sole "send the form-built spec onward" path.

if (exploreDirectBtn) {
  exploreDirectBtn.addEventListener("click", async () => {
    verifyStatus.classList.remove("error");
    verifyStatus.textContent = "Preparing explorer…";
    const yamlText = await buildAndStashYaml();
    if (yamlText == null) return;
    sessionStorage.setItem("te_form_yaml", yamlText);
    verifyStatus.textContent = "Done — opening explorer.";
    window.location.href = "/explore";
  });
}

// =====================================================================
// Verdict view (minimal reachability — only mode after the Rich/Minimal
// toggle was removed; same JSON shape the ABM and cadCAD export consume).
// =====================================================================

const minimalView = document.getElementById("minimal-view");
const minimalTable = document.getElementById("minimal-table");

let minimalCache = null;  // cached minimal verdicts for the most recent verify

function invalidateMinimalCache() { minimalCache = null; }

async function showMinimalView() {
  if (minimalView) minimalView.hidden = false;

  if (minimalCache) {
    renderMinimalTable(minimalCache);
    return;
  }
  if (!lastVerifiedYaml) {
    minimalTable.innerHTML = '<p class="hint">Run Verify first.</p>';
    return;
  }
  minimalTable.innerHTML = '<p class="hint">Loading reachability summary…</p>';
  try {
    const r = await fetch("/api/minimal-verdicts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml: lastVerifiedYaml }),
    });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    minimalCache = data.verdicts || [];
    renderMinimalTable(minimalCache);
  } catch (e) {
    minimalTable.innerHTML = `<p class="hint error">Failed: ${e.message}</p>`;
  }
}

function renderMinimalTable(verdicts) {
  if (!verdicts || !verdicts.length) {
    minimalTable.innerHTML = '<p class="hint">No verdicts.</p>';
    return;
  }
  const rows = verdicts.map((v) => {
    const status = v.structural_status;
    const thr = v.minimum_param_shift
      ? Object.entries(v.minimum_param_shift).map(([k, val]) => `${k}=${formatThreshold(val)}`).join(", ")
      : "—";
    const preds = (v.safety_predicates || []).map((p) =>
      `<code>${escapeHTML(p.variable)} ${p.operator} ${formatThreshold(p.threshold)}</code>`
    ).join("") || "—";  /* chips stack as blocks — no separator needed */
    const needsExplain =
      (status === "fragile" || status === "broken" || status === "inconclusive")
      && v.explanation;
    const explainRow = needsExplain
      ? `
      <tr class="explain-row">
        <td colspan="7">
          <details class="explain-details">
            <summary>Why this verdict</summary>
            <p>${escapeHTML(v.explanation)}</p>
          </details>
        </td>
      </tr>`
      : "";
    return `
      <tr>
        <td>${v.failure_mode}</td>
        <td>${escapeHTML(v.subject)}</td>
        <td><span class="status-pill status-${status}">${status}</span></td>
        <td>${triCell(v.violation_reachable, false)}</td>
        <td>${triCell(v.satisfaction_reachable, true)}</td>
        <td>${thr}</td>
        <td>${preds}</td>
      </tr>${explainRow}
    `;
  }).join("");
  minimalTable.innerHTML = `
    <details class="legend-box">
      <summary>Legend (what the columns and symbols mean)</summary>
      <dl class="legend-dl">
        <dt><strong>FM</strong></dt>
        <dd>The failure mode being checked (FM1 oversupply, FM2 velocity
            trap, FM3 burn/emission imbalance, FM4 free-rider, FM5 critical
            mass, FM6 governance capture).</dd>
        <dt><strong>Subject</strong></dt>
        <dd>What the verdict is about — a specific token id for per-token
            FMs (FM1, FM2, FM3) or <code>system</code> for whole-spec FMs
            (FM4, FM5, FM6).</dd>
        <dt><strong>Status</strong></dt>
        <dd>
          <span class="status-pill status-sound">sound</span> — predicate
              holds across the entire declared parameter box (safe by
              construction).<br/>
          <span class="status-pill status-fragile">fragile</span> — both
              safe and unsafe assignments exist in the box (the spec
              straddles the cliff). Run the ABM to estimate likelihood.<br/>
          <span class="status-pill status-broken">broken</span> — no
              assignment in the box satisfies the predicate. Structurally
              unsafe; redesign needed (the ABM cannot rescue it).<br/>
          <span class="status-pill status-not_applicable">not_applicable</span>
              — this FM does not apply (e.g. FM4 for a time-based emission).<br/>
          <span class="status-pill status-inconclusive">inconclusive</span>
              — solver couldn't decide; usually means a parameter is
              under-specified (range too wide, asymptotic class unset).
        </dd>
        <dt><strong>V — violation reachable</strong></dt>
        <dd>Is there at least one parameter assignment in the declared box
            for which the FM fires?
            <span class="tri-bad">yes</span> = reachable (bad — shown red);
            <span class="tri-good">no</span> = not reachable (good — shown green);
            <span class="tri-unk">?</span> = unknown (skipped /
            inconclusive / not applicable).</dd>
        <dt><strong>S — satisfaction reachable</strong></dt>
        <dd>Is there at least one parameter assignment in the box for
            which the safety predicate <em>holds</em>?
            <span class="tri-good">yes</span> = a safe corner exists
            (good — shown green);
            <span class="tri-bad">no</span> = no safe assignment
            anywhere (bad — shown red).
            Together with V it determines the status:
            <code>V=no, S=yes ⇒ sound</code>,
            <code>V=yes, S=yes ⇒ fragile</code>,
            <code>V=yes, S=no ⇒ broken</code>.</dd>
        <dt><strong>Threshold</strong></dt>
        <dd>For <em>fragile</em> / <em>broken</em> rows: the minimum
            parameter shift needed to reach <em>sound</em> — the
            closest point on the cliff. For <em>inconclusive</em>
            rows: the conservative worst-case threshold when the FM
            exposes one (e.g. FM5 under a spatial topology reports the
            well-mixed bound N* = 2·K·d + 1 at the worst corner of
            your ranges — meeting it guarantees safety, but a spatial
            economy may also survive below it). Empty for sound /
            not-applicable rows where no shift is required.</dd>
        <dt><strong>Safety predicates</strong></dt>
        <dd>The formal property the ABM evaluates per period and uses to
            count violations. Written as
            <code>variable operator threshold</code>; same JSON shape the
            cadCAD export consumes.</dd>
        <dt><strong>—</strong></dt>
        <dd>No value emitted (e.g. no threshold needed, FM not simulable).</dd>
      </dl>
    </details>
    <table class="minimal-table">
      <thead><tr>
        <th title="Failure mode (FM1–FM6 from the DLT2026 paper)">FM</th>
        <th title="Token id for per-token FMs; 'system' for whole-spec FMs">Subject</th>
        <th title="sound / fragile / broken / not_applicable / inconclusive">Status</th>
        <th title="Violation reachable in the declared parameter box?">V</th>
        <th title="Satisfaction (safety predicate holds) reachable in the box?">S</th>
        <th title="Minimum parameter shift to move fragile→sound">Threshold</th>
        <th title="Formal predicate evaluated by the ABM each period">Safety predicates</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function triCell(value, goodWhenTrue = false) {
  // Color by MEANING, not by literal yes/no: in the V column a "yes"
  // (violation reachable) is bad news; in the S column a "yes" (a safe
  // corner exists) is good news. Callers pass goodWhenTrue accordingly.
  if (value === "true")
    return `<span class="${goodWhenTrue ? "tri-good" : "tri-bad"}">yes</span>`;
  if (value === "false")
    return `<span class="${goodWhenTrue ? "tri-bad" : "tri-good"}">no</span>`;
  return '<span class="tri-unk">?</span>';
}

function formatThreshold(n) {
  if (n == null || isNaN(n)) return "—";
  if (Math.abs(n) >= 1e6 || (n !== 0 && Math.abs(n) < 0.001)) return n.toExponential(2);
  return Number.isInteger(n) ? String(n) : n.toFixed(3);
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

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
