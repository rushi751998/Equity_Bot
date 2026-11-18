"""Config -> component factory (single place that wires concrete classes)."""

from __future__ import annotations

from tfalgo.calendar import TradingCalendar
from tfalgo.config import AppConfig
from tfalgo.data.events import EVENTS, EventProvider
from tfalgo.data.provider import PROVIDERS, DataProvider
from tfalgo.data.store import STORES, BarStore
import tfalgo.data.providers  # noqa: F401  (registers built-ins)


def build_calendar(cfg: AppConfig) -> TradingCalendar:
    s = cfg.session
    return TradingCalendar.from_csv(s.holidays_file, session_open=s.open, session_close=s.close, tz=cfg.run.timezone)


def build_provider(cfg: AppConfig) -> DataProvider:
    cls = PROVIDERS.get(cfg.data.provider)
    if cfg.data.provider == "csv":
        return cls(cfg.data.csv, tz=cfg.run.timezone)  # type: ignore[call-arg]
    return cls()  # broker providers take credentials from env in later phases


def build_store(cfg: AppConfig) -> BarStore:
    return STORES.get(cfg.storage.backend)(cfg.storage.sqlite_path, tz=cfg.run.timezone)  # type: ignore[call-arg]


def build_events(cfg: AppConfig) -> EventProvider:
    e = cfg.events
    if e.provider == "csv":
        return EVENTS.get("csv")(e.csv_file)  # type: ignore[call-arg]
    if e.provider == "blackout":
        return EVENTS.get("blackout")(e.blackout_days)  # type: ignore[call-arg]
    return EVENTS.get("none")()
