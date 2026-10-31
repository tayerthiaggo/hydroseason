"""Pandas-only extent-CSV and monthly-axis helpers (no geospatial dependency)."""

from __future__ import annotations

import os
from typing import Literal

import numpy as np
import pandas as pd


def load_extent_csv(
    path: str | os.PathLike[str],
    *,
    date_col: str = "date",
    value_col: str = "extent_pct",
) -> pd.DataFrame:
    """Read a monthly extent CSV into date-indexed form for detection.

    This loader only parses dates and coerces the value column; it does not
    gapfill missing months or quality-screen invalid coverage. The CSV is
    valid input for ``detect_hydrological_years`` only if the upstream
    extent series already went through mask completion and quality
    screening (see the migration plan's gapfilling recommendation).
    """
    frame = pd.read_csv(path)
    missing = {date_col, value_col}.difference(frame.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}.")
    out = frame.copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.pop(date_col), errors="raise")).to_period("M").to_timestamp()
    out[value_col] = pd.to_numeric(out[value_col], errors="raise")
    return out.sort_index()


def complete_monthly_axis(
    masks,
    start_date: str,
    end_date: str,
    *,
    invalid_value: int = -1,
    duplicate_month_policy: Literal["raise", "warn"] = "raise",
    outside_aoi_value: int = -2,
):
    """Reindex a lazy mask cube to complete monthly starts; gaps become invalid.

    Inserted months are ``invalid_value`` inside the AOI. Cells marked
    ``outside_aoi_value`` in the first observed month stay outside on inserted
    months, so the AOI denominator is the same in every month.
    """
    if "time" not in masks.dims:
        raise ValueError("complete_monthly_axis expects a DataArray with a 'time' dimension.")
    source = pd.DatetimeIndex(np.asarray(masks.time.values)).to_period("M").to_timestamp()
    if source.has_duplicates:
        duplicates = sorted({date.strftime("%Y-%m") for date in source[source.duplicated()]})
        if duplicate_month_policy == "raise":
            raise ValueError(f"Duplicate month timestamps: {duplicates}.")
        if duplicate_month_policy != "warn":
            raise ValueError("duplicate_month_policy must be 'raise' or 'warn'.")
        import warnings

        warnings.warn(f"Duplicate month timestamps: {duplicates}; keeping first.", UserWarning, stacklevel=2)
        masks = masks.isel(time=np.flatnonzero(~source.duplicated()))
        source = pd.DatetimeIndex(np.asarray(masks.time.values))
    start = pd.Timestamp(start_date).to_period("M").to_timestamp()
    end = pd.Timestamp(end_date).to_period("M").to_timestamp()
    axis = pd.date_range(start, end, freq="MS")
    source_set = {date.strftime("%Y-%m") for date in source}
    inserted = sorted(set(masks.attrs.get("inserted_months", [])) | ({date.strftime("%Y-%m") for date in axis} - source_set))
    out = masks.assign_coords(time=("time", source)).reindex(time=axis, fill_value=np.array(invalid_value, dtype=masks.dtype).item())
    if np.issubdtype(out.dtype, np.floating):
        out = out.fillna(np.array(invalid_value, dtype=out.dtype).item())
    if inserted and masks.sizes.get("time", 0) > 0 and len(masks.dims) > 1:
        # The AOI clip marks outside cells -2 in every observed month. An
        # inserted month must keep that marking: filling it with -1 everywhere
        # would count outside cells as unobserved AOI cells and inflate n_aoi.
        outside_value = np.array(outside_aoi_value, dtype=out.dtype).item()
        outside = masks.isel(time=0, drop=True) == outside_value
        inserted_times = pd.DatetimeIndex([pd.Timestamp(f"{month}-01") for month in inserted])
        on_inserted_month = out["time"].isin(inserted_times)
        out = out.where(~(on_inserted_month & outside), outside_value).astype(masks.dtype)
    out.attrs.update(masks.attrs)
    out.attrs.update({"source_months": sorted(source_set), "inserted_months": inserted, "n_inserted_timesteps": len(inserted)})
    return out


__all__ = ["load_extent_csv", "complete_monthly_axis"]
