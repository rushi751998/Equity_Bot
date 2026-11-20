let STRATEGIES = [];
let BENCH = { dates: [], closes: [] };
let state = [];
let activeTrades = [];
let sortCol = "entry_ts";
let sortAsc = false;
let currentTrade = null;
let currentTf = "5m";
let cachedCandles = [];
let cachedPatternShapes = {};

// TradingView-style chart viewport & measurement state
let viewStart = 0;
let viewEnd = 0;
let anchorA = null;
let anchorB = null;
let lastMouse = null;

// Runner / Scenario Builder state (persisted in localStorage)
const STORAGE_KEY_SCENARIOS = "tfalgo_saved_scenarios_v1";
const STORAGE_KEY_LAST_FORM = "tfalgo_last_scenario_form_v1";
let AVAILABLE_CONFIGS = [];
let SAVED_SCENARIOS = {};
let SELECTED_CONFIGS = new Set();
let runnerTimer = null;
let runnerStartMs = 0;

const DEFAULT_SCENARIO_FORM = {
  fileName: "ema_breakout_custom.yaml",
  strategyName: "ema_breakout_v1",
  timeframe: "1h",
  emaPeriods: "9, 21, 50",
  consolidationDays: 5,
  maxRangePct: 8.0,
  volMult: 1.5,
  impulseMult: 2.0,
  slSource: "1h_low",
  holdingMode: "swing",
  riskPct: 1.0,
  tranches: "0.33, 0.33, 0.34",
  addAtR: "1.0, 2.0",
  riskNeutralSl: true,
  trailTimeframe: "1h",
  trailEmaInitial: 21,
  trailEmaRunner: 9,
  runnerAtrMult: 0.5,
  notes: "1H E9/21/50 breakout after >=5d consolidation, 5m trigger, 1R/2R pyramid, 3R/6R + E9-ATR trail",
};

function loadPersistedScenarios() {
  try {
    SAVED_SCENARIOS = JSON.parse(localStorage.getItem(STORAGE_KEY_SCENARIOS) || "{}") || {};
  } catch {
    SAVED_SCENARIOS = {};
  }
}

function savePersistedScenarios() {
  try {
    localStorage.setItem(STORAGE_KEY_SCENARIOS, JSON.stringify(SAVED_SCENARIOS));
  } catch (e) {
    console.warn("Could not save scenarios to localStorage:", e);
  }
}

function loadLastForm() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY_LAST_FORM) || "null");
    return raw ? { ...DEFAULT_SCENARIO_FORM, ...raw } : { ...DEFAULT_SCENARIO_FORM };
  } catch {
    return { ...DEFAULT_SCENARIO_FORM };
  }
}

function saveLastForm(formObj) {
  try {
    localStorage.setItem(STORAGE_KEY_LAST_FORM, JSON.stringify(formObj));
  } catch (e) {
    console.warn("Could not save last form:", e);
  }
}

function showTab(name, btn) {
  ["sim", "runner", "live"].forEach(t => {
    const el = document.getElementById("tab_" + t);
    if (el) el.style.display = t === name ? "block" : "none";
  });
  document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  if (name === "live") {
    fetch("/api/live")
      .then(r => r.json())
      .then(d => {
        const msg = document.getElementById("liveMsg");
        if (msg) msg.textContent = d.message || "";
      })
      .catch(err => {
        const msg = document.getElementById("liveMsg");
        if (msg) msg.textContent = "Failed to load live status: " + err.message;
      });
  }
}

async function init() {
  const capInput = document.getElementById("capInput");
  if (capInput) capInput.addEventListener("input", recalc);

  loadPersistedScenarios();
  injectRunnerStyles();

  try {
    const res = await fetch("/api/configs");
    const cfgs = await res.json();
    AVAILABLE_CONFIGS = cfgs.configs || [];
    AVAILABLE_CONFIGS.forEach((c, idx) => {
      if (idx === 0 || c.includes("ema_breakout")) SELECTED_CONFIGS.add(c);
    });
  } catch (err) {
    console.error("Failed to load configs:", err);
  }

  renderRunnerUI();
  await refreshRuns();
}

function injectRunnerStyles() {
  if (document.getElementById("tfalgoRunnerStyles")) return;
  const st = document.createElement("style");
  st.id = "tfalgoRunnerStyles";
  st.textContent = `
    .rn-wrap { display: grid; gap: 18px; }
    .rn-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(15,23,42,0.04); }
    .rn-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
    .rn-title { margin: 0; font-size: 16px; font-weight: 700; color: #0f172a; }
    .rn-sub { font-size: 12.5px; color: #64748b; }
    .rn-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 14px; }
    .sc-card { border: 1.5px solid #e2e8f0; border-radius: 10px; padding: 14px; background: #f8fafc; transition: border-color .15s, box-shadow .15s; display: flex; flex-direction: column; gap: 10px; }
    .sc-card.selected { border-color: #2563eb; background: #eff6ff; box-shadow: 0 2px 8px rgba(37,99,235,0.10); }
    .sc-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
    .sc-name { font-weight: 700; font-size: 13.5px; color: #0f172a; word-break: break-all; }
    .sc-badges { display: flex; gap: 5px; flex-wrap: wrap; }
    .sc-badge { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 999px; background: #e2e8f0; color: #334155; }
    .sc-badge.blue { background: #dbeafe; color: #1d4ed8; }
    .sc-badge.green { background: #dcfce7; color: #15803d; }
    .sc-cfg-box { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 9px 10px; font-size: 11.5px; color: #334155; display: grid; grid-template-columns: 1fr 1fr; gap: 5px 10px; }
    .sc-cfg-row b { color: #0f172a; }
    .sc-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: auto; }
    .rn-btn { border: 1px solid #cbd5e1; background: #fff; color: #0f172a; border-radius: 7px; padding: 6px 11px; font-size: 12px; font-weight: 600; cursor: pointer; }
    .rn-btn:hover { background: #f1f5f9; }
    .rn-btn.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
    .rn-btn.primary:hover { background: #1d4ed8; }
    .rn-btn.dark { background: #0f172a; border-color: #0f172a; color: #fff; }
    .rn-form { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
    .rn-field { display: flex; flex-direction: column; gap: 4px; }
    .rn-field label { font-size: 11.5px; font-weight: 600; color: #475569; }
    .rn-field input, .rn-field select { padding: 7px 9px; border: 1px solid #cbd5e1; border-radius: 7px; font-size: 13px; background: #fff; color: #0f172a; }
    .rn-prog-wrap { margin-top: 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 9px; padding: 12px 14px; display: none; }
    .rn-prog-wrap.active { display: block; }
    .rn-prog-top { display: flex; justify-content: space-between; font-size: 12.5px; font-weight: 600; color: #0f172a; margin-bottom: 7px; }
    .rn-prog-track { width: 100%; height: 10px; background: #e2e8f0; border-radius: 999px; overflow: hidden; }
    .rn-prog-bar { height: 100%; width: 0%; background: linear-gradient(90deg, #2563eb, #0ea5e9); transition: width 0.35s ease; }
    .rn-presets { display: flex; gap: 6px; flex-wrap: wrap; }
  `;
  document.head.appendChild(st);
}

function getScenarioMeta(cfgPath) {
  if (SAVED_SCENARIOS[cfgPath]) return SAVED_SCENARIOS[cfgPath];
  const base = cfgPath.split("/").pop() || cfgPath;
  if (base.includes("ema_breakout")) {
    return {
      strategyName: "ema_breakout_v1",
      timeframe: "1h",
      emaPeriods: "9, 21, 50",
      consolidationDays: 5,
      maxRangePct: 8.0,
      volMult: 1.5,
      impulseMult: 2.0,
      slSource: "1h_low",
      holdingMode: "swing",
      riskPct: 1.0,
      tranches: "0.33, 0.33, 0.34",
      addAtR: "1.0, 2.0",
      trailTimeframe: "1h",
      trailEmaInitial: 21,
      trailEmaRunner: 9,
      runnerAtrMult: 0.5,
      notes: "Default EMA Breakout + Pyramid",
    };
  }
  if (base.includes("orb_short")) {
    return { strategyName: "orb_short_v1", timeframe: "5m", holdingMode: "mis", notes: "Opening Range Breakdown (Short)" };
  }
  if (base.includes("orb")) {
    return { strategyName: "orb_v1", timeframe: "5m", holdingMode: "mis", notes: "Opening Range Breakout (Long)" };
  }
  if (base.includes("pilot")) {
    return { strategyName: "trend_pullback_v1", timeframe: "1h / 5m", holdingMode: "mis", notes: "Pilot Trend Pullback" };
  }
  return { strategyName: "default", timeframe: "5m", holdingMode: "mis", notes: "Base configuration" };
}

