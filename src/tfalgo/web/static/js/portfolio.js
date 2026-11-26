let EXIT_MODE = localStorage.getItem("tfalgo_exit_mode") || "pct"; // "pct" | "qty"
let SL_MODE = "px"; // "px" | "pct"
let TARGET_LEGS = [
  { qtyVal: 50, qtyUnit: "pct", pxVal: 3, pxUnit: "r" },
  { qtyVal: 50, qtyUnit: "pct", pxVal: 6, pxUnit: "r" },
];
let EXIT_INPUT_VALS = {};
let LAST_POSITIONS = [];
let LAST_CLOSED = [];
let LAST_ORDERS = [];
let LAST_EQUITY = 1000000;
let REC_SORT_COL = "ts";
let REC_SORT_ASC = false;
let ACTIVE_JOURNAL_KEY = "";
let PENDING_JOURNAL_IMG = "";


function showPortSection(name, btn) {
  document.querySelectorAll(".port-sec").forEach(el => { el.style.display = "none"; });
  const target = document.getElementById("psec_" + name);
  if (target) target.style.display = "block";
  document.querySelectorAll(".port-subtab").forEach(b => { b.className = "btn port-subtab"; });
  if (btn) btn.className = "btn primary port-subtab";
  if (name === "funds") refreshFunds();
}

function closeLiveTradeModal() {
  document.getElementById("liveTradeModal")?.classList.remove("open");
}

document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    closeLiveTradeModal();
    document.getElementById("userGuideModal")?.classList.remove("open");
  }
});

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
      <td class="left">${o.order_id}</td>
      <td class="left"><b>${o.symbol}</b></td>
      <td class="left">${o.side}</td>
      <td class="left">${o.order_type}</td>
      <td>${o.qty}</td>
      <td>${allocPct.toFixed(2)}%</td>
      <td>${Number(o.price || 0).toFixed(2)}</td>
      <td>${o.trigger_price ? Number(o.trigger_price).toFixed(2) : "-"}</td>
      <td class="left">${o.status}</td>
      <td class="left"><button class="btn danger" style="padding:3px 8px;" onclick="cancelOrder('${o.order_id}')">Cancel</button></td>
    </tr>`;
  }).join("") || `<tr><td colspan="12" class="left muted">No open orders</td></tr>`;
}

function sortRecentOrders(col) {
  if (REC_SORT_COL === col) REC_SORT_ASC = !REC_SORT_ASC;
  else { REC_SORT_COL = col; REC_SORT_ASC = false; }
  renderRecentOrders();
}

function renderRecentOrders() {
  const q = (document.getElementById("recOrdFilter")?.value || "").trim().toUpperCase();
  const list = [...LAST_ORDERS].filter(o =>
    !q || `${o.order_id} ${o.symbol} ${o.side} ${o.order_type} ${o.status}`.toUpperCase().includes(q)
  ).sort((a, b) => {
    const va = a[REC_SORT_COL], vb = b[REC_SORT_COL];
    if (typeof va === "number" || typeof vb === "number") return REC_SORT_ASC ? Number(va || 0) - Number(vb || 0) : Number(vb || 0) - Number(va || 0);
    return REC_SORT_ASC ? String(va || "").localeCompare(String(vb || "")) : String(vb || "").localeCompare(String(va || ""));
  });
  const ordEl = document.getElementById("ordRows");
  if (ordEl) {
    ordEl.innerHTML = list.map(o => `<tr>
      <td class="left">${String(o.ts || "").slice(0, 19).replace("T", " ")}</td>
      <td class="left">${o.order_id}</td>
      <td class="left"><b>${o.symbol}</b></td>
      <td class="left">${o.side}</td>
      <td class="left">${o.order_type}</td>
      <td>${o.qty}</td>
      <td>${Number(o.fill_price || o.price || 0).toFixed(2)}</td>
      <td>${o.trigger_price ? Number(o.trigger_price).toFixed(2) : "-"}</td>
      <td class="left">${o.status}</td>
    </tr>`).join("") || `<tr><td colspan="9" class="left muted">No recent orders</td></tr>`;
  }
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
  const fg = document.getElementById("fundsKpiGrid");
  if (fg) fg.innerHTML = fk.map(([l, v]) => `<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join("");

  const txTb = document.getElementById("fundsTxnRows");
  if (txTb) {
    txTb.innerHTML = (d.transactions || []).map(t => `<tr>
      <td class="left">${String(t.ts || "").slice(0, 19).replace("T", " ")}</td>
      <td class="left"><b>${t.kind}</b></td>
      <td class="${t.kind === "DEPOSIT" ? "pos" : "neg"}">₹${Number(t.amount).toLocaleString()}</td>
      <td class="left">${t.note || ""}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="left muted">No fund transfers yet</td></tr>`;
  }

  const chTb = document.getElementById("fundsChargesRows");
  if (chTb) {
    chTb.innerHTML = (d.charges_rows || []).map(c => `<tr>
      <td class="left">${c.trade_id || "-"}</td>
      <td class="left"><b>${c.symbol}</b></td>
      <td>${c.brokerage.toFixed(2)}</td>
      <td>${c.stt.toFixed(2)}</td>
      <td>${c.stamp.toFixed(2)}</td>
      <td>${c.exch_sebi.toFixed(2)}</td>
      <td>${c.gst.toFixed(2)}</td>
      <td><b>${c.total.toFixed(2)}</b></td>
    </tr>`).join("") || `<tr><td colspan="8" class="left muted">No closed trade charges yet</td></tr>`;
  }
}

