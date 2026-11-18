from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tfalgo.calendar import TradingCalendar, timeframe_minutes
from tfalgo.config import AppConfig, load_config

IST = ZoneInfo("Asia/Kolkata")


def test_default_yaml_loads_and_hash_stable():
    cfg = load_config("config/default.yaml")
    assert cfg.capital.initial == 1_000_000
    assert cfg.run.base_timeframe == "5m"
    assert cfg.snapshot_hash() == load_config("config/default.yaml").snapshot_hash()


def test_unknown_key_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"run": {"start": "2021-01-01", "end": "2021-02-01"}, "bogus": 1})


def test_end_before_start_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"run": {"start": "2021-02-01", "end": "2021-01-01"}})


def test_calendar_trading_days_and_holidays():
    cal = TradingCalendar({date(2024, 1, 26)})  # Friday holiday
    assert not cal.is_trading_day(date(2024, 1, 27))  # Saturday
    assert not cal.is_trading_day(date(2024, 1, 26))
    assert cal.next_trading_day(date(2024, 1, 25)) == date(2024, 1, 29)
    assert cal.add_trading_days(date(2024, 1, 25), 2) == date(2024, 1, 30)
    assert cal.add_trading_days(date(2024, 1, 29), -1) == date(2024, 1, 25)


def test_bar_geometry_last_60m_is_15_minutes():
    cal = TradingCalendar()
    starts = cal.expected_bar_starts(date(2024, 1, 1), "60m")
    assert [s.strftime("%H:%M") for s in starts] == ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]
    assert cal.bar_end(starts[-1], "60m") == datetime(2024, 1, 1, 15, 30, tzinfo=IST)
    assert len(cal.expected_bar_starts(date(2024, 1, 1), "5m")) == 75
    assert timeframe_minutes("1D") == 375


def test_completed_bar_rule_example7():
    cal = TradingCalendar()
    d = date(2024, 1, 1)
    now = datetime(2024, 1, 1, 10, 20, tzinfo=IST)
    assert cal.is_bar_visible(datetime(2024, 1, 1, 9, 15, tzinfo=IST), "60m", now)
    assert not cal.is_bar_visible(datetime(2024, 1, 1, 10, 15, tzinfo=IST), "60m", now)
    assert not cal.is_bar_visible(cal.session_open_dt(d), "1D", now)
