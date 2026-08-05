# HydroSeason

[![Tests](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml/badge.svg)](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://tayerthiaggo.github.io/hydroseason/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://github.com/tayerthiaggo/hydroseason)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Remote-sensing-first hydrological year detection and regime routing from monthly surface-water extent.**

HydroSeason identifies wet/dry timing, hydrological year boundaries, and inundation regimes in satellite-derived water-mask time series (such as Digital Earth Australia Water Observations).

> [!NOTE]
> HydroSeason analyzes surface-water extent percentages. It does **not** estimate river discharge, channel depth, total water volume, or groundwater storage.

---

## Installation

```bash
pip install hydroseason              # Core: CSV detection & reports (pandas, numpy)
pip install "hydroseason[raster]"    # + xarray, rioxarray, rasterio, geopandas, dask, zarr
pip install "hydroseason[stac]"      # + pystac-client, odc-stac (DEA STAC acquisition)
pip install "hydroseason[all]"       # Complete raster + STAC dependencies
```

---

## Quickstart

Run the complete local workflow from a monthly extent CSV:

```python
from hydroseason import run_hydroseason

result = run_hydroseason(
    "monthly_extent.csv",
    output_dir="output/report",
    aoi_name="My AOI",
    analysis_options={"phase_model": "rule_based"},
)

print(f"Regime: {result.analysis.regime.regime}")
print(f"Route: {result.analysis.route}")
print(f"HTML: {result.artifacts.html}")
```

Or fetch both DEA WOfS water extent and ancillary SILO rainfall:

```python
result = run_hydroseason(
    output_dir="output/fitzroy",
    aoi="fitzroy.geojson",
    aoi_name="Fitzroy River",
    start_date="2005-01-01",
    end_date="2025-12-01",
    fetch_rainfall=True,
)
```

Rainfall is ancillary and non-fatal. It adds context to the monthly CSV and
HTML report, but never changes water-regime routing, hydrological-year
boundaries, phases, wet events, or low-extent spells.

---

## Route Interpretation

HydroSeason evaluates regime signal-to-noise ratio (SNR) and peak dispersion to assign one of two routes via `analyze_catchment`:

1. **`per_year_detection` (Seasonal Regimes):**
   - Applies when a reproducible annual seasonal cycle is present (SNR > 1.5).
   - Trough-to-trough hydrological years are anchored to robust climatological minima.
   - Outputs complete annual recharge/trough metrics (`<stem>_hydro_years.csv`).

2. **`event_characterisation` (Aseasonal Regimes):**
   - Applies to dryland, ephemeral, or irregular systems where forcing annual boundaries creates arbitrary partitions (SNR ≤ 1.5).
   - Prevents artificial hydrological year boundaries.
   - Characterizes discrete wet inundation events (`<stem>_wet_event.csv`) and low-water spells (`<stem>_low_spells.csv`). Per-AOI summaries are presented in HTML rather than duplicated as CSVs.

---

## Digital Earth Australia (DEA) Acquisition Options

The default high-level acquisition follows one fixed workflow:

`user AOI acquisition boundary -> cached DEA Multi-Year Statistics -> fixed unfiltered count_wet > 0 raster -> separate planning superset -> monthly WOfS -> percentage-based analysis -> four CSVs`

- **Historical scientific footprint**: `load_wofs_monthly_extent` queries or reuses one pinned `ga_ls_wo_fq_myear_3` artifact and applies `(count_wet > 0) AND user AOI` on the analysis grid for every month. It applies no frequency threshold, closing, buffer, or Calendar Year union.
- **Pinned provenance and coverage**: The verified mask manifest records the exact source version, item IDs, lineage, and coverage period. The source observed at design time was unfiltered and covered 1987--2025; the manifest values are authoritative. If `coverage_end` does not include the requested analysis end, acquisition fails closed instead of silently reverting to the full AOI.
- **Conservative planning superset**: A separate coarse/dilated derivative restricts remote reads for efficiency. It never becomes the scientific denominator.
- **Percentages and quality**: `n_aoi` is the fixed historical-mask pixel count. Pixels outside that mask are outside (`-2`), so their invalid observations do not affect `invalid_pct`. Classification and selected dates continue to use percentages; no area or km2 fields are produced.
- **Explicit compatibility mode**: `python scripts/extract_water_extent_csv.py --full-aoi` retains the legacy full-AOI denominator for diagnostics and benchmarking only. The default never falls back to it when Statistics or a verified offline mask is unavailable.
- **Composite Bundles (`composite_bundle`)**: Supports `legacy` (default single mask) and `hydrofragments_v1` (dual max/median water counts for downstream fragment analysis).

---

## Case Studies

HydroSeason includes two fully reproducible offline case studies using 2005–2025 DEA 30 m whole-catchment extent data across five Australian catchments (Daly, Fitzroy, Gilbert, Lachlan, Moonie):

1. **[Main Catchment Workflow](docs/case-studies/main-workflow.md)**: Demonstrates route-aware analysis and self-contained report bundles across seasonal monsoonal and aseasonal dryland basins.
2. **[Resolution and Acquisition Evidence](docs/case-studies/resolution-and-acquisition.md)**: Evaluates resolution coarsening (30 m vs 60 m/90 m/300 m), conservative pruning guarantees, and composite bundle semantics.

---

## Scientific Limitations

- **Extent is not Volume or Discharge**: Surface area percentage (`extent_pct`) dilutes narrow river channels and misses sub-canopy water.
- **Cloud Gaps**: High cloud/shadow invalid coverage (`invalid_pct`) distorts extent statistics if unflagged.
- **Resolution**: Coarsening spatial resolution distorts peak/trough timing and event boundaries. 30 m resolution remains authoritative.

---

## Public API Summary

```python
from hydroseason import (
    # Main workflow
    run_hydroseason, HydroSeasonRunResult,
    # Loaders & I/O
    load_extent_csv, load_aoi, load_monthly_masks, load_monthly_masks_zarr,
    load_wofs_from_stac, load_wofs_monthly_extent, complete_monthly_axis,
    # DEA & Cache Surfaces
    open_wo_statistics, HistoricalWaterMask, load_or_build_historical_water_mask,
    build_wet_planning_footprint, WetPlanningFootprint,
    acquire_wofs_cache, open_completed_mask_cache, open_completed_dual_extent_counts,
    verify_cache_footprints,
    # Regime & Catchment Analysis
    assess_water_regime, analyze_catchment, extract_water_events,
    # Hydrological State & Detection
    analyze_hydrological_state, detect_dynamic_hydrological_years,
    detect_hydrological_years, label_hydrological_months,
    # Report Generation
    generate_catchment_report, generate_html_report, CatchmentReportPaths,
)
```

Full API documentation: [docs/api.md](docs/api.md).

---

## Citation

If you use HydroSeason in your research, please cite `CITATION.cff` and:

```bibtex
@article{Tayer2026,
  author = {Tayer, Thiaggo C. and others},
  title = {Remote-Sensing-First Hydrological Year Detection from Surface Water Extent},
  journal = {Journal of Hydrology},
  year = {2026},
  doi = {10.1016/j.jhydrol.2025.134750}
}
```

---

## License

MIT License — see [LICENSE](LICENSE).
