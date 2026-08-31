import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydroseason._calibration import (
    EVIDENCE_GRID,
    MIN_TIMING_YEARS_OVERRIDE,
    EvidenceThresholds,
    RecordStatistics,
    RecoverabilityThresholds,
    _apply_min_timing_years_override,
    build_evidence_cache,
    compute_statistics,
    evaluate_evidence_cache,
    iter_evidence_points,
    score_evidence_grid_point,
    select_evidence_defaults,
)
from hydroseason._synthetic import generate_record
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


def test_cache_is_a_frame_with_one_row_per_seed(cal_evidence_cache_fast):
    assert len(cal_evidence_cache_fast) == 20
    assert cal_evidence_cache_fast["seed"].is_unique
    assert set(cal_evidence_cache_fast["seed"]) == set(range(10000, 10020))


def test_cache_carries_truth_labels(cal_evidence_cache_fast):
    assert "truth_is_annual" in cal_evidence_cache_fast.columns
    assert cal_evidence_cache_fast["truth_is_annual"].dtype == bool


def test_cache_carries_boundary_gate_inputs_and_scenario_axes(cal_evidence_cache_fast):
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
    }.issubset(cal_evidence_cache_fast.columns)


def test_no_cached_value_is_infinite(cal_evidence_cache_fast):
    numeric = cal_evidence_cache_fast.select_dtypes(include=[np.number])
    assert np.isfinite(numeric.to_numpy(dtype=float)).all()


def test_flatline_record_reports_amplitude_at_or_below_floor():
    stats = compute_statistics(generate_record(10004, partition="calibration"))

    assert stats.at_or_below_floor
    assert stats.amplitude_noise_ratio == 0.0






def test_boundary_cache_requires_nine_candidate_usable_months():
    record = generate_record(10001, partition="calibration")
    frame = record.frame.copy()
    frame["invalid_pct"] = 100.0
    frame.loc[frame.index.month.isin([1, 2, 3]), "invalid_pct"] = 0.0

    stats = compute_statistics(replace(record, frame=frame))

    assert stats.boundary_n == 0
    assert stats.n_evaluable_years == record.truth.n_years










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




