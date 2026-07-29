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
from typing import Any, Callable, Literal

import pandas as pd

from hydroseason._io_dea_stats import (
    DEAStatsUnavailable,
    WetPlanningFootprint,
    fetch_dea_stats_wet_aoi,
    wet_mask_digest,
)
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
    write_empty_annual_group,
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


def _wet_aoi_from_planning_footprint(footprint: WetPlanningFootprint):
    """Vectorize a prepared :class:`WetPlanningFootprint`'s native mask into
    a ``wet_aoi``-shaped GeoDataFrame, for reuse by :func:`build_wofs_year_graph`'s
    existing ``wet_aoi`` pixel-clip path (see :func:`hydroseason._io_geo._clip_to_aoi`).

    ``footprint.native_mask`` is already a conservative, provenance-checked
    superset of ever-wet pixels (``build_wet_planning_footprint``'s whole
    contract) -- this reuses the SAME vectoriser
    (:func:`hydroseason._wet_aoi.wet_aoi_polygon`) the existing
    ``wet_mask="dea_stats"`` path already trusts, at the native (30 m, by
    default) resolution the footprint carries, rather than the coarser
    ``coarse_mask``. This is the one place a footprint's mask is turned into
    a polygon on the acquisition path -- ``build_wet_planning_footprint``
    itself never does (``geometry`` stays ``None`` there); an
    ``acquire_wofs_cache`` caller supplying a prepared footprint is exactly
    the "a consumer explicitly needs one" case that justifies it here.

    Distinct from the coarse ``active_windows``, which prune WHICH storage
    windows are read at all (the coarse half of spatial pruning, replacing
    :func:`hydroseason._spatial_plan.plan_storage_aligned_slices`'s
    default whole-AOI scan) -- this vectorised polygon prunes individual
    pixels WITHIN a read window (the fine-grain half), mirroring exactly how
    an explicit ``wet_aoi`` combines with the coarse plan today.
    """
    from hydroseason._wet_aoi import wet_aoi_polygon

    return wet_aoi_polygon(footprint.native_mask, close_m=0.0, buffer_m=0.0)


def _resolve_wet_aoi(
    stac_url: str,
    aoi_gdf,
    years: list[int],
    *,
    wet_aoi,
    wet_mask: str,
    crs,
    resolution: float,
    progress: bool,
    aoi_name: str,
    local_wet_aoi_handle: "WOfSCacheHandle | None" = None,
):
    """Decide which wet mask (if any) to prune this acquisition with.

    Returns ``(wet_aoi, wet_mask_sha256)``. Both are ``None`` when no
    pruning applies -- the full-coverage path, byte-identical to the
    behaviour before pruning existed.

    Preference order:

    1. An explicit caller-supplied ``wet_aoi``. The caller has asserted this
       is a valid superset; trust it and never spend a network call.
    2. Locally cached wet counts: only consulted when ``wet_mask`` requests
       pruning at all (i.e. ``wet_mask != "off"``). If ``local_wet_aoi_handle``
       points at a full-coverage store that has already completed every year
       in ``years``, derive the mask from its ``wet_count``/``clear_count``
       arrays (:func:`load_or_build_cached_wet_aoi`) -- free, no network,
       and an exact superset for the years it covers. Any failure here
       (no completed years yet, years that don't cover the request, or any
       other exception) falls through to the next level rather than
       propagating.
    3. ``wet_mask="dea_stats"``: fetch the DEA Water Observation Statistics
       summaries.
    4. Nothing -- no pruning.

    ``wet_mask="off"`` with no explicit ``wet_aoi`` always returns
    ``(None, None)``, regardless of whether ``local_wet_aoi_handle`` is
    supplied and regardless of whether that handle could otherwise resolve a
    usable mask. This is enforced here independently of the caller -- it must
    not depend on any caller only ever passing a handle when pruning was
    requested.

    Fails OPEN in every failure case. A mask that is wrong, partial, or
    empty would silently prune real water into permanent ``-2``, so any
    doubt drops back to a full read rather than pruning on a bad mask.
    """
    if wet_aoi is not None:
        return wet_aoi, wet_mask_digest(wet_aoi)

    if local_wet_aoi_handle is not None and wet_mask != "off":
        try:
            covered_years = completed_years(local_wet_aoi_handle)
            if set(years) <= covered_years:
                resolved = load_or_build_cached_wet_aoi(local_wet_aoi_handle)
                if progress:
                    print(
                        f"[{aoi_name}] Pruning reads to the locally cached wet mask.",
                        flush=True,
                    )
                return resolved, wet_mask_digest(resolved)
        except Exception:
            # No completed years yet, years don't cover the request, or any
            # other failure: this level doesn't apply. Fall through to
            # dea_stats -- never treat this as "no pruning" if a later level
            # might still succeed.
            pass

    if wet_mask != "dea_stats":
        return None, None

    try:
        resolved = fetch_dea_stats_wet_aoi(
            stac_url, aoi_gdf, years, crs=crs, resolution=float(resolution)
        )
    except DEAStatsUnavailable as exc:
        if progress:
            print(
                f"[{aoi_name}] DEA statistics wet mask unavailable ({exc}); "
                "falling back to a full-coverage read.",
                flush=True,
            )
        return None, None
    except Exception as exc:
        if progress:
            print(
                f"[{aoi_name}] DEA statistics wet mask failed "
                f"({type(exc).__name__}: {exc}); falling back to a full-coverage read.",
                flush=True,
            )
        return None, None

    if progress:
        print(f"[{aoi_name}] Pruning reads to the DEA statistics wet mask.", flush=True)
    return resolved, wet_mask_digest(resolved)


