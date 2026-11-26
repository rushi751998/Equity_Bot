let STRATEGIES = [];
let BENCH = { dates: [], closes: [] };
let STOCK_BENCH = {};
let SELECTED_BENCHMARKS = new Set(["NIFTY_50"]);
const BENCH_COLORS = ["#94a3b8", "#f59e0b", "#10b981", "#ec4899", "#8b5cf6", "#06b6d4"];
let state = [];
window.activeTrades = [];
let filteredTrades = [];
let sortCol = "entry_ts";
let sortAsc = false;
let simViewStart = 0;
let simViewEnd = null;
let capUsedUnit = "pct";
let lastSimSeries = null;
let SIM_SLIPPAGE_PCT = parseFloat(localStorage.getItem("tfalgo_sim_slip_pct") || "0.05") || 0;

async function loadRun(runId) {
  if (!runId) return;
  const run = await (await fetch("/api/run/" + encodeURIComponent(runId))).json();
  if (run.ok === false) {
    STRATEGIES = []; BENCH = { dates: [], closes: [] }; STOCK_BENCH = {}; state = [];
    renderControls(); recalc(); return;
  }
  simViewStart = 0; simViewEnd = null;
  STRATEGIES = run.strategies || [];
  BENCH = run.bench || { dates: [], closes: [] };
  STOCK_BENCH = run.stock_bench || {};
  document.getElementById("capInput").value = Math.round(run.initial_capital || 1000000);
  state = STRATEGIES.map(() => ({ active: true, weight: STRATEGIES.length ? Math.round((100 / STRATEGIES.length) * 10) / 10 : 0 }));
  injectBenchmarkDropdown();
  renderControls();
  recalc();
}

function injectBenchmarkDropdown() {
  const wrap = document.getElementById("benchDropdownWrap");
  if (!wrap) return;
  const opts = ["NIFTY_50", ...Object.keys(STOCK_BENCH).sort()];
  wrap.innerHTML = `
    <button type="button" class="btn" onclick="var m=document.getElementById('tfBenchMenu');m.style.display=m.style.display==='block'?'none':'block';">Compare (${SELECTED_BENCHMARKS.size}) &#9662;</button>
    <div id="tfBenchMenu" style="display:none;position:absolute;top:110%;left:0;z-index:50;min-width:180px;max-height:220px;overflow-y:auto;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:8px;">
      ${opts.map((o, i) => `<label style="display:flex;gap:6px;align-items:center;padding:3px;font-size:12px;"><input type="checkbox" ${SELECTED_BENCHMARKS.has(o) ? "checked" : ""} onchange="toggleBenchmark('${o}', this.checked)"> <span style="width:9px;height:9px;background:${BENCH_COLORS[i % BENCH_COLORS.length]};display:inline-block;"></span> ${o === "NIFTY_50" ? "Nifty 50" : o}</label>`).join("")}
    </div>`;
}

function toggleBenchmark(name, checked) {
  if (checked) SELECTED_BENCHMARKS.add(name); else SELECTED_BENCHMARKS.delete(name);
  injectBenchmarkDropdown();
  recalc();
}

function renderControls() {
  document.getElementById("stratRows").innerHTML = STRATEGIES.map((s, i) => `<tr>
    <td><input type="checkbox" ${state[i].active ? "checked" : ""} onchange="state[${i}].active=this.checked;renderControls();recalc()"></td>
    <td class="left"><b>${s.name}</b></td>
    <td><input type="range" min="0" max="100" value="${state[i].weight}" ${state[i].active ? "" : "disabled"} oninput="state[${i}].weight=parseFloat(this.value)||0;this.nextElementSibling.textContent=state[${i}].weight.toFixed(1)+'%';recalc()"> <span>${state[i].weight.toFixed(1)}%</span></td>
    <td id="alloc_${i}">-</td><td>${(s.trades || []).length}</td><td id="cpnl_${i}">-</td><td id="cpct_${i}">-</td>
  </tr>`).join("");
}

