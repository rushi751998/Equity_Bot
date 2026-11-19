"""Vetoes, entry score blocks, normalisation, and score zones (Section 7.4a)."""

from __future__ import annotations

from typing import Any

from tfalgo.config import AppConfig
from tfalgo.regime.chop import stock_efficiency_penalty
from tfalgo.strategy.base import SCORE_BLOCKS, VETOES, ScoreBlock, Veto


@VETOES.register("liquidity")
class LiquidityVeto(Veto):
    name = "liquidity"

    def check(self, ctx: dict[str, Any], cfg: AppConfig) -> tuple[bool, str | None]:
        ok = ctx.get("adtv_cr", 0.0) >= cfg.universe.min_adtv_cr and ctx.get("eligible", False)
        return (True, None) if ok else (False, "liquidity")


@VETOES.register("regime_low")
class RegimeLowVeto(Veto):
    name = "regime_low"

    def check(self, ctx: dict[str, Any], cfg: AppConfig) -> tuple[bool, str | None]:
        if cfg.regime.enabled and ctx.get("regime_label") == "LOW":
            return False, "regime_low"
        return True, None


@VETOES.register("close_below_200dma")
class CloseBelow200DmaVeto(Veto):
    name = "close_below_200dma"

    def check(self, ctx: dict[str, Any], cfg: AppConfig) -> tuple[bool, str | None]:
        return (True, None) if ctx.get("above_200dma", False) else (False, "close_below_200dma")


@VETOES.register("extension_gt_2_5_hatr")
class ExtensionVeto(Veto):
    name = "extension_gt_2_5_hatr"

    def check(self, ctx: dict[str, Any], cfg: AppConfig) -> tuple[bool, str | None]:
        ext = float(ctx.get("extension_hatr", 0.0))
        return (True, None) if ext <= 2.5 else (False, "extension_gt_2_5_hatr")


@VETOES.register("stop_too_wide")
class StopTooWideVeto(Veto):
    name = "stop_too_wide"

    def check(self, ctx: dict[str, Any], cfg: AppConfig) -> tuple[bool, str | None]:
        return (True, None) if ctx.get("stop_valid", True) else (False, "stop_too_wide")


@VETOES.register("data_gaps")
class DataGapsVeto(Veto):
    name = "data_gaps"

    def check(self, ctx: dict[str, Any], cfg: AppConfig) -> tuple[bool, str | None]:
        return (True, None) if ctx.get("data_gaps_ok", True) else (False, "data_gaps")


@SCORE_BLOCKS.register("trend_quality")
class TrendQualityBlock(ScoreBlock):
    name = "trend_quality"
    max_points = 25.0

    def score(self, ctx: dict[str, Any], cfg: AppConfig) -> float:
        pts = 0.0
        if ctx.get("dma_stack_full") and ctx.get("slow_dma_rising"):
            pts += 8.0
        elif ctx.get("dma_stack_partial"):
            pts += 4.0

        rs_pct = ctx.get("rs_pct")
        if rs_pct is not None:
            if rs_pct >= 90:
                pts += 8.0
            elif rs_pct >= 80:
                pts += 6.0
            elif rs_pct >= 70:
                pts += 3.0

        below_52w = ctx.get("pct_below_52w_high")
        if below_52w is not None:
            if below_52w <= 10.0:
                pts += 5.0
            elif below_52w <= 25.0:
                pts += 3.0

        if ctx.get("ribbon_stack_ok"):
            pts += 4.0 if ctx.get("ribbon_fanning") else 2.0
        return pts


@SCORE_BLOCKS.register("base_pattern")
class BasePatternBlock(ScoreBlock):
    name = "base_pattern"
    max_points = 20.0

    def score(self, ctx: dict[str, Any], cfg: AppConfig) -> float:
        q = float(ctx.get("pattern_quality", 0.0))
        return 20.0 * max(0.0, min(1.0, q))


@SCORE_BLOCKS.register("setup_tightness")
class SetupTightnessBlock(ScoreBlock):
    name = "setup_tightness"
    max_points = 15.0

    def score(self, ctx: dict[str, Any], cfg: AppConfig) -> float:
        pts = 0.0
        d_hatr = ctx.get("depth_hatr")
        d_leg = ctx.get("depth_leg_frac")
        pb = cfg.setup.pullback
        if d_hatr is not None and d_leg is not None:
            if pb.min_depth_hatr <= d_hatr <= pb.max_depth_hatr and d_leg <= pb.max_depth_leg_frac:
                pts += 5.0
            elif d_hatr <= 2.0:
                pts += 2.0

        below_cnt = int(ctx.get("hourly_closes_below_ema20", 99))
        if below_cnt == 0:
            pts += 4.0
        elif below_cnt == 1:
            pts += 1.0

        vr = float(ctx.get("vol_contraction_ratio", 99.0))
        if vr <= pb.volume_contraction:
            pts += 3.0
        elif vr <= 1.0:
            pts += 1.0

        rr = float(ctx.get("range_ratio_3bar", 99.0))
        if rr <= cfg.setup.tightness.max_range_ratio:
            pts += 3.0
        return pts


