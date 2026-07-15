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
