from datetime import datetime, time
from zoneinfo import ZoneInfo

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st
from polars.testing import assert_frame_equal

from p2_helpers import CAL, make_cfg, sym5
from tfalgo.data.access import build_symbol_data, visible_daily

IST = ZoneInfo("Asia/Kolkata")
CFG = make_cfg()
FULL5 = sym5(60, seed=3)
FULL = build_symbol_data("X", FULL5, CFG, CAL)
DAYS = FULL5["ts"].dt.date().unique().sort().to_list()


@settings(max_examples=20, deadline=None)
@given(k=st.integers(25, 58), hour=st.sampled_from([10, 11, 12, 13, 14]))
def test_truncation_does_not_change_past_signals(k, hour):
    cut = datetime.combine(DAYS[k], time(hour, 15), tzinfo=IST)   # on a 60m (and 15m) boundary
    part = build_symbol_data("X", FULL5.filter(pl.col("ts") < cut), CFG, CAL)
    assert_frame_equal(FULL.h60.filter(pl.col("bar_end") <= cut), part.h60)
    assert_frame_equal(FULL.m15.filter(pl.col("bar_end") <= cut), part.m15)
    assert_frame_equal(FULL.m5.filter(pl.col("bar_end") <= cut), part.m5)
    assert_frame_equal(visible_daily(FULL.d1, cut), visible_daily(part.d1, cut))