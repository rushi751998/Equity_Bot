"""Opening Range Breakout (ORB) strategy plugin."""

from __future__ import annotations

from datetime import date
from typing import Any

from tfalgo.config import AppConfig
from tfalgo.strategy.base import (
    SIZING_RULES,
    STOP_RULES,
    STRATEGIES,
    OrderIntent,
    PortfolioSnapshot,
    Strategy,
    SymbolState,
)


@STRATEGIES.register("orb_v1")
class OrbStrategy(Strategy):
    """Long-only Opening Range Breakout:
    - Builds [or_high, or_low] from bars with `bar_time_str < or_end` (default 09:30).
    - Enters on first 5m close > or_high between `or_end` and `entry_until`.
    - Places initial stop via configured StopRule using `or_low` as `swing_low`.
    """

    name = "orb_v1"

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
        require_regime: bool = bool(p.get("require_regime", True))

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

        # 2. Check breakout inside entry window
        if state.entries_today > 0 or not (or_end <= t_str <= entry_until):
            return state, []
        if key not in self._or or not ctx.get("eligible", False):
            return state, []
        if require_regime and ctx.get("regime_label") == "LOW":
            return state, []

        or_hi, or_lo = self._or[key]
        close_px = float(ctx["bar_close"])
        if close_px <= or_hi:
            return state, []

        atr15 = float(ctx.get("atr15") or 0.0)
        h_atr = float(ctx.get("hourly_atr") or atr15 * 2.0)
        stop_res = STOP_RULES.get(cfg.strategy.stop)().compute(close_px, or_lo, atr15, h_atr, cfg)
        if not stop_res["valid"]:
            return state, []

        sz = SIZING_RULES.get("risk_cap_liquidity")().size(
            portfolio.equity,
            close_px,
            stop_res["stop_price"],
            float(ctx["adv20"]),
            float(ctx.get("regime_mult", 1.0)),
            0.5 if portfolio.throttle_active else 1.0,
            1.0,
            cfg,
        )
        if sz["tranche1_qty"] <= 0:
            return state, []

        intent = OrderIntent(
            symbol=state.symbol,
            side="BUY",
            qty=sz["tranche1_qty"],
            order_type="MARKET_NEXT_OPEN",
            product="MIS",
            reason="orb_breakout",
            meta={
                "swing_low": or_lo,
                "atr15": atr15,
                "hourly_atr": h_atr,
                "planned_full_qty": sz["planned_full_qty"],
                "risk_budget": sz["risk_budget_inr"],
                "planned_full_risk": sz["planned_full_risk_inr"],
                "entry_score": 100.0,
                "score_zone": "full",
                "pattern": "orb",
                "pattern_quality": 1.0,
                "bound_constraint": sz["bound_constraint"],
            },
        )
        return state, [intent]