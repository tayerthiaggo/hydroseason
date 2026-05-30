# Quick Start

HydroSeason expects a monthly rainfall DataFrame with `Date`, `Year`, `Month`, and `Rainfall_mm` columns.

## Python API

```python
import pandas as pd
from hydroseason import classify_rainfall, generate_html_report

df = pd.read_csv("data/DATASET.csv")
artifacts = classify_rainfall(df)

result = artifacts.result
diagnostics = artifacts.diagnostics

print(result[["Date", "SeasonType", "Hydro_Year"]].head())
print(diagnostics.regime)

generate_html_report(artifacts, "output/hydroseason_report.html")
```

Disable the Walsh-Lawler promotion and use STL thresholds only:

```python
artifacts = classify_rainfall(df, rainfall_si_override=False)
```

Read common rainfall files and run in one step:

```python
from hydroseason import read_rainfall, classify_rainfall_from_file

monthly = read_rainfall("IDCJAC0001_003018_Data1.csv", source="auto")
artifacts = classify_rainfall_from_file("IDCJAC0001_003018_Data1.csv", source="auto")
```

## Pandas Accessor

Importing `hydroseason` registers `df.hydroseason` on pandas DataFrames.

```python
import hydroseason
import pandas as pd

df = pd.read_csv("data/DATASET.csv")

result = df.hydroseason.classify_rainfall_df()
artifacts = df.hydroseason.classify_rainfall()
diagnostics = df.hydroseason.diagnostics()

fig = df.hydroseason.plot_dashboard()
summary = df.hydroseason.display_summary()
report_path = df.hydroseason.generate_report("output/report.html")
```

## CLI

Run the pipeline from a YAML configuration file:

```bash
hydroseason run --config config/example.yaml
```

Run the packaged demo dataset:

```bash
hydroseason demo --out output/demo.csv
```

Run local rainfall files without writing Python:

```bash
hydroseason rainfall \
  --input IDCJAC0001_003018_Data1.csv \
  --source auto \
  --output output/rainfall_results.csv
```

Fetch monthly rainfall for an AOI polygon. Supported vector inputs include GeoJSON, SHP, KML, KMZ, GPKG, and GPCK.

SILO monthly rainfall for Australia:

```bash
hydroseason fetch \
  --source silo \
  --vector data/fitzroy_catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --cache-dir data/silo_cache \
  --output output/silo_monthly_rainfall.csv
```

ERA5 rainfall for global AOIs:

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

## YAML Config

```yaml
input:
  csv_path: data/DATASET.csv
  date_col: Date
  year_col: Year
  month_col: Month
  value_col: Rainfall_mm

output:
  output_csv: output/hydroseason_results.csv

algorithm:
  # Adaptive by default; set explicit values only for locked reproduction.
  firstpass_quantile: 0.2
  secondpass_quantile: 0.1
  long_period_threshold: 16
  smooth_window: null
  min_core_length: null
  onset_window_months: auto
  rainfall_si_override: true
  rainfall_si_threshold: 0.8
  shoulder_climatology_alpha: 0.10
  core_climatology_alpha: 0.05
  shoulder_residual_quantile: 0.95

validation:
  max_fraction_missing: 0.1
  max_gap_to_interpolate: 2
  max_consecutive_imputation_gap: 12
  raise_on_error: true
```

The HTML report and export bundle write interactive HTML plus CSV/JSON outputs by default. Static PNG exports are opt-in via `export_bundle(..., export_png=True)` because Kaleido/Chrome startup can be slow in notebook and CI environments.