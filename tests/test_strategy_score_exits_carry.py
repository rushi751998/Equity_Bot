from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tfalgo.config import AppConfig
from tfalgo.strategy.base import EXIT_RULES, PortfolioSnapshot, PositionState, SymbolState, TrancheFill
from tfalgo.strategy.carry import evaluate_carry
from tfalgo.strategy.exits import compute_hold_score
from tfalgo.strategy.risk import is_throttle_active, portfolio_allows_entry
from tfalgo.strategy.score import compute_entry_score

IST = ZoneInfo("Asia/Kolkata")


def _cfg(**over) -> AppConfig:
    base = {"run": {"start": "2024-01-01", "end": "2024-12-31"}}
    base.update(over)
    return AppConfig.model_validate(base)


def test_example_8_entry_score_zones_and_optional():
    cfg = _cfg()
    base_ctx = {
        "dma_stack_full": True, "slow_dma_rising": True, "rs_pct": 92.0,
        "pct_below_52w_high": 8.0, "ribbon_stack_ok": True, "ribbon_fanning": True,
        "pattern_quality": 0.75,
        "depth_hatr": 1.0, "depth_leg_frac": 0.25, "hourly_closes_below_ema20": 0,
        "vol_contraction_ratio": 0.7, "range_ratio_3bar": 0.8,
        "rvol_pace": 1.8, "close_in_bar_range": 0.91, "extension_hatr": 0.70, "gap_daily_atr": 0.4,
        "regime_label": "HIGH", "adtv_cr": 35.0, "atr_pct": 3.1, "stock_er": 0.45,
    }
    sc, zone, fac = compute_entry_score(base_ctx, cfg)
    assert sc == 81.0 and zone == "full" and fac == 1.0

    # Stock ER 0.25 (-4) -> 77, still full
    sc2, zone2, _ = compute_entry_score({**base_ctx, "stock_er": 0.25}, cfg)
    assert sc2 == 77.0 and zone2 == "full"

    # No pattern (-15) and rvol 1.2 (-2) -> 64, half
    sc3, zone3, fac3 = compute_entry_score({**base_ctx, "pattern_quality": 0.0, "rvol_pace": 1.2}, cfg)
    assert sc3 == 64.0 and zone3 == "half" and fac3 == 0.5

    # Optional sector_rs enabled (+4 earned, denom 104) -> 81.73
    cfg_opt = _cfg(score={"optional": {"sector_rs": True}})
    sc4, _, _ = compute_entry_score({**base_ctx, "sector_rs_ok": True}, cfg_opt)
    assert sc4 == pytest.approx(100.0 * 85.0 / 104.0)


def test_example_4_exhaustion_ladder():
    cfg = _cfg()
    t0 = datetime(2024, 1, 2, 9, 40, tzinfo=IST)
    pos = PositionState(
        symbol="S",
        tranches=(TrancheFill(59, 280.00, "CNC", t0),),
        initial_stop=276.25, current_stop=280.00, stop_source="swing",
        planned_full_qty=89, initial_risk_budget=500.0,
        entry_price_1=280.00, risk_per_share=3.75,
        carried=True, entry_bar_count=10,
    )
    ctx = {
        "bar_close": 318.00, "ext_daily_atr": 2.64,
        "hourly_range": 9.60, "hourly_avg_range_20": 3.80,
        "hourly_volume": 3100.0, "hourly_avg_vol_20": 1000.0,
        "hourly_close_in_range": 0.20, "bb_upper_streak": 0,
        "open_gap_daily_atr": 0.0, "below_day_open_within_window": False,
    }
    res = EXIT_RULES.get("ladder")().evaluate(pos, ctx, cfg)
    assert res["sell_qty"] == 14 and res["new_stage"] == 1


def test_example_5_carry_checklist():
    cfg = _cfg()
    ok, sell_q, cnc_q, fails = evaluate_carry(
        price_r=4.05, last_price=295.20, day_high=296.80, day_low=277.30,
        day_vol_pace=1.4, hourly_ribbon_ok=True, last_hourly_close=295.20,
        hourly_ema20=286.00, regime_label="HIGH", total_qty=87, cfg=cfg,
    )
    assert ok and sell_q == 28 and cnc_q == 59 and fails == []

    ok2, sell_q2, cnc_q2, fails2 = evaluate_carry(
        price_r=1.5, last_price=295.20, day_high=296.80, day_low=277.30,
        day_vol_pace=1.4, hourly_ribbon_ok=True, last_hourly_close=295.20,
        hourly_ema20=286.00, regime_label="HIGH", total_qty=87, cfg=cfg,
    )
    assert not ok2 and sell_q2 == 87 and cnc_q2 == 0 and "min_open_r" in fails2


def test_example_9_hold_score_and_portfolio_controls():
    cfg = _cfg()
    hs_day4 = compute_hold_score({
        "daily_close_above_ema9": True, "daily_ema9_above_ema21": True,
        "daily_ema21_slope_pos": True, "rs_line_ge_avg": False, "heavy_vol_down_days_5d": 1,
    })
    assert hs_day4 == 80

    hs_day5 = compute_hold_score({
        "daily_close_above_ema9": False, "daily_ema9_above_ema21": True,
        "daily_ema21_slope_pos": True, "rs_line_ge_avg": False, "heavy_vol_down_days_5d": 2,
    })
    assert hs_day5 == 40

    assert is_throttle_active([-0.5] * 10, False, cfg) is True
    assert is_throttle_active([-0.5] * 8 + [1.0, 1.0], True, cfg) is False

    snap = PortfolioSnapshot(equity=100_000.0, cash=50_000.0, open_positions=6,
                             open_heat_inr=1000.0, daily_pnl_pct=0.0, weekly_pnl_pct=0.0, entries_today=0)
    ok, reason = portfolio_allows_entry(SymbolState("X"), snap, "Auto", 0.2, 500.0, cfg)
    assert not ok and reason == "max_open_positions"