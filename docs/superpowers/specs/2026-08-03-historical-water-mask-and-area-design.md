# Historical Maximum-Water Mask Design

**Status:** Approved in conversation on 2026-08-03. Amended same day to drop
the absolute-area (km²) scope after Task 1 implementation showed that making
pixel area CRS-strict broke fixtures project-wide for no benefit the project
currently needs; the user decided absolute area is out of scope entirely.

## Purpose

Change the default HydroSeason workflow so a user-supplied AOI remains the
acquisition boundary, while the scientific analysis footprint is the exact
historical maximum-water mask from DEA Water Observations Multi-Year
Statistics. Use that one fixed mask for every monthly observation.

This work changes extraction semantics only (the denominator used for
`n_aoi`, `invalid_pct`, and percentage-based classification). It does not add
any new CSV columns and does not touch HTML reports.

## Decisions

- The historical maximum-water source is DEA WO Multi-Year Statistics,
  `ga_ls_wo_fq_myear_3`.
- The scientific mask is `count_wet > 0`, clipped to the user AOI.
- The exact scientific mask is a grid-aligned raster. It is not closed,
  buffered, coarsened, or converted through polygons.
- The same fixed mask is used for every month in the requested analysis
  period, regardless of the analysis start and end dates.
- The current source coverage and version are pinned in provenance. At design
  time the product covers 1987-2025 and is unfiltered.
- A separate conservative coarse/dilated derivative may prune remote storage
  windows. That derivative is performance-only and never becomes a metric
  denominator.
- Pixels outside the exact mask are canonical outside pixels (`-2`). Inside
  the mask, water is `1`, dry is `0`, and invalid is `-1`.
- Regime classification, hydrological-year detection, phases, wet events, and
  low spells remain percentage-based, unchanged in formula. Only the pixel
  population behind `n_aoi`/`n_valid`/`n_invalid` changes.
- No absolute area (km²) field is added anywhere. This was explored and
  reverted: making pixel area available required a CRS-strict primitive that
  raised on any fixture lacking real CRS metadata, which broke 32 unrelated
  tests across 5 files for a value the project does not currently need (WOfS
  pixel resolution is already known/expected; the project is not
  reprojecting or handling mixed grids that would make computed area
  necessary). Do not reintroduce `water_extent_km2`, `pixel_area_m2`, or any
  derived area/km² field without a fresh design decision.
- Benchmarks use `data/fitzroy_kimberley_aoi.geojson` and
  `data/Gilbert_river_buffer.geojson`, never the full catchments.

## Current Problem

Current monthly `invalid_pct` is derived from every pixel inside the supplied
AOI. For a catchment-scale AOI, invalid observations over land that has never
been water can therefore reduce quality or confidence even though those pixels
cannot affect the water signal.

HydroSeason already loads DEA Multi-Year Statistics and creates a native
`count_wet > 0` mask inside `WetPlanningFootprint`. That native mask is
currently documented as a planning artifact, while the scientific denominator
remains the full AOI. The default extraction command also leaves DEA pruning
off. The new design promotes the exact native raster to an explicit scientific
artifact and derives the planning windows from it, so one statistics load
serves both correctness and performance without conflating their masks.

## Domain Model

### User AOI

The polygon supplied by the user. It defines the outer acquisition boundary
and limits the DEA Statistics query. It is retained in provenance but does not
become the default water-quality denominator.

### Historical maximum-water mask

One immutable 2D boolean raster on the analysis grid:

```text
historical_max_water_mask = (DEA Multi-Year count_wet > 0) AND user_AOI
```

The mask describes the long-term potential-water domain. It is independent of
the requested monthly analysis dates, so two runs over different periods use
the same spatial reference whenever their AOI, grid, and DEA source version
match.

The implementation introduces a dedicated `HistoricalWaterMask` value object
rather than changing `WetPlanningFootprint` from performance-only to
scientific by implication. The value object carries:

- the exact boolean `xarray.DataArray` mask;
- CRS, affine transform, shape, and resolution;
- fixed pixel count;
- source product, version, item IDs, lineage, and coverage period;
- AOI digest and exact mask digest.

