"""Cup-with-handle pattern detector (stub; disabled by default in v1)."""

from __future__ import annotations

import polars as pl

from tfalgo.indicators.patterns.base import PATTERNS, PatternDetector


@PATTERNS.register("cup_handle")
class CupHandleDetector(PatternDetector):
    """Stub for future cup-with-handle detector (returns 0.0 in v1)."""

    name = "cup_handle"

    def score(self, df: pl.DataFrame) -> float:
        return 0.0