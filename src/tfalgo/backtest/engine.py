"""Two-stage deterministic backtest engine (Section 8.3)."""

from __future__ import annotations

import logging
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from tfalgo.calendar import TradingCalendar
from tfalgo.config import AppConfig
from tfalgo.data.resample import resample
from tfalgo.data.store import BarStore
from tfalgo.execution.sim_broker import SimBroker
from tfalgo.indicators.features import (
    daily_features,
    hourly_features,
    intraday_features,
    m15_features,
    with_relative_strength,
)
from tfalgo.indicators.patterns import evaluate_patterns
from tfalgo.regime.score import RegimeSnapshot, classify_regime
from tfalgo.strategy.base import (
    STRATEGIES,
    LifecycleState,
    PortfolioSnapshot,
    PositionState,
    SymbolState,
    TrancheFill,
)
from tfalgo.strategy.carry import evaluate_carry
from tfalgo.strategy.pyramiding import open_risk
from tfalgo.strategy.risk import is_throttle_active, portfolio_allows_entry
from tfalgo.strategy.score import compute_entry_score, evaluate_vetoes
from tfalgo.strategy.setup import daily_gate_ok
from tfalgo.strategy.sizing import SIZING_RULES, STOP_RULES
from tfalgo.strategy.trigger import compute_entry_zone, find_flag_high
from tfalgo.universe.constituents import build_constituents
from tfalgo.universe.filters import build_panel
from tfalgo.backtest.metrics import compute_trade_metrics, format_trade_summary
from tfalgo.backtest.portfolio import ActiveTradeMeta, PortfolioLedger

log = logging.getLogger(__name__)

LIMITATIONS_HEADER = """# KNOWN LIMITATIONS
# - Survivorship bias: symbol list is as-of today, not point-in-time.
# - Pilot basket (13 stocks) validates code only; it cannot prove an edge.
# - Only 5m bars: stops/fills use 5m data with conservative ambiguity rules; slippage is modelled.
# - Broker charges/STT/tax rules change (verify `as_of` in zerodha.yaml).
# - Backtest results are not a forecast.
"""


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    output_dir: Path
    trades: pl.DataFrame
    equity: pl.DataFrame
    summary_text: str


@dataclass
class PendingOrder:
    symbol: str
    side: str
    qty: int
    product: str
    reason: str
    bars_left: int
    is_entry: bool = False
    meta_ctx: dict[str, Any] | None = None


class BacktestEngine:
    def __init__(self, cfg: AppConfig, store: BarStore, cal: TradingCalendar) -> None:
        self.cfg, self.store, self.cal = cfg, store, cal

    def run(self) -> BacktestResult:
        tf = self.cfg.run.base_timeframe
        syms = self.cfg.data.symbols or [s for s in self.store.list_symbols(tf) if not s.startswith("idx:")]
        frames = {s: self.store.read_bars(s, tf, self.cfg.run.start, self.cfg.run.end) for s in syms}
        bench_key = f"idx:{self.cfg.benchmark.index}"
        bench = self.store.read_bars(bench_key, tf, self.cfg.run.start, self.cfg.run.end)
        return run_backtest_from_frames(self.cfg, frames, bench, self.cal)


