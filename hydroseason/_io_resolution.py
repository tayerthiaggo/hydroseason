"""Pure resolution-planning arithmetic and the cheap amplitude probe.

No raster or file I/O happens in ``plan_resolution`` itself. ``probe_amplitude``
does I/O (it calls ``load_wofs_from_stac``) but only to run a cheap, coarse
probe -- the real load at the chosen resolution stays the caller's job.
"""

from __future__ import annotations

import pandas as pd

from hydroseason._boundary import SIGNAL_FLOOR_FRACTION, robust_scale
from hydroseason._io_geo import _crs_value
from hydroseason._state_input import prepare_monthly_extent

# NOTE: ``load_wofs_from_stac`` is intentionally NOT imported at module level.
# ``probe_amplitude`` looks it up on ``hydroseason.io`` at call time so that
# ``monkeypatch.setattr(hydroseason.io, "load_wofs_from_stac", ...)`` in
# tests/test_run_multi_catchment_report.py is honoured (a name bound into this
# module's globals would be invisible to a setattr on the facade).


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


# Default candidate ladder mirrored from ``plan_resolution`` -- kept as a
# separate literal (rather than a shared import-time default) so a caller can
# pass a custom ``candidate_res_m`` to ``plan_resolution`` without silently
# changing what "one step coarser" means here.
_DEFAULT_CANDIDATE_RES_M: tuple[float, ...] = (30, 60, 100, 150, 300)

# Guard fires when the coarser pass retains less than this fraction of the
# probe pass's mean water fraction. 0.70 (retain >=70%) is chosen so that
# ordinary resampling noise -- a few percent drift from mode-resampling
# aggregation -- never trips the guard, while a real thin-channel collapse
# (braided/anabranching rivers where channels are only 1-2 pixels wide at the
# probe resolution and vanish entirely one step coarser) reliably does: losing
# a channel that carries a material share of total wetted area typically more
# than halves the observed fraction, well past a 30% drop. The threshold is a
# documented judgement call (not derived from a dataset), deliberately loose
# enough to avoid false positives on ordinary resampling variance.
_DEFAULT_RETENTION_THRESHOLD = 0.70


def _next_coarser_res_m(
    probe_res_m: float, guard_step_m: float | None, candidate_res_m: tuple[float, ...],
) -> float:
    """Resolve the "one step coarser" resolution used for the guard pass.

    If ``guard_step_m`` is given explicitly, it is used as-is (an absolute
    resolution in metres, not a multiplier) -- this lets a caller override the
    default ladder-based lookup entirely. Otherwise, "one step coarser" is
    defined relative to ``candidate_res_m`` (the same ladder
    ``plan_resolution`` walks): the smallest candidate strictly greater than
    ``probe_res_m``. If ``probe_res_m`` is at or beyond the coarsest candidate
    (or the ladder has no coarser entry), fall back to doubling
    ``probe_res_m`` -- a simple, well-understood step that still probes
    meaningfully coarser sampling without depending on the ladder's contents.
    """
    if guard_step_m is not None:
        return guard_step_m
    coarser_candidates = sorted(res for res in candidate_res_m if res > probe_res_m)
    return coarser_candidates[0] if coarser_candidates else probe_res_m * 2.0


def _mean_water_fraction(prepared: pd.DataFrame) -> float:
    """Mean observed water fraction over usable months.

    Takes the output of ``prepare_monthly_extent`` -- the exact same
    quality-screened frame fed to ``_boundary.robust_scale`` -- so the guard's
    fraction comparison and the amplitude estimate agree on which months
    count as usable. ``extent_pct`` is already ``100 * n_water / n_valid``
    restricted to usable rows, so dividing by 100 gives the mean water
    fraction on the same basis ``robust_scale`` uses for amplitude.
    """
    usable = prepared.loc[prepared["candidate_usable"], "extent_pct"]
    if not len(usable):
        return 0.0
    return float(usable.mean()) / 100.0


