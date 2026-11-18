from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tfalgo.data.resample import resample, visible_at
from tfalgo.data.synthetic import make_intraday_5m

IST = ZoneInfo("Asia/Kolkata")


def _mk(rows):
    return pl.DataFrame(rows, schema=["ts", "open", "high", "low", "close", "volume"], orient="row").with_columns(
        pl.col("ts").dt.replace_time_zone("Asia/Kolkata"))


def test_hand_built_fixture_15m():
    t0 = datetime(2024, 1, 1, 9, 15)
    rows = [(t0 + timedelta(minutes=5 * i), o, h, l, c, v) for i, (o, h, l, c, v) in enumerate(
        [(10, 12, 9, 11, 100), (11, 13, 10, 12, 200), (12, 12.5, 8, 9, 300), (9, 10, 8.5, 9.5, 50)])]
    r = resample(_mk(rows), "15m")
    assert r.height == 2
    b = r.row(0, named=True)
    assert (b["open"], b["high"], b["low"], b["close"], b["volume"], b["n_bars"]) == (10, 13, 8, 9, 600, 3)
    assert r["ts"][1].strftime("%H:%M") == "09:30"
    assert r["bar_end"][0].strftime("%H:%M") == "09:30"


def test_60m_buckets_and_short_last_bar(bars5):
    r = resample(bars5, "60m")
    day1 = r.filter(pl.col("ts").dt.date() == date(2024, 1, 1))
    assert day1["ts"].dt.strftime("%H:%M").to_list() == ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]
    assert day1["n_bars"].to_list() == [12] * 6 + [3]
    assert day1["bar_end"][-1].strftime("%H:%M") == "15:30"


def test_daily_from_session(bars5):
    d = resample(bars5, "1D")
    assert d.height == 10 and set(d["n_bars"].to_list()) == {75}
    day = bars5.filter(pl.col("ts").dt.date() == date(2024, 1, 1))
    row = d.row(0, named=True)
    assert row["open"] == day["open"][0] and row["close"] == day["close"][-1]
    assert row["high"] == day["high"].max() and row["volume"] == day["volume"].sum()


def test_reject_finer_or_non_multiple(bars5):
    with pytest.raises(ValueError):
        resample(bars5, "1m")


def test_visible_at_completed_bar_rule(bars5):
    r = resample(bars5, "60m")
    now = datetime(2024, 1, 1, 10, 20, tzinfo=IST)
    vis = visible_at(r, now)
    assert vis["ts"].dt.strftime("%H:%M").to_list() == ["09:15"]
    d = visible_at(resample(bars5, "1D"), now)
    assert d.is_empty()  # daily bar for D invisible until after the close
    assert visible_at(resample(bars5, "1D"), datetime(2024, 1, 2, 9, 15, tzinfo=IST)).height == 1


@settings(max_examples=40, deadline=None)
@given(cut=st.integers(min_value=1, max_value=10 * 75 - 1), tf=st.sampled_from(["15m", "60m", "1D"]))
def test_no_lookahead_truncation_does_not_change_visible_bars(cut, tf):
    full = make_intraday_5m(date(2024, 1, 1), 10, seed=3)
    now = full["ts"][cut] + timedelta(minutes=5)  # data known up to and including bar `cut`
    trunc = full.head(cut + 1)
    a = visible_at(resample(full, tf), now).drop("n_bars")
    b = visible_at(resample(trunc, tf), now).drop("n_bars")
    assert a.equals(b)
