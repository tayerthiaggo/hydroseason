[![Tests](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml/badge.svg)](https://github.com/tayerthiaggo/hydroseason/actions/workflows/test.yml)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://tayerthiaggo.github.io/hydroseason/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/tayerthiaggo/hydroseason/blob/main/LICENSE)
<!-- [![PyPI version](https://img.shields.io/pypi/v/hydroseason.svg)](https://pypi.org/project/hydroseason/)
[![Python versions](https://img.shields.io/pypi/pyversions/hydroseason.svg)](https://pypi.org/project/hydroseason/) -->

# HydroSeason

**Rainfall-based hydrological Wet/Dry season and hydrological-year delineation.**

HydroSeason turns monthly rainfall records into labelled Wet/Dry seasons,
hydrological years, rainfall metrics, diagnostics, plots, and self-contained HTML
reports. The package builds upon the rainfall-based hydrological-season workflow
introduced in Tayer et al. (2026) and extends it as a reusable Python API,
pandas accessor, YAML-driven CLI, local rainfall reader, and ERA5/SILO AOI
rainfall-fetch workflow.

HydroSeason is designed for hydrological, ecological, climatological and
remote-sensing workflows where calendar years do not adequately represent
wet/dry seasonal dynamics.

Full documentation: https://tayerthiaggo.github.io/hydroseason/

[![HydroSeason example report preview](https://tayerthiaggo.github.io/hydroseason/assets/images/hydroseason-report-preview.png)](https://tayerthiaggo.github.io/hydroseason/report/)

## Install

Install the core rainfall-classification workflow:
```bash
pip install hydroseason
```
Install plotting and HTML report generation support:
```bash
pip install "hydroseason[report]"
```
Install ERA5/SILO rainfall fetching and geospatial support:
```bash
pip install "hydroseason[fetch]"
```
Install all user-facing functionality:
```bash
pip install "hydroseason[all]"
```
For local development from this repository:
```bash
pip install -e ".[dev,docs,all]"
```
Verify the installation:
```bash
hydroseason --version
hydroseason demo --out output/demo.csv
```
Once available on conda-forge:

```bash
conda install -c conda-forge hydroseason
```

The core installation supports rainfall validation, hydrological-season
classification, hydrological-year assignment, diagnostics, metrics, local
rainfall readers, and the command-line interface. Plotting/reporting and
AOI-based rainfall fetching are available through optional dependency groups.

## Supported rainfall inputs

HydroSeason supports:

- tidy monthly CSV files with `Date`, `Year`, `Month`, and `Rainfall_mm`;
- Bureau of Meteorology monthly rainfall exports;
- SILO rainfall files;
- AOI-averaged monthly rainfall fetched from SILO or ERA5.

## Quick Example

```python
import pandas as pd
from hydroseason import classify_rainfall

df = pd.read_csv("data/monthly_rainfall.csv")
artifacts = classify_rainfall(df)

result = artifacts.result
print(result[["Date", "SeasonType", "Hydro_Year"]].head())
print(artifacts.diagnostics.regime)
```
Input data should contain monthly `Date`, `Year`, `Month`, and `Rainfall_mm`
columns.

### Generate an interactive HTML report

Install reporting support:
```bash
pip install "hydroseason[report]"
```
```python
from hydroseason import generate_html_report

generate_html_report(artifacts, "output/hydroseason_report.html")
```

### Pandas accessor

Importing `hydroseason` registers a `.hydroseason` accessor on every DataFrame,
so you can run the same workflow inline:

```python
import hydroseason  # registers df.hydroseason
import pandas as pd

df = pd.read_csv("data/monthly_rainfall.csv")
result = df.hydroseason.classify_rainfall_df()  # labelled DataFrame
artifacts = df.hydroseason.classify_rainfall()   # full PipelineArtifacts
# Requires: pip install "hydroseason[report]"
fig = df.hydroseason.plot_dashboard()           # interactive Plotly figure
```

### Try it instantly

No data of your own yet? Run the bundled demo dataset:

```bash
hydroseason demo --out output/demo.csv
```


## Command Line

```bash
hydroseason demo --out output/demo.csv
hydroseason rainfall --input data/monthly_rainfall.csv --source csv --output output/rainfall_results.csv
hydroseason run --config config/example.yaml
```

HydroSeason can also read common Australian rainfall formats and fetch
AOI-averaged monthly rainfall from SILO or ERA5.

## Documentation

- Quick start: https://tayerthiaggo.github.io/hydroseason/quickstart/
- Algorithm: https://tayerthiaggo.github.io/hydroseason/algorithm/
- Configuration: https://tayerthiaggo.github.io/hydroseason/configuration/
- Outputs and metrics: https://tayerthiaggo.github.io/hydroseason/outputs/
- Rainfall fetch: https://tayerthiaggo.github.io/hydroseason/era5/
- Example report: https://tayerthiaggo.github.io/hydroseason/report/
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

The software implementation has subsequently been extended and maintained as HydroSeason. If you use HydroSeason in an analysis, please cite both the methodological paper above and the specific software release used.

## Software citation

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
