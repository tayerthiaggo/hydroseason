"""SILO gridded rainfall as ancillary context for a water-extent record.

Rainfall never feeds ``assess_water_regime`` or hydrological-year detection
for the extent record itself -- it is compared *against* their output (see
``_regime_compare``). Folding it into the primary analysis would forfeit the
one thing that analysis is for: reporting what the satellite actually
observed, independent of a rainfall model's assumptions.

Ported from ``legacy/rainfall:hydroseason/fetch.py``
(``get_monthly_silo_rainfall``), narrowed to the one path this repo uses --
SILO's public monthly-rain NetCDF store on S3, one file per calendar year --
and changed from a full-file download to a lazy, byte-range read: each
catchment AOI covers roughly 1% of the national grid (SILO covers all of
Australia at 0.05 degree resolution), so downloading the ~14 MB national file
per year to keep 1% of it wastes the other 99% of every transfer, repeated for
every catchment. SILO's files are HDF5-based NetCDF4 served from S3, which
supports HTTP byte-range requests, so ``s3fs`` + the ``h5netcdf`` engine open
each file lazily and only the AOI's slice of bytes is ever transferred.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SILO_S3_BUCKET = "silo-open-data"
SILO_MONTHLY_RAIN_PREFIX = "Official/annual/monthly_rain"

_RAIN_VAR_CANDIDATES = ("monthly_rain", "Rainfall_mm", "rain", "rainfall")


def monthly_rainfall_to_frame(
    rainfall: pd.Series | pd.DataFrame,
    *,
    value_col: str = "rainfall_mm",
    date_col: str | None = None,
) -> pd.DataFrame:
    """Adapt a monthly rainfall series to the shared ``extent_pct`` input shape.

    ``assess_water_regime`` and ``extract_water_events`` are both written
    against a frame with an ``extent_pct`` column; rather than duplicate their
    logic for a second physical quantity, present rainfall through the same
    column name so one implementation judges both series. ``invalid_pct`` is
    set to 0 throughout -- SILO's gridded product has no missing-month concept
    at monthly resolution.
    """
    if isinstance(rainfall, pd.Series):
        frame = rainfall.rename("extent_pct").to_frame()
    else:
        if value_col not in rainfall.columns:
            raise KeyError(
                f"value_col={value_col!r} not a column of the rainfall frame; "
                f"available: {list(rainfall.columns)}"
            )
        source = rainfall.copy()
        if date_col is not None:
            source = source.set_index(pd.to_datetime(source[date_col]))
        frame = source[[value_col]].rename(columns={value_col: "extent_pct"})
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index)

    # The shared regime/event machinery enforces extent_pct in [0, 100] as a
    # domain invariant of the water-extent side (a percentage of pixels), and
    # rainfall in mm routinely exceeds 100 in the wet season -- rescaling here
    # rather than relaxing that bound. assess_water_regime's diagnostics
    # (amplitude SNR, peak-phase spread) are ratios of a series to itself, so
    # a monotonic linear rescale changes no verdict; only the column's literal
    # units change, from mm to "% of this record's own peak month".
    raw = pd.to_numeric(frame["extent_pct"], errors="coerce")
    peak = float(raw.max(skipna=True)) if raw.notna().any() else 0.0
    if peak > 0:
        # np.clip guards float rounding at the boundary (100*raw/peak can land
        # a hair above 100.0 when raw == peak), not a substantive adjustment.
        frame["extent_pct"] = np.clip(100.0 * raw / peak, 0.0, 100.0)
    else:
        frame["extent_pct"] = raw.fillna(0.0)
    frame["invalid_pct"] = 0.0
    return frame.sort_index()


def normalise_monthly_rainfall(
    rainfall: pd.DataFrame,
    *,
    date_col: str = "date",
    value_col: str = "rainfall_mm",
) -> pd.DataFrame:
    """Normalise a tidy ``date``/``rainfall_mm`` frame to a monthly index.

    Dates are floored to the first of their calendar month so a record
    dated anywhere in a month aligns with the extent record's own
    month-start index (see ``align_monthly_rainfall``). Duplicate months
    and a malformed input shape are rejected outright rather than silently
    aggregated or coerced -- ambiguity here should surface to the caller,
    not be resolved by a guess.
    """
    missing = {date_col, value_col}.difference(rainfall.columns)
    if missing:
        raise ValueError(
            f"Rainfall input requires {date_col!r} and {value_col!r} columns; missing: {sorted(missing)}."
        )
    out = rainfall[[date_col, value_col]].copy()
    out.index = pd.DatetimeIndex(
        pd.to_datetime(out.pop(date_col), errors="raise")
    ).to_period("M").to_timestamp()
    if out.index.has_duplicates:
        duplicates = sorted(out.index[out.index.duplicated()].strftime("%Y-%m").unique())
        raise ValueError(f"Rainfall input contains duplicate months: {duplicates}.")
    out[value_col] = pd.to_numeric(out[value_col], errors="raise")
    out = out.rename(columns={value_col: "rainfall_mm"}).sort_index()
    if out.empty:
        raise ValueError("Rainfall input is empty.")
    return out


def load_monthly_rainfall_csv(path: str | Path) -> pd.DataFrame:
    """Load a ``date``/``rainfall_mm`` CSV and normalise it to a monthly index.

    The CSV format is deliberately narrow -- two columns, ``date`` and
    ``rainfall_mm`` -- matching what ``get_monthly_silo_rainfall`` produces
    and what ``normalise_monthly_rainfall`` accepts, so a user-supplied file
    and a SILO fetch are interchangeable ancillary rainfall sources.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Rainfall CSV not found: {path}")
    return normalise_monthly_rainfall(pd.read_csv(path))


