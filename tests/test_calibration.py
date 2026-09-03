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
from hydroseason._timing_identifiability import TimingIdentifiabilityThresholds
from scripts.run_calibration import _drift_axis_rates, run_calibration, run_validation

ROOT = Path(__file__).parents[1]


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


def test_timing_identifiability_grid_and_selection_are_frozen_and_isolated():
    from hydroseason._calibration import (
        TIMING_IDENTIFIABILITY_GRID,
        build_timing_identifiability_cache,
        select_timing_identifiability_defaults,
        timing_identifiability_fingerprint,
    )

    assert TIMING_IDENTIFIABILITY_GRID == {
        "min_amplitude_to_floor_ratio": [1.0, 1.5, 2.0, 3.0],
        "min_peak_water_pixels": [1, 2, 3, 5],
        "max_point_span_months": [0, 1, 2],
        "max_boundary_interval_months": [2, 3, 4],
        "min_informative_years": [5, 7, 10],
    }
    calibration = build_timing_identifiability_cache(range(10000, 10032), partition="calibration")
    selected, score = select_timing_identifiability_defaults(calibration)

    assert isinstance(selected, TimingIdentifiabilityThresholds)
    assert score.selection_counts["selected"] == 1
    assert timing_identifiability_fingerprint(selected) == timing_identifiability_fingerprint(selected)


def test_timing_validation_truth_cannot_change_selected_defaults_or_fingerprint():
    from hydroseason._calibration import (
        build_timing_identifiability_cache,
        select_timing_identifiability_defaults,
        timing_identifiability_fingerprint,
    )

    calibration = build_timing_identifiability_cache(range(10000, 10032), partition="calibration")
    validation = build_timing_identifiability_cache(range(20000, 20016), partition="validation")
    selected, _ = select_timing_identifiability_defaults(calibration)
    original = timing_identifiability_fingerprint(selected)
    validation.loc[:, "truth_peak_status"] = "point"
    validation.loc[:, "truth_trough_status"] = "point"

    repeat, _ = select_timing_identifiability_defaults(calibration)
    assert repeat == selected
    assert timing_identifiability_fingerprint(repeat) == original


def test_timing_validation_scores_only_the_frozen_tuple(monkeypatch):
    import hydroseason._calibration as calibration

    def _grid_forbidden():
        raise AssertionError("untouched validation must not enumerate the timing grid")

    monkeypatch.setattr(calibration, "iter_timing_identifiability_points", _grid_forbidden)
    cache = calibration.build_timing_identifiability_cache(
        [20000, 20001], partition="validation"
    )
    from hydroseason import _scientific_defaults as defaults

    score = calibration.score_timing_identifiability_thresholds(
        cache, defaults.TIMING_IDENTIFIABILITY_DEFAULTS
    )

    assert score.selection_counts == {"evaluated_candidates": 1}


def test_timing_fingerprint_covers_metric_implementation(monkeypatch):
    import inspect

    import hydroseason._timing_identifiability as timing_metrics
    from hydroseason import _scientific_defaults as defaults
    from hydroseason._calibration import timing_identifiability_fingerprint

    baseline = timing_identifiability_fingerprint(defaults.TIMING_IDENTIFIABILITY_DEFAULTS)
    original = inspect.getsource

    def _changed_source(item):
        source = original(item)
        return source + "\n# synthetic metric implementation change" if item is timing_metrics.assess_timing_identifiability else source

    monkeypatch.setattr(inspect, "getsource", _changed_source)

    assert timing_identifiability_fingerprint(defaults.TIMING_IDENTIFIABILITY_DEFAULTS) != baseline


from hydroseason._calibration import (
    TROUGH_GEOMETRY_GRID,
    TroughGeometry,
    _geometry_metrics,
    build_trough_geometry_cache,
    iter_trough_geometry_points,
    score_trough_geometry,
    select_trough_geometry_defaults,
    trough_geometry_fingerprint,
)

SHIPPED_GEOMETRY = TroughGeometry(3, 5, 6)


def test_geometry_grid_matches_the_frozen_design():
    assert TROUGH_GEOMETRY_GRID == {
        "trough_search_radius_months": [3, 4, 5],
        "adaptive_trough_search_radius_months": [3, 4, 5],
        "adaptive_min_usable_months_per_cycle": [5, 6, 7, 8],
    }


def test_grid_enumerates_exactly_the_valid_tuples():
    points = list(iter_trough_geometry_points())
    assert len(points) == 24
    assert len(set(points)) == 24
    assert all(
        point.adaptive_trough_search_radius_months >= point.trough_search_radius_months
        for point in points
    )
    assert all(point.adaptive_min_usable_months_per_cycle <= 8 for point in points)


