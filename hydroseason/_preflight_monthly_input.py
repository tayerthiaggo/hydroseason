from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ._preflight_types import (
    MonthlyObservationCapabilities,
    MonthlyObservationRecord,
)
from ._state_input import prepare_monthly_extent
from .hydro_year import monthly_water_extent
from .io import (
    complete_monthly_axis,
    load_aoi,
    open_completed_extent_counts,
    open_completed_mask_cache,
)

_XARRAY_UNRESOLVED = object()
_xarray_module: Any = _XARRAY_UNRESOLVED


def _xarray() -> Any:
    """Return ``xarray``, or ``None`` when the raster extra is absent.

    Imported on first use rather than at module import: ``xarray`` costs
    roughly a quarter-second and reaches every ``import hydroseason``, while
    only the raster-backed monthly inputs below ever need it.
    """
    global _xarray_module
    if _xarray_module is _XARRAY_UNRESOLVED:
        try:
            import xarray
        except ImportError:
            _xarray_module = None
        else:
            _xarray_module = xarray
    return _xarray_module

try:  # pragma: no cover - optional dependency boundary
    from ._io_geo import _resolve_aoi_inside_mask, _resolve_raster_crs
except ImportError:  # pragma: no cover
    _resolve_aoi_inside_mask = None
    _resolve_raster_crs = None

try:  # pragma: no cover - optional dependency boundary
    from ._io_wofs_zarr import WOfSCacheHandle, verify_cache_analysis_mask
except ImportError:  # pragma: no cover
    WOfSCacheHandle = None
    verify_cache_analysis_mask = None


_COUNT_COLUMNS = ("n_water", "n_valid", "n_invalid", "n_aoi")
_RAW_COUNT_VARIABLES = ("n_clear_water", "n_clear_dry", "n_scenes")


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _month_window(start_date: str, end_date: str) -> pd.DatetimeIndex:
    start = pd.Timestamp(start_date).to_period("M").to_timestamp()
    end = pd.Timestamp(end_date).to_period("M").to_timestamp()
    if start > end:
        raise ValueError("start_date must not be after end_date.")
    return pd.date_range(start, end, freq="MS")


def _canonical_frame(frame: pd.DataFrame, months: pd.DatetimeIndex) -> pd.DataFrame:
    out = frame.copy()
    if "date" in out.columns:
        out.index = pd.to_datetime(out.pop("date"), errors="raise")
    elif not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, errors="raise")
    out.index = pd.DatetimeIndex(out.index).to_period("M").to_timestamp()
    if out.index.has_duplicates:
        duplicates = sorted(out.index[out.index.duplicated(False)].strftime("%Y-%m").unique())
        raise ValueError(f"duplicate month timestamps: {duplicates}.")
    return out.sort_index().reindex(months)


def _frame_fingerprint(frame: pd.DataFrame) -> str:
    payload = {
        "dates": [ts.strftime("%Y-%m-%d") for ts in pd.DatetimeIndex(frame.index)],
        "columns": list(frame.columns),
        "values": {
            col: [None if pd.isna(value) else float(value) if isinstance(value, (np.floating, float)) else value for value in frame[col].tolist()]
            for col in frame.columns
        },
    }
    return _sha256_payload(payload)


