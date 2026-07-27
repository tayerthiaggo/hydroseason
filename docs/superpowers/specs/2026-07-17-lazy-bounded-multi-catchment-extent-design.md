# Lazy, bounded, signal-safe multi-catchment extent

**Date:** 2026-07-17
**Status:** Design approved, pending spec review
**Scope:** The extent *feeder* (`load_wofs_from_stac`, `monthly_water_extent`) and the
multi-catchment report runner. No changes to detection, pattern classification, or the
(semi-)Markov trough adapter internals.

## Problem

Running the multi-catchment report crashes or hangs on large basins. Observed cube for
Gilbert River: `{time: 132, y: 12280, x: 10417}` int8 (~128 MB per timestep, ~16.8 GB
stacked). Two compounding causes:

1. **Eager, unbounded reduction.** `monthly_water_extent` issues a single `dask.compute`
   over the whole spatial reduction across all 132 months at once. The scheduler can hold
   a large working set of native-30 m chunks in flight; peak memory tracks the whole
   cube's working set, not one month. On ~16 GB PCs this OOMs.
2. **Native-resolution bbox raster.** `odc.stac.stac_load` defaults to native 30 m over
   the AOI *bounding box* — mostly outside-AOI pixels that are still allocated before the
   clip.

The bottleneck is **bytes moved + graph breadth**, not arithmetic. The reduction is int8
class-counting (`== 1`, `== 0`, `!= -2`) — memory-bandwidth-bound with trivial FLOPs.

### CUDA — explicitly rejected

GPU offload does not help this workload:
- Data streams from the DEA S3 bucket over the network and is GDAL-decoded on CPU; it is
  not resident on the GPU.
- 16.8 GB exceeds consumer VRAM, so it would stream anyway.
- PCIe host→device transfer costs more than the trivial count it would accelerate.

The win is **fewer bytes** (coarsen) plus **bounded streaming**, not faster arithmetic.

## Guiding principle: signal has veto power over memory

Coarsening resolution is the primary lever for fewer bytes, and it is acceptable for this
repo because every downstream consumer is **shape/pattern based and self-normalised per
catchment**, not absolute magnitude:

- **Pattern detection** works on the seasonal-cycle *shape* (peak/trough placement in the
  year) — invariant to a constant scale factor.
- **Hydro-year boundary** is the *timing* of the dry trough — coarsening shifts absolute
  extent % but not *when* the minimum falls.
- **Cross-catchment comparison** is regime-shape, never raw magnitude (Paroo terminal
  lakes vs Daly karst baseflow are already incomparable on absolute extent %).

But coarsening is **not free-choice**. It is bounded by a **signal-preservation
criterion**, because the detected signal must still support peak/trough mapping and the
(semi-)Markov wet/dry state sequence:

1. **Amplitude vs noise floor.** `_boundary.py` uses a resolution-dependent noise floor
   `100 / n_valid`. Coarsening shrinks `n_valid`, *raising* the floor. If a catchment's
   true peak–trough amplitude sinks under the floor, the detector flips to
   "low-variability" and the pattern is lost. Chosen resolution must keep the projected
   noise floor under a fraction (default ⅓) of observed amplitude.
2. **Wet/dry sequence integrity (Markov).** The trough adapter operates on the monthly
   wet/dry state sequence. Coarsening preserves *ordering* — safe — **unless** water is
   entirely thin sub-pixel channels (e.g. Kimberley braids), where coarsening can drop a
   wet month below threshold and break the state run.

**Rule:** memory can *request* coarsening; signal can *veto* it. The gate picks the
coarsest resolution that still clears the signal bound — never coarser. If native 30 m
still can't fit memory *and* signal forbids coarsening, the catchment is **flagged and
reported honestly**, not emitted with a broken pattern.

Mixed per-catchment resolution is accepted **as long as it is stamped** on every chart and
comparison is framed as regime-shape.

## Design

### 1. Resolution knob at load time (`load_wofs_from_stac`)

- Add `resolution: float | None = None`, passed to
  `odc.stac.stac_load(..., resolution=resolution, resampling="mode")`.
