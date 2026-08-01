from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.run_resolution_case_study import (
    ACQUISITION_SPEEDUP_GROUP_KEYS,
    ResolutionMetrics,
    compare_resolution,
    recommend_resolution,
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
