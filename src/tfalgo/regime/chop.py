"""Chop controls A1-A4 (individually switchable via AppConfig.chop)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from tfalgo.config import AppConfig
from tfalgo.registry import Registry


@dataclass(frozen=True)
class ShadowEvent:
    """Shadow breakout signal tracked for A1 breakout-success regime feedback."""

    symbol: str
    signal_date: date
    entry_price: float
    stop_price: float
    resolved_date: date | None = None
    success: bool | None = None


class ChopControl(ABC):
    """Base interface for switchable chop controls."""

    name: str = ""

    @abstractmethod
    def is_enabled(self, cfg: AppConfig) -> bool: ...


CHOP_CONTROLS: Registry[ChopControl] = Registry("chop control")


@CHOP_CONTROLS.register("breakout_success")
class BreakoutSuccessControl(ChopControl):
    name = "breakout_success"

    def is_enabled(self, cfg: AppConfig) -> bool:
        return cfg.chop.breakout_success.enabled


@CHOP_CONTROLS.register("efficiency")
class EfficiencyControl(ChopControl):
    name = "efficiency"

    def is_enabled(self, cfg: AppConfig) -> bool:
        return cfg.chop.efficiency.enabled


@CHOP_CONTROLS.register("probe_sizing")
class ProbeSizingControl(ChopControl):
    name = "probe_sizing"

    def is_enabled(self, cfg: AppConfig) -> bool:
        return cfg.regime.enabled


@CHOP_CONTROLS.register("time_stop")
class TimeStopControl(ChopControl):
    name = "time_stop"

    def is_enabled(self, cfg: AppConfig) -> bool:
        return cfg.chop.time_stop.enabled


def breakout_success_regime_points(
    events: list[ShadowEvent],
    as_of_date: date,
    trading_dates: list[date],
    cfg: AppConfig,
) -> tuple[int, float | None, int]:
    """A1: compute regime point (+1 / 0 / -1) using ONLY events resolved <= as_of_date."""
    c = cfg.chop.breakout_success
    if not c.enabled:
        return 0, None, 0

    recent_dates = set(d for d in trading_dates if d <= as_of_date)
    if len(recent_dates) > c.lookback_days:
        sorted_dates = sorted(recent_dates)[-c.lookback_days :]
        recent_dates = set(sorted_dates)

    resolved = [
        e
        for e in events
        if e.resolved_date is not None
        and e.resolved_date <= as_of_date
        and e.signal_date in recent_dates
        and e.success is not None
    ]
    n = len(resolved)
    if n < c.min_events:
        return 0, None, n

    rate = sum(1 for e in resolved if e.success) / n
    if rate >= c.high_rate:
        return 1, rate, n
    if rate < c.low_rate:
        return -1, rate, n
    return 0, rate, n


def index_efficiency_points(index_er: float | None, cfg: AppConfig) -> int:
    """A2 regime point: +1 if index ER >= index_min."""
    c = cfg.chop.efficiency
    if not c.enabled or index_er is None:
        return 0
    return 1 if index_er >= c.index_min else 0


def stock_efficiency_penalty(stock_er: float | None, cfg: AppConfig) -> float:
    """A2 stock entry-score penalty: -4 if stock ER < stock_min."""
    c = cfg.chop.efficiency
    if not c.enabled or stock_er is None:
        return 0.0
    return -4.0 if stock_er < c.stock_min else 0.0


def check_time_stop(
    days_held: int,
    max_price_r: float,
    days_since_new_high: int,
    cfg: AppConfig,
) -> tuple[bool, str | None]:
    """A4 time stop for CNC positions."""
    c = cfg.chop.time_stop
    if not c.enabled:
        return False, None
    if days_held >= c.max_days_to_reach_r and max_price_r < c.progress_r:
        return True, "time_stop_no_progress"
    if days_since_new_high >= c.stall_days and max_price_r < c.stall_exit_below_r:
        return True, "time_stop_stall"
    return False, None