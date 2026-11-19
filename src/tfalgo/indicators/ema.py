"""EMA / SMA."""

from __future__ import annotations

import numpy as np

from tfalgo.indicators._np import as_f64, rolling_mean

sma = rolling_mean


def ema(x: object, span: int) -> np.ndarray:
    """Recursive EMA, alpha = 2/(span+1), seeded with the first finite value
    (pandas `ewm(span, adjust=False)`). Output is NaN until `span` observations were seen;
    NaN inputs carry the previous value forward."""
    a = as_f64(x)
    alpha = 2.0 / (span + 1.0)
    out = np.full(a.shape, np.nan)
    prev = np.nan
    seen = 0
    for i in range(len(a)):
        v = a[i]
        if v != v:  # NaN
            if seen >= span:
                out[i] = prev
            continue
        prev = v if seen == 0 else prev + alpha * (v - prev)
        seen += 1
        if seen >= span:
            out[i] = prev
    return out