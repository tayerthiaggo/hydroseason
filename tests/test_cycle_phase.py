import numpy as np
import pandas as pd
import pytest

from hydroseason._cycle_phase import (
    NormalisedCycle,
    PhaseThresholds,
    effective_window,
    normalise_cycle,
    smooth_for_geometry,
)


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


def _cycle(values, start=None, end=None):
    index = pd.date_range("2000-07-01", periods=len(values), freq="MS")
    frame = pd.DataFrame({"extent_pct": values, "candidate_usable": True}, index=index)
    return frame, values[0] if start is None else start, values[-1] if end is None else end


def test_troughs_map_to_zero_and_peak_maps_to_one():
    values = [10.0, 30.0, 60.0, 90.0, 60.0, 30.0, 10.0]
    frame, start, end = _cycle(values)

    result = normalise_cycle(frame, start_extent=start, end_extent=end, window=1, resolution_floor_pp=0.5)

    assert isinstance(result, NormalisedCycle)
    assert result.sufficient
    assert result.z.iloc[0] == pytest.approx(0.0)
    assert result.z.iloc[-1] == pytest.approx(0.0)
    assert result.z.max() == pytest.approx(1.0)


def test_sloping_envelope_is_removed():
    """A cycle ending higher than it started still troughs at zero both ends."""
    values = [10.0, 40.0, 80.0, 40.0, 20.0]
    frame, _, _ = _cycle(values)

    result = normalise_cycle(frame, start_extent=10.0, end_extent=20.0, window=1, resolution_floor_pp=0.5)

    assert result.z.iloc[0] == pytest.approx(0.0)
    assert result.z.iloc[-1] == pytest.approx(0.0)


def test_values_are_clipped_into_the_unit_interval():
    values = [10.0, 30.0, 90.0, 30.0, 10.0]
    frame, start, end = _cycle(values)

    result = normalise_cycle(frame, start_extent=start, end_extent=end, window=1, resolution_floor_pp=0.5)

    assert result.z.min() >= 0.0
    assert result.z.max() <= 1.0


def test_spike_does_not_deflate_the_whole_cycle():
    """The audit finding: a raw-peak denominator loses the wet phase to one spike."""
    clean = [10.0, 30.0, 60.0, 75.0, 60.0, 30.0, 10.0]
    spiked = list(clean)
    spiked[1] = 99.0

    clean_frame, clean_start, clean_end = _cycle(clean)
    spiked_frame, spiked_start, spiked_end = _cycle(spiked)

    clean_result = normalise_cycle(
        clean_frame, start_extent=clean_start, end_extent=clean_end, window=3, resolution_floor_pp=0.5
    )
    spiked_result = normalise_cycle(
        spiked_frame, start_extent=spiked_start, end_extent=spiked_end, window=3, resolution_floor_pp=0.5
    )

    # The genuine mid-cycle high must still clear a 0.7 upper band in both.
    assert clean_result.smoothed_z.max() >= 0.7
    assert spiked_result.smoothed_z.max() >= 0.7


def test_flat_cycle_is_insufficient():
    values = [10.0, 10.0, 10.0, 10.0, 10.0]
    frame, start, end = _cycle(values)

    result = normalise_cycle(frame, start_extent=start, end_extent=end, window=1, resolution_floor_pp=0.5)

    assert not result.sufficient


def test_denominator_below_the_floor_is_insufficient():
    values = [10.0, 10.2, 10.3, 10.2, 10.0]
    frame, start, end = _cycle(values)

    result = normalise_cycle(frame, start_extent=start, end_extent=end, window=1, resolution_floor_pp=1.0)

    assert not result.sufficient
    assert np.isfinite(result.denominator_pp)


def test_no_value_is_ever_infinite():
    values = [0.0, 0.0, 0.0, 0.0]
    frame, start, end = _cycle(values)

    result = normalise_cycle(frame, start_extent=start, end_extent=end, window=1, resolution_floor_pp=0.5)

    assert np.isfinite(result.z.to_numpy(dtype=float)).all() or not result.sufficient

