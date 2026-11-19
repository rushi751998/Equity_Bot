"""Pydantic-validated configuration.

Phase 1 covers run/session/capital/data/storage/quality. Later phases extend `AppConfig`
with strategy, costs, portfolio, etc. (see the spec). Unknown keys are rejected so typos
in YAML fail loudly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Timeframe = Literal["1m", "5m", "15m", "60m", "1D"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunConfig(_Base):
    start: date
    end: date
    seed: int = 42
    base_timeframe: Timeframe = "5m"
    holdout_months: int = Field(6, ge=0)
    timezone: str = "Asia/Kolkata"

    @model_validator(mode="after")
    def _order(self) -> RunConfig:
        if self.end < self.start:
            raise ValueError("run.end must be >= run.start")
        return self


class SessionConfig(_Base):
    open: time = time(9, 15)
    close: time = time(15, 30)
    tick_size: float = 0.05
    holidays_file: Path | None = None  # CSV with a `date` column; None => weekdays only


class CapitalConfig(_Base):
    initial: float = Field(1_000_000, gt=0)  # INR 10 lakh
    compounding: bool = True
    leverage: float = Field(1.0, gt=0)
    sale_proceeds: Literal["immediate", "t_plus_1"] = "immediate"


class CsvColumns(_Base):
    ts: str = "date"
    open: str = "open"
    high: str = "high"
    low: str = "low"
    close: str = "close"
    volume: str = "volume"


class CsvProviderConfig(_Base):
    root: Path = Path("data/raw")
    symbol_pattern: str = "{symbol}.csv"
    index_pattern: str = "{index}.csv"
    native_timeframe: Timeframe = "5m"
    # native_timeframe: Timeframe = "1m"
    index_native_timeframe: Timeframe = "1m"
    columns: CsvColumns = CsvColumns()
    naive_timestamps_tz: str | None = None  # set if files have no UTC offset
    corporate_actions_file: Path | None = None  # CSV: symbol, ex_date, type, ratio
    instruments_file: Path | None = None  # CSV: symbol, isin, exchange, sector


class DataConfig(_Base):
    provider: str = "csv"
    csv: CsvProviderConfig = CsvProviderConfig()
    symbols: list[str] = []
    indexes: list[str] = []  # e.g. NIFTY_MIDCAP_150, INDIA_VIX (optional; missing => disabled)
    retry_attempts: int = 5


class StorageConfig(_Base):
    backend: str = "sqlite"
    sqlite_path: Path = Path("data/tfalgo.db")
    output_dir: Path = Path("reports")


class QualityConfig(_Base):
    zero_volume_streak_bars: int = 12
    max_missing_bar_frac: float = 0.02  # above this -> hard failure
    outlier_bar_return: float = 0.15
    outlier_daily_return: float = 0.25
    split_jump_tolerance: float = 0.03
    split_jump_ratios: list[float] = [2, 3, 4, 5, 6, 8, 10, 1.5]
    split_jump_severity: Literal["hard", "soft"] = "hard"
    max_special_day_frac: float = 0.02  # evening/special-session days above this share => hard (likely bad timezone)


class EventsConfig(_Base):
    provider: Literal["none", "csv", "blackout"] = "none"  # v1: chart-only => none
    csv_file: Path | None = None
    blackout_days: int = 3


class HourlyConfig(_Base):
    partial_bar_policy: Literal["price_only", "include_all"] = "price_only"


class BenchmarkConfig(_Base):
    index: str = "NIFTY_50"


class IndicatorConfig(_Base):
    atr_period: int = Field(14, ge=1)
    bollinger_period: int = Field(20, ge=2)
    bollinger_k: float = 2.0
    er_period: int = Field(10, ge=1)
    rs_windows: list[int] = [63, 126, 252]
    rs_line_avg_days: int = Field(10, ge=1)
    high_lookback_days: int = Field(252, ge=2)
    slope_days: int = Field(20, ge=1)
    daily_emas: list[int] = [9, 21]
    volume_avg_days: int = Field(50, ge=1)
    swing_k: int = Field(2, ge=1)
    rvol_window_days: int = Field(20, ge=1)

    @model_validator(mode="after")
    def _rs(self) -> IndicatorConfig:
        if not self.rs_windows or any(w < 1 for w in self.rs_windows):
            raise ValueError("indicators.rs_windows must be non-empty positive ints")
        return self


class UniverseConfig(_Base):
    symbols_source: Literal["data.symbols"] = "data.symbols"
    min_adtv_cr: float = Field(20, ge=0)
    adtv_window: int = Field(20, ge=1)
    min_atr_pct: float = Field(2.5, ge=0)
    min_price: float = Field(50, ge=0)
    min_window_coverage: float = Field(0.95, ge=0, le=1)
    exclude_lists: list[str] = ["asm.csv", "gsm.csv"]
    lists_dir: Path = Path("config/universe")
    sectors_file: Path = Path("config/universe/sectors.csv")
    filters: list[str] = ["adtv", "atr_pct", "price", "coverage", "lists"]


class DailyGateConfig(_Base):
    dma: list[int] = [50, 150, 200]
    max_pct_below_52w_high: float = 25
    rs_lookback_days: int = 63

    @model_validator(mode="after")
    def _dma(self) -> DailyGateConfig:
        if len(self.dma) < 2 or sorted(self.dma) != list(self.dma):
            raise ValueError("trend.daily_gate.dma must be >=2 ascending ints")
        return self


class TrendConfig(_Base):
    ribbon_emas: list[int] = [9, 15, 20]
    ribbon_timeframe: Literal["daily", "hourly", "both"] = "hourly"
    ribbon_min_spread_pct: float = 0.15
    ribbon_slope_bars: int = Field(3, ge=1)
    daily_gate: DailyGateConfig = DailyGateConfig()

    @model_validator(mode="after")
    def _ribbon(self) -> TrendConfig:
        if len(self.ribbon_emas) != 3 or sorted(self.ribbon_emas) != list(self.ribbon_emas):
            raise ValueError("trend.ribbon_emas must be 3 ascending ints (fast, mid, slow)")
        return self


class PullbackConfig(_Base):
    min_depth_hatr: float = 0.3
    max_depth_hatr: float = 1.5
    max_depth_leg_frac: float = 0.382
    volume_contraction: float = 0.8


class TightnessConfig(_Base):
    bars: int = Field(3, ge=1)
    max_range_ratio: float = 0.85


class FlagConfig(_Base):
    min_bars: int = 4
    max_bars: int = 8
    max_range_atr15: float = 2.0


class SetupConfig(_Base):
    leg_lookback_hours: int = Field(20, ge=2)
    pullback: PullbackConfig = PullbackConfig()
    tightness: TightnessConfig = TightnessConfig()
    flag: FlagConfig = FlagConfig()


class ScoreZones(_Base):
    full: float = 75.0
    half: float = 60.0

    @model_validator(mode="after")
    def _order(self) -> ScoreZones:
        if self.half > self.full:
            raise ValueError("score.zones.half must be <= full")
        return self


class ScoreHysteresis(_Base):
    """Optional WATCHLIST-stickiness filter on the pre-trigger score (all blocks except
    trigger quality), as a % of its max. Never gates entry size (zones do)."""

    enabled: bool = False
    enter_pct: float = Field(75.0, ge=0, le=100)
    exit_below_pct: float = Field(55.0, ge=0, le=100)

    @model_validator(mode="after")
    def _order(self) -> ScoreHysteresis:
        if self.exit_below_pct > self.enter_pct:
            raise ValueError("exit_below_pct must be <= enter_pct")
        return self


class ScoreWeights(_Base):
    trend_quality: float = 25
    base_pattern: float = 20
    setup_tightness: float = 15
    trigger_quality: float = 15
    regime: float = 10
    liquidity_range: float = 5
    penalties_max: float = -10

    def block_max_total(self) -> float:
        """Sum of block maxima (90 with defaults; NOT 100, see ASSUMPTIONS)."""
        return (self.trend_quality + self.base_pattern + self.setup_tightness
                + self.trigger_quality + self.regime + self.liquidity_range)

    def pre_trigger_max(self) -> float:
        return self.block_max_total() - self.trigger_quality


class ScoreOptional(_Base):
    sector_rs: bool = False
    rs_line_high: bool = False
    base_count: bool = False
    max_points: dict[str, float] = {"sector_rs": 4.0, "rs_line_high": 4.0, "base_count": 3.0}

    def enabled_max(self) -> float:
        return float(sum(v for k, v in self.max_points.items() if getattr(self, k, False)))


class ScoreConfig(_Base):
    enabled: bool = True
    zones: ScoreZones = ScoreZones()
    hysteresis: ScoreHysteresis = ScoreHysteresis()
    weights: ScoreWeights = ScoreWeights()
    patterns: dict[str, bool] = {"vcp": True, "flat_base": True,
                                 "cup_handle": False, "high_tight_flag": False}
    optional: ScoreOptional = ScoreOptional()

    def normalise(self, earned: float) -> float:
        """score = 100*earned/(100+enabled_optional_max); raw points unchanged otherwise."""
        return 100.0 * earned / (100.0 + self.optional.enabled_max())

class RegimeConfig(_Base):
    enabled: bool = True
    multipliers: dict[Literal["HIGH", "MEDIUM", "LOW"], float] = {
        "HIGH": 1.0,
        "MEDIUM": 0.5,
        "LOW": 0.0,
    }
    low_regime_stop: str = "hourly_ema20"
    index_dma: list[int] = [50, 200]
    breadth_dma: int = Field(50, ge=1)
    breadth_min_pct: float = Field(50.0, ge=0, le=100)
    high_low_lookback_days: int = Field(252, ge=2)
    dist_day_lookback: int = Field(10, ge=1)
    dist_day_min_count: int = Field(3, ge=1)
    dist_day_drop_pct: float = Field(0.2, ge=0)
    vix_avg_days: int = Field(20, ge=1)
    high_frac: float = Field(0.8, gt=0, le=1)
    medium_frac: float = Field(0.4, ge=0, le=1)


class ChopBreakoutSuccessConfig(_Base):
    enabled: bool = True
    lookback_days: int = Field(20, ge=1)
    horizon_days: int = Field(5, ge=1)
    success_r: float = 1.0
    min_events: int = Field(8, ge=1)
    low_rate: float = Field(0.30, ge=0, le=1)
    high_rate: float = Field(0.45, ge=0, le=1)


class ChopEfficiencyConfig(_Base):
    enabled: bool = True
    period: int = Field(10, ge=1)
    stock_min: float = Field(0.30, ge=0, le=1)
    index_min: float = Field(0.25, ge=0, le=1)


class ChopTimeStopConfig(_Base):
    enabled: bool = True
    max_days_to_reach_r: int = Field(3, ge=1)
    progress_r: float = 1.0
    stall_days: int = Field(5, ge=1)
    stall_exit_below_r: float = 3.0


class ChopConfig(_Base):
    breakout_success: ChopBreakoutSuccessConfig = ChopBreakoutSuccessConfig()
    efficiency: ChopEfficiencyConfig = ChopEfficiencyConfig()
    time_stop: ChopTimeStopConfig = ChopTimeStopConfig()


class AppConfig(_Base):
    run: RunConfig
    session: SessionConfig = SessionConfig()
    capital: CapitalConfig = CapitalConfig()
    data: DataConfig = DataConfig()
    storage: StorageConfig = StorageConfig()
    quality: QualityConfig = QualityConfig()
    events: EventsConfig = EventsConfig()
    hourly: HourlyConfig = HourlyConfig()
    benchmark: BenchmarkConfig = BenchmarkConfig()
    indicators: IndicatorConfig = IndicatorConfig()
    universe: UniverseConfig = UniverseConfig()
    trend: TrendConfig = TrendConfig()
    setup: SetupConfig = SetupConfig()
    score: ScoreConfig = ScoreConfig()
    regime: RegimeConfig = RegimeConfig()
    chop: ChopConfig = ChopConfig()

    def snapshot_hash(self) -> str:
        """Stable hash of the full config (for run reproducibility)."""
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read_raw(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    parent = raw.pop("extends", None)
    if parent:
        raw = _deep_merge(_read_raw(path.parent / parent), raw)
    return raw


def load_config(path: str | Path) -> AppConfig:
    return AppConfig.model_validate(_read_raw(Path(path)))
