let STRATEGIES = [], BENCH = {dates:[], closes:[]}, state = [], activeTrades = [], sortCol = "entry_ts", sortAsc = false;
let currentTrade = null, currentTf = "5m";

function showTab(name, btn) {
  ["sim","runner","live"].forEach(t => document.getElementById("tab_"+t).style.display = (t===name?"block":"none"));
  document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  if (name === "live") fetch("/api/live").then(r=>r.json()).then(d => document.getElementById("liveMsg").textContent = d.message);
}

async function init() {
  const cfgs = await (await fetch("/api/configs")).json();
  document.getElementById("cfgChecks").innerHTML = cfgs.configs.map(c => `<label style="font-size:13px;"><input type="checkbox" class="cfg-cb" value="${c}" checked> ${c}</label>`).join("");
  await refreshRuns();
}

async function refreshRuns() {
  const data = await (await fetch("/api/runs")).json();
  const sel = document.getElementById("runSelect");
  sel.innerHTML = data.runs.map((r, i) => `<option value="${r}">${r}${i===0?" (latest)":""}</option>`).join("");
  if (data.runs.length) await loadRun(data.runs[0]);
}

async function runBatchNow() {
  const configs = [...document.querySelectorAll(".cfg-cb:checked")].map(x => x.value);
  const res = await (await fetch("/api/run_batch", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({configs})})).json();
  if (!res.ok) { document.getElementById("runStatusMsg").textContent = res.error; return; }
  const timer = setInterval(async () => {
    const st = await (await fetch("/api/status")).json();
    document.getElementById("runStatusMsg").textContent = st.last_error ? ("Error: " + st.last_error) : st.message;
    if (!st.running) { clearInterval(timer); await refreshRuns(); }
  }, 1000);
}

async function loadRun(runId) {
  const run = await (await fetch("/api/run/" + encodeURIComponent(runId))).json();
  STRATEGIES = run.strategies || [];
  BENCH = run.bench || {dates:[], closes:[]};
  document.getElementById("capInput").value = Math.round(run.initial_capital || 1000000);
  state = STRATEGIES.map(() => ({active:true, weight: STRATEGIES.length ? Math.round((100/STRATEGIES.length)*10)/10 : 0}));
  renderControls(); recalc();
}

function renderControls() {
  document.getElementById("stratRows").innerHTML = STRATEGIES.map((s,i) => `<tr>
    <td><input type="checkbox" ${state[i].active?"checked":""} onchange="state[${i}].active=this.checked;renderControls();recalc()"></td>
    <td class="left"><b>${s.name}</b></td>
    <td><input type="range" min="0" max="100" value="${state[i].weight}" ${state[i].active?"":"disabled"} oninput="state[${i}].weight=parseFloat(this.value)||0;this.nextElementSibling.textContent=state[${i}].weight.toFixed(1)+'%';recalc()"> <span>${state[i].weight.toFixed(1)}%</span></td>
    <td id="alloc_${i}">-</td><td>${s.trades.length}</td><td id="cpnl_${i}">-</td><td id="cpct_${i}">-</td>
  </tr>`).join("");
}

function equalWeight() { const n = state.filter(x=>x.active).length; if(!n) return; state.forEach(x=>{if(x.active)x.weight=Math.round((100/n)*10)/10;}); renderControls(); recalc(); }
function normalizeWeights() { const t = state.reduce((a,x)=>a+(x.active?x.weight:0),0); if(t<=0) return equalWeight(); state.forEach(x=>{if(x.active)x.weight=Math.round((x.weight/t*100)*10)/10;}); renderControls(); recalc(); }

