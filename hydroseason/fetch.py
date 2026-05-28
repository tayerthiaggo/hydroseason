"""ERA5 zarr → monthly tidy DataFrame.

Improvements over the prototype:
- Polygon mask applied BEFORE temporal resampling (correctness + 5-50x speedup).
- Explicit spatial chunking to keep Dask graph sizes manageable on large catchments.
- Variable adapter registry (rainfall, temperature, evaporation, ...).
- Optional local cache (parquet) keyed by inputs hash to avoid re-downloading.
- Progress bar via dask.diagnostics when available.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .era5_variables import ERA5Variable, get as get_era5_variable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Spatial helpers (CRS-light, lazy imports for optional deps)
# ---------------------------------------------------------------------------
def _wrap_lon_to_ds_range(lon_vals, ds_lon):
    lo, hi = float(ds_lon.min()), float(ds_lon.max())
    if lo >= 0 and hi <= 360:
        return np.mod(lon_vals, 360)
    elif lo >= -180 and hi <= 180:
        lon = np.array(lon_vals)
        return np.where(lon > 180, lon - 360, lon)
    return lon_vals


def _ordered_slice(coord, a, b):
    lo, hi = sorted([a, b])
    return slice(lo, hi) if coord[0] <= coord[-1] else slice(hi, lo)


def rasterize_to_xarray_grid(gdf, ds, lon_name="longitude", lat_name="latitude",
                             all_touched=False, dtype="uint8"):
    import xarray as xr
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds
    from shapely.geometry import mapping

    lon = ds[lon_name].values
    lat = ds[lat_name].values
    transform = from_bounds(
        float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max()),
        len(lon), len(lat),
    )
    shapes = [(mapping(geom), 1) for geom in gdf.geometry]
    mask_np = rasterize(
        shapes=shapes,
        out_shape=(len(lat), len(lon)),
        transform=transform,
        fill=0,
        all_touched=all_touched,
        dtype=dtype,
    )
    return xr.DataArray(
        mask_np.astype(bool),
        coords={lat_name: ds[lat_name], lon_name: ds[lon_name]},
        dims=(lat_name, lon_name),
        name="mask",
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def _cache_key(path: str, gdf, start_year: int, end_year: int, variable_key: str) -> str:
    payload = {
        "path": str(path),
        "start": int(start_year),
        "end": int(end_year),
        "var": variable_key,
        "bbox": [float(x) for x in gdf.total_bounds.tolist()],
        "n_geoms": int(len(gdf)),
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _cache_paths(cache_dir: str | Path, key: str) -> tuple[Path, Path]:
    base = Path(cache_dir)
    return base / f"era5_monthly_{key}.parquet", base / f"era5_monthly_{key}.json"


def _read_cache(cache_dir: str | Path | None, key: str) -> pd.DataFrame | None:
    if cache_dir is None:
        return None
    data_path, _ = _cache_paths(cache_dir, key)
    if data_path.exists():
        logger.info("ERA5 fetch cache hit: %s", data_path)
        return pd.read_parquet(data_path)
    return None


def _write_cache(cache_dir: str | Path | None, key: str, df: pd.DataFrame, meta: dict) -> None:
    if cache_dir is None:
        return
    base = Path(cache_dir)
    base.mkdir(parents=True, exist_ok=True)
    data_path, meta_path = _cache_paths(base, key)
    df.to_parquet(data_path, index=False)
    meta_path.write_text(json.dumps(meta, default=str, indent=2), encoding="utf-8")
    logger.info("ERA5 fetch cache write: %s", data_path)


# ---------------------------------------------------------------------------
# Main fetch
# ---------------------------------------------------------------------------
def get_monthly_variable(
    path: str,
    gdf,
    start_year: int,
    end_year: int,
    *,
    variable: str | ERA5Variable = "rainfall",
    cache_dir: str | Path | None = None,
    spatial_chunk: int = 50,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Fetch monthly catchment-averaged values for one ERA5 variable.

    Parameters
    ----------
    path : str
        Zarr store URI (e.g. ``gs://gcp-public-data-arco-era5/...``).
    gdf : GeoDataFrame
        Polygon(s) defining the catchment.
    start_year, end_year : int
        Inclusive temporal range.
    variable : str | ERA5Variable
        Registry key (rainfall, temperature, evaporation) or an ``ERA5Variable``.
    cache_dir : str | Path | None
        If given, results are cached locally as parquet keyed by inputs hash.
    spatial_chunk : int
        Dask chunk size along latitude/longitude. ``"auto"`` is avoided because it
        blows up the task graph on multi-decade hourly ERA5 requests.
    """
    import xarray as xr

    var = variable if isinstance(variable, ERA5Variable) else get_era5_variable(variable)

    # ---- cache lookup
    key = _cache_key(path, gdf, start_year, end_year, var.key)
    cached = _read_cache(cache_dir, key)
    if cached is not None:
        return cached

    # ---- open lazily
    ds = xr.open_zarr(path, chunks={"time": 744}, storage_options={"token": "anon"})
    ds = ds.sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31"))

    # Resolve variable name in the store
    var_name = var.era5_name
    if var_name not in ds.data_vars:
        # try common short alias
        if "tp" in ds.data_vars and var.key == "rainfall":
            var_name = "tp"
        elif "t2m" in ds.data_vars and var.key == "temperature":
            var_name = "t2m"
        else:
            raise KeyError(
                f"Variable '{var.era5_name}' not found; available: {list(ds.data_vars)}"
            )
    ds = ds[[var_name]]

    # ---- spatial subset on bbox of polygons (CRS = EPSG:4326)
    gdf = gdf.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = gdf.total_bounds
    lon_pair = _wrap_lon_to_ds_range([minx, maxx], ds.longitude)
    lon_sel = _ordered_slice(ds.longitude.values, lon_pair[0], lon_pair[1])
    lat_sel = _ordered_slice(ds.latitude.values, maxy, miny)
    ds_small = ds.sel(longitude=lon_sel, latitude=lat_sel).chunk(
        {"time": 744, "latitude": spatial_chunk, "longitude": spatial_chunk}
    )

    # ---- rasterized polygon mask on the small grid
    mask = rasterize_to_xarray_grid(gdf, ds_small, lon_name="longitude", lat_name="latitude")

    # ---- MASK BEFORE RESAMPLE (correctness + speed)
    da = ds_small[var_name].where(mask)
    if var.aggregation == "sum":
        monthly = da.resample(time="MS").sum("time")
    elif var.aggregation == "mean":
        monthly = da.resample(time="MS").mean("time")
    else:
        raise ValueError(f"Unsupported aggregation '{var.aggregation}'.")

    catchment_series = monthly.mean(("latitude", "longitude"), skipna=True)

    # ---- compute with optional progress
    if show_progress:
        try:
            from dask.diagnostics import ProgressBar
            with ProgressBar():
                values = catchment_series.compute()
        except Exception:
            values = catchment_series.compute()
    else:
        values = catchment_series.compute()

    df = values.to_pandas().rename(var.out_column).to_frame().reset_index()
    df["Date"] = df["time"].dt.strftime("%Y-%m-%d")
    df["Year"] = df["time"].dt.year.astype(int)
    df["Month"] = df["time"].dt.month.astype(int)
    df.drop(columns=["time"], inplace=True)

    # unit conversion
    df[var.out_column] = (df[var.out_column] * var.unit_factor + var.unit_offset).round(2)

    # zero-clip for accumulation variables only (avoid clipping temperatures!)
    if var.aggregation == "sum":
        df.loc[df[var.out_column] < 1, var.out_column] = 0.0

    out = df[["Date", "Year", "Month", var.out_column]]

    _write_cache(
        cache_dir,
        key,
        out,
        meta={
            "path": str(path),
            "start_year": start_year,
            "end_year": end_year,
            "variable": var.key,
            "unit": var.unit_label,
        },
    )
    return out


# ---- backwards-compat shim
def get_monthly_total_precip(path, gdf, start_year, end_year, var="total_precipitation",
                             cache_dir=None, spatial_chunk=50, show_progress=True):
    return get_monthly_variable(
        path=path,
        gdf=gdf,
        start_year=start_year,
        end_year=end_year,
        variable="rainfall",
        cache_dir=cache_dir,
        spatial_chunk=spatial_chunk,
        show_progress=show_progress,
    )
