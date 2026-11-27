const STORAGE_KEY_ACTIVE_SESSION = "tfalgo_active_session_v1";
const STORAGE_KEY_SESSIONS = "tfalgo_sessions_v1";
const STORAGE_KEY_THEME = "tfalgo_theme_v1";

function isDarkMode() {
  return document.documentElement.classList.contains("tf-dark");
}

function applyCustomThemeColors(tc) {
  if (!tc || !isDarkMode()) return;
  const r = document.documentElement.style;
  if (tc.bg) r.setProperty("--bg", tc.bg);
  if (tc.card) r.setProperty("--card", tc.card);
  if (tc.primary) r.setProperty("--primary", tc.primary);
}
window.applyCustomThemeColors = applyCustomThemeColors;

function toggleTheme() {
  const dark = !isDarkMode();
  document.documentElement.classList.toggle("tf-dark", dark);
  localStorage.setItem(STORAGE_KEY_THEME, dark ? "dark" : "light");
  const btn = document.getElementById("themeToggleBtn");
  if (btn) btn.textContent = dark ? "☀️ Light" : "🌙 Dark";
  if (!dark) {
    ["--bg", "--card", "--primary"].forEach(k => document.documentElement.style.removeProperty(k));
  } else {
    try { applyCustomThemeColors(JSON.parse(localStorage.getItem("tfalgo_theme_colors_v1") || "null")); } catch {}
  }
  if (typeof window.onThemeChanged === "function") window.onThemeChanged();
}

function getActiveSession() {
  return localStorage.getItem(STORAGE_KEY_ACTIVE_SESSION) || "Session_1";
}

function setActiveSession(name) {
  localStorage.setItem(STORAGE_KEY_ACTIVE_SESSION, name);
  const sel = document.getElementById("globalSessionSelect");
  if (sel) sel.value = name;
  if (typeof window.onSessionChanged === "function") window.onSessionChanged(name);
}

async function initCoreHeader() {
  const btn = document.getElementById("themeToggleBtn");
  if (btn) btn.textContent = isDarkMode() ? "☀️ Light" : "🌙 Dark";

  const sel = document.getElementById("globalSessionSelect");
  if (sel) {
    try {
      const data = await (await fetch("/api/runs")).json();
      const runs = data.runs || [];
      const sessions = JSON.parse(localStorage.getItem(STORAGE_KEY_SESSIONS) || "{}");
      const names = [...new Set(["Session_1", ...Object.keys(sessions), ...runs])];
      const cur = getActiveSession();
      sel.innerHTML = names.map(n => `<option value="${n}" ${n === cur ? "selected" : ""}>${n}</option>`).join("");
      sel.onchange = () => setActiveSession(sel.value);
    } catch {}
  }

  const pollHealth = async () => {
    try {
      const h = await (await fetch("/api/health")).json();
      const badge = document.getElementById("healthBadge");
      if (badge) badge.textContent = `Sync: ${h.last_sync_ts || "live"}`;
    } catch {}
  };
  pollHealth();
  setInterval(pollHealth, 10000);
}

async function panicFlattenAll() {
  if (!confirm("PANIC FLATTEN ALL: Exit every open position at MARKET and cancel all pending orders?")) return;
  const res = await (await fetch("/api/portfolio/flatten", { method: "POST" })).json();
  alert(`Flattened ${res.exited || 0} position(s).`);
  if (typeof window.refreshPortfolio === "function") window.refreshPortfolio();
}


const HELP_DICT = {
  "Symbol": "NSE ticker symbol (e.g. RELIANCE, INFY).",
  "Side": "BUY for Long trades; SELL for Short trades (enforced MIS intraday).",
  "Product": "MIS = Intraday square-off; CNC = Delivery multi-day swing.",
  "% Capital Invest": "Maximum % of total capital allocated to this single position.",
  "Limit Price (₹)": "Initial entry limit price; chased every 5s if LTP is within max slip.",
  "Stop Loss": "Protective stop price (₹) or % distance from entry. Triggers SL-M order.",
  "Target Price (₹)": "Primary profit target price used for R:R calculation.",
  "Quantity (Shares)": "Auto-calculated from Risk % and % Capital Invest cap.",
  "Capital (₹)": "Total trading capital used for sizing and % risk calculations.",
  "Risk % / Trade": "Max % of capital risked per trade (1R budget).",
  "Assumed Win Rate %": "Expected win rate used for Expectancy & Kelly math.",
  "Avg Win (R) / Loss (R)": "Expected average winner and loser in R-multiples.",
  "Round-Trip Cost %": "Estimated brokerage, STT, taxes & slippage round-trip %.",
  "Target Profit (₹)": "Goal profit amount used to compute Trades Needed.",
  "Slippage %/side": "Simulated slippage applied per entry and exit side.",
  "Broker Sync Interval (sec)": "How often the background watchdog checks positions, SLs & alerts.",
  "Limit Chase Interval (sec)": "Seconds between limit price modifications on unfilled orders.",
  "Chase Max Retries": "Max limit modifications before converting to Market or cancelling.",
  "Chase Max Slip %": "Max % price drift allowed during limit chase before aborting entry.",
  "Active Broker": "Paper (built-in simulator) or live broker adapter from .env.",
  "MongoDB URI": "Optional MongoDB connection string for permanent trade/journal/audit storage.",
  "Risk Amount per Trade (₹)": "1R cash risk budget = Capital × Risk %.",
  "Position Size Needed (₹)": "Uncapped position size required to risk exactly 1R.",
  "Position Size Applied (₹, Capped)": "Actual position size after applying % Capital Invest cap.",
  "Breakeven Win Rate (%)": "Minimum win rate needed so Expectancy = 0.",
  "Expectancy (R-Multiples)": "Average net R earned per trade after costs.",
  "VERDICT": "Quick edge rating based on Expectancy, Log-Growth, and R:R.",
  "Live R": "Running campaign R = (Realized Partial P&L + Open MTM) / Initial Risk.",
  "Risk (₹ / %)": "Open downside risk to current SL in ₹ and % of equity.",
  "Open Risk (Heat)": "Sum of open risk across all active positions.",
};

function openUserGuide() {
  document.getElementById("userGuideModal")?.classList.add("open");
}

function attachHelpIcons(root = document) {
  root.querySelectorAll("label, th, .kpi .lbl").forEach(el => {
    if (el.querySelector(".tf-help-icon")) return;
    const raw = (el.childNodes[0]?.nodeType === 3 ? el.childNodes[0].textContent : el.textContent || "").trim();
    const key = Object.keys(HELP_DICT).find(k => raw === k || raw.startsWith(k));
    if (key) {
      const sp = document.createElement("span");
      sp.className = "tf-help-icon";
      sp.tabIndex = 0;
      sp.textContent = "i";
      sp.setAttribute("data-help", HELP_DICT[key]);
      el.appendChild(sp);
    }
  });
}
window.attachHelpIcons = attachHelpIcons;

document.addEventListener("DOMContentLoaded", () => { initCoreHeader(); attachHelpIcons(); });