def _json_file_payload(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _grid_identity_from_array(mask) -> dict[str, Any]:
    transform = None
    crs = None
    if _resolve_raster_crs is not None:
        crs = _resolve_raster_crs(mask)
    try:
        transform = tuple(mask.rio.transform())[:6]
    except Exception:
        transform = None
    return {
        "shape": (int(mask.sizes["y"]), int(mask.sizes["x"])),
        "crs": None if crs is None else str(crs),
        "transform": transform,
    }


def _inherit_dataset_georef(template, dataset):
    try:  # noqa: SIM105
        import rioxarray  # noqa: F401
    except Exception:
        return template
    crs_value = None
    try:
        crs_value = dataset.rio.crs
    except Exception:
        crs_value = None
    if crs_value is None and "spatial_ref" in dataset.coords:
        spatial_ref = dataset.coords["spatial_ref"]
        if hasattr(spatial_ref, "attrs"):
            crs_value = spatial_ref.attrs.get("spatial_ref") or spatial_ref.attrs.get("crs_wkt")
    if isinstance(crs_value, str):
        match = re.search(r'AUTHORITY\["EPSG","(\d+)"\]', crs_value)
        if match is not None:
            crs_value = f"EPSG:{match.group(1)}"
    try:
        if template.rio.crs is None and crs_value is not None:
            template = template.rio.write_crs(crs_value)
    except Exception:
        pass
    try:
        template = template.rio.write_transform(dataset.rio.transform())
    except Exception:
        pass
    return template


def _fallback_inside_mask(template, aoi_gdf):
    import xarray as xr
    from rasterio.features import geometry_mask

    transform = template.rio.transform()
    inside = geometry_mask(
        list(aoi_gdf.geometry),
        out_shape=(template.sizes["y"], template.sizes["x"]),
        transform=transform,
        invert=True,
        all_touched=True,
    )
    if hasattr(template.data, "dask"):
        import dask.array as da

        chunk_y = template.chunksizes["y"][0] if hasattr(template, "chunksizes") else template.sizes["y"]
        chunk_x = template.chunksizes["x"][0] if hasattr(template, "chunksizes") else template.sizes["x"]
        inside = da.from_array(inside, chunks=(chunk_y, chunk_x))
    return xr.DataArray(inside, dims=("y", "x"), coords={"y": template.y, "x": template.x})


def _prepare_mask(mask, *, start_date: str, end_date: str):
    if set(mask.dims) != {"time", "y", "x"}:
        raise ValueError("Canonical water masks require exactly time, y, and x dimensions.")
    months = _month_window(start_date, end_date)
    source_time = pd.DatetimeIndex(mask.time.values).to_period("M").to_timestamp()
    if pd.DatetimeIndex(source_time).has_duplicates:
        raise ValueError("Canonical water mask contains duplicate month timestamps.")
    mask = mask.assign_coords(time=("time", source_time)).sortby("time").sel(
        time=slice(months[0], months[-1])
    )
    mask = complete_monthly_axis(mask, start_date, end_date)
    valid_codes = mask.astype("int16").isin(np.array([-2, -1, 0, 1], dtype=np.int16)).all()
    scalar = valid_codes.compute() if hasattr(valid_codes.data, "compute") else valid_codes
    if not bool(scalar.item()):
        raise ValueError("Canonical water mask contains values outside -2, -1, 0, and 1.")
    return mask


def _mask_record(mask, *, source_identity: dict[str, Any], start_date: str, end_date: str) -> MonthlyObservationRecord:
    mask = _prepare_mask(mask, start_date=start_date, end_date=end_date)
    frame = monthly_water_extent(mask)
    frame = prepare_monthly_extent(frame)
    detectable_mask = (mask == 1)
    return MonthlyObservationRecord(
        frame=frame,
        capabilities=MonthlyObservationCapabilities(
            per_month_pixel_counts=True,
            unique_monthly_pixels=True,
            candidate_monthly_overlap=True,
            exact_geometry=True,
            exact_time_window=True,
        ),
        detectable_mask=detectable_mask,
        grid_identity=_grid_identity_from_array(mask),
        source_identity=source_identity,
    )


def _validate_extent_cross_check(frame: pd.DataFrame, check: pd.DataFrame) -> None:
    expected = frame.loc[:, list(_COUNT_COLUMNS)]
    observed = _canonical_frame(check.loc[:, list(_COUNT_COLUMNS)], pd.DatetimeIndex(frame.index))
    for column in _COUNT_COLUMNS:
        left = pd.to_numeric(expected[column], errors="coerce").fillna(np.nan).to_numpy(dtype=float)
        right = pd.to_numeric(observed[column], errors="coerce").fillna(np.nan).to_numpy(dtype=float)
        if not np.allclose(left, right, equal_nan=True):
            raise ValueError("extent counts cross-check failed against cached mask cube.")


def _normalize_dataframe(frame: pd.DataFrame, *, start_date: str, end_date: str) -> MonthlyObservationRecord:
    months = _month_window(start_date, end_date)
    normalized = _canonical_frame(frame, months)
    authoritative_minimum = {"n_water", "n_valid", "n_aoi"}
    has_counts = authoritative_minimum.issubset(normalized.columns)
    if has_counts and "n_invalid" not in normalized.columns:
        normalized["n_invalid"] = normalized["n_aoi"] - normalized["n_valid"]
    prepared = prepare_monthly_extent(normalized)
    if not has_counts:
        for column in _COUNT_COLUMNS:
            prepared[column] = np.nan
    return MonthlyObservationRecord(
        frame=prepared,
        capabilities=MonthlyObservationCapabilities(
            per_month_pixel_counts=has_counts,
            unique_monthly_pixels=False,
            candidate_monthly_overlap=False,
            exact_geometry=False,
            exact_time_window=True,
        ),
        detectable_mask=None,
        grid_identity={},
        source_identity={
            "kind": "dataframe",
            "content_fingerprint": _frame_fingerprint(normalized),
        },
    )


def _raw_count_store_identity(store_path: Path, *, variables: tuple[str, ...], start_date: str, end_date: str) -> dict[str, Any]:
    metadata_files = [".zgroup", ".zattrs", ".zmetadata"]
    variable_metadata: dict[str, dict[str, Any]] = {}
    for variable in variables:
        variable_dir = store_path / variable
        variable_metadata[variable] = {
            ".zarray": _json_file_payload(variable_dir / ".zarray"),
            ".zattrs": _json_file_payload(variable_dir / ".zattrs"),
        }
    chunk_inventory = sorted(
        str(path.relative_to(store_path)).replace(os.sep, "/")
        for path in store_path.rglob("*")
        if path.is_file()
        and not path.name.startswith(".")
        and any(part in variables for part in path.relative_to(store_path).parts)
    )
    metadata_scope = {
        "requested_window": [start_date, end_date],
        "metadata_files": {name: _json_file_payload(store_path / name) for name in metadata_files},
        "variables": variable_metadata,
    }
    return {
        "canonical_zarr_metadata_fingerprint": _sha256_payload(metadata_scope),
        "store_relative_chunk_inventory": chunk_inventory,
        "metadata_scope": metadata_scope,
    }


def _update_hasher_from_array(hasher, *, variable: str, time_value: pd.Timestamp, values: np.ndarray) -> None:
    hasher.update(variable.encode("utf-8"))
    hasher.update(time_value.strftime("%Y-%m-%d").encode("utf-8"))
    hasher.update(np.ascontiguousarray(values).tobytes())


def _raw_count_to_record(dataset, *, aoi, start_date: str, end_date: str, store_path: Path | None = None) -> MonthlyObservationRecord:
    missing = [name for name in _RAW_COUNT_VARIABLES if name not in dataset]
    if missing:
        raise ValueError(f"Raw-count monthly input requires variables {missing}.")
    if _xarray() is None or _resolve_aoi_inside_mask is None:
        raise ImportError("Raw-count monthly inputs require the raster extra.")
    months = _month_window(start_date, end_date)
    raw = dataset[list(_RAW_COUNT_VARIABLES)].copy()
    raw_time = pd.DatetimeIndex(raw.time.values).to_period("M").to_timestamp()
    if pd.DatetimeIndex(raw_time).has_duplicates:
        raise ValueError("Raw-count cube contains duplicate month timestamps.")
    raw = raw.assign_coords(time=("time", raw_time)).sortby("time").sel(
        time=slice(months[0], months[-1])
    )
    raw = raw.reindex(time=months, fill_value=0)
    template = _inherit_dataset_georef(raw["n_clear_water"].isel(time=0), raw)
    aoi_gdf = load_aoi(aoi)
    try:
        inside = _resolve_aoi_inside_mask(template, aoi_gdf)
    except Exception as exc:
        if "raster is missing CRS" not in str(exc):
            raise
        inside = _fallback_inside_mask(template, aoi_gdf)
    clear_water = raw["n_clear_water"]
    clear_dry = raw["n_clear_dry"]
    scenes = raw["n_scenes"]
    inside_values = (
        np.asarray(inside.compute().values, dtype=bool)
        if hasattr(inside.data, "compute")
        else np.asarray(inside.values, dtype=bool)
    )
    n_aoi = int(inside_values.sum())
    content_hasher = hashlib.sha256()
    n_water_values: list[float] = []
    n_valid_values: list[float] = []
    time_values = pd.DatetimeIndex(months)
    for index, time_value in enumerate(time_values):
        cw = clear_water.isel(time=index)
        cd = clear_dry.isel(time=index)
        ns = scenes.isel(time=index)
        cw_values, cd_values, ns_values = (
            np.asarray(cw.compute().values),
            np.asarray(cd.compute().values),
            np.asarray(ns.compute().values),
        )
        _update_hasher_from_array(content_hasher, variable="n_clear_water", time_value=time_value, values=cw_values[inside_values])
        _update_hasher_from_array(content_hasher, variable="n_clear_dry", time_value=time_value, values=cd_values[inside_values])
        _update_hasher_from_array(content_hasher, variable="n_scenes", time_value=time_value, values=ns_values[inside_values])
        detectable_values = (cw_values > 0) & inside_values
        valid_values = ((cw_values + cd_values) > 0) & inside_values
        n_water_values.append(float(detectable_values.sum()))
        n_valid_values.append(float(valid_values.sum()))
    frame = pd.DataFrame(
        {
            "n_water": np.asarray(n_water_values, dtype=float),
            "n_valid": np.asarray(n_valid_values, dtype=float),
            "n_invalid": np.full(len(months), float(n_aoi)) - np.asarray(n_valid_values, dtype=float),
            "n_aoi": np.full(len(months), float(n_aoi)),
        },
        index=months,
    )
    prepared = prepare_monthly_extent(frame)
    metadata_payload = {
        "window": [start_date, end_date],
        "coords": {
            "time": [ts.strftime("%Y-%m-%d") for ts in months],
            "y": [float(value) for value in raw.y.values.tolist()],
            "x": [float(value) for value in raw.x.values.tolist()],
        },
        "variables": {
            name: {
                "dtype": str(raw[name].dtype),
                "dims": list(raw[name].dims),
                "attrs": dict(raw[name].attrs),
            }
            for name in _RAW_COUNT_VARIABLES
        },
    }
    if _xarray() is None:
        raise ImportError("Raw-count monthly inputs require the raster extra.")
    detectable_mask = (clear_water > 0) & inside
    source_identity = {
        "kind": "raw_count_cube",
        "metadata_fingerprint": _sha256_payload(metadata_payload),
        "content_fingerprint": content_hasher.hexdigest(),
        "content_scope": {
            "requested_window": [start_date, end_date],
            "variables": list(_RAW_COUNT_VARIABLES),
            "inside_aoi_pixel_count": n_aoi,
        },
    }
    if store_path is not None:
        source_identity.update(
            _raw_count_store_identity(
                store_path,
                variables=_RAW_COUNT_VARIABLES,
                start_date=start_date,
                end_date=end_date,
            )
        )
    return MonthlyObservationRecord(
        frame=prepared,
        capabilities=MonthlyObservationCapabilities(
            per_month_pixel_counts=True,
            unique_monthly_pixels=True,
            candidate_monthly_overlap=True,
            exact_geometry=True,
            exact_time_window=True,
        ),
        detectable_mask=detectable_mask,
        grid_identity=_grid_identity_from_array(raw["n_clear_water"]),
        source_identity=source_identity,
    )


def normalize_monthly_observations(
    observations,
    *,
    aoi,
    start_date: str,
    end_date: str,
    water_mask_variable: str | None = None,
) -> MonthlyObservationRecord:
    if isinstance(observations, pd.DataFrame):
        return _normalize_dataframe(observations, start_date=start_date, end_date=end_date)

    if WOfSCacheHandle is not None and isinstance(observations, WOfSCacheHandle):
        if verify_cache_analysis_mask is None:
            raise ImportError("WOfS cache provenance verification is unavailable.")
        analysis_mask = verify_cache_analysis_mask(observations)
        mask = open_completed_mask_cache(observations, start_date, end_date)
        record = _mask_record(
            mask,
            source_identity={
                "kind": "wofs_cache",
                "cache_identity": observations.identity,
                "request_digest": observations.request_digest,
                "analysis_mask": {
                    "mask_sha256": analysis_mask.mask_sha256,
                    "pixel_count": analysis_mask.pixel_count,
                    "source_product": analysis_mask.source_product,
                    "source_version": analysis_mask.source_version,
                    "source_item_ids": list(analysis_mask.source_item_ids),
                    "source_lineage": list(analysis_mask.source_lineage),
                    "coverage_start": analysis_mask.coverage_start,
                    "coverage_end": analysis_mask.coverage_end,
                },
            },
            start_date=start_date,
            end_date=end_date,
        )
        check = open_completed_extent_counts(observations, start_date, end_date)
        if check is not None:
            _validate_extent_cross_check(record.frame, check)
        return record

    if isinstance(observations, (str, Path)):
        path = Path(observations)
        if path.suffix.casefold() != ".zarr":
            raise ValueError("Monthly observation paths must currently point to a .zarr store.")
        xr = _xarray()
        if xr is None:
            raise ImportError("Zarr monthly inputs require the raster extra.")
        opened = xr.open_zarr(path, chunks={}, mask_and_scale=False)
        try:
            return _raw_count_to_record(
                opened,
                aoi=aoi,
                start_date=start_date,
                end_date=end_date,
                store_path=path,
            )
        finally:
            opened.close()

    xr = _xarray()
    if xr is None:
        raise TypeError("Monthly observations require pandas or the raster extra.")

    if isinstance(observations, xr.DataArray):
        return _mask_record(
            observations,
            source_identity={
                "kind": "xarray_dataarray",
                "content_fingerprint": _sha256_payload(
                    {
                        "window": [start_date, end_date],
                        "shape": [
                            int(observations.sizes["time"]),
                            int(observations.sizes["y"]),
                            int(observations.sizes["x"]),
                        ],
                    }
                ),
            },
            start_date=start_date,
            end_date=end_date,
        )

    if isinstance(observations, xr.Dataset):
        if any(name in observations for name in _RAW_COUNT_VARIABLES):
            return _raw_count_to_record(
                observations,
                aoi=aoi,
                start_date=start_date,
                end_date=end_date,
            )
        if water_mask_variable is not None:
            if water_mask_variable not in observations:
                raise ValueError(f"water_mask_variable={water_mask_variable!r} is unavailable.")
            return _mask_record(
                observations[water_mask_variable],
                source_identity={"kind": "xarray_dataset", "variable": water_mask_variable},
                start_date=start_date,
                end_date=end_date,
            )
        raise ValueError(
            "Dataset monthly input must either expose raw-count variables or name a water_mask_variable."
        )

    raise TypeError(
        "Monthly observations must be a DataFrame, DataArray, Dataset, WOfSCacheHandle, or .zarr path."
    )


__all__ = ["normalize_monthly_observations"]


