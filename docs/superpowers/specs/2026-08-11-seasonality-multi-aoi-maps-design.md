# HydroSeason 0.1.1 Seasonality, Multi-AOI, and Map Design

**Status:** Approved approach; pending written-spec review

**Date:** 2026-08-11

**Release:** 0.1.1

> **Supersession (2026-08-13):** The 80% batch memory budget and ten-year
> circular-uniformity power guard in
> [`2026-08-13-hydroseason-0.1.1-release-readiness-design.md`](2026-08-13-hydroseason-0.1.1-release-readiness-design.md)
> supersede the 60% scheduling proposal in this document. Accepted 0.1.1 CLI
> additions (`doctor`, `--json`, and progress reporting) remain in scope per that
> release-readiness design.

## Context

HydroSeason currently calls a record seasonal only when its climatological
amplitude signal-to-noise ratio (SNR) is at least 2.0 and the circular
interquartile range (IQR) of annual peak months is no more than 1.5 months.
The 1.5-month value entered the implementation as an undocumented policy
threshold. It has no calibration record or direct literature basis. It also
does two jobs at once: classifying peak seasonality and authorising per-year
hydrological-year boundaries, even though those boundaries are defined by dry
troughs rather than peaks.

The public workflow accepts a multi-row GeoDataFrame, but the acquisition path
treats all rows as one AOI. Widely separated rows can therefore create a large
raster envelope spanning the gaps. The repository has an internal concurrent
multi-catchment script, but no stable public batch API.

Reports receive only temporal analysis products. AOI geometry is discarded
before report generation, so neither the HTML report nor a notebook call can
show the area being processed.

## Goals

1. Replace the unsupported peak-IQR gate with literature-grounded circular
   concentration and explicit sampling uncertainty.
2. Separate evidence for peak seasonality from evidence that dry boundaries
   are repeatable enough for per-year detection.
3. Add a public, DEA/STAC-only `run_hydroseason_many` workflow where every
   vector row is an independent AOI.
4. Schedule independent AOIs concurrently only when CPU and memory budgets make
   that safe.
5. Carry lightweight AOI geometry through workflow results into reports.
6. Show AOIs before expensive notebook acquisition and in generated HTML
   reports using lightweight interactive online basemap tiles.
7. Document the science, changed routing, batch semantics, map connectivity,
   and release compatibility clearly.

## Non-goals

- Do not support per-row CSV, NetCDF, Zarr, Dataset, or DataArray mappings in
  `run_hydroseason_many` for 0.1.1.
- Do not overload `run_hydroseason` with a return type that changes according
  to AOI row count.
- Do not embed raster basemap tiles in reports.
- Do not silently coarsen different AOIs to different scientific resolutions
  merely to increase concurrency.
- Do not publish, tag, or upload the release as part of implementation.
- Do not remove circular IQR from diagnostics; remove only its decision power.

## Literature basis

The direct remote-sensing analogue is Mao et al. (2019), who characterize the
timing of annual maximum flood extent using the circular mean direction and a
seasonality index equal to the mean resultant length. The index ranges from 0
for dispersed timing to 1 for identical timing.

Flood-seasonality studies likewise use the mean resultant length `R` as the
effect size for temporal concentration. Applied classifications commonly
describe `R > 0.7` as strong concentration. Hall and Bloeschl (2018) combine
circular concentration with a uniformity assessment and emphasize record-length
uncertainty. Cunderlik, Ouarda, and Bobee (2004) show that short annual-maximum
records can both create false seasonality and hide real seasonality; they
recommend extreme care below 30 observations and quantify sampling uncertainty
through resampling.

Primary references:

- Mao et al. (2019), *Flood Inundation Generation Mechanisms and Their Changes
  in 1953-2004 in Global Major River Basins*,
  <https://doi.org/10.1029/2019JD031381>.
- Hall and Bloeschl (2018), *Spatial patterns and characteristics of flood
  seasonality in Europe*, <https://doi.org/10.5194/hess-22-3883-2018>.
- Cunderlik, Ouarda, and Bobee (2004), *On the objective identification of
  flood seasons*, <https://doi.org/10.1029/2003WR002295>.
- Matti et al. (2017), *Flood seasonality across Scandinavia--Evidence of a
  shifting hydrograph?*, <https://doi.org/10.1002/hyp.11365>.
- Villarini (2016), *On the seasonality of flooding across the continental
  United States*, <https://doi.org/10.1016/j.advwatres.2015.11.009>.

Documentation must describe these as close methodological precedents, not as
validation that satellite surface-water extent is interchangeable with gauge
discharge.

## Scientific design

### Circular concentration

For each usable year, extract one peak month and one trough month from the
quality-screened monthly surface-water extent series. Convert month `m` to
angle

