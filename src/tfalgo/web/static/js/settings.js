let ACCOUNT_STATUS_MAP = {};
let BROKER_ACCOUNTS = [];
let TG_BOTS = [];

const THEME_PRESETS = {
  midnight: { bg: "#0b1120", card: "#111827", primary: "#2563eb" },
  oled: { bg: "#000000", card: "#0a0a0a", primary: "#3b82f6" },
  charcoal: { bg: "#18181b", card: "#27272a", primary: "#6366f1" },
  emerald: { bg: "#04100d", card: "#0a1f1a", primary: "#10b981" },
};

function applyPresetTheme(name) {
  const p = THEME_PRESETS[name];
  if (!p) return;
  document.getElementById("th_bg").value = p.bg;
  document.getElementById("th_card").value = p.card;
  document.getElementById("th_primary").value = p.primary;
  previewCustomTheme();
}

function previewCustomTheme() {
  const tc = {
    bg: document.getElementById("th_bg").value,
    card: document.getElementById("th_card").value,
    primary: document.getElementById("th_primary").value,
  };
  localStorage.setItem("tfalgo_theme_colors_v1", JSON.stringify(tc));
  if (window.applyCustomThemeColors) window.applyCustomThemeColors(tc);
}

async function loadSettingsUI() {
  const res = await (await fetch("/api/settings")).json();
  const s = res.settings || {};
  document.getElementById("st_active_broker").value = s.active_broker || "paper";
  document.getElementById("st_sync_sec").value = s.sync_interval_sec ?? 10;
  document.getElementById("st_chase_sec").value = s.chase_interval_sec ?? 5;
  document.getElementById("st_chase_retries").value = s.chase_max_retries ?? 2;
  document.getElementById("st_chase_slip").value = s.chase_max_slip_pct ?? 0.5;
  document.getElementById("st_direct_mkt").value = s.direct_market_exit !== false ? "1" : "0";
  document.getElementById("st_auto_sl").value = s.auto_replace_missing_sl !== false ? "1" : "0";
  document.getElementById("st_paper_cap").value = s.paper_capital ?? 1000000;
  document.getElementById("st_mongo_uri").value = s.mongo_uri || "";
  document.getElementById("st_mongo_db").value = s.mongo_db || "tfalgo_live";

  if (s.theme_colors) {
    document.getElementById("th_bg").value = s.theme_colors.bg || "#0b1120";
    document.getElementById("th_card").value = s.theme_colors.card || "#111827";
    document.getElementById("th_primary").value = s.theme_colors.primary || "#2563eb";
  }

  const b = s.brokers || {};
  document.getElementById("br_z_key").value = b.zerodha?.api_key || "";
  document.getElementById("br_z_sec").value = b.zerodha?.api_secret || "";
  document.getElementById("br_z_totp").value = b.zerodha?.totp_secret || "";
  document.getElementById("br_z_tok").value = b.zerodha?.access_token || "";
  document.getElementById("br_f_id").value = b.fyers?.app_id || "";
  document.getElementById("br_f_sec").value = b.fyers?.secret_key || "";
  document.getElementById("br_f_totp").value = b.fyers?.totp_secret || "";
  document.getElementById("br_f_tok").value = b.fyers?.access_token || "";
  document.getElementById("br_k_key").value = b.kotak_neo?.consumer_key || "";
  document.getElementById("br_k_sec").value = b.kotak_neo?.consumer_secret || "";
  document.getElementById("br_k_totp").value = b.kotak_neo?.totp_secret || "";
  document.getElementById("br_k_tok").value = b.kotak_neo?.access_token || "";

  TG_BOTS = s.telegram_bots || [];
  BROKER_ACCOUNTS = s.accounts || [];
  renderAccountsManager();
  checkAccountsStatus();
  renderTgBots();
}


