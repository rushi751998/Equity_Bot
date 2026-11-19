"""Daily universe eligibility (data through D-1 only) and the cross-sectional RS panel.
Row for session date S is built from the daily bar of the previous trading day (`avail_date`)."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import polars as pl

from tfalgo.config import AppConfig, UniverseConfig
from tfalgo.indicators.relstrength import cross_sectional_percentile
from tfalgo.registry import Registry
from tfalgo.universe.constituents import Constituents


class UniverseFilter(ABC):
    """Boolean polars expression over a daily-feature frame (nulls count as False)."""

    name: str = ""

    def __init__(self, cfg: UniverseConfig, cons: Constituents) -> None:
        self.cfg, self.cons = cfg, cons

    @abstractmethod
    def expr(self, symbol: str) -> pl.Expr: ...


UNIVERSE_FILTERS: Registry[UniverseFilter] = Registry("universe filter")


@UNIVERSE_FILTERS.register("adtv")
class AdtvFilter(UniverseFilter):
    name = "adtv"

    def expr(self, symbol: str) -> pl.Expr:
        return (pl.col("adtv_cr") >= self.cfg.min_adtv_cr).fill_null(False)


@UNIVERSE_FILTERS.register("atr_pct")
class AtrPctFilter(UniverseFilter):
    name = "atr_pct"

    def expr(self, symbol: str) -> pl.Expr:
        return (pl.col("atr_pct") >= self.cfg.min_atr_pct).fill_null(False)


@UNIVERSE_FILTERS.register("price")
class PriceFilter(UniverseFilter):
    name = "price"

    def expr(self, symbol: str) -> pl.Expr:
        return (pl.col("close") >= self.cfg.min_price).fill_null(False)


@UNIVERSE_FILTERS.register("coverage")
class CoverageFilter(UniverseFilter):
    name = "coverage"

    def expr(self, symbol: str) -> pl.Expr:
        return (pl.col("coverage_win") >= self.cfg.min_window_coverage).fill_null(False)


@UNIVERSE_FILTERS.register("lists")
class ListsFilter(UniverseFilter):
    name = "lists"

    def expr(self, symbol: str) -> pl.Expr:
        return pl.lit(symbol not in self.cons.excluded_any())


def build_eligibility(
    daily: dict[str, pl.DataFrame], cons: Constituents, cfg: UniverseConfig, rs_short: str = "rs63"
) -> pl.DataFrame:
    """Long frame: symbol, date (session it applies to), eligible, ok_<filter>..., key metrics."""
    filters = [UNIVERSE_FILTERS.get(n)(cfg, cons) for n in cfg.filters]
    if not filters:
        raise ValueError("universe.filters must not be empty")
    frames = []
    for sym, d in daily.items():
        d2 = d.with_columns([f.expr(sym).alias(f"ok_{f.name}") for f in filters])
        d2 = d2.with_columns(eligible=pl.all_horizontal([pl.col(f"ok_{f.name}") for f in filters]))
        nul = pl.lit(None, dtype=pl.Float64)
        frames.append(
            d2.unique(subset=["avail_date"], keep="last", maintain_order=True).select(
                pl.lit(sym).alias("symbol"), pl.col("avail_date").alias("date"), "eligible",
                *[pl.col(f"ok_{f.name}") for f in filters],
                "close", "adtv_cr", "atr_pct",
                (pl.col("rs_composite") if "rs_composite" in d2.columns else nul).alias("rs_composite"),
                (pl.col(rs_short) if rs_short in d2.columns else nul).alias("rs_short"),
            )
        )
    return pl.concat(frames)


def build_panel(daily: dict[str, pl.DataFrame], cons: Constituents, cfg: AppConfig) -> pl.DataFrame:
    """Eligibility + RS percentiles (`rs_pct`, `rs_short_pct`) ranked among ELIGIBLE symbols per
    session date, + sector. Coarse for small baskets (13 symbols)."""
    elig = build_eligibility(daily, cons, cfg.universe, f"rs{cfg.indicators.rs_windows[0]}")
    dates = sorted(set(elig["date"].to_list()))
    d_ix = {d: i for i, d in enumerate(dates)}
    syms = sorted(daily)
    s_ix = {s: j for j, s in enumerate(syms)}
    mc = np.full((len(dates), len(syms)), np.nan)
    ms = np.full((len(dates), len(syms)), np.nan)
    for sym, dt, ok, rc, rs in elig.select(["symbol", "date", "eligible", "rs_composite", "rs_short"]).iter_rows():
        if not ok:
            continue
        if rc is not None:
            mc[d_ix[dt], s_ix[sym]] = rc
        if rs is not None:
            ms[d_ix[dt], s_ix[sym]] = rs
    pc, ps = cross_sectional_percentile(mc), cross_sectional_percentile(ms)
    out_c: list[float | None] = []
    out_s: list[float | None] = []
    for sym, dt in elig.select(["symbol", "date"]).iter_rows():
        i, j = d_ix[dt], s_ix[sym]
        out_c.append(None if np.isnan(pc[i, j]) else float(pc[i, j]))
        out_s.append(None if np.isnan(ps[i, j]) else float(ps[i, j]))
    sector = [cons.sector_of(s) for s in elig["symbol"].to_list()]
    return elig.with_columns(
        pl.Series("rs_pct", out_c, dtype=pl.Float64),
        pl.Series("rs_short_pct", out_s, dtype=pl.Float64),
        pl.Series("sector", sector, dtype=pl.Utf8),
    )