def align_monthly_rainfall(
    rainfall: pd.DataFrame,
    extent_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Reindex a normalised rainfall frame onto an extent record's month axis.

    Months present in ``extent_index`` but absent from ``rainfall`` become
    NaN rows rather than being dropped or interpolated -- callers decide how
    to treat gaps, this function only aligns the axes.
    """
    axis = pd.DatetimeIndex(extent_index).to_period("M").to_timestamp()
    if axis.has_duplicates:
        raise ValueError("Extent month axis contains duplicate months.")
    return rainfall.reindex(axis)


def _silo_rain_var_name(dataset) -> str:
    for name in _RAIN_VAR_CANDIDATES:
        if name in dataset.data_vars:
            return name
    if len(dataset.data_vars) == 1:
        return list(dataset.data_vars)[0]
    raise KeyError(f"Could not infer SILO rainfall variable; available: {list(dataset.data_vars)}")


def _lat_lon_slice(lat_values: np.ndarray, lon_values: np.ndarray, bounds) -> dict:
    """A ``.sel`` slice dict that is correct regardless of coordinate order.

    SILO's grid stores latitude **ascending** (-44 to -10, south to north),
    the opposite of the north-first order common in GeoTIFF-derived rasters.
    A slice written assuming descending order silently returns an empty
    selection on this grid rather than raising -- xarray's ``.sel`` treats an
    empty match as valid, so the failure only surfaces later, far from its
    cause. Reading each axis's own direction from its coordinate values avoids
    hardcoding an order that only holds for some sources.
    """
    minx, miny, maxx, maxy = bounds
    lat_ascending = len(lat_values) < 2 or lat_values[1] >= lat_values[0]
    lon_ascending = len(lon_values) < 2 or lon_values[1] >= lon_values[0]
    return {
        "lat": slice(miny - 0.1, maxy + 0.1) if lat_ascending else slice(maxy + 0.1, miny - 0.1),
        "lon": slice(minx - 0.1, maxx + 0.1) if lon_ascending else slice(maxx + 0.1, minx - 0.1),
    }


def get_monthly_silo_rainfall(
    gdf,
    start_year: int,
    end_year: int,
    *,
    bucket: str = SILO_S3_BUCKET,
    prefix: str = SILO_MONTHLY_RAIN_PREFIX,
) -> pd.DataFrame:
    """Fetch SILO gridded monthly rainfall averaged over an AOI polygon.

    Opens one SILO annual monthly-rain NetCDF file per year lazily from the
    public AWS store (``anon=True`` S3 access; each file is HDF5-based and
    served with byte-range support, so slicing to the AOI's bounding box
    before reading transfers only that slice's bytes, not the national grid),
    masks the clipped slice to ``gdf`` (any CRS; reprojected to EPSG:4326
    internally, matching SILO's native grid), and returns the spatial mean per
    month as a tidy frame with columns ``date`` and ``rainfall_mm``.

    Network access required. Nothing is cached to disk -- a repeated call
    re-opens the remote files, which is cheap because each open only reads the
    AOI's slice (see module docstring), not the ~14 MB/year national file.
    """
    import s3fs
    import xarray as xr
    from rasterio.features import geometry_mask

    aoi = gdf.to_crs(4326) if gdf.crs is not None else gdf
    bounds = tuple(aoi.total_bounds)

    fs = s3fs.S3FileSystem(anon=True)
    rows = []
    for year in range(start_year, end_year + 1):
        key = f"{bucket}/{prefix}/{year}.monthly_rain.nc"
        try:
            handle = fs.open(key, "rb")
        except FileNotFoundError:
            continue
        with handle:
            with xr.open_dataset(handle, engine="h5netcdf") as dataset:
                var = _silo_rain_var_name(dataset)
                lat_name = "lat" if "lat" in dataset.coords else "latitude"
                lon_name = "lon" if "lon" in dataset.coords else "longitude"
                lat_values = dataset[lat_name].values
                lon_values = dataset[lon_name].values
                indexer = _lat_lon_slice(lat_values, lon_values, bounds)
                clipped = dataset[var].sel({lat_name: indexer["lat"], lon_name: indexer["lon"]})
                if clipped.sizes.get(lat_name, 0) == 0 or clipped.sizes.get(lon_name, 0) == 0:
                    raise ValueError(
                        f"AOI bounds {bounds} do not overlap the SILO grid for {year}; "
                        "check the boundary's CRS and extent."
                    )
                transform = _affine_from_coords(
                    clipped[lon_name].values, clipped[lat_name].values
                )
                mask = geometry_mask(
                    list(aoi.geometry),
                    out_shape=(clipped.sizes[lat_name], clipped.sizes[lon_name]),
                    transform=transform,
                    invert=True,
                    all_touched=True,
                )
                masked = clipped.where(xr.DataArray(mask, dims=(lat_name, lon_name)))
                monthly_mean = masked.mean(dim=(lat_name, lon_name), skipna=True)
                values = monthly_mean.values
                times = (
                    pd.to_datetime(clipped["time"].values)
                    if "time" in clipped.coords
                    else pd.date_range(f"{year}-01-01", periods=len(values), freq="MS")
                )
                for stamp, value in zip(times, values):
                    rows.append({"date": pd.Timestamp(stamp), "rainfall_mm": float(value)})

    if not rows:
        return pd.DataFrame(columns=["date", "rainfall_mm"])
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _affine_from_coords(lon_values: np.ndarray, lat_values: np.ndarray):
    """Build an affine transform for a regular lon/lat grid, north-up."""
    from affine import Affine

    lon_step = float(lon_values[1] - lon_values[0]) if len(lon_values) > 1 else 0.05
    lat_step = float(lat_values[1] - lat_values[0]) if len(lat_values) > 1 else -0.05
    origin_x = float(lon_values[0]) - lon_step / 2.0
    origin_y = float(lat_values[0]) - lat_step / 2.0
    return Affine(lon_step, 0.0, origin_x, 0.0, lat_step, origin_y)


__all__ = [
    "SILO_S3_BUCKET",
    "SILO_MONTHLY_RAIN_PREFIX",
    "align_monthly_rainfall",
    "get_monthly_silo_rainfall",
    "load_monthly_rainfall_csv",
    "monthly_rainfall_to_frame",
    "normalise_monthly_rainfall",
]
