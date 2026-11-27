let EXIT_MODE = localStorage.getItem("tfalgo_exit_mode") || "pct";
let SL_MODE = "px";
let PERF_FILTER = "all"; // all | closed | running
let PORT_CU_UNIT = "pct";
let TARGET_LEGS = [
  { qtyVal: 50, qtyUnit: "pct", pxVal: 3, pxUnit: "r" },
  { qtyVal: 50, qtyUnit: "pct", pxVal: 6, pxUnit: "r" },
];
let EXIT_INPUT_VALS = {};
let LAST_POSITIONS = [];
let LAST_CLOSED = [];
let LAST_ORDERS = [];
let LAST_SNAPS = [];
let JOURNAL_KEYS = new Set();
let LAST_EQUITY = 1000000;
let REC_SORT_COL = "ts";
let REC_SORT_ASC = false;
let ACTIVE_JOURNAL_KEY = "";
let PENDING_JOURNAL_IMG = "";

function openOrderModal(skipLtp = false) { document.getElementById("orderModal")?.classList.add("open"); recalcOrderTicket(); if (!skipLtp) fetchOrderLtp(true); }
function closeOrderModal() { document.getElementById("orderModal")?.classList.remove("open"); }
function closeLiveTradeModal() { document.getElementById("liveTradeModal")?.classList.remove("open"); }

function openImageLightbox(src) {
  const lb = document.getElementById("imgLightbox");
  const img = document.getElementById("imgLightboxImg");
  if (lb && img && src) { img.src = src; lb.classList.add("open"); }
}

function showTradeModalTab(tab) {
  document.getElementById("ltSecOrders").style.display = tab === "orders" ? "block" : "none";
  document.getElementById("ltSecComments").style.display = tab === "comments" ? "block" : "none";
  document.getElementById("ltTabOrdersBtn").className = "btn" + (tab === "orders" ? " primary" : "");
  document.getElementById("ltTabCommentsBtn").className = "btn" + (tab === "comments" ? " primary" : "");
}

function showPortSection(name, btn) {
  document.querySelectorAll(".port-sec").forEach(el => { el.style.display = "none"; });
  document.getElementById("psec_" + name)?.style.setProperty("display", "block");
  document.querySelectorAll(".port-subtab").forEach(b => { b.className = "btn port-subtab"; });
  if (btn) btn.className = "btn primary port-subtab";
  if (name === "funds") refreshFunds();
}

document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    const lb = document.getElementById("imgLightbox");
    if (lb && lb.classList.contains("open")) { lb.classList.remove("open"); return; }
    closeOrderModal();
    closeLiveTradeModal();
    document.getElementById("userGuideModal")?.classList.remove("open");
  }
});

function setSlMode(mode) {
  SL_MODE = mode;
  document.getElementById("slModePxBtn").className = "btn" + (mode === "px" ? " primary" : "");
  document.getElementById("slModePctBtn").className = "btn" + (mode === "pct" ? " primary" : "");
  const slInp = document.getElementById("ord_sl");
  const entry = parseFloat(document.getElementById("ord_price")?.value || "100") || 100;
  if (mode === "pct" && parseFloat(slInp.value) > 25) slInp.value = "1.0";
  if (mode === "px" && parseFloat(slInp.value) <= 25) slInp.value = (entry * 0.99).toFixed(2);
  recalcOrderTicket();
}

function getResolvedStop(entry, side) {
  const raw = parseFloat(document.getElementById("ord_sl")?.value || "0") || 0;
  if (SL_MODE === "px") return raw;
  const frac = raw / 100.0;
  return side === "BUY" ? entry * (1 - frac) : entry * (1 + frac);
}

function recalcOrderTicket() {
  const cap = Math.max(1, LAST_EQUITY || 1000000);
  const invPct = parseFloat(document.getElementById("ord_cap_pct")?.value || "5") || 5;
  const entry = Math.max(0.05, parseFloat(document.getElementById("ord_price")?.value || "100") || 100);
  const side = document.getElementById("ord_side")?.value || "BUY";
  const sl = getResolvedStop(entry, side);
  const tgt = parseFloat(document.getElementById("ord_target")?.value || "0") || entry;

  const slLbl = document.getElementById("slResolvedLbl");
  if (slLbl) slLbl.textContent = SL_MODE === "pct" ? `Resolved SL: ₹${sl.toFixed(2)}` : `${(Math.abs(entry - sl) / entry * 100).toFixed(2)}% from entry`;

  if (document.activeElement?.id !== "ord_qty") {
    const q = Math.max(1, Math.floor((cap * (invPct / 100)) / entry));
    const qEl = document.getElementById("ord_qty");
    if (qEl) qEl.value = q;
  }
  const qty = parseInt(document.getElementById("ord_qty")?.value || "1", 10) || 1;
  const posVal = qty * entry;
  const riskPerShare = Math.abs(entry - sl);
  const riskInr = qty * riskPerShare;
  const riskPct = (riskInr / cap) * 100;
  const rr = riskPerShare > 0 ? Math.abs(tgt - entry) / riskPerShare : 0;

  const bar = document.getElementById("ordRiskBar");
  if (bar) {
    bar.innerHTML = `<span><b>Position:</b> ₹${Math.round(posVal).toLocaleString()} (${(posVal / cap * 100).toFixed(2)}%)</span><span><b>Risk:</b> ₹${Math.round(riskInr).toLocaleString()} (${riskPct.toFixed(2)}%)</span><span><b>R:R:</b> 1 : ${rr.toFixed(2)}</span>`;
  }
  renderTargetLegs();
}

