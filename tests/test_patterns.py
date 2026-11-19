from datetime import date, timedelta

import numpy as np
import polars as pl

from tfalgo.indicators.patterns import PATTERNS, PatternDetector, evaluate_patterns


def _daily_df(closes: list[float], highs: list[float] | None = None,
              lows: list[float] | None = None, vols: list[float] | None = None) -> pl.DataFrame:
    n = len(closes)
    start = date(2024, 1, 1)
    dates = [start + timedelta(days=i) for i in range(n)]
    h = highs if highs is not None else [c * 1.01 for c in closes]
    lo = lows if lows is not None else [c * 0.99 for c in closes]
    v = vols if vols is not None else [1_000_000.0] * n
    return pl.DataFrame({"date": dates, "open": closes, "high": h, "low": lo, "close": closes, "volume": v})


def test_vcp_synthetic_scores_high_and_random_walk_near_zero():
    # 60-day uptrend followed by 3 tightening contractions (12%, 7%, 4%) with volume dry-up
    base_c = [100.0 + i * 0.6 for i in range(60)]
    base_h = [c * 1.01 for c in base_c]
    base_l = [c * 0.99 for c in base_c]
    base_v = [1_000_000.0] * 60

    # Pivot ~ 136 -> contraction 1 (~12%), contraction 2 (~7%), contraction 3 (~4%)
    c_pat = [
        136, 132, 126, 120, 125, 131, 135,   # -11.8%
        131, 128, 126, 130, 134, 135.5,      # -6.7%
        133, 131, 130.5, 133, 135.0,         # -3.7%
    ]
    h_pat = [x * 1.004 for x in c_pat]
    l_pat = [x * 0.996 for x in c_pat]
    v_pat = [800_000.0] * 13 + [450_000.0] * 5

    df = _daily_df(base_c + c_pat, base_h + h_pat, base_l + l_pat, base_v + v_pat)
    assert PATTERNS.get("vcp")().score(df) >= 0.70

    # V-shaped crash & rebound should fail VCP
    v_shape = _daily_df([100.0] * 50 + [90, 80, 70, 85, 100])
    assert PATTERNS.get("vcp")().score(v_shape) == 0.0


def test_flat_base_synthetic_scores_high_and_sanity_bound():
    c = [100.0 + i * 0.5 for i in range(55)] + [127.0 + (i % 3) * 0.5 for i in range(30)]
    df = _daily_df(c)
    assert PATTERNS.get("flat_base")().score(df) >= 0.70

    # Sanity bound: <= 5% of random-walk stock-days flagged
    rng = np.random.default_rng(42)
    rw = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.025, size=250))
    rw_df = _daily_df(rw.tolist())
    flagged = 0
    vcp = PATTERNS.get("vcp")()
    for i in range(60, 250):
        if vcp.score(rw_df.slice(0, i)) > 0:
            flagged += 1
    assert flagged / 190 <= 0.05


def test_pattern_extensibility_via_registry():
    @PATTERNS.register("dummy_test_pattern")
    class DummyPattern(PatternDetector):
        name = "dummy_test_pattern"

        def score(self, df: pl.DataFrame) -> float:
            return 0.88

    name, val = evaluate_patterns(_daily_df([100.0] * 60), {"dummy_test_pattern": True})
    assert name == "dummy_test_pattern" and val == 0.88