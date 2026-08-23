import pandas as pd

from hydroseason._synthetic import (
    CALIBRATION_SEEDS,
    VALIDATION_SEEDS,
    SyntheticRecord,
    apply_extent_dependent_bias,
    generate_record,
)


def test_seed_partitions_do_not_overlap():
    """The whole validation argument rests on this."""
    assert set(CALIBRATION_SEEDS).isdisjoint(set(VALIDATION_SEEDS))
    assert min(VALIDATION_SEEDS) > max(CALIBRATION_SEEDS)


def test_partitions_have_the_documented_ranges():
    assert min(CALIBRATION_SEEDS) == 10000 and max(CALIBRATION_SEEDS) == 14999
    assert min(VALIDATION_SEEDS) == 20000 and max(VALIDATION_SEEDS) == 24999


def test_generation_is_deterministic():
    first = generate_record(10001, partition="calibration")
    second = generate_record(10001, partition="calibration")

    assert isinstance(first, SyntheticRecord)
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert first.family == second.family


def test_every_calibration_family_appears():
    families = {generate_record(seed, partition="calibration").family for seed in range(10000, 10400)}

    for expected in (
        "unimodal_symmetric", "unimodal_asymmetric", "monsoonal_sharp", "wet_plateau",
        "bimodal", "switching_modes", "phase_drift", "amplitude_drift",
        "flatline", "near_flat_noise", "white_noise", "autocorrelated_noise",
        "random_walk", "monotonic_trend", "event_pulses", "multi_year_regimes",
        "tied_low_plateau",
    ):
        assert expected in families, f"missing family {expected}"


def test_validation_partition_adds_unseen_families():
    calibration = {generate_record(seed, partition="calibration").family for seed in range(10000, 10400)}
    validation = {generate_record(seed, partition="validation").family for seed in range(20000, 20400)}

    for expected in ("triangular", "skewed_pulse", "compound_pulse", "step_change"):
        assert expected in validation
        assert expected not in calibration


def test_record_lengths_span_the_documented_set():
    lengths = {generate_record(seed, partition="calibration").truth.n_years for seed in range(10000, 10400)}

    assert {5, 7, 10, 20, 30}.issubset(lengths)


def test_frames_are_valid_prepared_input():
    record = generate_record(10005, partition="calibration")

    assert {"extent_pct", "invalid_pct"}.issubset(record.frame.columns)
    finite = record.frame["extent_pct"].dropna()
    assert (finite >= 0).all() and (finite <= 100).all()


def test_annual_families_are_labelled_annual():
    for seed in range(10000, 10200):
        record = generate_record(seed, partition="calibration")
        if record.family in {"unimodal_symmetric", "monsoonal_sharp"}:
            assert record.truth.is_annual
            assert record.truth.trough_month is not None


def test_negative_control_families_are_labelled_not_annual():
    for seed in range(10000, 10200):
        record = generate_record(seed, partition="calibration")
        if record.family in {"white_noise", "random_walk", "flatline"}:
            assert not record.truth.is_annual


def test_extent_dependent_bias_is_one_sided_and_grows_as_extent_falls():
    """Distinct from quality degradation: this shifts values, not weights."""
    extent = pd.Series([5.0, 25.0, 50.0, 90.0])

    biased = apply_extent_dependent_bias(extent, strength_pp=4.0)

    delta = biased - extent
    assert (delta <= 0).all(), "bias must be one-sided (omission exceeds commission)"
    assert abs(delta.iloc[0]) > abs(delta.iloc[-1]), "low extent must be biased more"


def test_zero_strength_bias_is_a_passthrough():
    extent = pd.Series([5.0, 50.0, 90.0])

    assert apply_extent_dependent_bias(extent, strength_pp=0.0).tolist() == extent.tolist()


def test_bias_never_leaves_the_valid_range():
    extent = pd.Series([0.0, 0.5, 1.0])

    biased = apply_extent_dependent_bias(extent, strength_pp=20.0)

    assert (biased >= 0).all()


def test_bias_axis_spans_zero_and_positive_strengths():
    strengths = {
        generate_record(seed, partition="calibration").scenario.bias_strength_pp
        for seed in range(10000, 10400)
    }

    assert strengths == {0.0, 1.0, 2.0, 4.0, 8.0}


def test_degradation_axes_are_crossed_instead_of_confounded():
    scenarios = [
        generate_record(seed, partition="calibration").scenario
        for seed in range(10000, 10720)
    ]

    missingness_jitter = {
        (item.missingness, item.timing_jitter_months) for item in scenarios
    }
    quality_noise = {(item.quality_loss, item.noise_pp) for item in scenarios}

    assert missingness_jitter == {
        (missingness, jitter)
        for missingness in ("none", "random", "seasonal")
        for jitter in (0, 1, 2)
    }
    assert quality_noise == {
        (quality, noise)
        for quality in ("none", "extrema")
        for noise in (0.5, 2.0, 5.0, 8.0)
    }


def test_phase_truth_follows_cycle_relative_rising_and_receding_limbs():
    record = generate_record(10166, partition="calibration")
    phases = record.truth.phase_by_month.groupby(
        record.truth.phase_by_month.index.month
    ).first()

    assert record.family == "unimodal_symmetric"
    assert record.scenario.timing_jitter_months == 0
    assert record.truth.trough_month == 8
    assert phases.loc[11] == "recovery"
    assert phases.loc[5] == "recession"


def test_timing_jitter_keeps_per_year_trough_and_phase_truth_aligned():
    record = generate_record(10047, partition="calibration")
    years = sorted(set(record.frame.index.year))

    assert record.scenario.timing_jitter_months > 0
    assert len(record.truth.trough_month_by_year) == len(years)
    for year, trough_month in zip(
        years, record.truth.trough_month_by_year, strict=True
    ):
        trough = pd.Timestamp(year=year, month=trough_month, day=1)
        assert record.truth.phase_by_month.loc[trough] == "dry"


def test_annual_phase_truth_is_populated_and_aligned():
    records = [
        generate_record(seed, partition="calibration")
        for seed in range(10000, 10400)
    ]

    for record in records:
        if record.truth.is_annual:
            assert record.truth.phase_by_month is not None
            assert record.truth.phase_by_month.index.equals(record.frame.index)
