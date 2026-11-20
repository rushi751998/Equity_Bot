"""Flask server (`tfalgo ui`): backtest runner, multi-timeframe charts, and portfolio simulator."""

from __future__ import annotations

import json
import math
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from flask import Flask, Response, jsonify, render_template, request

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
    def index() -> str:
        return render_template("index.html")

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

