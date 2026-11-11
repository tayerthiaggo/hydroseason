"""Pure, dataset-independent read-window planner for WOfS reads.

Splits a raster grid into storage-aligned windows and keeps only those an AOI
(area of interest) polygon or coarse planning mask touches. This module has
no dependency on any I/O, dask, xarray, or STAC machinery -- it only reasons
about geometry, a raster ``shape``, and an affine ``transform``, so it can be
unit tested in isolation.

The entry points are :func:`plan_storage_aligned_slices` and
:func:`active_windows_from_mask`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from affine import Affine
from rasterio.transform import array_bounds
from shapely.geometry import box


@dataclass(frozen=True)
class GridWindow:
    """A single row-major grid cell of a raster, in pixel coordinates.

    ``y_stop``/``x_stop`` are exclusive, matching Python slicing and
    ``rasterio.windows.Window`` conventions.
    """

    tile_id: str
    y_start: int
    y_stop: int
    x_start: int
    x_stop: int


@dataclass(frozen=True)
class SpatialPlan:
    """The read plan: the tile size used and the grid windows to read.

    ``windows`` holds only the windows whose polygon intersects the AOI.
    """

    selected_tile_pixels: int | None
    windows: tuple[GridWindow, ...]
    reason: str


def _grid_windows(tile_pixels: int, height: int, width: int) -> list[GridWindow]:
    """Row-major full-grid windows of size ``tile_pixels`` over ``height``x``width``.

    Edge tiles are clipped to the raster shape rather than overhanging it, so
    the last row/column of tiles may be smaller than ``tile_pixels``.
    """
    windows = []
    n_rows = math.ceil(height / tile_pixels)
    n_cols = math.ceil(width / tile_pixels)
    for row in range(n_rows):
        y_start = row * tile_pixels
        y_stop = min(y_start + tile_pixels, height)
        for col in range(n_cols):
            x_start = col * tile_pixels
            x_stop = min(x_start + tile_pixels, width)
            windows.append(
                GridWindow(
                    tile_id=f"r{row}c{col}",
                    y_start=y_start,
                    y_stop=y_stop,
                    x_start=x_start,
                    x_stop=x_stop,
                )
            )
    return windows


def _window_polygon(window: GridWindow, transform: Affine):
    """The world-coordinate polygon a grid window covers, via the raster transform."""
    window_transform = transform * Affine.translation(window.x_start, window.y_start)
    west, south, east, north = array_bounds(
        window.y_stop - window.y_start, window.x_stop - window.x_start, window_transform
    )
    return box(west, south, east, north)


def plan_storage_aligned_slices(
    geometry,
    *,
    shape: tuple[int, int],
    transform: Affine,
    storage_chunk: int = 512,
) -> SpatialPlan:
    if storage_chunk < 1:
        raise ValueError("storage_chunk must be at least 1")
    height, width = shape
    if height < 1 or width < 1:
        raise ValueError(f"shape must have positive dimensions, got {shape!r}")

    windows = tuple(
        window
        for window in _grid_windows(storage_chunk, height, width)
        if _window_polygon(window, transform).intersects(geometry)
    )
    return SpatialPlan(
        selected_tile_pixels=storage_chunk,
        windows=windows,
        reason="storage-aligned shared-graph execution",
    )


def active_windows_from_mask(
    coarse_mask,
    *,
    factor: int,
    native_shape: tuple[int, int],
    storage_chunk: int,
) -> tuple[GridWindow, ...]:
    """Storage-aligned native-grid ``GridWindow``s covering the True cells of a coarse mask.

    ``coarse_mask`` is a 2D boolean array (or anything ``numpy.asarray``
    coerces to one) at ``factor``-times coarser resolution than the native
    grid described by ``native_shape``. Each True coarse cell corresponds to
    one ``factor``x``factor`` block of native pixels, clipped to
    ``native_shape`` so a trailing partial coarse cell (from ``coarsen(...,
    boundary="pad")``) never overhangs the native raster.
    ``GridWindow`` coordinates are in NATIVE pixel space throughout -- this
    is a raster/chunk predicate, not a polygon: no Shapely geometry is
    built here.

    ``storage_chunk`` snaps the resulting windows onto that stride's grid
    (matching :func:`plan_storage_aligned_slices`'s tiling unit) before
    deduplicating, so two True coarse cells that both fall inside the same
    on-disk storage chunk collapse into one window rather than two
    overlapping reads of the same chunk. ``storage_chunk`` must be a
    positive multiple of ``factor`` for every coarse cell to land on exactly
    one storage-aligned block edge.

    Returns an empty tuple for an all-False mask (or a mask with no True
    cells) -- callers must treat that as "no active windows", not an error;
    :func:`build_wet_planning_footprint` is the one place a genuinely-empty
    wet mask is treated as a fail-open condition, not this helper.
    """
    if factor < 1:
        raise ValueError(f"factor must be at least 1, got {factor!r}")
    if storage_chunk < 1:
        raise ValueError(f"storage_chunk must be at least 1, got {storage_chunk!r}")
    if storage_chunk % factor != 0:
        raise ValueError(
            f"storage_chunk must be a positive multiple of factor, got "
            f"storage_chunk={storage_chunk!r}, factor={factor!r}"
        )
    height, width = native_shape
    if height < 1 or width < 1:
        raise ValueError(f"native_shape must have positive dimensions, got {native_shape!r}")

    mask = np.asarray(coarse_mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError(f"coarse_mask must be 2D, got shape {mask.shape!r}")
    rows, cols = np.nonzero(mask)
    if rows.size == 0:
        return ()

    blocks = set()
    for row, col in zip(rows.tolist(), cols.tolist()):
        y_start = min(row * factor, height)
        y_stop = min(y_start + factor, height)
        x_start = min(col * factor, width)
        x_stop = min(x_start + factor, width)
        if y_start >= y_stop or x_start >= x_stop:
            continue
        # Snap onto the storage_chunk grid so True cells sharing a chunk
        # dedup to a single window rather than staying as separate,
        # potentially overlapping native-pixel blocks.
        block_y = y_start // storage_chunk
        block_x = x_start // storage_chunk
        blocks.add((block_y, block_x))

    windows = []
    for block_y, block_x in sorted(blocks):
        y_start = block_y * storage_chunk
        x_start = block_x * storage_chunk
        y_stop = min(y_start + storage_chunk, height)
        x_stop = min(x_start + storage_chunk, width)
        windows.append(
            GridWindow(
                tile_id=f"r{block_y}c{block_x}",
                y_start=y_start,
                y_stop=y_stop,
                x_start=x_start,
                x_stop=x_stop,
            )
        )
    return tuple(windows)


__all__ = [
    "GridWindow",
    "SpatialPlan",
    "plan_storage_aligned_slices",
    "active_windows_from_mask",
]