async function submitFundTxn() {
  await fetch("/api/portfolio/funds", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kind: document.getElementById("fnd_kind").value,
      amount: parseFloat(document.getElementById("fnd_amt").value || "0"),
      note: document.getElementById("fnd_note").value,
    }),
  });
  document.getElementById("fnd_amt").value = "";
  document.getElementById("fnd_note").value = "";
  refreshFunds();
}

function setExitMode(mode) {
  EXIT_MODE = mode;
  localStorage.setItem("tfalgo_exit_mode", mode);
  document.getElementById("exitModePctBtn").className = "btn" + (mode === "pct" ? " primary" : "");
  document.getElementById("exitModeQtyBtn").className = "btn" + (mode === "qty" ? " primary" : "");
  refreshPortfolio();
  refreshAlerts();
}

function setSlMode(mode) {
  SL_MODE = mode;
  document.getElementById("slModePxBtn").className = "btn" + (mode === "px" ? " primary" : "");
  document.getElementById("slModePctBtn").className = "btn" + (mode === "pct" ? " primary" : "");
  const slInp = document.getElementById("ord_sl");
  const entry = parseFloat(document.getElementById("ord_price")?.value || "100") || 100;
  if (mode === "pct" && parseFloat(slInp.value) > 25) slInp.value = "1.0";
  if (mode === "px" && parseFloat(slInp.value) <= 25) slInp.value = (entry * 0.99).toFixed(2);
  renderTargetLegs();
  recalcTicket();
}

