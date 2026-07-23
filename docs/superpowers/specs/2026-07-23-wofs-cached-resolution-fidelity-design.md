# Cached WOfS Resolution Fidelity Design

**Date:** 2026-07-23
**Status:** Approved design, pending implementation plan
**Depends on:** `2026-07-23-wofs-zarr-processing-optimization-design.md`
**Scope:** Local comparison of 30, 60, 90, and 300 m canonical monthly WOfS masks and their hydrological-state outputs.

## Problem

Coarser WOfS analysis can reduce local storage, task count, and repeated-analysis time, but it may move hydrological-year boundaries, peak months, or dry-end months. Existing comparison scripts compare one native/coarse pair and do not enforce strict end-to-end hydrological-state equality across a resolution ladder.

The study must run from cached local WOfS Zarr data. It must not repeatedly call DEA STAC, and it must separate coarse-cache construction cost from later cached-analysis cost.

## Goals

1. Derive 60, 90, and 300 m canonical monthly caches locally from the completed 30 m cache.
2. Compare monthly signal and complete hydrological-year outputs against 30 m.
3. Require exact month matching rather than a tolerance window.
4. Produce per-resolution, per-catchment pass/fail verdicts with auditable row-level evidence.
5. Measure cache construction, cold local analysis, warm local analysis, task count, storage, and peak memory.

## Non-Goals

- No STAC calls during fidelity comparison.
- No direct comparison against raw-bitfield coarse STAC resampling.
- No automatic change to production resolution.
- No generic Zarr public input feature.
- No detector changes made to force coarse results to agree.

## Source Data

The only raster source is a completed 30 m canonical monthly-mask cache produced by the WOfS Zarr processing design. CSV outputs are derived artifacts and may be used to rerun detector-only checks.

The study date range is 2015-01-01 through 2025-12-31.

## Resolution Matrix

- Baseline: 30 m
- Candidates: 60 m, 90 m, 300 m
- Integer spatial factors relative to 30 m: 2, 3, 10

Non-integer factors are rejected.

### Screening AOIs

All six existing 50 km lower-reach windows:

- Gilbert River QLD
- Fitzroy River WA
- Moonie River QLD/NSW
- Lachlan River NSW
- Paroo River QLD/NSW
- Daly River NT

### Full-boundary validation AOIs

- Gilbert River QLD
- Fitzroy River WA
- Moonie River QLD/NSW

These provide contrasting AOI size, compactness, and hydrological regime. Generated Zarr caches and reports remain under ignored `output/` paths and are not committed.

## Canonical Spatial Coarsening

Coarsening operates on monthly canonical values, not raw WOfS bit fields. For every output block:

1. Count outside, invalid, dry, and water source cells.
2. If every source cell is outside, output outside (`-2`).
3. Ignore outside cells for class voting.
4. Among valid cells, water wins only when `n_water > n_dry`.
5. If dry exists and water does not strictly win, output dry (`0`); this makes water/dry ties dry, matching current monthly-majority semantics.
6. If the block intersects the AOI but contains no valid water or dry cell, output invalid (`-1`).

Edges are padded with outside (`-2`) to preserve the 30 m grid origin. The output transform uses the same origin and factor-scaled pixel size. Every derived mask must remain in the canonical domain `{-2, -1, 0, 1}`.

Each derived resolution is materialised once as its own local Zarr cache. Analysis timing is measured from these completed derived stores; otherwise every coarse analysis would pay the 30 m read/coarsening cost and would not measure reusable coarse-cache performance.

## Analysis Pipeline

For every AOI and resolution:

1. Open the completed resolution cache lazily.
2. Run `monthly_water_extent`.
3. Run `analyze_hydrological_state` independently, including seasonal-pattern classification and automatic dynamic configuration.
4. Retain complete annual rows plus unresolved/partial diagnostics.
5. Write extent and hydrological-year CSV artifacts.

Independent end-to-end analysis is intentional. Reusing the 30 m detector configuration at coarse resolutions would hide resolution-driven pattern/configuration changes that the real workflow would experience.

## Strict Fidelity Verdict

