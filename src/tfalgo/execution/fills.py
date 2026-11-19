"""Fill and slippage models (Section 8.2)."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from tfalgo.config import SlippageConfig
from tfalgo.registry import Registry
from tfalgo.strategy.base import round_down_tick, round_up_tick


@dataclass(frozen=True)
class FillResult:
    filled_qty: int
    fill_price: float
    slippage_per_share: float
    remaining_qty: int
    skipped_reason: str | None = None


class FillModel(ABC):
    name: str = ""

    @abstractmethod
    def fill_order(
        self,
        side: Literal["BUY", "SELL"],
        qty: int,
        bar_open: float,
        bar_high: float,
        bar_low: float,
        bar_volume: float,
        bar_minute_of_day: int,
        session_open_minute: int,
        no_fill_first_minutes: int,
        tick_size: float,
        cfg: SlippageConfig,
        is_stop: bool = False,
        stop_price: float | None = None,
    ) -> FillResult: ...


FILLS: Registry[FillModel] = Registry("fill model")


@FILLS.register("next_open_slippage")
class NextOpenSlippageFillModel(FillModel):
    name = "next_open_slippage"

    def fill_order(
        self,
        side: Literal["BUY", "SELL"],
        qty: int,
        bar_open: float,
        bar_high: float,
        bar_low: float,
        bar_volume: float,
        bar_minute_of_day: int,
        session_open_minute: int,
        no_fill_first_minutes: int,
        tick_size: float,
        cfg: SlippageConfig,
        is_stop: bool = False,
        stop_price: float | None = None,
    ) -> FillResult:
        if qty <= 0:
            return FillResult(0, 0.0, 0.0, 0, "zero_qty")

        if not is_stop and (bar_minute_of_day - session_open_minute) < no_fill_first_minutes:
            return FillResult(0, 0.0, 0.0, qty, "no_fill_first_minutes")

        if is_stop:
            fill_qty = qty
        else:
            max_vol_qty = math.floor(cfg.max_participation * bar_volume) if bar_volume > 0 else 0
            fill_qty = min(qty, max_vol_qty)
            if fill_qty <= 0:
                return FillResult(0, 0.0, 0.0, qty, "participation_cap_zero")

        part = (fill_qty / bar_volume) if bar_volume > 0 else 0.0
        spread_bps = ((bar_high - bar_low) / bar_open * 10_000.0 * 0.25) if bar_open > 0 else 0.0
        slip_bps = max(cfg.min_bps, 0.5 * spread_bps) + cfg.impact_k_bps * math.sqrt(max(0.0, part))
        if is_stop:
            slip_bps *= cfg.stop_multiplier

        base_px = min(bar_open, stop_price) if (is_stop and stop_price is not None) else bar_open
        if side == "BUY":
            raw_px = base_px * (1.0 + slip_bps / 10_000.0)
            fill_px = round_up_tick(raw_px, tick_size)
        else:
            raw_px = base_px * (1.0 - slip_bps / 10_000.0)
            fill_px = round_down_tick(raw_px, tick_size)

        return FillResult(
            filled_qty=fill_qty,
            fill_price=fill_px,
            slippage_per_share=abs(fill_px - base_px),
            remaining_qty=qty - fill_qty,
        )