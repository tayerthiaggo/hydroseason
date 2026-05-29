# HydroSeason

**Rainfall-based hydrological wet/dry season and hydrological-year delineation.**

HydroSeason turns monthly rainfall records into hydrological Wet/Dry seasons and hydrological years. It validates and normalises rainfall data, detects rainfall seasonality, labels Wet/Dry periods when seasonality is present, assigns hydrological years using an ending-year convention, and returns diagnostics, metrics, plots, and optional HTML reports.

The package implements and extends the rainfall-based dynamic wet/dry period workflow described in the supplementary methodology for Tayer et al. (2026). It packages that research workflow as a reusable Python API, pandas accessor, YAML-driven CLI, local rainfall readers, and AOI rainfall fetch tools for ERA5 and SILO.

## About

HydroSeason is a research-focused Python package for reproducible monthly rainfall seasonality analysis. It is built for catchment-scale and site-scale rainfall records where Wet/Dry labels, hydrological-year boundaries, annual rainfall metrics, and diagnostics need to be consistent across notebooks, scripts, command-line workflows, and reports.

## Documentation

The full documentation now lives in `docs/` and can be published as a GitHub Pages site:

- [Quick Start](docs/quickstart.md)
- [Algorithm](docs/algorithm.md)
- [Configuration](docs/configuration.md)
- [Outputs & Metrics](docs/outputs.md)
- [Rainfall Fetch](docs/era5.md)
- [API Reference](docs/api.md)

When GitHub Pages is enabled for this repository, the site will be available at:

```text
https://tayerthiaggo.github.io/hydroseason/
```

Build it locally with:

```bash
pip install -e ".[docs]"
mkdocs serve
```

## Key Features

| Capability | Current support |
| --- | --- |
| Monthly rainfall validation | Coerces dates/year/month values, aggregates duplicate months, interpolates short gaps, and reports validation warnings. |
| Regime detection | STL seasonality strength with an optional Walsh-Lawler Seasonality Index promotion for strongly seasonal rainfall. |
| Fixed baseline seasons | Circular climatology by default, with the older k-means baseline still available through `method="kmeans"`. |
| Dynamic Wet/Dry labelling | Smooths rainfall while preserving zero months, segments the main wet-season core, and refines wet-season tails. |
| Hydrological years | Produces fixed and dynamic hydrological years using the ending-year convention. |
| Metrics | Adds annual rainfall totals, wet/dry month counts, dry-season rain-event counts, SPI classes, and end-of-dry metrics. |
| Reporting | Plotly figures, notebook summary cards, and self-contained HTML reports. |
| Workflows | Python API, pandas accessor, YAML config, command-line interface, local BoM/SILO readers, and ERA5/SILO AOI rainfall fetch. |

## Installation

```bash
pip install hydroseason
```

The standard install includes the core pipeline, plotting/reporting, local rainfall readers, and ERA5/SILO AOI rainfall fetch support.

For local development:

```bash
git clone https://github.com/tayerthiaggo/hydroseason.git
cd hydroseason
pip install -e ".[dev,docs]"
```

## Quick Start

```python
import pandas as pd
from hydroseason import delineate_monthly_dataframe, generate_html_report

df = pd.read_csv("data/DATASET.csv")
artifacts = delineate_monthly_dataframe(df)

result = artifacts.result
diagnostics = artifacts.diagnostics

print(result[["Date", "SeasonType", "Hydro_Year"]].head())
print(diagnostics.regime, diagnostics.hydro_year_start_month)

generate_html_report(artifacts, "output/hydroseason_report.html")
```

The input DataFrame needs monthly `Date`, `Year`, `Month`, and `Rainfall_mm` columns.

## Pandas Accessor

```python
import hydroseason
import pandas as pd

df = pd.read_csv("data/DATASET.csv")

result = df.hydroseason.classify()
artifacts = df.hydroseason.delineate()
summary = df.hydroseason.display_summary()
report_path = df.hydroseason.generate_report("output/report.html")
```

## Command Line

```bash
hydroseason run --config config/example.yaml
hydroseason demo --out output/demo.csv
hydroseason rainfall --input data/DATASET.csv --source csv --output output/rainfall_results.csv
```

The rainfall command can auto-detect common Australian formats:

```bash
hydroseason rainfall --input IDCJAC0001_003018_Data1.csv --source auto --output output/myroodah_results.csv
```

AOI rainfall fetch is included in the standard install. GeoJSON, SHP, KML, KMZ,
GPKG, and GPCK vector inputs are supported:

```bash
hydroseason fetch \
  --source era5 \
  --path gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3 \
  --vector data/fitzroy_catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --variable rainfall \
  --output output/monthly_rainfall.csv
```

SILO monthly rainfall polygon fetch (Australia):

```bash
hydroseason fetch \
  --source silo \
  --vector data/fitzroy_catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --output output/silo_monthly_rainfall.csv
```

## Notebooks

| Notebook | Description |
| --- | --- |
| [notebooks/hydroseason_quickstart.ipynb](notebooks/hydroseason_quickstart.ipynb) | End-to-end local workflow using the bundled example dataset. |
| [notebooks/hydroseason_rainfall_io_example.ipynb](notebooks/hydroseason_rainfall_io_example.ipynb) | Local rainfall ingestion examples for tidy CSV, BoM monthly rainfall CSV, and SILO point files. |
| [notebooks/hydroseason_aoi_fetch_example.ipynb](notebooks/hydroseason_aoi_fetch_example.ipynb) | AOI rainfall fetch examples for SILO and ERA5 using GeoJSON/SHP/KML/KMZ/GPKG/GPCK vectors. |
| [notebooks/hydroseason_era5_fetch_example.ipynb](notebooks/hydroseason_era5_fetch_example.ipynb) | ERA5 catchment rainfall fetch, delineation, plotting, and report export. |
| [tests/hydroseason_tayer2026_example.ipynb](tests/hydroseason_tayer2026_example.ipynb) | Advanced reproduction workflow for the Tayer et al. (2026) dataset and end-of-dry metrics. |

## Stress Testing

Run the unit tests, synthetic regime checks, notebook smoke path, and randomized rainfall stress harness before releases:

```bash
python -m pytest -q
python dev/_adaptive_sanity.py
python dev/_notebook_smoke.py quickstart
python scripts/stress_test.py --cases 100 --seed 42
```

The stress harness randomizes rainfall regimes, missing short gaps, duplicate months, zeros, and storm outliers, then checks pipeline invariants. Run the remote ERA5 smoke test separately when network access is available:

```bash
python dev/_notebook_smoke.py era5 --fetch
```

## Citation

If you use HydroSeason in research, cite the associated Tayer et al. manuscript when its final bibliographic details are available, and cite the software repository or release used for your analysis.

```bibtex
@software{tayer_hydroseason_2026,
  author = {Tayer, Thiaggo C.},
  title = {HydroSeason: Rainfall-based hydrological wet/dry season and hydrological-year delineation},
  year = {2026},
  url = {https://github.com/tayerthiaggo/hydroseason}
}
```

## License

MIT License - see [LICENSE](LICENSE) for details.
