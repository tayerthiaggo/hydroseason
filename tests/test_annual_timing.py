import numpy as np
import pandas as pd
import pytest

from hydroseason._circular_timing import equivalent_extremum_months


def _year(values, year=2000):
    index = pd.date_range(f"{year}-01-01", periods=len(values), freq="MS")
    return pd.Series(values, index=index, dtype=float)


def test_flat_year_returns_every_month_not_january():
    series = _year([5.0] * 12)

    months = equivalent_extremum_months(series, kind="min", tolerance=1.0)

    assert months == tuple(range(1, 13))


def test_sharp_trough_returns_one_month():
    series = _year([50.0] * 12)
    series.iloc[6] = 1.0

    months = equivalent_extremum_months(series, kind="min", tolerance=1.0)

    assert months == (7,)


def test_tolerance_admits_near_ties_only():
    series = _year([50.0] * 12)
    series.iloc[6] = 1.0
    series.iloc[8] = 1.5
    series.iloc[10] = 9.0

    months = equivalent_extremum_months(series, kind="min", tolerance=1.0)

    assert months == (7, 9)


def test_max_kind_selects_the_peak_side():
    series = _year([5.0] * 12)
    series.iloc[3] = 90.0

    months = equivalent_extremum_months(series, kind="max", tolerance=1.0)

    assert months == (4,)


def test_all_missing_year_returns_empty():
    series = _year([np.nan] * 12)

    assert equivalent_extremum_months(series, kind="min", tolerance=1.0) == ()


def test_missing_months_are_ignored_not_treated_as_zero():
    series = _year([50.0] * 12)
    series.iloc[2] = np.nan
    series.iloc[6] = 1.0

    months = equivalent_extremum_months(series, kind="min", tolerance=1.0)

    assert months == (7,)


def test_negative_tolerance_is_rejected():
    with pytest.raises(ValueError, match="tolerance"):
        equivalent_extremum_months(_year([1.0] * 12), kind="min", tolerance=-1.0)