function equalWeight() {
  const n = state.filter(x => x.active).length; if (!n) return;
  const w = Math.round((100 / n) * 10) / 10;
  state.forEach(x => { if (x.active) x.weight = w; });
  renderControls(); recalc();
}

function normalizeWeights() {
  const t = state.reduce((a, x) => a + (x.active ? x.weight : 0), 0);
  if (t <= 0) return equalWeight();
  state.forEach(x => { if (x.active) x.weight = Math.round((x.weight / t * 100) * 10) / 10; });
  renderControls(); recalc();
}

function fmtDur(eTs, xTs) {
  if (!eTs || !xTs) return "-";
  const m = Math.round(Math.max(0, new Date(xTs) - new Date(eTs)) / 60000);
  if (m < 60) return m + "m";
  const h = Math.floor(m / 60), rm = m % 60;
  if (h < 24) return h + "h" + (rm ? " " + rm + "m" : "");
  const d = Math.floor(h / 24), rh = h % 24;
  return d + "d" + (rh ? " " + rh + "h" : "");
}

function recalc() {
  const cap = parseFloat(document.getElementById("capInput")?.value || "1000000") || 1000000;
  const totW = state.reduce((a, x) => a + (x.active ? x.weight : 0), 0);
  document.getElementById("allocSummary").textContent = `Allocated: ${totW.toFixed(1)}% | Cash: ${Math.max(0, 100 - totW).toFixed(1)}%`;

  window.activeTrades = [];
  let totPnl = 0;
  const contribs = STRATEGIES.map((s, i) => {
    if (!state[i]?.active || state[i].weight <= 0) return 0;
    const alloc = cap * (state[i].weight / 100), scale = s.base_capital > 0 ? alloc / s.base_capital : 1;
    let c = 0;
    (s.trades || []).forEach(tr => {
      const p = (tr.net_pnl || 0) * scale;
      c += p;
      window.activeTrades.push({
        ...tr, strategy: s.name, uid: s.name + "_" + tr.trade_id, scaled_pnl: p,
        duration_ms: (tr.entry_ts && tr.exit_ts) ? Math.max(0, new Date(tr.exit_ts) - new Date(tr.entry_ts)) : 0,
        duration_str: fmtDur(tr.entry_ts, tr.exit_ts),
      });
    });
    totPnl += c; return c;
  });

  STRATEGIES.forEach((_, i) => {
    document.getElementById("alloc_" + i).textContent = Math.round(state[i].active ? cap * (state[i].weight / 100) : 0).toLocaleString();
    document.getElementById("cpnl_" + i).textContent = Math.round(contribs[i]).toLocaleString();
    document.getElementById("cpct_" + i).textContent = (totPnl ? (contribs[i] / Math.abs(totPnl)) * 100 : 0).toFixed(1) + "%";
  });

  populateFilters();
  applyFilters();
}

function populateFilters() {
  const fill = (id, vals) => {
    const s = document.getElementById(id); if (!s) return; const c = s.value;
    s.innerHTML = '<option value="">All</option>' + [...new Set(vals.filter(Boolean))].sort().map(v => `<option value="${v}">${v}</option>`).join("");
    s.value = c;
  };
  fill("fStrat", window.activeTrades.map(t => t.strategy));
  fill("fSym", window.activeTrades.map(t => t.symbol));
  fill("fReg", window.activeTrades.map(t => t.regime_at_entry));
  fill("fExit", window.activeTrades.map(t => t.exit_reason));
}

function clearFilters() { ["fStrat", "fSym", "fOut", "fReg", "fExit", "fFrom", "fTo"].forEach(id => { const el = document.getElementById(id); if (el) el.value = ""; }); applyFilters(); }
function sortBy(col) { if (sortCol === col) sortAsc = !sortAsc; else { sortCol = col; sortAsc = true; } applyFilters(); }

