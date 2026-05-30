"""ERA5/SILO rainfall fetch helpers returning monthly tidy DataFrames.

Improvements over the prototype:
- Polygon mask applied before temporal resampling.
- Explicit spatial chunking to keep Dask graph sizes manageable.
- Variable adapter registry for ERA5 rainfall conversion.
- Optional Parquet cache keyed by inputs hash.
- Progress bar via dask.diagnostics when available.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .era5_variables import ERA5Variable, get as get_era5_variable

logger = logging.getLogger(__name__)

SILO_MONTHLY_RAIN_BASE_URL = (
    "https://s3-ap-southeast-2.amazonaws.com/"
    "silo-open-data/Official/annual/monthly_rain"
)


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


def rasterize_to_xarray_grid(
    gdf,
    ds,
    lon_name="longitude",
    lat_name="latitude",
    all_touched=False,
    dtype="uint8",
):
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


def load_vector(path: str | Path):
    """Load a polygon vector file (GeoJSON/SHP/KML/KMZ/GPKG/GPCK and others).

    Parameters
    ----------
    path : str | Path
        Input vector path.
    """
    import geopandas as gpd

    path = Path(path)
    suffix = path.suffix.lower()

    # Accept the common typo/variant ".gpck" by reading through a temporary
    # ".gpkg" filename so GDAL/Fiona can resolve the driver reliably.
    if suffix == ".gpck":
        with tempfile.TemporaryDirectory() as tmpdir:
            gpkg_alias = Path(tmpdir) / f"{path.stem}.gpkg"
            gpkg_alias.write_bytes(path.read_bytes())
            gdf = gpd.read_file(gpkg_alias)
        if gdf.empty or gdf.geometry.isna().all():
            raise ValueError(
                f"No valid geometries found in vector file: {path}"
            )
        gdf = gdf[gdf.geometry.notna()].copy()
        gdf = gdf[gdf.geometry.is_valid].copy()
        if gdf.empty:
            raise ValueError(
                f"No valid polygon geometries found in vector file: {path}"
            )
        return gdf

    if suffix == ".kmz":
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(path) as zf:
                kml_names = [
                    n for n in zf.namelist() if n.lower().endswith(".kml")
                ]
                if not kml_names:
                    raise ValueError(f"KMZ has no .kml file: {path}")
                target_name = kml_names[0]
                extracted = Path(tmpdir) / Path(target_name).name
                extracted.write_bytes(zf.read(target_name))
            gdf = gpd.read_file(extracted)
    else:
        gdf = gpd.read_file(path)

    if gdf.empty or gdf.geometry.isna().all():
        raise ValueError(f"No valid geometries found in vector file: {path}")

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[gdf.geometry.is_valid].copy()
    if gdf.empty:
        raise ValueError(
            f"No valid polygon geometries found in vector file: {path}"
        )
    return gdf


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def _cache_key(
    path: str,
    gdf,
    start_year: int,
    end_year: int,
    variable_key: str,
) -> str:
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


def _cache_paths(
    cache_dir: str | Path,
    key: str,
    *,
    prefix: str = "era5_monthly",
) -> tuple[Path, Path]:
    base = Path(cache_dir)
    return base / f"{prefix}_{key}.parquet", base / f"{prefix}_{key}.json"


def _read_cache(
    cache_dir: str | Path | None,
    key: str,
    *,
    prefix: str = "era5_monthly",
) -> pd.DataFrame | None:
    if cache_dir is None:
        return None
    data_path, _ = _cache_paths(cache_dir, key, prefix=prefix)
    if data_path.exists():
        logger.info("ERA5 fetch cache hit: %s", data_path)
        return pd.read_parquet(data_path)
    return None


def _write_cache(
    cache_dir: str | Path | None,
    key: str,
    df: pd.DataFrame,
    meta: dict,
    *,
    prefix: str = "era5_monthly",
) -> None:
    if cache_dir is None:
        return
    base = Path(cache_dir)
    base.mkdir(parents=True, exist_ok=True)
    data_path, meta_path = _cache_paths(base, key, prefix=prefix)
    df.to_parquet(data_path, index=False)
    meta_path.write_text(
        json.dumps(meta, default=str, indent=2), encoding="utf-8"
    )
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
        Registry key or an ``ERA5Variable``.
    cache_dir : str | Path | None
        If given, results are cached locally as parquet keyed by inputs hash.
    spatial_chunk : int
        Dask chunk size along latitude/longitude.
    """
    import xarray as xr

    var = (
        variable
        if isinstance(variable, ERA5Variable)
        else get_era5_variable(variable)
    )

    # ---- cache lookup
    key = _cache_key(path, gdf, start_year, end_year, var.key)
    cached = _read_cache(cache_dir, key, prefix="era5_monthly")
    if cached is not None:
        return cached

    # ---- open lazily
    if (
        str(path).startswith("gs://")
        and importlib.util.find_spec("gcsfs") is None
    ):
        raise ImportError(
            "gcsfs is required to read Google Cloud Storage ERA5 Zarr stores. "
            "Install the fetch extra with: pip install -e \".[fetch]\""
        )
    ds = xr.open_zarr(
        path, chunks={"time": 744}, storage_options={"token": "anon"}
    )
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
                f"Variable '{var.era5_name}' not found; "
                f"available: {list(ds.data_vars)}"
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
    mask = rasterize_to_xarray_grid(
        gdf, ds_small, lon_name="longitude", lat_name="latitude"
    )

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
        except ImportError:
            values = catchment_series.compute()
        else:
            with ProgressBar():
                values = catchment_series.compute()
    else:
        values = catchment_series.compute()

    df = values.to_pandas().rename(var.out_column).to_frame().reset_index()
    df["Date"] = df["time"].dt.strftime("%Y-%m-%d")
    df["Year"] = df["time"].dt.year.astype(int)
    df["Month"] = df["time"].dt.month.astype(int)
    df.drop(columns=["time"], inplace=True)

    # unit conversion
    df[var.out_column] = (
        df[var.out_column] * var.unit_factor + var.unit_offset
    ).round(2)

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
        prefix="era5_monthly",
    )
    return out


