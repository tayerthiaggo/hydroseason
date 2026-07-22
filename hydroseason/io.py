"""Source-agnostic extent and raster loaders (re-export facade).

Implementation lives in ``_io_extent`` (pandas-only), ``_io_geo``
(AOI/raster loading and georeferencing), and ``_io_resolution`` (resolution
planning and the amplitude probe). This module exists so
``from hydroseason.io import X`` keeps working for every name that was
importable here before the split, including the private helpers already
used directly by scripts and tests.
"""

from __future__ import annotations

from hydroseason._io_extent import complete_monthly_axis, load_extent_csv  # noqa: F401
from hydroseason._io_extent_cache import load_wofs_monthly_extent  # noqa: F401
from hydroseason._io_geo import (  # noqa: F401
    AOIRasterizationError,
    GeoreferencingError,
    IrregularGridError,
    MaskEncoding,
    load_aoi,
    load_monthly_masks,
    load_monthly_masks_zarr,
    load_wofs_from_stac,
    mark_in_aoi_nodata_as_invalid,
    _assert_compatible_georef,
    _classify,
    _clip_to_aoi,
    _combine_observations,
    _crs_value,
    _inside_aoi_mask_like,
    _is_identity_transform,
    _load_wofs_items,
    _parse_date_from_name,
    _preserve_georef,
    _output_geobox_for_aoi,
    _query_wofs_items,
    _resolve_raster_crs,
    _resolve_raster_transform,
    _spatial_transform_from_xy,
    _tile_intersects_aoi,
    _tile_slices,
    _validate_classifier,
    iter_wofs_tiles_from_stac,
)
from hydroseason._io_resolution import (  # noqa: F401
    _DEFAULT_CANDIDATE_RES_M,
    _DEFAULT_RETENTION_THRESHOLD,
    _mean_water_fraction,
    _next_coarser_res_m,
    plan_resolution,
    probe_amplitude,
)

__all__ = ["load_aoi", "load_extent_csv", "complete_monthly_axis", "load_monthly_masks", "load_monthly_masks_zarr", "load_wofs_from_stac", "load_wofs_monthly_extent", "plan_resolution", "probe_amplitude"]
