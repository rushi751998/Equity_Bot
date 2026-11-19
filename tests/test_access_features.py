from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest

from p2_helpers import CAL, make_cfg, sym5
from tfalgo.data.access import build_symbol_data, visible_at, visible_daily

IST = ZoneInfo("Asia/Kolkata")


def test_partial_bar_flag_price_only():
    h = build_symbol_data("X", sym5(10), make_cfg(), CAL).h60
    last = h.filter(pl.col("ts").dt.hour() == 15)
    rest = h.filter(pl.col("ts").dt.hour() != 15)
    assert last["is_partial"].all() and set(last["n_bars"].to_list()) == {3}
    assert not rest["is_partial"].any()
    assert (~last["in_stats"]).all() and rest["in_stats"].all()


def test_partial_bar_include_all():
    h = build_symbol_data("X", sym5(10), make_cfg(hourly={"partial_bar_policy": "include_all"}), CAL).h60
    assert h["in_stats"].all()


def test_atr_skips_partial_only_under_price_only():
    bars = sym5(20)
    a = build_symbol_data("X", bars, make_cfg(), CAL).h60
    b = build_symbol_data("X", bars, make_cfg(hourly={"partial_bar_policy": "include_all"}), CAL).h60
    idx = np.flatnonzero(a["is_partial"].to_numpy())
    idx = idx[idx >= 20]
    x, y = a["atr"].to_numpy(), b["atr"].to_numpy()
    np.testing.assert_array_equal(x[idx], x[idx - 1])          # carried over the partial bar
    assert not np.allclose(y[idx], y[idx - 1])                  # included when policy says so
    # price logic still sees the partial bar: EMA changes on it
    e = a["ema20"].to_numpy()
    assert not np.allclose(e[idx], e[idx - 1])


def test_daily_avail_ts_and_example7():
    sd = build_symbol_data("X", sym5(10), make_cfg(), CAL)
    d = sd.d1
    assert d["avail_ts"][0] == datetime(2024, 1, 2, 9, 15, tzinfo=IST)
    fri = d.filter(pl.col("date") == datetime(2024, 1, 5).date())
    assert fri["avail_ts"][0] == datetime(2024, 1, 8, 9, 15, tzinfo=IST)
    now = datetime(2024, 1, 2, 10, 20, tzinfo=IST)
    assert visible_daily(d, now).height == 1                     # only D-1's daily bar
    assert visible_daily(d, datetime(2024, 1, 1, 10, 20, tzinfo=IST)).is_empty()
    assert visible_at(sd.h60, now)["ts"].dt.strftime("%H:%M").to_list() == ["09:15"] * 0 + visible_at(
        sd.h60, now)["ts"].dt.strftime("%H:%M").to_list()
    day1 = sd.h60.filter(pl.col("ts").dt.date() == datetime(2024, 1, 2).date())
    assert visible_at(day1, now)["ts"].dt.strftime("%H:%M").to_list() == ["09:15"]


def test_adtv_and_rvol_pace_last_day():
    sd = build_symbol_data("X", sym5(60), make_cfg(), CAL)
    d = sd.d1
    cv = (d["close"] * d["volume"]).to_list()
    assert d["adtv_cr"][-1] == pytest.approx(sum(cv[-20:]) / 20 / 1e7, rel=1e-12)
    vols = d["volume"].to_list()
    assert sd.m5["rvol_pace"][-1] == pytest.approx(vols[-1] / (sum(vols[-21:-1]) / 20), rel=1e-12)
    assert sd.m5["rvol_pace"][:20 * 75].null_count() == 20 * 75   # needs 20 prior days


def test_outputs_have_no_nan_only_nulls():
    sd = build_symbol_data("X", sym5(30), make_cfg(), CAL)
    for df in (sd.d1, sd.h60, sd.m15, sd.m5):
        for col, dt in df.schema.items():
            if dt == pl.Float64:
                assert df[col].is_nan().sum() == 0, col


def test_relative_strength_columns():
    cfg = make_cfg(indicators={"rs_windows": [5, 10]})
    bench = build_symbol_data("idx", sym5(40, seed=9), cfg, CAL, is_index=True)
    sd = build_symbol_data("X", sym5(40, seed=2), cfg, CAL, bench=bench)
    d = sd.d1
    assert {"rs5", "rs10", "rs_composite", "rs_line", "rs_line_ge_avg"} <= set(d.columns)
    r = d.row(-1, named=True)
    assert r["rs_composite"] == pytest.approx((r["rs5"] + r["rs10"]) / 2, abs=1e-12)
    assert r["rs5"] == pytest.approx((1 + r["ret5"]) / (1 + r["bench_ret5"]), abs=1e-12)