function renderAccountsManager() {
  const box = document.getElementById("accountsManagerBox");
  if (!box) return;
  box.innerHTML = BROKER_ACCOUNTS.map((a, i) => `
    <div style="border:1px solid var(--border);border-radius:8px;padding:10px;background:var(--card-alt);display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;align-items:end;">
      <div class="field"><label>Account ID</label><input value="${a.account_id || ""}" oninput="BROKER_ACCOUNTS[${i}].account_id=this.value"></div>
      <div class="field"><label>User Name</label><input value="${a.user_name || ""}" oninput="BROKER_ACCOUNTS[${i}].user_name=this.value"></div>
      <div class="field"><label>Broker</label><select onchange="BROKER_ACCOUNTS[${i}].broker=this.value"><option value="paper" ${a.broker==="paper"?"selected":""}>Paper</option><option value="zerodha" ${a.broker==="zerodha"?"selected":""}>Zerodha</option><option value="fyers" ${a.broker==="fyers"?"selected":""}>Fyers</option><option value="kotak_neo" ${a.broker==="kotak_neo"?"selected":""}>Kotak Neo</option></select></div>
      <div class="field"><label>API Key</label><input type="password" value="${a.api_key || ""}" oninput="BROKER_ACCOUNTS[${i}].api_key=this.value"></div>
      <div class="field"><label>Access Token</label><input type="password" value="${a.access_token || ""}" oninput="BROKER_ACCOUNTS[${i}].access_token=this.value"></div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <span id="acct_st_${a.account_id}" title="${(ACCOUNT_STATUS_MAP[a.account_id]?.detail || "")}" style="font-size:12px;font-weight:700;color:${ACCOUNT_STATUS_MAP[a.account_id]?.connected ? "#10b981" : "#ef4444"};">${ACCOUNT_STATUS_MAP[a.account_id] ? (ACCOUNT_STATUS_MAP[a.account_id].connected ? "✅" : "❌") : "⏳"}</span>
        <label class="muted" style="font-size:11.5px;"><input type="radio" name="tickSrc" ${a.is_tick_source?"checked":""} onchange="BROKER_ACCOUNTS.forEach((x,j)=>x.is_tick_source=(j===${i}))"> Tick Source</label>
        <button type="button" class="btn danger" style="padding:4px 8px;" onclick="BROKER_ACCOUNTS.splice(${i},1);renderAccountsManager()">×</button>
      </div>
    </div>`).join("");
}

function addBrokerAccount() {
  BROKER_ACCOUNTS.push({ account_id: `ACCT_${BROKER_ACCOUNTS.length + 1}`, user_name: "Trader", broker: "zerodha", api_key: "", api_secret: "", totp_secret: "", access_token: "", is_tick_source: false });
  renderAccountsManager();
}

function renderTgBots() {
  const c = document.getElementById("tgBotsContainer");
  if (!c) return;
  c.innerHTML = TG_BOTS.map((b, i) => `
    <div style="border:1px solid var(--border);border-radius:8px;padding:10px;background:var(--card-alt);">
      <div style="font-weight:700;font-size:12px;margin-bottom:6px;">Bot ${i + 1}: ${b.name || "Alert Bot"}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px;">
        <input placeholder="Bot Token" value="${b.token || ""}" oninput="TG_BOTS[${i}].token=this.value">
        <input placeholder="Chat ID" value="${b.chat_id || ""}" oninput="TG_BOTS[${i}].chat_id=this.value">
      </div>
      <div style="display:flex;gap:6px;">
        <input id="tg_msg_${i}" placeholder="Custom test message..." value="Test ping for Bot ${i + 1}" style="flex:1;">
        <button type="button" class="btn primary" onclick="testSingleTelegram(${i})">Test Bot ${i + 1}</button>
      </div>
    </div>`).join("");
}

async function testSingleTelegram(idx) {
  await saveAllSettings(true);
  const msg = document.getElementById(`tg_msg_${idx}`)?.value || "Test ping";
  const res = await (await fetch("/api/settings/telegram_test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bot_index: idx, message: msg }),
  })).json();
  alert(`Bot ${idx + 1} Result: ` + JSON.stringify(res.results));
}

async function testMongoInit() {
  const res = await (await fetch("/api/settings/mongo_test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mongo_uri: document.getElementById("st_mongo_uri").value,
      mongo_db: document.getElementById("st_mongo_db").value,
    }),
  })).json();
  document.getElementById("mongoStatusMsg").textContent = res.ok
    ? `MongoDB OK (${res.db}) — Created: [${(res.created || []).join(", ") || "none"}], Total Collections: ${(res.collections || []).length}`
    : `MongoDB Error: ${res.error}`;
}

