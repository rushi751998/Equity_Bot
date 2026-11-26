let currentTrade = null;
let currentTf = "5m";
let cachedCandles = [];
let viewStart = 0;
let viewEnd = 0;
let priceScaleMult = 1.0;
let priceOffset = 0.0;
let anchorA = null;
let anchorB = null;
let lastMouse = null;
let chartExtraDaysBefore = 0;
let chartExtraDaysAfter = 0;
let chartMaximized = false;
let calloutOffsets = {};
let replayTimer = null;
let replayLimitIdx = null;
let replaySpeed = 1.0;

function openTrade(uid) {
  currentTrade = (window.activeTrades || []).find(x => x.uid === uid);
  if (!currentTrade) return;
  stopReplay(true);
  calloutOffsets = {};
  chartExtraDaysBefore = 0;
  chartExtraDaysAfter = 0;

  document.getElementById("modalTitle").textContent = `${currentTrade.symbol} — Trade #${currentTrade.trade_id} (${currentTrade.strategy})`;
  document.getElementById("modalSub").innerHTML =
    `Entry: <b>${Number(currentTrade.avg_entry || 0).toFixed(2)}</b> | Exit: <b>${Number(currentTrade.avg_exit || 0).toFixed(2)}</b> | ` +
    `Stop: <b style="color:#dc2626">${Number(currentTrade.initial_stop || 0).toFixed(2)}</b> | ` +
    `P&amp;L: <b class="${currentTrade.adj_pnl >= 0 ? "pos" : "neg"}">INR ${Math.round(currentTrade.adj_pnl).toLocaleString()} (${Number(currentTrade.adj_r || 0).toFixed(2)}R)</b>`;

  document.getElementById("tradeModal").classList.add("open");
  fetchTradeChart();
}

function closeModal() {
  stopReplay(true);
  const m = document.getElementById("tradeModal");
  if (m) m.classList.remove("open");
}

function setTf(tf, btn) {
  currentTf = tf;
  document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  fetchTradeChart();
}

function shiftChartWindow(dB, dA) {
  chartExtraDaysBefore += dB;
  chartExtraDaysAfter += dA;
  fetchTradeChart();
}

function toggleMaximizeChart() {
  chartMaximized = !chartMaximized;
  document.querySelector("#tradeModal .modal-card")?.classList.toggle("tf-modal-max", chartMaximized);
  const btn = document.getElementById("tfMaxChartBtn");
  if (btn) btn.textContent = chartMaximized ? "🗗 Restore" : "⛶ Maximize";
}

function stopReplay(resetFull) {
  if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
  const btn = document.getElementById("tfReplayBtn");
  if (btn) btn.innerHTML = "&#9654; Replay";
  if (resetFull) { replayLimitIdx = null; redrawActiveTrade(); }
}

function setReplaySpeed(val) {
  replaySpeed = parseFloat(val) || 1.0;
  if (replayTimer) { stopReplay(false); toggleReplay(); }
}

function toggleReplay() {
  if (replayTimer) { stopReplay(false); return; }
  if (!cachedCandles.length) return;
  if (replayLimitIdx === null || replayLimitIdx >= cachedCandles.length - 1) {
    const eKey = (currentTrade.entry_ts || "").slice(0, 16);
    const eIdx = eKey ? cachedCandles.findIndex(b => b.t.slice(0, 16) >= eKey) : 20;
    replayLimitIdx = Math.max(5, (eIdx >= 0 ? eIdx : 20) - 20);
  }
  const btn = document.getElementById("tfReplayBtn");
  if (btn) btn.innerHTML = "&#9208; Pause";
  replayTimer = setInterval(() => {
    if (replayLimitIdx >= cachedCandles.length - 1) { stopReplay(false); return; }
    replayLimitIdx += 1;
    if (replayLimitIdx > viewEnd) { viewEnd = replayLimitIdx; viewStart = Math.max(0, viewEnd - 120); }
    redrawActiveTrade();
  }, Math.max(80, Math.round(600 / replaySpeed)));
}

function redrawActiveTrade() {
  if (currentTrade) drawCandles(cachedCandles);
}

async function fetchTradeChart() {
  if (!currentTrade) return;
  const shiftDate = (iso, d) => {
    const dt = new Date((iso || "").slice(0, 10) + "T00:00:00Z");
    if (Number.isNaN(dt.getTime())) return (iso || "").slice(0, 10);
    dt.setUTCDate(dt.getUTCDate() + d);
    return dt.toISOString().slice(0, 10);
  };
  const q = new URLSearchParams({
    symbol: currentTrade.symbol,
    tf: currentTf,
    entry: shiftDate(currentTrade.entry_ts, chartExtraDaysBefore),
    exit: shiftDate(currentTrade.exit_ts, chartExtraDaysAfter),
  });
  const data = await (await fetch("/api/candles?" + q)).json();
  cachedCandles = data.candles || [];
  viewStart = 0;
  viewEnd = Math.max(0, cachedCandles.length - 1);
  priceScaleMult = 1.0;
  priceOffset = 0.0;
  anchorA = null;
  anchorB = null;
  drawCandles(cachedCandles);
}

