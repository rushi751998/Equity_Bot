"""Simulated broker adapter combining FillModel + CostModel."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from tfalgo.config import AppConfig
from tfalgo.execution.broker_iface import BrokerAdapter, ExecutedFill
from tfalgo.execution.costs import COSTS, CostModel, FlatPctCostModel, ZerodhaCostModel
from tfalgo.execution.fills import FILLS, FillModel


class SimBroker(BrokerAdapter):
    def __init__(self, cfg: AppConfig, cost_model: CostModel | None = None, fill_model: FillModel | None = None) -> None:
        self.cfg = cfg
        if cost_model is not None:
            self.cost_model = cost_model
        elif cfg.costs.flat_cost_pct is not None:
            self.cost_model = FlatPctCostModel(cfg.costs.flat_cost_pct)
        else:
            self.cost_model = ZerodhaCostModel(cfg.costs.broker_file)
        self.fill_model = fill_model or FILLS.get("next_open_slippage")()
        self._dp_charged: set[tuple[str, date]] = set()
        self._open_min = cfg.session.open.hour * 60 + cfg.session.open.minute

    def execute_bar_fill(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: int,
        product: Literal["MIS", "CNC"],
        ts: datetime,
        bar_open: float,
        bar_high: float,
        bar_low: float,
        bar_volume: float,
        is_stop: bool = False,
        stop_price: float | None = None,
        reason: str = "",
    ) -> tuple[ExecutedFill | None, int]:
        bar_min = ts.hour * 60 + ts.minute
        res = self.fill_model.fill_order(
            side=side,
            qty=qty,
            bar_open=bar_open,
            bar_high=bar_high,
            bar_low=bar_low,
            bar_volume=bar_volume,
            bar_minute_of_day=bar_min,
            session_open_minute=self._open_min,
            no_fill_first_minutes=self.cfg.trigger.no_fill_first_minutes,
            tick_size=self.cfg.session.tick_size,
            cfg=self.cfg.costs.slippage,
            is_stop=is_stop,
            stop_price=stop_price,
        )
        if res.filled_qty <= 0:
            return None, res.remaining_qty

        charge_dp = False
        if product == "CNC" and side == "SELL":
            key = (symbol, ts.date())
            if key not in self._dp_charged:
                charge_dp = True
                self._dp_charged.add(key)

        notional = res.filled_qty * res.fill_price
        fees = self.cost_model.compute(side, product, notional, charge_dp=charge_dp)
        slip_cost = res.filled_qty * res.slippage_per_share
        return ExecutedFill(
            symbol=symbol,
            side=side,
            qty=res.filled_qty,
            price=res.fill_price,
            product=product,
            ts=ts,
            fees=fees,
            slippage_cost=slip_cost,
            reason=reason,
        ), res.remaining_qty