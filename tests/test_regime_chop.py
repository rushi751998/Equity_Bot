from datetime import date, timedelta

from tfalgo.config import AppConfig, RunConfig
from tfalgo.regime.chop import (
    ShadowEvent,
    breakout_success_regime_points,
    check_time_stop,
    index_efficiency_points,
    stock_efficiency_penalty,
)
from tfalgo.regime.score import RegimeSnapshot, classify_regime


def _cfg(**over) -> AppConfig:
    base = {"run": {"start": "2024-01-01", "end": "2024-12-31"}}
    base.update(over)
    return AppConfig.model_validate(base)


def test_regime_example6_and_rescaling():
    # Example 6 (6-component form, chop off): score 4 / 5 -> HIGH
    cfg_no_chop = _cfg(chop={"breakout_success": {"enabled": False}, "efficiency": {"enabled": False}})
    snap = RegimeSnapshot(
        index_close=105.0, index_sma50=100.0, index_sma200=95.0,
        breadth_above_50dma_pct=58.0, net_new_highs_minus_lows=-12,
        vix_close=14.0, vix_sma20=16.0, dist_days_10d=2,
    )
    res = classify_regime(snap, cfg_no_chop)
    assert res.score == 4 and res.max_score == 5 and res.label == "HIGH" and res.multiplier == 1.0

    # With chop components (+1, +1) -> score 6 / 7 -> HIGH
    cfg_chop = _cfg()
    snap_c = RegimeSnapshot(
        index_close=105.0, index_sma50=100.0, index_sma200=95.0,
        breadth_above_50dma_pct=58.0, net_new_highs_minus_lows=-12,
        vix_close=14.0, vix_sma20=16.0, dist_days_10d=2,
        chop_breakout_pt=1, chop_index_er_pt=1,
    )
    res_c = classify_regime(snap_c, cfg_chop)
    assert res_c.score == 6 and res_c.label == "HIGH"

    # VIX and dist_days missing (no chop): max_score = 4 -> HIGH >= 4, MEDIUM >= 2, LOW < 2
    snap_m = RegimeSnapshot(
        index_close=105.0, index_sma50=100.0, index_sma200=95.0,
        breadth_above_50dma_pct=40.0, net_new_highs_minus_lows=-5,
    )
    res_m = classify_regime(snap_m, cfg_no_chop)
    assert res_m.max_score == 4 and res_m.score == 2 and res_m.label == "MEDIUM" and res_m.multiplier == 0.5

    # Disabled regime always returns HIGH
    assert classify_regime(snap_m, _cfg(regime={"enabled": False})).label == "HIGH"


def test_a1_shadow_breakout_no_lookahead():
    cfg = _cfg()
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(25)]
    # 8 events resolved on or before day 15 (4 wins = 50% >= 45% -> +1)
    # plus 4 future losses resolved on day 20 (MUST NOT leak to as_of=day 15)
    events = [
        ShadowEvent("A", days[i], 100.0, 97.0, resolved_date=days[10 + (i % 5)], success=(i < 4))
        for i in range(8)
    ] + [
        ShadowEvent("B", days[14], 100.0, 97.0, resolved_date=days[20], success=False)
        for _ in range(4)
    ]
    pt, rate, n = breakout_success_regime_points(events, days[15], days, cfg)
    assert (pt, n) == (1, 8) and rate == 0.5

    # Fewer than 8 resolved events -> 0
    pt_few, _, n_few = breakout_success_regime_points(events[:5], days[15], days, cfg)
    assert (pt_few, n_few) == (0, 5)


def test_a2_efficiency_and_a4_time_stop():
    cfg = _cfg()
    assert index_efficiency_points(0.31, cfg) == 1
    assert index_efficiency_points(0.20, cfg) == 0
    assert stock_efficiency_penalty(0.25, cfg) == -4.0
    assert stock_efficiency_penalty(0.35, cfg) == 0.0

    # Example 9 time stop: stall 5 days with R < 3.0 -> exit
    assert check_time_stop(days_held=5, max_price_r=1.6, days_since_new_high=5, cfg=cfg) == (True, "time_stop_stall")
    assert check_time_stop(days_held=3, max_price_r=0.5, days_since_new_high=2, cfg=cfg) == (True, "time_stop_no_progress")
    assert check_time_stop(days_held=5, max_price_r=3.2, days_since_new_high=6, cfg=cfg) == (False, None)