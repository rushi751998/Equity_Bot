let STRATEGIES = [];
let BENCH = { dates: [], closes: [] };
let STOCK_BENCH = {};
let SELECTED_BENCHMARKS = new Set(["NIFTY_50"]);
const BENCH_COLORS = ["#94a3b8", "#f59e0b", "#10b981", "#ec4899", "#8b5cf6", "#06b6d4", "#f97316", "#84cc16"];
let calloutOffsets = {};
let replayTimer = null;
let replayLimitIdx = null;
let replaySpeed = 1.0;
let state = [];
let activeTrades = [];
let sortCol = "entry_ts";
let sortAsc = false;
let currentTrade = null;
let currentTf = "5m";
let cachedCandles = [];
let cachedPatternShapes = {};
let chartExtraDaysBefore = 0;
let chartExtraDaysAfter = 0;
let chartMaximized = false;
let EMA_COLORS = (() => {
  try {
    return JSON.parse(localStorage.getItem("tfalgo_ema_colors_v1") || "null") || { ema9: "#8b5cf6", ema21: "#f59e0b", ema50: "#0d9488" };
  } catch {
    return { ema9: "#8b5cf6", ema21: "#f59e0b", ema50: "#0d9488" };
  }
})();

// TradingView-style chart viewport & measurement state
let viewStart = 0;
let viewEnd = 0;
let anchorA = null;
let anchorB = null;
let lastMouse = null;

// Unified Sessions, Tickers, Theme & Progress state
const STORAGE_KEY_SCENARIOS = "tfalgo_saved_scenarios_v1";
const STORAGE_KEY_LAST_FORM = "tfalgo_last_scenario_form_v1";
const STORAGE_KEY_SESSIONS = "tfalgo_sessions_v1";
const STORAGE_KEY_ACTIVE_SESSION = "tfalgo_active_session_v1";
const STORAGE_KEY_THEME = "tfalgo_theme_v1";

let AVAILABLE_CONFIGS = [];
let AVAILABLE_SYMBOLS = [];
let AVAILABLE_RUNS = new Set();
let SAVED_SCENARIOS = {};
let SESSIONS = {};
let ACTIVE_SESSION = "Session_1";
let DARK_MODE = false;
let SELECTED_CONFIGS = new Set();
let SELECTED_SYMBOLS = new Set();
let LOG_HIDDEN = false;
let runnerTimer = null;
let runnerStartMs = 0;

const MACRO_PATTERNS = [
  ["ema_breakout", "EMA Breakout"],
  ["cup_handle", "Cup & Handle"],
  ["inv_head_shoulders", "Inv H&S"],
  ["head_shoulders", "Head & Shoulders"],
  ["double_bottom", "Double Bottom"],
  ["double_top", "Double Top"],
  ["triple_bottom", "Triple Bottom"],
  ["triple_top", "Triple Top"],
  ["vcp", "VCP"],
  ["flat_base", "Flat Base"],
];
const CANDLE_TRIGGERS = [
  ["doji", "Doji"],
  ["hammer", "Hammer"],
  ["shooting_star", "Shooting Star"],
  ["engulfing", "Engulfing"],
  ["flag_wedge", "Flag / Wedge"],
  ["impulse_2x", "2x Impulse"],
];