```text
theta = 2*pi*(m - 1)/12
```

and calculate mean resultant length

```text
R = abs(mean(exp(1j*theta)))
```

`R=1` means all annual timings coincide; values near zero mean timing is spread
around the year or symmetrically multimodal. Calculate peak and trough `R`
independently. Retain circular peak and trough IQR as descriptive diagnostics.

### Sampling uncertainty

Use the existing `analyze_catchment(..., n_bootstrap=..., random_state=...)`
controls for deterministic non-parametric resampling of annual timing
observations. Each bootstrap draw resamples usable years with replacement and
recomputes `R`. Publish percentile 95% confidence bounds.

The assessment records:

- `peak_timing_concentration`;
- `peak_timing_concentration_ci_low` and `_ci_high`;
- `peak_timing_uniformity_p`;
- `trough_timing_concentration`;
- `trough_timing_concentration_ci_low` and `_ci_high`;
- `trough_timing_uniformity_p`;
- `n_timing_years`;
- existing `peak_phase_iqr_months`, plus a parallel trough IQR diagnostic.

Calculate circular-uniformity p-values with a deterministic Monte Carlo Kuiper
test against the discrete 12-month uniform null, using the same
`n_bootstrap`/`random_state` controls. Kuiper's statistic is rotation-invariant
and can detect non-uniform timing that is not concentrated around one mean.
The uniformity test prevents a low `R` caused by two preferred seasons from
being mislabeled as evidence that no seasonality exists.

Fewer than 30 usable annual timings adds a sampling-uncertainty caveat. It does
not automatically change the regime or prepend a blanket `provisional` label.
Fewer than the existing minimum five usable years remains
`insufficient_record`.

### Regime classification

Publish these thresholds from the classifier so reports and documentation do
not duplicate them:

```text
seasonal_min_snr = 2.0
strong_timing_concentration = 0.7
weak_timing_concentration = 0.3
aseasonal_max_snr = 0.7
circular_uniformity_alpha = 0.1
timing_record_caution_years = 30
```

Classification rules:

1. `seasonal` when amplitude SNR is at least 2.0 and the lower 95% bootstrap
   bound for peak `R` is at least 0.7.
2. `aseasonal` when amplitude SNR is below 0.7 or circular uniformity of annual
   peak timing cannot be rejected at `alpha=0.1`.
3. `marginal` for the uncertainty zone between those gates.
4. `insufficient_record` when fewer than five usable years remain.

This preserves the deliberately wide marginal zone while replacing an
uncalibrated month cutoff with an established circular effect size and an
explicit uncertainty requirement. `R < 0.3` remains a reported weak-effect
label, not a stand-alone aseasonal decision: a symmetric bimodal distribution
can have low `R` while still being significantly non-uniform.

### Boundary routing

Regime and route become related but not identical decisions:

- A seasonal record uses `per_year_detection` only when the lower 95%
  bootstrap bound for trough `R` is at least 0.7.
- A seasonal record with concentrated peaks but insufficiently concentrated
  troughs uses `fixed_climatological_window`; report copy states that the
  seasonal cycle exists but detected starts are not repeatable enough.
- A marginal record uses `fixed_climatological_window` only when both peak and
  trough timing reject circular uniformity and have `R >= 0.3`, supporting one
  interpretable average window. Otherwise it uses `event_characterisation`
  with a caveat that timing is complex or too diffuse for one fixed window.
- An aseasonal record continues to use `event_characterisation`.
- An insufficient record defines no hydrological year.

`WaterRegimeAssessment.supports_per_year_boundaries` must read the trough
evidence, not simply test `regime == "seasonal"`.

### Checked-data sensitivity

The committed 30 m case-study inputs each provide 21 annual peaks. Measured
peak results are:

| Catchment | Peak IQR (months) | Peak R | Bootstrap 95% CI |
|---|---:|---:|---:|
| Daly River (NT) | 2.0 | 0.864 | 0.812-0.926 |
| Fitzroy River (WA) | 1.0 | 0.907 | 0.858-0.955 |
| Gilbert River (QLD) | 1.0 | 0.934 | 0.907-0.967 |
| Lachlan River (NSW) | 4.0 | 0.324 | 0.121-0.614 |
| Moonie River (QLD/NSW) | 3.0 | 0.532 | 0.315-0.757 |

Daly therefore clears the new peak-seasonality gate despite failing the old
1.5-month IQR rule. Its final route must be determined from its trough
concentration. Checked case-study outputs and regression expectations must be
regenerated deliberately and reviewed, not patched to preserve old labels.

## AOI spatial context

Add an immutable `AOIContext` value containing:

- compact EPSG:4326 GeoJSON text;
- `[min_lon, min_lat, max_lon, max_lat]` bounds;
- display name;
- feature count.

