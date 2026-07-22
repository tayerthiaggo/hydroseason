"""Wet-AOI precompute: collapse a mask cube to an ever-wet region and buffer it.

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
