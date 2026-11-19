"""15m flag trigger level, entry zone, and 5m trigger evaluation (Section 7.4)."""

from __future__ import annotations

from typing import Any

import polars as pl

from tfalgo.config import AppConfig
from tfalgo.strategy.base import TRIGGER_RULES, SymbolState, TriggerRule, round_up_tick


def find_flag_high(m15: pl.DataFrame, atr15: float, cfg: AppConfig) -> float | None:
    """Most recent 4-8 bar 15m consolidation with total range <= 2.0 * ATR15."""
    f = cfg.setup.flag
    if m15.is_empty() or atr15 <= 0:
        return None
    for length in range(f.max_bars, f.min_bars - 1, -1):
        if m15.height < length:
            continue
        win = m15.tail(length)
        hi = float(win["high"].max())  # type: ignore[arg-type]
        lo = float(win["low"].min())   # type: ignore[arg-type]
        if (hi - lo) <= f.max_range_atr15 * atr15:
            return hi
    return None


def compute_entry_zone(
    flag_or_pb_high: float,
    atr15: float,
    cfg: AppConfig,
) -> tuple[float, float, float]:
    """Return (trigger_level, zone_floor, zone_ceiling) rounded UP to tick."""
    tick = cfg.session.tick_size
    ez = cfg.buffers.entry_zone
    trigger_level = round_up_tick(flag_or_pb_high + tick, tick)
    zone_floor = round_up_tick(trigger_level + ez.confirm_atr15 * atr15, tick)
    zone_ceiling = round_up_tick(trigger_level + ez.chase_atr15 * atr15, tick)
    return trigger_level, zone_floor, zone_ceiling


@TRIGGER_RULES.register("pullback_flag")
class PullbackFlagTrigger(TriggerRule):
    name = "pullback_flag"

    def check(self, state: SymbolState, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
        bar_time = ctx.get("bar_time_str", "09:30")
        w = cfg.trigger.window
        if not (w.entry_from <= bar_time <= w.entry_until):
            return {"fired": False, "reason": "outside_entry_window"}

        close = float(ctx["bar_close"])
        tl = state.trigger_level
        zf = state.zone_floor
        if tl is None or zf is None:
            return {"fired": False, "reason": "no_trigger_level"}

        if close > tl and close >= zf:
            return {"fired": True, "reason": None}
        return {"fired": False, "reason": "below_entry_zone"}