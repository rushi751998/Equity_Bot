"""Volume / range statistics with partial-bar masking, and relative-volume pace."""

from __future__ import annotations

from collections import deque

import numpy as np

from tfalgo.indicators._np import apply_on_mask, as_f64, rolling_mean, shift


def masked_rolling_mean(x: object, mask: object, n: int) -> np.ndarray:
    """Mean of the last n MASKED-IN values (masked-out rows carry the previous value)."""
    return apply_on_mask(x, mask, lambda v: rolling_mean(v, n))


def range_ratio(rng: object, mask: object, bars: int = 3) -> np.ndarray:
    """Tightness: mean range of last `bars` masked-in bars / mean range of the `bars` before."""

    def _rr(r: np.ndarray) -> np.ndarray:
        m = rolling_mean(r, bars)
        prev = shift(m, bars)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(prev > 0, m / prev, np.nan)

    return apply_on_mask(rng, mask, _rr)


def rvol_pace(day_id: object, tod: object, volume: object, window: int = 20) -> np.ndarray:
    """Cumulative volume today through this bar / mean cumulative volume through the SAME
    time of day over the previous `window` days. `day_id` must be non-decreasing. NaN until
    `window` prior days exist for that time of day. Value at a row is usable at that bar's end."""
    d = np.asarray(day_id)
    t = np.asarray(tod)
    v = as_f64(volume)
    out = np.full(len(v), np.nan)
    hist: dict[int, deque[float]] = {}
    today: list[tuple[int, float]] = []
    cur = None
    run = 0.0
    for i in range(len(v)):
        if cur is None or d[i] != cur:
            for tt, cc in today:
                hist.setdefault(tt, deque(maxlen=window)).append(cc)
            today = []
            run = 0.0
            cur = d[i]
        run += v[i]
        ti = int(t[i])
        h = hist.get(ti)
        if h is not None and len(h) == window:
            avg = sum(h) / window
            if avg > 0:
                out[i] = run / avg
        today.append((ti, run))
    return out