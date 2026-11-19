"""Symbol list, sectors and exclusion lists. The list is as-of today (survivorship bias)."""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tfalgo.config import AppConfig

log = logging.getLogger(__name__)

SURVIVORSHIP_NOTE = "Survivorship bias: the symbol list is as-of today, not point-in-time."


def _rows(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_symbol_list(path: str | Path) -> set[str]:
    return {r["symbol"].strip() for r in _rows(path) if (r.get("symbol") or "").strip()}


def load_sectors(path: str | Path) -> dict[str, str]:
    return {r["symbol"].strip(): (r.get("sector") or "").strip()
            for r in _rows(path) if (r.get("symbol") or "").strip()}


@dataclass(frozen=True)
class Constituents:
    symbols: list[str]
    sectors: dict[str, str]
    excluded: dict[str, set[str]]  # list file name -> symbols

    def sector_of(self, symbol: str) -> str:
        return self.sectors.get(symbol) or "UNKNOWN"

    def excluded_any(self) -> set[str]:
        return set().union(*self.excluded.values()) if self.excluded else set()


def build_constituents(
    cfg: AppConfig, available: Iterable[str] | None = None, hard_failed: Iterable[str] | None = None
) -> Constituents:
    syms = list(cfg.data.symbols)
    if available is not None:
        have = set(available)
        missing = [s for s in syms if s not in have]
        if missing:
            log.warning("symbols without stored bars skipped: %s", missing)
        syms = [s for s in syms if s in have]
    bad = set(hard_failed or ())
    syms = [s for s in syms if s not in bad]
    u = cfg.universe
    excluded = {name: load_symbol_list(u.lists_dir / name) for name in u.exclude_lists}
    sectors = load_sectors(u.sectors_file)
    unknown = [s for s in syms if s not in sectors]
    if unknown:
        log.warning("no sector for %s (sector cap treats them as 'UNKNOWN')", unknown)
    return Constituents(syms, sectors, excluded)