@SCORE_BLOCKS.register("trigger_quality")
class TriggerQualityBlock(ScoreBlock):
    name = "trigger_quality"
    max_points = 15.0

    def score(self, ctx: dict[str, Any], cfg: AppConfig) -> float:
        pts = 0.0
        rvol = float(ctx.get("rvol_pace", 0.0))
        if rvol >= 2.0:
            pts += 6.0
        elif rvol >= 1.5:
            pts += 4.0
        elif rvol >= 1.2:
            pts += 2.0

        pos = float(ctx.get("close_in_bar_range", 0.0))
        if pos >= 0.75:
            pts += 3.0
        elif pos >= 0.60:
            pts += 1.0

        ext = float(ctx.get("extension_hatr", 99.0))
        if ext <= 0.75:
            pts += 3.0
        elif ext <= 1.5:
            pts += 2.0

        gap = abs(float(ctx.get("gap_daily_atr", 0.0)))
        if gap <= 1.0:
            pts += 3.0
        elif gap <= 1.5:
            pts += 1.0
        return pts


@SCORE_BLOCKS.register("regime")
class RegimeScoreBlock(ScoreBlock):
    name = "regime"
    max_points = 10.0

    def score(self, ctx: dict[str, Any], cfg: AppConfig) -> float:
        lbl = ctx.get("regime_label", "LOW")
        return 10.0 if lbl == "HIGH" else (5.0 if lbl == "MEDIUM" else 0.0)


@SCORE_BLOCKS.register("liquidity_range")
class LiquidityRangeBlock(ScoreBlock):
    name = "liquidity_range"
    max_points = 5.0

    def score(self, ctx: dict[str, Any], cfg: AppConfig) -> float:
        pts = 0.0
        adtv = float(ctx.get("adtv_cr", 0.0))
        if adtv >= 50.0:
            pts += 3.0
        elif adtv >= 20.0:
            pts += 2.0

        atr_pct = float(ctx.get("atr_pct", 0.0))
        if atr_pct >= 3.5:
            pts += 2.0
        elif atr_pct >= 2.5:
            pts += 1.0
        return pts


@SCORE_BLOCKS.register("penalties")
class PenaltiesBlock(ScoreBlock):
    name = "penalties"
    max_points = 0.0

    def score(self, ctx: dict[str, Any], cfg: AppConfig) -> float:
        pen = stock_efficiency_penalty(ctx.get("stock_er"), cfg)
        if float(ctx.get("extension_hatr", 0.0)) > 2.0:
            pen -= 5.0
        if cfg.score.optional.sector_rs and not ctx.get("sector_above_50dma", True):
            pen -= 3.0
        return max(cfg.score.weights.penalties_max, pen)


def evaluate_vetoes(ctx: dict[str, Any], cfg: AppConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for name in cfg.strategy.vetoes:
        ok, reason = VETOES.get(name)().check(ctx, cfg)
        if not ok and reason:
            reasons.append(reason)
    return len(reasons) == 0, reasons


def compute_entry_score(ctx: dict[str, Any], cfg: AppConfig) -> tuple[float, str, float]:
    """Return (final_score, zone ['full'|'half'|'none'], zone_factor [1.0|0.5|0.0])."""
    if not cfg.score.enabled:
        return 100.0, "full", 1.0

    earned = 0.0
    penalties = 0.0
    for name in cfg.strategy.score_blocks:
        val = SCORE_BLOCKS.get(name)().score(ctx, cfg)
        if name == "penalties":
            penalties += val
        else:
            earned += val

    opt = cfg.score.optional
    if opt.sector_rs and ctx.get("sector_rs_ok"):
        earned += opt.max_points["sector_rs"]
    if opt.rs_line_high and ctx.get("rs_line_high"):
        earned += opt.max_points["rs_line_high"]
    if opt.base_count:
        bc = int(ctx.get("base_count", 0))
        if bc in (1, 2):
            earned += opt.max_points["base_count"]
        elif bc == 3:
            earned += 1.0

    total = cfg.score.normalise(earned) + penalties
    z = cfg.score.zones
    if total >= z.full:
        return total, "full", 1.0
    if total >= z.half:
        return total, "half", 0.5
    return total, "none", 0.0