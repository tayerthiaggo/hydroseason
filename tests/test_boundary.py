import pandas as pd
import pytest

from hydroseason._boundary import (
    SIGNAL_FLOOR_FRACTION,
    BoundarySelection,
    RobustBoundaryConfig,
    select_boundary_sequence,
    select_cycle_peak,
    select_window_minimum,
)


def test_signal_floor_fraction_is_defined_and_importable():
    assert SIGNAL_FLOOR_FRACTION == 0.10


def test_peak_selector_flags_isolated_high_without_hiding_raw_maximum():
    index = pd.date_range("2020-01-01", periods=8, freq="MS")
    cycle = pd.DataFrame({
        "extent_pct": [2, 10, 90, 11, 8, 6, 4, 2],
        "invalid_pct": 0.0, "candidate_usable": True,
    }, index=index)
    peak = select_cycle_peak(cycle, start=index[0], end=index[-1], noise_pp=5, amplitude_pp=88)
    assert peak.raw_month == pd.Timestamp("2020-03-01")
    assert peak.selection_status == "ambiguous"


def test_peak_selector_flags_low_quality_peak_without_inventing_date():
    index = pd.date_range("2020-01-01", periods=8, freq="MS")
    cycle = pd.DataFrame({
        "extent_pct": [2, 90, 10, 8, 6, 4, 3, 2],
        "invalid_pct": [0, 60, 0, 0, 0, 0, 0, 0],
        "candidate_usable": [True, False, True, True, True, True, True, True],
        "quality_state": ["usable", "low", "usable", "usable", "usable", "usable", "usable", "usable"],
    }, index=index)
    peak = select_cycle_peak(cycle, start=index[0], end=index[-1], noise_pp=1, amplitude_pp=87)
    assert peak.raw_month == pd.Timestamp("2020-02-01")
    assert peak.selected_month == peak.raw_month
    assert peak.selection_status == "low_quality"


def test_peak_selector_falls_back_to_low_quality_when_no_usable_candidates():
    index = pd.date_range("2020-01-01", periods=8, freq="MS")
    cycle = pd.DataFrame({
        "extent_pct": [2, 90, 10, 8, 6, 4, 3, 2],
        "invalid_pct": [60, 60, 60, 60, 60, 60, 60, 60],
        "candidate_usable": [False] * 8,
        "quality_state": ["low"] * 8,
    }, index=index)
    peak = select_cycle_peak(cycle, start=index[0], end=index[-1], noise_pp=1, amplitude_pp=87)
    assert peak.raw_month == pd.Timestamp("2020-02-01")
    assert peak.selected_month == peak.raw_month
    assert peak.selection_status == "low_quality"


def test_peak_candidates_exclude_both_trough_boundaries():
    index = pd.date_range("2020-01-01", periods=8, freq="MS")
    cycle = pd.DataFrame({
        "extent_pct": [90, 10, 30, 40, 50, 45, 20, 88],
        "invalid_pct": 0.0, "candidate_usable": True,
    }, index=index)
    peak = select_cycle_peak(cycle, start=index[0], end=index[-1], noise_pp=1, amplitude_pp=10)
    assert index[0] < peak.selected_month < index[-1]


def test_boundary_selection_keeps_raw_and_selected_observations():
    selection = BoundarySelection(
        raw_month=pd.Timestamp("2020-09-01"), raw_extent_pct=2.0,
        selected_month=pd.Timestamp("2020-09-01"), selected_extent_pct=2.0,
        run_start=pd.Timestamp("2020-09-01"), run_end=pd.Timestamp("2020-10-01"),
        window_status="full", selection_status="raw", support=1.0,
        n_expected=7, n_usable=7, phase_shift_months=0,
    )
    assert selection.raw_month == selection.selected_month


def test_boundary_selection_can_diverge_between_raw_and_selected():
    selection = BoundarySelection(
        raw_month=pd.Timestamp("2020-09-01"), raw_extent_pct=2.0,
        selected_month=pd.Timestamp("2020-10-01"), selected_extent_pct=4.0,
        run_start=pd.Timestamp("2020-09-01"), run_end=pd.Timestamp("2020-11-01"),
        window_status="full", selection_status="quality_adjusted", support=0.85,
        n_expected=7, n_usable=6, phase_shift_months=1,
    )
    assert selection.raw_month != selection.selected_month
    assert selection.raw_extent_pct != selection.selected_extent_pct


def test_boundary_config_rejects_impossible_coverage():
    with pytest.raises(ValueError, match="min_window_coverage"):
        RobustBoundaryConfig(min_window_coverage=1.1)


def test_boundary_config_rejects_non_positive_usable_candidates():
    with pytest.raises(ValueError, match="min_usable_candidates"):
        RobustBoundaryConfig(min_usable_candidates=0)


def test_boundary_config_rejects_out_of_range_support_threshold():
    with pytest.raises(ValueError, match="support_threshold"):
        RobustBoundaryConfig(support_threshold=1.5)


