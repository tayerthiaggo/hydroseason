"""Orchestrates WOfS Zarr cache acquisition through one shared annual graph.

:func:`acquire_wofs_cache` is the single entry point a caller uses to fill
(or reuse) a :mod:`hydroseason._io_wofs_zarr` cache store for an AOI and
date range: it queries the STAC catalog exactly once for the whole
interval (see :func:`hydroseason._io_geo._query_wofs_items`), partitions
the returned items by calendar year (:func:`partition_items_by_year`), and
-- for every year not already present in the store
(:func:`hydroseason._io_wofs_zarr.completed_years`) -- builds one shared
lazy Dask graph for that year (:func:`build_wofs_year_graph`, which lives
in :mod:`hydroseason._io_geo`) and writes it once
(:func:`hydroseason._io_wofs_zarr.write_annual_group`). Years already
completed are never rebuilt, and a query/graph/write failure for one year
never rolls back or deletes a different year's already-completed group,
because each year's write is independent and atomic
(:func:`write_annual_group` publishes via a single ``os.replace``).

Every name this module calls that a caller might want to intercept in a
unit test (``_query_wofs_items``, ``build_wofs_year_graph``,
``write_annual_group``, ``resolve_cached_request``, ``completed_years``,
``preflight_request_space``, ...) is imported here at module scope and
invoked unqualified, so ``monkeypatch.setattr("hydroseason._io_wofs_acquire.<name>",
...)`` actually intercepts the call site inside :func:`acquire_wofs_cache`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from hydroseason._io_geo import (
    _output_geobox_for_aoi,
    _query_wofs_items,
    build_wofs_year_graph,
)
from hydroseason._io_wofs_zarr import (
    WOFS_CACHE_SCHEMA_VERSION,
    WOFS_CLASSIFIER_VERSION,
    WOFS_PLANNER_VERSION,
    MASK_CHUNKS,
    WOfSCacheHandle,
    WOfSCacheIdentity,
    WOfSCacheRequest,
    _COMPLETE_FILENAME,
    _long_path,
    _read_json,
    _sha256_digest,
    _write_json_atomic,
    _zarr_store,
    cache_writer_lock,
    completed_years,
    create_cache_handle,
    preflight_request_space,
    require_cached_request,
    resolve_cached_request,
    write_annual_group,
)
from hydroseason._spatial_plan import plan_spatial_slices, plan_storage_aligned_slices


def partition_items_by_year(items) -> dict[int, tuple]:
    """Group STAC ``items`` by the calendar year of their acquisition timestamp.

    Parses each item's timestamp the same way
    :func:`hydroseason._io_geo._load_wofs_items` does --
    ``item.properties.get("datetime") or item.properties.get("start_datetime")``,
    compared timezone-naive -- so an item lands in the same year bucket
    :func:`build_wofs_year_graph`'s own per-item validation expects. Years
    are returned in ascending order; items within a year keep their
    original relative order.
    """
    groups: dict[int, list] = {}
    for item in items:
        date = pd.Timestamp(
            item.properties.get("datetime") or item.properties.get("start_datetime")
        )
        if date.tzinfo is not None:
            date = date.tz_convert(None)
        groups.setdefault(int(date.year), []).append(item)
    return {year: tuple(year_items) for year, year_items in sorted(groups.items())}


def _months_in_range(start_date: str, end_date: str) -> int:
    start = pd.Timestamp(start_date).to_period("M")
    end = pd.Timestamp(end_date).to_period("M")
    return int((end - start).n) + 1


def _year_date_bounds(year: int, start_date: str, end_date: str) -> tuple[str, str]:
    """Clip ``[start_date, end_date]`` to the portion that falls in ``year``."""
    start = max(pd.Timestamp(start_date), pd.Timestamp(f"{year}-01-01"))
    end = min(pd.Timestamp(end_date), pd.Timestamp(f"{year}-12-31"))
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _package_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    versions: dict[str, str] = {}
    for package in ("hydroseason", "odc-stac", "xarray", "dask", "zarr", "pystac-client", "rioxarray"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            continue
    return versions


def _planned_pixel_shape(plan) -> tuple[int, int]:
    """A ``(height, width)`` shape whose area equals the plan's de-duplicated pixel footprint.

    ``preflight_cache_space``/``preflight_request_space`` take a rectangular
    ``shape`` and project ``height * width * months`` bytes; the planner's
    selected windows are a de-duplicated set of grid cells that need not
    themselves form a rectangle, so this collapses their total pixel area
    into an equivalent ``(1, total_pixels)`` shape -- the same byte
    projection ``preflight_cache_space`` would compute for a real rectangle
    of that many pixels, without inventing a covering bounding box that
    could overstate the true footprint.
    """
    total_pixels = sum(
        (window.y_stop - window.y_start) * (window.x_stop - window.x_start)
        for window in plan.windows
    )
    return (1, int(total_pixels))


def _diagnostics_payload(query_count: int, graph_count: int, write_stats=()) -> dict[str, int]:
    return {
        "query_count": int(query_count),
        "graph_count": int(graph_count),
        "task_count": sum(int(stats.task_count) for stats in write_stats),
        "chunks_considered": sum(int(stats.chunks_considered) for stats in write_stats),
        "chunks_written": sum(int(stats.chunks_written) for stats in write_stats),
        "loaded_pixels": sum(int(stats.loaded_pixels) for stats in write_stats),
    }


def _empty_year_mask(geobox, start_date: str, end_date: str, aoi_gdf):
    """A lazy all-``-1``-inside/``-2``-outside-AOI cube for a year with zero STAC items.

    Matches the existing missing-month policy (see
    :func:`hydroseason._io_extent.complete_monthly_axis`): a month with no
    observation becomes ``-1`` invalid, not ``-2`` outside. AOI clipping
    marks genuinely outside-AOI pixels ``-2`` afterwards, so this starts
    every pixel at ``-1`` and lets the same AOI clip used elsewhere carve
    out the outside-AOI ``-2`` region -- no ``stac_load``/network call is
    made for a year with no items.
    """
    import dask.array as da
    import numpy as np
    import rioxarray  # noqa: F401  (registers the .rio accessor)
    import xarray as xr

    months = pd.date_range(
        pd.Timestamp(start_date).to_period("M").to_timestamp(),
        pd.Timestamp(end_date).to_period("M").to_timestamp(),
        freq="MS",
    )
    height, width = geobox.shape
    data = da.full(
        (len(months), height, width),
        -1,
        dtype=np.int8,
        chunks=(
            1,
            min(MASK_CHUNKS[1], int(height)),
            min(MASK_CHUNKS[2], int(width)),
        ),
    )
    y, x = geobox.coordinates.values()
    template = xr.DataArray(
        data,
        dims=("time", "y", "x"),
        coords={"time": months, "y": y.values, "x": x.values},
    )
    template = template.rio.write_crs(geobox.crs)
    template = template.rio.write_transform(geobox.affine)
    from hydroseason._io_geo import _clip_to_aoi

    return _clip_to_aoi(template, aoi_gdf)


def acquire_wofs_cache(
    stac_url: str,
    collection: str,
    aoi,
    start_date: str,
    end_date: str,
    *,
    cache_root: str | Path,
    crs: int | str = 3577,
    resolution: float = 30.0,
    chunk_x: int = 512,
    chunk_y: int = 512,
    time_chunk: int = 12,
    majority: bool = True,
    offline: bool = False,
    force: bool = False,
    progress: bool = False,
    progress_desc: str | None = None,
    progress_position: int | None = None,
    diagnostics_callback: Callable[[dict[str, int]], None] | None = None,
    wet_aoi: Any = None,
    compute_batch_size: int = 16,
    read_workers: int | None = None,
    resampling_policy: Literal["categorical_safe", "native_aligned"] = "categorical_safe",
    year_workers: int = 1,
) -> WOfSCacheHandle:
    """Fill (or reuse) a WOfS Zarr cache store for ``aoi``/``[start_date, end_date]``.

    Queries STAC exactly once for the whole interval, derives one parent
    GeoBox for the AOI, and writes one annual Zarr group per calendar year
    not already completed -- see the module docstring for the full flow.

    ``offline=True`` never touches the network or filesystem beyond the
    local cache index: it looks the request up via
    :func:`hydroseason._io_wofs_zarr.require_cached_request` and raises
    ``FileNotFoundError`` on a miss, matching that function's contract.

    ``force=True`` treats every requested year as needing a rebuild
    (ignores :func:`hydroseason._io_wofs_zarr.completed_years` and passes
    ``overwrite=True`` to :func:`hydroseason._io_wofs_zarr.write_annual_group`),
    mirroring the ``force`` convention already used elsewhere in this
    package (e.g. :mod:`hydroseason._io_extent_cache`) to mean "treat a
    cache hit as a miss."
    """
    cache_root = Path(cache_root)
    aoi_name = "aoi"
    if isinstance(aoi, (str, Path)):
        aoi_name = Path(aoi).stem
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if end < start:
        raise ValueError(f"end_date {end_date!r} is before start_date {start_date!r}.")
    if resolution is None or resolution <= 0:
        raise ValueError(f"resolution must be a positive number, got {resolution!r}.")

    from hydroseason._io_geo import load_aoi, _crs_value

    aoi_gdf = load_aoi(aoi)
    aoi_hash = _aoi_digest(aoi_gdf)
    crs_value = _crs_value(crs)

    request = WOfSCacheRequest(
        stac_url=stac_url,
        collection=collection,
        aoi_sha256=aoi_hash,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        crs=str(crs_value),
        resolution=float(resolution),
        classifier_version=WOFS_CLASSIFIER_VERSION,
        groupby="solar_day",
        majority=bool(majority),
        planner_version=WOFS_PLANNER_VERSION,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
    )

    if offline:
        handle = require_cached_request(cache_root, request, offline=True)
        if diagnostics_callback is not None:
            diagnostics_callback(_diagnostics_payload(0, 0))
        return handle

    requested_years = set(range(start.year, end.year + 1))

    existing_handle = resolve_cached_request(cache_root, request, offline=True)
    if existing_handle is not None and not force:
        already_done = completed_years(existing_handle)
        if requested_years <= already_done:
            if diagnostics_callback is not None:
                diagnostics_callback(_diagnostics_payload(0, 0))
            return existing_handle

    months = _months_in_range(request.start_date, request.end_date)
    cache_root.mkdir(parents=True, exist_ok=True)
    preflight_request_space(
        cache_root, aoi_gdf, crs=crs_value, resolution=float(resolution), months=months
    )

    target = aoi_gdf.to_crs(crs_value) if crs_value is not None else aoi_gdf
    # crs/resolution are always explicit here (never None), so output_geobox
    # only needs the AOI geometry -- no per-item raster metadata is required
    # to derive the parent grid, so an empty item list is passed rather than
    # running odc.stac.parse_items over every queried STAC item.
    parent_geobox = _output_geobox_for_aoi([], target, crs=crs_value, resolution=float(resolution))

    identity = WOfSCacheIdentity.from_request(
        request,
        shape=tuple(int(v) for v in parent_geobox.shape),
        transform=tuple(parent_geobox.affine)[:6],
    )

    with cache_writer_lock(cache_root, identity.request_digest):
        handle = create_cache_handle(cache_root, identity)

        already_done = set() if force else completed_years(handle)
        missing_years = sorted(requested_years - already_done)

        if not missing_years:
            if diagnostics_callback is not None:
                diagnostics_callback(_diagnostics_payload(0, 0))
            return handle

        phase_started = time.monotonic()
        query_elapsed = 0.0
        graph_count = 0
        all_item_ids: list[str] = []
        plan_diagnostics: list[dict[str, Any]] = []
        write_stats: list[Any] = []

        missing_start, missing_end = f"{missing_years[0]}-01-01", f"{missing_years[-1]}-12-31"
        if progress:
            print(f"[{aoi_name}] Searching STAC catalog for missing years ({missing_years[0]} to {missing_years[-1]})...", flush=True)
        phase_started = time.monotonic()
        items, _ = _query_wofs_items(
            stac_url, collection, aoi_gdf, missing_start, missing_end,
            item_cache_root=cache_root, force_item_refresh=force,
        )
        query_elapsed = time.monotonic() - phase_started
        if progress:
            print(f"[{aoi_name}] Found {len(items)} STAC scenes in {query_elapsed:.1f}s. Preparing Zarr acquisition...", flush=True)

        by_year = partition_items_by_year(items)
        graph_count = 0
        plan_diagnostics: list[dict[str, Any]] = []
        write_stats: list[Any] = []

        pruning_geom = (
            wet_aoi.geometry.union_all()
            if (wet_aoi is not None and hasattr(wet_aoi.geometry, "union_all"))
            else (wet_aoi.geometry.unary_union if wet_aoi is not None
                  else (target.geometry.union_all() if hasattr(target.geometry, "union_all")
                        else target.geometry.unary_union))
        )
        plan = plan_storage_aligned_slices(
            pruning_geom,
            shape=tuple(int(v) for v in parent_geobox.shape),
            transform=parent_geobox.affine,
            storage_chunk=512,
        )
        planned_shape = _planned_pixel_shape(plan)

        year_iter = missing_years
        if progress and missing_years:
            from tqdm.auto import tqdm

            tqdm_kwargs = {
                "total": len(missing_years),
                "desc": progress_desc if progress_desc else f"[{aoi_name}]",
                "unit": "yr",
            }
            if progress_position is not None:
                tqdm_kwargs["position"] = progress_position
                tqdm_kwargs["leave"] = True
            year_iter = tqdm(missing_years, **tqdm_kwargs)

        import gc
        from hydroseason._io_wofs_zarr import preflight_cache_space

        def _process_one_year(year: int):
            year_start, year_end = _year_date_bounds(year, request.start_date, request.end_date)
            year_items = by_year.get(year, ())

            if year_items:
                mask = build_wofs_year_graph(
                    list(year_items),
                    target,
                    year_start,
                    year_end,
                    geobox=parent_geobox,
                    chunk_x=chunk_x,
                    chunk_y=chunk_y,
                    time_chunk=time_chunk,
                    majority=majority,
                    groupby="solar_day",
                    resampling_policy=resampling_policy,
                )
            else:
                mask = _empty_year_mask(parent_geobox, year_start, year_end, target)

            p_diag = {
                "year": year,
                "selected_tile_pixels": plan.selected_tile_pixels,
                "reason": plan.reason,
                "n_windows": len(plan.windows),
            }

            year_months = len(
                pd.date_range(
                    pd.Timestamp(year_start).to_period("M").to_timestamp(),
                    pd.Timestamp(year_end).to_period("M").to_timestamp(),
                    freq="MS",
                )
            )

            preflight_cache_space(handle.path, shape=planned_shape, months=year_months)

            item_ids = tuple(item.id for item in year_items)
            final_year_path = Path(handle.path) / "years" / str(int(year))
            stats = write_annual_group(
                handle,
                year,
                mask,
                windows=plan.windows,
                item_ids=item_ids,
                overwrite=force or Path(_long_path(final_year_path)).exists(),
                compute_batch_size=compute_batch_size,
                read_workers=read_workers,
            )
            y_diag = {
                "year": int(year),
                "item_count": len(item_ids),
                "selected_tile_pixels": plan.selected_tile_pixels,
                "n_windows": len(plan.windows),
                "task_count": stats.task_count,
                "chunks_considered": stats.chunks_considered,
                "chunks_written": stats.chunks_written,
                "loaded_pixels": stats.loaded_pixels,
                "compute_seconds": getattr(stats, "compute_seconds", 0.0),
                "encode_write_seconds": getattr(stats, "encode_write_seconds", 0.0),
                "validation_seconds": getattr(stats, "validation_seconds", 0.0),
            }
            del mask
            gc.collect()
            return y_diag, stats, p_diag, item_ids, bool(year_items)

        year_diagnostics: list[dict[str, Any]] = []
        if year_workers > 1 and len(missing_years) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=min(year_workers, len(missing_years))) as pool:
                futures = {pool.submit(_process_one_year, yr): yr for yr in missing_years}
                for future in as_completed(futures):
                    y_diag, stats, p_diag, item_ids, was_graph = future.result()
                    if was_graph:
                        graph_count += 1
                    all_item_ids.extend(item_ids)
                    write_stats.append(stats)
                    plan_diagnostics.append(p_diag)
                    year_diagnostics.append(y_diag)
                    _write_acquisition_progress(handle, query_elapsed, [y_diag])
        else:
            for year in year_iter:
                y_diag, stats, p_diag, item_ids, was_graph = _process_one_year(year)
                if was_graph:
                    graph_count += 1
                all_item_ids.extend(item_ids)
                write_stats.append(stats)
                plan_diagnostics.append(p_diag)
                year_diagnostics.append(y_diag)
                _write_acquisition_progress(handle, query_elapsed, [y_diag])

        elapsed = time.monotonic() - phase_started
        _write_acquisition_manifest(
            handle,
            query_count=1,
            graph_count=graph_count,
            plan_diagnostics=plan_diagnostics,
            item_ids=tuple(item.id for item in items),
            write_stats=write_stats,
            elapsed_phases={"query_seconds": query_elapsed, "total_seconds": elapsed},
            year_diagnostics=year_diagnostics,
        )
        if diagnostics_callback is not None:
            diagnostics_callback(_diagnostics_payload(1, graph_count, write_stats))

    return handle


def _annual_fingerprints(handle: WOfSCacheHandle, years: list[int]) -> list[dict[str, Any]]:
    fingerprints = []
    for year in years:
        payload = _read_json(Path(handle.path) / "years" / str(int(year)) / _COMPLETE_FILENAME) or {}
        fingerprints.append(
            {
                "year": int(year),
                "item_digest": payload.get("item_digest"),
                "content_digest": payload.get("content_digest"),
                "chunks_considered": payload.get("chunks_considered"),
                "chunks_written": payload.get("chunks_written"),
                "loaded_pixels": payload.get("loaded_pixels"),
            }
        )
    return fingerprints


def _wet_aoi_sidecar_key(
    handle: WOfSCacheHandle,
    *,
    persistence_min: float,
    close_m: float,
    buffer_m: float,
    annual_fingerprints: list[dict[str, Any]],
) -> str:
    """A stable filename stem covering the cache identity AND the wet-AOI params.

    Hashing ``handle.identity`` together with ``persistence_min``/``close_m``/
    ``buffer_m`` means two calls that agree on all four reuse the same
    sidecar (a cache hit), while a call that changes any one of them -- even
    against the same completed cache -- gets a distinct filename rather than
    overwriting or silently reusing a sidecar built under different params.
    """
    payload = {
        "identity": handle.identity,
        "persistence_min": float(persistence_min),
        "close_m": float(close_m),
        "buffer_m": float(buffer_m),
        "annual_fingerprints": annual_fingerprints,
    }
    return _sha256_digest(payload)


def _wet_aoi_paths(
    handle: WOfSCacheHandle,
    *,
    persistence_min: float,
    close_m: float,
    buffer_m: float,
    annual_fingerprints: list[dict[str, Any]],
) -> tuple[Path, Path]:
    key = _wet_aoi_sidecar_key(
        handle,
        persistence_min=persistence_min,
        close_m=close_m,
        buffer_m=buffer_m,
        annual_fingerprints=annual_fingerprints,
    )
    wet_aoi_dir = Path(handle.path) / "wet_aoi"
    return wet_aoi_dir / f"{key}.geojson", wet_aoi_dir / f"{key}.identity.json"


def load_or_build_cached_wet_aoi(
    handle: WOfSCacheHandle,
    *,
    persistence_min: float = 0.0,
    close_m: float = 150.0,
    buffer_m: float = 300.0,
):
    """Derive (or reuse) a wet-AOI polygon purely from already-cached local WOfS counts.

    Opens every completed annual group's ``wet_count``/``clear_count``
    arrays (:func:`hydroseason._io_wofs_zarr.completed_years`) lazily via
    ``xr.open_zarr`` -- the same per-year opening pattern
    :func:`hydroseason._io_wofs_zarr.open_completed_mask_cache` uses -- sums
    them across years with Dask (never eagerly materialising a whole year in
    memory before summing), reduces the summed counts to a wet-AOI boolean
    with :func:`hydroseason._wet_aoi.compute_ever_wet_from_counts`, and
    vectorises/buffers it with :func:`hydroseason._wet_aoi.wet_aoi_polygon`.

    Nothing in this function's call graph queries STAC or rebuilds a Dask
    year graph (no ``_query_wofs_items``/``build_wofs_year_graph``): it
    operates purely on Zarr arrays already written to ``handle.path`` by a
    prior :func:`acquire_wofs_cache` run.

    The result is cached as a GeoJSON sidecar plus a JSON identity file
    under ``handle.path / "wet_aoi"``, both written atomically
    (:func:`hydroseason._io_wofs_zarr._write_json_atomic`). The sidecar
    filename is derived from a hash of the cache identity together with
    ``persistence_min``/``close_m``/``buffer_m`` (see
    :func:`_wet_aoi_sidecar_key`), so a later call with the same identity and
    the same three params reuses the existing sidecar instead of
    recomputing, while a call with different params for the same cache
    writes to a different filename rather than overwriting or ambiguating
    the previous one.

    Raises ``FileNotFoundError`` if ``handle`` has no completed years at all.
    """
    import geopandas as gpd

    from hydroseason._wet_aoi import compute_ever_wet_from_counts, wet_aoi_polygon

    years = sorted(completed_years(handle))
    if not years:
        raise FileNotFoundError(
            f"no completed WOfS annual group found at {Path(handle.path)!s}; "
            "load_or_build_cached_wet_aoi requires at least one completed year."
        )
    annual_fingerprints = _annual_fingerprints(handle, years)
    geojson_path, identity_path = _wet_aoi_paths(
        handle,
        persistence_min=persistence_min,
        close_m=close_m,
        buffer_m=buffer_m,
        annual_fingerprints=annual_fingerprints,
    )
    if Path(_long_path(geojson_path)).exists() and Path(_long_path(identity_path)).exists():
        wet_aoi = gpd.read_file(_long_path(geojson_path))
        wet_aoi.attrs["hydroseason_wet_aoi_identity"] = geojson_path.stem
        return wet_aoi

    import xarray as xr

    from hydroseason._io_wofs_zarr import _read_georef

    store_path = Path(handle.path)
    wet_arrays = []
    clear_arrays = []
    crs = None
    transform = None
    for year in years:
        year_path = store_path / "years" / str(int(year))
        opened = xr.open_zarr(
            _zarr_store(year_path), consolidated=False, mask_and_scale=False
        )
        # wet_count/clear_count are raw Zarr arrays written outside xarray's
        # to_zarr (see write_annual_group) and so carry no grid_mapping link
        # to the group's spatial_ref sibling variable -- only water_mask does
        # -- so the CRS/transform is read off water_mask via _read_georef
        # (the same helper open_completed_mask_cache uses) once per year and
        # reattached to wet_count/clear_count explicitly below.
        _mask_da, year_crs, year_transform = _read_georef(opened)
        if crs is None:
            crs = year_crs
            transform = year_transform
        wet_arrays.append(opened["wet_count"])
        clear_arrays.append(opened["clear_count"])

    summed_wet = sum(wet_arrays[1:], start=wet_arrays[0]) if len(wet_arrays) > 1 else wet_arrays[0]
    summed_clear = sum(clear_arrays[1:], start=clear_arrays[0]) if len(clear_arrays) > 1 else clear_arrays[0]
    if crs is not None:
        summed_wet = summed_wet.rio.write_crs(crs)
        summed_clear = summed_clear.rio.write_crs(crs)
    if transform is not None:
        from affine import Affine

        affine_transform = Affine(*transform)
        summed_wet = summed_wet.rio.write_transform(affine_transform)
        summed_clear = summed_clear.rio.write_transform(affine_transform)

    ever_wet = compute_ever_wet_from_counts(
        summed_wet, summed_clear, persistence_min=persistence_min
    )
    wet_aoi = wet_aoi_polygon(ever_wet, close_m=close_m, buffer_m=buffer_m)

    Path(_long_path(geojson_path.parent)).mkdir(parents=True, exist_ok=True)
    _write_geojson_atomic(geojson_path, wet_aoi)
    _write_json_atomic(
        identity_path,
        {
            "cache_identity": handle.identity,
            "request_digest": handle.request_digest,
            "persistence_min": float(persistence_min),
            "close_m": float(close_m),
            "buffer_m": float(buffer_m),
            "years": years,
            "annual_fingerprints": annual_fingerprints,
        },
    )
    wet_aoi.attrs["hydroseason_wet_aoi_identity"] = geojson_path.stem

    return wet_aoi


def _write_geojson_atomic(path: Path, gdf) -> None:
    """Write ``gdf`` as GeoJSON to ``path`` without ever leaving a partial file.

    Mirrors :func:`hydroseason._io_wofs_zarr._write_json_atomic`'s
    write-to-temp-then-``os.replace`` pattern (same directory, so the final
    rename is atomic on the same filesystem, and routed through
    :func:`hydroseason._io_wofs_zarr._long_path` so this also works past
    Windows' legacy ``MAX_PATH`` limit) rather than reimplementing a second
    atomic-write helper for JSON payloads -- this one only differs because
    ``gpd.GeoDataFrame.to_file`` writes to a path itself instead of
    returning bytes to write.
    """
    import os
    import tempfile

    parent = Path(_long_path(path.parent))
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(parent), prefix=f".{path.name}-", suffix=".tmp"
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        gdf.to_file(temp_path, driver="GeoJSON")
        os.replace(str(temp_path), _long_path(path))
    finally:
        temp_path.unlink(missing_ok=True)


def _aoi_digest(aoi_gdf) -> str:
    import hashlib

    payload = f"{aoi_gdf.crs}\n{aoi_gdf.to_json()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _output_digest(write_stats: list[Any]) -> str:
    """A stable digest over every year's :class:`AnnualWriteStats` this run wrote.

    Distinct from each year's own ``item_digest`` (a hash of *input* STAC
    item IDs, recorded by :func:`write_annual_group` itself): this digest
    covers what was actually written -- chunk/pixel counts and each year's
    ``item_digest`` -- so two acquisition runs that wrote byte-identical
    output hash identically, and a run that wrote nothing new (all years
    already completed) contributes an empty, stable digest.
    """
    import hashlib
    import json

    payload = [
        {
            "year": stats.year,
            "chunks_considered": stats.chunks_considered,
            "chunks_written": stats.chunks_written,
            "loaded_pixels": stats.loaded_pixels,
            "item_digest": stats.item_digest,
        }
        for stats in sorted(write_stats, key=lambda stats: stats.year)
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _write_acquisition_progress(
    handle: WOfSCacheHandle,
    query_seconds: float,
    year_diagnostics: list[dict[str, Any]],
) -> None:
    from hydroseason._io_wofs_zarr import _read_json, _write_json_atomic

    manifest_path = Path(handle.path) / "manifest.json"
    manifest = _read_json(manifest_path) or {}
    acq = manifest.setdefault("acquisition", {})
    existing = {d["year"]: d for d in acq.get("year_diagnostics", [])}
    for d in year_diagnostics:
        existing[d["year"]] = d
    acq["year_diagnostics"] = [existing[y] for y in sorted(existing)]
    _write_json_atomic(manifest_path, manifest)


def _write_acquisition_manifest(
    handle: WOfSCacheHandle,
    *,
    query_count: int,
    graph_count: int,
    plan_diagnostics: list[dict[str, Any]],
    item_ids: tuple[str, ...],
    write_stats: list[Any],
    elapsed_phases: dict[str, float],
    year_diagnostics: list[dict[str, Any]] = (),
) -> None:
    """Record acquisition provenance into the store's root manifest.json.

    Read-modify-write, preserving every key
    :func:`hydroseason._io_wofs_zarr.create_cache_handle`/``_validate_hit``
    already depend on (``identity``/``request_digest``), mirroring
    :func:`hydroseason._io_wofs_zarr._record_completed_year`'s pattern.
    """
    import hashlib
    import json

    from hydroseason._io_wofs_zarr import _read_json, _write_json_atomic

    manifest_path = Path(handle.path) / "manifest.json"
    manifest = _read_json(manifest_path) or {}
    item_digest = hashlib.sha256(
        json.dumps({"item_ids": sorted(item_ids)}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    acq = manifest.get("acquisition", {})
    existing_diags = {d["year"]: d for d in acq.get("year_diagnostics", [])}
    for d in year_diagnostics:
        existing_diags[d["year"]] = d

    manifest["acquisition"] = {
        "query_count": acq.get("query_count", 0) + query_count,
        "graph_count": acq.get("graph_count", 0) + graph_count,
        "plan_diagnostics": acq.get("plan_diagnostics", []) + plan_diagnostics,
        "item_ids": sorted(item_ids),
        "item_digest": item_digest,
        "output_digest": _output_digest(write_stats),
        "package_versions": _package_versions(),
        "elapsed_phases": elapsed_phases,
        "year_diagnostics": [existing_diags[y] for y in sorted(existing_diags)],
    }
    _write_json_atomic(manifest_path, manifest)


__all__ = [
    "partition_items_by_year",
    "build_wofs_year_graph",
    "acquire_wofs_cache",
    "load_or_build_cached_wet_aoi",
]
