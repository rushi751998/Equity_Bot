"""Exhaustion ladder, runner trail, hold score, soft exits, and time stop (Sections 7.7, 7.9)."""

from __future__ import annotations

import math
from typing import Any

from tfalgo.config import AppConfig
from tfalgo.regime.chop import check_time_stop
from tfalgo.strategy.base import EXIT_RULES, ExitRule, PositionState, round_down_tick


def compute_exhaustion_signals(ctx: dict[str, Any], cfg: AppConfig) -> dict[str, bool]:
    ex = cfg.exits.exhaustion
    s1 = float(ctx.get("ext_daily_atr", 0.0)) >= ex.ext_atr_daily

    bar_rng = float(ctx.get("hourly_range", 0.0))
    avg_rng = float(ctx.get("hourly_avg_range_20", 1.0))
    bar_vol = float(ctx.get("hourly_volume", 0.0))
    avg_vol = float(ctx.get("hourly_avg_vol_20", 1.0))
    close_pos = float(ctx.get("hourly_close_in_range", 0.5))
    s2 = (
        avg_rng > 0
        and avg_vol > 0
        and (bar_rng >= ex.climax_range_mult * avg_rng)
        and (bar_vol >= ex.climax_vol_mult * avg_vol)
        and (close_pos <= ex.climax_close_lower_frac)
    )
    s3 = int(ctx.get("bb_upper_streak", 0)) >= ex.parabolic_bb_closes
    s4 = (
        float(ctx.get("open_gap_daily_atr", 0.0)) >= ex.gapfail_atr
        and bool(ctx.get("below_day_open_within_window", False))
    )
    return {"S1": s1, "S2": s2, "S3": s3, "S4": s4}


def compute_hold_score(ctx: dict[str, Any]) -> int:
    """0-100 hold score after daily close (20 points per condition, Section 7.9)."""
    pts = 0
    if ctx.get("daily_close_above_ema9"):
        pts += 20
    if ctx.get("daily_ema9_above_ema21"):
        pts += 20
    if ctx.get("daily_ema21_slope_pos"):
        pts += 20
    if ctx.get("rs_line_ge_avg"):
        pts += 20
    if int(ctx.get("heavy_vol_down_days_5d", 2)) < 2:
        pts += 20
    return pts


@EXIT_RULES.register("ladder")
class LadderExitRule(ExitRule):
    name = "ladder"

    def evaluate(self, pos: PositionState, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
        p = cfg.exits.partials
        if not p.enabled or pos.entry_bar_count < 2:
            return {"sell_qty": 0, "new_stop": pos.current_stop, "new_stage": pos.ladder_stage}

        price = float(ctx["bar_close"])
        if pos.price_r(price) < p.gate_min_r:
            return {"sell_qty": 0, "new_stop": pos.current_stop, "new_stage": pos.ladder_stage}

        sigs = compute_exhaustion_signals(ctx, cfg)
        n_true = sum(sigs.values())
        if n_true == 0:
            return {"sell_qty": 0, "new_stop": pos.current_stop, "new_stage": pos.ladder_stage}

        base_qty = pos.ladder_base_qty or pos.total_qty
        min_runner = math.ceil(p.runner_min_frac * base_qty)
        new_stop = pos.current_stop
        if ctx.get("hourly_higher_low") is not None:
            new_stop = max(new_stop, round_down_tick(float(ctx["hourly_higher_low"]), cfg.session.tick_size))

        if n_true == 1:
            return {"sell_qty": 0, "new_stop": new_stop, "new_stage": pos.ladder_stage, "base_qty": base_qty}

        target_stage = 1 if n_true == 2 else 2
        if target_stage <= pos.ladder_stage:
            return {"sell_qty": 0, "new_stop": new_stop, "new_stage": pos.ladder_stage, "base_qty": base_qty}

        frac = sum(p.ladder[pos.ladder_stage : target_stage])
        sell_qty = min(math.floor(frac * base_qty), max(0, pos.total_qty - min_runner))
        if sell_qty * price < p.min_partial_value_inr:
            sell_qty = 0
        return {"sell_qty": sell_qty, "new_stop": new_stop, "new_stage": target_stage, "base_qty": base_qty}


@EXIT_RULES.register("runner")
class RunnerExitRule(ExitRule):
    name = "runner"

    def evaluate(self, pos: PositionState, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
        # Hard stop always checked first by execution/engine; here handle trailing stop & runner exits
        r = cfg.exits.runner
        new_stop = pos.current_stop
        if pos.carried and ctx.get("daily_ema21") is not None and ctx.get("daily_atr14") is not None:
            if ctx.get("daily_trend_confirmed"):
                trail = max(float(ctx["daily_ema21"]), pos.highest_high - r.chandelier_atr * float(ctx["daily_atr14"]))
                new_stop = max(new_stop, round_down_tick(trail, cfg.session.tick_size))
        return {"new_stop": new_stop, "exit_all": False, "reason": None}


@EXIT_RULES.register("hold_score")
class HoldScoreExitRule(ExitRule):
    name = "hold_score"

    def evaluate(self, pos: PositionState, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
        hs = compute_hold_score(ctx)
        if hs <= 20:
            return {"hold_score": hs, "exit_next_open": True, "new_stop": pos.current_stop, "reason": "hold_score_exit"}
        new_stop = pos.current_stop
        if hs <= 40 and ctx.get("hourly_higher_low") is not None:
            new_stop = max(new_stop, round_down_tick(float(ctx["hourly_higher_low"]), cfg.session.tick_size))
        return {"hold_score": hs, "exit_next_open": False, "new_stop": new_stop, "reason": None}


@EXIT_RULES.register("time_stop")
class TimeStopExitRule(ExitRule):
    name = "time_stop"

    def evaluate(self, pos: PositionState, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
        if not pos.carried:
            return {"exit_next_open": False, "reason": None}
        if pos.days_held >= cfg.carry.hold.max_trading_days:
            return {"exit_next_open": True, "reason": "max_hold_days"}
        hit, reason = check_time_stop(pos.days_held, pos.max_price_r, pos.days_since_new_high, cfg)
        return {"exit_next_open": hit, "reason": reason}


@EXIT_RULES.register("soft_exit")
class SoftExitRule(ExitRule):
    name = "soft_exit"

    def evaluate(self, pos: PositionState, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
        se = cfg.buffers.soft_exit
        if not se.enabled:
            return {"exit_next_open": False, "reason": None}
        if pos.hourly_below_ema20_streak >= se.confirm_closes:
            return {"exit_next_open": True, "reason": "hourly_close_below_ema20"}
        return {"exit_next_open": False, "reason": None}