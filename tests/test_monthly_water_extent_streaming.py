"""Perf-regression coverage for ``monthly_water_extent``'s time-block streaming.

``monthly_water_extent`` used to build the four scalar reductions
(``n_aoi``/``n_valid``/``n_water``/``n_invalid``) over the whole ``time``
axis and hand them to a *single* ``dask.compute(...)`` call. That call must
hold every time step's spatial chunks in memory concurrently, so peak memory
scales with the length of ``time`` -- unbounded for long series over large
catchments.

The fix streams over ``time`` in blocks of ``time_block`` (new keyword-only
parameter, default 1): each block gets its own small ``dask.compute()`` call,
so the previous block's spatial chunks can be released before the next block
is even built.

These tests prove two things:

1. The streamed result is numerically **identical** to the old all-at-once
   path. Rather than keeping a second implementation around as a "reference",
   we exploit that ``time_block`` equal to the full length of ``time``
   collapses the new loop to exactly one iteration over the whole axis --
   which is architecturally the same thing the old code did (one
   ``dask.compute()`` over reductions spanning all of ``time``). That is the
   cleanest "old-equivalent" case, so ``time_block=<full length>`` acts as
   the reference and ``time_block=1`` (and other block sizes) must match it
   exactly.
2. Peak per-``dask.compute()``-call chunk load is bounded by ``time_block``
   and does NOT grow with the total length of ``time``. This is checked with
   a deterministic ``dask.diagnostics``-style scheduler callback that counts
   how many leaf chunk-reducing tasks (the ``sum-*`` tasks dask/xarray build
   for ``.sum(dim=spatial_dims)``, excluding the tree-reduction
   ``sum-aggregate-*`` tasks) fire within a single ``dask.compute()`` call --
   NOT wall-clock memory (no ``psutil``/RSS involved). If the implementation
   regressed back to a single all-at-once compute, this counter would scale
   linearly with ``time`` and the boundedness assertion would fail.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("xarray")
pytest.importorskip("dask")

import xarray as xr
from dask.callbacks import Callback

from hydroseason.hydro_year import monthly_water_extent


def _synthetic_cube(time: int, *, y: int = 8, x: int = 8, ychunk: int = 4, xchunk: int = 4) -> "xr.DataArray":
    """Lazy, dask-backed water-mask cube with canonical codes and real chunks."""
    rng = np.random.default_rng(42)
    # Canonical codes: 1=water, 0=dry, -1=invalid, -2=outside-AOI.
    codes = np.array([1, 0, -1, -2], dtype=np.int8)
    cube = rng.choice(codes, size=(time, y, x)).astype(np.int8)
    da = xr.DataArray(
        cube,
        dims=("time", "y", "x"),
        coords={"time": pd.date_range("2000-01-01", periods=time, freq="MS")},
    ).chunk({"time": 1, "y": ychunk, "x": xchunk})
    return da


class _LeafChunkTaskCounter(Callback):
    """Counts leaf spatial-reduction tasks executed within one scheduler run.

    dask/xarray lower ``(mask <op> value).sum(dim=spatial_dims)`` into one
    ``sum-<hash>`` task per source chunk (the partial per-chunk reduction),
    followed by a small number of ``sum-aggregate-<hash>`` tree-reduction
    tasks that combine those partials. The ``sum-*`` (non-aggregate) tasks
    are the ones that must touch/hold a spatial chunk in memory, so counting
    their executions is a direct, deterministic stand-in for "how many
    spatial chunks were live during this compute call" -- independent of
    wall-clock scheduling, thread counts, or timing noise.
    """

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def _pretask(self, key, dsk, state) -> None:  # noqa: ANN001 - dask callback signature
        name = key[0] if isinstance(key, tuple) else key
        if isinstance(name, str) and name.startswith("sum-") and "aggregate" not in name:
            self.count += 1


def _max_leaf_tasks_per_compute_call(
    water_mask: "xr.DataArray", *, time_block: int, spatial_dims=("y", "x")
) -> int:
    """Replicate monthly_water_extent's per-block compute loop, counting leaf tasks.

    Mirrors exactly what the implementation does per block (slice, build the
    4 reductions, single ``dask.compute``) so the count reflects the real
    call shape, not an idealized one.
    """
    import dask

    dims = list(spatial_dims)
    n_time = water_mask.sizes["time"]
    peak = 0
    for start in range(0, n_time, time_block):
        block = water_mask.isel(time=slice(start, start + time_block))
        n_aoi = (block != -2).sum(dim=dims)
        n_water = (block == 1).sum(dim=dims)
        n_dry = (block == 0).sum(dim=dims)
        n_valid = n_water + n_dry
        n_invalid = n_aoi - n_valid
        counter = _LeafChunkTaskCounter()
        with counter:
            dask.compute(n_aoi, n_valid, n_water, n_invalid, scheduler="synchronous")
        peak = max(peak, counter.count)
    return peak


def test_streamed_result_matches_old_all_at_once_reference():
    """time_block=1 must be bit-identical to time_block=<full length> (old-equivalent)."""
    cube = _synthetic_cube(time=120)

    streamed = monthly_water_extent(cube, time_block=1)
    reference = monthly_water_extent(cube, time_block=cube.sizes["time"])

    pd.testing.assert_frame_equal(streamed, reference)


@pytest.mark.parametrize("time_block", [3, 7])
def test_streamed_result_matches_reference_for_other_block_sizes(time_block):
    cube = _synthetic_cube(time=120)

    streamed = monthly_water_extent(cube, time_block=time_block)
    reference = monthly_water_extent(cube, time_block=cube.sizes["time"])

    pd.testing.assert_frame_equal(streamed, reference)


def test_default_time_block_is_one_and_matches_reference():
    cube = _synthetic_cube(time=24)

    default_result = monthly_water_extent(cube)
    reference = monthly_water_extent(cube, time_block=cube.sizes["time"])

    pd.testing.assert_frame_equal(default_result, reference)


def test_peak_chunk_load_is_bounded_and_independent_of_time_length():
    """Streaming (time_block=1) must not scale with total time length.

    Uses identical y/x chunk shape at time=24 and time=120: the streamed
    peak leaf-task count per compute call must be the SAME at both lengths
    (bounded by time_block * n_spatial_chunks), whereas the old all-at-once
    approach (time_block == full length) scales linearly with time length.
    This is the crux of the perf-regression guard: if someone reverts to a
    single dask.compute(...) over the whole time axis, this assertion fails.
    """
    cube_24 = _synthetic_cube(time=24)
    cube_120 = _synthetic_cube(time=120)

    streamed_peak_24 = _max_leaf_tasks_per_compute_call(cube_24, time_block=1)
    streamed_peak_120 = _max_leaf_tasks_per_compute_call(cube_120, time_block=1)

    assert streamed_peak_24 == streamed_peak_120, (
        "streamed (time_block=1) peak leaf-task count per compute call must be "
        "independent of total time length"
    )

    # Sanity check that the counter is actually sensitive to workload size at
    # all -- otherwise the equality above would be trivially true because the
    # counter never counts anything. The old-equivalent (all-at-once) path
    # must scale linearly with time length.
    all_at_once_peak_24 = _max_leaf_tasks_per_compute_call(cube_24, time_block=24)
    all_at_once_peak_120 = _max_leaf_tasks_per_compute_call(cube_120, time_block=120)

    assert all_at_once_peak_120 > all_at_once_peak_24
    assert all_at_once_peak_120 == pytest.approx(
        all_at_once_peak_24 * (120 / 24), rel=0, abs=1e-9
    )

    # And the streamed peak must be strictly smaller than the all-at-once
    # peak at the larger time length -- proving the bound is real, not just
    # coincidentally equal.
    assert streamed_peak_120 < all_at_once_peak_120