def _prep_daily(df5: pl.DataFrame, cfg: AppConfig, cal: TradingCalendar) -> pl.DataFrame:
    d1 = resample(df5, "1D", session_open=cfg.session.open, session_close=cfg.session.close, tz=cfg.run.timezone)
    if d1.is_empty():
        return d1
    d1 = d1.with_columns(
        date=pl.col("ts").dt.date(),
        coverage=pl.col("n_bars").cast(pl.Float64) / float(max(1, cal.session_minutes // 5)),
    )
    dates = d1["date"].to_list()
    avail = [cal.next_trading_day(d) for d in dates]
    d1 = d1.with_columns(pl.Series("avail_date", avail))
    return daily_features(d1, cfg)

@dataclass(frozen=True)
class PreparedMarketData:
    """Precomputed multi-timeframe features reusable across 1000+ strategy runs."""

    daily_map: dict[str, pl.DataFrame]
    hourly_map: dict[str, pl.DataFrame]
    m15_map: dict[str, pl.DataFrame]
    m5_map: dict[str, pl.DataFrame]
    bench_d1: pl.DataFrame
    panel: pl.DataFrame
    all_dates: list[date]
    daily_by_avail: dict[str, dict[date, dict[str, Any]]]
    avail_lists: dict[str, list[date]]
    h_ends: dict[str, list[datetime]]
    m15_ends: dict[str, list[datetime]]
    h_rows: dict[str, list[dict[str, Any]]]
    m15_rows: dict[str, list[dict[str, Any]]]
    m5_by_date: dict[date, list[tuple[datetime, str, dict[str, Any]]]]
    bench_by_avail: dict[date, dict[str, Any]]
    panel_by_date: dict[date, dict[str, dict[str, Any]]]


def prepare_market_data(
    cfg: AppConfig,
    frames_5m: dict[str, pl.DataFrame],
    bench_5m: pl.DataFrame,
    cal: TradingCalendar,
) -> PreparedMarketData:
    cons = build_constituents(cfg, available=frames_5m.keys())
    bench_d1 = _prep_daily(bench_5m, cfg, cal) if not bench_5m.is_empty() else pl.DataFrame()
    daily_map: dict[str, pl.DataFrame] = {}
    hourly_map: dict[str, pl.DataFrame] = {}
    m15_map: dict[str, pl.DataFrame] = {}
    m5_map: dict[str, pl.DataFrame] = {}

    for sym, df5 in sorted(frames_5m.items()):
        if df5.is_empty():
            continue
        d1 = _prep_daily(df5, cfg, cal)
        if not bench_d1.is_empty():
            d1 = with_relative_strength(d1, bench_d1, cfg)
        daily_map[sym] = d1
        h60 = resample(df5, "60m", session_open=cfg.session.open, session_close=cfg.session.close, tz=cfg.run.timezone)
        h60 = h60.with_columns(in_stats=(pl.col("n_bars") == 12) if cfg.hourly.partial_bar_policy == "price_only" else pl.lit(True))
        hourly_map[sym] = hourly_features(h60, cfg)
        m15 = resample(df5, "15m", session_open=cfg.session.open, session_close=cfg.session.close, tz=cfg.run.timezone)
        m15_map[sym] = m15_features(m15, cfg)
        m5_map[sym] = intraday_features(df5.sort("ts"), cfg)

    panel = build_panel(daily_map, cons, cfg) if daily_map else pl.DataFrame()
    all_dates = sorted({d for df5 in m5_map.values() for d in df5["ts"].dt.date().to_list()})
    daily_by_avail = {s: {r["avail_date"]: r for r in d1.iter_rows(named=True)} for s, d1 in daily_map.items()}
    avail_lists = {s: d1["avail_date"].to_list() for s, d1 in daily_map.items()}
    h_ends = {s: df["bar_end"].to_list() for s, df in hourly_map.items()}
    m15_ends = {s: df["bar_end"].to_list() for s, df in m15_map.items()}
    h_rows = {s: df.to_dicts() for s, df in hourly_map.items()}
    m15_rows = {s: df.to_dicts() for s, df in m15_map.items()}
    m5_by_date: dict[date, list[tuple[datetime, str, dict[str, Any]]]] = {}
    for sym, m5 in m5_map.items():
        for row in m5.iter_rows(named=True):
            m5_by_date.setdefault(row["ts"].date(), []).append((row["ts"], sym, row))
    for bars in m5_by_date.values():
        bars.sort(key=lambda x: (x[0], x[1]))
    bench_by_avail = {r["avail_date"]: r for r in bench_d1.iter_rows(named=True)} if not bench_d1.is_empty() else {}
    panel_by_date: dict[date, dict[str, dict[str, Any]]] = {}
    if not panel.is_empty():
        for row in panel.iter_rows(named=True):
            panel_by_date.setdefault(row["date"], {})[row["symbol"]] = row
    return PreparedMarketData(
        daily_map, hourly_map, m15_map, m5_map, bench_d1, panel, all_dates,
        daily_by_avail, avail_lists, h_ends, m15_ends, h_rows, m15_rows,
        m5_by_date, bench_by_avail, panel_by_date,
    )

def run_backtest_from_frames(
    cfg: AppConfig,
    frames_5m: dict[str, pl.DataFrame],
    bench_5m: pl.DataFrame,
    cal: TradingCalendar,
    output_dir: Path | None = None,
    prepared: PreparedMarketData | None = None,
    progress_cb=None,
) -> BacktestResult:
    """Pure in-memory runner (used by both BacktestEngine and synthetic tests)."""
    if cfg.strategy.name == "ema_breakout_v1":
        from tfalgo.strategy.ema_breakout_strategy import run_ema_breakout_backtest
        return run_ema_breakout_backtest(cfg, frames_5m, bench_5m, cal, output_dir, progress_cb=progress_cb)
    run_id = f"run_{cfg.snapshot_hash()}_{cfg.run.seed}"
    out_dir = output_dir or (cfg.storage.output_dir / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = prepared or prepare_market_data(cfg, frames_5m, bench_5m, cal)
    strategy = STRATEGIES.get(cfg.strategy.name)()
    stop_rule = STOP_RULES.get(cfg.strategy.stop)()

    ledger = PortfolioLedger(cfg.capital.initial, cfg.capital.sale_proceeds)
    broker = SimBroker(cfg)
    states: dict[str, SymbolState] = {s: SymbolState(s) for s in data.m5_map}
    active_meta: dict[str, ActiveTradeMeta] = {}
    pending: dict[str, PendingOrder] = {}
    equity_rows: list[dict[str, Any]] = []
    event_lines: list[str] = []
    last_prices: dict[str, float] = {}

    log.info("Starting backtest: %d trading days, %d symbols", len(data.all_dates), len(data.m5_map))

    for idx_d, cur_date in enumerate(data.all_dates):
        if idx_d % 50 == 0 or idx_d == len(data.all_dates) - 1:
            log.info("Progress: %d/%d days (%s) | trades=%d", idx_d + 1, len(data.all_dates), cur_date, len(ledger.trades))
        if progress_cb and (idx_d % 20 == 0 or idx_d == len(data.all_dates) - 1):
            progress_cb(idx_d + 1, len(data.all_dates), f"{cur_date} — {idx_d + 1} / {len(data.all_dates)} days | trades={len(ledger.trades)}")
        ledger.settle_t1(cur_date)
        next_td = data.all_dates[idx_d + 1] if idx_d + 1 < len(data.all_dates) else None

        # Pre-open regime for cur_date (data <= D-1 via avail_date == cur_date)
        b_row = data.bench_by_avail.get(cur_date)
        p_rows = data.panel_by_date.get(cur_date, {})
        if b_row is not None:
            elig_rows = [r for r in p_rows.values() if r["eligible"]]
            if elig_rows:
                above50 = sum(
                    1 for r in elig_rows
                    if (d_row := data.daily_by_avail[r["symbol"]].get(cur_date)) and d_row.get("sma50") and d_row["close"] > d_row["sma50"]
                )
                breadth_pct = 100.0 * above50 / len(elig_rows)
            else:
                breadth_pct = None
            snap = RegimeSnapshot(
                index_close=float(b_row["close"]),
                index_sma50=b_row.get("sma50"),
                index_sma200=b_row.get("sma200"),
                breadth_above_50dma_pct=breadth_pct,
                net_new_highs_minus_lows=0 if elig_rows else None,
            )
            reg = classify_regime(snap, cfg)
        else:
            reg = classify_regime(RegimeSnapshot(100.0, 95.0, 90.0, 60.0, 1), cfg)

        # Reset daily entry counters & tick cooldowns
        for sym, st in list(states.items()):
            cd = max(0, st.cooldown_days_left - 1) if st.cooldown_days_left > 0 else 0
            states[sym] = SymbolState(**{**st.__dict__, "entries_today": 0, "cooldown_days_left": cd})

        day_bars = data.m5_by_date.get(cur_date, [])
        pat_cache: dict[str, tuple[str | None, float]] = {}

        day_start_eq = ledger.cash + sum(
            (-1 if states[s].position.side == "SHORT" else 1) * states[s].position.total_qty * last_prices.get(s, states[s].position.avg_entry)
            for s in states if states[s].position is not None
        )
        entries_today_port = 0

        for ts, sym, bar in day_bars:
            last_prices[sym] = float(bar["close"])
            st = states[sym]
            t_str = ts.strftime("%H:%M")

            # 1. Fill pending order at bar open
            if sym in pending:
                po = pending[sym]
                fill, rem = broker.execute_bar_fill(
                    sym, po.side, po.qty, po.product, ts,  # type: ignore[arg-type]
                    float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["volume"]),
                    reason=po.reason,
                )
                if fill is not None:
                    ledger.apply_fill(fill, next_td)
                    if po.is_entry and st.position is None and po.meta_ctx is not None:
                        mc = po.meta_ctx
                        pos_side = mc.get("side", "LONG")
                        if pos_side == "SHORT":
                            sp = float(mc["stop_price"])
                            stop_res = {"valid": sp > fill.price, "stop_price": sp, "stop_source": mc.get("stop_source", "or_high")}
                            rps = sp - fill.price
                        else:
                            stop_res = stop_rule.compute(fill.price, mc["swing_low"], mc["atr15"], mc["hourly_atr"], cfg)
                            rps = fill.price - (stop_res["stop_price"] or fill.price)
                        if stop_res["valid"] and rps > 0:
                            pos = PositionState(
                                symbol=sym,
                                tranches=(TrancheFill(fill.qty, fill.price, "MIS", ts),),
                                initial_stop=stop_res["stop_price"],
                                current_stop=stop_res["stop_price"],
                                stop_source=stop_res["stop_source"],
                                planned_full_qty=mc["planned_full_qty"],
                                initial_risk_budget=mc["risk_budget"],
                                entry_price_1=fill.price,
                                risk_per_share=rps,
                                highest_high=float(bar["high"]),
                                side=pos_side,
                            )
                            tid = ledger.next_trade_id()
                            active_meta[sym] = ActiveTradeMeta(
                                trade_id=tid, symbol=sym, entry_ts=ts,
                                initial_stop=stop_res["stop_price"], stop_source=stop_res["stop_source"],
                                risk_per_share=pos.risk_per_share, planned_full_risk_inr=mc["planned_full_risk"],
                                regime_at_entry=reg.label, entry_score=mc["entry_score"],
                                score_zone=mc["score_zone"], pattern=mc["pattern"] or "none",
                                pattern_quality=mc["pattern_quality"], bound_constraint=mc["bound_constraint"],
                                qty_peak=fill.qty,
                                total_buy_qty=fill.qty if pos_side == "LONG" else 0,
                                total_buy_notional=(fill.qty * fill.price) if pos_side == "LONG" else 0.0,
                                total_sell_qty=fill.qty if pos_side == "SHORT" else 0,
                                total_sell_notional=(fill.qty * fill.price) if pos_side == "SHORT" else 0.0,
                                fees=fill.fees, slippage_cost=fill.slippage_cost,
                                stop_trail=[(ts.isoformat(), stop_res["stop_price"])],
                                events=[{"ts": ts.isoformat(), "price": round(fill.price, 2), "label": f"E1 ({fill.qty} qty)", "kind": "entry"}],
                            )
                            states[sym] = SymbolState(
                                symbol=sym, lifecycle=LifecycleState.OPEN_MIS, position=pos,
                                entries_today=st.entries_today + 1,
                            )
                            entries_today_port += 1
                            event_lines.append(f"{ts.isoformat()} ENTRY {sym} qty={fill.qty} @ {fill.price:.2f}")
                if rem <= 0 or po.bars_left <= 1:
                    pending.pop(sym, None)
                else:
                    po.qty = rem
                    po.bars_left -= 1

            # 2. Evaluate stops on open position (STOP WINS if same bar as entry/add)
            st = states[sym]
            stop_hit = st.position is not None and (
                float(bar["high"]) >= st.position.current_stop if st.position.side == "SHORT"
                else float(bar["low"]) <= st.position.current_stop
            )
            if stop_hit:
                pos = st.position
                prod = "CNC" if pos.carried else "MIS"
                exit_side = "BUY" if pos.side == "SHORT" else "SELL"
                fill, _ = broker.execute_bar_fill(
                    sym, exit_side, pos.total_qty, prod, ts,
                    float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["volume"]),
                    is_stop=True, stop_price=pos.current_stop, reason="stop_hit",
                )
                if fill is not None:
                    ledger.apply_fill(fill, next_td)
                    meta = active_meta.pop(sym)
                    if fill.side == "SELL":
                        meta.total_sell_qty += fill.qty
                        meta.total_sell_notional += fill.qty * fill.price
                    else:
                        meta.total_buy_qty += fill.qty
                        meta.total_buy_notional += fill.qty * fill.price
                    meta.fees += fill.fees
                    meta.slippage_cost += fill.slippage_cost
                    if float(bar["open"]) < pos.current_stop:
                        meta.gap_loss_flag = True
                    meta.events.append({
                        "ts": ts.isoformat(),
                        "price": round(fill.price, 2),
                        "label": f"Stop (-{fill.qty})",
                        "kind": "exit",
                    })
                    ledger.close_trade(meta, ts, "stop_hit", max(1, pos.days_held + 1))
                    states[sym] = SymbolState(
                        symbol=sym, lifecycle=LifecycleState.COOLDOWN,
                        cooldown_days_left=cfg.reentry.cooldown_days_after_stop,
                        entries_today=st.entries_today,
                    )
                    event_lines.append(f"{ts.isoformat()} STOP {sym} qty={fill.qty} @ {fill.price:.2f}")
                continue

            # 3. 15:15 MIS square-off
            if t_str >= cfg.carry.mis_squareoff_time and st.position is not None and not st.position.carried:
                pos = st.position
                sq_side = "BUY" if pos.side == "SHORT" else "SELL"
                fill, _ = broker.execute_bar_fill(
                    sym, sq_side, pos.total_qty, "MIS", ts,
                    float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["volume"]),
                    is_stop=True, stop_price=float(bar["open"]), reason="mis_squareoff",
                )
                if fill is not None:
                    ledger.apply_fill(fill, next_td)
                    meta = active_meta.pop(sym)
                    if fill.side == "SELL":
                        meta.total_sell_qty += fill.qty
                        meta.total_sell_notional += fill.qty * fill.price
                    else:
                        meta.total_buy_qty += fill.qty
                        meta.total_buy_notional += fill.qty * fill.price
                    meta.fees += fill.fees
                    meta.slippage_cost += fill.slippage_cost
                    meta.events.append({
                        "ts": ts.isoformat(),
                        "price": round(fill.price, 2),
                        "label": f"MIS Exit (-{fill.qty})",
                        "kind": "exit",
                    })
                    ledger.close_trade(meta, ts, "mis_squareoff", 1)
                    states[sym] = SymbolState(symbol=sym, lifecycle=LifecycleState.IDLE, entries_today=st.entries_today)
                continue

            # 4. Strategy signal generation (delegated to registered Strategy)
            if st.position is None and sym not in pending:
                d_row = data.daily_by_avail.get(sym, {}).get(cur_date)
                p_row = p_rows.get(sym)
                h_idx = bisect_right(data.h_ends[sym], ts)
                m15_idx = bisect_right(data.m15_ends[sym], ts)
                if d_row and p_row and h_idx > 0 and m15_idx > 0:
                    h_last = data.h_rows[sym][h_idx - 1]
                    m15_list = data.m15_rows[sym]
                    m15_last = m15_list[m15_idx - 1]
                    atr15 = float(m15_last.get("atr") or 0.0)
                    h_atr = float(h_last.get("atr") or atr15 * 2.0)
                    flag_hi = None
                    if atr15 > 0 and cfg.strategy.name == "trend_pullback_v1":
                        f_cfg = cfg.setup.flag
                        for flen in range(f_cfg.max_bars, f_cfg.min_bars - 1, -1):
                            if m15_idx >= flen:
                                win = m15_list[m15_idx - flen : m15_idx]
                                w_hi = max(float(r["high"]) for r in win)
                                w_lo = min(float(r["low"]) for r in win)
                                if (w_hi - w_lo) <= f_cfg.max_range_atr15 * atr15:
                                    flag_hi = w_hi
                                    break
                    if cfg.strategy.name == "trend_pullback_v1" or cfg.strategy.params.get("use_patterns"):
                        if sym not in pat_cache:
                            d_idx = bisect_right(data.avail_lists[sym], cur_date)
                            pat_cache[sym] = evaluate_patterns(data.daily_map[sym].slice(0, d_idx), cfg.score.patterns)
                        pat_name, pat_q = pat_cache[sym]
                    else:
                        pat_name, pat_q = None, 0.0
                    close_px = float(bar["close"])
                    rng_b = float(bar["high"]) - float(bar["low"])
                    ext_h = (close_px - float(h_last.get(f"ema{cfg.trend.ribbon_emas[-1]}") or close_px)) / max(h_atr, 1e-6)
                    ctx = {
                        "ts": ts, "bar_time_str": t_str, "bar_open": float(bar["open"]),
                        "bar_high": float(bar["high"]), "bar_low": float(bar["low"]),
                        "bar_close": close_px, "bar_volume": float(bar["volume"]),
                        "eligible": bool(p_row["eligible"]), "above_200dma": bool(d_row.get("above_slow_dma")),
                        "regime_label": reg.label, "regime_mult": reg.multiplier,
                        "adtv_cr": float(p_row["adtv_cr"] or 0.0), "atr_pct": float(p_row["atr_pct"] or 0.0),
                        "adv20": float(p_row["adtv_cr"] or 20.0) * 1e7 / max(close_px, 1.0),
                        "dma_stack_full": bool(d_row.get("dma_stack_full")),
                        "dma_stack_partial": bool(d_row.get("dma_stack_partial")),
                        "slow_dma_rising": bool(d_row.get("slow_dma_rising")),
                        "rs_pct": p_row.get("rs_pct"), "pct_below_52w_high": d_row.get("pct_below_52w_high"),
                        "leg_valid": bool(h_last.get("leg_valid")), "pullback_low": h_last.get("pullback_low"),
                        "pullback_high": h_last.get("leg_high"), "flag_high": flag_hi,
                        "atr15": atr15, "hourly_atr": h_atr,
                        "ribbon_stack_ok": bool(h_last.get("rib_stack_ok")), "ribbon_fanning": bool(h_last.get("rib_fanning")),
                        "pattern_name": pat_name, "pattern_quality": pat_q,
                        "depth_hatr": h_last.get("pullback_depth_hatr"), "depth_leg_frac": 0.25,
                        "hourly_closes_below_ema20": 0 if not h_last.get("close_below_slow_ema") else 1,
                        "vol_contraction_ratio": 0.7, "range_ratio_3bar": float(h_last.get("range_ratio") or 1.0),
                        "rvol_pace": float(bar.get("rvol_pace") or 1.5),
                        "close_in_bar_range": (close_px - float(bar["low"])) / rng_b if rng_b > 0 else 0.5,
                        "extension_hatr": ext_h, "gap_daily_atr": 0.5, "stock_er": d_row.get("er"),
                    }
                    throt = is_throttle_active(ledger.closed_money_rs, False, cfg)
                    open_pos_cnt = sum(1 for s in states.values() if s.position is not None)
                    heat = sum(open_risk(s.position.tranches, s.position.current_stop) for s in states.values() if s.position is not None)
                    snap_p = PortfolioSnapshot(day_start_eq, ledger.cash, open_pos_cnt, heat, 0.0, 0.0, entries_today_port, {}, throt)
                    new_st, intents = strategy.on_bar(st, ctx, snap_p, cfg)
                    states[sym] = new_st
                    for intent in intents:
                        if intent.side in ("BUY", "SELL") and intent.qty > 0:
                            rps = intent.meta.get("risk_per_share") or max(close_px * 0.03, 0.05)
                            p_ok, _ = portfolio_allows_entry(st, snap_p, p_row.get("sector"), 0.0, intent.qty * rps, cfg)
                            if p_ok:
                                pending[sym] = PendingOrder(
                                    symbol=sym, side=intent.side, qty=intent.qty, product=intent.product,
                                    reason=intent.reason, bars_left=cfg.costs.slippage.max_fill_bars,
                                    is_entry=True, meta_ctx=intent.meta or None,
                                )

        # End-of-day equity snapshot
        mtm = ledger.cash + sum(
            (-1 if states[s].position.side == "SHORT" else 1) * states[s].position.total_qty * last_prices.get(s, states[s].position.avg_entry)
            for s in states if states[s].position is not None
        )
        equity_rows.append({"date": cur_date.isoformat(), "equity": round(mtm, 2), "cash": round(ledger.cash, 2)})

    # Build output DataFrames & write files
    trades_df = pl.DataFrame([t.__dict__ for t in ledger.trades]) if ledger.trades else pl.DataFrame()
    equity_df = pl.DataFrame(equity_rows) if equity_rows else pl.DataFrame({"date": [], "equity": [], "cash": []})
    fills_df = pl.DataFrame(ledger.fills) if ledger.fills else pl.DataFrame()

    if not trades_df.is_empty():
        trades_df.write_csv(out_dir / "trades.csv")
    else:
        (out_dir / "trades.csv").write_text("trade_id,symbol,net_pnl,money_r\n", encoding="utf-8")
    equity_df.write_csv(out_dir / "equity.csv")
    if not fills_df.is_empty():
        fills_df.write_csv(out_dir / "fills.csv")
    (out_dir / "events.log").write_text("\n".join(event_lines), encoding="utf-8")

    metrics = compute_trade_metrics(ledger.trades)
    summary = f"{LIMITATIONS_HEADER}\nRun ID: {run_id}\n{format_trade_summary(metrics)}\n"
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")
    return BacktestResult(run_id, out_dir, trades_df, equity_df, summary)