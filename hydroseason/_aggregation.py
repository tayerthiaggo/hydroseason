from __future__ import annotations

import numpy as np
import pandas as pd


def aggregate_basin_monthly_extent(monthly: pd.DataFrame, *, date_col: str = "date", aoi_col: str = "aoi_id", area_weight_col: str | None = None) -> pd.DataFrame:
    """Combine per-AOI monthly extent rows into one basin record.

    With pixel-count columns (``n_water``, ``n_valid``, ``n_invalid``,
    ``n_aoi``) the counts are summed and ``extent_pct`` and ``invalid_pct``
    are recomputed from the sums. Otherwise ``extent_pct`` is weighted by
    ``area_weight_col``, which is then required, and ``invalid_pct`` is NaN.
    An AOI missing from a month counts as fully invalid in the count path and
    carries no weight in the area path; a month no AOI reported stays NaN.
    Each AOI may contribute one row per month. ``n_aoi_reporting``,
    ``n_aoi_expected`` and ``aoi_coverage_pct`` say how many AOIs reported
    each month.
    """
    frame = monthly.copy()
    frame[date_col] = pd.to_datetime(frame[date_col]).dt.to_period("M").dt.to_timestamp()
    if frame.duplicated([date_col, aoi_col]).any():
        raise ValueError("each AOI may contribute at most one row per month.")
    expected_aoi = frame[aoi_col].nunique()
    count_cols = ["n_water", "n_valid", "n_invalid", "n_aoi"]
    if set(count_cols).issubset(frame.columns):
        # A missing AOI-month counts as fully invalid over that AOI's footprint
        # (the largest n_aoi it reports), so a gap cannot look fully observed.
        # shortcut: assumes a fixed AOI footprint; pass explicit per-month n_aoi rows if footprints vary.
        full = pd.MultiIndex.from_product([frame[date_col].unique(), frame[aoi_col].unique()], names=[date_col, aoi_col])
        grid = frame.set_index([date_col, aoi_col])[count_cols].reindex(full)
        missing = grid["n_valid"].isna()
        grid["n_aoi"] = grid["n_aoi"].fillna(grid.groupby(level=aoi_col)["n_aoi"].transform("max"))
        grid.loc[missing, ["n_water", "n_valid"]] = 0
        grid.loc[missing, "n_invalid"] = grid.loc[missing, "n_aoi"]
        grouped = grid.groupby(level=date_col)[count_cols].sum(min_count=1)
        grouped["extent_pct"] = np.where(grouped["n_valid"] > 0, 100.0 * grouped["n_water"] / grouped["n_valid"], np.nan)
        grouped["invalid_pct"] = np.where(grouped["n_aoi"] > 0, 100.0 * grouped["n_invalid"] / grouped["n_aoi"], np.nan)
        reporting = frame.loc[frame["n_valid"] > 0].groupby(date_col)[aoi_col].nunique()
    else:
        if area_weight_col is None or area_weight_col not in frame:
            raise ValueError("percentage-only aggregation requires an explicit area weight column.")
        if (frame[area_weight_col] <= 0).any():
            raise ValueError("area weights must be positive.")
        frame["weighted_extent"] = frame["extent_pct"] * frame[area_weight_col]
        # Only AOIs that reported carry weight; a month nobody reported stays NaN (0/0).
        frame["reported_weight"] = frame[area_weight_col].where(frame["extent_pct"].notna())
        grouped = frame.groupby(date_col).agg(weighted_extent=("weighted_extent", "sum"), total_weight=("reported_weight", "sum"))
        grouped["extent_pct"] = grouped["weighted_extent"] / grouped["total_weight"]
        grouped["invalid_pct"] = np.nan
        reporting = frame.loc[frame["extent_pct"].notna()].groupby(date_col)[aoi_col].nunique()
    grouped["n_aoi_reporting"] = reporting.reindex(grouped.index, fill_value=0)
    grouped["n_aoi_expected"] = expected_aoi
    grouped["aoi_coverage_pct"] = 100.0 * grouped["n_aoi_reporting"] / expected_aoi
    return grouped
