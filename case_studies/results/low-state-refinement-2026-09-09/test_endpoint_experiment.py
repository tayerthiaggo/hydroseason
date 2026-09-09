"""Hand-checked scientific counterexamples for the research-only prototype."""
from __future__ import annotations

import pandas as pd
import pytest
import numpy as np

from endpoint_experiment import refine_experimental, second_difference_scale
from hydroseason._state_input import prepare_monthly_extent
from hydroseason._trough_refinement import PeakBoundary
from hydroseason._trough_refinement_defaults import TROUGH_REFINEMENT_POLICY


def run(values, tolerance=0.0):
    dates = pd.date_range("2020-01-01", periods=len(values), freq="MS")
    frame = prepare_monthly_extent(pd.DataFrame(
        {"extent_pct": values, "invalid_pct": 0.0}, index=dates,
    ))
    return refine_experimental(
        frame,
        left_peak=PeakBoundary(dates[0], (dates[0],), "point", "normal"),
        right_peak=PeakBoundary(dates[-1], (dates[-1],), "point", "normal"),
        policy=TROUGH_REFINEMENT_POLICY,
        measurement_tolerance_pp=tolerance,
    )


def test_small_increases_remain_in_one_low_state():
    result = run([0.4, 0.2, 0.118779628, 0.119376506, 0.121805752, 0.2, 0.4], 0.004)
    assert result.boundary == pd.Timestamp("2020-05-01")
    assert result.low_state_start == pd.Timestamp("2020-03-01")
    assert result.recovery_start == pd.Timestamp("2020-06-01")


def test_plateau_duration_is_not_endpoint_uncertainty():
    result = run([0.4, 0.2, 0.12, 0.12, 0.12, 0.2, 0.4])
    assert result.low_state_start == pd.Timestamp("2020-03-01")
    assert result.low_state_end == pd.Timestamp("2020-05-01")
    assert result.boundary_candidates == (pd.Timestamp("2020-05-01"),)


def test_cumulative_recovery_uses_fixed_reference_not_chained_monthly_differences():
    result = run([0.4, 0.25, 0.12, 0.121, 0.122, 0.123, 0.125, 0.13, 0.14, 0.3], 0.004)
    assert result.boundary == pd.Timestamp("2020-06-01")
    assert result.recovery_start == pd.Timestamp("2020-07-01")


def test_clear_recovery_is_not_absorbed():
    result = run([0.4, 0.2, 0.12, 0.15, 0.3], 0.004)
    assert result.boundary == pd.Timestamp("2020-03-01")


def test_no_departure_means_no_confirmed_boundary():
    result = run([0.12] * 7, 0.004)
    assert result.status == "unresolved"
    assert result.boundary is None
    assert result.recovery_start is None


@pytest.mark.parametrize("factor", [0.1, 10.0])
def test_units_do_not_change_dates(factor):
    values = [0.4, 0.2, 0.118, 0.119, 0.121, 0.2, 0.4]
    expected = run(values, 0.004)
    actual = run([value * factor for value in values], 0.004 * factor)
    assert actual.boundary == expected.boundary
    assert actual.boundary_candidates == expected.boundary_candidates


def test_detrended_scale_recovers_simulated_independent_noise_without_valley_fit():
    noise = np.random.default_rng(731).normal(0.0, 0.003, 10000)
    values = np.linspace(0.1, 2.0, len(noise)) + noise
    assert second_difference_scale(values) == pytest.approx(0.003, rel=0.06)


def test_detrended_scale_does_not_join_across_a_gap():
    assert second_difference_scale(np.array([0., 1., 2., np.nan, 100., 110., 120.])) == 0.0


def test_research_hook_restores_original_callable_after_failure():
    import hydroseason._trough_refinement as core
    before = core._refine_selected_span
    with pytest.raises(ValueError):
        run([0.4, 0.12, 0.4], -0.1)
    assert core._refine_selected_span is before


def test_quality_challenges_are_still_applied():
    dates = pd.date_range("2020-01-01", periods=7, freq="MS")
    frame = prepare_monthly_extent(pd.DataFrame({
        "extent_pct": [0.4, 0.2, 0.12, 0.121, 0.122, 0.2, 0.4],
        "invalid_pct": [0., 0., 0., 50., 0., 0., 0.],
    }, index=dates))
    result = refine_experimental(
        frame,
        left_peak=PeakBoundary(dates[0], (dates[0],), "point", "normal"),
        right_peak=PeakBoundary(dates[-1], (dates[-1],), "point", "normal"),
        policy=TROUGH_REFINEMENT_POLICY, measurement_tolerance_pp=0.004,
    )
    assert result.status == "unresolved"
    assert result.reason == "unstable_quality_sensitivity"


def test_scoring_keeps_abstentions_in_coverage_and_false_precision_denominators():
    from evaluate_endpoint import score_records
    score = score_records([
        {"truth_index": 5, "predicted_index": 5, "support_indexes": [5]},
        {"truth_index": 5, "predicted_index": 4, "support_indexes": [4, 5]},
        {"truth_index": 5, "predicted_index": None, "support_indexes": []},
        {"truth_index": None, "predicted_index": 3, "support_indexes": [3]},
    ])
    assert score.get("n") == 4
    assert score["resolvable_n"] == 3
    assert score["all_case_applied_n"] == 3
    assert score["resolvable_coverage"] == pytest.approx(2 / 3)
    assert score["truth_support_coverage"] == pytest.approx(2 / 3)
    assert score["unresolvable_n"] == 1
    assert score["false_precise_unresolvable_n"] == 1
    assert score["point_predictions_n"] == 2
    assert score["wrong_point_predictions_n"] == 1
