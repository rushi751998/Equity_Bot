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


class AppConfig(_Base):
    run: RunConfig
    session: SessionConfig = SessionConfig()
    capital: CapitalConfig = CapitalConfig()
    data: DataConfig = DataConfig()
    storage: StorageConfig = StorageConfig()
    quality: QualityConfig = QualityConfig()
    events: EventsConfig = EventsConfig()

    def snapshot_hash(self) -> str:
        """Stable hash of the full config (for run reproducibility)."""
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]


def load_config(path: str | Path) -> AppConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return AppConfig.model_validate(raw)
