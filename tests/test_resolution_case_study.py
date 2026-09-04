from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.run_resolution_case_study import (
    ACQUISITION_SPEEDUP_GROUP_KEYS,
    ResolutionMetrics,
    check_resolution_study,
    compare_resolution,
    summarize_acquisition,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CASE_DATA = REPO_ROOT / "case_studies" / "data" / "extent"


def test_resolution_metrics_compare_scientific_products():
    native = pd.DataFrame(
        {"extent_pct": [10.0, 20.0, 30.0, 40.0], "invalid_pct": [0.0, 0.0, 0.0, 0.0]},
        index=pd.date_range("2020-01-01", periods=4, freq="MS"),
    )
    coarse = pd.DataFrame(
        {"extent_pct": [10.5, 19.5, 30.2, 39.8], "invalid_pct": [0.0, 0.0, 0.0, 0.0]},
        index=pd.date_range("2020-01-01", periods=4, freq="MS"),
    )
    result = compare_resolution(
        native, coarse, catchment="test_catchment", candidate_resolution_m=60
    )
    assert isinstance(result, ResolutionMetrics)
    assert result.correlation is not None
    assert 0.0 <= result.correlation <= 1.0
    assert result.n_months == 4
    assert isinstance(result.route_match, bool)
    assert 0.0 <= result.peak_within_one_month_fraction <= 1.0
    assert 0.0 <= result.trough_within_one_month_fraction <= 1.0


def test_resolution_metrics_handles_constant_input():
    native = pd.DataFrame(
        {"extent_pct": [10.0, 10.0, 10.0, 10.0], "invalid_pct": [0.0, 0.0, 0.0, 0.0]},
        index=pd.date_range("2020-01-01", periods=4, freq="MS"),
    )
    coarse = pd.DataFrame(
        {"extent_pct": [10.0, 10.0, 10.0, 10.0], "invalid_pct": [0.0, 0.0, 0.0, 0.0]},
        index=pd.date_range("2020-01-01", periods=4, freq="MS"),
    )
    result = compare_resolution(
        native, coarse, catchment="test_constant", candidate_resolution_m=60
    )
    assert result.correlation_status == "constant_input"
    assert pd.isna(result.correlation) or result.correlation is None


def test_acquisition_summary_never_compares_different_analysis_resolutions():
    runs = pd.DataFrame(
        [
            {"resolution_m": 30, "pruning": "off", "seconds": 20},
            {"resolution_m": 60, "pruning": "planning_footprint", "seconds": 5},
        ]
    )
    with pytest.raises(ValueError, match="fixed analysis resolution"):
        summarize_acquisition(runs)


def test_composite_mode_is_not_reported_as_pruning_speedup():
    assert "composite_bundle" not in ACQUISITION_SPEEDUP_GROUP_KEYS


def test_checked_resolution_results_match_fresh_offline_computation():
    assert check_resolution_study(
        output_dir=REPO_ROOT / "case_studies" / "results" / "resolution"
    )


def test_fitzroy_trough_recovery_after_recession_limb_fix():
    """Pin the recovery this work exists to deliver.

    Before: 8 of 21 cycles resolved at 30m, with windows up to 13 months that
    spanned the wet-season peak. After: the whole-cycle contamination is gone
    and a sustained minimum is reported as `broad` rather than discarded.
    """
    from hydroseason import analyze_catchment, load_extent_csv
    from scripts.run_resolution_case_study import DEFAULT_DATA_DIR

    df = load_extent_csv(
        DEFAULT_DATA_DIR / "fitzroy_river_wa_30m.csv", date_col="date", value_col="extent_pct"
    )
    analysis = analyze_catchment(df, phase_scheme="two_phase")
    years = analysis.hydro_years
    resolved = years["trough_timing_status"].isin(["point", "interval", "broad"]).sum()

    assert analysis.route == "per_year_detection"
    assert resolved >= 18, f"expected >=18 of 21 cycles resolved, got {resolved}"
    assert (years["trough_timing_status"] == "unresolved").sum() <= 3
