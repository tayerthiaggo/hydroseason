import numpy as np
import pandas as pd
import pytest

from hydroseason._seasonality import (
    HarmonicSelection,
    _design,
    _solve_gram,
    _year_gram,
    _year_matrices,
    select_harmonic_order,
)
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


def _matrices(frame):
    prepared = prepare_monthly_extent(frame)
    weights = candidate_weights(prepared)
    _, values, matrix_weights = _year_matrices(prepared, weights)
    return values, matrix_weights


def test_clean_sinusoid_selects_order_one():
    values, weights = _matrices(_multi_year_frame(n_years=8, amplitude=20.0))

    selection = select_harmonic_order(values, weights)

    assert isinstance(selection, HarmonicSelection)
    assert selection.order == 1
    assert selection.mean_skill > 0.9


def test_order_zero_scores_exactly_zero():
    """Order 0 is the training weighted mean, which is the null itself."""
    values, weights = _matrices(_multi_year_frame(n_years=6))

    selection = select_harmonic_order(values, weights, max_order=0)

    assert selection.order == 0
    assert selection.mean_skill == pytest.approx(0.0, abs=1e-12)
    assert selection.pooled_skill == pytest.approx(0.0, abs=1e-12)


def test_pure_noise_selects_the_nonseasonal_null():
    rng = np.random.default_rng(0)
    months = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    frame = pd.DataFrame(
        {"extent_pct": rng.uniform(20.0, 60.0, size=len(months)), "invalid_pct": 0.0},
        index=months,
    )
    values, weights = _matrices(frame)

    selection = select_harmonic_order(values, weights)

    assert selection.order == 0


def test_one_standard_error_rule_prefers_the_simpler_order():
    """A higher harmonic that adds only noise-level skill must not be selected."""
    rng = np.random.default_rng(7)
    months = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    angle = 2.0 * np.pi * (months.month.to_numpy() - 7) / 12.0
    values_series = 50.0 + 20.0 * np.cos(angle) + rng.normal(0.0, 3.0, size=len(months))
    frame = pd.DataFrame({"extent_pct": np.clip(values_series, 0, 100), "invalid_pct": 0.0}, index=months)
    values, weights = _matrices(frame)

    selection = select_harmonic_order(values, weights)

    assert selection.order == 1
    assert 3 in selection.eligible_orders



def test_bimodal_record_selects_order_two():
    months = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    angle = 2.0 * np.pi * (months.month - 1) / 12.0
    values_series = 50.0 + 20.0 * np.cos(2.0 * angle)
    frame = pd.DataFrame({"extent_pct": values_series, "invalid_pct": 0.0}, index=months)
    values, weights = _matrices(frame)

    selection = select_harmonic_order(values, weights)

    assert selection.order == 2


def test_partial_years_contribute_rather_than_being_dropped():
    frame = _multi_year_frame(n_years=8)
    frame.loc[frame.index[3], "extent_pct"] = np.nan
    frame.loc[frame.index[16], "extent_pct"] = np.nan
    frame.loc[frame.index[17], "extent_pct"] = np.nan
    values, weights = _matrices(frame)

    selection = select_harmonic_order(values, weights)

    assert selection.order == 1
    assert len(selection.fold_skills) == 8


def test_low_weight_months_are_less_informative_than_full_months():
    clean = _multi_year_frame(n_years=8)
    degraded = clean.copy()
    for position in (5, 17, 29):
        degraded.iloc[position, degraded.columns.get_loc("extent_pct")] = 0.0
        degraded.iloc[position, degraded.columns.get_loc("invalid_pct")] = 99.0

    clean_selection = select_harmonic_order(*_matrices(clean))
    degraded_selection = select_harmonic_order(*_matrices(degraded))

    assert degraded_selection.order == clean_selection.order
    assert degraded_selection.mean_skill > 0.8


def test_too_few_years_returns_none():
    values, weights = _matrices(_multi_year_frame(n_years=1))

    assert select_harmonic_order(values, weights) is None


def test_selection_is_deterministic():
    values, weights = _matrices(_multi_year_frame(n_years=6))

    first = select_harmonic_order(values, weights)
    second = select_harmonic_order(values, weights)

    assert first.order == second.order
    assert first.fold_skills == second.fold_skills