Coordinates are rounded to six decimal places and nonessential source
properties are omitted to keep reports small. `HydroSeasonRunResult` gains
`aoi_context: AOIContext | None`.

`run_hydroseason` loads a supplied AOI once before acquisition, constructs the
context, previews it when requested, and passes the loaded GeoDataFrame onward
to water acquisition and optional rainfall. This avoids repeated file reads.
Precomputed water inputs may still supply an AOI solely for map/rainfall
context. Calls without an AOI remain valid and produce no map.

`generate_catchment_report` accepts optional AOI context. Direct report callers
can omit it without changing existing behavior.

## Map design

Use a vendored, pinned lightweight Leaflet runtime so boundaries and controls
still render when the basemap service is unavailable. Include Leaflet's
license in package assets. Do not embed tiles. At view time, request standard
OpenStreetMap tiles from
`https://tile.openstreetmap.org/{z}/{x}/{y}.png` and display
`© OpenStreetMap contributors` attribution.

The reusable map component:

- embeds compact boundary GeoJSON;
- fits bounds with a sensible maximum zoom;
- draws high-contrast boundary fill/outline;
- includes AOI name and row identifier in accessible text/popups;
- shows a visible online-basemap requirement and tile-load failure message;
- records the external tile request/privacy implication in report methodology;
- avoids map creation when geometry is unavailable.

Single-AOI reports show one boundary near the report summary. Batch notebook
preview shows every pending AOI together, labelled by resolved identifier.

`run_hydroseason` gains `show_map: Literal["auto"] | bool = "auto"`:

- `"auto"`: display before acquisition only in a Jupyter/IPython kernel;
- `True`: request inline display and warn if no display-capable IPython runtime
  exists;
- `False`: never display.

Scripts and CLI calls therefore stay silent by default. Map rendering and
notebook detection remain isolated from analysis and acquisition logic.

## Public multi-AOI API

Add:

```python
run_hydroseason_many(
    aois,
    *,
    output_dir,
    start_date,
    end_date,
    id_col=None,
    workers="auto",
    memory_budget_gb=None,
    show_map="auto",
    # shared single-run DEA, rainfall, analysis, and report options
) -> HydroSeasonBatchResult
```

The function is DEA/STAC-only in 0.1.1: there is no `water_source` parameter.
It loads and validates the vector input once, then creates one single-row
GeoDataFrame per non-empty input row. A MultiPolygon in one row remains one
AOI; multiple rows never dissolve into one analysis.

Identifiers:

- if `id_col` is given, require the column, nonblank values, and uniqueness;
- if omitted, generate stable `aoi-0001`, `aoi-0002`, ... identifiers;
- sanitize identifiers with the existing report filename rules;
- reject post-sanitization collisions before any network or filesystem work.

Every AOI writes under `output_dir/<safe-id>/`. If a shared `cache_dir` is
provided, each AOI uses `cache_dir/<safe-id>/`. No two workers write the same
target.

### Batch results and failures

Add immutable public result types:

```text
HydroSeasonAOIOutcome
  id
  source_position
  result: HydroSeasonRunResult | None
  error_type: str | None
  error_message: str | None

HydroSeasonBatchResult
  outcomes: tuple[HydroSeasonAOIOutcome, ...]
  succeeded
  failed
  raise_for_failures()
```

Outcomes preserve source-row order. One AOI failure does not cancel unrelated
AOIs. `raise_for_failures()` gives callers an explicit fail-fast handoff after
the batch completes.

## Adaptive scheduling

Default `workers="auto"` is parallel but conservative:

1. determine available logical CPUs and available physical memory;
2. reserve 40% of currently available memory for the OS/notebook and use 60%
   as the default global batch budget when `memory_budget_gb` is omitted;
3. estimate each AOI's native-resolution annual working set from projected
   bounds using existing spatial-planning arithmetic;
4. cap outer concurrency at two AOIs and at available CPU count;
5. admit concurrent AOIs only while their summed estimates fit the global
   budget;
6. run an AOI whose estimate exceeds the budget alone and attach a warning;
7. schedule larger AOIs first internally while restoring source order in the
   returned outcomes.

Use threads, matching the existing internal runner and the I/O/decode-heavy
acquisition path. Do not add process-based cache writers. Add `psutil` to the
STAC extra for cross-platform available-memory detection. If explicit
`workers=N` exceeds two, honor the override but keep the global memory admission
gate; `workers=1` guarantees sequential execution.

The scheduler controls outer AOI concurrency only. It must not override dask's
internal worker count, because repository profiling found forced internal
worker counts slower than dask's default.

## Data flow

