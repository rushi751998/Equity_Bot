"""Portfolio-level risk gates, signal ranking, and performance throttle (Section 7.10)."""

from __future__ import annotations

from typing import Any

from tfalgo.config import AppConfig
from tfalgo.strategy.base import PortfolioSnapshot, SymbolState


def is_throttle_active(closed_money_rs: list[float], currently_active: bool, cfg: AppConfig) -> bool:
    """Halve risk if sum of last N closed trades' money-R < 0 until 2 consecutive winners."""
    th = cfg.portfolio.throttle
    if len(closed_money_rs) < th.lookback_trades:
        return False
    recent = closed_money_rs[-th.lookback_trades :]
    if currently_active:
        wins = closed_money_rs[-th.release_after_consecutive_wins :]
        if len(wins) == th.release_after_consecutive_wins and all(r > 0 for r in wins):
            return False
        return True
    return sum(recent) < 0.0


def portfolio_allows_entry(
    state: SymbolState,
    portfolio: PortfolioSnapshot,
    sector: str | None,
    corr_20d: float,
    new_risk_inr: float,
    cfg: AppConfig,
) -> tuple[bool, str | None]:
    p = cfg.portfolio
    if portfolio.open_positions >= p.max_open_positions:
        return False, "max_open_positions"
    max_heat_inr = portfolio.equity * (p.max_heat_pct / 100.0)
    if portfolio.open_heat_inr + new_risk_inr > max_heat_inr:
        return False, "max_heat"
    if sector and portfolio.sector_counts.get(sector, 0) >= p.max_per_sector:
        return False, "max_per_sector"
    if corr_20d > p.max_corr_20d:
        return False, "max_corr_20d"
    if portfolio.entries_today >= p.max_new_entries_per_day:
        return False, "max_new_entries_per_day"
    if portfolio.daily_pnl_pct <= -p.daily_loss_limit_pct:
        return False, "daily_loss_limit"
    if portfolio.weekly_pnl_pct <= -p.weekly_loss_limit_pct:
        return False, "weekly_loss_limit"
    if state.entries_today >= cfg.reentry.max_entries_per_stock_per_day:
        return False, "max_entries_per_stock_per_day"
    if state.cooldown_days_left > 0:
        return False, "cooldown"
    return True, None


def rank_signals(candidates: list[dict[str, Any]], cfg: AppConfig) -> list[dict[str, Any]]:
    keys = cfg.portfolio.ranking
    return sorted(
        candidates,
        key=lambda c: tuple(float(c.get(k, 0.0)) for k in keys),
        reverse=True,
    )