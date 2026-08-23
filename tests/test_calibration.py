import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydroseason._boundary_recoverability import RecoverabilityThresholds
from hydroseason._calibration import (
    EVIDENCE_GRID,
    PHASE_GRID,
    PhaseCycleStatistics,
    RecordStatistics,
    build_evidence_cache,
    build_phase_cache,
    build_validation_report,
    compute_phase_statistics,
    compute_statistics,
    evaluate_evidence_cache,
    iter_evidence_points,
    score_evidence_grid_point,
    score_phase_grid_point,
    select_evidence_defaults,
    select_phase_defaults,
)
from hydroseason._cycle_phase import PhaseThresholds
from hydroseason._evidence import EvidenceThresholds
from hydroseason._synthetic import CALIBRATION_SEEDS, generate_record
from scripts.run_calibration import _drift_axis_rates, run_calibration, run_validation


def _tiny_gate_cache() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "seed": [1, 2],
            "family": ["white_noise", "unimodal_symmetric"],
            "n_years": [7, 7],
            "n_evaluable_years": [7, 7],
            "seasonal_cv_skill": [0.9, 0.9],
            "periodicity_p": [0.001, 0.001],
            "amplitude_noise_ratio": [4.0, 4.0],
            "at_or_below_floor": [False, False],
            "timing_concentration": [0.9, 0.9],
            "timing_uniformity_p": [0.001, 0.001],
            "drift_status": ["insufficient_for_drift", "insufficient_for_drift"],
            "boundary_n": [5, 5],
            "boundary_coverage": [1.0, 1.0],
            "boundary_within_1_count": [5, 5],
            "boundary_p90_error_months": [0.0, 0.0],
            "boundary_mae": [0.0, 0.0],
            "boundary_truth_errors": [(), (0.0, 1.0, 2.0, -1.0, -2.0)],
            "boundary_truth_n": [0, 5],
            "boundary_truth_within_1_count": [0, 3],
            "boundary_truth_bias_months": [0.0, 0.0],
            "boundary_truth_mae_months": [0.0, 1.2],
            "boundary_truth_p90_error_months": [12.0, 2.0],
            "truth_is_annual": [False, True],
            "missingness": ["none", "random"],
            "quality_loss": ["none", "extrema"],
            "noise_pp": [0.5, 2.0],
            "timing_jitter_months": [0, 1],
            "bias_strength_pp": [0.0, 4.0],
            **{
                f"{kind}_n_modes_{frequency:.2f}": [1, 1]
                for kind in ("peak", "trough")
                for frequency in (0.50, 0.60, 0.70, 0.80)
            },
        }
    )


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


def test_cache_carries_boundary_gate_inputs_and_scenario_axes():
    cache = build_evidence_cache(range(10000, 10020), partition="calibration")

    assert {
        "boundary_within_1_count",
        "boundary_p90_error_months",
        "boundary_truth_n",
        "boundary_truth_within_1_count",
        "boundary_truth_bias_months",
        "boundary_truth_mae_months",
        "boundary_truth_p90_error_months",
        "boundary_truth_errors",
        "missingness",
        "quality_loss",
        "noise_pp",
        "timing_jitter_months",
        "bias_strength_pp",
    }.issubset(cache.columns)


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
    record = generate_record(10166, partition="calibration")
    cycles = compute_phase_statistics(record)

    assert cycles
    assert all(isinstance(cycle, PhaseCycleStatistics) for cycle in cycles)
    for cycle in cycles:
        assert cycle.normalised_z.shape == cycle.true_phase.shape
        assert len(cycle.noise_residuals) > 0
        assert cycle.start_extent_candidates
        assert cycle.end_extent_candidates


def test_tied_low_phase_cache_preserves_multiple_boundary_choices():
    record = generate_record(10012, partition="calibration")
    assert record.family == "tied_low_plateau"

    cycles = compute_phase_statistics(record)

    assert any(
        len(cycle.start_extent_candidates) > 1
        or len(cycle.end_extent_candidates) > 1
        for cycle in cycles
    )


def test_boundary_cache_requires_nine_candidate_usable_months():
    record = generate_record(10001, partition="calibration")
    frame = record.frame.copy()
    frame["invalid_pct"] = 100.0
    frame.loc[frame.index.month.isin([1, 2, 3]), "invalid_pct"] = 0.0

    stats = compute_statistics(replace(record, frame=frame))

    assert stats.boundary_n == 0
    assert stats.n_evaluable_years == record.truth.n_years


def test_phase_cache_excludes_records_without_phase_truth():
    record = next(
        generate_record(seed, partition="calibration")
        for seed in CALIBRATION_SEEDS
        if not generate_record(seed, partition="calibration").truth.is_annual
    )

    assert compute_phase_statistics(record) == ()