def test_boundary_config_rejects_non_positive_anomaly_noise_scales():
    with pytest.raises(ValueError, match="anomaly_noise_scales"):
        RobustBoundaryConfig(anomaly_noise_scales=0)


def test_boundary_config_defaults_are_valid():
    config = RobustBoundaryConfig()
    assert config.min_usable_candidates == 2
    assert config.min_window_coverage == pytest.approx(0.70)
    assert config.support_threshold == pytest.approx(0.80)
    assert config.anomaly_noise_scales == pytest.approx(3.0)


def test_singleton_low_is_retained_but_marked_ambiguous():
    index = pd.date_range("2020-06-01", periods=7, freq="MS")
    frame = pd.DataFrame({
        "extent_pct": [20, 15, 10, 1, 11, 16, 22],
        "invalid_pct": 0.0, "candidate_usable": True,
    }, index=index)
    result = select_window_minimum(frame, expected=pd.Timestamp("2020-09-01"),
                                   expected_count=7, noise_pp=2.0, amplitude_pp=21.0)
    assert result.raw_month == pd.Timestamp("2020-09-01")
    assert result.selected_month == result.raw_month
    assert result.selection_status == "ambiguous"


def test_low_run_is_contiguous_and_does_not_cross_rewetting():
    index = pd.date_range("2020-06-01", periods=7, freq="MS")
    frame = pd.DataFrame({
        "extent_pct": [8, 2, 2.2, 9, 2.1, 10, 15],
        "invalid_pct": 0.0, "candidate_usable": True,
    }, index=index)
    result = select_window_minimum(frame, expected=pd.Timestamp("2020-09-01"),
                                   expected_count=7, noise_pp=0.5, amplitude_pp=13.0)
    assert result.run_start == pd.Timestamp("2020-07-01")
    assert result.run_end == pd.Timestamp("2020-08-01")


def test_right_truncated_window_is_provisional_evidence():
    index = pd.date_range("2020-08-01", periods=5, freq="MS")
    frame = pd.DataFrame({"extent_pct": [5, 4, 3, 2, 1], "invalid_pct": 0.0,
                          "candidate_usable": True}, index=index)
    result = select_window_minimum(frame, expected=pd.Timestamp("2020-11-01"),
                                   expected_count=7, noise_pp=0.2, amplitude_pp=4.0)
    assert result.window_status == "right_truncated"
    assert result.support < 0.80


def test_sequence_optimizer_uses_equivalent_date_to_avoid_short_cycle():
    opportunities = [
        {"year": 2020, "expected": pd.Timestamp("2020-09-01"),
         "candidates": [(pd.Timestamp("2020-08-01"), 2.0),
                        (pd.Timestamp("2020-09-01"), 2.1)]},
        {"year": 2021, "expected": pd.Timestamp("2021-09-01"),
         "candidates": [(pd.Timestamp("2021-07-01"), 1.9),
                        (pd.Timestamp("2021-09-01"), 2.0)]},
    ]
    selected = select_boundary_sequence(opportunities)
    assert selected == [pd.Timestamp("2020-09-01"), pd.Timestamp("2021-09-01")]


def test_sequence_optimizer_preserves_unresolved_year_and_restarts():
    opportunities = [
        {"year": 2020, "expected": pd.Timestamp("2020-09-01"),
         "candidates": [(pd.Timestamp("2020-09-01"), 2.0)]},
        {"year": 2021, "expected": pd.Timestamp("2021-09-01"), "candidates": []},
        {"year": 2022, "expected": pd.Timestamp("2022-09-01"),
         "candidates": [(pd.Timestamp("2022-09-01"), 2.0)]},
    ]
    assert select_boundary_sequence(opportunities) == [
        pd.Timestamp("2020-09-01"), None, pd.Timestamp("2022-09-01")
    ]


def test_sequence_optimizer_handles_single_opportunity_block():
    opportunities = [
        {"year": 2020, "expected": pd.Timestamp("2020-09-01"),
         "candidates": [(pd.Timestamp("2020-08-01"), 3.0),
                        (pd.Timestamp("2020-09-01"), 2.5)]},
    ]
    assert select_boundary_sequence(opportunities) == [pd.Timestamp("2020-09-01")]


def test_sequence_optimizer_handles_empty_opportunity_list():
    assert select_boundary_sequence([]) == []


def test_sequence_optimizer_can_preserve_each_year_raw_minimum():
    opportunities = [
        {"year": 2020, "expected": pd.Timestamp("2020-09-01"),
         "candidates": [(pd.Timestamp("2020-09-01"), 1.0),
                        (pd.Timestamp("2020-10-01"), 1.01)]},
        {"year": 2021, "expected": pd.Timestamp("2021-09-01"),
         "candidates": [(pd.Timestamp("2021-08-01"), 1.0),
                        (pd.Timestamp("2021-09-01"), 1.01)]},
    ]
    assert select_boundary_sequence(
        opportunities, raw_minimum_rel_tolerance=0.0
    ) == [pd.Timestamp("2020-09-01"), pd.Timestamp("2021-08-01")]