async function openKiteLogin() {
  const res = await (await fetch("/api/settings/zerodha/login_url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: document.getElementById("br_z_key").value }),
  })).json();
  if (!res.ok) { alert(res.error); return; }
  window.open(res.url, "_blank");
}

async function exchangeKiteToken() {
  const res = await (await fetch("/api/settings/zerodha/exchange_token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      api_key: document.getElementById("br_z_key").value,
      api_secret: document.getElementById("br_z_sec").value,
      request_token: document.getElementById("br_z_req_tok").value,
    }),
  })).json();
  if (res.ok) {
    document.getElementById("br_z_tok").value = res.access_token;
    alert("Zerodha Access Token saved to .env!");
  } else {
    alert("Exchange failed: " + res.error);
  }
}

async function saveAllSettings(silent = false) {
  const payload = {
    active_broker: document.getElementById("st_active_broker").value,
    sync_interval_sec: parseInt(document.getElementById("st_sync_sec").value || "10", 10),
    chase_interval_sec: parseInt(document.getElementById("st_chase_sec").value || "5", 10),
    chase_max_retries: parseInt(document.getElementById("st_chase_retries").value || "2", 10),
    chase_max_slip_pct: parseFloat(document.getElementById("st_chase_slip").value || "0.5"),
    direct_market_exit: document.getElementById("st_direct_mkt").value === "1",
    auto_replace_missing_sl: document.getElementById("st_auto_sl").value === "1",
    paper_capital: parseFloat(document.getElementById("st_paper_cap").value || "1000000"),
    mongo_uri: document.getElementById("st_mongo_uri").value,
    mongo_db: document.getElementById("st_mongo_db").value,
    theme_colors: {
      bg: document.getElementById("th_bg").value,
      card: document.getElementById("th_card").value,
      primary: document.getElementById("th_primary").value,
    },
    telegram_bots: TG_BOTS,
    accounts: BROKER_ACCOUNTS,
    brokers: {
      zerodha: { api_key: document.getElementById("br_z_key").value, api_secret: document.getElementById("br_z_sec").value, totp_secret: document.getElementById("br_z_totp").value, access_token: document.getElementById("br_z_tok").value },
      fyers: { app_id: document.getElementById("br_f_id").value, secret_key: document.getElementById("br_f_sec").value, totp_secret: document.getElementById("br_f_totp").value, access_token: document.getElementById("br_f_tok").value },
      kotak_neo: { consumer_key: document.getElementById("br_k_key").value, consumer_secret: document.getElementById("br_k_sec").value, totp_secret: document.getElementById("br_k_totp").value, access_token: document.getElementById("br_k_tok").value },
    },
  };
  const res = await (await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })).json();
  if (!silent) document.getElementById("st_save_msg").textContent = res.ok ? "Settings saved to .env!" : "Save failed.";
}

async function generatePyotp() {
  const res = await (await fetch("/api/settings/pyotp_setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ secret: document.getElementById("pyotp_secret").value }) })).json();
  document.getElementById("pyotp_secret").value = res.secret || "";
  document.getElementById("pyotp_now").value = res.current_code || "";
  document.getElementById("pyotp_uri").textContent = res.provisioning_uri ? "Authenticator URI: " + res.provisioning_uri : "";
}

async function verifyPyotp() {
  const res = await (await fetch("/api/settings/pyotp_verify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ secret: document.getElementById("pyotp_secret").value, code: document.getElementById("pyotp_check").value }) })).json();
  alert(res.ok ? "PyOTP Verified!" : "Invalid 6-digit code.");
}

document.addEventListener("DOMContentLoaded", loadSettingsUI);


async function checkAccountsStatus() {
  try {
    const res = await (await fetch("/api/settings/accounts_status")).json();
    if (!res.ok) return;
    ACCOUNT_STATUS_MAP = {};
    (res.statuses || []).forEach(s => { ACCOUNT_STATUS_MAP[s.account_id] = s; });
    renderAccountsManager();
  } catch {}
}
