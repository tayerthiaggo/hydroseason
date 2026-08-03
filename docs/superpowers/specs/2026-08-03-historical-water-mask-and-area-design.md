# Historical Maximum-Water Mask and Absolute Area Design

**Status:** Approved in conversation on 2026-08-03.

## Purpose

Change the default HydroSeason workflow so a user-supplied AOI remains the
acquisition boundary, while the scientific analysis footprint is the exact
historical maximum-water mask from DEA Water Observations Multi-Year
Statistics. Use that one fixed mask for every monthly observation, calculate
absolute observed water extent in square kilometres during extraction, and
carry the area values through the user-facing CSV results.

This work changes CSV and extraction semantics only. HTML reports remain
unchanged until a later design.

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
- Absolute water extent is calculated from water pixels, not all valid pixels:
  `water_extent_km2 = n_water * pixel_area_m2 / 1_000_000`.
- Only water area is added. No `valid_observed_area_km2` field is added because
  existing invalid-percentage and quality columns already describe support.
- Regime classification, hydrological-year detection, phases, wet events, and
  low spells remain percentage-based. The km2 values are parallel absolute
  descriptions of the same selected dates and intervals.
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

The current CSVs also report only percentage water extent. This prevents users
from seeing whether a percentage represents a small wetland or hundreds of
square kilometres of inundation.

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
- fixed pixel count and area in km2;
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
water_extent_km2 = n_water * pixel_area_m2 / 1_000_000
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
  -> calculate monthly counts, percentages, quality, and water_extent_km2
  -> classify regime and choose the analysis route
  -> detect HY boundaries, peak, mid-dry, trough, phases, events, and spells
  -> write the four user-facing CSVs
```

The historical mask is known before monthly acquisition. The workflow does
not load and union every DEA Calendar Year summary and does not need a second
network pass to discover the analysis footprint.

## Grid and Area Contract

The default grid remains EPSG:3577 at 30 m. Pixel area is derived from the
absolute determinant of the affine transform rather than hard-coded as 900
square metres, so rotated metric grids and supported non-default metric
resolutions remain mathematically correct.

Area calculation requires a projected metric CRS. A geographic or non-metric
analysis grid fails with a clear validation error instead of emitting an
incorrect km2 value.

`water_extent_km2` is observed classified water area. It is not expanded to
estimate water hidden by invalid pixels. `invalid_pct`, `quality_state`, and
confidence remain the evidence needed to interpret incomplete observation.

## CSV Schema

The default bundle remains four CSVs. Existing fields retain their meanings.

### Monthly CSV

Add:

- `water_extent_km2`: observed monthly water pixels multiplied by pixel area;
- `baseline_water_extent_km2`: median usable monthly water area used as the
  absolute companion to `baseline_extent_pct`.

### Hydro-years CSV

Add:

- `peak_water_extent_km2` from the selected `peak_date`;
- `mid_dry_water_extent_km2` from the selected `mid_dry_date`;
- `trough_water_extent_km2` from the selected `trough_date`;
- `drawdown_km2 = peak_water_extent_km2 - trough_water_extent_km2`.

The selected dates do not change. A quality-flagged selected date retains its
observed area and its existing confidence fields.

### Wet-event CSV

Add:

- `baseline_water_extent_km2`, the median usable monthly water area;
- `peak_water_extent_km2`, from the percentage-selected `peak_date`;
- `mean_water_extent_km2`, the mean observed water area over the event window;
- `magnitude_km2_months`, the area-time equivalent of
  `magnitude_pp_months`.

Event membership and the exit threshold remain percentage-based. For month
`m`, the absolute exit threshold is:

```text
exit_threshold_water_km2[m]
  = exit_threshold_pct / 100
    * n_valid[m]
    * pixel_area_m2 / 1_000_000
```

The event magnitude is:

```text
magnitude_km2_months
  = sum(max(water_extent_km2[m] - exit_threshold_water_km2[m], 0))
```

This preserves the existing event threshold while expressing integrated
excess in absolute observed area-time.

### Low-spells CSV

Add:

- `baseline_water_extent_km2`;
- `min_water_extent_km2`, taken from the same month that supplies
  `min_extent_pct` within the spell. Percentage ties resolve to the first
  matching month, consistent with pandas' current `idxmin` behavior.

### HTML

No HTML columns, plots, KPIs, or copy change in this work.

## API and Compatibility

The extraction path adds `water_extent_km2` to the monthly count frame and
preserves all existing columns. Core analysis continues to consume
`extent_pct` and `invalid_pct`; it carries the area column as aligned context
for exports.

Lower-level percentage-only analysis remains supported. The default
extraction/report workflow is the supported path for complete absolute-area
results and always supplies `water_extent_km2`. No synthetic area is inferred
from percentage alone.

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

The manifest records historical-mask pixel count and area independently of
the full user-AOI count. Annual/monthly extent sidecars are valid only when
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
- Prove affine pixel-area calculation and the 30 m result of 0.0009 km2 per
  water pixel.
- Prove metric-CRS validation and mask-grid mismatch errors.
- Prove cache identity changes with mask digest or DEA source lineage.
- Prove incompatible source lineage or insufficient temporal coverage fails
  closed before monthly acquisition.

### Analysis and export tests

- Prove existing regime and HY/event selection is unchanged when the aligned
  area column is added.
- Prove monthly and baseline km2 fields.
- Prove HY peak, mid-dry, trough, and drawdown km2 fields use the selected
  monthly dates.
- Prove event peak, mean, baseline, and integrated `magnitude_km2_months`.
- Prove low-spell minimum area comes from the percentage-minimum month.
- Prove populated and empty CSVs have the stable approved headers.
- Keep the Fitzroy and Gilbert manual-review regression tests green.

### Integration tests

- Compare an unmasked synthetic/full-AOI run with a historical-mask run and
  prove `n_water` and `water_extent_km2` are identical while `invalid_pct`
  changes only because the denominator intentionally changes.
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
- exact `n_water` and `water_extent_km2` equality against the full-AOI run.

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
0` rule, fixed-mask comparability, area formula, and fail-closed coverage
contract.

Re-extract and rebuild the case-study CSVs before treating them as final. Remove
stale artifacts using the existing four-CSV bundle policy. HTML remains outside
this work.

## Out of Scope

- Calendar-year mask unions or user-selectable mask-source modes.
- Confidence or frequency thresholds applied to DEA Multi-Year Statistics.
- Buffered scientific masks.
- Estimated water area under invalid pixels.
- `valid_observed_area_km2` output.
- HTML report changes.
- Full-catchment performance benchmarks.
