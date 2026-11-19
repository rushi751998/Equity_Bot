from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tfalgo.backtest.engine import run_backtest_from_frames
from tfalgo.calendar import TradingCalendar
from tfalgo.config import AppConfig
from tfalgo.data.synthetic import make_intraday_5m
from tfalgo.execution.costs import FlatPctCostModel, ZerodhaCostModel
from tfalgo.execution.fills import NextOpenSlippageFillModel

IST = ZoneInfo("Asia/Kolkata")


def _cfg(**over) -> AppConfig:
    base = {"run": {"start": "2024-01-01", "end": "2024-03-31", "seed": 42}}
    base.update(over)
    return AppConfig.model_validate(base)


def test_example_4_zerodha_costs_and_example_1_flat_pct():
    z = ZerodhaCostModel("config/brokers/zerodha.yaml")
    # Example 4 delivery sell: 14 * 317.25 = 4441.50 -> ~19.95
    sell_fee = z.compute("SELL", "CNC", 4441.50, charge_dp=True)
    assert sell_fee == pytest.approx(19.95, abs=0.01)

    # Example 4 delivery buy: 35 * 280.00 = 9800.00 -> ~11.64
    buy_fee = z.compute("BUY", "CNC", 9800.00)
    assert buy_fee == pytest.approx(11.64, abs=0.01)

    # Example 1 flat-cost mode: 0.30% of 16,667 = 50.00
    f = FlatPctCostModel(0.30)
    assert f.compute("BUY", "CNC", 16_667.0) == pytest.approx(50.001, abs=0.01)


def test_fill_model_no_fill_first_2min_participation_and_stop_gap():
    cfg = _cfg()
    fm = NextOpenSlippageFillModel()

    # 09:16 (< 2 mins from 09:15) -> deferred
    r0 = fm.fill_order("BUY", 100, 100.0, 101.0, 99.0, 10_000.0, 9 * 60 + 16, 9 * 60 + 15, 2, 0.05, cfg.costs.slippage)
    assert r0.filled_qty == 0 and r0.skipped_reason == "no_fill_first_minutes"

    # 09:20 with 10% participation cap on 500 vol -> max 50 shares
    r1 = fm.fill_order("BUY", 100, 100.0, 100.4, 99.8, 500.0, 9 * 60 + 20, 9 * 60 + 15, 2, 0.05, cfg.costs.slippage)
    assert r1.filled_qty == 50 and r1.remaining_qty == 50 and r1.fill_price >= 100.0

    # Gap through stop: stop 100.0, bar opens 97.0 -> fills below 97.0
    r2 = fm.fill_order(
        "SELL", 50, 97.0, 98.0, 96.5, 1000.0, 9 * 60 + 15, 9 * 60 + 15, 2, 0.05,
        cfg.costs.slippage, is_stop=True, stop_price=100.0,
    )
    assert r2.filled_qty == 50 and r2.fill_price < 97.0


def test_engine_determinism_and_smoke(tmp_path):
    cfg = _cfg()
    cal = TradingCalendar()
    s1 = make_intraday_5m(date(2024, 1, 1), 35, seed=10, drift=0.002)
    bench = make_intraday_5m(date(2024, 1, 1), 35, seed=99, drift=0.001)

    res1 = run_backtest_from_frames(cfg, {"AAA": s1}, bench, cal, output_dir=tmp_path / "r1")
    res2 = run_backtest_from_frames(cfg, {"AAA": s1}, bench, cal, output_dir=tmp_path / "r2")

    assert res1.equity.equals(res2.equity)
    assert (tmp_path / "r1" / "trades.csv").exists()
    assert (tmp_path / "r1" / "equity.csv").exists()
    assert (tmp_path / "r1" / "summary.txt").exists()
    assert "Survivorship bias" in (tmp_path / "r1" / "summary.txt").read_text(encoding="utf-8")

def test_strategy_extensibility_and_prepared_reuse(tmp_path):
    from tfalgo.backtest.engine import prepare_market_data
    from tfalgo.strategy.base import STRATEGIES, OrderIntent, Strategy

    @STRATEGIES.register("dummy_test_strat")
    class DummyStrat(Strategy):
        name = "dummy_test_strat"

        def on_bar(self, state, ctx, portfolio, cfg):
            if cfg.strategy.params.get("buy_once") and state.entries_today == 0 and ctx["bar_time_str"] == "09:30":
                px = ctx["bar_close"]
                return state, [OrderIntent(
                    state.symbol, "BUY", 10, reason="dummy",
                    meta={"swing_low": px * 0.97, "atr15": 1.0, "hourly_atr": 2.0,
                          "planned_full_qty": 10, "risk_budget": 500.0, "planned_full_risk": 500.0,
                          "entry_score": 80.0, "score_zone": "full", "pattern": "dummy",
                          "pattern_quality": 1.0, "bound_constraint": "risk"},
                )]
            return state, []

    cfg = _cfg(strategy={"name": "dummy_test_strat", "params": {"buy_once": True}})
    cal = TradingCalendar()
    s1 = make_intraday_5m(date(2024, 1, 1), 35, seed=10, drift=0.002)
    bench = make_intraday_5m(date(2024, 1, 1), 35, seed=99, drift=0.001)
    prep = prepare_market_data(cfg, {"AAA": s1}, bench, cal)
    res = run_backtest_from_frames(cfg, {"AAA": s1}, bench, cal, output_dir=tmp_path / "dum", prepared=prep)
    assert res.equity.height > 0