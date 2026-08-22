import numpy as np

from hydroseason._calibration import (
    PhaseCycleStatistics,
    RecordStatistics,
    build_evidence_cache,
    build_phase_cache,
    compute_phase_statistics,
    compute_statistics,
)
from hydroseason._synthetic import generate_record


def test_statistics_are_threshold_independent():
    """Nothing cached may depend on a value the grid varies."""
    stats = compute_statistics(generate_record(10001, partition="calibration"))

    assert isinstance(stats, RecordStatistics)
    for name in ("seasonal_cv_skill", "periodicity_p", "amplitude_noise_ratio"):
        assert np.isfinite(getattr(stats, name))


def test_mode_counts_are_stored_per_candidate_frequency():
    stats = compute_statistics(generate_record(10001, partition="calibration"))

    assert set(stats.peak_n_modes_by_frequency) == {0.50, 0.60, 0.70, 0.80}
    assert set(stats.trough_n_modes_by_frequency) == {0.50, 0.60, 0.70, 0.80}


def test_computation_is_deterministic():
    record = generate_record(10007, partition="calibration")

    assert compute_statistics(record) == compute_statistics(record)


def test_cache_is_a_frame_with_one_row_per_seed():
    cache = build_evidence_cache(range(10000, 10020), partition="calibration")

    assert len(cache) == 20
    assert cache["seed"].is_unique
    assert set(cache["seed"]) == set(range(10000, 10020))


def test_cache_carries_truth_labels():
    cache = build_evidence_cache(range(10000, 10020), partition="calibration")

    assert "truth_is_annual" in cache.columns
    assert cache["truth_is_annual"].dtype == bool


def test_no_cached_value_is_infinite():
    cache = build_evidence_cache(range(10000, 10020), partition="calibration")
    numeric = cache.select_dtypes(include=[np.number])

    assert np.isfinite(numeric.to_numpy(dtype=float)).all()


def test_flatline_record_reports_amplitude_at_or_below_floor():
    seeds = [seed for seed in range(10000, 10100)
             if generate_record(seed, partition="calibration").family == "flatline"]
    stats = compute_statistics(generate_record(seeds[0], partition="calibration"))

    assert stats.at_or_below_floor
    assert stats.amplitude_noise_ratio == 0.0


def test_phase_cache_contains_geometry_residuals_boundaries_and_truth():
    record = generate_record(10001, partition="calibration")
    cycles = compute_phase_statistics(record)

    assert cycles
    assert all(isinstance(cycle, PhaseCycleStatistics) for cycle in cycles)
    for cycle in cycles:
        assert cycle.normalised_z.shape == cycle.true_phase.shape
        assert len(cycle.noise_residuals) > 0
        assert cycle.start_extent_candidates
        assert cycle.end_extent_candidates


def test_evidence_and_phase_cache_schemas_are_distinct():
    evidence = build_evidence_cache(range(10000, 10020), partition="calibration")
    phases = build_phase_cache(range(10000, 10020), partition="calibration")

    assert "seasonal_cv_skill" in evidence.columns
    assert phases and isinstance(phases[0], PhaseCycleStatistics)
    assert not hasattr(phases[0], "seasonal_cv_skill")
