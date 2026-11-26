"""Backtest, Simulator (lightweight run payload), Dynamic Runner, Config CRUD & Data Upload API."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, Form, Request, UploadFile

router = APIRouter(prefix="/api", tags=["backtest"])

_RUN_STATUS: dict[str, Any] = {
    "running": False,
    "message": "Idle",
    "days_done": 0,
    "total_days": 0,
    "logs": [],
    "last_error": None,
}


def update_progress(days_done: int, total_days: int, msg: str) -> None:
    _RUN_STATUS["days_done"] = days_done
    _RUN_STATUS["total_days"] = total_days
    _RUN_STATUS["message"] = msg
    _RUN_STATUS["logs"].append(msg)
    _RUN_STATUS["logs"] = _RUN_STATUS["logs"][-200:]


@router.get("/runs")
def list_runs(request: Request) -> dict[str, Any]:
    from tfalgo.config import load_config

    cfg = load_config(request.app.state.default_config)
    hist_dir = cfg.storage.output_dir / "batch" / "history"
    if not hist_dir.exists():
        return {"runs": []}
    runs = [p.stem for p in sorted(hist_dir.glob("*.json"), reverse=True)[:40]]
    return {"runs": runs}


@router.get("/run/{run_id}")
def get_run_lightweight(run_id: str, request: Request) -> dict[str, Any]:
    """Return trades + equity + benchmarks ONLY (strips embedded candles for fast loading)."""
    from tfalgo.config import load_config

    cfg = load_config(request.app.state.default_config)
    p = cfg.storage.output_dir / "batch" / "history" / f"{Path(run_id).name}.json"
    if not p.exists():
        return {"ok": False, "error": "Run not found"}
    data = json.loads(p.read_text(encoding="utf-8"))
    for s in data.get("strategies", []):
        for t in s.get("trades", []):
            t.pop("candles", None)
            t.pop("day_emas", None)
    return data


@router.get("/candles")
def get_candles(
    request: Request,
    symbol: str,
    tf: str = "5m",
    entry: str = "",
    exit: str = "",
) -> dict[str, Any]:
    from tfalgo.config import load_config
    from tfalgo.factory import build_store

    cfg = load_config(request.app.state.default_config)
    store = build_store(cfg)
    pl_df = store.read_bars(symbol, cfg.run.base_timeframe)
    if pl_df.is_empty():
        return {"candles": [], "pattern_shapes": {}}

    pdf = pl_df.sort("ts").to_pandas().set_index("ts")
    if entry and exit:
        lo = str((__import__("pandas").Timestamp(entry) - __import__("pandas").Timedelta(days=5)).date())
        hi = str((__import__("pandas").Timestamp(exit) + __import__("pandas").Timedelta(days=5)).date())
        pdf = pdf[(pdf.index.strftime("%Y-%m-%d") >= lo) & (pdf.index.strftime("%Y-%m-%d") <= hi)]

    if tf in ("15m", "1h", "1d", "1w"):
        rule = {"15m": "15min", "1h": "60min", "1d": "1D", "1w": "1W"}[tf]
        pdf = pdf.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

    pdf["ema9"] = pdf["close"].ewm(span=9, adjust=False).mean()
    pdf["ema21"] = pdf["close"].ewm(span=21, adjust=False).mean()
    pdf["ema50"] = pdf["close"].ewm(span=50, adjust=False).mean()

    candles = [
        {
            "t": idx.isoformat(),
            "o": round(float(r["open"]), 2),
            "h": round(float(r["high"]), 2),
            "l": round(float(r["low"]), 2),
            "c": round(float(r["close"]), 2),
            "v": float(r["volume"]),
            "ema9": round(float(r["ema9"]), 2),
            "ema21": round(float(r["ema21"]), 2),
            "ema50": round(float(r["ema50"]), 2),
        }
        for idx, r in pdf.iterrows()
    ]
    return {"candles": candles, "pattern_shapes": {}}


@router.get("/configs")
def list_configs() -> dict[str, Any]:
    cfgs = sorted(str(p).replace("\\", "/") for p in Path("config").glob("*.yaml"))
    return {"configs": cfgs}


@router.post("/save_config")
def save_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name = Path(str(body.get("filename", "custom.yaml"))).name
    if not name.endswith(".yaml"):
        name += ".yaml"
    p = Path("config") / name
    p.write_text(str(body.get("content", "")), encoding="utf-8")
    return {"ok": True, "path": f"config/{name}"}


@router.post("/config/rename")
def rename_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    old_p = Path("config") / Path(str(body.get("old_name", ""))).name
    new_p = Path("config") / Path(str(body.get("new_name", ""))).name
    if old_p.exists() and not new_p.exists():
        old_p.rename(new_p)
    return {"ok": True}


@router.post("/config/delete")
def delete_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    p = Path("config") / Path(str(body.get("filename", ""))).name
    if p.exists():
        p.unlink()
    return {"ok": True}


@router.get("/symbols")
def list_symbols(request: Request) -> dict[str, Any]:
    from tfalgo.config import load_config
    from tfalgo.factory import build_store

    cfg = load_config(request.app.state.default_config)
    store = build_store(cfg)
    syms = [s for s in store.list_symbols(cfg.run.base_timeframe) if not s.startswith("idx:")]
    return {"symbols": sorted(syms)}


@router.get("/status")
def batch_status() -> dict[str, Any]:
    return dict(_RUN_STATUS)


@router.post("/run_batch")
def trigger_batch(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from tfalgo.backtest.batch import run_batch
    from tfalgo.config import load_config
    from tfalgo.factory import build_calendar, build_store

    if _RUN_STATUS["running"]:
        return {"ok": False, "error": "A backtest is already running"}
    paths = [Path(p) for p in body.get("configs", []) if p]
    if not paths:
        return {"ok": False, "error": "Select at least one config"}

    selected_symbols = body.get("symbols") or []
    session_name = body.get("session_name") or "Session_1"
    cached_map = body.get("cached_symbols_by_config") or {}

    def _worker() -> None:
        _RUN_STATUS.update({"running": True, "message": f"Running {len(paths)} config(s)...", "days_done": 0, "total_days": 0, "logs": [], "last_error": None})
        try:
            cfg = load_config(paths[0])
            cal = build_calendar(cfg)
            store = build_store(cfg)
            outdir = cfg.storage.output_dir / "batch"
            run_batch(
                paths, store, cal, outdir,
                symbols=selected_symbols,
                cached_map=cached_map,
                progress_cb=update_progress,
                session_name=session_name,
            )
            _RUN_STATUS.update({"running": False, "message": "Completed", "last_error": None})
        except Exception as exc:
            _RUN_STATUS.update({"running": False, "message": "Failed", "last_error": str(exc)})

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True}


@router.post("/session/rename")
def rename_session(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from tfalgo.config import load_config

    cfg = load_config(request.app.state.default_config)
    hist = cfg.storage.output_dir / "batch" / "history"
    old_p = hist / f"{Path(str(body.get('old_name', ''))).name}.json"
    new_p = hist / f"{Path(str(body.get('new_name', ''))).name}.json"
    if old_p.exists():
        data = json.loads(old_p.read_text(encoding="utf-8"))
        data["run_id"] = Path(str(body.get("new_name", ""))).name
        new_p.write_text(json.dumps(data), encoding="utf-8")
        old_p.unlink()
    return {"ok": True}


@router.post("/session/delete")
def delete_session(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from tfalgo.config import load_config

    cfg = load_config(request.app.state.default_config)
    p = cfg.storage.output_dir / "batch" / "history" / f"{Path(str(body.get('name', ''))).name}.json"
    if p.exists():
        p.unlink()
    return {"ok": True}


@router.post("/data/upload")
async def upload_data(
    request: Request,
    files: list[UploadFile] = File(...),
    symbol: str = Form(""),
    timeframe: str = Form("5m"),
    is_index: str = Form("0"),
) -> dict[str, Any]:
    import pandas as pd
    import polars as pl
    from tfalgo.config import load_config
    from tfalgo.factory import build_store

    cfg = load_config(request.app.state.default_config)
    store = build_store(cfg)
    sym_override = symbol.strip().upper()
    is_idx = is_index == "1"
    results = []
    total_rows = 0

    for f in files:
        fname = f.filename or "data.csv"
        ext = Path(fname).suffix.lower()
        sym = sym_override if (sym_override and len(files) == 1) else Path(fname).stem.upper()
        if is_idx and not sym.startswith("idx:"):
            sym = f"idx:{sym}"

        if ext == ".csv":
            pdf = pd.read_csv(f.file)
        elif ext in (".xlsx", ".xls"):
            pdf = pd.read_excel(f.file)
        elif ext == ".parquet":
            pdf = pd.read_parquet(f.file)
        else:
            results.append({"symbol": sym, "rows": 0, "status": f"unsupported {ext}"})
            continue

        pdf.columns = [str(c).strip().lower() for c in pdf.columns]
        if "date" in pdf.columns and "ts" not in pdf.columns:
            pdf = pdf.rename(columns={"date": "ts"})
        pdf["ts"] = pd.to_datetime(pdf["ts"])
        if pdf["ts"].dt.tz is None:
            pdf["ts"] = pdf["ts"].dt.tz_localize(cfg.run.timezone)
        else:
            pdf["ts"] = pdf["ts"].dt.tz_convert(cfg.run.timezone)

        keep = [c for c in ["ts", "open", "high", "low", "close", "volume"] if c in pdf.columns]
        pl_df = pl.from_pandas(pdf[keep])
        n_rows = store.upsert_bars(sym, timeframe, pl_df) if hasattr(store, "upsert_bars") else store.write_bars(sym, timeframe, pl_df)
        cnt = int(n_rows) if isinstance(n_rows, (int, float)) else len(pdf)
        total_rows += cnt
        results.append({"symbol": sym, "rows": cnt, "status": "stored"})

    return {"ok": True, "total_rows": total_rows, "results": results}