const DEFAULT_SCENARIO_FORM = {
  fileName: "dynamic_edge_v1.yaml",
  strategyName: "dynamic_v1",
  direction: "LONG",
  patternTf: "1h",
  triggerTf: "5m",
  patterns: ["ema_breakout", "cup_handle", "double_bottom", "vcp"],
  candleTriggers: ["hammer", "engulfing", "impulse_2x", "flag_wedge"],
  useRsi: true,
  rsiMin: 50,
  rsiMax: 80,
  useRs: true,
  minPassScore: 70,
  qtyMinMult: 0.5,
  qtyMaxMult: 1.5,
  maxWaitBars: 36,
  retraceMin: 15,
  retraceMax: 65,
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

function loadPersistedState() {
  try {
    SAVED_SCENARIOS = JSON.parse(localStorage.getItem(STORAGE_KEY_SCENARIOS) || "{}") || {};
    SESSIONS = JSON.parse(localStorage.getItem(STORAGE_KEY_SESSIONS) || "{}") || {};
    ACTIVE_SESSION = localStorage.getItem(STORAGE_KEY_ACTIVE_SESSION) || "Session_1";
    DARK_MODE = localStorage.getItem(STORAGE_KEY_THEME) === "dark";
  } catch {
    SAVED_SCENARIOS = {};
    SESSIONS = {};
    ACTIVE_SESSION = "Session_1";
    DARK_MODE = false;
  }
  if (!SESSIONS[ACTIVE_SESSION]) {
    SESSIONS[ACTIVE_SESSION] = {
      name: ACTIVE_SESSION,
      configSig: null,
      completedSymbolsByConfig: {},
      logs: [],
    };
  }
}

function savePersistedState() {
  try {
    localStorage.setItem(STORAGE_KEY_SCENARIOS, JSON.stringify(SAVED_SCENARIOS));
    localStorage.setItem(STORAGE_KEY_SESSIONS, JSON.stringify(SESSIONS));
    localStorage.setItem(STORAGE_KEY_ACTIVE_SESSION, ACTIVE_SESSION);
    localStorage.setItem(STORAGE_KEY_THEME, DARK_MODE ? "dark" : "light");
  } catch (e) {
    console.warn("Storage warning:", e);
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
  } catch {}
}

function applyTheme() {
  document.documentElement.classList.toggle("tf-dark", DARK_MODE);
  const btn = document.getElementById("tfThemeToggleBtn");
  if (btn) btn.textContent = DARK_MODE ? "☀️ Light Mode" : "🌙 Dark Mode";
}

function toggleDarkMode() {
  DARK_MODE = !DARK_MODE;
  savePersistedState();
  applyTheme();
  recalc();
  redrawActiveTrade();
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

  loadPersistedState();
  injectRunnerStyles();
  setupHeaderSessionAndTheme();
  applyTheme();

  try {
    const [cfgRes, symRes] = await Promise.all([
      fetch("/api/configs").then(r => r.json()).catch(() => ({ configs: [] })),
      fetch("/api/symbols").then(r => r.json()).catch(() => ({ symbols: [] })),
    ]);
    AVAILABLE_CONFIGS = cfgRes.configs || [];
    AVAILABLE_SYMBOLS = (symRes.symbols || []).filter(s => !String(s).startsWith("idx:"));
    AVAILABLE_CONFIGS.forEach((c, idx) => {
      if (idx === 0 || c.includes("ema_breakout")) SELECTED_CONFIGS.add(c);
    });
    AVAILABLE_SYMBOLS.forEach(s => SELECTED_SYMBOLS.add(s));
  } catch (err) {
    console.error("Failed to load configs/symbols:", err);
  }

  await refreshRuns();
  renderRunnerUI();
}

function setupHeaderSessionAndTheme() {
  const sel = document.getElementById("runSelect");
  if (sel && sel.parentElement) {
    // Replace "Saved Run:" label text with "Session:"
    const parent = sel.parentElement;
    const walk = el => el.childNodes.forEach(n => {
      if (n.nodeType === 3 && n.textContent.includes("Saved Run")) {
        n.textContent = n.textContent.replace("Saved Run", "Session");
      } else if (n.nodeType === 1) walk(n);
    });
    walk(parent);
    sel.onchange = () => switchSession(sel.value);

    if (!document.getElementById("tfThemeToggleBtn")) {
      const btn = document.createElement("button");
      btn.id = "tfThemeToggleBtn";
      btn.type = "button";
      btn.className = "rn-btn";
      btn.style.marginLeft = "10px";
      btn.onclick = toggleDarkMode;
      parent.appendChild(btn);
    }
  }
}

function injectRunnerStyles() {
  if (document.getElementById("tfalgoRunnerStyles")) return;
  const st = document.createElement("style");
  st.id = "tfalgoRunnerStyles";
  st.textContent = `
    .rn-wrap { display: grid; gap: 16px; }
    .rn-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(15,23,42,0.04); }
    .rn-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
    .rn-title { margin: 0; font-size: 16px; font-weight: 700; color: #0f172a; }
    .rn-sub { font-size: 12.5px; color: #64748b; }
    .rn-session-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 14px; }
    .rn-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(305px, 1fr)); gap: 14px; }
    .sc-card { border: 1.5px solid #e2e8f0; border-radius: 10px; padding: 14px; background: #f8fafc; display: flex; flex-direction: column; gap: 10px; }
    .sc-card.selected { border-color: #2563eb; background: #eff6ff; box-shadow: 0 2px 8px rgba(37,99,235,0.10); }
    .sc-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
    .sc-name { font-weight: 700; font-size: 13.5px; color: #0f172a; word-break: break-all; }
    .sc-badges { display: flex; gap: 5px; flex-wrap: wrap; }
    .sc-badge { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 999px; background: #e2e8f0; color: #334155; }
    .sc-badge.blue { background: #dbeafe; color: #1d4ed8; }
    .sc-badge.green { background: #dcfce7; color: #15803d; }
    .sc-cfg-box { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 9px 10px; font-size: 11.5px; color: #334155; display: grid; grid-template-columns: 1fr 1fr; gap: 5px 10px; }
    .sc-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: auto; }
    .rn-btn { border: 1px solid #cbd5e1; background: #fff; color: #0f172a; border-radius: 7px; padding: 6px 11px; font-size: 12px; font-weight: 600; cursor: pointer; }
    .rn-btn:hover { background: #f1f5f9; }
    .rn-btn.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
    .rn-btn.primary:hover { background: #1d4ed8; }
    .rn-btn.dark { background: #0f172a; border-color: #0f172a; color: #fff; }
    .rn-btn.danger { background: #fee2e2; border-color: #fca5a5; color: #b91c1c; }
    .rn-btn.danger:hover { background: #fecaca; }
    .rn-sym-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(145px, 1fr)); gap: 8px; max-height: 170px; overflow-y: auto; padding: 6px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; }
    .rn-sym-item { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 5px 8px; border-radius: 6px; background: #fff; border: 1px solid #e2e8f0; font-size: 12px; cursor: pointer; }
    .rn-sym-done { font-size: 10px; font-weight: 700; color: #15803d; background: #dcfce7; padding: 1px 5px; border-radius: 4px; }
    .rn-form { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
    .rn-field { display: flex; flex-direction: column; gap: 4px; }
    .rn-field label { font-size: 11.5px; font-weight: 600; color: #475569; }
    .rn-field input, .rn-field select { padding: 7px 9px; border: 1px solid #cbd5e1; border-radius: 7px; font-size: 13px; background: #fff; color: #0f172a; }
    .rn-prog-wrap { margin-top: 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 9px; padding: 12px 14px; display: none; }
    .rn-prog-wrap.active { display: block; }
    .rn-prog-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 600; color: #0f172a; margin-bottom: 7px; }
    .rn-prog-track { width: 100%; height: 11px; background: #e2e8f0; border-radius: 999px; overflow: hidden; }
    .rn-prog-bar { height: 100%; width: 0%; background: linear-gradient(90deg, #2563eb, #0ea5e9); transition: width 0.25s ease; }
    .rn-log-box { margin-top: 10px; background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 10px 12px; font-family: ui-monospace, monospace; font-size: 11.5px; max-height: 170px; overflow-y: auto; white-space: pre-wrap; }

    /* Dark mode theme */
    html.tf-dark {
      --bg: #0b1120 !important;
      --card: #111827 !important;
      --border: #1f2937 !important;
      --text: #e2e8f0 !important;
      --muted: #94a3b8 !important;
    }
    html.tf-dark body { background: #0b1120 !important; color: #e2e8f0 !important; }
    html.tf-dark .panel, html.tf-dark .box, html.tf-dark .section, html.tf-dark .chart-card, html.tf-dark .toolbar, html.tf-dark .filters, html.tf-dark .table-wrap, html.tf-dark .modal-box, html.tf-dark .modal-inner {
      background: #111827 !important; border-color: #1f2937 !important; color: #e2e8f0 !important;
    }
    html.tf-dark svg { background: #0f172a !important; border-radius: 8px; }
    html.tf-dark label, html.tf-dark span, html.tf-dark td, html.tf-dark th { color: inherit; }
    html.tf-dark header h1, html.tf-dark header h2, html.tf-dark h2, html.tf-dark h3, html.tf-dark .rn-title, html.tf-dark .sc-name { color: #f8fafc !important; }
    html.tf-dark .card, html.tf-dark .rn-card, html.tf-dark .kpi, html.tf-dark .modal-card, html.tf-dark .modal-content { background: #111827 !important; border-color: #1f2937 !important; color: #e2e8f0 !important; }
    html.tf-dark .rn-session-bar, html.tf-dark .sc-card, html.tf-dark .rn-sym-grid, html.tf-dark .rn-prog-wrap, html.tf-dark .sc-cfg-box, html.tf-dark .rn-sym-item { background: #1e293b !important; border-color: #334155 !important; color: #e2e8f0 !important; }
    html.tf-dark .sc-card.selected { background: #172554 !important; border-color: #3b82f6 !important; }
    html.tf-dark .rn-sub, html.tf-dark .lbl, html.tf-dark .rn-field label { color: #94a3b8 !important; }
    html.tf-dark input, html.tf-dark select { background: #0f172a !important; color: #f8fafc !important; border-color: #334155 !important; }
    html.tf-dark table th { background: #1e293b !important; color: #cbd5e1 !important; border-color: #334155 !important; }
    html.tf-dark table td { border-color: #1f2937 !important; color: #e2e8f0 !important; }
    html.tf-dark .tab { background: #1e293b !important; color: #cbd5e1 !important; border-color: #334155 !important; }
    html.tf-dark .tab.active { background: #2563eb !important; color: #fff !important; }
    html.tf-dark .rn-btn { background: #1e293b; border-color: #334155; color: #e2e8f0; }
    html.tf-dark .rn-btn:hover { background: #334155; }
    html.tf-dark .rn-btn.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
    html.tf-dark .rn-btn.danger { background: #450a0a; border-color: #7f1d1d; color: #fecaca; }
    html.tf-dark .rn-prog-top { color: #f8fafc; }
    html.tf-dark .rn-prog-track { background: #334155; }
    html.tf-dark .rn-sym-done { background: #14532d !important; color: #86efac !important; }
    html.tf-dark td.pos, html.tf-dark .pos, html.tf-dark b.pos { color: #4ade80 !important; }
    html.tf-dark td.neg, html.tf-dark .neg, html.tf-dark b.neg { color: #f87171 !important; }
    html.tf-dark #tradeModal > div, html.tf-dark #tradeModal .modal-dialog, html.tf-dark #tradeModal .modal-body, html.tf-dark #tradeModal .modal-header {
      background: #111827 !important; color: #e2e8f0 !important; border-color: #1f2937 !important;
    }
    html.tf-dark .tf-btn { background: #1e293b !important; color: #e2e8f0 !important; border-color: #334155 !important; }
    html.tf-dark .tf-btn.active { background: #2563eb !important; color: #fff !important; }
    .tf-modal-max { width: 98vw !important; max-width: 98vw !important; height: 94vh !important; max-height: 94vh !important; display: flex; flex-direction: column; }
    .tf-modal-max #candleSvg { flex: 1 1 auto; width: 100%; height: 74vh !important; }
    .tf-chart-tools { display: inline-flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-left: 10px; }
    .tf-color-pick { width: 22px; height: 22px; padding: 0; border: 1px solid #64748b; border-radius: 4px; cursor: pointer; background: transparent; vertical-align: middle; }
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
  if (base.includes("orb_short")) return { strategyName: "orb_short_v1", timeframe: "5m", holdingMode: "mis", notes: "Opening Range Short" };
  if (base.includes("orb")) return { strategyName: "orb_v1", timeframe: "5m", holdingMode: "mis", notes: "Opening Range Long" };
  if (base.includes("pilot")) return { strategyName: "trend_pullback_v1", timeframe: "1h / 5m", holdingMode: "mis", notes: "Pilot Trend Pullback" };
  return { strategyName: "default", timeframe: "5m", holdingMode: "mis", notes: "Base configuration" };
}

function syncSessionDropdown() {
  const sel = document.getElementById("runSelect");
  if (!sel) return;
  const names = [...new Set([...Object.keys(SESSIONS), ...AVAILABLE_RUNS])];
  sel.innerHTML = names
    .map(n => `<option value="${n}" ${n === ACTIVE_SESSION ? "selected" : ""}>${n}${AVAILABLE_RUNS.has(n) ? "" : " (not run yet)"}</option>`)
    .join("");
  sel.value = ACTIVE_SESSION;
}

function createNewSession(suggestedName) {
  const name = (suggestedName || prompt("Enter new session name:", `Session_${Object.keys(SESSIONS).length + 1}`) || "").trim();
  if (!name) return false;
  const clean = name.replace(/[^a-zA-Z0-9._-]/g, "_");
  if (!SESSIONS[clean]) {
    SESSIONS[clean] = { name: clean, configSig: null, completedSymbolsByConfig: {}, logs: [] };
  }
  ACTIVE_SESSION = clean;
  savePersistedState();
  syncSessionDropdown();
  renderRunnerUI();
  loadSessionIntoSimulator(clean);
  return true;
}

async function renameActiveSession() {
  const oldName = ACTIVE_SESSION;
  const raw = (prompt(`Rename session "${oldName}" to:`, oldName) || "").trim();
  if (!raw || raw === oldName) return;
  const newName = raw.replace(/[^a-zA-Z0-9._-]/g, "_");
  if (SESSIONS[newName]) {
    alert(`Session "${newName}" already exists.`);
    return;
  }
  const obj = SESSIONS[oldName] || { name: oldName, configSig: null, completedSymbolsByConfig: {}, logs: [] };
  obj.name = newName;
  SESSIONS[newName] = obj;
  delete SESSIONS[oldName];
  ACTIVE_SESSION = newName;
  if (AVAILABLE_RUNS.has(oldName)) {
    AVAILABLE_RUNS.delete(oldName);
    AVAILABLE_RUNS.add(newName);
  }
  savePersistedState();

  try {
    await fetch("/api/session/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_name: oldName, new_name: newName }),
    });
  } catch {}

  syncSessionDropdown();
  renderRunnerUI();
  loadSessionIntoSimulator(newName);
}

async function deleteActiveSession() {
  const target = ACTIVE_SESSION;
  if (!confirm(`Delete session "${target}" and its saved results?`)) return;
  delete SESSIONS[target];
  AVAILABLE_RUNS.delete(target);

  const remaining = Object.keys(SESSIONS);
  if (!remaining.length) {
    SESSIONS["Session_1"] = { name: "Session_1", configSig: null, completedSymbolsByConfig: {}, logs: [] };
    ACTIVE_SESSION = "Session_1";
  } else {
    ACTIVE_SESSION = remaining[0];
  }
  savePersistedState();

  try {
    await fetch("/api/session/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: target }),
    });
  } catch {}

  syncSessionDropdown();
  renderRunnerUI();
  await loadSessionIntoSimulator(ACTIVE_SESSION);
}

async function switchSession(name) {
  if (!name) return;
  if (!SESSIONS[name]) {
    SESSIONS[name] = { name, configSig: null, completedSymbolsByConfig: {}, logs: [] };
  }
  ACTIVE_SESSION = name;
  savePersistedState();
  syncSessionDropdown();
  renderRunnerUI();
  await loadSessionIntoSimulator(name);
}

async function loadSessionIntoSimulator(sessionName) {
  if (AVAILABLE_RUNS.has(sessionName)) {
    await loadRun(sessionName);
  } else {
    STRATEGIES = [];
    BENCH = { dates: [], closes: [] };
    state = [];
    renderControls();
    recalc();
  }
}

function toggleLogVisibility() {
  LOG_HIDDEN = !LOG_HIDDEN;
  const box = document.getElementById("rnLogBox");
  const btn = document.getElementById("rnToggleLogBtn");
  if (box) box.style.display = LOG_HIDDEN ? "none" : "block";
  if (btn) btn.textContent = LOG_HIDDEN ? "Show Log" : "Hide Log";
}

function renderRunnerUI() {
  const tab = document.getElementById("tab_runner");
  if (!tab) return;
  const f = loadLastForm();
  const sess = SESSIONS[ACTIVE_SESSION] || { name: ACTIVE_SESSION, completedSymbolsByConfig: {}, logs: [] };
  const doneMap = sess.completedSymbolsByConfig || {};
  const firstSelCfg = [...SELECTED_CONFIGS][0] || "";
  const doneSymsForCfg = new Set(doneMap[firstSelCfg] || []);

  const sessionOpts = Object.keys(SESSIONS)
    .map(s => `<option value="${s}" ${s === ACTIVE_SESSION ? "selected" : ""}>${s}</option>`)
    .join("");

  const cardsHtml = AVAILABLE_CONFIGS.length
    ? AVAILABLE_CONFIGS.map(cfgPath => {
        const meta = getScenarioMeta(cfgPath);
        const sel = SELECTED_CONFIGS.has(cfgPath);
        const name = cfgPath.split("/").pop();
        const isEma = (meta.strategyName || "").includes("ema_breakout") || name.includes("ema_breakout");
        const cachedCnt = (doneMap[cfgPath] || []).length;
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
                ${cachedCnt ? `<span class="sc-badge">${cachedCnt} cached</span>` : ""}
              </div>
            </div>
            <div class="sc-cfg-box">
              <div><b>Setup TF:</b> ${meta.timeframe || "1h"}</div>
              <div><b>EMAs:</b> ${meta.emaPeriods || "9, 21, 50"}</div>
              ${isEma ? `
                <div><b>Consol:</b> &ge;${meta.consolidationDays ?? 5}d (&le;${meta.maxRangePct ?? 8}%)</div>
                <div><b>Vol Mult:</b> &ge;${meta.volMult ?? 1.5}x</div>
                <div><b>SL Source:</b> ${meta.slSource || "1h_low"}</div>
                <div><b>Tranches:</b> ${meta.tranches || "0.33/0.33/0.34"}</div>
                <div><b>Trail:</b> E${meta.trailEmaInitial ?? 21} &rarr; E${meta.trailEmaRunner ?? 9} - ${meta.runnerAtrMult ?? 0.5} ATR</div>
                <div><b>Risk/Trade:</b> ${meta.riskPct ?? 1.0}%</div>
              ` : `
                <div style="grid-column:span 2;"><b>Notes:</b> ${meta.notes || cfgPath}</div>
              `}
            </div>
            <div class="sc-actions">
              <button type="button" class="rn-btn primary" onclick="runSingleScenario('${cfgPath}')">Run</button>
              <button type="button" class="rn-btn" onclick="loadScenarioIntoForm('${cfgPath}')">Edit</button>
              <button type="button" class="rn-btn" onclick="renameScenario('${cfgPath}')">Rename</button>
              <button type="button" class="rn-btn danger" onclick="deleteScenario('${cfgPath}')">Delete</button>
            </div>
          </div>`;
      }).join("")
    : `<div class="rn-sub">No YAML configs found in <code>config/</code>.</div>`;

  const symHtml = AVAILABLE_SYMBOLS.length
    ? AVAILABLE_SYMBOLS.map(s => {
        const chk = SELECTED_SYMBOLS.has(s);
        const isCached = doneSymsForCfg.has(s);
        return `
          <label class="rn-sym-item" data-sym="${s}">
            <span><input type="checkbox" ${chk ? "checked" : ""} onchange="toggleSymbolSelect('${s}', this.checked)"> <b>${s}</b></span>
            ${isCached ? `<span class="rn-sym-done">cached</span>` : ""}
          </label>`;
      }).join("")
    : `<div class="rn-sub">No symbols loaded from DB yet (add <code>/api/symbols</code> in <code>app.py</code>).</div>`;

  tab.innerHTML = `
    <div class="rn-wrap">
      <div class="rn-card">
        <div class="rn-session-bar">
          <b>Active Session:</b>
          <select id="rnSessionSelect" onchange="switchSession(this.value)" style="padding:6px 10px;border-radius:7px;border:1px solid #cbd5e1;font-size:13px;">${sessionOpts}</select>
          <button type="button" class="rn-btn dark" onclick="createNewSession()">+ New</button>
          <button type="button" class="rn-btn" onclick="renameActiveSession()">Rename</button>
          <button type="button" class="rn-btn danger" onclick="deleteActiveSession()">Delete</button>
          <span class="rn-sub">Synced with Portfolio Simulator. Partial scenarios &amp; new tickers merge into this session.</span>
        </div>
      </div>

      <div class="rn-card">
        <div class="rn-head">
          <div>
            <h3 class="rn-title">1. Select Tickers (${SELECTED_SYMBOLS.size}/${AVAILABLE_SYMBOLS.length})</h3>
            <div class="rn-sub">Already-tested tickers in this session are marked <b>cached</b> and skipped automatically if config is unchanged.</div>
          </div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
            <input id="symSearch" placeholder="Filter ticker..." oninput="filterTickerList(this.value)" style="padding:5px 9px;border:1px solid #cbd5e1;border-radius:7px;font-size:12px;">
            <button type="button" class="rn-btn" onclick="selectAllSymbols(true)">Select All</button>
            <button type="button" class="rn-btn" onclick="selectAllSymbols(false)">Clear</button>
          </div>
        </div>
        <div class="rn-sym-grid" id="rnSymGrid">${symHtml}</div>
      </div>

      <div class="rn-card">
        <div class="rn-head">
          <div>
            <h3 class="rn-title">2. Scenario Library</h3>
            <div class="rn-sub">Select one or more scenario cards, inspect their configuration, and run partial or full batches.</div>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <label style="font-size:12.5px;display:flex;align-items:center;gap:5px;">
              <input type="checkbox" id="autoOpenSim" checked> Auto-open Simulator on finish
            </label>
            <button type="button" class="rn-btn primary" onclick="runBatchNow()">Run Selected (${SELECTED_CONFIGS.size})</button>
          </div>
        </div>

        <div class="rn-grid">${cardsHtml}</div>

        <div id="rnProgressWrap" class="rn-prog-wrap ${runnerTimer ? "active" : ""}">
          <div class="rn-prog-top">
            <span id="runStatusMsg">Ready</span>
            <div style="display:flex;gap:10px;align-items:center;">
              <span id="rnElapsed">0s</span>
              <button type="button" id="rnToggleLogBtn" class="rn-btn" onclick="toggleLogVisibility()">${LOG_HIDDEN ? "Show Log" : "Hide Log"}</button>
            </div>
          </div>
          <div class="rn-prog-track"><div id="rnProgressBar" class="rn-prog-bar"></div></div>
          <pre id="rnLogBox" class="rn-log-box" style="display:${LOG_HIDDEN ? "none" : "block"};">${(sess.logs || []).join("\n")}</pre>
        </div>
      </div>

      <div class="rn-card">
        <div class="rn-head">
          <div>
            <h3 class="rn-title">3. Create / Edit Scenario Configuration</h3>
            <div class="rn-sub">Last settings are remembered automatically.</div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <button type="button" class="rn-btn" onclick="applyPreset('1h_swing')">Preset: 1H Swing</button>
            <button type="button" class="rn-btn" onclick="applyPreset('1d_swing')">Preset: 1D Swing</button>
            <button type="button" class="rn-btn" onclick="applyPreset('tight_base')">Preset: Tight Base</button>
          </div>
        </div>

        <div class="rn-form">
          <div class="rn-field"><label>Config Filename (.yaml)</label><input id="sc_fileName" value="${f.fileName}"></div>
          <div class="rn-field"><label>Engine / Direction</label>
            <div style="display:flex;gap:6px;">
              <select id="sc_strategyName" style="width:55%;">
                <option value="dynamic_v1" ${f.strategyName === "dynamic_v1" ? "selected" : ""}>dynamic_v1 (Edge Studio)</option>
                <option value="ema_breakout_v1" ${f.strategyName === "ema_breakout_v1" ? "selected" : ""}>ema_breakout_v1</option>
              </select>
              <select id="sc_direction" style="width:45%;">
                <option value="LONG" ${f.direction === "LONG" ? "selected" : ""}>LONG</option>
                <option value="SHORT" ${f.direction === "SHORT" ? "selected" : ""}>SHORT</option>
                <option value="BOTH" ${f.direction === "BOTH" ? "selected" : ""}>BOTH</option>
              </select>
            </div>
          </div>
          <div class="rn-field"><label>Pattern TF / Trigger TF</label>
            <div style="display:flex;gap:6px;">
              <select id="sc_patternTf" style="width:50%;">
                ${["5m","15m","1h","1d"].map(tf => `<option value="${tf}" ${(f.patternTf||f.timeframe)===tf?"selected":""}>Pat: ${tf}</option>`).join("")}
              </select>
              <select id="sc_triggerTf" style="width:50%;">
                ${["5m","15m","1h","1d"].map(tf => `<option value="${tf}" ${(f.triggerTf||"5m")===tf?"selected":""}>Trig: ${tf}</option>`).join("")}
              </select>
            </div>
          </div>
          <div class="rn-field"><label>RSI Min / Max &amp; RS Filter</label>
            <div style="display:flex;gap:5px;align-items:center;">
              <input type="checkbox" id="sc_useRsi" ${f.useRsi !== false ? "checked" : ""} title="Enable RSI">
              <input type="number" id="sc_rsiMin" value="${f.rsiMin ?? 50}" style="width:52px;">
              <input type="number" id="sc_rsiMax" value="${f.rsiMax ?? 80}" style="width:52px;">
              <label style="font-size:11px;display:flex;align-items:center;gap:3px;"><input type="checkbox" id="sc_useRs" ${f.useRs !== false ? "checked" : ""}> RS</label>
            </div>
          </div>
          <div class="rn-field"><label>Pass Score % / Wait Bars</label>
            <div style="display:flex;gap:6px;">
              <input type="number" id="sc_minPassScore" value="${f.minPassScore ?? 70}" style="width:50%;" title="Min Pass Score %">
              <input type="number" id="sc_maxWaitBars" value="${f.maxWaitBars ?? 36}" style="width:50%;" title="Max Wait Bars">
            </div>
          </div>
          <div class="rn-field"><label>Retrace % (Min / Max)</label>
            <div style="display:flex;gap:6px;">
              <input type="number" id="sc_retraceMin" value="${f.retraceMin ?? 15}" style="width:50%;">
              <input type="number" id="sc_retraceMax" value="${f.retraceMax ?? 65}" style="width:50%;">
            </div>
          </div>
          <div class="rn-field"><label>Score Qty Mult (Min / Max)</label>
            <div style="display:flex;gap:6px;">
              <input type="number" step="0.1" id="sc_qtyMinMult" value="${f.qtyMinMult ?? 0.5}" style="width:50%;">
              <input type="number" step="0.1" id="sc_qtyMaxMult" value="${f.qtyMaxMult ?? 1.5}" style="width:50%;">
            </div>
          </div>
          <div class="rn-field" style="grid-column: 1 / -1;"><label>Macro Chart Patterns</label>
            <div style="display:flex;gap:10px;flex-wrap:wrap;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;">
              ${MACRO_PATTERNS.map(([k, lbl]) => `<label style="font-size:12px;display:flex;align-items:center;gap:4px;"><input type="checkbox" class="sc-pat-cb" value="${k}" ${(f.patterns||[]).includes(k)?"checked":""}> ${lbl}</label>`).join("")}
            </div>
          </div>
          <div class="rn-field" style="grid-column: 1 / -1;"><label>Candlestick / Bar Triggers</label>
            <div style="display:flex;gap:10px;flex-wrap:wrap;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;">
              ${CANDLE_TRIGGERS.map(([k, lbl]) => `<label style="font-size:12px;display:flex;align-items:center;gap:4px;"><input type="checkbox" class="sc-trig-cb" value="${k}" ${(f.candleTriggers||[]).includes(k)?"checked":""}> ${lbl}</label>`).join("")}
            </div>
          </div>
          <div class="rn-field" style="display:none;"><label>Setup Timeframe</label>
            <select id="sc_timeframe">
              <option value="1h" ${f.timeframe === "1h" ? "selected" : ""}>1h (Hourly)</option>
              <option value="1d" ${f.timeframe === "1d" ? "selected" : ""}>1d (Daily)</option>
            </select>
          </div>
          <div class="rn-field"><label>EMAs (Fast, Mid, Slow)</label><input id="sc_emaPeriods" value="${f.emaPeriods}"></div>
          <div class="rn-field"><label>Min Consolidation Days</label><input type="number" id="sc_consolidationDays" value="${f.consolidationDays}"></div>
          <div class="rn-field"><label>Max Range %</label><input type="number" step="0.5" id="sc_maxRangePct" value="${f.maxRangePct}"></div>
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
          <div class="rn-field"><label>Trail Initial / Runner EMA</label>
            <div style="display:flex;gap:6px;">
              <input type="number" id="sc_trailEmaInitial" value="${f.trailEmaInitial}" style="width:50%;">
              <input type="number" id="sc_trailEmaRunner" value="${f.trailEmaRunner}" style="width:50%;">
            </div>
          </div>
          <div class="rn-field"><label>Runner ATR Mult</label><input type="number" step="0.1" id="sc_runnerAtrMult" value="${f.runnerAtrMult}"></div>
          <div class="rn-field" style="grid-column:span 2;"><label>Scenario Notes</label><input id="sc_notes" value="${f.notes || ""}"></div>
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

function toggleSymbolSelect(sym, checked) {
  if (checked) SELECTED_SYMBOLS.add(sym);
  else SELECTED_SYMBOLS.delete(sym);
  renderRunnerUI();
}

function selectAllSymbols(flag) {
  if (flag) AVAILABLE_SYMBOLS.forEach(s => SELECTED_SYMBOLS.add(s));
  else SELECTED_SYMBOLS.clear();
  renderRunnerUI();
}

function filterTickerList(q) {
  const term = (q || "").trim().toUpperCase();
  document.querySelectorAll("#rnSymGrid .rn-sym-item").forEach(el => {
    const s = (el.getAttribute("data-sym") || "").toUpperCase();
    el.style.display = !term || s.includes(term) ? "flex" : "none";
  });
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
  saveLastForm({ ...readFormValues(), ...p });
  renderRunnerUI();
}

async function renameScenario(cfgPath) {
  const oldName = cfgPath.split("/").pop();
  const raw = (prompt(`Rename "${oldName}" to:`, oldName) || "").trim();
  if (!raw || raw === oldName) return;
  let newName = raw.replace(/[^a-zA-Z0-9._-]/g, "_");
  if (!newName.endsWith(".yaml")) newName += ".yaml";
  const newPath = "config/" + newName;
  try {
    await fetch("/api/config/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_name: oldName, new_name: newName }),
    });
  } catch {}
  AVAILABLE_CONFIGS = AVAILABLE_CONFIGS.map(c => (c === cfgPath ? newPath : c));
  if (SELECTED_CONFIGS.has(cfgPath)) { SELECTED_CONFIGS.delete(cfgPath); SELECTED_CONFIGS.add(newPath); }
  if (SAVED_SCENARIOS[cfgPath]) { SAVED_SCENARIOS[newPath] = { ...SAVED_SCENARIOS[cfgPath], fileName: newName }; delete SAVED_SCENARIOS[cfgPath]; }
  savePersistedState();
  renderRunnerUI();
}

async function deleteScenario(cfgPath) {
  const name = cfgPath.split("/").pop();
  if (!confirm(`Delete scenario "${name}"?`)) return;
  try {
    await fetch("/api/config/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: name }),
    });
  } catch {}
  AVAILABLE_CONFIGS = AVAILABLE_CONFIGS.filter(c => c !== cfgPath);
  SELECTED_CONFIGS.delete(cfgPath);
  delete SAVED_SCENARIOS[cfgPath];
  savePersistedState();
  renderRunnerUI();
}

function loadScenarioIntoForm(cfgPath) {
  const meta = getScenarioMeta(cfgPath);
  const name = cfgPath.split("/").pop();
  saveLastForm({ ...DEFAULT_SCENARIO_FORM, ...meta, fileName: name });
  renderRunnerUI();
  const msg = document.getElementById("scFormMsg");
  if (msg) msg.textContent = `Loaded ${name} into editor.`;
}

function readFormValues() {
  const g = id => (document.getElementById(id) ? document.getElementById(id).value : "");
  const chk = id => !!(document.getElementById(id) && document.getElementById(id).checked);
  const pats = [...document.querySelectorAll(".sc-pat-cb:checked")].map(x => x.value);
  const trigs = [...document.querySelectorAll(".sc-trig-cb:checked")].map(x => x.value);
  return {
    fileName: (g("sc_fileName").trim() || "dynamic_edge_v1.yaml").replace(/[^a-zA-Z0-9._-]/g, "_"),
    strategyName: g("sc_strategyName") || "dynamic_v1",
    direction: g("sc_direction") || "LONG",
    patternTf: g("sc_patternTf") || "1h",
    triggerTf: g("sc_triggerTf") || "5m",
    patterns: pats,
    candleTriggers: trigs,
    useRsi: chk("sc_useRsi"),
    rsiMin: Number(g("sc_rsiMin")) || 50,
    rsiMax: Number(g("sc_rsiMax")) || 80,
    useRs: chk("sc_useRs"),
    minPassScore: Number(g("sc_minPassScore")) || 70,
    maxWaitBars: Number(g("sc_maxWaitBars")) || 36,
    retraceMin: Number(g("sc_retraceMin")) || 15,
    retraceMax: Number(g("sc_retraceMax")) || 65,
    qtyMinMult: Number(g("sc_qtyMinMult")) || 0.5,
    qtyMaxMult: Number(g("sc_qtyMaxMult")) || 1.5,
    timeframe: g("sc_patternTf") || "1h",
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
  if (f.strategyName === "dynamic_v1") {
    const pList = (f.patterns || []).map(x => `"${x}"`).join(", ");
    const tList = (f.candleTriggers || []).map(x => `"${x}"`).join(", ");
    return `extends: default.yaml