def probe_amplitude(
    stac_url: str, collection: str, aoi, start_date: str, end_date: str, *,
    crs: int | str | None = 3577, probe_res_m: float = 300, guard_step_m: float | None = None,
    candidate_res_m: tuple[float, ...] = _DEFAULT_CANDIDATE_RES_M,
    retention_threshold: float = _DEFAULT_RETENTION_THRESHOLD,
    cache_dir=None, force: bool = False, time_block: int = 12,
) -> dict:
    """Cheaply probe seasonal amplitude and guard against thin-channel loss when coarsening.

    Loads WOfS twice via ``load_wofs_from_stac``: once at ``probe_res_m``, once
    at one step coarser (see ``_next_coarser_res_m``) -- both coarse relative
    to any native-resolution run, so this is ~100x cheaper than a full
    fine-resolution load. This is a *probe*, not the real load: callers still
    do the real ``load_wofs_from_stac`` at whatever resolution ``plan_resolution``
    ultimately picks.

    Amplitude pipeline (matches ``_boundary.robust_scale``'s definition exactly,
    so the signal gate in ``plan_resolution`` and this detector agree): the
    probe-resolution mask goes through ``monthly_water_extent`` (raw pixel
    counts) -> ``prepare_monthly_extent`` (quality screening, produces
    ``candidate_usable`` + ``extent_pct``) -> ``robust_scale`` (10th-90th
    percentile spread of ``extent_pct`` among usable rows). Only the first
    (``probe_res_m``) pass feeds ``amplitude_pp``; the coarser pass exists
    solely to drive the guard below.

    Thin-channel guard: mean water fraction (mean ``extent_pct / 100`` over
    usable months -- see ``_mean_water_fraction``) is compared between the two
    passes. If the coarser pass retains less than ``retention_threshold``
    (default 0.70, i.e. a drop of more than 30%) of the probe pass's fraction,
    braided/thin channels that are sub-pixel at the coarser resolution are the
    most likely explanation (a real reduction in wetted area, rather than
    measurement noise, would not typically collapse this fast from one step
    on a resolution ladder). The guard then sets ``guard_caveat`` to a
    human-readable string describing the collapse (for reports, not just
    logs) and pins ``refuse_coarsen_past`` to ``probe_res_m`` -- meaning
    callers should never coarsen past this resolution for this AOI. If
    retention holds, both are ``None``.

    Returns a dict:
    - ``amplitude_pp``: seasonal amplitude estimate (percentage points) at
      ``probe_res_m``, from ``robust_scale``.
    - ``water_fraction_by_res``: ``{probe_res_m: fraction, coarser_res_m:
      fraction}`` mean water fraction at each probed resolution, so
      callers/reports can see both data points behind the guard decision.
    - ``guard_caveat``: ``None``, or a labelled human-readable string
      describing the thin-channel collapse.
    - ``refuse_coarsen_past``: ``None``, or ``probe_res_m`` if the guard fired.
    """
    coarser_res_m = _next_coarser_res_m(probe_res_m, guard_step_m, candidate_res_m)

    # Resolve load_wofs_from_stac off the hydroseason.io facade at call time so
    # tests that patch hydroseason.io.load_wofs_from_stac take effect here.
    import hydroseason.io as _io

    probe_extent = _io.load_wofs_monthly_extent(
        stac_url, collection, aoi, start_date, end_date, crs=crs,
        resolution=probe_res_m, cache_dir=cache_dir, force=force, time_block=time_block,
    )
    probe_prepared = prepare_monthly_extent(probe_extent)
    amplitude_pp, _noise_pp = robust_scale(probe_prepared)
    probe_fraction = _mean_water_fraction(probe_prepared)

    coarser_extent = _io.load_wofs_monthly_extent(
        stac_url, collection, aoi, start_date, end_date, crs=crs,
        resolution=coarser_res_m, cache_dir=cache_dir, force=force, time_block=time_block,
    )
    coarser_prepared = prepare_monthly_extent(coarser_extent)
    coarser_fraction = _mean_water_fraction(coarser_prepared)

    water_fraction_by_res = {probe_res_m: probe_fraction, coarser_res_m: coarser_fraction}

    retention = (coarser_fraction / probe_fraction) if probe_fraction > 0 else 1.0
    if probe_fraction > 0 and retention < retention_threshold:
        guard_caveat = (
            f"Thin-channel guard: mean water fraction dropped from "
            f"{probe_fraction:.4f} at {probe_res_m:.0f} m to {coarser_fraction:.4f} at "
            f"{coarser_res_m:.0f} m (retained {retention:.0%}, below the "
            f"{retention_threshold:.0%} threshold). Coarsening past {probe_res_m:.0f} m "
            f"risks losing sub-pixel/thin channels; refusing to coarsen beyond it."
        )
        refuse_coarsen_past = probe_res_m
    else:
        guard_caveat = None
        refuse_coarsen_past = None

    return {
        "amplitude_pp": amplitude_pp,
        "water_fraction_by_res": water_fraction_by_res,
        "guard_caveat": guard_caveat,
        "refuse_coarsen_past": refuse_coarsen_past,
    }


__all__ = ["plan_resolution", "probe_amplitude"]
