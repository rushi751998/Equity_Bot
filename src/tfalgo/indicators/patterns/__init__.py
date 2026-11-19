"""Daily chart pattern detectors (registered via PATTERNS)."""

from tfalgo.indicators.patterns import cup_handle, flat_base, high_tight_flag, vcp  # noqa: F401
from tfalgo.indicators.patterns.base import PATTERNS, PatternDetector, evaluate_patterns

__all__ = ["PATTERNS", "PatternDetector", "evaluate_patterns"]