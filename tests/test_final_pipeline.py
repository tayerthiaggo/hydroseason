import numpy as np
import pandas as pd

from hydroseason._trough_refinement import TroughRefinementPolicy
from scripts.evaluate_final_pipeline import (
    PIPELINE_CALIBRATION_SEEDS,
    _error_summary,
    _singleton_errors,
    _split_wrong_cycle,
    compare_cycle_tables,
    evaluate_records,
)


def _base_row(**overrides) -> dict:
    row = {
        "hy_year": 2020,
        "hy_start": pd.Timestamp("2019-10-01"),
        "hy_end": pd.Timestamp("2020-09-01"),
        "peak_month": pd.Timestamp("2020-02-01"),
        "peak_extent_pct": 80.0,
        "trough_month": pd.Timestamp("2020-09-01"),
        "status_reason": "ok",
    }
    row.update(overrides)
    return row


def test_comparison_detects_peak_change():
    rows = pd.DataFrame({
        "hy_year": [2020], "hy_start": [pd.Timestamp("2019-10-01")],
        "hy_end": [pd.Timestamp("2020-09-01")],
        "peak_month": [pd.Timestamp("2020-02-01")],
        "peak_extent_pct": [80.0], "trough_month": [pd.Timestamp("2020-09-01")],
        "status_reason": ["ok"],
    })
    altered = rows.copy()
    altered.loc[0, "peak_month"] = pd.Timestamp("2020-03-01")
    _, counts = compare_cycle_tables(rows, altered)
    assert counts["peak_changes"] == 1


def test_comparison_detects_duplicate_boundary():
    before = pd.DataFrame(
        [
            _base_row(hy_year=2020, trough_month=pd.Timestamp("2020-09-01")),
            _base_row(hy_year=2021, trough_month=pd.Timestamp("2021-09-01")),
        ]
    )
    after = before.copy()
    # 2021's boundary collapses onto 2020's -- a duplicate operational date.
    after.loc[after["hy_year"] == 2021, "trough_month"] = pd.Timestamp("2020-09-01")

    _, counts = compare_cycle_tables(before, after)
    assert counts["before_duplicate_or_nonmonotonic_boundaries"] == 0
    assert counts["after_duplicate_or_nonmonotonic_boundaries"] == 1


def test_comparison_detects_reversed_boundaries():
    before = pd.DataFrame(
        [
            _base_row(hy_year=2020, trough_month=pd.Timestamp("2020-09-01")),
            _base_row(hy_year=2021, trough_month=pd.Timestamp("2021-09-01")),
        ]
    )
    after = before.copy()
    # 2021's boundary moves earlier than 2020's -- chronological order breaks.
    after.loc[after["hy_year"] == 2021, "trough_month"] = pd.Timestamp("2020-01-01")

    _, counts = compare_cycle_tables(before, after)
    assert counts["after_duplicate_or_nonmonotonic_boundaries"] == 1
    assert counts["boundary_shifted"] == 1


def test_comparison_detects_newly_uncomputable_row():
    before = pd.DataFrame([_base_row(hy_year=2020)])
    after = before.copy()
    after.loc[0, "status_reason"] = "insufficient_cycle_coverage"

    _, counts = compare_cycle_tables(before, after)
    assert counts["newly_uncomputable"] == 1
    assert counts["newly_computable"] == 0


def test_comparison_detects_missing_row():
    before = pd.DataFrame(
        [
            _base_row(hy_year=2020),
            _base_row(hy_year=2021, trough_month=pd.Timestamp("2021-09-01")),
        ]
    )
    after = before.loc[before["hy_year"] == 2020].copy()

    diff, counts = compare_cycle_tables(before, after)
    assert counts["dropped_rows"] == 1
    assert counts["added_rows"] == 0
    dropped = diff.loc[diff["change"] == "dropped_row"]
    assert list(dropped["hy_year"]) == [2021]


def test_comparison_separates_quality_upgrade_from_downgrade():
    before = pd.DataFrame([_base_row(hy_year=2020, status="partial")])
    upgraded = pd.DataFrame([_base_row(hy_year=2020, status="complete")])
    downgraded_before = pd.DataFrame([_base_row(hy_year=2020, status="complete")])
    downgraded_after = pd.DataFrame([_base_row(hy_year=2020, status="partial")])

    _, up_counts = compare_cycle_tables(before, upgraded)
    assert up_counts["quality_upgraded"] == 1
    assert up_counts["quality_downgraded"] == 0

    _, down_counts = compare_cycle_tables(downgraded_before, downgraded_after)
    assert down_counts["quality_downgraded"] == 1
    assert down_counts["quality_upgraded"] == 0


