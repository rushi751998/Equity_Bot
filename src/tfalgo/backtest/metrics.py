"""Trade-level performance metrics (Phase 4 summary)."""

from __future__ import annotations

from typing import Any

from tfalgo.backtest.portfolio import TradeRecord


def _max_streak(flags: list[bool]) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        if cur > best:
            best = cur
    return best


def compute_trade_metrics(trades: list[TradeRecord]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "total_closed_campaigns": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate_pct": 0.0,
            "avg_win_inr": 0.0,
            "avg_loss_inr": 0.0,
            "payoff_ratio": 0.0,
            "expectancy_inr": 0.0,
            "expectancy_r": 0.0,
            "gross_profit_inr": 0.0,
            "gross_loss_inr": 0.0,
            "profit_factor": 0.0,
            "best_trade_inr": 0.0,
            "best_trade_r": 0.0,
            "worst_trade_inr": 0.0,
            "worst_trade_r": 0.0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "avg_hold_days_winners": 0.0,
            "avg_hold_days_losers": 0.0,
            "avg_hold_days_all": 0.0,
            "cap_bound_count": 0,
        }

    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]

    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = sum(t.net_pnl for t in losses)
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0

    payoff = (avg_win / abs(avg_loss)) if (wins and avg_loss < 0) else (float("inf") if wins and not losses else 0.0)
    pf = (gross_profit / abs(gross_loss)) if gross_loss < 0 else (float("inf") if gross_profit > 0 else 0.0)

    return {
        "total_closed_campaigns": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": 100.0 * len(wins) / n,
        "avg_win_inr": avg_win,
        "avg_loss_inr": avg_loss,
        "payoff_ratio": payoff,
        "expectancy_inr": sum(t.net_pnl for t in trades) / n,
        "expectancy_r": sum(t.money_r for t in trades) / n,
        "gross_profit_inr": gross_profit,
        "gross_loss_inr": gross_loss,
        "profit_factor": pf,
        "best_trade_inr": max(t.net_pnl for t in trades),
        "best_trade_r": max(t.money_r for t in trades),
        "worst_trade_inr": min(t.net_pnl for t in trades),
        "worst_trade_r": min(t.money_r for t in trades),
        "max_consecutive_wins": _max_streak([t.net_pnl > 0 for t in trades]),
        "max_consecutive_losses": _max_streak([t.net_pnl <= 0 for t in trades]),
        "avg_hold_days_winners": sum(t.hold_days for t in wins) / len(wins) if wins else 0.0,
        "avg_hold_days_losers": sum(t.hold_days for t in losses) / len(losses) if losses else 0.0,
        "avg_hold_days_all": sum(t.hold_days for t in trades) / n,
        "cap_bound_count": sum(1 for t in trades if t.bound_constraint == "cap"),
    }


def format_trade_summary(m: dict[str, Any]) -> str:
    return "\n".join([
        f"Total Closed Campaigns         : {m['total_closed_campaigns']}",
        f"Winning Trades                 : {m['winning_trades']}",
        f"Losing Trades (incl. breakeven): {m['losing_trades']}",
        f"Win Rate (%)                   : {m['win_rate_pct']:.2f}%",
        f"Avg Win (INR)                  : {m['avg_win_inr']:,.2f}",
        f"Avg Loss (INR)                 : {m['avg_loss_inr']:,.2f}",
        f"Payoff Ratio (Avg Win/Avg Loss): {m['payoff_ratio']:.2f}",
        f"Expectancy per Trade (INR)     : {m['expectancy_inr']:,.2f}",
        f"Expectancy (R-Multiples)       : {m['expectancy_r']:.3f}R",
        f"Gross Profit (INR)             : {m['gross_profit_inr']:,.2f}",
        f"Gross Loss (INR)               : {m['gross_loss_inr']:,.2f}",
        f"Profit Factor                  : {m['profit_factor']:.2f}",
        f"Best Trade (INR)               : {m['best_trade_inr']:,.2f}",
        f"Best Trade (R)                 : {m['best_trade_r']:.3f}R",
        f"Worst Trade (INR)              : {m['worst_trade_inr']:,.2f}",
        f"Worst Trade (R)                : {m['worst_trade_r']:.3f}R",
        f"Max Consecutive Wins           : {m['max_consecutive_wins']}",
        f"Max Consecutive Losses         : {m['max_consecutive_losses']}",
        f"Avg Holding Days - Winners     : {m['avg_hold_days_winners']:.2f}",
        f"Avg Holding Days - Losers      : {m['avg_hold_days_losers']:.2f}",
        f"Avg Holding Days - All Closed  : {m['avg_hold_days_all']:.2f}",
        f"25% Cap Bound                  : {m['cap_bound_count']}/{m['total_closed_campaigns']}",
    ])