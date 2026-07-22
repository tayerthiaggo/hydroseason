"""Geospatial AOI and raster mask loaders.

Raster support is adapted from WaterMask-TSFill commit
90983c1559e7c08951096bbf196c0daedead6b4f.  All geospatial imports
(geopandas, rioxarray, xarray, pystac_client, odc.stac, rasterio, affine,
pyproj) stay inside function bodies so importing this module never requires
those packages -- only calling a function that needs one does.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import pandas as pd

from hydroseason._io_extent import complete_monthly_axis

MaskEncoding = Literal["canonical", "binary", "wofs"]


class AOIRasterizationError(RuntimeError):
    """AOI clipping or rasterization could not be applied safely."""


class GeoreferencingError(ValueError):
    """Raster lacks usable CRS or affine georeferencing."""


class IrregularGridError(GeoreferencingError):
    """Raster x/y coordinates cannot define an affine transform."""


def load_aoi(aoi, *, to_crs: str | int | None = None):
    """Load a non-empty GeoDataFrame from vector path or GeoDataFrame."""
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("load_aoi requires the raster extra (geopandas).") from exc

    if isinstance(aoi, gpd.GeoDataFrame):
        result = aoi.copy()
    elif isinstance(aoi, (str, os.PathLike)):
        path = Path(aoi)
        if not path.exists():
            raise FileNotFoundError(f"AOI file not found: {path}")
        result = gpd.read_file(path)
    else:
        raise TypeError("aoi must be a vector path or geopandas.GeoDataFrame.")
    if result.empty:
        raise ValueError("AOI GeoDataFrame is empty.")
    result = result[~result.geometry.isna() & ~result.geometry.is_empty].copy()
    if result.empty:
        raise ValueError("AOI has no valid non-empty geometries.")
    if not result.geometry.is_valid.all():
        raise ValueError(
            "AOI contains geometrically invalid (e.g. self-intersecting) "
            "geometry; fix or repair the AOI before use."
        )
    if to_crs is not None:
        result = result.to_crs(_crs_value(to_crs))
    return result


def load_monthly_masks(
    input_dir: str | os.PathLike[str],
    start_date: str,
    end_date: str,
    *,
    aoi=None,
    encoding: MaskEncoding | None = None,
    classifier: Callable | None = None,
    chunk_x: int = 512,
    chunk_y: int = 512,
    time_chunk: int = 24,
    majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Load AOI-clipped TIFF masks as lazy canonical time/y/x data.

    Explicit ``encoding`` prevents ambiguous uint8 masks from being mistaken
    for raw WOfS flags. Canonical values: dry 0, water 1, invalid -1, outside -2.
    """
    if aoi is None:
        raise ValueError("AOI is required for raster mask loading.")
    _validate_classifier(encoding, classifier)
    try:
        import rioxarray as rxr
        import xarray as xr
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("load_monthly_masks requires the raster extra.") from exc

    files = sorted(Path(input_dir).glob("water_*.tif"))
    if not files:
        raise FileNotFoundError(f"No water_*.tif files found in {input_dir}")
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    grouped: dict[pd.Timestamp, list] = {}
    for path in files:
        timestamp = _parse_date_from_name(path)
        if start <= timestamp <= end:
            arr = rxr.open_rasterio(path, chunks={"x": chunk_x, "y": chunk_y}).squeeze(drop=True)
            grouped.setdefault(timestamp.to_period("M").to_timestamp(), []).append(_classify(arr, encoding, classifier))
    if not grouped:
        raise FileNotFoundError(f"No mask files fall within {start_date} to {end_date}.")

    aoi_gdf = load_aoi(aoi)
    masks, dates, reference = [], [], None
    for month, observations in sorted(grouped.items()):
        mask = observations[0] if len(observations) == 1 else _combine_observations(xr.concat(observations, dim="time"), majority)
        mask = _clip_to_aoi(mask, aoi_gdf)
        if reference is not None:
            _assert_compatible_georef(reference, mask, context=f"month {month:%Y-%m}")
        reference = mask if reference is None else reference
        masks.append(mask)
        dates.append(month)
    return complete_monthly_axis(
        xr.concat(masks, dim="time").assign_coords(time=("time", dates)), start_date, end_date,
        duplicate_month_policy=duplicate_month_policy,
    ).chunk({"time": min(time_chunk, len(dates)), "x": chunk_x, "y": chunk_y})


