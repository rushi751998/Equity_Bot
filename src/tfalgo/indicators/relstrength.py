"""Relative strength helpers."""

from __future__ import annotations

import numpy as np

from tfalgo.indicators._np import as_f64, shift


def period_return(close: object, n: int) -> np.ndarray:
    c = as_f64(close)
    with np.errstate(divide="ignore", invalid="ignore"):
        return c / shift(c, n) - 1.0


def rs_ratio(ret: object, bench_ret: object) -> np.ndarray:
    """(1+r_stock)/(1+r_bench); > 1 = leader. NaN if the benchmark lost >= 100%."""
    r, b = as_f64(ret), as_f64(bench_ret)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(1.0 + b > 0, (1.0 + r) / (1.0 + b), np.nan)


def cross_sectional_percentile(matrix: object) -> np.ndarray:
    """Per row (date), percentile 0..100 across columns (symbols): (rank-1)/(k-1)*100 with
    average ranks for ties. NaN entries are excluded; rows with < 2 valid values give NaN."""
    m = as_f64(matrix)
    out = np.full(m.shape, np.nan)
    for r in range(m.shape[0]):
        row = m[r]
        ok = np.isfinite(row)
        k = int(ok.sum())
        if k < 2:
            continue
        vals = row[ok]
        s = np.sort(vals)
        less = np.searchsorted(s, vals, side="left")
        leq = np.searchsorted(s, vals, side="right")
        out[r, ok] = (less + leq - 1) / 2.0 / (k - 1) * 100.0
    return out