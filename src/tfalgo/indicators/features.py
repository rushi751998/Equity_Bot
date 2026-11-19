"""Polars feature builders. Every column at a row uses data up to and including that row only.
Unavailable values are null (never NaN) so polars comparisons stay safe."""

from __future__ import annotations

import numpy as np
import polars as pl

from tfalgo.config import AppConfig
from tfalgo.indicators._np import rolling_max, rolling_mean, shift
from tfalgo.indicators.atr import wilder_atr
from tfalgo.indicators.bollinger import bollinger
from tfalgo.indicators.efficiency import efficiency_ratio
from tfalgo.indicators.ema import ema
from tfalgo.indicators.relstrength import period_return
from tfalgo.indicators.structure import leg_structure, ribbon, swing_points
from tfalgo.indicators.volume import range_ratio, rvol_pace

INR_PER_CRORE = 1e7


def _f(name: str, arr: object) -> pl.Series:
    return pl.Series(name, np.asarray(arr, dtype=np.float64)).fill_nan(None)


def _b(name: str, arr: object) -> pl.Series:
    return pl.Series(name, np.asarray(arr, dtype=bool))


def _ribbon_cols(prefix: str, c: np.ndarray, emas: dict[int, np.ndarray], cfg: AppConfig) -> list[pl.Series]:
    f, m, s = cfg.trend.ribbon_emas
    r = ribbon(c, emas[f], emas[m], emas[s], cfg.trend.ribbon_slope_bars, cfg.trend.ribbon_min_spread_pct)
    return [_b(f"{prefix}stack_ok", r["stack_ok"]), _b(f"{prefix}compressed", r["compressed"]),
            _b(f"{prefix}fanning", r["fanning"]), _f(f"{prefix}spread_pct", r["spread_pct"])]


def daily_features(d: pl.DataFrame, cfg: AppConfig) -> pl.DataFrame:
    """Daily indicators. Row D is usable from `avail_ts` (next session open)."""
    ind, tr, uni = cfg.indicators, cfg.trend, cfg.universe
    h, l, c, v = (d[k].to_numpy() for k in ("high", "low", "close", "volume"))
    cols: list[pl.Series] = []
    emas = {n: ema(c, n) for n in sorted(set(tr.ribbon_emas) | set(ind.daily_emas))}
    cols += [_f(f"ema{n}", a) for n, a in emas.items()]
    dmas = sorted(tr.daily_gate.dma)
    sma = {n: rolling_mean(c, n) for n in dmas}
    cols += [_f(f"sma{n}", a) for n, a in sma.items()]
    atr = wilder_atr(h, l, c, ind.atr_period)
    with np.errstate(divide="ignore", invalid="ignore"):
        atr_pct = atr / c * 100.0
        hi = rolling_max(h, ind.high_lookback_days)
        below_hi = (hi - c) / hi * 100.0
    cols += [_f("atr", atr), _f("atr_pct", atr_pct),
             _f("adtv_cr", rolling_mean(c * v, uni.adtv_window) / INR_PER_CRORE),
             _f("vol_avg", rolling_mean(v, ind.volume_avg_days)),
             _f("hi_52w", hi), _f("pct_below_52w_high", below_hi),
             _f("er", efficiency_ratio(c, ind.er_period))]
    with np.errstate(invalid="ignore"):
        full = c > sma[dmas[0]]
        for a, b in zip(dmas[:-1], dmas[1:], strict=True):
            full = full & (sma[a] > sma[b])
        partial = (c > sma[dmas[0]]) & (sma[dmas[0]] > sma[dmas[-1]])
        cols += [_b("above_slow_dma", c > sma[dmas[-1]]), _b("dma_stack_full", full),
                 _b("dma_stack_partial", partial),
                 _b("slow_dma_rising", sma[dmas[-1]] > shift(sma[dmas[-1]], ind.slope_days))]
    cols += [_f(f"ret{n}", period_return(c, n)) for n in ind.rs_windows]
    cols += _ribbon_cols("rib_", c, emas, cfg)
    if "coverage" in d.columns:
        cols.append(_f("coverage_win", rolling_mean(d["coverage"].to_numpy(), uni.adtv_window)))
    return d.with_columns(cols)


