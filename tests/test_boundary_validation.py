import pandas as pd

from hydroseason._boundary_validation import summarize_timing, align_events_by_interval


def test_timing_summary_counts_unresolved_truth_as_failure():
    aligned = pd.DataFrame({
        "truth_month": pd.to_datetime(["2020-09-01", "2021-09-01"]),
        "actual_month": pd.to_datetime(["2020-09-01", None]),
    })
    metrics = summarize_timing(aligned)
    assert metrics["n_eligible"] == 2
    assert metrics["n_resolved"] == 1
    assert metrics["coverage"] == 0.5
    assert metrics["within_1_month"] == 0.5


def test_timing_summary_exposes_large_tail_error_despite_good_median():
    aligned = pd.DataFrame({
        "truth_month": pd.to_datetime(["2020-09-01", "2021-09-01", "2022-09-01"]),
        "actual_month": pd.to_datetime(["2020-09-01", "2021-10-01", "2023-09-01"]),
    })
    metrics = summarize_timing(aligned)
    assert metrics["median_abs_error_months"] == 1.0
    assert metrics["max_abs_error_months"] == 12.0
    assert metrics["p90_abs_error_months"] > 9.0


def test_interval_alignment_uses_cycle_dates_not_raw_year_label():
    truth = pd.DataFrame({
        "event_id": ["a"],
        "interval_start": pd.to_datetime(["2015-12-01"]),
        "interval_end": pd.to_datetime(["2016-11-01"]),
        "truth_month": pd.to_datetime(["2016-03-01"]),
    })
    actual = pd.DataFrame({
        "actual_month": pd.to_datetime(["2016-03-01"]),
    })
    aligned = align_events_by_interval(truth, actual)
    assert aligned.loc[0, "actual_month"] == pd.Timestamp("2016-03-01")


def test_interval_alignment_includes_exact_match_on_interval_end():
    # interval_end IS this event's own target boundary month; an actual date
    # landing exactly there is the best possible match, not an exclusion.
    truth = pd.DataFrame({
        "event_id": ["a"],
        "interval_start": pd.to_datetime(["2015-11-01"]),
        "interval_end": pd.to_datetime(["2016-10-01"]),
        "truth_month": pd.to_datetime(["2016-10-01"]),
    })
    actual = pd.DataFrame({
        "actual_month": pd.to_datetime(["2016-10-01"]),
    })
    aligned = align_events_by_interval(truth, actual)
    assert aligned.loc[0, "actual_month"] == pd.Timestamp("2016-10-01")


def test_interval_alignment_excludes_exact_match_on_interval_start():
    # interval_start is the PREVIOUS event's own boundary month; an actual
    # date landing exactly there belongs to that previous event, not this one.
    truth = pd.DataFrame({
        "event_id": ["a"],
        "interval_start": pd.to_datetime(["2015-11-01"]),
        "interval_end": pd.to_datetime(["2016-10-01"]),
        "truth_month": pd.to_datetime(["2016-10-01"]),
    })
    actual = pd.DataFrame({
        "actual_month": pd.to_datetime(["2015-11-01"]),
    })
    aligned = align_events_by_interval(truth, actual)
    assert pd.isna(aligned.loc[0, "actual_month"])
