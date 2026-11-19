from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tfalgo.config import AppConfig
from tfalgo.strategy.base import PositionState, TrancheFill, round_down_tick, round_up_tick
from tfalgo.strategy.pyramiding import assert_controlled_loss_invariant, evaluate_add, open_risk
from tfalgo.strategy.sizing import SIZING_RULES, STOP_RULES

IST = ZoneInfo("Asia/Kolkata")


def _cfg(**over) -> AppConfig:
    base = {"run": {"start": "2024-01-01", "end": "2024-12-31"}}
    base.update(over)
    return AppConfig.model_validate(base)


def test_tick_rounding_directions():
    assert round_up_tick(279.91) == 279.95
    assert round_down_tick(276.28) == 276.25
    assert round_down_tick(284.98) == 284.95


def test_examples_2_2b_2c_stop_and_sizing():
    cfg = _cfg()
    stop_rule = STOP_RULES.get("swing_low_with_fallback")()
    sizer = SIZING_RULES.get("risk_cap_liquidity")()

    # Example 2: swing stop 276.25, cap binds -> full 89, tranche1 35
    s2 = stop_rule.compute(280.00, 276.40, 1.20, 3.00, cfg)
    assert s2["valid"] and s2["stop_source"] == "swing" and s2["stop_price"] == 276.25
    z2 = sizer.size(100_000.0, 280.00, s2["stop_price"], 200_000.0, 1.0, 1.0, 1.0, cfg)
    assert z2["planned_full_qty"] == 89 and z2["tranche1_qty"] == 35 and z2["bound_constraint"] == "cap"

    # Example 2b: swing low 270.00 -> stop 269.85 -> risk binds -> full 49, tranche1 19
    s2b = stop_rule.compute(280.00, 270.00, 1.20, 3.00, cfg)
    assert s2b["stop_price"] == 269.85 and s2b["stop_source"] == "swing"
    z2b = sizer.size(100_000.0, 280.00, s2b["stop_price"], 200_000.0, 1.0, 1.0, 1.0, cfg)
    assert z2b["planned_full_qty"] == 49 and z2b["tranche1_qty"] == 19 and z2b["bound_constraint"] == "risk"

    # Example 2c: swing low 265.00 (>5%) -> fallback fixed 271.60 -> full 59, tranche1 23
    s2c = stop_rule.compute(280.00, 265.00, 1.20, 3.00, cfg)
    assert s2c["stop_price"] == 271.60 and s2c["stop_source"] == "fallback_fixed"
    z2c = sizer.size(100_000.0, 280.00, s2c["stop_price"], 200_000.0, 1.0, 1.0, 1.0, cfg)
    assert z2c["planned_full_qty"] == 59 and z2c["tranche1_qty"] == 23

    # Example 2c ATR fallback variant: 280 - 3*3 = 271.00 -> full 55, tranche1 22
    cfg_atr = _cfg(stop={"fallback": {"type": "atr"}})
    s2c_atr = stop_rule.compute(280.00, 265.00, 1.20, 3.00, cfg_atr)
    assert s2c_atr["stop_price"] == 271.00 and s2c_atr["stop_source"] == "fallback_atr"
    z2c_atr = sizer.size(100_000.0, 280.00, s2c_atr["stop_price"], 200_000.0, 1.0, 1.0, 1.0, cfg_atr)
    assert z2c_atr["planned_full_qty"] == 55 and z2c_atr["tranche1_qty"] == 22


def test_example_3_pyramiding_and_zone_scaling():
    cfg = _cfg()
    t0 = datetime(2024, 1, 2, 9, 40, tzinfo=IST)
    pos = PositionState(
        symbol="S",
        tranches=(TrancheFill(35, 280.00, "MIS", t0),),
        initial_stop=276.25,
        current_stop=276.25,
        stop_source="swing",
        planned_full_qty=89,
        initial_risk_budget=500.0,
        entry_price_1=280.00,
        risk_per_share=3.75,
    )
    # Add #1 at 284.40, score 78 -> qty 35, stop raised to 280.00, open risk 154.00
    q1, st1, r1 = evaluate_add(
        pos, 284.40, 78.0, 100.0, "HIGH", 1.0, "11:00", None, 1.20,
        100_000.0, 200_000.0, 131.25, 1.0, True, cfg,
    )
    assert (q1, st1, r1) == (35, 280.00, None)
    pos2 = PositionState(
        **{**pos.__dict__, "tranches": (*pos.tranches, TrancheFill(35, 284.40, "MIS", t0)), "current_stop": st1}
    )
    assert open_risk(pos2.tranches, st1) == pytest.approx(154.00)

    # Add #2 at 289.10, score 81, hourly HL 285.10 -> stop 284.95, qty 17, open risk 70.55
    q2, st2, r2 = evaluate_add(
        pos2, 289.10, 81.0, 100.0, "HIGH", 1.0, "13:00", 285.10, 1.20,
        100_000.0, 200_000.0, 154.00, 1.0, True, cfg,
    )
    assert (q2, st2, r2) == (17, 284.95, None)
    assert open_risk((*pos2.tranches, TrancheFill(17, 289.10, "MIS", t0)), st2) == pytest.approx(70.55)

    # Score 72 (half zone) -> floor(0.5 * 17) = 8; score 55 -> rejected
    q2_half, _, _ = evaluate_add(
        pos2, 289.10, 72.0, 100.0, "HIGH", 1.0, "13:00", 285.10, 1.20,
        100_000.0, 200_000.0, 154.00, 0.5, True, cfg,
    )
    assert q2_half == 8
    q2_low, _, r_low = evaluate_add(
        pos2, 289.10, 55.0, 100.0, "HIGH", 1.0, "13:00", 285.10, 1.20,
        100_000.0, 200_000.0, 154.00, 0.0, True, cfg,
    )
    assert q2_low == 0 and r_low == "add_score_low"


@given(
    add_price=st.floats(min_value=285.0, max_value=320.0),
    hl=st.floats(min_value=280.5, max_value=284.5),
)
@settings(max_examples=40)
def test_controlled_loss_invariant_property(add_price, hl):
    cfg = _cfg()
    t0 = datetime(2024, 1, 2, 9, 40, tzinfo=IST)
    pos = PositionState(
        symbol="S",
        tranches=(TrancheFill(35, 280.00, "MIS", t0),),
        initial_stop=276.25,
        current_stop=276.25,
        stop_source="swing",
        planned_full_qty=89,
        initial_risk_budget=500.0,
        entry_price_1=280.00,
        risk_per_share=3.75,
    )
    q, st_new, _ = evaluate_add(
        pos, add_price, 80.0, 100.0, "HIGH", 1.0, "11:00", hl, 1.20,
        100_000.0, 200_000.0, 131.25, 1.0, True, cfg,
    )
    if q > 0:
        assert_controlled_loss_invariant((*pos.tranches, TrancheFill(q, add_price, "MIS", t0)), st_new, 500.0)