def test_phase_cache_uses_true_trough_to_trough_cycles():
    record = generate_record(10166, partition="calibration")

    cycles = compute_phase_statistics(record)

    assert record.family == "unimodal_symmetric"
    assert record.scenario.timing_jitter_months == 0
    assert len(cycles) == record.truth.n_years - 1
    assert cycles[0].cycle_frame.index[0] == pd.Timestamp("1990-09-01")
    assert cycles[0].cycle_frame.index[-1] == pd.Timestamp("1991-08-01")


def test_phase_cache_tracks_jittered_truth_boundaries():
    record = generate_record(10047, partition="calibration")

    cycles = compute_phase_statistics(record)
    first_trough, second_trough = record.truth.trough_month_by_year[:2]

    assert cycles[0].cycle_frame.index[0] == pd.Timestamp(
        year=1990, month=first_trough, day=1
    ) + pd.DateOffset(months=1)
    assert cycles[0].cycle_frame.index[-1] == pd.Timestamp(
        year=1991, month=second_trough, day=1
    )


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


def test_recoverability_axes_change_public_annualisation_score():
    cache = pd.DataFrame(
        {
            "seed": [1, 2],
            "family": ["white_noise", "unimodal_symmetric"],
            "n_years": [7, 7],
            "n_evaluable_years": [7, 7],
            "seasonal_cv_skill": [0.9, 0.9],
            "periodicity_p": [0.001, 0.001],
            "amplitude_noise_ratio": [4.0, 4.0],
            "at_or_below_floor": [False, False],
            "timing_concentration": [0.9, 0.9],
            "drift_status": ["insufficient_for_drift", "insufficient_for_drift"],
            "boundary_n": [5, 5],
            "boundary_coverage": [1.0, 1.0],
            "boundary_within_1_count": [5, 5],
            "boundary_p90_error_months": [0.0, 0.0],
            "boundary_mae": [0.0, 0.0],
            "truth_is_annual": [False, True],
            "peak_n_modes_0.50": [1, 1],
            "trough_n_modes_0.50": [1, 1],
        }
    )
    base = (0.3, 0.05, 1.0, 0.50, 0.70, 0.40, 7, 0.50)

    rejected = score_evidence_grid_point(cache, (*base, False))
    admitted = score_evidence_grid_point(cache, (*base, True))

    assert rejected.false_annualisation_rate == 0.0
    assert rejected.routing_recall == 0.0
    assert admitted.false_annualisation_rate == 1.0
    assert admitted.routing_recall == 1.0


def test_evidence_cache_evaluation_uses_runtime_evidence_and_gate_states():
    cache = _tiny_gate_cache()
    evidence = EvidenceThresholds(
        seasonal_cv_skill=0.3,
        periodicity_alpha=0.05,
        amplitude_noise_ratio=1.0,
        mode_min_frequency=0.50,
        mode_min_separation_months=2,
        strong_timing_concentration=0.70,
        weak_timing_concentration=0.40,
        min_timing_years=7,
    )
    recoverability = RecoverabilityThresholds(
        min_years=5,
        min_coverage=0.80,
        min_within_1_month=0.80,
        within_1_month_wilson_floor=0.50,
        max_p90_error_months=2.0,
        admit_insufficient_drift=False,
    )

    rejected = evaluate_evidence_cache(
        cache,
        evidence_thresholds=evidence,
        recoverability_thresholds=recoverability,
    )
    admitted = evaluate_evidence_cache(
        cache,
        evidence_thresholds=evidence,
        recoverability_thresholds=replace(
            recoverability, admit_insufficient_drift=True
        ),
    )

    assert rejected["annual_cycle_evidence"].tolist() == ["strong", "strong"]
    assert rejected["boundary_recoverability"].tolist() == [
        "provisional",
        "provisional",
    ]
    assert not rejected["publish_annual_rows"].any()
    assert admitted["publish_annual_rows"].all()


def test_calibration_drift_axis_rates_are_rerun_not_copied():
    evidence = EvidenceThresholds(0.3, 0.05, 1.0, 0.50, 2, 0.70, 0.40, 7)
    recoverability = RecoverabilityThresholds(5, 0.80, 0.80, 0.50, 2.0, False)

    rates = _drift_axis_rates(
        _tiny_gate_cache(),
        evidence_thresholds=evidence,
        recoverability_thresholds=recoverability,
    )

    assert rates == {"reject": 0.0, "admit": 1.0}