def _probe_local_wet_aoi_handle(
    cache_root: str | Path,
    base_request_kwargs: dict[str, Any],
    *,
    wet_aoi: Any,
    wet_mask: str,
) -> "WOfSCacheHandle | None":
    """Look up an already-completed full-coverage (unpruned) local store for
    ``base_request_kwargs``, for :func:`_resolve_wet_aoi` to prefer over a
    ``dea_stats`` network call (see that function's preference order).

    Shared verbatim between :func:`acquire_wofs_cache`'s own resolution and
    any caller (e.g. the ``--profile`` diagnostics block in
    ``scripts/extract_water_extent_csv.py``) that needs to reproduce exactly
    which store the main call will resolve to, so the two never diverge.

    Only attempted when the caller has opted into pruning at all (``wet_aoi``
    explicit, or ``wet_mask != "off"``); returns ``None`` otherwise, matching
    ``wet_mask="off"``'s no-pruning, byte-identical-to-legacy contract.
    """
    if wet_aoi is not None or wet_mask == "off":
        return None
    return resolve_cached_request(
        cache_root,
        WOfSCacheRequest(**base_request_kwargs, wet_mask_sha256=None),
        offline=True,
    )


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
    wet_mask: Literal["off", "dea_stats"] = "off",
    planning_footprint: WetPlanningFootprint | None = None,
    composite_bundle: Literal["legacy", "hydrofragments_v1"] = "legacy",
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

    A failed year is deferred while the remaining missing years continue,
    then retried once after the first pass. Successfully published years stay
    resumable even if a deferred year fails again; the final error lists only
    years still incomplete after that retry.

    ``planning_footprint`` accepts an already-built
    :class:`hydroseason._io_dea_stats.WetPlanningFootprint` (see
    :func:`hydroseason._io_dea_stats.build_wet_planning_footprint`), reusing
    ONE planning footprint across both acquisition (here) and later analysis
    -- the caller builds it once (a single DEA-statistics STAC query) and
    hands it to every acquisition call, instead of each acquisition
    independently re-deriving its own mask. Passing a prepared
    ``planning_footprint`` never queries DEA statistics itself; it plugs
    directly into the same pruning machinery ``wet_aoi``/``wet_mask="dea_stats"``
    already drive (a vectorised wet region for the fine-grain pixel clip, and
    storage-aligned windows for the coarse read-planning half -- see
    :func:`_wet_aoi_from_planning_footprint`). ``wet_aoi`` and
    ``planning_footprint`` are mutually exclusive pruning sources: supplying
    both raises ``ValueError`` (ambiguous precedence), matching this
    function's existing single-source-of-pruning contract.

    ``composite_bundle`` selects the acquisition's output semantics.
    ``"legacy"`` (the default) preserves every existing hydroseason result
    and cache identity byte-for-byte. ``"hydrofragments_v1"`` is new
    behaviour (dual-composite extent counts, analysis-footprint metadata --
    see the plan's later tasks) that is recorded in cache identity here so a
    ``"legacy"`` and a ``"hydrofragments_v1"`` run of otherwise-identical
    parameters never share a store; this task only records the flag and
    threads it through, it does not implement the ``"hydrofragments_v1"``
    behaviour itself.
    """
    if wet_aoi is not None and planning_footprint is not None:
        raise ValueError(
            "acquire_wofs_cache received both wet_aoi and planning_footprint; "
            "these are mutually exclusive pruning sources (ambiguous "
            "precedence) -- pass only one."
        )
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
    requested_years = list(range(start.year, end.year + 1))

    # Every field of WOfSCacheRequest except wet_mask_sha256, shared by the
    # offline lookup, the unpruned local-cache probe, and the final request
    # built below -- kept in one place so the three never drift apart.
    base_request_kwargs = dict(
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
        composite_bundle=composite_bundle,
    )

    # A prepared planning_footprint carries its own cache-identity fields
    # (digest/factor/safety_cells/covered_years) regardless of offline mode --
    # unlike wet_mask_sha256 (only computable from an explicit wet_aoi, or by
    # resolving one over the network), every one of these is already sitting
    # on the footprint object the caller handed in, so offline lookups get
    # them too without touching the network.
    footprint_request_kwargs = (
        dict(
            footprint_digest=planning_footprint.digest,
            footprint_factor=int(planning_footprint.factor),
            footprint_safety_cells=int(planning_footprint.safety_cells),
            footprint_covered_years=tuple(sorted(planning_footprint.covered_years)),
        )
        if planning_footprint is not None
        else {}
    )

    # Resolve the wet mask BEFORE building the request: its digest is part of
    # the cache identity, so a pruned run and a full-coverage run of otherwise
    # identical parameters resolve to different stores and can never mix.
    #
    # ``offline=True`` must never touch the network or a not-yet-existing
    # local store, so it skips mask resolution entirely and looks up the
    # request directly (with wet_mask_sha256 set only from an explicit
    # caller-supplied wet_aoi) -- matching the pre-existing offline contract
    # byte-for-byte when the caller passes neither ``wet_aoi`` nor ``wet_mask``.
    if offline:
        offline_wet_mask_sha256 = (
            planning_footprint.digest
            if planning_footprint is not None
            else (wet_mask_digest(wet_aoi) if wet_aoi is not None else None)
        )
        request = WOfSCacheRequest(
            **base_request_kwargs,
            **footprint_request_kwargs,
            wet_mask_sha256=offline_wet_mask_sha256,
        )
        handle = require_cached_request(cache_root, request, offline=True)
        if diagnostics_callback is not None:
            diagnostics_callback(_diagnostics_payload(0, 0))
        return handle

    # A prepared planning_footprint is a caller-supplied, already-resolved
    # pruning source: skip _resolve_wet_aoi (and its local-cache/dea_stats
    # network fallbacks) entirely -- consuming a prepared footprint must
    # never trigger another DEA-statistics query. Vectorise it into the same
    # wet_aoi shape build_wofs_year_graph's existing pixel-clip path expects
    # (see _wet_aoi_from_planning_footprint), so the fine-grain clip and the
    # coarse storage-aligned window plan below both reuse it exactly like an
    # explicit wet_aoi would.
    if planning_footprint is not None:
        wet_aoi = _wet_aoi_from_planning_footprint(planning_footprint)
        wet_mask_sha256 = planning_footprint.digest
        if progress:
            print(
                f"[{aoi_name}] Pruning reads to a prepared DEA planning footprint "
                f"(factor={planning_footprint.factor}, "
                f"safety_cells={planning_footprint.safety_cells}, "
                f"years={sorted(planning_footprint.covered_years)}); "
                "no additional DEA-statistics query issued.",
                flush=True,
            )
    else:
        # Probe for an already-completed full-coverage (unpruned) store for
        # this same request. If one exists and its completed years cover the
        # request, its wet_count/clear_count arrays are a free, network-free,
        # exact superset mask -- ranked above dea_stats (see _resolve_wet_aoi).
        #
        # Only attempted when the caller has opted into pruning at all
        # (wet_aoi explicit, or wet_mask != "off"): wet_mask="off" with no
        # explicit wet_aoi is the default, no-pruning path, and must stay
        # byte-identical to acquisition before pruning existed -- including
        # never resolving to a *different* (pruned) store digest than before
        # even when a completed full-coverage store already happens to exist.
        local_wet_aoi_handle = _probe_local_wet_aoi_handle(
            cache_root, base_request_kwargs, wet_aoi=wet_aoi, wet_mask=wet_mask
        )

        wet_aoi, wet_mask_sha256 = _resolve_wet_aoi(
            stac_url,
            aoi_gdf,
            requested_years,
            wet_aoi=wet_aoi,
            wet_mask=wet_mask,
            crs=crs,
            resolution=float(resolution),
            progress=progress,
            aoi_name=aoi_name,
            local_wet_aoi_handle=local_wet_aoi_handle,
        )

    request = WOfSCacheRequest(
        **base_request_kwargs, **footprint_request_kwargs, wet_mask_sha256=wet_mask_sha256
    )

    requested_years = set(requested_years)

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
                    wet_aoi=wet_aoi,
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
            overwrite = force or Path(_long_path(final_year_path)).exists()
            try:
                if year_items:
                    stats = write_annual_group(
                        handle,
                        year,
                        mask,
                        windows=plan.windows,
                        item_ids=item_ids,
                        overwrite=overwrite,
                        compute_batch_size=compute_batch_size,
                        read_workers=read_workers,
                    )
                else:
                    # No source observations: every pixel is -2 by
                    # construction, so skip computing and hashing every block
                    # only to write none of them.
                    stats = write_empty_annual_group(
                        handle, year, mask, overwrite=overwrite
                    )
            finally:
                del mask
                gc.collect()
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
            return y_diag, stats, p_diag, item_ids, bool(year_items)

        year_diagnostics: list[dict[str, Any]] = []
        deferred_years: list[int] = []

        def _record_year_result(result) -> None:
            nonlocal graph_count
            y_diag, stats, p_diag, item_ids, was_graph = result
            if was_graph:
                graph_count += 1
            all_item_ids.extend(item_ids)
            write_stats.append(stats)
            plan_diagnostics.append(p_diag)
            year_diagnostics.append(y_diag)
            _write_acquisition_progress(handle, query_elapsed, [y_diag])

        def _defer_failed_year(year: int, exc: Exception) -> None:
            deferred_years.append(int(year))
            if progress:
                print(
                    f"[{aoi_name}] Year {year} failed ({type(exc).__name__}: {exc}); "
                    "deferring until the remaining years finish.",
                    flush=True,
                )

        if year_workers > 1 and len(missing_years) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=min(year_workers, len(missing_years))) as pool:
                futures = {pool.submit(_process_one_year, yr): yr for yr in missing_years}
                for future in as_completed(futures):
                    year = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        _defer_failed_year(year, exc)
                    else:
                        _record_year_result(result)
        else:
            for year in year_iter:
                try:
                    result = _process_one_year(year)
                except Exception as exc:
                    _defer_failed_year(year, exc)
                else:
                    _record_year_result(result)

        terminal_failures: dict[int, str] = {}
        if deferred_years:
            if progress:
                years_text = ", ".join(str(year) for year in deferred_years)
                print(f"[{aoi_name}] Retrying deferred years: {years_text}", flush=True)
            for year in deferred_years:
                try:
                    result = _process_one_year(year)
                except Exception as exc:
                    terminal_failures[year] = f"{type(exc).__name__}: {exc}"
                else:
                    _record_year_result(result)

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
            planning_footprint=planning_footprint,
            composite_bundle=composite_bundle,
        )
        if diagnostics_callback is not None:
            diagnostics_callback(_diagnostics_payload(1, graph_count, write_stats))
        if terminal_failures:
            details = "; ".join(
                f"{year}: {message}" for year, message in sorted(terminal_failures.items())
            )
            raise RuntimeError(f"WOfS acquisition failed after deferred retry ({details})")

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
    planning_footprint: "WetPlanningFootprint | None" = None,
    composite_bundle: str = "legacy",
) -> None:
    """Record acquisition provenance into the store's root manifest.json.

    Read-modify-write, preserving every key
    :func:`hydroseason._io_wofs_zarr.create_cache_handle`/``_validate_hit``
    already depend on (``identity``/``request_digest``), mirroring
    :func:`hydroseason._io_wofs_zarr._record_completed_year`'s pattern.

    ``planning_footprint``/``composite_bundle`` are recorded as a small
    ``planning_footprint`` diagnostics block (source collection/version,
    factor, safety halo, covered years, digest, and the composite bundle
    mode) purely for human/tooling visibility -- they already independently
    determine cache identity via :class:`WOfSCacheRequest`'s
    ``footprint_*``/``composite_bundle`` fields (see
    :mod:`hydroseason._io_wofs_zarr`); this block does not itself gate
    anything.
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
        "composite_bundle": composite_bundle,
        "planning_footprint": (
            {
                "digest": planning_footprint.digest,
                "factor": int(planning_footprint.factor),
                "safety_cells": int(planning_footprint.safety_cells),
                "covered_years": list(sorted(planning_footprint.covered_years)),
                "source_collection": planning_footprint.source_collection,
                "source_version": planning_footprint.source_version,
            }
            if planning_footprint is not None
            else None
        ),
    }
    _write_json_atomic(manifest_path, manifest)


__all__ = [
    "partition_items_by_year",
    "build_wofs_year_graph",
    "acquire_wofs_cache",
    "load_or_build_cached_wet_aoi",
]
