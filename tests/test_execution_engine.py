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

def test_trade_metrics_all_21_fields():
    from tfalgo.backtest.metrics import compute_trade_metrics, format_trade_summary
    from tfalgo.backtest.portfolio import TradeRecord

    t0 = datetime(2024, 1, 2, 9, 30, tzinfo=IST)

    def _tr(tid: int, pnl: float, mr: float, days: int, bound: str = "risk") -> TradeRecord:
        return TradeRecord(
            trade_id=tid, symbol="AAA", entry_ts=t0, exit_ts=t0, product_path="MIS",
            tranche_fills=1, avg_entry=100.0, avg_exit=100.0, qty_peak=10,
            initial_stop=97.0, stop_source="swing", risk_per_share=3.0,
            planned_full_risk_inr=500.0, price_r_max=mr, mae_r=0.0, mfe_r=mr,
            gross_pnl=pnl, fees=0.0, slippage_cost=0.0, net_pnl=pnl, money_r=mr,
            exit_reason="stop_hit", regime_at_entry="HIGH", entry_score=80.0,
            score_zone="full", pattern="vcp", pattern_quality=0.8, add_scores="",
            hold_score_min=80, time_stop_flag=False, bound_constraint=bound,
            hold_days=days, gap_loss_flag=False,
        )

    trades = [
        _tr(1, 1000.0, 2.0, 4, "cap"),
        _tr(2, 500.0, 1.0, 2),
        _tr(3, -300.0, -0.6, 1),
        _tr(4, 0.0, 0.0, 3),     # breakeven counts as losing
        _tr(5, -200.0, -0.4, 2),
    ]
    m = compute_trade_metrics(trades)
    assert m["total_closed_campaigns"] == 5
    assert m["winning_trades"] == 2
    assert m["losing_trades"] == 3
    assert m["win_rate_pct"] == pytest.approx(40.0)
    assert m["avg_win_inr"] == pytest.approx(750.0)
    assert m["avg_loss_inr"] == pytest.approx(-500.0 / 3.0)
    assert m["payoff_ratio"] == pytest.approx(4.5)
    assert m["expectancy_inr"] == pytest.approx(200.0)
    assert m["expectancy_r"] == pytest.approx(0.4)
    assert m["gross_profit_inr"] == pytest.approx(1500.0)
    assert m["gross_loss_inr"] == pytest.approx(-500.0)
    assert m["profit_factor"] == pytest.approx(3.0)
    assert m["best_trade_inr"] == pytest.approx(1000.0)
    assert m["best_trade_r"] == pytest.approx(2.0)
    assert m["worst_trade_inr"] == pytest.approx(-300.0)
    assert m["worst_trade_r"] == pytest.approx(-0.6)
    assert m["max_consecutive_wins"] == 2
    assert m["max_consecutive_losses"] == 3
    assert m["avg_hold_days_winners"] == pytest.approx(3.0)
    assert m["avg_hold_days_losers"] == pytest.approx(2.0)
    assert m["avg_hold_days_all"] == pytest.approx(2.4)
    assert "Profit Factor" in format_trade_summary(m)