def test_error_summary_is_none_for_empty_population():
    summary = _error_summary([])
    assert summary["n"] == 0
    assert summary["median_abs_error_months"] is None
    assert summary["p90_abs_error_months"] is None
    assert summary["mean_abs_error_months"] is None
    assert summary["signed_bias_months"] is None


def test_error_summary_reports_measured_denominators():
    summary = _error_summary([1.0, -2.0, 3.0])
    assert summary["n"] == 3
    assert summary["mean_abs_error_months"] == 2.0
    assert summary["signed_bias_months"] == np.mean([1.0, -2.0, 3.0])


class _FakeTruth:
    def __init__(self, identifiable_by_year, trough_date_by_year):
        self.identifiable_by_year = identifiable_by_year
        self.trough_date_by_year = trough_date_by_year


def test_singleton_errors_counts_wrong_point_prediction_on_identifiable_year():
    """A wrong singleton claim on an identifiable year is an error -- the
    year being otherwise resolvable does not excuse a wrong point date.
    """
    annual = pd.DataFrame(
        {
            "hy_year": [2020],
            "trough_timing_status": ["point"],
            "trough_month": [pd.Timestamp("2020-08-01")],
        }
    )
    truth = _FakeTruth(
        identifiable_by_year=(True,),
        trough_date_by_year=(pd.Timestamp("2020-09-01"),),
    )
    errors = _singleton_errors(annual, base_year=2020, truth=truth)
    assert errors == [(2020, -1.0)]


def test_singleton_errors_ignores_non_point_rows():
    """An interval/broad/unresolved row is a correct abstention, not an
    error -- even though the year is truth-identifiable.
    """
    annual = pd.DataFrame(
        {
            "hy_year": [2020],
            "trough_timing_status": ["interval"],
            "trough_month": [pd.Timestamp("2020-08-01")],
        }
    )
    truth = _FakeTruth(
        identifiable_by_year=(True,),
        trough_date_by_year=(pd.Timestamp("2020-09-01"),),
    )
    assert _singleton_errors(annual, base_year=2020, truth=truth) == []


def test_split_wrong_cycle_separates_year_misattribution_from_precision_errors():
    """Opus checkpoint-1 finding F7: a boundary landing far from its matched
    truth year is a wrong-cycle event, not a precision measurement, and must
    not dominate the accuracy pool's median/p90.
    """
    errors = [(2020, 1.0), (2021, -2.0), (2022, 7.0), (2023, -8.0)]
    accuracy, wrong_cycle = _split_wrong_cycle(errors)
    assert accuracy == [1.0, -2.0]
    assert wrong_cycle == 2


def test_evaluate_records_reports_structural_diff_totals():
    """Opus checkpoint-1 finding F6: the summary must state the aggregate
    structural counters explicitly, not only per-record in the cycles table.
    """
    seeds = list(PIPELINE_CALIBRATION_SEEDS)[:3]
    policy = TroughRefinementPolicy(huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5)

    _, summary = evaluate_records(seeds=seeds, partition="calibration", policy=policy)

    assert "structural_diff_totals" in summary
    assert "peak_changes" in summary["structural_diff_totals"]
    assert "wrong_cycle" in summary["off"]
    assert "wrong_cycle" in summary["on"]


def test_evaluate_records_runs_detector_twice_and_reports_family_outcomes():
    """Small real-seed smoke check: the detector actually runs (no supplied
    truth peaks), errors are family-bucketed, and denominators are honest.
    """
    seeds = list(PIPELINE_CALIBRATION_SEEDS)[:10]  # one seed per family
    policy = TroughRefinementPolicy(huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5)

    per_record, summary = evaluate_records(seeds=seeds, partition="calibration", policy=policy)

    assert len(per_record) == len(seeds)
    assert summary["n_seeds"] == len(seeds)
    assert set(summary["families"]) <= {
        "stationary_trough", "wide_phase_excursion", "abrupt_phase_shift",
        "competing_secondary_minimum", "tied_low_plateau_wide",
        "missing_outer_months", "quality_loss_outer_months",
        "zero_dominated_wide_excursion", "short_cycle_stress", "long_cycle_stress",
    }
    for family_summary in summary["families"].values():
        assert family_summary["n_seeds"] >= 1
        assert "off" in family_summary and "on" in family_summary
