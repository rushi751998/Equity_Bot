from datetime import date

import pytest

from tfalgo.data.synthetic import make_intraday_5m


@pytest.fixture
def bars5():
    return make_intraday_5m(date(2024, 1, 1), 10, seed=1)
