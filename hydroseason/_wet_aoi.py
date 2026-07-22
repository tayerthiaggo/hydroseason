"""Wet-AOI precompute: collapse a mask cube to ever-wet region and buffer it.

All geospatial imports stay inside function bodies so importing this module
never requires the raster/stac extras -- only calling a function that needs
one does. Distances are meters (scale-invariant). Morphology is done in
geometry space via shapely buffer, never scipy (not a dependency).
"""

from __future__ import annotations

import numpy as np

from hydroseason._io_geo import _preserve_georef


def compute_ever_wet(mask, *, persistence_min: float = 0.0):
    """Collapse a canonical (time, y, x) mask cube to a 2D wet-AOI boolean.

    At ``persistence_min == 0.0`` a pixel is in the wet AOI if it was water in
    *any* time step -- this preserves the superset guarantee (no ever-wet pixel
    is dropped). A positive ``persistence_min`` is an opt-in denoise knob: a
    pixel is kept only when ``wet_count / clear_count >= persistence_min``,
    where ``clear_count`` counts explicitly water-or-dry observations at that
    pixel (matching the ``n_valid`` denominator semantics of
    ``monthly_water_extent``). Pixels never observed clear are excluded.

    WARNING: any ``persistence_min > 0`` breaks the superset guarantee by
    design -- rare-but-real floods below the threshold are cut from the AOI and
    will read as zero water there forever. Leave at 0.0 unless you explicitly
    want denoising.
    """
    ever_wet = (mask == 1).any("time")
    if persistence_min <= 0.0:
        return _preserve_georef(ever_wet, mask)

    wet_count = (mask == 1).sum("time")
    clear_count = ((mask == 0) | (mask == 1)).sum("time")
    persistence = wet_count / clear_count.where(clear_count > 0)
    kept = (persistence >= persistence_min).fillna(False)
    return _preserve_georef(kept, mask)


def wet_aoi_polygon(
    ever_wet, *, close_m: float = 150.0, buffer_m: float = 300.0
):
    """Vectorize ever-wet boolean raster, close and buffer it.

    Closing (dilate-then-erode, ``buffer(+close_m).buffer(-close_m)``) fills
    gaps and reconnects thin channels *without* deleting them -- doing raw
    erosion first would permanently drop 1-2px rivers. The final outward
    ``buffer_m`` grows a safety margin. All distances are meters, invariant
    to pixel size. Returns a single dissolved GeoDataFrame row in raster CRS.
    """
    import geopandas as gpd
    import rasterio.features
    from shapely.geometry import shape
    from shapely.ops import unary_union

    crs = ever_wet.rio.crs
    transform = ever_wet.rio.transform()
    data = np.asarray(ever_wet.values, dtype=np.uint8)

    geometries = [
        shape(geom)
        for geom, value in rasterio.features.shapes(
            data, transform=transform
        )
        if value == 1
    ]
    if not geometries:
        return gpd.GeoDataFrame(
            {"geometry": []}, geometry="geometry", crs=crs
        )

    merged = unary_union(geometries)
    if close_m > 0.0:
        merged = merged.buffer(close_m).buffer(-close_m)
    if buffer_m > 0.0:
        merged = merged.buffer(buffer_m)

    from pyproj import CRS as ProjCRS
    epsg = ProjCRS.from_wkt(str(crs)).to_epsg()
    if epsg is not None:
        crs = f"EPSG:{epsg}"

    return gpd.GeoDataFrame(
        {"geometry": [merged]}, geometry="geometry", crs=crs
    )


def compute_wet_aoi(mask, *, persistence_min: float = 0.0,
                    close_m: float = 150.0, buffer_m: float = 300.0):
    """End-to-end: mask cube -> ever-wet boolean -> closed+buffered wet-AOI polygon."""
    ever_wet = compute_ever_wet(mask, persistence_min=persistence_min)
    return wet_aoi_polygon(ever_wet, close_m=close_m, buffer_m=buffer_m)


def tile_intersects_wet_aoi(tile_geobox, wet_aoi) -> bool:
    """True if the tile bbox intersects the wet AOI; fail-open when wet AOI absent.

    A missing or empty ``wet_aoi`` means "no pruning information" -- return True
    so the caller never drops a tile it should have loaded. Mirrors the bbox
    test in ``_io_geo._tile_intersects_aoi``.
    """
    if wet_aoi is None or len(wet_aoi) == 0 or bool(wet_aoi.geometry.is_empty.all()):
        return True
    from shapely.geometry import box

    bounds = tile_geobox.extent.boundingbox
    tile_polygon = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
    return bool(wet_aoi.to_crs(tile_geobox.crs).geometry.intersects(tile_polygon).any())
