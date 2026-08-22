import json
from pathlib import Path

import numpy as np
import pytest

from hydroseason._calibration import (
    EVIDENCE_GRID,
    PHASE_GRID,
    PhaseCycleStatistics,
    RecordStatistics,
    build_evidence_cache,
    build_phase_cache,
    compute_phase_statistics,
    compute_statistics,
    iter_evidence_points,
    select_evidence_defaults,
    select_phase_defaults,
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


def test_grid_matches_the_committed_specification():
    assert EVIDENCE_GRID["seasonal_cv_skill"] == pytest.approx(
        [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    )
    assert EVIDENCE_GRID["periodicity_alpha"] == pytest.approx([0.01, 0.025, 0.05, 0.10])
    assert EVIDENCE_GRID["amplitude_noise_ratio"] == pytest.approx([0.5, 0.7, 1.0, 1.5, 2.0])
    assert EVIDENCE_GRID["mode_min_frequency"] == pytest.approx([0.50, 0.60, 0.70, 0.80])
    assert EVIDENCE_GRID["min_timing_years"] == [5, 7, 10]
    assert EVIDENCE_GRID["within_1_month_wilson_floor"] == pytest.approx([0.30, 0.40, 0.50, 0.60])
    assert EVIDENCE_GRID["admit_insufficient_drift"] == [False, True]


def test_phase_grid_matches_the_committed_specification():
    assert PHASE_GRID["phase_low_fraction"] == pytest.approx([0.10, 0.20, 0.25, 0.30])
    assert PHASE_GRID["phase_high_fraction"] == pytest.approx([0.60, 0.70, 0.75, 0.80])
    assert PHASE_GRID["phase_min_duration_months"] == [1, 2, 3]
    assert PHASE_GRID["phase_smoothing_window"] == [1, 3, 5]


def test_valid_evidence_grid_has_exact_cardinality():
    assert sum(1 for _ in iter_evidence_points()) == 190_080


def test_selection_is_deterministic():
    evidence_cache = build_evidence_cache(range(10000, 10200), partition="calibration")
    phase_cache = build_phase_cache(range(10000, 10200), partition="calibration")

    first = (select_evidence_defaults(evidence_cache), select_phase_defaults(phase_cache))
    second = (select_evidence_defaults(evidence_cache), select_phase_defaults(phase_cache))

    assert first == second


def test_selected_point_respects_the_negative_control_bound():
    """Stage 1 of the objective is a hard constraint, not a preference."""
    cache = build_evidence_cache(range(10000, 10400), partition="calibration")

    _, _, scores = select_evidence_defaults(cache)
    chosen = scores[0]

    assert chosen.false_annualisation_wilson_high <= 0.05


def test_weak_concentration_is_always_below_strong():
    cache = build_evidence_cache(range(10000, 10200), partition="calibration")
    evidence, _, _ = select_evidence_defaults(cache)

    assert evidence.weak_timing_concentration < evidence.strong_timing_concentration


def test_scoring_reports_false_annualisation_stratified_by_record_length():
    cache = build_evidence_cache(range(10000, 10400), partition="calibration")
    _, _, scores = select_evidence_defaults(cache)

    assert set(scores[0].false_annualisation_by_length) >= {"5", "7", "10", "20", "30"} or set(scores[0].false_annualisation_by_length) >= {5, 7, 10, 20, 30}


def test_phase_selection_uses_the_specified_lexicographic_order():
    cache = build_phase_cache(range(10000, 10400), partition="calibration")

    selected, scores = select_phase_defaults(cache)
    best = scores[0]

    assert best.thresholds == selected
    assert scores == sorted(
        scores,
        key=lambda item: (
            -item.macro_accuracy,
            item.transition_mae,
            item.forced_complete_rate,
            item.thresholds.phase_smoothing_window,
            item.thresholds.phase_min_duration_months,
        ),
    )


def test_validation_report_exists_and_is_from_frozen_constants():
    report_path = Path("docs/calibration/2026-08-21-validation-report.json")
    assert report_path.exists(), "validation report not found"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    from hydroseason import _scientific_defaults as defaults

    assert payload["calibration_version"] == defaults.CALIBRATION_VERSION
    assert payload["fingerprint"] == defaults.CALIBRATION_FINGERPRINT
    assert payload["partition"] == "validation"


def test_validation_seeds_never_overlap_calibration_seeds():
    report_path = Path("docs/calibration/2026-08-21-validation-report.json")
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert min(payload["seeds"]) >= 20000


def test_validation_report_carries_every_required_section():
    report_path = Path("docs/calibration/2026-08-21-validation-report.json")
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    for section in (
        "evidence_confusion_matrix",
        "false_annualisation",
        "correct_abstention",
        "false_annualisation_by_length",
        "route_coverage",
        "boundary_metrics",
        "phase_accuracy",
        "phase_stability_calibration",
        "sensitivity",
        "runtime",
    ):
        assert section in payload, f"missing required section {section}"


def test_sensitivity_covers_extent_dependent_bias():
    report_path = Path("docs/calibration/2026-08-21-validation-report.json")
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert "extent_dependent_bias" in payload["sensitivity"]


def test_sensitivity_covers_every_fixed_recoverability_criterion():
    report_path = Path("docs/calibration/2026-08-21-validation-report.json")
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert set(payload["recoverability_sensitivity"]) == {
        "min_years",
        "min_coverage",
        "min_within_1_month",
        "max_p90_error_months",
    }

