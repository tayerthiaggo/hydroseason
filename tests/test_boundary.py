import pandas as pd
import pytest

from hydroseason._boundary import (
    BoundarySelection,
    RobustBoundaryConfig,
    select_window_minimum,
)


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
