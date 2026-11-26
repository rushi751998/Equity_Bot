let AVAILABLE_CONFIGS = [];
let AVAILABLE_SYMBOLS = [];
let SELECTED_CONFIGS = new Set();
let SELECTED_SYMBOLS = new Set();

async function initRunner() {
  const [cRes, sRes] = await Promise.all([
    fetch("/api/configs").then(r => r.json()).catch(() => ({ configs: [] })),
    fetch("/api/symbols").then(r => r.json()).catch(() => ({ symbols: [] })),
  ]);
  AVAILABLE_CONFIGS = cRes.configs || [];
  AVAILABLE_SYMBOLS = sRes.symbols || [];
  if (AVAILABLE_CONFIGS.length) SELECTED_CONFIGS.add(AVAILABLE_CONFIGS[0]);
  AVAILABLE_SYMBOLS.forEach(s => SELECTED_SYMBOLS.add(s));
  renderRunner();
}

function renderRunner() {
  const root = document.getElementById("runnerRoot");
  if (!root) return;
  root.innerHTML = `
    <div class="card">
      <div class="card-head">
        <div><h2 class="card-title">1. Select Tickers (${SELECTED_SYMBOLS.size}/${AVAILABLE_SYMBOLS.length})</h2></div>
        <div style="display:flex;gap:6px;">
          <button class="btn" onclick="AVAILABLE_SYMBOLS.forEach(s=>SELECTED_SYMBOLS.add(s));renderRunner()">Select All</button>
          <button class="btn" onclick="SELECTED_SYMBOLS.clear();renderRunner()">Clear</button>
        </div>
      </div>
      <div class="form-grid">${AVAILABLE_SYMBOLS.map(s => `<label class="muted"><input type="checkbox" ${SELECTED_SYMBOLS.has(s) ? "checked" : ""} onchange="if(this.checked)SELECTED_SYMBOLS.add('${s}');else SELECTED_SYMBOLS.delete('${s}');renderRunner()"> <b>${s}</b></label>`).join("")}</div>
    </div>
    <div class="card">
      <div class="card-head">
        <div><h2 class="card-title">2. Scenario Library</h2></div>
        <button class="btn primary" onclick="runSelectedBatch()">Run Selected (${SELECTED_CONFIGS.size})</button>
      </div>
      <div class="sc-grid">${AVAILABLE_CONFIGS.map(c => `<div class="sc-card ${SELECTED_CONFIGS.has(c) ? "selected" : ""}">
        <label><input type="checkbox" ${SELECTED_CONFIGS.has(c) ? "checked" : ""} onchange="if(this.checked)SELECTED_CONFIGS.add('${c}');else SELECTED_CONFIGS.delete('${c}');renderRunner()"> <b>${c.split("/").pop()}</b></label>
        <div style="display:flex;gap:6px;"><button class="btn danger" onclick="deleteCfg('${c}')">Delete</button></div>
      </div>`).join("")}</div>
      <div id="rnStatus" class="muted" style="margin-top:10px;"></div>
      <pre id="rnLogs" class="log-box" style="display:none;margin-top:8px;"></pre>
    </div>`;
}

async function deleteCfg(cfgPath) {
  await fetch("/api/config/delete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: cfgPath.split("/").pop() }) });
  AVAILABLE_CONFIGS = AVAILABLE_CONFIGS.filter(c => c !== cfgPath);
  SELECTED_CONFIGS.delete(cfgPath);
  renderRunner();
}

async function runSelectedBatch() {
  const stEl = document.getElementById("rnStatus"), logEl = document.getElementById("rnLogs");
  if (!SELECTED_CONFIGS.size) { stEl.textContent = "Select at least one scenario."; return; }
  await fetch("/api/run_batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ configs: [...SELECTED_CONFIGS], symbols: [...SELECTED_SYMBOLS], session_name: getActiveSession() }),
  });
  logEl.style.display = "block";
  const timer = setInterval(async () => {
    const st = await (await fetch("/api/status")).json();
    stEl.textContent = st.last_error ? "Error: " + st.last_error : st.message;
    logEl.textContent = (st.logs || []).join("\n");
    if (!st.running) { clearInterval(timer); if (!st.last_error) window.location.href = "/backtest/simulator"; }
  }, 700);
}

document.addEventListener("DOMContentLoaded", initRunner);
