"""CLI: `tfalgo data ingest|check`. Later phases add backtest/walkforward/ablation/report."""

from __future__ import annotations

import logging
from pathlib import Path
import polars as pl
import typer

from tfalgo.config import load_config
from tfalgo.data.ingest import IngestService
from tfalgo.data.quality import QualityChecker, hard_failed_symbols, write_report
from tfalgo.factory import build_calendar, build_provider, build_store
from tfalgo.logging_utils import setup_logging

app = typer.Typer(help="tfalgo trend-following backtester")
data_app = typer.Typer(help="Data ingestion and checks")
app.add_typer(data_app, name="data")
# before:
app = typer.Typer(help="tfalgo trend-following backtester")
data_app = typer.Typer(help="Data ingestion and checks")
app.add_typer(data_app, name="data")

# after:
app = typer.Typer(help="tfalgo trend-following backtester")
data_app = typer.Typer(help="Data ingestion and checks")
backtest_app = typer.Typer(help="Backtest execution")
app.add_typer(data_app, name="data")
app.add_typer(backtest_app, name="backtest")
ConfigOpt = typer.Option("config/default.yaml", "--config", "-c", help="YAML config")


@data_app.command("ingest")
def ingest(config: Path = ConfigOpt, symbols: str = typer.Option("", help="comma list; default = config")) -> None:
    """Idempotent incremental ingest (provider -> SQLite)."""
    setup_logging()
    cfg = load_config(config)
    prov, store = build_provider(cfg), build_store(cfg)
    svc = IngestService(prov, store, cfg.data.retry_attempts)
    tf = cfg.data.csv.native_timeframe
    syms = [s for s in symbols.split(",") if s] or cfg.data.symbols
    if not syms:
        typer.echo("No symbols: set data.symbols in config or pass --symbols", err=True)
        raise typer.Exit(1)
    for s in syms:
        r = svc.ingest(s, tf, cfg.run.start, cfg.run.end)
        typer.echo(f"{s}: inserted={r.inserted} identical={r.identical} conflicts={r.conflicts} {r.skipped_reason or ''}")
    for ix in cfg.data.indexes:
        r = svc.ingest(ix, tf, cfg.run.start, cfg.run.end, is_index=True)
        typer.echo(f"idx:{ix}: inserted={r.inserted} {r.skipped_reason or ''}")


@data_app.command("check")
def check(config: Path = ConfigOpt) -> None:
    """Run data-quality checks on stored bars; write quality_report.csv + summary."""
    setup_logging()
    cfg = load_config(config)
    store, cal = build_store(cfg), build_calendar(cfg)
    tf = cfg.data.csv.native_timeframe
    syms = store.list_symbols(tf)
    frames = {s: store.read_bars(s, tf) for s in syms}
    acts = {s: store.read_corporate_actions(s) for s in syms}
    issues = QualityChecker(cfg.quality, cal, cfg.run.timezone).run(frames, tf, acts)
    path = write_report(issues, syms, cfg.storage.output_dir / "data")
    failed = hard_failed_symbols(issues)
    typer.echo(f"Checked {len(syms)} symbols; excluded: {sorted(failed) or 'none'}. Report: {path}")


@data_app.command("outside")
def outside(symbol: str = typer.Option(..., help="symbol to inspect"), config: Path = ConfigOpt) -> None:
    """List bars outside the regular session, grouped by day (diagnoses quality failures)."""
    cfg = load_config(config)
    cal = build_calendar(cfg)
    store = build_store(cfg)
    df = store.read_bars(symbol, cfg.data.csv.native_timeframe)
    o, c = cal.session_open, cal.session_close
    mins = pl.col("ts").dt.hour().cast(pl.Int64) * 60 + pl.col("ts").dt.minute().cast(pl.Int64)
    out_mask = (mins < o.hour * 60 + o.minute) | (mins >= c.hour * 60 + c.minute)
    reg_days = set(df.filter(~out_mask)["ts"].dt.date().to_list())
    out = df.filter(out_mask).with_columns(day=pl.col("ts").dt.date())
    if out.is_empty():
        typer.echo("No out-of-session bars.")
        return
    g = out.group_by("day").agg(
        pl.len().alias("bars"), pl.col("ts").min().dt.strftime("%H:%M").alias("first"),
        pl.col("ts").max().dt.strftime("%H:%M").alias("last"),
    ).sort("day").with_columns(has_regular_bars=pl.col("day").is_in(list(reg_days)))
    with pl.Config(tbl_rows=100):
        typer.echo(str(g))

@backtest_app.command("run")
def backtest_run(config: Path = ConfigOpt) -> None:
    """Run deterministic backtest from SQLite store and write trades/equity/summary."""
    from tfalgo.backtest.engine import BacktestEngine

    setup_logging()
    cfg = load_config(config)
    cal = build_calendar(cfg)
    store = build_store(cfg)
    res = BacktestEngine(cfg, store, cal).run()
    typer.echo(res.summary_text)
    typer.echo(f"Outputs written to: {res.output_dir}")

@backtest_app.command("batch")
def backtest_batch(
    configs: list[Path] = typer.Option(..., "--config", "-c", help="Pass -c multiple times for each strategy YAML"),
    outdir: Path = typer.Option(Path("reports/batch"), "--outdir", help="Output folder"),
) -> None:
    """Run multiple strategy configs sharing one precomputed dataset + drawdown report."""
    from tfalgo.backtest.batch import run_batch

    setup_logging()
    base_cfg = load_config(configs[0])
    cal = build_calendar(base_cfg)
    store = build_store(base_cfg)
    res = run_batch(configs, store, cal, outdir)
    with pl.Config(tbl_cols=20, tbl_rows=50):
        typer.echo(str(res.comparison))
    typer.echo(f"Report HTML   : {res.report_html}")
    typer.echo(f"Simulator HTML: {res.simulator_html}")

if __name__ == "__main__":
    logging.basicConfig()
    app()