function getResolvedStop(entry, side) {
  const raw = parseFloat(document.getElementById("ord_sl")?.value || "0") || 0;
  if (SL_MODE === "px") return raw;
  const frac = raw / 100.0;
  return side === "BUY" ? entry * (1 - frac) : entry * (1 + frac);
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
    return `
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:12px;">
        <b>T${i + 1}:</b>
        <input type="number" step="1" value="${leg.qtyVal}" oninput="TARGET_LEGS[${i}].qtyVal=parseFloat(this.value)||0;renderTargetLegs()" style="width:58px;padding:4px 6px;">
        <select onchange="TARGET_LEGS[${i}].qtyUnit=this.value;renderTargetLegs()" style="padding:4px 6px;">
          <option value="pct" ${leg.qtyUnit === "pct" ? "selected" : ""}>% Qty</option>
          <option value="qty" ${leg.qtyUnit === "qty" ? "selected" : ""}>Shares</option>
        </select>
        <span>@</span>
        <input type="number" step="0.05" value="${leg.pxVal}" oninput="TARGET_LEGS[${i}].pxVal=parseFloat(this.value)||0;renderTargetLegs()" style="width:68px;padding:4px 6px;">
        <select onchange="TARGET_LEGS[${i}].pxUnit=this.value;renderTargetLegs()" style="padding:4px 6px;">
          <option value="px" ${leg.pxUnit === "px" ? "selected" : ""}>₹ Price</option>
          <option value="pct" ${leg.pxUnit === "pct" ? "selected" : ""}>% Gain</option>
          <option value="r" ${leg.pxUnit === "r" ? "selected" : ""}>R-Mult</option>
        </select>
        <span class="muted">(${q} sh @ ₹${px.toFixed(2)})</span>
        <button type="button" class="btn" style="padding:2px 7px;" onclick="TARGET_LEGS.splice(${i},1);renderTargetLegs()">×</button>
      </div>`;
  }).join("") || `<span class="muted" style="font-size:11.5px;">No partial target legs — full position held until SL or manual exit.</span>`;
}

function addTargetLeg() {
  TARGET_LEGS.push({ qtyVal: 33, qtyUnit: "pct", pxVal: 3, pxUnit: "r" });
  renderTargetLegs();
}

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

