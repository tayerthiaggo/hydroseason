"""Annual DEA Water Observation Statistics loader for preflight workflows."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    import xarray as xr

from hydroseason._historical_water_mask import _aoi_digest
from hydroseason._io_dea_stats import (
    COUNT_CLEAR_BAND,
    COUNT_WET_BAND,
    DEA_STATS_ANNUAL_COLLECTION,
    DEFAULT_WO_STATISTICS_STAC_URL,
    STAC_CONNECT_TIMEOUT_S,
    STAC_READ_TIMEOUT_S,
    STAC_SEARCH_DEADLINE_S,
    DEAStatsUnavailable,
    _run_with_timeout,
    fetch_dea_stats_wet_aoi,
)

_CACHE_DIRNAME = "preflight-annual-statistics"
_COUNT_WET_FILENAME = "count_wet.npy"
_COUNT_CLEAR_FILENAME = "count_clear.npy"
_MANIFEST_FILENAME = "manifest.json"
_CACHE_SCHEMA_VERSION = 1
_METRIC_IMPLEMENTATION_VERSION = "preflight_annual_statistics_v1"


class AnnualStatisticsUnavailable(RuntimeError):
    """The annual DEA Water Observation Statistics source was unusable."""


@dataclass(frozen=True)
class CompleteYearWindow:
    """Closed requested interval resolved into complete calendar years."""

    requested_start: str
    requested_end: str
    complete_years: tuple[int, ...]
    partial_start: tuple[str, str] | None
    partial_end: tuple[str, str] | None


def resolve_complete_year_window(start_date: str, end_date: str) -> CompleteYearWindow:
    """Resolve the complete calendar years fully contained in a closed interval."""

    start_ts = _normalized_interval_start(start_date)
    end_ts = _normalized_interval_end(end_date)
    if end_ts < start_ts:
        raise ValueError("end_date must be on or after start_date")
    candidate_years = range(start_ts.year, end_ts.year + 1)
    complete_years = tuple(
        year
        for year in candidate_years
        if start_ts <= _calendar_year_start(year) and end_ts >= _calendar_year_end(year)
    )

    partial_start = None
    if start_ts > _calendar_year_start(start_ts.year):
        partial_start = (
            start_date,
            f"{start_ts.year}-12-31",
        )

    partial_end = None
    if end_ts < _calendar_year_end(end_ts.year):
        partial_end = (
            f"{end_ts.year}-01-01",
            end_date,
        )

    if not complete_years and start_ts.year == end_ts.year and partial_start is not None:
        partial_end = None

    return CompleteYearWindow(
        requested_start=start_date,
        requested_end=end_date,
        complete_years=complete_years,
        partial_start=partial_start,
        partial_end=partial_end,
    )


def _normalized_interval_start(value: str):
    import pandas as pd

    timestamp = pd.Timestamp(value).tz_localize(None)
    return timestamp.normalize() if _looks_like_date_only(value) else timestamp


def _normalized_interval_end(value: str):
    import pandas as pd

    timestamp = pd.Timestamp(value).tz_localize(None)
    if _looks_like_date_only(value):
        return timestamp.normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return timestamp


def _looks_like_date_only(value: str) -> bool:
    text = value.strip()
    return "T" not in text and " " not in text and len(text) == 10


def _calendar_year_start(year: int):
    import pandas as pd

    return pd.Timestamp(year=year, month=1, day=1)


def _calendar_year_end(year: int):
    import pandas as pd

    return pd.Timestamp(year=year, month=12, day=31) + pd.Timedelta(days=1) - pd.Timedelta(
        nanoseconds=1
    )


def _search_complete_year_items(
    *,
    bbox: Sequence[float],
    product: str,
    stac_url: str,
    complete_years: Sequence[int],
):
    import concurrent.futures

    import pystac_client

    if not complete_years:
        return []
    start_year = int(min(complete_years))
    end_year = int(max(complete_years))
    try:
        client = pystac_client.Client.open(
            stac_url,
            timeout=(STAC_CONNECT_TIMEOUT_S, STAC_READ_TIMEOUT_S),
        )
        search = client.search(
            collections=[product],
            bbox=list(bbox),
            datetime=f"{start_year}-01-01/{end_year}-12-31",
            limit=1000,
        )
        return _run_with_timeout(
            lambda: list(search.items()),
            STAC_SEARCH_DEADLINE_S,
        )
    except (TimeoutError, concurrent.futures.TimeoutError) as exc:
        raise AnnualStatisticsUnavailable(
            f"annual statistics search at {stac_url} exceeded the {STAC_SEARCH_DEADLINE_S:g}s deadline"
        ) from exc
    except Exception as exc:
        raise AnnualStatisticsUnavailable(
            f"annual statistics STAC search failed for product {product!r} at {stac_url}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def _item_year(item) -> int:
    import pandas as pd

    raw = getattr(item, "properties", {}).get("datetime")
    try:
        return int(pd.Timestamp(raw).tz_localize(None).year)
    except Exception as exc:
        raise AnnualStatisticsUnavailable(
            f"annual statistics item {getattr(item, 'id', None)!r} has an invalid datetime {raw!r}"
        ) from exc


def _item_id(item) -> str:
    raw = getattr(item, "id", None)
    if raw is None:
        raise AnnualStatisticsUnavailable("annual statistics item id is missing")
    item_id = str(raw).strip()
    if not item_id or item_id.lower() == "none":
        raise AnnualStatisticsUnavailable("annual statistics item id is missing")
    return item_id


def _group_items_by_year(items: Sequence[Any]) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = {}
    for item in items:
        grouped.setdefault(_item_year(item), []).append(item)
    return grouped


def _version_token(collection: str) -> str | None:
    tail = str(collection).rsplit("_", 1)[-1]
    return tail if tail.isdigit() else None


def _item_processing_version(item) -> str | None:
    properties = getattr(item, "properties", {}) or {}
    explicit = properties.get("odc:processing_version")
    if explicit is not None:
        return str(explicit)
    product = getattr(item, "collection_id", None) or properties.get("odc:product")
    return _version_token(str(product)) if product is not None else None


def _item_temporal_fields(items: Sequence[Any]) -> dict[str, list[str | None]]:
    return {
        "datetime": [getattr(item, "properties", {}).get("datetime") for item in items],
        "start_datetime": [getattr(item, "properties", {}).get("start_datetime") for item in items],
        "end_datetime": [getattr(item, "properties", {}).get("end_datetime") for item in items],
    }


def _cache_identity_payload(
    *,
    aoi_sha256: str,
    product: str,
    complete_years: Sequence[int],
    crs: str,
    resolution: float,
    item_ids_by_year: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    return {
        "aoi_sha256": aoi_sha256,
        "product": product,
        "complete_years": [int(year) for year in complete_years],
        "crs": str(crs),
        "resolution": float(resolution),
        "item_ids_by_year": {
            str(year): [str(item_id) for item_id in ids]
            for year, ids in sorted(item_ids_by_year.items())
        },
    }


def _validate_item_ids_by_year(
    item_ids_by_year: Mapping[str, Sequence[str]],
    *,
    expected: Mapping[str, Sequence[str]] | None = None,
) -> None:
    if not item_ids_by_year:
        raise ValueError("annual statistics cache verification failed: item identity missing")
    normalized: dict[str, tuple[str, ...]] = {}
    for year, item_ids in item_ids_by_year.items():
        year_key = str(year)
        cleaned = tuple(str(item_id).strip() for item_id in item_ids)
        if not year_key or not cleaned or any(not item_id or item_id.lower() == "none" for item_id in cleaned):
            raise ValueError("annual statistics cache verification failed: item identity missing")
        normalized[year_key] = cleaned
    if expected is not None:
        expected_normalized = {
            str(year): tuple(str(item_id).strip() for item_id in item_ids)
            for year, item_ids in expected.items()
        }
        if normalized != expected_normalized:
            raise ValueError("annual statistics cache verification failed: item identity mismatch")


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def _sha256_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _cache_root(cache_dir: Path) -> Path:
    return cache_dir / _CACHE_DIRNAME


def _cache_dir_for_digest(cache_dir: Path, cache_digest: str) -> Path:
    return _cache_root(cache_dir) / cache_digest


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json_bytes(payload))
        os.replace(str(temp_path), str(path))
    finally:
        temp_path.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _manifest_payload(
    *,
    provenance: dict[str, Any],
    cache_identity: dict[str, Any],
    dataset: "xr.Dataset",
) -> dict[str, Any]:
    years = [int(year) for year in dataset["year"].values.tolist()]
    return {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "cache_identity": cache_identity,
        "cache_digest": _sha256_digest(cache_identity),
        "years": years,
        "y": [float(value) for value in dataset["y"].values.tolist()],
        "x": [float(value) for value in dataset["x"].values.tolist()],
        "shape": [int(size) for size in dataset[COUNT_WET_BAND].shape],
        "provenance": provenance,
    }


def _verify_cache_manifest(manifest: dict[str, Any], expected_identity: dict[str, Any]) -> None:
    if manifest.get("schema_version") != _CACHE_SCHEMA_VERSION:
        raise ValueError("annual statistics cache verification failed: schema version mismatch")
    manifest_identity = manifest.get("cache_identity")
    if not isinstance(manifest_identity, Mapping):
        raise ValueError("annual statistics cache verification failed: cache identity missing")
    _validate_item_ids_by_year(
        manifest_identity.get("item_ids_by_year", {}),
        expected=expected_identity.get("item_ids_by_year", {}),
    )
    if manifest_identity != expected_identity:
        raise ValueError("annual statistics cache verification failed: cache identity mismatch")
    if manifest.get("cache_digest") != _sha256_digest(expected_identity):
        raise ValueError("annual statistics cache verification failed: cache digest mismatch")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("annual statistics cache verification failed: provenance missing")
    _validate_item_ids_by_year(
        provenance.get("item_ids_by_year", {}),
        expected=expected_identity.get("item_ids_by_year", {}),
    )
    if "shape" not in manifest:
        raise ValueError("annual statistics cache verification failed: array shape missing")
    manifest_years = [int(year) for year in manifest.get("years", [])]
    identity_years = sorted(int(year) for year in expected_identity.get("item_ids_by_year", {}).keys())
    if manifest_years != identity_years:
        raise ValueError("annual statistics cache verification failed: years list mismatch")


def _write_cache(cache_dir: Path, *, dataset: "xr.Dataset", manifest: dict[str, Any]) -> None:
    import shutil

    final_dir = _cache_dir_for_digest(cache_dir, manifest["cache_digest"])
    if (final_dir / _MANIFEST_FILENAME).exists():
        return

    root = _cache_root(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f".{manifest['cache_digest']}.incomplete-{os.getpid()}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True)
    try:
        cache_dataset = dataset[[COUNT_WET_BAND, COUNT_CLEAR_BAND]]
        _write_band_streamed(temp_dir / _COUNT_WET_FILENAME, cache_dataset[COUNT_WET_BAND])
        _write_band_streamed(temp_dir / _COUNT_CLEAR_FILENAME, cache_dataset[COUNT_CLEAR_BAND])
        _write_json_atomic(temp_dir / _MANIFEST_FILENAME, manifest)
        if final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        os.replace(str(temp_dir), str(final_dir))
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _write_band_streamed(path: Path, band: "xr.DataArray") -> None:
    """Write ``band`` to ``path`` one year at a time.

    ``band`` is Dask-backed at full-catchment resolution; materialising every
    year at once as a single NumPy array can require tens of GiB for large
    catchments. Writing year-by-year into a pre-allocated on-disk array
    bounds peak memory to a single year's plane.
    """
    import gc

    import numpy as np

    if band.dims[0] != "year":
        raise ValueError(f"expected 'year' as the first dimension of {path.name}, got {band.dims}")
    memmap = np.lib.format.open_memmap(path, mode="w+", dtype=band.dtype, shape=tuple(band.shape))
    try:
        for index in range(band.sizes["year"]):
            plane = band.isel(year=index).data
            memmap[index] = plane.compute() if hasattr(plane, "compute") else np.asarray(plane)
        memmap.flush()
    finally:
        underlying_mmap = getattr(memmap, "_mmap", None)
        del memmap
        if underlying_mmap is not None:
            underlying_mmap.close()
        gc.collect()


def _open_cached_dataset(cache_dir: Path, expected_identity: dict[str, Any]) -> "xr.Dataset | None":
    import numpy as np
    import xarray as xr

    cache_digest = _sha256_digest(expected_identity)
    stored_dir = _cache_dir_for_digest(cache_dir, cache_digest)
    manifest = _read_json(stored_dir / _MANIFEST_FILENAME)
    if manifest is None:
        return None
    _verify_cache_manifest(manifest, expected_identity)
    wet = np.load(stored_dir / _COUNT_WET_FILENAME, mmap_mode="r")
    clear = np.load(stored_dir / _COUNT_CLEAR_FILENAME, mmap_mode="r")
    dataset = xr.Dataset(
        {
            COUNT_WET_BAND: (
                ("year", "y", "x"),
                wet,
            ),
            COUNT_CLEAR_BAND: (
                ("year", "y", "x"),
                clear,
            ),
        },
        coords={
            "year": manifest["years"],
            "y": manifest["y"],
            "x": manifest["x"],
        },
    )
    dataset.attrs["provenance"] = manifest["provenance"]
    return dataset


def open_annual_wo_statistics(
    aoi: Any,
    start_date: str,
    end_date: str,
    *,
    product: str = DEA_STATS_ANNUAL_COLLECTION,
    stac_url: str = DEFAULT_WO_STATISTICS_STAC_URL,
    resolution: float = 30.0,
    crs: str = "EPSG:3577",
    chunks: Mapping[str, int] | None = None,
    cache_dir: str | os.PathLike[str] | None = None,
    prune_to_wet_aoi: bool = True,
    wet_aoi_min_frequency_fraction: float | None = None,
    wet_aoi_require_year_union: bool = False,
    materialize: bool = True,
) -> "xr.Dataset":
    """Load annual DEA Water Observation Statistics with an explicit year axis.

    ``materialize`` (default ``True``) converts the returned dataset's data
    variables to plain, already-computed NumPy arrays before returning --
    ``.compute()`` for the fresh-fetch (Dask-backed) path, which genuinely
    triggers the underlying S3/COG fetch once and holds the result in RAM;
    an explicit ``np.asarray()`` per variable for the cache-hit
    (NumPy-memmap-backed) path, since ``.compute()``/``.load()`` silently
    no-op on a memmap (it is an ``np.ndarray`` subclass, not a Dask
    collection). Note the cache-hit conversion only strips memmap's
    lazy/disk-paged *interface* -- ``np.asarray()`` on a memmap returns a
    view sharing the same underlying buffer, not a copy detached from disk,
    so it does not by itself force local disk pages into RAM. What it fixes
    is the Dask-backed fresh-fetch case: left lazy, every downstream scalar
    reduction in candidate evaluation (there are many -- one per requested
    year, several more per pathway) independently re-triggers the full
    upstream S3 fetch from scratch; measured on fitzroy_river_wa this cost
    ~340s lazy vs. ~70s materialized once. Set
    ``materialize=False`` only if investigating memory behaviour for an
    unusually large, unpruned, native-resolution request -- this is the same
    class of allocation the streamed cache-writing path was built to bound,
    applied here to the read/evaluation side instead of the write side.
    """
    import odc.stac

    from hydroseason._io_geo import _configure_cog_read_env, _crs_value, load_aoi

    window = resolve_complete_year_window(start_date, end_date)
    if not window.complete_years:
        raise AnnualStatisticsUnavailable(
            "requested interval does not contain a complete calendar year"
        )

    aoi_gdf = load_aoi(aoi)
    crs_value = _crs_value(crs)
    target = aoi_gdf.to_crs(crs_value) if crs_value is not None else aoi_gdf
    wet_aoi_pruning_applied = False
    wet_aoi_pruning_fallback_reason: str | None = None
    if prune_to_wet_aoi:
        try:
            target = fetch_dea_stats_wet_aoi(
                stac_url,
                target,
                years=list(window.complete_years),
                crs=crs_value if crs_value is not None else crs,
                resolution=resolution,
                min_frequency_fraction=wet_aoi_min_frequency_fraction,
                require_year_union=wet_aoi_require_year_union,
            )
            wet_aoi_pruning_applied = True
        except DEAStatsUnavailable as exc:
            wet_aoi_pruning_fallback_reason = str(exc)
        except ValueError:
            # A bad min_frequency_fraction (e.g. 10 meaning "10%" instead of
            # 0.1, or a negative value) is a caller/operator error, not a
            # genuine wet-AOI construction failure (network, geometry,
            # timeout) -- categorically different from the exceptions the
            # broad `except Exception` below exists to fail open on. Letting
            # it propagate keeps it a hard, visible failure instead of
            # silently disabling pruning and burying the reason in
            # provenance["wet_aoi_pruning"]["fallback_reason"].
            raise
        except Exception as exc:
            wet_aoi_pruning_fallback_reason = str(exc)
    bbox = list(target.to_crs("EPSG:4326").total_bounds)

    try:
        items = _search_complete_year_items(
            bbox=bbox,
            product=product,
            stac_url=stac_url,
            complete_years=window.complete_years,
        )
    except AnnualStatisticsUnavailable:
        raise
    except Exception as exc:
        raise AnnualStatisticsUnavailable(str(exc)) from exc

    items_by_year = _group_items_by_year(items)
    requested_years = set(window.complete_years)
    item_ids_by_year = {
        str(year): sorted(_item_id(item) for item in year_items)
        for year, year_items in sorted(items_by_year.items())
    }
    missing_requested_years = sorted(year for year in requested_years if year not in items_by_year)
    if not items_by_year:
        raise AnnualStatisticsUnavailable("no annual statistics items found for the complete-year window")

    aoi_sha256 = _aoi_digest(target)
    cache_identity = _cache_identity_payload(
        aoi_sha256=aoi_sha256,
        product=product,
        complete_years=window.complete_years,
        crs=crs,
        resolution=resolution,
        item_ids_by_year=item_ids_by_year,
    )
    if cache_dir is not None:
        cached = _open_cached_dataset(Path(cache_dir), cache_identity)
        if cached is not None:
            if materialize:
                import numpy as np

                # Strips memmap's lazy interface so downstream .compute()
                # checks behave predictably -- np.asarray() on a memmap
                # returns a view sharing the same buffer, not a RAM copy
                # detached from disk (see the materialize docstring above).
                cached = cached.copy(
                    data={name: np.asarray(da.data) for name, da in cached.data_vars.items()}
                )
            return cached

    _configure_cog_read_env()
    odc.stac.configure_rio(
        cloud_defaults=True,
        aws={"aws_unsigned": True},
    )

    load_kwargs: dict[str, Any] = {
        "bands": [COUNT_WET_BAND, COUNT_CLEAR_BAND],
        "crs": crs_value,
        "resolution": resolution,
        "geopolygon": target.geometry,
        "chunks": dict(chunks) if chunks is not None else {"x": 2048, "y": 2048},
    }
    annual_planes = []
    for year in sorted(items_by_year):
        loaded = odc.stac.load(items_by_year[year], **load_kwargs)
        if "time" not in loaded.dims or int(loaded.sizes.get("time", 0)) != 1:
            raise AnnualStatisticsUnavailable(f"ambiguous annual summary for {year}")
        annual_planes.append(loaded.isel(time=0, drop=True).expand_dims(year=[year]))

    import xarray as xr

    dataset = xr.concat(annual_planes, dim="year")
    # ``geopolygon`` determines the read window but may still leave pixels
    # from its bounding rectangle in the returned array. Rasterize the
    # clipped wet-AOI again so the feasibility reduction cannot admit a
    # recurrent pixel outside the observed max-water extent (or outside the
    # user AOI when wet-AOI pruning falls back to the full AOI).
    from hydroseason._io_geo import _inside_aoi_mask_like

    inside_target = _inside_aoi_mask_like(dataset[COUNT_WET_BAND].isel(year=0), target)
    dataset = dataset.where(inside_target)
    resolved_crs = str(crs)
    pixel_area = abs(float(resolution)) * abs(float(resolution))
    processing_versions_by_year = {
        str(year): [_item_processing_version(item) for item in items_by_year[year]]
        for year in sorted(items_by_year)
    }
    provenance = {
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "complete_years": [int(year) for year in window.complete_years],
        "partial_start": list(window.partial_start) if window.partial_start is not None else None,
        "partial_end": list(window.partial_end) if window.partial_end is not None else None,
        "missing_requested_years": missing_requested_years,
        "product": product,
        "stac_url": stac_url,
        "crs": resolved_crs,
        "resolution": float(resolution),
        "pixel_area": pixel_area,
        "metric_implementation_version": _METRIC_IMPLEMENTATION_VERSION,
        "item_ids_by_year": item_ids_by_year,
        "temporal_fields_by_year": {
            str(year): _item_temporal_fields(items_by_year[year]) for year in sorted(items_by_year)
        },
        "processing_versions_by_year": processing_versions_by_year,
        "cache_identity_inputs": cache_identity,
        "frequency_fraction": {
            "derivation": f"{COUNT_WET_BAND} / {COUNT_CLEAR_BAND} where {COUNT_CLEAR_BAND} > 0",
        },
        "wet_aoi_pruning": {
            "requested": prune_to_wet_aoi,
            "applied": wet_aoi_pruning_applied,
            "fallback_reason": wet_aoi_pruning_fallback_reason,
            "min_frequency_fraction": wet_aoi_min_frequency_fraction,
            "require_year_union": wet_aoi_require_year_union,
        },
    }
    dataset.attrs["provenance"] = provenance

    if cache_dir is not None:
        manifest = _manifest_payload(
            provenance=provenance,
            cache_identity=cache_identity,
            dataset=dataset[[COUNT_WET_BAND, COUNT_CLEAR_BAND]],
        )
        _write_cache(Path(cache_dir), dataset=dataset, manifest=manifest)

    return dataset.compute() if materialize else dataset


__all__ = [
    "AnnualStatisticsUnavailable",
    "CompleteYearWindow",
    "open_annual_wo_statistics",
    "resolve_complete_year_window",
]

