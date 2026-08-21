import time

import numpy as np
import pandas as pd
import pytest

from hydroseason._seasonality import (
    AmplitudeEvidence,
    HarmonicSelection,
    _design,
    _solve_gram,
    _year_gram,
    _year_matrices,
    amplitude_evidence,
    periodicity_p_value,
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


def test_amplitude_matches_the_fitted_curve_range():
    values, weights = _matrices(_multi_year_frame(n_years=8, amplitude=20.0))
    selection = select_harmonic_order(values, weights)

    evidence = amplitude_evidence(values, weights, selection, resolution_floor_pp=0.5)

    assert isinstance(evidence, AmplitudeEvidence)
    assert evidence.seasonal_amplitude_pp == pytest.approx(40.0, abs=1e-6)
    assert not evidence.at_or_below_floor


def test_constant_record_never_produces_infinity():
    """The defect this replaces: amplitude / 0 evaluated to np.inf."""
    months = pd.date_range("2000-01-01", periods=12 * 8, freq="MS")
    frame = pd.DataFrame({"extent_pct": 0.0, "invalid_pct": 0.0}, index=months)
    values, weights = _matrices(frame)
    selection = select_harmonic_order(values, weights)

    evidence = amplitude_evidence(values, weights, selection, resolution_floor_pp=0.5)

    assert np.isfinite(evidence.amplitude_noise_ratio)
    assert evidence.amplitude_noise_ratio == 0.0
    assert evidence.at_or_below_floor


def test_constant_nonzero_record_also_stays_finite():
    months = pd.date_range("2000-01-01", periods=12 * 8, freq="MS")
    frame = pd.DataFrame({"extent_pct": 42.0, "invalid_pct": 0.0}, index=months)
    values, weights = _matrices(frame)
    selection = select_harmonic_order(values, weights)

    evidence = amplitude_evidence(values, weights, selection, resolution_floor_pp=0.5)

    assert evidence.amplitude_noise_ratio == 0.0
    assert evidence.at_or_below_floor


def test_amplitude_just_below_floor_is_flagged():
    months = pd.date_range("2000-01-01", periods=12 * 8, freq="MS")
    angle = 2.0 * np.pi * (months.month.to_numpy() - 7) / 12.0
    frame = pd.DataFrame({"extent_pct": 50.0 + 0.1 * np.cos(angle), "invalid_pct": 0.0}, index=months)
    values, weights = _matrices(frame)
    selection = select_harmonic_order(values, weights)

    evidence = amplitude_evidence(values, weights, selection, resolution_floor_pp=1.0)

    assert evidence.at_or_below_floor
    assert evidence.amplitude_noise_ratio == 0.0


def test_noise_denominator_never_drops_below_the_floor():
    """A noiseless record must not divide by a near-zero noise scale."""
    values, weights = _matrices(_multi_year_frame(n_years=8, amplitude=20.0))
    selection = select_harmonic_order(values, weights)

    evidence = amplitude_evidence(values, weights, selection, resolution_floor_pp=2.0)

    assert evidence.amplitude_noise_ratio == pytest.approx(40.0 / 2.0, rel=1e-6)


def test_noisy_record_has_a_lower_ratio_than_a_clean_one():
    rng = np.random.default_rng(3)
    months = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    angle = 2.0 * np.pi * (months.month.to_numpy() - 7) / 12.0
    clean = pd.DataFrame({"extent_pct": 50.0 + 20.0 * np.cos(angle), "invalid_pct": 0.0}, index=months)
    noisy_values = np.clip(50.0 + 20.0 * np.cos(angle) + rng.normal(0.0, 8.0, size=len(months)), 0, 100)
    noisy = pd.DataFrame({"extent_pct": noisy_values, "invalid_pct": 0.0}, index=months)

    clean_values, clean_weights = _matrices(clean)
    noisy_values_matrix, noisy_weights = _matrices(noisy)
    clean_evidence = amplitude_evidence(
        clean_values, clean_weights, select_harmonic_order(clean_values, clean_weights), resolution_floor_pp=0.5
    )
    noisy_evidence = amplitude_evidence(
        noisy_values_matrix,
        noisy_weights,
        select_harmonic_order(noisy_values_matrix, noisy_weights),
        resolution_floor_pp=0.5,
    )

    assert noisy_evidence.amplitude_noise_ratio < clean_evidence.amplitude_noise_ratio


def test_resolution_floor_must_be_positive():
    values, weights = _matrices(_multi_year_frame(n_years=6))
    selection = select_harmonic_order(values, weights)

    with pytest.raises(ValueError, match="resolution_floor_pp"):
        amplitude_evidence(values, weights, selection, resolution_floor_pp=0.0)


def test_strong_seasonal_record_is_significant():
    values, weights = _matrices(_multi_year_frame(n_years=12, amplitude=20.0))

    p_value = periodicity_p_value(values, weights, n_null=199, random_state=0)

    assert p_value <= 0.01


def test_noise_record_is_not_significant():
    rng = np.random.default_rng(11)
    months = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    frame = pd.DataFrame(
        {"extent_pct": rng.uniform(20.0, 60.0, size=len(months)), "invalid_pct": 0.0},
        index=months,
    )
    values, weights = _matrices(frame)

    p_value = periodicity_p_value(values, weights, n_null=199, random_state=0)

    assert p_value > 0.05


def test_p_value_is_bounded_and_deterministic():
    values, weights = _matrices(_multi_year_frame(n_years=8))

    first = periodicity_p_value(values, weights, n_null=99, random_state=4)
    second = periodicity_p_value(values, weights, n_null=99, random_state=4)

    assert first == second
    assert 1.0 / (99 + 1.0) <= first <= 1.0


def test_rotation_preserves_each_years_values_weights_and_gaps():
    from hydroseason._seasonality import _rotate_years

    values = np.array([[1.0, 2.0, np.nan, 4.0]], dtype=float)
    weights = np.array([[1.0, 0.5, 0.0, 1.0]], dtype=float)

    rotated_values, rotated_weights = _rotate_years(values, weights, np.array([1]))

    assert np.nansum(rotated_values) == pytest.approx(np.nansum(values))
    assert rotated_weights.sum() == pytest.approx(weights.sum())
    assert np.count_nonzero(np.isnan(rotated_values)) == 1
    # Value and its weight must travel together.
    moved = int(np.where(np.isnan(rotated_values[0]))[0][0])
    assert rotated_weights[0, moved] == 0.0


def test_holding_the_order_fixed_inflates_significance():
    """Pinning the documented reason order re-selection lives inside the loop.

    A null that cannot re-select order is a weaker null, so it produces a
    smaller p-value. If this ever inverts, the re-selection has been lost.
    """
    from hydroseason._seasonality import _null_skills

    rng = np.random.default_rng(2)
    months = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    angle = 2.0 * np.pi * (months.month.to_numpy() - 7) / 12.0
    series = np.clip(50.0 + 4.0 * np.cos(angle) + rng.normal(0.0, 6.0, size=len(months)), 0, 100)
    frame = pd.DataFrame({"extent_pct": series, "invalid_pct": 0.0}, index=months)
    values, weights = _matrices(frame)

    reselected = _null_skills(values, weights, n_null=199, random_state=1, max_order=3, reselect_order=True)
    fixed = _null_skills(values, weights, n_null=199, random_state=1, max_order=3, reselect_order=False)

    assert np.mean(reselected) >= np.mean(fixed)


def test_null_runs_within_a_sane_time_budget():
    """999 resamples over a 30-year record must stay interactive."""
    values, weights = _matrices(_multi_year_frame(n_years=30, amplitude=20.0))

    started = time.perf_counter()
    periodicity_p_value(values, weights, n_null=999, random_state=0)
    elapsed = time.perf_counter() - started

    assert elapsed < 30.0




