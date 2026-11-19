import polars as pl

from p2_helpers import CAL, make_cfg, sym5
from tfalgo.data.access import build_symbol_data
from tfalgo.universe.constituents import (
    Constituents, build_constituents, load_sectors, load_symbol_list,
)
from tfalgo.universe.filters import UNIVERSE_FILTERS, build_eligibility, build_panel

ZERO = {"min_adtv_cr": 0, "min_atr_pct": 0, "min_price": 0, "min_window_coverage": 0.9}


def _cons(symbols=("X",), excluded=None):
    return Constituents(list(symbols), {s: "Auto" for s in symbols}, excluded or {})


def test_registry_has_builtin_filters():
    assert {"adtv", "atr_pct", "price", "coverage", "lists"} <= set(UNIVERSE_FILTERS.names())


def test_warmup_then_eligible_keyed_to_next_session():
    cfg = make_cfg(universe=ZERO)
    sd = build_symbol_data("X", sym5(40), cfg, CAL)
    e = build_eligibility({"X": sd.d1}, _cons(), cfg.universe)
    flags = e["eligible"].to_list()
    assert not any(flags[:19]) and all(flags[19:])               # 20-day window
    assert e["date"][0] == sd.d1["avail_date"][0]                # applies to the NEXT session


def test_thresholds_exclude():
    cfg = make_cfg(universe={**ZERO, "min_adtv_cr": 1e6})
    sd = build_symbol_data("X", sym5(40), cfg, CAL)
    assert not build_eligibility({"X": sd.d1}, _cons(), cfg.universe)["eligible"].any()
    cfg = make_cfg(universe={**ZERO, "min_price": 1e6})
    assert not build_eligibility({"X": sd.d1}, _cons(), cfg.universe)["eligible"].any()


def test_exclusion_lists_and_sectors(tmp_path):
    (tmp_path / "asm.csv").write_text("symbol\nX\n")
    (tmp_path / "gsm.csv").write_text("symbol\n")
    (tmp_path / "sectors.csv").write_text("symbol,isin,exchange,sector\nX,,NSE,Auto\nY,,NSE,IT\n")
    cfg = make_cfg(data={"symbols": ["X", "Y", "Z"]}, universe={
        **ZERO, "lists_dir": str(tmp_path), "sectors_file": str(tmp_path / "sectors.csv")})
    assert load_symbol_list(tmp_path / "asm.csv") == {"X"}
    assert load_symbol_list(tmp_path / "missing.csv") == set()
    assert load_sectors(tmp_path / "sectors.csv") == {"X": "Auto", "Y": "IT"}
    cons = build_constituents(cfg, available=["X", "Y"], hard_failed=["Y"])
    assert cons.symbols == ["X"] and cons.sector_of("Z") == "UNKNOWN"
    sd = build_symbol_data("X", sym5(40), cfg, CAL)
    assert not build_eligibility({"X": sd.d1}, cons, cfg.universe)["eligible"].any()


def test_panel_rs_percentiles():
    cfg = make_cfg(universe=ZERO, indicators={"rs_windows": [5, 10, 20]})
    bench = build_symbol_data("idx", sym5(60, seed=9), cfg, CAL, is_index=True)
    mk = lambda s, drift, seed: build_symbol_data(s, sym5(60, seed=seed, drift=drift), cfg, CAL, bench=bench)  # noqa: E731
    daily = {"A": mk("A", 0.0002, 1).d1, "B": mk("B", 0.0, 2).d1, "C": mk("C", -0.0002, 3).d1}
    panel = build_panel(daily, _cons(("A", "B", "C")), cfg)
    last = panel.filter(pl.col("date") == panel["date"].max()).sort("symbol")
    assert last["rs_pct"].to_list() == [100.0, 50.0, 0.0]
    assert last["sector"].to_list() == ["Auto"] * 3
    early = panel.filter(pl.col("symbol") == "A").head(10)
    assert early["rs_pct"].null_count() == 10                    # RS warm-up -> null