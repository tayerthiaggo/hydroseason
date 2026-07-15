# tests/test_fitzroy_regression.py
from pathlib import Path

import numpy as np
import pandas as pd

from hydroseason import (
    DynamicHydroYearConfig,
    detect_dynamic_hydrological_years,
    detect_hydrological_years,
    suggest_hydro_year_config,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _month_shift(left, right):
    left, right = pd.to_datetime(left), pd.to_datetime(right)
    return (left.dt.year - right.dt.year) * 12 + left.dt.month - right.dt.month


def test_legacy_fitzroy_output_is_unchanged():
    monthly = pd.read_csv(FIXTURES / "fitzroy_kimberley_monthly.csv", parse_dates=["date"]).set_index("date")
    expected = pd.read_csv(FIXTURES / "fitzroy_kimberley_legacy.csv", parse_dates=["hy_start", "hy_end", "peak_month", "mid_dry_month", "end_dry_month"])
    actual = detect_hydrological_years(
        monthly, config=suggest_hydro_year_config(monthly),
        missing_month_policy="ignore", max_invalid_pct=95.0,
    )
    compare = [column for column in actual.columns if column in expected.columns]
    pd.testing.assert_frame_equal(actual[compare].reset_index(drop=True), expected[compare].reset_index(drop=True), check_dtype=False)


def test_dynamic_fitzroy_years_do_not_merge_and_remain_close_to_reviewed_results():
    monthly = pd.read_csv(FIXTURES / "fitzroy_kimberley_monthly.csv", parse_dates=["date"]).set_index("date")
    old = pd.read_csv(FIXTURES / "fitzroy_kimberley_legacy.csv", parse_dates=["peak_month", "end_dry_month"])
    config = DynamicHydroYearConfig(expected_trough_month=11, trough_search_radius_months=3, max_invalid_pct=95.0)
    new = detect_dynamic_hydrological_years(monthly, config=config)
    assert new["hy_year"].is_unique
    adequate = new.loc[new["status"].isin(["complete", "partial"]) & new["peak_month"].notna()]
    comparison = old.merge(adequate, on="hy_year", suffixes=("_old", "_new"))
    assert set(comparison["hy_year"]) == set(adequate["hy_year"])
    peak_shift = _month_shift(comparison["peak_month_new"], comparison["peak_month_old"]).abs()
    trough_shift = _month_shift(comparison["trough_month"], comparison["end_dry_month"]).abs()
    assert float(peak_shift.median()) <= 1.0
    assert float(trough_shift.median()) <= 1.0
    differences = comparison.loc[(peak_shift > 1) | (trough_shift > 1), [
        "hy_year", "peak_month_old", "peak_month_new", "end_dry_month", "trough_month",
        "peak_extent_pct_old", "peak_extent_pct_new", "end_extent_pct", "trough_extent_pct",
        "confidence_old", "confidence_new",
    ]]
    print("Fitzroy rows requiring scientific review:")
    print(differences.to_string(index=False))
