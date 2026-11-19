"""Pure trend-pullback state machine (Section 7.1)."""

from __future__ import annotations

from typing import Any

from tfalgo.config import AppConfig
from tfalgo.strategy.base import (
    STRATEGIES,
    LifecycleState,
    OrderIntent,
    PortfolioSnapshot,
    Strategy,
    SymbolState,
)
from tfalgo.strategy.score import compute_entry_score, evaluate_vetoes
from tfalgo.strategy.setup import daily_gate_ok
from tfalgo.strategy.sizing import SIZING_RULES, STOP_RULES
from tfalgo.strategy.trigger import TRIGGER_RULES, compute_entry_zone


@STRATEGIES.register("trend_pullback_v1")
class TrendPullbackStrategy(Strategy):
    name = "trend_pullback_v1"

    def on_bar(
        self,
        state: SymbolState,
        ctx: dict[str, Any],
        portfolio: PortfolioSnapshot,
        cfg: AppConfig,
    ) -> tuple[SymbolState, list[OrderIntent]]:
        orders: list[OrderIntent] = []

        if state.lifecycle == LifecycleState.IDLE:
            gate_ok, _ = daily_gate_ok(ctx, cfg)
            if gate_ok and ctx.get("leg_valid") and ctx.get("pullback_low") is not None:
                ref_high = ctx.get("flag_high") or ctx.get("pullback_high")
                if ref_high is not None and ctx.get("atr15"):
                    tl, zf, zc = compute_entry_zone(float(ref_high), float(ctx["atr15"]), cfg)
                    state = SymbolState(
                        symbol=state.symbol,
                        lifecycle=LifecycleState.ARMED,
                        trigger_level=tl,
                        zone_floor=zf,
                        zone_ceiling=zc,
                        entries_today=state.entries_today,
                    )
            if state.lifecycle != LifecycleState.ARMED:
                return state, orders

        if state.lifecycle == LifecycleState.ARMED:
            trig = TRIGGER_RULES.get("pullback_flag")().check(state, ctx, cfg)
            if not trig["fired"]:
                return state, orders
            veto_ok, _ = evaluate_vetoes(ctx, cfg)
            score, zone, z_factor = compute_entry_score(ctx, cfg)
            if not veto_ok or zone == "none" or ctx.get("pullback_low") is None or not ctx.get("atr15"):
                return state, orders

            est_entry = float(ctx["bar_close"])
            stop_res = STOP_RULES.get(cfg.strategy.stop)().compute(
                est_entry, float(ctx["pullback_low"]), float(ctx["atr15"]),
                float(ctx["hourly_atr"]), cfg,
            )
            if not stop_res["valid"]:
                return state, orders

            sz = SIZING_RULES.get("risk_cap_liquidity")().size(
                portfolio.equity, est_entry, stop_res["stop_price"],
                float(ctx["adv20"]), float(ctx.get("regime_mult", 1.0)),
                0.5 if portfolio.throttle_active else 1.0, z_factor, cfg,
            )
            if sz["tranche1_qty"] <= 0:
                return state, orders

            orders.append(OrderIntent(
                symbol=state.symbol,
                side="BUY",
                qty=sz["tranche1_qty"],
                order_type="MARKET_NEXT_OPEN",
                product="MIS",
                reason="entry_signal",
                meta={
                    "swing_low": float(ctx["pullback_low"]),
                    "atr15": float(ctx["atr15"]),
                    "hourly_atr": float(ctx["hourly_atr"]),
                    "planned_full_qty": sz["planned_full_qty"],
                    "risk_budget": sz["risk_budget_inr"],
                    "planned_full_risk": sz["planned_full_risk_inr"],
                    "entry_score": score,
                    "score_zone": zone,
                    "pattern": ctx.get("pattern_name"),
                    "pattern_quality": float(ctx.get("pattern_quality", 0.0)),
                    "bound_constraint": sz["bound_constraint"],
                },
            ))
            return SymbolState(
                symbol=state.symbol,
                lifecycle=LifecycleState.ENTRY_PENDING,
                trigger_level=state.trigger_level,
                zone_floor=state.zone_floor,
                zone_ceiling=state.zone_ceiling,
                entries_today=state.entries_today,
                entry_score=score,
                score_zone=zone,
            ), orders

        return state, orders