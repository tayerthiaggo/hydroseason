# HydroSeason

Remote-sensing-first hydrological year detection and regime routing from **monthly surface-water extent**.

HydroSeason detects wet/dry timing, hydrological year boundaries, and inundation regimes in satellite-derived water-mask time series (such as Digital Earth Australia Water Observations).

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

## Input Paths

| Input Type | Entry Point | Required Extra |
|---|---|---|
| Monthly extent CSV | [`load_extent_csv`](guide.md#path-1-extent-csv) | Core only |
| Generic water-mask rasters / Zarr | [`load_monthly_masks`, `load_monthly_masks_zarr`](guide.md#path-2-generic-water-mask-rasters) | `[raster]` |
| Digital Earth Australia (DEA) STAC | [`open_wo_statistics`, `load_wofs_from_stac`, `load_wofs_monthly_extent`](guide.md#path-3-wofs-stac) | `[stac]` |

---

## Quickstart

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

## Navigation & Documentation

| Page | Contents |
|---|---|
| [User Guide](guide.md) | DEA acquisition options, pruning footprints, and reporting |
| [Hydrological State](hydrological-state.md) | Dynamic years, trough diagnostics, and phase models |
| [Case Studies Overview](case-studies/index.md) | Two reproducible studies across five catchments |
| [Main Workflow Study](case-studies/main-workflow.md) | Case Study 1 — Route-aware analysis across 5 catchments |
| [Resolution & Acquisition Evidence](case-studies/resolution-and-acquisition.md) | Case Study 2 — Resolution fidelity and pruning benchmarks |
| [Report Export Columns](report-columns.md) | CSV column dictionary for generated report bundles |
| [API Reference](api.md) | Public functions, classes, and exported entry points |
| [Citation](citation.md) | Software and paper citation details |