### Planning mask

A conservative max-pooled and safety-dilated derivative of the exact mask.
It selects aligned source/cache windows. It may contain pixels outside the
scientific mask, but those pixels are converted to `-2` before monthly counts
are calculated. Its digest and parameters remain separate from the exact mask
digest.

### Monthly water extent

For every month, after applying the exact mask:

```text
n_aoi       = count(mask != -2)
n_water     = count(mask == 1)
n_valid     = count(mask == 0 or mask == 1)
n_invalid   = count(mask == -1)
extent_pct  = 100 * n_water / n_valid
invalid_pct = 100 * n_invalid / n_aoi
```

`n_aoi` must equal the historical-mask pixel count in every month, including a
month with no source observation. Such a month is invalid inside the mask, not
outside it.

## Data Flow

```text
User AOI + monthly start/end dates
  -> load DEA WO Multi-Year count_wet/count_clear at the analysis grid
  -> build exact HistoricalWaterMask from count_wet > 0
  -> derive conservative storage-window planning mask
  -> retrieve and classify monthly WOfS data only in planned windows
  -> apply exact mask: outside = -2
  -> calculate monthly counts, percentages, and quality
  -> classify regime and choose the analysis route
  -> detect HY boundaries, peak, mid-dry, trough, phases, events, and spells
  -> write the four user-facing CSVs
```

The historical mask is known before monthly acquisition. The workflow does
not load and union every DEA Calendar Year summary and does not need a second
network pass to discover the analysis footprint.

## Grid Contract

The default grid remains EPSG:3577 at 30 m. This design does not require
pixel-area or metric-CRS validation; it only requires the historical mask and
every monthly raster to share the same grid (CRS, transform, shape,
resolution) so cell-for-cell masking is valid.

## CSV Schema

The default bundle remains four CSVs (monthly, hydro-years, wet-event,
low-spells). No new columns are added by this design. Existing fields retain
their meanings; only the pixel population behind `n_aoi`, `n_valid`,
`n_invalid`, and the percentage fields derived from them changes, because the
denominator is now the historical mask instead of the full user AOI.

### HTML

No HTML columns, plots, KPIs, or copy change in this work.

## API and Compatibility

The extraction path preserves all existing CSV columns and formulas. Core
analysis continues to consume `extent_pct` and `invalid_pct` exactly as
before; only their underlying pixel counts change.

Lower-level percentage-only analysis remains supported and is the only
analysis mode — there is no absolute-area mode to fall back to or opt into.

The legacy polygon `wet_aoi` and planning-only APIs remain available for
compatibility, but documentation and the default workflow use
`HistoricalWaterMask` plus its derived planning footprint.

## Cache and Provenance

Persist the exact mask as a chunked, grid-aligned 2D boolean sidecar. Do not
vectorize and rasterize it, because that can alter edge pixels and is needless
for a raster analysis.

The cache identity includes:

- user AOI digest;
- exact historical-mask digest;
- DEA source product, version, item IDs, and coverage period;
- CRS, transform, shape, and resolution;
- planning factor and safety-cell parameters;
- monthly analysis start and end dates.

The manifest records the historical-mask pixel count independently of the
full user-AOI count. Annual/monthly extent sidecars are valid only when
their historical-mask digest matches the root manifest. A mismatch invalidates
derived counts and rebuilds them from verified cached source masks.

Because the scientific mask is available before acquisition, annual masks are
written with exact outside pixels already set to `-2`; no post-acquisition
scientific-mask discovery pass is required.

## Validation and Failure Behaviour

- If DEA Multi-Year Statistics is unavailable and no verified cached mask
  exists, stop. Do not fall back to the full AOI because that changes the
  scientific denominator.
- Require the source coverage to include the requested analysis end date.
  This prevents a new flood outside an outdated mask from being silently
  discarded.
- If `count_wet > 0` is empty within the user AOI, stop with a clear
  `no historically observed water` error.
- Verify that the Multi-Year Statistics source lineage is compatible with the
  monthly WOfS collection and that its coverage includes the analysis end
  date. A pruned production run cannot inspect pixels it intentionally does
  not read, so it must not claim a per-run outside-mask scan.