function recalc() {
  const cap = parseFloat(document.getElementById("capInput").value) || 1000000;
  const totW = state.reduce((a,x)=>a+(x.active?x.weight:0),0);
  document.getElementById("allocSummary").textContent = `Allocated: ${totW.toFixed(1)}% | Cash: ${Math.max(0,100-totW).toFixed(1)}%`;
  const dates = STRATEGIES.length ? STRATEGIES[0].dates : [];
  const nDays = STRATEGIES.length ? STRATEGIES[0].daily_returns.length : 0;
  const eq = [cap], rets = [];
  for (let t=1; t<nDays; t++) {
    let r = 0;
    STRATEGIES.forEach((s,i)=>{ if(state[i].active && t<s.daily_returns.length) r += (state[i].weight/100)*s.daily_returns[t]; });
    rets.push(r); eq.push(eq[eq.length-1]*(1+r));
  }
  const portPct = eq.map(v => cap>0 ? (v/cap - 1)*100 : 0);
  const benchPct = (BENCH.closes && BENCH.closes.length===eq.length && BENCH.closes[0]>0) ? BENCH.closes.map(c => (c/BENCH.closes[0] - 1)*100) : [];
  let pk = eq[0], maxDd = 0;
  const dd = eq.map(v => { if(v>pk)pk=v; const d=pk>0?(v-pk)/pk*100:0; if(d<maxDd)maxDd=d; return d; });

  drawPctChart(portPct, dd, dates, benchPct);

  activeTrades = [];
  let totPnl = 0;
  const contribs = STRATEGIES.map((s,i)=>{
    if(!state[i].active || state[i].weight<=0) return 0;
    const alloc = cap*(state[i].weight/100), scale = s.base_capital>0?alloc/s.base_capital:1;
    let c = 0;
    s.trades.forEach(tr=>{ const p = tr.net_pnl*scale; c+=p; activeTrades.push({...tr, strategy:s.name, uid:s.name+"_"+tr.trade_id, scaled_pnl:p}); });
    totPnl += c; return c;
  });
  STRATEGIES.forEach((s,i)=>{
    document.getElementById("alloc_"+i).textContent = Math.round(state[i].active?cap*(state[i].weight/100):0).toLocaleString();
    document.getElementById("cpnl_"+i).textContent = Math.round(contribs[i]).toLocaleString();
    document.getElementById("cpct_"+i).textContent = (totPnl?contribs[i]/Math.abs(totPnl)*100:0).toFixed(1)+"%";
  });

  const wins = activeTrades.filter(t=>t.scaled_pnl>0), gp = wins.reduce((a,t)=>a+t.scaled_pnl,0);
  const gl = activeTrades.filter(t=>t.scaled_pnl<=0).reduce((a,t)=>a+t.scaled_pnl,0);
  const meanR = rets.length?rets.reduce((a,b)=>a+b,0)/rets.length:0;
  const stdR = rets.length>1?Math.sqrt(rets.reduce((a,b)=>a+(b-meanR)**2,0)/(rets.length-1)):0;
  const kpis = [
    ["Final Equity", "INR "+Math.round(eq[eq.length-1]).toLocaleString()],
    ["Portfolio Return", (portPct[portPct.length-1]||0).toFixed(2)+"%"],
    ["Nifty 50 Return", (benchPct[benchPct.length-1]||0).toFixed(2)+"%"],
    ["Max Drawdown", maxDd.toFixed(2)+"%"],
    ["Sharpe", (stdR>0?meanR/stdR*Math.sqrt(252):0).toFixed(2)],
    ["Trades", activeTrades.length],
    ["Win Rate", (activeTrades.length?wins.length/activeTrades.length*100:0).toFixed(1)+"%"],
    ["Profit Factor", (gl<0?gp/Math.abs(gl):(gp>0?999:0)).toFixed(2)],
  ];
  document.getElementById("kpiGrid").innerHTML = kpis.map(([l,v])=>`<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join("");
  populateFilters(); applyFilters();
}

function drawPctChart(portPct, dd, dates, benchPct) {
  const showB = document.getElementById("showBench").checked && benchPct.length === portPct.length;
  const eSvg = document.getElementById("eqSvg"), W=1100, H=320, P=56, R=20;
  if (!portPct.length) return;
  const all = showB ? portPct.concat(benchPct, [0]) : portPct.concat([0]);
  let ymin = Math.min(...all), ymax = Math.max(...all);
  if (ymax===ymin) { ymax+=1; ymin-=1; }
  const mx = i => P + (W-P-R)*(i/Math.max(1,portPct.length-1));
  const my = v => (H-30) - (H-50)*((v-ymin)/(ymax-ymin));
  let g = "";
  for (let k=0; k<=4; k++) {
    const v = ymin + (ymax-ymin)*(k/4), y = my(v);
    g += `<line x1="${P}" y1="${y}" x2="${W-R}" y2="${y}" stroke="#e2e8f0" stroke-dasharray="3,3"/>`;
    g += `<text x="${P-6}" y="${y+4}" font-size="11" text-anchor="end" fill="#64748b">${v.toFixed(1)}%</text>`;
  }
  const y0 = my(0);
  g += `<line x1="${P}" y1="${y0}" x2="${W-R}" y2="${y0}" stroke="#94a3b8" stroke-width="1"/>`;
  const pEq = portPct.map((v,i)=>`${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ");
  const pB = showB ? `<polyline fill="none" stroke="#64748b" stroke-width="1.6" stroke-dasharray="5,4" points="${benchPct.map((v,i)=>`${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ")}"/>` : "";
  eSvg.innerHTML = `${g}${pB}<polyline fill="none" stroke="#2563eb" stroke-width="2.4" points="${pEq}"/>
    <text x="${P}" y="${H-8}" font-size="11" fill="#64748b">${dates[0]||""}</text>
    <text x="${W-R}" y="${H-8}" font-size="11" text-anchor="end" fill="#64748b">${dates[dates.length-1]||""}</text>`;

  const dSvg = document.getElementById("ddSvg"), Hd=240, dmin=Math.min(...dd,-0.5);
  const myd = v => 20 + (Hd-50)*(v/dmin);
  const dPts = dd.map((v,i)=>`${mx(i).toFixed(1)},${myd(v).toFixed(1)}`).join(" ");
  dSvg.innerHTML = `<polygon fill="rgba(220,38,38,0.14)" points="${P},${myd(0)} ${dPts} ${W-R},${myd(0)}"/><polyline fill="none" stroke="#dc2626" stroke-width="2" points="${dPts}"/>
    <text x="${P-6}" y="${myd(dmin)+4}" font-size="11" text-anchor="end" fill="#64748b">${dmin.toFixed(1)}%</text>`;
}

function populateFilters() {
  const fill = (id, vals) => { const s=document.getElementById(id), c=s.value; s.innerHTML='<option value="">All</option>'+[...new Set(vals)].sort().map(v=>`<option value="${v}">${v}</option>`).join(""); s.value=c; };
  fill("fStrat", activeTrades.map(t=>t.strategy)); fill("fSym", activeTrades.map(t=>t.symbol));
  fill("fReg", activeTrades.map(t=>t.regime_at_entry)); fill("fExit", activeTrades.map(t=>t.exit_reason));
}
function clearFilters() { ["fStrat","fSym","fOut","fReg","fExit","fFrom","fTo"].forEach(id=>document.getElementById(id).value=""); applyFilters(); }
function sortBy(col) { if(sortCol===col) sortAsc=!sortAsc; else {sortCol=col;sortAsc=true;} applyFilters(); }

function applyFilters() {
  const fs=fStrat.value, fym=fSym.value, fo=fOut.value, fr=fReg.value, fx=fExit.value, ff=fFrom.value, ft=fTo.value;
  const list = activeTrades.filter(t => (!fs||t.strategy===fs)&&(!fym||t.symbol===fym)&&(!fo||(fo==="win"?t.scaled_pnl>0:t.scaled_pnl<=0))&&(!fr||t.regime_at_entry===fr)&&(!fx||t.exit_reason===fx)&&(!ff||t.entry_ts.slice(0,10)>=ff)&&(!ft||t.entry_ts.slice(0,10)<=ft));
  list.sort((a,b)=> typeof a[sortCol]==="string" ? (sortAsc?a[sortCol].localeCompare(b[sortCol]):b[sortCol].localeCompare(a[sortCol])) : (sortAsc?a[sortCol]-b[sortCol]:b[sortCol]-a[sortCol]));
  const pnl = list.reduce((a,t)=>a+t.scaled_pnl,0), w = list.filter(t=>t.scaled_pnl>0).length;
  document.getElementById("filteredBar").innerHTML = `<b>Showing:</b> ${list.length}/${activeTrades.length} | <b>Win Rate:</b> ${(list.length?w/list.length*100:0).toFixed(1)}% | <b>Net P&amp;L:</b> INR ${Math.round(pnl).toLocaleString()}`;
  document.getElementById("tradeRows").innerHTML = list.map(t=>`<tr>
    <td class="left"><span class="trade-link" onclick="openTrade('${t.uid}')">#${t.trade_id}</span></td>
    <td class="left">${t.strategy}</td><td class="left"><b>${t.symbol}</b></td>
    <td class="left">${t.entry_ts.slice(0,16).replace("T"," ")}</td><td class="left">${t.exit_ts.slice(0,16).replace("T"," ")}</td>
    <td>${t.avg_entry.toFixed(2)}</td><td>${t.avg_exit.toFixed(2)}</td><td>${t.initial_stop.toFixed(2)}</td>
    <td class="${t.scaled_pnl>=0?'pos':'neg'}"><b>${Math.round(t.scaled_pnl).toLocaleString()}</b></td>
    <td class="${t.money_r>=0?'pos':'neg'}">${t.money_r.toFixed(2)}R</td><td class="left">${t.exit_reason}</td>
  </tr>`).join("");
}

function openTrade(uid) {
  currentTrade = activeTrades.find(x=>x.uid===uid);
  if (!currentTrade) return;
  document.getElementById("modalTitle").textContent = `${currentTrade.symbol} — Trade #${currentTrade.trade_id} (${currentTrade.strategy})`;
  document.getElementById("modalSub").innerHTML = `Entry: <b>${currentTrade.avg_entry.toFixed(2)}</b> (${currentTrade.entry_ts.slice(0,16).replace("T"," ")}) | Exit: <b>${currentTrade.avg_exit.toFixed(2)}</b> (${currentTrade.exit_ts.slice(0,16).replace("T"," ")}) | Stop: <b style="color:#dc2626">${currentTrade.initial_stop.toFixed(2)}</b> | P&amp;L: <b class="${currentTrade.scaled_pnl>=0?'pos':'neg'}">INR ${Math.round(currentTrade.scaled_pnl).toLocaleString()} (${currentTrade.money_r.toFixed(2)}R)</b>`;
  document.getElementById("tradeModal").classList.add("open");
  fetchTradeChart();
}
function closeModal() { document.getElementById("tradeModal").classList.remove("open"); }
document.addEventListener("keydown", e => { if(e.key==="Escape") closeModal(); });

function setTf(tf, btn) {
  currentTf = tf;
  document.querySelectorAll(".tf-btn").forEach(b=>b.classList.remove("active"));
  btn.classList.add("active");
  fetchTradeChart();
}

async function fetchTradeChart() {
  if (!currentTrade) return;
  const q = new URLSearchParams({
    symbol: currentTrade.symbol, tf: currentTf,
    entry: currentTrade.entry_ts.slice(0,10), exit: currentTrade.exit_ts.slice(0,10),
    pattern: currentTrade.pattern || "none"
  });
  const data = await (await fetch("/api/candles?" + q)).json();
  drawCandles(data.candles || [], data.pattern_shapes || {});
}

function drawCandles(bars, pat) {
  const svg = document.getElementById("candleSvg");
  if (!bars.length) { svg.innerHTML = `<text x="550" y="240" text-anchor="middle" fill="#64748b">No data for timeframe ${currentTf}</text>`; return; }
  const showE = togEmas.checked, showV = togVol.checked, showP = togPat.checked;
  const W=1100, H=500, P=64, R=30, T=30, B=showV?110:48, V_TOP=H-94, V_BOT=H-40;
  const ev = [];
  if (showE) bars.forEach(b=>{ if(b.ema9)ev.push(b.ema9); if(b.ema21)ev.push(b.ema21); if(b.ema50)ev.push(b.ema50); });
  let pmin = Math.min(...bars.map(b=>b.l), currentTrade.initial_stop, ...ev);
  let pmax = Math.max(...bars.map(b=>b.h), currentTrade.initial_stop, ...ev);
  const pad = (pmax-pmin)*0.10 || 1; pmin-=pad; pmax+=pad;
  const cw = Math.max(2, Math.min(10, (W-P-R)/bars.length*0.7));
  const mx = i => P + (W-P-R)*((i+0.5)/bars.length);
  const my = v => T + (H-T-B)*(1-(v-pmin)/(pmax-pmin));
  let out = "";
  for (let g=0; g<=5; g++) {
    const v=pmin+(pmax-pmin)*(g/5), y=my(v);
    out += `<line x1="${P}" y1="${y}" x2="${W-R}" y2="${y}" stroke="#f1f5f9"/><text x="${P-8}" y="${y+4}" font-size="11" text-anchor="end" fill="#64748b">${v.toFixed(2)}</text>`;
  }
  // Pattern curve/box (VCP zig-zag or Flat Base or OR)
  if (showP && pat && pat.type === "vcp" && pat.zigzag && pat.zigzag.length) {
    const zpts = pat.zigzag.map(z => {
      const idx = bars.findIndex(b => b.t.slice(0,10) >= z.t.slice(0,10));
      return idx >= 0 ? `${mx(idx).toFixed(1)},${my(z.p).toFixed(1)}` : null;
    }).filter(Boolean);
    if (zpts.length > 1) out += `<polyline fill="none" stroke="#8b5cf6" stroke-width="2" stroke-dasharray="4,2" points="${zpts.join(" ")}"/>`;
    if (pat.pivot) out += `<line x1="${P}" y1="${my(pat.pivot)}" x2="${W-R}" y2="${my(pat.pivot)}" stroke="#8b5cf6" stroke-width="1.2" stroke-dasharray="5,3"/>`;
  } else if (showP && pat && pat.type === "flat_base") {
    const i0 = Math.max(0, bars.findIndex(b => b.t.slice(0,10) >= pat.t0.slice(0,10)));
    const i1 = bars.findIndex(b => b.t.slice(0,10) >= pat.t1.slice(0,10));
    if (i1 > i0) out += `<rect x="${mx(i0)}" y="${my(pat.high)}" width="${mx(i1)-mx(i0)}" height="${my(pat.low)-my(pat.high)}" fill="rgba(139,92,246,0.10)" stroke="#8b5cf6" stroke-dasharray="4,3"/>`;
  }

  // Smooth EMAs on selected timeframe
  if (showE) {
    [["ema9","#8b5cf6"],["ema21","#f59e0b"],["ema50","#0d9488"]].forEach(([k,col])=>{
      const pts = bars.map((b,i)=> b[k]!=null ? `${mx(i).toFixed(1)},${my(b[k]).toFixed(1)}` : null).filter(Boolean);
      if (pts.length>1) out += `<polyline fill="none" stroke="${col}" stroke-width="1.6" points="${pts.join(" ")}"/>`;
    });
  }
  if (showV) {
    const vmax = Math.max(...bars.map(b=>b.v||0), 1);
    bars.forEach((b,i)=>{ const vh=((b.v||0)/vmax)*(V_BOT-V_TOP-4), col=b.c>=b.o?"rgba(22,163,74,0.45)":"rgba(220,38,38,0.45)"; out+=`<rect x="${mx(i)-cw/2}" y="${V_BOT-vh}" width="${cw}" height="${vh}" fill="${col}"/>`; });
  }
  bars.forEach((b,i)=>{
    const x=mx(i), col=b.c>=b.o?"#16a34a":"#dc2626", top=Math.min(my(b.o),my(b.c)), bh=Math.max(1.5,Math.abs(my(b.o)-my(b.c)));
    out += `<g><title>${b.t.slice(0,16).replace("T"," ")} | O:${b.o} H:${b.h} L:${b.l} C:${b.c}</title><line x1="${x}" y1="${my(b.h)}" x2="${x}" y2="${my(b.l)}" stroke="${col}" stroke-width="1.2"/><rect x="${x-cw/2}" y="${top}" width="${cw}" height="${bh}" fill="${col}"/></g>`;
  });
  // Initial stop + Entry/Exit markers
  const ys = my(currentTrade.initial_stop);
  out += `<line x1="${P}" y1="${ys}" x2="${W-R}" y2="${ys}" stroke="#dc2626" stroke-width="1.4" stroke-dasharray="6,4"/><text x="${W-R-4}" y="${ys-5}" font-size="11" font-weight="700" text-anchor="end" fill="#dc2626">STOP ${currentTrade.initial_stop.toFixed(2)}</text>`;
  const eIdx = bars.findIndex(b => b.t.slice(0,16) >= currentTrade.entry_ts.slice(0,16));
  const xIdx = bars.findIndex(b => b.t.slice(0,16) >= currentTrade.exit_ts.slice(0,16));
  if (eIdx>=0) { const ex=mx(eIdx), ey=my(currentTrade.avg_entry); out+=`<line x1="${ex}" y1="${T}" x2="${ex}" y2="${H-B}" stroke="#2563eb" stroke-dasharray="2,2"/><polygon points="${ex},${ey+3} ${ex-6},${ey+15} ${ex+6},${ey+15}" fill="#2563eb"/><text x="${ex}" y="${ey+29}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#1d4ed8">ENTRY ${currentTrade.avg_entry.toFixed(2)} (${currentTrade.entry_ts.slice(11,16)})</text>`; }
  if (xIdx>=0) { const xx=mx(xIdx), xy=my(currentTrade.avg_exit); out+=`<line x1="${xx}" y1="${T}" x2="${xx}" y2="${H-B}" stroke="#d97706" stroke-dasharray="2,2"/><polygon points="${xx},${xy-3} ${xx-6},${xy-15} ${xx+6},${xy-15}" fill="#d97706"/><text x="${xx}" y="${xy-21}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#b45309">EXIT ${currentTrade.avg_exit.toFixed(2)} (${currentTrade.exit_ts.slice(11,16)})</text>`; }
  out += `<text x="${P}" y="${H-10}" font-size="11" fill="#64748b">${bars[0].t.slice(0,16).replace("T"," ")}</text><text x="${W-R}" y="${H-10}" font-size="11" text-anchor="end" fill="#64748b">${bars[bars.length-1].t.slice(0,16).replace("T"," ")}</text>`;
  svg.innerHTML = out;
}

init();