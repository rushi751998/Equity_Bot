import pytest
from pydantic import ValidationError

from p2_helpers import make_cfg
from tfalgo.config import load_config


def test_hourly_default_and_validation():
    assert make_cfg().hourly.partial_bar_policy == "price_only"
    assert make_cfg(hourly={"partial_bar_policy": "include_all"}).hourly.partial_bar_policy == "include_all"
    with pytest.raises(ValidationError):
        make_cfg(hourly={"partial_bar_policy": "nope"})


def test_score_defaults_and_max_is_90():
    s = make_cfg().score
    assert s.hysteresis.enabled is False
    assert (s.zones.full, s.zones.half) == (75, 60)
    assert s.weights.block_max_total() == 90
    assert s.weights.pre_trigger_max() == 75


def test_score_normalisation_example8():
    s = make_cfg().score
    assert s.normalise(81) == pytest.approx(81.0, abs=1e-12)
    s2 = make_cfg(score={"optional": {"sector_rs": True}}).score
    assert s2.optional.enabled_max() == 4
    assert s2.normalise(85) == pytest.approx(100 * 85 / 104, abs=1e-9)  # 81.7


def test_hysteresis_and_zone_validation():
    with pytest.raises(ValidationError):
        make_cfg(score={"zones": {"full": 60, "half": 75}})
    with pytest.raises(ValidationError):
        make_cfg(score={"hysteresis": {"enter_pct": 50, "exit_below_pct": 60}})


def test_ribbon_validation():
    with pytest.raises(ValidationError):
        make_cfg(trend={"ribbon_emas": [20, 15, 9]})


def test_default_and_pilot_yaml():
    d = load_config("config/default.yaml")
    p = load_config("config/pilot.yaml")
    assert (d.universe.min_adtv_cr, d.universe.min_atr_pct) == (20, 2.5)
    assert (p.universe.min_adtv_cr, p.universe.min_atr_pct) == (5, 1.5)
    assert p.capital.initial == d.capital.initial and p.data.symbols == d.data.symbols
    assert p.hourly.partial_bar_policy == "price_only"