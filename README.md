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

## Quickstart (CSV Input)

```python
from hydroseason import analyze_catchment, generate_catchment_report, load_extent_csv

# 1. Load monthly surface-water extent series (2005-2025)
extent = load_extent_csv(
    "monthly_extent.csv",
    date_col="date",
    value_col="extent_pct",
)

# 2. Automatic regime routing (seasonal vs aseasonal)
analysis = analyze_catchment(extent, phase_model="rule_based")
print(f"Regime: {analysis.regime.regime} | Route: {analysis.route}")

# 3. Generate self-contained HTML report and CSV bundle
paths = generate_catchment_report(
    extent,
    output_dir="output/report",
    name="my_catchment",
    analysis=analysis,
    title="My Catchment",
    subtitle="Monthly surface-water hydrological analysis",
)
print(f"HTML report written to: {paths.html}")
```

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
   - Characterizes discrete wet inundation events (`<stem>_events.csv`) and low-water spells (`<stem>_low_spells.csv`).

---

## Digital Earth Australia (DEA) Acquisition Options

When acquiring water masks directly from DEA STAC:

- **`open_wo_statistics`**: Queries lazy DEA Water Observations statistics and derives historical frequency.
- **Conservative Pruning (`planning_footprint` / `WetPlanningFootprint`)**: Restricts tile acquisition to an expanded, max-pooled planning mask for I/O efficiency without shrinking the full-AOI scientific denominator.
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
    # Loaders & I/O
    load_extent_csv, load_aoi, load_monthly_masks, load_monthly_masks_zarr,
    load_wofs_from_stac, load_wofs_monthly_extent, complete_monthly_axis,
    # DEA & Cache Surfaces
    open_wo_statistics, build_wet_planning_footprint, WetPlanningFootprint,
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
