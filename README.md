[![Tests](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml/badge.svg)](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://tayerthiaggo.github.io/hydroseason/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/tayerthiaggo/hydroseason/blob/main/LICENSE)
<!-- [![PyPI version](https://img.shields.io/pypi/v/hydroseason.svg)](https://pypi.org/project/hydroseason/)
[![Python versions](https://img.shields.io/pypi/pyversions/hydroseason.svg)](https://pypi.org/project/hydroseason/) -->

# HydroSeason

**Hydrological seasons do not always follow the calendar.**

HydroSeason helps you turn rainfall records into Wet/Dry seasons,
hydrological years, rainfall metrics, diagnostics, plots, and a self-contained
HTML report. Bring your own monthly rainfall table, or provide a catchment or
area-of-interest polygon and let HydroSeason fetch monthly rainfall for you
from SILO, CHIRPS, or ERA5.

It is built for hydrology, ecology, climate, environmental-flow, and
remote-sensing workflows where fixed calendar years can hide what the rainfall
season is actually doing.

Full documentation: https://tayerthiaggo.github.io/hydroseason/

[![HydroSeason example report preview](docs/assets/images/hydroseason-report-preview.png)](https://tayerthiaggo.github.io/hydroseason/report/)

## Why HydroSeason?

Many analyses start with a fixed rule: January to December, or the same
wet/dry months every year. That is convenient, but it can split one wet season
across two reporting years, miss early or late shoulder months, and change
annual rainfall or dry-season interpretation.

HydroSeason uses the rainfall record itself to find Wet/Dry timing and assign
hydrological years. It also reports season onsets, data-quality notes, and
method diagnostics so the decision is inspectable.

| Common static approach | HydroSeason |
| --- | --- |
| Uses calendar years or one fixed water-year start | Assigns hydrological years from rainfall season timing |
| Assumes Wet/Dry months are fixed | Refines Wet/Dry labels year by year |
| Can split one wet season across two reporting years | Keeps rainfall grouped by hydrological season |
| Requires rainfall data to be prepared separately | Can fetch area-averaged rainfall from a polygon |
| Gives limited method diagnostics | Exports thresholds, confidence notes, plots, and a report |

![Static calendar seasons compared with HydroSeason dynamic hydrological years](docs/assets/images/static-vs-hydroseason.png)

The top panel uses one fixed climatology-derived Wet/Dry template and one fixed
hydrological-year start. The bottom panel lets the rainfall record decide
where wet/dry seasons and hydrological years begin.

This matters when a few shifted shoulder months change wet-season totals,
dry-season length, annual classifications, or ecological interpretation.

## Start Quickly

Install the core workflow, including interactive Plotly plots and HTML reports:

```bash
pip install hydroseason
```

Run the bundled demo:

```bash
hydroseason demo --out output/demo.csv
```

Or classify your own monthly rainfall table:

```python
import pandas as pd
from hydroseason import classify_rainfall, generate_html_report

df = pd.read_csv("data/monthly_rainfall.csv")
artifacts = classify_rainfall(df)

print(artifacts.result[["Date", "SeasonType", "Hydro_Year"]].head())
print(artifacts.diagnostics.regime)

generate_html_report(artifacts, "output/hydroseason_report.html")
```

Input rainfall tables should contain monthly `Date`, `Year`, `Month`, and
`Rainfall_mm` columns.

## No Rainfall Table Yet?

If you have a catchment or area-of-interest polygon, HydroSeason can fetch
monthly rainfall averaged over that area.

```bash
pip install "hydroseason[fetch]"
```

In a notebook, load your polygon and fetch monthly rainfall before running the
same season workflow:

```python
from hydroseason import (
    classify_rainfall,
    generate_html_report,
    get_monthly_aoi_rainfall,
    get_monthly_silo_rainfall,
    load_vector,
)

gdf = load_vector("catchment.geojson")

monthly = get_monthly_silo_rainfall(
    gdf,
    start_year=1985,
    end_year=2023,
    cache_dir="data/silo_cache",
)

artifacts = classify_rainfall(monthly)
generate_html_report(artifacts, "output/hydroseason_report.html")
```

For the fastest default, use the AOI wrapper. It keeps SILO as the Australian
default, uses CHIRPS v3 monthly rainfall elsewhere, and keeps the public ERA5
Zarr store under the hood for explicit ERA5 runs or fallback coverage:

```python
from hydroseason import classify_rainfall, get_monthly_aoi_rainfall, load_vector

gdf = load_vector("catchment.geojson")

monthly = get_monthly_aoi_rainfall(
    gdf=gdf,
    start_year=1985,
    end_year=2023,
    source="auto",          # SILO in Australia, CHIRPS elsewhere
    cache_dir="data/fetch_cache",
)

artifacts = classify_rainfall(monthly)
```

## Incomplete Rainfall Data?

No worries. HydroSeason can apply rainfall data imputation during validation,
fill supported missing monthly values, and keep track of what was changed.
The diagnostics tell you how many values were imputed, which gaps were too long
to fill automatically, and how missing data affects confidence in the result.
Negative rainfall values are clipped to 0.0 with a validation warning. Annual
SPI classes use the sample standard deviation of hydrological-year rainfall
totals, matching the short-record empirical workflow.

## What You Get

HydroSeason returns a `PipelineArtifacts` object and can export:

- a labelled monthly table with `SeasonType` and `Hydro_Year`;
- Wet/Dry rainfall totals and month counts by hydrological year;
- seasonality diagnostics, thresholds, validation warnings, and confidence notes;
- interactive Plotly figures;
- a self-contained HTML report that can be opened without Python.

Importing `hydroseason` also registers a pandas accessor:

```python
import hydroseason
import pandas as pd

df = pd.read_csv("data/monthly_rainfall.csv")
result = df.hydroseason.classify_rainfall_df()
artifacts = df.hydroseason.classify_rainfall()
fig = df.hydroseason.plot_dashboard()
```

## Supported Rainfall Inputs

HydroSeason supports:

- tidy monthly CSV files with `Date`, `Year`, `Month`, and `Rainfall_mm`;
- Bureau of Meteorology (BoM Australia) monthly rainfall exports;
- SILO point rainfall files and gridded polygon rainfall for Australia;
- CHIRPS-first global polygon rainfall, with ERA5 available as backup or exact mode.

AOI wrapper and CLI fetches include `Data_Source`, `Data_Product`, and
`Fetch_Note` columns. If a request mixes CHIRPS, ERA5, or SILO, keep that
metadata with the analysis and consider sensitivity checks near source
transitions.

## Command Line

```bash
hydroseason demo --out output/demo.csv

hydroseason rainfall \
  --input data/monthly_rainfall.csv \
  --source csv \
  --output output/rainfall_results.csv

hydroseason fetch \
  --source auto \
  --vector catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --output output/monthly_rainfall.csv

hydroseason rainfall \
  --input output/monthly_rainfall.csv \
  --source csv \
  --output output/fetched_results.csv

hydroseason run --config config/example.yaml
```

## Documentation

- Quick start: https://tayerthiaggo.github.io/hydroseason/quickstart/
- Rainfall fetch: https://tayerthiaggo.github.io/hydroseason/era5/
- Example report: https://tayerthiaggo.github.io/hydroseason/report/
- Algorithm: https://tayerthiaggo.github.io/hydroseason/algorithm/
- Configuration: https://tayerthiaggo.github.io/hydroseason/configuration/
- Outputs and metrics: https://tayerthiaggo.github.io/hydroseason/outputs/
- API reference: https://tayerthiaggo.github.io/hydroseason/api/

## Development

```bash
git clone https://github.com/tayerthiaggo/hydroseason.git
cd hydroseason
pip install -e ".[dev,docs,all]"
python -m pytest -q
python scripts/stress_test.py --cases 100 --seed 42
```

## Citation

HydroSeason builds upon the rainfall-based hydrological-season workflow presented in:

> Tayer, T.C. et al. (2026). *Mapping resilience: A framework for analysing surface-water dynamics and persistent pools in non-perennial rivers using remote sensing, rainfall and river discharge data* Journal of Hydrology, 666, p. 134750. Available at: https://doi.org/10.1016/j.jhydrol.2025.134750.

The software implementation has subsequently been extended and maintained as
HydroSeason. If you use HydroSeason in an analysis, please cite both the
methodological paper above and the specific software release used.

## Software Citation

A versioned software DOI will be minted through Zenodo when the first public
GitHub release is archived. After publication, please cite the specific
HydroSeason software release used in your analysis.

```bibtex
@article{tayer2026mapping,
  author  = {Tayer, Thiaggo C. and Beesley, Leah S. and Stewart-Koster, Ben and Bond, Nick and Douglas, Michael M. and Rossi, Maria J. and McGregor, Glenn B. and Marshall, Jonathan C.},
  title   = {Mapping resilience: A framework for analysing surface-water dynamics and persistent pools in non-perennial rivers using remote sensing, rainfall and river discharge data},
  journal = {Journal of Hydrology},
  volume  = {666},
  pages   = {134750},
  year    = {2026},
  doi     = {10.1016/j.jhydrol.2025.134750}
}
```

## License

MIT License - see [LICENSE](https://github.com/tayerthiaggo/hydroseason/blob/main/LICENSE) for details.
