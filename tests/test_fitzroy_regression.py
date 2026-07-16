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
from hydroseason._boundary_validation import align_events_by_interval, summarize_timing


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


def _fitzroy_trough_truth() -> pd.DataFrame:
    """Build interval-scored trough truth from genuine independent review.

    The fixture ``fitzroy_reviewed_events.csv`` contains manually reviewed
    hydrological year boundaries and trough months (not derived from the
    legacy detector's own output). Dates are stored day-first (DD/MM/YYYY),
    so we must parse with ``dayfirst=True`` to avoid silently misinterpreting
    dates like ``01/01/2024`` as January 1st instead of the intended
    January 1st 2024 (the hazard was already encountered once for Gilbert and
    fixed by explicit day-first parsing).

    We build the standard interval-scored format:

    * ``truth_month``     = reviewed ``trough_month``
    * ``interval_end``    = reviewed ``trough_month`` (right-inclusive)
    * ``interval_start``  = the prior trough's month + 1 (left-exclusive),
      or the series' start date for the first chronological event

    Consecutive events never double-count a shared month; each ``truth_month``
    lies inside its own half-open [interval_start, interval_end] window.
    """
    monthly = pd.read_csv(FIXTURES / "fitzroy_kimberley_monthly.csv", parse_dates=["date"])
    series_start = monthly["date"].min()

    reviewed = pd.read_csv(
        FIXTURES / "fitzroy_reviewed_events.csv",
        parse_dates=["trough_month", "peak_month"],
        dayfirst=True,
    )
    # Filter to detectable events only (case-insensitive).
    detectable = reviewed["detectable"].astype(str).str.lower().eq("yes")
    reviewed = reviewed.loc[detectable].reset_index(drop=True)

    # Sort by trough_month chronologically to ensure "previous" is always correct.
    reviewed = reviewed.sort_values("trough_month").reset_index(drop=True)

    # Compute interval_start: prior trough + 1 month, or series start for first.
    reviewed["interval_start"] = pd.NaT
    reviewed["interval_end"] = reviewed["trough_month"]

    for i in range(len(reviewed)):
        if i == 0:
            reviewed.loc[i, "interval_start"] = series_start
        else:
            # Prior trough + 1 month
            prior_trough = reviewed.loc[i - 1, "trough_month"]
            reviewed.loc[i, "interval_start"] = prior_trough + pd.DateOffset(months=1)

    return pd.DataFrame(
        {
            "event_id": reviewed["event_id"],
            "interval_start": reviewed["interval_start"],
            "interval_end": reviewed["interval_end"],
            "truth_month": reviewed["trough_month"],
        }
    )


def test_dynamic_fitzroy_troughs_meet_unblocking_gate():
    monthly = pd.read_csv(FIXTURES / "fitzroy_kimberley_monthly.csv", parse_dates=["date"]).set_index("date")
    config = DynamicHydroYearConfig(expected_trough_month=11, trough_search_radius_months=3, max_invalid_pct=95.0)
    actual = detect_dynamic_hydrological_years(monthly, config=config)
    assert actual["hy_year"].is_unique
    trough_actual = actual.rename(columns={"trough_month": "actual_month"})[["actual_month"]]
    trough_truth = _fitzroy_trough_truth()
    aligned = align_events_by_interval(trough_truth, trough_actual)
    metrics = summarize_timing(aligned)
    print("Fitzroy trough alignment metrics:", metrics)
    print(aligned.to_string(index=False))
    assert metrics["coverage"] >= 0.80, metrics
    assert metrics["within_1_month"] >= 0.80, metrics
    assert metrics["p90_abs_error_months"] <= 2.0, metrics
    assert metrics["max_abs_error_months"] < 11.0, metrics
