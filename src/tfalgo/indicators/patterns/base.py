"""Pattern detector ABC, registry, and evaluation helper.

Adding a new pattern requires:
1. Subclass `PatternDetector` in `src/tfalgo/indicators/patterns/<name>.py`.
2. Decorate with `@PATTERNS.register("<name>")`.
3. Import it in `patterns/__init__.py` and enable it in YAML under `score.patterns`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import polars as pl

from tfalgo.registry import Registry


class PatternDetector(ABC):
    """Evaluates a completed daily-bar DataFrame and returns quality in [0.0, 1.0]."""

    name: str = ""

    @abstractmethod
    def score(self, df: pl.DataFrame) -> float:
        """Return pattern quality in [0.0, 1.0] at the last row of `df` (0.0 if invalid)."""


PATTERNS: Registry[PatternDetector] = Registry("pattern detector")


def evaluate_patterns(
    df: pl.DataFrame,
    enabled: dict[str, bool],
) -> tuple[str | None, float]:
    """Run all enabled registered patterns on `df`; return (best_name, best_score)."""
    best_name: str | None = None
    best_score = 0.0
    for name, is_on in enabled.items():
        if not is_on:
            continue
        detector = PATTERNS.get(name)()
        val = float(max(0.0, min(1.0, detector.score(df))))
        if val > best_score:
            best_score = val
            best_name = name
    return best_name, best_score