def test_sequence_optimizer_returns_none_for_all_unresolved_years():
    opportunities = [
        {"year": 2020, "expected": pd.Timestamp("2020-09-01"), "candidates": []},
        {"year": 2021, "expected": pd.Timestamp("2021-09-01"), "candidates": []},
    ]
    assert select_boundary_sequence(opportunities) == [None, None]


def test_fidelity_guard_prevents_materially_higher_coherent_candidate():
    # Test that raw_minimum_rel_tolerance actually constrains the DP to prefer
    # the true per-year minimum over a materially higher candidate, even when
    # the higher candidate would create a more coherent 12-month cycle.
    #
    # Setup: two years, each with two candidates. Year 2020's minimum (2.0) is
    # at the off-cycle month (Sept), while an on-cycle month (Aug) has a higher
    # value (2.15 = 7.5% above minimum, clearly outside 5% tolerance). Year
    # 2021's minimum (1.9) is at July (2 months off-cycle), while Sept has 2.0
    # (5.26% above minimum, just outside 5% tolerance). Without the guard, the
    # DP prefers both Sept months for a clean 12-month cycle. With the guard at
    # 5%, year 2021 must revert to its true minimum at July.
    opportunities = [
        {
            "year": 2020,
            "expected": pd.Timestamp("2020-09-01"),
            "candidates": [
                (pd.Timestamp("2020-08-01"), 2.15),  # 7.5% above 2020-min
                (pd.Timestamp("2020-09-01"), 2.0),   # true minimum
            ],
        },
        {
            "year": 2021,
            "expected": pd.Timestamp("2021-09-01"),
            "candidates": [
                (pd.Timestamp("2021-07-01"), 1.9),   # true minimum
                (pd.Timestamp("2021-09-01"), 2.0),   # 5.26% above 2021-min
            ],
        },
    ]

    # Without guard (None): old value-blind behavior, coherence wins for both
    selected_no_guard = select_boundary_sequence(opportunities)
    assert selected_no_guard == [
        pd.Timestamp("2020-09-01"),
        pd.Timestamp("2021-09-01"),
    ]

    # With guard at 0.05 (5%): true minimum is preserved, year 2021 stays July
    selected_with_guard = select_boundary_sequence(
        opportunities, raw_minimum_rel_tolerance=0.05
    )
    assert selected_with_guard == [
        pd.Timestamp("2020-09-01"),
        pd.Timestamp("2021-07-01"),  # forced back to true minimum
    ]


def _climatology_frame():
    """Ten years where March is reliably clear and January reliably cloudy."""
    idx = pd.date_range("2010-01-01", periods=120, freq="MS")
    invalid = []
    for date in idx:
        if date.month == 1:
            invalid.append(30.0)
        elif date.month == 3:
            invalid.append(4.0)
        else:
            invalid.append(2.0)
    return pd.DataFrame({"extent_pct": 10.0, "invalid_pct": invalid}, index=idx)


def test_climatology_reports_a_threshold_per_calendar_month():
    from hydroseason._boundary import month_of_year_invalid_climatology

    clim = month_of_year_invalid_climatology(_climatology_frame(), fallback_pct=20.0)

    assert set(clim) == set(range(1, 13))
    assert clim[1] == pytest.approx(30.0, abs=0.5)
    assert clim[3] == pytest.approx(4.0, abs=0.5)


def test_climatology_falls_back_when_a_month_has_too_little_history():
    from hydroseason._boundary import month_of_year_invalid_climatology

    frame = _climatology_frame().iloc[:24]  # only two samples per month
    clim = month_of_year_invalid_climatology(frame, min_years=5, fallback_pct=20.0)

    assert clim[1] == 20.0
    assert clim[3] == 20.0


def test_a_cloudy_month_that_is_normal_for_itself_is_not_anomalous():
    from hydroseason._boundary import peak_quality_verdict

    # 30% invalid in a January whose own p90 is 30% -- an ordinary January.
    assert peak_quality_verdict(30.0, 1, {1: 30.0}) == "normal"


def test_a_month_far_above_its_own_norm_is_anomalous():
    from hydroseason._boundary import peak_quality_verdict

    # 87.2% invalid in a March whose p90 is 47.3% -- the reviewed Daly 2011 case.
    assert peak_quality_verdict(87.2, 3, {3: 47.3}) == "anomalous"


def test_the_absolute_backstop_catches_a_month_that_is_always_obscured():
    from hydroseason._boundary import peak_quality_verdict

    # A month whose own p90 is 90% cannot excuse an unobservable observation.
    assert peak_quality_verdict(85.0, 7, {7: 90.0}, absolute_backstop_pct=80.0) == "anomalous"


def test_a_missing_invalid_value_is_not_treated_as_anomalous():
    from hydroseason._boundary import peak_quality_verdict

    assert peak_quality_verdict(float("nan"), 5, {5: 10.0}) == "normal"