- Reject mask/grid CRS, shape, transform, or resolution mismatches.
- Enforce `n_water <= n_valid`, `n_valid + n_invalid == n_aoi`, and constant
  `n_aoi == historical_mask_pixel_count`.
- Record that the Multi-Year Statistics product is unfiltered. Do not hide or
  denoise isolated `count_wet > 0` pixels in this design; doing so would no
  longer be the historical maximum extent selected by the user.

## Testing Strategy

### Unit tests

- Build an exact `count_wet > 0` mask and prove zero-wet pixels are excluded.
- Prove exact mask pixels are not altered by planning-mask dilation.
- Prove mask application preserves `1`, `0`, and `-1` inside and assigns `-2`
  outside.
- Prove invalid pixels outside the historical mask do not change
  `invalid_pct`.
- Prove `n_aoi` is constant through normal, all-invalid, and missing-source
  months.
- Prove mask-grid CRS/shape/transform/resolution mismatch errors.
- Prove cache identity changes with mask digest or DEA source lineage.
- Prove incompatible source lineage or insufficient temporal coverage fails
  closed before monthly acquisition.

### Analysis and export tests

- Prove existing regime and HY/event selection is unchanged in formula;
  only the pixel counts feeding them change.
- Prove populated and empty CSVs have the stable existing headers (no new
  columns).
- Keep the Fitzroy and Gilbert manual-review regression tests green.

### Integration tests

- Compare an unmasked synthetic/full-AOI run with a historical-mask run and
  prove `n_water` is identical while `invalid_pct` changes only because the
  denominator intentionally changes.
- In the bounded full-AOI benchmark fixtures, prove every primary monthly
  water pixel is contained in the Multi-Year mask. This is an explicit audit,
  not a production check that would negate I/O pruning.
- Prove online acquisition and offline cache replay produce identical CSV
  frames and mask digests.
- Rebuild the checked case-study CSVs from corrected pixel-level inputs before
  declaring their results final.

## Performance Benchmark

Extend `scripts/benchmark_wofs_cache.py`; retain its bounded 2015 calendar-year
window and 30 m EPSG:3577 grid. Use only:

- `data/fitzroy_kimberley_aoi.geojson`;
- `data/Gilbert_river_buffer.geojson`.

Do not benchmark full catchments.

Compare three modes:

1. current full-AOI extraction;
2. existing planning-only extraction;
3. Multi-Year scientific mask plus derived planning windows.

Measure cold and warm runs where meaningful and record:

- total seconds;
- DEA Statistics preparation seconds;
- STAC query and WOfS read seconds;
- selected active windows and loaded pixels;
- local reduction seconds;
- peak resident memory;
- cache bytes;
- exact `n_water` equality against the full-AOI run.

The benchmark publishes measured results even when the expected speedup is not
observed. Documentation may claim a speed improvement only from those results.
The expected outcome is that the scientific-mask workflow outperforms full AOI
for sparse-water AOIs and is close to or faster than planning-only extraction
while producing the corrected denominator.

## Documentation and Case Studies

Update the user guide and report-column reference to distinguish:

- user AOI: acquisition boundary;
- historical maximum-water mask: scientific denominator;
- planning mask: performance-only superset.

Document the Multi-Year source coverage, unfiltered nature, exact `count_wet >
0` rule, fixed-mask comparability, and fail-closed coverage contract.

Re-extract and rebuild the case-study CSVs before treating them as final. Remove
stale artifacts using the existing four-CSV bundle policy. HTML remains outside
this work.

## Out of Scope

- Calendar-year mask unions or user-selectable mask-source modes.
- Confidence or frequency thresholds applied to DEA Multi-Year Statistics.
- Buffered scientific masks.
- Absolute/observed water area in any unit (`water_extent_km2`,
  `pixel_area_m2`, or any derived area/km² field), and any CRS-strictness
  this would require. Explicitly reverted after Task 1 implementation; see
  Decisions.
- HTML report changes.
- Full-catchment performance benchmarks.
