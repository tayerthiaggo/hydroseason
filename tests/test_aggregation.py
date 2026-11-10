import pandas as pd
import pytest

from hydroseason._aggregation import aggregate_basin_monthly_extent


def test_basin_extent_uses_summed_counts_not_mean_percentages():
    frame = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-01"], "aoi_id": ["small", "large"],
            "n_water": [10, 180], "n_valid": [20, 900],
            "n_invalid": [0, 100], "n_aoi": [20, 1000],
        }
    )
    result = aggregate_basin_monthly_extent(frame)
    assert result.loc[pd.Timestamp("2020-01-01"), "extent_pct"] == pytest.approx(100 * 190 / 920)
    assert result.loc[pd.Timestamp("2020-01-01"), "aoi_coverage_pct"] == 100.0


def test_percentage_only_input_requires_explicit_area_weight():
    frame = pd.DataFrame(
        {"date": ["2020-01-01", "2020-01-01"], "aoi_id": ["a", "b"], "extent_pct": [10.0, 90.0]}
    )
    with pytest.raises(ValueError, match="area weight"):
        aggregate_basin_monthly_extent(frame)


def test_area_weighted_extent_divides_only_by_areas_that_reported():
    frame = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-01", "2020-02-01", "2020-02-01"],
            "aoi_id": ["a", "b", "a", "b"],
            "extent_pct": [50.0, float("nan"), float("nan"), float("nan")],
            "area": [1.0, 1.0, 1.0, 1.0],
        }
    )
    result = aggregate_basin_monthly_extent(frame, area_weight_col="area")
    assert result.loc[pd.Timestamp("2020-01-01"), "extent_pct"] == 50.0
    assert pd.isna(result.loc[pd.Timestamp("2020-02-01"), "extent_pct"])


def test_count_path_treats_a_missing_aoi_month_as_fully_invalid():
    frame = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-01", "2020-02-01"],
            "aoi_id": ["small", "large", "small"],
            "n_water": [10, 180, 10], "n_valid": [20, 1000, 20],
            "n_invalid": [0, 0, 0], "n_aoi": [20, 1000, 20],
        }
    )
    february = aggregate_basin_monthly_extent(frame).loc[pd.Timestamp("2020-02-01")]
    assert february["extent_pct"] == 50.0
    assert february["invalid_pct"] == pytest.approx(100 * 1000 / 1020)
