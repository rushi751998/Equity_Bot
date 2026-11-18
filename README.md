# tfalgo

Chart-only, long-only trend-following backtester for Indian mid/small-cap equities.
Python 3.12+, pydantic v2, polars, SQLite (stage 1), typer. OOP interfaces so the same
strategy code can later run live behind a `BrokerAdapter`.

## Status
Phase 1 (data layer) done: config, calendar, provider interface, CsvProvider, SQLite store,
resampling, corporate-action adjustment, data-quality checks, events (off in v1), CLI.
Next: Phase 2 (universe, indicators, regime, chop controls, patterns), then strategy,
execution/engine, research outputs.

## Setup
    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    make test

## Use
1. Put one CSV per symbol in `data/raw/` (e.g. `RELIANCE.csv`), columns
   `date,open,high,low,close,volume`, ISO timestamps with `+05:30`, 5-minute bars,
   timestamp = bar START. A leading unnamed pandas index column is ignored.
2. Edit `config/default.yaml` (`data.symbols`, optional `data.indexes`).
3. `tfalgo data ingest` then `tfalgo data check` (writes `reports/data/quality_*`).
   Symbols with hard failures are excluded from backtests.

## Extension points (customization / prod)
| Interface | Where | Register with |
|---|---|---|
| `DataProvider` | `data/provider.py` | `PROVIDERS.register("name")` |
| `BarStore` | `data/store.py` | `STORES.register("name")` |
| `EventProvider` | `data/events.py` | `EVENTS.register("name")` |
Later phases add `Strategy`, `BrokerAdapter`, `CostModel`, `FillModel`, `ScoreBlock`, `ExitRule`
the same way. `factory.py` is the only place that wires concrete classes from config.

## Known limitations (printed in every report)
- Survivorship bias: constituent lists are not point-in-time.
- A few pilot stocks cannot validate an edge; they only prove the code works.
- Only 5m data: no 1m stop evaluation and no slippage calibration; fills use the next 5m open.
- Slippage is modelled, not observed. Broker charges change: verify `as_of` in the cost profile.
- Score weights, pattern rules and chop thresholds are hypotheses, not fitted values.
- A backtest is not a forecast. Live trading needs broker integration, reconciliation, a kill
  switch and compliance with current SEBI retail-algo rules (out of scope).
