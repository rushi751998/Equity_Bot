"""Portfolio accounting, trade log, and equity tracking (Section 8.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from tfalgo.execution.broker_iface import ExecutedFill
from tfalgo.strategy.base import PortfolioSnapshot


@dataclass
class TradeRecord:
    trade_id: int
    symbol: str
    entry_ts: datetime
    exit_ts: datetime
    product_path: str
    tranche_fills: int
    avg_entry: float
    avg_exit: float
    qty_peak: int
    initial_stop: float
    stop_source: str
    risk_per_share: float
    planned_full_risk_inr: float
    price_r_max: float
    mae_r: float
    mfe_r: float
    gross_pnl: float
    fees: float
    slippage_cost: float
    net_pnl: float
    money_r: float
    exit_reason: str
    regime_at_entry: str
    entry_score: float
    score_zone: str
    pattern: str
    pattern_quality: float
    add_scores: str
    hold_score_min: int
    time_stop_flag: bool
    bound_constraint: str
    hold_days: int
    gap_loss_flag: bool
    stop_trail: str = ""


@dataclass
class ActiveTradeMeta:
    trade_id: int
    symbol: str
    entry_ts: datetime
    initial_stop: float
    stop_source: str
    risk_per_share: float
    planned_full_risk_inr: float
    regime_at_entry: str
    entry_score: float
    score_zone: str
    pattern: str
    pattern_quality: float
    bound_constraint: str
    product_path: str = "MIS"
    tranche_fills: int = 1
    qty_peak: int = 0
    total_buy_qty: int = 0
    total_buy_notional: float = 0.0
    total_sell_qty: int = 0
    total_sell_notional: float = 0.0
    fees: float = 0.0
    slippage_cost: float = 0.0
    price_r_max: float = 0.0
    mae_r: float = 0.0
    mfe_r: float = 0.0
    add_scores: list[float] = field(default_factory=list)
    hold_score_min: int = 100
    time_stop_flag: bool = False
    gap_loss_flag: bool = False
    stop_trail: list[tuple[str, float]] = field(default_factory=list)


class PortfolioLedger:
    def __init__(self, initial_cash: float, sale_proceeds: str = "immediate") -> None:
        self.cash = float(initial_cash)
        self.sale_proceeds = sale_proceeds
        self.pending_t1: dict[date, float] = {}
        self.trades: list[TradeRecord] = []
        self.fills: list[dict[str, Any]] = []
        self.signals: list[dict[str, Any]] = []
        self.closed_money_rs: list[float] = []
        self._next_trade_id = 1

    def settle_t1(self, today: date) -> None:
        for d in [k for k in self.pending_t1 if k <= today]:
            self.cash += self.pending_t1.pop(d)

    def apply_fill(self, fill: ExecutedFill, next_trading_day: date | None = None) -> None:
        notional = fill.qty * fill.price
        if fill.side == "BUY":
            self.cash -= (notional + fill.fees)
        else:
            net_proceeds = notional - fill.fees
            if self.sale_proceeds == "t_plus_1" and next_trading_day is not None:
                self.pending_t1[next_trading_day] = self.pending_t1.get(next_trading_day, 0.0) + net_proceeds
            else:
                self.cash += net_proceeds

        self.fills.append({
            "ts": fill.ts.isoformat(),
            "symbol": fill.symbol,
            "side": fill.side,
            "qty": fill.qty,
            "price": fill.price,
            "product": fill.product,
            "fees": round(fill.fees, 4),
            "slippage_cost": round(fill.slippage_cost, 4),
            "reason": fill.reason,
        })

    def next_trade_id(self) -> int:
        tid = self._next_trade_id
        self._next_trade_id += 1
        return tid

    def close_trade(self, meta: ActiveTradeMeta, exit_ts: datetime, exit_reason: str, hold_days: int) -> None:
        avg_entry = meta.total_buy_notional / meta.total_buy_qty if meta.total_buy_qty > 0 else 0.0
        avg_exit = meta.total_sell_notional / meta.total_sell_qty if meta.total_sell_qty > 0 else 0.0
        gross_pnl = meta.total_sell_notional - meta.total_buy_notional
        net_pnl = gross_pnl - meta.fees
        money_r = net_pnl / meta.planned_full_risk_inr if meta.planned_full_risk_inr > 0 else 0.0
        self.closed_money_rs.append(money_r)
        self.trades.append(TradeRecord(
            trade_id=meta.trade_id,
            symbol=meta.symbol,
            entry_ts=meta.entry_ts,
            exit_ts=exit_ts,
            product_path=meta.product_path,
            tranche_fills=meta.tranche_fills,
            avg_entry=round(avg_entry, 4),
            avg_exit=round(avg_exit, 4),
            qty_peak=meta.qty_peak,
            initial_stop=meta.initial_stop,
            stop_source=meta.stop_source,
            risk_per_share=round(meta.risk_per_share, 4),
            planned_full_risk_inr=round(meta.planned_full_risk_inr, 2),
            price_r_max=round(meta.price_r_max, 4),
            mae_r=round(meta.mae_r, 4),
            mfe_r=round(meta.mfe_r, 4),
            gross_pnl=round(gross_pnl, 2),
            fees=round(meta.fees, 2),
            slippage_cost=round(meta.slippage_cost, 2),
            net_pnl=round(net_pnl, 2),
            money_r=round(money_r, 4),
            exit_reason=exit_reason,
            regime_at_entry=meta.regime_at_entry,
            entry_score=round(meta.entry_score, 2),
            score_zone=meta.score_zone,
            pattern=meta.pattern,
            pattern_quality=round(meta.pattern_quality, 4),
            add_scores=",".join(f"{s:.1f}" for s in meta.add_scores),
            hold_score_min=meta.hold_score_min,
            time_stop_flag=meta.time_stop_flag,
            bound_constraint=meta.bound_constraint,
            hold_days=hold_days,
            gap_loss_flag=meta.gap_loss_flag,
            stop_trail=";".join(f"{t}@{p:.2f}" for t, p in meta.stop_trail),
        ))