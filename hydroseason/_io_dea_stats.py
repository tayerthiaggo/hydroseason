"""DEA Water Observation Statistics -> wet-AOI mask.

Fetches Geoscience Australia's pre-computed WOfS frequency summaries
(``ga_ls_wo_fq_myear_3``, all-time; ``ga_ls_wo_fq_cyear_3``, per calendar
year) and reduces them to a buffered ever-wet polygon. Acquiring
``ga_ls_wo_3`` daily observations only where that polygon says water has
ever been observed is the whole point: a catchment bounding box is mostly
land that never floods, and every pixel of it currently costs an S3 range
GET plus a reprojection.

The mask must be a SUPERSET of every pixel ever water in the requested
period. Outside it, a pruned acquisition writes -2 forever, and no reader
can tell that apart from genuinely dry. Two consequences drive the design:

* Years are UNIONED, never intersected. A pixel wet in one year only must
  survive.
* Any doubt fails open. Every failure path raises ``DEAStatsUnavailable``
  rather than returning a small or empty mask, so the caller falls back to
  a full-coverage read instead of silently pruning real water away.

All geospatial imports stay inside function bodies, per the package rule.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Collection, Mapping, Sequence

if TYPE_CHECKING:
    import geopandas
    import xarray as xr

    from hydroseason._historical_water_mask import HistoricalWaterMask
    from hydroseason._spatial_plan import GridWindow

# The all-time summary: one small raster covering the full WOfS archive.
# Cheap, and the primary source.
DEA_STATS_ALLTIME_COLLECTION = "ga_ls_wo_fq_myear_3"
# The per-calendar-year summary. Unioned over the requested years so the mask
# provably covers the period being acquired even when the all-time product
# lags it or was regenerated under different filtering.
DEA_STATS_ANNUAL_COLLECTION = "ga_ls_wo_fq_cyear_3"

# The band carrying the number of water observations per pixel. > 0 means
# "water was observed here at least once", which is exactly the superset
# condition. Deliberately NOT the `frequency` band: frequency is a ratio that
# rounds small counts toward zero.
COUNT_WET_BAND = "count_wet"
# The companion band: the number of CLEAR (cloud/shadow/nodata-free)
# observations per pixel, regardless of wet/dry. `count_wet / count_clear`
# is exactly DEA's own `frequency` band definition, which is why
# `open_wo_statistics` requests these two raw counts and derives frequency
# itself rather than also requesting the precomputed ratio.
COUNT_CLEAR_BAND = "count_clear"

# Default STAC product for `open_wo_statistics`: the all-time frequency
# summary. Matches DEA_STATS_ALLTIME_COLLECTION -- kept as a separate public
# constant/default because `open_wo_statistics` is a general-purpose native
# loader (any DEA WO Statistics product), not specifically the wet-AOI path.
DEFAULT_WO_STATISTICS_PRODUCT = DEA_STATS_ALLTIME_COLLECTION
DEFAULT_WO_STATISTICS_STAC_URL = "https://explorer.sandbox.dea.ga.gov.au/stac"

# The on-disk WOfS storage tiling unit used elsewhere in the package (see
# plan_storage_aligned_slices's default in _spatial_plan.py / its
# storage_chunk=512 call site in _io_wofs_acquire.py). build_wet_planning_footprint
# snaps its active_windows onto this same stride so a later acquisition pass
# reads whole storage chunks.
_WOFS_STORAGE_CHUNK_PIXELS = 512

# Wall-clock ceiling for the STAC search phase of open_wo_statistics. This is
# the "overall load deadline" from the task brief: odc.stac.load itself
# builds a lazy Dask graph and never touches the network, so the only phase
# that can hang is the STAC catalog search. Bounding it means a zoning-source
# failure here returns control (and lets the local-cube zoning path proceed)
# instead of hanging the caller indefinitely.
STAC_SEARCH_DEADLINE_S = 60.0
# Per-request connect/read timeouts asked of the STAC HTTP client.
STAC_CONNECT_TIMEOUT_S = 15.0
STAC_READ_TIMEOUT_S = 30.0


class DEAStatsUnavailable(RuntimeError):
    """Required DEA Statistics data could not be established safely.

    Raised for every failure mode -- unreachable STAC, no matching items, a
    load error, or a mask with no wet pixels at all. Policy belongs to the
    caller: an optional planning/pruning mask may fall back to a full-coverage
    read, while a fixed historical mask that defines the scientific
    denominator must stop rather than silently change that denominator.
    """


class WoStatisticsUnavailable(DEAStatsUnavailable):
    """`open_wo_statistics` could not resolve a dataset for this AOI/product.

    Raised for an unreachable STAC endpoint, a search that exceeds the load
    deadline, or a search that returns no items. This loader never returns a
    partial or empty-but-successful result. Callers decide whether their use
    is optional (planning may fall back) or scientific identity (the fixed
    historical denominator must remain fatal).

    Deliberately a SUBCLASS of :class:`DEAStatsUnavailable`, not a sibling:
    this module's contract is that every failure path raises
    ``DEAStatsUnavailable``, and the package's fail-open handlers are written
    as ``except DEAStatsUnavailable``. As siblings, an unreachable statistics
    endpoint -- the most common failure of all -- slipped past every one of
    them.
    """


# Wall-clock budget for one source's STAC search + COG read + dask compute,
# combined. Per-request GDAL/pystac_client timeouts bound a single socket,
# but a large catchment fans out to many tile requests -- with retries, that
# can still run for minutes with no overall cap. This is the backstop.
SOURCE_TIMEOUT_S = 120.0


def _run_with_timeout(fn, timeout_s: float):
    """Run ``fn()`` in a worker thread; raise ``TimeoutError`` past timeout.

    A thread (not ``signal.alarm``) so this works on Windows, where the
    overnight extraction runs. Deliberately does NOT use the executor as a
    context manager: ``shutdown(wait=True)`` on exit would block on the
    still-running worker and defeat the timeout. There is no way to forcibly
    kill a Python thread -- an orphaned worker is left to finish or die on
    its own, and the un-joined pool is garbage-collected once it does.
    """
    import concurrent.futures

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    finally:
        pool.shutdown(wait=False)


def _load_count_wet(stac_url: str, collection: str, year: int | None, geobox):
    """Load the ``count_wet`` band for one collection over ``geobox``.

    ``year=None`` requests the all-time product (no datetime filter).
    """
    import odc.stac
    import pystac_client
    import rioxarray  # noqa: F401  (registers the .rio accessor used downstream)

    from hydroseason._io_geo import _configure_cog_read_env

    _configure_cog_read_env()

    search_kwargs = {
        "collections": [collection],
        "bbox": list(geobox.extent.to_crs("EPSG:4326").boundingbox),
        "limit": 1000,
    }
    if year is not None:
        search_kwargs["datetime"] = f"{year}-01-01/{year}-12-31"

    # (connect, read) timeout -- a hung STAC connection otherwise blocks
    # forever, since pystac_client's default is None (no bound).
    odc.stac.configure_rio(
        cloud_defaults=True,
        aws={"aws_unsigned": True},
    )
    client = pystac_client.Client.open(
        stac_url,
        timeout=(STAC_CONNECT_TIMEOUT_S, STAC_READ_TIMEOUT_S),
    )
    items = list(client.search(**search_kwargs).items())
    if not items:
        raise DEAStatsUnavailable(
            f"no {collection} items for {'all time' if year is None else year}"
        )

    dataset = odc.stac.stac_load(
        items,
        bands=[COUNT_WET_BAND],
        geobox=geobox,
        chunks={"x": 2048, "y": 2048},
        # Summary rasters are counts, and this is a presence test (> 0), so
        # any resampling that can only preserve or raise a nonzero count is
        # safe. Nearest never invents zeros where data exists.
        resampling="nearest",
    )
    # Collapse the (usually length-1) time axis: a pixel wet in ANY returned
    # summary is wet.
    return dataset[COUNT_WET_BAND].max("time") if "time" in dataset.dims else dataset[COUNT_WET_BAND]


def open_wo_statistics(
    aoi: Any,
    *,
    product: str = DEFAULT_WO_STATISTICS_PRODUCT,
    stac_url: str = DEFAULT_WO_STATISTICS_STAC_URL,
    resolution: float = 30.0,
    crs: str = "EPSG:3577",
    chunks: Mapping[str, int] | None = None,
) -> "xr.Dataset":
    """Load native DEA Water Observation Statistics for ``aoi``.

    Public, general-purpose statistics loader: a single STAC search against
    ``product`` (default the all-time ``ga_ls_wo_fq_myear_3`` summary),
    requesting exactly the two raw count bands (``count_wet``,
    ``count_clear``) and deriving ``frequency`` (0-100) lazily as
    ``100 * count_wet / count_clear``. This is the SAME ratio DEA's own
    precomputed ``frequency`` band encodes, requested this way so the
    derivation is explicit and auditable via ``provenance`` rather than
    trusting an opaque upstream band.

    Unlike :func:`fetch_dea_stats_wet_aoi`, this function does no planning
    reduction: no union-of-years, no vectorisation, no buffering. It returns
    the raw, dask-backed statistics cube at whatever native grid ``crs`` and
    ``resolution`` describe -- by default DEA's native 30 m WOfS/Albers grid.
    Turning statistics into a planning mask is a separate, later concern
    (``WetPlanningFootprint`` / ``build_wet_planning_footprint``, not part of
    this function).

    ``resolution``/``crs`` are passed to ``odc.stac.load`` explicitly so the
    output grid is never implicitly resampled or coarsened; there is no
    scientific-resolution knob here; callers that need a coarser working
    grid resample the *returned* dataset themselves, deliberately, downstream.

    Returns a lazy (Dask-backed) ``xarray.Dataset`` with data variables
    ``count_wet``, ``count_clear``, ``frequency`` and ``.attrs["provenance"]``
    recording ``product``, ``stac_url``, the resolved STAC item IDs, and how
    ``frequency`` was derived. Never calls ``.load()``/``.compute()``.

    Raises :class:`WoStatisticsUnavailable` (a :class:`DEAStatsUnavailable`)
    if the endpoint is unreachable, or the STAC search fails, times out, or
    returns no items. Does not raise on a geographic CRS -- CRS
    (``guard_area_metric_crs``); this loader is source-agnostic and hands
    whatever grid was asked for, unsigned COG reads and all, straight back.
    """
    import concurrent.futures

    import odc.stac
    import pystac_client

    from hydroseason._io_geo import _configure_cog_read_env, _crs_value, load_aoi

    aoi_gdf = load_aoi(aoi)
    crs_value = _crs_value(crs)
    target = aoi_gdf.to_crs(crs_value) if crs_value is not None else aoi_gdf
    bbox = list(target.to_crs("EPSG:4326").total_bounds)

    # Scope the unsigned-COG/GDAL env to this call: snapshot every key
    # _configure_cog_read_env might set, apply it (setdefault, same as every
    # other hydroseason STAC loader), then restore the caller's prior
    # environment afterwards rather than leaving our defaults installed.
    # Safe for these keys specifically because odc.stac.configure_rio (called
    # below) installs odc-stac's OWN rasterio environment for the lazy COG
    # reads, so they do not need to survive in os.environ to take effect.
    import os

    env_keys = (
        "AWS_NO_SIGN_REQUEST", "GDAL_DISABLE_READDIR_ON_OPEN",
        "GDAL_HTTP_MULTIPLEX", "GDAL_HTTP_VERSION", "VSI_CACHE",
        "VSI_CACHE_SIZE", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS",
        "GDAL_HTTP_MAX_RETRY", "GDAL_HTTP_RETRY_DELAY", "GDAL_HTTP_RETRY_CODES",
        "GDAL_HTTP_TIMEOUT", "GDAL_HTTP_CONNECTTIMEOUT",
        "GDAL_HTTP_MAX_TOTAL_CONNECTIONS",
    )
    # PROJ_LIB/PROJ_DATA are deliberately NOT restored. This function returns a
    # LAZY dask graph whose reprojection runs long after it returns, and that
    # reprojection reads the PROJ database named by these variables. A
    # system-wide value -- e.g. a PostGIS install, which sets PROJ_LIB
    # machine-wide on Windows -- points at a proj.db too old for pyproj
    # ("DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 6 is expected"),
    # and every lazy read of the returned cube then dies with
    # pyproj.exceptions.ProjError. _configure_cog_read_env repoints them at a
    # known-good bundled database precisely to avoid that, so putting the
    # hostile value back on the way out would re-arm the failure for the
    # caller. Leaving the working database installed is the whole point.
    before = {key: os.environ.get(key) for key in env_keys}
    try:
        _configure_cog_read_env()

        # Client.open performs the first network round-trip (the STAC
        # landing page / conformance fetch), so it belongs INSIDE the
        # conversion block. Left outside it, an unreachable endpoint or a
        # hostile proxy escaped as a raw pystac_client.APIError and broke
        # this module's documented fail-open contract at the one boundary
        # users hit first.
        try:
            client = pystac_client.Client.open(
                stac_url,
                timeout=(STAC_CONNECT_TIMEOUT_S, STAC_READ_TIMEOUT_S),
            )
            search = client.search(
                collections=[product],
                bbox=bbox,
                limit=1000,
            )
            items = _run_with_timeout(
                lambda: list(search.items()),
                STAC_SEARCH_DEADLINE_S,
            )
        except (TimeoutError, concurrent.futures.TimeoutError) as exc:
            raise WoStatisticsUnavailable(
                f"DEA Water Observation Statistics search at {stac_url} "
                f"exceeded the {STAC_SEARCH_DEADLINE_S:g}s deadline"
            ) from exc
        except WoStatisticsUnavailable:
            raise
        except Exception as exc:
            raise WoStatisticsUnavailable(
                f"DEA Water Observation Statistics STAC search failed for "
                f"product '{product}' at {stac_url}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if not items:
            raise WoStatisticsUnavailable(
                f"no {product} items found for this AOI at {stac_url}"
            )

        item_ids = [getattr(item, "id", None) for item in items]
        time_span = _item_time_span(items)

        load_kwargs: dict[str, Any] = dict(
            bands=[COUNT_WET_BAND, COUNT_CLEAR_BAND],
            crs=crs_value,
            resolution=resolution,
            geopolygon=target.geometry,
        )
        if chunks is not None:
            load_kwargs["chunks"] = dict(chunks)
        else:
            load_kwargs["chunks"] = {"x": 2048, "y": 2048}

        # configure_rio installs odc-stac's Rasterio environment for lazy
        # COG reads that happen after this function has returned. The worker
        # thread used to enforce STAC search deadlines cannot be killed by
        # Python; timeout returns control while that orphaned request finishes.
        odc.stac.configure_rio(
            cloud_defaults=True,
            aws={"aws_unsigned": True},
        )
        dataset = odc.stac.load(items, **load_kwargs)
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    if "time" in dataset.dims:
        # Statistics products are one summary raster per queried period, but
        # a search can still resolve more than one item (e.g. overlapping
        # Albers tiles for a large AOI): collapse the time axis by summing
        # per-pixel counts across contributing items rather than reducing to
        # a single item, so an AOI spanning a tile boundary still gets a
        # correct count instead of an arbitrarily chosen tile's value.
        dataset = dataset.sum("time", keep_attrs=True, skipna=True)

    count_wet = dataset[COUNT_WET_BAND]
    count_clear = dataset[COUNT_CLEAR_BAND]

    # Derive frequency (0-100) lazily. A clear-count of 0 (or either input at
    # its nodata sentinel) has no defined frequency -- propagate NaN there
    # rather than dividing by zero or trusting a raw negative nodata value.
    wet_nodata = count_wet.attrs.get("nodata")
    clear_nodata = count_clear.attrs.get("nodata")
    wet_valid = count_wet != wet_nodata if wet_nodata is not None else True
    clear_valid = count_clear != clear_nodata if clear_nodata is not None else True
    valid = wet_valid & clear_valid & (count_clear > 0)

    frequency = (100.0 * count_wet / count_clear.where(count_clear != 0)).where(valid)
    frequency.name = "frequency"
    frequency.attrs["units"] = "percent"
    frequency.attrs["valid_range"] = (0.0, 100.0)

    dataset = dataset.assign(frequency=frequency)
    dataset.attrs["provenance"] = {
        "product": product,
        "stac_url": stac_url,
        "item_ids": item_ids,
        "crs": str(crs_value),
        "resolution": resolution,
        "time_span": time_span,
        "frequency": {
            "derivation": "100 * count_wet / count_clear",
            "count_wet": COUNT_WET_BAND,
            "count_clear": COUNT_CLEAR_BAND,
        },
    }
    return dataset


def _item_time_span(items) -> str | None:
    """A ``"start/end"`` ISO string spanning every resolved item's coverage.

    Reads ``start_datetime``/``end_datetime`` when present (typical for
    summary products), falling back to ``datetime``. Returns ``None`` if no
    item carries usable temporal properties -- callers must treat that as
    "unknown", never as "instantaneous".
    """
    starts: list[str] = []
    ends: list[str] = []
    for item in items:
        properties = getattr(item, "properties", None) or {}
        start = properties.get("start_datetime") or properties.get("datetime")
        end = properties.get("end_datetime") or properties.get("datetime")
        if start:
            starts.append(start)
        if end:
            ends.append(end)
    if not starts or not ends:
        return None
    return f"{min(starts)}/{max(ends)}"


@dataclass(frozen=True)
class WetPlanningFootprint:
    """A conservative, coarse pruning aid for planning remote WOfS reads.

    This is a SEPARATE, performance-only artifact from anything zoning-related
    (``build_zones()``). It must never be fed into zoning as frequency or
    support, and it must never change what counts as inside/outside the
    catchment for any metric denominator -- pixels it skips for I/O still
    represent dry/outside-the-planning-footprint, not a smaller catchment.

    ``native_mask`` is ``count_wet > 0`` at the statistics' native grid.
    ``coarse_mask`` is ``native_mask`` aggregated by ``factor`` via aligned
    max-pooling (``coarsen(..., boundary="pad").max()``) plus an optional
    ``safety_cells``-wide coarse-grid dilation halo -- never nearest/mode/mean,
    so an isolated native wet pixel can never disappear when coarsened. Every
    accepted footprint satisfies the round-trip proof: expanding
    ``coarse_mask`` back to the native grid is always a superset of
    ``native_mask`` (see :func:`build_wet_planning_footprint`'s tests).

    ``active_windows`` are storage/source-aligned native-grid ``GridWindow``s
    covering the wet coarse cells -- a chunk/window predicate, not a polygon.
    ``geometry`` stays ``None`` on the default path (no Shapely close/buffer);
    it exists only for a consumer that explicitly needs a vectorised polygon.
    """

    native_mask: "xr.DataArray"
    coarse_mask: "xr.DataArray"
    active_windows: "Sequence[GridWindow]"
    factor: int
    safety_cells: int
    digest: str
    covered_years: Sequence[int]
    source_collection: str
    source_version: str
    source_lineage: str
    geometry: "geopandas.GeoDataFrame | None" = None


def _eager_values(array: "xr.DataArray"):
    """``array``'s values, computing first if it is Dask-backed.

    ``count_wet``/``coarse_mask`` stay lazy through every xarray operation in
    :func:`build_wet_planning_footprint`; this is the one, explicit place
    values get materialized, for the emptiness check and for the digest/window
    derivation, which both need concrete data.
    """
    return array.compute().values if hasattr(array.data, "compute") else array.values


def _dilate_coarse_mask(mask: "xr.DataArray", safety_cells: int) -> "xr.DataArray":
    """Grow ``mask`` (boolean, coarse grid) by ``safety_cells`` coarse cells in every direction.

    Implemented as a union of shifted copies (never scipy, matching the rest
    of the package's raster-morphology style, e.g. ``_wet_aoi.py``) so it
    works identically whether ``mask`` is numpy- or Dask-backed. A cell within
    Chebyshev distance ``safety_cells`` of any True cell becomes True. This is
    the "one coarse-cell safety dilation when grids are not exactly aligned"
    the task brief calls for.
    """
    if safety_cells <= 0:
        return mask
    dilated = mask
    for dy in range(-safety_cells, safety_cells + 1):
        for dx in range(-safety_cells, safety_cells + 1):
            if dy == 0 and dx == 0:
                continue
            dilated = dilated | mask.shift(y=dy, x=dx, fill_value=False)
    return dilated


def _resolve_source_provenance(stats: "xr.Dataset") -> tuple[str, str, str, str | None]:
    """Extract ``(collection, version, lineage, time_span)`` from ``stats.attrs``.

    Raises :class:`DEAStatsUnavailable` if the ``provenance`` block
    ``open_wo_statistics`` writes is absent or missing the ``product`` field
    -- the statistics/daily-observation lineage/version contract this
    function needs to validate temporal coverage against is itself the thing
    being checked, so an absent or malformed contract must fail open exactly
    like an uncovered year would.
    """
    provenance = stats.attrs.get("provenance")
    if not isinstance(provenance, Mapping) or not provenance.get("product"):
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics lineage/version provenance is "
            "absent or incompatible; refusing to build a wet planning "
            "footprint without a verifiable source contract"
        )

    collection = str(provenance["product"])
    # DEA WOfS statistics collection ids encode their processing version as a
    # trailing "_<n>" token (e.g. "ga_ls_wo_fq_myear_3" -> version "3"). Fall
    # back to the full collection id if that convention isn't present rather
    # than fabricating a version number.
    tail = collection.rsplit("_", 1)[-1]
    version = tail if tail.isdigit() else collection

    item_ids = provenance.get("item_ids") or []
    lineage = f"{collection}:{','.join(sorted(str(i) for i in item_ids))}" if item_ids else collection

    time_span = provenance.get("time_span")
    return collection, version, lineage, time_span


def _years_covered_by_time_span(time_span: str | None, requested_years: Collection[int]) -> bool:
    """True if every year in ``requested_years`` falls within ``time_span``.

    ``time_span`` is the ``"start/end"`` ISO string ``open_wo_statistics``
    records (see ``_item_time_span``); ``None`` means "unknown coverage",
    which is never treated as covering anything.
    """
    if not time_span or "/" not in time_span:
        return False
    start_str, _, end_str = time_span.partition("/")
    try:
        start_year = int(start_str[:4])
        end_year = int(end_str[:4])
    except (ValueError, IndexError):
        return False
    return all(start_year <= year <= end_year for year in requested_years)


def build_wet_planning_footprint(
    stats: "xr.Dataset",
    *,
    factor: int = 4,
    safety_cells: int = 1,
    requested_years: Collection[int],
) -> WetPlanningFootprint:
    """Build a conservative coarse wet-pixel planning footprint from ``stats``.

    ``stats`` is the ``xr.Dataset`` returned by :func:`open_wo_statistics`
    (``count_wet``/``count_clear``/``frequency`` at native resolution, with
    ``.attrs["provenance"]``). This is a PERFORMANCE-ONLY artifact: it gates
    which spatial windows a later remote read touches, and must never be
    confused with or fed into zoning (``build_zones()``).

    Steps, matching the task's correctness contract exactly:

    1. ``native_mask = count_wet > 0`` at native resolution.
    2. ``coarse_mask = native_mask.coarsen(y=factor, x=factor,
       boundary="pad").max()`` -- aligned max-pooling only (never
       nearest/mode/mean), with ``boundary="pad"`` so a trailing partial
       block is padded (False) rather than dropped, preserving edge cells.
    3. A ``safety_cells``-wide coarse-grid dilation halo is applied on top,
       covering grids that are not exactly aligned.

    Every accepted footprint satisfies ``native_mask <= expand(coarse_mask)``
    (the round-trip proof) -- see the test suite in ``test_io_dea_stats.py``.

    ``active_windows`` are derived directly from ``coarse_mask`` as a
    raster/chunk predicate (:func:`hydroseason._spatial_plan.active_windows_from_mask`);
    no polygon is vectorised on this path. ``geometry`` stays ``None``.

    Fails open (raises :class:`DEAStatsUnavailable`) rather than returning a
    partial or empty mask when:

    * ``count_wet`` has no wet pixels at all -- an empty footprint could be
      mistaken for "nothing here to prune" and must never be returned.
    * ``stats.attrs["provenance"]`` is absent or missing a resolvable
      collection/version -- the statistics/daily-observation lineage/version
      contract is itself unverifiable.
    * ``stats``'s recorded ``time_span`` does not cover every year in
      ``requested_years``.
    """
    import numpy as np

    from hydroseason._spatial_plan import active_windows_from_mask

    if not requested_years:
        raise DEAStatsUnavailable(
            "build_wet_planning_footprint requires at least one requested year"
        )
    if factor < 1:
        raise ValueError(f"factor must be at least 1, got {factor!r}")
    if safety_cells < 0:
        raise ValueError(f"safety_cells must be non-negative, got {safety_cells!r}")

    collection, version, lineage, time_span = _resolve_source_provenance(stats)
    if not _years_covered_by_time_span(time_span, requested_years):
        raise DEAStatsUnavailable(
            f"DEA Water Observation Statistics time_span {time_span!r} does not "
            f"cover requested years {sorted(requested_years)!r}; refusing to "
            "build a wet planning footprint that would silently under-prune"
        )

    count_wet = stats["count_wet"]
    native_mask = (count_wet > 0).astype(bool)
    native_mask.name = "wet_planning_native_mask"

    if not bool(_eager_values(native_mask.any())):
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics returned no wet pixels for this "
            "AOI; refusing to build a planning footprint (an empty footprint "
            "would be indistinguishable from 'nothing here to prune')"
        )

    coarse_mask = (
        native_mask.coarsen(y=factor, x=factor, boundary="pad").max().astype(bool)
    )
    coarse_mask = _dilate_coarse_mask(coarse_mask, safety_cells)
    coarse_mask.name = "wet_planning_coarse_mask"

    native_shape = (native_mask.sizes["y"], native_mask.sizes["x"])
    coarse_values = np.asarray(_eager_values(coarse_mask), dtype=bool)
    # Snap active windows onto the same 512px storage-chunk stride
    # plan_storage_aligned_slices uses elsewhere in the package (the
    # on-disk WOfS Zarr/COG tiling unit), so a later acquisition pass reads
    # whole storage chunks rather than a mix of chunk-unaligned windows.
    # Must stay a multiple of factor so every coarse cell lands on exactly
    # one storage-aligned block edge (see active_windows_from_mask).
    storage_chunk = _WOFS_STORAGE_CHUNK_PIXELS
    if storage_chunk % factor != 0:
        storage_chunk = factor
    active_windows = active_windows_from_mask(
        coarse_values,
        factor=factor,
        native_shape=native_shape,
        storage_chunk=storage_chunk,
    )

    covered_years = tuple(sorted(requested_years))
    digest = _wet_planning_footprint_digest(
        coarse_values, factor=factor, safety_cells=safety_cells,
        covered_years=covered_years, source_collection=collection,
        source_version=version,
    )

    return WetPlanningFootprint(
        native_mask=native_mask,
        coarse_mask=coarse_mask,
        active_windows=active_windows,
        factor=factor,
        safety_cells=safety_cells,
        digest=digest,
        covered_years=covered_years,
        source_collection=collection,
        source_version=version,
        source_lineage=lineage,
        geometry=None,
    )


def _wet_planning_footprint_digest(
    coarse_values, *, factor: int, safety_cells: int,
    covered_years: Sequence[int], source_collection: str, source_version: str,
) -> str:
    """A stable SHA-256 over the coarse mask's values and the plan's parameters.

    Feeds cache identity per the plan's global constraint ("Cache identity
    includes both masks, grid, temporal coverage, product provenance,
    aggregation factor, safety halo, and composite bundle"). Uses the raw
    boolean bytes of ``coarse_mask`` rather than a geometry hash so two
    footprints with identical masks and parameters always digest identically,
    independent of dask chunking.
    """
    hasher = hashlib.sha256()
    hasher.update(coarse_values.tobytes())
    hasher.update(str(coarse_values.shape).encode("utf-8"))
    hasher.update(str(factor).encode("utf-8"))
    hasher.update(str(safety_cells).encode("utf-8"))
    hasher.update(str(tuple(covered_years)).encode("utf-8"))
    hasher.update(source_collection.encode("utf-8"))
    hasher.update(source_version.encode("utf-8"))
    return hasher.hexdigest()


def build_planning_footprint_from_historical_mask(
    historical_mask: "HistoricalWaterMask", *, factor: int = 4, safety_cells: int = 1,
) -> WetPlanningFootprint:
    """Derive a performance-only :class:`WetPlanningFootprint` from an exact
    :class:`~hydroseason._historical_water_mask.HistoricalWaterMask`.

    ``native_mask`` is set to ``historical_mask.mask`` EXACTLY -- the same
    boolean array the scientific denominator uses, with no dilation applied.
    Only ``coarse_mask`` (used solely to pick ``active_windows`` for pruning
    remote reads) is max-pooled and, if ``safety_cells`` is nonzero,
    dilated -- reusing :func:`_dilate_coarse_mask` and
    :func:`hydroseason._spatial_plan.active_windows_from_mask`, the same
    helpers :func:`build_wet_planning_footprint` uses. This guarantees the
    planning derivative can never mutate, coarsen, or shrink the exact mask
    it was built from: ``historical_mask.mask``/``pixel_count``/``mask_sha256``
    are unaffected by any ``factor``/``safety_cells`` choice made here.

    The historical mask is already known to have at least one wet pixel
    (:func:`~hydroseason._historical_water_mask.build_historical_water_mask`
    fails closed on an empty mask before returning), so this function does
    not repeat that emptiness check.
    """
    import numpy as np
    import xarray as xr

    from hydroseason._spatial_plan import active_windows_from_mask

    if factor < 1:
        raise ValueError(f"factor must be at least 1, got {factor!r}")
    if safety_cells < 0:
        raise ValueError(f"safety_cells must be non-negative, got {safety_cells!r}")

    exact_values = np.asarray(historical_mask.mask, dtype=bool)
    native_mask = xr.DataArray(exact_values, dims=("y", "x"))
    native_mask.name = "historical_native_mask"

    coarse_mask = (
        native_mask.coarsen(y=factor, x=factor, boundary="pad").max().astype(bool)
    )
    coarse_mask = _dilate_coarse_mask(coarse_mask, safety_cells)
    coarse_mask.name = "historical_planning_coarse_mask"

    native_shape = historical_mask.shape
    coarse_values = np.asarray(_eager_values(coarse_mask), dtype=bool)
    storage_chunk = _WOFS_STORAGE_CHUNK_PIXELS
    if storage_chunk % factor != 0:
        storage_chunk = factor
    active_windows = active_windows_from_mask(
        coarse_values, factor=factor, native_shape=native_shape,
        storage_chunk=storage_chunk,
    )

    digest = _historical_planning_footprint_digest(
        coarse_values, factor=factor, safety_cells=safety_cells,
        historical_mask_sha256=historical_mask.mask_sha256,
        source_collection=historical_mask.source_product,
        source_version=historical_mask.source_version,
    )

    return WetPlanningFootprint(
        native_mask=native_mask,
        coarse_mask=coarse_mask,
        active_windows=active_windows,
        factor=factor,
        safety_cells=safety_cells,
        digest=digest,
        covered_years=(),
        source_collection=historical_mask.source_product,
        source_version=historical_mask.source_version,
        source_lineage=",".join(historical_mask.source_lineage),
        geometry=None,
    )


def _historical_planning_footprint_digest(
    coarse_values, *, factor: int, safety_cells: int, historical_mask_sha256: str,
    source_collection: str, source_version: str,
) -> str:
    """A stable SHA-256 over the coarse mask, plan parameters, and the exact
    historical-mask digest it was derived from.

    Matches :func:`_wet_planning_footprint_digest`'s field-by-field style,
    plus ``historical_mask_sha256`` so a planning footprint can never be
    mistaken for one derived from a different exact mask (e.g. after a
    Multi-Year Statistics source update) even if the coarsened/dilated
    result happens to collide.
    """
    hasher = hashlib.sha256()
    hasher.update(coarse_values.tobytes())
    hasher.update(str(coarse_values.shape).encode("utf-8"))
    hasher.update(str(factor).encode("utf-8"))
    hasher.update(str(safety_cells).encode("utf-8"))
    hasher.update(historical_mask_sha256.encode("utf-8"))
    hasher.update(source_collection.encode("utf-8"))
    hasher.update(source_version.encode("utf-8"))
    return hasher.hexdigest()


def fetch_dea_stats_wet_aoi(
    stac_url: str,
    aoi_gdf,
    years: list[int],
    *,
    crs: int | str = 3577,
    resolution: float = 30.0,
    close_m: float = 0.0,
    buffer_m: float = 0.0,
    cache_root: str | Path | None = None,
    _loader=None,
):
    """Build an ever-wet polygon for ``aoi_gdf`` over ``years``.

    Unions ``count_wet > 0`` from the all-time summary with each requested
    year's annual summary, then vectorizes the result via
    :func:`hydroseason._wet_aoi.wet_aoi_polygon` (the same vectoriser the
    local-counts path uses, so both wet-AOI sources produce identically
    shaped geometry).

    ``close_m`` and ``buffer_m`` both default to 0 here. This source is
    already a DEA-computed all-time/all-year maximum extent -- there is no
    pixel-level acquisition error to pad against (unlike the local-counts
    path), and both are pure ``shapely`` distance-buffer operations whose
    cost tracks merged-geometry boundary complexity, not polygon count. On
    gilbert_river_qld's braided floodplain (a genuinely fragmented mask, not
    sparse speckle) ``buffer_m=300`` alone cost ~760s and ``close_m=150``
    alone cost ~490s on top of a ~24s fetch+union. The result is a superset
    with more/thinner disconnected fragments than a closed+buffered mask
    would give, which only affects tile-pruning granularity, not
    correctness -- fine since this mask only gates which tiles get fetched.
    Left overridable for a caller that wants the smoothing back.

    ``_loader`` is a test seam: a callable ``(collection, year, geobox) ->
    DataArray`` of ``count_wet``. Production callers leave it ``None``.

    Raises ``DEAStatsUnavailable`` if no source resolves, or if the union
    contains no wet pixels at all -- an empty mask would prune the entire
    AOI, which is never a correct answer.
    """
    import numpy as np
    import rioxarray  # noqa: F401  (registers the .rio accessor used below)

    from hydroseason._io_geo import (
        _crs_value,
        _output_geobox_for_aoi,
        _preserve_georef,
    )
    from hydroseason._wet_aoi import wet_aoi_polygon

    if not years:
        raise DEAStatsUnavailable("no years requested")

    crs_value = _crs_value(crs)
    target = aoi_gdf.to_crs(crs_value) if crs_value is not None else aoi_gdf
    # Vectorized at a coarser resolution than the caller's extraction
    # resolution: this is a boolean presence mask, so fine-resolution
    # precision here is wasted, and polygon count from
    # rasterio.features.shapes feeds shapely.union_all, whose cost scales
    # worse than linearly with polygon count on fragmented masks. Measured
    # on gilbert_river_qld's braided floodplain (isolated, no network):
    # 100m -> 170,277 polygons -> union_all alone took 361.6s. 300m ->
    # ~25,000 polygons -> union_all ~12.9s. 100m is not a safe floor for a
    # heavily-fragmented wet mask; 300m is. Never coarsens below the
    # caller's request, only above this floor.
    mask_resolution = max(float(resolution), 300.0)
    geobox = _output_geobox_for_aoi([], target, crs=crs_value, resolution=mask_resolution)

    loader = _loader if _loader is not None else (
        lambda collection, year, gb: _load_count_wet(stac_url, collection, year, gb)
    )

    sources = [(DEA_STATS_ALLTIME_COLLECTION, None)]
    sources.extend((DEA_STATS_ANNUAL_COLLECTION, year) for year in sorted(set(years)))

    def _load_and_materialize(collection, year):
        count_wet = loader(collection, year, geobox)
        # A source that resolves but is entirely zero contributes nothing;
        # that is fine as long as SOME source contributes. Computed eagerly,
        # inside the timeout, so a slow tile fetch on a large catchment is
        # bounded here rather than deferred to the final union's compute.
        #
        # The comparison drops rioxarray's CRS/transform, which wet_aoi_polygon
        # needs downstream -- restore them from the source, exactly as the
        # local-counts path does in compute_ever_wet_from_counts.
        wet = _preserve_georef(count_wet > 0, count_wet)
        return wet.load()

    union = None
    failures = []
    for collection, year in sources:
        try:
            wet = _run_with_timeout(
                lambda c=collection, y=year: _load_and_materialize(c, y),
                SOURCE_TIMEOUT_S,
            )
        except DEAStatsUnavailable as exc:
            failures.append(f"{collection}/{year}: {exc}")
            continue
        except Exception as exc:
            failures.append(f"{collection}/{year}: {type(exc).__name__}: {exc}")
            continue
        union = wet if union is None else (union | wet)

    if union is None:
        raise DEAStatsUnavailable(
            "no DEA Water Observation Statistics source could be loaded "
            f"({'; '.join(failures) if failures else 'no sources tried'})"
        )

    if not bool(np.asarray(union.values).any()):
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics returned no wet pixels for this "
            "AOI; refusing to prune (an empty mask would drop the entire AOI)"
        )

    wet_aoi = wet_aoi_polygon(union, close_m=close_m, buffer_m=buffer_m)

    # Clip to the AOI itself. The geobox above spans the AOI's BOUNDING BOX,
    # so the raw mask carries every ever-wet pixel in that rectangle --
    # including large areas outside an irregular catchment (on
    # fitzroy_river_wa the unclipped mask made the coarse planner select 828
    # storage windows where the bare AOI polygon selects 489: pruning that
    # added 69% more work than not pruning at all). Intersecting here fixes
    # it once for every consumer, and cannot break the superset guarantee:
    # pixels outside the AOI are already written as -2 by _clip_to_aoi, so
    # dropping them costs no real water.
    clipped = wet_aoi.clip(target) if not wet_aoi.empty else wet_aoi
    if clipped.empty or bool(clipped.geometry.is_empty.all()):
        raise DEAStatsUnavailable("wet-AOI vectorisation produced an empty geometry")
    return clipped


def wet_mask_digest(wet_aoi) -> str:
    """A stable SHA-256 over a wet-AOI's geometry and CRS.

    Feeds ``WOfSCacheRequest.wet_mask_sha256`` so a store built under one
    mask is never confused with a store built under another. Uses WKB at
    fixed precision rather than the GeoDataFrame's repr so the digest is
    stable across geopandas versions.
    """
    import shapely
    from shapely import wkb

    geometry = (
        wet_aoi.geometry.union_all()
        if hasattr(wet_aoi.geometry, "union_all")
        else wet_aoi.geometry.unary_union
    )
    # Snap to a fixed 1e-3 precision grid before serializing (rather than
    # relying on wkb.dumps' rounding_precision kwarg, which is not accepted by
    # every shapely 2.x point release) so the digest is stable across
    # equivalent geometries that differ only in floating-point noise.
    geometry = shapely.set_precision(geometry, grid_size=0.001)
    hasher = hashlib.sha256()
    hasher.update(str(wet_aoi.crs).encode("utf-8"))
    hasher.update(wkb.dumps(geometry))
    return hasher.hexdigest()


__all__ = [
    "COUNT_CLEAR_BAND",
    "COUNT_WET_BAND",
    "DEA_STATS_ALLTIME_COLLECTION",
    "DEA_STATS_ANNUAL_COLLECTION",
    "DEFAULT_WO_STATISTICS_PRODUCT",
    "DEFAULT_WO_STATISTICS_STAC_URL",
    "DEAStatsUnavailable",
    "WetPlanningFootprint",
    "WoStatisticsUnavailable",
    "build_planning_footprint_from_historical_mask",
    "build_wet_planning_footprint",
    "fetch_dea_stats_wet_aoi",
    "open_wo_statistics",
    "wet_mask_digest",
]
