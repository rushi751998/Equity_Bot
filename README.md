# tfalgo

Chart-only, long-only trend-following backtester for Indian mid/small-cap equities.
Python 3.12+, pydantic v2, polars, SQLite (stage 1), typer. OOP interfaces so the same
strategy code can later run live behind a `BrokerAdapter`.

## Status
- **Phase 1 (Data layer) done:** config, calendar, `DataProvider`/`CsvProvider`, SQLite `BarStore`, resampling, corporate-action adjustment, data-quality checks, events (`none` in v1), CLI.
- **Phase 2 (Universe, indicators, regime, chop, patterns) done:** daily eligibility & RS panel, vectorised polars indicators, regime scoring (with dynamic rescaling), chop controls A1–A4, VCP & Flat Base pattern detectors.
- **Phase 3 (Strategy) done:** pluggable `Strategy` state machine (`trend_pullback_v1`, `orb_v1`), entry score & vetoes, stops/sizing, pyramiding with controlled-loss invariant, exhaustion ladder, carry checklist, hold score, and portfolio risk gates.
- **Phase 4 (Execution & engine) done:** Zerodha & flat-pct cost models, next-open slippage & participation fill model, deterministic two-stage `BacktestEngine`, 21-metric trade summary, multi-strategy `batch` runner with SVG drawdown charts, and interactive `portfolio_simulator.html`.
- **Next (Phase 5):** full `tfalgo report` with bootstrap CIs, Monte Carlo, walk-forward, and ablation.

## Setup
    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    pytest -q

## Use
1. Put one CSV per symbol in `data/raw/` (e.g. `RELIANCE.csv`), columns
   `date,open,high,low,close,volume`, ISO timestamps with `+05:30`, 5-minute bars,
   timestamp = bar START. A leading unnamed pandas index column is ignored.
2. Edit `config/default.yaml` (`data.symbols`, optional `data.indexes`).
3. Ingest and validate data:
   - `tfalgo data ingest --config config/pilot.yaml`
   - `tfalgo data check --config config/pilot.yaml` (writes `reports/data/quality_*`)
4. Run a single backtest:
   - `tfalgo backtest run --config config/pilot.yaml`
5. Run multiple strategies together (writes `comparison.csv`, `batch_report.html`, and interactive `portfolio_simulator.html`):
   - `tfalgo backtest batch -c config/pilot.yaml -c config/orb_pilot.yaml`

## Extension points (customization / prod)
Adding any new component requires **one new class + decorator + one YAML line** (no core engine edits):

| Interface | Where | Register with |
|---|---|---|
| `DataProvider` | `data/provider.py` | `PROVIDERS.register("name")` |
| `BarStore` | `data/store.py` | `STORES.register("name")` |
| `EventProvider` | `data/events.py` | `EVENTS.register("name")` |
| `UniverseFilter` | `universe/filters.py` | `UNIVERSE_FILTERS.register("name")` |
| `PatternDetector` | `indicators/patterns/base.py` | `PATTERNS.register("name")` |
| `RegimeComponent` | `regime/score.py` | `REGIME_COMPONENTS.register("name")` |
| `ChopControl` | `regime/chop.py` | `CHOP_CONTROLS.register("name")` |
| `Strategy` | `strategy/base.py` | `STRATEGIES.register("name")` |
| `ScoreBlock` / `Veto` | `strategy/base.py` | `SCORE_BLOCKS.register(...)` / `VETOES.register(...)` |
| `StopRule` / `SizingRule` | `strategy/base.py` | `STOP_RULES.register(...)` / `SIZING_RULES.register(...)` |
| `PyramidRule` / `ExitRule` | `strategy/base.py` | `PYRAMID_RULES.register(...)` / `EXIT_RULES.register(...)` |
| `CostModel` / `FillModel` | `execution/costs.py`, `fills.py` | `COSTS.register(...)` / `FILLS.register(...)` |

Example (adding a new strategy):
1. Create `src/tfalgo/strategy/my_strat.py`, subclass `Strategy`, decorate with `@STRATEGIES.register("my_strat")`.
2. Import `my_strat` in `src/tfalgo/strategy/__init__.py`.
3. Create a YAML config with `extends: pilot.yaml` and `strategy: {name: my_strat, params: {...}}`.

## Known limitations (printed in every report)
- Survivorship bias: constituent lists are as-of today, not point-in-time.
- The 13 pilot stocks (mostly large/mid caps) cannot validate an edge; they only prove the code works.
- Score weights, pattern rules, and chop thresholds are hypotheses, not fitted values; pattern detection is fuzzy.
- RS percentile and breadth are computed over a 13-stock basket (coarse); India VIX and index-volume components are disabled.
- Only 5m data: stops and fills are modelled on 5m bars with conservative ambiguity rules; slippage is modelled, not observed.
- Broker charges, STT, and tax rules change: verify `as_of` in `config/brokers/zerodha.yaml`.
- MIS eligibility and leverage are ignored (1x cash assumed).
- The sealed holdout includes the 2020 COVID crash and rebound (an unusual regime).
- A backtest is not a forecast. Live trading additionally requires broker API integration, reconciliation, a kill switch, and compliance with current SEBI retail-algo rules (out of scope).