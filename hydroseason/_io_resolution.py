"""Pure resolution-planning arithmetic.

No raster or file I/O happens in ``plan_resolution``; the real load at the
chosen resolution stays the caller's job.
"""

from __future__ import annotations

from hydroseason._boundary import SIGNAL_FLOOR_FRACTION
from hydroseason._io_geo import _crs_value


def plan_resolution(
    bounds_wgs84: tuple[float, float, float, float],
    target_crs: str | int,
    *,
    memory_budget_gb: float,
    observed_amplitude_pp: float | None = None,
    candidate_res_m: tuple[float, ...] = (30, 60, 100, 150, 300),
    bytes_per_scratch: float = 5.0,
    time_chunk: int = 24,
) -> tuple[float, float, float, str]:
    """Pick the finest resolution that fits a memory budget without breaking signal.

    Pure arithmetic: reprojects ``bounds_wgs84`` (WGS84/EPSG:4326 bounding box,
    as ``(minx, miny, maxx, maxy)``) into ``target_crs`` to get an AOI area in
    m^2, then estimates per-resolution peak memory and noise floor. No raster,
    file, or network I/O happens here -- callers do the real load separately
    (``load_wofs_from_stac``) once a resolution is chosen.

    Memory model: for a candidate resolution ``res`` (metres), pixel count is
    ``area_m2 / res**2``. Peak scratch bytes per pixel per timestep default to
    ``bytes_per_scratch=5``, representing the canonical int8 water mask (1
    byte) plus four boolean comparison arrays (``== water_value``, ``==
    dry_value``, ``!= outside_value``, plus one derived difference), each a
    pixel-shaped boolean/int8 array (1 byte/pixel).

    ``time_chunk`` here is a proxy for the *loaded cube's* chunk depth, not
    the reduction's peak. ``monthly_water_extent`` streams its four
    reduction accumulators (n_aoi, n_valid, n_water, n_invalid) over ``time``
    in blocks of its own ``time_block`` parameter (default 1) -- see
    ``hydroseason.hydro_year.monthly_water_extent`` -- so the reduction's
    actual peak concurrent footprint is bounded by ``time_block``, not by
    however deep the cube is chunked. What *does* still scale with
    ``time_chunk`` is ``load_wofs_from_stac``: it rechunks the dask cube it
    returns to ``{"time": min(time_chunk, len(dates)), ...}``, so a single
    chunk in the resulting dask graph genuinely spans up to ``time_chunk``
    timesteps. Even though ``monthly_water_extent`` only asks the scheduler
    for one ``time_block``-sized slice at a time, dask's scheduler operates
    on whole chunks -- depending on how tasks are fused/scheduled it can
    still materialise a full chunk's worth of data to serve a slice that
    only touches part of it. Multiplying by ``time_chunk`` therefore models
    conservative headroom for that chunk depth rather than the reduction's
    real streamed peak; it deliberately overestimates so the memory gate
    stays safe even if the scheduler doesn't fuse as favourably as
    ``time_block=1`` alone would suggest. ``peak_gb = n_pixels * time_chunk *
    bytes_per_scratch / 1e9``. Candidates are walked finest-first (ascending
    ``res_m``, since smaller pixels mean more pixels); the first (finest) one
    with ``peak_gb <= memory_budget_gb`` is the memory pick.

    Signal model: noise floor is ``100 / n_valid_at_res``, using
    ``n_valid_at_res ~= n_pixels`` (in-AOI valid fraction assumed ~1 for this
    planning estimate -- it is not an exact figure). Finer resolutions always
    have both a higher peak_gb *and* a lower (better) noise floor than coarser
    ones, so the memory pick -- the finest candidate the budget allows -- is
    already the best-signal candidate obtainable within budget; no candidate
    that costs less memory can improve on its floor. Per
    ``SIGNAL_FLOOR_FRACTION`` (from ``hydroseason._boundary``), a resolution
    is signal-safe when ``floor <= SIGNAL_FLOOR_FRACTION * observed_amplitude_pp``.

    ``reason`` values:
    - ``"ok"``: the memory pick is the finest candidate (no coarsening was
      needed to fit the budget), or no ``observed_amplitude_pp`` was supplied
      so the signal bound isn't checked.
    - ``"coarsened"``: the memory pick is coarser than the finest candidate
      (the budget forced coarsening) but still clears the signal bound --
      memory requested coarsening and signal allowed it.
    - ``"signal_veto_no_fit"``: an ``observed_amplitude_pp`` was supplied and
      the memory pick's noise floor violates the signal bound. No finer
      candidate can be substituted without exceeding the memory budget (finer
      always costs more), so no candidate satisfies both constraints.
    - ``"native_no_fit"``: even the coarsest candidate exceeds
      ``memory_budget_gb`` -- the budget is too tight for any candidate, so
      the catchment should be excluded from pattern claims.
    """
    try:
        import pyproj
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("plan_resolution requires the raster extra (pyproj).") from exc

    minx, miny, maxx, maxy = bounds_wgs84
    transformer = pyproj.Transformer.from_crs("EPSG:4326", _crs_value(target_crs), always_xy=True)
    xs, ys = transformer.transform([minx, maxx, minx, maxx], [miny, miny, maxy, maxy])
    area_m2 = (max(xs) - min(xs)) * (max(ys) - min(ys))

    finest_res_m = min(candidate_res_m)
    ordered = sorted(candidate_res_m)

    def peak_gb_at(res_m: float) -> float:
        n_pixels = area_m2 / res_m**2
        return n_pixels * time_chunk * bytes_per_scratch / 1e9

    def floor_pp_at(res_m: float) -> float:
        n_pixels = area_m2 / res_m**2
        return 100.0 / n_pixels

    memory_pick = next((res_m for res_m in ordered if peak_gb_at(res_m) <= memory_budget_gb), None)
    if memory_pick is None:
        coarsest = ordered[-1]
        return coarsest, peak_gb_at(coarsest), floor_pp_at(coarsest), "native_no_fit"

    peak_gb = peak_gb_at(memory_pick)
    floor_pp = floor_pp_at(memory_pick)

    if observed_amplitude_pp is None:
        reason = "ok" if memory_pick == finest_res_m else "coarsened"
        return memory_pick, peak_gb, floor_pp, reason

    signal_bound = SIGNAL_FLOOR_FRACTION * observed_amplitude_pp
    if floor_pp > signal_bound:
        return memory_pick, peak_gb, floor_pp, "signal_veto_no_fit"

    reason = "ok" if memory_pick == finest_res_m else "coarsened"
    return memory_pick, peak_gb, floor_pp, reason


__all__ = ["plan_resolution"]
