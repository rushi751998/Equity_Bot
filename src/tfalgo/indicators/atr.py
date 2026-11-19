"""True range and Wilder ATR (optionally skipping bars excluded from range statistics)."""

from __future__ import annotations

import numpy as np

from tfalgo.indicators._np import as_f64


def true_range(high: object, low: object, close: object) -> np.ndarray:
    """TR = max(H-L, |H-prevC|, |L-prevC|); first bar uses H-L."""
    h, l, c = as_f64(high), as_f64(low), as_f64(close)
    prev = np.concatenate(([np.nan], c[:-1])) if len(c) else c
    return np.fmax(h - l, np.fmax(np.abs(h - prev), np.abs(l - prev)))


def wilder_atr(
    high: object, low: object, close: object, period: int, include: object | None = None
) -> np.ndarray:
    """Wilder ATR: seed = mean of the first `period` TRs, then (ATR*(p-1)+TR)/p.

    `include` (bool array) marks bars that may update the ATR. Excluded bars (e.g. the 15-minute
    15:15 hourly bar under `price_only`) carry the previous ATR forward; their close still serves
    as prev-close for the next TR.
    """
    tr = true_range(high, low, close)
    n = len(tr)
    inc = np.ones(n, dtype=bool) if include is None else np.asarray(include, dtype=bool)
    out = np.full(n, np.nan)
    atr = np.nan
    used = 0
    acc = 0.0
    for i in range(n):
        t = tr[i]
        if not inc[i] or t != t:
            out[i] = atr
            continue
        used += 1
        if used <= period:
            acc += t
            if used == period:
                atr = acc / period
        else:
            atr = (atr * (period - 1) + t) / period
        out[i] = atr
    return out