async function recalcTicket() {
  const cap = parseFloat(document.getElementById("calc_cap")?.value || "1000000") || 1000000;
  const investPct = parseFloat(document.getElementById("ord_cap_pct")?.value || "5") || 5;
  const entry = parseFloat(document.getElementById("ord_price")?.value || "100") || 100;
  const side = document.getElementById("ord_side")?.value || "BUY";
  const stop = getResolvedStop(entry, side);
  const slLbl = document.getElementById("slResolvedLbl");
  if (slLbl) slLbl.textContent = SL_MODE === "pct" ? `Resolved SL: ₹${stop.toFixed(2)}` : `${(Math.abs(entry - stop) / Math.max(entry, 1e-6) * 100).toFixed(2)}% from entry`;
  const target = parseFloat(document.getElementById("ord_target")?.value || "106") || 106;

  const body = {
    capital: cap,
    risk_pct: parseFloat(document.getElementById("calc_risk_pct")?.value || "1.0") || 1.0,
    invest_pct: investPct,
    entry_price: entry,
    stop_price: stop,
    target_price: target,
    win_rate_pct: parseFloat(document.getElementById("calc_wr")?.value || "45") || 45,
    avg_win_r: parseFloat(document.getElementById("calc_win_r")?.value || "2.5") || 2.5,
    avg_loss_r: parseFloat(document.getElementById("calc_loss_r")?.value || "1.0") || 1.0,
    cost_pct_rt: parseFloat(document.getElementById("calc_cost")?.value || "0.12") || 0.12,
    target_profit_inr: parseFloat(document.getElementById("calc_target_inr")?.value || String(cap)) || cap,
  };

  const res = await (
    await fetch("/api/portfolio/calc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  ).json();

  if (!res.ok) return;
  const qtyEl = document.getElementById("ord_qty");
  if (qtyEl && res.qty_shares) qtyEl.value = res.qty_shares;
  renderTargetLegs();

  const tb = document.getElementById("calcMetricsBody");
  if (tb) {
    tb.innerHTML = (res.metrics || [])
      .map(([k, v]) => `<tr><td class="left">${k}</td><td><b>${v}</b></td></tr>`)
      .join("");
  }
}

async function submitSmartOrder() {
  const msg = document.getElementById("ord_msg");
  const payload = {
    symbol: document.getElementById("ord_symbol").value,
    side: document.getElementById("ord_side").value,
    product: document.getElementById("ord_product").value,
    qty: parseInt(document.getElementById("ord_qty").value || "0", 10),
    limit_price: parseFloat(document.getElementById("ord_price").value || "0"),
    sl_price: Number(getResolvedStop(parseFloat(document.getElementById("ord_price").value || "0"), document.getElementById("ord_side").value).toFixed(2)),
    target_price: parseFloat(document.getElementById("ord_target").value || "0") || null,
    targets: resolveTargetLegs(),
    move_sl_be_after_t1: !!document.getElementById("ord_be_after_t1")?.checked,
  };
  const res = await (
    await fetch("/api/portfolio/order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  ).json();
  if (msg) msg.textContent = res.ok ? `Placed ${res.order.order_id} (${res.order.status}) — 5s chase active` : `Error: ${res.error}`;
  await refreshPortfolio();
}

async function customQuickExit(symbol, netQtyAbs) {
  const inp = document.getElementById(`exit_val_${symbol}`);
  const val = parseFloat(inp?.value || (EXIT_MODE === "pct" ? "50" : "1")) || 0;
  if (val <= 0) return;
  const payload = EXIT_MODE === "pct"
    ? { symbol, fraction: Math.min(1.0, val / 100.0) }
    : { symbol, qty: Math.min(netQtyAbs, Math.max(1, Math.round(val))) };
  await fetch("/api/portfolio/exit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await refreshPortfolio();
}

async function quickExitFull(symbol) {
  await fetch("/api/portfolio/exit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, fraction: 1.0 }),
  });
  await refreshPortfolio();
}

async function sendPaperTick() {
  await fetch("/api/portfolio/tick", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: document.getElementById("tick_sym").value,
      ltp: parseFloat(document.getElementById("tick_ltp").value || "0"),
    }),
  });
  await refreshPortfolio();
}

async function refreshPortfolio() {
  const d = await (await fetch("/api/portfolio/state")).json();
  if (!d.ok) return;
  const eq = Math.max(1, Number(d.equity || d.capital || 1000000));
  const positions = d.positions || [];
  const closed = d.closed_trades || [];
  LAST_POSITIONS = positions;
  LAST_CLOSED = closed;
  LAST_ORDERS = d.orders || [];
  LAST_EQUITY = eq;

  let totalOpenRiskInr = 0;
  let totalLiveR = 0;

  const posRowsHtml = positions.map(p => {
    const qtyAbs = Math.abs(Number(p.net_qty || 0));
    const isLong = Number(p.net_qty || 0) > 0;
    const avgE = Number(p.avg_price || 0);
    const ltp = Number(p.ltp || avgE);
    const sl = p.sl_price ? Number(p.sl_price) : null;
    const tgt = p.target_price ? Number(p.target_price) : null;

    let riskInr = 0;
    let liveR = 0;
    const realizedPart = Number(p.realized_pnl || 0);
    const totalCampaignPnl = realizedPart + Number(p.mtm || 0);
    const peakQty = Math.max(qtyAbs, Number(p.peak_qty || qtyAbs));
    let initRisk = Number(p.initial_risk_inr || 0);
    if (sl !== null && sl > 0) {
      const openSlRiskPerShare = isLong ? Math.max(0, avgE - sl) : Math.max(0, sl - avgE);
      riskInr = openSlRiskPerShare * qtyAbs;
      if (initRisk <= 0) initRisk = Math.abs(avgE - sl) * peakQty;
    }
    if (initRisk > 0) {
      liveR = totalCampaignPnl / initRisk;
    }
    totalOpenRiskInr += riskInr;
    totalLiveR += liveR;
    const riskPct = (riskInr / eq) * 100;
    const allocPct = ((qtyAbs * avgE) / eq) * 100;
    const defaultVal = EXIT_INPUT_VALS[p.symbol] ?? (EXIT_MODE === "pct" ? 50 : Math.max(1, Math.floor(qtyAbs / 2)));

    return `<tr>
      <td class="left"><a href="javascript:void(0)" onclick="openLiveTradeLog('open', '${p.symbol}')"><b>${p.symbol}</b></a></td>
      <td class="left">${p.product}</td>
      <td>${p.net_qty}</td>
      <td>${allocPct.toFixed(2)}%</td>
      <td>${avgE.toFixed(2)}</td>
      <td>${ltp.toFixed(2)}</td>
      <td>${sl ? sl.toFixed(2) : "-"}</td>
      <td>${tgt ? tgt.toFixed(2) : "-"}</td>
      <td>₹${Math.round(riskInr).toLocaleString()} (${riskPct.toFixed(2)}%)</td>
      <td class="${liveR >= 0 ? "pos" : "neg"}">${liveR >= 0 ? "+" : ""}${liveR.toFixed(2)}R</td>
      <td class="${p.mtm >= 0 ? "pos" : "neg"}">${Math.round(p.mtm).toLocaleString()}</td>
      <td class="left" style="white-space:nowrap;">
        <input id="exit_val_${p.symbol}" type="number" step="${EXIT_MODE === "pct" ? "5" : "1"}" min="1" value="${defaultVal}" oninput="EXIT_INPUT_VALS['${p.symbol}']=this.value" style="width:62px;padding:4px 6px;">
        <span class="muted" style="font-size:11px;">${EXIT_MODE === "pct" ? "%" : "qty"}</span>
        <button class="btn" onclick="customQuickExit('${p.symbol}', ${qtyAbs})">Exit</button>
        <button class="btn danger" onclick="quickExitFull('${p.symbol}')">100%</button>
      </td>
    </tr>`;
  }).join("");

  const totalHeatPct = (totalOpenRiskInr / eq) * 100;
  const kpis = [
    ["Broker", String(d.broker || "paper").toUpperCase()],
    ["Equity", "₹" + Math.round(eq).toLocaleString()],
    ["Realized P&L", "₹" + Math.round(d.realized_pnl).toLocaleString()],
    ["Unrealized MTM", "₹" + Math.round(d.unrealized_mtm).toLocaleString()],
    ["Open Risk (Heat)", `₹${Math.round(totalOpenRiskInr).toLocaleString()} (${totalHeatPct.toFixed(2)}%)`],
    ["Live Open R", `${totalLiveR >= 0 ? "+" : ""}${totalLiveR.toFixed(2)}R`],
    ["Open Positions", positions.length],
    ["Last Sync", d.last_sync_ts || "--"],
  ];
  const grid = document.getElementById("portKpiGrid");
  if (grid) { grid.innerHTML = kpis.map(([l, v]) => `<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join(""); if (window.attachHelpIcons) attachHelpIcons(grid); }

  const posEl = document.getElementById("posRows");
  if (posEl) posEl.innerHTML = posRowsHtml || `<tr><td colspan="12" class="left muted">No open positions</td></tr>`;


  const clEl = document.getElementById("closedRows");
  if (clEl) {
    clEl.innerHTML = closed.map((c, idx) => {
      const ep = Number(c.entry_price || 0), xp = Number(c.exit_price || 0);
      const pctChg = ep > 0 ? ((c.side === "SHORT" ? (ep - xp) : (xp - ep)) / ep) * 100 : 0;
      const chgInr = Number(c.charges || 0);
      return `<tr>
      <td class="left"><a href="javascript:void(0)" onclick="openLiveTradeLog('closed', ${idx})">${c.trade_id || ("#" + (idx + 1))}</a></td>
      <td class="left"><b>${c.symbol}</b></td>
      <td class="left">${c.side}</td>
      <td>${c.qty}</td>
      <td>${ep.toFixed(2)}</td>
      <td>${xp.toFixed(2)}</td>
      <td class="${pctChg >= 0 ? "pos" : "neg"}">${pctChg >= 0 ? "+" : ""}${pctChg.toFixed(2)}%</td>
      <td>₹${chgInr.toFixed(2)}</td>
      <td>₹${Math.round(Number(c.initial_risk_inr || 0)).toLocaleString()}</td>
      <td class="${c.net_pnl >= 0 ? "pos" : "neg"}">${Math.round(c.net_pnl).toLocaleString()}</td>
      <td class="${(c.money_r || 0) >= 0 ? "pos" : "neg"}">${Number(c.money_r || 0) >= 0 ? "+" : ""}${Number(c.money_r || 0).toFixed(2)}R</td>
      <td class="left">${String(c.closed_at || "").slice(0, 19).replace("T", " ")}</td>
    </tr>`;
    }).join("") || `<tr><td colspan="12" class="left muted">No closed trades yet</td></tr>`;
  }

  renderOpenOrders();
  renderRecentOrders();
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
    } catch {}
  }
  renderTargetLegs();
  recalcTicket();
  refreshPortfolio();
  refreshAlerts();
  setInterval(refreshPortfolio, 10000);
});


function openLiveTradeLog(kind, key) {
  const item = kind === "open"
    ? LAST_POSITIONS.find(p => p.symbol === key)
    : LAST_CLOSED[key];
  if (!item) return;
  document.getElementById("ltModalTitle").textContent = `${item.symbol} — Detailed Trade Log (${kind.toUpperCase()})`;
  const rTxt = item.money_r != null ? ` | Final R: ${Number(item.money_r).toFixed(2)}R` : "";
  const ep = Number(item.avg_price || item.entry_price || 0);
  const xp = Number(item.ltp || item.exit_price || ep);
  const isShort = item.side === "SHORT" || Number(item.net_qty || 0) < 0;
  const pctChg = ep > 0 ? ((isShort ? (ep - xp) : (xp - ep)) / ep) * 100 : 0;
  const chgInr = Number(item.charges || 0);
  const rVal = Number(item.money_r ?? (Number(item.initial_risk_inr || 0) > 0 ? ((Number(item.realized_pnl || 0) + Number(item.mtm || 0)) / Number(item.initial_risk_inr)) : 0));
  document.getElementById("ltModalSub").textContent = `Avg Entry: ₹${ep.toFixed(2)} | Current/Exit: ₹${xp.toFixed(2)}`;
  const mk = document.getElementById("ltModalKpis");
  if (mk) {
    mk.innerHTML = [
      ["% Change", `${pctChg >= 0 ? "+" : ""}${pctChg.toFixed(2)}%`],
      ["R-Multiple", `${rVal >= 0 ? "+" : ""}${rVal.toFixed(2)}R`],
      ["Txn Charges", `₹${chgInr.toFixed(2)}`],
      ["Net P&L", `₹${Math.round(Number(item.net_pnl ?? (Number(item.realized_pnl || 0) + Number(item.mtm || 0)))).toLocaleString()}`],
    ].map(([l, v]) => `<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join("");
  }
  const fills = item.fills || [];
  document.getElementById("ltFillRows").innerHTML = fills.map(f => `<tr>
    <td class="left">${String(f.ts || "").slice(0, 19).replace("T", " ")}</td>
    <td class="left"><b>${f.note || "-"}</b></td>
    <td class="left">${f.side}</td>
    <td>${f.qty}</td>
    <td>${Number(f.price || 0).toFixed(2)}</td>
    <td class="${(f.pnl || 0) >= 0 ? "pos" : "neg"}">${Math.round(Number(f.pnl || 0)).toLocaleString()}</td>
  </tr>`).join("") || `<tr><td colspan="6" class="left muted">No fills recorded</td></tr>`;
  loadTradeJournal(item.trade_id || item.symbol);
  document.getElementById("liveTradeModal").classList.add("open");
}


async function refreshAlerts() {
  const res = await (await fetch("/api/portfolio/alerts")).json();
  const box = document.getElementById("alertsList");
  if (!box) return;
  box.innerHTML = (res.alerts || []).map(a => `
    <div style="border:1px solid var(--border);border-radius:8px;padding:6px 10px;font-size:12px;display:flex;gap:8px;align-items:center;background:var(--card-alt);">
      <b>${a.symbol} ${a.condition} ₹${a.price}</b>
      <span class="muted">${a.message}</span>
      <span class="pos">${a.triggered ? "✓ Sent" : "Active"}</span>
      <button type="button" class="btn" style="padding:1px 6px;" onclick="deletePriceAlert('${a.id}')">×</button>
    </div>`).join("") || `<span class="muted" style="font-size:12px;">No price alerts set.</span>`;
}

async function addPriceAlert() {
  await fetch("/api/portfolio/alerts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: document.getElementById("al_sym").value,
      condition: document.getElementById("al_cond").value,
      price: parseFloat(document.getElementById("al_px").value || "0"),
      message: document.getElementById("al_msg").value,
    }),
  });
  document.getElementById("al_msg").value = "";
  refreshAlerts();
}

