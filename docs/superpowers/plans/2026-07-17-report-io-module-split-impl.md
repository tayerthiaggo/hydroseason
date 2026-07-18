# Report/IO Module Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `hydroseason/io.py` and `hydroseason/report.py` — each currently bundling multiple unrelated concerns in one file — into focused modules behind unchanged public import paths, with zero behavior change.

**Architecture:** Pure move-and-re-export refactor. `io.py` becomes a facade re-exporting names from three new submodules (`_io_extent.py`, `_io_geo.py`, `_io_resolution.py`). `report.py` becomes a thin orchestrator calling into two new submodules (`_report_metrics.py`, `_report_svg.py`). No function signature, behavior, or return-value changes anywhere.

**Tech Stack:** Python, pytest. No new dependencies.

## Global Constraints

- Zero behavior change — every moved function keeps its exact body, signature, and docstring.
- Every name currently importable as `hydroseason.io.<name>` (public *and* the private ones already used externally: `_DEFAULT_CANDIDATE_RES_M`, `_clip_to_aoi`, `_classify`) must remain importable at that exact path after the split.
- `hydroseason/__init__.py`'s public API surface (`__all__` list) does not change.
- Lazy geo imports (`import geopandas`, `import rioxarray`, etc. inside function bodies) stay exactly where they are — do not hoist any of them to module level.
- `tests/test_io.py`, `tests/test_report.py`, `tests/test_run_multi_catchment_report.py` must pass **unmodified** — do not edit these files. Their current import statements are the acceptance check.
- **Monkeypatch-through-facade (do not skip):** three existing tests patch a dependency on the `hydroseason.io` module and then call a function that uses it — `test_io.py:232`/`:286` patch `hydroseason.io._clip_to_aoi` then call `load_wofs_from_stac`; `test_run_multi_catchment_report.py:429` patches `hydroseason.io.load_wofs_from_stac` then (via `run_one_catchment`) drives `probe_amplitude`. A `monkeypatch.setattr` rebinds a name **only** on the module object it targets; a re-export in the facade is a separate binding it does not reach. So after the split the call sites must resolve those two dependencies off `hydroseason.io` at **call time** (`import hydroseason.io as _io; _io.<name>(...)` inside the function body), not via a module-level `from hydroseason._io_geo import <name>` into the submodule's own globals. This is the one place a naive "move + re-export" silently breaks green tests — see T2 (`probe_amplitude` → `load_wofs_from_stac`) and T3 (`load_wofs_from_stac` → `_clip_to_aoi`).
- `tests/test_io.py::test_csv_loader_imports_without_raster_dependencies` is the specific regression check for the lazy-import guarantee — it stubs `xarray`/`dask`/`rasterio`/`geopandas`/`zarr` to `None` in `sys.modules` and asserts `hydroseason.io` still imports and `load_extent_csv` still works. Watch this one after every io.py-related step.
- `scripts/run_multi_catchment_report.py` and `scripts/compare_resolution_signal_fidelity.py` must still import successfully (both do `from hydroseason.io import ...`).

---

## Task graph

```
T0 capture pre-split HTML baseline (no dep)
T1 create _io_extent.py       (no dep)
T2 create _io_resolution.py   (no dep) -- independent of T1, parallel-safe
T3 create _io_geo.py          (no dep) -- independent of T1/T2, parallel-safe
T4 io.py becomes facade       (dep T1, T2, T3)
T5 io split full verification (dep T4)
T6 create _report_metrics.py  (no dep) -- independent of io tasks, parallel-safe
T7 create _report_svg.py      (no dep) -- independent of T6, parallel-safe
T8 report.py becomes orchestrator (dep T6, T7)
T9 report split full verification (dep T8)
```

---

## T0 — Capture pre-split HTML baseline

**Files:**
- Create: `scratch_report_baseline.html` (gitignored scratch artifact, not committed)

This runs `generate_html_report` against the *current, unsplit* `report.py` and saves the output so T9 can diff against it byte-for-byte instead of just eyeballing a length. Must run before T1 touches anything.

- [ ] **Step 1: Generate the baseline**

Run:
```bash
python -c "
import pandas as pd, numpy as np
from hydroseason import detect_hydrological_years, generate_html_report

index = pd.date_range('2018-01-01', periods=36, freq='MS')
month = index.month
wet = 40.0 * np.cos(2 * np.pi * (month - 2) / 12) + 50.0
extent = pd.DataFrame({'extent_pct': wet, 'invalid_pct': 0.0}, index=index)
hy_df = detect_hydrological_years(extent)
generate_html_report(extent, hy_df, 'scratch_report_baseline.html', title='Verify')
print('baseline written')
"
```
Expected: `baseline written`, and `scratch_report_baseline.html` exists in the repo root.

- [ ] **Step 2: Confirm it's not tracked by git (scratch file, must not be committed)**

Run: `git status --short scratch_report_baseline.html`
Expected: `??` prefix (untracked). Do not `git add` this file in any task.

No commit — this task only produces a local scratch file for T9 to compare against.

---

## T1 — Create `_io_extent.py`

**Files:**
- Create: `hydroseason/_io_extent.py`
- Modify: `hydroseason/io.py` (remove `load_extent_csv`, `complete_monthly_axis` bodies — done in T4, not here)
- Test: none new — existing `tests/test_io.py` covers this after T4

**Interfaces:**
- Produces: `load_extent_csv(path, *, date_col="date", value_col="extent_pct") -> pd.DataFrame`, `complete_monthly_axis(masks, start_date, end_date, *, invalid_value=-1, duplicate_month_policy="raise")`.

This task only creates the new file. `io.py` keeps its current content until T4 — do not delete anything from `io.py` yet, to keep the repo importable between tasks.

- [ ] **Step 1: Create `hydroseason/_io_extent.py`** with this exact content (moved verbatim from `hydroseason/io.py` lines 36-124):

```python
"""Pandas-only extent-CSV and monthly-axis helpers (no geospatial dependency)."""

from __future__ import annotations

import os
from typing import Literal

import numpy as np
import pandas as pd


def load_extent_csv(
    path: str | os.PathLike[str],
    *,
    date_col: str = "date",
    value_col: str = "extent_pct",
) -> pd.DataFrame:
    """Read a monthly extent CSV into date-indexed form for detection.

    This loader only parses dates and coerces the value column; it does not
    gapfill missing months or quality-screen invalid coverage. The CSV is
    valid input for ``detect_hydrological_years`` only if the upstream
    extent series already went through mask completion and quality
    screening (see the migration plan's gapfilling recommendation).
    """
    frame = pd.read_csv(path)
    missing = {date_col, value_col}.difference(frame.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}.")
    out = frame.copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.pop(date_col), errors="raise")).to_period("M").to_timestamp()
    out[value_col] = pd.to_numeric(out[value_col], errors="raise")
    return out.sort_index()


def complete_monthly_axis(
    masks,
    start_date: str,
    end_date: str,
    *,
    invalid_value: int = -1,
    duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Reindex a lazy mask cube to complete monthly starts; gaps become invalid."""
    if "time" not in masks.dims:
        raise ValueError("complete_monthly_axis expects a DataArray with a 'time' dimension.")
    source = pd.DatetimeIndex(np.asarray(masks.time.values)).to_period("M").to_timestamp()
    if source.has_duplicates:
        duplicates = sorted({date.strftime("%Y-%m") for date in source[source.duplicated()]})
        if duplicate_month_policy == "raise":
            raise ValueError(f"Duplicate month timestamps: {duplicates}.")
        if duplicate_month_policy != "warn":
            raise ValueError("duplicate_month_policy must be 'raise' or 'warn'.")
        import warnings

        warnings.warn(f"Duplicate month timestamps: {duplicates}; keeping first.", UserWarning, stacklevel=2)
        masks = masks.isel(time=np.flatnonzero(~source.duplicated()))
        source = pd.DatetimeIndex(np.asarray(masks.time.values))
    start = pd.Timestamp(start_date).to_period("M").to_timestamp()
    end = pd.Timestamp(end_date).to_period("M").to_timestamp()
    axis = pd.date_range(start, end, freq="MS")
    source_set = {date.strftime("%Y-%m") for date in source}
    inserted = sorted(set(masks.attrs.get("inserted_months", [])) | ({date.strftime("%Y-%m") for date in axis} - source_set))
    out = masks.assign_coords(time=("time", source)).reindex(time=axis, fill_value=np.array(invalid_value, dtype=masks.dtype).item())
    if np.issubdtype(out.dtype, np.floating):
        out = out.fillna(np.array(invalid_value, dtype=out.dtype).item())
    out.attrs.update(masks.attrs)
    out.attrs.update({"source_months": sorted(source_set), "inserted_months": inserted, "n_inserted_timesteps": len(inserted)})
    return out


__all__ = ["load_extent_csv", "complete_monthly_axis"]
```

- [ ] **Step 2: Verify the new file has no syntax errors**

Run: `python -c "import ast; ast.parse(open('hydroseason/_io_extent.py').read())"`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add hydroseason/_io_extent.py
git commit -m "refactor: extract _io_extent.py (pandas-only loaders, not yet wired)"
```

---

## T2 — Create `_io_resolution.py`

**Files:**
- Create: `hydroseason/_io_resolution.py`

**Interfaces:**
- Consumes: `hydroseason._boundary.SIGNAL_FLOOR_FRACTION`, `hydroseason._boundary.robust_scale`, `hydroseason._state_input.prepare_monthly_extent`, `hydroseason.hydro_year.monthly_water_extent`.
- Produces: `plan_resolution(...) -> tuple[float, float, float, str]`, `probe_amplitude(...) -> dict`, `_next_coarser_res_m(...)`, `_mean_water_fraction(...)`, `_DEFAULT_CANDIDATE_RES_M: tuple[float, ...]`, `_DEFAULT_RETENTION_THRESHOLD: float`.
- `probe_amplitude` calls `load_wofs_from_stac`, which lives in `_io_geo.py` (T3). **Monkeypatch-compatibility:** `tests/test_run_multi_catchment_report.py:429` does `monkeypatch.setattr(hio, "load_wofs_from_stac", ...)` where `hio = hydroseason.io`, relying on `probe_amplitude` resolving `load_wofs_from_stac` off the `hydroseason.io` module namespace at call time. A plain `from hydroseason._io_geo import load_wofs_from_stac` would bind the name in `_io_resolution`'s own globals, which that `setattr` does **not** touch — the test would then attempt real STAC I/O and its `load_mock.call_count == 3` assertion would fail. So `probe_amplitude` must call it via a **deferred, module-level lookup** on `hydroseason.io`: `import hydroseason.io as _io; _io.load_wofs_from_stac(...)`. `_crs_value` is not monkeypatched — import it normally.

- [ ] **Step 1: Create `hydroseason/_io_resolution.py`** with this exact content (moved verbatim from `hydroseason/io.py` lines 252-505, `_crs_value` helper reused from `_io_geo` per the import below):

```python
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
from hydroseason.hydro_year import monthly_water_extent

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

    probe_mask = _io.load_wofs_from_stac(
        stac_url, collection, aoi, start_date, end_date, crs=crs, resolution=probe_res_m,
    )
    probe_prepared = prepare_monthly_extent(monthly_water_extent(probe_mask))
    amplitude_pp, _noise_pp = robust_scale(probe_prepared)
    probe_fraction = _mean_water_fraction(probe_prepared)

    coarser_mask = _io.load_wofs_from_stac(
        stac_url, collection, aoi, start_date, end_date, crs=crs, resolution=coarser_res_m,
    )
    coarser_prepared = prepare_monthly_extent(monthly_water_extent(coarser_mask))
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
```

Note: this file does `from hydroseason._io_geo import _crs_value` at module level, so it will not import successfully until T3 creates `_io_geo.py`. That's expected — T4 wires everything together before anything is asked to actually run. `load_wofs_from_stac` is deliberately **not** imported here (see the module note and the monkeypatch-compatibility constraint) — `probe_amplitude` resolves it via `hydroseason.io` at call time.

- [ ] **Step 2: Verify syntax only (not import) since `_io_geo` doesn't exist yet**

Run: `python -c "import ast; ast.parse(open('hydroseason/_io_resolution.py').read())"`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add hydroseason/_io_resolution.py
git commit -m "refactor: extract _io_resolution.py (plan_resolution/probe_amplitude, not yet wired)"
```

