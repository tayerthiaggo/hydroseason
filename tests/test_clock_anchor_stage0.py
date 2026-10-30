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
    end_dry_as_run,
    exported_extent,
    leave_one_out_deviations,
    month_from_index,
    month_index,
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
