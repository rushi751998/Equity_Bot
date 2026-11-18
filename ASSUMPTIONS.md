# Assumptions and decisions

## Phase 1
- Data is 5m OHLCV only (no ticks, no 1m). Base timeframe 5m; 15m/60m/1D are resampled from it,
  anchored at 09:15 (last 60m bar 15:15-15:30). `calibrate-slippage` needs 1m data: deferred.
- Chart-only v1: fundamentals, news and event data are off. `events.provider: none`; event
  vetoes/penalties and the carry event check are inactive. Blackout heuristic exists but is off.
- Storage: SQLite behind `BarStore` (spec said Parquet/DuckDB). Quality report written as CSV
  + markdown (spec said parquet). Raw bars are never overwritten; differing re-ingests are
  counted as conflicts and the stored bar is kept.
- Timestamps stored as UTC epoch seconds, returned as Asia/Kolkata tz-aware.
- Corporate actions: `ratio` = new shares per old share; backward adjustment; dividends off.
  Adjusted series are computed on the fly from raw bars + actions (never stored over raw).
- No holiday list was invented: `config/calendar/nse_holidays.csv` is header-only. Until filled,
  the calendar is weekdays-only (a warning is logged) and missing whole days are not flagged.
- Universe files are empty templates; pilot symbols come from `data.symbols`.
- Benchmark index / India VIX: optional. Missing => regime components needing them are disabled
  and thresholds rescaled (implemented in Phase 2).
- A split-like daily jump without a recorded action is a HARD failure by default
  (`quality.split_jump_severity`), because unadjusted jumps corrupt indicators.
- Costs (Phase 4) use Zerodha's published page, verified 2026-11-18: delivery STT 0.1% both
  sides, NSE txn 0.00307%, stamp 0.015% buy (0.003% intraday), SEBI Rs10/cr, GST 18%,
  intraday brokerage min(Rs20, 0.03%), DP Rs15.34 per scrip per sell day (GST included).
  Capital Rs 10,00,000.
