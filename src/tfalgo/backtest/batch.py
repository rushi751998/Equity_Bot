"""Multi-strategy batch runner, comparison table, and SVG drawdown report."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tfalgo.backtest.engine import PreparedMarketData, prepare_market_data, run_backtest_from_frames
from tfalgo.backtest.metrics import compute_trade_metrics
from tfalgo.calendar import TradingCalendar
from tfalgo.config import AppConfig
from tfalgo.data.store import BarStore


@dataclass(frozen=True)
class BatchResult:
    output_dir: Path
    comparison: pl.DataFrame
    report_html: Path


def compute_equity_metrics(equity_df: pl.DataFrame) -> dict[str, Any]:
    """Compute return, max drawdown %, Sharpe, Calmar, and drawdown series from equity.csv."""
    if equity_df.is_empty() or equity_df.height < 2:
        return {
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "calmar_ratio": 0.0,
            "dates": [],
            "equities": [],
            "drawdowns": [],
        }
    dates = equity_df["date"].to_list()
    eq = equity_df["equity"].to_numpy().astype(np.float64)
    peaks = np.maximum.accumulate(eq)
    dd_pct = np.where(peaks > 0, (eq - peaks) / peaks * 100.0, 0.0)
    rets = np.diff(eq) / np.where(eq[:-1] > 0, eq[:-1], 1.0)
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = (float(np.mean(rets)) / std * math.sqrt(252.0)) if std > 0 else 0.0
    tot_ret = (eq[-1] / eq[0] - 1.0) * 100.0 if eq[0] > 0 else 0.0
    years = max(len(eq) / 252.0, 1.0 / 252.0)
    ann_ret = ((eq[-1] / eq[0]) ** (1.0 / years) - 1.0) * 100.0 if eq[0] > 0 and eq[-1] > 0 else tot_ret
    max_dd = float(np.min(dd_pct))
    calmar = (ann_ret / abs(max_dd)) if max_dd < 0 else 0.0
    return {
        "total_return_pct": tot_ret,
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "calmar_ratio": calmar,
        "dates": dates,
        "equities": eq.tolist(),
        "drawdowns": dd_pct.tolist(),
    }


def _svg_line_chart(title: str, values: list[float], color: str, y_suffix: str = "") -> str:
    w, h, pad = 640, 170, 28
    if not values:
        return f"<div><h4>{title}</h4><p>No data</p></div>"
    ymin, ymax = min(values), max(values)
    if ymax == ymin:
        ymax = ymin + 1.0
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad + (w - 2 * pad) * (i / max(1, n - 1))
        y = h - pad - (h - 2 * pad) * ((v - ymin) / (ymax - ymin))
        pts.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(pts)
    return (
        f'<div class="card"><h4>{title}</h4>'
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}">'
        f'<rect x="{pad}" y="{pad}" width="{w - 2*pad}" height="{h - 2*pad}" fill="#fafafa" stroke="#ddd"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.8" points="{poly}"/>'
        f'<text x="{pad}" y="18" font-size="11" fill="#444">max: {ymax:,.2f}{y_suffix}</text>'
        f'<text x="{w - pad}" y="{h - 8}" font-size="11" text-anchor="end" fill="#444">min: {ymin:,.2f}{y_suffix}</text>'
        f"</svg></div>"
    )


def run_batch_from_frames(
    configs: list[tuple[str, AppConfig]],
    frames_5m: dict[str, pl.DataFrame],
    bench_5m: pl.DataFrame,
    cal: TradingCalendar,
    output_dir: Path,
    prepared: PreparedMarketData | None = None,
) -> BatchResult:
    """Run multiple strategy configs sharing one PreparedMarketData and generate comparison + drawdown charts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    base_cfg = configs[0][1]
    data = prepared or prepare_market_data(base_cfg, frames_5m, bench_5m, cal)

    rows: list[dict[str, Any]] = []
    chart_blocks: list[str] = []
    eq_curves: list[np.ndarray] = []
    common_dates: list[str] = []

    for label, cfg in configs:
        res = run_backtest_from_frames(
            cfg, frames_5m, bench_5m, cal,
            output_dir=output_dir / label, prepared=data,
        )
        em = compute_equity_metrics(res.equity)
        # Reconstruct TradeRecord-compatible metrics from trades.csv
        if not res.trades.is_empty():
            trades_df = res.trades
            n = trades_df.height
            wins = trades_df.filter(pl.col("net_pnl") > 0)
            losses = trades_df.filter(pl.col("net_pnl") <= 0)
            gp = float(wins["net_pnl"].sum()) if wins.height else 0.0
            gl = float(losses["net_pnl"].sum()) if losses.height else 0.0
            tm = {
                "total_closed_campaigns": n,
                "winning_trades": wins.height,
                "losing_trades": losses.height,
                "win_rate_pct": 100.0 * wins.height / n,
                "expectancy_r": float(trades_df["money_r"].mean()),
                "profit_factor": (gp / abs(gl)) if gl < 0 else (float("inf") if gp > 0 else 0.0),
                "expectancy_inr": float(trades_df["net_pnl"].mean()),
            }
        else:
            tm = compute_trade_metrics([])

        rows.append({
            "strategy": label,
            "trades": tm["total_closed_campaigns"],
            "win_rate_pct": round(tm["win_rate_pct"], 2),
            "expectancy_r": round(tm["expectancy_r"], 3),
            "expectancy_inr": round(tm["expectancy_inr"], 2),
            "profit_factor": round(tm["profit_factor"], 2) if math.isfinite(tm["profit_factor"]) else 999.0,
            "total_return_pct": round(em["total_return_pct"], 2),
            "max_drawdown_pct": round(em["max_drawdown_pct"], 2),
            "sharpe_ratio": round(em["sharpe_ratio"], 2),
            "calmar_ratio": round(em["calmar_ratio"], 2),
        })
        chart_blocks.append(
            f"<h3>{label}</h3><div class='grid'>"
            + _svg_line_chart("Equity (INR)", em["equities"], "#1f77b4")
            + _svg_line_chart("Drawdown (%)", em["drawdowns"], "#d62728", "%")
            + "</div>"
        )
        if em["equities"]:
            eq_curves.append(np.asarray(em["equities"], dtype=np.float64))
            common_dates = em["dates"]

    # Equal-weight combined portfolio across all strategies
    if len(eq_curves) >= 2 and all(len(c) == len(eq_curves[0]) for c in eq_curves):
        rets = [np.diff(c) / np.where(c[:-1] > 0, c[:-1], 1.0) for c in eq_curves]
        port_ret = np.mean(rets, axis=0)
        port_eq = np.empty(len(eq_curves[0]), dtype=np.float64)
        port_eq[0] = base_cfg.capital.initial
        for i, r in enumerate(port_ret):
            port_eq[i + 1] = port_eq[i] * (1.0 + r)
        port_df = pl.DataFrame({"date": common_dates, "equity": port_eq.tolist()})
        pm = compute_equity_metrics(port_df)
        rows.append({
            "strategy": "COMBINED_EQUAL_WEIGHT",
            "trades": sum(r["trades"] for r in rows),
            "win_rate_pct": 0.0,
            "expectancy_r": 0.0,
            "expectancy_inr": 0.0,
            "profit_factor": 0.0,
            "total_return_pct": round(pm["total_return_pct"], 2),
            "max_drawdown_pct": round(pm["max_drawdown_pct"], 2),
            "sharpe_ratio": round(pm["sharpe_ratio"], 2),
            "calmar_ratio": round(pm["calmar_ratio"], 2),
        })
        chart_blocks.insert(
            0,
            "<h3>COMBINED EQUAL-WEIGHT PORTFOLIO</h3><div class='grid'>"
            + _svg_line_chart("Portfolio Equity (INR)", pm["equities"], "#2ca02c")
            + _svg_line_chart("Portfolio Drawdown (%)", pm["drawdowns"], "#9467bd", "%")
            + "</div>",
        )

    comp_df = pl.DataFrame(rows)
    comp_df.write_csv(output_dir / "comparison.csv")

    tbl_hdr = "".join(f"<th>{c}</th>" for c in comp_df.columns)
    tbl_rows = "".join(
        "<tr>" + "".join(f"<td>{row[c]}</td>" for c in comp_df.columns) + "</tr>"
        for row in comp_df.iter_rows(named=True)
    )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>tfalgo batch report</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:24px;color:#222}"
        "table{border-collapse:collapse;width:100%;margin-bottom:24px;font-size:13px}"
        "th,td{border:1px solid #ddd;padding:6px 10px;text-align:right}th{background:#f4f4f4}"
        "td:first-child,th:first-child{text-align:left}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}"
        ".card{border:1px solid #e5e5e5;padding:10px;border-radius:6px}</style></head>"
        f"<body><h2>tfalgo Multi-Strategy Comparison</h2>"
        f"<table><thead><tr>{tbl_hdr}</tr></thead><tbody>{tbl_rows}</tbody></table>"
        f"{''.join(chart_blocks)}</body></html>"
    )
    report_path = output_dir / "batch_report.html"
    report_path.write_text(html, encoding="utf-8")
    return BatchResult(output_dir, comp_df, report_path)


def run_batch(config_paths: list[Path], store: BarStore, cal: TradingCalendar, output_dir: Path) -> BatchResult:
    configs = [(p.stem, load_config_cached(p)) for p in config_paths]
    base_cfg = configs[0][1]
    tf = base_cfg.run.base_timeframe
    syms = base_cfg.data.symbols or [s for s in store.list_symbols(tf) if not s.startswith("idx:")]
    frames = {s: store.read_bars(s, tf, base_cfg.run.start, base_cfg.run.end) for s in syms}
    bench = store.read_bars(f"idx:{base_cfg.benchmark.index}", tf, base_cfg.run.start, base_cfg.run.end)
    return run_batch_from_frames(configs, frames, bench, cal, output_dir)


def load_config_cached(path: Path) -> AppConfig:
    from tfalgo.config import load_config

    return load_config(path)