def test_shipped_geometry_competes_on_equal_terms():
    assert SHIPPED_GEOMETRY in set(iter_trough_geometry_points())


def test_cache_covers_every_record_and_every_tuple():
    seeds = list(range(30000, 30004))
    cache = build_trough_geometry_cache(seeds, partition="calibration")
    assert set(cache["seed"]) == set(seeds)
    assert cache["geometry_index"].nunique() == 24
    for column in (
        "family", "hy_year", "published", "truth_identifiable", "error_months",
        "wrong_cycle", "coverage_drop", "record_nonmonotonic", "outside_window_lower",
    ):
        assert column in cache.columns


def test_scoring_one_tuple_reports_every_predeclared_metric():
    cache = build_trough_geometry_cache(range(30000, 30004), partition="calibration")
    score = score_trough_geometry(cache, SHIPPED_GEOMETRY)
    assert score.geometry == SHIPPED_GEOMETRY
    for value in (
        score.false_precise_boundary_rate, score.duplicate_or_nonmonotonic_rate,
        score.boundary_mae, score.boundary_signed_bias, score.wrong_cycle_rate,
        score.short_long_cycle_rate, score.coverage_drop_rate, score.abstention_rate,
        score.outside_window_lower_rate,
    ):
        assert np.isfinite(value)
    low, high = score.false_precise_boundary_wilson
    assert 0.0 <= low <= high <= 1.0


def test_selector_prefers_the_shipped_tuple_when_every_metric_ties():
    """A tie must not republish every hydrological year downstream."""
    points = list(iter_trough_geometry_points())
    rows = []
    for index, _point in enumerate(points):
        rows.append({
            "seed": 30000, "family": "stationary_trough", "geometry_index": index,
            "hy_year": 2001, "published": True, "truth_identifiable": True,
            "error_months": 0.0, "wrong_cycle": False, "coverage_drop": False,
            "record_nonmonotonic": False, "outside_window_lower": False,
            "outside_window_observed": True, "cycle_months": 12.0,
        })
    selected, score = select_trough_geometry_defaults(pd.DataFrame(rows))
    assert selected == SHIPPED_GEOMETRY
    assert score.selection_counts["selected"] == 1


def test_selector_rejects_a_tuple_that_can_emit_nonmonotonic_boundaries():
    points = list(iter_trough_geometry_points())
    shipped_index = points.index(SHIPPED_GEOMETRY)
    rows = []
    for index, _point in enumerate(points):
        rows.append({
            "seed": 30000, "family": "stationary_trough", "geometry_index": index,
            "hy_year": 2001, "published": True, "truth_identifiable": True,
            # The shipped tuple is made worse on accuracy but structurally sound;
            # every rival is perfect on accuracy but structurally broken.
            "error_months": 0.0 if index != shipped_index else 1.0,
            "wrong_cycle": False, "coverage_drop": False,
            "record_nonmonotonic": index != shipped_index,
            "outside_window_lower": False, "outside_window_observed": True,
            "cycle_months": 12.0,
        })
    selected, _score = select_trough_geometry_defaults(pd.DataFrame(rows))
    assert selected == SHIPPED_GEOMETRY


def test_selector_raises_rather_than_relaxing_an_empty_structural_gate():
    points = list(iter_trough_geometry_points())
    rows = [{
        "seed": 30000, "family": "stationary_trough", "geometry_index": index,
        "hy_year": 2001, "published": True, "truth_identifiable": True,
        "error_months": 0.0, "wrong_cycle": False, "coverage_drop": False,
        "record_nonmonotonic": True, "outside_window_lower": False,
        "outside_window_observed": True, "cycle_months": 12.0,
    } for index, _point in enumerate(points)]
    with pytest.raises(RuntimeError, match="duplicate_or_nonmonotonic"):
        select_trough_geometry_defaults(pd.DataFrame(rows))


def test_challenge_count_is_not_a_selection_metric():
    """Selecting on it would reward widening regardless of correctness."""
    import inspect

    from hydroseason import _calibration

    source = inspect.getsource(_calibration.select_trough_geometry_defaults)
    assert "outside_window_lower" not in source


def test_geometry_fingerprint_is_stable_and_tuple_sensitive():
    first = trough_geometry_fingerprint(SHIPPED_GEOMETRY)
    assert first == trough_geometry_fingerprint(SHIPPED_GEOMETRY)
    assert first != trough_geometry_fingerprint(TroughGeometry(5, 5, 6))
    assert len(first) == 64


