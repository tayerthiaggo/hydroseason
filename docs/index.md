# HydroSeason

Hydrological-year detection and seasonal/aseasonal analysis from **monthly
satellite surface-water extent**, such as Digital Earth Australia Water
Observations.

HydroSeason tests whether a catchment floods and dries on a reliable annual
cycle. If it does, you get per-year boundaries and wet/dry phases. If it
doesn't, you get flood events and low-water spells instead of a forced
calendar.

!!! note "Scope"
    HydroSeason measures surface-water **extent**. It does not estimate
    discharge, depth, volume, or groundwater.

## What you get

[![HydroSeason report preview](assets/report-preview.png)](examples/fitzroy-river-wa.html)

One call writes a self-contained HTML report, four CSVs, and a run manifest.
Live examples:
[Fitzroy River](examples/fitzroy-river-wa.html) (seasonal) ·
[Lachlan River](examples/lachlan-river-nsw.html) (aseasonal) ·
[Fitzroy + rainfall context](examples/fitzroy-river-wa-rainfall.html).

## Install

```bash
pip install hydroseason              # CSV input (pandas + numpy only)
pip install "hydroseason[raster]"    # + NetCDF/Zarr/xarray input and SILO rainfall
pip install "hydroseason[stac]"      # + fetch DEA Water Observations directly
```

## Quickstart

```python
from hydroseason import run_hydroseason

result = run_hydroseason(
    "monthly_extent.csv",
    output_dir="output/report",
    aoi_name="My AOI",
)

print(f"Regime: {result.analysis.regime.regime}")
print(f"Route: {result.analysis.route}")
print(f"HTML: {result.artifacts.html}")
```

## Where next

| Page | Contents |
|---|---|
| [Usage Guide](guide.md) | The four ways to run `run_hydroseason`, batches, routing, data quality, DEA internals |
| [Methods Reference](methods.md) | The frozen `hydroseason-v0.2.0` method and its validation |
| [CLI Recipes](cli-recipes.md) | The same workflow from the command line: progress, logs, resuming, exit codes |
| [Preflight](preflight.md) | What an AOI's record can support, decided before acquisition |
| [Dynamic Hydrological State](hydrological-state.md) | Per-year boundaries, trough diagnostics, and phases |
| [Case Studies](case-studies/index.md) | Three reproducible studies across five Australian catchments |
| [Export Columns](report-columns.md) | Column dictionary for the four CSVs |
| [API Reference](api/index.md) | Every public function and class |
| [Citation](citation.md) | How to cite HydroSeason |
