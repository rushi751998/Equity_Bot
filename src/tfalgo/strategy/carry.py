"""15:10 MIS-to-CNC carry checklist (Section 7.8)."""

from __future__ import annotations

import math

from tfalgo.config import AppConfig

_REGIME_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def evaluate_carry(
    price_r: float,
    last_price: float,
    day_high: float,
    day_low: float,
    day_vol_pace: float,
    hourly_ribbon_ok: bool,
    last_hourly_close: float,
    hourly_ema20: float,
    regime_label: str,
    total_qty: int,
    cfg: AppConfig,
    has_event_within_4d: bool = False,
) -> tuple[bool, int, int, list[str]]:
    """Return (carry_pass, mis_sell_qty, convert_cnc_qty, failed_checks)."""
    c = cfg.carry
    if not c.enabled or total_qty <= 0:
        return False, total_qty, 0, ["carry_disabled"]

    fails: list[str] = []
    if price_r < c.min_open_r:
        fails.append("min_open_r")
    rng = day_high - day_low
    pos_in_range = (last_price - day_low) / rng if rng > 0 else 0.0
    if pos_in_range < c.min_close_in_range:
        fails.append("close_in_range")
    if day_vol_pace < c.min_vol_pace:
        fails.append("vol_pace")
    if not (hourly_ribbon_ok and last_hourly_close > hourly_ema20):
        fails.append("hourly_structure")
    if _REGIME_RANK.get(regime_label, 0) < _REGIME_RANK.get(c.min_regime, 1):
        fails.append("regime")
    if cfg.events.provider != "none" and has_event_within_4d:
        fails.append("event_within_4d")

    if fails:
        return False, total_qty, 0, fails

    trim_qty = math.floor(total_qty * c.trim_pct)
    convert_qty = total_qty - trim_qty
    return True, trim_qty, convert_qty, []