from datetime import date, timedelta

import polars as pl

from tfalgo.calendar import TradingCalendar
from tfalgo.config import QualityConfig
from tfalgo.data.events import BlackoutEventProvider, NullEventProvider
from tfalgo.data.quality import QualityChecker, hard_failed_symbols
from tfalgo.data.synthetic import make_intraday_5m


def _checks(df, actions=None):
    q = QualityChecker(QualityConfig(), TradingCalendar())
    iss = q.check_symbol("S", df, "5m", actions)
    return {i.check: i for i in iss}


def test_clean_data_has_no_issues(bars5):
    assert _checks(bars5) == {}


def test_missing_bars_detected(bars5):
    out = _checks(bars5.slice(0, 100).vstack(bars5.slice(130)))  # 30 bars removed
    assert out["missing_bars"].count == 30


def test_duplicates_detected(bars5):
    out = _checks(bars5.vstack(bars5.head(3)))
    assert out["duplicate_timestamps"].severity == "hard"


def test_bad_ohlc_and_nonpositive(bars5):
    df = bars5.with_columns(pl.when(pl.int_range(pl.len()) == 5).then(pl.col("low") + 100).otherwise(pl.col("low")).alias("low"))
    assert "ohlc_inconsistent" in _checks(df)
    df2 = bars5.with_columns(pl.when(pl.int_range(pl.len()) == 7).then(0.0).otherwise(pl.col("close")).alias("close"))
    assert "non_positive_price" in _checks(df2)


def test_outside_session_and_naive_tz(bars5):
    shifted = bars5.with_columns(pl.col("ts") + pl.duration(hours=7))
    assert "outside_session" in _checks(shifted)
    naive = bars5.with_columns(pl.col("ts").dt.replace_time_zone(None))
    assert _checks(naive)["wrong_timezone"].severity == "hard"


def test_zero_volume_streak(bars5):
    df = bars5.with_columns(pl.when(pl.int_range(pl.len()).is_between(10, 30)).then(0.0).otherwise(pl.col("volume")).alias("volume"))
    assert "zero_volume_streak" in _checks(df)


def test_split_like_jump_flagged_unless_action_recorded():
    df = make_intraday_5m(date(2024, 1, 1), 6, seed=5)
    cut = date(2024, 1, 4)
    jumped = df.with_columns(pl.when(pl.col("ts").dt.date() >= cut).then(pl.col(c) / 5).otherwise(pl.col(c)).alias(c)
                             for c in ["open", "high", "low", "close"])
    out = _checks(jumped)
    assert out["split_like_jump"].severity == "hard"
    actions = pl.DataFrame({"ex_date": [cut], "type": ["split"], "ratio": [5.0]})
    assert "split_like_jump" not in _checks(jumped, actions)


def test_hard_failed_symbols_helper(bars5):
    q = QualityChecker(QualityConfig(), TradingCalendar())
    iss = q.run({"GOOD": bars5, "BAD": bars5.vstack(bars5.head(2))})
    assert list(hard_failed_symbols(iss)) == ["BAD"]


def test_events_null_and_blackout():
    cal = TradingCalendar()
    assert not NullEventProvider().has_event_within("X", date(2024, 1, 10), 4, cal)
    b = BlackoutEventProvider(3)
    assert b.is_event_day("X", date(2024, 1, 20)) and not b.is_event_day("X", date(2024, 3, 10))
    assert b.has_event_within("X", date(2024, 1, 10), 4, cal)  # 2024-01-12 is inside the window (>= Jan 12)


def test_muhurat_evening_session_is_soft_and_ignored_by_resample(bars5):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from tfalgo.data.resample import resample

    base = datetime(2024, 1, 6, 18, 15, tzinfo=ZoneInfo("Asia/Kolkata"))  # Saturday, no regular bars
    ev = pl.DataFrame({"ts": [base + timedelta(minutes=5 * i) for i in range(12)],
                       "open": [100.0] * 12, "high": [100.5] * 12, "low": [99.5] * 12,
                       "close": [100.0] * 12, "volume": [500.0] * 12}).with_columns(
        pl.col("ts").dt.convert_time_zone("Asia/Kolkata"))
    big = make_intraday_5m(date(2024, 1, 8), 60, seed=4).vstack(ev).sort("ts")
    out = _checks(big)
    assert out["special_session_bars"].severity == "soft" and out["special_session_bars"].count == 12
    assert "outside_session" not in out
    q = QualityChecker(QualityConfig(), TradingCalendar())
    assert hard_failed_symbols(q.run({"S": big})) == {}
    assert resample(big, "1D").height == 60  # no bogus extra daily bar


def test_stray_bar_on_normal_day_is_hard_and_located(bars5):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    stray = pl.DataFrame({"ts": [datetime(2024, 1, 2, 16, 5, tzinfo=ZoneInfo("Asia/Kolkata"))],
                          "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.0], "volume": [10.0]}
                         ).with_columns(pl.col("ts").dt.convert_time_zone("Asia/Kolkata"))
    out = _checks(bars5.vstack(stray).sort("ts"))
    assert out["outside_session"].severity == "hard"
    assert out["outside_session"].first_ts.startswith("2024-01-02T15:30")
    assert "2024-01-02 15:30" in out["outside_session"].detail