- `None` → native 30 m, behaviour unchanged (default).
- Coarsening happens **inside odc.stac's lazy load** (GDAL overview/averaged reads), so
  fewer bytes ever enter the graph — not a post-load block-reduce.
- `resampling="mode"` (majority) preserves water/dry class better than averaging for a
  categorical mask.

### 2. Memory estimate + auto-coarsen gate (pre-load, pure arithmetic)

New helper `plan_resolution(bounds_wgs84, target_crs, *, memory_budget_gb,
observed_amplitude_pp=None) -> (resolution_m, projected_peak_gb, projected_noise_floor_pp,
reason)`:

- Pixel count = AOI-bbox area / res². Peak bytes ≈
  `n_pixels × time_chunk × bytes_per_scratch` (int8 mask + reduction accumulators).
- Walk candidate resolutions (e.g. 30, 60, 100, 150, 300 m). Pick the **finest that fits
  the memory budget**, then **veto** any choice that violates the signal bound (§ guiding
  principle). If the finest-that-fits is coarser than signal allows → return a
  `reason` that flags the catchment (runner excludes it from pattern claims).
- **Amplitude chicken-and-egg:** amplitude is unknown before loading. Resolve with a
  **cheap coarse probe** (one ~300 m pass, ≈100× cheaper) to get a provisional amplitude,
  then set the signal-bound floor from it.

Runner behaviour: **estimate → auto-coarsen → print exact cost, no interactive prompt**
(unattended/checkpointed batch stays non-interactive).
- `--resolution N` overrides the gate.
- `--allow-large` bypasses the memory veto for a defensible native-res run.

### 3. Per-month streaming in `monthly_water_extent`

Replace the single all-months `dask.compute` with a **bounded loop** computing the four
scalar reductions one month (or small `time_block`, default 1) at a time. Each iteration's
spatial chunks release before the next loads. Peak memory ≈ one month's chunks, independent
of `time` length. Same numbers, bounded footprint, interruptible (per-month progress).
Optional `time_block` param trades scheduler overhead for locality.

### 4. Resolution stamp + thin-channel guard (runtime)

- **Stamp:** chosen `resolution_m`, `n_valid`, and projected noise floor recorded in each
  catchment result dict → shown on every chart; comparison framed as regime-shape.
- **Thin-channel guard:** during the coarse probe (§2), compare water fraction at chosen
  resolution vs one step coarser. If water fraction collapses disproportionately (channels
  sub-pixel), **warn + refuse to coarsen past that point** — the runtime enforcement of the
  Markov-sequence-integrity veto. Guard emits a **labelled caveat into the report**, not
  just a log line.

### 5. Tests (all TDD, RED first)

- **Perf regression** (pytest): synthetic large-ish lazy dask cube; assert
  `monthly_water_extent` peak (chunk-load counter / `dask.diagnostics`, or a fake scheduler
  counting concurrent chunks) stays bounded and **independent of `time` length** — guards
  § 3 against regressing to all-at-once.
- **Signal preservation** (pytest): synthetic cube with known peak/trough plus a
  thin-channel-only case; assert `plan_resolution` vetoes coarsening that would sink
  amplitude under the noise floor, and the guard fires on the braided case.
- **Resolution passthrough**: assert `resolution` reaches `stac_load` with
  `resampling="mode"`; `None` leaves behaviour unchanged.

## Non-goals (YAGNI)

- No CUDA / GPU offload (rejected above).
- No Zarr caching layer, no distributed cluster.
- No change to detection, pattern classification, or (semi-)Markov internals — only the
  extent *feeder* and the runner.

## Affected files

- `hydroseason/io.py` — `load_wofs_from_stac` gains `resolution`; new `plan_resolution`.
- `hydroseason/hydro_year.py` — `monthly_water_extent` per-month streaming loop.
- `scripts/run_multi_catchment_report.py` — gate wiring, `--resolution`/`--allow-large`,
  stamp into result dict.
- `scripts/build_multi_catchment_html.py` — render resolution stamp + thin-channel caveat.
- `tests/` — perf, signal-preservation, passthrough tests.
