"""Self-contained interactive HTML+JS post-backtest Portfolio Simulator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_portfolio_simulator_html(
    strategies_payload: list[dict[str, Any]],
    initial_capital: float,
    output_path: Path,
) -> Path:
    """Write an interactive portfolio simulator HTML page with toggles, sliders, and live SVG charts."""
    data_json = json.dumps(strategies_payload)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>tfalgo Portfolio Simulator</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 24px; color: #1e293b; background: #f8fafc; }}
  h2 {{ margin-top: 0; }}
  .panel {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
  .controls-top {{ display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
  .kpi {{ background: #f1f5f9; border-radius: 6px; padding: 10px; }}
  .kpi .lbl {{ font-size: 11px; color: #64748b; text-transform: uppercase; }}
  .kpi .val {{ font-size: 18px; font-weight: 700; margin-top: 2px; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid #e2e8f0; padding: 8px 10px; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ background: #f8fafc; color: #475569; }}
  button {{ background: #2563eb; color: #fff; border: none; padding: 7px 12px; border-radius: 6px; cursor: pointer; font-weight: 600; }}
  button.sec {{ background: #475569; }}
  input[type=range] {{ width: 140px; vertical-align: middle; }}
  input[type=number] {{ padding: 5px 8px; border: 1px solid #cbd5e1; border-radius: 4px; width: 130px; }}
</style>
</head>
<body>
<h2>tfalgo Post-Backtest Portfolio Simulator</h2>

<div class="panel">
  <div class="controls-top">
    <label><b>Total Capital (INR):</b> <input id="capInput" type="number" value="{int(initial_capital)}" step="50000" min="10000"></label>
    <button onclick="equalWeight()">Equal Weight Active</button>
    <button class="sec" onclick="normalizeWeights()">Normalize to 100%</button>
    <span id="allocSummary" style="font-size:13px;color:#475569;"></span>
  </div>
  <table>
    <thead>
      <tr>
        <th>Active</th><th>Strategy</th><th>Allocation (%)</th><th>Allocated (INR)</th>
        <th>Trades</th><th>Contrib P&L (INR)</th><th>Contrib (%)</th>
      </tr>
    </thead>
    <tbody id="stratRows"></tbody>
  </table>
</div>

<div class="panel">
  <div class="kpis" id="kpiGrid"></div>
</div>

<div class="charts">
  <div class="panel"><h4>Combined Portfolio Equity (INR)</h4><svg id="eqSvg" viewBox="0 0 640 220" width="100%"></svg></div>
  <div class="panel"><h4>Combined Portfolio Drawdown (%)</h4><svg id="ddSvg" viewBox="0 0 640 220" width="100%"></svg></div>
</div>

<script>
const STRATEGIES = {data_json};
const state = STRATEGIES.map((s, i) => ({{
  active: true,
  weight: STRATEGIES.length ? Math.round((100 / STRATEGIES.length) * 10) / 10 : 0
}}));

function renderControls() {{
  const tb = document.getElementById("stratRows");
  tb.innerHTML = "";
  STRATEGIES.forEach((s, i) => {{
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" ${{state[i].active ? "checked" : ""}} onchange="toggleStrat(${{i}}, this.checked)"></td>
      <td><b>${{s.name}}</b></td>
      <td>
        <input type="range" min="0" max="100" step="1" value="${{state[i].weight}}" ${{state[i].active ? "" : "disabled"}}
               oninput="setWeight(${{i}}, this.value)">
        <span id="wLbl_${{i}}">${{state[i].weight.toFixed(1)}}%</span>
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

function drawSvg(svgId, vals, color, suffix) {{
  const svg = document.getElementById(svgId);
  const W = 640, H = 220, P = 34;
  if (!vals.length) {{ svg.innerHTML = ""; return; }}
  let ymin = Math.min(...vals), ymax = Math.max(...vals);
  if (ymax === ymin) ymax = ymin + 1;
  const pts = vals.map((v, i) => {{
    const x = P + (W - 2*P) * (i / Math.max(1, vals.length - 1));
    const y = H - P - (H - 2*P) * ((v - ymin) / (ymax - ymin));
    return `${{x.toFixed(1)}},${{y.toFixed(1)}}`;
  }}).join(" ");
  svg.innerHTML = `
    <rect x="${{P}}" y="${{P}}" width="${{W-2*P}}" height="${{H-2*P}}" fill="#f8fafc" stroke="#cbd5e1"/>
    <polyline fill="none" stroke="${{color}}" stroke-width="2" points="${{pts}}"/>
    <text x="${{P}}" y="20" font-size="11" fill="#475569">Max: ${{ymax.toLocaleString(undefined, {{maximumFractionDigits:2}})}}${{suffix}}</text>
    <text x="${{W-P}}" y="${{H-10}}" font-size="11" text-anchor="end" fill="#475569">Min: ${{ymin.toLocaleString(undefined, {{maximumFractionDigits:2}})}}${{suffix}}</text>`;
}}

function recalc() {{
  const cap = parseFloat(document.getElementById("capInput").value) || 1000000;
  const totW = state.reduce((a, x) => a + (x.active ? x.weight : 0), 0);
  document.getElementById("allocSummary").textContent = `Active Allocation: ${{totW.toFixed(1)}}% | Cash Reserve: ${{Math.max(0, 100 - totW).toFixed(1)}}%`;

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

  let peak = eq[0], maxDd = 0;
  const dd = eq.map(v => {{ if (v > peak) peak = v; const d = peak > 0 ? (v - peak) / peak * 100 : 0; if (d < maxDd) maxDd = d; return d; }});
  const totRet = cap > 0 ? (eq[eq.length - 1] / cap - 1) * 100 : 0;
  const meanR = portRets.length ? portRets.reduce((a, b) => a + b, 0) / portRets.length : 0;
  const stdR = portRets.length > 1 ? Math.sqrt(portRets.reduce((a, b) => a + (b - meanR) ** 2, 0) / (portRets.length - 1)) : 0;
  const sharpe = stdR > 0 ? (meanR / stdR) * Math.sqrt(252) : 0;
  const yrs = Math.max(eq.length / 252, 1 / 252);
  const annRet = (eq[eq.length - 1] > 0 && cap > 0) ? ((eq[eq.length - 1] / cap) ** (1 / yrs) - 1) * 100 : totRet;
  const calmar = maxDd < 0 ? annRet / Math.abs(maxDd) : 0;

  let allTrades = [], totalTradePnl = 0;
  const contribs = STRATEGIES.map((s, i) => {{
    if (!state[i].active || state[i].weight <= 0) return 0;
    const alloc = cap * (state[i].weight / 100);
    const scale = s.base_capital > 0 ? alloc / s.base_capital : 1;
    let cPnl = 0;
    s.trades.forEach(tr => {{
      const p = tr.net_pnl * scale;
      cPnl += p;
      allTrades.push({{ pnl: p, mr: tr.money_r }});
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

  const nT = allTrades.length;
  const wins = allTrades.filter(t => t.pnl > 0);
  const losses = allTrades.filter(t => t.pnl <= 0);
  const gp = wins.reduce((a, t) => a + t.pnl, 0);
  const gl = losses.reduce((a, t) => a + t.pnl, 0);
  const pf = gl < 0 ? gp / Math.abs(gl) : (gp > 0 ? 999 : 0);
  const expR = nT ? allTrades.reduce((a, t) => a + t.mr, 0) / nT : 0;

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
  drawSvg("eqSvg", eq, "#2563eb", "");
  drawSvg("ddSvg", dd, "#dc2626", "%");
}}

document.getElementById("capInput").addEventListener("input", recalc);
renderControls();
recalc();
</script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path