function renderTargetLegs() {
  const box = document.getElementById("targetLegsBox");
  if (!box) return;
  const entry = parseFloat(document.getElementById("ord_price")?.value || "100") || 100;
  const side = document.getElementById("ord_side")?.value || "BUY";
  const sl = getResolvedStop(entry, side);
  const rUnit = Math.max(0.05, Math.abs(entry - sl));
  const totQty = parseInt(document.getElementById("ord_qty")?.value || "1", 10) || 1;
  box.innerHTML = TARGET_LEGS.map((leg, i) => {
    const q = leg.qtyUnit === "pct" ? Math.max(1, Math.round(totQty * (leg.qtyVal / 100))) : Math.round(leg.qtyVal);
    let px = leg.pxVal;
    if (leg.pxUnit === "pct") px = side === "BUY" ? entry * (1 + leg.pxVal / 100) : entry * (1 - leg.pxVal / 100);
    if (leg.pxUnit === "r") px = side === "BUY" ? entry + leg.pxVal * rUnit : entry - leg.pxVal * rUnit;
    return `<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:12px;"><b>T${i + 1}:</b>
      <input type="number" step="1" value="${leg.qtyVal}" oninput="TARGET_LEGS[${i}].qtyVal=parseFloat(this.value)||0;renderTargetLegs()" style="width:56px;padding:4px;">
      <select onchange="TARGET_LEGS[${i}].qtyUnit=this.value;renderTargetLegs()" style="padding:4px;"><option value="pct" ${leg.qtyUnit === "pct" ? "selected" : ""}>% Qty</option><option value="qty" ${leg.qtyUnit === "qty" ? "selected" : ""}>Shares</option></select>
      <span>@</span>
      <input type="number" step="0.05" value="${leg.pxVal}" oninput="TARGET_LEGS[${i}].pxVal=parseFloat(this.value)||0;renderTargetLegs()" style="width:66px;padding:4px;">
      <select onchange="TARGET_LEGS[${i}].pxUnit=this.value;renderTargetLegs()" style="padding:4px;"><option value="px" ${leg.pxUnit === "px" ? "selected" : ""}>₹</option><option value="pct" ${leg.pxUnit === "pct" ? "selected" : ""}>%</option><option value="r" ${leg.pxUnit === "r" ? "selected" : ""}>R</option></select>
      <span class="muted">(${q} sh @ ₹${px.toFixed(2)})</span>
      <button type="button" class="btn" style="padding:2px 7px;" onclick="TARGET_LEGS.splice(${i},1);renderTargetLegs()">×</button></div>`;
  }).join("") || `<span class="muted" style="font-size:11.5px;">No partial target legs.</span>`;
}

function addTargetLeg() { TARGET_LEGS.push({ qtyVal: 33, qtyUnit: "pct", pxVal: 3, pxUnit: "r" }); renderTargetLegs(); }

function resolveTargetLegs() {
  const entry = parseFloat(document.getElementById("ord_price")?.value || "100") || 100;
  const side = document.getElementById("ord_side")?.value || "BUY";
  const sl = getResolvedStop(entry, side);
  const rUnit = Math.max(0.05, Math.abs(entry - sl));
  const totQty = parseInt(document.getElementById("ord_qty")?.value || "1", 10) || 1;
  return TARGET_LEGS.map(leg => {
    const q = leg.qtyUnit === "pct" ? Math.max(1, Math.round(totQty * (leg.qtyVal / 100))) : Math.max(1, Math.round(leg.qtyVal));
    let px = leg.pxVal;
    if (leg.pxUnit === "pct") px = side === "BUY" ? entry * (1 + leg.pxVal / 100) : entry * (1 - leg.pxVal / 100);
    if (leg.pxUnit === "r") px = side === "BUY" ? entry + leg.pxVal * rUnit : entry - leg.pxVal * rUnit;
    return { qty: q, price: Number(px.toFixed(2)) };
  }).filter(x => x.qty > 0 && x.price > 0);
}

function exchBadge(o) {
  const raw = String(o.symbol || "");
  const ex = (o.exchange || (raw.startsWith("BSE:") ? "BSE" : "NSE")).toUpperCase();
  const sym = raw.includes(":") ? raw.split(":")[1] : raw;
  const col = ex === "BSE" ? "#f59e0b" : "#3b82f6";
  return `<b>${sym}</b> <span style="font-size:10px;padding:1px 5px;border-radius:4px;background:${col}22;color:${col};border:1px solid ${col}55;vertical-align:middle;">${ex}</span>`;
}

async function submitSmartOrder() {
  const msg = document.getElementById("ord_msg");
  if (!validateOrderSymbol()) {
    if (msg) msg.textContent = "Error: Invalid symbol for selected exchange.";
    return;
  }
  const entry = parseFloat(document.getElementById("ord_price").value || "0");
  const side = document.getElementById("ord_side").value;
  const payload = {
    exchange: document.getElementById("ord_exchange")?.value || "NSE",
    symbol: document.getElementById("ord_symbol").value,
    side,
    product: document.getElementById("ord_product").value,
    qty: parseInt(document.getElementById("ord_qty").value || "0", 10),
    limit_price: entry,
    sl_price: Number(getResolvedStop(entry, side).toFixed(2)),
    target_price: parseFloat(document.getElementById("ord_target").value || "0") || null,
    targets: resolveTargetLegs(),
    move_sl_be_after_t1: !!document.getElementById("ord_be_after_t1")?.checked,
    account_id: document.getElementById("ord_account")?.value || null,
  };
  const res = await (await fetch("/api/portfolio/order", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })).json();
  if (msg) msg.textContent = res.ok ? `Placed ${res.order.order_id} (${res.order.status})` : `Error: ${res.error}`;
  if (res.ok && window.showOrderToast) showOrderToast(side === "BUY" ? "buy" : "target", `${payload.symbol} ${side} ${payload.qty} placed!`);
  await refreshPortfolio();
}

