"""Kaufman efficiency ratio."""

from __future__ import annotations

import numpy as np

from tfalgo.indicators._np import as_f64, rolling_sum, shift


def efficiency_ratio(close: object, period: int = 10) -> np.ndarray:
    """ER = |C_t - C_{t-n}| / sum_{i=t-n+1..t} |C_i - C_{i-1}|; 0 when the path length is 0."""
    c = as_f64(close)
    net = np.abs(c - shift(c, period))
    step = np.abs(np.diff(c, prepend=np.nan))
    path = rolling_sum(step, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        er = np.where(path > 0, net / path, 0.0)
    return np.where(np.isnan(net) | np.isnan(path), np.nan, er)