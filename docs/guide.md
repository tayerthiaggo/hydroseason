# Usage Guide

## Canonical Mask Shape

Every raster loader converges on the same canonical values before detection sees the data (`time`/`y`/`x`, `int8`):

| Value | Meaning |
|---:|---|
| `1` | Water |
| `0` | Dry |
| `-1` | Invalid (cloud, shadow, no-data, out-of-domain code) |
| `-2` | Outside AOI |

`monthly_water_extent` summarizes a canonical cube into a monthly `extent_pct`/`invalid_pct` DataFrame. Only pixels explicitly equal to `0` or `1` count as valid observations (`n_valid`). In the default high-level DEA workflow, `n_aoi` is the fixed historical-water-mask pixel count; invalid pixels outside that mask are `-2` and do not contribute to `invalid_pct`.

---

## AOI and Input Requirements

`load_monthly_masks` and `load_wofs_from_stac` both require an AOI (`aoi=`, a vector path or `geopandas.GeoDataFrame`, validated by `load_aoi`). If AOI clipping or rasterization fails, the loader raises rather than processing an unclipped raster. `load_monthly_masks_zarr` assumes the Zarr cube is already canonical and AOI-clipped.

---

## Gapfilling Recommendation

Water-mask gaps, cloud/shadow contamination, and missing months can shift wet/dry boundaries. **Strongly run gapfilling (e.g. WaterMask-TSFill) on raw/incomplete masks before running hydro-year detection.** The robust detector still reports an observed extremum when its month exceeds `max_invalid_pct=20.0`% invalid coverage, but marks that extremum `low_quality` and the annual cycle `provisional`; low-quality cycles cannot anchor historical condition baselines.

For review-oriented mapping where every finite observation should contribute to
the cycle search, pass `quality_policy="flag"` (the main case-study build uses
this mode). Months with partial invalid coverage remain `usable_month=True`,
while `invalid_pct`, `quality_state="low"`, support, and confidence expose the
uncertainty. A month with 100% invalid coverage or no observed extent remains
unusable.

---

## Digital Earth Australia (DEA) & Cache Contracts

HydroSeason provides direct interfaces for Digital Earth Australia (DEA) Water Observations (`ga_ls_wo_3`) and local Zarr caching:

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
> **Legacy Compatibility:** Pass `use_historical_water_mask=False`, or use `--full-aoi` in the extraction script, only when an explicit full-AOI diagnostic/reference result is required.

### 3. Mask Cache Integrity & Dual Composite Bundles
Local cache stores record persistent metadata to prevent tamper or mismatched parameters:
- **`verify_cache_footprints`**: Validates cache footprint integrity against full AOI metadata.
- **`open_completed_mask_cache`**: Opens completed Zarr mask cache handles.
- **`open_completed_dual_extent_counts`**: Retrieves dual max-water and median-water extent count sidecars when `composite_bundle="hydrofragments_v1"` is enabled.

---

## Input Paths

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

This default resolves the fixed historical mask and separate planning superset. Regime, hydrological-year, phase, wet-event, and low-spell logic continues to select from `extent_pct`; no absolute-area columns are added.

---

## Catchment Routing Authority

`analyze_catchment` assesses water regime and automatically assigns the supported analysis route:

- **`per_year_detection`**: Applied when SNR > 1.5. Anchors hydrological year boundaries to climatological troughs.
- **`event_characterisation`**: Applied when SNR ≤ 1.5. Characterizes inundation events and low-water spells without forcing hydrological year partitions.

---

## HTML & CSV Report Bundle Export

Generate manager-ready self-contained HTML reports and the four matching CSV exports (`monthly`, `hydro_years`, `wet_event`, and `low_spells`):

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

`name` is optional and can be any AOI label (it does not need to be a named
catchment). If omitted or blank, the report uses **HydroSeason results** and
the files use the `hydroseason-results` stem.
