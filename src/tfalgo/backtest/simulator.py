"""Self-contained interactive HTML+JS post-backtest Portfolio Simulator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_portfolio_simulator_html(
    strategies_payload: list[dict[str, Any]],
    initial_capital: float,
    output_path: Path,
    bench_payload: dict[str, Any] | None = None,
    runs_history: list[dict[str, Any]] | None = None,
) -> Path:
    """Write interactive portfolio simulator HTML with run switcher, filters, day-wise P&L, Nifty 50 overlay, and 5m candlesticks."""
    runs = runs_history or [{
        "run_id": "current",
        "initial_capital": initial_capital,
        "strategies": strategies_payload,
        "bench": bench_payload or {"dates": [], "closes": []},
    }]
    runs_json = json.dumps(runs)

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>tfalgo Portfolio Simulator & Trade Inspector</title>
<style>
  :root {{
    --bg: #f1f5f9; --card: #ffffff; --border: #e2e8f0; --text: #0f172a;
    --muted: #64748b; --primary: #2563eb; --green: #16a34a; --red: #dc2626;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 24px; color: var(--text); background: var(--bg); }}
  .container {{ max-width: 1440px; margin: 0 auto; }}
  header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }}
  h2 {{ margin: 0; font-size: 22px; font-weight: 700; color: #0f172a; }}
  h3 {{ margin: 0 0 12px 0; font-size: 15px; font-weight: 600; color: #1e293b; }}
  .panel {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px; margin-bottom: 18px; box-shadow: 0 1px 3px rgba(15,23,42,0.04); }}
  .controls-top {{ display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 12px; }}
  .kpi {{ background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }}
  .kpi .lbl {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  .kpi .val {{ font-size: 19px; font-weight: 700; margin-top: 4px; }}
  .pos {{ color: var(--green); }} .neg {{ color: var(--red); }}
  .charts-stack {{ display: grid; grid-template-columns: 1fr; gap: 18px; }}
  .chart-hdr {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .legend {{ display: flex; gap: 16px; font-size: 12px; color: var(--muted); }}
  .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  th, td {{ border-bottom: 1px solid var(--border); padding: 8px 10px; text-align: right; white-space: nowrap; }}
  th:first-child, td:first-child, th.left, td.left {{ text-align: left; }}
  th {{ background: #f8fafc; color: #475569; font-weight: 600; position: sticky; top: 0; z-index: 2; cursor: pointer; }}
  th:hover {{ background: #eef2ff; }}
  tbody tr:hover {{ background: #f8fafc; }}
  .scroll-box {{ max-height: 360px; overflow: auto; border: 1px solid var(--border); border-radius: 8px; }}
  .filters {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(135px, 1fr)); gap: 10px; margin-bottom: 12px; background: #f8fafc; padding: 12px; border-radius: 8px; border: 1px solid var(--border); }}
  .filters label {{ display: flex; flex-direction: column; font-size: 11px; color: var(--muted); gap: 4px; font-weight: 600; }}
  input, select {{ padding: 6px 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 12.5px; background: #fff; }}
  input[type=range] {{ width: 150px; padding: 0; }}
  button {{ background: var(--primary); color: #fff; border: none; padding: 7px 13px; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 12.5px; }}
  button.sec {{ background: #475569; }} button.ghost {{ background: #e2e8f0; color: #334155; }}
  .trade-link {{ color: var(--primary); font-weight: 700; cursor: pointer; text-decoration: underline; }}
  .day-link {{ color: var(--primary); font-weight: 600; cursor: pointer; }}
  .filtered-bar {{ display: flex; gap: 18px; flex-wrap: wrap; font-size: 12.5px; padding: 8px 12px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; margin-bottom: 10px; color: #1e3a8a; }}
  .modal-bg {{ display: none; position: fixed; inset: 0; background: rgba(15,23,42,0.62); z-index: 50; align-items: center; justify-content: center; padding: 24px; }}
  .modal-bg.open {{ display: flex; }}
  .modal {{ background: #fff; border-radius: 12px; width: 100%; max-width: 1120px; padding: 20px; box-shadow: 0 20px 50px rgba(0,0,0,0.25); }}
  .modal-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }}
  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; background: #e2e8f0; color: #334155; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h2>tfalgo Portfolio Simulator & Trade Inspector</h2>
      <div style="font-size:12.5px;color:#64748b;margin-top:2px;">Toggle strategies, allocate capital, filter trades Excel-style, and click any Trade ID for its 5m candlestick chart.</div>
    </div>
    <div style="display:flex;align-items:center;gap:8px;">
      <label style="font-size:12.5px;font-weight:600;color:#334155;">Test Run:</label>
      <select id="runSelect" onchange="switchRun(this.value)" style="min-width:240px;"></select>
    </div>
  </header>

  <div class="panel">
    <div class="controls-top">
      <label style="font-size:13px;"><b>Total Capital (INR):</b> <input id="capInput" type="number" value="{int(initial_capital)}" step="50000" min="10000"></label>
      <button onclick="equalWeight()">Equal Weight Active</button>
      <button class="sec" onclick="normalizeWeights()">Normalize to 100%</button>
      <label style="font-size:13px;display:flex;align-items:center;gap:6px;cursor:pointer;">
        <input type="checkbox" id="showBench" checked onchange="recalc()"> Overlay Nifty 50
      </label>
      <span id="allocSummary" style="font-size:13px;color:#475569;margin-left:auto;font-weight:600;"></span>
    </div>
    <table>
      <thead>
        <tr>
          <th>Active</th><th class="left">Strategy</th><th>Allocation (%)</th><th>Allocated (INR)</th>
          <th>Trades</th><th>Contrib P&L (INR)</th><th>Contrib (%)</th>
        </tr>
      </thead>
      <tbody id="stratRows"></tbody>
    </table>
  </div>

  <div class="panel">
    <div class="kpis" id="kpiGrid"></div>
  </div>

  <div class="charts-stack">
    <div class="panel">
      <div class="chart-hdr">
        <h3>Portfolio Equity Curve vs. Nifty 50 (INR)</h3>
        <div class="legend">
          <span><span class="dot" style="background:#2563eb;"></span>Portfolio</span>
          <span><span class="dot" style="background:#64748b;"></span>Nifty 50 (Buy & Hold)</span>
        </div>
      </div>
      <svg id="eqSvg" viewBox="0 0 1100 320" width="100%"></svg>
    </div>
    <div class="panel">
      <div class="chart-hdr">
        <h3>Combined Portfolio Drawdown (%)</h3>
        <div class="legend"><span><span class="dot" style="background:#dc2626;"></span>Drawdown %</span></div>
      </div>
      <svg id="ddSvg" viewBox="0 0 1100 250" width="100%"></svg>
    </div>
  </div>

  <div class="panel">
    <div class="chart-hdr">
      <h3>Day-Wise Trades Summary <span style="font-weight:400;color:#64748b;font-size:12px;">(click a date to filter trades below)</span></h3>
    </div>
    <div class="scroll-box" style="max-height:240px;">
      <table>
        <thead><tr><th class="left">Date</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Daily Net P&L (INR)</th><th>Daily Sum R</th></tr></thead>
        <tbody id="dayRows"></tbody>
      </table>
    </div>
  </div>

  <div class="panel">
    <div class="chart-hdr">
      <h3>All Trades (Excel-Style Filter & Sort)</h3>
      <button class="ghost" onclick="clearFilters()">Clear Filters</button>
    </div>
    <div class="filters">
      <label>Strategy<select id="fStrat" onchange="applyTradeFilters()"><option value="">All</option></select></label>
      <label>Symbol<select id="fSym" onchange="applyTradeFilters()"><option value="">All</option></select></label>
      <label>Outcome<select id="fOutcome" onchange="applyTradeFilters()"><option value="">All</option><option value="win">Winners (&gt;0)</option><option value="loss">Losers (&lt;=0)</option></select></label>
      <label>Regime<select id="fRegime" onchange="applyTradeFilters()"><option value="">All</option></select></label>
      <label>Exit Reason<select id="fExit" onchange="applyTradeFilters()"><option value="">All</option></select></label>
      <label>From Date<input type="date" id="fFrom" onchange="applyTradeFilters()"></label>
      <label>To Date<input type="date" id="fTo" onchange="applyTradeFilters()"></label>
      <label>Min P&L (INR)<input type="number" id="fMinPnl" placeholder="e.g. -5000" oninput="applyTradeFilters()"></label>
      <label>Min R<input type="number" id="fMinR" step="0.1" placeholder="e.g. 1.0" oninput="applyTradeFilters()"></label>
    </div>
    <div class="filtered-bar" id="filteredBar"></div>
    <div class="scroll-box">
      <table>
        <thead>
          <tr>
            <th class="left" onclick="sortTrades('trade_id')">Trade ID</th>
            <th class="left" onclick="sortTrades('strategy')">Strategy</th>
            <th class="left" onclick="sortTrades('symbol')">Symbol</th>
            <th class="left" onclick="sortTrades('entry_ts')">Entry Time</th>
            <th class="left" onclick="sortTrades('exit_ts')">Exit Time</th>
            <th onclick="sortTrades('avg_entry')">Entry</th>
            <th onclick="sortTrades('avg_exit')">Exit</th>
            <th onclick="sortTrades('initial_stop')">Stop</th>
            <th onclick="sortTrades('qty_peak')">Qty</th>
            <th onclick="sortTrades('net_pnl')">Net P&L (INR)</th>
            <th onclick="sortTrades('money_r')">Money-R</th>
            <th class="left" onclick="sortTrades('regime_at_entry')">Regime</th>
            <th class="left" onclick="sortTrades('exit_reason')">Exit Reason</th>
          </tr>
        </thead>
        <tbody id="tradeRows"></tbody>
      </table>
    </div>
  </div>
</div>

<div class="modal-bg" id="tradeModal" onclick="if(event.target===this) closeModal()">
  <div class="modal">
    <div class="modal-top">
      <div>
        <h3 id="modalTitle" style="margin:0;font-size:17px;"></h3>
        <div id="modalSub" style="font-size:12.5px;color:#475569;margin-top:4px;"></div>
      </div>
      <button class="ghost" onclick="closeModal()">Close (Esc)</button>
    </div>
    <div style="display:flex;gap:16px;align-items:center;font-size:12px;color:#475569;margin-bottom:8px;flex-wrap:wrap;">
      <label style="display:flex;align-items:center;gap:5px;cursor:pointer;"><input type="checkbox" id="togEmas" checked onchange="redrawActiveTrade()"> <span style="color:#8b5cf6;font-weight:700;">9D EMA</span> / <span style="color:#f59e0b;font-weight:700;">21D EMA</span> / <span style="color:#0d9488;font-weight:700;">50D EMA</span></label>
      <label style="display:flex;align-items:center;gap:5px;cursor:pointer;"><input type="checkbox" id="togVol" checked onchange="redrawActiveTrade()"> Volume</label>
      <label style="display:flex;align-items:center;gap:5px;cursor:pointer;"><input type="checkbox" id="togPat" checked onchange="redrawActiveTrade()"> Auto Pattern Overlay</label>
    </div>
    <svg id="candleSvg" viewBox="0 0 1060 510" width="100%"></svg>
  </div>
</div>

<script>
const RUNS = {runs_json};
let STRATEGIES = RUNS[0].strategies;
let BENCH = RUNS[0].bench || {{ dates: [], closes: [] }};
let state = [];

function initRunDropdown() {{
  const sel = document.getElementById("runSelect");
  sel.innerHTML = RUNS.map((r, idx) => `<option value="${{idx}}">${{r.run_id}}${{idx === 0 ? " (latest)" : ""}}</option>`).join("");
}}

function switchRun(idxStr) {{
  const run = RUNS[parseInt(idxStr, 10) || 0];
  STRATEGIES = run.strategies || [];
  BENCH = run.bench || {{ dates: [], closes: [] }};
  document.getElementById("capInput").value = Math.round(run.initial_capital || 1000000);
  state = STRATEGIES.map(() => ({{
    active: true,
    weight: STRATEGIES.length ? Math.round((100 / STRATEGIES.length) * 10) / 10 : 0
  }}));
  clearFilters();
  renderControls();
  recalc();
}}

let activeTrades = [];
let sortCol = "entry_ts";
let sortAsc = false;

function renderControls() {{
  const tb = document.getElementById("stratRows");
  tb.innerHTML = "";
  STRATEGIES.forEach((s, i) => {{
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" ${{state[i].active ? "checked" : ""}} onchange="toggleStrat(${{i}}, this.checked)"></td>
      <td class="left"><b>${{s.name}}</b></td>
      <td>
        <input type="range" min="0" max="100" step="1" value="${{state[i].weight}}" ${{state[i].active ? "" : "disabled"}} oninput="setWeight(${{i}}, this.value)">
        <span id="wLbl_${{i}}" style="display:inline-block;width:48px;">${{state[i].weight.toFixed(1)}}%</span>
      </td>
      <td id="alloc_${{i}}">-</td>
      <td>${{s.trades.length}}</td>
      <td id="cpnl_${{i}}">-</td>
      <td id="cpct_${{i}}">-</td>`;
    tb.appendChild(tr);
  }});
}}

function toggleStrat(i, on) {{ state[i].active = on; renderControls(); recalc(); }}
function setWeight(i, val) {{ state[i].weight = parseFloat(val) || 0; document.getElementById("wLbl_"+i).textContent = state[i].weight.toFixed(1)+"%"; recalc(); }}

function equalWeight() {{
  const n = state.filter(x => x.active).length;
  if (!n) return;
  const w = Math.round((100 / n) * 10) / 10;
  state.forEach(x => {{ if (x.active) x.weight = w; }});
  renderControls(); recalc();
}}

function normalizeWeights() {{
  const tot = state.reduce((a, x) => a + (x.active ? x.weight : 0), 0);
  if (tot <= 0) return equalWeight();
  state.forEach(x => {{ if (x.active) x.weight = Math.round((x.weight / tot * 100) * 10) / 10; }});
  renderControls(); recalc();
}}

function drawPortfolioCharts(eq, dd, dates, benchEq) {{
  const showB = document.getElementById("showBench").checked && benchEq.length === eq.length;
  // Equity SVG
  const eSvg = document.getElementById("eqSvg");
  const W = 1100, H = 320, P = 56, R = 20;
  if (!eq.length) {{ eSvg.innerHTML = ""; return; }}
  const allV = showB ? eq.concat(benchEq) : eq;
  let ymin = Math.min(...allV), ymax = Math.max(...allV);
  if (ymax === ymin) ymax = ymin + 1;
  const mapX = i => P + (W - P - R) * (i / Math.max(1, eq.length - 1));
  const mapY = v => (H - 32) - (H - 54) * ((v - ymin) / (ymax - ymin));
  let grid = "";
  for (let g = 0; g <= 4; g++) {{
    const v = ymin + (ymax - ymin) * (g / 4);
    const y = mapY(v);
    grid += `<line x1="${{P}}" y1="${{y}}" x2="${{W-R}}" y2="${{y}}" stroke="#e2e8f0" stroke-dasharray="3,3"/>`;
    grid += `<text x="${{P-6}}" y="${{y+4}}" font-size="11" text-anchor="end" fill="#64748b">${{Math.round(v).toLocaleString()}}</text>`;
  }}
  const ptsEq = eq.map((v, i) => `${{mapX(i).toFixed(1)}},${{mapY(v).toFixed(1)}}`).join(" ");
  const ptsB = showB ? `<polyline fill="none" stroke="#64748b" stroke-width="1.8" stroke-dasharray="5,4" points="${{benchEq.map((v,i)=>`${{mapX(i).toFixed(1)}},${{mapY(v).toFixed(1)}}`).join(" ")}}"/>` : "";
  const dStart = dates[0] || "", dEnd = dates[dates.length - 1] || "";
  eSvg.innerHTML = `${{grid}}${{ptsB}}<polyline fill="none" stroke="#2563eb" stroke-width="2.4" points="${{ptsEq}}"/>
    <text x="${{P}}" y="${{H-10}}" font-size="11" fill="#64748b">${{dStart}}</text>
    <text x="${{W-R}}" y="${{H-10}}" font-size="11" text-anchor="end" fill="#64748b">${{dEnd}}</text>`;

  // Drawdown SVG
  const dSvg = document.getElementById("ddSvg");
  const Hd = 250;
  let dmin = Math.min(...dd, -0.5);
  const mapYd = v => 20 + (Hd - 52) * (v / dmin);
  let dGrid = "";
  for (let g = 0; g <= 3; g++) {{
    const v = dmin * (g / 3);
    const y = mapYd(v);
    dGrid += `<line x1="${{P}}" y1="${{y}}" x2="${{W-R}}" y2="${{y}}" stroke="#e2e8f0" stroke-dasharray="3,3"/>`;
    dGrid += `<text x="${{P-6}}" y="${{y+4}}" font-size="11" text-anchor="end" fill="#64748b">${{v.toFixed(1)}}%</text>`;
  }}
  const dPts = dd.map((v, i) => `${{mapX(i).toFixed(1)}},${{mapYd(v).toFixed(1)}}`).join(" ");
  const areaPts = `${{P}},${{mapYd(0)}} ${{dPts}} ${{W-R}},${{mapYd(0)}}`;
  dSvg.innerHTML = `${{dGrid}}<polygon fill="rgba(220,38,38,0.14)" points="${{areaPts}}"/><polyline fill="none" stroke="#dc2626" stroke-width="2" points="${{dPts}}"/>
    <text x="${{P}}" y="${{Hd-10}}" font-size="11" fill="#64748b">${{dStart}}</text>
    <text x="${{W-R}}" y="${{Hd-10}}" font-size="11" text-anchor="end" fill="#64748b">${{dEnd}}</text>`;
}}

function populateFilterOptions() {{
  const fill = (id, vals) => {{
    const sel = document.getElementById(id), cur = sel.value;
    sel.innerHTML = '<option value="">All</option>' + [...new Set(vals)].sort().map(v => `<option value="${{v}}">${{v}}</option>`).join("");
    sel.value = cur;
  }};
  fill("fStrat", activeTrades.map(t => t.strategy));
  fill("fSym", activeTrades.map(t => t.symbol));
  fill("fRegime", activeTrades.map(t => t.regime_at_entry));
  fill("fExit", activeTrades.map(t => t.exit_reason));
}}

function clearFilters() {{
  ["fStrat","fSym","fOutcome","fRegime","fExit","fFrom","fTo","fMinPnl","fMinR"].forEach(id => document.getElementById(id).value = "");
  applyTradeFilters();
}}

function filterByDate(d) {{
  document.getElementById("fFrom").value = d;
  document.getElementById("fTo").value = d;
  applyTradeFilters();
}}

function sortTrades(col) {{
  if (sortCol === col) sortAsc = !sortAsc;
  else {{ sortCol = col; sortAsc = true; }}
  applyTradeFilters();
}}

function applyTradeFilters() {{
  const fs = document.getElementById("fStrat").value;
  const fym = document.getElementById("fSym").value;
  const fout = document.getElementById("fOutcome").value;
  const freg = document.getElementById("fRegime").value;
  const fex = document.getElementById("fExit").value;
  const ffrom = document.getElementById("fFrom").value;
  const fto = document.getElementById("fTo").value;
  const fminp = document.getElementById("fMinPnl").value;
  const fminr = document.getElementById("fMinR").value;

  let list = activeTrades.filter(t => {{
    if (fs && t.strategy !== fs) return false;
    if (fym && t.symbol !== fym) return false;
    if (fout === "win" && t.scaled_pnl <= 0) return false;
    if (fout === "loss" && t.scaled_pnl > 0) return false;
    if (freg && t.regime_at_entry !== freg) return false;
    if (fex && t.exit_reason !== fex) return false;
    const d = t.entry_ts.slice(0, 10);
    if (ffrom && d < ffrom) return false;
    if (fto && d > fto) return false;
    if (fminp !== "" && t.scaled_pnl < parseFloat(fminp)) return false;
    if (fminr !== "" && t.money_r < parseFloat(fminr)) return false;
    return true;
  }});

  list.sort((a, b) => {{
    let va = sortCol === "net_pnl" ? a.scaled_pnl : a[sortCol];
    let vb = sortCol === "net_pnl" ? b.scaled_pnl : b[sortCol];
    if (typeof va === "string") return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    return sortAsc ? (va - vb) : (vb - va);
  }});

  // Filtered summary bar
  const wins = list.filter(t => t.scaled_pnl > 0).length;
  const sumPnl = list.reduce((a, t) => a + t.scaled_pnl, 0);
  const avgR = list.length ? list.reduce((a, t) => a + t.money_r, 0) / list.length : 0;
  document.getElementById("filteredBar").innerHTML =
    `<span><b>Showing:</b> ${{list.length}} / ${{activeTrades.length}} trades</span>` +
    `<span><b>Win Rate:</b> ${{(list.length ? wins/list.length*100 : 0).toFixed(1)}}%</span>` +
    `<span><b>Net P&L:</b> INR ${{Math.round(sumPnl).toLocaleString()}}</span>` +
    `<span><b>Avg R:</b> ${{avgR.toFixed(3)}}R</span>`;

  // Render Day-Wise table
  const byDay = {{}};
  list.forEach(t => {{
    const d = t.entry_ts.slice(0, 10);
    if (!byDay[d]) byDay[d] = {{ n: 0, w: 0, l: 0, pnl: 0, r: 0 }};
    byDay[d].n++;
    if (t.scaled_pnl > 0) byDay[d].w++; else byDay[d].l++;
    byDay[d].pnl += t.scaled_pnl;
    byDay[d].r += t.money_r;
  }});
  document.getElementById("dayRows").innerHTML = Object.keys(byDay).sort().reverse().map(d => {{
    const x = byDay[d];
    return `<tr>
      <td class="left"><span class="day-link" onclick="filterByDate('${{d}}')">${{d}}</span></td>
      <td>${{x.n}}</td><td>${{x.w}}</td><td>${{x.l}}</td>
      <td class="${{x.pnl>=0?'pos':'neg'}}">${{Math.round(x.pnl).toLocaleString()}}</td>
      <td class="${{x.r>=0?'pos':'neg'}}">${{x.r.toFixed(2)}}R</td>
    </tr>`;
  }}).join("");

  // Render Trades table
  document.getElementById("tradeRows").innerHTML = list.map(t => `<tr>
    <td class="left"><span class="trade-link" onclick="openTradeChart('${{t.uid}}')">#${{t.trade_id}}</span></td>
    <td class="left">${{t.strategy}}</td>
    <td class="left"><b>${{t.symbol}}</b></td>
    <td class="left">${{t.entry_ts.slice(0,16).replace("T"," ")}}</td>
    <td class="left">${{t.exit_ts.slice(0,16).replace("T"," ")}}</td>
    <td>${{t.avg_entry.toFixed(2)}}</td>
    <td>${{t.avg_exit.toFixed(2)}}</td>
    <td>${{t.initial_stop.toFixed(2)}}</td>
    <td>${{t.qty_peak}}</td>
    <td class="${{t.scaled_pnl>=0?'pos':'neg'}}"><b>${{Math.round(t.scaled_pnl).toLocaleString()}}</b></td>
    <td class="${{t.money_r>=0?'pos':'neg'}}">${{t.money_r.toFixed(2)}}R</td>
    <td class="left">${{t.regime_at_entry}}</td>
    <td class="left">${{t.exit_reason}}</td>
  </tr>`).join("");
}}

let currentTradeUid = null;
function redrawActiveTrade() {{ if (currentTradeUid) openTradeChart(currentTradeUid); }}

function openTradeChart(uid) {{
  currentTradeUid = uid;
  const t = activeTrades.find(x => x.uid === uid);
  if (!t) return;
  document.getElementById("modalTitle").textContent = `${{t.symbol}} — Trade #${{t.trade_id}} (${{t.strategy}})`;
  document.getElementById("modalSub").innerHTML =
    `<span class="pill">${{t.exit_reason}}</span> &nbsp; Entry: <b>${{t.avg_entry.toFixed(2)}}</b> (${{t.entry_ts.slice(0,16).replace("T"," ")}}) | ` +
    `Exit: <b>${{t.avg_exit.toFixed(2)}}</b> (${{t.exit_ts.slice(0,16).replace("T"," ")}}) | ` +
    `Stop: <b style="color:#dc2626">${{t.initial_stop.toFixed(2)}}</b> | ` +
    `P&L: <b class="${{t.scaled_pnl>=0?'pos':'neg'}}">INR ${{Math.round(t.scaled_pnl).toLocaleString()}} (${{t.money_r.toFixed(2)}}R)</b>` +
    ` &nbsp;<span style="color:#64748b;font-size:11.5px;">(Click 2 points on chart to measure)</span>`;

  const svg = document.getElementById("candleSvg");
  const bars = t.candles || [];
  if (!bars.length) {{
    svg.innerHTML = `<text x="530" y="220" text-anchor="middle" fill="#64748b">No 5m candlestick data embedded for this trade.</text>`;
  }} else {{
    const showEmas = document.getElementById("togEmas").checked;
    const showVol = document.getElementById("togVol").checked;
    const showPat = document.getElementById("togPat").checked;
    const W = 1060, H = 510, P = 64, R = 30, T = 30, B = showVol ? 112 : 48;
    const V_TOP = H - 96, V_BOT = H - 42;

    const emaVals = [];
    if (showEmas && t.day_emas) {{
      Object.values(t.day_emas).forEach(e => {{
        if (e.ema9) emaVals.push(e.ema9);
        if (e.ema21) emaVals.push(e.ema21);
        if (e.ema50) emaVals.push(e.ema50);
      }});
    }}
    let pmin = Math.min(...bars.map(b => b.l), t.initial_stop, ...emaVals);
    let pmax = Math.max(...bars.map(b => b.h), t.initial_stop, ...emaVals);
    const pad = (pmax - pmin) * 0.10 || 1;
    pmin -= pad; pmax += pad;
    const cw = Math.max(2, Math.min(10, (W - P - R) / bars.length * 0.7));
    const mapX = i => P + (W - P - R) * ((i + 0.5) / bars.length);
    const mapY = v => T + (H - T - B) * (1 - (v - pmin) / (pmax - pmin));

    let out = "";
    for (let g = 0; g <= 5; g++) {{
      const v = pmin + (pmax - pmin) * (g / 5);
      const y = mapY(v);
      out += `<line x1="${{P}}" y1="${{y}}" x2="${{W-R}}" y2="${{y}}" stroke="#f1f5f9"/>`;
      out += `<text x="${{P-8}}" y="${{y+4}}" font-size="11" text-anchor="end" fill="#64748b">${{v.toFixed(2)}}</text>`;
    }}

    // Day-start, day-end, and subtle hourly vertical dotted lines
    let prevDay = "";
    bars.forEach((b, i) => {{
      const day = b.t.slice(0, 10), hhmm = b.t.slice(11, 16), x = mapX(i);
      const isDayStart = day !== prevDay;
      const isDayEnd = (i === bars.length - 1) || (bars[i + 1].t.slice(0, 10) !== day);
      if (isDayStart) {{
        out += `<line x1="${{x}}" y1="${{T}}" x2="${{x}}" y2="${{H-B}}" stroke="#94a3b8" stroke-width="1.1" stroke-dasharray="4,3"/>`;
        out += `<text x="${{x+3}}" y="${{H-B+14}}" font-size="10.5" font-weight="700" fill="#334155">${{day}} 09:15</text>`;
      }} else if (isDayEnd) {{
        out += `<line x1="${{x}}" y1="${{T}}" x2="${{x}}" y2="${{H-B}}" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="4,3"/>`;
      }} else if (["10:15","11:15","12:15","13:15","14:15"].includes(hhmm)) {{
        out += `<line x1="${{x}}" y1="${{T}}" x2="${{x}}" y2="${{H-B}}" stroke="#e2e8f0" stroke-width="0.9" stroke-dasharray="2,3"/>`;
        out += `<text x="${{x}}" y="${{H-B+28}}" font-size="9.5" text-anchor="middle" fill="#94a3b8">${{hhmm}}</text>`;
      }}
      prevDay = day;
    }});

    // Initial stop dashed line
    const yStop = mapY(t.initial_stop);
    out += `<line x1="${{P}}" y1="${{yStop}}" x2="${{W-R}}" y2="${{yStop}}" stroke="#dc2626" stroke-width="1.4" stroke-dasharray="6,4"/>`;
    out += `<text x="${{W-R-4}}" y="${{yStop-5}}" font-size="11" font-weight="700" text-anchor="end" fill="#dc2626">INITIAL STOP ${{t.initial_stop.toFixed(2)}}</text>`;

    // Trailing stop step-line
    if (t.stop_trail) {{
      const pts = t.stop_trail.split(";").filter(Boolean).map(s => {{
        const [ts, pr] = s.split("@");
        const idx = bars.findIndex(b => b.t.slice(0, 16) >= ts.slice(0, 16));
        return {{ idx: idx >= 0 ? idx : 0, price: parseFloat(pr), ts }};
      }});
      if (pts.length > 0) {{
        let stepPts = [];
        for (let k = 0; k < pts.length; k++) {{
          const x0 = mapX(pts[k].idx), y0 = mapY(pts[k].price);
          stepPts.push(`${{x0.toFixed(1)}},${{y0.toFixed(1)}}`);
          const nextIdx = (k + 1 < pts.length) ? pts[k + 1].idx : bars.length - 1;
          stepPts.push(`${{mapX(nextIdx).toFixed(1)}},${{y0.toFixed(1)}}`);
          out += `<circle cx="${{x0}}" cy="${{y0}}" r="3.5" fill="#dc2626"><title>Stop -> ${{pts[k].price.toFixed(2)}} @ ${{pts[k].ts.slice(11,16)}}</title></circle>`;
        }}
        out += `<polyline fill="none" stroke="#dc2626" stroke-width="1.8" points="${{stepPts.join(" ")}}"/>`;
      }}
    }}

    if (showPat && t.pattern && t.pattern !== "none") {{
      const eDay = t.entry_ts.slice(0, 10);
      if (t.pattern === "orb" || t.pattern === "orb_short") {{
        const orBars = bars.map((b, i) => ({{ b, i }})).filter(x => x.b.t.slice(0,10) === eDay && x.b.t.slice(11,16) < "09:30");
        const dayLast = bars.map((b, i) => ({{ b, i }})).filter(x => x.b.t.slice(0,10) === eDay).pop();
        if (orBars.length && dayLast) {{
          const orHi = Math.max(...orBars.map(x => x.b.h)), orLo = Math.min(...orBars.map(x => x.b.l));
          const x0 = mapX(orBars[0].i) - cw/2, x1 = mapX(orBars[orBars.length-1].i) + cw/2, xEnd = mapX(dayLast.i);
          const yHi = mapY(orHi), yLo = mapY(orLo);
          out += `<rect x="${{x0}}" y="${{yHi}}" width="${{Math.max(4,x1-x0)}}" height="${{Math.max(2,yLo-yHi)}}" fill="rgba(37,99,235,0.12)" stroke="#2563eb" stroke-width="1" stroke-dasharray="3,2"/>`;
          out += `<line x1="${{x1}}" y1="${{yHi}}" x2="${{xEnd}}" y2="${{yHi}}" stroke="#2563eb" stroke-width="1" stroke-dasharray="3,3" opacity="0.65"/>`;
          out += `<line x1="${{x1}}" y1="${{yLo}}" x2="${{xEnd}}" y2="${{yLo}}" stroke="#2563eb" stroke-width="1" stroke-dasharray="3,3" opacity="0.65"/>`;
          out += `<text x="${{x0+4}}" y="${{yHi-4}}" font-size="10" font-weight="700" fill="#1d4ed8">OR [${{orLo.toFixed(2)}} - ${{orHi.toFixed(2)}}]</text>`;
        }}
      }} else {{
        out += `<rect x="${{P+6}}" y="${{T+6}}" width="165" height="20" rx="4" fill="rgba(139,92,246,0.12)" stroke="#8b5cf6"/>`;
        out += `<text x="${{P+14}}" y="${{T+20}}" font-size="10.5" font-weight="700" fill="#6d28d9">Pattern: ${{t.pattern.toUpperCase()}} (${{(t.pattern_quality*100).toFixed(0)}}%)</text>`;
      }}
    }}

    // 9D, 21D, 50D Daily EMA lines
    if (showEmas && t.day_emas) {{
      const emaSpecs = [["ema9", "#8b5cf6", "9D"], ["ema21", "#f59e0b", "21D"], ["ema50", "#0d9488", "50D"]];
      emaSpecs.forEach(([key, col, lbl]) => {{
        const pts = [];
        let lastVal = null;
        bars.forEach((b, i) => {{
          const de = t.day_emas[b.t.slice(0, 10)];
          if (de && de[key] != null) {{
            pts.push(`${{mapX(i).toFixed(1)}},${{mapY(de[key]).toFixed(1)}}`);
            lastVal = de[key];
          }}
        }});
        if (pts.length > 1) {{
          out += `<polyline fill="none" stroke="${{col}}" stroke-width="1.4" stroke-dasharray="4,2" opacity="0.85" points="${{pts.join(" ")}}"/>`;
          out += `<text x="${{W-R-4}}" y="${{mapY(lastVal)-3}}" font-size="9.5" font-weight="700" text-anchor="end" fill="${{col}}">${{lbl}} ${{lastVal.toFixed(1)}}</text>`;
        }}
      }});
    }}

    // Volume Pane
    if (showVol) {{
      const vmax = Math.max(...bars.map(b => b.v || 0), 1);
      out += `<line x1="${{P}}" y1="${{V_TOP}}" x2="${{W-R}}" y2="${{V_TOP}}" stroke="#e2e8f0"/>`;
      out += `<text x="${{P-8}}" y="${{V_TOP+10}}" font-size="9.5" text-anchor="end" fill="#94a3b8">VOL</text>`;
      bars.forEach((b, i) => {{
        const vh = ((b.v || 0) / vmax) * (V_BOT - V_TOP - 4);
        const col = b.c >= b.o ? "rgba(22,163,74,0.45)" : "rgba(220,38,38,0.45)";
        out += `<rect x="${{mapX(i) - cw/2}}" y="${{V_BOT - vh}}" width="${{cw}}" height="${{vh}}" fill="${{col}}"/>`;
      }});
    }}

    // Candlesticks
    bars.forEach((b, i) => {{
      const x = mapX(i), col = b.c >= b.o ? "#16a34a" : "#dc2626";
      const yH = mapY(b.h), yL = mapY(b.l), yO = mapY(b.o), yC = mapY(b.c);
      const top = Math.min(yO, yC), bh = Math.max(1.5, Math.abs(yO - yC));
      out += `<g><title>${{b.t.slice(0,16).replace("T"," ")}} | O:${{b.o}} H:${{b.h}} L:${{b.l}} C:${{b.c}}</title>`;
      out += `<line x1="${{x}}" y1="${{yH}}" x2="${{x}}" y2="${{yL}}" stroke="${{col}}" stroke-width="1.2"/>`;
      out += `<rect x="${{x - cw/2}}" y="${{top}}" width="${{cw}}" height="${{bh}}" fill="${{col}}"/></g>`;
    }});

    // Entry & Exit vertical dotted markers + time-stamped badges
    const eKey = t.entry_ts.slice(0, 16), xKey = t.exit_ts.slice(0, 16);
    const eIdx = bars.findIndex(b => b.t.slice(0, 16) >= eKey);
    const xIdx = bars.findIndex(b => b.t.slice(0, 16) >= xKey);
    if (eIdx >= 0) {{
      const ex = mapX(eIdx), ey = mapY(t.avg_entry), eTime = t.entry_ts.slice(11, 16);
      out += `<line x1="${{ex}}" y1="${{T}}" x2="${{ex}}" y2="${{H-B}}" stroke="#2563eb" stroke-width="1.2" stroke-dasharray="2,2"/>`;
      out += `<polygon points="${{ex}},${{ey+3}} ${{ex-6}},${{ey+15}} ${{ex+6}},${{ey+15}}" fill="#2563eb"/>`;
      out += `<rect x="${{ex-64}}" y="${{ey+17}}" width="128" height="18" rx="4" fill="#eff6ff" stroke="#2563eb" stroke-width="0.9"/>`;
      out += `<text x="${{ex}}" y="${{ey+30}}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#1d4ed8">ENTRY ${{t.avg_entry.toFixed(2)}} (${{eTime}})</text>`;
    }}
    if (xIdx >= 0) {{
      const xx = mapX(xIdx), xy = mapY(t.avg_exit), xTime = t.exit_ts.slice(11, 16);
      out += `<line x1="${{xx}}" y1="${{T}}" x2="${{xx}}" y2="${{H-B}}" stroke="#d97706" stroke-width="1.2" stroke-dasharray="2,2"/>`;
      out += `<polygon points="${{xx}},${{xy-3}} ${{xx-6}},${{xy-15}} ${{xx+6}},${{xy-15}}" fill="#d97706"/>`;
      out += `<rect x="${{xx-60}}" y="${{xy-36}}" width="120" height="18" rx="4" fill="#fffbeb" stroke="#d97706" stroke-width="0.9"/>`;
      out += `<text x="${{xx}}" y="${{xy-23}}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#b45309">EXIT ${{t.avg_exit.toFixed(2)}} (${{xTime}})</text>`;
    }}
    svg.innerHTML = out;

    // TradingView-style crosshair + 2-click distance/time ruler
    const overlay = document.createElementNS("http://www.w3.org/2000/svg", "g");
    svg.appendChild(overlay);
    let anchorA = null, anchorB = null;
    const toSvg = (evt) => {{
      const rect = svg.getBoundingClientRect();
      const sx = (evt.clientX - rect.left) * (W / rect.width);
      const sy = (evt.clientY - rect.top) * (H / rect.height);
      const idx = Math.max(0, Math.min(bars.length - 1, Math.round(((sx - P) / (W - P - R)) * bars.length - 0.5)));
      const cy = Math.max(T, Math.min(H - B, sy));
      const price = pmin + (1 - (cy - T) / (H - T - B)) * (pmax - pmin);
      return {{ idx, x: mapX(idx), y: cy, price }};
    }};
    const fmtDur = (t1, t2) => {{
      const m = Math.round(Math.abs(new Date(t2) - new Date(t1)) / 60000);
      const d = Math.floor(m / 1440), hh = Math.floor((m % 1440) / 60), mm = m % 60;
      return (d ? d + "d " : "") + (hh ? hh + "h " : "") + mm + "m";
    }};
    const drawOverlay = (cur) => {{
      let h = "";
      const p2 = anchorB || (anchorA ? cur : null);
      if (anchorA && p2) {{
        const x1 = Math.min(anchorA.x, p2.x), x2 = Math.max(anchorA.x, p2.x);
        const y1 = Math.min(anchorA.y, p2.y), y2 = Math.max(anchorA.y, p2.y);
        const dp = p2.price - anchorA.price, pct = anchorA.price ? (dp / anchorA.price * 100) : 0;
        const nBars = Math.abs(p2.idx - anchorA.idx), dur = fmtDur(bars[anchorA.idx].t, bars[p2.idx].t);
        const col = dp >= 0 ? "#16a34a" : "#dc2626";
        h += `<rect x="${{x1}}" y="${{y1}}" width="${{Math.max(2,x2-x1)}}" height="${{Math.max(2,y2-y1)}}" fill="${{dp>=0?'rgba(22,163,74,0.12)':'rgba(220,38,38,0.12)'}}" stroke="${{col}}" stroke-dasharray="3,2"/>`;
        h += `<line x1="${{anchorA.x}}" y1="${{anchorA.y}}" x2="${{p2.x}}" y2="${{p2.y}}" stroke="${{col}}" stroke-width="1.5"/>`;
        const bx = Math.min(W - 220, Math.max(P, (x1 + x2) / 2 - 105)), by = Math.max(T + 4, y1 - 36);
        h += `<rect x="${{bx}}" y="${{by}}" width="210" height="30" rx="5" fill="#0f172a" opacity="0.9"/>`;
        h += `<text x="${{bx+105}}" y="${{by+13}}" font-size="10.5" font-weight="700" text-anchor="middle" fill="#fff">${{dp>=0?'+':''}}${{dp.toFixed(2)}} (${{pct>=0?'+':''}}${{pct.toFixed(2)}}%)</text>`;
        h += `<text x="${{bx+105}}" y="${{by+25}}" font-size="10" text-anchor="middle" fill="#cbd5e1">${{nBars}} bars | ${{dur}}</text>`;
      }}
      if (cur) {{
        const b = bars[cur.idx];
        h += `<line x1="${{cur.x}}" y1="${{T}}" x2="${{cur.x}}" y2="${{H-B}}" stroke="#475569" stroke-width="0.9" stroke-dasharray="3,3"/>`;
        h += `<line x1="${{P}}" y1="${{cur.y}}" x2="${{W-R}}" y2="${{cur.y}}" stroke="#475569" stroke-width="0.9" stroke-dasharray="3,3"/>`;
        h += `<rect x="4" y="${{cur.y-9}}" width="56" height="18" rx="3" fill="#0f172a"/><text x="32" y="${{cur.y+4}}" font-size="10" text-anchor="middle" fill="#fff">${{cur.price.toFixed(2)}}</text>`;
        h += `<rect x="${{Math.min(W-120, Math.max(P, cur.x-55))}}" y="${{H-B+2}}" width="110" height="16" rx="3" fill="#0f172a"/><text x="${{Math.min(W-65, Math.max(P+55, cur.x))}}" y="${{H-B+13}}" font-size="9.5" text-anchor="middle" fill="#fff">${{b.t.slice(5,16).replace("T"," ")}}</text>`;
      }}
      overlay.innerHTML = h;
    }};
    svg.onmousemove = (e) => drawOverlay(toSvg(e));
    svg.onmouseleave = () => drawOverlay(null);
    svg.onclick = (e) => {{
      const pt = toSvg(e);
      if (!anchorA || (anchorA && anchorB)) {{ anchorA = pt; anchorB = null; }}
      else {{ anchorB = pt; }}
      drawOverlay(pt);
    }};
  }}
  document.getElementById("tradeModal").classList.add("open");
}}

function closeModal() {{ document.getElementById("tradeModal").classList.remove("open"); }}
document.addEventListener("keydown", e => {{ if (e.key === "Escape") closeModal(); }});

function recalc() {{
  const cap = parseFloat(document.getElementById("capInput").value) || 1000000;
  const totW = state.reduce((a, x) => a + (x.active ? x.weight : 0), 0);
  document.getElementById("allocSummary").textContent = `Active Allocation: ${{totW.toFixed(1)}}% | Cash Reserve: ${{Math.max(0, 100 - totW).toFixed(1)}}%`;

  const dates = STRATEGIES.length ? STRATEGIES[0].dates : [];
  const nDays = STRATEGIES.length ? STRATEGIES[0].daily_returns.length : 0;
  const eq = [cap];
  const portRets = [];
  for (let t = 1; t < nDays; t++) {{
    let r = 0;
    STRATEGIES.forEach((s, i) => {{
      if (state[i].active && t < s.daily_returns.length) r += (state[i].weight / 100) * s.daily_returns[t];
    }});
    portRets.push(r);
    eq.push(eq[eq.length - 1] * (1 + r));
  }}

  const benchEq = (BENCH.closes && BENCH.closes.length === eq.length && BENCH.closes[0] > 0)
    ? BENCH.closes.map(c => cap * (c / BENCH.closes[0])) : [];

  let peak = eq[0], maxDd = 0;
  const dd = eq.map(v => {{ if (v > peak) peak = v; const d = peak > 0 ? (v - peak) / peak * 100 : 0; if (d < maxDd) maxDd = d; return d; }});
  const totRet = cap > 0 ? (eq[eq.length - 1] / cap - 1) * 100 : 0;
  const meanR = portRets.length ? portRets.reduce((a, b) => a + b, 0) / portRets.length : 0;
  const stdR = portRets.length > 1 ? Math.sqrt(portRets.reduce((a, b) => a + (b - meanR) ** 2, 0) / (portRets.length - 1)) : 0;
  const sharpe = stdR > 0 ? (meanR / stdR) * Math.sqrt(252) : 0;
  const yrs = Math.max(eq.length / 252, 1 / 252);
  const annRet = (eq[eq.length - 1] > 0 && cap > 0) ? ((eq[eq.length - 1] / cap) ** (1 / yrs) - 1) * 100 : totRet;
  const calmar = maxDd < 0 ? annRet / Math.abs(maxDd) : 0;

  activeTrades = [];
  let totalTradePnl = 0;
  const contribs = STRATEGIES.map((s, i) => {{
    if (!state[i].active || state[i].weight <= 0) return 0;
    const alloc = cap * (state[i].weight / 100);
    const scale = s.base_capital > 0 ? alloc / s.base_capital : 1;
    let cPnl = 0;
    s.trades.forEach(tr => {{
      const p = tr.net_pnl * scale;
      cPnl += p;
      activeTrades.push({{ ...tr, strategy: s.name, uid: s.name + "_" + tr.trade_id, scaled_pnl: p }});
    }});
    totalTradePnl += cPnl;
    return cPnl;
  }});

  STRATEGIES.forEach((s, i) => {{
    const alloc = state[i].active ? cap * (state[i].weight / 100) : 0;
    document.getElementById("alloc_"+i).textContent = Math.round(alloc).toLocaleString();
    document.getElementById("cpnl_"+i).textContent = Math.round(contribs[i]).toLocaleString();
    const share = totalTradePnl !== 0 ? (contribs[i] / Math.abs(totalTradePnl) * 100) : 0;
    document.getElementById("cpct_"+i).textContent = share.toFixed(1) + "%";
  }});

  const nT = activeTrades.length;
  const wins = activeTrades.filter(t => t.scaled_pnl > 0);
  const losses = activeTrades.filter(t => t.scaled_pnl <= 0);
  const gp = wins.reduce((a, t) => a + t.scaled_pnl, 0);
  const gl = losses.reduce((a, t) => a + t.scaled_pnl, 0);
  const pf = gl < 0 ? gp / Math.abs(gl) : (gp > 0 ? 999 : 0);
  const expR = nT ? activeTrades.reduce((a, t) => a + t.money_r, 0) / nT : 0;

  const kpis = [
    ["Final Equity", "INR " + Math.round(eq[eq.length - 1]).toLocaleString()],
    ["Total Return", totRet.toFixed(2) + "%"],
    ["Max Drawdown", maxDd.toFixed(2) + "%"],
    ["Sharpe Ratio", sharpe.toFixed(2)],
    ["Calmar Ratio", calmar.toFixed(2)],
    ["Total Trades", nT],
    ["Win Rate", (nT ? wins.length / nT * 100 : 0).toFixed(1) + "%"],
    ["Profit Factor", pf.toFixed(2)],
    ["Expectancy (R)", expR.toFixed(3) + "R"],
  ];
  document.getElementById("kpiGrid").innerHTML = kpis.map(([l, v]) => `<div class="kpi"><div class="lbl">${{l}}</div><div class="val">${{v}}</div></div>`).join("");
  drawPortfolioCharts(eq, dd, dates, benchEq);
  populateFilterOptions();
  applyTradeFilters();
}}

document.getElementById("capInput").addEventListener("input", recalc);
initRunDropdown();
switchRun("0");
</script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path