import numpy as np
import pandas as pd
import pytest

from hydroseason._cycle_phase import PhaseThresholds, effective_window, smooth_for_geometry


def _series(values):
    index = pd.date_range("2000-01-01", periods=len(values), freq="MS")
    return pd.Series(values, index=index, dtype=float)


@pytest.mark.parametrize(
    "requested, cycle_length, expected",
    [(3, 12, 3), (5, 12, 5), (7, 5, 5), (9, 4, 3), (3, 1, 1), (1, 12, 1), (7, 2, 1)],
)
def test_effective_window_clamps_to_the_largest_valid_odd_window(requested, cycle_length, expected):
    assert effective_window(requested, cycle_length) == expected


def test_effective_window_is_always_odd_and_positive():
    for requested in range(1, 16, 2):
        for cycle_length in range(1, 16):
            window = effective_window(requested, cycle_length)
            assert window >= 1 and window % 2 == 1


def test_window_of_one_is_a_passthrough():
    values = _series([1.0, 9.0, 2.0, 8.0])

    smoothed = smooth_for_geometry(values, 1)

    assert smoothed.tolist() == values.tolist()


def test_median_suppresses_a_single_spike():
    values = _series([10.0, 10.0, 90.0, 10.0, 10.0])

    smoothed = smooth_for_geometry(values, 3)

    assert smoothed.iloc[2] == pytest.approx(10.0)


def test_smoothing_preserves_length_and_index():
    values = _series(np.arange(12.0))

    smoothed = smooth_for_geometry(values, 5)

    assert len(smoothed) == len(values)
    assert smoothed.index.equals(values.index)


def test_edges_are_filled_not_dropped():
    values = _series(np.arange(12.0))

    smoothed = smooth_for_geometry(values, 5)

    assert smoothed.notna().all()


def test_missing_values_do_not_propagate_across_the_whole_window():
    values = _series([1.0, 2.0, np.nan, 4.0, 5.0])

    smoothed = smooth_for_geometry(values, 3)

    assert smoothed.notna().sum() >= 4


def test_phase_thresholds_have_no_defaults():
    with pytest.raises(TypeError):
        PhaseThresholds()


def test_phase_thresholds_share_config_validation():
    with pytest.raises(ValueError, match="phase_smoothing_window"):
        PhaseThresholds(0.25, 0.75, 2, 4)
