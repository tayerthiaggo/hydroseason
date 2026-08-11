# Usage Guide

## Start here: one call

`run_hydroseason` is the function almost everyone needs. Point it at water
data — a CSV, a raster, or nothing at all (it will fetch DEA WOfS for you) —
and it writes back a self-contained HTML report plus four CSVs.

```python
from hydroseason import run_hydroseason

result = run_hydroseason(
    "monthly_extent.csv",
    output_dir="output/report",
    aoi_name="My AOI",
)

print(f"Regime: {result.analysis.regime.regime} | Route: {result.analysis.route}")
print(f"HTML report: {result.artifacts.html}")
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
    output_dir="output/isaac",
    aoi="isaac.geojson",
    aoi_name="Isaac River",
    start_date="2005-01-01",
    end_date="2025-12-01",
    cache_dir="cache/isaac",
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
| `.rainfall`, `.rainfall_status`, `.rainfall_comparison` | Present only when rainfall was requested |
| `.warnings` | Non-fatal issues encountered (e.g. rainfall fetch failure) |

Full CSV column dictionary: [Report Export Columns](report-columns.md).

---

## Which route did my catchment take?

`analyze_catchment` is the routing authority behind `run_hydroseason`. It
assesses annual amplitude (signal-to-noise ratio, SNR) and the reproducibility
of one annual peak month per usable year. Timing is circular: for peak month
`m_y` in year `y`, it calculates

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
| Seasonal | SNR >= 2 and peak `R` 95% CI lower bound >= 0.70 | A repeatable annual peak is supported. |
| Aseasonal | SNR < 0.70, or peak uniformity p >= 0.10 with at least 10 timing years | Do not force a hydrological year; report events and low spells. |
| Marginal | Otherwise | Evidence sits between the gates; a fixed climatological window is used only when both peak and trough evidence support it. |
| Insufficient record | <5 usable annual timings | Do not infer lack of seasonality from inadequate data. |

The seasonal label and the route are related but separate. Per-year boundaries
need trough timing support too: `per_year_detection` requires the lower 95%
bootstrap CI for trough `R` to be >= 0.70. A seasonal record with unstable
troughs instead uses `fixed_climatological_window`; complex or diffuse timing
uses `event_characterisation`. `n_timing_years` counts qualifying **years**,
not months. Fewer than 30 usable annual timings (not 30 months) keeps the
classification but warns that uncertainty intervals may be wide. The approved
10-year guard keeps a strong 5–9-year record marginal when a Kuiper uniformity
result has little power.

---

## Many AOIs: one row, one analysis

Use `run_hydroseason_many` for a DEA/STAC run that keeps each source vector row
independent. `run_hydroseason` accepts a multi-row AOI as one combined analysis
over the union footprint; `run_hydroseason_many` preserves rows, so one input
row produces one analysis and one report. A one-row `MultiPolygon` stays one
AOI. Results remain in input order even though the scheduler may start larger
AOIs first.

In other words: one input row produces one analysis and one report.

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
count but applies a default concurrency cap of 2. It reserves 40% and uses
60% of currently available RAM as the global admission budget. Before each
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

## AOI boundary maps

When an AOI is available, HydroSeason carries compact boundary geometry into
the report and embeds Leaflet with that boundary. The report remains readable
without map tiles. At view time its basemap requests tiles from OpenStreetMap;
those requests go to OpenStreetMap and require an internet connection. The
boundary is embedded locally, so it remains visible if tiles fail.

`show_map="auto"` previews the boundary before acquisition only in a Jupyter
or IPython kernel. `show_map=True` requests an inline preview (and warns if it
cannot display); `show_map=False` suppresses previews. The display boundary
may be topology-preservingly simplified and rounded for compact output. It is
display-only: the analysed footprint remains the unsimplified acquisition
geometry and fixed historical water mask.

## Data quality before you trust it

Water-mask gaps, cloud/shadow contamination, and missing months can shift
wet/dry boundaries. **Strongly consider gapfilling** (e.g. [WaterMask-TSFill](https://github.com/tayerthiaggo/WaterMask-TSFill))
on raw/incomplete masks before running hydro-year detection. The robust
detector still reports an observed extremum when its month exceeds
`max_invalid_pct=20.0`% invalid coverage, but marks that extremum
`low_quality` and the annual cycle `provisional`; low-quality cycles cannot
anchor historical condition baselines.

For review-oriented mapping where every finite observation should
contribute to the cycle search, pass `quality_policy="flag"` (the main
case-study build uses this mode). Months with partial invalid coverage
remain `usable_month=True`, while `invalid_pct`, `quality_state="low"`,
support, and confidence expose the uncertainty. A month with 100% invalid
coverage or no observed extent remains unusable.

---

## Advanced: calling the building blocks directly

> [!NOTE]
> Skip `run_hydroseason` and call `load_extent_csv`/`analyze_catchment`/`generate_catchment_report` yourself

Useful when you need custom loading, or want to inspect/modify the
analysis before generating a report.

### Path 1: Extent CSV (Lightweight / Core Only)

```python
from hydroseason import analyze_catchment, load_extent_csv

