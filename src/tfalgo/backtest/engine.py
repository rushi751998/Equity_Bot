"""Two-stage deterministic backtest engine (Section 8.3)."""

from __future__ import annotations

import logging
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


def run_backtest_from_frames(
    cfg: AppConfig,
    frames_5m: dict[str, pl.DataFrame],
    bench_5m: pl.DataFrame,
    cal: TradingCalendar,
    output_dir: Path | None = None,
) -> BacktestResult:
    """Pure in-memory runner (used by both BacktestEngine and synthetic tests)."""
    run_id = f"run_{cfg.snapshot_hash()}_{cfg.run.seed}"
    out_dir = output_dir or (cfg.storage.output_dir / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

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

    ledger = PortfolioLedger(cfg.capital.initial, cfg.capital.sale_proceeds)
    broker = SimBroker(cfg)
    states: dict[str, SymbolState] = {s: SymbolState(s) for s in m5_map}
    active_meta: dict[str, ActiveTradeMeta] = {}
    pending: dict[str, PendingOrder] = {}
    equity_rows: list[dict[str, Any]] = []
    event_lines: list[str] = []
    last_prices: dict[str, float] = {}

    # Index daily lookup by avail_date
    bench_by_avail: dict[date, dict[str, Any]] = {}
    if not bench_d1.is_empty():
        for row in bench_d1.iter_rows(named=True):
            bench_by_avail[row["avail_date"]] = row

    panel_by_date: dict[date, dict[str, dict[str, Any]]] = {}
    if not panel.is_empty():
        for row in panel.iter_rows(named=True):
            panel_by_date.setdefault(row["date"], {})[row["symbol"]] = row

    daily_by_avail: dict[str, dict[date, dict[str, Any]]] = {}
    for sym, d1 in daily_map.items():
        daily_by_avail[sym] = {row["avail_date"]: row for row in d1.iter_rows(named=True)}

    stop_rule = STOP_RULES.get(cfg.strategy.stop)()
    sizer = SIZING_RULES.get("risk_cap_liquidity")()

    for idx_d, cur_date in enumerate(all_dates):
        ledger.settle_t1(cur_date)
        next_td = all_dates[idx_d + 1] if idx_d + 1 < len(all_dates) else None

        # Pre-open regime for cur_date (data <= D-1 via avail_date == cur_date)
        b_row = bench_by_avail.get(cur_date)
        p_rows = panel_by_date.get(cur_date, {})
        if b_row is not None:
            elig_rows = [r for r in p_rows.values() if r["eligible"]]
            if elig_rows:
                above50 = sum(
                    1 for r in elig_rows
                    if (d_row := daily_by_avail[r["symbol"]].get(cur_date)) and d_row.get("sma50") and d_row["close"] > d_row["sma50"]
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

        # Watchlist: symbols passing daily gate & having valid hourly setup
        day_bars: list[tuple[datetime, str, dict[str, Any]]] = []
        for sym, m5 in m5_map.items():
            sub = m5.filter(pl.col("ts").dt.date() == cur_date)
            for row in sub.iter_rows(named=True):
                day_bars.append((row["ts"], sym, row))
        day_bars.sort(key=lambda x: (x[0], x[1]))

        day_start_eq = ledger.cash + sum(
            states[s].position.total_qty * last_prices.get(s, states[s].position.avg_entry)
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
                        stop_res = stop_rule.compute(
                            fill.price, mc["swing_low"], mc["atr15"], mc["hourly_atr"], cfg
                        )
                        if stop_res["valid"]:
                            pos = PositionState(
                                symbol=sym,
                                tranches=(TrancheFill(fill.qty, fill.price, "MIS", ts),),
                                initial_stop=stop_res["stop_price"],
                                current_stop=stop_res["stop_price"],
                                stop_source=stop_res["stop_source"],
                                planned_full_qty=mc["planned_full_qty"],
                                initial_risk_budget=mc["risk_budget"],
                                entry_price_1=fill.price,
                                risk_per_share=fill.price - stop_res["stop_price"],
                                highest_high=float(bar["high"]),
                            )
                            tid = ledger.next_trade_id()
                            active_meta[sym] = ActiveTradeMeta(
                                trade_id=tid, symbol=sym, entry_ts=ts,
                                initial_stop=stop_res["stop_price"], stop_source=stop_res["stop_source"],
                                risk_per_share=pos.risk_per_share, planned_full_risk_inr=mc["planned_full_risk"],
                                regime_at_entry=reg.label, entry_score=mc["entry_score"],
                                score_zone=mc["score_zone"], pattern=mc["pattern"] or "none",
                                pattern_quality=mc["pattern_quality"], bound_constraint=mc["bound_constraint"],
                                qty_peak=fill.qty, total_buy_qty=fill.qty,
                                total_buy_notional=fill.qty * fill.price,
                                fees=fill.fees, slippage_cost=fill.slippage_cost,
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
            if st.position is not None and float(bar["low"]) <= st.position.current_stop:
                pos = st.position
                prod = "CNC" if pos.carried else "MIS"
                fill, _ = broker.execute_bar_fill(
                    sym, "SELL", pos.total_qty, prod, ts,
                    float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["volume"]),
                    is_stop=True, stop_price=pos.current_stop, reason="stop_hit",
                )
                if fill is not None:
                    ledger.apply_fill(fill, next_td)
                    meta = active_meta.pop(sym)
                    meta.total_sell_qty += fill.qty
                    meta.total_sell_notional += fill.qty * fill.price
                    meta.fees += fill.fees
                    meta.slippage_cost += fill.slippage_cost
                    if float(bar["open"]) < pos.current_stop:
                        meta.gap_loss_flag = True
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
                fill, _ = broker.execute_bar_fill(
                    sym, "SELL", pos.total_qty, "MIS", ts,
                    float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["volume"]),
                    reason="mis_squareoff",
                )
                if fill is not None:
                    ledger.apply_fill(fill, next_td)
                    meta = active_meta.pop(sym)
                    meta.total_sell_qty += fill.qty
                    meta.total_sell_notional += fill.qty * fill.price
                    meta.fees += fill.fees
                    meta.slippage_cost += fill.slippage_cost
                    ledger.close_trade(meta, ts, "mis_squareoff", 1)
                    states[sym] = SymbolState(symbol=sym, lifecycle=LifecycleState.IDLE, entries_today=st.entries_today)
                continue

            # 4. Entry signal generation (inside entry window, IDLE/ARMED)
            if (
                st.position is None
                and sym not in pending
                and cfg.trigger.window.entry_from <= t_str <= cfg.trigger.window.entry_until
            ):
                d_row = daily_by_avail.get(sym, {}).get(cur_date)
                p_row = p_rows.get(sym)
                if d_row and p_row and p_row["eligible"] and d_row.get("above_slow_dma") and reg.label != "LOW":
                    h_done = hourly_map[sym].filter(pl.col("bar_end") <= ts)
                    m15_done = m15_map[sym].filter(pl.col("bar_end") <= ts)
                    if not h_done.is_empty() and not m15_done.is_empty():
                        h_last = h_done.tail(1).to_dicts()[0]
                        m15_last = m15_done.tail(1).to_dicts()[0]
                        if h_last.get("leg_valid") and h_last.get("pullback_low") and m15_last.get("atr"):
                            atr15 = float(m15_last["atr"])
                            flag_hi = find_flag_high(m15_done, atr15, cfg)
                            ref_hi = flag_hi or float(h_last["leg_high"])
                            tl, zf, zc = compute_entry_zone(ref_hi, atr15, cfg)
                            close_px = float(bar["close"])
                            if close_px > tl and close_px >= zf:
                                d_hist = daily_map[sym].filter(pl.col("avail_date") <= cur_date)
                                pat_name, pat_q = evaluate_patterns(d_hist, cfg.score.patterns)
                                h_atr = float(h_last["atr"] or atr15 * 2.0)
                                ext_h = (close_px - float(h_last[f"ema{cfg.trend.ribbon_emas[-1]}"] or close_px)) / max(h_atr, 1e-6)
                                rng_b = float(bar["high"]) - float(bar["low"])
                                c_pos = (close_px - float(bar["low"])) / rng_b if rng_b > 0 else 0.5
                                ctx = {
                                    "eligible": True, "above_200dma": True, "regime_label": reg.label,
                                    "adtv_cr": float(p_row["adtv_cr"] or 0.0), "atr_pct": float(p_row["atr_pct"] or 0.0),
                                    "dma_stack_full": bool(d_row.get("dma_stack_full")),
                                    "dma_stack_partial": bool(d_row.get("dma_stack_partial")),
                                    "slow_dma_rising": bool(d_row.get("slow_dma_rising")),
                                    "rs_pct": p_row.get("rs_pct"),
                                    "pct_below_52w_high": d_row.get("pct_below_52w_high"),
                                    "ribbon_stack_ok": bool(h_last.get("rib_stack_ok")),
                                    "ribbon_fanning": bool(h_last.get("rib_fanning")),
                                    "pattern_quality": pat_q,
                                    "depth_hatr": h_last.get("pullback_depth_hatr"),
                                    "depth_leg_frac": 0.25,
                                    "hourly_closes_below_ema20": 0 if not h_last.get("close_below_slow_ema") else 1,
                                    "vol_contraction_ratio": 0.7,
                                    "range_ratio_3bar": float(h_last.get("range_ratio") or 1.0),
                                    "rvol_pace": float(bar.get("rvol_pace") or 1.5),
                                    "close_in_bar_range": c_pos,
                                    "extension_hatr": ext_h,
                                    "gap_daily_atr": 0.5,
                                    "stock_er": d_row.get("er"),
                                }
                                veto_ok, v_reasons = evaluate_vetoes(ctx, cfg)
                                sc, zone, z_fac = compute_entry_score(ctx, cfg)
                                if veto_ok and zone != "none":
                                    stop_res = stop_rule.compute(close_px, float(h_last["pullback_low"]), atr15, h_atr, cfg)
                                    if stop_res["valid"]:
                                        throt = is_throttle_active(ledger.closed_money_rs, False, cfg)
                                        adv20 = float(p_row["adtv_cr"] or 20.0) * 1e7 / max(close_px, 1.0)
                                        sz = sizer.size(day_start_eq, close_px, stop_res["stop_price"], adv20, reg.multiplier, 0.5 if throt else 1.0, z_fac, cfg)
                                        open_pos_cnt = sum(1 for s in states.values() if s.position is not None)
                                        heat = sum(open_risk(s.position.tranches, s.position.current_stop) for s in states.values() if s.position is not None)
                                        snap_p = PortfolioSnapshot(day_start_eq, ledger.cash, open_pos_cnt, heat, 0.0, 0.0, entries_today_port, {}, throt)
                                        p_ok, _ = portfolio_allows_entry(st, snap_p, p_row.get("sector"), 0.0, sz["tranche1_qty"] * sz["risk_per_share"], cfg)
                                        if p_ok and sz["tranche1_qty"] > 0:
                                            pending[sym] = PendingOrder(
                                                symbol=sym, side="BUY", qty=sz["tranche1_qty"],
                                                product="MIS", reason="entry_signal",
                                                bars_left=cfg.costs.slippage.max_fill_bars, is_entry=True,
                                                meta_ctx={
                                                    "swing_low": float(h_last["pullback_low"]), "atr15": atr15,
                                                    "hourly_atr": h_atr, "planned_full_qty": sz["planned_full_qty"],
                                                    "risk_budget": sz["risk_budget_inr"], "planned_full_risk": sz["planned_full_risk_inr"],
                                                    "entry_score": sc, "score_zone": zone,
                                                    "pattern": pat_name, "pattern_quality": pat_q,
                                                    "bound_constraint": sz["bound_constraint"],
                                                },
                                            )

        # End-of-day equity snapshot
        mtm = ledger.cash + sum(
            states[s].position.total_qty * last_prices.get(s, states[s].position.avg_entry)
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

    n_trades = len(ledger.trades)
    wins = sum(1 for t in ledger.trades if t.net_pnl > 0)
    win_rate = (wins / n_trades * 100.0) if n_trades else 0.0
    exp_r = (sum(t.money_r for t in ledger.trades) / n_trades) if n_trades else 0.0
    cap_bound = sum(1 for t in ledger.trades if t.bound_constraint == "cap")
    summary = (
        f"{LIMITATIONS_HEADER}\n"
        f"Run ID: {run_id}\n"
        f"Trades: {n_trades} | Win rate: {win_rate:.1f}% | Expectancy: {exp_r:.3f}R | "
        f"25% cap bound: {cap_bound}/{n_trades}\n"
    )
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")
    return BacktestResult(run_id, out_dir, trades_df, equity_df, summary)