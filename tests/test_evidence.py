import numpy as np
import pandas as pd
import pytest

from hydroseason._evidence import annual_extremum_month_sets, wilson_interval
from hydroseason._state_input import prepare_monthly_extent


def test_four_of_five_has_a_low_lower_bound():
    """The number that motivates the gate: 80% of five is weak evidence."""
    low, high = wilson_interval(4, 5)

    assert low == pytest.approx(0.376, abs=0.01)
    assert high == pytest.approx(0.964, abs=0.01)


def test_five_of_five_is_stronger_than_four_of_five():
    low_perfect, _ = wilson_interval(5, 5)
    low_partial, _ = wilson_interval(4, 5)

    assert low_perfect > low_partial
    assert low_perfect == pytest.approx(0.566, abs=0.01)


def test_more_trials_narrow_the_interval_at_the_same_rate():
    low_small, high_small = wilson_interval(8, 10)
    low_large, high_large = wilson_interval(80, 100)

    assert (high_large - low_large) < (high_small - low_small)
    assert low_large > low_small


def test_bounds_stay_inside_zero_and_one():
    for successes, trials in [(0, 1), (1, 1), (0, 50), (50, 50)]:
        low, high = wilson_interval(successes, trials)
        assert 0.0 <= low <= high <= 1.0


def test_zero_trials_returns_the_widest_interval():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_successes_cannot_exceed_trials():
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(6, 5)


def test_interval_is_finite_for_every_rate():
    for successes in range(0, 21):
        low, high = wilson_interval(successes, 20)
        assert np.isfinite(low) and np.isfinite(high)


def _record(values, start="2000-01-01"):
    index = pd.date_range(start, periods=len(values), freq="MS")
    return prepare_monthly_extent(
        pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)
    )


def test_sharp_trough_yields_one_month_per_year():
    values = np.tile(np.array([50.0] * 6 + [5.0] + [50.0] * 5), 4)
    prepared = _record(values)

    month_sets = annual_extremum_month_sets(prepared, kind="min", tolerance_pct=1.0)

    assert month_sets == {2000: (7,), 2001: (7,), 2002: (7,), 2003: (7,)}


def test_flat_year_does_not_collapse_to_january():
    """The defect being replaced: idxmin on a tied year returns the first row."""
    values = np.concatenate(
        [np.full(12, 30.0), np.array([50.0] * 6 + [5.0] + [50.0] * 5)]
    )
    prepared = _record(values)

    month_sets = annual_extremum_month_sets(prepared, kind="min", tolerance_pct=1.0)

    assert month_sets[2000] == tuple(range(1, 13))
    assert month_sets[2001] == (7,)


def test_years_without_usable_months_are_absent():
    values = np.concatenate(
        [np.full(12, np.nan), np.array([50.0] * 6 + [5.0] + [50.0] * 5)]
    )
    prepared = _record(values)

    month_sets = annual_extremum_month_sets(prepared, kind="min", tolerance_pct=1.0)

    assert 2000 not in month_sets
    assert len(month_sets) == 1


def test_max_kind_finds_peaks():
    values = np.tile(np.array([5.0] * 2 + [90.0] + [5.0] * 9), 3)
    prepared = _record(values)

    month_sets = annual_extremum_month_sets(prepared, kind="max", tolerance_pct=1.0)

    assert all(months == (3,) for months in month_sets.values())


def test_partial_years_contribute_their_own_extremum():
    index = pd.date_range("2000-07-01", periods=6, freq="MS")
    prepared = prepare_monthly_extent(
        pd.DataFrame(
            {"extent_pct": [50.0, 50.0, 5.0, 50.0, 50.0, 50.0], "invalid_pct": 0.0},
            index=index,
        )
    )

    month_sets = annual_extremum_month_sets(prepared, kind="min", tolerance_pct=1.0)

    assert month_sets == {2000: (9,)}
