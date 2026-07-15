from __future__ import annotations

import numpy as np
import pandas as pd


def aggregate_basin_monthly_extent(monthly: pd.DataFrame, *, date_col: str = "date", aoi_col: str = "aoi_id", area_weight_col: str | None = None) -> pd.DataFrame:
    frame = monthly.copy()
    frame[date_col] = pd.to_datetime(frame[date_col]).dt.to_period("M").dt.to_timestamp()
    if frame.duplicated([date_col, aoi_col]).any():
        raise ValueError("each AOI may contribute at most one row per month.")
    expected_aoi = frame[aoi_col].nunique()
    count_cols = ["n_water", "n_valid", "n_invalid", "n_aoi"]
    if set(count_cols).issubset(frame.columns):
        grouped = frame.groupby(date_col)[count_cols].sum(min_count=1)
        grouped["extent_pct"] = np.where(grouped["n_valid"] > 0, 100.0 * grouped["n_water"] / grouped["n_valid"], np.nan)
        grouped["invalid_pct"] = np.where(grouped["n_aoi"] > 0, 100.0 * grouped["n_invalid"] / grouped["n_aoi"], np.nan)
        reporting = frame.loc[frame["n_valid"] > 0].groupby(date_col)[aoi_col].nunique()
    else:
        if area_weight_col is None or area_weight_col not in frame:
            raise ValueError("percentage-only aggregation requires an explicit area weight column.")
        if (frame[area_weight_col] <= 0).any():
            raise ValueError("area weights must be positive.")
        frame["weighted_extent"] = frame["extent_pct"] * frame[area_weight_col]
        grouped = frame.groupby(date_col).agg(weighted_extent=("weighted_extent", "sum"), total_weight=(area_weight_col, "sum"))
        grouped["extent_pct"] = grouped["weighted_extent"] / grouped["total_weight"]
        grouped["invalid_pct"] = np.nan
        reporting = frame.loc[frame["extent_pct"].notna()].groupby(date_col)[aoi_col].nunique()
    grouped["n_aoi_reporting"] = reporting.reindex(grouped.index, fill_value=0)
    grouped["n_aoi_expected"] = expected_aoi
    grouped["aoi_coverage_pct"] = 100.0 * grouped["n_aoi_reporting"] / expected_aoi
    return grouped
