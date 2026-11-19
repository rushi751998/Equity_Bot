"""Pyramiding rules, stop ratcheting, and controlled-loss invariant (Section 7.6)."""

from __future__ import annotations

import math
from typing import Any

from tfalgo.config import AppConfig
from tfalgo.strategy.base import PYRAMID_RULES, PositionState, PyramidRule, TrancheFill, round_down_tick


def open_risk(tranches: tuple[TrancheFill, ...] | list[TrancheFill], stop_price: float) -> float:
    """Worst-case INR loss at `stop_price` across all tranches."""
    return sum(t.qty * max(0.0, t.entry_price - stop_price) for t in tranches)


def assert_controlled_loss_invariant(
    tranches: tuple[TrancheFill, ...] | list[TrancheFill],
    stop_price: float,
    initial_risk_budget: float,
    tol: float = 1e-6,
) -> None:
    loss = open_risk(tranches, stop_price)
    if loss > initial_risk_budget + tol:
        raise AssertionError(
            f"Controlled-loss invariant violated: open_risk={loss:.2f} > budget={initial_risk_budget:.2f}"
        )


@PYRAMID_RULES.register("breakout")
class BreakoutAddRule(PyramidRule):
    name = "breakout"

    def triggered(self, ctx: dict[str, Any], cfg: AppConfig) -> bool:
        return bool(ctx.get("fresh_15m_flag_breakout")) and float(ctx.get("rvol_pace", 0.0)) >= 1.0


@PYRAMID_RULES.register("pullback")
class PullbackAddRule(PyramidRule):
    name = "pullback"

    def triggered(self, ctx: dict[str, Any], cfg: AppConfig) -> bool:
        pa = cfg.pyramid.pullback_add
        return (
            bool(ctx.get("in_ema_band"))
            and float(ctx.get("pullback_depth_hatr", 99.0)) <= pa.max_depth_hatr
            and int(ctx.get("hourly_closes_below_ema20", 1)) == 0
            and bool(ctx.get("above_mini_15m_high"))
        )


def evaluate_add(
    pos: PositionState,
    add_price: float,
    add_score: float,
    hold_score: float,
    regime_label: str,
    ext_daily_atr: float,
    now_time_str: str,
    hourly_higher_low: float | None,
    atr15: float,
    equity: float,
    adv20: float,
    open_heat_inr: float,
    zone_factor: float,
    trigger_ok: bool,
    cfg: AppConfig,
) -> tuple[int, float, str | None]:
    """Return (add_qty, new_stop, skip_reason)."""
    p = cfg.pyramid
    if not p.enabled:
        return 0, pos.current_stop, "pyramid_disabled"

    add_idx = len(pos.tranches)  # 1 for add #1, 2 for add #2
    if add_idx >= len(cfg.sizing.tranches):
        return 0, pos.current_stop, "max_tranches_reached"

    min_r = p.add1_min_r if add_idx == 1 else p.add2_min_r
    if pos.price_r(add_price) < min_r:
        return 0, pos.current_stop, "insufficient_r"
    if add_score < cfg.score.zones.half:
        return 0, pos.current_stop, "add_score_low"
    if hold_score < p.min_hold_score:
        return 0, pos.current_stop, "hold_score_low"
    if regime_label == "LOW":
        return 0, pos.current_stop, "regime_low"
    if ext_daily_atr > p.max_extension_atr_daily:
        return 0, pos.current_stop, "overextended"
    if now_time_str > p.last_add_time:
        return 0, pos.current_stop, "past_last_add_time"
    if not trigger_ok:
        return 0, pos.current_stop, "no_add_trigger"

    # Ratchet stop first
    tick = cfg.session.tick_size
    cand_stop = max(pos.current_stop, pos.tranches[-1].entry_price)
    if hourly_higher_low is not None:
        hl_stop = round_down_tick(hourly_higher_low - cfg.stop.buffer_atr15 * atr15, tick)
        cand_stop = max(cand_stop, hl_stop)
    new_stop = round_down_tick(cand_stop, tick)

    if new_stop < pos.avg_entry or add_price <= new_stop:
        return 0, pos.current_stop, "cannot_raise_stop_to_breakeven"

    risk_after_move = open_risk(pos.tranches, new_stop)
    risk_headroom = pos.initial_risk_budget - risk_after_move
    if risk_headroom <= 0:
        return 0, pos.current_stop, "no_risk_headroom"

    max_heat_inr = equity * (cfg.portfolio.max_heat_pct / 100.0)
    heat_headroom = max_heat_inr - (open_heat_inr - open_risk(pos.tranches, pos.current_stop) + risk_after_move)
    eff_risk_headroom = min(risk_headroom, max(0.0, heat_headroom))

    max_pos_inr = equity * (cfg.sizing.max_position_pct / 100.0)
    existing_cost = sum(t.qty * t.entry_price for t in pos.tranches)
    cap_headroom_inr = max(0.0, max_pos_inr - existing_cost)

    liq_cap = math.floor(adv20 * (cfg.sizing.max_adv_participation_pct / 100.0))
    liq_headroom = max(0, liq_cap - pos.total_qty)

    planned_tranche = math.floor(cfg.sizing.tranches[add_idx] * pos.planned_full_qty)
    planned_scaled = math.floor(zone_factor * planned_tranche)

    by_risk = math.floor(eff_risk_headroom / (add_price - new_stop))
    by_cap = math.floor(cap_headroom_inr / add_price)
    add_qty = min(planned_scaled, by_risk, by_cap, liq_headroom)
    if add_qty <= 0:
        return 0, pos.current_stop, "sized_to_zero"

    new_tranches = (*pos.tranches, TrancheFill(add_qty, add_price, "MIS", pos.tranches[-1].fill_ts))
    assert_controlled_loss_invariant(new_tranches, new_stop, pos.initial_risk_budget)
    return add_qty, new_stop, None