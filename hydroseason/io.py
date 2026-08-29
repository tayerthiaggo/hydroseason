"""Source-agnostic extent and raster loaders (re-export facade).

Implementation lives in ``_io_extent`` (pandas-only), ``_io_geo``
(AOI/raster loading and georeferencing), and ``_io_resolution`` (resolution
planning and the amplitude probe). This module exists so
``from hydroseason.io import X`` keeps working for every name that was
importable here before the split, including the private helpers already
used directly by scripts and tests.
"""

from __future__ import annotations

from hydroseason._historical_water_mask import (  # noqa: F401
    HistoricalMaskCoverageWarning,
    HistoricalMaskRefreshedWarning,
    HistoricalWaterMask,
    build_historical_water_mask,
    load_or_build_historical_water_mask,
)
from hydroseason._io_dea_stats import (  # noqa: F401
    WetPlanningFootprint,
    build_planning_footprint_from_historical_mask,
    build_wet_planning_footprint,
    open_wo_statistics,
    probe_wo_statistics_coverage,
)
from hydroseason._io_extent import complete_monthly_axis, load_extent_csv  # noqa: F401
from hydroseason._io_extent_cache import load_wofs_monthly_extent  # noqa: F401
from hydroseason._io_preflight_stats import open_annual_wo_statistics  # noqa: F401
from hydroseason._io_geo import (  # noqa: F401
    AOIRasterizationError,
    GeoreferencingError,
    IrregularGridError,
    MaskEncoding,
    _apply_aoi_inside_mask,
    _assert_compatible_georef,
    _classify,
    _clip_to_aoi,
    _combine_observations,
    _crs_value,
    _inside_aoi_mask_like,
    _is_identity_transform,
    _load_wofs_items,
    _output_geobox_for_aoi,
    _parse_date_from_name,
    _preserve_georef,
    _query_wofs_items,
    _resolve_aoi_inside_mask,
    _resolve_raster_crs,
    _resolve_raster_transform,
    _spatial_transform_from_xy,
    _tile_intersects_aoi,
    _tile_slices,
    _validate_classifier,
    iter_wofs_tiles_from_stac,
    load_aoi,
    load_monthly_masks,
    load_monthly_masks_zarr,
    load_wofs_from_stac,
    mark_in_aoi_nodata_as_invalid,
)
from hydroseason._io_resolution import (  # noqa: F401
    _DEFAULT_CANDIDATE_RES_M,
    _DEFAULT_RETENTION_THRESHOLD,
    _mean_water_fraction,
    _next_coarser_res_m,
    plan_resolution,
    probe_amplitude,
)
from hydroseason._io_wofs_zarr import WOfSCacheHandle  # noqa: F401
from hydroseason._wet_aoi import compute_wet_aoi, tile_intersects_wet_aoi  # noqa: F401


def acquire_wofs_cache(*args, **kwargs):
    """Acquire or reuse the canonical local WOfS mask cache."""
    from hydroseason._io_wofs_acquire import acquire_wofs_cache as _acquire_wofs_cache

    return _acquire_wofs_cache(*args, **kwargs)


def open_completed_mask_cache(*args, **kwargs):
    """Lazily open the canonical WOfS water-mask cube for a completed cache store.

    Public reader counterpart to :func:`acquire_wofs_cache`: given a
    :class:`WOfSCacheHandle` (as returned by ``acquire_wofs_cache``) and a
    ``[start_date, end_date]`` range, opens every completed annual Zarr
    group that overlaps the range, concatenates them in year order, and
    fills any still-missing months with the package's standard missing-month
    convention (``-1`` invalid, never fabricated). See
    :func:`hydroseason._io_wofs_zarr.open_completed_mask_cache` for the full
    contract, including its ``FileNotFoundError``/``ValueError`` cases.
    """
    from hydroseason._io_wofs_zarr import open_completed_mask_cache as _open_completed_mask_cache

    return _open_completed_mask_cache(*args, **kwargs)


def load_or_build_cached_wet_aoi(*args, **kwargs):
    """Internal facade for locally derived wet-AOI sidecars."""
    from hydroseason._io_wofs_acquire import (
        load_or_build_cached_wet_aoi as _load_or_build_cached_wet_aoi,
    )

    return _load_or_build_cached_wet_aoi(*args, **kwargs)


def open_completed_extent_counts(*args, **kwargs):
    """Internal facade for the extent counts reader."""
    from hydroseason._io_wofs_zarr import (
        open_completed_extent_counts as _open_completed_extent_counts,
    )

    return _open_completed_extent_counts(*args, **kwargs)


def verify_cache_footprints(*args, **kwargs):
    """Read, independently re-rasterize, and verify a cache's persisted AOI/analysis footprints.

    Public reader/verifier counterpart to :func:`acquire_wofs_cache` (Task
    W2.3): given a :class:`WOfSCacheHandle`, reads the full-AOI and
    analysis-footprint geometry/counts/digests persisted in the store's root
    manifest, re-rasterizes each geometry from its persisted canonical WKB,
    and cross-checks both the digest and the pixel count against what was
    persisted -- never trusting either alone. Raises ``ValueError`` on any
    tamper/corruption mismatch, or ``FileNotFoundError``/``ValueError`` if no
    manifest or no footprints metadata exists yet. See
    :func:`hydroseason._io_wofs_zarr.verify_cache_footprints` for the full
    contract.
    """
    from hydroseason._io_wofs_zarr import verify_cache_footprints as _verify_cache_footprints

    return _verify_cache_footprints(*args, **kwargs)


def open_completed_dual_extent_counts(*args, **kwargs):
    """Read back the second (any-day-wet ``max_water``) composite's per-month pixel counts.

    Public reader counterpart to :func:`acquire_wofs_cache` when it was
    called with ``composite_bundle="dual_composite_v1"`` (Task W2.2): given
    a :class:`WOfSCacheHandle` and a ``[start_date, end_date]`` range,
    returns a ``pandas.DataFrame`` combining every completed year's
    ``years/<year>/dual_extent_counts.json`` sidecar -- the SECONDARY
    composite's per-month wet/valid pixel counts alongside the fixed
    full-AOI/analysis-mask pixel-count denominators -- or ``None`` if any
    requested year is incomplete, the sidecar is missing/malformed for any
    requested year (including a store acquired with the default
    ``composite_bundle="single_mask"``, which never writes this file), or the
    resulting range has no rows. See
    :func:`hydroseason._io_wofs_zarr.open_completed_dual_extent_counts` for
    the full contract.
    """
    from hydroseason._io_wofs_zarr import (
        open_completed_dual_extent_counts as _open_completed_dual_extent_counts,
    )

    return _open_completed_dual_extent_counts(*args, **kwargs)


__all__ = ["load_aoi", "load_extent_csv", "complete_monthly_axis", "load_monthly_masks", "load_monthly_masks_zarr", "load_wofs_from_stac", "load_wofs_monthly_extent", "plan_resolution", "probe_amplitude", "compute_wet_aoi", "acquire_wofs_cache", "open_completed_mask_cache", "open_completed_extent_counts", "open_completed_dual_extent_counts", "WOfSCacheHandle", "open_wo_statistics", "open_annual_wo_statistics", "verify_cache_footprints", "build_wet_planning_footprint", "WetPlanningFootprint", "HistoricalWaterMask", "build_historical_water_mask", "load_or_build_historical_water_mask"]