function renderRunnerUI() {
  const tab = document.getElementById("tab_runner");
  if (!tab) return;
  const f = loadLastForm();

  const cardsHtml = AVAILABLE_CONFIGS.length
    ? AVAILABLE_CONFIGS.map(cfgPath => {
        const meta = getScenarioMeta(cfgPath);
        const sel = SELECTED_CONFIGS.has(cfgPath);
        const name = cfgPath.split("/").pop();
        const isEma = (meta.strategyName || "").includes("ema_breakout") || name.includes("ema_breakout");
        return `
          <div class="sc-card ${sel ? "selected" : ""}">
            <div class="sc-top">
              <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                <input type="checkbox" class="cfg-cb" value="${cfgPath}" ${sel ? "checked" : ""} onchange="toggleScenarioSelect('${cfgPath}', this.checked)">
                <span class="sc-name">${name}</span>
              </label>
              <div class="sc-badges">
                <span class="sc-badge blue">${meta.strategyName || "strategy"}</span>
                <span class="sc-badge green">${(meta.holdingMode || "swing").toUpperCase()}</span>
              </div>
            </div>
            <div class="sc-cfg-box">
              <div class="sc-cfg-row"><b>Setup TF:</b> ${meta.timeframe || "1h"}</div>
              <div class="sc-cfg-row"><b>EMAs:</b> ${meta.emaPeriods || "9, 21, 50"}</div>
              ${isEma ? `
                <div class="sc-cfg-row"><b>Consol:</b> &ge;${meta.consolidationDays ?? 5}d (&le;${meta.maxRangePct ?? 8}%)</div>
                <div class="sc-cfg-row"><b>Vol Mult:</b> &ge;${meta.volMult ?? 1.5}x</div>
                <div class="sc-cfg-row"><b>SL Source:</b> ${meta.slSource || "1h_low"}</div>
                <div class="sc-cfg-row"><b>Tranches:</b> ${meta.tranches || "0.33/0.33/0.34"}</div>
                <div class="sc-cfg-row"><b>Trail:</b> E${meta.trailEmaInitial ?? 21} &rarr; E${meta.trailEmaRunner ?? 9} - ${meta.runnerAtrMult ?? 0.5} ATR</div>
                <div class="sc-cfg-row"><b>Risk/Trade:</b> ${meta.riskPct ?? 1.0}%</div>
              ` : `
                <div class="sc-cfg-row" style="grid-column:span 2;"><b>Notes:</b> ${meta.notes || cfgPath}</div>
              `}
            </div>
            <div class="sc-actions">
              <button type="button" class="rn-btn primary" onclick="runSingleScenario('${cfgPath}')">Run Scenario</button>
              <button type="button" class="rn-btn" onclick="loadScenarioIntoForm('${cfgPath}')">Load into Editor</button>
            </div>
          </div>`;
      }).join("")
    : `<div class="rn-sub">No YAML configs found in <code>config/</code>. Create one below.</div>`;

  tab.innerHTML = `
    <div class="rn-wrap">
      <div class="rn-card">
        <div class="rn-head">
          <div>
            <h3 class="rn-title">Scenario Library</h3>
            <div class="rn-sub">Select one or more scenario cards to compare, inspect their configuration below, or run individually.</div>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <label style="font-size:12.5px;color:#475569;display:flex;align-items:center;gap:5px;">
              <input type="checkbox" id="autoOpenSim" checked> Auto-open Simulator on finish
            </label>
            <button type="button" class="rn-btn primary" onclick="runBatchNow()">Run Selected (${SELECTED_CONFIGS.size})</button>
          </div>
        </div>

        <div class="rn-grid">${cardsHtml}</div>

        <div id="rnProgressWrap" class="rn-prog-wrap">
          <div class="rn-prog-top">
            <span id="runStatusMsg">Ready</span>
            <span id="rnElapsed">0s</span>
          </div>
          <div class="rn-prog-track"><div id="rnProgressBar" class="rn-prog-bar"></div></div>
        </div>
      </div>

      <div class="rn-card">
        <div class="rn-head">
          <div>
            <h3 class="rn-title">Create / Edit Scenario Configuration</h3>
            <div class="rn-sub">Your last configuration is saved automatically in browser storage (and saved to <code>config/</code> if <code>/api/save_config</code> is enabled).</div>
          </div>
          <div class="rn-presets">
            <button type="button" class="rn-btn" onclick="applyPreset('1h_swing')">Preset: 1H Swing</button>
            <button type="button" class="rn-btn" onclick="applyPreset('1d_swing')">Preset: 1D Swing</button>
            <button type="button" class="rn-btn" onclick="applyPreset('tight_base')">Preset: Tight Base</button>
          </div>
        </div>

        <div class="rn-form">
          <div class="rn-field"><label>Config Filename (.yaml)</label><input id="sc_fileName" value="${f.fileName}"></div>
          <div class="rn-field"><label>Setup Timeframe</label>
            <select id="sc_timeframe">
              <option value="1h" ${f.timeframe === "1h" ? "selected" : ""}>1h (Hourly)</option>
              <option value="1d" ${f.timeframe === "1d" ? "selected" : ""}>1d (Daily)</option>
            </select>
          </div>
          <div class="rn-field"><label>EMAs (Fast, Mid, Slow)</label><input id="sc_emaPeriods" value="${f.emaPeriods}"></div>
          <div class="rn-field"><label>Min Consolidation Days</label><input type="number" id="sc_consolidationDays" value="${f.consolidationDays}"></div>
          <div class="rn-field"><label>Max Range % (Tightness)</label><input type="number" step="0.5" id="sc_maxRangePct" value="${f.maxRangePct}"></div>
          <div class="rn-field"><label>Breakout Volume Mult</label><input type="number" step="0.1" id="sc_volMult" value="${f.volMult}"></div>
          <div class="rn-field"><label>5m Impulse % Mult</label><input type="number" step="0.1" id="sc_impulseMult" value="${f.impulseMult}"></div>
          <div class="rn-field"><label>Initial Stop Source</label>
            <select id="sc_slSource">
              <option value="1h_low" ${f.slSource === "1h_low" ? "selected" : ""}>1h Candle Low</option>
              <option value="1d_low" ${f.slSource === "1d_low" ? "selected" : ""}>1d Candle Low</option>
              <option value="5m_low" ${f.slSource === "5m_low" ? "selected" : ""}>5m Swing Low</option>
            </select>
          </div>
          <div class="rn-field"><label>Holding Mode</label>
            <select id="sc_holdingMode">
              <option value="swing" ${f.holdingMode === "swing" ? "selected" : ""}>Swing (Multi-day)</option>
              <option value="mis" ${f.holdingMode === "mis" ? "selected" : ""}>MIS (Intraday)</option>
            </select>
          </div>
          <div class="rn-field"><label>Risk per Trade (%)</label><input type="number" step="0.25" id="sc_riskPct" value="${f.riskPct}"></div>
          <div class="rn-field"><label>Pyramid Tranches</label><input id="sc_tranches" value="${f.tranches}"></div>
          <div class="rn-field"><label>Add at R Levels</label><input id="sc_addAtR" value="${f.addAtR}"></div>
          <div class="rn-field"><label>Trail Initial EMA / Runner EMA</label>
            <div style="display:flex;gap:6px;">
              <input type="number" id="sc_trailEmaInitial" value="${f.trailEmaInitial}" style="width:50%;">
              <input type="number" id="sc_trailEmaRunner" value="${f.trailEmaRunner}" style="width:50%;">
            </div>
          </div>
          <div class="rn-field"><label>Runner ATR Mult</label><input type="number" step="0.1" id="sc_runnerAtrMult" value="${f.runnerAtrMult}"></div>
          <div class="rn-field" style="grid-column: span 2;"><label>Scenario Notes</label><input id="sc_notes" value="${f.notes || ""}"></div>
        </div>

        <div style="display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap;">
          <button type="button" class="rn-btn dark" onclick="saveScenarioFromForm(false)">Save Scenario</button>
          <button type="button" class="rn-btn primary" onclick="saveScenarioFromForm(true)">Save &amp; Run Scenario</button>
          <button type="button" class="rn-btn" onclick="copyScenarioYaml()">Copy YAML</button>
          <span id="scFormMsg" class="rn-sub"></span>
        </div>
      </div>
    </div>
  `;
}