def test_run_validation_executes_report_builder_on_real_small_partition(tmp_path):
    output = tmp_path / "validation.json"

    run_validation(
        seeds=[20000, 20001],
        out_report=output,
        workers=1,
        sensitivity_limit=2,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["seeds"] == [20000, 20001]
    assert payload["runtime"]["validation_wall_seconds"] > 0.0
    assert payload["runtime"]["records"] == 2
    assert payload["runtime"]["relative_to_0_1_1"]["status"] == "not comparable"


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


@pytest.fixture(scope="module")
def cal_evidence_cache_fast() -> pd.DataFrame:
    return build_evidence_cache(range(10000, 10020), partition="calibration")




@pytest.fixture(scope="module")
def cal_selected_evidence(cal_evidence_cache_fast):
    return select_evidence_defaults(cal_evidence_cache_fast)




def test_min_timing_years_override_ships_five_and_records_why(cal_evidence_cache_fast):
    """The search's own answer (10) is recorded, not silently replaced.

    `min_timing_years=10` reproducibly wins the search because
    `correct_abstention` is pruned before this axis is ever consulted as a
    tie-break -- but that floor removes challenger coverage on records
    shorter than itself with no measurable false-annualisation benefit
    above it, and it makes the challenger stricter than the released
    `_MIN_USABLE_YEARS=5` floor it is meant to second-guess (see
    `_apply_min_timing_years_override`'s docstring for the full argument).
    Shipping 5 is a stated policy override on top of the search, not a
    change to the search itself: both values must remain visible.
    """
    searched, _, _ = select_evidence_defaults(cal_evidence_cache_fast)

    shipped, note = _apply_min_timing_years_override(searched, cal_evidence_cache_fast)

    assert shipped.min_timing_years == MIN_TIMING_YEARS_OVERRIDE
    assert note is not None
    assert note["searched_value"] == searched.min_timing_years
    assert note["shipped_value"] == MIN_TIMING_YEARS_OVERRIDE
    # every other field is untouched by the override
    assert replace(shipped, min_timing_years=searched.min_timing_years) == searched


def test_min_timing_years_override_is_a_noop_if_search_ever_agrees(cal_evidence_cache_fast):
    """If a future search independently selects 5, nothing is overridden."""
    searched, _, _ = select_evidence_defaults(cal_evidence_cache_fast)
    already_five = replace(searched, min_timing_years=MIN_TIMING_YEARS_OVERRIDE)

    shipped, note = _apply_min_timing_years_override(already_five, cal_evidence_cache_fast)

    assert shipped == already_five
    assert note is None


def test_selection_is_deterministic(cal_evidence_cache_fast):
    evidence_cache = cal_evidence_cache_fast

    first = select_evidence_defaults(evidence_cache)
    second = select_evidence_defaults(evidence_cache)

    assert first == second


def test_selected_point_survives_every_pruning_stage(cal_selected_evidence):
    """The pick must come from the pruned set, not the stage-1 candidate set.

    Regression: the final sort ran over `candidate_indices` -- still the whole
    stage-1 set -- while every `_retain_metric`/`_retain_axis` stage narrowed a
    separate `survivors` array that nothing read. The staged pruning was dead
    work, and the counts reported as `selection_survivors` described a set the
    selection did not use. Guarded by shape rather than by value: each recorded
    stage must be a subset of the one before it, and the last must be what the
    selection actually chose from.
    """
    _, _, scores = cal_selected_evidence
    counts = scores[0].selection_counts

    stages = [
        "grid",
        "negative_control_wilson",
        "routing_recall",
        "correct_abstention",
        "boundary_mae",
        "seasonal_cv_skill_margin",
        "periodicity_alpha_margin",
        "amplitude_noise_ratio_margin",
        "strong_timing_concentration_margin",
        "wilson_floor_margin",
        "min_timing_years_margin",
        "reject_insufficient_drift_margin",
        "mode_frequency_margin",
        "weak_timing_concentration_margin",
        "final_survivors",
    ]
    for name in stages:
        assert name in counts, f"stage {name} not recorded"
    recorded = [counts[name] for name in stages]
    assert recorded == sorted(recorded, reverse=True), (
        "pruning must be monotonically narrowing; a stage that grows means the "
        f"counts describe a set the selection never used: {dict(zip(stages, recorded))}"
    )
    assert counts["final_survivors"] >= 1
    assert counts["selected"] == 1


def test_selected_point_respects_the_negative_control_bound(cal_selected_evidence):
    """Stage 1 of the objective is a hard constraint, not a preference."""
    _, _, scores = cal_selected_evidence
    chosen = scores[0]

    assert chosen.false_annualisation_rate == 0.0
    assert chosen.false_annualisation_wilson_high <= 0.30


def test_weak_concentration_is_always_below_strong(cal_selected_evidence):
    evidence, _, _ = cal_selected_evidence

    assert evidence.weak_timing_concentration < evidence.strong_timing_concentration


def test_scoring_reports_false_annualisation_stratified_by_record_length(cal_selected_evidence):
    _, _, scores = cal_selected_evidence

    assert set(scores[0].false_annualisation_by_length) >= {"5", "7", "10", "20", "30"} or set(scores[0].false_annualisation_by_length) >= {5, 7, 10, 20, 30}






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


def test_calibration_report_scopes_each_generated_product():
    """Every group the calibration reports on is a challenger.

    The four-phase labeller `phase` scoped as authoritative was unreachable
    from any public entry point and has been removed; nothing in the
    calibration claims authority over released behaviour any more.
    """
    payload = json.loads(Path("docs/calibration/2026-08-21-calibration-report.json").read_text(encoding="utf-8"))
    assert payload["authority_scope"] == {
        "evidence": "experimental_challenger",
        "recoverability": "experimental_challenger",
    }
    assert payload["metric_groups"] == {
        "challenger_decision": ["evidence", "recoverability"],
    }
    assert "phase" not in payload


def test_validation_report_uses_the_same_authority_scope():
    payload = json.loads(Path("docs/calibration/2026-08-21-validation-report.json").read_text(encoding="utf-8"))
    assert payload["authority_scope"] == {
        "evidence": "experimental_challenger",
        "recoverability": "experimental_challenger",
    }
    assert "phase_accuracy" not in payload
    assert "phase_stability_calibration" not in payload