def test_selector_composes_with_a_real_cache_from_the_calibration_partition():
    """Run the cache builder and selector back-to-back on real synthetic data.

    This is the path that was never exercised end-to-end: Task 6's own tests
    only ever fed the selector a hand-built ``pd.DataFrame`` of rows, never
    the output of ``build_trough_geometry_cache`` itself.  The per-year
    ``truth_identifiable`` bug (fixed in ``_geometry_rows``, first fix pass)
    hid exactly here -- a hand-built fixture cannot reproduce a per-record mix
    of identifiable and unidentifiable years the way the real corpus does.

    The seed range below is 4 seeds per one of the 10 trough-geometry
    families (``range(30000, 30040)``, families cycling on ``seed % 10``).

    A second fix pass changed what counts as "published" from a populated
    ``trough_month`` (an internal operational boundary date that is set on
    essentially every row regardless of timing status) to
    ``trough_timing_status == "point"`` (a genuine point-timing claim; see
    ``_geometry_rows``'s docstring). Before that fix, every ``"interval"``-
    status row on ``tied_low_plateau_wide`` (whose truth is unidentifiable in
    every year by construction) was miscounted as a claimed point-truth date,
    driving a flat 100% false-precise-boundary rate on that family alone and
    causing the RuntimeError below for that reason. After the fix,
    ``tied_low_plateau_wide`` correctly contributes zero false-precise
    boundaries (it never emits ``"point"`` status), confirmed by direct
    inspection of ``_geometry_rows`` output for seed 30004.

    The RuntimeError below still fires, but the cause has changed: this real
    cache now shows a small (8/64), geometry-invariant false-precise-boundary
    rate whose Wilson upper bound still exceeds the frozen 0.05 admission
    gate. Tracing it lands entirely on ``missing_outer_months`` (seeds 30005,
    30015, 30025, 30035), and specifically on the first year of each of that
    family's two 2-year "missing outer months" gaps (hy_year 1993 of the
    1993-1994 gap, 1998 of the 1998-1999 gap): the truth corpus marks *both*
    years of each gap unidentifiable, but the detector resolves the first
    year's boundary to a confident ``"point"`` (``status_reason="ok"``) while
    correctly returning ``"unresolved"`` for the second. This is a genuine
    detector-vs-corpus-labelling disagreement about exactly one of the two
    masked years per gap, not a ``_geometry_rows``/``_geometry_metrics``
    counting artifact -- it reproduces identically across all four seeds of
    the family and is invariant to all 24 geometry candidates (the gate
    rejects every point on the grid by the same 8/64 count), so no geometry
    choice can route around it. Whether the corpus should also treat that
    first gap year as identifiable, or the detector should decline to claim
    a point there, is a genuine open question separate from Task 6's scoring
    code and is out of scope for this fix pass -- this test intentionally
    does not weaken the gate to force a selection through.
    """
    seeds = list(range(30000, 30040))
    cache = build_trough_geometry_cache(seeds, partition="calibration")

    # Pin the ``tied_low_plateau_wide`` claim from the docstring above: this
    # family's truth is unidentifiable in every year by construction, and
    # after the point-only-publication fix it must never emit a published
    # (point-status) boundary. Reverting that fix (scoring any populated
    # ``trough_month`` as published, regardless of ``trough_timing_status``)
    # makes this fail, since every "interval"-status row on this family would
    # then count as published.
    tied_low_plateau_wide = cache.loc[cache["family"] == "tied_low_plateau_wide"]
    assert len(tied_low_plateau_wide) > 0
    assert tied_low_plateau_wide["published"].sum() == 0

    # Pin the exact false-precise-boundary count/denominator from the
    # docstring for the shipped geometry (3, 5, 6): 8 false-precise
    # boundaries out of 64 unidentifiable-year rows, all attributable to the
    # documented ``missing_outer_months`` corpus gap. Under the reverted
    # (pre-fix) scoring this count is 64/64 -- same error message, wildly
    # different cause -- so this is what actually distinguishes the two.
    points = list(iter_trough_geometry_points())
    metrics = _geometry_metrics(cache, points.index(SHIPPED_GEOMETRY))
    assert metrics["n_false"] == 8.0
    assert metrics["n_unidentifiable"] == 64.0

    with pytest.raises(RuntimeError, match="false precise-boundary"):
        select_trough_geometry_defaults(cache)


