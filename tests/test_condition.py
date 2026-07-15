import numpy as np
import pandas as pd

from hydroseason._condition import (
    classify_annual_surface_water_condition,
    compute_monthly_surface_water_condition,
)


def _annual():
    years = np.arange(2000, 2012)
    return pd.DataFrame(
        {
            "hy_year": years,
            "status": "complete",
            "hy_end": pd.to_datetime([f"{year}-09-01" for year in years]),
            "peak_extent_pct": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120],
            "trough_extent_pct": [1, 12, 3, 4, 5, 6, 7, 8, 9, 10, 2, 11],
        }
    )


def test_recharge_and_refuge_axes_produce_all_four_joint_states():
    result = classify_annual_surface_water_condition(_annual())
    by_year = result.set_index("hy_year")["annual_condition"]
    assert by_year[2000] == "dry_low_refuge"
    assert by_year[2001] == "buffered_low_recharge"
    assert by_year[2010] == "recharged_then_contracting"
    assert by_year[2011] == "wet_persistent"
    assert result.loc[result["hy_year"] == 2000, "peak_percentile"].item() == 0.0
    assert result.loc[result["hy_year"] == 2011, "peak_percentile"].item() == 100.0


def test_consecutive_counts_only_follow_joint_extremes():
    annual = _annual()
    annual.loc[annual["hy_year"].isin([2002, 2003]), ["peak_extent_pct", "trough_extent_pct"]] = [5, 0]
    result = classify_annual_surface_water_condition(annual)
    assert result.loc[result["hy_year"] == 2003, "consecutive_dry_cycles"].item() >= 2


def test_low_variability_suppresses_public_labels_but_keeps_percentiles():
    result = classify_annual_surface_water_condition(_annual(), low_variability=True)
    assert result["peak_percentile"].notna().all()
    assert set(result["annual_condition"]) == {"not_applicable_low_variability"}


def test_monthly_condition_uses_same_calendar_month_and_fixed_reference():
    index = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    frame = pd.DataFrame(
        {"extent_pct": index.year - 1999 + index.month / 100, "invalid_pct": 0.0},
        index=index,
    )
    result = compute_monthly_surface_water_condition(
        frame, reference_start="2000-01-01", reference_end="2009-12-01"
    )
    row = result.loc["2011-01-01"]
    assert row["reference_n"] == 10
    assert row["reference_median_pct"] == 5.51
    assert row["anomaly_pct"] == 6.5
    assert row["condition_percentile"] == 100.0


def test_low_quality_month_has_no_condition_rank():
    frame = pd.DataFrame(
        {"extent_pct": [10.0, 20.0], "invalid_pct": [0.0, 50.0]},
        index=pd.to_datetime(["2000-01-01", "2001-01-01"]),
    )
    result = compute_monthly_surface_water_condition(frame)
    assert pd.isna(result.loc["2001-01-01", "condition_percentile"])