```text
vector path / GeoDataFrame
        |
        v
load + validate rows -----> notebook all-AOI preview
        |
        v
resolve IDs + isolated paths + workload estimates
        |
        v
memory-aware thread scheduler (max 2 by default)
        |
        +----> run_hydroseason(single-row AOI) ----> result/report/map
        +----> run_hydroseason(single-row AOI) ----> result/report/map
        |
        v
ordered HydroSeasonBatchResult, including isolated failures
```

## Error handling

Preflight failures abort before processing:

- missing CRS;
- invalid or empty geometries;
- missing/nonunique identifiers;
- sanitized output collisions;
- invalid dates, workers, or memory budget.

Runtime failures are isolated per AOI and captured as type/message. Keyboard
interrupt and process-level cancellation propagate rather than being converted
into ordinary AOI failures. Existing rainfall best-effort behavior remains
inside each successful water run.

Map tile failure never fails analysis or report generation. Missing optional
AOI context simply omits maps.

## Documentation and report changes

Update:

- README quickstart with single and batch AOI examples;
- guide regime section with `R`, bootstrap bounds, threshold table, and the
  distinction between seasonality and boundary routing;
- API pages for new fields, result types, and functions;
- report-column dictionary for peak/trough concentration and confidence bounds;
- report methodology with literature citations and the under-30-year warning;
- map connectivity, attribution, and privacy note;
- explicit statement that one vector row equals one independent analysis in
  `run_hydroseason_many`;
- changelog and 0.1.1 release metadata.

Remove the incorrect guide claim that seasonality is decided by `SNR > 1.5`.
Reports must state live thresholds sourced from `REGIME_THRESHOLDS`, not copied
numbers.

## Compatibility

- Existing `run_hydroseason` calls and return type remain valid.
- `HydroSeasonRunResult` gains an optional field.
- `generate_catchment_report` gains an optional AOI argument/context.
- Regime and route outputs may change intentionally, especially Daly.
- Existing exported IQR names remain available.
- Existing no-AOI and core-only report tests remain map-free.
- The STAC extra gains the small `psutil` runtime dependency; core pandas-only
  analysis remains unchanged.

## Testing

### Scientific tests

- exact `R` for identical, adjacent, wraparound, dispersed, and bimodal months;
- deterministic bootstrap bounds for fixed seed;
- strong peak concentration plus SNR routes seasonal;
- high SNR with uncertain concentration routes marginal;
- low-R but significantly bimodal timing is not mislabeled as uniform;
- low SNR or weak concentration routes aseasonal;
- peak-seasonal/trough-unstable record uses fixed window;
- peak-seasonal/trough-stable record uses per-year detection;
- fewer than 30 timing years warns without automatic downgrade;
- IQR remains exported but changing IQR alone no longer controls classification;
- 30 m case-study sensitivity and reviewed regenerated outputs.

### Batch tests

- rows are never dissolved;
- MultiPolygon within one row stays one AOI;
- generated and explicit identifiers are deterministic;
- collisions fail before network work;
- output/cache paths are isolated;
- automatic scheduler overlaps small jobs but serializes oversized combinations;
- worker override and global memory gate interact as documented;
- outcomes preserve input order;
- one failure does not cancel other AOIs;
- interrupt propagates;
- scattered AOIs never produce one combined acquisition call.

### Map tests

- AOI context normalizes to compact EPSG:4326 GeoJSON;
- report embeds boundary, tile URL, attribution, and offline message only when
  AOI context exists;
- report does not embed raster tile bytes;
- notebook auto-display occurs before acquisition in IPython and never in a
  normal script;
- `show_map=False` suppresses display;
- batch preview contains all identifiers and boundaries;
- map failures do not change analysis artifacts.

### Verification

- focused tests for regime, catchment routing, workflow, batch workflow, map,
  report HTML, and docs;
- full `python -m pytest -q`;
- `ruff check .`;
- `python -m mkdocs build --strict`;
- build wheel/sdist and inspect package assets;
- regenerate and review checked case-study summaries/reports;
- exercise a small two-row DEA AOI batch when network integration testing is
  available.

## Acceptance criteria

- No classification or report copy depends on the 1.5-month IQR cutoff.
- Peak seasonality reports literature-aligned `R` with deterministic confidence
  bounds and sample size.
- Boundary routing reads trough evidence independently.
- Short annual records disclose sampling uncertainty without automatic regime
  downgrading.
- `run_hydroseason_many` treats every row independently and safely handles
  scattered AOIs.
- Default batch execution is memory-aware, parallel where safe, and capped at
  two outer workers.
- Single and batch notebook calls preview boundaries before remote work.
- Every report with AOI context contains a lightweight interactive boundary map
  using online tiles and correct attribution.
- Documentation cites primary studies and describes limitations accurately.
- Full tests, lint, docs, and package checks pass for version 0.1.1.
