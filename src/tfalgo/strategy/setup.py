"""Daily gate and hourly pullback setup evaluation."""

from __future__ import annotations

from typing import Any

from tfalgo.config import AppConfig
from tfalgo.strategy.base import SETUP_RULES, SetupRule


def daily_gate_ok(ctx: dict[str, Any], cfg: AppConfig) -> tuple[bool, str | None]:
    """Pre-open daily gate (Section 7.2)."""
    if not ctx.get("eligible", False):
        return False, "ineligible"
    if not ctx.get("above_200dma", False):
        return False, "close_below_200dma"
    if ctx.get("regime_label", "LOW") == "LOW":
        return False, "regime_low"
    return True, None


@SETUP_RULES.register("pullback_flag")
class PullbackFlagSetup(SetupRule):
    """Hourly pullback setup (Section 7.3): structural validity + scored metrics."""

    name = "pullback_flag"

    def evaluate(self, ctx: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
        leg_valid = bool(ctx.get("leg_valid", False))
        leg_high = ctx.get("leg_high")
        leg_low = ctx.get("leg_low")
        pb_low = ctx.get("pullback_low")
        hatr = ctx.get("hourly_atr")

        if not leg_valid or leg_high is None or pb_low is None or hatr is None or hatr <= 0:
            return {"valid": False, "depth_hatr": None, "depth_leg_frac": None}

        depth = float(leg_high) - float(pb_low)
        depth_hatr = depth / float(hatr)
        leg_range = float(leg_high) - float(leg_low) if leg_low is not None else 0.0
        depth_leg_frac = depth / leg_range if leg_range > 0 else 1.0

        return {
            "valid": True,
            "depth_hatr": depth_hatr,
            "depth_leg_frac": depth_leg_frac,
            "hourly_closes_below_ema20": int(ctx.get("hourly_closes_below_ema20", 0)),
            "vol_contraction_ratio": float(ctx.get("vol_contraction_ratio", 1.0)),
            "range_ratio_3bar": float(ctx.get("range_ratio_3bar", 1.0)),
            "ribbon_stack_ok": bool(ctx.get("ribbon_stack_ok", False)),
            "ribbon_compressed": bool(ctx.get("ribbon_compressed", False)),
            "ribbon_fanning": bool(ctx.get("ribbon_fanning", False)),
        }