def _coord_name(ds, candidates: tuple[str, ...], label: str) -> str:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise KeyError(
        f"Could not locate {label} coordinate. Checked: {candidates}"
    )


def _silo_rain_var_name(ds) -> str:
    preferred = ("monthly_rain", "Rainfall_mm", "rain", "rainfall")
    for name in preferred:
        if name in ds.data_vars:
            return name
    if len(ds.data_vars) == 1:
        return list(ds.data_vars)[0]
    raise KeyError(
        "Could not infer SILO rainfall variable; "
        f"available: {list(ds.data_vars)}"
    )


def _silo_year_dataset_path(
    year: int,
    base_url: str,
    cache_dir: str | Path | None,
) -> tuple[Path, bool]:
    """Return a local NetCDF path for a SILO annual monthly-rain file.

    Returns ``(path, is_temporary)``. HTTP/S sources are downloaded because
    raw NetCDF-over-HTTPS support varies by xarray backend.
    """
    filename = f"{year}.monthly_rain.nc"
    source = str(base_url).rstrip("/")

    if source.startswith(("http://", "https://")):
        if cache_dir is not None:
            base = Path(cache_dir) / "silo_netcdf"
            base.mkdir(parents=True, exist_ok=True)
            target = base / filename
            if not target.exists():
                urllib.request.urlretrieve(f"{source}/{filename}", target)
            return target, False

        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".monthly_rain.nc"
        )
        tmp_path = Path(tmp.name)
        tmp.close()
        urllib.request.urlretrieve(f"{source}/{filename}", tmp_path)
        return tmp_path, True

    return Path(source) / filename, False


