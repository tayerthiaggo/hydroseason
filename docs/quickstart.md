# Quick Start

HydroSeason expects monthly rainfall DataFrame with `Date`, `Year`, `Month`, and `Rainfall_mm` columns.

!!! note "Data Sufficiency Requirements"
    Input must contain at least **24 months** of observations.

    Monthly series must be continuous. Missing months auto-filled using calendar-month climatological mean (WMO method) during validation, but runs exceeding `max_consecutive_imputation_gap` (default 12 months) or total missing fraction exceeding `max_fraction_missing` (default 10%) will fail validation.


## Python API

```python
import pandas as pd
from hydroseason import classify_rainfall

df = pd.read_csv("data/monthly_rainfall.csv")
artifacts = classify_rainfall(df)

result = artifacts.result
diagnostics = artifacts.diagnostics

print(result[["Date", "SeasonType", "Hydro_Year"]].head())
print(diagnostics.regime)
```

Disable Walsh-Lawler promotion, use STL thresholds only:

```python
artifacts = classify_rainfall(df, rainfall_si_override=False)
```

!!! note "Date-range sensitivity"
    HydroSeason recomputes climatology, adaptive parameters, and hydrological-year
    boundaries from supplied date range, so same site with different start/end date
    is not guaranteed to give identical season onsets.

    Edge years most sensitive. If subset starts/ends inside ongoing Wet season,
    true onset may lie outside visible window and first/last hydrological year can
    shift. Shorter records can also change behaviour because rolling guardrails fall
    back to full-record guardrails when fewer than two rolling windows available.

    Example bundled dataset:
    full record `1986-12` to `2023-10` and subset `2013-01` to `2023-10` give same
    monthly `SeasonType` labels and Wet onsets for hydrological years `2014`–`2023`,
    but subset reports hydrological year `2013` starting Wet in `Jan 2013` instead
    of `Nov 2012` because earlier onset is outside subset.

Read common rainfall files and run in one step:

```python
from hydroseason import read_rainfall, classify_rainfall_from_file

monthly = read_rainfall("IDCJAC0001_003018_Data1.csv", source="auto")
artifacts = classify_rainfall_from_file("IDCJAC0001_003018_Data1.csv", source="auto")
```

### Plotting and reports

Interactive reports included in default install.

```python
from hydroseason import generate_html_report

generate_html_report(artifacts, "output/hydroseason_report.html")
```

## Pandas Accessor

Importing `hydroseason` registers `df.hydroseason` on pandas DataFrames.

```python
import hydroseason
import pandas as pd

df = pd.read_csv("data/monthly_rainfall.csv")

result = df.hydroseason.classify_rainfall_df()
artifacts = df.hydroseason.classify_rainfall()
diagnostics = df.hydroseason.diagnostics()
```

Plotting and report accessors available in default install:

```python
fig = df.hydroseason.plot_dashboard()
summary = df.hydroseason.display_summary()
report_path = df.hydroseason.generate_report("output/report.html")
```

## CLI

Run pipeline from YAML config:

```bash
hydroseason run --config config/example.yaml
```

Run packaged demo dataset:

```bash
hydroseason demo --out output/demo.csv
```

Run local rainfall files without Python:

```bash
hydroseason rainfall \
  --input IDCJAC0001_003018_Data1.csv \
  --source auto \
  --output output/rainfall_results.csv
```

Fetch monthly rainfall for AOI polygon. Supported: GeoJSON, SHP, KML, KMZ, GPKG, GPCK.

> Requires: `pip install "hydroseason[fetch]"`

Recommended default for AOIs — uses SILO in Australia, CHIRPS globally, default ERA5 store as backup:

```bash
hydroseason fetch \
  --source auto \
  --vector data/fitzroy_catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --cache-dir data/fetch_cache \
  --output output/my_project/monthly_rainfall.csv
```

Force SILO for Australian AOI:

```bash
hydroseason fetch \
  --source silo \
  --vector data/fitzroy_catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --cache-dir data/silo_cache \
  --output output/silo_monthly_rainfall.csv
```

## YAML Config

```yaml
input:
  csv_path: data/monthly_rainfall.csv
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
  # Custom settings
  cap_rolling_tail_at_global: true
  keep_debug_columns: false
  require_low_floor_break_for_pruning: true

validation:
  max_fraction_missing: 0.1
  max_gap_to_interpolate: 2
  max_consecutive_imputation_gap: 12
  raise_on_error: true
```

HTML report and export bundle write interactive HTML plus CSV/JSON. Static PNG/SVG figure export planned for future release.