strategy:
  name: dynamic_v1
  params:
    direction: "${f.direction || "LONG"}"
    pattern_tf: "${f.patternTf || "1h"}"
    trigger_tf: "${f.triggerTf || "5m"}"
    trail_tf: "${f.trailTimeframe || "1h"}"
    patterns: [${pList}]
    candle_triggers: [${tList}]
    ema_periods: [${emas.join(", ")}]
    consolidation_min_days: ${f.consolidationDays}
    consolidation_max_range_pct: ${f.maxRangePct}
    breakout_vol_mult: ${f.volMult}
    use_rsi: ${f.useRsi !== false}
    rsi_period: 14
    rsi_min: ${f.rsiMin ?? 50}
    rsi_max: ${f.rsiMax ?? 80}
    use_rs: ${f.useRs !== false}
    rs_lookback_bars: 20
    min_pass_score_pct: ${f.minPassScore ?? 70}
    score_qty_min_mult: ${f.qtyMinMult ?? 0.5}
    score_qty_max_mult: ${f.qtyMaxMult ?? 1.5}
    max_wait_bars: ${f.maxWaitBars ?? 36}
    retrace_min_pct: ${f.retraceMin ?? 15}
    retrace_max_pct: ${f.retraceMax ?? 65}
    impulse_pct_mult: ${f.impulseMult}
    sl_source: "${f.slSource === "5m_low" ? "trigger_low" : "pattern_low"}"
    holding_mode: "${f.holdingMode}"
    risk_per_trade_pct: ${f.riskPct}
    tranches: [${tr.join(", ")}]
    add_at_r: [${ar.join(", ")}]
    use_risk_neutral_sl: true
    trail_ema_initial: ${f.trailEmaInitial}
    trail_ema_runner: ${f.trailEmaRunner}
    runner_atr_period: 14
    runner_atr_mult: ${f.runnerAtrMult}
