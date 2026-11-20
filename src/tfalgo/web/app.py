"""Flask server (`tfalgo ui`): backtest runner, multi-timeframe charts, and portfolio simulator."""

from __future__ import annotations

import json
import math
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from flask import Flask, Response, jsonify, request

from tfalgo.backtest.batch import run_batch
from tfalgo.config import load_config
from tfalgo.data.resample import resample
from tfalgo.factory import build_calendar, build_store
from tfalgo.indicators.ema import ema
from tfalgo.indicators.patterns.vcp import _extract_contractions
from tfalgo.indicators.atr import wilder_atr

_RUN_STATUS: dict[str, Any] = {"running": False, "message": "Idle", "last_error": None}


def _resample_weekly(df1d: pl.DataFrame) -> pl.DataFrame:
    if df1d.is_empty():
        return df1d
    return (
        df1d.sort("ts")
        .with_columns(wk=pl.col("ts").dt.strftime("%G-W%V"))
        .group_by("wk", maintain_order=True)
        .agg(
            pl.col("ts").first(),
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
        )
        .drop("wk")
    )


def create_app(default_config: Path = Path("config/pilot.yaml")) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> Response:
        return Response(_HTML_PAGE, mimetype="text/html")

    @app.get("/api/configs")
    def list_configs() -> Response:
        cfg_dir = Path("config")
        files = sorted(str(p).replace("\\", "/") for p in cfg_dir.glob("*.yaml"))
        return jsonify({"configs": files})

    @app.get("/api/status")
    def status() -> Response:
        return jsonify(_RUN_STATUS)

    @app.post("/api/run_batch")
    def trigger_batch() -> Response:
        if _RUN_STATUS["running"]:
            return jsonify({"ok": False, "error": "A backtest is already running"}), 409
        body = request.get_json(silent=True) or {}
        paths = [Path(p) for p in body.get("configs", []) if p]
        if not paths:
            return jsonify({"ok": False, "error": "Select at least one config"}), 400

        def _worker() -> None:
            _RUN_STATUS.update({"running": True, "message": f"Running {len(paths)} config(s)...", "last_error": None})
            try:
                cfg = load_config(paths[0])
                cal = build_calendar(cfg)
                store = build_store(cfg)
                outdir = cfg.storage.output_dir / "batch"
                run_batch(paths, store, cal, outdir)
                _RUN_STATUS.update({"running": False, "message": "Completed", "last_error": None})
            except Exception as exc:
                _RUN_STATUS.update({"running": False, "message": "Failed", "last_error": str(exc)})

        threading.Thread(target=_worker, daemon=True).start()
        return jsonify({"ok": True})

    @app.get("/api/runs")
    def list_runs() -> Response:
        cfg = load_config(default_config)
        hist_dir = cfg.storage.output_dir / "batch" / "history"
        if not hist_dir.exists():
            return jsonify({"runs": []})
        runs = [p.stem for p in sorted(hist_dir.glob("*.json"), reverse=True)[:30]]
        return jsonify({"runs": runs})

    @app.get("/api/run/<run_id>")
    def get_run(run_id: str) -> Response:
        cfg = load_config(default_config)
        p = cfg.storage.output_dir / "batch" / "history" / f"{run_id}.json"
        if not p.exists():
            return jsonify({"error": "Run not found"}), 404
        return Response(p.read_text(encoding="utf-8"), mimetype="application/json")

    @app.get("/api/candles")
    def get_candles() -> Response:
        symbol = request.args.get("symbol", "")
        tf = request.args.get("tf", "5m")
        entry_str = request.args.get("entry", "")[:10]
        exit_str = request.args.get("exit", "")[:10]
        pattern = request.args.get("pattern", "none")
        if not symbol or not entry_str:
            return jsonify({"error": "symbol and entry required"}), 400

        cfg = load_config(default_config)
        store = build_store(cfg)
        e_date = date.fromisoformat(entry_str)
        x_date = date.fromisoformat(exit_str or entry_str)

        lookback = {"5m": 2, "15m": 5, "60m": 20, "1D": 180, "1W": 400}.get(tf, 5)
        # Extra warmup for EMA50 on selected timeframe
        warmup = {"5m": 5, "15m": 10, "60m": 30, "1D": 100, "1W": 360}.get(tf, 10)
        start_d = e_date - timedelta(days=lookback + warmup)
        end_d = x_date + timedelta(days=2 if tf in ("5m", "15m") else 10)

        df5 = store.read_bars(symbol, cfg.run.base_timeframe, start_d, end_d)
        if df5.is_empty():
            return jsonify({"candles": [], "pattern_shapes": {}})

        if tf == "5m":
            df = df5.sort("ts")
        elif tf in ("15m", "60m", "1D"):
            df = resample(df5, tf, session_open=cfg.session.open, session_close=cfg.session.close, tz=cfg.run.timezone)
        elif tf == "1W":
            d1 = resample(df5, "1D", session_open=cfg.session.open, session_close=cfg.session.close, tz=cfg.run.timezone)
            df = _resample_weekly(d1)
        else:
            return jsonify({"error": f"Unsupported tf {tf}"}), 400

        c_arr = df["close"].to_numpy()
        e9 = ema(c_arr, 9)
        e21 = ema(c_arr, 21)
        e50 = ema(c_arr, 50)

        view_start = e_date - timedelta(days=lookback)
        candles: list[dict[str, Any]] = []
        for idx_r, row in enumerate(df.iter_rows(named=True)):
            ts = row["ts"]
            if ts.date() < view_start:
                continue
            candles.append({
                "t": ts.isoformat(),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": float(row["volume"]),
                "ema9": None if math.isnan(e9[idx_r]) else round(float(e9[idx_r]), 2),
                "ema21": None if math.isnan(e21[idx_r]) else round(float(e21[idx_r]), 2),
                "ema50": None if math.isnan(e50[idx_r]) else round(float(e50[idx_r]), 2),
            })

        # Pattern curve/lines on 1D up to entry_date
        pat_shapes: dict[str, Any] = {}
        if pattern in ("vcp", "flat_base"):
            d1_all = resample(df5, "1D", session_open=cfg.session.open, session_close=cfg.session.close, tz=cfg.run.timezone)
            d1_pre = d1_all.filter(pl.col("ts").dt.date() < e_date).tail(90)
            if d1_pre.height >= 20:
                hi = d1_pre["high"].to_numpy()
                lo = d1_pre["low"].to_numpy()
                cl = d1_pre["close"].to_numpy()
                ts_list = [x.isoformat() for x in d1_pre["ts"].to_list()]
                if pattern == "vcp":
                    atr14 = wilder_atr(hi, lo, cl, 14)[-1]
                    thresh = max(0.03, 0.8 * (atr14 / cl[-1])) if not math.isnan(atr14) and cl[-1] > 0 else 0.04
                    cons = _extract_contractions(hi, lo, thresh)
                    zig: list[dict[str, Any]] = []
                    for p_i, t_i, _ in cons:
                        zig.append({"t": ts_list[p_i], "p": float(hi[p_i])})
                        zig.append({"t": ts_list[t_i], "p": float(lo[t_i])})
                    pat_shapes = {"type": "vcp", "zigzag": zig, "pivot": float(hi.max())}
                else:
                    pat_shapes = {
                        "type": "flat_base",
                        "t0": ts_list[0], "t1": ts_list[-1],
                        "high": float(hi.max()), "low": float(lo.min()),
                    }

        return jsonify({"candles": candles, "pattern_shapes": pat_shapes})

    @app.get("/api/live")
    def live_watch() -> Response:
        return jsonify({
            "mode": "sim_ready",
            "message": "BrokerAdapter live feed hook ready. Connect Kite/Upstox/Dhan adapter to stream live positions.",
            "positions": [],
            "signals": [],
        })

    return app


_HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>tfalgo Control Center & Simulator</title>
<style>
  :root { --bg:#f1f5f9; --card:#fff; --border:#e2e8f0; --text:#0f172a; --muted:#64748b; --primary:#2563eb; --green:#16a34a; --red:#dc2626; }
  * { box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; margin:0; padding:20px; background:var(--bg); color:var(--text); }
  .wrap { max-width:1460px; margin:0 auto; }
  header { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:12px; }
  .tabs { display:flex; gap:8px; margin-bottom:16px; }
  .tab { padding:8px 16px; border-radius:8px; border:1px solid var(--border); background:#fff; cursor:pointer; font-weight:600; font-size:13px; color:#475569; }
  .tab.active { background:var(--primary); color:#fff; border-color:var(--primary); }
  .panel { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:16px; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; }
  .kpi { background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:10px; }
  .kpi .lbl { font-size:11px; color:var(--muted); text-transform:uppercase; }
  .kpi .val { font-size:18px; font-weight:700; margin-top:3px; }
  .pos { color:var(--green); } .neg { color:var(--red); }
  table { width:100%; border-collapse:collapse; font-size:12.5px; }
  th, td { border-bottom:1px solid var(--border); padding:7px 9px; text-align:right; white-space:nowrap; }
  th:first-child, td:first-child, th.left, td.left { text-align:left; }
  th { background:#f8fafc; color:#475569; position:sticky; top:0; cursor:pointer; z-index:2; }
  .scroll { max-height:350px; overflow:auto; border:1px solid var(--border); border-radius:8px; }
  .filters { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:8px; margin-bottom:10px; background:#f8fafc; padding:10px; border-radius:8px; border:1px solid var(--border); }
  .filters label { display:flex; flex-direction:column; font-size:11px; color:var(--muted); font-weight:600; gap:3px; }
  input, select { padding:6px 8px; border:1px solid #cbd5e1; border-radius:6px; font-size:12.5px; background:#fff; }
  button { background:var(--primary); color:#fff; border:none; padding:7px 13px; border-radius:6px; cursor:pointer; font-weight:600; font-size:12.5px; }
  button.sec { background:#475569; } button.ghost { background:#e2e8f0; color:#334155; }
  .tf-btn { padding:4px 10px; border-radius:5px; border:1px solid #cbd5e1; background:#f8fafc; color:#334155; cursor:pointer; font-weight:600; font-size:12px; }
  .tf-btn.active { background:var(--primary); color:#fff; border-color:var(--primary); }
  .trade-link { color:var(--primary); font-weight:700; cursor:pointer; text-decoration:underline; }
  .modal-bg { display:none; position:fixed; inset:0; background:rgba(15,23,42,0.62); z-index:50; align-items:center; justify-content:center; padding:20px; }
  .modal-bg.open { display:flex; }
  .modal { background:#fff; border-radius:12px; width:100%; max-width:1160px; padding:18px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h2 style="margin:0;">tfalgo Quant Workstation</h2>
      <div style="font-size:12.5px;color:#64748b;">Run Backtests, Simulate Capital Allocations, Inspect Multi-Timeframe Charts &amp; Watch Live Trades</div>
    </div>
    <div style="display:flex;align-items:center;gap:8px;">
      <label style="font-size:12.5px;font-weight:600;">Saved Run:</label>
      <select id="runSelect" onchange="loadRun(this.value)" style="min-width:250px;"></select>
    </div>
  </header>

  <div class="tabs">
    <button class="tab active" onclick="showTab('sim', this)">Portfolio Simulator</button>
    <button class="tab" onclick="showTab('runner', this)">Run Backtest / Batch</button>
    <button class="tab" onclick="showTab('live', this)">Live Watch</button>
  </div>

  <div id="tab_runner" style="display:none;" class="panel">
    <h3>Select Strategy Configs to Run</h3>
    <div id="cfgChecks" style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px;"></div>
    <button onclick="runBatchNow()">Run Selected Strategies</button>
    <span id="runStatusMsg" style="margin-left:12px;font-size:13px;font-weight:600;color:#2563eb;"></span>
  </div>

  <div id="tab_live" style="display:none;" class="panel">
    <h3>Live Trade &amp; Position Watcher</h3>
    <p id="liveMsg" style="color:#475569;font-size:13px;"></p>
  </div>

  <div id="tab_sim">
    <div class="panel">
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px;">
        <label style="font-size:13px;"><b>Total Capital (INR):</b> <input id="capInput" type="number" value="1000000" step="50000" oninput="recalc()"></label>
        <button onclick="equalWeight()">Equal Weight Active</button>
        <button class="sec" onclick="normalizeWeights()">Normalize 100%</button>
        <label style="font-size:13px;"><input type="checkbox" id="showBench" checked onchange="recalc()"> Overlay Nifty 50 (%)</label>
        <span id="allocSummary" style="margin-left:auto;font-size:13px;font-weight:600;color:#475569;"></span>
      </div>
      <table><thead><tr><th>Active</th><th class="left">Strategy</th><th>Allocation (%)</th><th>Allocated (INR)</th><th>Trades</th><th>Contrib P&amp;L</th><th>Contrib (%)</th></tr></thead><tbody id="stratRows"></tbody></table>
    </div>

    <div class="panel"><div class="kpis" id="kpiGrid"></div></div>

    <div class="panel">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
        <h3 style="margin:0;">Cumulative Return (%) — Portfolio vs. Nifty 50</h3>
        <div style="font-size:12px;color:#64748b;"><b style="color:#2563eb;">— Portfolio %</b> &nbsp; <b style="color:#64748b;">--- Nifty 50 %</b></div>
      </div>
      <svg id="eqSvg" viewBox="0 0 1100 320" width="100%"></svg>
    </div>

    <div class="panel">
      <h3 style="margin:0 0 6px 0;">Combined Portfolio Drawdown (%)</h3>
      <svg id="ddSvg" viewBox="0 0 1100 240" width="100%"></svg>
    </div>

    <div class="panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <h3 style="margin:0;">All Trades (Excel-Style Filter &amp; Sort)</h3>
        <button class="ghost" onclick="clearFilters()">Clear Filters</button>
      </div>
      <div class="filters">
        <label>Strategy<select id="fStrat" onchange="applyFilters()"><option value="">All</option></select></label>
        <label>Symbol<select id="fSym" onchange="applyFilters()"><option value="">All</option></select></label>
        <label>Outcome<select id="fOut" onchange="applyFilters()"><option value="">All</option><option value="win">Winners</option><option value="loss">Losers</option></select></label>
        <label>Regime<select id="fReg" onchange="applyFilters()"><option value="">All</option></select></label>
        <label>Exit<select id="fExit" onchange="applyFilters()"><option value="">All</option></select></label>
        <label>From<input type="date" id="fFrom" onchange="applyFilters()"></label>
        <label>To<input type="date" id="fTo" onchange="applyFilters()"></label>
      </div>
      <div id="filteredBar" style="font-size:12.5px;margin-bottom:8px;color:#1e3a8a;background:#eff6ff;padding:7px 10px;border-radius:6px;"></div>
      <div class="scroll">
        <table>
          <thead><tr>
            <th class="left" onclick="sortBy('trade_id')">ID</th><th class="left" onclick="sortBy('strategy')">Strategy</th><th class="left" onclick="sortBy('symbol')">Symbol</th>
            <th class="left" onclick="sortBy('entry_ts')">Entry Time</th><th class="left" onclick="sortBy('exit_ts')">Exit Time</th>
            <th onclick="sortBy('avg_entry')">Entry</th><th onclick="sortBy('avg_exit')">Exit</th><th onclick="sortBy('initial_stop')">Stop</th>
            <th onclick="sortBy('scaled_pnl')">Net P&amp;L</th><th onclick="sortBy('money_r')">R</th><th class="left">Exit Reason</th>
          </tr></thead>
          <tbody id="tradeRows"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<div class="modal-bg" id="tradeModal" onclick="if(event.target===this) closeModal()">
  <div class="modal">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;border-bottom:1px solid var(--border);padding-bottom:8px;">
      <div>
        <h3 id="modalTitle" style="margin:0;"></h3>
        <div id="modalSub" style="font-size:12px;color:#475569;margin-top:3px;"></div>
      </div>
      <button class="ghost" onclick="closeModal()">Close (Esc)</button>
    </div>
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
      <span style="font-size:12px;font-weight:600;color:#475569;">Timeframe:</span>
      <button class="tf-btn active" onclick="setTf('5m', this)">5m</button>
      <button class="tf-btn" onclick="setTf('15m', this)">15m</button>
      <button class="tf-btn" onclick="setTf('60m', this)">1H</button>
      <button class="tf-btn" onclick="setTf('1D', this)">1D</button>
      <button class="tf-btn" onclick="setTf('1W', this)">1W</button>
      <label style="margin-left:14px;font-size:12px;"><input type="checkbox" id="togEmas" checked onchange="fetchTradeChart()"> <b style="color:#8b5cf6;">EMA 9</b> / <b style="color:#f59e0b;">EMA 21</b> / <b style="color:#0d9488;">EMA 50</b></label>
      <label style="font-size:12px;"><input type="checkbox" id="togVol" checked onchange="fetchTradeChart()"> Volume</label>
      <label style="font-size:12px;"><input type="checkbox" id="togPat" checked onchange="fetchTradeChart()"> Pattern Curve/Box</label>
      <span style="margin-left:auto;font-size:11.5px;color:#64748b;">Click 2 points to measure</span>
    </div>
    <svg id="candleSvg" viewBox="0 0 1100 500" width="100%"></svg>
  </div>
</div>

<script>
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
</script>
</body>
</html>
"""