def test_geometry_runner_writes_defaults_and_a_report(tmp_path, monkeypatch):
    """Exercise the runner's report/defaults-writing plumbing end to end.

    The real calibration corpus (seeds 30000+) is known -- per Task 6's own
    ``test_selector_composes_with_a_real_cache_from_the_calibration_partition``
    -- to make ``select_trough_geometry_defaults`` raise ``RuntimeError`` on
    every occurrence of the ``missing_outer_months`` family, regardless of
    geometry candidate or seed-range size: it is an accepted, geometry-
    invariant 8/64 false-precise-boundary rate, not a bug this task should
    route around. So this test stands up the runner against a hand-built
    cache (mirroring Task 6's own tie-break fixtures) where selection
    succeeds by construction, to isolate and verify the plumbing this task
    actually adds -- report payload shape and defaults-module writing --
    from that already-documented, not-this-task's-problem selector outcome.
    """
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location(
        "run_calibration", ROOT / "scripts" / "run_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from hydroseason._calibration import TroughGeometry, iter_trough_geometry_points

    shipped = TroughGeometry(3, 5, 6)
    points = list(iter_trough_geometry_points())
    rows = [
        {
            "seed": 30000, "family": "stationary_trough", "geometry_index": index,
            "hy_year": 2001, "published": True, "truth_identifiable": True,
            "error_months": 0.0, "wrong_cycle": False, "coverage_drop": False,
            "record_nonmonotonic": False, "outside_window_lower": False,
            "outside_window_observed": True, "cycle_months": 12.0,
        }
        for index, _point in enumerate(points)
    ]
    fake_cache = pd.DataFrame(rows)
    import hydroseason._calibration as calibration_module

    monkeypatch.setattr(
        calibration_module, "build_trough_geometry_cache",
        lambda seeds, *, partition: fake_cache,
    )

    out_module = tmp_path / "_generated_defaults.py"
    out_module.write_text("# placeholder\n", encoding="utf-8")
    out_report = tmp_path / "geometry-calibration.json"
    module.run_trough_geometry_calibration(
        seeds=list(range(30000, 30010)),
        out_report=out_report,
        out_module=out_module,
    )

    payload = json.loads(out_report.read_text(encoding="utf-8"))
    assert payload["partition"] == "calibration"
    assert payload["authority_scope"] == "candidate_for_established_0_3_0"
    assert set(payload["geometry"]) == {
        "trough_search_radius_months",
        "adaptive_trough_search_radius_months",
        "adaptive_min_usable_months_per_cycle",
    }
    assert len(payload["fingerprint"]) == 64
    assert "outside_window_lower_rate" in payload["metrics"]

    text = out_module.read_text(encoding="utf-8")
    assert "TROUGH_GEOMETRY_DEFAULTS" in text
    assert "TROUGH_GEOMETRY_FINGERPRINT" in text


def test_geometry_validation_refuses_when_defaults_are_not_generated(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_calibration", ROOT / "scripts" / "run_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(RuntimeError, match="not generated"):
        module.run_trough_geometry_validation(
            seeds=list(range(40000, 40004)),
            out_report=tmp_path / "geometry-validation.json",
            frozen_fingerprint="0" * 64,
        )


def test_geometry_validation_refuses_a_fingerprint_mismatch(tmp_path, monkeypatch):
    """Exercise the actual mismatch branch, not the earlier not-generated guard.

    Monkeypatches real ``TROUGH_GEOMETRY_DEFAULTS``/``TROUGH_GEOMETRY_FINGERPRINT``
    attributes onto ``hydroseason._scientific_defaults`` (removed afterwards by
    monkeypatch's teardown) so the ``hasattr`` guard passes and the runner reaches
    its fingerprint comparison, then calls with a ``frozen_fingerprint`` that does
    not match -- proving the comparison itself, not just the guard in front of it,
    is what raises.
    """
    import importlib.util

    import hydroseason._scientific_defaults as defaults
    from hydroseason._calibration import TroughGeometry, trough_geometry_fingerprint

    fake_geometry = TroughGeometry(3, 5, 6)
    real_fingerprint = trough_geometry_fingerprint(fake_geometry)
    monkeypatch.setattr(defaults, "TROUGH_GEOMETRY_DEFAULTS", fake_geometry, raising=False)
    monkeypatch.setattr(defaults, "TROUGH_GEOMETRY_FINGERPRINT", real_fingerprint, raising=False)

    spec = importlib.util.spec_from_file_location(
        "run_calibration", ROOT / "scripts" / "run_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(RuntimeError, match="differs from calibration"):
        module.run_trough_geometry_validation(
            seeds=list(range(40000, 40004)),
            out_report=tmp_path / "geometry-validation.json",
            frozen_fingerprint="0" * 64,
        )
