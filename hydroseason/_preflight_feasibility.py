"""Cheap feasibility filter: is there any recurrent surface water here?

This module deliberately answers ONE question and refuses to answer more.
Session testing against 18 real AOIs established that every richer
criterion encodes a hidden assumption about which water regime counts as
"valid", and each produced wrong answers on real data: absolute
pixel-count thresholds passed a desert dunefield and a snow/shadow alpine
ridge; a core-to-ever-wet concentration ratio inverted (reservoirs 66-93%,
real rivers 2.8-4.8%); DEA's seasonal products are northern-monsoon-
windowed and score southern catchments backwards; cluster shape metrics
were noise at catchment scale.

Frequency-distribution metrics DO separate regime types cleanly, but
regime is not suitability -- a reservoir, a wetland, a salt lake and a
before/after-dam comparison are all legitimate subjects with opposite
signatures. So this filter rejects only AOIs with no recurrent water at
all, and everything else goes to the real workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# A pixel counts as recurrently wet at >=10% of its clear observations,
# summed over the whole requested window. Fixed, not per-profile: the
# multi-profile design this replaces produced gates that passed a desert.
FEASIBILITY_MIN_FREQUENCY_FRACTION = 0.10

SUPPORTED_FEASIBILITY_RESOLUTIONS: tuple[float, ...] = (30.0, 60.0, 90.0)


def _max_excluding_background_label(counts_block):
    """Reduce a bincount chunk to its max, excluding index 0 (background).

    Used as a ``map_blocks`` kernel rather than a slice-then-max, because
    ``da.bincount``'s output has an unknown chunk length until computed --
    ``[1:]`` on it eagerly resolves shapes, which is exactly the
    materialization this reduction exists to avoid. ``map_blocks`` needs no
    such shape knowledge: it runs once the underlying (single, tree-reduced)
    chunk is available and immediately collapses it to a 1-element array, so
    only that scalar -- never the full per-label counts vector -- crosses
    back out of the dask graph.
    """
    import numpy as np

    if counts_block.size <= 1:
        return np.array([0], dtype=counts_block.dtype)
    return np.array([counts_block[1:].max()], dtype=counts_block.dtype)


# The cluster bar is a fixed real-world area (~3600 m^2, one 60m pixel),
# floored at 2 pixels so contiguity stays a LIVE criterion at every
# supported resolution. A single isolated pixel is what scattered
# classifier noise looks like (DEA WOfS national commission error ~8%,
# Mueller et al. 2016) at 30m just as much as at 60m/90m -- area alone
# does not scale contiguity, so a naive area-only conversion (1 px at 60m
# and 90m) would switch the noise-discrimination check off entirely at
# exactly the resolutions where AOIs are largest and noise most abundant.
# A contiguous *group* of at least 2 pixels has real physical extent.
_MINIMUM_CLUSTER_AREA_M2 = 3600.0
_MINIMUM_CLUSTER_PIXEL_FLOOR = 2


def minimum_cluster_pixels(resolution: float) -> int:
    """Pixels needed to cover ``_MINIMUM_CLUSTER_AREA_M2`` at ``resolution``,
    floored at :data:`_MINIMUM_CLUSTER_PIXEL_FLOOR` so contiguity remains a
    live criterion at every supported resolution."""
    pixel_area = float(resolution) * float(resolution)
    return max(_MINIMUM_CLUSTER_PIXEL_FLOOR, int(round(_MINIMUM_CLUSTER_AREA_M2 / pixel_area)))


@dataclass(frozen=True)
class FeasibilityResult:
    feasible: bool
    resolution: float
    core_pixel_count: int
    cluster_count: int
    largest_cluster_pixels: int
    minimum_cluster_pixels: int
    reason: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feasible": self.feasible,
            "resolution": self.resolution,
            "core_pixel_count": self.core_pixel_count,
            "cluster_count": self.cluster_count,
            "largest_cluster_pixels": self.largest_cluster_pixels,
            "minimum_cluster_pixels": self.minimum_cluster_pixels,
            "reason": self.reason,
            "provenance": self.provenance,
        }


def assess_feasibility(annual, *, resolution: float) -> FeasibilityResult:
    """Decide whether ``annual`` shows any recurrent surface water.

    ``annual`` is normally the dataset from
    :func:`hydroseason._io_preflight_stats.open_annual_wo_statistics`
    (``count_wet``/``count_clear`` over dims ``(year, y, x)``).  The regular
    workflow may also pass the already-loaded all-time statistics dataset
    from :func:`hydroseason._io_dea_stats.open_wo_statistics` (dims
    ``(y, x)``).  Any non-spatial dimensions are summed before screening so
    both paths apply the same ``>10%`` test.

    ``resolution`` must be one of :data:`SUPPORTED_FEASIBILITY_RESOLUTIONS`
    and is NEVER silently snapped -- it is AOI-size sensitive. Measured on
    a real ~97 km^2 perennial creek, 60m yielded only 8 qualifying pixels
    with a largest cluster of 4: a genuine watercourse nearly invisible.
    Coarser resolution is a throughput lever for large catchments, not a
    default for small AOIs.
    """
    import numpy as np

    if isinstance(resolution, bool) or not isinstance(resolution, (int, float)):
        raise TypeError(f"resolution must be a real number, got {resolution!r}")
    if float(resolution) not in SUPPORTED_FEASIBILITY_RESOLUTIONS:
        raise ValueError(
            "resolution must be one of "
            f"{SUPPORTED_FEASIBILITY_RESOLUTIONS}, got {resolution!r}"
        )

    # Keep whatever backing the caller handed us -- do NOT coerce a dask
    # array to NumPy here just to reach scipy. open_annual_wo_statistics
    # materializes by default, but a materialize=False caller (or a very
    # large AOI) is exactly the case dask-backed labelling exists for, and
    # forcing a compute here would reintroduce the redundant-
    # materialization cost fixed earlier in this session.
    wet = annual["count_wet"]
    clear = annual["count_clear"]
    reduction_dims = [dim for dim in wet.dims if dim not in {"y", "x"}]
    wet_sum = wet.sum(reduction_dims).data if reduction_dims else wet.data
    clear_sum = clear.sum(reduction_dims).data if reduction_dims else clear.data
    is_dask = hasattr(wet_sum, "compute")

    # Algebraically equivalent to (wet_sum / clear_sum) >= FRACTION, but
    # never forms a float64 frequency array -- eliminates ~16 bytes/pixel
    # (float64 division result) on top of the two int64 sum arrays already
    # required, which matters at Fitzroy-scale (90,000 km^2 @ 30m) AOIs.
    # The `& (clear_sum > 0)` guard is load-bearing, not incidental: with
    # zero clear observations, `wet_sum >= FRACTION * 0` is trivially true,
    # so a never-observed pixel would otherwise count as water.
    # Keep the screen explicitly inside the observed max/ever-wet extent.
    # The frequency threshold implies this already when clear_sum > 0, but
    # retaining the mask makes the denominator boundary auditable and guards
    # against future threshold changes accidentally admitting dry pixels.
    max_water = wet_sum > 0
    core = max_water & (wet_sum >= FEASIBILITY_MIN_FREQUENCY_FRACTION * clear_sum) & (clear_sum > 0)
    required = minimum_cluster_pixels(resolution)

    # 4-way connectivity: diagonal touching is not contiguity.
    if is_dask:
        import dask
        import dask.array as da
        from dask_image.ndmeasure import label as dask_label

        labelled, cluster_count = dask_label(core)
        # Reduce to a SCALAR inside the graph -- never compute the labelled
        # array itself, nor the full per-label counts vector. The labelled
        # array is int-typed and the size of the whole AOI grid; the counts
        # vector scales with CLUSTER COUNT, not real water bodies, and can
        # exceed the labelled array's size on pathological (e.g. desert
        # checkerboard) noise -- an adversarial 2000x2000 4-connected
        # checkerboard produces 2,000,000 clusters and a 16 MB counts
        # vector, four times the int32 labelled array it was meant to avoid
        # materializing.
        #
        # da.bincount's output has an unknown length until computed, so
        # slicing it with [1:] before compute() forces an eager shape
        # resolution (defeating the point). map_blocks has no such
        # requirement: it runs against whatever chunk bincount's own
        # tree-reduce produces and collapses it to a 1-element array
        # in-graph, so only that scalar -- never the full counts vector --
        # is what dask.compute() below actually returns.
        #
        # ONE dask.compute over the tuple: the graph is shared, so the
        # underlying data is read once rather than once per reduction.
        label_counts = da.bincount(labelled.ravel())
        largest_lazy = label_counts.map_blocks(
            _max_excluding_background_label, dtype=label_counts.dtype, chunks=((1,),)
        )
        core_pixel_count, cluster_count, largest_arr = dask.compute(
            core.sum(), cluster_count, largest_lazy
        )
        core_pixel_count = int(core_pixel_count)
        cluster_count = int(cluster_count)
        largest_from_counts = int(largest_arr[0])
    else:
        from scipy import ndimage

        core_pixel_count = int(core.sum())
        labelled, cluster_count = ndimage.label(core)
        # Reduce to the maximum only -- np.bincount still forms the full
        # per-label counts vector (it is cheap on the eager NumPy path
        # already holding the labelled array), but nothing beyond a Python
        # int escapes this branch.
        counts_np = np.bincount(labelled.ravel())
        largest_from_counts = int(counts_np[1:].max()) if counts_np.size > 1 else 0

    if core_pixel_count == 0:
        return FeasibilityResult(
            feasible=False,
            resolution=float(resolution),
            core_pixel_count=0,
            cluster_count=0,
            largest_cluster_pixels=0,
            minimum_cluster_pixels=required,
            reason="no_recurrent_water",
        )

    # At least one label always exists past this point: core_pixel_count
    # > 0 means some pixel satisfied `core`, so ndimage.label/dask_label
    # assigned it a nonzero label and cluster_count >= 1.
    feasible = largest_from_counts >= required
    return FeasibilityResult(
        feasible=feasible,
        resolution=float(resolution),
        core_pixel_count=core_pixel_count,
        cluster_count=int(cluster_count),
        largest_cluster_pixels=largest_from_counts,
        minimum_cluster_pixels=required,
        reason="recurrent_water_present" if feasible else "recurrent_water_below_minimum_cluster",
    )