extent = load_extent_csv("monthly_extent.csv", date_col="date", value_col="extent_pct")
analysis = analyze_catchment(extent)
```

### Path 2: Generic Rasters or Local Zarr

Requires `pip install "hydroseason[raster]"`.

```python
from hydroseason import load_monthly_masks, monthly_water_extent

masks = load_monthly_masks(
    "masks_dir/", "2015-01-01", "2020-12-31",
    aoi="aoi.geojson", encoding="binary",
)
extent = monthly_water_extent(masks)
```

### Path 3: WOfS / STAC Acquisition

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

### HTML & CSV Report Bundle Export

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

---

## Advanced: DEA acquisition internals

> [!NOTE]
> Canonical mask codes, the fixed historical water mask, planning footprints, and cache integrity

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

The verified manifest pins source product/version, item IDs, lineage, and coverage start/end. The source observed at design time was unfiltered and covered 1987--2025; use the manifest's exact values as authority. If `coverage_end` predates the requested analysis end, or no verified cache exists in offline mode, loading fails closed and never substitutes the full AOI.

`open_wo_statistics` remains available for direct inspection:
```python
from hydroseason import open_wo_statistics

stats = open_wo_statistics(stac_url="https://explorer.dea.ga.gov.au/stac", aoi="aoi.geojson")
```

### 2. Conservative Planning Footprint (`WetPlanningFootprint`)
To optimize tile acquisition and I/O without shrinking the scientific denominator, generate a conservative max-pooled planning footprint:
```python
from hydroseason import build_wet_planning_footprint, acquire_wofs_cache

footprint = build_wet_planning_footprint(aoi="aoi.geojson", resolution_m=30)

# Pass footprint as performance-only I/O filter
handle = acquire_wofs_cache(
    stac_url="https://explorer.dea.ga.gov.au/stac",
    aoi="aoi.geojson",
    planning_footprint=footprint,
)
    ```

> [!IMPORTANT]
> **Superset Guarantee:** `WetPlanningFootprint` expands native wet pixels via max pooling. All historical-mask pixels remain inside the planning footprint. The exact historical raster, not this performance-only superset, determines `n_aoi` and `invalid_pct`.

> [!NOTE]
> **Full-AOI diagnostic mode:** Pass `use_historical_water_mask=False`, or use `--full-aoi` in the extraction script, only when an explicit full-AOI diagnostic/reference result is required.

### 3. Mask Cache Integrity & Dual Composite Bundles
Local cache stores record persistent metadata to prevent tamper or mismatched parameters:
- **`verify_cache_footprints`**: Validates cache footprint integrity against full AOI metadata.
- **`open_completed_mask_cache`**: Opens completed Zarr mask cache handles.
- **`open_completed_dual_extent_counts`**: Retrieves dual max-water and median-water extent count sidecars when `composite_bundle="dual_composite_v1"` is enabled.

`composite_bundle` selects the acquisition's output semantics: `"single_mask"` (the default) preserves every existing result and cache identity byte-for-byte; `"dual_composite_v1"` additionally computes dual max-water/median-water composites for downstream fragment analysis.
