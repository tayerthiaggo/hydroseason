# API Reference

Public symbols re-exported from `hydroseason` (and a handful of
submodule-only helpers from `hydroseason.io`). Internals (`hydroseason._*`
module contents not listed below) are not part of the stable public API
surface.

Most users need exactly one entry point:

```python
from hydroseason import run_hydroseason
```

Everything below is organized by task. Full signatures, parameters, and
return types are on each linked page.

## At a glance

| Symbol | Purpose | Page |
|---|---|---|
| `run_hydroseason` | One-call orchestrator: resolve water input, analyze, optional rainfall, write report | [Workflow](workflow.md) |
| `HydroSeasonRunResult` | Everything a `run_hydroseason` call produced | [Workflow](workflow.md) |
| `load_extent_csv` | Read a monthly extent CSV into date-indexed form | [Loading Data](io.md) |
| `load_aoi` | Load and validate an AOI (vector path or GeoDataFrame) | [Loading Data](io.md) |
| `load_monthly_masks` | Load AOI-clipped raster masks from a directory | [Loading Data](io.md) |
| `load_monthly_masks_zarr` | Open an already-canonical Zarr mask cube lazily | [Loading Data](io.md) |
| `load_wofs_from_stac` | Load DEA WOfS from STAC directly, compose monthly, clip to AOI | [Loading Data](io.md) |
| `load_wofs_monthly_extent` | High-level DEA WOfS fetch, resumable by calendar year | [Loading Data](io.md) |
| `complete_monthly_axis` | Reindex a mask cube to a complete monthly axis | [Loading Data](io.md) |
| `open_wo_statistics` | Load native DEA Water Observation Statistics for an AOI | [Loading Data](io.md) |
| `HistoricalWaterMask` | The exact, immutable `(count_wet > 0) AND AOI` raster and its provenance | [Loading Data](io.md) |
| `build_historical_water_mask` | Build the exact historical water mask | [Loading Data](io.md) |
| `load_or_build_historical_water_mask` | Resolve a verified historical water mask, cache-first | [Loading Data](io.md) |
| `build_wet_planning_footprint` | Build a conservative coarse pruning footprint | [Loading Data](io.md) |
| `WetPlanningFootprint` | A prepared planning footprint's identity/geometry | [Loading Data](io.md) |
| `acquire_wofs_cache` | Fill or reuse a local WOfS Zarr cache store | [Loading Data](io.md) |
| `open_completed_mask_cache` | Lazily open a completed cache store's water-mask cube | [Loading Data](io.md) |
| `open_completed_dual_extent_counts` | Read back dual max/median-water pixel counts (`composite_bundle="hydrofragments_v1"`) | [Loading Data](io.md) |
| `verify_cache_footprints` | Verify a cache's persisted AOI/analysis footprints | [Loading Data](io.md) |
| `WOfSCacheHandle` | Pointer to a (possibly complete) on-disk WOfS cache store | [Loading Data](io.md) |
| `analyze_catchment` | Assess regime, then run the analysis that regime supports (routing authority) | [Analysis](analysis.md) |
| `CatchmentAnalysis` | Everything the record supports, plus how that was decided | [Analysis](analysis.md) |
| `assess_water_regime` | Assess what the observed surface-water record supports | [Analysis](analysis.md) |
| `WaterRegimeAssessment` | What the record supports, and what it does not | [Analysis](analysis.md) |
| `Regime` | Regime classification (`seasonal` / `marginal` / `aseasonal`) | [Analysis](analysis.md) |
| `extract_water_events` | Extract wet episodes and dry spells from a monthly record | [Analysis](analysis.md) |
| `WaterEventResult` | Wet episodes, dry spells, and record-level summaries | [Analysis](analysis.md) |
| `detect_hydrological_years` | Detect hydrological years from a quality-screened monthly series | [Analysis](analysis.md) |
| `label_hydrological_months` | Assign Wet/Dry and hydrological-year labels from detected boundaries | [Analysis](analysis.md) |
| `monthly_water_extent` | Summarise monthly canonical masks (invalid pixels never count as dry) | [Analysis](analysis.md) |
| `suggest_hydro_year_config` | Propose a `HydroYearConfig` from a monthly climatology | [Analysis](analysis.md) |
| `HydroYearConfig` | Wet/dry search windows, at any phase of the calendar year | [Analysis](analysis.md) |
| `analyze_hydrological_state` | Run the dynamic hydrological-year + phase pipeline | [Analysis](analysis.md) |
| `detect_dynamic_hydrological_years` | Robust-extrema trough/peak boundary detection | [Analysis](analysis.md) |
| `classify_seasonal_pattern` | Classify a record as seasonal / marginal / aseasonal | [Analysis](analysis.md) |
| `generate_catchment_report` | Write the self-contained HTML report plus the 4-CSV bundle | [Reporting](report.md) |
| `generate_html_report` | Compatibility API: render HTML from a supplied `hydro_years` DataFrame | [Reporting](report.md) |
| `CatchmentReportPaths` | Paths written by `generate_catchment_report` | [Reporting](report.md) |

## Pages

- **[Workflow](workflow.md)** — `run_hydroseason`, the one-call orchestrator.
- **[Loading Data](io.md)** — CSV/raster/Zarr loaders, DEA/STAC acquisition, historical water mask, planning footprints, cache surfaces.
- **[Analysis](analysis.md)** — Catchment routing, regime assessment, wet events, hydrological-year detection, dynamic hydrological state.
- **[Reporting](report.md)** — HTML report and CSV bundle generation.
