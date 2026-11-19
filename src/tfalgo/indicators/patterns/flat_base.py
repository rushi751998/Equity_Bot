"""Flat base pattern detector."""

from __future__ import annotations

import numpy as np
import polars as pl

from tfalgo.indicators._np import rolling_mean
from tfalgo.indicators.patterns.base import PATTERNS, PatternDetector


@PATTERNS.register("flat_base")
class FlatBaseDetector(PatternDetector):
    """Flat Base detector (>= 25 trading days, depth <= 15%).

    Hard conditions (0.0 if any fails):
    - At least 50 daily bars (for 50-day SMA) and base length in [25, 100] days.
    - Close[-1] > 50-day SMA.
    - Base depth (base_high - base_low) / base_high <= 0.15.
    - Close[-1] within 5% of base_high.

    Sub-scores (clipped [0, 1], averaged):
    - Depth tightness: clip((0.15 - depth) / 0.10, 0, 1)  (5% -> 1.0, 15% -> 0.0).
    - Proximity to base high: clip((0.05 - dist) / 0.05, 0, 1) (0% -> 1.0, 5% -> 0.0).
    - Duration: clip(length / 50.0, 0.5, 1.0) (25d -> 0.5, >=50d -> 1.0).
    """

    name = "flat_base"

    def score(self, df: pl.DataFrame) -> float:
        n = df.height
        if n < 50:
            return 0.0
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        close = df["close"].to_numpy()

        sma50 = rolling_mean(close, 50)[-1]
        if np.isnan(sma50) or close[-1] <= sma50:
            return 0.0

        best = 0.0
        max_len = min(100, n)
        for length in range(25, max_len + 1, 5):
            start = n - length
            b_hi = float(np.max(high[start:]))
            b_lo = float(np.min(low[start:]))
            if b_hi <= 0:
                continue
            depth = (b_hi - b_lo) / b_hi
            if depth > 0.15:
                continue
            dist = (b_hi - float(close[-1])) / b_hi
            if dist < 0.0 or dist > 0.05:
                continue

            s_depth = float(np.clip((0.15 - depth) / 0.10, 0.0, 1.0))
            s_prox = float(np.clip((0.05 - dist) / 0.05, 0.0, 1.0))
            s_dur = float(np.clip(length / 50.0, 0.5, 1.0))
            cand = (s_depth + s_prox + s_dur) / 3.0
            if cand > best:
                best = cand
        return best