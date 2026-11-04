# Usage Guide

## Start here: one call

`run_hydroseason` is the function almost everyone needs. It analyzes satellite water data — from a CSV,
a raster, or fetched directly from DEA WOfS — and writes back a self-contained HTML
report, four CSVs, and a run manifest (`<stem>_manifest.json`).

```python
from hydroseason import run_hydroseason

result = run_hydroseason(
    "monthly_extent.csv",
    output_dir="output/report",
    aoi_name="My AOI",
)

print(f"Regime: {result.analysis.regime.regime} | Route: {result.analysis.route}")
print(f"HTML report: {result.artifacts.html}")
print(f"Manifest: {result.artifacts.manifest_json}")
```

See real output first: [Fitzroy River report](examples/fitzroy-river-wa.html)
(seasonal regime) and [Lachlan River report](examples/lachlan-river-nsw.html)
(aseasonal regime).

---

## The four ways to run it

`run_hydroseason` accepts water input in four shapes. Pick the row that
matches what you already have:

| You have... | Pass it as `water_source` | Extra required |
|---|---|---|
| A monthly extent CSV or `pandas.DataFrame` | the CSV path or the DataFrame | none (core install) |
| A NetCDF/Zarr file, or an `xarray` object | the file path, or the `Dataset`/`DataArray` | `hydroseason[raster]` |
| Nothing yet — fetch it from DEA | `None`, plus `aoi=`, `start_date=`, `end_date=` | `hydroseason[stac]` |
| Any of the above, plus rainfall context | add `fetch_rainfall=True` or `rainfall_csv_path=` | `hydroseason[raster]` for SILO fetch |

### 1. From a CSV you already have

```python
result = run_hydroseason(
    "monthly_extent.csv",
    output_dir="output/report",
    aoi_name="My AOI",
)
```

Optional `invalid_pct` defaults to `0.0`, treating the CSV as an
already-screened series.

If you have pixel counts, include them as `n_water`, `n_valid`, `n_invalid`
and `n_aoi` columns. HydroSeason then works out the percentages itself:
`extent_pct = 100 * n_water / n_valid`, the wet share of the pixels observed
that month, and `invalid_pct = 100 * n_invalid / n_aoi`. These replace any
percentages in the file, and a warning reports the months where a supplied
`extent_pct` disagrees, for example because it was a share of the whole AOI.
Counts also tell HydroSeason how small a change it can detect. Without them,
on a series that barely changes from month to month, that detectability floor
can fall to effectively zero, so tiny fluctuations pass as a season;
HydroSeason warns when this happens. Pass counts whenever you have them.

### 2. From rasters, NetCDF, or Zarr

Requires `pip install "hydroseason[raster]"`.

```python
result = run_hydroseason(
    "monthly_masks.nc",
    output_dir="output/local",
    water_mask_variable="water_mask",
    aoi_name="Local AOI",
)
```

### 3. Fetch DEA WOfS for an AOI

Requires `pip install "hydroseason[stac]"`.

```python
result = run_hydroseason(
    output_dir="output/fitzroy",
    aoi="fitzroy.geojson",
    aoi_name="Fitzroy River",
    start_date="2005-01-01",
    end_date="2025-12-01",
)
```

Before any monthly data is fetched, one all-time WOfS Statistics read screens
the AOI for recurrent surface water. An AOI with none raises
`HydroSeasonPreflightError` rather than returning an empty analysis; a
Statistics outage warns and continues instead of being read as "no water".
See [Preflight](preflight.md).

