"""Intraday MIS Opening Range Breakout — Short Side (orb_short_v1)."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from tfalgo.config import AppConfig
from tfalgo.strategy.base import (
    STRATEGIES,
    OrderIntent,
    PortfolioSnapshot,
    Strategy,
    SymbolState,
    round_up_tick,
)


@STRATEGIES.register("orb_short_v1")
class OrbShortStrategy(Strategy):
    """Intraday MIS Short Opening Range Breakdown:
    - Builds [or_high, or_low] from bars with `bar_time_str < or_end` (default 09:30).
    - Shorts (MIS) on first 5m close < or_low between `or_end` and `entry_until`.
    - Initial stop placed at `or_high + buffer_atr15 * atr15` (rounded UP to tick),
      with fixed_pct fallback if distance > max_swing_stop_pct.
    """

    name = "orb_short_v1"

    def __init__(self) -> None:
        self._or: dict[tuple[str, date], tuple[float, float]] = {}

    def on_bar(
        self,
        state: SymbolState,
        ctx: dict[str, Any],
        portfolio: PortfolioSnapshot,
        cfg: AppConfig,
    ) -> tuple[SymbolState, list[OrderIntent]]:
        p = cfg.strategy.params
        or_end: str = p.get("or_end", "09:30")
        entry_until: str = p.get("entry_until", "11:30")
        require_not_high: bool = bool(p.get("skip_high_regime", False))

        t_str: str = ctx["bar_time_str"]
        cur_date: date = ctx["ts"].date()
        key = (state.symbol, cur_date)

        # 1. Build opening range
        if t_str < or_end:
            hi, lo = float(ctx["bar_high"]), float(ctx["bar_low"])
            if key in self._or:
                prev_hi, prev_lo = self._or[key]
                self._or[key] = (max(prev_hi, hi), min(prev_lo, lo))
            else:
                self._or[key] = (hi, lo)
            return state, []

        # 2. Check breakdown inside entry window
        if state.entries_today > 0 or not (or_end <= t_str <= entry_until):
            return state, []
        if key not in self._or or not ctx.get("eligible", False):
            return state, []
        if require_not_high and ctx.get("regime_label") == "HIGH":
            return state, []

        or_hi, or_lo = self._or[key]
        close_px = float(ctx["bar_close"])
        if close_px >= or_lo:
            return state, []

        tick = cfg.session.tick_size
        atr15 = float(ctx.get("atr15") or 0.0)
        stop_px = round_up_tick(or_hi + cfg.stop.buffer_atr15 * atr15, tick)
        dist_pct = (stop_px - close_px) / close_px * 100.0
        if dist_pct > cfg.stop.max_swing_stop_pct:
            stop_px = round_up_tick(close_px * (1.0 + cfg.stop.fallback.fixed_pct / 100.0), tick)
            stop_source = "fallback_fixed"
        else:
            stop_source = "or_high"

        rps = stop_px - close_px
        if rps <= 0:
            return state, []

        s = cfg.sizing
        reg_mult = float(ctx.get("regime_mult", 1.0)) or 0.5
        throt_mult = 0.5 if portfolio.throttle_active else 1.0
        risk_budget = portfolio.equity * (s.risk_per_trade_pct / 100.0) * reg_mult * throt_mult
        by_risk = math.floor(risk_budget / rps)
        by_cap = math.floor((portfolio.equity * s.max_position_pct / 100.0) / close_px)
        by_liq = math.floor(float(ctx["adv20"]) * (s.max_adv_participation_pct / 100.0))
        full_qty = min(by_risk, by_cap, by_liq)
        qty = math.floor(s.tranches[0] * full_qty)
        if qty <= 0:
            return state, []

        bound = "cap" if full_qty == by_cap else ("liquidity" if full_qty == by_liq else "risk")
        return state, [OrderIntent(
            symbol=state.symbol,
            side="SELL",
            qty=qty,
            order_type="MARKET_NEXT_OPEN",
            product="MIS",
            reason="orb_short_breakdown",
            meta={
                "side": "SHORT",
                "stop_price": stop_px,
                "stop_source": stop_source,
                "risk_per_share": rps,
                "planned_full_qty": full_qty,
                "risk_budget": risk_budget,
                "planned_full_risk": full_qty * rps,
                "entry_score": 100.0,
                "score_zone": "full",
                "pattern": "orb_short",
                "pattern_quality": 1.0,
                "bound_constraint": bound,
            },
        )]