# tests/test_gilbert_regression.py
from pathlib import Path

import pandas as pd

from hydroseason import detect_dynamic_hydrological_years, suggest_dynamic_hydro_year_config
from hydroseason._boundary_validation import align_events_by_interval, summarize_timing

FIXTURES = Path(__file__).parent / "fixtures"


def test_gilbert_reviewed_events_meet_unblocking_gate():
    monthly = pd.read_csv(FIXTURES / "gilbert_river_monthly.csv", parse_dates=["date"]).set_index("date")
    truth = pd.read_csv(
        FIXTURES / "gilbert_river_reviewed_events.csv",
        parse_dates=["interval_start", "interval_end", "trough_month", "peak_month"],
    )
    config = suggest_dynamic_hydro_year_config(monthly, max_invalid_pct=20.0)
    actual = detect_dynamic_hydrological_years(monthly, config=config)
    trough_actual = actual.rename(columns={"trough_month": "actual_month"})[["actual_month"]]
    # Real fixture encodes detectability as the string "yes" (not "true").
    detectable = truth["detectable"].astype(str).str.lower().eq("yes")
    trough_truth = truth.loc[detectable].rename(columns={"trough_month": "truth_month"})
    aligned = align_events_by_interval(trough_truth, trough_actual)
    metrics = summarize_timing(aligned)
    print("Gilbert trough alignment metrics:", metrics)
    print(aligned.to_string(index=False))
    assert metrics["coverage"] >= 0.80, metrics
    assert metrics["within_1_month"] >= 0.80, metrics
    assert metrics["p90_abs_error_months"] <= 2.0, metrics
    assert metrics["max_abs_error_months"] < 11.0, metrics