function toggleScenarioSelect(cfgPath, checked) {
  if (checked) SELECTED_CONFIGS.add(cfgPath);
  else SELECTED_CONFIGS.delete(cfgPath);
  renderRunnerUI();
}

function applyPreset(name) {
  const presets = {
    "1h_swing": { fileName: "ema_breakout_1h.yaml", timeframe: "1h", maxRangePct: 8.0, volMult: 1.5, slSource: "1h_low", holdingMode: "swing", runnerAtrMult: 0.5 },
    "1d_swing": { fileName: "ema_breakout_1d.yaml", timeframe: "1d", maxRangePct: 10.0, volMult: 1.5, slSource: "1d_low", holdingMode: "swing", runnerAtrMult: 0.75 },
    "tight_base": { fileName: "ema_breakout_tight.yaml", timeframe: "1h", maxRangePct: 5.0, volMult: 2.0, slSource: "1h_low", holdingMode: "swing", runnerAtrMult: 0.5 },
  };
  const p = presets[name];
  if (!p) return;
  const merged = { ...readFormValues(), ...p };
  saveLastForm(merged);
  renderRunnerUI();
}

function loadScenarioIntoForm(cfgPath) {
  const meta = getScenarioMeta(cfgPath);
  const name = cfgPath.split("/").pop();
  const merged = { ...DEFAULT_SCENARIO_FORM, ...meta, fileName: name };
  saveLastForm(merged);
  renderRunnerUI();
  const msg = document.getElementById("scFormMsg");
  if (msg) msg.textContent = `Loaded ${name} into editor.`;
}

function readFormValues() {
  const g = id => (document.getElementById(id) ? document.getElementById(id).value : "");
  return {
    fileName: (g("sc_fileName").trim() || "ema_breakout_custom.yaml").replace(/[^a-zA-Z0-9._-]/g, "_"),
    strategyName: "ema_breakout_v1",
    timeframe: g("sc_timeframe") || "1h",
    emaPeriods: g("sc_emaPeriods") || "9, 21, 50",
    consolidationDays: Number(g("sc_consolidationDays")) || 5,
    maxRangePct: Number(g("sc_maxRangePct")) || 8.0,
    volMult: Number(g("sc_volMult")) || 1.5,
    impulseMult: Number(g("sc_impulseMult")) || 2.0,
    slSource: g("sc_slSource") || "1h_low",
    holdingMode: g("sc_holdingMode") || "swing",
    riskPct: Number(g("sc_riskPct")) || 1.0,
    tranches: g("sc_tranches") || "0.33, 0.33, 0.34",
    addAtR: g("sc_addAtR") || "1.0, 2.0",
    riskNeutralSl: true,
    trailTimeframe: "1h",
    trailEmaInitial: Number(g("sc_trailEmaInitial")) || 21,
    trailEmaRunner: Number(g("sc_trailEmaRunner")) || 9,
    runnerAtrMult: Number(g("sc_runnerAtrMult")) || 0.5,
    notes: g("sc_notes") || "",
  };
}

function buildYamlFromForm(f) {
  const emas = f.emaPeriods.split(",").map(x => Number(x.trim())).filter(Boolean);
  const tr = f.tranches.split(",").map(x => Number(x.trim())).filter(x => !Number.isNaN(x));
  const ar = f.addAtR.split(",").map(x => Number(x.trim())).filter(x => !Number.isNaN(x));
  return `extends: default.yaml

strategy:
  name: ${f.strategyName}
  params:
    timeframe: "${f.timeframe}"
    ema_periods: [${emas.join(", ")}]
    consolidation_min_days: ${f.consolidationDays}
    consolidation_max_range_pct: ${f.maxRangePct}
    breakout_vol_mult: ${f.volMult}
    vol_avg_bars: 20
    max_wait_bars_5m: 36
    double_bottom: true
    flag_wedge: true
    impulse_2x: true
    impulse_pct_mult: ${f.impulseMult}
    sl_source: "${f.slSource}"
    holding_mode: "${f.holdingMode}"
    risk_per_trade_pct: ${f.riskPct}
    tranches: [${tr.join(", ")}]
    add_at_r: [${ar.join(", ")}]
    use_risk_neutral_sl: true
    trail_timeframe: "${f.trailTimeframe}"
    trail_ema_initial: ${f.trailEmaInitial}
    trail_ema_runner: ${f.trailEmaRunner}
    runner_atr_period: 14
    runner_atr_mult: ${f.runnerAtrMult}
`;
}

function copyScenarioYaml() {
  const f = readFormValues();
  saveLastForm(f);
  const yamlTxt = buildYamlFromForm(f);
  if (navigator.clipboard) navigator.clipboard.writeText(yamlTxt);
  const msg = document.getElementById("scFormMsg");
  if (msg) msg.textContent = "YAML copied to clipboard & form saved.";
}

async function saveScenarioFromForm(andRun) {
  const f = readFormValues();
  if (!f.fileName.endsWith(".yaml")) f.fileName += ".yaml";
  const cfgPath = "config/" + f.fileName;
  saveLastForm(f);
  SAVED_SCENARIOS[cfgPath] = f;
  savePersistedScenarios();

  const msg = document.getElementById("scFormMsg");
  const yamlTxt = buildYamlFromForm(f);

  try {
    const resp = await fetch("/api/save_config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: f.fileName, content: yamlTxt }),
    });
    if (resp.ok) {
      if (!AVAILABLE_CONFIGS.includes(cfgPath)) AVAILABLE_CONFIGS.push(cfgPath);
      SELECTED_CONFIGS.add(cfgPath);
      renderRunnerUI();
      const msg2 = document.getElementById("scFormMsg");
      if (msg2) msg2.textContent = `Saved ${cfgPath} to disk & browser.`;
      if (andRun) await runSingleScenario(cfgPath);
      return;
    }
  } catch {
    // Fallback if /api/save_config isn't added yet
  }

  if (msg) msg.textContent = `Saved settings in browser. Add /api/save_config in app.py or click Copy YAML to save ${cfgPath}.`;
}

async function runSingleScenario(cfgPath) {
  SELECTED_CONFIGS = new Set([cfgPath]);
  renderRunnerUI();
  await runBatchNow();
}

async function refreshRuns() {
  try {
    const data = await (await fetch("/api/runs")).json();
    const runs = data.runs || [];
    const sel = document.getElementById("runSelect");
    if (sel) {
      sel.innerHTML = runs
        .map((r, i) => `<option value="${r}">${r}${i === 0 ? " (latest)" : ""}</option>`)
        .join("");
    }
    if (runs.length) {
      await loadRun(runs[0]);
    } else {
      STRATEGIES = [];
      BENCH = { dates: [], closes: [] };
      state = [];
      renderControls();
      recalc();
    }
  } catch (err) {
    console.error("Failed to refresh runs:", err);
  }
}

async function runBatchNow() {
  const configs = [...SELECTED_CONFIGS];
  const progWrap = document.getElementById("rnProgressWrap");
  const progBar = document.getElementById("rnProgressBar");
  const msgEl = document.getElementById("runStatusMsg");
  const elapEl = document.getElementById("rnElapsed");

  if (!configs.length) {
    if (progWrap) progWrap.classList.add("active");
    if (msgEl) msgEl.textContent = "Please select at least one scenario card.";
    return;
  }

  if (progWrap) progWrap.classList.add("active");
  if (progBar) progBar.style.width = "12%";
  if (msgEl) msgEl.textContent = `Starting ${configs.length} scenario(s)...`;
  runnerStartMs = Date.now();
  if (runnerTimer) clearInterval(runnerTimer);

  try {
    const res = await (
      await fetch("/api/run_batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ configs }),
      })
    ).json();

    if (!res.ok) {
      if (msgEl) msgEl.textContent = res.error || "Batch run failed to start.";
      if (progBar) progBar.style.width = "0%";
      return;
    }

    let pct = 18;
    runnerTimer = setInterval(async () => {
      try {
        const secs = Math.round((Date.now() - runnerStartMs) / 1000);
        if (elapEl) elapEl.textContent = `${secs}s`;
        const st = await (await fetch("/api/status")).json();
        pct = st.progress != null ? st.progress : Math.min(92, pct + 4);
        if (progBar) progBar.style.width = `${st.running ? pct : 100}%`;
        if (msgEl) {
          msgEl.textContent = st.last_error ? "Error: " + st.last_error : (st.message || "Running...");
        }
        if (!st.running) {
          clearInterval(runnerTimer);
          runnerTimer = null;
          await refreshRuns();
          const autoOpen = document.getElementById("autoOpenSim");
          if (!st.last_error && autoOpen && autoOpen.checked) {
            const simBtn = document.querySelector(".tab");
            showTab("sim", simBtn);
          }
        }
      } catch (err) {
        clearInterval(runnerTimer);
        runnerTimer = null;
        if (msgEl) msgEl.textContent = "Status check failed: " + err.message;
      }
    }, 800);
  } catch (err) {
    if (msgEl) msgEl.textContent = "Request failed: " + err.message;
  }
}