def load_monthly_masks_zarr(
    zarr_path: str | os.PathLike[str], start_date: str, end_date: str, *, chunk_x: int = 512, chunk_y: int = 512,
    time_chunk: int = 24, duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Open an already-canonical, already-AOI-clipped Zarr mask cube lazily."""
    try:
        import xarray as xr
    except ImportError as exc:  # pragma: no cover
        raise ImportError("load_monthly_masks_zarr requires the raster extra.") from exc
    dataset = xr.open_zarr(zarr_path, chunks={"x": chunk_x, "y": chunk_y}, mask_and_scale=False)
    if "water_mask" not in dataset:
        raise ValueError("Zarr store must contain a 'water_mask' variable.")
    masks = dataset["water_mask"].sel(time=slice(pd.Timestamp(start_date), pd.Timestamp(end_date)))
    masks = complete_monthly_axis(masks, start_date, end_date, duplicate_month_policy=duplicate_month_policy)
    return masks.chunk({"time": min(time_chunk, masks.sizes["time"]), "x": chunk_x, "y": chunk_y})


def load_wofs_from_stac(
    stac_url: str, collection: str, aoi, start_date: str, end_date: str, *, crs: int | str | None = 3577,
    chunk_x: int = 512, chunk_y: int = 512, time_chunk: int = 24, majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise", resolution: float | None = None,
):
    """Load WOfS observations in annual batches, compose monthly, and clip to the AOI.

    A calendar year is sent to ``odc.stac.stac_load`` at once.  The returned
    lazy cube is then split into monthly composites, avoiding the substantial
    graph/setup overhead of one loader call per month while retaining the same
    monthly result.
    """
    if aoi is None:
        raise ValueError("AOI is required for WOfS/STAC loading.")
    try:
        import xarray as xr
        import pystac_client
        import odc.stac
        import rioxarray  # noqa: F401  (registers the .rio accessor used by _clip_to_aoi)
    except ImportError as exc:  # pragma: no cover
        raise ImportError("load_wofs_from_stac requires the stac extra.") from exc
    # DEA's public S3 bucket (dea-public-data) rejects unsigned GDAL/rasterio
    # reads unless explicitly told not to sign requests; without this, every
    # lazy dask read of the returned cube fails with CPLE_AWSInvalidCredentialsError.
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    # Resolve _clip_to_aoi off the hydroseason.io facade at call time so
    # tests that patch hydroseason.io._clip_to_aoi take effect here.
    import hydroseason.io as _io

    aoi_gdf = load_aoi(aoi)
    try:
        aoi_4326 = aoi_gdf.to_crs("EPSG:4326")
        client = pystac_client.Client.open(stac_url)
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        items = _collect_stac_items(
            client,
            collections=[collection],
            datetime=f"{start:%Y-%m-%d}/{end:%Y-%m-%d}",
            bbox=list(aoi_4326.total_bounds),
        )
    except Exception as exc:
        raise AOIRasterizationError("STAC AOI query failed; refusing to load an unclipped raster.") from exc
    if not items:
        raise ValueError("No STAC items found for requested AOI and date range.")
    groups: dict[pd.Timestamp, list] = {}
    for item in items:
        date = pd.Timestamp(item.properties.get("datetime") or item.properties.get("start_datetime"))
        if date.tzinfo is not None:
            date = date.tz_convert(None)
        groups.setdefault(date.to_period("M").to_timestamp(), []).append(item)
    annual_groups: dict[int, list[tuple[pd.Timestamp, list]]] = {}
    for month, month_items in sorted(groups.items()):
        annual_groups.setdefault(month.year, []).append((month, month_items))

    target = aoi_gdf.to_crs(_crs_value(crs)) if crs is not None else aoi_gdf
    masks, dates, reference = [], [], None
    for year, year_groups in sorted(annual_groups.items()):
        try:
            year_items = [item for _month, month_items in year_groups for item in month_items]
            ds = odc.stac.stac_load(year_items, bands=["water"], chunks={"x": chunk_x, "y": chunk_y}, geopolygon=target.geometry, **({"crs": _crs_value(crs)} if crs is not None else {}), **({"resolution": resolution, "resampling": "mode"} if resolution is not None else {}))
            classified = _classify(ds["water"], "wofs", None)
            loaded_months = pd.DatetimeIndex(classified["time"].values).to_period("M")
        except AOIRasterizationError:
            raise
        except Exception as exc:
            raise AOIRasterizationError(f"STAC load failed for batch year {year}.") from exc

        for month, _month_items in year_groups:
            try:
                indices = np.flatnonzero(loaded_months == month.to_period("M"))
                if not len(indices):
                    raise ValueError(f"loaded STAC batch has no observations for {month:%Y-%m}")
                observations = classified.isel(time=indices)
                mask = _combine_observations(observations, majority)
                mask = _io._clip_to_aoi(mask, target)
            except AOIRasterizationError:
                raise
            except Exception as exc:
                raise AOIRasterizationError(
                    f"AOI clip failed; refusing to process STAC month {month:%Y-%m}."
                ) from exc
            if reference is not None:
                _assert_compatible_georef(reference, mask, context=f"month {month:%Y-%m}")
            reference = mask if reference is None else reference
            masks.append(mask)
            dates.append(month)

    completed = complete_monthly_axis(
        xr.concat(masks, dim="time").assign_coords(time=("time", dates)),
        start_date,
        end_date,
        duplicate_month_policy=duplicate_month_policy,
    )
    return completed.chunk({"time": min(time_chunk, completed.sizes["time"]), "x": chunk_x, "y": chunk_y})


def _collect_stac_items(client, *, max_attempts: int = 4, **search_kwargs):
    delay = 2.0
    for attempt in range(1, max_attempts + 1):
        try:
            return list(client.search(**search_kwargs).items())
        except Exception as exc:
            if attempt == max_attempts or not _is_transient_stac_error(exc):
                raise
            time.sleep(delay)
            delay *= 2.0
    raise RuntimeError("unreachable")


def _is_transient_stac_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    if status_code in {500, 502, 503, 504}:
        return True
    text = str(exc).lower()
    return any(token in text for token in ("500", "502", "503", "504", "gateway", "timeout", "temporarily unavailable"))


def _validate_classifier(encoding, classifier):
    if classifier is not None and not callable(classifier):
        raise TypeError("classifier must be callable.")
    if classifier is None and encoding not in {"canonical", "binary", "wofs"}:
        raise ValueError("Specify encoding='canonical', 'binary', or 'wofs', or provide classifier=callable.")
    if classifier is not None and encoding is not None:
        raise ValueError("Pass either encoding or classifier, not both.")


def _classify(arr, encoding, classifier):
    import xarray as xr

    if classifier is not None:
        result = classifier(arr)
        if not hasattr(result, "dims"):
            raise TypeError("classifier must return an xarray.DataArray.")
        in_domain = result.isin([-2, -1, 0, 1])
        canonical = xr.where(in_domain, result, np.int8(-1)).astype(np.int8)
        return _preserve_georef(canonical, arr)
    if encoding == "canonical":
        in_domain = arr.isin([-2, -1, 0, 1])
        canonical = xr.where(in_domain, arr, np.int8(-1)).astype(np.int8)
        return _preserve_georef(canonical, arr)
    if encoding == "binary":
        return _preserve_georef(xr.where(arr == 1, np.int8(1), xr.where(arr == 0, np.int8(0), np.int8(-1))).astype(np.int8), arr)
    raw = arr.fillna(1).astype(np.uint16)
    invalid = ((raw & np.uint16(1)) != 0) | arr.isnull()
    return _preserve_georef(xr.where(invalid, np.int8(-1), xr.where(arr == 128, np.int8(1), xr.where(arr == 0, np.int8(0), np.int8(-1)))).astype(np.int8), arr)


def _preserve_georef(result, source):
    """Restore rioxarray metadata dropped by xarray classification operations."""
    try:
        result = result.rio.set_spatial_dims(x_dim="x", y_dim="y")
        crs = source.rio.crs
        if crs is not None:
            result = result.rio.write_crs(crs)
        return result.rio.write_transform(source.rio.transform())
    except Exception:
        return result


def _combine_observations(series, majority):
    water, dry, invalid = (series == 1).sum("time"), (series == 0).sum("time"), (series == -1).sum("time")
    water_wins = (water > 0) & ((water > dry) if majority else True)
    import xarray as xr

    combined = xr.where(water_wins, np.int8(1), xr.where(dry > 0, np.int8(0), xr.where(invalid > 0, np.int8(-1), np.int8(-2)))).astype(np.int8)
    return _preserve_georef(combined, series)


def _clip_to_aoi(mask, aoi_gdf):
    outside_value = np.int8(-2)
    try:
        mask = mask.rio.set_spatial_dims(x_dim="x", y_dim="y")
        crs = _resolve_raster_crs(mask)
        if crs is None:
            raise GeoreferencingError("raster is missing CRS")
        # Canonical values are already int8, so an unset nodata makes
        # rio.clip's outside-AOI fill land on NaN, which casts straight to
        # 0 (dry) instead of a real sentinel. Write nodata=-2 first so
        # clip's fill value is representable and outside pixels survive as
        # outside (-2), not dry.
        mask = mask.rio.write_nodata(outside_value)
        clipped = mask.rio.clip(aoi_gdf.to_crs(crs).geometry, drop=False, all_touched=True)
    except Exception as exc:
        raise AOIRasterizationError("AOI clip failed; refusing to process an unclipped raster.") from exc
    clipped = clipped.fillna(outside_value).astype(np.int8)
    return mark_in_aoi_nodata_as_invalid(clipped, aoi_gdf)


def mark_in_aoi_nodata_as_invalid(mask, aoi, *, outside_value: int = -2, invalid_value: int = -1):
    aoi_gdf = load_aoi(aoi)
    crs = _resolve_raster_crs(mask)
    if crs is None:
        raise AOIRasterizationError("AOI masking failed: raster is missing CRS.")
    try:
        inside = _inside_aoi_mask_like(mask, aoi_gdf.to_crs(crs))
    except Exception as exc:
        if isinstance(exc, AOIRasterizationError):
            raise
        raise AOIRasterizationError("AOI masking failed; refusing unclipped raster.") from exc
    return mask.where(~((mask == outside_value) & inside), np.int8(invalid_value)).astype(np.int8)


def _inside_aoi_mask_like(template, aoi_gdf):
    try:
        from rasterio.features import geometry_mask
        import xarray as xr

        transform = _resolve_raster_transform(template)
        inside = geometry_mask(list(aoi_gdf.geometry), out_shape=(template.sizes["y"], template.sizes["x"]), transform=transform, invert=True, all_touched=True)
        return xr.DataArray(inside, dims=("y", "x"), coords={"y": template.y, "x": template.x})
    except Exception as exc:
        raise AOIRasterizationError("AOI rasterization failed; refusing unclipped raster.") from exc


def _resolve_raster_crs(da):
    try:
        return da.rio.crs
    except Exception:
        return None


def _resolve_raster_transform(da):
    try:
        transform = da.rio.transform()
    except Exception:
        transform = None
    return _spatial_transform_from_xy(da) if transform is None or _is_identity_transform(transform) else transform


def _spatial_transform_from_xy(da):
    from affine import Affine

    x, y = np.asarray(da.x.values, dtype=float), np.asarray(da.y.values, dtype=float)
    if len(x) < 2 or len(y) < 2:
        raise GeoreferencingError("x/y axes need at least two coordinates.")
    dx, dy = np.diff(x), np.diff(y)
    if not np.allclose(dx, dx[0]) or not np.allclose(dy, dy[0]):
        raise IrregularGridError("x/y coordinate spacing is irregular.")
    return Affine(dx[0], 0, x[0] - dx[0] / 2, 0, dy[0], y[0] - dy[0] / 2)


def _is_identity_transform(transform):
    from affine import Affine

    return tuple(transform)[:6] == tuple(Affine.identity())[:6]


def _assert_compatible_georef(reference, other, *, context):
    try:
        same = _resolve_raster_crs(reference) == _resolve_raster_crs(other) and _resolve_raster_transform(reference) == _resolve_raster_transform(other) and reference.sizes["x"] == other.sizes["x"] and reference.sizes["y"] == other.sizes["y"]
    except Exception as exc:
        raise GeoreferencingError(f"{context}: cannot validate georeferencing.") from exc
    if not same:
        raise GeoreferencingError(f"{context}: raster georeferencing mismatch.")


def _parse_date_from_name(path: Path) -> pd.Timestamp:
    parts = path.stem.split("_")
    if len(parts) < 4:
        raise ValueError(f"Unexpected filename format: {path.name}")
    return pd.Timestamp(f"{parts[-3]}-{parts[-2]}-{parts[-1]}")


def _crs_value(crs):
    return f"EPSG:{crs}" if isinstance(crs, int) else crs


__all__ = [
    "load_aoi", "load_monthly_masks", "load_monthly_masks_zarr", "load_wofs_from_stac",
    "mark_in_aoi_nodata_as_invalid", "AOIRasterizationError", "GeoreferencingError", "IrregularGridError",
]
