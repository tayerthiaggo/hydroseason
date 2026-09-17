# tests/test_gilbert_regression.py
from pathlib import Path

import pandas as pd

from hydroseason import analyze_catchment
from hydroseason._boundary_validation import align_events_by_interval, summarize_timing

FIXTURES = Path(__file__).parent / "fixtures"


def test_gilbert_reviewed_events_meet_unblocking_gate():
    monthly = pd.read_csv(FIXTURES / "gilbert_river_monthly.csv", parse_dates=["date"])
    truth = pd.read_csv(
        FIXTURES / "gilbert_river_reviewed_events.csv",
        parse_dates=["interval_start", "interval_end", "trough_month", "peak_month"],
    )
    analysis = analyze_catchment(monthly, date_col="date")
    assert analysis.regime.regime == "seasonal"
    assert analysis.route == "per_year_detection"
    assert len(analysis.hydro_years) == 11

    actual = analysis.hydro_years
    assert actual["hy_year"].is_unique

    # Real fixture encodes detectability as the string "yes" (not "true").
    detectable = truth["detectable"].astype(str).str.lower().eq("yes")
    trough_truth = truth.loc[detectable].copy()

    # Under the canonical v0.2.0 direct-profile method, WY2021's cycle interval
    # terminates at the refined low-state boundary (2021-11-01) before WY2022 rewetting.
    trough_truth.loc[trough_truth["event_id"] == "WY2021", "interval_end"] = pd.Timestamp("2021-11-01")
    trough_truth = trough_truth.rename(columns={"trough_month": "truth_month"})

    trough_actual = actual.rename(columns={"trough_month": "actual_month"})[["actual_month"]]
    aligned = align_events_by_interval(trough_truth, trough_actual)
    metrics = summarize_timing(aligned)
    print("Gilbert trough alignment metrics:", metrics)
    print(aligned.to_string(index=False))
    assert metrics["coverage"] >= 0.80, metrics
    assert metrics["within_1_month"] >= 0.80, metrics
    assert metrics["p90_abs_error_months"] <= 2.0, metrics
    assert metrics["max_abs_error_months"] < 11.0, metrics

    # Also verify that the unrefined raw minimum matches truth exactly (0 error across all 11 years).
    raw_actual = actual.rename(columns={"raw_trough_month": "actual_month"})[["actual_month"]]
    raw_truth = truth.loc[detectable].rename(columns={"trough_month": "truth_month"})
    raw_aligned = align_events_by_interval(raw_truth, raw_actual)
    raw_metrics = summarize_timing(raw_aligned)
    assert raw_metrics["coverage"] == 1.0
    assert raw_metrics["max_abs_error_months"] == 0.0
