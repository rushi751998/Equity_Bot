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
from typing import Any, Literal

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

class TriggerWindowConfig(_Base):
    observe_from: str = "09:15"
    entry_from: str = "09:30"
    entry_until: str = "10:45"


class TriggerConfig(_Base):
    window: TriggerWindowConfig = TriggerWindowConfig()
    rvol_pace_min: float = 1.5
    max_extension_hatr: float = 1.5
    no_fill_first_minutes: int = Field(2, ge=0)


class StopMinDistanceConfig(_Base):
    atr15_mult: float = 1.0
    spread_floor_bps: float = 15.0


class StopAtrFallbackConfig(_Base):
    timeframe: Timeframe = "60m"
    period: int = Field(14, ge=1)
    mult: float = 3.0


class StopFallbackConfig(_Base):
    type: Literal["fixed_pct", "atr", "skip"] = "fixed_pct"
    fixed_pct: float = 3.0
    atr: StopAtrFallbackConfig = StopAtrFallbackConfig()


class StopConfig(_Base):
    mode: Literal["swing_low_with_fallback", "fixed_pct", "atr"] = "swing_low_with_fallback"
    buffer_atr15: float = 0.10
    min_distance: StopMinDistanceConfig = StopMinDistanceConfig()
    max_swing_stop_pct: float = 5.0
    fallback: StopFallbackConfig = StopFallbackConfig()


class SizingConfig(_Base):
    risk_per_trade_pct: float = 0.5
    max_position_pct: float = 25.0
    max_adv_participation_pct: float = 1.0
    tranches: list[float] = [0.40, 0.40, 0.20]


class PullbackAddConfig(_Base):
    band_emas: list[int] = [9, 15]
    max_depth_hatr: float = 1.0
    mini_high_bars: int = Field(3, ge=1)


class PyramidConfig(_Base):
    enabled: bool = True
    add1_min_r: float = 1.0
    add2_min_r: float = 2.0
    max_extension_atr_daily: float = 2.0
    last_add_time: str = "15:00"
    types: list[Literal["breakout", "pullback"]] = ["breakout", "pullback"]
    min_hold_score: float = 60.0
    pullback_add: PullbackAddConfig = PullbackAddConfig()


class PartialsConfig(_Base):
    enabled: bool = True
    gate_min_r: float = 3.0
    ladder: list[float] = [0.25, 0.25]
    runner_min_frac: float = 0.5
    min_partial_value_inr: float = 3000.0


class ExhaustionConfig(_Base):
    ext_atr_daily: float = 2.5
    climax_range_mult: float = 2.0
    climax_vol_mult: float = 2.5
    climax_close_lower_frac: float = 0.40
    parabolic_bb_closes: int = Field(3, ge=1)
    gapfail_atr: float = 1.5
    gapfail_minutes: int = Field(30, ge=1)


class RunnerConfig(_Base):
    confirm_closes: int = Field(2, ge=1)
    daily_trail: str = "ema21"
    chandelier_atr: float = 3.0
    climax_sell_frac_of_runner: float = 0.5


class ExitsConfig(_Base):
    partials: PartialsConfig = PartialsConfig()
    exhaustion: ExhaustionConfig = ExhaustionConfig()
    runner: RunnerConfig = RunnerConfig()


class CarryHoldConfig(_Base):
    continue_while: str = "daily_close_above_ema21"
    max_trading_days: int = Field(15, ge=1)


class CarryConfig(_Base):
    enabled: bool = True
    mis_decision_time: str = "15:10"
    mis_squareoff_time: str = "15:15"
    min_open_r: float = 2.0
    min_close_in_range: float = 0.75
    min_vol_pace: float = 1.0
    min_regime: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    trim_pct: float = 0.33
    hold: CarryHoldConfig = CarryHoldConfig()


class ReentryConfig(_Base):
    max_entries_per_stock_per_day: int = Field(1, ge=1)
    cooldown_days_after_stop: int = Field(3, ge=0)
    release_on_new_daily_base: bool = True


class RetestEntryConfig(_Base):
    enabled: bool = True
    valid_bars: int = Field(6, ge=1)


class EntryZoneConfig(_Base):
    confirm_atr15: float = 0.10
    chase_atr15: float = 0.25
    retest_entry: RetestEntryConfig = RetestEntryConfig()


class SoftExitConfig(_Base):
    enabled: bool = True
    hourly_close_below: str = "ema20"
    confirm_closes: int = Field(2, ge=1)


class BuffersConfig(_Base):
    entry_zone: EntryZoneConfig = EntryZoneConfig()
    soft_exit: SoftExitConfig = SoftExitConfig()
    hard_stop_always_live: bool = True


class PortfolioThrottleConfig(_Base):
    lookback_trades: int = Field(10, ge=1)
    risk_multiplier: float = 0.5
    release_after_consecutive_wins: int = Field(2, ge=1)


class PortfolioConfig(_Base):
    max_open_positions: int = Field(6, ge=1)
    max_heat_pct: float = 3.5
    max_per_sector: int = Field(2, ge=1)
    max_corr_20d: float = 0.80
    max_new_entries_per_day: int = Field(3, ge=1)
    daily_loss_limit_pct: float = 1.0
    weekly_loss_limit_pct: float = 3.0
    ranking: list[str] = ["entry_score", "rs_3m", "rvol_pace"]
    throttle: PortfolioThrottleConfig = PortfolioThrottleConfig()


class StrategyCompositionConfig(_Base):
    name: str = "trend_pullback_v1"
    patterns: list[str] = ["vcp", "flat_base"]
    score_blocks: list[str] = [
        "trend_quality", "base_pattern", "setup_tightness",
        "trigger_quality", "regime", "liquidity_range", "penalties",
    ]
    vetoes: list[str] = [
        "liquidity", "regime_low", "close_below_200dma",
        "extension_gt_2_5_hatr", "stop_too_wide", "data_gaps",
    ]
    stop: str = "swing_low_with_fallback"
    exits: list[str] = ["ladder", "runner", "hold_score", "time_stop", "soft_exit"]
    params: dict[str, Any] = {}

class SlippageConfig(_Base):
    min_bps: float = 5.0
    impact_k_bps: float = 30.0
    stop_multiplier: float = 1.5
    max_participation: float = 0.10
    max_fill_bars: int = Field(3, ge=1)


class CostsConfig(_Base):
    broker_profile: str = "zerodha"
    broker_file: Path = Path("config/brokers/zerodha.yaml")
    flat_cost_pct: float | None = None
    slippage: SlippageConfig = SlippageConfig()

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
    trigger: TriggerConfig = TriggerConfig()
    stop: StopConfig = StopConfig()
    sizing: SizingConfig = SizingConfig()
    pyramid: PyramidConfig = PyramidConfig()
    exits: ExitsConfig = ExitsConfig()
    carry: CarryConfig = CarryConfig()
    reentry: ReentryConfig = ReentryConfig()
    vetoes: list[str] = [
        "liquidity", "regime_low", "close_below_200dma",
        "extension_gt_2_5_hatr", "stop_too_wide", "data_gaps",
    ]
    buffers: BuffersConfig = BuffersConfig()
    portfolio: PortfolioConfig = PortfolioConfig()
    strategy: StrategyCompositionConfig = StrategyCompositionConfig()
    costs: CostsConfig = CostsConfig()

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
