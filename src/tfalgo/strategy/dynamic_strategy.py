"""Modular Dynamic Edge-Discovery Strategy (`dynamic_v1`).

Place in: src/tfalgo/strategy/dynamic_strategy.py
Supports:
- Direction: LONG | SHORT | BOTH
- Independent Macro Pattern TF & Bar/Candlestick Trigger TF (5m, 15m, 1h, 1d)
- Patterns: ema_breakout, cup_handle, head_shoulders, inv_head_shoulders,
            double_bottom, double_top, triple_bottom, triple_top, vcp, flat_base
- Candlestick triggers: doji, hammer, shooting_star, engulfing, flag_wedge, impulse_2x
- Indicators: EMA stack, RSI(period, min, max), RS vs Nifty 50, Volume surge
- Retracement % window, Wait Time (max_wait_bars), Weighted Pass Score %, Score-Scaled Qty
- Full Trade Journey (`events` + `stop_trail`) for interactive replay & callouts
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import polars as pl

from tfalgo.calendar import TradingCalendar
from tfalgo.config import AppConfig
from tfalgo.strategy.base import (
    STRATEGIES,
    OrderIntent,
    PortfolioSnapshot,
    Strategy,
    SymbolState,
)


DEFAULT_DYNAMIC_PARAMS: dict[str, Any] = {
    "direction": "LONG",  # LONG | SHORT | BOTH
    "pattern_tf": "1h",   # 5m | 15m | 1h | 1d
    "trigger_tf": "5m",   # 5m | 15m | 1h | 1d
    "trail_tf": "1h",     # 5m | 15m | 1h | 1d
    "patterns": ["ema_breakout", "cup_handle", "double_bottom", "vcp"],
    "candle_triggers": ["hammer", "engulfing", "impulse_2x", "flag_wedge"],
    "ema_periods": [9, 21, 50],
    "consolidation_min_days": 5,
    "consolidation_max_range_pct": 8.0,
    "breakout_vol_mult": 1.5,
    "use_rsi": True,
    "rsi_period": 14,
    "rsi_min": 50.0,
    "rsi_max": 80.0,
    "use_rs": True,
    "rs_lookback_bars": 20,
    "min_pass_score_pct": 70.0,
    "score_qty_min_mult": 0.5,
    "score_qty_max_mult": 1.5,
    "max_wait_bars": 36,
    "retrace_min_pct": 15.0,
    "retrace_max_pct": 65.0,
    "impulse_pct_mult": 2.0,
    "sl_source": "pattern_low",  # pattern_low | trigger_low | atr_stop
    "holding_mode": "swing",     # swing | mis
    "risk_per_trade_pct": 1.0,
    "tranches": [0.33, 0.33, 0.34],
    "add_at_r": [1.0, 2.0],
    "use_risk_neutral_sl": True,
    "trail_ema_initial": 21,
    "trail_ema_runner": 9,
    "runner_atr_period": 14,
    "runner_atr_mult": 0.5,
    "slippage_bps": 0.0,
}


@STRATEGIES.register("dynamic_v1")
class DynamicEdgeStrategy(Strategy):
    name = "dynamic_v1"

    def on_bar(
        self,
        state: SymbolState,
        ctx: dict[str, Any],
        portfolio: PortfolioSnapshot,
        cfg: AppConfig,
    ) -> tuple[SymbolState, list[OrderIntent]]:
        return state, []


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_wilder_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_c = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_c).abs(), (df["low"] - prev_c).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def resample_tf(df_5m: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf == "5m":
        return df_5m.copy()
    rule = {"15m": "15min", "1h": "60min", "1d": "1D"}.get(tf, "60min")
    origin = "start_day" if tf == "1d" else pd.Timestamp("2015-01-01 09:15:00", tz=df_5m.index.tz)
    return (
        df_5m.resample(rule, origin=origin, label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open", "close"])
    )


def detect_macro_pattern(win: pd.DataFrame, enabled: list[str], side: str, p: dict[str, Any]) -> tuple[str | None, float]:
    """Check macro chart patterns on the last N bars of pattern_tf. Returns (pattern_name, quality_0_to_1)."""
    if len(win) < 25:
        return None, 0.0
    c = win["close"].to_numpy()
    h = win["high"].to_numpy()
    l = win["low"].to_numpy()
    o = win["open"].to_numpy()
    v = win["volume"].to_numpy()
    avg_v = float(np.mean(v[-21:-1])) if len(v) > 21 else float(np.mean(v))
    vol_ok = avg_v > 0 and v[-1] >= float(p["breakout_vol_mult"]) * avg_v

    if side == "LONG":
        if "ema_breakout" in enabled and c[-1] > o[-1] and vol_ok:
            prior_hi = float(np.max(h[-15:-1]))
            prior_lo = float(np.min(l[-15:-1]))
            rng_pct = ((prior_hi - prior_lo) / max(prior_lo, 1e-6)) * 100.0
            if rng_pct <= float(p["consolidation_max_range_pct"]) and c[-1] > prior_hi:
                return "ema_breakout", 0.85

        if "cup_handle" in enabled and len(win) >= 30:
            left_hi = float(np.max(h[-30:-20]))
            cup_lo = float(np.min(l[-22:-8]))
            right_hi = float(np.max(h[-10:-3]))
            handle_lo = float(np.min(l[-4:-1]))
            depth = (left_hi - cup_lo) / max(left_hi, 1e-6)
            if 0.06 <= depth <= 0.35 and abs(right_hi - left_hi) / max(left_hi, 1e-6) <= 0.04 and handle_lo > cup_lo and c[-1] > right_hi:
                return "cup_handle", 0.90

        if "double_bottom" in enabled and len(win) >= 20:
            b1 = float(np.min(l[-20:-10]))
            b2 = float(np.min(l[-10:-1]))
            neck = float(np.max(h[-14:-4]))
            if abs(b2 - b1) / max(b1, 1e-6) <= 0.015 and c[-1] > neck:
                return "double_bottom", 0.85

        if "triple_bottom" in enabled and len(win) >= 27:
            b1, b2, b3 = float(np.min(l[-27:-18])), float(np.min(l[-18:-9])), float(np.min(l[-9:-1]))
            mid = float(np.mean([b1, b2, b3]))
            neck = float(np.max(h[-20:-2]))
            if max(abs(b1 - mid), abs(b2 - mid), abs(b3 - mid)) / max(mid, 1e-6) <= 0.018 and c[-1] > neck:
                return "triple_bottom", 0.92

        if "inv_head_shoulders" in enabled and len(win) >= 24:
            ls, hd, rs = float(np.min(l[-24:-16])), float(np.min(l[-16:-8])), float(np.min(l[-8:-1]))
            neck = float(np.max(h[-16:-3]))
            if hd < ls * 0.985 and hd < rs * 0.985 and abs(ls - rs) / max(ls, 1e-6) <= 0.025 and c[-1] > neck:
                return "inv_head_shoulders", 0.92

        if "vcp" in enabled and len(win) >= 18:
            r1 = float(np.max(h[-18:-10]) - np.min(l[-18:-10]))
            r2 = float(np.max(h[-10:-4]) - np.min(l[-10:-4]))
            r3 = float(np.max(h[-4:-1]) - np.min(l[-4:-1]))
            if r1 > r2 > r3 > 0 and c[-1] > float(np.max(h[-6:-1])):
                return "vcp", 0.88

        if "flat_base" in enabled and len(win) >= 15:
            hi, lo = float(np.max(h[-15:-1])), float(np.min(l[-15:-1]))
            if ((hi - lo) / max(lo, 1e-6)) * 100.0 <= float(p["consolidation_max_range_pct"]) and c[-1] > hi:
                return "flat_base", 0.80

    else:  # SHORT
        if "head_shoulders" in enabled and len(win) >= 24:
            ls, hd, rs = float(np.max(h[-24:-16])), float(np.max(h[-16:-8])), float(np.max(h[-8:-1]))
            neck = float(np.min(l[-16:-3]))
            if hd > ls * 1.015 and hd > rs * 1.015 and abs(ls - rs) / max(ls, 1e-6) <= 0.025 and c[-1] < neck:
                return "head_shoulders", 0.92

        if "double_top" in enabled and len(win) >= 20:
            t1, t2 = float(np.max(h[-20:-10])), float(np.max(h[-10:-1]))
            neck = float(np.min(l[-14:-4]))
            if abs(t2 - t1) / max(t1, 1e-6) <= 0.015 and c[-1] < neck:
                return "double_top", 0.85

        if "triple_top" in enabled and len(win) >= 27:
            t1, t2, t3 = float(np.max(h[-27:-18])), float(np.max(h[-18:-9])), float(np.max(h[-9:-1]))
            mid = float(np.mean([t1, t2, t3]))
            neck = float(np.min(l[-20:-2]))
            if max(abs(t1 - mid), abs(t2 - mid), abs(t3 - mid)) / max(mid, 1e-6) <= 0.018 and c[-1] < neck:
                return "triple_top", 0.92

    return None, 0.0


def detect_candle_trigger(win: pd.DataFrame, enabled: list[str], side: str, p: dict[str, Any]) -> tuple[str | None, float]:
    """Detect bar/candlestick trigger (Doji, Hammer, Shooting Star, Engulfing, Flag/Wedge, 2x Impulse)."""
    if len(win) < 7:
        return None, 0.0
    last = win.iloc[-1]
    prev = win.iloc[-2]
    o, h, l, c = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])
    rng = max(h - l, 1e-6)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if "doji" in enabled and body / rng <= 0.12:
        return "doji", 0.70

    if side == "LONG":
        if "hammer" in enabled and lower_wick >= 2.0 * max(body, rng * 0.05) and upper_wick <= 0.25 * rng and c >= o:
            return "hammer", 0.85
        if "engulfing" in enabled and c > o and float(prev["close"]) < float(prev["open"]) and c >= float(prev["open"]) and o <= float(prev["close"]):
            return "engulfing", 0.88
        if "impulse_2x" in enabled and c > o:
            pct = (win["close"] - win["open"]).abs() / win["open"].replace(0, np.nan)
            avg5 = float(pct.iloc[-6:-1].mean())
            cur = (c - o) / max(o, 1e-6)
            if avg5 > 0 and cur >= float(p["impulse_pct_mult"]) * avg5 and c > float(prev["high"]):
                return "impulse_2x", 0.90
        if "flag_wedge" in enabled and c > o:
            pb = win.iloc[-6:-1]
            r_early = float(pb["high"].iloc[:2].max() - pb["low"].iloc[:2].min())
            r_late = float(pb["high"].iloc[-2:].max() - pb["low"].iloc[-2:].min())
            if r_early > 0 and r_late <= 0.75 * r_early and c > float(pb["high"].iloc[-3:].max()):
                return "flag_wedge", 0.82
    else:
        if "shooting_star" in enabled and upper_wick >= 2.0 * max(body, rng * 0.05) and lower_wick <= 0.25 * rng and c <= o:
            return "shooting_star", 0.85
        if "engulfing" in enabled and c < o and float(prev["close"]) > float(prev["open"]) and c <= float(prev["open"]) and o >= float(prev["close"]):
            return "engulfing", 0.88
        if "impulse_2x" in enabled and c < o:
            pct = (win["close"] - win["open"]).abs() / win["open"].replace(0, np.nan)
            avg5 = float(pct.iloc[-6:-1].mean())
            cur = (o - c) / max(o, 1e-6)
            if avg5 > 0 and cur >= float(p["impulse_pct_mult"]) * avg5 and c < float(prev["low"]):
                return "impulse_2x", 0.90

    return None, 0.0


@dataclass
class _DynPos:
    symbol: str
    trade_id: int
    side: str
    entry_ts: pd.Timestamp
    entry1_price: float
    initial_sl: float
    r_unit: float
    first_swing: float
    pattern: str
    tranches_filled: int = 1
    qty_by_tranche: list[float] = field(default_factory=list)
    entry_prices: list[float] = field(default_factory=list)
    remaining_qty: float = 0.0
    sl_price: float = 0.0
    sold_3r: bool = False
    sold_6r: bool = False
    realized_pnl: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)
    stop_trail: list[tuple[str, float]] = field(default_factory=list)
    exit_fills: list[tuple[float, float]] = field(default_factory=list)


def backtest_dynamic_symbol(
    symbol: str,
    df_5m: pd.DataFrame,
    bench_5m: pd.DataFrame,
    params: dict[str, Any],
    capital: float = 1_000_000.0,
    start_trade_id: int = 1,
    day_progress_cb: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    p = {**DEFAULT_DYNAMIC_PARAMS, **params}
    pat_df = resample_tf(df_5m, p["pattern_tf"])
    trig_df = resample_tf(df_5m, p["trigger_tf"])
    trail_df = resample_tf(df_5m, p["trail_tf"])

    e_f, e_m, e_s = [int(x) for x in p["ema_periods"]]
    pat_df["ema_f"] = compute_ema(pat_df["close"], e_f)
    pat_df["ema_m"] = compute_ema(pat_df["close"], e_m)
    pat_df["ema_s"] = compute_ema(pat_df["close"], e_s)
    pat_df["rsi"] = compute_rsi(pat_df["close"], int(p["rsi_period"]))
    pat_df["atr"] = compute_wilder_atr(pat_df, 14)

    if not bench_5m.empty:
        b_pat = resample_tf(bench_5m, p["pattern_tf"])
        rs_lb = int(p["rs_lookback_bars"])
        s_ret = pat_df["close"].pct_change(rs_lb)
        b_ret = b_pat["close"].pct_change(rs_lb).reindex(pat_df.index, method="ffill")
        pat_df["rs_ok"] = s_ret > b_ret
    else:
        pat_df["rs_ok"] = True

    trail_df["ema9"] = compute_ema(trail_df["close"], int(p["trail_ema_runner"]))
    trail_df["ema21"] = compute_ema(trail_df["close"], int(p["trail_ema_initial"]))
    trail_df["atr"] = compute_wilder_atr(trail_df, int(p["runner_atr_period"]))

    sides_to_check = ["LONG", "SHORT"] if p["direction"] == "BOTH" else [p["direction"]]
    base_risk_inr = capital * (float(p["risk_per_trade_pct"]) / 100.0)
    tranches = p["tranches"]
    add_r1, add_r2 = p["add_at_r"]
    atr_mult = float(p["runner_atr_mult"])
    slip_bps = float(p.get("slippage_bps", 5.0))

    unique_days = df_5m.index.normalize().unique()
    total_days = max(1, len(unique_days))
    last_day = None
    day_num = 0

    trades: list[dict[str, Any]] = []
    pos: _DynPos | None = None
    pending: dict[str, Any] | None = None
    tid = start_trade_id
    last_pat_ts = None

    for i in range(30, len(df_5m)):
        bar = df_5m.iloc[i]
        ts = df_5m.index[i]
        if ts.date() != last_day:
            last_day = ts.date()
            day_num += 1
            if day_progress_cb and (day_num % 20 == 0 or day_num == total_days):
                day_progress_cb(day_num, total_days)

        # Manage open position
        if pos is not None:
            is_long = pos.side == "LONG"
            hit_sl = float(bar["low"]) <= pos.sl_price if is_long else float(bar["high"]) >= pos.sl_price
            if hit_sl:
                px = pos.sl_price
                avg_e = sum(pr * q for pr, q in zip(pos.entry_prices, pos.qty_by_tranche)) / max(sum(pos.qty_by_tranche), 1e-6)
                pos.exit_fills.append((pos.remaining_qty, px))
                pos.realized_pnl += pos.remaining_qty * ((px - avg_e) if is_long else (avg_e - px))
                pos.events.append({"ts": ts.isoformat(), "price": round(px, 2), "label": f"Stop (-{int(round(pos.remaining_qty))})", "kind": "exit"})
                trades.append(_dyn_trade_dict(pos, ts, px, "stop_hit", base_risk_inr, slip_bps, p["holding_mode"]))
                pos = None
                continue

            p1r = pos.entry1_price + (add_r1 * pos.r_unit if is_long else -add_r1 * pos.r_unit)
            p2r = pos.entry1_price + (add_r2 * pos.r_unit if is_long else -add_r2 * pos.r_unit)
            hit_1r = float(bar["high"]) >= p1r if is_long else float(bar["low"]) <= p1r
            hit_2r = float(bar["high"]) >= p2r if is_long else float(bar["low"]) <= p2r

            if pos.tranches_filled == 1 and tranches[1] > 0 and hit_1r:
                q2 = (pos.qty_by_tranche[0] / tranches[0]) * tranches[1]
                pos.qty_by_tranche.append(q2)
                pos.entry_prices.append(p1r)
                pos.remaining_qty += q2
                pos.tranches_filled = 2
                pos.events.append({"ts": ts.isoformat(), "price": round(p1r, 2), "label": f"E2 +{int(round(q2))} @ 1R", "kind": "add"})
                if p["use_risk_neutral_sl"]:
                    pos.sl_price = max(pos.sl_price, pos.first_swing) if is_long else min(pos.sl_price, pos.first_swing)
                    pos.stop_trail.append((ts.isoformat(), round(pos.sl_price, 2)))

            if pos.tranches_filled == 2 and tranches[2] > 0 and hit_2r:
                q3 = (pos.qty_by_tranche[0] / tranches[0]) * tranches[2]
                pos.qty_by_tranche.append(q3)
                pos.entry_prices.append(p2r)
                pos.remaining_qty += q3
                pos.tranches_filled = 3
                pos.events.append({"ts": ts.isoformat(), "price": round(p2r, 2), "label": f"E3 +{int(round(q3))} @ 2R", "kind": "add"})
                pos.sl_price = max(pos.sl_price, pos.entry1_price) if is_long else min(pos.sl_price, pos.entry1_price)
                pos.stop_trail.append((ts.isoformat(), round(pos.sl_price, 2)))

            p3r = pos.entry1_price + (3.0 * pos.r_unit if is_long else -3.0 * pos.r_unit)
            p6r = pos.entry1_price + (6.0 * pos.r_unit if is_long else -6.0 * pos.r_unit)
            tot_q = sum(pos.qty_by_tranche)
            avg_e = sum(pr * q for pr, q in zip(pos.entry_prices, pos.qty_by_tranche)) / max(tot_q, 1e-6)

            if not pos.sold_3r and (float(bar["high"]) >= p3r if is_long else float(bar["low"]) <= p3r):
                sq = min(pos.remaining_qty, tot_q / 3.0)
                pos.exit_fills.append((sq, p3r))
                pos.realized_pnl += sq * ((p3r - avg_e) if is_long else (avg_e - p3r))
                pos.remaining_qty -= sq
                pos.sold_3r = True
                pos.events.append({"ts": ts.isoformat(), "price": round(p3r, 2), "label": f"Exit 1/3 (-{int(round(sq))}) @ 3R", "kind": "partial_exit"})

            if not pos.sold_6r and pos.remaining_qty > 0 and (float(bar["high"]) >= p6r if is_long else float(bar["low"]) <= p6r):
                sq = min(pos.remaining_qty, tot_q / 3.0)
                pos.exit_fills.append((sq, p6r))
                pos.realized_pnl += sq * ((p6r - avg_e) if is_long else (avg_e - p6r))
                pos.remaining_qty -= sq
                pos.sold_6r = True
                pos.events.append({"ts": ts.isoformat(), "price": round(p6r, 2), "label": f"Exit 1/3 (-{int(round(sq))}) @ 6R", "kind": "partial_exit"})

            closed_t = trail_df[trail_df.index < ts]
            if len(closed_t) > 0:
                ct = closed_t.iloc[-1]
                cand = pos.sl_price
                if pos.sold_3r and pos.sold_6r and pd.notna(ct["ema9"]) and pd.notna(ct["atr"]):
                    cand = float(ct["ema9"]) - atr_mult * float(ct["atr"]) if is_long else float(ct["ema9"]) + atr_mult * float(ct["atr"])
                elif pd.notna(ct["ema21"]):
                    cand = float(ct["ema21"])
                improved = (cand > pos.sl_price + 0.05) if is_long else (cand < pos.sl_price - 0.05)
                if improved:
                    pos.sl_price = cand
                    pos.stop_trail.append((ts.isoformat(), round(cand, 2)))

            if p["holding_mode"] == "mis" and ts.strftime("%H:%M") >= "15:15":
                px = float(bar["close"])
                pos.exit_fills.append((pos.remaining_qty, px))
                pos.realized_pnl += pos.remaining_qty * ((px - avg_e) if is_long else (avg_e - px))
                pos.events.append({"ts": ts.isoformat(), "price": round(px, 2), "label": f"MIS Exit (-{int(round(pos.remaining_qty))})", "kind": "exit"})
                trades.append(_dyn_trade_dict(pos, ts, px, "mis_squareoff", base_risk_inr, slip_bps, p["holding_mode"]))
                pos = None
            continue

        # Check new HTF macro pattern
        p_closed = pat_df[pat_df.index < ts]
        if len(p_closed) >= 30 and p_closed.index[-1] != last_pat_ts:
            last_pat_ts = p_closed.index[-1]
            row_p = p_closed.iloc[-1]
            for side in sides_to_check:
                pat_name, pat_q = detect_macro_pattern(p_closed.iloc[-35:], p["patterns"], side, p)
                if pat_name:
                    score_pts, max_pts = 35.0 * pat_q, 35.0
                    # EMA stack score (25 pts)
                    max_pts += 25.0
                    ema_ok = (row_p["close"] > row_p["ema_f"] > row_p["ema_m"] > row_p["ema_s"]) if side == "LONG" else (row_p["close"] < row_p["ema_f"] < row_p["ema_m"] < row_p["ema_s"])
                    if pd.notna(row_p["ema_s"]) and ema_ok:
                        score_pts += 25.0
                    # RSI score (20 pts)
                    if p.get("use_rsi", True):
                        max_pts += 20.0
                        if pd.notna(row_p["rsi"]) and float(p["rsi_min"]) <= float(row_p["rsi"]) <= float(p["rsi_max"]):
                            score_pts += 20.0
                    # RS vs Nifty score (20 pts)
                    if p.get("use_rs", True):
                        max_pts += 20.0
                        if bool(row_p["rs_ok"]) if side == "LONG" else (not bool(row_p["rs_ok"])):
                            score_pts += 20.0
                    score_pct = (score_pts / max_pts) * 100.0 if max_pts > 0 else 0.0
                    if score_pct >= float(p["min_pass_score_pct"]):
                        pending = {
                            "side": side,
                            "pattern": pat_name,
                            "score_pct": score_pct,
                            "pat_low": float(row_p["low"]),
                            "pat_high": float(row_p["high"]),
                            "pat_atr": float(row_p["atr"]) if pd.notna(row_p["atr"]) else float(row_p["high"] - row_p["low"]),
                            "waited": 0,
                        }
                        break

        # Wait for Trigger TF candlestick + Retracement
        if pending is not None:
            pending["waited"] += 1
            if pending["waited"] > int(p["max_wait_bars"]):
                pending = None
                continue
            t_closed = trig_df[trig_df.index <= ts]
            if len(t_closed) < 10:
                continue
            trig_name, _ = detect_candle_trigger(t_closed.iloc[-12:], p["candle_triggers"], pending["side"], p)
            if trig_name:
                px = float(bar["close"])
                is_long = pending["side"] == "LONG"
                span = max(pending["pat_high"] - pending["pat_low"], 1e-6)
                retrace = ((pending["pat_high"] - px) / span * 100.0) if is_long else ((px - pending["pat_low"]) / span * 100.0)
                if not (float(p["retrace_min_pct"]) <= retrace <= float(p["retrace_max_pct"])):
                    continue
                sw_val = float(t_closed["low"].iloc[-6:].min()) if is_long else float(t_closed["high"].iloc[-6:].max())
                if p["sl_source"] == "pattern_low":
                    init_sl = pending["pat_low"] if is_long else pending["pat_high"]
                elif p["sl_source"] == "atr_stop":
                    init_sl = px - pending["pat_atr"] if is_long else px + pending["pat_atr"]
                else:
                    init_sl = sw_val
                r_unit = (px - init_sl) if is_long else (init_sl - px)
                if r_unit <= 0:
                    continue

                # Setup-Quality / Score-Scaled Dynamic Qty
                s_min = float(p["min_pass_score_pct"])
                ratio = (pending["score_pct"] - s_min) / max(100.0 - s_min, 1.0)
                qty_mult = float(p["score_qty_min_mult"]) + ratio * (float(p["score_qty_max_mult"]) - float(p["score_qty_min_mult"]))
                eff_risk = base_risk_inr * qty_mult
                q1 = (eff_risk / r_unit) * tranches[0]
                pos = _DynPos(
                    symbol=symbol, trade_id=tid, side=pending["side"], entry_ts=ts, entry1_price=px,
                    initial_sl=init_sl, r_unit=r_unit, first_swing=sw_val, pattern=f"{pending['pattern']}+{trig_name}",
                    qty_by_tranche=[q1], entry_prices=[px], remaining_qty=q1, sl_price=init_sl,
                    events=[{"ts": ts.isoformat(), "price": round(px, 2), "label": f"E1 ({int(round(q1))} | {pending['score_pct']:.0f}%)", "kind": "entry"}],
                    stop_trail=[(ts.isoformat(), round(init_sl, 2))],
                )
                tid += 1
                pending = None

    if pos is not None and pos.remaining_qty > 0:
        px = float(df_5m.iloc[-1]["close"])
        is_long = pos.side == "LONG"
        avg_e = sum(pr * q for pr, q in zip(pos.entry_prices, pos.qty_by_tranche)) / max(sum(pos.qty_by_tranche), 1e-6)
        pos.exit_fills.append((pos.remaining_qty, px))
        pos.realized_pnl += pos.remaining_qty * ((px - avg_e) if is_long else (avg_e - px))
        pos.events.append({"ts": df_5m.index[-1].isoformat(), "price": round(px, 2), "label": f"EOD (-{int(round(pos.remaining_qty))})", "kind": "exit"})
        trades.append(_dyn_trade_dict(pos, df_5m.index[-1], px, "eod_close", base_risk_inr, slip_bps, p["holding_mode"]))

    return trades



def _calc_charges(buy_notional: float, sell_notional: float, holding_mode: str, slip_bps: float) -> float:
    turnover = buy_notional + sell_notional
    if holding_mode == "mis":
        brok = min(20.0, 0.0003 * buy_notional) + min(20.0, 0.0003 * sell_notional)
        stt = 0.00025 * sell_notional
        stamp = 0.00003 * buy_notional
    else:
        brok = 0.0
        stt = 0.001 * turnover
        stamp = 0.00015 * buy_notional
    exch_sebi = 0.0000335 * turnover
    gst = 0.18 * (brok + exch_sebi)
    return round(brok + stt + stamp + exch_sebi + gst, 2)

def _dyn_trade_dict(pos: _DynPos, exit_ts: pd.Timestamp, exit_px: float, reason: str, risk_inr: float, slip_bps: float = 0.0, holding_mode: str = "swing") -> dict[str, Any]:
    tot_q = sum(pos.qty_by_tranche)
    avg_e = sum(pr * q for pr, q in zip(pos.entry_prices, pos.qty_by_tranche)) / max(tot_q, 1e-6)
    tot_ex_q = sum(q for q, _ in pos.exit_fills)
    avg_x = (sum(q * px for q, px in pos.exit_fills) / tot_ex_q) if tot_ex_q > 0 else exit_px
    gross_pnl = ((avg_x - avg_e) if pos.side == "LONG" else (avg_e - avg_x)) * tot_q
    buy_n, sell_n = tot_q * avg_e, tot_q * avg_x
    charges = _calc_charges(buy_n, sell_n, holding_mode, slip_bps)
    slip_cost = (buy_n + sell_n) * (slip_bps / 10000.0) if slip_bps > 0 else 0.0
    net_pnl = gross_pnl - charges - slip_cost
    return {
        "trade_id": pos.trade_id,
        "symbol": pos.symbol,
        "entry_ts": pos.entry_ts.to_pydatetime(),
        "exit_ts": exit_ts.to_pydatetime(),
        "avg_entry": round(avg_e, 2),
        "avg_exit": round(avg_x, 2),
        "charges": charges,
        "initial_stop": round(pos.initial_sl, 2),
        "qty_peak": int(round(tot_q)),
        "net_pnl": round(net_pnl, 2),
        "money_r": round(net_pnl / risk_inr, 2) if risk_inr > 0 else 0.0,
        "exit_reason": reason,
        "pattern": pos.pattern,
        "regime_at_entry": pos.side.lower(),
        "stop_trail": json.dumps(pos.stop_trail),
        "events": json.dumps(pos.events),
    }


def run_dynamic_backtest(
    cfg: AppConfig,
    frames_5m: dict[str, pl.DataFrame],
    bench_5m: pl.DataFrame,
    cal: TradingCalendar,
    output_dir: Path | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> Any:
    from tfalgo.backtest.engine import BacktestResult

    run_id = f"run_{cfg.snapshot_hash()}_{cfg.run.seed}"
    out_dir = output_dir or (cfg.storage.output_dir / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    params = dict(getattr(cfg.strategy, "params", {}) or {})
    bench_pd = bench_5m.sort("ts").to_pandas().set_index("ts") if not bench_5m.is_empty() else pd.DataFrame()

    all_trades: list[dict[str, Any]] = []
    all_dates: set[str] = set()
    tid = 1
    syms = [s for s, df in sorted(frames_5m.items()) if not df.is_empty()]
    total_syms = max(1, len(syms))

    for s_idx, sym in enumerate(syms, start=1):
        pd_df = frames_5m[sym].sort("ts").to_pandas().set_index("ts")
        all_dates.update(pd_df.index.strftime("%Y-%m-%d").unique())

        def _on_day(d_done: int, d_tot: int, _sym: str = sym, _si: int = s_idx) -> None:
            if progress_cb:
                progress_cb(d_done, d_tot, f"{_sym} ({_si}/{total_syms}) — {d_done} / {d_tot} days")

        sym_trades = backtest_dynamic_symbol(sym, pd_df, bench_pd, params, cfg.capital.initial, tid, _on_day)
        all_trades.extend(sym_trades)
        tid += len(sym_trades)

    pnl_by_date: dict[str, float] = {}
    for t in all_trades:
        d = t["exit_ts"].strftime("%Y-%m-%d")
        pnl_by_date[d] = pnl_by_date.get(d, 0.0) + float(t["net_pnl"])

    eq = float(cfg.capital.initial)
    eq_rows = []
    for d in sorted(all_dates):
        eq += pnl_by_date.get(d, 0.0)
        eq_rows.append({"date": d, "equity": round(eq, 2), "cash": round(eq, 2)})

    trades_df = pl.DataFrame(all_trades) if all_trades else pl.DataFrame()
    equity_df = pl.DataFrame(eq_rows) if eq_rows else pl.DataFrame({"date": [], "equity": [], "cash": []})
    if not trades_df.is_empty():
        trades_df.write_csv(out_dir / "trades.csv")
    else:
        (out_dir / "trades.csv").write_text("trade_id,symbol,net_pnl,money_r\n", encoding="utf-8")
    equity_df.write_csv(out_dir / "equity.csv")

    tot_pnl = sum(t["net_pnl"] for t in all_trades)
    wins = sum(1 for t in all_trades if t["net_pnl"] > 0)
    wr = (wins / len(all_trades) * 100.0) if all_trades else 0.0
    summary = f"Run ID: {run_id}\nStrategy: dynamic_v1 | Trades: {len(all_trades)} | Win Rate: {wr:.1f}% | Net PnL: INR {tot_pnl:,.2f}\n"
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")
    return BacktestResult(run_id, out_dir, trades_df, equity_df, summary)