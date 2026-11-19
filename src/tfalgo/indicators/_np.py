"""NumPy helpers shared by indicators. NaN = not available. Inputs are never mutated."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def as_f64(x: object) -> np.ndarray:
    return np.asarray(x, dtype=np.float64)


def _roll(x: object, n: int, fn: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    a = as_f64(x)
    out = np.full(a.shape, np.nan)
    if n >= 1 and len(a) >= n:
        out[n - 1:] = fn(sliding_window_view(a, n))
    return out


def rolling_mean(x: object, n: int) -> np.ndarray:
    return _roll(x, n, lambda w: w.mean(axis=1))


def rolling_sum(x: object, n: int) -> np.ndarray:
    return _roll(x, n, lambda w: w.sum(axis=1))


def rolling_max(x: object, n: int) -> np.ndarray:
    return _roll(x, n, lambda w: w.max(axis=1))


def rolling_min(x: object, n: int) -> np.ndarray:
    return _roll(x, n, lambda w: w.min(axis=1))


def rolling_std(x: object, n: int, ddof: int = 0) -> np.ndarray:
    return _roll(x, n, lambda w: w.std(axis=1, ddof=ddof))


def shift(x: object, k: int) -> np.ndarray:
    """Value k rows ago (NaN where unavailable)."""
    a = as_f64(x)
    if k == 0:
        return a.copy()
    out = np.full(a.shape, np.nan)
    if 0 < k < len(a):
        out[k:] = a[:-k]
    return out


def ffill(x: object) -> np.ndarray:
    a = as_f64(x).copy()
    if a.size == 0:
        return a
    idx = np.where(np.isnan(a), 0, np.arange(len(a)))
    np.maximum.accumulate(idx, out=idx)
    return a[idx]


def apply_on_mask(x: object, mask: object, fn: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    """Run `fn` on the masked-in subsequence only, scatter back, forward-fill masked-out rows."""
    a = as_f64(x)
    m = np.asarray(mask, dtype=bool)
    idx = np.flatnonzero(m)
    out = np.full(a.shape, np.nan)
    if idx.size:
        out[idx] = fn(a[idx])
    return ffill(out)