Rows are matched by `hy_year`. A candidate resolution passes an AOI only when all conditions hold:

- 30 m yields at least five complete hydrological years; otherwise the AOI verdict is `inconclusive`.
- Candidate and 30 m have exactly the same set of complete `hy_year` values.
- Seasonal-pattern classification is identical.
- For every complete shared year, these timestamps match exactly:
  - `hy_start`
  - `hy_end`
  - `peak_month`
  - `trough_month`
- `trough_month` is the dynamic workflow's end-dry/boundary month.

No `+/-1 month` tolerance is accepted. Any missing/extra complete year, pattern change, or timestamp difference fails that candidate for that AOI.

A 300 m failure is a valid study result, not a failed execution. The study completes and reports candidate verdicts even when one or all candidates are scientifically unsafe.

## Secondary Diagnostics

Verdicts are strict dates, but the report also records:

- usable-month counts;
- unresolved and partial HY counts/reasons;
- monthly `extent_pct` correlation with 30 m;
- mean and maximum absolute `extent_pct` difference;
- amplitude and noise change;
- `n_valid`, `invalid_pct`, and water-pixel retention;
- selected pattern and automatic detector configuration;
- first exact mismatch with native/coarse values.

These diagnostics explain failures; they never relax the strict verdict.

## Performance Measurements

For every resolution/AOI combination record:

- derived-cache construction time;
- derived-cache bytes on disk;
- cold local extent-plus-state analysis time;
- median of three warm local analysis runs;
- Dask graph/task count;
- estimated and measured loaded chunks;
- peak resident memory when available;
- environment and package versions;
- extent and HY output digests.

Expected pixel-count reductions are approximately 4x at 60 m, 9x at 90 m, and 100x at 300 m, subject to edge padding. Deterministic tests assert shape/pixel-count relationships. Real runtime is reported rather than inferred from pixel count.

## Artifacts

Under `output/resolution_fidelity/`:

- one extent CSV per AOI/resolution;
- one HY CSV per AOI/resolution;
- one comparison JSON per AOI;
- `summary.csv` containing one row per AOI/candidate resolution;
- `hy_mismatches.csv` containing row-level strict mismatches;
- one self-contained HTML report with signal plots, performance tables, and verdicts.

Every artifact records source-cache identity and analysis configuration.

## Error Handling

- Missing or incomplete 30 m coverage fails before derived-cache work begins.
- Offline execution never contacts STAC.
- Derived-cache provenance mismatch creates a new identity.
- Corrupt derived group is incomplete and can be rebuilt from local 30 m cache.
- Non-integer resolution factor fails validation.
- Fewer than five complete native HY rows yields `inconclusive`, not `pass`.
- Comparison continues across other AOIs after one AOI fails, but the failure is captured in summary artifacts.

## Testing Strategy

### Default deterministic tests

- Categorical reducer: water win, dry win, water/dry tie to dry, invalid-only, outside-only, and mixed outside/AOI blocks.
- Edge padding preserves origin and emits correct shape/transform at factors 2, 3, and 10.
- Derived values stay canonical.
- Derived cache identity includes source identity and factor.
- Analysis opens derived cache without STAC imports or calls.
- Strict matcher passes exact frames.
- Strict matcher fails changed `hy_start`, `hy_end`, `peak_month`, `trough_month`, pattern, missing year, and extra year independently.
- Native records below five complete years produce `inconclusive`.
- Summary and mismatch artifacts retain every candidate verdict.
- Pixel-count/task-count structural assertions show decreasing derived workloads.

### Opt-in cached-real suite

- Runs the six lower-reach screening AOIs.
- Runs the three full-boundary validation AOIs when their caches exist.
- Makes no network calls.
- Produces complete artifacts even when a candidate fails fidelity.
- Repeated analysis uses completed derived caches rather than rebuilding them.

## Acceptance Criteria

- All deterministic tests pass.
- Study runs entirely from local cache after 30 m acquisition.
- Each 60/90/300 candidate receives a strict verdict for every conclusive AOI.
- Exact mismatch evidence is present for every failed verdict.
- Cache construction and analysis timings are separated.
- No generated Zarr or report data is committed.

