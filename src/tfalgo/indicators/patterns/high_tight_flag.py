"""High-tight-flag pattern detector (stub; disabled by default in v1)."""

from __future__ import annotations

import polars as pl

from tfalgo.indicators.patterns.base import PATTERNS, PatternDetector


@PATTERNS.register("high_tight_flag")
class HighTightFlagDetector(PatternDetector):
    """Stub for future high-tight-flag detector (returns 0.0 in v1)."""

    name = "high_tight_flag"

    def score(self, df: pl.DataFrame) -> float:
        return 0.0