async function loadRun(runId) {
  if (!runId) return;
  try {
    const run = await (await fetch("/api/run/" + encodeURIComponent(runId))).json();
    STRATEGIES = run.strategies || [];
    BENCH = run.bench || { dates: [], closes: [] };
    const capEl = document.getElementById("capInput");
    if (capEl) capEl.value = Math.round(run.initial_capital || 1000000);
    state = STRATEGIES.map(() => ({
      active: true,
      weight: STRATEGIES.length ? Math.round((100 / STRATEGIES.length) * 10) / 10 : 0,
    }));
    renderControls();
    recalc();
  } catch (err) {
    console.error("Failed to load run:", err);
  }
}

function renderControls() {
  const tb = document.getElementById("stratRows");
  if (!tb) return;
  tb.innerHTML = STRATEGIES.map((s, i) => `<tr>
    <td><input type="checkbox" ${state[i].active ? "checked" : ""} onchange="state[${i}].active=this.checked;renderControls();recalc()"></td>
    <td class="left"><b>${s.name}</b></td>
    <td>
      <input type="range" min="0" max="100" value="${state[i].weight}" ${state[i].active ? "" : "disabled"} oninput="state[${i}].weight=parseFloat(this.value)||0;this.nextElementSibling.textContent=state[${i}].weight.toFixed(1)+'%';recalc()">
      <span>${state[i].weight.toFixed(1)}%</span>
    </td>
    <td id="alloc_${i}">-</td>
    <td>${(s.trades || []).length}</td>
    <td id="cpnl_${i}">-</td>
    <td id="cpct_${i}">-</td>
  </tr>`).join("");
}

function equalWeight() {
  const n = state.filter(x => x.active).length;
  if (!n) return;
  const w = Math.round((100 / n) * 10) / 10;
  state.forEach(x => { if (x.active) x.weight = w; });
  renderControls();
  recalc();
}

function normalizeWeights() {
  const t = state.reduce((a, x) => a + (x.active ? x.weight : 0), 0);
  if (t <= 0) return equalWeight();
  state.forEach(x => { if (x.active) x.weight = Math.round((x.weight / t * 100) * 10) / 10; });
  renderControls();
  recalc();
}

function recalc() {
  const capEl = document.getElementById("capInput");
  const cap = parseFloat(capEl ? capEl.value : "1000000") || 1000000;
  const totW = state.reduce((a, x) => a + (x.active ? x.weight : 0), 0);
  const allocEl = document.getElementById("allocSummary");
  if (allocEl) {
    allocEl.textContent = `Allocated: ${totW.toFixed(1)}% | Cash: ${Math.max(0, 100 - totW).toFixed(1)}%`;
  }

  const dates = STRATEGIES.length ? (STRATEGIES[0].dates || []) : [];
  const nDays = STRATEGIES.length ? (STRATEGIES[0].daily_returns || []).length : 0;
  const eq = [cap];
  const rets = [];
  for (let t = 1; t < nDays; t++) {
    let r = 0;
    STRATEGIES.forEach((s, i) => {
      if (state[i] && state[i].active && t < (s.daily_returns || []).length) {
        r += (state[i].weight / 100) * s.daily_returns[t];
      }
    });
    rets.push(r);
    eq.push(eq[eq.length - 1] * (1 + r));
  }

  const portPct = eq.map(v => (cap > 0 ? (v / cap - 1) * 100 : 0));
  const benchPct =
    BENCH.closes && BENCH.closes.length === eq.length && BENCH.closes[0] > 0
      ? BENCH.closes.map(c => (c / BENCH.closes[0] - 1) * 100)
      : [];

  let pk = eq[0];
  let maxDd = 0;
  const dd = eq.map(v => {
    if (v > pk) pk = v;
    const d = pk > 0 ? ((v - pk) / pk) * 100 : 0;
    if (d < maxDd) maxDd = d;
    return d;
  });

  drawPctChart(portPct, dd, dates, benchPct);

  activeTrades = [];
  let totPnl = 0;
  const contribs = STRATEGIES.map((s, i) => {
    if (!state[i] || !state[i].active || state[i].weight <= 0) return 0;
    const alloc = cap * (state[i].weight / 100);
    const scale = s.base_capital > 0 ? alloc / s.base_capital : 1;
    let c = 0;
    (s.trades || []).forEach(tr => {
      const p = (tr.net_pnl || 0) * scale;
      c += p;
      activeTrades.push({
        ...tr,
        strategy: s.name,
        uid: s.name + "_" + tr.trade_id,
        scaled_pnl: p,
      });
    });
    totPnl += c;
    return c;
  });

  STRATEGIES.forEach((s, i) => {
    const allocCell = document.getElementById("alloc_" + i);
    const pnlCell = document.getElementById("cpnl_" + i);
    const pctCell = document.getElementById("cpct_" + i);
    if (allocCell) allocCell.textContent = Math.round(state[i].active ? cap * (state[i].weight / 100) : 0).toLocaleString();
    if (pnlCell) pnlCell.textContent = Math.round(contribs[i]).toLocaleString();
    if (pctCell) pctCell.textContent = (totPnl ? (contribs[i] / Math.abs(totPnl)) * 100 : 0).toFixed(1) + "%";
  });

  const wins = activeTrades.filter(t => t.scaled_pnl > 0);
  const gp = wins.reduce((a, t) => a + t.scaled_pnl, 0);
  const gl = activeTrades.filter(t => t.scaled_pnl <= 0).reduce((a, t) => a + t.scaled_pnl, 0);
  const meanR = rets.length ? rets.reduce((a, b) => a + b, 0) / rets.length : 0;
  const stdR = rets.length > 1
    ? Math.sqrt(rets.reduce((a, b) => a + (b - meanR) ** 2, 0) / (rets.length - 1))
    : 0;

  const kpis = [
    ["Final Equity", "INR " + Math.round(eq[eq.length - 1]).toLocaleString()],
    ["Portfolio Return", (portPct[portPct.length - 1] || 0).toFixed(2) + "%"],
    ["Nifty 50 Return", (benchPct[benchPct.length - 1] || 0).toFixed(2) + "%"],
    ["Max Drawdown", maxDd.toFixed(2) + "%"],
    ["Sharpe", (stdR > 0 ? (meanR / stdR) * Math.sqrt(252) : 0).toFixed(2)],
    ["Trades", activeTrades.length],
    ["Win Rate", (activeTrades.length ? (wins.length / activeTrades.length) * 100 : 0).toFixed(1) + "%"],
    ["Profit Factor", (gl < 0 ? gp / Math.abs(gl) : (gp > 0 ? 999 : 0)).toFixed(2)],
  ];

  const kpiGrid = document.getElementById("kpiGrid");
  if (kpiGrid) {
    kpiGrid.innerHTML = kpis
      .map(([l, v]) => `<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`)
      .join("");
  }

  populateFilters();
  applyFilters();
}

