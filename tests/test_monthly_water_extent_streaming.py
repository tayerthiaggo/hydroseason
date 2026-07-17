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
   and does NOT grow with the total length of ``time``. This is checked by
   wrapping a call to the REAL ``monthly_water_extent(cube, time_block=...)``
   (imported from ``hydroseason.hydro_year``, not a local reimplementation)
   in a ``dask.callbacks.Callback`` that hooks ``_start``/``_pretask``/
   ``_finish`` to observe every ``dask.compute()`` call the function makes
   internally, resetting a leaf-task counter (the ``sum-*`` tasks dask/xarray
   build for ``.sum(dim=spatial_dims)``, excluding the tree-reduction
   ``sum-aggregate-*`` tasks) at the start of each such call and recording its
   tally at the end -- NOT wall-clock memory (no ``psutil``/RSS involved).
   Because the callback observes the function's own internal ``dask.compute``
   calls rather than a parallel reimplementation of its loop, a regression
   back to a single all-at-once compute (equivalent here to calling the real
   function with ``time_block`` set to the full length of ``time``) is
   directly observable: the recorded peak would scale linearly with ``time``
   instead of staying flat, and the boundedness assertion would fail. This is
   verified explicitly by
   ``test_peak_chunk_load_regression_guard_detects_reverted_all_at_once_path``.
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


class _PerComputeCallLeafTaskCounter(Callback):
    """Counts leaf spatial-reduction tasks executed within EACH scheduler run.

    dask/xarray lower ``(mask <op> value).sum(dim=spatial_dims)`` into one
    ``sum-<hash>`` task per source chunk (the partial per-chunk reduction),
    followed by a small number of ``sum-aggregate-<hash>`` tree-reduction
    tasks that combine those partials. The ``sum-*`` (non-aggregate) tasks
    are the ones that must touch/hold a spatial chunk in memory, so counting
    their executions is a direct, deterministic stand-in for "how many
    spatial chunks were live during this compute call" -- independent of
    wall-clock scheduling, thread counts, or timing noise.

    Unlike a single running total, this callback resets its counter every
    time the scheduler starts a new run (``_start``, fired once per
    ``dask.compute()`` invocation) and records the tally for that run into
    ``per_call_counts`` when the run finishes (``_finish``). Used as a
    context manager wrapped around a call to the REAL ``monthly_water_extent``
    (not a re-implementation), it observes every internal ``dask.compute()``
    call that function makes, however many there are, and lets the test
    inspect the max per-call count -- the genuine "peak chunk load per
    compute call" metric -- directly from production code execution.
    """

    def __init__(self) -> None:
        super().__init__()
        self.per_call_counts: list[int] = []
        self._current = 0

    def _start(self, dsk) -> None:  # noqa: ANN001 - dask callback signature
        self._current = 0

    def _pretask(self, key, dsk, state) -> None:  # noqa: ANN001 - dask callback signature
        name = key[0] if isinstance(key, tuple) else key
        if isinstance(name, str) and name.startswith("sum-") and "aggregate" not in name:
            self._current += 1

    def _finish(self, dsk, state, failed) -> None:  # noqa: ANN001 - dask callback signature
        self.per_call_counts.append(self._current)

    @property
    def peak(self) -> int:
        return max(self.per_call_counts) if self.per_call_counts else 0