`;
  }
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
  if (navigator.clipboard) navigator.clipboard.writeText(buildYamlFromForm(f));
  const msg = document.getElementById("scFormMsg");
  if (msg) msg.textContent = "YAML copied to clipboard & form saved.";
}

async function saveScenarioFromForm(andRun) {
  const f = readFormValues();
  if (!f.fileName.endsWith(".yaml")) f.fileName += ".yaml";
  const cfgPath = "config/" + f.fileName;
  saveLastForm(f);
  SAVED_SCENARIOS[cfgPath] = f;
  savePersistedState();

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
  } catch {}

  const msg = document.getElementById("scFormMsg");
  if (msg) msg.textContent = `Saved settings in browser. Add /api/save_config in app.py to write ${cfgPath} to disk.`;
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
    AVAILABLE_RUNS = new Set(runs);
    syncSessionDropdown();
    await loadSessionIntoSimulator(ACTIVE_SESSION);
  } catch (err) {
    console.error("Failed to refresh runs:", err);
  }
}

async function runBatchNow() {
  const configs = [...SELECTED_CONFIGS];
  const symbols = [...SELECTED_SYMBOLS];
  const sess = SESSIONS[ACTIVE_SESSION];

  const sig = JSON.stringify(configs.map(c => ({ c, m: getScenarioMeta(c) })));
  if (sess.configSig && sess.configSig !== sig) {
    const okNew = confirm(
      `Configuration changed in "${ACTIVE_SESSION}".\n\nClick OK to create a NEW session for this configuration, or Cancel to stay.`
    );
    if (!okNew) return;
    if (!createNewSession(`Session_${Object.keys(SESSIONS).length + 1}`)) return;
  }

  const activeSess = SESSIONS[ACTIVE_SESSION];
  activeSess.configSig = sig;
  savePersistedState();

  const progWrap = document.getElementById("rnProgressWrap");
  const progBar = document.getElementById("rnProgressBar");
  const msgEl = document.getElementById("runStatusMsg");
  const elapEl = document.getElementById("rnElapsed");
  const logBox = document.getElementById("rnLogBox");

  if (!configs.length) {
    if (progWrap) progWrap.classList.add("active");
    if (msgEl) msgEl.textContent = "Please select at least one scenario card.";
    return;
  }

  if (progWrap) progWrap.classList.add("active");
  if (progBar) progBar.style.width = "5%";
  if (msgEl) msgEl.textContent = `Starting ${configs.length} scenario(s) in ${ACTIVE_SESSION}...`;
  runnerStartMs = Date.now();
  if (runnerTimer) clearInterval(runnerTimer);

  try {
    const res = await (
      await fetch("/api/run_batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          configs,
          symbols,
          session_name: ACTIVE_SESSION,
          cached_symbols_by_config: activeSess.completedSymbolsByConfig || {},
        }),
      })
    ).json();

    if (!res.ok) {
      if (msgEl) msgEl.textContent = res.error || "Batch run failed to start.";
      if (progBar) progBar.style.width = "0%";
      return;
    }

    runnerTimer = setInterval(async () => {
      try {
        const secs = Math.round((Date.now() - runnerStartMs) / 1000);
        if (elapEl) elapEl.textContent = `${secs}s`;
        const st = await (await fetch("/api/status")).json();

        let pct = 10;
        if (st.total_days > 0 && st.days_done != null) {
          pct = Math.max(5, Math.min(100, Math.round((st.days_done / st.total_days) * 100)));
        } else if (st.progress != null) {
          pct = st.progress;
        }
        if (progBar) progBar.style.width = `${st.running ? pct : 100}%`;
        if (msgEl) {
          msgEl.textContent = st.last_error
            ? "Error: " + st.last_error
            : `${st.message || "Running..."} (${pct}%)`;
        }
        if (st.logs && Array.isArray(st.logs) && logBox) {
          logBox.textContent = st.logs.join("\n");
          logBox.scrollTop = logBox.scrollHeight;
          activeSess.logs = st.logs.slice(-150);
          savePersistedState();
        }

        if (!st.running) {
          clearInterval(runnerTimer);
          runnerTimer = null;
          if (!st.last_error) {
            configs.forEach(c => {
              const prev = new Set(activeSess.completedSymbolsByConfig[c] || []);
              symbols.forEach(s => prev.add(s));
              activeSess.completedSymbolsByConfig[c] = [...prev];
            });
            savePersistedState();
          }
          AVAILABLE_RUNS.add(ACTIVE_SESSION);
          await refreshRuns();
          syncSessionDropdown();
          renderRunnerUI();
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
    }, 600);
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
    STOCK_BENCH = run.stock_bench || {};
    injectBenchmarkDropdown();
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
      const durMs = (tr.entry_ts && tr.exit_ts) ? Math.max(0, new Date(tr.exit_ts) - new Date(tr.entry_ts)) : 0;
      activeTrades.push({
        ...tr,
        strategy: s.name,
        uid: s.name + "_" + tr.trade_id,
        scaled_pnl: p,
        duration_ms: durMs,
        duration_str: fmtTradeDuration(tr.entry_ts, tr.exit_ts),
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
  const losses = activeTrades.filter(t => t.scaled_pnl <= 0);
  const gp = wins.reduce((a, t) => a + t.scaled_pnl, 0);
  const glAbs = Math.abs(losses.reduce((a, t) => a + t.scaled_pnl, 0));
  const netPnlAll = gp - glAbs;
  const nT = activeTrades.length;
  const avgWin = wins.length ? gp / wins.length : 0;
  const avgLoss = losses.length ? glAbs / losses.length : 0;
  const payoff = avgLoss > 0 ? avgWin / avgLoss : 0;
  const expInr = nT ? netPnlAll / nT : 0;
  const expR = nT ? activeTrades.reduce((a, t) => a + Number(t.money_r || 0), 0) / nT : 0;
  const bestInr = nT ? Math.max(...activeTrades.map(t => t.scaled_pnl)) : 0;
  const worstInr = nT ? Math.min(...activeTrades.map(t => t.scaled_pnl)) : 0;
  const bestR = nT ? Math.max(...activeTrades.map(t => Number(t.money_r || 0))) : 0;
  const worstR = nT ? Math.min(...activeTrades.map(t => Number(t.money_r || 0))) : 0;

  const chrono = [...activeTrades].sort((a, b) => String(a.exit_ts || "").localeCompare(String(b.exit_ts || "")));
  let maxCW = 0, maxCL = 0, cw = 0, cl = 0;
  chrono.forEach(t => {
    if (t.scaled_pnl > 0) { cw++; cl = 0; if (cw > maxCW) maxCW = cw; }
    else { cl++; cw = 0; if (cl > maxCL) maxCL = cl; }
  });

  const holdDays = t => {
    if (!t.entry_ts || !t.exit_ts) return 0;
    const ms = new Date(t.exit_ts) - new Date(t.entry_ts);
    return Math.max(0, ms / 86400000);
  };
  const avgHoldW = wins.length ? wins.reduce((a, t) => a + holdDays(t), 0) / wins.length : 0;
  const avgHoldL = losses.length ? losses.reduce((a, t) => a + holdDays(t), 0) / losses.length : 0;
  const avgHoldAll = nT ? activeTrades.reduce((a, t) => a + holdDays(t), 0) / nT : 0;

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
    ["Total Closed Campaigns", nT],
    ["Winning Trades", wins.length],
    ["Losing Trades (incl. BE)", losses.length],
    ["Win Rate (%)", (nT ? (wins.length / nT) * 100 : 0).toFixed(1) + "%"],
    ["Avg Win (INR)", "INR " + Math.round(avgWin).toLocaleString()],
    ["Avg Loss (INR)", "INR " + Math.round(avgLoss).toLocaleString()],
    ["Payoff Ratio", payoff.toFixed(2)],
    ["Expectancy / Trade", "INR " + Math.round(expInr).toLocaleString()],
    ["Expectancy (R)", expR.toFixed(2) + "R"],
    ["Gross Profit", "INR " + Math.round(gp).toLocaleString()],
    ["Gross Loss", "INR " + Math.round(glAbs).toLocaleString()],
    ["Profit Factor", (glAbs > 0 ? gp / glAbs : (gp > 0 ? 999 : 0)).toFixed(2)],
    ["Best Trade (INR)", "INR " + Math.round(bestInr).toLocaleString()],
    ["Best Trade (R)", bestR.toFixed(2) + "R"],
    ["Worst Trade (INR)", "INR " + Math.round(worstInr).toLocaleString()],
    ["Worst Trade (R)", worstR.toFixed(2) + "R"],
    ["Max Consec. Wins", maxCW],
    ["Max Consec. Losses", maxCL],
    ["Avg Hold Days (Win)", avgHoldW.toFixed(1)],
    ["Avg Hold Days (Loss)", avgHoldL.toFixed(1)],
    ["Avg Hold Days (All)", avgHoldAll.toFixed(1)],
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

function injectBenchmarkDropdown() {
  const showBenchEl = document.getElementById("showBench");
  const anchor = showBenchEl ? showBenchEl.parentElement : null;
  if (!anchor) return;
  let wrap = document.getElementById("tfBenchMultiWrap");
  if (!wrap) {
    wrap = document.createElement("span");
    wrap.id = "tfBenchMultiWrap";
    wrap.style.cssText = "position:relative;display:inline-block;margin-left:10px;";
    anchor.insertAdjacentElement("afterend", wrap);
  }
  const syms = Object.keys(STOCK_BENCH).sort();
  const opts = ["NIFTY_50", ...syms];
  wrap.innerHTML = `
    <button type="button" class="rn-btn" onclick="var m=document.getElementById('tfBenchMenu');m.style.display=m.style.display==='block'?'none':'block';">
      Compare (${SELECTED_BENCHMARKS.size}) &#9662;
    </button>
    <div id="tfBenchMenu" style="display:none;position:absolute;top:110%;left:0;z-index:50;min-width:190px;max-height:240px;overflow-y:auto;background:var(--card,#fff);border:1px solid var(--border,#cbd5e1);border-radius:8px;padding:8px;box-shadow:0 8px 20px rgba(0,0,0,0.18);">
      ${opts.map((o, idx) => `
        <label style="display:flex;align-items:center;gap:7px;padding:4px 6px;font-size:12px;cursor:pointer;">
          <input type="checkbox" ${SELECTED_BENCHMARKS.has(o) ? "checked" : ""} onchange="toggleBenchmark('${o}', this.checked)">
          <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${BENCH_COLORS[idx % BENCH_COLORS.length]};"></span>
          <span>${o === "NIFTY_50" ? "Nifty 50" : o}</span>
        </label>
      `).join("")}
    </div>
  `;
}

function toggleBenchmark(name, checked) {
  if (checked) SELECTED_BENCHMARKS.add(name);
  else SELECTED_BENCHMARKS.delete(name);
  const showBenchEl = document.getElementById("showBench");
  if (name === "NIFTY_50" && showBenchEl) showBenchEl.checked = checked;
  injectBenchmarkDropdown();
  recalc();
}

function fmtTradeDuration(entryTs, exitTs) {
  if (!entryTs || !exitTs) return "-";
  const ms = Math.max(0, new Date(exitTs) - new Date(entryTs));
  const mins = Math.round(ms / 60000);
  if (mins < 60) return mins + "m";
  const hrs = Math.floor(mins / 60);
  const remM = mins % 60;
  if (hrs < 24) return hrs + "h" + (remM ? " " + remM + "m" : "");
  const days = Math.floor(hrs / 24);
  const remH = hrs % 24;
  return days + "d" + (remH ? " " + remH + "h" : "");
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

  const gridCol = DARK_MODE ? "#334155" : "#e2e8f0";
  const lblCol = DARK_MODE ? "#94a3b8" : "#64748b";
  const showBenchEl = document.getElementById("showBench");
  const showB = !!(showBenchEl && showBenchEl.checked && benchPct.length === portPct.length);
  if (showBenchEl && showBenchEl.checked) SELECTED_BENCHMARKS.add("NIFTY_50");

  const extraSeries = [];
  if (showB && SELECTED_BENCHMARKS.has("NIFTY_50")) {
    extraSeries.push({ name: "Nifty 50", pct: benchPct, color: BENCH_COLORS[0], dashed: true });
  }
  const stockKeys = Object.keys(STOCK_BENCH).sort();
  stockKeys.forEach((sym, idx) => {
    if (SELECTED_BENCHMARKS.has(sym)) {
      const closes = STOCK_BENCH[sym] || [];
      if (closes.length === portPct.length && closes[0] > 0) {
        extraSeries.push({
          name: sym,
          pct: closes.map(c => (c / closes[0] - 1) * 100),
          color: BENCH_COLORS[(idx + 1) % BENCH_COLORS.length],
          dashed: false,
        });
      }
    }
  });

  const W = 1100, H = 320, P = 56, R = 20;
  let all = portPct.concat([0]);
  extraSeries.forEach(s => { all = all.concat(s.pct); });
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
    g += `<line x1="${P}" y1="${y}" x2="${W - R}" y2="${y}" stroke="${gridCol}" stroke-dasharray="3,3"/>`;
    g += `<text x="${P - 6}" y="${y + 4}" font-size="11" text-anchor="end" fill="${lblCol}">${v.toFixed(1)}%</text>`;
  }

  const y0 = my(0);
  g += `<line x1="${P}" y1="${y0}" x2="${W - R}" y2="${y0}" stroke="#94a3b8" stroke-width="1"/>`;
  const pEq = portPct.map((v, i) => `${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ");
  const pB = extraSeries.map(s =>
    `<polyline fill="none" stroke="${s.color}" stroke-width="1.6" ${s.dashed ? "stroke-dasharray=\"5,4\"" : ""} points="${s.pct.map((v, i) => `${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ")}"/>`
  ).join("");
  const legHtml = extraSeries.map((s, idx) =>
    `<text x="${P + 10 + idx * 115}" y="16" font-size="10.5" font-weight="600" fill="${s.color}">&#9632; ${s.name}: ${(s.pct[s.pct.length - 1] || 0).toFixed(1)}%</text>`
  ).join("");

  eSvg.innerHTML = `${g}${pB}${legHtml}<polyline fill="none" stroke="#3b82f6" stroke-width="2.4" points="${pEq}"/>
    <text x="${P}" y="${H - 8}" font-size="11" fill="${lblCol}">${dates[0] || ""}</text>
    <text x="${W - R}" y="${H - 8}" font-size="11" text-anchor="end" fill="${lblCol}">${dates[dates.length - 1] || ""}</text>`;

  const Hd = 240;
  const dmin = Math.min(...dd, -0.5);
  const myd = v => 20 + (Hd - 50) * (v / dmin);
  const dPts = dd.map((v, i) => `${mx(i).toFixed(1)},${myd(v).toFixed(1)}`).join(" ");
  dSvg.innerHTML = `<polygon fill="rgba(220,38,38,0.14)" points="${P},${myd(0)} ${dPts} ${W - R},${myd(0)}"/>
    <polyline fill="none" stroke="#dc2626" stroke-width="2" points="${dPts}"/>
    <text x="${P - 6}" y="${myd(dmin) + 4}" font-size="11" text-anchor="end" fill="${lblCol}">${dmin.toFixed(1)}%</text>`;

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

    let eh = `<line x1="${x}" y1="10" x2="${x}" y2="${H - 26}" stroke="#64748b" stroke-width="1" stroke-dasharray="3,3"/>`;
    eh += `<circle cx="${x}" cy="${py}" r="4" fill="#3b82f6" stroke="#fff" stroke-width="1.5"/>`;
    if (showB) eh += `<circle cx="${x}" cy="${my(bv)}" r="3.5" fill="#94a3b8" stroke="#fff" stroke-width="1.2"/>`;
    eh += `<rect x="${tx}" y="${ty}" width="${tipW}" height="${tipH}" rx="5" fill="#0f172a" opacity="0.94"/>`;
    eh += `<text x="${tx + 8}" y="${ty + 15}" font-size="10.5" font-weight="700" fill="#e2e8f0">${dt}</text>`;
    eh += `<text x="${tx + 8}" y="${ty + 30}" font-size="11" font-weight="700" fill="#60a5fa">Portfolio: ${pv >= 0 ? "+" : ""}${pv.toFixed(2)}%</text>`;
    if (showB) {
      const aCol = alpha >= 0 ? "#4ade80" : "#f87171";
      eh += `<text x="${tx + 8}" y="${ty + 45}" font-size="10.5" fill="#cbd5e1">Nifty: ${bv >= 0 ? "+" : ""}${bv.toFixed(2)}% | <tspan fill="${aCol}" font-weight="700">${alpha >= 0 ? "+" : ""}${alpha.toFixed(2)}%</tspan></text>`;
    }
    eqOv.innerHTML = eh;

    const dv = dd[idx];
    const dy = myd(dv);
    let dh = `<line x1="${x}" y1="12" x2="${x}" y2="${Hd - 24}" stroke="#64748b" stroke-width="1" stroke-dasharray="3,3"/>`;
    dh += `<circle cx="${x}" cy="${dy}" r="4" fill="#dc2626" stroke="#fff" stroke-width="1.5"/>`;
    const dtx = Math.min(W - R - 150, Math.max(P + 6, x + 12));
    dh += `<rect x="${dtx}" y="12" width="144" height="34" rx="5" fill="#0f172a" opacity="0.94"/>`;
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
    const theadRow = rowsEl.parentElement ? rowsEl.parentElement.querySelector("thead tr") : null;
    if (theadRow && !theadRow.querySelector("[data-col='duration_ms']")) {
      const th = document.createElement("th");
      th.setAttribute("data-col", "duration_ms");
      th.style.cursor = "pointer";
      th.textContent = "Duration";
      th.onclick = () => sortBy("duration_ms");
      const exitTh = theadRow.children[4];
      if (exitTh && exitTh.nextSibling) theadRow.insertBefore(th, exitTh.nextSibling);
      else theadRow.appendChild(th);
    }
    rowsEl.innerHTML = list.map(t => `<tr>
      <td class="left"><span class="trade-link" onclick="openTrade('${t.uid}')">#${t.trade_id}</span></td>
      <td class="left">${t.strategy}</td>
      <td class="left"><b>${t.symbol}</b></td>
      <td class="left">${(t.entry_ts || "").slice(0, 16).replace("T", " ")}</td>
      <td class="left">${(t.exit_ts || "").slice(0, 16).replace("T", " ")}</td>
      <td>${t.duration_str || "-"}</td>
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
  if (titleEl) titleEl.textContent = `${currentTrade.symbol} — Trade #${currentTrade.trade_id} (${currentTrade.strategy})`;

  const subEl = document.getElementById("modalSub");
  if (subEl) {
    subEl.innerHTML =
      `Entry: <b>${Number(currentTrade.avg_entry || 0).toFixed(2)}</b> (${(currentTrade.entry_ts || "").slice(0, 16).replace("T", " ")}) | ` +
      `Exit: <b>${Number(currentTrade.avg_exit || 0).toFixed(2)}</b> (${(currentTrade.exit_ts || "").slice(0, 16).replace("T", " ")}) | ` +
      `Stop: <b style="color:#dc2626">${Number(currentTrade.initial_stop || 0).toFixed(2)}</b> | ` +
      `P&amp;L: <b class="${currentTrade.scaled_pnl >= 0 ? "pos" : "neg"}">INR ${Math.round(currentTrade.scaled_pnl).toLocaleString()} (${Number(currentTrade.money_r || 0).toFixed(2)}R)</b>` +
      ` &nbsp;<span style="color:#64748b;font-size:11.5px;">(Scroll: Zoom | Drag: Pan | Click 2 pts: Measure % | DblClick: Reset)</span>`;
  }

  stopReplay(true);
  calloutOffsets = {};
  chartExtraDaysBefore = 0;
  chartExtraDaysAfter = 0;
  injectChartToolbarControls();
  const modal = document.getElementById("tradeModal");
  if (modal) modal.classList.add("open");
  fetchTradeChart();
}

function closeModal() {
  stopReplay(true);
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

function injectChartToolbarControls() {
  if (document.getElementById("tfChartTools")) return;
  const togPat = document.getElementById("togPat");
  const bar = togPat ? togPat.parentElement : null;
  if (!bar) return;
  const wrap = document.createElement("span");
  wrap.id = "tfChartTools";
  wrap.className = "tf-chart-tools";
  wrap.innerHTML = `
    <button type="button" class="rn-btn" onclick="shiftChartWindow(-7, 0)">&laquo; Load Earlier</button>
    <button type="button" class="rn-btn" onclick="shiftChartWindow(0, 7)">Load Later &raquo;</button>
    <label style="font-size:11.5px;">E9 <input type="color" class="tf-color-pick" value="${EMA_COLORS.ema9}" oninput="setEmaColor('ema9', this.value)"></label>
    <label style="font-size:11.5px;">E21 <input type="color" class="tf-color-pick" value="${EMA_COLORS.ema21}" oninput="setEmaColor('ema21', this.value)"></label>
    <label style="font-size:11.5px;">E50 <input type="color" class="tf-color-pick" value="${EMA_COLORS.ema50}" oninput="setEmaColor('ema50', this.value)"></label>
    <button type="button" id="tfReplayBtn" class="rn-btn primary" onclick="toggleReplay()">&#9654; Replay</button>
    <button type="button" class="rn-btn" onclick="stepReplay(-1)">&#9664;</button>
    <button type="button" class="rn-btn" onclick="stepReplay(1)">&#9654;&#124;</button>
    <select id="tfReplaySpeed" onchange="setReplaySpeed(this.value)" style="padding:4px 6px;border-radius:6px;font-size:12px;">
      <option value="1">1x</option>
      <option value="1.5">1.5x</option>
      <option value="2">2x</option>
      <option value="3">3x</option>
    </select>
    <button type="button" class="rn-btn" onclick="stopReplay(true)">Reset Replay</button>
    <button type="button" id="tfMaxChartBtn" class="rn-btn" onclick="toggleMaximizeChart()">⛶ Maximize</button>
  `;
  bar.appendChild(wrap);
}

function stopReplay(resetFull) {
  if (replayTimer) {
    clearInterval(replayTimer);
    replayTimer = null;
  }
  const btn = document.getElementById("tfReplayBtn");
  if (btn) btn.innerHTML = "&#9654; Replay";
  if (resetFull) {
    replayLimitIdx = null;
    redrawActiveTrade();
  }
}

function setReplaySpeed(val) {
  replaySpeed = parseFloat(val) || 1.0;
  if (replayTimer) {
    stopReplay(false);
    toggleReplay();
  }
}

function stepReplay(delta) {
  stopReplay(false);
  if (!cachedCandles.length) return;
  if (replayLimitIdx === null) {
    const eKey = (currentTrade.entry_ts || "").slice(0, 16);
    const eIdx = eKey ? cachedCandles.findIndex(b => b.t.slice(0, 16) >= eKey) : 20;
    replayLimitIdx = Math.max(5, (eIdx >= 0 ? eIdx : 20) - 20);
  }
  replayLimitIdx = Math.max(5, Math.min(cachedCandles.length - 1, replayLimitIdx + delta));
  redrawActiveTrade();
}

function toggleReplay() {
  if (replayTimer) {
    stopReplay(false);
    return;
  }
  if (!cachedCandles.length) return;
  if (replayLimitIdx === null || replayLimitIdx >= cachedCandles.length - 1) {
    const eKey = (currentTrade.entry_ts || "").slice(0, 16);
    const eIdx = eKey ? cachedCandles.findIndex(b => b.t.slice(0, 16) >= eKey) : 20;
    replayLimitIdx = Math.max(5, (eIdx >= 0 ? eIdx : 20) - 20);
  }
  const btn = document.getElementById("tfReplayBtn");
  if (btn) btn.innerHTML = "&#9208; Pause";
  const delay = Math.max(80, Math.round(600 / replaySpeed));
  replayTimer = setInterval(() => {
    if (replayLimitIdx >= cachedCandles.length - 1) {
      stopReplay(false);
      return;
    }
    replayLimitIdx += 1;
    if (replayLimitIdx > viewEnd) {
      viewEnd = replayLimitIdx;
      viewStart = Math.max(0, viewEnd - 120);
    }
    redrawActiveTrade();
  }, delay);
}

function setEmaColor(key, col) {
  EMA_COLORS[key] = col;
  try { localStorage.setItem("tfalgo_ema_colors_v1", JSON.stringify(EMA_COLORS)); } catch {}
  redrawActiveTrade();
}

function toggleMaximizeChart() {
  chartMaximized = !chartMaximized;
  const modal = document.getElementById("tradeModal");
  const card = modal ? modal.firstElementChild : null;
  if (card) card.classList.toggle("tf-modal-max", chartMaximized);
  const btn = document.getElementById("tfMaxChartBtn");
  if (btn) btn.textContent = chartMaximized ? "🗗 Restore" : "⛶ Maximize";
}

function shiftChartWindow(dBefore, dAfter) {
  chartExtraDaysBefore += dBefore;
  chartExtraDaysAfter += dAfter;
  fetchTradeChart();
}

async function fetchTradeChart() {
  if (!currentTrade) return;
  const shiftDate = (iso, deltaDays) => {
    const d = new Date((iso || "").slice(0, 10) + "T00:00:00Z");
    if (Number.isNaN(d.getTime())) return (iso || "").slice(0, 10);
    d.setUTCDate(d.getUTCDate() + deltaDays);
    return d.toISOString().slice(0, 10);
  };
  const q = new URLSearchParams({
    symbol: currentTrade.symbol,
    tf: currentTf,
    entry: shiftDate(currentTrade.entry_ts, chartExtraDaysBefore),
    exit: shiftDate(currentTrade.exit_ts, chartExtraDaysAfter),
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
    if (svg) svg.innerHTML = `<text x="550" y="240" text-anchor="middle" fill="#dc2626">Failed to load candles: ${err.message}</text>`;
  }
}

function drawCandles(allBars, pat) {
  const svg = document.getElementById("candleSvg");
  if (!svg) return;
  if (!allBars.length) {
    svg.innerHTML = `<text x="550" y="240" text-anchor="middle" fill="#64748b">No data for timeframe ${currentTf}</text>`;
    return;
  }

  const gridCol = DARK_MODE ? "#1e293b" : "#f1f5f9";
  const lblCol = DARK_MODE ? "#94a3b8" : "#64748b";
  const hudTextCol = DARK_MODE ? "#e2e8f0" : "#334155";

  const activeBarsPool = replayLimitIdx !== null ? allBars.slice(0, replayLimitIdx + 1) : allBars;
  viewStart = Math.max(0, Math.min(activeBarsPool.length - 1, viewStart));
  viewEnd = Math.max(viewStart, Math.min(activeBarsPool.length - 1, replayLimitIdx !== null ? activeBarsPool.length - 1 : (viewEnd || (activeBarsPool.length - 1))));
  const bars = activeBarsPool.slice(viewStart, viewEnd + 1);

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
    out += `<line x1="${P}" y1="${y}" x2="${W - R}" y2="${y}" stroke="${gridCol}"/>`;
    out += `<text x="${P - 8}" y="${y + 4}" font-size="11" text-anchor="end" fill="${lblCol}">${v.toFixed(2)}</text>`;
  }

  if (showP && pat && pat.type === "vcp" && pat.zigzag && pat.zigzag.length) {
    const zpts = pat.zigzag
      .map(z => {
        const idx = bars.findIndex(b => b.t.slice(0, 10) >= z.t.slice(0, 10));
        return idx >= 0 ? `${mx(idx).toFixed(1)},${my(z.p).toFixed(1)}` : null;
      })
      .filter(Boolean);
    if (zpts.length > 1) out += `<polyline fill="none" stroke="#8b5cf6" stroke-width="2" stroke-dasharray="4,2" points="${zpts.join(" ")}"/>`;
    if (pat.pivot != null) out += `<line x1="${P}" y1="${my(pat.pivot)}" x2="${W - R}" y2="${my(pat.pivot)}" stroke="#8b5cf6" stroke-width="1.2" stroke-dasharray="5,3"/>`;
  } else if (showP && pat && pat.type === "flat_base" && pat.t0 && pat.t1) {
    const i0 = Math.max(0, bars.findIndex(b => b.t.slice(0, 10) >= pat.t0.slice(0, 10)));
    const i1 = bars.findIndex(b => b.t.slice(0, 10) >= pat.t1.slice(0, 10));
    if (i1 > i0) out += `<rect x="${mx(i0)}" y="${my(pat.high)}" width="${mx(i1) - mx(i0)}" height="${my(pat.low) - my(pat.high)}" fill="rgba(139,92,246,0.10)" stroke="#8b5cf6" stroke-dasharray="4,3"/>`;
  } else if (showP && pat && pat.type === "cup_handle" && pat.cup && pat.cup.length >= 3) {
    const cpts = pat.cup
      .map(pt => {
        const idx = bars.findIndex(b => b.t.slice(0, 10) >= pt.t.slice(0, 10));
        return idx >= 0 ? `${mx(idx).toFixed(1)},${my(pt.p).toFixed(1)}` : null;
      })
      .filter(Boolean);
    if (cpts.length >= 2) out += `<polyline fill="none" stroke="#8b5cf6" stroke-width="2" stroke-dasharray="5,3" points="${cpts.join(" ")}"/>`;
  }

  if (showE) {
    [["ema9", EMA_COLORS.ema9], ["ema21", EMA_COLORS.ema21], ["ema50", EMA_COLORS.ema50]].forEach(([k, col]) => {
      const pts = bars.map((b, i) => (b[k] != null ? `${mx(i).toFixed(1)},${my(b[k]).toFixed(1)}` : null)).filter(Boolean);
      if (pts.length > 1) out += `<polyline fill="none" stroke="${col}" stroke-width="1.6" points="${pts.join(" ")}"/>`;
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
    out += `<line x1="${ex}" y1="${T}" x2="${ex}" y2="${H - B}" stroke="#3b82f6" stroke-dasharray="2,2"/><polygon points="${ex},${ey + 3} ${ex - 6},${ey + 15} ${ex + 6},${ey + 15}" fill="#3b82f6"/><text x="${ex}" y="${ey + 29}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3b82f6">ENTRY ${Number(currentTrade.avg_entry || 0).toFixed(2)} (${(currentTrade.entry_ts || "").slice(11, 16)})</text>`;
  }

  if (xIdx >= 0) {
    const xx = mx(xIdx), xy = my(currentTrade.avg_exit);
    out += `<line x1="${xx}" y1="${T}" x2="${xx}" y2="${H - B}" stroke="#f59e0b" stroke-dasharray="2,2"/><polygon points="${xx},${xy - 3} ${xx - 6},${xy - 15} ${xx + 6},${xy - 15}" fill="#f59e0b"/><text x="${xx}" y="${xy - 21}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#f59e0b">EXIT ${Number(currentTrade.avg_exit || 0).toFixed(2)} (${(currentTrade.exit_ts || "").slice(11, 16)})</text>`;
  }

  out += `<text x="${P}" y="${H - 10}" font-size="11" fill="${lblCol}">${bars[0].t.slice(0, 16).replace("T", " ")}</text><text x="${W - R}" y="${H - 10}" font-size="11" text-anchor="end" fill="${lblCol}">${bars[bars.length - 1].t.slice(0, 16).replace("T", " ")} (${bars.length}/${allBars.length} bars)</text>`;
  // Parse Trailing SL steps (T1, T2, ...)
  let trailPts = [];
  try {
    const rawT = typeof currentTrade.stop_trail === "string" ? JSON.parse(currentTrade.stop_trail || "[]") : (currentTrade.stop_trail || []);
    if (Array.isArray(rawT)) trailPts = rawT;
  } catch {}
  if (trailPts.length) {
    const lastVisibleTs = bars[bars.length - 1].t.slice(0, 16);
    const visTrail = trailPts.filter(([tsStr]) => String(tsStr).slice(0, 16) <= lastVisibleTs);
    for (let k = 0; k < visTrail.length; k++) {
      const [ts0, sl0] = visTrail[k];
      const i0 = Math.max(0, bars.findIndex(b => b.t.slice(0, 16) >= String(ts0).slice(0, 16)));
      const i1 = (k + 1 < visTrail.length)
        ? Math.max(i0, bars.findIndex(b => b.t.slice(0, 16) >= String(visTrail[k + 1][0]).slice(0, 16)))
        : bars.length - 1;
      const ysl = my(sl0);
      if (ysl >= T && ysl <= H - B) {
        out += `<line x1="${mx(i0)}" y1="${ysl}" x2="${mx(i1)}" y2="${ysl}" stroke="#f97316" stroke-width="1.8" stroke-dasharray="4,3"/>`;
        out += `<text x="${mx(i0) + 4}" y="${ysl - 4}" font-size="10" font-weight="700" fill="#f97316">T${k + 1} (${Number(sl0).toFixed(2)})</text>`;
      }
    }
  }

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
        ? ` | <tspan fill="${EMA_COLORS.ema9}">E9:${hudBar.ema9 != null ? hudBar.ema9.toFixed(1) : "-"}</tspan> <tspan fill="${EMA_COLORS.ema21}">E21:${hudBar.ema21 != null ? hudBar.ema21.toFixed(1) : "-"}</tspan> <tspan fill="${EMA_COLORS.ema50}">E50:${hudBar.ema50 != null ? hudBar.ema50.toFixed(1) : "-"}</tspan>`
        : "";
      h += `<text x="${P + 4}" y="18" font-size="11" font-weight="600" fill="${hudTextCol}">${hudBar.t.slice(0, 16).replace("T", " ")} | O:${Number(hudBar.o).toFixed(2)} H:${Number(hudBar.h).toFixed(2)} L:${Number(hudBar.l).toFixed(2)} C:${Number(hudBar.c).toFixed(2)} <tspan fill="${chgCol}">(${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%)</tspan> V:${Math.round(hudBar.v || 0).toLocaleString()}${eTxt}</text>`;
    }

    const p2 = anchorB || (anchorA ? cur : null);
    if (anchorA && p2) {
      const aLocal = anchorA.gIdx - viewStart;
      const bLocal = p2.gIdx - viewStart;
      const ax = mx(aLocal), ay = my(anchorA.price);
      const bx2 = mx(bLocal), by2 = my(p2.price);
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
      h += `<rect x="${boxX}" y="${boxY}" width="210" height="30" rx="5" fill="#0f172a" opacity="0.94"/>`;
      h += `<text x="${boxX + 105}" y="${boxY + 13}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#fff">${dp >= 0 ? "+" : ""}${dp.toFixed(2)} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)</text>`;
      h += `<text x="${boxX + 105}" y="${boxY + 25}" font-size="10" text-anchor="middle" fill="#cbd5e1">${nBars} bars | ${dur}</text>`;
    }

    if (cur) {
      const b = bars[cur.localIdx];
      h += `<line x1="${cur.x}" y1="${T}" x2="${cur.x}" y2="${H - B}" stroke="#64748b" stroke-width="0.9" stroke-dasharray="3,3"/>`;
      h += `<line x1="${P}" y1="${cur.y}" x2="${W - R}" y2="${cur.y}" stroke="#64748b" stroke-width="0.9" stroke-dasharray="3,3"/>`;
      h += `<rect x="4" y="${cur.y - 9}" width="56" height="18" rx="3" fill="#0f172a"/><text x="32" y="${cur.y + 4}" font-size="10" text-anchor="middle" fill="#fff">${cur.price.toFixed(2)}</text>`;
      const lx = Math.min(W - 120, Math.max(P, cur.x - 55));
      h += `<rect x="${lx}" y="${H - B + 2}" width="110" height="16" rx="3" fill="#0f172a"/><text x="${lx + 55}" y="${H - B + 13}" font-size="9.5" text-anchor="middle" fill="#fff">${b.t.slice(5, 16).replace("T", " ")}</text>`;
    }
    // Draggable Trade Journey Callouts (Entries, Pyramid Adds, Partial Exits, Final Exit)
    let evList = [];
    try {
      const rawE = typeof currentTrade.events === "string" ? JSON.parse(currentTrade.events || "[]") : (currentTrade.events || []);
      if (Array.isArray(rawE)) evList = rawE;
    } catch {}
    if (!evList.length) {
      if (currentTrade.entry_ts) evList.push({ ts: currentTrade.entry_ts, price: currentTrade.avg_entry, label: `E1 @ ${Number(currentTrade.avg_entry || 0).toFixed(2)}`, kind: "entry" });
      if (currentTrade.exit_ts) evList.push({ ts: currentTrade.exit_ts, price: currentTrade.avg_exit, label: `Exit @ ${Number(currentTrade.avg_exit || 0).toFixed(2)}`, kind: "exit" });
    }
    const lastVis = bars[bars.length - 1].t.slice(0, 16);
    evList.forEach((ev, idx) => {
      const k = String(ev.ts || "").slice(0, 16);
      if (!k || k > lastVis) return;
      const bIdx = bars.findIndex(b => b.t.slice(0, 16) >= k);
      if (bIdx < 0) return;
      const ax = mx(bIdx), ay = my(ev.price);
      const cid = "c_" + idx;
      const off = calloutOffsets[cid] || { dx: (idx % 2 === 0 ? -55 : 55), dy: -34 - (idx % 3) * 22 };
      const bx = Math.max(P + 4, Math.min(W - R - 134, ax + off.dx));
      const by = Math.max(T + 4, Math.min(H - B - 24, ay + off.dy));
      const fill = ev.kind === "entry" ? "#1d4ed8" : ev.kind === "add" ? "#7c3aed" : ev.kind === "partial_exit" ? "#059669" : "#b45309";
      h += `<line x1="${ax}" y1="${ay}" x2="${bx + 65}" y2="${by + 10}" stroke="${fill}" stroke-width="1" stroke-dasharray="2,2"/>`;
      h += `<circle cx="${ax}" cy="${ay}" r="3.5" fill="${fill}" stroke="#fff" stroke-width="1"/>`;
      h += `<g data-callout="${cid}" style="cursor:move;"><rect x="${bx}" y="${by}" width="132" height="20" rx="5" fill="${fill}" opacity="0.95"/><text x="${bx + 66}" y="${by + 13.5}" font-size="10" font-weight="700" text-anchor="middle" fill="#fff">${ev.label}</text></g>`;
    });

    overlay.innerHTML = h;
  };

  drawOverlay(lastMouse);

  let dragStartX = null;
  let dragStartView = 0;
  let didDrag = false;

  let dragCalloutId = null;
  let dragCalloutStart = null;
  svg.onmousedown = evt => {
    if (evt.button !== 0) return;
    const cg = evt.target && evt.target.closest ? evt.target.closest("[data-callout]") : null;
    if (cg) {
      dragCalloutId = cg.getAttribute("data-callout");
      const rect = svg.getBoundingClientRect();
      dragCalloutStart = {
        x: evt.clientX, y: evt.clientY,
        sx: W / Math.max(1, rect.width), sy: H / Math.max(1, rect.height),
        base: { ...(calloutOffsets[dragCalloutId] || { dx: 0, dy: -36 }) },
      };
      return;
    }
    dragStartX = evt.clientX;
    dragStartView = viewStart;
    didDrag = false;
    svg.style.cursor = "grabbing";
  };

  svg.onmousemove = evt => {
    if (dragCalloutId && dragCalloutStart) {
      const dx = (evt.clientX - dragCalloutStart.x) * dragCalloutStart.sx;
      const dy = (evt.clientY - dragCalloutStart.y) * dragCalloutStart.sy;
      calloutOffsets[dragCalloutId] = { dx: dragCalloutStart.base.dx + dx, dy: dragCalloutStart.base.dy + dy };
      drawOverlay(lastMouse);
      return;
    }
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
    if (dragCalloutId) { dragCalloutId = null; dragCalloutStart = null; return; }
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