function setExitMode(mode) {
  EXIT_MODE = mode;
  localStorage.setItem("tfalgo_exit_mode", mode);
  document.getElementById("exitModePctBtn").className = "btn" + (mode === "pct" ? " primary" : "");
  document.getElementById("exitModeQtyBtn").className = "btn" + (mode === "qty" ? " primary" : "");
  refreshPortfolio();
}

async function customQuickExit(symbol, netQtyAbs) {
  const val = parseFloat(document.getElementById(`exit_val_${symbol}`)?.value || "50") || 0;
  if (val <= 0) return;
  const payload = EXIT_MODE === "pct" ? { symbol, fraction: Math.min(1.0, val / 100.0) } : { symbol, qty: Math.min(netQtyAbs, Math.max(1, Math.round(val))) };
  await fetch("/api/portfolio/exit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  await refreshPortfolio();
}

async function quickExitFull(symbol) {
  await fetch("/api/portfolio/exit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, fraction: 1.0 }) });
  await refreshPortfolio();
}

async function sendPaperTick() {
  await fetch("/api/portfolio/tick", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: document.getElementById("tick_sym").value, ltp: parseFloat(document.getElementById("tick_ltp").value || "0") }) });
  await refreshPortfolio();
}

function setPerfFilter(mode, btn) {
  PERF_FILTER = mode;
  document.querySelectorAll(".perf-filter-btn").forEach(b => { b.className = "btn perf-filter-btn"; });
  if (btn) btn.className = "btn primary perf-filter-btn";
  renderPerformanceMetrics();
}

