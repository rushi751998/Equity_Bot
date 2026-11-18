"""Trading calendar and bar-time arithmetic (Asia/Kolkata, NSE regular session).

Conventions (spec section 2):
* bars are labelled by START time; ``bar_end = min(start + timeframe, session_close)``
* a bar is visible to the strategy only when ``now >= bar_end``  (completed-bar rule)
"""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "60m": 60}


def timeframe_minutes(tf: str, session_len_min: int = 375) -> int:
    """Minutes per bar; '1D' is the full session."""
    if tf == "1D":
        return session_len_min
    try:
        return _TF_MINUTES[tf]
    except KeyError:
        raise ValueError(f"Unsupported timeframe: {tf}") from None


class TradingCalendar:
    """Weekday calendar minus an explicit holiday set.

    If no holiday file is supplied the calendar is weekdays-only and ``strict`` is False;
    callers (e.g. data quality) then rely on days actually present in the data.
    """

    def __init__(
        self,
        holidays: set[date] | None = None,
        session_open: time = time(9, 15),
        session_close: time = time(15, 30),
        tz: str = "Asia/Kolkata",
    ) -> None:
        self.holidays: set[date] = set(holidays or ())
        self.session_open = session_open
        self.session_close = session_close
        self.tz = ZoneInfo(tz)
        self.strict = bool(self.holidays)
        if not self.strict:
            log.warning("No holidays loaded: calendar is weekdays-only (fill nse_holidays.csv)")

    # -- construction -------------------------------------------------------------
    @classmethod
    def from_csv(cls, path: str | Path | None, **kw: object) -> TradingCalendar:
        holidays: set[date] = set()
        if path and Path(path).exists():
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("date"):
                        holidays.add(date.fromisoformat(row["date"].strip()))
        return cls(holidays, **kw)  # type: ignore[arg-type]

    # -- session geometry ---------------------------------------------------------
    @property
    def session_minutes(self) -> int:
        o, c = self.session_open, self.session_close
        return (c.hour * 60 + c.minute) - (o.hour * 60 + o.minute)

    def session_open_dt(self, d: date) -> datetime:
        return datetime.combine(d, self.session_open, tzinfo=self.tz)

    def session_close_dt(self, d: date) -> datetime:
        return datetime.combine(d, self.session_close, tzinfo=self.tz)

    # -- trading days -------------------------------------------------------------
    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def trading_days(self, start: date, end: date) -> list[date]:
        out, d = [], start
        while d <= end:
            if self.is_trading_day(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def next_trading_day(self, d: date) -> date:
        d += timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d

    def prev_trading_day(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def add_trading_days(self, d: date, n: int) -> date:
        step = self.next_trading_day if n >= 0 else self.prev_trading_day
        for _ in range(abs(n)):
            d = step(d)
        return d

    # -- bars ---------------------------------------------------------------------
    def expected_bar_starts(self, d: date, tf: str) -> list[datetime]:
        """All bar start times in the session on day d (last bar may be shorter)."""
        step = timeframe_minutes(tf, self.session_minutes)
        start = self.session_open_dt(d)
        return [start + timedelta(minutes=m) for m in range(0, self.session_minutes, step)]

    def bar_end(self, start: datetime, tf: str) -> datetime:
        step = timeframe_minutes(tf, self.session_minutes)
        return min(start + timedelta(minutes=step), self.session_close_dt(start.date()))

    def is_bar_visible(self, start: datetime, tf: str, now: datetime) -> bool:
        """Completed-bar rule: usable only once now >= bar_end."""
        return now >= self.bar_end(start, tf)