function drawCandles(allBars) {
  const svg = document.getElementById("candleSvg");
  if (!svg || !allBars.length) return;
  const pool = replayLimitIdx !== null ? allBars.slice(0, replayLimitIdx + 1) : allBars;
  viewStart = Math.max(0, Math.min(pool.length - 1, viewStart));
  viewEnd = Math.max(viewStart, Math.min(pool.length - 1, replayLimitIdx !== null ? pool.length - 1 : (viewEnd || pool.length - 1)));
  const bars = pool.slice(viewStart, viewEnd + 1);

  const showE = document.getElementById("togEmas")?.checked ?? true;
  const showV = document.getElementById("togVol")?.checked ?? true;
  const W = 1100, H = 500, P = 64, R = 30, T = 36, B = showV ? 110 : 48;
  const V_TOP = H - 94, V_BOT = H - 40;

  let pmin = Math.min(...bars.map(b => b.l)), pmax = Math.max(...bars.map(b => b.h));
  const pad = (pmax - pmin) * 0.10 || 1;
  pmin -= pad; pmax += pad;
  const pMid = (pmin + pmax) / 2 + priceOffset;
  const pHalf = Math.max(0.05, ((pmax - pmin) / 2) * priceScaleMult);
  pmin = pMid - pHalf; pmax = pMid + pHalf;

  const cw = Math.max(1.5, Math.min(14, ((W - P - R) / bars.length) * 0.7));
  const mx = i => P + (W - P - R) * ((i + 0.5) / bars.length);
  const my = v => T + (H - T - B) * (1 - (v - pmin) / (pmax - pmin));

  const gridCol = isDarkMode() ? "#1e293b" : "#f1f5f9";
  const lblCol = isDarkMode() ? "#94a3b8" : "#64748b";
  let out = "";
  for (let g = 0; g <= 5; g++) {
    const v = pmin + (pmax - pmin) * (g / 5), y = my(v);
    out += `<line x1="${P}" y1="${y}" x2="${W - R}" y2="${y}" stroke="${gridCol}"/>`;
    out += `<text x="${P - 8}" y="${y + 4}" font-size="11" text-anchor="end" fill="${lblCol}">${v.toFixed(2)}</text>`;
  }

  if (showE) {
    [["ema9", "#8b5cf6"], ["ema21", "#f59e0b"], ["ema50", "#0d9488"]].forEach(([k, col]) => {
      const pts = bars.map((b, i) => (b[k] != null ? `${mx(i).toFixed(1)},${my(b[k]).toFixed(1)}` : null)).filter(Boolean);
      if (pts.length > 1) out += `<polyline fill="none" stroke="${col}" stroke-width="1.6" points="${pts.join(" ")}"/>`;
    });
  }

  if (showV) {
    const vmax = Math.max(...bars.map(b => b.v || 0), 1);
    bars.forEach((b, i) => {
      const vh = ((b.v || 0) / vmax) * (V_BOT - V_TOP - 4);
      out += `<rect x="${mx(i) - cw / 2}" y="${V_BOT - vh}" width="${cw}" height="${vh}" fill="${b.c >= b.o ? "rgba(22,163,74,0.45)" : "rgba(220,38,38,0.45)"}"/>`;
    });
  }

  bars.forEach((b, i) => {
    const x = mx(i), col = b.c >= b.o ? "#16a34a" : "#dc2626";
    const top = Math.min(my(b.o), my(b.c)), bh = Math.max(1.5, Math.abs(my(b.o) - my(b.c)));
    out += `<line x1="${x}" y1="${my(b.h)}" x2="${x}" y2="${my(b.l)}" stroke="${col}" stroke-width="1.2"/><rect x="${x - cw / 2}" y="${top}" width="${cw}" height="${bh}" fill="${col}"/>`;
  });

  svg.innerHTML = out;
  const ov = document.createElementNS("http://www.w3.org/2000/svg", "g");
  svg.appendChild(ov);
  svg.style.cursor = "crosshair";

  const drawOverlay = cur => {
    let h = "";
    let evList = [];
    try { evList = JSON.parse(currentTrade.events || "[]"); } catch {}
    if (!evList.length) {
      if (currentTrade.entry_ts) evList.push({ ts: currentTrade.entry_ts, price: currentTrade.avg_entry, label: `E1 @ ${Number(currentTrade.avg_entry).toFixed(2)}`, kind: "entry" });
      if (currentTrade.exit_ts) evList.push({ ts: currentTrade.exit_ts, price: currentTrade.avg_exit, label: `Exit @ ${Number(currentTrade.avg_exit).toFixed(2)}`, kind: "exit" });
    }
    const lastVis = bars[bars.length - 1].t.slice(0, 16);
    evList.forEach((ev, idx) => {
      const k = String(ev.ts || "").slice(0, 16);
      if (!k || k > lastVis) return;
      const bIdx = bars.findIndex(b => b.t.slice(0, 16) >= k);
      if (bIdx < 0) return;
      const ax = mx(bIdx), ay = my(ev.price), cid = "c_" + idx;
      const off = calloutOffsets[cid] || { dx: idx % 2 === 0 ? -55 : 55, dy: -34 - (idx % 3) * 22 };
      const bx = Math.max(P + 4, Math.min(W - R - 134, ax + off.dx));
      const by = Math.max(T + 4, Math.min(H - B - 24, ay + off.dy));
      const fill = ev.kind === "entry" ? "#1d4ed8" : ev.kind === "add" ? "#7c3aed" : ev.kind === "partial_exit" ? "#059669" : "#b45309";
      h += `<line x1="${ax}" y1="${ay}" x2="${bx + 65}" y2="${by + 10}" stroke="${fill}" stroke-dasharray="2,2"/>`;
      h += `<g data-callout="${cid}" style="cursor:move;"><rect x="${bx}" y="${by}" width="132" height="20" rx="5" fill="${fill}"/><text x="${bx + 66}" y="${by + 13.5}" font-size="10" font-weight="700" text-anchor="middle" fill="#fff">${ev.label}</text></g>`;
    });
    if (cur) {
      h += `<line x1="${cur.x}" y1="${T}" x2="${cur.x}" y2="${H - B}" stroke="#64748b" stroke-dasharray="3,3"/>`;
      h += `<line x1="${P}" y1="${cur.y}" x2="${W - R}" y2="${cur.y}" stroke="#64748b" stroke-dasharray="3,3"/>`;
    }
    ov.innerHTML = h;
  };
  drawOverlay(lastMouse);

  let dragX = null, dragY = null, dragView = 0, dragOff = 0, dragScale = 1, dragMode = "pan2d", dragCid = null, dragCStart = null;
  svg.onmousedown = evt => {
    const cg = evt.target?.closest?.("[data-callout]");
    if (cg) {
      dragCid = cg.getAttribute("data-callout");
      const r = svg.getBoundingClientRect();
      dragCStart = { x: evt.clientX, y: evt.clientY, sx: W / r.width, sy: H / r.height, base: { ...(calloutOffsets[dragCid] || { dx: 0, dy: -36 }) } };
      return;
    }
    const r = svg.getBoundingClientRect();
    dragMode = ((evt.clientX - r.left) * (W / r.width)) < P ? "yscale" : "pan2d";
    dragX = evt.clientX; dragY = evt.clientY; dragView = viewStart; dragOff = priceOffset; dragScale = priceScaleMult;
  };
  svg.onmousemove = evt => {
    const r = svg.getBoundingClientRect();
    if (dragCid && dragCStart) {
      calloutOffsets[dragCid] = { dx: dragCStart.base.dx + (evt.clientX - dragCStart.x) * dragCStart.sx, dy: dragCStart.base.dy + (evt.clientY - dragCStart.y) * dragCStart.sy };
      drawOverlay(lastMouse); return;
    }
    if (dragX !== null) {
      const dx = evt.clientX - dragX, dy = evt.clientY - dragY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
        if (dragMode === "yscale") { priceScaleMult = Math.max(0.15, Math.min(8, dragScale * Math.exp(dy * 0.008))); drawCandles(allBars); return; }
        const span = viewEnd - viewStart + 1;
        const shift = Math.round((-dx / Math.max(1, r.width * ((W - P - R) / W))) * span);
        let ns = Math.max(0, Math.min(pool.length - span, dragView + shift));
        viewStart = ns; viewEnd = ns + span - 1;
        priceOffset = dragOff + (dy / Math.max(1, r.height * ((H - T - B) / H))) * (pmax - pmin);
        drawCandles(allBars); return;
      }
    }
    const sx = (evt.clientX - r.left) * (W / r.width), sy = (evt.clientY - r.top) * (H / r.height);
    const lIdx = Math.max(0, Math.min(bars.length - 1, Math.round(((sx - P) / (W - P - R)) * bars.length - 0.5)));
    lastMouse = { x: mx(lIdx), y: Math.max(T, Math.min(H - B, sy)) };
    drawOverlay(lastMouse);
  };
  svg.onmouseup = () => { dragX = null; dragCid = null; };
  svg.ondblclick = () => { viewStart = 0; viewEnd = pool.length - 1; priceScaleMult = 1; priceOffset = 0; drawCandles(allBars); };
  svg.onwheel = evt => {
    evt.preventDefault();
    const r = svg.getBoundingClientRect(), sx = (evt.clientX - r.left) * (W / r.width), factor = evt.deltaY < 0 ? 0.85 : 1.18;
    if (sx < P || evt.ctrlKey) { priceScaleMult = Math.max(0.15, Math.min(8, priceScaleMult * factor)); drawCandles(allBars); return; }
    const oldSpan = viewEnd - viewStart + 1, newSpan = Math.max(12, Math.min(pool.length, Math.round(oldSpan * factor)));
    const ratio = Math.max(0, Math.min(1, (sx - P) / (W - P - R)));
    const anchor = viewStart + Math.round(oldSpan * ratio);
    let ns = Math.max(0, Math.min(pool.length - newSpan, Math.round(anchor - newSpan * ratio)));
    viewStart = ns; viewEnd = ns + newSpan - 1; drawCandles(allBars);
  };
}

document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });
