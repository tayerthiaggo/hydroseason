"""Pin the arithmetic of the frozen stage-0 rise rule on known-truth synthetic series.

Nothing here is hydrological truth. The tests record what the rule in
scripts/clock_anchor_stage0.py computes, so that the real-data run in the plan
is a pre-specified test and not an exploration.
"""

import numpy as np
import pandas as pd
import pytest

from scripts.clock_anchor_stage0 import (
    HY_DATE_COLUMNS,
    MARGIN,
    RULE,
    decide,
    end_dry_as_run,
    exported_extent,
    leave_one_out_deviations,
    month_from_index,
    month_index,
    rise_month,
    synchrony,
    valid_denominator_extent,
    weighted_median,
)


def test_rule_and_margin_are_the_frozen_values():
    assert RULE["version"] == "stage0_rise_v1"
    assert RULE["floor_pp_min"] == 1.0
    assert RULE["confirm_max_gap_months"] == 2
    assert RULE["scored_statuses"] == ["point", "interval"]
    assert MARGIN["min_within_1"] == 0.90
    assert MARGIN["min_gain_over_end_dry"] == 0.05
    assert MARGIN["min_coverage"] == 0.90
    assert MARGIN["big_tile_min_px"] == 3000
    assert MARGIN["min_other_tiles"] == 3
    assert MARGIN["min_scored_tile_years"] == 500
    assert (MARGIN["hy_first"], MARGIN["hy_last"]) == (1988, 2025)
    assert "trough_boundary_date" in HY_DATE_COLUMNS


def test_valid_denominator_extent_divides_by_observed_share():
    monthly = pd.DataFrame(
        {
            "date": ["2000-01-01", "2000-02-01", "2000-03-01"],
            "extent_pct": [10.0, 10.0, np.nan],
            "invalid_pct": [50.0, 0.0, 100.0],
        }
    )
    values = valid_denominator_extent(monthly)
    assert values.loc["2000-01-01"] == pytest.approx(20.0)
    assert values.loc["2000-02-01"] == pytest.approx(10.0)
    assert np.isnan(values.loc["2000-03-01"])
    assert exported_extent(monthly).loc["2000-01-01"] == pytest.approx(10.0)
    assert isinstance(values.index, pd.DatetimeIndex)


def test_month_index_is_absolute_and_invertible():
    assert month_index("2000-01-01") == 2000 * 12
    assert month_index("2000-12-01") - month_index("2000-01-01") == 11
    assert month_index("2001-01-01") - month_index("2000-12-01") == 1
    assert month_from_index(month_index("1999-11-01")) == pd.Timestamp("1999-11-01")


def test_end_dry_as_run_follows_the_hydropools_chain():
    point = pd.Series(
        {
            "trough_timing_status": "point",
            "trough_date": pd.Timestamp("2000-09-01"),
            "trough_interval_end_date": pd.Timestamp("2000-10-01"),
            "trough_boundary_date": pd.Timestamp("2000-09-01"),
        }
    )
    broad = pd.Series(
        {
            "trough_timing_status": "broad",
            "trough_date": pd.NaT,
            "trough_interval_end_date": pd.Timestamp("2000-10-01"),
            "trough_boundary_date": pd.Timestamp("2000-10-01"),
        }
    )
    unresolved = pd.Series(
        {
            "trough_timing_status": "unresolved",
            "trough_date": pd.NaT,
            "trough_interval_end_date": pd.NaT,
            "trough_boundary_date": pd.Timestamp("2000-08-01"),
        }
    )
    blank = pd.Series(
        {
            "trough_timing_status": None,
            "trough_date": pd.NaT,
            "trough_interval_end_date": pd.NaT,
            "trough_boundary_date": pd.NaT,
        }
    )
    assert end_dry_as_run(point) == pd.Timestamp("2000-09-01")
    assert end_dry_as_run(broad) == pd.Timestamp("2000-10-01")
    assert end_dry_as_run(unresolved) == pd.Timestamp("2000-08-01")
    assert end_dry_as_run(blank) is None


def test_weighted_median_matches_the_proposal_definition():
    assert weighted_median([1, 2, 10], [1, 1, 1]) == 2.0
    assert weighted_median([1, 2, 10], [5, 1, 1]) == 1.0
    assert weighted_median([3], [7]) == 3.0


def test_leave_one_out_deviations_exclude_the_target():
    devs = leave_one_out_deviations([5, 5, 5, 9], [1, 1, 1, 1], min_other=3)
    assert list(devs) == [0.0, 0.0, 0.0, 4.0]
    assert np.isnan(leave_one_out_deviations([5, 9], [1, 1], min_other=3)).all()


def _series(overrides=None, missing=(), base=2.0, start="2000-01-01", months=48):
    index = pd.date_range(start, periods=months, freq="MS")
    values = pd.Series(base, index=index, dtype=float)
    for stamp, value in (overrides or {}).items():
        values.loc[pd.Timestamp(stamp)] = value
    for stamp in missing:
        values.loc[pd.Timestamp(stamp)] = np.nan
    return values


def _cycle(year, floor=0.5):
    return dict(
        hy_year=year,
        trough_boundary_date=f"{year}-09-01",
        trough_interval_start_date=f"{year}-08-01",
        trough_interval_end_date=f"{year}-09-01",
        trough_date=f"{year}-09-01",
        trough_timing_status="point",
        peak_date=f"{year}-02-01",
        peak_interval_start_date=None,
        mid_dry_date=f"{year}-06-01",
        detectability_floor_pp=floor,
    )


def _rows(*years):
    frame = pd.DataFrame([_cycle(year) for year in years])
    for col in HY_DATE_COLUMNS:
        frame[col] = pd.to_datetime(frame[col])
    return frame


def _rise(values, rows, **kwargs):
    kwargs.setdefault("floor_pp_min", 1.0)
    kwargs.setdefault("confirm_max_gap_months", 2)
    return rise_month(values, rows.iloc[0], rows.iloc[1], **kwargs)


def test_rise_month_point_when_the_departure_is_bracketed_and_confirmed():
    values = _series({"2000-12-01": 6.0, "2001-01-01": 12.0, "2001-02-01": 20.0})
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "point"
    assert result["rise_month"] == pd.Timestamp("2000-12-01")
    assert result["interval_start"] == pd.Timestamp("2000-12-01")
    assert result["interval_end"] == pd.Timestamp("2000-12-01")
    assert result["level_pp"] == pytest.approx(2.0)
    assert result["threshold_pp"] == pytest.approx(3.0)  # band median 2.0 + max(0.5, 1.0)
    assert result["window_end"] == pd.Timestamp("2001-02-01")
    assert result["band_start"] == pd.Timestamp("2000-08-01")
    assert result["n_pulses"] == 0


def test_rise_month_skips_a_one_month_pulse():
    values = _series({"2000-10-01": 5.0, "2001-01-01": 7.0, "2001-02-01": 12.0})
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "point"
    assert result["rise_month"] == pd.Timestamp("2001-01-01")
    assert result["n_pulses"] == 1


def test_rise_month_reports_an_interval_across_a_gap():
    values = _series({"2000-12-01": 6.0, "2001-01-01": 12.0}, missing=["2000-11-01"])
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "interval"
    assert result["rise_month"] == pd.Timestamp("2000-12-01")
    assert result["interval_start"] == pd.Timestamp("2000-11-01")
    assert result["interval_end"] == pd.Timestamp("2000-12-01")


def test_rise_month_is_unconfirmed_without_a_following_observation():
    values = _series({"2001-02-01": 6.0})  # the exceedance is the window's last month
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "unconfirmed"
    assert result["rise_month"] == pd.Timestamp("2001-02-01")


def test_rise_month_is_unconfirmed_when_the_next_observation_is_too_far():
    values = _series(
        {"2000-11-01": 6.0, "2001-02-01": 12.0}, missing=["2000-12-01", "2001-01-01"]
    )
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "unconfirmed"
    assert result["rise_month"] == pd.Timestamp("2000-11-01")


def test_rise_month_confirms_across_a_single_missing_month():
    values = _series({"2000-11-01": 6.0, "2001-01-01": 12.0}, missing=["2000-12-01"])
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "point"
    assert result["rise_month"] == pd.Timestamp("2000-11-01")
    assert _rise(values, _rows(2000, 2001), confirm_max_gap_months=1)["status"] == "unconfirmed"


def test_rise_month_no_rise_when_nothing_leaves_the_band():
    assert _rise(_series(), _rows(2000, 2001))["status"] == "no_rise"


def test_rise_month_abstention_statuses():
    rows = _rows(2000, 2001)
    no_band = _series(missing=["2000-08-01", "2000-09-01"])
    assert _rise(no_band, rows)["status"] == "no_band_level"
    unobserved = _series(missing=[f"2000-{m:02d}-01" for m in (10, 11, 12)] + ["2001-01-01", "2001-02-01"])
    assert _rise(unobserved, rows)["status"] == "no_observed_months"
    assert rise_month(_series(), rows.iloc[0], None, floor_pp_min=1.0, confirm_max_gap_months=2)["status"] == "no_window"


def test_rise_month_uses_the_detectability_floor_when_it_exceeds_the_minimum():
    values = _series({"2000-12-01": 4.5, "2001-01-01": 4.6, "2001-02-01": 20.0})
    rows = _rows(2000, 2001)
    rows.loc[0, "detectability_floor_pp"] = 3.0  # threshold 2.0 + 3.0 = 5.0
    result = _rise(values, rows)
    assert result["threshold_pp"] == pytest.approx(5.0)
    assert result["status"] == "unconfirmed"  # only February exceeds, and it is the last month


def test_rise_month_falls_back_to_the_next_boundary_when_the_next_peak_is_missing():
    rows = _rows(2000, 2001)
    rows.loc[1, "peak_date"] = pd.NaT
    values = _series({"2001-03-01": 6.0, "2001-04-01": 12.0})
    result = _rise(values, rows)
    assert result["window_end"] == pd.Timestamp("2001-09-01")
    assert result["status"] == "point"
    assert result["rise_month"] == pd.Timestamp("2001-03-01")


def test_rise_month_abstains_if_first_post_band_month_is_missing():
    values = _series({"2000-11-01": 6.0, "2000-12-01": 8.0}, missing=["2000-10-01"])
    result = _rise(values, _rows(2000, 2001))
    assert result["status"] == "missing_first_post_band_month"
    assert pd.isna(result["rise_month"])


def test_rise_month_search_begins_after_band_end_not_boundary():
    rows = _rows(2000, 2001)
    rows.loc[0, "trough_boundary_date"] = pd.Timestamp("2000-08-01")
    values = _series({"2000-09-01": 6.0, "2000-10-01": 6.0, "2000-11-01": 8.0})
    result = _rise(values, rows)
    assert result["rise_month"] == pd.Timestamp("2000-10-01")
    assert result["status"] == "interval"
    assert result["interval_start"] == pd.Timestamp("2000-10-01")


def test_synchrony_scores_leave_target_out_agreement_on_big_tiles():
    table = pd.DataFrame(
        {
            "tile": ["a", "b", "c", "d", "small"] * 2,
            "hy_year": [2000] * 5 + [2001] * 5,
            "px": [5000, 5000, 5000, 5000, 100] * 2,
            "month": pd.to_datetime(
                [
                    "2000-12-01", "2000-12-01", "2001-01-01", "2001-04-01", "2000-06-01",
                    "2001-12-01", "2001-12-01", "2001-12-01", None, "2001-06-01",
                ]
            ),
        }
    )
    result = synchrony(table, "month", big_tile_min_px=3000, min_other_tiles=3)
    assert result["n_years"] == 1
    assert result["n_tile_years"] == 4
    assert result["pooled_within_1"] == pytest.approx(0.75)
    assert result["mean_within_1"] == pytest.approx(0.75)
    assert result["share_ge3"] == pytest.approx(0.25)


def test_synchrony_is_empty_without_enough_tiles():
    table = pd.DataFrame({"hy_year": [2000, 2000], "px": [5000, 5000], "month": pd.to_datetime(["2000-12-01", "2001-01-01"])})
    result = synchrony(table, "month", big_tile_min_px=3000, min_other_tiles=3)
    assert result["n_tile_years"] == 0
    assert np.isnan(result["pooled_within_1"])


def test_decide_applies_the_frozen_margin():
    end_dry = {"n_tile_years": 1000, "pooled_within_1": 0.83}
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.91}, end_dry, coverage=0.95) == "PASS"
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.91}, end_dry, coverage=0.85) == "FAIL"
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.87}, end_dry, coverage=0.95) == "FAIL"
    strong_baseline = {"n_tile_years": 1000, "pooled_within_1": 0.92}
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.95}, strong_baseline, coverage=0.95) == "FAIL"
    assert decide({"n_tile_years": 100, "pooled_within_1": 0.95}, end_dry, coverage=0.95) == "INCONCLUSIVE"
    assert decide({"n_tile_years": 1000, "pooled_within_1": np.nan}, end_dry, coverage=0.95) == "INCONCLUSIVE"


def test_decide_accepts_exact_gain_boundary_but_not_below_it():
    end_dry = {"n_tile_years": 1000, "pooled_within_1": 0.90}
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.95}, end_dry, coverage=0.95) == "PASS"
    assert decide({"n_tile_years": 1000, "pooled_within_1": 0.9499999999}, end_dry, coverage=0.95) == "FAIL"
