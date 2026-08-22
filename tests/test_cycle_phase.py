import numpy as np
import pandas as pd
import pytest

from hydroseason._cycle_phase import (
    UNSPECIFIED,
    NormalisedCycle,
    PhaseThresholds,
    effective_window,
    label_cycle,
    normalise_cycle,
    phase_stability,
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


def _labels(values, *, low=0.25, high=0.75, duration=1, window=1):
    frame, start, end = _cycle(values)
    normalised = normalise_cycle(
        frame, start_extent=start, end_extent=end, window=window, resolution_floor_pp=0.5
    )
    return label_cycle(
        normalised, low_fraction=low, high_fraction=high, min_duration_months=duration
    ).tolist()


def test_ideal_sinusoid_contains_all_four_phases_in_order():
    """Failure 4: the old rules produced no recovery and started dry while high."""
    months = np.arange(13)
    values = (50.0 - 40.0 * np.cos(2.0 * np.pi * months / 12.0)).tolist()

    labels = _labels(values)

    order = [label for index, label in enumerate(labels) if index == 0 or label != labels[index - 1]]
    assert order[0] == "dry"
    assert "recovery" in order
    assert "wet" in order
    assert "recession" in order
    assert order.index("recovery") < order.index("wet") < order.index("recession")


def test_low_plateau_stays_dry_until_sustained_rise():
    values = [5.0, 5.0, 5.0, 5.0, 20.0, 55.0, 85.0, 55.0, 20.0, 5.0]

    labels = _labels(values, duration=1)

    assert labels[:4] == ["dry"] * 4


def test_high_post_peak_extent_cannot_become_dry_before_lower_band_entry():
    values = [5.0, 30.0, 70.0, 95.0, 80.0, 60.0, 35.0, 5.0]

    labels = _labels(values)

    for label, value in zip(labels, values):
        if value >= 60.0:
            assert label != "dry"


def test_missing_transition_evidence_yields_unspecified_not_a_forced_label():
    """A cycle that never reaches the upper band has no wet phase to report."""
    values = [5.0, 8.0, 12.0, 15.0, 12.0, 8.0, 5.0]

    labels = _labels(values, low=0.25, high=0.95, duration=3)

    assert UNSPECIFIED in labels
    assert "wet" not in labels


def test_min_duration_suppresses_a_one_month_blip():
    values = [5.0, 5.0, 25.0, 5.0, 5.0, 40.0, 80.0, 40.0, 5.0]

    labels = _labels(values, duration=2)

    assert labels[2] in {"dry", UNSPECIFIED}


def test_rewetting_pulse_does_not_restart_the_cycle():
    values = [5.0, 30.0, 70.0, 95.0, 60.0, 75.0, 40.0, 10.0, 5.0]

    labels = _labels(values)

    assert labels.count("dry") >= 1
    # One cycle, so the opening dry run and closing dry run are the only two.
    runs = [label for index, label in enumerate(labels) if index == 0 or label != labels[index - 1]]
    assert runs.count("wet") <= 1


def test_insufficient_cycle_is_entirely_unspecified():
    values = [10.0, 10.0, 10.0, 10.0]

    labels = _labels(values)

    assert set(labels) == {UNSPECIFIED}


def test_labels_align_with_the_cycle_index():
    values = [5.0, 30.0, 70.0, 95.0, 60.0, 30.0, 5.0]
    frame, start, end = _cycle(values)
    normalised = normalise_cycle(frame, start_extent=start, end_extent=end, window=1, resolution_floor_pp=0.5)

    labels = label_cycle(normalised, low_fraction=0.25, high_fraction=0.75, min_duration_months=1)

    assert labels.index.equals(frame.index)
    assert len(labels) == len(frame)


def _stability(values, observed_fraction=1.0, noise_pp=1.0, n_replicates=199, **kwargs):
    index = pd.date_range("2000-07-01", periods=len(values), freq="MS")
    frame = pd.DataFrame(
        {
            "extent_pct": values,
            "candidate_usable": True,
            "observed_fraction": observed_fraction,
        },
        index=index,
    )
    params = dict(
        start_extent_candidates=(values[0],),
        end_extent_candidates=(values[-1],),
        low_fraction=0.25,
        high_fraction=0.75,
        min_duration_months=1,
        window=1,
        resolution_floor_pp=0.5,
        noise_pp=noise_pp,
        noise_residuals=np.array([-noise_pp, 0.0, noise_pp]),
        n_replicates=n_replicates,
        random_state=0,
    )
    params.update(kwargs)
    return phase_stability(frame, **params)


def test_probabilities_sum_to_at_most_one_and_stability_is_the_max():
    values = [5.0, 30.0, 70.0, 95.0, 60.0, 30.0, 5.0]

    table = _stability(values)

    totals = table[["p_dry", "p_recovery", "p_wet", "p_recession"]].sum(axis=1)
    assert (totals <= 1.0 + 1e-9).all()
    assert np.allclose(
        table["phase_stability"],
        table[["p_dry", "p_recovery", "p_wet", "p_recession"]].max(axis=1),
    )


def test_clean_cycle_is_highly_stable():
    months = np.arange(13)
    values = (50.0 - 40.0 * np.cos(2.0 * np.pi * months / 12.0)).tolist()

    table = _stability(values, noise_pp=0.5)

    assert table["phase_stability"].median() > 0.8


def test_thin_observational_support_lowers_stability():
    """Observation error is inside the bootstrap, so poorly observed months move."""
    values = [5.0, 30.0, 70.0, 95.0, 60.0, 30.0, 5.0]

    well_observed = _stability(values, observed_fraction=1.0, noise_pp=8.0)
    thinly_observed = _stability(values, observed_fraction=0.1, noise_pp=8.0)

    assert thinly_observed["phase_stability"].mean() <= well_observed["phase_stability"].mean()


def test_month_on_a_threshold_is_less_stable_than_one_far_from_it():
    values = [5.0, 30.0, 70.0, 95.0, 60.0, 30.0, 5.0]

    table = _stability(values, noise_pp=6.0)

    assert table["phase_stability"].min() < table["phase_stability"].max()


def test_stability_is_deterministic_for_a_fixed_seed():
    values = [5.0, 30.0, 70.0, 95.0, 60.0, 30.0, 5.0]

    first = _stability(values, random_state=7)
    second = _stability(values, random_state=7)

    pd.testing.assert_frame_equal(first, second)


def test_noise_fit_is_bootstrapped_from_record_residuals():
    values = [5.0, 30.0, 70.0, 95.0, 60.0, 30.0, 5.0]

    narrow = _stability(values, noise_residuals=np.array([-0.1, 0.0, 0.1]))
    broad = _stability(values, noise_residuals=np.array([-12.0, 0.0, 12.0]))

    assert broad["phase_stability"].mean() < narrow["phase_stability"].mean()


def test_equivalent_boundary_choices_enter_the_bootstrap():
    values = [5.0, 30.0, 70.0, 95.0, 60.0, 30.0, 5.0]

    fixed = _stability(values)
    ambiguous = _stability(
        values,
        start_extent_candidates=(5.0, 15.0),
        end_extent_candidates=(5.0, 15.0),
    )

    assert ambiguous["phase_stability"].mean() <= fixed["phase_stability"].mean()


def test_every_probability_is_finite():
    values = [5.0, 30.0, 70.0, 95.0, 60.0, 30.0, 5.0]

    table = _stability(values)

    assert np.isfinite(table.to_numpy(dtype=float)).all()



