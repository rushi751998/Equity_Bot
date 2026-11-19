"""Bollinger bands (population std) and closes-above-upper streaks."""

from __future__ import annotations

import numpy as np

from tfalgo.indicators._np import as_f64, rolling_mean, rolling_std


def bollinger(close: object, period: int = 20, k: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (mid, upper, lower); std uses ddof=0 (classic Bollinger)."""
    mid = rolling_mean(close, period)
    sd = rolling_std(close, period, ddof=0)
    return mid, mid + k * sd, mid - k * sd


def consecutive_above(close: object, level: object) -> np.ndarray:
    """Length of the current run of closes strictly above `level` (0 if not above/unknown)."""
    c, lv = as_f64(close), as_f64(level)
    out = np.zeros(len(c), dtype=np.int64)
    run = 0
    for i in range(len(c)):
        run = run + 1 if (c[i] > lv[i]) else 0
        out[i] = run
    return out