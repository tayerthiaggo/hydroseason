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
from pathlib import Path

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
    "COUNT_WET_BAND",
    "DEA_STATS_ALLTIME_COLLECTION",
    "DEA_STATS_ANNUAL_COLLECTION",
    "DEAStatsUnavailable",
    "fetch_dea_stats_wet_aoi",
    "wet_mask_digest",
]
