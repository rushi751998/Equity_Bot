from datetime import date
from pathlib import Path

import polars as pl
import pytest

from tfalgo.config import CsvProviderConfig
from tfalgo.data.adjust import adjust_bars, compute_factors
from tfalgo.data.ingest import IngestService, subtract_ranges
from tfalgo.data.providers.csv_provider import CsvProvider
from tfalgo.data.store import SqliteBarStore, merge_ranges
from tfalgo.data.synthetic import make_intraday_5m


def _write_pandas_style_csv(path: Path, df: pl.DataFrame):
    out = df.with_columns(pl.col("ts").dt.strftime("%Y-%m-%d %H:%M:%S%:z").alias("date")).select(
        "date", "open", "high", "low", "close", "volume")
    out = out.with_row_index("")  # unnamed pandas index column
    out.write_csv(path)


@pytest.fixture
def csv_root(tmp_path, bars5):
    _write_pandas_style_csv(tmp_path / "ABC.csv", bars5)
    return tmp_path


def test_csv_provider_reads_pandas_export_and_resamples(csv_root, bars5):
    p = CsvProvider(CsvProviderConfig(root=csv_root))
    got = p.get_ohlcv("ABC", "5m", date(2024, 1, 1), date(2024, 12, 31))
    assert got.height == bars5.height
    assert got["ts"].dtype == bars5["ts"].dtype
    assert got["close"].to_list() == bars5["close"].to_list()
    assert p.get_ohlcv("ABC", "1D", date(2024, 1, 1), date(2024, 1, 3)).height == 3
    assert [i.symbol for i in p.list_instruments()] == ["ABC"]
    with pytest.raises(ValueError):
        p.get_ohlcv("ABC", "1m", date(2024, 1, 1), date(2024, 1, 3))


def test_range_helpers():
    assert merge_ranges([(date(2024, 1, 1), date(2024, 1, 5)), (date(2024, 1, 6), date(2024, 1, 9))]) == [(date(2024, 1, 1), date(2024, 1, 9))]
    gaps = subtract_ranges((date(2024, 1, 1), date(2024, 1, 31)), [(date(2024, 1, 10), date(2024, 1, 20))])
    assert gaps == [(date(2024, 1, 1), date(2024, 1, 9)), (date(2024, 1, 21), date(2024, 1, 31))]
    assert subtract_ranges((date(2024, 1, 1), date(2024, 1, 5)), [(date(2023, 1, 1), date(2024, 2, 1))]) == []


def test_ingest_idempotent_and_incremental(csv_root, bars5):
    store = SqliteBarStore(":memory:")
    svc = IngestService(CsvProvider(CsvProviderConfig(root=csv_root)), store)
    r1 = svc.ingest("ABC", "5m", date(2024, 1, 1), date(2024, 1, 5))
    assert r1.inserted == 5 * 75
    r2 = svc.ingest("ABC", "5m", date(2024, 1, 1), date(2024, 1, 5))  # fully covered: nothing fetched
    assert r2.fetched == [] and r2.inserted == 0
    r3 = svc.ingest("ABC", "5m", date(2024, 1, 1), date(2024, 1, 12))  # only the new tail
    assert r3.fetched == [(date(2024, 1, 6), date(2024, 1, 12))]
    back = store.read_bars("ABC", "5m")
    assert back.height == bars5.height
    assert back["ts"].dtype == bars5["ts"].dtype
    assert back.equals(bars5)


def test_store_never_overwrites_raw_and_reports_conflicts(bars5):
    store = SqliteBarStore(":memory:")
    store.write_bars("X", "5m", bars5)
    again = store.write_bars("X", "5m", bars5)
    assert (again.inserted, again.identical, again.conflicts) == (0, bars5.height, 0)
    tampered = bars5.with_columns(pl.col("close") + 1.0)
    res = store.write_bars("X", "5m", tampered)
    assert res.inserted == 0 and res.conflicts == bars5.height
    assert store.read_bars("X", "5m").equals(bars5)  # raw unchanged


def test_missing_file_is_skipped_not_crashed(tmp_path):
    svc = IngestService(CsvProvider(CsvProviderConfig(root=tmp_path)), SqliteBarStore(":memory:"))
    r = svc.ingest("NOPE", "5m", date(2024, 1, 1), date(2024, 1, 5), is_index=True)
    assert r.skipped_reason and r.inserted == 0


def test_split_adjustment_backward_and_raw_untouched():
    df = make_intraday_5m(date(2024, 1, 1), 4, seed=2)
    actions = pl.DataFrame({"ex_date": [date(2024, 1, 3)], "type": ["split"], "ratio": [5.0]})
    adj = adjust_bars(df, actions)
    pre = pl.col("ts").dt.date() < date(2024, 1, 3)
    assert adj.filter(pre)["close"].to_list() == pytest.approx((df.filter(pre)["close"] / 5).to_list())
    assert adj.filter(pre)["volume"].to_list() == pytest.approx((df.filter(pre)["volume"] * 5).to_list())
    assert adj.filter(~pre)["close"].to_list() == df.filter(~pre)["close"].to_list()


def test_two_actions_compound():
    f = compute_factors(pl.DataFrame({"ex_date": [date(2022, 1, 1), date(2023, 1, 1)], "type": ["split", "bonus"], "ratio": [2.0, 2.0]}))
    assert dict(zip(f["ex_date"], f["cum_factor"], strict=True)) == {date(2022, 1, 1): 0.25, date(2023, 1, 1): 0.5}
