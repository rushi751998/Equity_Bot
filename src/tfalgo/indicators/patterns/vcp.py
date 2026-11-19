"""Volatility Contraction Pattern (VCP) detector."""

from __future__ import annotations

import numpy as np
import polars as pl

from tfalgo.indicators._np import rolling_mean
from tfalgo.indicators.atr import wilder_atr
from tfalgo.indicators.patterns.base import PATTERNS, PatternDetector


def _extract_contractions(
    high: np.ndarray,
    low: np.ndarray,
    threshold: float,
) -> list[tuple[int, int, float]]:
    """Extract zig-zag contractions (peak_idx, trough_idx, depth) from a base slice."""
    n = len(high)
    if n < 5:
        return []
    contractions: list[tuple[int, int, float]] = []
    # Start from the initial peak in the base
    peak_idx = 0
    trough_idx = 0
    seeking_trough = True

    for i in range(1, n):
        if seeking_trough:
            if high[i] >= high[peak_idx] and (high[peak_idx] - low[trough_idx]) / max(high[peak_idx], 1e-12) < threshold:
                peak_idx = i
                trough_idx = i
            elif low[i] < low[trough_idx]:
                trough_idx = i
            elif (high[i] - low[trough_idx]) / max(low[trough_idx], 1e-12) >= threshold:
                depth = (high[peak_idx] - low[trough_idx]) / max(high[peak_idx], 1e-12)
                if depth >= threshold:
                    contractions.append((peak_idx, trough_idx, float(depth)))
                peak_idx = i
                trough_idx = i
                seeking_trough = False
        else:
            if high[i] > high[peak_idx]:
                peak_idx = i
            elif (high[peak_idx] - low[i]) / max(high[peak_idx], 1e-12) >= threshold:
                trough_idx = i
                seeking_trough = True

    if seeking_trough and trough_idx > peak_idx:
        depth = (high[peak_idx] - low[trough_idx]) / max(high[peak_idx], 1e-12)
        if depth >= threshold:
            contractions.append((peak_idx, trough_idx, float(depth)))
    return contractions


@PATTERNS.register("vcp")
class VcpDetector(PatternDetector):
    """Volatility Contraction Pattern (20-150d base, 2-4 tightening contractions).

    Hard conditions (0.0 if any fails):
    - Base length in [20, 150] trading days (at least 50 bars total for 50 DMA/vol).
    - Close[-1] > 50-day SMA and within 5% of base pivot (highest high).
    - 2 to 4 zig-zag contractions (threshold = max(3%, 0.8 * ATR%)),
      each contraction depth <= 0.70 * previous depth.
    - Last contraction depth <= 10%.
    - Mean volume in last contraction <= 0.80 * 50-day average volume.

    Sub-scores (clipped [0, 1], averaged):
    - Contraction count: 2 -> 0.70, 3 -> 0.90, 4 -> 1.00.
    - Tightness: clip((0.10 - last_depth) / 0.07, 0, 1)  (3% -> 1.0, 10% -> 0.0).
    - Volume dry-up: clip((1.0 - vol_ratio) / 0.4, 0, 1) (0.6 -> 1.0, 1.0 -> 0.0).
    - Proximity to pivot: clip((0.05 - dist) / 0.05, 0, 1) (0% -> 1.0, 5% -> 0.0).
    """

    name = "vcp"

    def score(self, df: pl.DataFrame) -> float:
        n = df.height
        if n < 50:
            return 0.0
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        close = df["close"].to_numpy()
        vol = df["volume"].to_numpy()

        sma50 = rolling_mean(close, 50)[-1]
        vol50 = rolling_mean(vol, 50)[-1]
        atr14 = wilder_atr(high, low, close, 14)[-1]
        if np.isnan(sma50) or np.isnan(vol50) or np.isnan(atr14) or vol50 <= 0 or close[-1] <= 0:
            return 0.0
        if close[-1] <= sma50:
            return 0.0

        atr_pct = atr14 / close[-1]
        zz_thresh = max(0.03, 0.8 * atr_pct)

        best = 0.0
        max_len = min(150, n)
        for length in range(20, max_len + 1, 5):
            start = n - length
            bh = high[start:]
            bl = low[start:]
            bv = vol[start:]
            pivot = float(np.max(bh))
            if pivot <= 0:
                continue
            dist = (pivot - float(close[-1])) / pivot
            if dist < 0.0 or dist > 0.05:
                continue

            cons = _extract_contractions(bh, bl, zz_thresh)
            if not (2 <= len(cons) <= 4):
                continue
            if any(cons[k][2] > 0.70 * cons[k - 1][2] for k in range(1, len(cons))):
                continue
            last_p, last_t, last_depth = cons[-1]
            if last_depth > 0.10:
                continue
            last_vol = float(np.mean(bv[last_p : max(last_t + 1, last_p + 1)]))
            vol_ratio = last_vol / float(vol50)
            if vol_ratio > 0.80:
                continue

            s_count = {2: 0.70, 3: 0.90, 4: 1.00}[len(cons)]
            s_tight = float(np.clip((0.10 - last_depth) / 0.07, 0.0, 1.0))
            s_vol = float(np.clip((1.0 - vol_ratio) / 0.40, 0.0, 1.0))
            s_prox = float(np.clip((0.05 - dist) / 0.05, 0.0, 1.0))
            cand = 0.25 * (s_count + s_tight + s_vol + s_prox)
            if cand > best:
                best = cand
        return best