def _peak_leaf_tasks_per_compute_call(water_mask: "xr.DataArray", *, time_block: int) -> int:
    """Call the REAL ``monthly_water_extent`` and measure its actual per-call chunk load.

    Registers ``_PerComputeCallLeafTaskCounter`` as a context manager around
    the call, so it observes every ``dask.compute()`` invocation that
    ``monthly_water_extent`` itself makes internally (one per streamed block),
    then returns the max task count seen in any single one of those calls.
    This directly instruments production code -- no reimplementation of the
    blocking loop is involved.
    """
    counter = _PerComputeCallLeafTaskCounter()
    with counter:
        monthly_water_extent(water_mask, time_block=time_block)
    return counter.peak


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

    Calls the REAL ``monthly_water_extent(cube, time_block=...)`` -- imported
    from ``hydroseason.hydro_year`` -- wrapped in a scheduler callback that
    observes every ``dask.compute()`` call the function makes internally, and
    measures the max leaf-task count seen in any single one of those calls.

    Uses identical y/x chunk shape at time=24 and time=120: the streamed
    peak leaf-task count per compute call must be the SAME at both lengths
    (bounded by time_block * n_spatial_chunks), whereas calling the same real
    function with ``time_block`` equal to the full length (which collapses
    its internal loop to one all-at-once call, architecturally identical to
    the old pre-streaming behaviour) scales linearly with time length. This
    is the crux of the perf-regression guard: if the internal streaming loop
    were deleted and ``monthly_water_extent`` reverted to a single
    all-at-once ``dask.compute()``, the "streamed" measurement below would
    itself start scaling with time length and the equality assertion would
    fail -- see the module-level verification note for a concrete check of
    this using ``time_block=<full length>`` as a stand-in for the reverted
    code path.
    """
    cube_24 = _synthetic_cube(time=24)
    cube_120 = _synthetic_cube(time=120)

    streamed_peak_24 = _peak_leaf_tasks_per_compute_call(cube_24, time_block=1)
    streamed_peak_120 = _peak_leaf_tasks_per_compute_call(cube_120, time_block=1)

    assert streamed_peak_24 == streamed_peak_120, (
        "streamed (time_block=1) peak leaf-task count per compute call must be "
        "independent of total time length"
    )

    # Sanity check that the counter is actually sensitive to workload size at
    # all -- otherwise the equality above would be trivially true because the
    # counter never counts anything. Calling the same real function with
    # time_block == full length collapses its internal loop to a single
    # all-at-once dask.compute() call (architecturally identical to the old,
    # pre-streaming code path), which must scale linearly with time length.
    all_at_once_peak_24 = _peak_leaf_tasks_per_compute_call(cube_24, time_block=24)
    all_at_once_peak_120 = _peak_leaf_tasks_per_compute_call(cube_120, time_block=120)

    assert all_at_once_peak_120 > all_at_once_peak_24
    assert all_at_once_peak_120 == pytest.approx(
        all_at_once_peak_24 * (120 / 24), rel=0, abs=1e-9
    )

    # And the streamed peak must be strictly smaller than the all-at-once
    # peak at the larger time length -- proving the bound is real, not just
    # coincidentally equal.
    assert streamed_peak_120 < all_at_once_peak_120


def test_peak_chunk_load_regression_guard_detects_reverted_all_at_once_path():
    """Directly proves the boundedness test would catch a reversion.

    If ``monthly_water_extent``'s internal loop were deleted and it went back
    to a single, all-at-once ``dask.compute()`` over the whole ``time`` axis,
    that is architecturally identical to calling the CURRENT real function
    with ``time_block`` equal to the full length of ``time`` (the loop then
    executes exactly one iteration over a slice spanning all of ``time``).
    This test measures exactly that "reverted" call shape at two different
    time lengths using the real function and the real instrumentation used
    above, and asserts the peak is NOT independent of time length in that
    case -- i.e. the assertion in
    ``test_peak_chunk_load_is_bounded_and_independent_of_time_length`` would
    fail if streaming were ever removed, because the "streamed" measurement
    would collapse to this same reverted shape.
    """
    cube_24 = _synthetic_cube(time=24)
    cube_120 = _synthetic_cube(time=120)

    reverted_peak_24 = _peak_leaf_tasks_per_compute_call(cube_24, time_block=cube_24.sizes["time"])
    reverted_peak_120 = _peak_leaf_tasks_per_compute_call(cube_120, time_block=cube_120.sizes["time"])

    assert reverted_peak_24 != reverted_peak_120, (
        "the all-at-once (reverted) call shape must scale with time length; "
        "if this ever becomes equal, the boundedness test above would no "
        "longer be able to distinguish streaming from no streaming"
    )