function applyFilters() {
  const val = id => document.getElementById(id)?.value || "";
  const fs = val("fStrat"), fym = val("fSym"), fo = val("fOut"), fr = val("fReg"), fx = val("fExit"), ff = val("fFrom"), ft = val("fTo");
  const cap = parseFloat(document.getElementById("capInput")?.value || "1000000") || 1000000;

  const list = window.activeTrades.filter(t => {
    const d = (t.entry_ts || "").slice(0, 10);
    return (!fs || t.strategy === fs) && (!fym || t.symbol === fym) && (!fo || (fo === "win" ? t.scaled_pnl > 0 : t.scaled_pnl <= 0)) && (!fr || t.regime_at_entry === fr) && (!fx || t.exit_reason === fx) && (!ff || d >= ff) && (!ft || d <= ft);
  });

  list.forEach(t => {
    const qty = Number(t.qty_peak || 0), slipCost = qty > 0 ? qty * (Number(t.avg_entry || 0) + Number(t.avg_exit || 0)) * (SIM_SLIPPAGE_PCT / 100.0) : 0;
    t.adj_pnl = t.scaled_pnl - slipCost;
    t.adj_r = (t.scaled_pnl !== 0 && Number.isFinite(Number(t.money_r))) ? Number(t.money_r) * (t.adj_pnl / t.scaled_pnl) : Number(t.money_r || 0);
  });
  filteredTrades = list;

  list.sort((a, b) => {
    const va = a[sortCol], vb = b[sortCol];
    if (typeof va === "string" || typeof vb === "string") return sortAsc ? String(va ?? "").localeCompare(String(vb ?? "")) : String(vb ?? "").localeCompare(String(va ?? ""));
    return sortAsc ? Number(va ?? 0) - Number(vb ?? 0) : Number(vb ?? 0) - Number(va ?? 0);
  });

  const wins = list.filter(t => t.adj_pnl > 0), losses = list.filter(t => t.adj_pnl <= 0);
  const gp = wins.reduce((a, t) => a + t.adj_pnl, 0), glAbs = Math.abs(losses.reduce((a, t) => a + t.adj_pnl, 0)), pnl = gp - glAbs, nT = list.length;
  const chrono = [...list].sort((a, b) => String(a.exit_ts || "").localeCompare(String(b.exit_ts || "")));
  const dates = STRATEGIES.length && (STRATEGIES[0].dates || []).length ? STRATEGIES[0].dates : [...new Set(chrono.map(t => String(t.exit_ts || "").slice(0, 10)).filter(Boolean))].sort();
  const pnlByDay = {};
  chrono.forEach(t => { const d = String(t.exit_ts || "").slice(0, 10); if (d) pnlByDay[d] = (pnlByDay[d] || 0) + t.adj_pnl; });

  let runEq = cap, pkEq = cap, maxDdF = 0;
  const fEq = [], fRets = [];
  dates.forEach((d, idx) => { const prev = runEq; runEq += (pnlByDay[d] || 0); if (idx > 0 && prev > 0) fRets.push((runEq - prev) / prev); fEq.push(runEq); });
  const fPortPct = fEq.map(v => (cap > 0 ? (v / cap - 1) * 100 : 0));
  const fDd = fEq.map(v => { if (v > pkEq) pkEq = v; const dd = pkEq > 0 ? ((v - pkEq) / pkEq) * 100 : 0; if (dd < maxDdF) maxDdF = dd; return dd; });
  const fBenchPct = BENCH.closes && BENCH.closes.length === fEq.length && BENCH.closes[0] > 0 ? BENCH.closes.map(c => (c / BENCH.closes[0] - 1) * 100) : [];
  const capUsedInr = dates.map(d => chrono.reduce((acc, t) => (String(t.entry_ts || "").slice(0, 10) <= d && d <= String(t.exit_ts || "").slice(0, 10) ? acc + Number(t.qty_peak || 0) * Number(t.avg_entry || 0) : acc), 0));
  const capUsedPct = capUsedInr.map(v => (cap > 0 ? (v / cap) * 100 : 0));

  if (simViewEnd === null || simViewEnd >= dates.length) { simViewStart = 0; simViewEnd = Math.max(0, dates.length - 1); }
  if (fPortPct.length) drawPctChart(fPortPct, fDd, dates, fBenchPct, capUsedPct, capUsedInr);

  const avgWin = wins.length ? gp / wins.length : 0, avgLoss = losses.length ? glAbs / losses.length : 0;
  const meanR = fRets.length ? fRets.reduce((a, b) => a + b, 0) / fRets.length : 0;
  const stdR = fRets.length > 1 ? Math.sqrt(fRets.reduce((a, b) => a + (b - meanR) ** 2, 0) / (fRets.length - 1)) : 0;
  const holdDays = t => (t.entry_ts && t.exit_ts) ? Math.max(0, (new Date(t.exit_ts) - new Date(t.entry_ts)) / 86400000) : 0;

  const kpis = [
    ["Final Equity", "INR " + Math.round(fEq.length ? fEq[fEq.length - 1] : cap + pnl).toLocaleString()],
    ["Portfolio Return", (fPortPct.length ? fPortPct[fPortPct.length - 1] : (pnl / cap) * 100).toFixed(2) + "%"],
    ["Nifty 50 Return", (fBenchPct[fBenchPct.length - 1] || 0).toFixed(2) + "%"],
    ["Max Drawdown", maxDdF.toFixed(2) + "%"],
    ["Sharpe", (stdR > 0 ? (meanR / stdR) * Math.sqrt(252) : 0).toFixed(2)],
    ["Total Closed", nT], ["Winning", wins.length], ["Losing", losses.length],
    ["Win Rate", (nT ? (wins.length / nT) * 100 : 0).toFixed(1) + "%"],
    ["Avg Win", "INR " + Math.round(avgWin).toLocaleString()],
    ["Avg Loss", "INR " + Math.round(avgLoss).toLocaleString()],
    ["Payoff Ratio", (avgLoss > 0 ? avgWin / avgLoss : 0).toFixed(2)],
    ["Expectancy", "INR " + Math.round(nT ? pnl / nT : 0).toLocaleString()],
    ["Expectancy (R)", (nT ? list.reduce((a, t) => a + t.adj_r, 0) / nT : 0).toFixed(2) + "R"],
    ["Profit Factor", (glAbs > 0 ? gp / glAbs : (gp > 0 ? 999 : 0)).toFixed(2)],
    ["Avg Hold (All)", (nT ? list.reduce((a, t) => a + holdDays(t), 0) / nT : 0).toFixed(1) + "d"],
  ];
  document.getElementById("kpiGrid").innerHTML = kpis.map(([l, v]) => `<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join("");
  document.getElementById("filteredBar").innerHTML = `<b>Showing:</b> ${nT}/${window.activeTrades.length} | <b>Net P&amp;L:</b> INR ${Math.round(pnl).toLocaleString()}`;
  document.getElementById("tradeRows").innerHTML = list.map(t => `<tr>
    <td class="left"><a href="javascript:void(0)" onclick="openTrade('${t.uid}')">#${t.trade_id}</a></td>
    <td class="left">${t.strategy}</td><td class="left"><b>${t.symbol}</b></td>
    <td class="left">${(t.entry_ts || "").slice(0, 16).replace("T", " ")}</td>
    <td class="left">${(t.exit_ts || "").slice(0, 16).replace("T", " ")}</td>
    <td>${t.duration_str}</td>
    <td>${Number(t.avg_entry || 0).toFixed(2)}</td><td>${Number(t.avg_exit || 0).toFixed(2)}</td>
    <td>${Number(t.initial_stop || 0).toFixed(2)}</td><td>${Math.round(Number(t.charges || 0)).toLocaleString()}</td>
    <td class="${t.adj_pnl >= 0 ? "pos" : "neg"}">${Math.round(t.adj_pnl).toLocaleString()}</td>
    <td class="${t.adj_r >= 0 ? "pos" : "neg"}">${Number(t.adj_r || 0).toFixed(2)}R</td>
    <td class="left">${t.exit_reason || ""}</td>
  </tr>`).join("");
}

function setCapUsedUnit(u) { capUsedUnit = u; document.getElementById("capUsedUnitLbl").textContent = u === "pct" ? "% of Capital" : "INR"; if (lastSimSeries) drawPctChart(lastSimSeries.portPct, lastSimSeries.dd, lastSimSeries.dates, lastSimSeries.benchPct, lastSimSeries.capUsedPct, lastSimSeries.capUsedInr); }
function resetSimRange() { if (!lastSimSeries) return; simViewStart = 0; simViewEnd = lastSimSeries.dates.length - 1; drawPctChart(lastSimSeries.portPct, lastSimSeries.dd, lastSimSeries.dates, lastSimSeries.benchPct, lastSimSeries.capUsedPct, lastSimSeries.capUsedInr); }
function onSimSliderInput() {
  if (!lastSimSeries) return;
  const maxIdx = lastSimSeries.dates.length - 1;
  let s = parseInt(document.getElementById("simRangeStart").value, 10) || 0, e = parseInt(document.getElementById("simRangeEnd").value, 10) || maxIdx;
  if (s >= e) { s = Math.max(0, e - 1); }
  simViewStart = s; simViewEnd = e;
  drawPctChart(lastSimSeries.portPct, lastSimSeries.dd, lastSimSeries.dates, lastSimSeries.benchPct, lastSimSeries.capUsedPct, lastSimSeries.capUsedInr);
}

function drawPctChart(portPct, dd, dates, benchPct, capUsedPct = [], capUsedInr = []) {
  const eSvg = document.getElementById("eqSvg"), dSvg = document.getElementById("ddSvg"), cSvg = document.getElementById("capUsedSvg");
  if (!eSvg || !dSvg || !portPct.length) return;
  lastSimSeries = { portPct, dd, dates, benchPct, capUsedPct, capUsedInr };
  const totalLen = portPct.length, sIdx = Math.max(0, Math.min(totalLen - 1, simViewStart)), eIdx = Math.max(sIdx, Math.min(totalLen - 1, simViewEnd ?? totalLen - 1));
  document.getElementById("simRangeStart").max = totalLen - 1; document.getElementById("simRangeStart").value = sIdx;
  document.getElementById("simRangeEnd").max = totalLen - 1; document.getElementById("simRangeEnd").value = eIdx;
  document.getElementById("simRangeLbl").textContent = `${dates[sIdx] || ""} → ${dates[eIdx] || ""}`;

  const vPort = portPct.slice(sIdx, eIdx + 1), vDd = dd.slice(sIdx, eIdx + 1), vDates = dates.slice(sIdx, eIdx + 1);
  const vBench = benchPct.length === totalLen ? benchPct.slice(sIdx, eIdx + 1) : [];
  const vCap = (capUsedUnit === "inr" ? capUsedInr : capUsedPct).slice(sIdx, eIdx + 1);
  const W = 1100, H = 320, P = 56, R = 20, gridCol = isDarkMode() ? "#334155" : "#e2e8f0", lblCol = isDarkMode() ? "#94a3b8" : "#64748b";
  let ymin = Math.min(...vPort, ...(vBench.length ? vBench : [0]), 0), ymax = Math.max(...vPort, ...(vBench.length ? vBench : [0]), 0);
  if (ymax === ymin) { ymax += 1; ymin -= 1; }
  const mx = i => P + (W - P - R) * (i / Math.max(1, vPort.length - 1));
  const my = v => (H - 30) - (H - 50) * ((v - ymin) / (ymax - ymin));
  let g = "";
  for (let k = 0; k <= 4; k++) { const v = ymin + (ymax - ymin) * (k / 4), y = my(v); g += `<line x1="${P}" y1="${y}" x2="${W - R}" y2="${y}" stroke="${gridCol}" stroke-dasharray="3,3"/><text x="${P - 6}" y="${y + 4}" font-size="11" text-anchor="end" fill="${lblCol}">${v.toFixed(1)}%</text>`; }
  const pEq = vPort.map((v, i) => `${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ");
  const pB = (document.getElementById("showBench")?.checked && vBench.length) ? `<polyline fill="none" stroke="#94a3b8" stroke-width="1.6" stroke-dasharray="5,4" points="${vBench.map((v, i) => `${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ")}"/>` : "";
  eSvg.innerHTML = `${g}${pB}<polyline fill="none" stroke="#3b82f6" stroke-width="2.4" points="${pEq}"/><text x="${P}" y="${H - 8}" font-size="11" fill="${lblCol}">${vDates[0] || ""}</text><text x="${W - R}" y="${H - 8}" font-size="11" text-anchor="end" fill="${lblCol}">${vDates[vDates.length - 1] || ""}</text>`;

  const Hd = 240, dmin = Math.min(...vDd, -0.5), myd = v => 20 + (Hd - 50) * (v / dmin);
  const dPts = vDd.map((v, i) => `${mx(i).toFixed(1)},${myd(v).toFixed(1)}`).join(" ");
  dSvg.innerHTML = `<polygon fill="rgba(220,38,38,0.14)" points="${P},${myd(0)} ${dPts} ${W - R},${myd(0)}"/><polyline fill="none" stroke="#dc2626" stroke-width="2" points="${dPts}"/><text x="${P - 6}" y="${myd(dmin) + 4}" font-size="11" text-anchor="end" fill="${lblCol}">${dmin.toFixed(1)}%</text>`;

  if (cSvg) {
    const Hc = 220, cmax = Math.max(...vCap, capUsedUnit === "inr" ? 1000 : 10), myc = v => (Hc - 28) - (Hc - 46) * (v / cmax);
    const cPts = vCap.map((v, i) => `${mx(i).toFixed(1)},${myc(v).toFixed(1)}`).join(" ");
    cSvg.innerHTML = `<polygon fill="rgba(16,185,129,0.16)" points="${P},${myc(0)} ${cPts} ${W - R},${myc(0)}"/><polyline fill="none" stroke="#10b981" stroke-width="2" points="${cPts}"/>`;
  }
}

function runMonteCarlo() {
  const trades = filteredTrades.length ? filteredTrades : window.activeTrades;
  const svg = document.getElementById("mcSvg"), stats = document.getElementById("mcStats");
  if (!trades.length) { stats.innerHTML = "<span class='muted'>No trades</span>"; return; }
  const nSims = parseInt(document.getElementById("mc_sims").value || "1000", 10), cap = parseFloat(document.getElementById("capInput").value || "1000000") || 1000000;
  const pnls = trades.map(t => t.adj_pnl), n = pnls.length, mdds = [];
  for (let s = 0; s < nSims; s++) {
    const arr = [...pnls].sort(() => Math.random() - 0.5);
    let eq = cap, pk = cap, mdd = 0;
    arr.forEach(p => { eq += p; if (eq > pk) pk = eq; const d = pk > 0 ? ((pk - eq) / pk) * 100 : 0; if (d > mdd) mdd = d; });
    mdds.push(mdd);
  }
  mdds.sort((a, b) => a - b);
  stats.innerHTML = `<span><b>Median DD:</b> -${mdds[Math.floor(nSims * 0.5)].toFixed(2)}%</span><span><b>95th Pct DD:</b> -${mdds[Math.floor(nSims * 0.95)].toFixed(2)}%</span>`;
}

window.onSessionChanged = name => loadRun(name);
window.onThemeChanged = () => recalc();

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("capInput")?.addEventListener("input", recalc);
  document.getElementById("simSlipInput")?.addEventListener("input", e => { SIM_SLIPPAGE_PCT = Math.max(0, parseFloat(e.target.value) || 0); localStorage.setItem("tfalgo_sim_slip_pct", String(SIM_SLIPPAGE_PCT)); applyFilters(); });
  loadRun(getActiveSession());
});
