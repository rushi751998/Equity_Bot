"""Swing points, leg/pullback structure and the EMA ribbon (all causal)."""

from __future__ import annotations

import numpy as np

from tfalgo.indicators._np import as_f64, shift


def swing_points(high: object, low: object, k: int = 2) -> dict[str, np.ndarray]:
    """Fractal swings: a high at i needs h[i] > the k bars before and >= the k bars after.
    It is CONFIRMED (usable) only at row i+k. Returns as-of arrays last/prev swing high/low."""
    h, l = as_f64(high), as_f64(low)
    n = len(h)
    new_h = np.full(n, np.nan)
    new_l = np.full(n, np.nan)
    for i in range(k, n - k):
        if h[i] > h[i - k:i].max() and h[i] >= h[i + 1:i + k + 1].max():
            new_h[i + k] = h[i]
        if l[i] < l[i - k:i].min() and l[i] <= l[i + 1:i + k + 1].min():
            new_l[i + k] = l[i]
    names = ("last_swing_high", "prev_swing_high", "last_swing_low", "prev_swing_low")
    out = {nm: np.full(n, np.nan) for nm in names}
    lh = ph = ll = pl_ = np.nan
    for j in range(n):
        if new_h[j] == new_h[j]:
            ph, lh = lh, new_h[j]
        if new_l[j] == new_l[j]:
            pl_, ll = ll, new_l[j]
        out["last_swing_high"][j], out["prev_swing_high"][j] = lh, ph
        out["last_swing_low"][j], out["prev_swing_low"][j] = ll, pl_
    return out


def leg_structure(high: object, low: object, lookback: int = 20) -> dict[str, np.ndarray]:
    """leg_high = max high of the last `lookback` bars (latest occurrence); leg_low = min low of
    the (up to) `lookback` bars BEFORE it; pullback_low = min low of bars AFTER leg_high.
    `leg_valid` = all three exist and leg_high > leg_low."""
    h, l = as_f64(high), as_f64(low)
    n = len(h)
    leg_high = np.full(n, np.nan)
    leg_low = np.full(n, np.nan)
    pb_low = np.full(n, np.nan)
    since = np.full(n, np.nan)
    for t in range(lookback - 1, n):
        w = h[t - lookback + 1:t + 1]
        if np.isnan(w).any():
            continue
        j = lookback - 1 - int(np.argmax(w[::-1]))
        i = t - lookback + 1 + j
        leg_high[t] = w[j]
        since[t] = t - i
        lo0 = max(0, i - lookback)
        if i > lo0:
            leg_low[t] = l[lo0:i].min()
        if t > i:
            pb_low[t] = l[i + 1:t + 1].min()
    valid = np.isfinite(leg_high) & np.isfinite(leg_low) & np.isfinite(pb_low) & (leg_high > leg_low)
    return {"leg_high": leg_high, "leg_low": leg_low, "pullback_low": pb_low,
            "bars_since_leg_high": since, "leg_valid": valid}


def ribbon(
    close: object, fast: object, mid: object, slow: object,
    slope_bars: int = 3, min_spread_pct: float = 0.15,
) -> dict[str, np.ndarray]:
    """stack_ok = close>fast>mid>slow and slow EMA rising over `slope_bars`;
    compressed = (fast-slow)/slow*100 < min_spread_pct; fanning = spread > spread `slope_bars` ago."""
    c, f, m, s = as_f64(close), as_f64(fast), as_f64(mid), as_f64(slow)
    with np.errstate(divide="ignore", invalid="ignore"):
        spread = (f - s) / s * 100.0
        stack = (c > f) & (f > m) & (m > s) & (s > shift(s, slope_bars))
        compressed = spread < min_spread_pct
        fanning = spread > shift(spread, slope_bars)
    return {"stack_ok": stack, "compressed": compressed, "fanning": fanning, "spread_pct": spread}