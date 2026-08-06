from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from .hydro_year import monthly_water_extent
from .io import complete_monthly_axis, load_extent_csv, load_wofs_monthly_extent

DEFAULT_STAC_URL = "https://explorer.dea.ga.gov.au/stac"
DEFAULT_STAC_COLLECTION = "ga_ls_wo_3"

WaterSourceKind = Literal[
    "dea_wofs",
    "extent_csv",
    "extent_dataframe",
    "netcdf_mask",
    "zarr_mask",
    "xarray_dataset",
    "xarray_dataarray",
]


@dataclass(frozen=True)
class ResolvedWaterInput:
    extent: pd.DataFrame
    source_kind: WaterSourceKind


def _normalise_extent_frame(
    frame: pd.DataFrame,
    *,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    out = frame.copy()
    if "date" in out.columns:
        out.index = pd.to_datetime(out.pop("date"), errors="raise")
    elif not isinstance(out.index, pd.DatetimeIndex):
        raise ValueError("Extent input requires a DatetimeIndex or 'date' column.")
    if "extent_pct" not in out.columns:
        raise ValueError("Extent input requires an 'extent_pct' column.")
    out.index = pd.DatetimeIndex(out.index).to_period("M").to_timestamp()
    out.index.name = None  # Normalize index name
    if out.index.has_duplicates:
        duplicates = sorted(out.index[out.index.duplicated()].strftime("%Y-%m").unique())
        raise ValueError(f"Extent input contains duplicate months: {duplicates}.")
    out["extent_pct"] = pd.to_numeric(out["extent_pct"], errors="raise")
    if "invalid_pct" in out.columns:
        out["invalid_pct"] = pd.to_numeric(out["invalid_pct"], errors="raise")
    else:
        # The public precomputed-extent contract only requires extent_pct.
        # Missing quality metadata means the supplied series is already screened.
        out["invalid_pct"] = 0.0
    start = pd.Timestamp(start_date).to_period("M").to_timestamp() if start_date else out.index.min()
    end = pd.Timestamp(end_date).to_period("M").to_timestamp() if end_date else out.index.max()
    out = out.sort_index().loc[start:end]
    if out.empty:
        raise ValueError("Extent input has no months inside the requested date range.")
    return out


def _require_xarray():
    try:
        import xarray as xr
    except ImportError as exc:
        raise ImportError(
            "NetCDF, Zarr, Dataset, and DataArray inputs require the raster extra."
        ) from exc
    return xr


def _select_mask(dataset, variable: str | None):
    available = list(dataset.data_vars)
    if variable is not None:
        if variable not in dataset:
            raise ValueError(
                f"water_mask_variable={variable!r} is unavailable; available variables: {available}."
            )
        return dataset[variable]
    if "water_mask" in dataset:
        return dataset["water_mask"]
    if len(available) == 1:
        return dataset[available[0]]
    raise ValueError(
        f"Dataset variable is ambiguous; available variables: {available}. "
        "Set water_mask_variable."
    )


def _summarise_mask(mask, *, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    if set(mask.dims) != {"time", "y", "x"}:
        raise ValueError("Canonical water masks require exactly time, y, and x dimensions.")
    if mask.sizes["time"] == 0:
        raise ValueError("Canonical water mask has no time steps.")
    valid_codes = mask.astype("int16").isin(np.array([-2, -1, 0, 1], dtype=np.int16)).all()
    scalar = valid_codes.compute() if hasattr(valid_codes.data, "compute") else valid_codes
    if not bool(scalar.item()):
        raise ValueError("Canonical water mask contains values outside canonical values: -2, -1, 0, and 1.")
    source_time = pd.DatetimeIndex(mask.time.values).to_period("M").to_timestamp()
    mask = mask.assign_coords(time=("time", source_time))
    start = pd.Timestamp(start_date).to_period("M").to_timestamp() if start_date else source_time.min()
    end = pd.Timestamp(end_date).to_period("M").to_timestamp() if end_date else source_time.max()
    if start > end:
        raise ValueError("start_date must not be after end_date.")
    mask = mask.sel(time=slice(start, end))
    if mask.sizes["time"] == 0:
        raise ValueError("Water mask has no months inside the requested date range.")
    mask = complete_monthly_axis(mask, str(start.date()), str(end.date()))
    return monthly_water_extent(mask)


def resolve_water_input(
    water_source=None,
    *,
    aoi=None,
    start_date: str | None = None,
    end_date: str | None = None,
    water_mask_variable: str | None = None,
    stac_url: str = DEFAULT_STAC_URL,
    stac_collection: str = DEFAULT_STAC_COLLECTION,
    cache_dir: str | Path | None = None,
) -> ResolvedWaterInput:
    if water_source is None:
        if aoi is None or start_date is None or end_date is None:
            raise ValueError("DEA fetching requires aoi, start_date, and end_date.")
        extent = load_wofs_monthly_extent(
            stac_url,
            stac_collection,
            aoi,
            start_date,
            end_date,
            cache_dir=cache_dir,
        )
        return ResolvedWaterInput(
            _normalise_extent_frame(extent, start_date=start_date, end_date=end_date),
            "dea_wofs",
        )

    if isinstance(water_source, pd.DataFrame):
        return ResolvedWaterInput(
            _normalise_extent_frame(
                water_source, start_date=start_date, end_date=end_date
            ),
            "extent_dataframe",
        )

    if isinstance(water_source, (str, Path)):
        path = Path(water_source)
        if not path.exists():
            raise FileNotFoundError(f"Water source not found: {path}")
        suffix = path.suffix.casefold()
        if suffix == ".csv":
            frame = load_extent_csv(path)
            return ResolvedWaterInput(
                _normalise_extent_frame(frame, start_date=start_date, end_date=end_date),
                "extent_csv",
            )
        xr = _require_xarray()
        if suffix in {".nc", ".nc4", ".netcdf"}:
            dataset = xr.open_dataset(path, chunks={})
            kind: WaterSourceKind = "netcdf_mask"
        elif suffix == ".zarr":
            dataset = xr.open_zarr(path, chunks={}, mask_and_scale=False)
            kind = "zarr_mask"
        else:
            raise ValueError(
                "Water path must be CSV, NetCDF (.nc/.nc4/.netcdf), or Zarr (.zarr)."
            )
        try:
            mask = _select_mask(dataset, water_mask_variable)
            extent = _summarise_mask(mask, start_date=start_date, end_date=end_date)
        finally:
            dataset.close()
        return ResolvedWaterInput(extent, kind)

    xr = _require_xarray()
    if isinstance(water_source, xr.DataArray):
        return ResolvedWaterInput(
            _summarise_mask(
                water_source, start_date=start_date, end_date=end_date
            ),
            "xarray_dataarray",
        )
    if isinstance(water_source, xr.Dataset):
        mask = _select_mask(water_source, water_mask_variable)
        return ResolvedWaterInput(
            _summarise_mask(mask, start_date=start_date, end_date=end_date),
            "xarray_dataset",
        )
    raise TypeError(
        "water_source must be None, a CSV/NetCDF/Zarr path, DataFrame, Dataset, or DataArray."
    )
