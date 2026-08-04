import numpy as np
import pytest

pytest.importorskip("affine")
pytest.importorskip("shapely")

from affine import Affine
from shapely.geometry import box

from hydroseason._spatial_plan import (
    active_windows_from_mask,
    plan_spatial_slices,
    plan_storage_aligned_slices,
)


def test_thin_aoi_selects_1024_windows():
    plan = plan_spatial_slices(
        box(0, -4096, 600, 0),
        shape=(4096, 4096),
        transform=Affine(1, 0, 0, 0, -1, 0),
    )

    assert plan.selected_tile_pixels == 1024
    assert len(plan.windows) == 4
    assert plan.reason == "predicted improvement meets 15.0% minimum"
    assert plan.candidates[0].tile_pixels is None
    assert plan.to_dict()["planner_version"] == 1


def test_compact_aoi_keeps_parent_when_savings_are_below_threshold():
    plan = plan_spatial_slices(
        box(0, -2048, 2048, 0),
        shape=(2048, 2048),
        transform=Affine(1, 0, 0, 0, -1, 0),
    )

    assert plan.selected_tile_pixels is None
    assert [(w.y_start, w.y_stop, w.x_start, w.x_stop) for w in plan.windows] == [
        (0, 2048, 0, 2048)
    ]
    assert plan.reason == "best candidate is below 15.0% minimum improvement"


def test_planner_is_deterministic_and_json_serialisable():
    kwargs = dict(
        geometry=box(0, -100, 50, 0),
        shape=(100, 100),
        transform=Affine(1, 0, 0, 0, -1, 0),
        candidate_tile_pixels=(None, 50),
        tile_overhead=10.0,
    )
    assert plan_spatial_slices(**kwargs).to_dict() == plan_spatial_slices(**kwargs).to_dict()


def test_planner_rejects_invalid_cost_inputs():
    for kwargs, message in [
        ({"shape": (0, 10)}, "shape"),
        ({"pixel_cost": 0.0}, "pixel_cost"),
        ({"tile_overhead": -1.0}, "tile_overhead"),
        ({"min_improvement": 1.1}, "min_improvement"),
    ]:
        base = dict(
            geometry=box(0, -10, 10, 0),
            shape=(10, 10),
            transform=Affine(1, 0, 0, 0, -1, 0),
        )
        base.update(kwargs)
        try:
            plan_spatial_slices(**base)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_storage_aligned_plan_returns_only_intersecting_execution_chunks():
    geometry = box(0, 0, 20, 100)
    plan = plan_storage_aligned_slices(
        geometry,
        shape=(100, 100),
        transform=Affine(1, 0, 0, 0, -1, 100),
        storage_chunk=25,
    )

    assert plan.selected_tile_pixels == 25
    assert [window.tile_id for window in plan.windows] == [
        "r0c0", "r1c0", "r2c0", "r3c0"
    ]
    assert all(window.x_start == 0 and window.x_stop == 25 for window in plan.windows)


def test_storage_aligned_plan_never_expands_back_to_coarser_windows():
    geometry = box(0, 0, 20, 100)
    plan = plan_storage_aligned_slices(
        geometry,
        shape=(100, 100),
        transform=Affine(1, 0, 0, 0, -1, 100),
        storage_chunk=25,
    )

    assert sum(
        (w.y_stop - w.y_start) * (w.x_stop - w.x_start)
        for w in plan.windows
    ) == 4 * 25 * 25


# --------------------------------------------------------------------------
# active_windows_from_mask: storage/source-aligned active acquisition windows
# derived directly from a coarse boolean planning mask (W1.5), rather than
# from a vectorised polygon. Coordinates are in NATIVE pixel space: each
# True coarse cell expands to the ``factor``x``factor`` block of native
# pixels it summarises, clipped to ``native_shape``.
# --------------------------------------------------------------------------


def test_active_windows_from_mask_one_window_per_true_coarse_cell():
    coarse = np.array([
        [True, False],
        [False, True],
    ])
    windows = active_windows_from_mask(
        coarse, factor=4, native_shape=(8, 8), storage_chunk=4,
    )

    assert len(windows) == 2
    covered = {(w.y_start, w.y_stop, w.x_start, w.x_stop) for w in windows}
    assert covered == {(0, 4, 0, 4), (4, 8, 4, 8)}


def test_active_windows_from_mask_clips_partial_edge_block():
    # A 3x3 native grid coarsened by factor 2 -> 2x2 coarse grid, where the
    # last coarse row/col only covers 1 native pixel, not 2.
    coarse = np.array([
        [True, False],
        [False, True],
    ])
    windows = active_windows_from_mask(
        coarse, factor=2, native_shape=(3, 3), storage_chunk=2,
    )

    covered = {(w.y_start, w.y_stop, w.x_start, w.x_stop) for w in windows}
    # (0,0) coarse cell -> native (0:2, 0:2); (1,1) coarse cell -> native
    # (2:3, 2:3) clipped to the 3x3 shape, never overhanging it.
    assert covered == {(0, 2, 0, 2), (2, 3, 2, 3)}
    for w in windows:
        assert w.y_stop <= 3 and w.x_stop <= 3


def test_active_windows_from_mask_empty_mask_returns_no_windows():
    coarse = np.zeros((4, 4), dtype=bool)
    windows = active_windows_from_mask(
        coarse, factor=4, native_shape=(16, 16), storage_chunk=4,
    )
    assert windows == ()


def test_active_windows_from_mask_merges_adjacent_true_cells_to_storage_chunk():
    # Two adjacent True coarse cells that both fall inside the same
    # storage_chunk-aligned native block should not duplicate overlapping
    # windows -- the storage grid is the unit of dedup.
    coarse = np.array([[True, True]])
    windows = active_windows_from_mask(
        coarse, factor=2, native_shape=(2, 4), storage_chunk=4,
    )
    # Both coarse cells (native cols 0:2 and 2:4) land in the single
    # storage_chunk=4 block spanning native cols 0:4.
    assert len(windows) == 1
    assert (windows[0].y_start, windows[0].y_stop, windows[0].x_start, windows[0].x_stop) == (0, 2, 0, 4)


def test_active_windows_from_mask_rejects_unaligned_storage_chunk():
    """A coarse cell that straddles a storage boundary would otherwise drop
    native pixels outside the chunk selected by the cell's start coordinate."""
    coarse = np.array([[False, True, False]])

    with pytest.raises(ValueError, match="multiple of factor"):
        active_windows_from_mask(
            coarse, factor=3, native_shape=(3, 9), storage_chunk=4,
        )