function drawPctChart(portPct, dd, dates, benchPct) {
  const eSvg = document.getElementById("eqSvg");
  const dSvg = document.getElementById("ddSvg");
  if (!eSvg || !dSvg) return;

  if (!portPct.length) {
    eSvg.innerHTML = "";
    dSvg.innerHTML = "";
    return;
  }

  const showBenchEl = document.getElementById("showBench");
  const showB = !!(showBenchEl && showBenchEl.checked && benchPct.length === portPct.length);
  const W = 1100, H = 320, P = 56, R = 20;
  const all = showB ? portPct.concat(benchPct, [0]) : portPct.concat([0]);
  let ymin = Math.min(...all);
  let ymax = Math.max(...all);
  if (ymax === ymin) {
    ymax += 1;
    ymin -= 1;
  }

  const mx = i => P + (W - P - R) * (i / Math.max(1, portPct.length - 1));
  const my = v => (H - 30) - (H - 50) * ((v - ymin) / (ymax - ymin));

  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = ymin + (ymax - ymin) * (k / 4);
    const y = my(v);
    g += `<line x1="${P}" y1="${y}" x2="${W - R}" y2="${y}" stroke="#e2e8f0" stroke-dasharray="3,3"/>`;
    g += `<text x="${P - 6}" y="${y + 4}" font-size="11" text-anchor="end" fill="#64748b">${v.toFixed(1)}%</text>`;
  }

  const y0 = my(0);
  g += `<line x1="${P}" y1="${y0}" x2="${W - R}" y2="${y0}" stroke="#94a3b8" stroke-width="1"/>`;
  const pEq = portPct.map((v, i) => `${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ");
  const pB = showB
    ? `<polyline fill="none" stroke="#64748b" stroke-width="1.6" stroke-dasharray="5,4" points="${benchPct.map((v, i) => `${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ")}"/>`
    : "";

  eSvg.innerHTML = `${g}${pB}<polyline fill="none" stroke="#2563eb" stroke-width="2.4" points="${pEq}"/>
    <text x="${P}" y="${H - 8}" font-size="11" fill="#64748b">${dates[0] || ""}</text>
    <text x="${W - R}" y="${H - 8}" font-size="11" text-anchor="end" fill="#64748b">${dates[dates.length - 1] || ""}</text>`;

  const Hd = 240;
  const dmin = Math.min(...dd, -0.5);
  const myd = v => 20 + (Hd - 50) * (v / dmin);
  const dPts = dd.map((v, i) => `${mx(i).toFixed(1)},${myd(v).toFixed(1)}`).join(" ");
  dSvg.innerHTML = `<polygon fill="rgba(220,38,38,0.14)" points="${P},${myd(0)} ${dPts} ${W - R},${myd(0)}"/>
    <polyline fill="none" stroke="#dc2626" stroke-width="2" points="${dPts}"/>
    <text x="${P - 6}" y="${myd(dmin) + 4}" font-size="11" text-anchor="end" fill="#64748b">${dmin.toFixed(1)}%</text>`;

  const eqOv = document.createElementNS("http://www.w3.org/2000/svg", "g");
  const ddOv = document.createElementNS("http://www.w3.org/2000/svg", "g");
  eSvg.appendChild(eqOv);
  dSvg.appendChild(ddOv);

  const renderSyncHover = idx => {
    if (idx < 0 || idx >= portPct.length) {
      eqOv.innerHTML = "";
      ddOv.innerHTML = "";
      return;
    }
    const x = mx(idx);
    const pv = portPct[idx];
    const py = my(pv);
    const dt = dates[idx] || "";
    const bv = showB ? benchPct[idx] : null;
    const alpha = bv != null ? pv - bv : null;

    const tipW = showB ? 215 : 155;
    const tipH = showB ? 54 : 38;
    const tx = Math.min(W - R - tipW - 6, Math.max(P + 6, x + 12));
    const ty = Math.max(12, Math.min(H - tipH - 34, py - tipH / 2));

    let eh = `<line x1="${x}" y1="10" x2="${x}" y2="${H - 26}" stroke="#475569" stroke-width="1" stroke-dasharray="3,3"/>`;
    eh += `<circle cx="${x}" cy="${py}" r="4" fill="#2563eb" stroke="#fff" stroke-width="1.5"/>`;
    if (showB) {
      eh += `<circle cx="${x}" cy="${my(bv)}" r="3.5" fill="#64748b" stroke="#fff" stroke-width="1.2"/>`;
    }
    eh += `<rect x="${tx}" y="${ty}" width="${tipW}" height="${tipH}" rx="5" fill="#0f172a" opacity="0.92"/>`;
    eh += `<text x="${tx + 8}" y="${ty + 15}" font-size="10.5" font-weight="700" fill="#e2e8f0">${dt}</text>`;
    eh += `<text x="${tx + 8}" y="${ty + 30}" font-size="11" font-weight="700" fill="#60a5fa">Portfolio: ${pv >= 0 ? "+" : ""}${pv.toFixed(2)}%</text>`;
    if (showB) {
      const aCol = alpha >= 0 ? "#4ade80" : "#f87171";
      eh += `<text x="${tx + 8}" y="${ty + 45}" font-size="10.5" fill="#cbd5e1">Nifty: ${bv >= 0 ? "+" : ""}${bv.toFixed(2)}% | <tspan fill="${aCol}" font-weight="700">${alpha >= 0 ? "+" : ""}${alpha.toFixed(2)}%</tspan></text>`;
    }
    eqOv.innerHTML = eh;

    const dv = dd[idx];
    const dy = myd(dv);
    let dh = `<line x1="${x}" y1="12" x2="${x}" y2="${Hd - 24}" stroke="#475569" stroke-width="1" stroke-dasharray="3,3"/>`;
    dh += `<circle cx="${x}" cy="${dy}" r="4" fill="#dc2626" stroke="#fff" stroke-width="1.5"/>`;
    const dtx = Math.min(W - R - 150, Math.max(P + 6, x + 12));
    dh += `<rect x="${dtx}" y="12" width="144" height="34" rx="5" fill="#0f172a" opacity="0.92"/>`;
    dh += `<text x="${dtx + 8}" y="26" font-size="10" fill="#cbd5e1">${dt}</text>`;
    dh += `<text x="${dtx + 8}" y="40" font-size="11" font-weight="700" fill="#f87171">DD: ${dv.toFixed(2)}%</text>`;
    ddOv.innerHTML = dh;
  };

  const idxFromEvent = (svgEl, evt) => {
    const rect = svgEl.getBoundingClientRect();
    const sx = (evt.clientX - rect.left) * (W / Math.max(1, rect.width));
    const t = (sx - P) / Math.max(1, W - P - R);
    return Math.max(0, Math.min(portPct.length - 1, Math.round(t * (portPct.length - 1))));
  };

  eSvg.style.cursor = "crosshair";
  dSvg.style.cursor = "crosshair";
  eSvg.onmousemove = evt => renderSyncHover(idxFromEvent(eSvg, evt));
  dSvg.onmousemove = evt => renderSyncHover(idxFromEvent(dSvg, evt));
  eSvg.onmouseleave = () => renderSyncHover(-1);
  dSvg.onmouseleave = () => renderSyncHover(-1);
}

function populateFilters() {
  const fill = (id, vals) => {
    const s = document.getElementById(id);
    if (!s) return;
    const c = s.value;
    s.innerHTML = '<option value="">All</option>' + [...new Set(vals.filter(Boolean))].sort().map(v => `<option value="${v}">${v}</option>`).join("");
    s.value = c;
  };
  fill("fStrat", activeTrades.map(t => t.strategy));
  fill("fSym", activeTrades.map(t => t.symbol));
  fill("fReg", activeTrades.map(t => t.regime_at_entry));
  fill("fExit", activeTrades.map(t => t.exit_reason));
}

