import math

import numpy as np
import pytest

from tfalgo.indicators._np import apply_on_mask, ffill
from tfalgo.indicators.atr import true_range, wilder_atr
from tfalgo.indicators.bollinger import bollinger, consecutive_above
from tfalgo.indicators.efficiency import efficiency_ratio
from tfalgo.indicators.ema import ema
from tfalgo.indicators.relstrength import cross_sectional_percentile, period_return, rs_ratio
from tfalgo.indicators.structure import leg_structure, ribbon, swing_points
from tfalgo.indicators.volume import masked_rolling_mean, range_ratio, rvol_pace

TOL = 1e-8
H = [10, 11, 13, 12]
L = [8, 9, 10, 9]
C = [9, 10, 12, 10]


def test_ema_reference_and_warmup():
    out = ema([1, 2, 3, 4, 5], 3)
    assert np.isnan(out[:2]).all()
    np.testing.assert_allclose(out[2:], [2.25, 3.125, 4.0625], atol=TOL, rtol=0)


def test_ema_nan_carry():
    np.testing.assert_allclose(ema([1, 2, np.nan, 4], 1), [1, 2, 2, 4], atol=TOL, rtol=0)


def test_true_range_and_wilder_atr_reference():
    np.testing.assert_allclose(true_range(H, L, C), [2, 2, 3, 3], atol=TOL, rtol=0)
    out = wilder_atr(H, L, C, 2)
    assert np.isnan(out[0])
    np.testing.assert_allclose(out[1:], [2.0, 2.5, 2.75], atol=TOL, rtol=0)


def test_atr_excluded_bar_carries_and_mask_none_equals_all_true():
    h, l, c = H + [30], L + [5], C + [20]
    out = wilder_atr(h, l, c, 2, include=[True, True, True, True, False])
    assert out[4] == pytest.approx(out[3], abs=TOL)
    full = wilder_atr(h, l, c, 2)
    np.testing.assert_allclose(wilder_atr(h, l, c, 2, include=[True] * 5), full, equal_nan=True)
    assert full[4] != pytest.approx(out[3])


def test_bollinger_reference():
    mid, up, dn = bollinger(np.arange(1, 21, dtype=float), 20, 2.0)
    sd = math.sqrt(33.25)
    assert mid[-1] == pytest.approx(10.5, abs=TOL)
    assert up[-1] == pytest.approx(10.5 + 2 * sd, abs=TOL)
    assert dn[-1] == pytest.approx(10.5 - 2 * sd, abs=TOL)
    assert np.isnan(mid[:19]).all()


def test_consecutive_above():
    np.testing.assert_array_equal(
        consecutive_above([1, 3, 3, 1, 3, 3, 3], [2] * 7), [0, 1, 2, 0, 1, 2, 3])
    np.testing.assert_array_equal(consecutive_above([3, 3], [np.nan, 2]), [0, 1])


def test_efficiency_ratio_reference():
    assert efficiency_ratio([10, 11, 10, 12], 3)[3] == pytest.approx(0.5, abs=TOL)
    assert efficiency_ratio(np.arange(1.0, 20.0), 10)[-1] == pytest.approx(1.0, abs=TOL)
    zig = np.tile([1.0, 2.0], 10)
    assert efficiency_ratio(zig, 10)[-1] == pytest.approx(0.0, abs=TOL)
    assert np.isnan(efficiency_ratio(zig, 10)[:10]).all()


def test_period_return_and_rs_ratio():
    np.testing.assert_allclose(period_return([100, 110, 121], 1), [np.nan, 0.1, 0.1], equal_nan=True, atol=TOL)
    assert rs_ratio(0.2, 0.1) == pytest.approx(1.2 / 1.1, abs=TOL)
    assert np.isnan(rs_ratio(0.2, -1.0))


def test_cross_sectional_percentile():
    m = np.array([[1, 2, 3, np.nan], [5, 5, np.nan, np.nan], [1, np.nan, np.nan, np.nan]])
    out = cross_sectional_percentile(m)
    np.testing.assert_allclose(out[0], [0, 50, 100, np.nan], equal_nan=True, atol=TOL)
    np.testing.assert_allclose(out[1], [50, 50, np.nan, np.nan], equal_nan=True, atol=TOL)
    assert np.isnan(out[2]).all()


def test_helpers_ffill_and_masked_mean():
    np.testing.assert_allclose(ffill([np.nan, 1, np.nan, np.nan, 2]), [np.nan, 1, 1, 1, 2], equal_nan=True)
    out = masked_rolling_mean([1, 2, 3, 4, 5], [True, True, False, True, True], 2)
    np.testing.assert_allclose(out, [np.nan, 1.5, 1.5, 3, 4.5], equal_nan=True, atol=TOL)
    np.testing.assert_allclose(apply_on_mask([1, 2, 3], [False, True, True], lambda v: v * 10),
                               [np.nan, 20, 30], equal_nan=True)


def test_range_ratio_reference():
    out = range_ratio([1, 1, 2, 2, 4, 4], [True] * 6, 2)
    np.testing.assert_allclose(out[3:], [2, 2, 2], atol=TOL)
    assert np.isnan(out[:3]).all()


def test_rvol_pace_reference():
    day = [0, 0, 1, 1, 2, 2, 3, 3]
    tod = [0, 1] * 4
    vol = [10, 10, 20, 20, 30, 30, 15, 15]
    out = rvol_pace(day, tod, vol, window=2)
    assert np.isnan(out[:4]).all()
    np.testing.assert_allclose(out[4:], [2.0, 2.0, 0.6, 0.6], atol=TOL)


def test_swing_points_confirmation_lag():
    sw = swing_points([1, 3, 2, 4, 2], [0, 0, 0, 0, 0], k=1)
    np.testing.assert_allclose(sw["last_swing_high"], [np.nan, np.nan, 3, 3, 4], equal_nan=True)
    np.testing.assert_allclose(sw["prev_swing_high"], [np.nan, np.nan, np.nan, np.nan, 3], equal_nan=True)


def test_leg_structure_reference():
    hi = [10, 11, 12, 11, 10.5, 10]
    lo = [9, 10, 11, 10, 9.8, 9.5]
    g = leg_structure(hi, lo, lookback=3)
    assert not g["leg_valid"][2]                    # leg_high is the current bar: no pullback yet
    assert (g["leg_high"][3], g["leg_low"][3], g["pullback_low"][3]) == (12, 9, 10)
    assert g["bars_since_leg_high"][3] == 1 and g["leg_valid"][3]
    assert (g["leg_high"][5], g["leg_low"][5], g["pullback_low"][5]) == (11, 9, 9.5)
    assert g["bars_since_leg_high"][5] == 2


def test_ribbon_flags():
    s = np.array([10, 10.1, 10.2, 10.3, 10.4, 10.5])
    m = s + 0.05
    f = s + np.array([0.1, 0.1, 0.1, 0.1, 0.2, 0.3])
    r = ribbon(f + 0.1, f, m, s, slope_bars=1, min_spread_pct=1.0)
    assert not r["stack_ok"][0] and r["stack_ok"][1:].all()
    assert r["compressed"][1] and not r["compressed"][5]
    assert r["fanning"][4] and r["fanning"][5] and not r["fanning"][3]