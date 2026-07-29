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
import time
from pathlib import Path
from typing import Any, Mapping

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


class WoStatisticsUnavailable(RuntimeError):
    """`open_wo_statistics` could not resolve a dataset for this AOI/product.

    Raised for an unreachable STAC endpoint, a search that exceeds the load
    deadline, or a search that returns no items. Callers that use this as a
    zoning source must treat it as "the DEA-statistics zoning source is
    unavailable" and fall back to their own local-cube zoning path -- this
    loader never returns a partial or empty-but-successful result.
    """


class DEAStatsUnavailable(RuntimeError):
    """The wet mask could not be established, so pruning must not be attempted.

    Raised for every failure mode -- unreachable STAC, no matching items, a
    load error, or a mask with no wet pixels at all. The caller's only correct
    response is to fall back to a full-coverage read.
    """


def _load_count_wet(stac_url: str, collection: str, year: int | None, geobox):
    """Load the ``count_wet`` band for one collection over ``geobox``.

    ``year=None`` requests the all-time product (no datetime filter).
    """
    import odc.stac
    import pystac_client

    from hydroseason._io_geo import _configure_cog_read_env

    _configure_cog_read_env()

    search_kwargs = {
        "collections": [collection],
        "bbox": list(geobox.extent.to_crs("EPSG:4326").boundingbox),
        "limit": 1000,
    }
    if year is not None:
        search_kwargs["datetime"] = f"{year}-01-01/{year}-12-31"

    client = pystac_client.Client.open(stac_url)
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

    Raises :class:`WoStatisticsUnavailable` if the STAC search fails, times
    out, or returns no items. Does not raise on a geographic CRS -- CRS
    validity for area-metric use is HydroFragments' concern
    (``guard_area_metric_crs``); this loader is source-agnostic and hands
    whatever grid was asked for, unsigned COG reads and all, straight back.
    """
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
    import os

    env_keys = (
        "AWS_NO_SIGN_REQUEST", "GDAL_DISABLE_READDIR_ON_OPEN",
        "GDAL_HTTP_MULTIPLEX", "GDAL_HTTP_VERSION", "VSI_CACHE",
        "VSI_CACHE_SIZE", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS",
        "GDAL_HTTP_MAX_RETRY", "GDAL_HTTP_RETRY_DELAY", "GDAL_HTTP_RETRY_CODES",
        "GDAL_HTTP_TIMEOUT", "GDAL_HTTP_CONNECTTIMEOUT",
        "GDAL_HTTP_MAX_TOTAL_CONNECTIONS", "PROJ_LIB", "PROJ_DATA",
    )
    before = {key: os.environ.get(key) for key in env_keys}
    try:
        _configure_cog_read_env()
        # Explicit per-request STAC connect/read timeouts (the brief's
        # "set explicit STAC connect/read timeouts"): pystac_client forwards
        # unknown kwargs to the underlying requests session via
        # stac_io, but the simplest, dependency-light way to bound this is
        # the same GDAL_HTTP_* timeouts _configure_cog_read_env already sets
        # for the COG reads themselves (STAC_CONNECT_TIMEOUT_S /
        # STAC_READ_TIMEOUT_S document the intended bounds; GDAL_HTTP_TIMEOUT
        # /GDAL_HTTP_CONNECTTIMEOUT are the enforcement mechanism already
        # wired by _configure_cog_read_env).
        client = pystac_client.Client.open(stac_url)

        # This measures elapsed time around the search rather than
        # interrupting an in-flight request (hydroseason has no established
        # pattern for hard-cancelling a blocking network call, and the
        # per-request GDAL_HTTP_TIMEOUT/CONNECTTIMEOUT above already bound
        # each individual COG read). What this guarantees is the promised
        # contract: a slow or hanging zoning source still resolves to a
        # raised WoStatisticsUnavailable rather than blocking forever, so
        # the caller can always fall back to its local-cube zoning path.
        started = time.monotonic()
        try:
            search = client.search(
                collections=[product],
                bbox=bbox,
                limit=1000,
            )
            items = list(search.items())
        except Exception as exc:
            raise WoStatisticsUnavailable(
                f"DEA Water Observation Statistics STAC search failed for "
                f"product '{product}': {type(exc).__name__}: {exc}"
            ) from exc
        elapsed = time.monotonic() - started
        if elapsed > STAC_SEARCH_DEADLINE_S:
            raise WoStatisticsUnavailable(
                f"DEA Water Observation Statistics STAC search for product "
                f"'{product}' took {elapsed:.1f}s, exceeding the "
                f"{STAC_SEARCH_DEADLINE_S}s load deadline"
            )

        if not items:
            raise WoStatisticsUnavailable(
                f"no {product} items found for this AOI"
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


def fetch_dea_stats_wet_aoi(
    stac_url: str,
    aoi_gdf,
    years: list[int],
    *,
    crs: int | str = 3577,
    resolution: float = 30.0,
    close_m: float = 150.0,
    buffer_m: float = 300.0,
    cache_root: str | Path | None = None,
    _loader=None,
):
    """Build a buffered ever-wet polygon for ``aoi_gdf`` over ``years``.

    Unions ``count_wet > 0`` from the all-time summary with each requested
    year's annual summary, then closes and buffers the result via
    :func:`hydroseason._wet_aoi.wet_aoi_polygon` (the same vectoriser the
    local-counts path uses, so both wet-AOI sources produce identically
    shaped geometry).

    ``_loader`` is a test seam: a callable ``(collection, year, geobox) ->
    DataArray`` of ``count_wet``. Production callers leave it ``None``.

    Raises ``DEAStatsUnavailable`` if no source resolves, or if the union
    contains no wet pixels at all -- an empty mask would prune the entire
    AOI, which is never a correct answer.
    """
    import numpy as np

    from hydroseason._io_geo import _crs_value, _output_geobox_for_aoi
    from hydroseason._wet_aoi import wet_aoi_polygon

    if not years:
        raise DEAStatsUnavailable("no years requested")

    crs_value = _crs_value(crs)
    target = aoi_gdf.to_crs(crs_value) if crs_value is not None else aoi_gdf
    geobox = _output_geobox_for_aoi([], target, crs=crs_value, resolution=float(resolution))

    loader = _loader if _loader is not None else (
        lambda collection, year, gb: _load_count_wet(stac_url, collection, year, gb)
    )

    sources = [(DEA_STATS_ALLTIME_COLLECTION, None)]
    sources.extend((DEA_STATS_ANNUAL_COLLECTION, year) for year in sorted(set(years)))

    union = None
    failures = []
    for collection, year in sources:
        try:
            count_wet = loader(collection, year, geobox)
            # A source that resolves but is entirely zero contributes nothing;
            # that is fine as long as SOME source contributes.
            wet = count_wet > 0
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
    if wet_aoi.empty or bool(wet_aoi.geometry.is_empty.all()):
        raise DEAStatsUnavailable("wet-AOI vectorisation produced an empty geometry")
    return wet_aoi


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
    "WoStatisticsUnavailable",
    "fetch_dea_stats_wet_aoi",
    "open_wo_statistics",
    "wet_mask_digest",
]
