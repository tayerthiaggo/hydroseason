"""The exact historical maximum-water mask: a pure value object and builder.

``historical_max_water_mask = (DEA WO Multi-Year Statistics count_wet > 0)
AND user_AOI``, at the Statistics' native grid resolution. This is a SEPARATE,
scientific artifact from :class:`hydroseason._io_dea_stats.WetPlanningFootprint`
(performance-only, coarsened/dilated). The mask built here is never closed,
buffered, dilated, or round-tripped through polygons -- it is the raw,
grid-aligned boolean raster used exactly as-is as the fixed denominator for
every requested month (see
``docs/superpowers/specs/2026-08-03-historical-water-mask-and-area-design.md``).

This module does no I/O of its own: :func:`build_historical_water_mask` takes
an already-loaded ``stats`` dataset (whatever
:func:`hydroseason._io_dea_stats.open_wo_statistics` returns) and an AOI, and
is pure computation from there. All geospatial imports stay inside function
bodies, per the package rule.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    import xarray as xr

# The only DEA WO Statistics product accepted as a historical-mask source.
# The all-time summary is the one whose provenance is pinned as the fixed
# scientific footprint for the entire requested analysis period -- see
# hydroseason._io_dea_stats.DEA_STATS_ALLTIME_COLLECTION, duplicated here as
# a literal rather than imported. This module does import
# hydroseason._io_dea_stats.DEAStatsUnavailable (a leaf exception class with
# no dependency back on this module) for its fail-closed raises, but not the
# collection constants, so the existing one-way dependency direction between
# the two modules is preserved (_io_dea_stats.
# build_planning_footprint_from_historical_mask depends on this module for
# HistoricalWaterMask/build_historical_water_mask, not the reverse).
HISTORICAL_MASK_SOURCE_PRODUCT = "ga_ls_wo_fq_myear_3"

# The monthly WOfS observation collection the historical mask is applied
# against. Both collection ids encode the WOfS algorithm/processing version
# as their trailing "_<n>" token; the historical mask's source lineage is
# only compatible with this monthly collection when that version token
# matches (see _resolve_and_validate_provenance's "incompatible WOfS
# lineage" check).
MONTHLY_WOFS_COLLECTION = "ga_ls_wo_3"


@dataclass(frozen=True)
class HistoricalWaterMask:
    """The exact, immutable `(count_wet > 0) AND AOI` raster and its provenance.

    ``mask`` is a 2D boolean array (row-major, shape ``shape``) at the
    Statistics' native grid -- never a polygon. ``pixel_count`` is the fixed
    number of True cells, which becomes the constant ``n_aoi`` denominator
    for every month in the requested analysis period.

    ``source_item_ids`` and ``source_lineage`` are recorded as sorted tuples
    so two builds over the same underlying STAC items always compare equal
    regardless of search-result ordering. ``aoi_sha256``/``mask_sha256`` are
    stable SHA-256 digests -- see :func:`build_historical_water_mask` for
    exactly what each is computed over.
    """

    mask: Any
    crs: str
    transform: "tuple[float, ...]"
    shape: "tuple[int, int]"
    resolution: "tuple[float, float]"
    pixel_count: int
    source_product: str
    source_version: str
    source_item_ids: "tuple[str, ...]"
    source_lineage: "tuple[str, ...]"
    coverage_start: str
    coverage_end: str
    aoi_sha256: str
    mask_sha256: str


def _resolve_provenance(stats: "xr.Dataset") -> Mapping[str, Any]:
    """The ``stats.attrs["provenance"]`` block written by ``open_wo_statistics``.

    Raises :class:`hydroseason._io_dea_stats.DEAStatsUnavailable` if it is
    absent or missing ``product`` -- the lineage/version/coverage contract
    this builder validates is itself the thing being checked, so an absent
    or malformed block must fail exactly like an incompatible lineage would,
    and via the same fail-closed exception type
    :func:`hydroseason._io_dea_stats.build_wet_planning_footprint` already
    uses for the identical provenance contract.
    """
    from hydroseason._io_dea_stats import DEAStatsUnavailable

    provenance = stats.attrs.get("provenance")
    if not isinstance(provenance, Mapping) or not provenance.get("product"):
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics provenance is absent or "
            "malformed -- incompatible WOfS lineage; refusing to build a "
            "historical water mask without a verifiable source contract"
        )
    return provenance


def _version_token(collection: str) -> str:
    """The trailing ``_<n>`` processing-version token of a DEA collection id.

    Matches the convention ``hydroseason._io_dea_stats._resolve_source_provenance``
    already uses (e.g. ``"ga_ls_wo_fq_myear_3"`` -> ``"3"``). Falls back to the
    full collection id if that convention isn't present.
    """
    tail = collection.rsplit("_", 1)[-1]
    return tail if tail.isdigit() else collection


def _parse_time_span(time_span: str | None) -> "tuple[str, str]":
    from hydroseason._io_dea_stats import DEAStatsUnavailable

    if not time_span or "/" not in time_span:
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics does not cover analysis end: "
            f"source coverage {time_span!r} is unknown or malformed"
        )
    start, _, end = time_span.partition("/")
    if not start or not end:
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics does not cover analysis end: "
            f"source coverage {time_span!r} is unknown or malformed"
        )
    return start, end


def _coverage_covers_analysis_end(coverage_end: str, analysis_end: str) -> bool:
    import pandas as pd

    return pd.Timestamp(coverage_end).tz_localize(None) >= pd.Timestamp(analysis_end).tz_localize(None)


def build_historical_water_mask(
    stats: "xr.Dataset", aoi: Any, *, analysis_end: str,
) -> HistoricalWaterMask:
    """Build the exact `(count_wet > 0) AND AOI` historical water mask.

    ``stats`` is the ``xr.Dataset`` returned by
    :func:`hydroseason._io_dea_stats.open_wo_statistics` (must be the
    all-time Multi-Year product, ``ga_ls_wo_fq_myear_3``). ``aoi`` is a user
    AOI geometry/GeoDataFrame, rasterized onto ``stats``'s native grid via
    :func:`hydroseason._io_geo._inside_aoi_mask_like` (the same
    AOI-onto-grid rasterizer ``_clip_to_aoi`` already uses elsewhere in the
    package). The result is never closed, buffered, dilated, or converted
    through a polygon: it is exactly ``(count_wet > 0) & rasterized_aoi``,
    materialized as a plain boolean ``numpy`` array.

    Raises :class:`hydroseason._io_dea_stats.DEAStatsUnavailable`
    (fail-closed, matching the identical three-category validation
    :func:`hydroseason._io_dea_stats.build_wet_planning_footprint` already
    performs against the same ``stats.attrs["provenance"]`` contract) for:

    * an incompatible source product/lineage (anything other than
      ``ga_ls_wo_fq_myear_3``, or a version token that does not match the
      monthly WOfS collection ``ga_ls_wo_3``) -- message contains
      ``"incompatible WOfS lineage"``;
    * source coverage that does not reach ``analysis_end`` -- message
      contains ``"does not cover analysis end"``;
    * an exact mask with no True cells after the AND-with-AOI step --
      message contains ``"no historically observed water"``.
    """
    import numpy as np

    from hydroseason._io_dea_stats import DEAStatsUnavailable
    from hydroseason._io_geo import _inside_aoi_mask_like, load_aoi

    provenance = _resolve_provenance(stats)
    product = str(provenance["product"])
    if product != HISTORICAL_MASK_SOURCE_PRODUCT:
        raise DEAStatsUnavailable(
            f"incompatible WOfS lineage: historical water mask requires "
            f"product {HISTORICAL_MASK_SOURCE_PRODUCT!r}, got {product!r}"
        )

    version = _version_token(product)
    monthly_version = _version_token(MONTHLY_WOFS_COLLECTION)
    if version != monthly_version:
        # Unreachable in practice today: both collection constants above are
        # hardcoded to agree, so this can only fire if a future edit lets
        # them drift apart. Kept as defense-in-depth for that drift rather
        # than trusting the product-identity check above to catch it alone.
        raise DEAStatsUnavailable(
            f"incompatible WOfS lineage: Multi-Year Statistics version "
            f"{version!r} (from {product!r}) does not match the monthly "
            f"WOfS collection {MONTHLY_WOFS_COLLECTION!r} version "
            f"{monthly_version!r}"
        )

    item_ids = tuple(sorted(str(i) for i in (provenance.get("item_ids") or [])))
    lineage = tuple(sorted({product, *item_ids})) if item_ids else (product,)

    coverage_start, coverage_end = _parse_time_span(provenance.get("time_span"))
    if not _coverage_covers_analysis_end(coverage_end, analysis_end):
        raise DEAStatsUnavailable(
            f"DEA Water Observation Statistics source coverage "
            f"{coverage_start!r}/{coverage_end!r} does not cover analysis "
            f"end {analysis_end!r}"
        )

    count_wet = stats["count_wet"]
    wet = (count_wet > 0).astype(bool)

    aoi_gdf = load_aoi(aoi)
    crs = count_wet.rio.crs
    aoi_on_grid = aoi_gdf.to_crs(crs) if crs is not None else aoi_gdf
    inside_aoi = _inside_aoi_mask_like(wet, aoi_on_grid)

    exact = wet & inside_aoi
    exact_values = np.asarray(exact.values, dtype=bool)

    pixel_count = int(exact_values.sum())
    if pixel_count == 0:
        raise DEAStatsUnavailable(
            "no historically observed water: (count_wet > 0) AND AOI is "
            "empty for this AOI; refusing to build a historical water mask "
            "that would silently become an empty scientific denominator"
        )

    transform = tuple(count_wet.rio.transform())[:6]
    resolution = (abs(float(transform[0])), abs(float(transform[4])))
    shape = (int(exact_values.shape[0]), int(exact_values.shape[1]))

    aoi_sha256 = _aoi_digest(aoi_on_grid)
    mask_sha256 = _mask_digest(
        exact_values, crs=str(crs), transform=transform, shape=shape,
        resolution=resolution,
    )

    return HistoricalWaterMask(
        mask=exact_values,
        crs=str(crs),
        transform=transform,
        shape=shape,
        resolution=resolution,
        pixel_count=pixel_count,
        source_product=product,
        source_version=version,
        source_item_ids=item_ids,
        source_lineage=lineage,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        aoi_sha256=aoi_sha256,
        mask_sha256=mask_sha256,
    )


def _aoi_digest(aoi_gdf) -> str:
    """A stable SHA-256 over an AOI's geometry and CRS.

    Reuses the exact WKB-at-fixed-precision pattern
    :func:`hydroseason._io_dea_stats.wet_mask_digest` already uses, so an
    AOI's digest is computed identically everywhere in the package rather
    than by a second, parallel scheme.
    """
    import shapely
    from shapely import wkb

    geometry = (
        aoi_gdf.geometry.union_all()
        if hasattr(aoi_gdf.geometry, "union_all")
        else aoi_gdf.geometry.unary_union
    )
    geometry = shapely.set_precision(geometry, grid_size=0.001)
    hasher = hashlib.sha256()
    hasher.update(str(aoi_gdf.crs).encode("utf-8"))
    hasher.update(wkb.dumps(geometry))
    return hasher.hexdigest()


def _mask_digest(
    mask_values, *, crs: str, transform: "tuple[float, ...]",
    shape: "tuple[int, int]", resolution: "tuple[float, float]",
) -> str:
    """A stable SHA-256 over canonical grid metadata plus row-major mask bytes.

    Matches the digest style already used by
    :func:`hydroseason._io_dea_stats._wet_planning_footprint_digest`: raw
    boolean bytes plus every grid parameter that could otherwise make two
    different masks collide, hashed in a fixed field order so the result is
    independent of dict/attrs ordering.
    """
    hasher = hashlib.sha256()
    hasher.update(crs.encode("utf-8"))
    hasher.update(str(transform).encode("utf-8"))
    hasher.update(str(shape).encode("utf-8"))
    hasher.update(str(resolution).encode("utf-8"))
    hasher.update(mask_values.tobytes(order="C"))
    return hasher.hexdigest()


__all__ = [
    "HISTORICAL_MASK_SOURCE_PRODUCT",
    "MONTHLY_WOFS_COLLECTION",
    "HistoricalWaterMask",
    "build_historical_water_mask",
]
