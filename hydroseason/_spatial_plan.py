"""Pure, dataset-independent geometry-cost planner for WOfS reads.

Decides whether a large AOI (area of interest) polygon should be split into
tiled grid windows for more efficient raster reads, based on a simple cost
model that trades pixel count against a fixed per-tile read overhead. This
module has no dependency on any I/O, dask, xarray, or STAC machinery -- it
only reasons about geometry, a raster ``shape``, and an affine ``transform``,
so it can be unit tested in isolation and reused by any loader that needs to
decide "one whole-AOI read, or several tiled reads?" before touching data.

The public entry point is :func:`plan_spatial_slices`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from affine import Affine
from rasterio.transform import array_bounds
from shapely.geometry import box

# Bumped whenever the selection rule, cost model, or SpatialPlan/CandidateScore
# schema changes in a way that could shift which tile size a caller receives
# for the same inputs. Callers that persist plans (e.g. as cache keys) can use
# this to invalidate stale plans rather than silently trusting old geometry.
_PLANNER_VERSION = 1


@dataclass(frozen=True)
class GridWindow:
    """A single row-major grid cell of a raster, in pixel coordinates.

    ``y_stop``/``x_stop`` are exclusive, matching Python slicing and
    ``rasterio.windows.Window`` conventions. A window with no tiling applied
    (the "parent" candidate) covers the full raster shape as one window.
    """

    tile_id: str
    y_start: int
    y_stop: int
    x_start: int
    x_stop: int

    def to_dict(self) -> dict:
        return {
            "tile_id": self.tile_id,
            "y_start": self.y_start,
            "y_stop": self.y_stop,
            "x_start": self.x_start,
            "x_stop": self.x_stop,
        }


@dataclass(frozen=True)
class CandidateScore:
    """The predicted cost of reading the AOI at one candidate tile size.

    ``tile_pixels=None`` denotes the untiled "parent" candidate: one window
    covering the whole raster grid, regardless of how little of it the AOI
    actually touches. ``windows`` holds only the grid windows that survive
    tiling (i.e. whose polygon intersects the AOI geometry); it is always a
    single full-grid window for the parent candidate.
    """

    tile_pixels: int | None
    n_tiles: int
    intersecting_pixels: int
    predicted_cost: float
    relative_improvement: float
    windows: tuple[GridWindow, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "tile_pixels": self.tile_pixels,
            "n_tiles": self.n_tiles,
            "intersecting_pixels": self.intersecting_pixels,
            "predicted_cost": self.predicted_cost,
            "relative_improvement": self.relative_improvement,
            "windows": [window.to_dict() for window in self.windows],
        }


@dataclass(frozen=True)
class SpatialPlan:
    """The planner's decision: which tile size to use, and why.

    ``windows`` are the grid windows a caller should actually read --
    the selected candidate's windows. ``candidates`` holds every candidate
    that was scored, in the order ``candidate_tile_pixels`` was given
    (index 0 is always the ``tile_pixels=None`` parent), so callers can
    inspect the full cost comparison if needed.
    """

    selected_tile_pixels: int | None
    windows: tuple[GridWindow, ...]
    candidates: tuple[CandidateScore, ...]
    reason: str
    planner_version: int = _PLANNER_VERSION

    def to_dict(self) -> dict:
        return {
            "selected_tile_pixels": self.selected_tile_pixels,
            "windows": [window.to_dict() for window in self.windows],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "reason": self.reason,
            "planner_version": self.planner_version,
        }


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


def _score_candidate(
    tile_pixels: int | None,
    geometry,
    shape: tuple[int, int],
    transform: Affine,
    pixel_cost: float,
    tile_overhead: float,
) -> CandidateScore:
    height, width = shape
    if tile_pixels is None:
        windows = (
            GridWindow(tile_id="r0c0", y_start=0, y_stop=height, x_start=0, x_stop=width),
        )
        intersecting_pixels = height * width
    else:
        surviving = []
        intersecting_pixels = 0
        for window in _grid_windows(tile_pixels, height, width):
            polygon = _window_polygon(window, transform)
            if polygon.intersects(geometry):
                surviving.append(window)
                intersecting_pixels += (window.y_stop - window.y_start) * (
                    window.x_stop - window.x_start
                )
        windows = tuple(surviving)
    n_tiles = len(windows)
    predicted_cost = pixel_cost * intersecting_pixels + tile_overhead * n_tiles
    return CandidateScore(
        tile_pixels=tile_pixels,
        n_tiles=n_tiles,
        intersecting_pixels=intersecting_pixels,
        predicted_cost=predicted_cost,
        # Filled in once the parent candidate's cost is known.
        relative_improvement=0.0,
        windows=windows,
    )


def plan_spatial_slices(
    geometry,
    *,
    shape: tuple[int, int],
    transform: Affine,
    candidate_tile_pixels: tuple[int | None, ...] = (None, 2048, 1024, 512),
    pixel_cost: float = 1.0,
    tile_overhead: float = 262144.0,
    min_improvement: float = 0.15,
) -> SpatialPlan:
    """Decide whether to tile a raster read of ``geometry``, and at what size.

    Scores every candidate in ``candidate_tile_pixels`` (index 0 must
    conceptually be the untiled parent, ``None``) under a simple additive
    cost model -- ``pixel_cost * intersecting_pixels + tile_overhead *
    n_tiles`` -- then picks the cheapest tiled candidate if it beats the
    parent's cost by at least ``min_improvement`` (a fraction, e.g. 0.15 for
    15%); otherwise keeps the untiled parent. See the module docstring for
    the geometry model.

    Deterministic and side-effect free: calling this twice with identical
    arguments produces identical ``SpatialPlan.to_dict()`` output, so callers
    may use it to key a cache.

    Raises ``ValueError`` if ``shape`` has a non-positive dimension,
    ``pixel_cost`` is not positive, ``tile_overhead`` is negative, or
    ``min_improvement`` is outside ``[0, 1]``.
    """
    height, width = shape
    if height <= 0 or width <= 0:
        raise ValueError(f"shape must have positive dimensions, got {shape!r}")
    if pixel_cost <= 0:
        raise ValueError(f"pixel_cost must be positive, got {pixel_cost!r}")
    if tile_overhead < 0:
        raise ValueError(f"tile_overhead must be non-negative, got {tile_overhead!r}")
    if not 0.0 <= min_improvement <= 1.0:
        raise ValueError(f"min_improvement must be between 0 and 1, got {min_improvement!r}")

    scores = [
        _score_candidate(tile_pixels, geometry, shape, transform, pixel_cost, tile_overhead)
        for tile_pixels in candidate_tile_pixels
    ]

    parent = scores[0]
    best = min(scores, key=lambda score: (score.predicted_cost, score.tile_pixels is not None))
    improvement = 0.0 if parent.predicted_cost == 0 else (
        parent.predicted_cost - best.predicted_cost
    ) / parent.predicted_cost
    if best.tile_pixels is not None and improvement >= min_improvement:
        selected = best
        reason = f"predicted improvement meets {min_improvement:.1%} minimum"
    else:
        selected = parent
        reason = f"best candidate is below {min_improvement:.1%} minimum improvement"

    # relative_improvement is reported per-candidate against the parent cost,
    # independent of which candidate ended up selected.
    scores = [
        CandidateScore(
            tile_pixels=score.tile_pixels,
            n_tiles=score.n_tiles,
            intersecting_pixels=score.intersecting_pixels,
            predicted_cost=score.predicted_cost,
            relative_improvement=(
                0.0
                if parent.predicted_cost == 0
                else (parent.predicted_cost - score.predicted_cost) / parent.predicted_cost
            ),
            windows=score.windows,
        )
        for score in scores
    ]
    selected = next(score for score in scores if score.tile_pixels == selected.tile_pixels)

    return SpatialPlan(
        selected_tile_pixels=selected.tile_pixels,
        windows=selected.windows,
        candidates=tuple(scores),
        reason=reason,
        planner_version=_PLANNER_VERSION,
    )


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
    selected_pixels = sum(
        (window.y_stop - window.y_start) * (window.x_stop - window.x_start)
        for window in windows
    )
    score = CandidateScore(
        tile_pixels=storage_chunk,
        n_tiles=len(windows),
        intersecting_pixels=selected_pixels,
        predicted_cost=float(selected_pixels),
        relative_improvement=0.0,
        windows=windows,
    )
    return SpatialPlan(
        selected_tile_pixels=storage_chunk,
        windows=windows,
        candidates=(score,),
        reason="storage-aligned shared-graph execution",
        planner_version=_PLANNER_VERSION,
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
    height, width = native_shape
    if height < 1 or width < 1:
        raise ValueError(f"native_shape must have positive dimensions, got {native_shape!r}")

    mask = np.asarray(coarse_mask, dtype=bool)
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
    "CandidateScore",
    "SpatialPlan",
    "plan_spatial_slices",
    "plan_storage_aligned_slices",
    "active_windows_from_mask",
]

