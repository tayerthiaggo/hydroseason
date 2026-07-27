from affine import Affine
from shapely.geometry import box

from hydroseason._spatial_plan import plan_spatial_slices, plan_storage_aligned_slices


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

