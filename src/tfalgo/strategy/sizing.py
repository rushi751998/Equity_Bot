"""Initial stop placement and position sizing (Section 7.5)."""

from __future__ import annotations

import math
from typing import Any

from tfalgo.config import AppConfig
from tfalgo.strategy.base import SIZING_RULES, STOP_RULES, SizingRule, StopRule, round_down_tick


def _apply_min_floor(entry: float, stop: float, atr15: float, cfg: AppConfig) -> tuple[float, bool]:
    tick = cfg.session.tick_size
    md = cfg.stop.min_distance
    min_dist = max(md.atr15_mult * atr15, entry * md.spread_floor_bps / 10_000.0)
    if (entry - stop) < min_dist:
        stop = round_down_tick(entry - min_dist, tick)
    dist_pct = (entry - stop) / entry * 100.0 if entry > 0 else 999.0
    return stop, dist_pct <= cfg.stop.max_swing_stop_pct


@STOP_RULES.register("swing_low_with_fallback")
class SwingLowWithFallbackStop(StopRule):
    name = "swing_low_with_fallback"

    def compute(self, entry_price: float, swing_low: float, atr15: float,
                hourly_atr14: float, cfg: AppConfig) -> dict[str, Any]:
        tick = cfg.session.tick_size
        max_pct = cfg.stop.max_swing_stop_pct
        swing_stop = round_down_tick(swing_low - cfg.stop.buffer_atr15 * atr15, tick)
        dist_pct = (entry_price - swing_stop) / entry_price * 100.0

        if 0 < dist_pct <= max_pct:
            final_stop, ok = _apply_min_floor(entry_price, swing_stop, atr15, cfg)
            return {
                "valid": ok,
                "stop_price": final_stop,
                "stop_source": "swing",
                "dist_pct": (entry_price - final_stop) / entry_price * 100.0,
            }

        fb = cfg.stop.fallback
        if fb.type == "skip":
            return {"valid": False, "stop_price": None, "stop_source": "skip", "dist_pct": dist_pct}
        if fb.type == "fixed_pct":
            fb_stop = round_down_tick(entry_price * (1.0 - fb.fixed_pct / 100.0), tick)
            final_stop, ok = _apply_min_floor(entry_price, fb_stop, atr15, cfg)
            return {
                "valid": ok,
                "stop_price": final_stop,
                "stop_source": "fallback_fixed",
                "dist_pct": (entry_price - final_stop) / entry_price * 100.0,
            }
        # fallback == "atr"
        fb_stop = round_down_tick(entry_price - fb.atr.mult * hourly_atr14, tick)
        final_stop, ok = _apply_min_floor(entry_price, fb_stop, atr15, cfg)
        return {
            "valid": ok,
            "stop_price": final_stop,
            "stop_source": "fallback_atr",
            "dist_pct": (entry_price - final_stop) / entry_price * 100.0,
        }


@STOP_RULES.register("fixed_pct")
class FixedPctStop(StopRule):
    name = "fixed_pct"

    def compute(self, entry_price: float, swing_low: float, atr15: float,
                hourly_atr14: float, cfg: AppConfig) -> dict[str, Any]:
        tick = cfg.session.tick_size
        stop = round_down_tick(entry_price * (1.0 - cfg.stop.fallback.fixed_pct / 100.0), tick)
        final_stop, ok = _apply_min_floor(entry_price, stop, atr15, cfg)
        return {
            "valid": ok,
            "stop_price": final_stop,
            "stop_source": "fixed_pct",
            "dist_pct": (entry_price - final_stop) / entry_price * 100.0,
        }


@STOP_RULES.register("atr")
class AtrStop(StopRule):
    name = "atr"

    def compute(self, entry_price: float, swing_low: float, atr15: float,
                hourly_atr14: float, cfg: AppConfig) -> dict[str, Any]:
        tick = cfg.session.tick_size
        stop = round_down_tick(entry_price - cfg.stop.fallback.atr.mult * hourly_atr14, tick)
        final_stop, ok = _apply_min_floor(entry_price, stop, atr15, cfg)
        return {
            "valid": ok,
            "stop_price": final_stop,
            "stop_source": "atr",
            "dist_pct": (entry_price - final_stop) / entry_price * 100.0,
        }


@SIZING_RULES.register("risk_cap_liquidity")
class RiskCapLiquiditySizing(SizingRule):
    name = "risk_cap_liquidity"

    def size(self, equity: float, entry_price: float, stop_price: float, adv20: float,
             regime_mult: float, throttle_mult: float, zone_factor: float,
             cfg: AppConfig) -> dict[str, Any]:
        rps = entry_price - stop_price
        if rps <= 0 or entry_price <= 0:
            return {"planned_full_qty": 0, "tranche1_qty": 0, "risk_per_share": 0.0,
                    "risk_budget_inr": 0.0, "bound_constraint": "invalid_stop"}

        s = cfg.sizing
        risk_budget = equity * (s.risk_per_trade_pct / 100.0) * regime_mult * throttle_mult
        by_risk = math.floor(risk_budget / rps)
        by_cap = math.floor((equity * s.max_position_pct / 100.0) / entry_price)
        by_liq = math.floor(adv20 * (s.max_adv_participation_pct / 100.0))

        full_qty = min(by_risk, by_cap, by_liq)
        if full_qty == by_cap and by_cap <= by_risk and by_cap <= by_liq:
            bound = "cap"
        elif full_qty == by_liq and by_liq <= by_risk:
            bound = "liquidity"
        else:
            bound = "risk"

        t1 = math.floor(math.floor(s.tranches[0] * full_qty) * zone_factor)
        return {
            "planned_full_qty": full_qty,
            "tranche1_qty": t1,
            "risk_per_share": rps,
            "risk_budget_inr": risk_budget,
            "planned_full_risk_inr": full_qty * rps,
            "bound_constraint": bound,
        }