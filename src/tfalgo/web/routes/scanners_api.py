"""Scanners API: switchable data sources (Local DB / yfinance / Broker) + Scan Strategies."""
from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Body, Request

from tfalgo.web.core.brokers import get_active_broker, get_tick_broker

router = APIRouter(prefix="/api/scanners", tags=["scanners"])


def _fetch_yf_ohlcv(sym: str, tf: str) -> pd.DataFrame:
    import yfinance as yf
    period = "1y" if tf in ("1d", "1w") else "60d"
    interval = {"5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}.get(tf, "1d")
    df = yf.download(f"{sym}.NS", period=period, interval=interval, progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    return df[[c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]].dropna()


def _match_strategy(pdf: pd.DataFrame, strategy: str, min_chg: float, max_chg: float, min_vol_mult: float, above_ema21: bool) -> dict[str, Any] | None:
    if len(pdf) < 25:
        return None
    ema9 = float(pdf["close"].ewm(span=9, adjust=False).mean().iloc[-1])
    ema21 = float(pdf["close"].ewm(span=21, adjust=False).mean().iloc[-1])
    ema50 = float(pdf["close"].ewm(span=50, adjust=False).mean().iloc[-1])
    avg_v = float(pdf["volume"].iloc[-21:-1].mean()) or 1.0
    last, prev = pdf.iloc[-1], pdf.iloc[-2]
    c = float(last["close"])
    chg_pct = ((c - float(prev["close"])) / max(float(prev["close"]), 1e-6)) * 100.0
    vol_mult = float(last["volume"]) / avg_v

    if strategy == "ema_breakout":
        prior_hi = float(pdf["high"].iloc[-12:-1].max())
        if not (c > ema9 > ema21 > ema50 and c > prior_hi and vol_mult >= 1.5):
            return None
    elif strategy == "vcp":
        r1 = float(pdf["high"].iloc[-18:-10].max() - pdf["low"].iloc[-18:-10].min())
        r2 = float(pdf["high"].iloc[-10:-4].max() - pdf["low"].iloc[-10:-4].min())
        r3 = float(pdf["high"].iloc[-4:-1].max() - pdf["low"].iloc[-4:-1].min())
        if not (r1 > r2 > r3 > 0 and c > float(pdf["high"].iloc[-6:-1].max())):
            return None
    elif strategy == "cup_handle" and len(pdf) >= 30:
        l_hi = float(pdf["high"].iloc[-30:-20].max())
        cup_lo = float(pdf["low"].iloc[-22:-8].min())
        r_hi = float(pdf["high"].iloc[-10:-3].max())
        if not ((l_hi - cup_lo) / max(l_hi, 1e-6) >= 0.06 and c > r_hi):
            return None
    elif strategy == "vol_surge":
        if vol_mult < max(1.8, min_vol_mult) or chg_pct <= 0:
            return None
    else:  # custom
        if chg_pct < min_chg or chg_pct > max_chg or vol_mult < min_vol_mult:
            return None
        if above_ema21 and c <= ema21:
            return None

    return {
        "close": round(c, 2),
        "low": round(float(last["low"]), 2),
        "chg_pct": round(chg_pct, 2),
        "vol_mult": round(vol_mult, 2),
        "ema21": round(ema21, 2),
        "strategy": strategy,
    }


@router.post("/run")
def run_scanner(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from tfalgo.config import load_config
    from tfalgo.factory import build_store

    cfg = load_config(request.app.state.default_config)
    store = build_store(cfg)
    source = str(body.get("source", "db"))  # db | yfinance | broker
    strategy = str(body.get("strategy", "custom"))
    tf = str(body.get("timeframe", "1d"))
    min_chg = float(body.get("min_chg_pct", -100.0))
    max_chg = float(body.get("max_chg_pct", 100.0))
    min_vol_mult = float(body.get("min_vol_mult", 0.0))
    above_ema21 = bool(body.get("above_ema21", False))

    custom_syms = [s.strip().upper() for s in str(body.get("symbols") or "").split(",") if s.strip()]
    syms = custom_syms or [s for s in store.list_symbols(cfg.run.base_timeframe) if not s.startswith("idx:")]
    if not syms:
        syms = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "TATAMOTORS"]

    matches: list[dict[str, Any]] = []
    broker = get_tick_broker() if source == "broker" else None

    for sym in sorted(syms)[:80]:
        try:
            if source == "yfinance":
                pdf = _fetch_yf_ohlcv(sym, tf)
            elif source == "broker" and broker is not None:
                if hasattr(broker, "get_historical_df"):
                    pdf = broker.get_historical_df(sym, tf)
                else:
                    ltp = broker.get_ltp(sym)
                    if ltp > 0:
                        matches.append({"symbol": sym, "close": round(ltp, 2), "low": round(ltp * 0.99, 2), "chg_pct": 0.0, "vol_mult": 1.0, "ema21": round(ltp, 2), "strategy": "broker_ltp"})
                    continue
            else:
                pl_df = store.read_bars(sym, cfg.run.base_timeframe)
                if pl_df.is_empty():
                    continue
                pdf = pl_df.sort("ts").to_pandas().set_index("ts")
                if tf == "1h":
                    pdf = pdf.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
                elif tf == "1d":
                    pdf = pdf.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            hit = _match_strategy(pdf, strategy, min_chg, max_chg, min_vol_mult, above_ema21)
            if hit:
                matches.append({"symbol": sym, **hit})
        except Exception:
            continue

    return {"ok": True, "source": source, "scanned": len(syms), "matches": matches}
