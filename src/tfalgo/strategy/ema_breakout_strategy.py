"""Multi-Timeframe EMA (9/21/50) Breakout + Pyramid Trend-Following Strategy.

Place in: src/tfalgo/strategy/ema_breakout_strategy.py
Registers `ema_breakout_v1` in STRATEGIES and provides `run_ema_breakout_backtest(...)`
with day-by-day + symbol progress callbacks for the Flask UI.
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


DEFAULT_PARAMS: dict[str, Any] = {
    "timeframe": "1h",
    "ema_periods": [9, 21, 50],
    "consolidation_min_days": 5,
    "consolidation_max_range_pct": 8.0,
    "breakout_vol_mult": 1.5,
    "vol_avg_bars": 20,
    "max_wait_bars_5m": 36,
    "double_bottom": True,
    "flag_wedge": True,
    "impulse_2x": True,
    "impulse_pct_mult": 2.0,
    "sl_source": "1h_low",
    "holding_mode": "swing",
    "risk_per_trade_pct": 1.0,
    "tranches": [0.33, 0.33, 0.34],
    "add_at_r": [1.0, 2.0],
    "use_risk_neutral_sl": True,
    "trail_timeframe": "1h",
    "trail_ema_initial": 21,
    "trail_ema_runner": 9,
    "runner_atr_period": 14,
    "runner_atr_mult": 0.5,
}


@STRATEGIES.register("ema_breakout_v1")
class EmaBreakoutStrategy(Strategy):
    name = "ema_breakout_v1"

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


def compute_wilder_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_c = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_c).abs(),
            (df["low"] - prev_c).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def resample_ohlcv(df_5m: pd.DataFrame, tf: str) -> pd.DataFrame:
    rule = {"1h": "60min", "1d": "1D"}.get(tf, tf)
    origin = "start_day" if tf == "1d" else pd.Timestamp("2015-01-01 09:15:00", tz=df_5m.index.tz)
    return (
        df_5m.resample(rule, origin=origin, label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open", "close"])
    )


def detect_htf_breakout(htf: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    e_fast, e_mid, e_slow = params.get("ema_periods", [9, 21, 50])
    ema_f = compute_ema(htf["close"], int(e_fast))
    ema_m = compute_ema(htf["close"], int(e_mid))
    ema_s = compute_ema(htf["close"], int(e_slow))

    vol_win = int(params.get("vol_avg_bars", 20))
    vol_mult = float(params.get("breakout_vol_mult", 1.5))
    avg_vol = htf["volume"].rolling(vol_win, min_periods=vol_win).mean().shift(1)

    tf = params.get("timeframe", "1h")
    bars_per_day = 7 if tf == "1h" else 1
    cons_bars = int(params.get("consolidation_min_days", 5)) * bars_per_day
    max_rng_pct = float(params.get("consolidation_max_range_pct", 8.0))

    prior_high = htf["high"].shift(1).rolling(cons_bars, min_periods=cons_bars).max()
    prior_low = htf["low"].shift(1).rolling(cons_bars, min_periods=cons_bars).min()
    prior_rng_pct = ((prior_high - prior_low) / prior_low.replace(0, np.nan)) * 100.0
    prior_below_slow = htf["close"].shift(1).rolling(cons_bars).max() <= ema_s.shift(1) * 1.015

    tight_consolidation = (prior_rng_pct <= max_rng_pct) & prior_below_slow
    bull_break = (
        (htf["close"] > htf["open"])
        & (htf["close"] > ema_f)
        & (htf["close"] > ema_m)
        & (htf["close"] > ema_s)
        & (htf["close"] > prior_high)
        & (htf["volume"] >= vol_mult * avg_vol)
    )
    return (tight_consolidation & bull_break).fillna(False)


def detect_5m_entry_trigger(window_5m: pd.DataFrame, params: dict[str, Any]) -> tuple[bool, str, float]:
    if len(window_5m) < 7:
        return False, "none", np.nan

    last = window_5m.iloc[-1]
    prev = window_5m.iloc[-2]
    if last["close"] <= last["open"]:
        return False, "none", np.nan

    swing_low = float(window_5m["low"].iloc[-6:].min())

    if params.get("impulse_2x", True):
        pct_chg = (window_5m["close"] - window_5m["open"]).abs() / window_5m["open"].replace(0, np.nan)
        avg_prev5 = float(pct_chg.iloc[-6:-1].mean())
        cur_pct = float((last["close"] - last["open"]) / last["open"]) if last["open"] > 0 else 0.0
        mult = float(params.get("impulse_pct_mult", 2.0))
        if avg_prev5 > 0 and cur_pct >= mult * avg_prev5 and last["close"] > prev["high"]:
            return True, "impulse_2x", swing_low

    if params.get("flag_wedge", True) and len(window_5m) >= 6:
        pb = window_5m.iloc[-6:-1]
        early_rng = float(pb["high"].iloc[:2].max() - pb["low"].iloc[:2].min())
        late_rng = float(pb["high"].iloc[-2:].max() - pb["low"].iloc[-2:].min())
        if early_rng > 0 and late_rng <= 0.75 * early_rng and last["close"] > float(pb["high"].iloc[-3:].max()):
            return True, "flag_wedge", float(pb["low"].min())

    if params.get("double_bottom", True) and len(window_5m) >= 10:
        seg = window_5m.iloc[-10:-1]
        l1 = float(seg["low"].iloc[:4].min())
        l2 = float(seg["low"].iloc[5:].min())
        mid_high = float(seg["high"].iloc[3:6].max())
        if l1 > 0 and abs(l2 - l1) / l1 <= 0.0025 and last["close"] > mid_high:
            return True, "double_bottom", min(l1, l2)

    return False, "none", np.nan


@dataclass
class _Pos:
    symbol: str
    trade_id: int
    entry_ts: pd.Timestamp
    entry1_price: float
    initial_sl: float
    r_unit: float
    first_swing_low: float
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


def _avg_entry(pos: _Pos) -> float:
    tot_q = sum(pos.qty_by_tranche)
    return sum(p * q for p, q in zip(pos.entry_prices, pos.qty_by_tranche)) / tot_q if tot_q > 0 else pos.entry1_price


def _risk_neutral_stop(entry_prices: list[float], qtys: list[float], max_loss_inr: float) -> float:
    tot_q = sum(qtys)
    if tot_q <= 0:
        return 0.0
    return (sum(p * q for p, q in zip(entry_prices, qtys)) - max_loss_inr) / tot_q


def backtest_symbol(
    symbol: str,
    df_5m: pd.DataFrame,
    params: dict[str, Any],
    capital: float = 1_000_000.0,
    start_trade_id: int = 1,
    day_progress_cb: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    p = {**DEFAULT_PARAMS, **params}
    htf = resample_ohlcv(df_5m, p["timeframe"])
    htf_trail = htf if p["trail_timeframe"] == p["timeframe"] else resample_ohlcv(df_5m, p["trail_timeframe"])

    htf["breakout"] = detect_htf_breakout(htf, p)
    htf_trail["ema9"] = compute_ema(htf_trail["close"], int(p["trail_ema_runner"]))
    htf_trail["ema21"] = compute_ema(htf_trail["close"], int(p["trail_ema_initial"]))
    htf_trail["atr"] = compute_wilder_atr(htf_trail, int(p["runner_atr_period"]))

    tranches = p["tranches"]
    add_r1, add_r2 = p["add_at_r"]
    risk_inr = capital * (float(p["risk_per_trade_pct"]) / 100.0)
    atr_mult = float(p["runner_atr_mult"])
    holding_mode = p["holding_mode"]

    unique_days = df_5m.index.normalize().unique()
    total_days = max(1, len(unique_days))
    last_day = None
    day_num = 0

    trades: list[dict[str, Any]] = []
    pos: _Pos | None = None
    pending_setup: dict[str, Any] | None = None
    tid = start_trade_id

    for i in range(20, len(df_5m)):
        bar = df_5m.iloc[i]
        ts = df_5m.index[i]
        cur_d = ts.date()
        if cur_d != last_day:
            last_day = cur_d
            day_num += 1
            if day_progress_cb and (day_num % 20 == 0 or day_num == total_days):
                day_progress_cb(day_num, total_days)

        prev_htf = htf[htf.index < ts]
        if pos is None and len(prev_htf) > 0:
            last_htf = prev_htf.iloc[-1]
            if bool(last_htf["breakout"]) and (pending_setup is None or pending_setup["htf_ts"] != prev_htf.index[-1]):
                pending_setup = {"htf_ts": prev_htf.index[-1], "htf_low": float(last_htf["low"]), "bars_waited": 0}

        if pos is not None:
            if float(bar["low"]) <= pos.sl_price:
                exit_px = pos.sl_price
                pos.events.append({"ts": ts.isoformat(), "price": round(exit_px, 2), "label": f"Stop (-{int(round(pos.remaining_qty))})", "kind": "exit"})
                pos.realized_pnl += pos.remaining_qty * (exit_px - _avg_entry(pos))
                trades.append(_trade_dict(pos, ts, exit_px, "stop_hit", risk_inr))
                pos = None
                continue

            p1r = pos.entry1_price + add_r1 * pos.r_unit
            p2r = pos.entry1_price + add_r2 * pos.r_unit
            if pos.tranches_filled == 1 and tranches[1] > 0 and float(bar["high"]) >= p1r:
                q2 = (pos.qty_by_tranche[0] / tranches[0]) * tranches[1]
                pos.qty_by_tranche.append(q2)
                pos.entry_prices.append(p1r)
                pos.remaining_qty += q2
                pos.tranches_filled = 2
                pos.events.append({"ts": ts.isoformat(), "price": round(p1r, 2), "label": f"E2 +{int(round(q2))} @ 1R", "kind": "add"})
                if p["use_risk_neutral_sl"]:
                    rn_sl = _risk_neutral_stop(pos.entry_prices, pos.qty_by_tranche, risk_inr)
                    new_sl = max(pos.sl_price, pos.first_swing_low, rn_sl)
                    if new_sl > pos.sl_price + 0.01:
                        pos.sl_price = new_sl
                        pos.stop_trail.append((ts.isoformat(), round(new_sl, 2)))

            if pos.tranches_filled == 2 and tranches[2] > 0 and float(bar["high"]) >= p2r:
                q3 = (pos.qty_by_tranche[0] / tranches[0]) * tranches[2]
                pos.qty_by_tranche.append(q3)
                pos.entry_prices.append(p2r)
                pos.remaining_qty += q3
                pos.tranches_filled = 3
                pos.events.append({"ts": ts.isoformat(), "price": round(p2r, 2), "label": f"E3 +{int(round(q3))} @ 2R", "kind": "add"})
                rn_sl = _risk_neutral_stop(pos.entry_prices, pos.qty_by_tranche, risk_inr)
                new_sl = max(pos.sl_price, pos.entry1_price, rn_sl)
                if new_sl > pos.sl_price + 0.01:
                    pos.sl_price = new_sl
                    pos.stop_trail.append((ts.isoformat(), round(new_sl, 2)))

            p3r = pos.entry1_price + 3.0 * pos.r_unit
            p6r = pos.entry1_price + 6.0 * pos.r_unit
            tot_filled = sum(pos.qty_by_tranche)
            avg_e = _avg_entry(pos)

            if not pos.sold_3r and float(bar["high"]) >= p3r:
                sell_q = min(pos.remaining_qty, tot_filled / 3.0)
                pos.realized_pnl += sell_q * (p3r - avg_e)
                pos.remaining_qty -= sell_q
                pos.sold_3r = True
                pos.events.append({"ts": ts.isoformat(), "price": round(p3r, 2), "label": f"Exit 1/3 (-{int(round(sell_q))}) @ 3R", "kind": "partial_exit"})

            if not pos.sold_6r and float(bar["high"]) >= p6r and pos.remaining_qty > 0:
                sell_q = min(pos.remaining_qty, tot_filled / 3.0)
                pos.realized_pnl += sell_q * (p6r - avg_e)
                pos.remaining_qty -= sell_q
                pos.sold_6r = True
                pos.events.append({"ts": ts.isoformat(), "price": round(p6r, 2), "label": f"Exit 1/3 (-{int(round(sell_q))}) @ 6R", "kind": "partial_exit"})

            closed_trail = htf_trail[htf_trail.index < ts]
            if len(closed_trail) > 0:
                ct = closed_trail.iloc[-1]
                cand_sl = pos.sl_price
                if pos.sold_3r and pos.sold_6r:
                    if pd.notna(ct["ema9"]) and pd.notna(ct["atr"]):
                        cand_sl = max(cand_sl, float(ct["ema9"]) - atr_mult * float(ct["atr"]))
                elif pd.notna(ct["ema21"]):
                    cand_sl = max(cand_sl, float(ct["ema21"]))
                if cand_sl > pos.sl_price + 0.05:
                    pos.sl_price = cand_sl
                    pos.stop_trail.append((ts.isoformat(), round(cand_sl, 2)))

            if holding_mode == "mis" and ts.strftime("%H:%M") >= "15:15":
                exit_px = float(bar["close"])
                pos.events.append({"ts": ts.isoformat(), "price": round(exit_px, 2), "label": f"MIS Exit (-{int(round(pos.remaining_qty))})", "kind": "exit"})
                pos.realized_pnl += pos.remaining_qty * (exit_px - avg_e)
                trades.append(_trade_dict(pos, ts, exit_px, "mis_squareoff", risk_inr))
                pos = None
            continue

        if pending_setup is not None:
            pending_setup["bars_waited"] += 1
            if pending_setup["bars_waited"] > int(p["max_wait_bars_5m"]):
                pending_setup = None
                continue
            ok, pat, sw_low = detect_5m_entry_trigger(df_5m.iloc[max(0, i - 14):i + 1], p)
            if ok:
                entry_px = float(bar["close"])
                init_sl = pending_setup["htf_low"] if p["sl_source"] in ("1h_low", "1d_low") else sw_low
                r_unit = entry_px - init_sl
                if r_unit <= 0:
                    continue
                q1 = (risk_inr / r_unit) * tranches[0]
                pos = _Pos(
                    symbol=symbol, trade_id=tid, entry_ts=ts, entry1_price=entry_px,
                    initial_sl=init_sl, r_unit=r_unit, first_swing_low=sw_low, pattern=pat,
                    qty_by_tranche=[q1], entry_prices=[entry_px], remaining_qty=q1, sl_price=init_sl,
                    events=[{"ts": ts.isoformat(), "price": round(entry_px, 2), "label": f"E1 ({int(round(q1))} qty)", "kind": "entry"}],
                    stop_trail=[(ts.isoformat(), round(init_sl, 2))],
                )
                tid += 1
                pending_setup = None

    if pos is not None and pos.remaining_qty > 0:
        exit_px = float(df_5m.iloc[-1]["close"])
        pos.events.append({"ts": df_5m.index[-1].isoformat(), "price": round(exit_px, 2), "label": f"EOD Exit (-{int(round(pos.remaining_qty))})", "kind": "exit"})
        pos.realized_pnl += pos.remaining_qty * (exit_px - _avg_entry(pos))
        trades.append(_trade_dict(pos, df_5m.index[-1], exit_px, "eod_close", risk_inr))

    return trades


def _trade_dict(pos: _Pos, exit_ts: pd.Timestamp, exit_px: float, reason: str, risk_inr: float) -> dict[str, Any]:
    return {
        "trade_id": pos.trade_id,
        "symbol": pos.symbol,
        "entry_ts": pos.entry_ts.to_pydatetime(),
        "exit_ts": exit_ts.to_pydatetime(),
        "avg_entry": round(_avg_entry(pos), 2),
        "avg_exit": round(exit_px, 2),
        "initial_stop": round(pos.initial_sl, 2),
        "tranches_filled": pos.tranches_filled,
        "qty_peak": int(round(sum(pos.qty_by_tranche))),
        "net_pnl": round(pos.realized_pnl, 2),
        "money_r": round(pos.realized_pnl / risk_inr, 2) if risk_inr > 0 else 0.0,
        "exit_reason": reason,
        "pattern": pos.pattern,
        "regime_at_entry": "trend",
        "stop_trail": json.dumps(pos.stop_trail),
        "events": json.dumps(pos.events),
    }


def run_ema_breakout_backtest(
    cfg: AppConfig,
    frames_5m: dict[str, pl.DataFrame],
    bench_5m: pl.DataFrame,
    cal: TradingCalendar,
    output_dir: Path | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> Any:
    """Drop-in BacktestResult runner called from engine.py when strategy == ema_breakout_v1."""
    from tfalgo.backtest.engine import BacktestResult

    run_id = f"run_{cfg.snapshot_hash()}_{cfg.run.seed}"
    out_dir = output_dir or (cfg.storage.output_dir / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    params = dict(getattr(cfg.strategy, "params", {}) or {})
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

        sym_trades = backtest_symbol(sym, pd_df, params, cfg.capital.initial, start_trade_id=tid, day_progress_cb=_on_day)
        all_trades.extend(sym_trades)
        tid += len(sym_trades)

    sorted_dates = sorted(all_dates)
    pnl_by_date: dict[str, float] = {}
    for t in all_trades:
        d = t["exit_ts"].strftime("%Y-%m-%d")
        pnl_by_date[d] = pnl_by_date.get(d, 0.0) + float(t["net_pnl"])

    eq = float(cfg.capital.initial)
    eq_rows = []
    for d in sorted_dates:
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
    summary = (
        f"Run ID: {run_id}\n"
        f"Strategy: ema_breakout_v1 | Trades: {len(all_trades)} | Win Rate: {wr:.1f}% | Net PnL: INR {tot_pnl:,.2f}\n"
    )
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")
    return BacktestResult(run_id, out_dir, trades_df, equity_df, summary)