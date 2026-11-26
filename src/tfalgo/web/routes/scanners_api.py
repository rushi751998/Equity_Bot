"""Scanners API: filter across stored symbols with multi-timeframe indicators."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request

router = APIRouter(prefix="/api/scanners", tags=["scanners"])


@router.post("/run")
def run_scanner(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from tfalgo.config import load_config
    from tfalgo.factory import build_store

    cfg = load_config(request.app.state.default_config)
    store = build_store(cfg)
    tf = str(body.get("timeframe", "1d"))
    min_chg = float(body.get("min_chg_pct", -100.0))
    max_chg = float(body.get("max_chg_pct", 100.0))
    min_vol_mult = float(body.get("min_vol_mult", 0.0))
    above_ema21 = bool(body.get("above_ema21", False))

    syms = [s for s in store.list_symbols(cfg.run.base_timeframe) if not s.startswith("idx:")]
    matches: list[dict[str, Any]] = []

    for sym in sorted(syms):
        pl_df = store.read_bars(sym, cfg.run.base_timeframe)
        if pl_df.is_empty():
            continue
        pdf = pl_df.sort("ts").to_pandas().set_index("ts")
        if tf == "1h":
            pdf = pdf.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        elif tf == "1d":
            pdf = pdf.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        if len(pdf) < 25:
            continue
        ema21 = float(pdf["close"].ewm(span=21, adjust=False).mean().iloc[-1])
        avg_v = float(pdf["volume"].iloc[-21:-1].mean()) or 1.0
        last = pdf.iloc[-1]
        prev = pdf.iloc[-2]
        chg_pct = ((float(last["close"]) - float(prev["close"])) / max(float(prev["close"]), 1e-6)) * 100.0
        vol_mult = float(last["volume"]) / avg_v
        if chg_pct < min_chg or chg_pct > max_chg or vol_mult < min_vol_mult:
            continue
        if above_ema21 and float(last["close"]) <= ema21:
            continue
        matches.append({
            "symbol": sym,
            "close": round(float(last["close"]), 2),
            "low": round(float(last["low"]), 2),
            "chg_pct": round(chg_pct, 2),
            "vol_mult": round(vol_mult, 2),
            "ema21": round(ema21, 2),
            "ts": pdf.index[-1].isoformat(),
        })

    return {"ok": True, "scanned": len(syms), "matches": matches}