def get_monthly_silo_rainfall(
    gdf,
    start_year: int,
    end_year: int,
    *,
    base_url: str = SILO_MONTHLY_RAIN_BASE_URL,
    cache_dir: str | Path | None = None,
    spatial_chunk: int = 50,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Fetch SILO gridded monthly rainfall averaged over an AOI polygon.

    Downloads SILO annual monthly-rain NetCDF files hosted on AWS, masks each to
    the polygon, and returns the spatial mean per month.

    Parameters
    ----------
    gdf:
        A GeoDataFrame defining the area of interest (any CRS; reprojected to
        EPSG:4326 internally). Use :func:`load_vector` to load one from a file.
    start_year, end_year:
        Inclusive range of calendar years to fetch.
    base_url:
        Base URL of the SILO monthly-rain NetCDF store.
    cache_dir:
        Optional directory for caching the assembled monthly series as Parquet.
    spatial_chunk:
        Dask chunk size (grid cells) along each spatial dimension.
    show_progress:
        Show a dask progress bar during compute when available.

    Returns
    -------
    pandas.DataFrame
        Tidy monthly frame with columns ``Date``, ``Year``, ``Month`` and
        ``Rainfall_mm``, ready to pass to :func:`delineate_monthly_dataframe`.
    """
    import xarray as xr

    key = _cache_key(base_url, gdf, start_year, end_year, "silo_monthly_rain")
    cached = _read_cache(cache_dir, key, prefix="silo_monthly")
    if cached is not None:
        return cached

    gdf = gdf.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = gdf.total_bounds

    monthly_frames: list[pd.DataFrame] = []
    years = range(int(start_year), int(end_year) + 1)

    for year in years:
        nc_path, is_temporary = _silo_year_dataset_path(
            year, base_url, cache_dir
        )
        ds = xr.open_dataset(nc_path)

        lon_name = _coord_name(ds, ("longitude", "lon", "x"), "longitude")
        lat_name = _coord_name(ds, ("latitude", "lat", "y"), "latitude")
        time_name = _coord_name(ds, ("time",), "time")
        var_name = _silo_rain_var_name(ds)

        lon_pair = _wrap_lon_to_ds_range([minx, maxx], ds[lon_name].values)
        lon_sel = _ordered_slice(ds[lon_name].values, lon_pair[0], lon_pair[1])
        lat_sel = _ordered_slice(ds[lat_name].values, maxy, miny)
        ds_small = ds.sel({lon_name: lon_sel, lat_name: lat_sel}).chunk(
            {time_name: 12, lat_name: spatial_chunk, lon_name: spatial_chunk}
        )

        mask = rasterize_to_xarray_grid(
            gdf, ds_small, lon_name=lon_name, lat_name=lat_name
        )
        da = ds_small[var_name].where(mask)
        catchment_series = da.mean((lat_name, lon_name), skipna=True)

        if show_progress:
            try:
                from dask.diagnostics import ProgressBar
            except ImportError:
                values = catchment_series.compute()
            else:
                with ProgressBar():
                    values = catchment_series.compute()
        else:
            values = catchment_series.compute()

        df = values.to_pandas().rename("Rainfall_mm").to_frame().reset_index()
        df["Date"] = pd.to_datetime(df[time_name]).dt.strftime("%Y-%m-%d")
        df["Year"] = pd.to_datetime(df[time_name]).dt.year.astype(int)
        df["Month"] = pd.to_datetime(df[time_name]).dt.month.astype(int)
        df = df[["Date", "Year", "Month", "Rainfall_mm"]]
        monthly_frames.append(df)
        ds.close()
        if is_temporary:
            nc_path.unlink(missing_ok=True)

    out = (
        pd.concat(monthly_frames, ignore_index=True)
        .sort_values("Date")
        .reset_index(drop=True)
    )

    _write_cache(
        cache_dir,
        key,
        out,
        meta={
            "base_url": base_url,
            "start_year": int(start_year),
            "end_year": int(end_year),
            "variable": "monthly_rain",
            "unit": "mm",
        },
        prefix="silo_monthly",
    )
    return out


def get_monthly_total_precip(
    path,
    gdf,
    start_year,
    end_year,
    var="total_precipitation",
    cache_dir=None,
    spatial_chunk=50,
    show_progress=True,
):
    """Backward-compatible shim for the original rainfall fetch helper."""
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
