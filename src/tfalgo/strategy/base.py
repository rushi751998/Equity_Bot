"""Strategy ABCs, registries, tick rounding, and pure state dataclasses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import StrEnum
from typing import Any, Literal

from tfalgo.config import AppConfig
from tfalgo.registry import Registry


def round_up_tick(price: float, tick: float = 0.05) -> float:
    """Round price UP to nearest tick (used for buy / trigger prices)."""
    d_tick = Decimal(str(tick))
    d_val = Decimal(f"{price:.8f}")
    steps = (d_val / d_tick).to_integral_value(rounding=ROUND_CEILING)
    return float(steps * d_tick)


def round_down_tick(price: float, tick: float = 0.05) -> float:
    """Round price DOWN to nearest tick (used for sell / stop prices)."""
    d_tick = Decimal(str(tick))
    d_val = Decimal(f"{price:.8f}")
    steps = (d_val / d_tick).to_integral_value(rounding=ROUND_FLOOR)
    return float(steps * d_tick)


class LifecycleState(StrEnum):
    IDLE = "IDLE"
    WATCHING = "WATCHING"
    ARMED = "ARMED"
    ENTRY_PENDING = "ENTRY_PENDING"
    OPEN_MIS = "OPEN_MIS"
    CARRIED_CNC = "CARRIED_CNC"
    EXITED = "EXITED"
    COOLDOWN = "COOLDOWN"


@dataclass(frozen=True)
class TrancheFill:
    qty: int
    entry_price: float
    product: Literal["MIS", "CNC"]
    fill_ts: datetime


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: int
    order_type: Literal["MARKET_NEXT_OPEN", "LIMIT", "CONVERT_CNC"] = "MARKET_NEXT_OPEN"
    limit_price: float | None = None
    product: Literal["MIS", "CNC"] = "MIS"
    reason: str = ""
    tag: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PositionState:
    symbol: str
    tranches: tuple[TrancheFill, ...]
    initial_stop: float
    current_stop: float
    stop_source: str
    planned_full_qty: int
    initial_risk_budget: float
    entry_price_1: float
    risk_per_share: float
    max_price_r: float = 0.0
    ladder_base_qty: int = 0
    ladder_stage: int = 0
    carried: bool = False
    days_held: int = 0
    days_since_new_high: int = 0
    highest_daily_close: float = 0.0
    highest_high: float = 0.0
    hourly_below_ema20_streak: int = 0
    entry_bar_count: int = 0
    side: Literal["LONG", "SHORT"] = "LONG"

    @property
    def total_qty(self) -> int:
        return sum(t.qty for t in self.tranches)

    @property
    def avg_entry(self) -> float:
        q = self.total_qty
        return sum(t.qty * t.entry_price for t in self.tranches) / q if q > 0 else 0.0

    def price_r(self, price: float) -> float:
        return (price - self.entry_price_1) / self.risk_per_share if self.risk_per_share > 0 else 0.0


@dataclass(frozen=True)
class SymbolState:
    symbol: str
    lifecycle: LifecycleState = LifecycleState.IDLE
    position: PositionState | None = None
    trigger_level: float | None = None
    zone_floor: float | None = None
    zone_ceiling: float | None = None
    retest_bars_left: int = 0
    cooldown_days_left: int = 0
    entries_today: int = 0
    entry_score: float = 0.0
    score_zone: str = "none"


@dataclass(frozen=True)
class PortfolioSnapshot:
    equity: float
    cash: float
    open_positions: int
    open_heat_inr: float
    daily_pnl_pct: float
    weekly_pnl_pct: float
    entries_today: int
    sector_counts: dict[str, int] = field(default_factory=dict)
    throttle_active: bool = False


class Strategy(ABC):
    name: str = ""

    @abstractmethod
    def on_bar(self, state: SymbolState, ctx: dict[str, Any],
               portfolio: PortfolioSnapshot, cfg: AppConfig) -> tuple[SymbolState, list[OrderIntent]]: ...


class Veto(ABC):
    name: str = ""

    @abstractmethod
    def check(self, ctx: dict[str, Any], cfg: AppConfig) -> tuple[bool, str | None]:
        """Return (passed, fail_reason)."""


class ScoreBlock(ABC):
    name: str = ""
    max_points: float = 0.0

    @abstractmethod
    def score(self, ctx: dict[str, Any], cfg: AppConfig) -> float: ...


class SetupRule(ABC):
    name: str = ""

    @abstractmethod
    def evaluate(self, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]: ...


class TriggerRule(ABC):
    name: str = ""

    @abstractmethod
    def check(self, state: SymbolState, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]: ...


class StopRule(ABC):
    name: str = ""

    @abstractmethod
    def compute(self, entry_price: float, swing_low: float, atr15: float,
                hourly_atr14: float, cfg: AppConfig) -> dict[str, Any]: ...


class SizingRule(ABC):
    name: str = ""

    @abstractmethod
    def size(self, equity: float, entry_price: float, stop_price: float, adv20: float,
             regime_mult: float, throttle_mult: float, zone_factor: float,
             cfg: AppConfig) -> dict[str, Any]: ...


class PyramidRule(ABC):
    name: str = ""

    @abstractmethod
    def triggered(self, ctx: dict[str, Any], cfg: AppConfig) -> bool: ...


class ExitRule(ABC):
    name: str = ""

    @abstractmethod
    def evaluate(self, pos: PositionState, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]: ...


STRATEGIES: Registry[Strategy] = Registry("strategy")
VETOES: Registry[Veto] = Registry("veto")
SCORE_BLOCKS: Registry[ScoreBlock] = Registry("score block")
SETUP_RULES: Registry[SetupRule] = Registry("setup rule")
TRIGGER_RULES: Registry[TriggerRule] = Registry("trigger rule")
STOP_RULES: Registry[StopRule] = Registry("stop rule")
SIZING_RULES: Registry[SizingRule] = Registry("sizing rule")
PYRAMID_RULES: Registry[PyramidRule] = Registry("pyramid rule")
EXIT_RULES: Registry[ExitRule] = Registry("exit rule")