This resolves the fixed historical water mask and separate planning
superset described in [Advanced: DEA acquisition internals](#advanced-dea-acquisition-internals)
below. Regime, hydrological-year, phase, wet-event, and low-spell logic
continues to select from `extent_pct`; no absolute-area columns are added.

### 4. Add rainfall context (optional)

Rainfall is off by default and always ancillary: it enriches the monthly CSV
and HTML report but never changes water regime, route, boundaries, phases,
wet events, or low spells.

```python
result = run_hydroseason(
    "monthly_masks.nc",
    output_dir="output/local",
    water_mask_variable="water_mask",
    aoi_name="Local AOI",
    rainfall_csv_path="monthly_rainfall.csv",
)

# Or fetch SILO rainfall automatically over the resolved water-extent years:
result = run_hydroseason(
    output_dir="output/fitzroy",
    aoi="fitzroy.geojson",
    aoi_name="Fitzroy River",
    start_date="2005-01-01",
    end_date="2025-12-01",
    fetch_rainfall=True,
)
```

`rainfall_csv_path` takes precedence over `fetch_rainfall=True`.
`result.rainfall_status` is one of `disabled`, `provided`, `fetched`,
`provided_failed`, or `fetch_failed`. A supplied/fetched load failure or
comparison failure emits a warning and is recorded on the result, but the
water-only report bundle is still written. Water loading, analysis, and
report-writing failures remain fatal.

### 5. Watch a long run

`run_hydroseason` is silent by default. `progress=True` writes five numbered
step lines to standard error and switches on a bar that ticks once per
calendar year during a DEA fetch:

```python
result = run_hydroseason(
    output_dir="output/fitzroy",
    aoi="data/fitzroy_kimberley_aoi.geojson",
    aoi_name="Fitzroy River (WA)",
    start_date="2005-01-01",
    end_date="2025-12-01",
    cache_dir="cache/fitzroy",
    progress=True,
)
```

Pass a callable instead to receive structured events — one
`hydroseason._progress.ProgressEvent` per step boundary, carrying `step`,
`total_steps`, `label`, `phase`, `detail`, and `elapsed_s` — and no bar:

```python
events = []
result = run_hydroseason(..., progress=events.append)
```

For runs long enough to outlive a notebook session, use the command line
instead; see [CLI Recipes](cli-recipes.md).

!!! note "Both DEA searches share one endpoint"
    The fetch path performs two STAC searches: the monthly `ga_ls_wo_3`
    search and the `ga_ls_wo_fq_myear_3` historical-statistics search that
    fixes the spatial denominator. `stac_url` configures both. Pass
    `statistics_stac_url` only to point them at different services.

---

## What you get back

`run_hydroseason` returns a `HydroSeasonRunResult`:

| Field | Contents |
|---|---|
| `.analysis` | `CatchmentAnalysis` — regime, route, hydrological years, events, low spells |
| `.artifacts.html` | Path to the self-contained HTML report |
| `.artifacts.monthly_csv` | Monthly timeline CSV |
| `.artifacts.hydro_years_csv` | Hydrological-year markers CSV |
| `.artifacts.wet_event_csv` | Wet inundation events CSV |
| `.artifacts.low_spells_csv` | Low-extent spells CSV |
| `.artifacts.manifest_json` | Run manifest: method fingerprint, input and output checksums, versions |
| `.preflight_result` | DEA recurrent-water screen result (`None` for CSV/raster input) |
| `.rainfall`, `.rainfall_status`, `.rainfall_comparison` | Present only when rainfall was requested |
| `.warnings` | Non-fatal issues encountered (e.g. rainfall fetch failure) |

Full CSV column dictionary: [Report Export Columns](report-columns.md).

---

## Which route did my catchment take?

`analyze_catchment` is the routing authority behind `run_hydroseason`. It
assesses calendar timing recurrence and the reproducibility of annual peak and
trough months per usable year. Timing is circular: for peak month `m_y` in
year `y`, it calculates

```text
theta_y = 2*pi*(m_y - 1)/12
R = |mean(exp(i*theta_y))|
```

`R` is the mean resultant length, from 0 (diffuse or cancelling timing) to 1
(the same month every year). Its 95% bootstrap interval resamples usable
annual timings. Circular IQR is retained as a descriptive spread in months;
it is not a regime cutoff. A low `R` can also arise from symmetric bimodality:
January/July preferences cancel even though timing is not uniform. The Kuiper
test complements `R` by testing the discrete 12-month uniform null.

| Regime | Decision rule | Interpretation |
|---|---|---|
| Seasonal | Peak Kuiper p < 0.05 and trough Kuiper p < 0.05, with >= 5 detectable years | Calendar recurrence of annual peak and trough timing is established. |
| Aseasonal | Recurrence not established (peak or trough Kuiper p >= 0.05, or < 5 detectable years) | Timing recurrence is not established; do not force a hydrological year. Report discrete wet events and low-extent spells. |
| Insufficient record | < 5 qualifying calendar years (>= 9 candidate-usable months each) | Do not infer lack of seasonality from inadequate data. |

The regime label and the route are related but separate. In v0.2.0, the
route additionally requires that annual timing be *identifiable* and satisfy the
**seven-cycle annualization guard**:
- `per_year_detection` is used only for a seasonal record where at least 7 informative peak cycles and at least 7 informative trough cycles are resolved.
- If fewer than 7 cycles are resolved, dynamic annual boundaries are withheld, and the catchment routes to `event_characterisation` instead — wet events and low-extent spells are reported, but no dynamic hydrological-year boundary is published.

When only one extremum recurs, the conjunction decides against seasonality and
the reason says which test failed. A record whose trough returns to the same
month every year while flood peaks land anywhere is aseasonal with reason
`peak_uniformity_not_rejected`; the mirror case gives
`trough_uniformity_not_rejected`. The recurring extremum's test is still
reported: `peak_timing_uniformity_p` and `trough_timing_uniformity_p` are public
on `WaterRegimeAssessment`, and the full test, including each year's
equivalent-month sets and the dominant month, is on
`assessment.seasonality_test`. `mean_monthly_peak_month` and
`mean_monthly_trough_month` are `None` unless the record is seasonal.

Fewer than 30 usable annual timings (not 30 months) keeps the classification
but warns that uncertainty intervals may be wide.

Exact-zero extent is a valid dry observation, not missing data, and zero
frequency (`n_zero_months`, `zero_month_fraction`, `n_whole_zero_years`) is
reported descriptively but never used to decide detectability or route. A
whole-zero year still contributes to dry-duration and event summaries; it
contributes no peak or trough timing observation. See
[Dynamic Hydrological State](hydrological-state.md#diagnostic-columns) for the
per-cycle `timing_status` fields and
[Methods Reference](methods.md) for method specifications.

---

## Many AOIs: one row, one analysis

Use `run_hydroseason_many` for a DEA/STAC run over a multi-row vector layer
(GeoPackage, Shapefile, GeoJSON): one input row produces one analysis and one report.
`run_hydroseason`, by contrast, treats a multi-row AOI as one combined analysis
over the union footprint. A one-row `MultiPolygon` stays one AOI. Results
remain in input order even though the scheduler may start larger AOIs first.

```python
from hydroseason import run_hydroseason_many

batch = run_hydroseason_many(
    "catchments.gpkg",
    output_dir="results",
    cache_dir="cache",
    start_date="2000-01-01",
    end_date="2025-12-01",
    id_col="catchment_id",
    workers="auto",
)

for outcome in batch.outcomes:
    if outcome.succeeded:
        print(outcome.id, outcome.result.artifacts.html)
    else:
        print(outcome.id, outcome.error_type, outcome.error_message)
batch.raise_for_failures()
```

Each run writes `output_dir/<safe-id>/`; a shared cache writes to
`cache_dir/<safe-id>/`. `id_col` values must be nonblank and unique (including
after filename sanitisation). Without it, identifiers are stable
`aoi-0001`, `aoi-0002`, and so on. A failed AOI is captured in its
`HydroSeasonAOIOutcome` and does not cancel unrelated rows; call
`batch.raise_for_failures()` after handling any successes to raise one summary
error for all failures.

### Batch memory and threads

With `workers="auto"`, HydroSeason chooses at most the available logical CPU
count but applies a default concurrency cap of 2. By default it uses 80% of
currently available RAM as the global admission budget; pass
`memory_budget_gb=` to set it explicitly. Before each
run, a conservative native-30 m peak-memory estimate is calculated from the
AOI bounding box; the box is intentionally conservative because it includes
space outside irregular geometry. An AOI estimated above the budget emits a
warning and runs alone, never alongside another batch item.

Set `workers=1` for strictly sequential execution, or an explicit positive
integer to override the default worker cap. The global memory admission gate
still applies. A native 30 m whole-catchment run is commonly about 10 GB on a
typical 8–16 GB machine, so sequential execution may be necessary. The outer
thread pool improves I/O overlap; it does not force Dask's internal pool and
does not mean 2x computational throughput.

If you run HydroSeason in your own process pool, for example with
`concurrent.futures.ProcessPoolExecutor` over many CSVs, set
`OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1` and `MKL_NUM_THREADS=1` in the
environment before the workers start. Otherwise each worker's numerical
libraries can start one thread per CPU, and the pool oversubscribes the
machine.

## AOI boundary maps

When an AOI is available, HydroSeason carries compact boundary geometry into
the report and embeds Leaflet with that boundary. The report remains readable
without map tiles. At view time its basemap requests online tiles
(from Esri World Topo Map / OpenStreetMap); those requests require an
internet connection. The boundary is embedded locally, so it remains visible if
tiles fail.

`show_map="auto"` previews the boundary before acquisition only in a Jupyter
or IPython kernel. `show_map=True` requests an inline preview (and warns if it
cannot display); `show_map=False` suppresses previews. The display boundary
may be topology-preservingly simplified and rounded for compact output. It is
display-only: the analysed footprint remains the unsimplified acquisition
geometry and fixed historical water mask.

## Choosing the area to analyse

HydroSeason reports on all the surface water inside the area you give it, so
the area decides what the dates mean. Choose it for the question you are
asking: a reach, a refuge, a planning zone, a subbasin or a whole catchment.

A study on the five case-study catchments compared 1,278 areas built from the
same 30 m pixels: whole catchments, HydroBASINS subbasins (Lehner and Grill
2013, [10.1002/hyp.9740](https://doi.org/10.1002/hyp.9740)) of about 4,800,
1,700 and 480 km², and square grid tiles of the same three sizes. Its
decision rules were fixed before any result was read.

**Grid tiles work as well as subbasins of the same size.** At matched size,
tiles and subbasins routed to per-year detection at the same rate (difference
−1.2 percentage points, 95% interval −5.1 to +2.5) and confirmed the same
share of cycle boundaries (+0.9 points, −0.6 to +2.5). You do not need to
redraw areas along drainage divides for the method to behave.

**Small areas detect the season but date it less consistently.** In the three
seasonal catchments, more than 92% of areas routed seasonal even when they
held very little water. Areas with fewer than about 100 water pixels in a typical month (about
0.09 km² of open water at 30 m) had a trough within one month of their
catchment's in only 38–45% of cases, against 80% or more for larger areas, and
fewer of their cycle boundaries were confirmed. This comparison was
exploratory, and part of the difference may be real local timing. Treat dates
from areas that small as indicative, and compare them with a larger area that
contains them.

**A whole catchment can hide seasonal parts.** The Lachlan routes aseasonal as
a whole, yet 16 of its 36 level-7 subbasins (about 1,700 km² each) route
seasonal, mostly in the upper catchment, with winter–spring peaks and summer
troughs. The subbasins that stay aseasonal hold about four times as much
water, so they dominate the catchment total. If a large catchment routes
aseasonal, run its subbasins before concluding it has no season; a catchment
that is aseasonal throughout (the Moonie: none of its 7 subbasins) stays
aseasonal when split.

**A catchment's dates describe most of its parts, not all.** In the seasonal
catchments, a quarter of level-7 subbasins (24.7%) had a typical trough month
more than one month from their catchment's. When the timing at a particular
reach or refuge matters, analyse that area as well.

**Borrow peaks more readily than troughs, and from the nearest larger area.**
A second study compared the dates year by year: each subbasin against the
subbasin one level up that contains it, and against its whole catchment.
- **Agreement within one month.** A subbasin's peak agreed with the subbasin
  containing it in 87% of cycles and with its catchment in 84%. Its trough
  boundary agreed in 81% and 73%.
- **Above about 100 water pixels a month.** The containing subbasin's peak
  and trough dates both agreed in at least 89% of cycles.
- **The whole catchment's trough boundary** fell below 80% agreement even for
  the largest subbasins.

If you need a place's dry-season boundary, run that place or the subbasin
just above it rather than borrowing the catchment's.

In practice:

- Prefer areas with at least a few hundred water pixels in a typical month
  when you need dates, not only a seasonal or aseasonal call.
- For a large catchment, also run its subbasins and compare. HydroBASINS
  level 7 is a convenient, citable set; `run_hydroseason_many` takes one row
  per subbasin.
- When you combine areas, sum their pixel counts rather than averaging
  percentages (see [Dynamic Hydrological State](hydrological-state.md)).

## Dates around the dry-season low

The hydrological-years table gives two dates around the dry-season low, and
both come from the same boundary.

- `trough_boundary_date` is the cycle boundary that the trough method places
  at the end of the dry-season low; [Dynamic Hydrological State](hydrological-state.md)
  explains how it is found and refined. `trough_date` repeats it only when the
  low resolves to a single month; the interval columns give its span
  otherwise.
- The **following year's `start_date`** is the month after that boundary. It
  is always `trough_boundary_date` plus one month, except for the first year
  of the record and a year that starts after a gap.

Because both dates come from one boundary, they vary across a catchment in
the same way. In the five case-study catchments a quarter of level-7
subbasins had a typical trough more than a month from their catchment's, so
read these dates for the area your question is about.

**How far to trust a single trough month.** `trough_date` appears only when
the trough status is `point`. That means one month stood out as the lowest
since the cycle's peak by more than the cycle's detectability floor. The
months after the trough are not compared. So the low is distinct, but the
month is not necessarily exact. Three November 2026 known-truth tests (G2,
L1 and L2, each on fresh records) used synthetic seasons and seasons
injected into real records, with today's defaults:

- On weak cycles (amplitude 3 to 6 times the floor), between 1 in 3 and
  just over 4 in 10 `point` troughs were more than a month from the true
  month.
- On strong, smooth seasons (10 or more times the floor), fewer than 1 in 7
  were.
- Where water recedes slowly to its low, a trough that missed was early
  eight to nine times in ten, by two to five months, whatever the
  amplitude.
- A `point` trough was not right more often than an `interval` one. On
  smooth seasons it was right less often.

On weak cycles, or where the recession is long and flat, read a single
trough month as approximate. Check it against `amplitude_to_floor_ratio`
and the interval columns.

## Data quality before you trust it

Water-mask gaps, cloud/shadow contamination, and missing months can shift
wet/dry boundaries. **Strongly consider gapfilling** (e.g. [WaterMask-TSFill](https://github.com/tayerthiaggo/WaterMask-TSFill))
on raw/incomplete masks before running hydro-year detection. The robust
detector still reports an observed extremum when its month exceeds
`max_invalid_pct=20.0`% invalid coverage. For the TROUGH this still marks
that extremum `low_quality` and the annual cycle `provisional`; low-quality
trough cycles cannot anchor historical condition baselines. The PEAK is
judged differently: it is compared against its own calendar month's typical
invalid coverage (see `peak_quality` below), so routine wet-season cloud over
the peak no longer marks the cycle `provisional` on its own — only a peak
that is anomalous for its own month, or obscured past an absolute backstop,
does.

For review-oriented mapping where every finite observation should
contribute to the cycle search, pass `quality_policy="flag"` (the main
case-study build uses this mode). Months with partial invalid coverage
remain `usable_month=True`, while `invalid_pct`, `quality_state="low"`,
support, and confidence expose the uncertainty. A month with 100% invalid
coverage or no observed extent remains unusable.

---

## Scientific uncertainty and calibration semantics

HydroSeason rigorously separates four distinct uncertainty concepts and avoids conflating quality classifications with probabilistic confidence:

1. **Observation uncertainty**: Satellite surface-water measurement error, cloud/shadow gaps, sensor resolution limitations, and historical mask boundaries.
2. **Statistical sampling uncertainty**: Sampling variation across available observation years, quantified via non-parametric bootstrap confidence intervals (e.g., circular timing concentration CIs) and Wilson score intervals for discrete rates.
3. **Model structural uncertainty**: Discretization choices in harmonic order selection, circular statistics assumptions, and rule-based cycle-relative phase thresholding.
4. **Empirical threshold validation**: Calibrated false annualisation, abstention, boundary error, and phase accuracy bounds established over 5,000 independent synthetic benchmarks.

### Post-selection held-out skill (`seasonal_cv_skill`)

The `seasonal_cv_skill` metric measures **post-selection** cross-validation skill: the fraction of variance explained by the fitted seasonal harmonic model evaluated strictly on held-out folds after selecting the harmonic order. It quantifies how well the chosen seasonal cycle predicts unseen years, distinguishing true periodic regularities from in-sample overfitting.

### Benchmark recoverability vs real-world validation

Boundary recoverability metrics (such as leave-one-year-out within-one-month accuracy and MAE) demonstrate algorithmic recoverability under controlled benchmark data with known truth. Real-world boundary accuracy is not claimed as interchangeable with streamflow or gauge discharge without catchment-specific physical validation. Quality grades indicate methodological admissibility under explicit evidentiary thresholds, not probabilities of truth.

---

## Advanced: calling the building blocks directly

Skip `run_hydroseason` and call `load_extent_csv`, `analyze_catchment`, and
`generate_catchment_report` yourself. Useful when you need custom loading, or want to inspect/modify the
analysis before generating a report.

### Extent CSV (core install)

```python
from hydroseason import analyze_catchment, load_extent_csv

extent = load_extent_csv("monthly_extent.csv", date_col="date", value_col="extent_pct")
analysis = analyze_catchment(extent)
```

### Rasters or local Zarr

Requires `pip install "hydroseason[raster]"`.

```python
from hydroseason import load_monthly_masks, monthly_water_extent

masks = load_monthly_masks(
    "masks_dir/", "2015-01-01", "2020-12-31",
    aoi="aoi.geojson", encoding="binary",
)
extent = monthly_water_extent(masks)
```

### DEA WOfS via STAC

Requires `pip install "hydroseason[stac]"`.

```python
from hydroseason import load_wofs_monthly_extent

extent = load_wofs_monthly_extent(
    stac_url="https://explorer.dea.ga.gov.au/stac",
    collection="ga_ls_wo_3",
    aoi="aoi.geojson",
    start_date="2005-01-01",
    end_date="2025-12-01",
    cache_dir="output/extent_cache",
    mask_cache_dir="output/wofs_cache",
)
```

### Report bundle

```python
from hydroseason import analyze_catchment, generate_catchment_report, load_extent_csv

extent = load_extent_csv("monthly_extent.csv")
analysis = analyze_catchment(extent)

paths = generate_catchment_report(
    extent,
    output_dir="output/report",
    name="fitzroy_river_wa",  # optional AOI label
    analysis=analysis,
    title="Fitzroy River (WA)",
    subtitle="Surface-water hydrological analysis",
)
```

`name` is optional and can be any AOI label (it does not need to be a
named catchment). If omitted or blank, the report uses **HydroSeason
results** and the files use the `hydroseason-results` stem.

`generate_catchment_report` also writes the run manifest
(`<stem>_manifest.json`, schema `hydroseason-run-manifest-v1`) recording the
method policy (`hydroseason-v0.2.0`) and its fingerprint, package and
dependency versions, and output checksums; `paths.manifest_json` points to it.

---

## Advanced: DEA acquisition internals

### Canonical Mask Shape

Every raster loader converges on the same canonical values before detection sees the data (`time`/`y`/`x`, `int8`):

| Value | Meaning |
|---:|---|
| `1` | Water |
| `0` | Dry |
| `-1` | Invalid (cloud, shadow, no-data, out-of-domain code) |
| `-2` | Outside AOI |

`monthly_water_extent` summarizes a canonical cube into a monthly `extent_pct`/`invalid_pct` DataFrame. Only pixels explicitly equal to `0` or `1` count as valid observations (`n_valid`). In the default high-level DEA workflow, `n_aoi` is the fixed historical-water-mask pixel count; invalid pixels outside that mask are `-2` and do not contribute to `invalid_pct`.

### AOI and Input Requirements

`load_monthly_masks` and `load_wofs_from_stac` both require an AOI (`aoi=`, a vector path or `geopandas.GeoDataFrame`, validated by `load_aoi`). If AOI clipping or rasterization fails, the loader raises rather than processing an unclipped raster. `load_monthly_masks_zarr` assumes the Zarr cube is already canonical and AOI-clipped.

### 1. Fixed Historical Water Mask

The default high-level route is:

`user AOI acquisition boundary -> cached DEA Multi-Year Statistics -> fixed unfiltered count_wet > 0 raster -> separate planning superset -> monthly WOfS -> percentage-based analysis -> four CSVs`

HydroSeason queries or reuses exactly one pinned `ga_ls_wo_fq_myear_3` artifact. The scientific mask is exactly `(count_wet > 0) AND rasterized user AOI` on the analysis grid. It has no frequency threshold, closing, buffer, Calendar Year union, or polygon round trip. The same raster is used for every requested month.

The verified manifest pins source product/version, item IDs, lineage, and coverage start/end. The source observed at design time was unfiltered and covered 1987--2025; use the manifest's exact values as authority. If no verified cache exists in offline mode, loading still fails closed and never substitutes the full AOI. If the requested analysis window falls outside `[coverage_start, coverage_end]`, the run instead proceeds with a `HistoricalMaskCoverageWarning`; a window that extends past `coverage_end` carries a one-sentence truncation caveat, since a pixel first inundated after `coverage_end` is invisible to the mask and is not counted in `extent_pct` for the affected months.

**Refresh lifecycle.** A cached historical water mask is pinned to its build vintage: an ordinary run whose window falls entirely inside the cached coverage never touches the network, and the cached artifact is returned as-is. A run whose window overhangs the cached coverage instead probes DEA for a refresh -- a cheap metadata-only check for wider Statistics coverage -- and adopts it if one exists. Adopting a refreshed vintage changes `n_aoi` (the mask's pixel count) and therefore shifts `extent_pct` across the whole record, not only the newly-covered months; that whole-record shift is why adoption warns (`HistoricalMaskRefreshedWarning`) rather than proceeding quietly. The superseded artifact is retained under `artifacts/<digest>/` rather than deleted, so an earlier run built against it stays reproducible. Pass `refresh_historical_mask=False` to pin deliberately and always return the cached artifact unchanged. To force a rebuild of a pinned cache by hand, delete `<cache_root>/historical-water-masks/index/<request_digest>.json` and leave `artifacts/` alone -- the next run resolves a cache miss and rebuilds.

`open_wo_statistics` remains available for direct inspection:
```python
from hydroseason import open_wo_statistics

stats = open_wo_statistics(stac_url="https://explorer.dea.ga.gov.au/stac", aoi="aoi.geojson")
```

### 2. Conservative Planning Footprint (`WetPlanningFootprint`)
To limit tile reads without shrinking the scientific denominator, build a
conservative max-pooled planning footprint from the WOfS statistics:

```python
from hydroseason import acquire_wofs_cache, build_wet_planning_footprint, open_wo_statistics

stats = open_wo_statistics("aoi.geojson")
footprint = build_wet_planning_footprint(stats, requested_years=range(2005, 2026))

handle = acquire_wofs_cache(
    "https://explorer.dea.ga.gov.au/stac",
    "ga_ls_wo_3",
    "aoi.geojson",
    "2005-01-01",
    "2025-12-01",
    cache_root="output/wofs_cache",
    planning_footprint=footprint,  # performance-only read filter
)
```

!!! important "Superset guarantee"
    `WetPlanningFootprint` expands native wet pixels via max pooling. All historical-mask pixels remain inside the planning footprint.
    The exact historical raster, not this performance-only superset, determines
    `n_aoi` and `invalid_pct`.

!!! note "Full-AOI diagnostic mode"
    Pass `use_historical_water_mask=False` to `load_wofs_monthly_extent` only
    when an explicit full-AOI diagnostic/reference result is required.

### 3. Mask Cache Integrity & Dual Composite Bundles
Local cache stores record persistent metadata to prevent tamper or mismatched parameters:
- **`verify_cache_footprints`**: Validates cache footprint integrity against full AOI metadata.
- **`open_completed_mask_cache`**: Opens completed Zarr mask cache handles.
- **`open_completed_dual_extent_counts`**: Retrieves dual max-water and median-water extent count sidecars when `composite_bundle="dual_composite_v1"` is enabled.

`composite_bundle` selects the acquisition's output semantics: `"single_mask"` (the default) preserves every existing result and cache identity byte-for-byte; `"dual_composite_v1"` additionally computes dual max-water/median-water composites for downstream fragment analysis.
