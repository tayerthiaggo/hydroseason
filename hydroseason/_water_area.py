"""Metric pixel-area primitive for observed water-extent area.

Area comes from the raster's actual affine transform, not from
``resolution_x * resolution_y``, so it stays correct under rotated or
sheared grids.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray as xr


def metric_pixel_area_m2(array: "xr.DataArray") -> float:
    """Pixel area in m^2 from ``array``'s affine transform.

    Requires a projected CRS with metre linear units; raises ``ValueError``
    for a missing, geographic, or non-metric CRS.
    """
    crs = array.rio.crs
    if crs is None or not crs.is_projected or crs.linear_units not in ("metre", "meter"):
        raise ValueError("water area requires a projected metric CRS")

    transform = array.rio.transform()
    return abs(transform.a * transform.e - transform.b * transform.d)


__all__ = ["metric_pixel_area_m2"]
