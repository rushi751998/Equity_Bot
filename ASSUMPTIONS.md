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

## Phase 2a
- Hourly 15:15 bar (15 min, n_bars=3) is kept with `is_partial`. `hourly.partial_bar_policy`
  (default `price_only`): partial bars feed price logic only (closes, EMA, swings, "no close below
  EMA20"); they are excluded from range/volume statistics (ATR, tightness ratio, volume-contraction
  means, S2 climax averages) via the `in_stats` column. `include_all` includes them everywhere.
  Wilder ATR carries its last value over excluded bars; TR of the next bar still uses the partial close.
- Entry/add permission and size come ONLY from the score zones at the signal bar (>=75 full,
  60-74 half, <60 none). Hysteresis never blocks a 60-74 half-size entry. Watchlist membership
  (WATCHING/ARMED) is structural: gate vetoes pass + valid leg_high/pullback low. Score hysteresis is
  an optional watchlist-stickiness filter on the PRE-TRIGGER score (all blocks except trigger quality,
  as % of its max = 75 points), `score.hysteresis.enabled: false` by default. Keys are
  `enter_pct`/`exit_below_pct` (spec had raw 75/55).
- Block maxima sum to 90 (25+20+15+15+10+5), not 100. Raw points stay as specified (Example 8).
  Normalisation only with optional features: score = 100*earned/(100+optional_max). The 75 "full" zone
  therefore needs ~83% of the 90 available points.
- RS = (1+r_stock)/(1+r_bench) (ratio of price relatives; avoids sign flips when the benchmark
  return is ~0 or negative). `rs_composite` = mean of the 3 windows (null unless all exist).
  Percentile = (rank-1)/(n-1)*100 (average rank for ties) among ELIGIBLE symbols per date; n<2 -> null.
- Daily bar for date D is visible from the next trading day's 09:15 (`avail_ts`); eligibility and
  universe flags are keyed to that session date (data through D-1 only).
- "Complete data" = rolling mean of daily 5m-bar coverage over `adtv_window` >= `min_window_coverage`
  (0.95) plus enough history; one bad day (e.g. 2017-07-10) does not drop a symbol for a month.
- EMA is seeded with the first value (pandas ewm adjust=False), valid after `span` observations;
  Wilder ATR seeds with the SMA of the first `period` TRs. Unavailable values are null (never NaN) in frames.
- Swing points use k=2 bars each side and are confirmed k bars late (no lookahead). leg_high = latest
  occurrence of the 20-bar max; leg_low = min low of the (up to) 20 bars before it; pullback low = min
  low of bars AFTER leg_high (null if leg_high is the current bar).
- Rvol pace needs a full 20 prior days at that time of day; missing 5m bars are not imputed.
- `config/pilot.yaml` uses `extends: default.yaml` (deep merge). `sectors.csv` keeps the template
  header; isin left blank (not invented).