import numpy as np
import pandas as pd
import pytest

from hydroseason._seasonality import _design, _solve_gram, _year_gram, _year_matrices
from hydroseason._state_input import candidate_weights, prepare_monthly_extent


def _frame(extent, invalid_pct=None):
    index = pd.date_range("2000-01-01", periods=len(extent), freq="MS")
    data = {"extent_pct": extent}
    if invalid_pct is not None:
        data["invalid_pct"] = invalid_pct
    return pd.DataFrame(data, index=index)


def test_candidate_weights_track_observed_fraction():
    prepared = prepare_monthly_extent(_frame([10.0, 20.0, 30.0], [0.0, 50.0, 90.0]))

    weights = candidate_weights(prepared)

    assert weights.tolist() == pytest.approx([1.0, 0.5, 0.1])


def test_candidate_weights_clip_to_floor_and_ceiling():
    prepared = prepare_monthly_extent(_frame([10.0, 20.0], [99.5, 0.0]))

    weights = candidate_weights(prepared)

    # 0.5% observed would be 0.005; the floor keeps it informative but small.
    assert weights.iloc[0] == pytest.approx(0.05)
    assert weights.iloc[1] == pytest.approx(1.0)


def test_candidate_weights_are_zero_for_unusable_months():
    prepared = prepare_monthly_extent(_frame([10.0, np.nan, 30.0], [0.0, 0.0, 0.0]))

    weights = candidate_weights(prepared)

    assert weights.iloc[1] == 0.0
    assert (weights.iloc[[0, 2]] > 0).all()


def test_candidate_weights_treat_unknown_quality_as_fully_observed():
    prepared = prepare_monthly_extent(_frame([10.0, 20.0]))

    weights = candidate_weights(prepared)

    assert weights.tolist() == pytest.approx([1.0, 1.0])


def _multi_year_frame(n_years=3, amplitude=20.0, mean=50.0, phase=7):

    months = pd.date_range("2000-01-01", periods=12 * n_years, freq="MS")
    angle = 2.0 * np.pi * (months.month - phase) / 12.0
    values = mean + amplitude * np.cos(angle)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=months)


def test_year_matrices_are_year_by_month():
    prepared = prepare_monthly_extent(_multi_year_frame(n_years=3))
    weights = candidate_weights(prepared)

    years, values, matrix_weights = _year_matrices(prepared, weights)

    assert years.tolist() == [2000, 2001, 2002]
    assert values.shape == (3, 12)
    assert matrix_weights.shape == (3, 12)
    assert np.all(matrix_weights > 0)


def test_year_matrices_mark_absent_months_as_zero_weight():
    frame = _multi_year_frame(n_years=2)
    frame.loc[frame.index[5], "extent_pct"] = np.nan
    prepared = prepare_monthly_extent(frame)
    weights = candidate_weights(prepared)

    _, values, matrix_weights = _year_matrices(prepared, weights)

    assert np.isnan(values[0, 5])
    assert matrix_weights[0, 5] == 0.0


def test_year_matrices_place_partial_years_by_true_calendar_month():
    """A short year must not have its months inferred positionally.

    The previous implementation tiled ``arange(1, 13)`` across each drawn year,
    which is only correct while every year is complete. Dropping the
    complete-year requirement makes that assumption silently mislabel months.
    """
    index = pd.date_range("2000-07-01", periods=6, freq="MS")
    frame = pd.DataFrame({"extent_pct": np.arange(6.0), "invalid_pct": 0.0}, index=index)
    prepared = prepare_monthly_extent(frame)
    weights = candidate_weights(prepared)

    _, values, matrix_weights = _year_matrices(prepared, weights)

    assert np.all(matrix_weights[0, :6] == 0.0)
    assert np.all(matrix_weights[0, 6:] > 0.0)
    assert values[0, 6] == pytest.approx(0.0)


def test_design_shape_grows_with_order():
    assert _design(0).shape == (12, 1)
    assert _design(1).shape == (12, 3)
    assert _design(3).shape == (12, 7)


def test_gram_solve_recovers_a_known_harmonic():
    prepared = prepare_monthly_extent(_multi_year_frame(n_years=4, amplitude=20.0, mean=50.0, phase=7))
    weights = candidate_weights(prepared)
    _, values, matrix_weights = _year_matrices(prepared, weights)
    design = _design(1)

    gram = np.zeros((3, 3))
    moment = np.zeros(3)
    for row in range(values.shape[0]):
        year_gram, year_moment, _, _ = _year_gram(values[row], matrix_weights[row], design)
        gram += year_gram
        moment += year_moment
    beta = _solve_gram(gram, moment)

    curve = design @ beta
    assert curve.max() - curve.min() == pytest.approx(40.0, abs=1e-6)
    assert int(np.argmax(curve)) + 1 == 7


def test_solve_gram_returns_none_when_singular():
    assert _solve_gram(np.zeros((3, 3)), np.zeros(3)) is None

