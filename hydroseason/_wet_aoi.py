"""Wet-AOI precompute: collapse a mask cube to ever-wet region and buffer it.

All geospatial imports stay inside function bodies so importing this module
never requires the raster/stac extras -- only calling a function that needs
one does. Distances are meters (scale-invariant). Morphology is done in
geometry space via shapely buffer, never scipy (not a dependency).
"""

from __future__ import annotations

import re

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

    Delegates to :func:`compute_ever_wet_from_counts` after reducing ``mask``
    to per-pixel ``wet_count``/``clear_count`` -- the single shared
    implementation, so this cube-reduction path and the cached-count path
    (:func:`compute_ever_wet_from_counts`, used when only pre-aggregated
    annual counts are available on disk) can never drift apart.
    """
    wet_count = (mask == 1).sum("time")
    clear_count = ((mask == 0) | (mask == 1)).sum("time")
    return compute_ever_wet_from_counts(
        wet_count, clear_count, persistence_min=max(persistence_min, 0.0)
    )


def compute_ever_wet_from_counts(wet_count, clear_count, *, persistence_min: float = 0.0):
    """Collapse pre-aggregated per-pixel ``wet_count``/``clear_count`` to a wet-AOI boolean.

    The shared reducer behind :func:`compute_ever_wet`: given ``wet_count``
    (number of water observations) and ``clear_count`` (number of
    water-or-dry, i.e. not-invalid, observations) per pixel -- the same
    counts :func:`compute_ever_wet` derives from a mask cube via
    ``(mask == 1).sum("time")`` / ``((mask == 0) | (mask == 1)).sum("time")``
    -- this lets a caller reconstruct the identical wet-AOI boolean from
    counts alone, without ever holding the full mask cube in memory (e.g.
    counts already persisted per-year on disk and summed across years).

    At ``persistence_min == 0.0`` a pixel is kept if it was ever wet
    (``wet_count > 0``), matching ``(mask == 1).any("time")``. A positive
    ``persistence_min`` keeps a pixel only when
    ``wet_count / clear_count >= persistence_min``; pixels never observed
    clear are excluded. Raises ``ValueError`` if ``persistence_min`` is
    outside ``[0.0, 1.0]``.
    """
    if not 0.0 <= persistence_min <= 1.0:
        raise ValueError("persistence_min must be 0.0 through 1.0.")
    if persistence_min == 0.0:
        kept = wet_count > 0
    else:
        kept = ((wet_count / clear_count.where(clear_count > 0)) >= persistence_min).fillna(False)
    return _preserve_georef(kept, wet_count)


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
    import shapely
    from shapely.geometry import shape

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

    # shapely.union_all works on the array directly (STRtree-backed), rather
    # than unary_union's Python-list reduction -- a large constant-factor win
    # when rasterio.features.shapes emits many small polygons (speckle from
    # isolated wet pixels), which is the common case at fine resolution.
    merged = shapely.union_all(geometries)
    if close_m > 0.0:
        merged = merged.buffer(close_m).buffer(-close_m)
    if buffer_m > 0.0:
        merged = merged.buffer(buffer_m)

    epsg = _crs_epsg(crs)
    if epsg is not None:
        crs = f"EPSG:{epsg}"

    return gpd.GeoDataFrame(
        {"geometry": [merged]}, geometry="geometry", crs=crs
    )


def _crs_epsg(crs) -> int | None:
    try:
        epsg = crs.to_epsg()
    except Exception:
        epsg = None
    if epsg is not None:
        return int(epsg)
    try:
        wkt = crs.to_wkt()
    except Exception:
        return None
    authority = re.findall(r'AUTHORITY\["EPSG","(\d+)"\]', wkt)
    identifier = re.findall(r'ID\["EPSG",(\d+)\]', wkt)
    matches = authority or identifier
    return int(matches[-1]) if matches else None


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
    target_wet_aoi = wet_aoi.to_crs(tile_geobox.crs) if wet_aoi.crs is not None else wet_aoi
    return bool(target_wet_aoi.geometry.intersects(tile_polygon).any())
