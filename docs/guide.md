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
    analysis_options={"phase_model": "rule_based"},
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
checks whether a catchment has a reproducible annual cycle (signal-to-noise
ratio, or SNR — how strong and repeatable the yearly wet/dry swing is
relative to noise) and assigns one of two routes:

- **`per_year_detection`** (seasonal): SNR > 1.5. Hydrological year
  boundaries are anchored to climatological troughs, with complete annual
  recharge/trough metrics.
- **`event_characterisation`** (aseasonal): SNR ≤ 1.5. No hydrological years
  are forced — the workflow instead reports discrete wet inundation events
  and low-water spell durations.

---

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

??? note "Skip `run_hydroseason` and call `load_extent_csv`/`analyze_catchment`/`generate_catchment_report` yourself"

    Useful when you need custom loading, or want to inspect/modify the
    analysis before generating a report.

    ### Path 1: Extent CSV (Lightweight / Core Only)

    ```python
    from hydroseason import analyze_catchment, load_extent_csv

    extent = load_extent_csv("monthly_extent.csv", date_col="date", value_col="extent_pct")
    analysis = analyze_catchment(extent, phase_model="rule_based")
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
    analysis = analyze_catchment(extent, phase_model="rule_based")

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

??? note "Canonical mask codes, the fixed historical water mask, planning footprints, and cache integrity"

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
