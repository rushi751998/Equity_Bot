"""Daily market regime score (computed after close, applied next session)."""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from tfalgo.config import AppConfig
from tfalgo.registry import Registry

log = logging.getLogger(__name__)
RegimeLabel = Literal["HIGH", "MEDIUM", "LOW"]

_WARNED_MISSING = False


@dataclass(frozen=True)
class RegimeSnapshot:
    """Inputs for one session's regime evaluation (all from data <= D-1)."""

    index_close: float
    index_sma50: float | None
    index_sma200: float | None
    breadth_above_50dma_pct: float | None
    net_new_highs_minus_lows: int | None
    vix_close: float | None = None
    vix_sma20: float | None = None
    dist_days_10d: int | None = None  # None when index volume is 0 / unavailable
    chop_breakout_pt: int = 0
    chop_index_er_pt: int = 0


@dataclass(frozen=True)
class RegimeResult:
    label: RegimeLabel
    multiplier: float
    score: int
    max_score: int
    active_components: tuple[str, ...]


class RegimeComponent(ABC):
    name: str = ""
    max_positive_points: int = 1

    @abstractmethod
    def is_available(self, snap: RegimeSnapshot, cfg: AppConfig) -> bool: ...

    @abstractmethod
    def points(self, snap: RegimeSnapshot, cfg: AppConfig) -> int: ...


REGIME_COMPONENTS: Registry[RegimeComponent] = Registry("regime component")


@REGIME_COMPONENTS.register("index_above_50dma")
class IndexAbove50Dma(RegimeComponent):
    name = "index_above_50dma"
    max_positive_points = 1

    def is_available(self, snap: RegimeSnapshot, cfg: AppConfig) -> bool:
        return snap.index_sma50 is not None

    def points(self, snap: RegimeSnapshot, cfg: AppConfig) -> int:
        return 1 if snap.index_sma50 is not None and snap.index_close > snap.index_sma50 else 0


@REGIME_COMPONENTS.register("index_above_200dma")
class IndexAbove200Dma(RegimeComponent):
    name = "index_above_200dma"
    max_positive_points = 1

    def is_available(self, snap: RegimeSnapshot, cfg: AppConfig) -> bool:
        return snap.index_sma200 is not None

    def points(self, snap: RegimeSnapshot, cfg: AppConfig) -> int:
        return 1 if snap.index_sma200 is not None and snap.index_close > snap.index_sma200 else 0


@REGIME_COMPONENTS.register("breadth_above_50dma")
class BreadthAbove50Dma(RegimeComponent):
    name = "breadth_above_50dma"
    max_positive_points = 1

    def is_available(self, snap: RegimeSnapshot, cfg: AppConfig) -> bool:
        return snap.breadth_above_50dma_pct is not None

    def points(self, snap: RegimeSnapshot, cfg: AppConfig) -> int:
        return 1 if (snap.breadth_above_50dma_pct or 0.0) > cfg.regime.breadth_min_pct else 0


@REGIME_COMPONENTS.register("net_new_highs_minus_lows")
class NetNewHighsMinusLows(RegimeComponent):
    name = "net_new_highs_minus_lows"
    max_positive_points = 1

    def is_available(self, snap: RegimeSnapshot, cfg: AppConfig) -> bool:
        return snap.net_new_highs_minus_lows is not None

    def points(self, snap: RegimeSnapshot, cfg: AppConfig) -> int:
        return 1 if (snap.net_new_highs_minus_lows or 0) > 0 else 0


@REGIME_COMPONENTS.register("vix_below_avg")
class VixBelowAvg(RegimeComponent):
    name = "vix_below_avg"
    max_positive_points = 1

    def is_available(self, snap: RegimeSnapshot, cfg: AppConfig) -> bool:
        return snap.vix_close is not None and snap.vix_sma20 is not None

    def points(self, snap: RegimeSnapshot, cfg: AppConfig) -> int:
        return 1 if snap.vix_close is not None and snap.vix_sma20 is not None and snap.vix_close < snap.vix_sma20 else 0


@REGIME_COMPONENTS.register("distribution_days")
class DistributionDays(RegimeComponent):
    name = "distribution_days"
    max_positive_points = 0  # penalty-only component (-1 or 0)

    def is_available(self, snap: RegimeSnapshot, cfg: AppConfig) -> bool:
        return snap.dist_days_10d is not None

    def points(self, snap: RegimeSnapshot, cfg: AppConfig) -> int:
        return -1 if (snap.dist_days_10d or 0) >= cfg.regime.dist_day_min_count else 0


def classify_regime(
    snap: RegimeSnapshot,
    cfg: AppConfig,
    components: list[str] | None = None,
) -> RegimeResult:
    """Compute regime score, rescale thresholds to active max, and return label + multiplier."""
    global _WARNED_MISSING
    if not cfg.regime.enabled:
        return RegimeResult("HIGH", cfg.regime.multipliers["HIGH"], 0, 0, ())

    names = components or [
        "index_above_50dma",
        "index_above_200dma",
        "breadth_above_50dma",
        "net_new_highs_minus_lows",
        "vix_below_avg",
        "distribution_days",
    ]

    score = 0
    max_score = 0
    active: list[str] = []
    missing: list[str] = []

    for name in names:
        comp = REGIME_COMPONENTS.get(name)()
        if comp.is_available(snap, cfg):
            score += comp.points(snap, cfg)
            max_score += comp.max_positive_points
            active.append(name)
        else:
            missing.append(name)

    if missing and not _WARNED_MISSING:
        log.warning("Regime components disabled due to missing data (%s); rescaling thresholds.", ", ".join(missing))
        _WARNED_MISSING = True

    if cfg.chop.breakout_success.enabled:
        score += snap.chop_breakout_pt
        max_score += 1
        active.append("chop_breakout_success")
    if cfg.chop.efficiency.enabled:
        score += snap.chop_index_er_pt
        max_score += 1
        active.append("chop_efficiency")

    if max_score <= 0:
        return RegimeResult("LOW", cfg.regime.multipliers["LOW"], score, 0, tuple(active))

    high_thr = math.ceil(cfg.regime.high_frac * max_score)
    med_thr = math.ceil(cfg.regime.medium_frac * max_score)

    if score >= high_thr:
        label: RegimeLabel = "HIGH"
    elif score >= med_thr:
        label = "MEDIUM"
    else:
        label = "LOW"
    return RegimeResult(label, cfg.regime.multipliers[label], score, max_score, tuple(active))