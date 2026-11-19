from datetime import date

from tfalgo.calendar import TradingCalendar
from tfalgo.config import AppConfig
from tfalgo.data.synthetic import make_intraday_5m

CAL = TradingCalendar()


def make_cfg(**over) -> AppConfig:
    raw = {"run": {"start": "2024-01-01", "end": "2024-12-31"}}
    raw.update(over)
    return AppConfig.model_validate(raw)


def sym5(n_days: int = 60, seed: int = 1, **kw):
    return make_intraday_5m(date(2024, 1, 1), n_days, seed=seed, **kw)