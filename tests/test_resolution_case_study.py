from __future__ import annotations

import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.run_resolution_case_study as study
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
    # Four months give no hydro years, so timing agreement does not apply.
    assert pd.isna(result.peak_within_one_month_fraction)
    assert pd.isna(result.trough_within_one_month_fraction)


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


def test_years_lost_at_the_candidate_count_as_timing_misses(monkeypatch):
    def analysis(years):
        return types.SimpleNamespace(
            hydro_years=pd.DataFrame(
                {"hy_year": years, "peak_month": "2001-02-01", "trough_month": "2001-09-01"}
            ),
            events=types.SimpleNamespace(summary={"n_events": 0, "longest_low_spell_months": 0}),
            regime=types.SimpleNamespace(amplitude_snr=1.0, regime="seasonal"),
            route="per_year_detection",
        )

    # 10 years at 30 m; the candidate keeps one of them, with matching timing.
    analyses = iter([analysis(list(range(2000, 2010))), analysis([2000])])
    monkeypatch.setattr(study, "analyze_catchment", lambda *a, **k: next(analyses))
    extent = pd.DataFrame({"extent_pct": np.arange(12, dtype=float)})
    result = compare_resolution(extent, extent.copy())
    assert result.peak_within_one_month_fraction == pytest.approx(0.1)
    assert result.trough_within_one_month_fraction == pytest.approx(0.1)


def test_timing_gates_fail_when_no_catchment_has_a_cycle():
    row = {
        "candidate_resolution_m": 60, "route_match": True, "correlation": 0.999,
        "normalized_mae": 0.003, "event_count_delta": 0, "longest_low_spell_delta": 0,
        "peak_within_one_month_fraction": np.nan, "trough_within_one_month_fraction": np.nan,
    }
    decision = recommend_resolution(pd.DataFrame([row] * 3))
    assert not decision.loc[0, "recommended"]


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