def hourly_features(h60: pl.DataFrame, cfg: AppConfig) -> pl.DataFrame:
    """Hourly indicators. Needs `in_stats` (False for the partial 15:15 bar under price_only):
    ATR and tightness skip those bars; EMA, Bollinger, swings, legs use every bar's price."""
    ind, tr = cfg.indicators, cfg.trend
    hi, lo, c = (h60[k].to_numpy() for k in ("high", "low", "close"))
    stats = h60["in_stats"].to_numpy()
    emas = {n: ema(c, n) for n in tr.ribbon_emas}
    slow = emas[tr.ribbon_emas[-1]]
    atr = wilder_atr(hi, lo, c, ind.atr_period, include=stats)
    rng = hi - lo
    mid, up, dn = bollinger(c, ind.bollinger_period, ind.bollinger_k)
    sw = swing_points(hi, lo, ind.swing_k)
    leg = leg_structure(hi, lo, cfg.setup.leg_lookback_hours)
    with np.errstate(divide="ignore", invalid="ignore"):
        depth_hatr = (leg["leg_high"] - leg["pullback_low"]) / atr
        below_slow = c < slow
    cols = [_f(f"ema{n}", a) for n, a in emas.items()]
    cols += [_f("atr", atr), _f("range", rng),
             _f("range_ratio", range_ratio(rng, stats, cfg.setup.tightness.bars)),
             _f("bb_mid", mid), _f("bb_upper", up), _f("bb_lower", dn),
             _b("close_below_slow_ema", below_slow), _f("pullback_depth_hatr", depth_hatr)]
    cols += [_f(k, v) for k, v in sw.items()]
    cols += [_f(k, v) for k, v in leg.items() if k != "leg_valid"]
    cols.append(_b("leg_valid", leg["leg_valid"]))
    cols += _ribbon_cols("rib_", c, emas, cfg)
    return h60.with_columns(cols)


def m15_features(m15: pl.DataFrame, cfg: AppConfig) -> pl.DataFrame:
    """15m ATR (no partial bars exist: 375 = 25 x 15) and range."""
    hi, lo, c = (m15[k].to_numpy() for k in ("high", "low", "close"))
    return m15.with_columns([_f("atr", wilder_atr(hi, lo, c, cfg.indicators.atr_period)),
                             _f("range", hi - lo)])


def intraday_features(m5: pl.DataFrame, cfg: AppConfig) -> pl.DataFrame:
    """Adds `rvol_pace` (usable at the bar's end)."""
    open_min = cfg.session.open.hour * 60 + cfg.session.open.minute
    day = m5["ts"].dt.date().cast(pl.Int32).to_numpy()
    tod = (
        m5["ts"].dt.hour().cast(pl.Int32) * 60
        + m5["ts"].dt.minute().cast(pl.Int32)
        - open_min
    ).to_numpy()
    window = getattr(cfg.indicators, "rvol_window_days", 20)
    pace = rvol_pace(day, tod, m5["volume"].to_numpy(), window=window)
    return m5.with_columns(_f("rvol_pace", pace))


def with_relative_strength(d: pl.DataFrame, bench_d1: pl.DataFrame, cfg: AppConfig) -> pl.DataFrame:
    """Join benchmark daily returns; add rs{n}, rs_composite, rs_line, rs_line_avg, rs_line_ge_avg."""
    w = cfg.indicators.rs_windows
    b = bench_d1.select(["date", pl.col("close").alias("bench_close"),
                         *[pl.col(f"ret{n}").alias(f"bench_ret{n}") for n in w]])
    out = d.join(b, on="date", how="left").sort("ts")
    out = out.with_columns([((1.0 + pl.col(f"ret{n}")) / (1.0 + pl.col(f"bench_ret{n}"))).alias(f"rs{n}")
                            for n in w])
    comp = pl.sum_horizontal([pl.col(f"rs{n}") for n in w]) / float(len(w))
    ok = pl.all_horizontal([pl.col(f"rs{n}").is_not_null() for n in w])
    out = out.with_columns(pl.when(ok).then(comp).otherwise(None).alias("rs_composite"))
    line = (out["close"] / out["bench_close"]).to_numpy()
    avg = rolling_mean(line, cfg.indicators.rs_line_avg_days)
    with np.errstate(invalid="ignore"):
        ge = line >= avg
    return out.with_columns([_f("rs_line", line), _f("rs_line_avg", avg), _b("rs_line_ge_avg", ge)])