async function deletePriceAlert(id) {
  await fetch("/api/portfolio/alerts/" + encodeURIComponent(id), { method: "DELETE" });
  refreshAlerts();
}

function previewJournalFile(inp) {
  const f = inp.files && inp.files[0];
  if (!f) return;
  const r = new FileReader();
  r.onload = () => {
    PENDING_JOURNAL_IMG = r.result;
    const img = document.getElementById("jrn_preview");
    img.src = PENDING_JOURNAL_IMG;
    img.style.display = "block";
    document.getElementById("jrn_img_status").textContent = "Image ready";
  };
  r.readAsDataURL(f);
}

async function loadTradeJournal(key) {
  ACTIVE_JOURNAL_KEY = key;
  PENDING_JOURNAL_IMG = "";
  const prev = document.getElementById("jrn_preview");
  if (prev) prev.style.display = "none";
  const res = await (await fetch("/api/portfolio/journal/" + encodeURIComponent(key))).json();
  const box = document.getElementById("jrnEntries");
  if (box) {
    box.innerHTML = (res.entries || []).slice().reverse().map(e => `
      <div style="border:1px solid var(--border);border-radius:8px;padding:8px 10px;background:var(--card-alt);">
        <div class="muted" style="font-size:11px;">${String(e.ts || "").slice(0, 19).replace("T", " ")}</div>
        ${e.comment ? `<div style="margin-top:4px;font-size:12.5px;">${e.comment}</div>` : ""}
        ${e.image_data_url ? `<img src="${e.image_data_url}" class="journal-img-thumb">` : ""}
      </div>`).join("") || `<span class="muted" style="font-size:12px;">No journal notes yet.</span>`;
  }
}

async function saveTradeJournal() {
  const c = document.getElementById("jrn_comment").value;
  await fetch("/api/portfolio/journal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trade_key: ACTIVE_JOURNAL_KEY, comment: c, image_base64: PENDING_JOURNAL_IMG }),
  });
  document.getElementById("jrn_comment").value = "";
  document.getElementById("jrn_img_status").textContent = "";
  await loadTradeJournal(ACTIVE_JOURNAL_KEY);
}

document.addEventListener("paste", evt => {
  const modal = document.getElementById("liveTradeModal");
  if (!modal || !modal.classList.contains("open")) return;
  const items = evt.clipboardData?.items || [];
  for (const it of items) {
    if (it.type.startsWith("image/")) {
      const blob = it.getAsFile();
      const r = new FileReader();
      r.onload = () => {
        PENDING_JOURNAL_IMG = r.result;
        const img = document.getElementById("jrn_preview");
        img.src = PENDING_JOURNAL_IMG;
        img.style.display = "block";
        document.getElementById("jrn_img_status").textContent = "Clipboard screenshot pasted!";
      };
      r.readAsDataURL(blob);
      break;
    }
  }
});