function clearFilters() {
  ["fStrat", "fSym", "fOut", "fReg", "fExit", "fFrom", "fTo"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  applyFilters();
}

function sortBy(col) {
  if (sortCol === col) sortAsc = !sortAsc;
  else {
    sortCol = col;
    sortAsc = true;
  }
  applyFilters();
}

function applyFilters() {
  const val = id => {
    const el = document.getElementById(id);
    return el ? el.value : "";
  };
  const fs = val("fStrat");
  const fym = val("fSym");
  const fo = val("fOut");
  const fr = val("fReg");
  const fx = val("fExit");
  const ff = val("fFrom");
  const ft = val("fTo");

  const list = activeTrades.filter(t => {
    const d = (t.entry_ts || "").slice(0, 10);
    return (
      (!fs || t.strategy === fs) &&
      (!fym || t.symbol === fym) &&
      (!fo || (fo === "win" ? t.scaled_pnl > 0 : t.scaled_pnl <= 0)) &&
      (!fr || t.regime_at_entry === fr) &&
      (!fx || t.exit_reason === fx) &&
      (!ff || d >= ff) &&
      (!ft || d <= ft)
    );
  });

  list.sort((a, b) => {
    const va = a[sortCol];
    const vb = b[sortCol];
    if (typeof va === "string" || typeof vb === "string") {
      const sa = String(va ?? "");
      const sb = String(vb ?? "");
      return sortAsc ? sa.localeCompare(sb) : sb.localeCompare(sa);
    }
    const na = Number(va ?? 0);
    const nb = Number(vb ?? 0);
    return sortAsc ? na - nb : nb - na;
  });

  const pnl = list.reduce((a, t) => a + t.scaled_pnl, 0);
  const w = list.filter(t => t.scaled_pnl > 0).length;
  const bar = document.getElementById("filteredBar");
  if (bar) {
    bar.innerHTML = `<b>Showing:</b> ${list.length}/${activeTrades.length} | <b>Win Rate:</b> ${(list.length ? (w / list.length) * 100 : 0).toFixed(1)}% | <b>Net P&amp;L:</b> INR ${Math.round(pnl).toLocaleString()}`;
  }

  const rowsEl = document.getElementById("tradeRows");
  if (rowsEl) {
    rowsEl.innerHTML = list.map(t => `<tr>
      <td class="left"><span class="trade-link" onclick="openTrade('${t.uid}')">#${t.trade_id}</span></td>
      <td class="left">${t.strategy}</td>
      <td class="left"><b>${t.symbol}</b></td>
      <td class="left">${(t.entry_ts || "").slice(0, 16).replace("T", " ")}</td>
      <td class="left">${(t.exit_ts || "").slice(0, 16).replace("T", " ")}</td>
      <td>${Number(t.avg_entry || 0).toFixed(2)}</td>
      <td>${Number(t.avg_exit || 0).toFixed(2)}</td>
      <td>${Number(t.initial_stop || 0).toFixed(2)}</td>
      <td class="${t.scaled_pnl >= 0 ? "pos" : "neg"}"><b>${Math.round(t.scaled_pnl).toLocaleString()}</b></td>
      <td class="${Number(t.money_r || 0) >= 0 ? "pos" : "neg"}">${Number(t.money_r || 0).toFixed(2)}R</td>
      <td class="left">${t.exit_reason || ""}</td>
    </tr>`).join("");
  }
}

function openTrade(uid) {
  currentTrade = activeTrades.find(x => x.uid === uid);
  if (!currentTrade) return;

  const titleEl = document.getElementById("modalTitle");
  if (titleEl) {
    titleEl.textContent = `${currentTrade.symbol} — Trade #${currentTrade.trade_id} (${currentTrade.strategy})`;
  }

  const subEl = document.getElementById("modalSub");
  if (subEl) {
    subEl.innerHTML =
      `Entry: <b>${Number(currentTrade.avg_entry || 0).toFixed(2)}</b> (${(currentTrade.entry_ts || "").slice(0, 16).replace("T", " ")}) | ` +
      `Exit: <b>${Number(currentTrade.avg_exit || 0).toFixed(2)}</b> (${(currentTrade.exit_ts || "").slice(0, 16).replace("T", " ")}) | ` +
      `Stop: <b style="color:#dc2626">${Number(currentTrade.initial_stop || 0).toFixed(2)}</b> | ` +
      `P&amp;L: <b class="${currentTrade.scaled_pnl >= 0 ? "pos" : "neg"}">INR ${Math.round(currentTrade.scaled_pnl).toLocaleString()} (${Number(currentTrade.money_r || 0).toFixed(2)}R)</b>` +
      ` &nbsp;<span style="color:#64748b;font-size:11.5px;">(Scroll: Zoom | Drag: Pan | Click 2 pts: Measure % | DblClick: Reset)</span>`;
  }

  const modal = document.getElementById("tradeModal");
  if (modal) modal.classList.add("open");
  fetchTradeChart();
}

function closeModal() {
  const modal = document.getElementById("tradeModal");
  if (modal) modal.classList.remove("open");
}

document.addEventListener("keydown", e => {
  const modal = document.getElementById("tradeModal");
  const isOpen = modal && modal.classList.contains("open");
  if (e.key === "Escape") {
    if (anchorA || anchorB) {
      anchorA = null;
      anchorB = null;
      redrawActiveTrade();
    } else {
      closeModal();
    }
    return;
  }
  if (!isOpen || !cachedCandles.length) return;
  const span = viewEnd - viewStart + 1;
  const step = Math.max(1, Math.round(span * 0.15));
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    panCandles(-step);
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    panCandles(step);
  } else if (e.key === "+" || e.key === "=") {
    e.preventDefault();
    zoomCandles(0.8, 0.5);
  } else if (e.key === "-") {
    e.preventDefault();
    zoomCandles(1.25, 0.5);
  } else if (e.key === "0") {
    e.preventDefault();
    resetCandleView();
  }
});

function setTf(tf, btn) {
  currentTf = tf;
  document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  fetchTradeChart();
}

function redrawActiveTrade() {
  if (currentTrade) drawCandles(cachedCandles, cachedPatternShapes);
}

function resetCandleView() {
  viewStart = 0;
  viewEnd = Math.max(0, cachedCandles.length - 1);
  redrawActiveTrade();
}

function panCandles(deltaBars) {
  if (!cachedCandles.length) return;
  const span = viewEnd - viewStart;
  let ns = viewStart + deltaBars;
  let ne = ns + span;
  if (ns < 0) {
    ns = 0;
    ne = span;
  }
  if (ne >= cachedCandles.length) {
    ne = cachedCandles.length - 1;
    ns = Math.max(0, ne - span);
  }
  viewStart = ns;
  viewEnd = ne;
  redrawActiveTrade();
}

function zoomCandles(factor, anchorRatio) {
  if (cachedCandles.length <= 10) return;
  const minSpan = Math.min(12, cachedCandles.length);
  const oldSpan = viewEnd - viewStart + 1;
  const newSpan = Math.max(minSpan, Math.min(cachedCandles.length, Math.round(oldSpan * factor)));
  if (newSpan === oldSpan) return;
  const anchorIdx = viewStart + Math.round(oldSpan * anchorRatio);
  let ns = Math.round(anchorIdx - newSpan * anchorRatio);
  let ne = ns + newSpan - 1;
  if (ns < 0) {
    ns = 0;
    ne = newSpan - 1;
  }
  if (ne >= cachedCandles.length) {
    ne = cachedCandles.length - 1;
    ns = Math.max(0, ne - newSpan + 1);
  }
  viewStart = ns;
  viewEnd = ne;
  redrawActiveTrade();
}

async function fetchTradeChart() {
  if (!currentTrade) return;
  const q = new URLSearchParams({
    symbol: currentTrade.symbol,
    tf: currentTf,
    entry: (currentTrade.entry_ts || "").slice(0, 10),
    exit: (currentTrade.exit_ts || "").slice(0, 10),
    pattern: currentTrade.pattern || "none",
  });
  try {
    const data = await (await fetch("/api/candles?" + q)).json();
    cachedCandles = data.candles || [];
    cachedPatternShapes = data.pattern_shapes || {};
    viewStart = 0;
    viewEnd = Math.max(0, cachedCandles.length - 1);
    anchorA = null;
    anchorB = null;
    lastMouse = null;
    drawCandles(cachedCandles, cachedPatternShapes);
  } catch (err) {
    const svg = document.getElementById("candleSvg");
    if (svg) {
      svg.innerHTML = `<text x="550" y="240" text-anchor="middle" fill="#dc2626">Failed to load candles: ${err.message}</text>`;
    }
  }
}