def test_validation_report_metrics_are_derived_from_cache_values():
    cache = _tiny_gate_cache()
    evidence = EvidenceThresholds(
        seasonal_cv_skill=0.3,
        periodicity_alpha=0.05,
        amplitude_noise_ratio=1.0,
        mode_min_frequency=0.50,
        mode_min_separation_months=2,
        strong_timing_concentration=0.70,
        weak_timing_concentration=0.40,
        min_timing_years=7,
    )
    recoverability = RecoverabilityThresholds(
        min_years=5,
        min_coverage=0.80,
        min_within_1_month=0.80,
        within_1_month_wilson_floor=0.50,
        max_p90_error_months=2.0,
        admit_insufficient_drift=True,
    )
    runtime = {
        "validation_wall_seconds": 12.5,
        "peak_traced_memory_mb": 3.25,
        "relative_to_0_1_1": {"runtime_ratio": 1.4, "memory_ratio": 1.1},
    }

    report = build_validation_report(
        cache,
        phase_cache=compute_phase_statistics(
            generate_record(10166, partition="calibration")
        )[:1],
        seeds=[20000, 20001],
        calibration_version="test",
        calibration_fingerprint="abc",
        evidence_thresholds=evidence,
        recoverability_thresholds=recoverability,
        phase_thresholds=PhaseThresholds(
            phase_low_fraction=0.2,
            phase_high_fraction=0.8,
            phase_min_duration_months=1,
            phase_smoothing_window=3,
        ),
        runtime_metrics=runtime,
        quality_policy_sensitivity={"flag": 1.0, "drop": 0.5},
        phase_stability_replicates=20,
        phase_stability_max_cycles=1,
    )

    assert report["false_annualisation"]["rate"] == 1.0
    assert report["drift_axis"] == {"reject": 0.0, "admit": 1.0}
    assert report["boundary_metrics"]["n"] == 5
    assert report["boundary_metrics"]["within_1_month"] == 0.6
    assert report["boundary_metrics"]["bias"] == 0.0
    assert report["boundary_metrics"]["mae"] == 1.2
    assert report["boundary_metrics"]["p90"] == 2.0
    assert report["runtime"] == runtime
    assert report["phase_stability_calibration"]["n_cycles"] == 1
    assert report["phase_stability_calibration"]["bins"]
    assert report["sensitivity"]["quality_policy"] == {
        "flag": 1.0,
        "drop": 0.5,
    }


def test_run_validation_executes_report_builder_on_real_small_partition(tmp_path):
    output = tmp_path / "validation.json"

    run_validation(
        seeds=[20000, 20001],
        out_report=output,
        workers=1,
        sensitivity_limit=2,
        phase_stability_replicates=20,
        phase_stability_max_cycles=1,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["seeds"] == [20000, 20001]
    assert payload["runtime"]["validation_wall_seconds"] > 0.0
    assert payload["runtime"]["records"] == 2
    assert payload["runtime"]["relative_to_0_1_1"]["status"] == "not comparable"
    assert payload["phase_stability_calibration"]["n_cycles"] <= 1


def test_run_calibration_reports_measured_workflow_and_drift_axes(tmp_path):
    report_path = tmp_path / "calibration.json"
    module_path = tmp_path / "defaults.py"

    run_calibration(
        seeds=[10000, 10001],
        out_report=report_path,
        out_module=module_path,
        workers=1,
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["runtime"]["calibration_wall_seconds"] > 0.0
    assert payload["runtime"]["records"] == 2
    assert payload["runtime"]["peak_sampled_rss_mb"] > 0.0
    assert set(payload["drift_axis"]) == {"reject", "admit"}
    assert payload["selection_survivors"]["grid"] == 190_080
    assert payload["selection_survivors"]["selected"] == 1


def test_selection_scores_the_public_recoverability_gate():
    cache = pd.DataFrame(
        {
            "seed": [1, 2],
            "family": ["white_noise", "unimodal_symmetric"],
            "n_years": [7, 7],
            "n_evaluable_years": [7, 7],
            "seasonal_cv_skill": [0.9, 0.9],
            "periodicity_p": [0.001, 0.001],
            "amplitude_noise_ratio": [4.0, 4.0],
            "at_or_below_floor": [False, False],
            "timing_concentration": [0.9, 0.9],
            "drift_status": ["insufficient_for_drift", "insufficient_for_drift"],
            "boundary_n": [5, 5],
            "boundary_coverage": [1.0, 1.0],
            "boundary_within_1_count": [5, 5],
            "boundary_p90_error_months": [0.0, 0.0],
            "boundary_mae": [0.0, 0.0],
            "truth_is_annual": [False, True],
            **{
                f"{kind}_n_modes_{frequency:.2f}": [1, 1]
                for kind in ("peak", "trough")
                for frequency in (0.50, 0.60, 0.70, 0.80)
            },
        }
    )

    _, selected_recoverability, scores = select_evidence_defaults(cache)

    assert not selected_recoverability.admit_insufficient_drift
    assert scores[0].false_annualisation_rate == 0.0
    assert scores[0].routing_recall == 0.0


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


def test_complete_truth_cycle_is_not_counted_as_forced_completion():
    cycle = build_phase_cache([10166], partition="calibration")[0]
    assert set(cycle.true_phase) == {"dry", "recovery", "wet", "recession"}

    score = score_phase_grid_point((cycle,), PhaseThresholds(0.2, 0.8, 1, 5))

    assert score.forced_complete_rate == 0.0


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