---

## T3 — Create `_io_geo.py`

**Files:**
- Create: `hydroseason/_io_geo.py`

**Interfaces:**
- Consumes: `hydroseason._io_extent.complete_monthly_axis` (for `load_monthly_masks`, `load_monthly_masks_zarr`, `load_wofs_from_stac`).
- Produces: `load_aoi`, `load_monthly_masks`, `load_monthly_masks_zarr`, `load_wofs_from_stac`, `mark_in_aoi_nodata_as_invalid`, `AOIRasterizationError`, `GeoreferencingError`, `IrregularGridError`, plus private helpers `_validate_classifier`, `_classify`, `_preserve_georef`, `_combine_observations`, `_clip_to_aoi`, `_inside_aoi_mask_like`, `_resolve_raster_crs`, `_resolve_raster_transform`, `_spatial_transform_from_xy`, `_is_identity_transform`, `_assert_compatible_georef`, `_parse_date_from_name`, `_crs_value`.

**Monkeypatch-compatibility (critical):** `tests/test_io.py:232` and `:286` do `monkeypatch.setattr("hydroseason.io._clip_to_aoi", Mock(...))` and then call `load_wofs_from_stac`. Those tests rely on `load_wofs_from_stac` resolving `_clip_to_aoi` off the `hydroseason.io` namespace at call time. If `load_wofs_from_stac` calls a bare `_clip_to_aoi` (resolved in `_io_geo`'s own globals), the facade `setattr` is invisible and the real `_clip_to_aoi` runs on the mock dataset — raising `AOIRasterizationError`, so both tests fail. Therefore **only inside `load_wofs_from_stac`**, resolve `_clip_to_aoi` via a deferred facade lookup: `import hydroseason.io as _io; _io._clip_to_aoi(mask, target)`. `load_monthly_masks`'s own `_clip_to_aoi(mask, aoi_gdf)` call is **not** monkeypatched by any test, so leave it as a bare call — do not change it.

- [ ] **Step 1: Create `hydroseason/_io_geo.py`** with this exact content (moved verbatim from `hydroseason/io.py` lines 1-33 header/exceptions, 60-89 `load_aoi`, 127-249 raster/STAC loaders, 508-655 classify/georef helpers):

```python
"""Geospatial AOI and raster mask loaders.

Raster support is adapted from WaterMask-TSFill commit
90983c1559e7c08951096bbf196c0daedead6b4f.  All geospatial imports
(geopandas, rioxarray, xarray, pystac_client, odc.stac, rasterio, affine,
pyproj) stay inside function bodies so importing this module never requires
those packages -- only calling a function that needs one does.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import pandas as pd

from hydroseason._io_extent import complete_monthly_axis

MaskEncoding = Literal["canonical", "binary", "wofs"]


class AOIRasterizationError(RuntimeError):
    """AOI clipping or rasterization could not be applied safely."""


class GeoreferencingError(ValueError):
    """Raster lacks usable CRS or affine georeferencing."""


class IrregularGridError(GeoreferencingError):
    """Raster x/y coordinates cannot define an affine transform."""


def load_aoi(aoi, *, to_crs: str | int | None = None):
    """Load a non-empty GeoDataFrame from vector path or GeoDataFrame."""
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("load_aoi requires the raster extra (geopandas).") from exc

    if isinstance(aoi, gpd.GeoDataFrame):
        result = aoi.copy()
    elif isinstance(aoi, (str, os.PathLike)):
        path = Path(aoi)
        if not path.exists():
            raise FileNotFoundError(f"AOI file not found: {path}")
        result = gpd.read_file(path)
    else:
        raise TypeError("aoi must be a vector path or geopandas.GeoDataFrame.")
    if result.empty:
        raise ValueError("AOI GeoDataFrame is empty.")
    result = result[~result.geometry.isna() & ~result.geometry.is_empty].copy()
    if result.empty:
        raise ValueError("AOI has no valid non-empty geometries.")
    if not result.geometry.is_valid.all():
        raise ValueError(
            "AOI contains geometrically invalid (e.g. self-intersecting) "
            "geometry; fix or repair the AOI before use."
        )
    if to_crs is not None:
        result = result.to_crs(_crs_value(to_crs))
    return result


def load_monthly_masks(
    input_dir: str | os.PathLike[str],
    start_date: str,
    end_date: str,
    *,
    aoi=None,
    encoding: MaskEncoding | None = None,
    classifier: Callable | None = None,
    chunk_x: int = 512,
    chunk_y: int = 512,
    time_chunk: int = 24,
    majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Load AOI-clipped TIFF masks as lazy canonical time/y/x data.

    Explicit ``encoding`` prevents ambiguous uint8 masks from being mistaken
    for raw WOfS flags. Canonical values: dry 0, water 1, invalid -1, outside -2.
    """
    if aoi is None:
        raise ValueError("AOI is required for raster mask loading.")
    _validate_classifier(encoding, classifier)
    try:
        import rioxarray as rxr
        import xarray as xr
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("load_monthly_masks requires the raster extra.") from exc

    files = sorted(Path(input_dir).glob("water_*.tif"))
    if not files:
        raise FileNotFoundError(f"No water_*.tif files found in {input_dir}")
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    grouped: dict[pd.Timestamp, list] = {}
    for path in files:
        timestamp = _parse_date_from_name(path)
        if start <= timestamp <= end:
            arr = rxr.open_rasterio(path, chunks={"x": chunk_x, "y": chunk_y}).squeeze(drop=True)
            grouped.setdefault(timestamp.to_period("M").to_timestamp(), []).append(_classify(arr, encoding, classifier))
    if not grouped:
        raise FileNotFoundError(f"No mask files fall within {start_date} to {end_date}.")

    aoi_gdf = load_aoi(aoi)
    masks, dates, reference = [], [], None
    for month, observations in sorted(grouped.items()):
        mask = observations[0] if len(observations) == 1 else _combine_observations(xr.concat(observations, dim="time"), majority)
        mask = _clip_to_aoi(mask, aoi_gdf)
        if reference is not None:
            _assert_compatible_georef(reference, mask, context=f"month {month:%Y-%m}")
        reference = mask if reference is None else reference
        masks.append(mask)
        dates.append(month)
    return complete_monthly_axis(
        xr.concat(masks, dim="time").assign_coords(time=("time", dates)), start_date, end_date,
        duplicate_month_policy=duplicate_month_policy,
    ).chunk({"time": min(time_chunk, len(dates)), "x": chunk_x, "y": chunk_y})


def load_monthly_masks_zarr(
    zarr_path: str | os.PathLike[str], start_date: str, end_date: str, *, chunk_x: int = 512, chunk_y: int = 512,
    time_chunk: int = 24, duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Open an already-canonical, already-AOI-clipped Zarr mask cube lazily."""
    try:
        import xarray as xr
    except ImportError as exc:  # pragma: no cover
        raise ImportError("load_monthly_masks_zarr requires the raster extra.") from exc
    dataset = xr.open_zarr(zarr_path, chunks={"x": chunk_x, "y": chunk_y}, mask_and_scale=False)
    if "water_mask" not in dataset:
        raise ValueError("Zarr store must contain a 'water_mask' variable.")
    masks = dataset["water_mask"].sel(time=slice(pd.Timestamp(start_date), pd.Timestamp(end_date)))
    masks = complete_monthly_axis(masks, start_date, end_date, duplicate_month_policy=duplicate_month_policy)
    return masks.chunk({"time": min(time_chunk, masks.sizes["time"]), "x": chunk_x, "y": chunk_y})


def load_wofs_from_stac(
    stac_url: str, collection: str, aoi, start_date: str, end_date: str, *, crs: int | str | None = 3577,
    chunk_x: int = 512, chunk_y: int = 512, time_chunk: int = 24, majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise", resolution: float | None = None,
):
    """Load WOfS STAC observations, compose them monthly, and clip to required AOI."""
    if aoi is None:
        raise ValueError("AOI is required for WOfS/STAC loading.")
    try:
        import xarray as xr
        import pystac_client
        import odc.stac
        import rioxarray  # noqa: F401  (registers the .rio accessor used by _clip_to_aoi)
    except ImportError as exc:  # pragma: no cover
        raise ImportError("load_wofs_from_stac requires the stac extra.") from exc
    # DEA's public S3 bucket (dea-public-data) rejects unsigned GDAL/rasterio
    # reads unless explicitly told not to sign requests; without this, every
    # lazy dask read of the returned cube fails with CPLE_AWSInvalidCredentialsError.
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    # Resolve _clip_to_aoi off the hydroseason.io facade at call time so
    # tests that patch hydroseason.io._clip_to_aoi take effect here.
    import hydroseason.io as _io

    aoi_gdf = load_aoi(aoi)
    try:
        aoi_4326 = aoi_gdf.to_crs("EPSG:4326")
        client = pystac_client.Client.open(stac_url)
        items = list(client.search(collections=[collection], datetime=f"{start_date}/{end_date}", bbox=list(aoi_4326.total_bounds)).items())
    except Exception as exc:
        raise AOIRasterizationError("STAC AOI query failed; refusing to load an unclipped raster.") from exc
    if not items:
        raise ValueError("No STAC items found for requested AOI and date range.")
    groups: dict[pd.Timestamp, list] = {}
    for item in items:
        date = pd.Timestamp(item.properties.get("datetime") or item.properties.get("start_datetime"))
        groups.setdefault(date.to_period("M").to_timestamp(), []).append(item)
    target = aoi_gdf.to_crs(_crs_value(crs)) if crs is not None else aoi_gdf
    masks, dates, reference = [], [], None
    for month, month_items in sorted(groups.items()):
        try:
            ds = odc.stac.stac_load(month_items, bands=["water"], chunks={"x": chunk_x, "y": chunk_y}, geopolygon=target.geometry, **({"crs": _crs_value(crs)} if crs is not None else {}), **({"resolution": resolution, "resampling": "mode"} if resolution is not None else {}))
            mask = _combine_observations(_classify(ds["water"], "wofs", None), majority)
            mask = _io._clip_to_aoi(mask, target)
        except AOIRasterizationError:
            raise
        except Exception as exc:
            raise AOIRasterizationError("AOI clip failed; refusing to process an unclipped STAC month.") from exc
        if reference is not None:
            _assert_compatible_georef(reference, mask, context=f"month {month:%Y-%m}")
        reference = mask if reference is None else reference
        masks.append(mask)
        dates.append(month)
    return complete_monthly_axis(xr.concat(masks, dim="time").assign_coords(time=("time", dates)), start_date, end_date, duplicate_month_policy=duplicate_month_policy).chunk({"time": min(time_chunk, len(dates)), "x": chunk_x, "y": chunk_y})


def _validate_classifier(encoding, classifier):
    if classifier is not None and not callable(classifier):
        raise TypeError("classifier must be callable.")
    if classifier is None and encoding not in {"canonical", "binary", "wofs"}:
        raise ValueError("Specify encoding='canonical', 'binary', or 'wofs', or provide classifier=callable.")
    if classifier is not None and encoding is not None:
        raise ValueError("Pass either encoding or classifier, not both.")


def _classify(arr, encoding, classifier):
    import xarray as xr

    if classifier is not None:
        result = classifier(arr)
        if not hasattr(result, "dims"):
            raise TypeError("classifier must return an xarray.DataArray.")
        in_domain = result.isin([-2, -1, 0, 1])
        canonical = xr.where(in_domain, result, np.int8(-1)).astype(np.int8)
        return _preserve_georef(canonical, arr)
    if encoding == "canonical":
        in_domain = arr.isin([-2, -1, 0, 1])
        canonical = xr.where(in_domain, arr, np.int8(-1)).astype(np.int8)
        return _preserve_georef(canonical, arr)
    if encoding == "binary":
        return _preserve_georef(xr.where(arr == 1, np.int8(1), xr.where(arr == 0, np.int8(0), np.int8(-1))).astype(np.int8), arr)
    raw = arr.fillna(1).astype(np.uint16)
    invalid = ((raw & np.uint16(1)) != 0) | arr.isnull()
    return _preserve_georef(xr.where(invalid, np.int8(-1), xr.where(arr == 128, np.int8(1), xr.where(arr == 0, np.int8(0), np.int8(-1)))).astype(np.int8), arr)


def _preserve_georef(result, source):
    """Restore rioxarray metadata dropped by xarray classification operations."""
    try:
        result = result.rio.set_spatial_dims(x_dim="x", y_dim="y")
        crs = source.rio.crs
        if crs is not None:
            result = result.rio.write_crs(crs)
        return result.rio.write_transform(source.rio.transform())
    except Exception:
        return result


def _combine_observations(series, majority):
    water, dry, invalid = (series == 1).sum("time"), (series == 0).sum("time"), (series == -1).sum("time")
    water_wins = (water > 0) & ((water > dry) if majority else True)
    import xarray as xr

    combined = xr.where(water_wins, np.int8(1), xr.where(dry > 0, np.int8(0), xr.where(invalid > 0, np.int8(-1), np.int8(-2)))).astype(np.int8)
    return _preserve_georef(combined, series)


def _clip_to_aoi(mask, aoi_gdf):
    outside_value = np.int8(-2)
    try:
        mask = mask.rio.set_spatial_dims(x_dim="x", y_dim="y")
        crs = _resolve_raster_crs(mask)
        if crs is None:
            raise GeoreferencingError("raster is missing CRS")
        # Canonical values are already int8, so an unset nodata makes
        # rio.clip's outside-AOI fill land on NaN, which casts straight to
        # 0 (dry) instead of a real sentinel. Write nodata=-2 first so
        # clip's fill value is representable and outside pixels survive as
        # outside (-2), not dry.
        mask = mask.rio.write_nodata(outside_value)
        clipped = mask.rio.clip(aoi_gdf.to_crs(crs).geometry, drop=False, all_touched=True)
    except Exception as exc:
        raise AOIRasterizationError("AOI clip failed; refusing to process an unclipped raster.") from exc
    clipped = clipped.fillna(outside_value).astype(np.int8)
    return mark_in_aoi_nodata_as_invalid(clipped, aoi_gdf)


def mark_in_aoi_nodata_as_invalid(mask, aoi, *, outside_value: int = -2, invalid_value: int = -1):
    aoi_gdf = load_aoi(aoi)
    crs = _resolve_raster_crs(mask)
    if crs is None:
        raise AOIRasterizationError("AOI masking failed: raster is missing CRS.")
    try:
        inside = _inside_aoi_mask_like(mask, aoi_gdf.to_crs(crs))
    except Exception as exc:
        if isinstance(exc, AOIRasterizationError):
            raise
        raise AOIRasterizationError("AOI masking failed; refusing unclipped raster.") from exc
    return mask.where(~((mask == outside_value) & inside), np.int8(invalid_value)).astype(np.int8)


def _inside_aoi_mask_like(template, aoi_gdf):
    try:
        from rasterio.features import geometry_mask
        import xarray as xr

        transform = _resolve_raster_transform(template)
        inside = geometry_mask(list(aoi_gdf.geometry), out_shape=(template.sizes["y"], template.sizes["x"]), transform=transform, invert=True, all_touched=True)
        return xr.DataArray(inside, dims=("y", "x"), coords={"y": template.y, "x": template.x})
    except Exception as exc:
        raise AOIRasterizationError("AOI rasterization failed; refusing unclipped raster.") from exc


def _resolve_raster_crs(da):
    try:
        return da.rio.crs
    except Exception:
        return None


def _resolve_raster_transform(da):
    try:
        transform = da.rio.transform()
    except Exception:
        transform = None
    return _spatial_transform_from_xy(da) if transform is None or _is_identity_transform(transform) else transform


def _spatial_transform_from_xy(da):
    from affine import Affine

    x, y = np.asarray(da.x.values, dtype=float), np.asarray(da.y.values, dtype=float)
    if len(x) < 2 or len(y) < 2:
        raise GeoreferencingError("x/y axes need at least two coordinates.")
    dx, dy = np.diff(x), np.diff(y)
    if not np.allclose(dx, dx[0]) or not np.allclose(dy, dy[0]):
        raise IrregularGridError("x/y coordinate spacing is irregular.")
    return Affine(dx[0], 0, x[0] - dx[0] / 2, 0, dy[0], y[0] - dy[0] / 2)


def _is_identity_transform(transform):
    from affine import Affine

    return tuple(transform)[:6] == tuple(Affine.identity())[:6]


def _assert_compatible_georef(reference, other, *, context):
    try:
        same = _resolve_raster_crs(reference) == _resolve_raster_crs(other) and _resolve_raster_transform(reference) == _resolve_raster_transform(other) and reference.sizes["x"] == other.sizes["x"] and reference.sizes["y"] == other.sizes["y"]
    except Exception as exc:
        raise GeoreferencingError(f"{context}: cannot validate georeferencing.") from exc
    if not same:
        raise GeoreferencingError(f"{context}: raster georeferencing mismatch.")


def _parse_date_from_name(path: Path) -> pd.Timestamp:
    parts = path.stem.split("_")
    if len(parts) < 4:
        raise ValueError(f"Unexpected filename format: {path.name}")
    return pd.Timestamp(f"{parts[-3]}-{parts[-2]}-{parts[-1]}")


def _crs_value(crs):
    return f"EPSG:{crs}" if isinstance(crs, int) else crs


__all__ = [
    "load_aoi", "load_monthly_masks", "load_monthly_masks_zarr", "load_wofs_from_stac",
    "mark_in_aoi_nodata_as_invalid", "AOIRasterizationError", "GeoreferencingError", "IrregularGridError",
]
```

- [ ] **Step 2: Verify import works standalone (geo deps ARE available in the dev venv, so this should succeed now)**

Run: `python -c "import hydroseason._io_geo"`
Expected: no output, exit code 0. (If it fails with `ModuleNotFoundError: hydroseason._io_extent`, T1 wasn't committed — check.)

- [ ] **Step 3: Commit**

```bash
git add hydroseason/_io_geo.py
git commit -m "refactor: extract _io_geo.py (AOI/raster loaders + georef helpers, not yet wired)"
```

---

## T4 — `io.py` becomes a re-export facade

**Files:**
- Modify: `hydroseason/io.py` (replace entire contents)

**Interfaces:**
- Consumes: everything from `_io_extent.py`, `_io_geo.py`, `_io_resolution.py`.
- Produces: `hydroseason.io.<name>` for every name listed below — identical set to what `hydroseason.io` exposed before this task.

This is the task where `io.py` shrinks from 658 lines to a re-export shim. After this step, every existing test and script that imports from `hydroseason.io` must work unchanged — that's the whole point.

- [ ] **Step 1: Replace `hydroseason/io.py` with this exact content**

```python
"""Source-agnostic extent and raster loaders (re-export facade).

Implementation lives in ``_io_extent`` (pandas-only), ``_io_geo``
(AOI/raster loading and georeferencing), and ``_io_resolution`` (resolution
planning and the amplitude probe). This module exists so
``from hydroseason.io import X`` keeps working for every name that was
importable here before the split, including the private helpers already
used directly by scripts and tests.
"""

from __future__ import annotations

from hydroseason._io_extent import complete_monthly_axis, load_extent_csv
from hydroseason._io_geo import (
    AOIRasterizationError,
    GeoreferencingError,
    IrregularGridError,
    MaskEncoding,
    load_aoi,
    load_monthly_masks,
    load_monthly_masks_zarr,
    load_wofs_from_stac,
    mark_in_aoi_nodata_as_invalid,
    _assert_compatible_georef,
    _classify,
    _clip_to_aoi,
    _combine_observations,
    _crs_value,
    _inside_aoi_mask_like,
    _is_identity_transform,
    _parse_date_from_name,
    _preserve_georef,
    _resolve_raster_crs,
    _resolve_raster_transform,
    _spatial_transform_from_xy,
    _validate_classifier,
)
from hydroseason._io_resolution import (
    _DEFAULT_CANDIDATE_RES_M,
    _DEFAULT_RETENTION_THRESHOLD,
    _mean_water_fraction,
    _next_coarser_res_m,
    plan_resolution,
    probe_amplitude,
)

__all__ = ["load_aoi", "load_extent_csv", "complete_monthly_axis", "load_monthly_masks", "load_monthly_masks_zarr", "load_wofs_from_stac", "plan_resolution", "probe_amplitude"]
```

- [ ] **Step 2: No import cycle at module load**

The facade imports `_io_resolution`, which (top-level) imports `_io_geo._crs_value`, which (top-level) imports `_io_extent` — a straight chain, no back-edge to `hydroseason.io`. The `import hydroseason.io` statements added in `load_wofs_from_stac` / `probe_amplitude` are inside function bodies, so they only run at call time, not at import. Confirm the chain loads clean:

Run: `python -c "import hydroseason.io; print('ok')"`
Expected: `ok`. A `ImportError` / `partially initialized module` here means one of the deferred `import hydroseason.io as _io` statements leaked to module level — put it back inside the function body.

- [ ] **Step 3: Run the lazy-import regression test specifically**

Run: `pytest tests/test_io.py::test_csv_loader_imports_without_raster_dependencies -v`
Expected: PASS. If it fails, the facade's top-level imports are pulling in a geo dependency eagerly — check that `_io_geo.py` and `_io_resolution.py` have no module-level `import geopandas`/`rioxarray`/etc. (they shouldn't per T2/T3 content above).

- [ ] **Step 4: Run the full io test file**

Run: `pytest tests/test_io.py -v`
Expected: all pass (same count as before the split — 24 tests per the pre-check). Watch specifically `test_stac_loader_passes_resolution_to_stac_load` and `test_stac_loader_omits_resolution_when_none`: they `monkeypatch.setattr("hydroseason.io._clip_to_aoi", ...)` and only pass if `load_wofs_from_stac` resolves `_clip_to_aoi` via the facade (the `_io._clip_to_aoi` call from T3). A failure here with `AOIRasterizationError` means that indirection was dropped.

- [ ] **Step 5: Run the multi-catchment report test file (imports `_DEFAULT_CANDIDATE_RES_M` and does `import hydroseason.io as hio`)**

Run: `pytest tests/test_run_multi_catchment_report.py -v`
Expected: all pass (12 tests per the pre-check). The test that patches `hio.load_wofs_from_stac` and asserts `load_mock.call_count == 3` only passes if `probe_amplitude` resolves `load_wofs_from_stac` via the facade (the `_io.load_wofs_from_stac` calls from T2). A `call_count` mismatch or a real network attempt means that indirection was dropped.

- [ ] **Step 6: Verify the two scripts that import from `hydroseason.io` still import cleanly**

Run: `python -c "import ast,sys; [ast.parse(open(f).read(), f) for f in ('scripts/run_multi_catchment_report.py','scripts/compare_resolution_signal_fidelity.py')]; print('ok')"`
Expected: `ok`. (Syntax-only check; both scripts have side effects at import time via `sys.path` manipulation so a full import isn't safe to run here — the real import check is T4 Step 4/5 exercising the same `hydroseason.io` surface those scripts use.)

- [ ] **Step 7: Run the full test suite**

Run: `pytest -q`
Expected: same pass count as the pre-split baseline, zero failures.

- [ ] **Step 8: Commit**

```bash
git add hydroseason/io.py
git commit -m "refactor: io.py becomes a re-export facade over _io_extent/_io_geo/_io_resolution"
```

---

## T5 — io split full verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm `hydroseason/__init__.py` still imports cleanly and exposes the same names**

Run: `python -c "from hydroseason import load_extent_csv, load_aoi, load_wofs_from_stac, load_monthly_masks, load_monthly_masks_zarr, complete_monthly_axis; print('ok')"`
Expected: `ok`.

- [ ] **Step 2: Confirm every previously-private-but-externally-used name still resolves at its old path**

Run: `python -c "from hydroseason.io import _DEFAULT_CANDIDATE_RES_M, _clip_to_aoi, _classify; print(_DEFAULT_CANDIDATE_RES_M)"`
Expected: `(30, 60, 100, 150, 300)`.

- [ ] **Step 3: Full test suite, one more time, as the gate before moving to the report split**

Run: `pytest -q`
Expected: zero failures.

No commit — this task is a checkpoint, not a change.

---

## T6 — Create `_report_metrics.py`

**Files:**
- Create: `hydroseason/_report_metrics.py`
- Test: `tests/test_report_metrics.py` (new)

**Interfaces:**
- Consumes: `extent: pd.DataFrame`, `hydro_years: pd.DataFrame`, `labels: pd.DataFrame` (the output of `hydroseason.hydro_year.label_hydrological_months`).
- Produces: `compute_report_kpis(extent, hydro_years) -> dict`, `build_year_cards_data(extent, hydro_years, labels) -> list[dict]`, `build_monthly_records(extent, labels) -> list[dict]`.

This is the one place where the split isn't a pure verbatim move — `generate_html_report`'s KPI block, year-card loop, and monthly-records loop currently produce Python values that get formatted into HTML strings in the same breath. Here they're separated: these three functions return **plain data** (dicts/lists of primitives), no HTML. `_report_svg.py` (T7) and the orchestrator (T8) turn that data into markup.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_metrics.py`:

```python
import numpy as np
import pandas as pd
import pytest

from hydroseason import detect_hydrological_years, label_hydrological_months
from hydroseason._report_metrics import build_monthly_records, build_year_cards_data, compute_report_kpis


def _seasonal_extent(n_years=3):
    index = pd.date_range("2018-01-01", periods=12 * n_years, freq="MS")
    month = index.month
    wet_amplitude = 40.0 * np.cos(2 * np.pi * (month - 2) / 12) + 50.0
    return pd.DataFrame({"extent_pct": wet_amplitude, "invalid_pct": 0.0}, index=index)


def test_compute_report_kpis_matches_manual_calc():
    extent = _seasonal_extent(n_years=3)
    hy_df = detect_hydrological_years(extent)

    kpis = compute_report_kpis(extent, hy_df)

    assert kpis["total_months"] == len(extent)
    assert kpis["n_years"] == len(hy_df)
    assert kpis["mean_peak"] == pytest.approx(hy_df["peak_extent_pct"].mean())
    assert kpis["mean_end"] == pytest.approx(hy_df["end_extent_pct"].mean())
    assert kpis["mean_amp"] == pytest.approx(hy_df["amplitude_pct"].mean())
    assert kpis["mean_len"] == pytest.approx(hy_df["n_months_cycle"].mean())
    assert kpis["high_conf"] == len(hy_df[hy_df["confidence"] == "high"])
    assert kpis["med_conf"] == len(hy_df[hy_df["confidence"] == "medium"])
    assert kpis["low_conf"] == len(hy_df[hy_df["confidence"] == "low"])
    assert kpis["min_end"] == pytest.approx(hy_df["end_extent_pct"].min())
    assert kpis["max_peak"] == pytest.approx(hy_df["peak_extent_pct"].max())
    assert kpis["avg_invalid"] == pytest.approx(extent["invalid_pct"].mean())
    assert kpis["start_date"] == extent.index.min().strftime("%b %Y")
    assert kpis["end_date_label"] == extent.index.max().strftime("%b %Y")


def test_compute_report_kpis_empty_hydro_years():
    extent = _seasonal_extent(n_years=1)
    empty_hy = pd.DataFrame(columns=[
        "hy_year", "peak_extent_pct", "end_extent_pct", "amplitude_pct",
        "n_months_cycle", "confidence",
    ])

    kpis = compute_report_kpis(extent, empty_hy)

    assert kpis["n_years"] == 0
    assert kpis["mean_peak"] == 0.0
    assert kpis["high_conf"] == 0
    assert kpis["min_end"] == 0.0
    assert kpis["max_peak"] == 0.0


def test_build_year_cards_data_shape():
    extent = _seasonal_extent(n_years=2)
    hy_df = detect_hydrological_years(extent)
    labels = label_hydrological_months(extent.index, hy_df)

    cards = build_year_cards_data(extent, hy_df, labels)

    assert len(cards) == len(hy_df)
    for card in cards:
        assert set(["hy_val", "conf", "start_ts", "end_ts", "n_months_cycle", "amplitude_pct", "peak_month", "peak_extent_pct", "mid_dry_month", "mid_extent_pct", "end_dry_month", "end_extent_pct", "month_rows"]).issubset(card.keys())
        for month_row in card["month_rows"]:
            assert set(["ts", "season", "extent_pct", "invalid_pct", "is_peak", "is_mid", "is_end"]).issubset(month_row.keys())


def test_build_monthly_records_shape_and_values():
    extent = _seasonal_extent(n_years=1)
    hy_df = detect_hydrological_years(extent)
    labels = label_hydrological_months(extent.index, hy_df)

    records = build_monthly_records(extent, labels)

    assert len(records) == len(labels)
    first = records[0]
    assert set(["date", "display_date", "year", "season", "hy_year", "extent_pct", "invalid_pct"]) == set(first.keys())
    assert first["extent_pct"] == round(float(extent.iloc[0]["extent_pct"]), 2)
```

- [ ] **Step 2: Run test to verify it fails (module doesn't exist yet)**

Run: `pytest tests/test_report_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydroseason._report_metrics'`.

- [ ] **Step 3: Create `hydroseason/_report_metrics.py`**

```python
"""Pure data-shaping for the HTML report: KPIs, year-card rows, monthly records.

No HTML or string templating happens here -- every function returns plain
dicts/lists of primitives (str, int, float, Timestamp, None) that
``_report_svg.py`` and ``report.py`` turn into markup.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_report_kpis(extent: pd.DataFrame, hydro_years: pd.DataFrame) -> dict:
    """Summary KPI values for the report header cards and executive summary."""
    total_months = len(extent)
    start_date = extent.index.min().strftime("%b %Y") if not extent.empty else "N/A"
    end_date_label = extent.index.max().strftime("%b %Y") if not extent.empty else "N/A"

    n_years = len(hydro_years)

    if n_years > 0:
        mean_peak = hydro_years["peak_extent_pct"].mean()
        mean_end = hydro_years["end_extent_pct"].mean()
        mean_amp = hydro_years["amplitude_pct"].mean()
        mean_len = hydro_years["n_months_cycle"].mean()
        high_conf = len(hydro_years[hydro_years["confidence"] == "high"])
        med_conf = len(hydro_years[hydro_years["confidence"] == "medium"])
        low_conf = len(hydro_years[hydro_years["confidence"] == "low"])
        min_end = hydro_years["end_extent_pct"].min()
        max_peak = hydro_years["peak_extent_pct"].max()
    else:
        mean_peak = mean_end = mean_amp = mean_len = 0.0
        high_conf = med_conf = low_conf = 0
        min_end = max_peak = 0.0

    avg_invalid = extent["invalid_pct"].mean() if "invalid_pct" in extent.columns else 0.0

    return {
        "total_months": total_months,
        "start_date": start_date,
        "end_date_label": end_date_label,
        "n_years": n_years,
        "mean_peak": mean_peak,
        "mean_end": mean_end,
        "mean_amp": mean_amp,
        "mean_len": mean_len,
        "high_conf": high_conf,
        "med_conf": med_conf,
        "low_conf": low_conf,
        "min_end": min_end,
        "max_peak": max_peak,
        "avg_invalid": avg_invalid,
    }


def build_year_cards_data(extent: pd.DataFrame, hydro_years: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    """Per-hydrological-year data for the expandable year-card sections, newest first."""
    cards = []
    for _, row in hydro_years.sort_values("hy_year", ascending=False).iterrows():
        hy_val = int(row["hy_year"])
        conf = row.get("confidence", "unassigned")

        start_ts = pd.Timestamp(row["hy_start"])
        end_ts = pd.Timestamp(row["hy_end"])
        year_months = labels[(labels.index >= start_ts) & (labels.index <= end_ts)].copy()

        peak_month = pd.Timestamp(row["peak_month"])
        mid_dry_month = pd.Timestamp(row["mid_dry_month"])
        end_dry_month = pd.Timestamp(row["end_dry_month"])

        month_rows = []
        for ts, m_row in year_months.iterrows():
            ext_val = extent.loc[ts, "extent_pct"] if ts in extent.index else np.nan
            inv_val = extent.loc[ts, "invalid_pct"] if (ts in extent.index and "invalid_pct" in extent.columns) else 0.0
            month_rows.append({
                "ts": ts,
                "season": m_row["season"],
                "extent_pct": ext_val,
                "invalid_pct": inv_val,
                "is_peak": ts == peak_month,
                "is_mid": ts == mid_dry_month,
                "is_end": ts == end_dry_month,
            })

        cards.append({
            "hy_val": hy_val,
            "conf": conf,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "n_months_cycle": row["n_months_cycle"],
            "amplitude_pct": row["amplitude_pct"],
            "peak_month": peak_month,
            "peak_extent_pct": row["peak_extent_pct"],
            "mid_dry_month": mid_dry_month,
            "mid_extent_pct": row["mid_extent_pct"],
            "end_dry_month": end_dry_month,
            "end_extent_pct": row["end_extent_pct"],
            "month_rows": month_rows,
        })
    return cards


def build_monthly_records(extent: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    """Flat per-month records for the report's JS-driven filterable data table."""
    records = []
    for ts, row in labels.iterrows():
        ext_val = extent.loc[ts, "extent_pct"] if ts in extent.index else None
        inv_val = extent.loc[ts, "invalid_pct"] if (ts in extent.index and "invalid_pct" in extent.columns) else 0.0

        records.append({
            "date": ts.strftime("%Y-%m-%d"),
            "display_date": ts.strftime("%b %Y"),
            "year": ts.year,
            "season": row["season"],
            "hy_year": int(row["hy_year"]) if not pd.isna(row["hy_year"]) else None,
            "extent_pct": round(float(ext_val), 2) if ext_val is not None else None,
            "invalid_pct": round(float(inv_val), 2),
        })
    return records


__all__ = ["compute_report_kpis", "build_year_cards_data", "build_monthly_records"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report_metrics.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_report_metrics.py tests/test_report_metrics.py
git commit -m "feat: extract _report_metrics.py (pure KPI/year-card/monthly-record data, not yet wired)"
```

---

## T7 — Create `_report_svg.py`

**Files:**
- Create: `hydroseason/_report_svg.py`

**Interfaces:**
- Produces: `generate_svg_chart(extent_df, hy_df, labels_df) -> str`, `generate_seasonal_context_svg(extent_df) -> str`. (Renamed from `_generate_svg_chart`/`_generate_seasonal_context_svg` — dropping the leading underscore since they're now the public surface of this submodule; `report.py`'s orchestrator imports them by these new names.)

- [ ] **Step 1: Create `hydroseason/_report_svg.py`** with this content — body moved verbatim from `hydroseason/report.py` lines 16-421, only the two function names changed (leading underscore dropped):

```python
"""SVG chart builders for the HTML report. Pure string generation, no I/O."""

from __future__ import annotations

import html
import numpy as np
import pandas as pd


def generate_svg_chart(extent_df: pd.DataFrame, hy_df: pd.DataFrame, labels_df: pd.DataFrame) -> str:
    """Generate a clean, beautiful, offline-friendly SVG chart for water extent and seasons."""
    if extent_df.empty or len(extent_df) < 2:
        return '<div class="no-chart">Insufficient data points to render time-series chart.</div>'

    # Dimensions (main chart + a smaller HY-boundary subplot below it)
    width = 1200
    main_height = 360
    hy_height = 110
    gap = 30
    height = main_height + gap + hy_height
    pad_left = 60
    pad_right = 40
    pad_top = 30
    pad_bottom = 50

    chart_w = width - pad_left - pad_right
    chart_h = main_height - pad_top - pad_bottom

    df = extent_df.sort_index().copy()
    min_date = df.index.min()
    max_date = df.index.max()
    dt_range = (max_date - min_date).total_seconds()
    if dt_range <= 0:
        dt_range = 1.0

    # Draw shaded seasonal backgrounds
    season_bands = []
    # Identify contiguous blocks of Wet / Dry / Unassigned
    month_width = (30.5 * 24 * 3600) / dt_range * chart_w  # approximate month width

    for i, (ts, row) in enumerate(labels_df.sort_index().iterrows()):
        dt = (ts - min_date).total_seconds()
        x_start = pad_left + (dt / dt_range) * chart_w - month_width / 2
        x_end = x_start + month_width

        # Clip to chart boundaries
        x_start = max(pad_left, x_start)
        x_end = min(width - pad_right, x_end)
        if x_end <= x_start:
            continue

        season = row.get("season", "unassigned")
        if season == "Wet":
            # Blue hue (lighter for white bg)
            fill = "rgba(59, 130, 246, 0.15)"
            title_text = f"{ts.strftime('%b %Y')}: Wet Season"
        elif season == "Dry":
            # Reddish hue (lighter for white bg)
            fill = "rgba(239, 68, 68, 0.12)"
            title_text = f"{ts.strftime('%b %Y')}: Dry Season"
        else:
            fill = "transparent"
            title_text = f"{ts.strftime('%b %Y')}: Unassigned"

        season_bands.append(
            f'<rect x="{x_start:.1f}" y="{pad_top}" width="{(x_end - x_start):.1f}" height="{chart_h}" '
            f'fill="{fill}" stroke="none"><title>{title_text}</title></rect>'
        )

    # Gridlines & Labels
    gridlines = []
    # Y-axis ticks (0%, 25%, 50%, 75%, 100%)
    for pct in [0, 25, 50, 75, 100]:
        y = pad_top + (1.0 - pct / 100.0) * chart_h
        gridlines.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}" '
            f'stroke="#e2e8f0" stroke-dasharray="4,4" stroke-width="1" />'
        )
        gridlines.append(
            f'<text x="{pad_left - 10}" y="{(y + 4):.1f}" fill="#64748b" font-size="11" '
            f'text-anchor="end" font-family="sans-serif">{pct}%</text>'
        )

    # X-axis ticks (Annual boundaries)
    years = range(min_date.year, max_date.year + 1)
    for yr in years:
        tick_date = pd.Timestamp(yr, 1, 1)
        if tick_date < min_date:
            tick_date = min_date
        if tick_date > max_date:
            tick_date = max_date

        dt = (tick_date - min_date).total_seconds()
        x = pad_left + (dt / dt_range) * chart_w
        gridlines.append(
            f'<line x1="{x:.1f}" y1="{pad_top}" x2="{x:.1f}" y2="{pad_top + chart_h}" '
            f'stroke="#e2e8f0" stroke-width="1" />'
        )
        gridlines.append(
            f'<text x="{x:.1f}" y="{height - pad_bottom + 20}" fill="#64748b" font-size="11" '
            f'text-anchor="middle" font-family="sans-serif">{yr}</text>'
        )

    # Main extent line
    points = []
    invalid_points = []
    for ts, row in df.iterrows():
        val = row.get("extent_pct", np.nan)
        if pd.isna(val):
            continue
        dt = (ts - min_date).total_seconds()
        x = pad_left + (dt / dt_range) * chart_w
        y = pad_top + (1.0 - val / 100.0) * chart_h
        points.append((x, y, ts, val))

        # Track invalid coverage if high
        inv = row.get("invalid_pct", 0.0)
        if inv > 20.0:
            invalid_points.append((x, y, ts, inv))

    path_data = ""
    if points:
        path_data = f"M {points[0][0]:.1f} {points[0][1]:.1f} "
        for p in points[1:]:
            path_data += f"L {p[0]:.1f} {p[1]:.1f} "

    extent_path = (
        f'<path d="{path_data}" fill="none" stroke="#93c5fd" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round" />'
    )

    # 3-month smoothed extent, drawn thicker on top of the raw line
    smoothed = df["extent_pct"].rolling(window=3, min_periods=1, center=True).mean()
    smooth_points = []
    for ts, val in smoothed.items():
        if pd.isna(val):
            continue
        dt = (ts - min_date).total_seconds()
        x = pad_left + (dt / dt_range) * chart_w
        y = pad_top + (1.0 - val / 100.0) * chart_h
        smooth_points.append((x, y))

    smooth_path_data = ""
    if smooth_points:
        smooth_path_data = f"M {smooth_points[0][0]:.1f} {smooth_points[0][1]:.1f} "
        for p in smooth_points[1:]:
            smooth_path_data += f"L {p[0]:.1f} {p[1]:.1f} "

    smooth_path = (
        f'<path d="{smooth_path_data}" fill="none" stroke="#2563eb" stroke-width="2.5" '
        f'stroke-linecap="round" stroke-linejoin="round" />'
    )

    # Highlight Peak Wet, Mid Dry and End Dry months from hy_df
    markers = []
    for _, row in hy_df.iterrows():
        peak_t = pd.Timestamp(row["peak_month"])
        mid_t = pd.Timestamp(row["mid_dry_month"])
        end_t = pd.Timestamp(row["end_dry_month"])

        peak_val = row["peak_extent_pct"]
        mid_val = row["mid_extent_pct"]
        end_val = row["end_extent_pct"]
        confidence = row.get("confidence", "unassigned")

        # Peak marker: diamond, filled for high confidence, hollow outline for medium/low
        dt_p = (peak_t - min_date).total_seconds()
        x_p = pad_left + (dt_p / dt_range) * chart_w
        y_p = pad_top + (1.0 - peak_val / 100.0) * chart_h
        d = 7
        diamond_pts = f"{x_p:.1f},{y_p - d:.1f} {x_p + d:.1f},{y_p:.1f} {x_p:.1f},{y_p + d:.1f} {x_p - d:.1f},{y_p:.1f}"
        peak_fill = "#3b82f6" if confidence == "high" else "#ffffff"
        peak_label = f"Peak Wet {row['hy_year']} ({confidence} confidence): {peak_t.strftime('%b %Y')} ({peak_val:.1f}%)"
        markers.append(
            f'<polygon points="{diamond_pts}" fill="{peak_fill}" stroke="#3b82f6" stroke-width="2" '
            f'class="chart-marker" data-label="{html.escape(peak_label)}">'
            f'<title>{peak_label}</title>'
            f'</polygon>'
        )

        # Mid Dry marker: square
        dt_m = (mid_t - min_date).total_seconds()
        x_m = pad_left + (dt_m / dt_range) * chart_w
        y_m = pad_top + (1.0 - mid_val / 100.0) * chart_h
        s = 6
        mid_label = f"Mid Dry {row['hy_year']}: {mid_t.strftime('%b %Y')} ({mid_val:.1f}%)"
        markers.append(
            f'<rect x="{x_m - s:.1f}" y="{y_m - s:.1f}" width="{2 * s}" height="{2 * s}" '
            f'fill="#f97316" stroke="#ffffff" stroke-width="1.5" '
            f'class="chart-marker" data-label="{html.escape(mid_label)}">'
            f'<title>{mid_label}</title>'
            f'</rect>'
        )

        # End Dry marker: downward triangle (HY boundary)
        dt_e = (end_t - min_date).total_seconds()
        x_e = pad_left + (dt_e / dt_range) * chart_w
        y_e = pad_top + (1.0 - end_val / 100.0) * chart_h
        t = 7
        tri_pts = f"{x_e - t:.1f},{y_e - t * 0.6:.1f} {x_e + t:.1f},{y_e - t * 0.6:.1f} {x_e:.1f},{y_e + t * 0.8:.1f}"
        end_label = f"End Dry {row['hy_year']}: {end_t.strftime('%b %Y')} ({end_val:.1f}%)"
        markers.append(
            f'<polygon points="{tri_pts}" fill="#ef4444" stroke="#ffffff" stroke-width="1.5" '
            f'class="chart-marker" data-label="{html.escape(end_label)}">'
            f'<title>{end_label}</title>'
            f'</polygon>'
        )

    # Add points for hover/click interaction
    hover_points = []
    for x, y, ts, val in points:
        node_label = f"{ts.strftime('%b %Y')}: {val:.1f}%"
        hover_points.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#334155" opacity="0.0" '
            f'class="chart-node chart-marker" data-label="{html.escape(node_label)}">'
            f'<title>{node_label}</title>'
            f'</circle>'
        )

    # HY-boundary subplot: a step line showing which hydrological year each month belongs to
    hy_top = main_height + gap
    hy_chart_h = hy_height - pad_bottom + 10
    hy_elements = []
    hy_years_sorted = hy_df.dropna(subset=["hy_year"]).sort_values("hy_year") if not hy_df.empty else hy_df
    if not hy_years_sorted.empty:
        hy_min = hy_years_sorted["hy_year"].min()
        hy_max = hy_years_sorted["hy_year"].max()
        hy_span = max(hy_max - hy_min, 1)

        step_points = []
        for _, row in hy_years_sorted.iterrows():
            start_ts = pd.Timestamp(row["hy_start"])
            end_ts = pd.Timestamp(row["hy_end"])
            hy_val = row["hy_year"]
            y_val = hy_top + (1.0 - (hy_val - hy_min) / hy_span) * hy_chart_h
            for ts in (start_ts, end_ts):
                dt = (ts - min_date).total_seconds()
                x = pad_left + (dt / dt_range) * chart_w
                step_points.append((x, y_val))

        if step_points:
            hy_path_data = f"M {step_points[0][0]:.1f} {step_points[0][1]:.1f} "
            for p in step_points[1:]:
                hy_path_data += f"L {p[0]:.1f} {p[1]:.1f} "
            hy_elements.append(
                f'<path d="{hy_path_data}" fill="none" stroke="#334155" stroke-width="1.5" />'
            )

        for pct in (0, 50, 100):
            hy_val = hy_min + hy_span * pct / 100.0
            y = hy_top + (1.0 - pct / 100.0) * hy_chart_h
            hy_elements.append(
                f'<text x="{pad_left - 10}" y="{(y + 4):.1f}" fill="#64748b" font-size="11" '
                f'text-anchor="end" font-family="sans-serif">{int(round(hy_val))}</text>'
            )

    hy_subplot = f"""
  <text x="{pad_left}" y="{hy_top - 8}" fill="#64748b" font-size="12" font-family="sans-serif">Hydrological year labels from month-after-end-dry to end-dry boundaries</text>
  <line x1="{pad_left}" y1="{hy_top}" x2="{width - pad_right}" y2="{hy_top}" stroke="#e2e8f0" stroke-width="1" />
  {"".join(hy_elements)}"""

    svg = f"""<svg viewBox="0 0 {width} {height}" width="100%" height="100%" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
  {"".join(season_bands)}
  {"".join(gridlines)}
  {extent_path}
  {smooth_path}
  {"".join(markers)}
  {"".join(hover_points)}
  {hy_subplot}
</svg>"""
    return svg


def generate_seasonal_context_svg(extent_df: pd.DataFrame) -> str:
    """Two-panel SVG: monthly climatology (mean +/- 1 std) and raw-vs-smoothed time series."""
    if extent_df.empty:
        return '<div class="no-chart">Insufficient data points to render seasonal context chart.</div>'

    df = extent_df.sort_index().copy()

    width = 1200
    height = 320
    gap = 50
    panel_w = (width - gap) / 2
    pad_left = 55
    pad_right = 20
    pad_top = 30
    pad_bottom = 45
    panel_chart_w = panel_w - pad_left - pad_right
    panel_chart_h = height - pad_top - pad_bottom

    # --- Left panel: monthly climatology (mean +/- 1 std) ---
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly = df.groupby(df.index.month)["extent_pct"].agg(["mean", "std"]).reindex(range(1, 13))
    monthly["std"] = monthly["std"].fillna(0.0)
    max_val = max((monthly["mean"] + monthly["std"]).max(), 1.0)

    bars = []
    bar_w = panel_chart_w / 12 * 0.65
    slot_w = panel_chart_w / 12
    for i, month_num in enumerate(range(1, 13)):
        mean_val = monthly.loc[month_num, "mean"]
        std_val = monthly.loc[month_num, "std"]
        if pd.isna(mean_val):
            continue
        x_center = pad_left + slot_w * (i + 0.5)
        bar_h = (mean_val / max_val) * panel_chart_h
        y_top = pad_top + panel_chart_h - bar_h
        bars.append(
            f'<rect x="{x_center - bar_w / 2:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'fill="#60a5fa" stroke="#2563eb" stroke-width="1">'
            f'<title>{month_names[i]}: {mean_val:.2f}% +/- {std_val:.2f}%</title></rect>'
        )
        err_top = pad_top + panel_chart_h - min((mean_val + std_val) / max_val * panel_chart_h, panel_chart_h)
        err_bottom = pad_top + panel_chart_h - max((mean_val - std_val) / max_val * panel_chart_h, 0)
        bars.append(
            f'<line x1="{x_center:.1f}" y1="{err_top:.1f}" x2="{x_center:.1f}" y2="{err_bottom:.1f}" '
            f'stroke="#1e293b" stroke-width="1.5" />'
        )
        bars.append(
            f'<text x="{x_center:.1f}" y="{height - pad_bottom + 16:.1f}" fill="#64748b" font-size="10" '
            f'text-anchor="middle" font-family="sans-serif">{month_names[i]}</text>'
        )

    left_gridlines = []
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        val = max_val * frac
        y = pad_top + panel_chart_h - frac * panel_chart_h
        left_gridlines.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + panel_chart_w}" y2="{y:.1f}" '
            f'stroke="#e2e8f0" stroke-dasharray="4,4" stroke-width="1" />'
        )
        left_gridlines.append(
            f'<text x="{pad_left - 8}" y="{(y + 4):.1f}" fill="#64748b" font-size="10" '
            f'text-anchor="end" font-family="sans-serif">{val:.1f}%</text>'
        )

    left_panel = f"""
  <text x="{pad_left}" y="16" fill="#334155" font-size="13" font-weight="600" font-family="sans-serif">Long-term monthly climatology (+/-1 std)</text>
  {"".join(left_gridlines)}
  {"".join(bars)}"""

    # --- Right panel: raw vs 3-month smoothed time series ---
    right_x0 = panel_w + gap
    min_date = df.index.min()
    max_date = df.index.max()
    dt_range = (max_date - min_date).total_seconds() or 1.0
    right_chart_w = panel_chart_w
    series_max = max(df["extent_pct"].max(), 1.0)

    raw_pts = []
    for ts, val in df["extent_pct"].items():
        if pd.isna(val):
            continue
        dt = (ts - min_date).total_seconds()
        x = right_x0 + pad_left + (dt / dt_range) * right_chart_w
        y = pad_top + (1.0 - val / series_max) * panel_chart_h
        raw_pts.append((x, y))

    smoothed = df["extent_pct"].rolling(window=3, min_periods=1, center=True).mean()
    smooth_pts = []
    for ts, val in smoothed.items():
        if pd.isna(val):
            continue
        dt = (ts - min_date).total_seconds()
        x = right_x0 + pad_left + (dt / dt_range) * right_chart_w
        y = pad_top + (1.0 - val / series_max) * panel_chart_h
        smooth_pts.append((x, y))

    def _path(pts):
        if not pts:
            return ""
        d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f} "
        for p in pts[1:]:
            d += f"L {p[0]:.1f} {p[1]:.1f} "
        return d

    raw_path = f'<path d="{_path(raw_pts)}" fill="none" stroke="#93c5fd" stroke-width="1.2" />'
    smooth_path_r = f'<path d="{_path(smooth_pts)}" fill="none" stroke="#2563eb" stroke-width="2.2" />'

    right_gridlines = []
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        val = series_max * frac
        y = pad_top + panel_chart_h - frac * panel_chart_h
        right_gridlines.append(
            f'<line x1="{right_x0 + pad_left}" y1="{y:.1f}" x2="{right_x0 + pad_left + right_chart_w}" y2="{y:.1f}" '
            f'stroke="#e2e8f0" stroke-dasharray="4,4" stroke-width="1" />'
        )
        right_gridlines.append(
            f'<text x="{right_x0 + pad_left - 8}" y="{(y + 4):.1f}" fill="#64748b" font-size="10" '
            f'text-anchor="end" font-family="sans-serif">{val:.1f}%</text>'
        )

    years = range(min_date.year, max_date.year + 1, max(1, (max_date.year - min_date.year) // 6 or 1))
    for yr in years:
        tick_date = pd.Timestamp(yr, 1, 1)
        tick_date = min(max(tick_date, min_date), max_date)
        dt = (tick_date - min_date).total_seconds()
        x = right_x0 + pad_left + (dt / dt_range) * right_chart_w
        right_gridlines.append(
            f'<text x="{x:.1f}" y="{height - pad_bottom + 16:.1f}" fill="#64748b" font-size="10" '
            f'text-anchor="middle" font-family="sans-serif">{yr}</text>'
        )

    right_panel = f"""
  <text x="{right_x0 + pad_left}" y="16" fill="#334155" font-size="13" font-weight="600" font-family="sans-serif">Extent time series - raw vs smoothed</text>
  {"".join(right_gridlines)}
  {raw_path}
  {smooth_path_r}"""

    svg = f"""<svg viewBox="0 0 {width} {height}" width="100%" height="100%" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
  {left_panel}
  {right_panel}
</svg>"""
    return svg


__all__ = ["generate_svg_chart", "generate_seasonal_context_svg"]
```

- [ ] **Step 2: Verify import works standalone**

Run: `python -c "import hydroseason._report_svg; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add hydroseason/_report_svg.py
git commit -m "refactor: extract _report_svg.py (SVG chart builders, not yet wired)"
```

---

## T8 — `report.py` becomes a thin orchestrator

**Files:**
- Modify: `hydroseason/report.py` (replace entire contents)

**Interfaces:**
- Consumes: `hydroseason._report_metrics.{compute_report_kpis, build_year_cards_data, build_monthly_records}`, `hydroseason._report_svg.{generate_svg_chart, generate_seasonal_context_svg}`, `hydroseason.hydro_year.label_hydrological_months`.
- Produces: `generate_html_report(extent, hydro_years, output_path, title="HydroSeason Seasonal Analysis") -> Path` — identical signature and behavior to before.

The HTML template itself (the big f-string with CSS/JS, lines 596-1323 of the original) stays inline in `generate_html_report` — it is not independently reusable and splitting it further would just create an artificial seam. What moves out is the *data preparation* (now in `_report_metrics`/`_report_svg`, done in T6/T7); this task rewires `generate_html_report` to call those instead of computing inline, and rebuilds the two loops (`year_cards`, `monthly_records`) that turn the now-external data into HTML fragments / JSON.

- [ ] **Step 1: Replace `hydroseason/report.py` with this exact content**

```python
"""HTML Report Generator for HydroSeason.

Generates a gorgeous, self-contained, responsive, and interactive HTML report
summarizing water-extent seasonal detection results.

Orchestrates ``_report_metrics`` (KPI/year-card/monthly-record data) and
``_report_svg`` (chart markup) into the final HTML document.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
import pandas as pd

from hydroseason._report_metrics import build_monthly_records, build_year_cards_data, compute_report_kpis
from hydroseason._report_svg import generate_seasonal_context_svg, generate_svg_chart


def _render_year_card(card: dict) -> str:
    conf_cls = f"badge-{card['conf']}"

    month_rows_html = []
    for m_row in card["month_rows"]:
        ts = m_row["ts"]
        ext_val = m_row["extent_pct"]
        inv_val = m_row["invalid_pct"]

        ext_str = f"{ext_val:.1f}%" if not pd.isna(ext_val) else "N/A"
        inv_str = f"{inv_val:.1f}%" if inv_val > 0 else "0%"

        label_style = "season-wet" if m_row["season"] == "Wet" else "season-dry"
        label_text = m_row["season"]

        marker_html = ""
        if m_row["is_peak"]:
            marker_html = '<span class="cell-marker marker-wet">Wet Peak</span>'
        elif m_row["is_end"]:
            marker_html = '<span class="cell-marker marker-dry">Dry End</span>'
        elif m_row["is_mid"]:
            marker_html = '<span class="cell-marker marker-mid">Mid Dry</span>'

        month_rows_html.append(f"""
            <tr>
              <td>{ts.strftime("%b %Y")}</td>
              <td><span class="season-badge {label_style}">{label_text}</span></td>
              <td><strong>{ext_str}</strong></td>
              <td>{inv_str}</td>
              <td>{marker_html}</td>
            </tr>""")

    month_table = f"""
        <table class="nested-table">
          <thead>
            <tr>
              <th>Month</th>
              <th>Season Assignment</th>
              <th>Water Extent</th>
              <th>Invalid/Cloud Cover</th>
              <th>Key Event</th>
            </tr>
          </thead>
          <tbody>
            {"".join(month_rows_html)}
          </tbody>
        </table>"""

    return f"""
        <details class="year-card" id="hy-card-{card['hy_val']}">
          <summary class="year-header">
            <div class="year-title-group">
              <span class="expand-icon">▶</span>
              <span class="year-number">HY {card['hy_val']}</span>
              <span class="year-dates">{card['start_ts'].strftime("%b %Y")} – {card['end_ts'].strftime("%b %Y")}</span>
            </div>
            <div class="year-meta-group">
              <span class="summary-stat">Cycle: <strong>{card['n_months_cycle']} mos</strong></span>
              <span class="summary-stat">Amplitude: <strong>{card['amplitude_pct']:.1f}%</strong></span>
              <span class="confidence-badge {conf_cls}">{card['conf'].upper()}</span>
            </div>
          </summary>
          <div class="year-detail-content">
            <div class="detail-kpis">
              <div class="detail-kpi-card">
                <span class="detail-kpi-label">Peak Wet Month</span>
                <span class="detail-kpi-value value-wet">{card['peak_month'].strftime("%B %Y")}</span>
                <span class="detail-kpi-sub">{card['peak_extent_pct']:.1f}% extent</span>
              </div>
              <div class="detail-kpi-card">
                <span class="detail-kpi-label">Mid-Dry Target</span>
                <span class="detail-kpi-value value-mid">{card['mid_dry_month'].strftime("%B %Y")}</span>
                <span class="detail-kpi-sub">{card['mid_extent_pct']:.1f}% extent</span>
              </div>
              <div class="detail-kpi-card">
                <span class="detail-kpi-label">End Dry Month</span>
                <span class="detail-kpi-value value-dry">{card['end_dry_month'].strftime("%B %Y")}</span>
                <span class="detail-kpi-sub">{card['end_extent_pct']:.1f}% extent</span>
              </div>
            </div>
            {month_table}
          </div>
        </details>"""


def generate_html_report(
    extent: pd.DataFrame,
    hydro_years: pd.DataFrame,
    output_path: str | Path,
    title: str = "HydroSeason Seasonal Analysis",
) -> Path:
    """Generate a self-contained interactive HTML report of the hydrological season detection.

    Parameters
    ----------
    extent : pd.DataFrame
        Monthly water extent DataFrame (must contain 'extent_pct' index should be DatetimeIndex).
    hydro_years : pd.DataFrame
        Hydrological years DataFrame returned by `detect_hydrological_years`.
    output_path : str | Path
        Path to save the generated HTML file.
    title : str, default "HydroSeason Seasonal Analysis"
        Title shown in the report header.

    Returns
    -------
    Path
        Absolute path to the written HTML file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from hydroseason.hydro_year import label_hydrological_months
    labels = label_hydrological_months(extent.index, hydro_years)

    kpis = compute_report_kpis(extent, hydro_years)
    year_cards_data = build_year_cards_data(extent, hydro_years, labels)
    monthly_records = build_monthly_records(extent, labels)

    total_months = kpis["total_months"]
    start_date = kpis["start_date"]
    end_date = kpis["end_date_label"]
    n_years = kpis["n_years"]
    mean_peak = kpis["mean_peak"]
    mean_end = kpis["mean_end"]
    mean_amp = kpis["mean_amp"]
    mean_len = kpis["mean_len"]
    high_conf = kpis["high_conf"]
    min_end = kpis["min_end"]
    max_peak = kpis["max_peak"]
    avg_invalid = kpis["avg_invalid"]

    year_cards = [_render_year_card(card) for card in year_cards_data]

    svg_chart = generate_svg_chart(extent, hydro_years, labels)
    seasonal_context_svg = generate_seasonal_context_svg(extent)

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');
    
    :root {{
      --bg-main: #f8fafc;
      --bg-card: #ffffff;
      --border: #e2e8f0;
      --text-main: #334155;
      --text-muted: #64748b;
      
      --wet: #10b981;
      --wet-bg: rgba(16, 185, 129, 0.15);
      --dry: #f59e0b;
      --dry-bg: rgba(245, 158, 11, 0.15);
      --danger: #ef4444;
      --mid: #3b82f6;
      
      --accent: #2563eb;
    }}
    
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    
    body {{
      font-family: 'Roboto', sans-serif;
      background-color: var(--bg-main);
      color: var(--text-main);
      line-height: 1.5;
      padding: 24px;
    }}
    
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    
    header {{
      margin-bottom: 32px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 20px;
    }}
    
    h1 {{
      font-size: 2.2rem;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 8px;
    }}
    
    .subtitle {{
      color: var(--text-muted);
      font-size: 1.05rem;
      font-weight: 400;
    }}
    
    .grid {{
      display: grid;
      gap: 16px;
      margin-bottom: 32px;
    }}
    
    .grid.cards {{
      grid-template-columns: repeat(4, 1fr);
    }}
    
    .grid.two {{
      grid-template-columns: repeat(2, 1fr);
    }}
    
    .card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .card .value {{
      font-size: 2rem;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 4px;
    }}
    
    .card .label {{
      font-size: 0.85rem;
      color: var(--text-muted);
      line-height: 1.3;
    }}
    
    .report-text {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .report-text h2 {{
      margin-bottom: 16px;
      font-size: 1.2rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
    }}
    
    .report-text p {{
      margin-bottom: 12px;
    }}
    
    .report-text ul, .report-text ol {{
      margin-left: 20px;
      margin-bottom: 12px;
    }}
    
    .report-text li {{
      margin-bottom: 6px;
    }}
    
    .chart-container {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      position: relative;
      margin-top: 16px;
    }}
    
    .chart-svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    
    .chart-node {{
      transition: r 0.15s ease, opacity 0.15s ease;
      cursor: pointer;
    }}

    .chart-node:hover {{
      r: 8;
      opacity: 0.8;
    }}

    .chart-marker {{
      cursor: pointer;
    }}

    .chart-tooltip {{
      position: absolute;
      display: none;
      background-color: #172033;
      color: #ffffff;
      font-size: 0.8rem;
      padding: 6px 10px;
      border-radius: 6px;
      pointer-events: none;
      white-space: nowrap;
      transform: translate(-50%, -100%);
      z-index: 10;
      box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }}

    .legend-container {{
      display: flex;
      gap: 16px;
      justify-content: center;
      margin-top: 16px;
      font-size: 0.85rem;
    }}
    
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--text-muted);
    }}
    
    .legend-color {{
      width: 12px;
      height: 12px;
      border-radius: 3px;
    }}
    
    .legend-circle {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }}

    .legend-shape {{
      width: 14px;
      height: 14px;
      flex-shrink: 0;
    }}

    .year-cards-container {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 40px;
    }}
    
    .year-card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      transition: border-color 0.2s ease;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .year-card[open] {{
      border-color: var(--accent);
    }}
    
    .year-header {{
      padding: 16px 20px;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      user-select: none;
      list-style: none;
    }}
    
    .year-header::-webkit-details-marker {{
      display: none;
    }}
    
    .year-title-group {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    
    .expand-icon {{
      font-size: 0.8rem;
      color: var(--text-muted);
      transition: transform 0.2s ease;
    }}
    
    .year-card[open] .expand-icon {{
      transform: rotate(90deg);
    }}
    
    .year-number {{
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text-main);
    }}
    
    .year-dates {{
      font-size: 0.9rem;
      color: var(--text-muted);
      font-weight: 400;
    }}
    
    .year-meta-group {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    
    .summary-stat {{
      font-size: 0.9rem;
      color: var(--text-muted);
    }}
    
    .confidence-badge {{
      font-size: 0.75rem;
      font-weight: 600;
      padding: 4px 8px;
      border-radius: 4px;
      letter-spacing: 0.05em;
    }}
    
    .badge-high {{
      background-color: var(--wet-bg);
      color: var(--wet);
    }}
    
    .badge-medium {{
      background-color: var(--dry-bg);
      color: #b45309;
    }}
    
    .badge-low {{
      background-color: rgba(239, 68, 68, 0.15);
      color: var(--danger);
    }}
    
    .year-detail-content {{
      padding: 0 20px 20px 20px;
      border-top: 1px solid var(--border);
      background-color: #fafafa;
    }}
    
    .detail-kpis {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 16px;
      margin-bottom: 20px;
    }}
    
    .detail-kpi-card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px;
    }}
    
    .detail-kpi-label {{
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      margin-bottom: 4px;
      display: block;
    }}
    
    .detail-kpi-value {{
      font-size: 1.15rem;
      font-weight: 600;
    }}
    
    .value-wet {{ color: var(--wet); }}
    .value-dry {{ color: var(--danger); }}
    .value-mid {{ color: var(--mid); }}
    
    .detail-kpi-sub {{
      font-size: 0.8rem;
      color: var(--text-muted);
      display: block;
      margin-top: 2px;
    }}
    
    .nested-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }}
    
    .nested-table th, .nested-table td {{
      padding: 8px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    
    .nested-table th {{
      background-color: #f1f5f9;
      color: var(--text-main);
      font-weight: 600;
      font-size: 0.8rem;
    }}
    
    .season-badge {{
      font-size: 0.8rem;
      font-weight: 500;
      padding: 2px 6px;
      border-radius: 4px;
    }}
    
    .season-wet {{
      background-color: var(--wet-bg);
      color: #047857;
    }}
    
    .season-dry {{
      background-color: var(--dry-bg);
      color: #b45309;
    }}
    
    .cell-marker {{
      font-size: 0.75rem;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 4px;
    }}
    
    .marker-wet {{
      background-color: var(--wet);
      color: #ffffff;
    }}
    
    .marker-mid {{
      background-color: var(--mid);
      color: #ffffff;
    }}
    
    .marker-dry {{
      background-color: var(--danger);
      color: #ffffff;
    }}
    
    .filters-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
      align-items: center;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .filter-item {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    
    .filter-item label {{
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
    }}
    
    .filter-item select, .filter-item input {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 6px 12px;
      border-radius: 4px;
      font-family: inherit;
      outline: none;
    }}
    
    .filter-item select:focus, .filter-item input:focus {{
      border-color: var(--accent);
    }}
    
    .main-table-container {{
      background-color: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    
    .main-table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }}
    
    .main-table th, .main-table td {{
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
    }}
    
    .main-table th {{
      background-color: #f1f5f9;
      color: var(--text-main);
      font-weight: 600;
      font-size: 0.85rem;
    }}
    
    .main-table tbody tr:hover {{
      background-color: #f8fafc;
    }}
    
    @media (max-width: 900px) {{
      .grid.cards, .grid.two {{ grid-template-columns: 1fr; }}
      .detail-kpis {{ grid-template-columns: 1fr; }}
    }}
    
    @media print {{
      body {{ background: white; }}
      .filters-row {{ display: none; }}
      .card, .report-text, .year-card, .main-table-container {{ box-shadow: none; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>{html.escape(title)}</h1>
      <p class="subtitle">Manager-ready summary of hydrological-year workflow based on remote-sensing water extent series.</p>
    </header>
    
    <main>
      <section class="grid cards">
        <div class="card"><div class="value">{n_years}</div><div class="label">hydrological years<br><small>{start_date} to {end_date}</small></div></div>
        <div class="card"><div class="value">{mean_amp:.1f}%</div><div class="label">mean annual amplitude<br><small>diff between peak and end dry</small></div></div>
        <div class="card"><div class="value">{mean_len:.1f}</div><div class="label">mean cycle length<br><small>months per hydro-year</small></div></div>
        <div class="card"><div class="value">{high_conf}</div><div class="label">high confidence years<br><small>out of {n_years} total years</small></div></div>
        <div class="card"><div class="value">{min_end:.1f}%</div><div class="label">lower water extent at end of dry season<br><small>minimum across all hydro-years</small></div></div>
        <div class="card"><div class="value">{max_peak:.1f}%</div><div class="label">higher water extent in wet season<br><small>maximum across all hydro-years</small></div></div>
        <div class="card"><div class="value">{mean_end:.1f}%</div><div class="label">average water extent at end of dry season<br><small>mean across all hydro-years</small></div></div>
        <div class="card"><div class="value">{avg_invalid:.1f}%</div><div class="label">average invalid/cloud cover<br><small>mean across {total_months} months of observations</small></div></div>
      </section>
      
      <section class="grid two">
        <div class="report-text">
          <h2>Executive Summary</h2>
          <p>This report details the seasonal dynamics of surface water extent derived from satellite observations. The timeseries has been analyzed to detect continuous hydrological years, isolating the natural wet and dry phases of the landscape.</p>
          <ul>
            <li><b>{n_years} total hydrological years</b> were successfully detected across {total_months} months of observations.</li>
            <li>The average cycle length is <b>{mean_len:.1f} months</b>.</li>
            <li><b>{high_conf} years ({round(high_conf/n_years*100) if n_years else 0}%)</b> are classified as high-confidence based on data availability and clear amplitude signals.</li>
          </ul>
        </div>
        <div class="report-text">
          <h2>Workflow</h2>
          <ol>
            <li>Load and gap-fill remote sensing water extent observations over the target period.</li>
            <li>Detect hydrological years by identifying localized peaks (Wet season) and subsequent minima (End Dry season).</li>
            <li>Calculate the Mid-Dry target month for each year to represent the transition period.</li>
            <li>Label all intermediate months based on their position within the defined hydrological years.</li>
            <li>Export visual summaries and underlying statistics.</li>
          </ol>
        </div>
      </section>

      <section class="report-text">
        <h2>Hydrological-Year Signal</h2>
        <p>The chart below displays the continuous water extent percentage over time. The background is shaded to indicate the assigned seasonal context (blue for Wet, red for Dry). Key points in each cycle are highlighted: Peak Wet (blue diamond, filled for high confidence), Mid-Dry (orange square), and End-Dry (red triangle, hydrological-year boundary). Click any marker or line point to see its exact value. The lower panel shows which hydrological year each month belongs to.</p>

        <div class="chart-container">
          {svg_chart}
          <div class="chart-tooltip" data-tooltip-for="hy-signal"></div>
          <div class="legend-container">
            <div class="legend-item"><div class="legend-color" style="background-color: var(--wet-bg);"></div> Wet Season</div>
            <div class="legend-item"><div class="legend-color" style="background-color: var(--dry-bg);"></div> Dry Season</div>
            <div class="legend-item"><div class="legend-color" style="background-color: #93c5fd; height: 2px;"></div> Monthly extent (raw)</div>
            <div class="legend-item"><div class="legend-color" style="background-color: var(--accent); height: 2px;"></div> 3-mo smoothed</div>
            <div class="legend-item"><svg class="legend-shape" viewBox="0 0 16 16"><polygon points="8,1 15,8 8,15 1,8" fill="#3b82f6" stroke="#3b82f6"/></svg> Peak Wet (high confidence)</div>
            <div class="legend-item"><svg class="legend-shape" viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" fill="#f97316"/></svg> Mid Dry</div>
            <div class="legend-item"><svg class="legend-shape" viewBox="0 0 16 16"><polygon points="2,3 14,3 8,14" fill="#ef4444"/></svg> End Dry (HY boundary)</div>
          </div>
        </div>
      </section>

      <section class="report-text">
        <h2>Seasonal Context</h2>
        <p>Wet-season peaks and dry-season stress months vary by year, so the analysis avoids fixed calendar-month assumptions. This matters for persistent pools, where antecedent catchment response can shift the timing of water retention.</p>
        <div class="chart-container">
          {seasonal_context_svg}
        </div>
      </section>

      <div class="report-text" style="margin-bottom: 32px;">
        <h2>Yearly Cycle Details</h2>
        <p>Expand individual hydrological years to view monthly breakdowns and detailed statistics.</p>
        <div class="year-cards-container" style="margin-top: 16px;">
          {"".join(year_cards)}
        </div>
      </div>
      
      <div class="report-text">
        <h2>Raw Data Browser</h2>
        <p>Filter and explore the monthly extent data directly.</p>
        
        <div class="filters-row" style="margin-top: 16px;">
          <div class="filter-item">
            <label for="yearFilter">Filter by Year</label>
            <select id="yearFilter">
              <option value="all">All Years</option>
            </select>
          </div>
          <div class="filter-item">
            <label for="seasonFilter">Filter by Season</label>
            <select id="seasonFilter">
              <option value="all">All Seasons</option>
              <option value="Wet">Wet</option>
              <option value="Dry">Dry</option>
            </select>
          </div>
          <div class="filter-item">
            <label for="invalidFilter">Data Quality</label>
            <select id="invalidFilter">
              <option value="all">All Records</option>
              <option value="clean">Clean (≤ 10% Invalid)</option>
              <option value="warn">Warning (> 10% Invalid)</option>
            </select>
          </div>
        </div>
        
        <div class="main-table-container">
          <table class="main-table" id="dataTable">
            <thead>
              <tr>
                <th>Date</th>
                <th>Season</th>
                <th>Hydro Year</th>
                <th>Extent (%)</th>
                <th>Invalid (%)</th>
              </tr>
            </thead>
            <tbody>
              <!-- Populated by JS -->
            </tbody>
          </table>
        </div>
      </div>
    </main>
  </div>

  <script>
    // Data Injected from Python
    const chartData = {json.dumps(monthly_records)};
    
    document.addEventListener('DOMContentLoaded', () => {{
      // Click-to-reveal tooltips for chart markers/points
      document.querySelectorAll('.chart-container').forEach((container) => {{
        const tooltip = container.querySelector('.chart-tooltip');
        if (!tooltip) return;

        container.addEventListener('click', (evt) => {{
          const marker = evt.target.closest('.chart-marker');
          if (!marker) {{
            tooltip.style.display = 'none';
            return;
          }}
          const label = marker.getAttribute('data-label');
          if (!label) return;

          const containerRect = container.getBoundingClientRect();
          const markerRect = marker.getBoundingClientRect();
          tooltip.textContent = label;
          tooltip.style.left = (markerRect.left - containerRect.left + markerRect.width / 2) + 'px';
          tooltip.style.top = (markerRect.top - containerRect.top) + 'px';
          tooltip.style.display = 'block';
          evt.stopPropagation();
        }});
      }});

      document.addEventListener('click', (evt) => {{
        if (!evt.target.closest('.chart-container')) {{
          document.querySelectorAll('.chart-tooltip').forEach((t) => {{ t.style.display = 'none'; }});
        }}
      }});

      // Populate Year Dropdown
      const yearSelect = document.getElementById('yearFilter');
      const years = [...new Set(chartData.map(d => d.year))].sort((a,b) => b-a);
      years.forEach(y => {{
        const opt = document.createElement('option');
        opt.value = y;
        opt.textContent = y;
        yearSelect.appendChild(opt);
      }});
      
      // Filtering Logic
      const tbody = document.querySelector('#dataTable tbody');
      
      function renderTable() {{
        const yFilter = yearSelect.value;
        const sFilter = document.getElementById('seasonFilter').value;
        const iFilter = document.getElementById('invalidFilter').value;
        
        let filtered = chartData;
        
        if (yFilter !== 'all') {{
          filtered = filtered.filter(d => d.year.toString() === yFilter);
        }}
        
        if (sFilter !== 'all') {{
          filtered = filtered.filter(d => d.season === sFilter);
        }}
        
        if (iFilter === 'clean') {{
          filtered = filtered.filter(d => d.invalid_pct <= 10.0);
        }} else if (iFilter === 'warn') {{
          filtered = filtered.filter(d => d.invalid_pct > 10.0);
        }}
        
        tbody.innerHTML = '';
        
        filtered.forEach(row => {{
          const tr = document.createElement('tr');
          
          let extDisplay = row.extent_pct !== null ? row.extent_pct.toFixed(2) + '%' : 'N/A';
          let invDisplay = row.invalid_pct.toFixed(2) + '%';
          
          let seasonBadge = '';
          if (row.season === 'Wet') {{
            seasonBadge = '<span class="season-badge season-wet">Wet</span>';
          }} else if (row.season === 'Dry') {{
            seasonBadge = '<span class="season-badge season-dry">Dry</span>';
          }} else {{
            seasonBadge = '<span class="season-badge" style="background:#e2e8f0; color:#475569;">Unassigned</span>';
          }}
          
          let hyDisplay = row.hy_year !== null ? 'HY ' + row.hy_year : '-';
          
          tr.innerHTML = `
            <td><strong>${{row.display_date}}</strong></td>
            <td>${{seasonBadge}}</td>
            <td>${{hyDisplay}}</td>
            <td>${{extDisplay}}</td>
            <td>${{invDisplay}}</td>
          `;
          tbody.appendChild(tr);
        }});
        
        if (filtered.length === 0) {{
          tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 20px; color:#64748b;">No records match the current filters.</td></tr>';
        }}
      }}
      
      // Bind Events
      document.getElementById('yearFilter').addEventListener('change', renderTable);
      document.getElementById('seasonFilter').addEventListener('change', renderTable);
      document.getElementById('invalidFilter').addEventListener('change', renderTable);
      
      // Initial Render
      renderTable();
    }});
  </script>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_template)
        
    return output_path
```

- [ ] **Step 2: Run the existing report test**

Run: `pytest tests/test_report.py -v`
Expected: PASS (same assertions as before: `"Test Report"`, `"HY 2018"`, `"HY 2019"`, `"HY 2020"`, `"Wet Peak"`, `"Dry End"`, `"svg"` all present in output).

- [ ] **Step 3: Run the new metrics test file again (must still pass, unaffected by this task)**

Run: `pytest tests/test_report_metrics.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add hydroseason/report.py
git commit -m "refactor: report.py becomes a thin orchestrator over _report_metrics/_report_svg"
```

---

## T9 — Report split full verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm `hydroseason/__init__.py` still exposes `generate_html_report` unchanged**

Run: `python -c "from hydroseason import generate_html_report; import inspect; print(inspect.signature(generate_html_report))"`
Expected: `(extent: pandas.core.frame.DataFrame, hydro_years: pandas.core.frame.DataFrame, output_path: str | pathlib.Path, title: str = 'HydroSeason Seasonal Analysis') -> pathlib.Path`

- [ ] **Step 2: Byte-for-byte output check against the T0 baseline**

This confirms the split produced zero output drift versus the pre-split `report.py` captured in T0. Run:

```bash
python -c "
import pandas as pd, numpy as np
from hydroseason import detect_hydrological_years, generate_html_report

index = pd.date_range('2018-01-01', periods=36, freq='MS')
month = index.month
wet = 40.0 * np.cos(2 * np.pi * (month - 2) / 12) + 50.0
extent = pd.DataFrame({'extent_pct': wet, 'invalid_pct': 0.0}, index=index)
hy_df = detect_hydrological_years(extent)
generate_html_report(extent, hy_df, 'scratch_report_after.html', title='Verify')
print('after written')
"
```
Then diff:

Run: `diff scratch_report_baseline.html scratch_report_after.html`
Expected: no output (files identical). Any diff means the split changed behavior — stop and investigate before proceeding; do not paper over a mismatch by updating the baseline.

- [ ] **Step 3: Clean up the scratch files**

Run: `rm -f scratch_report_baseline.html scratch_report_after.html` (or `Remove-Item scratch_report_baseline.html,scratch_report_after.html -Force -ErrorAction SilentlyContinue` on PowerShell)

- [ ] **Step 4: Full test suite — final gate**

Run: `pytest -q`
Expected: zero failures, same total test count as the T5 checkpoint plus the 4 new `test_report_metrics.py` tests.

- [ ] **Step 5: Confirm no stray references to the old private SVG function names remain**

Run: `grep -rn "_generate_svg_chart\|_generate_seasonal_context_svg" hydroseason/ tests/ scripts/`
Expected: no matches (both were renamed without the leading underscore in `_report_svg.py`, and nothing outside `report.py` referenced them before this split since they were private).

No commit — this task is a checkpoint, not a change. If everything above is green, the refactor is complete.