function drawCandles(allBars, pat) {
  const svg = document.getElementById("candleSvg");
  if (!svg) return;
  if (!allBars.length) {
    svg.innerHTML = `<text x="550" y="240" text-anchor="middle" fill="#64748b">No data for timeframe ${currentTf}</text>`;
    return;
  }

  viewStart = Math.max(0, Math.min(allBars.length - 1, viewStart));
  viewEnd = Math.max(viewStart, Math.min(allBars.length - 1, viewEnd || (allBars.length - 1)));
  const bars = allBars.slice(viewStart, viewEnd + 1);

  const togEmas = document.getElementById("togEmas");
  const togVol = document.getElementById("togVol");
  const togPat = document.getElementById("togPat");
  const showE = togEmas ? togEmas.checked : true;
  const showV = togVol ? togVol.checked : true;
  const showP = togPat ? togPat.checked : true;

  const W = 1100, H = 500, P = 64, R = 30, T = 36, B = showV ? 110 : 48;
  const V_TOP = H - 94, V_BOT = H - 40;

  const ev = [];
  if (showE) {
    bars.forEach(b => {
      if (b.ema9 != null) ev.push(b.ema9);
      if (b.ema21 != null) ev.push(b.ema21);
      if (b.ema50 != null) ev.push(b.ema50);
    });
  }

  const stopVal = Number(currentTrade.initial_stop);
  const extra = Number.isFinite(stopVal) && stopVal > 0 ? [stopVal, ...ev] : ev;
  let pmin = Math.min(...bars.map(b => b.l), ...extra);
  let pmax = Math.max(...bars.map(b => b.h), ...extra);
  const pad = (pmax - pmin) * 0.10 || 1;
  pmin -= pad;
  pmax += pad;

  const cw = Math.max(1.5, Math.min(14, ((W - P - R) / bars.length) * 0.7));
  const mx = i => P + (W - P - R) * ((i + 0.5) / bars.length);
  const my = v => T + (H - T - B) * (1 - (v - pmin) / (pmax - pmin));

  let out = "";
  for (let g = 0; g <= 5; g++) {
    const v = pmin + (pmax - pmin) * (g / 5);
    const y = my(v);
    out += `<line x1="${P}" y1="${y}" x2="${W - R}" y2="${y}" stroke="#f1f5f9"/>`;
    out += `<text x="${P - 8}" y="${y + 4}" font-size="11" text-anchor="end" fill="#64748b">${v.toFixed(2)}</text>`;
  }

  if (showP && pat && pat.type === "vcp" && pat.zigzag && pat.zigzag.length) {
    const zpts = pat.zigzag
      .map(z => {
        const idx = bars.findIndex(b => b.t.slice(0, 10) >= z.t.slice(0, 10));
        return idx >= 0 ? `${mx(idx).toFixed(1)},${my(z.p).toFixed(1)}` : null;
      })
      .filter(Boolean);
    if (zpts.length > 1) {
      out += `<polyline fill="none" stroke="#8b5cf6" stroke-width="2" stroke-dasharray="4,2" points="${zpts.join(" ")}"/>`;
    }
    if (pat.pivot != null) {
      out += `<line x1="${P}" y1="${my(pat.pivot)}" x2="${W - R}" y2="${my(pat.pivot)}" stroke="#8b5cf6" stroke-width="1.2" stroke-dasharray="5,3"/>`;
    }
  } else if (showP && pat && pat.type === "flat_base" && pat.t0 && pat.t1) {
    const i0 = Math.max(0, bars.findIndex(b => b.t.slice(0, 10) >= pat.t0.slice(0, 10)));
    const i1 = bars.findIndex(b => b.t.slice(0, 10) >= pat.t1.slice(0, 10));
    if (i1 > i0) {
      out += `<rect x="${mx(i0)}" y="${my(pat.high)}" width="${mx(i1) - mx(i0)}" height="${my(pat.low) - my(pat.high)}" fill="rgba(139,92,246,0.10)" stroke="#8b5cf6" stroke-dasharray="4,3"/>`;
    }
  } else if (showP && pat && pat.type === "cup_handle" && pat.cup && pat.cup.length >= 3) {
    const cpts = pat.cup
      .map(pt => {
        const idx = bars.findIndex(b => b.t.slice(0, 10) >= pt.t.slice(0, 10));
        return idx >= 0 ? `${mx(idx).toFixed(1)},${my(pt.p).toFixed(1)}` : null;
      })
      .filter(Boolean);
    if (cpts.length >= 2) {
      out += `<polyline fill="none" stroke="#8b5cf6" stroke-width="2" stroke-dasharray="5,3" points="${cpts.join(" ")}"/>`;
    }
  }

  if (showE) {
    [["ema9", "#8b5cf6"], ["ema21", "#f59e0b"], ["ema50", "#0d9488"]].forEach(([k, col]) => {
      const pts = bars.map((b, i) => (b[k] != null ? `${mx(i).toFixed(1)},${my(b[k]).toFixed(1)}` : null)).filter(Boolean);
      if (pts.length > 1) {
        out += `<polyline fill="none" stroke="${col}" stroke-width="1.6" points="${pts.join(" ")}"/>`;
      }
    });
  }

  if (showV) {
    const vmax = Math.max(...bars.map(b => b.v || 0), 1);
    bars.forEach((b, i) => {
      const vh = ((b.v || 0) / vmax) * (V_BOT - V_TOP - 4);
      const col = b.c >= b.o ? "rgba(22,163,74,0.45)" : "rgba(220,38,38,0.45)";
      out += `<rect x="${mx(i) - cw / 2}" y="${V_BOT - vh}" width="${cw}" height="${vh}" fill="${col}"/>`;
    });
  }

  bars.forEach((b, i) => {
    const x = mx(i);
    const col = b.c >= b.o ? "#16a34a" : "#dc2626";
    const top = Math.min(my(b.o), my(b.c));
    const bh = Math.max(1.5, Math.abs(my(b.o) - my(b.c)));
    out += `<g><line x1="${x}" y1="${my(b.h)}" x2="${x}" y2="${my(b.l)}" stroke="${col}" stroke-width="1.2"/><rect x="${x - cw / 2}" y="${top}" width="${cw}" height="${bh}" fill="${col}"/></g>`;
  });

  if (Number.isFinite(stopVal) && stopVal > 0) {
    const ys = my(stopVal);
    if (ys >= T && ys <= H - B) {
      out += `<line x1="${P}" y1="${ys}" x2="${W - R}" y2="${ys}" stroke="#dc2626" stroke-width="1.4" stroke-dasharray="6,4"/><text x="${W - R - 4}" y="${ys - 5}" font-size="11" font-weight="700" text-anchor="end" fill="#dc2626">STOP ${stopVal.toFixed(2)}</text>`;
    }
  }

  const eKey = (currentTrade.entry_ts || "").slice(0, 16);
  const xKey = (currentTrade.exit_ts || "").slice(0, 16);
  const eIdx = eKey ? bars.findIndex(b => b.t.slice(0, 16) >= eKey) : -1;
  const xIdx = xKey ? bars.findIndex(b => b.t.slice(0, 16) >= xKey) : -1;

  if (eIdx >= 0) {
    const ex = mx(eIdx), ey = my(currentTrade.avg_entry);
    out += `<line x1="${ex}" y1="${T}" x2="${ex}" y2="${H - B}" stroke="#2563eb" stroke-dasharray="2,2"/><polygon points="${ex},${ey + 3} ${ex - 6},${ey + 15} ${ex + 6},${ey + 15}" fill="#2563eb"/><text x="${ex}" y="${ey + 29}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#1d4ed8">ENTRY ${Number(currentTrade.avg_entry || 0).toFixed(2)} (${(currentTrade.entry_ts || "").slice(11, 16)})</text>`;
  }

  if (xIdx >= 0) {
    const xx = mx(xIdx), xy = my(currentTrade.avg_exit);
    out += `<line x1="${xx}" y1="${T}" x2="${xx}" y2="${H - B}" stroke="#d97706" stroke-dasharray="2,2"/><polygon points="${xx},${xy - 3} ${xx - 6},${xy - 15} ${xx + 6},${xy - 15}" fill="#d97706"/><text x="${xx}" y="${xy - 21}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#b45309">EXIT ${Number(currentTrade.avg_exit || 0).toFixed(2)} (${(currentTrade.exit_ts || "").slice(11, 16)})</text>`;
  }

  out += `<text x="${P}" y="${H - 10}" font-size="11" fill="#64748b">${bars[0].t.slice(0, 16).replace("T", " ")}</text><text x="${W - R}" y="${H - 10}" font-size="11" text-anchor="end" fill="#64748b">${bars[bars.length - 1].t.slice(0, 16).replace("T", " ")} (${bars.length}/${allBars.length} bars)</text>`;
  svg.innerHTML = out;

  const overlay = document.createElementNS("http://www.w3.org/2000/svg", "g");
  svg.appendChild(overlay);
  svg.style.cursor = "crosshair";
  svg.style.userSelect = "none";

  const toPt = evt => {
    const rect = svg.getBoundingClientRect();
    const sx = (evt.clientX - rect.left) * (W / Math.max(1, rect.width));
    const sy = (evt.clientY - rect.top) * (H / Math.max(1, rect.height));
    const localIdx = Math.max(0, Math.min(bars.length - 1, Math.round(((sx - P) / Math.max(1, W - P - R)) * bars.length - 0.5)));
    const cy = Math.max(T, Math.min(H - B, sy));
    const price = pmin + (1 - (cy - T) / Math.max(1, H - T - B)) * (pmax - pmin);
    return {
      gIdx: viewStart + localIdx,
      localIdx,
      x: mx(localIdx),
      y: cy,
      price,
      ratioX: Math.max(0, Math.min(1, (sx - P) / Math.max(1, W - P - R))),
    };
  };

  const fmtDur = (t1, t2) => {
    const m = Math.round(Math.abs(new Date(t2) - new Date(t1)) / 60000);
    const d = Math.floor(m / 1440), hh = Math.floor((m % 1440) / 60), mm = m % 60;
    return (d ? d + "d " : "") + (hh ? hh + "h " : "") + mm + "m";
  };

  const drawOverlay = cur => {
    let h = "";
    const hudBar = cur ? bars[cur.localIdx] : bars[bars.length - 1];
    const hudGlobalIdx = cur ? cur.gIdx : viewEnd;
    if (hudBar) {
      const prevBar = hudGlobalIdx > 0 ? allBars[hudGlobalIdx - 1] : null;
      const chg = prevBar && prevBar.c ? ((hudBar.c - prevBar.c) / prevBar.c) * 100 : 0;
      const chgCol = chg >= 0 ? "#16a34a" : "#dc2626";
      const eTxt = showE
        ? ` | <tspan fill="#8b5cf6">E9:${hudBar.ema9 != null ? hudBar.ema9.toFixed(1) : "-"}</tspan> <tspan fill="#f59e0b">E21:${hudBar.ema21 != null ? hudBar.ema21.toFixed(1) : "-"}</tspan> <tspan fill="#0d9488">E50:${hudBar.ema50 != null ? hudBar.ema50.toFixed(1) : "-"}</tspan>`
        : "";
      h += `<text x="${P + 4}" y="18" font-size="11" font-weight="600" fill="#334155">${hudBar.t.slice(0, 16).replace("T", " ")} | O:${Number(hudBar.o).toFixed(2)} H:${Number(hudBar.h).toFixed(2)} L:${Number(hudBar.l).toFixed(2)} C:${Number(hudBar.c).toFixed(2)} <tspan fill="${chgCol}">(${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%)</tspan> V:${Math.round(hudBar.v || 0).toLocaleString()}${eTxt}</text>`;
    }

    const p2 = anchorB || (anchorA ? cur : null);
    if (anchorA && p2) {
      const aLocal = anchorA.gIdx - viewStart;
      const bLocal = p2.gIdx - viewStart;
      const ax = mx(aLocal);
      const ay = my(anchorA.price);
      const bx2 = mx(bLocal);
      const by2 = my(p2.price);
      const x1 = Math.min(ax, bx2), x2 = Math.max(ax, bx2);
      const y1 = Math.min(ay, by2), y2 = Math.max(ay, by2);
      const dp = p2.price - anchorA.price;
      const pct = anchorA.price ? (dp / anchorA.price) * 100 : 0;
      const nBars = Math.abs(p2.gIdx - anchorA.gIdx);
      const tA = allBars[anchorA.gIdx] ? allBars[anchorA.gIdx].t : "";
      const tB = allBars[p2.gIdx] ? allBars[p2.gIdx].t : "";
      const dur = tA && tB ? fmtDur(tA, tB) : "";
      const col = dp >= 0 ? "#16a34a" : "#dc2626";

      h += `<rect x="${x1}" y="${y1}" width="${Math.max(2, x2 - x1)}" height="${Math.max(2, y2 - y1)}" fill="${dp >= 0 ? "rgba(22,163,74,0.12)" : "rgba(220,38,38,0.12)"}" stroke="${col}" stroke-dasharray="3,2"/>`;
      h += `<line x1="${ax}" y1="${ay}" x2="${bx2}" y2="${by2}" stroke="${col}" stroke-width="1.5"/>`;
      const boxX = Math.min(W - 220, Math.max(P, (x1 + x2) / 2 - 105));
      const boxY = Math.max(T + 4, y1 - 36);
      h += `<rect x="${boxX}" y="${boxY}" width="210" height="30" rx="5" fill="#0f172a" opacity="0.92"/>`;
      h += `<text x="${boxX + 105}" y="${boxY + 13}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#fff">${dp >= 0 ? "+" : ""}${dp.toFixed(2)} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)</text>`;
      h += `<text x="${boxX + 105}" y="${boxY + 25}" font-size="10" text-anchor="middle" fill="#cbd5e1">${nBars} bars | ${dur}</text>`;
    }

    if (cur) {
      const b = bars[cur.localIdx];
      h += `<line x1="${cur.x}" y1="${T}" x2="${cur.x}" y2="${H - B}" stroke="#475569" stroke-width="0.9" stroke-dasharray="3,3"/>`;
      h += `<line x1="${P}" y1="${cur.y}" x2="${W - R}" y2="${cur.y}" stroke="#475569" stroke-width="0.9" stroke-dasharray="3,3"/>`;
      h += `<rect x="4" y="${cur.y - 9}" width="56" height="18" rx="3" fill="#0f172a"/><text x="32" y="${cur.y + 4}" font-size="10" text-anchor="middle" fill="#fff">${cur.price.toFixed(2)}</text>`;
      const lx = Math.min(W - 120, Math.max(P, cur.x - 55));
      h += `<rect x="${lx}" y="${H - B + 2}" width="110" height="16" rx="3" fill="#0f172a"/><text x="${lx + 55}" y="${H - B + 13}" font-size="9.5" text-anchor="middle" fill="#fff">${b.t.slice(5, 16).replace("T", " ")}</text>`;
    }
    overlay.innerHTML = h;
  };

  drawOverlay(lastMouse);

  let dragStartX = null;
  let dragStartView = 0;
  let didDrag = false;

  svg.onmousedown = evt => {
    if (evt.button !== 0) return;
    dragStartX = evt.clientX;
    dragStartView = viewStart;
    didDrag = false;
    svg.style.cursor = "grabbing";
  };

  svg.onmousemove = evt => {
    if (dragStartX !== null) {
      const dx = evt.clientX - dragStartX;
      if (Math.abs(dx) > 4) {
        didDrag = true;
        const rect = svg.getBoundingClientRect();
        const plotW = Math.max(1, rect.width * ((W - P - R) / W));
        const span = viewEnd - viewStart + 1;
        const barShift = Math.round((-dx / plotW) * span);
        let ns = dragStartView + barShift;
        let ne = ns + (span - 1);
        if (ns < 0) {
          ns = 0;
          ne = span - 1;
        }
        if (ne >= allBars.length) {
          ne = allBars.length - 1;
          ns = Math.max(0, ne - span + 1);
        }
        if (ns !== viewStart || ne !== viewEnd) {
          viewStart = ns;
          viewEnd = ne;
          drawCandles(allBars, pat);
          return;
        }
      }
    }
    lastMouse = toPt(evt);
    drawOverlay(lastMouse);
  };

  svg.onmouseup = evt => {
    svg.style.cursor = "crosshair";
    if (dragStartX !== null && !didDrag) {
      const pt = toPt(evt);
      if (!anchorA || (anchorA && anchorB)) {
        anchorA = pt;
        anchorB = null;
      } else {
        anchorB = pt;
      }
      drawOverlay(pt);
    }
    dragStartX = null;
  };

  svg.onmouseleave = () => {
    dragStartX = null;
    svg.style.cursor = "crosshair";
    lastMouse = null;
    drawOverlay(null);
  };

  svg.oncontextmenu = evt => {
    if (anchorA || anchorB) {
      evt.preventDefault();
      anchorA = null;
      anchorB = null;
      drawOverlay(lastMouse);
    }
  };

  svg.ondblclick = () => resetCandleView();

  svg.onwheel = evt => {
    evt.preventDefault();
    const pt = toPt(evt);
    const factor = evt.deltaY < 0 ? 0.82 : 1.22;
    zoomCandles(factor, pt.ratioX);
  };
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}