function renderPerformanceMetrics() {
  const grid = document.getElementById("perfMetricsGrid");
  if (!grid) return;

  const closedList = LAST_CLOSED.map(c => {
    const ep = Number(c.entry_price || 0), xp = Number(c.exit_price || 0);
    const pct = ep > 0 ? ((c.side === "SHORT" ? (ep - xp) : (xp - ep)) / ep) * 100 : 0;
    return { pnl: Number(c.net_pnl || 0), r: Number(c.money_r || 0), pct };
  });
  const runningList = LAST_POSITIONS.map(p => {
    const avgE = Number(p.avg_price || 0), ltp = Number(p.ltp || avgE);
    const isLong = Number(p.net_qty || 0) > 0;
    const pct = avgE > 0 ? ((isLong ? (ltp - avgE) : (avgE - ltp)) / avgE) * 100 : 0;
    const pnl = Number(p.realized_pnl || 0) + Number(p.mtm || 0);
    const ir = Number(p.initial_risk_inr || 0);
    return { pnl, r: ir > 0 ? pnl / ir : 0, pct };
  });

  const pool = PERF_FILTER === "closed" ? closedList : (PERF_FILTER === "running" ? runningList : [...closedList, ...runningList]);
  const n = pool.length;
  const wins = pool.filter(x => x.pnl > 0), losses = pool.filter(x => x.pnl <= 0);
  const gp = wins.reduce((a, x) => a + x.pnl, 0), gl = Math.abs(losses.reduce((a, x) => a + x.pnl, 0));
  const net = gp - gl;
  const avgWinPct = wins.length ? wins.reduce((a, x) => a + x.pct, 0) / wins.length : 0;
  const avgLossPct = losses.length ? losses.reduce((a, x) => a + x.pct, 0) / losses.length : 0;
  const avgR = n ? pool.reduce((a, x) => a + x.r, 0) / n : 0;
  const pf = gl > 0 ? gp / gl : (gp > 0 ? 999 : 0);

  const items = [
    ["Trades", n],
    ["Win Rate", (n ? (wins.length / n) * 100 : 0).toFixed(1) + "%"],
    ["Net P&L", "₹" + Math.round(net).toLocaleString()],
    ["Avg % Winner", `+${avgWinPct.toFixed(2)}%`],
    ["Avg % Loser", `${avgLossPct.toFixed(2)}%`],
    ["Avg R", `${avgR >= 0 ? "+" : ""}${avgR.toFixed(2)}R`],
    ["Expectancy / Trade", "₹" + Math.round(n ? net / n : 0).toLocaleString()],
    ["Profit Factor", pf.toFixed(2)],
  ];
  grid.innerHTML = items.map(([l, v]) => `<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join("");
}

function setPortCuUnit(u) {
  PORT_CU_UNIT = u;
  document.getElementById("pCuPctBtn").className = "btn" + (u === "pct" ? " primary" : "");
  document.getElementById("pCuInrBtn").className = "btn" + (u === "inr" ? " primary" : "");
  renderPortfolioCharts();
}

function renderPortfolioCharts() {
  const eqSvg = document.getElementById("portEqSvg"), capSvg = document.getElementById("portCapSvg"), ddSvg = document.getElementById("portDdSvg");
  if (!eqSvg || !capSvg || !ddSvg || !LAST_SNAPS.length) return;
  const pts = LAST_SNAPS;
  const dates = pts.map(x => x.date);
  const retPct = pts.map(x => (x.capital > 0 ? ((x.equity / x.capital) - 1) * 100 : 0));
  const capVals = pts.map(x => (PORT_CU_UNIT === "pct" ? (x.capital > 0 ? (x.capital_used / x.capital) * 100 : 0) : x.capital_used));
  let pk = pts[0].equity || pts[0].capital || 1;
  const ddPct = pts.map(x => { if (x.equity > pk) pk = x.equity; return pk > 0 ? ((x.equity - pk) / pk) * 100 : 0; });

  const drawMini = (svg, vals, col, suffix, fillCol) => {
    const W = 550, H = 170, P = 46, R = 12;
    let ymin = Math.min(...vals, 0), ymax = Math.max(...vals, 0);
    if (ymax === ymin) { ymax += 1; ymin -= 1; }
    const mx = i => P + (W - P - R) * (i / Math.max(1, vals.length - 1));
    const my = v => (H - 22) - (H - 36) * ((v - ymin) / (ymax - ymin));
    const ptsArr = vals.length === 1 ? [vals[0], vals[0]] : vals;
    const mx2 = i => P + (W - P - R) * (i / Math.max(1, ptsArr.length - 1));
    const poly = ptsArr.map((v, i) => `${mx2(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ");
    svg.innerHTML = `
      <line x1="${P}" y1="${my(0)}" x2="${W - R}" y2="${my(0)}" stroke="#475569" stroke-dasharray="3,3"/>
      <text x="${P - 4}" y="${my(ymax) + 4}" font-size="10" text-anchor="end" fill="#94a3b8">${ymax.toFixed(1)}${suffix}</text>
      <text x="${P - 4}" y="${my(ymin) + 4}" font-size="10" text-anchor="end" fill="#94a3b8">${ymin.toFixed(1)}${suffix}</text>
      ${fillCol ? `<polygon fill="${fillCol}" points="${P},${my(0)} ${poly} ${W - R},${my(0)}"/>` : ""}
      <polyline fill="none" stroke="${col}" stroke-width="2" points="${poly}"/>
      <text x="${P}" y="${H - 5}" font-size="9.5" fill="#94a3b8">${dates[0] || ""}</text>
      <text x="${W - R}" y="${H - 5}" font-size="9.5" text-anchor="end" fill="#94a3b8">${dates[dates.length - 1] || ""}</text>`;
  };
  drawMini(eqSvg, retPct, "#3b82f6", "%", "rgba(59,130,246,0.12)");
  drawMini(capSvg, capVals, "#10b981", PORT_CU_UNIT === "pct" ? "%" : "", "rgba(16,185,129,0.14)");
  drawMini(ddSvg, ddPct, "#ef4444", "%", "rgba(239,68,68,0.15)");
}

async function cancelOrder(orderId) {
  await fetch("/api/portfolio/cancel/" + encodeURIComponent(orderId), { method: "POST" });
  refreshPortfolio();
}

function renderOpenOrders() {
  const q = (document.getElementById("openOrdFilter")?.value || "").trim().toUpperCase();
  const list = LAST_ORDERS.filter(o => ["OPEN", "TRIGGER_PENDING"].includes(o.status)).filter(o =>
    !q || `${o.order_id} ${o.symbol} ${o.side} ${o.order_type} ${o.status}`.toUpperCase().includes(q)
  );
  const tb = document.getElementById("openOrdRows");
  if (!tb) return;
  tb.innerHTML = list.map(o => {
    const allocPct = ((Number(o.qty || 0) * Number(o.price || 0)) / Math.max(1, LAST_EQUITY)) * 100;
    return `<tr>
      <td class="left">${String(o.ts || "").slice(0, 19).replace("T", " ")}</td>
      <td class="left">${o.order_id}</td><td class="left">${exchBadge(o)}</td><td class="left">${o.side}</td><td class="left">${o.order_type}</td>
      <td>${o.qty}</td><td>${allocPct.toFixed(2)}%</td><td>${Number(o.price || 0).toFixed(2)}</td>
      <td>${o.trigger_price ? Number(o.trigger_price).toFixed(2) : "-"}</td><td class="left">${o.status}</td>
      <td class="left"><button class="btn danger" style="padding:3px 8px;" onclick="cancelOrder('${o.order_id}')">Cancel</button></td>
    </tr>`;
  }).join("") || `<tr><td colspan="11" class="left muted">No open orders</td></tr>`;
}

function sortRecentOrders(col) { if (REC_SORT_COL === col) REC_SORT_ASC = !REC_SORT_ASC; else { REC_SORT_COL = col; REC_SORT_ASC = false; } renderRecentOrders(); }

function renderRecentOrders() {
  const q = (document.getElementById("recOrdFilter")?.value || "").trim().toUpperCase();
  const list = [...LAST_ORDERS].filter(o => !q || `${o.order_id} ${o.symbol} ${o.side} ${o.order_type} ${o.status}`.toUpperCase().includes(q))
    .sort((a, b) => REC_SORT_ASC ? String(a[REC_SORT_COL] || "").localeCompare(String(b[REC_SORT_COL] || "")) : String(b[REC_SORT_COL] || "").localeCompare(String(a[REC_SORT_COL] || "")));
  document.getElementById("ordRows").innerHTML = list.map(o => `<tr>
    <td class="left">${String(o.ts || "").slice(0, 19).replace("T", " ")}</td>
    <td class="left">${o.order_id}</td><td class="left">${exchBadge(o)}</td><td class="left">${o.side}</td><td class="left">${o.order_type}</td>
    <td>${o.qty}</td><td>${Number(o.fill_price || o.price || 0).toFixed(2)}</td><td>${o.trigger_price ? Number(o.trigger_price).toFixed(2) : "-"}</td><td class="left">${o.status}</td>
  </tr>`).join("") || `<tr><td colspan="9" class="left muted">No recent orders</td></tr>`;
}

function renderClosedTrades() {
  const symQ = (document.getElementById("cl_sym")?.value || "").trim().toUpperCase();
  const dFrom = document.getElementById("cl_from")?.value || "";
  const dTo = document.getElementById("cl_to")?.value || "";
  const filtered = LAST_CLOSED.filter(c => {
    const dt = String(c.closed_at || "").slice(0, 10);
    return (!symQ || String(c.symbol || "").toUpperCase().includes(symQ)) && (!dFrom || dt >= dFrom) && (!dTo || dt <= dTo);
  });
  const clEl = document.getElementById("closedRows");
  if (!clEl) return;
  clEl.innerHTML = filtered.map(c => {
    const idx = LAST_CLOSED.indexOf(c);
    const ep = Number(c.entry_price || 0), xp = Number(c.exit_price || 0);
    const pctChg = ep > 0 ? ((c.side === "SHORT" ? (ep - xp) : (xp - ep)) / ep) * 100 : 0;
    const hasNote = JOURNAL_KEYS.has(c.trade_id) || JOURNAL_KEYS.has(c.symbol);
    return `<tr>
      <td style="text-align:center;">${hasNote ? "👁" : ""}</td>
      <td class="left">${c.account_id || "PAPER_1"}</td>
      <td class="left"><a href="javascript:void(0)" onclick="openLiveTradeLog('closed', ${idx})">${c.trade_id || ("#" + (idx + 1))}</a></td>
      <td class="left">${exchBadge(c)}</td><td class="left">${c.side}</td><td>${c.qty}</td>
      <td>${ep.toFixed(2)}</td><td>${xp.toFixed(2)}</td>
      <td class="${pctChg >= 0 ? "pos" : "neg"}">${pctChg >= 0 ? "+" : ""}${pctChg.toFixed(2)}%</td>
      <td>₹${Number(c.charges || 0).toFixed(2)}</td>
      <td>₹${Math.round(Number(c.initial_risk_inr || 0)).toLocaleString()}</td>
      <td class="${c.net_pnl >= 0 ? "pos" : "neg"}">${Math.round(c.net_pnl).toLocaleString()}</td>
      <td class="${(c.money_r || 0) >= 0 ? "pos" : "neg"}">${Number(c.money_r || 0) >= 0 ? "+" : ""}${Number(c.money_r || 0).toFixed(2)}R</td>
      <td class="left">${String(c.closed_at || "").slice(0, 19).replace("T", " ")}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="14" class="left muted">No closed trades match filter</td></tr>`;
}

async function refreshPortfolio() {
  const [d, snapRes] = await Promise.all([
    fetch("/api/portfolio/state").then(r => r.json()),
    fetch("/api/portfolio/snapshots").then(r => r.json()).catch(() => ({ snapshots: [] })),
  ]);
  if (!d.ok) return;
  const eq = Math.max(1, Number(d.equity || d.capital || 1000000));
  LAST_POSITIONS = d.positions || [];
  LAST_CLOSED = d.closed_trades || [];
  LAST_ORDERS = d.orders || [];
  LAST_SNAPS = snapRes.snapshots || [];
  JOURNAL_KEYS = new Set(d.journal_keys || []);
  LAST_EQUITY = eq;
  const accts = d.accounts || [];
  const ordAc = document.getElementById("ord_account");
  if (ordAc && accts.length) {
    const curA = ordAc.value;
    ordAc.innerHTML = accts.map(a => `<option value="${a.account_id}">${a.account_id} (${a.broker})</option>`).join("");
    if (curA) ordAc.value = curA;
  }
  const pfAc = document.getElementById("perfAcctFilter");
  if (pfAc && accts.length) {
    const curP = pfAc.value;
    pfAc.innerHTML = '<option value="">All Accounts</option>' + accts.map(a => `<option value="${a.account_id}">${a.account_id}</option>`).join("");
    pfAc.value = curP;
  }

  let totalOpenRiskInr = 0, totalLiveR = 0;
  const posRowsHtml = LAST_POSITIONS.map(p => {
    const qtyAbs = Math.abs(Number(p.net_qty || 0)), isLong = Number(p.net_qty || 0) > 0;
    const avgE = Number(p.avg_price || 0), ltp = Number(p.ltp || avgE);
    const sl = p.sl_price ? Number(p.sl_price) : null, tgt = p.target_price ? Number(p.target_price) : null;
    const totalCampaignPnl = Number(p.realized_pnl || 0) + Number(p.mtm || 0);
    const peakQty = Math.max(qtyAbs, Number(p.peak_qty || qtyAbs));
    let riskInr = 0, liveR = 0, initRisk = Number(p.initial_risk_inr || 0);
    if (sl !== null && sl > 0) {
      riskInr = (isLong ? Math.max(0, avgE - sl) : Math.max(0, sl - avgE)) * qtyAbs;
      if (initRisk <= 0) initRisk = Math.abs(avgE - sl) * peakQty;
    }
    if (initRisk > 0) liveR = totalCampaignPnl / initRisk;
    totalOpenRiskInr += riskInr; totalLiveR += liveR;
    const riskPct = (riskInr / eq) * 100, allocPct = ((qtyAbs * avgE) / eq) * 100;
    const defaultVal = EXIT_INPUT_VALS[p.symbol] ?? (EXIT_MODE === "pct" ? 50 : Math.max(1, Math.floor(qtyAbs / 2)));
    const hasNote = JOURNAL_KEYS.has(p.symbol);

    return `<tr>
      <td style="text-align:center;">${hasNote ? "👁" : ""}</td>
      <td class="left">${p.account_id || "PAPER_1"}</td>
      <td class="left"><a href="javascript:void(0)" onclick="openLiveTradeLog('open', '${p.symbol}')">${exchBadge(p)}</a></td>
      <td class="left">${p.product}</td><td>${p.net_qty}</td><td>${allocPct.toFixed(2)}%</td>
      <td>${avgE.toFixed(2)}</td><td>${ltp.toFixed(2)}</td><td>${sl ? sl.toFixed(2) : "-"}</td><td>${tgt ? tgt.toFixed(2) : "-"}</td>
      <td>₹${Math.round(riskInr).toLocaleString()} (${riskPct.toFixed(2)}%)</td>
      <td class="${liveR >= 0 ? "pos" : "neg"}">${liveR >= 0 ? "+" : ""}${liveR.toFixed(2)}R</td>
      <td class="${p.mtm >= 0 ? "pos" : "neg"}">${Math.round(p.mtm).toLocaleString()}</td>
      <td class="left" style="white-space:nowrap;">
        <input id="exit_val_${p.symbol}" type="number" step="${EXIT_MODE === "pct" ? "5" : "1"}" min="1" value="${defaultVal}" oninput="EXIT_INPUT_VALS['${p.symbol}']=this.value" style="width:58px;padding:4px;">
        <span class="muted" style="font-size:11px;">${EXIT_MODE === "pct" ? "%" : "qty"}</span>
        <button class="btn" onclick="customQuickExit('${p.symbol}', ${qtyAbs})">Exit</button>
        <button class="btn danger" onclick="quickExitFull('${p.symbol}')">100%</button>
      </td>
    </tr>`;
  }).join("");

  const kpis = [
    ["Broker", String(d.broker || "paper").toUpperCase()],
    ["Equity", "₹" + Math.round(eq).toLocaleString()],
    ["Realized P&L", "₹" + Math.round(d.realized_pnl).toLocaleString()],
    ["Unrealized MTM", "₹" + Math.round(d.unrealized_mtm).toLocaleString()],
    ["Open Risk (Heat)", `₹${Math.round(totalOpenRiskInr).toLocaleString()} (${(totalOpenRiskInr / eq * 100).toFixed(2)}%)`],
    ["Live Open R", `${totalLiveR >= 0 ? "+" : ""}${totalLiveR.toFixed(2)}R`],
    ["Open Positions", LAST_POSITIONS.length],
    ["Last Sync", d.last_sync_ts || "--"],
  ];
  const grid = document.getElementById("portKpiGrid");
  if (grid) { grid.innerHTML = kpis.map(([l, v]) => `<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join(""); if (window.attachHelpIcons) attachHelpIcons(grid); }

  document.getElementById("posRows").innerHTML = posRowsHtml || `<tr><td colspan="14" class="left muted">No open positions</td></tr>`;
  renderPerformanceMetrics();
  renderPortfolioCharts();
  renderOpenOrders();
  renderRecentOrders();
  renderClosedTrades();
}

async function refreshFunds() {
  const d = await (await fetch("/api/portfolio/funds")).json();
  if (!d.ok) return;
  const fk = [
    ["Base Capital", "₹" + Math.round(d.base_capital).toLocaleString()],
    ["Added Funds", "₹" + Math.round(d.added).toLocaleString()],
    ["Withdrawn", "₹" + Math.round(d.withdrawn).toLocaleString()],
    ["Realized P&L", "₹" + Math.round(d.realized_pnl).toLocaleString()],
    ["Total Charges", "₹" + d.total_charges.toFixed(2)],
    ["Used Margin", "₹" + Math.round(d.used_margin).toLocaleString()],
    ["Available Funds", "₹" + Math.round(d.available_funds).toLocaleString()],
  ];
  document.getElementById("fundsKpiGrid").innerHTML = fk.map(([l, v]) => `<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join("");
  document.getElementById("fundsTxnRows").innerHTML = (d.transactions || []).map(t => `<tr><td class="left">${String(t.ts || "").slice(0, 19).replace("T", " ")}</td><td class="left"><b>${t.kind}</b></td><td class="${t.kind === "DEPOSIT" ? "pos" : "neg"}">₹${Number(t.amount).toLocaleString()}</td><td class="left">${t.note || ""}</td></tr>`).join("") || `<tr><td colspan="4" class="left muted">No fund transfers yet</td></tr>`;
  document.getElementById("fundsChargesRows").innerHTML = (d.charges_rows || []).map(c => `<tr><td class="left">${c.trade_id || "-"}</td><td class="left"><b>${c.symbol}</b></td><td>${c.brokerage.toFixed(2)}</td><td>${c.stt.toFixed(2)}</td><td>${c.stamp.toFixed(2)}</td><td>${c.exch_sebi.toFixed(2)}</td><td>${c.gst.toFixed(2)}</td><td><b>${c.total.toFixed(2)}</b></td></tr>`).join("") || `<tr><td colspan="8" class="left muted">No closed trade charges yet</td></tr>`;
}

async function submitFundTxn() {
  await fetch("/api/portfolio/funds", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: document.getElementById("fnd_kind").value, amount: parseFloat(document.getElementById("fnd_amt").value || "0"), note: document.getElementById("fnd_note").value }) });
  document.getElementById("fnd_amt").value = ""; document.getElementById("fnd_note").value = ""; refreshFunds();
}

async function refreshAlerts() {
  const res = await (await fetch("/api/portfolio/alerts")).json();
  const box = document.getElementById("alertsList");
  if (!box) return;
  box.innerHTML = (res.alerts || []).map(a => `<div style="border:1px solid var(--border);border-radius:8px;padding:6px 10px;font-size:12px;display:flex;gap:8px;align-items:center;background:var(--card-alt);"><b>${a.symbol} ${a.condition} ₹${a.price}</b><span class="muted">${a.message}</span><button type="button" class="btn" style="padding:1px 6px;" onclick="deletePriceAlert('${a.id}')">×</button></div>`).join("") || `<span class="muted" style="font-size:12px;">No active price alerts.</span>`;
}

async function addPriceAlert() {
  await fetch("/api/portfolio/alerts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: document.getElementById("al_sym").value, condition: document.getElementById("al_cond").value, price: parseFloat(document.getElementById("al_px").value || "0"), message: document.getElementById("al_msg").value }) });
  document.getElementById("al_msg").value = ""; refreshAlerts();
}

async function deletePriceAlert(id) { await fetch("/api/portfolio/alerts/" + encodeURIComponent(id), { method: "DELETE" }); refreshAlerts(); }

function openLiveTradeLog(kind, key) {
  const item = kind === "open" ? LAST_POSITIONS.find(p => p.symbol === key) : LAST_CLOSED[key];
  if (!item) return;
  document.getElementById("ltModalTitle").textContent = `${item.symbol} — Detailed Trade Log (${kind.toUpperCase()})`;
  const ep = Number(item.avg_price || item.entry_price || 0), xp = Number(item.ltp || item.exit_price || ep);
  const isShort = item.side === "SHORT" || Number(item.net_qty || 0) < 0;
  const pctChg = ep > 0 ? ((isShort ? (ep - xp) : (xp - ep)) / ep) * 100 : 0;
  const chgInr = Number(item.charges || 0);
  const rVal = Number(item.money_r ?? (Number(item.initial_risk_inr || 0) > 0 ? ((Number(item.realized_pnl || 0) + Number(item.mtm || 0)) / Number(item.initial_risk_inr)) : 0));
  document.getElementById("ltModalSub").textContent = `Avg Entry: ₹${ep.toFixed(2)} | Current/Exit: ₹${xp.toFixed(2)}`;
  document.getElementById("ltModalKpis").innerHTML = [
    ["% Change", `${pctChg >= 0 ? "+" : ""}${pctChg.toFixed(2)}%`],
    ["R-Multiple", `${rVal >= 0 ? "+" : ""}${rVal.toFixed(2)}R`],
    ["Txn Charges", `₹${chgInr.toFixed(2)}`],
    ["Net P&L", `₹${Math.round(Number(item.net_pnl ?? (Number(item.realized_pnl || 0) + Number(item.mtm || 0)))).toLocaleString()}`],
  ].map(([l, v]) => `<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join("");

  document.getElementById("ltFillRows").innerHTML = (item.fills || []).map(f => `<tr>
    <td class="left">${String(f.ts || "").slice(0, 19).replace("T", " ")}</td><td class="left"><b>${f.note || "-"}</b></td><td class="left">${f.side}</td>
    <td>${f.qty}</td><td>${Number(f.price || 0).toFixed(2)}</td><td class="${(f.pnl || 0) >= 0 ? "pos" : "neg"}">${Math.round(Number(f.pnl || 0)).toLocaleString()}</td>
  </tr>`).join("") || `<tr><td colspan="6" class="left muted">No fills recorded</td></tr>`;

  showTradeModalTab("orders");
  loadTradeJournal(item.trade_id || item.symbol);
  document.getElementById("liveTradeModal").classList.add("open");
}

function previewJournalFile(inp) {
  const f = inp.files && inp.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = () => { PENDING_JOURNAL_IMG = r.result; const img = document.getElementById("jrn_preview"); img.src = PENDING_JOURNAL_IMG; img.style.display = "block"; document.getElementById("jrn_img_status").textContent = "Image ready"; };
  r.readAsDataURL(f);
}

async function loadTradeJournal(key) {
  ACTIVE_JOURNAL_KEY = key; PENDING_JOURNAL_IMG = "";
  const prev = document.getElementById("jrn_preview"); if (prev) prev.style.display = "none";
  const res = await (await fetch("/api/portfolio/journal/" + encodeURIComponent(key))).json();
  document.getElementById("jrnEntries").innerHTML = (res.entries || []).slice().reverse().map(e => `
    <div style="border:1px solid var(--border);border-radius:8px;padding:8px 10px;background:var(--card-alt);">
      <div class="muted" style="font-size:11px;">${String(e.ts || "").slice(0, 19).replace("T", " ")}</div>
      ${e.comment ? `<div style="margin-top:4px;font-size:12.5px;">${e.comment}</div>` : ""}
      ${e.image_data_url ? `<img src="${e.image_data_url}" class="journal-img-thumb" onclick="openImageLightbox(this.src)" title="Click to enlarge">` : ""}
    </div>`).join("") || `<span class="muted" style="font-size:12px;">No journal notes yet.</span>`;
}

async function saveTradeJournal() {
  await fetch("/api/portfolio/journal", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ trade_key: ACTIVE_JOURNAL_KEY, comment: document.getElementById("jrn_comment").value, image_base64: PENDING_JOURNAL_IMG }) });
  document.getElementById("jrn_comment").value = ""; document.getElementById("jrn_img_status").textContent = "";
  await loadTradeJournal(ACTIVE_JOURNAL_KEY);
  refreshPortfolio();
}

document.addEventListener("paste", evt => {
  const modal = document.getElementById("liveTradeModal");
  if (!modal || !modal.classList.contains("open")) return;
  for (const it of (evt.clipboardData?.items || [])) {
    if (it.type.startsWith("image/")) {
      const r = new FileReader();
      r.onload = () => { PENDING_JOURNAL_IMG = r.result; const img = document.getElementById("jrn_preview"); img.src = PENDING_JOURNAL_IMG; img.style.display = "block"; document.getElementById("jrn_img_status").textContent = "Screenshot pasted!"; showTradeModalTab("comments"); };
      r.readAsDataURL(it.getAsFile()); break;
    }
  }
});

let MASTER_SYMBOLS = { NSE: [], BSE: [], synced: false };

function updateSymbolDatalist() {
  const ex = document.getElementById("ord_exchange")?.value || "NSE";
  const dl = document.getElementById("nseSymbolList");
  const list = MASTER_SYMBOLS[ex]?.length ? MASTER_SYMBOLS[ex] : (MASTER_SYMBOLS.NSE || []);
  if (dl) dl.innerHTML = list.map(s => `<option value="${s}">`).join("");
}

function validateOrderSymbol() {
  const inp = document.getElementById("ord_symbol");
  const st = document.getElementById("ord_sym_status");
  if (!inp || !st) return true;
  let raw = inp.value.trim().toUpperCase();
  if (raw.startsWith("BSE:")) {
    document.getElementById("ord_exchange").value = "BSE";
    raw = raw.slice(4);
  } else if (raw.startsWith("NSE:")) {
    document.getElementById("ord_exchange").value = "NSE";
    raw = raw.slice(4);
  }
  const ex = document.getElementById("ord_exchange")?.value || "NSE";
  if (!raw) { st.textContent = "Enter a symbol"; st.style.color = "#ef4444"; return false; }
  if (!MASTER_SYMBOLS.synced) {
    st.textContent = `${ex}: ${raw} (click Sync IPOs to validate)`;
    st.style.color = "#94a3b8";
    return true;
  }
  const ok = (MASTER_SYMBOLS[ex] || []).includes(raw);
  st.textContent = ok ? `✅ Valid ${ex} symbol` : `⚠️ Not found in ${ex} master list`;
  st.style.color = ok ? "#10b981" : "#ef4444";
  return ok;
}

async function loadNseAutocomplete() {
  const res = await (await fetch("/api/portfolio/symbols")).json().catch(() => ({ symbols: [] }));
  MASTER_SYMBOLS = { NSE: res.nse || res.symbols || [], BSE: res.bse || [], synced: !!res.synced };
  updateSymbolDatalist();
  validateOrderSymbol();
}

async function syncNseSymbols() {
  const res = await (await fetch("/api/portfolio/symbols/sync", { method: "POST" })).json();
  alert(res.ok ? `Synced ${res.nse_count || res.count} NSE + ${res.bse_count || 0} BSE symbols!` : `Sync failed: ${res.error}`);
  loadNseAutocomplete();
}

window.refreshPortfolio = refreshPortfolio;

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("exitModePctBtn").className = "btn" + (EXIT_MODE === "pct" ? " primary" : "");
  document.getElementById("exitModeQtyBtn").className = "btn" + (EXIT_MODE === "qty" ? " primary" : "");
  const pre = sessionStorage.getItem("tfalgo_prefill_order");
  if (pre) {
    try {
      const p = JSON.parse(pre);
      if (p.symbol) document.getElementById("ord_symbol").value = p.symbol;
      if (p.price) document.getElementById("ord_price").value = p.price;
      if (p.sl) document.getElementById("ord_sl").value = p.sl;
      if (p.target) document.getElementById("ord_target").value = p.target;
      sessionStorage.removeItem("tfalgo_prefill_order");
      openOrderModal(true);
    } catch {}
  }
  loadNseAutocomplete();
  refreshPortfolio();
  refreshAlerts();
  setInterval(refreshPortfolio, 10000);
});


let _LTP_TIMER = null;
function debouncedFetchLtp() {
  clearTimeout(_LTP_TIMER);
  _LTP_TIMER = setTimeout(() => fetchOrderLtp(true), 400);
}

async function fetchOrderLtp(autoAdjustSlTgt = true) {
  const sym = (document.getElementById("ord_symbol")?.value || "").trim().toUpperCase();
  const ex = document.getElementById("ord_exchange")?.value || "NSE";
  if (!sym) return;
  try {
    const res = await (await fetch(`/api/portfolio/ltp?symbol=${encodeURIComponent(sym)}&exchange=${encodeURIComponent(ex)}`)).json();
    if (res.ok && res.ltp > 0) {
      const ltp = Number(res.ltp.toFixed(2));
      const pxEl = document.getElementById("ord_price");
      if (pxEl) pxEl.value = ltp;
      if (autoAdjustSlTgt) {
        const side = document.getElementById("ord_side")?.value || "BUY";
        const slEl = document.getElementById("ord_sl");
        const tgtEl = document.getElementById("ord_target");
        if (slEl && SL_MODE === "px") slEl.value = (side === "BUY" ? ltp * 0.99 : ltp * 1.01).toFixed(2);
        if (tgtEl) tgtEl.value = (side === "BUY" ? ltp * 1.03 : ltp * 0.97).toFixed(2);
      }
      recalcOrderTicket();
    }
  } catch {}
}
