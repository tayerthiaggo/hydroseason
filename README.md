# HydroSeason

**Data-driven hydrological season and year delineation from monthly time series.**

HydroSeason is a pure-Python package that turns a raw monthly time series (rainfall, discharge, or any seasonally-varying variable) into labelled hydrological seasons (**Wet / Dry**, or **Unclassified** for non-seasonal records) and **hydrological years**, with diagnostics, metrics, and optional ERA5 data fetching.

It was developed to support Tayer et al. (2026) — an automated classification framework for tropical river regimes — and is designed to be reproducible, config-driven, and easy to embed in existing workflows.

---

## Table of Contents

1. [Key Features](#key-features)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
   - [Python API](#python-api)
   - [Pandas Accessor](#pandas-accessor)
   - [CLI](#cli)
   - [YAML Config](#yaml-config)
4. [Algorithm Overview](#algorithm-overview)
5. [Output Schema](#output-schema)
6. [Metrics & Derived Products](#metrics--derived-products)
7. [Seasonality Detection](#seasonality-detection)
8. [Configuration Reference](#configuration-reference)
9. [ERA5 Fetch (optional)](#era5-fetch-optional)
10. [Notebooks](#notebooks)
11. [Citation](#citation)
12. [License](#license)

---

## Key Features

| Capability | Details |
|---|---|
| **Regime detection** | STL decomposition + Walsh-Lawler Seasonality Index (SI override) |
| **Season labelling** | Wet / Dry classification using circular climatology or KMeans |
| **Hydrological years** | Fixed and dynamic (onset-anchored); ending-year convention |
| **End-of-dry metrics** | Terminal-minimum anchor for robust end-of-dry-season averaging |
| **Zero-flow counting** | Per-year below-threshold month count |
| **Config-file workflow** | Full pipeline via a single YAML file |
| **Pandas accessor** | `df.hydroseason.classify()` one-liner |
| **CLI** | `hydroseason run --config config.yaml` |
| **ERA5 fetch** | Optional monthly precipitation from Google Cloud ERA5 Zarr |
| **Plotting** | Season timelines, climatology, STL decomposition, annual metrics dashboard |

---

## Installation

**Requirements:** Python >= 3.10

```bash
# Core (no ERA5 fetch, no plotting)
pip install hydroseason

# With plotting support
pip install hydroseason[plot]

# With ERA5 fetch support (requires geopandas, xarray, rasterio)
pip install hydroseason[fetch]

# Full development install
git clone https://github.com/tayerthiaggo/hydroseason.git
cd hydroseason
pip install -e ".[plot,fetch,dev]"
```

---

## Quick Start

### Python API

```python
import pandas as pd
from hydroseason import delineate_monthly_dataframe

df = pd.read_csv("monthly_rainfall.csv")

# Required columns: Date, Year, Month, and a value column (e.g. Rainfall_mm)
artifacts = delineate_monthly_dataframe(df)

# Main labelled result
result = artifacts.result         # DataFrame with SeasonType, Hydro_Year ...
diag   = artifacts.diagnostics   # STL strength, Walsh-Lawler SI, regime ...

print(result[["Date", "SeasonType", "Hydro_Year"]].head())
```

Output:

```
        Date SeasonType  Hydro_Year
0 1986-12-01        Wet        1987
1 1987-01-01        Wet        1987
2 1987-02-01        Wet        1987
3 1987-03-01        Wet        1987
4 1987-04-01        Wet        1987
```

#### Opt out of the SI override (STL only)

```python
artifacts = delineate_monthly_dataframe(df, rainfall_si_override=False)
```

### Pandas Accessor

Import the package once to register the accessor on every DataFrame:

```python
import hydroseason                               # registers df.hydroseason accessor
import pandas as pd

df = pd.read_csv("monthly_rainfall.csv")

result      = df.hydroseason.classify()          # -> labelled DataFrame
artifacts   = df.hydroseason.delineate()         # -> PipelineArtifacts namedtuple
diag        = df.hydroseason.diagnostics()       # -> DiagnosticsReport
fig_tl      = df.hydroseason.plot_timeline()     # -> Plotly Figure
fig_db      = df.hydroseason.plot_dashboard()    # -> Plotly Figure
```

### CLI

```bash
# Run from a YAML configuration file
hydroseason run --config config/example.yaml

# Run on the bundled fixture dataset
hydroseason demo --out output/demo.csv

# Fetch monthly ERA5 rainfall for a catchment polygon
hydroseason fetch \
        --path    gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3 \
        --vector  catchment.shp \
    --start-year 1985 \
    --end-year   2023 \
    --variable   rainfall \
    --output  monthly_rainfall.csv
```

### YAML Config

```yaml
# config/example.yaml
input:
  # Gilbert River (QLD, Australia) — bundled example dataset
  csv_path: data/DATASET.csv
  date_col: Date
  year_col: Year
  month_col: Month
  value_col: Rainfall_mm

output:
  output_csv: output/hydroseason_results.csv

algorithm:
        smooth_window: 3
  firstpass_quantile: 0.20
  secondpass_quantile: 0.10
  long_period_threshold: 16
  onset_window_months: 1       # restrict new-year onsets to +/- 1 month of anchor
  rainfall_si_override: true   # default; set false for STL-only regime
  rainfall_si_threshold: 0.80
```

```bash
hydroseason run --config config/example.yaml
```

---

## Algorithm Overview

The pipeline runs in five stages:

```
Monthly time series
        |
        v
+-------------------------------------+
|  1. Validation & gap interpolation  |
+-------------------------------------+
        |
        v
+-----------------------------------------------------------------+
|  2. Regime detection                                            |
|     * STL decomposition -> seasonality strength F_S            |
|     * Walsh-Lawler Seasonality Index (SI)                       |
|     * If F_S >= 0.30 AND SI >= 0.80 -> promote to "seasonal"   |
|       (handles skewed rainfall distributions)                   |
|     * Regime: seasonal | borderline | non_seasonal              |
+-----------------------------------------------------------------+
        |
        +--- seasonal / borderline -------------------------+
        |                                                   |
        v                                                   v
+---------------------+                       +------------------------+
|  3. Fixed season    |                       |  Monthly climatology   |
|     Circular        |                       |  (borderline fallback) |
|     climatology or  |                       +------------------------+
|     KMeans          |
|     -> start month  |
|     -> fixed HY     |
+---------------------+
        |
        v
+------------------------------------------------------------------+
|  4. Dynamic season (seasonal only)                               |
|     * Smooth harmonic envelope                                   |
|     * Segment main Wet core                                      |
|     * Refine wet-season tails                                    |
|     * Assign dynamic hydrological years (onset-window filtered)  |
+------------------------------------------------------------------+
        |
        v
+-----------------------------------------------------------------+
|  5. Metrics                                                     |
|     * Season-level summaries (total, mean, duration, ...)       |
|     * End-of-dry season state (terminal-minimum anchor)         |
|     * Zero-flow month counts                                    |
+-----------------------------------------------------------------+
        |
        v
  PipelineArtifacts (result, diagnostics, fixed_monthly, ...)
```

### Regime thresholds

| F_S (STL strength) | SI (Walsh-Lawler) | Regime |
|---|---|---|
| >= 0.60 | any | `seasonal` |
| 0.30 – 0.59 | >= 0.80 | `seasonal` (SI override) |
| 0.30 – 0.59 | < 0.80 | `borderline` |
| < 0.30 | any | `non_seasonal` |

The `regime_source` field in `DiagnosticsReport` records whether the final regime came from STL alone (`"stl"`) or was promoted by the SI (`"rainfall_si_override"`).

### Hydrological year convention

HydroSeason uses the **ending-year convention** throughout: a hydrological year that spans Dec 1986 – Nov 1987 is labelled **HY 1987**.

The `onset_window_months` parameter (default 1) prevents mid-year wet pulses from triggering spurious new hydrological years: only Wet-season onsets within +/- 1 month of the climatological start month are accepted as valid year boundaries.

---

## Output Schema

### `artifacts.result` — main labelled DataFrame

| Column | Type | Description |
|---|---|---|
| `Date` | datetime | First day of the month |
| `Year` | int | Calendar year |
| `Month` | int | Calendar month (1–12) |
| `Rainfall_mm` | float | Input value (column name preserved) |
| `SeasonType` | str | `Wet`, `Dry`, or `Unclassified` for non-seasonal records |
| `SeasonShift` | bool | `True` where the season label changes from the previous row |
| `Hydro_Year` | int | Hydrological year (ending-year convention) |
| `Hydro_Year_fixed` | int | Baseline hydrological year from the fixed climatological start month |
| `Seasonality_SI` | float | Walsh-Lawler Seasonality Index copied onto each row |
| `Seasonality_STL` | float | STL seasonality strength copied onto each row |
| `Seasonality_Regime` | str | Final detected regime copied onto each row |
| `dry_total`, `wet_total` | float | Annual dry/wet season totals when metrics can be computed |
| `dry_month_count`, `wet_month_count` | int | Annual dry/wet month counts when metrics can be computed |

### `artifacts.diagnostics` — `DiagnosticsReport`

| Field | Description |
|---|---|
| `stl_strength` | STL seasonality strength F_S in [0, 1] |
| `walsh_lawler_si` | Walsh-Lawler Seasonality Index |
| `regime` | `seasonal`, `borderline`, or `non_seasonal` |
| `regime_source` | `stl` or `rainfall_si_override` |
| `rainfall_si_override` | Whether the SI override was active |
| `hydro_year_start_month` | Anchor month for the hydrological year (1–12) |
| `validation_warnings` | List of data-quality warnings |

### `artifacts.fixed_monthly` — monthly climatology table

Pivot table of mean values by month and season label, used internally for the fixed season boundary step.

### `artifacts.wet_boundaries` — per-year wet-season boundaries

| Column | Description |
|---|---|
| `Hydro_Year` | Year |
| `WetStart` | First Wet month date |
| `WetEnd` | Last Wet month date |
| `wet_duration_months` | Length of Wet season |

---

## Metrics & Derived Products

### Season-level metrics

```python
from hydroseason import compute_season_metrics

metrics = compute_season_metrics(result)
# Returns a per-(Hydro_Year, SeasonType) DataFrame with
# total, mean, max, min, duration_months for the value column
```

### End-of-dry-season state

The end-of-dry rule avoids the naive "last N Dry rows" approach, which fails when the terminal Dry month has already rebounded (e.g. brief rainfall before the true annual minimum). Instead it walks backward from the final Dry row while the anchor variable is *increasing*, stops at the local minimum, and averages the last `n` rows ending there.

```python
from hydroseason import compute_end_dry_metrics

end_dry = compute_end_dry_metrics(
    df,
    metric_cols=["wet_area_ha", "npools", "AWMPA"],
    anchor="terminal_minimum",    # robust end-of-dry anchor
    anchor_col="wet_area_ha",     # variable that should be at minimum at dry-season end
    last_n=2,                     # average last 2 months at minimum
    suffix="_endDry",
)
```

### Zero-flow months

```python
from hydroseason import compute_zero_flow_months

zf = compute_zero_flow_months(
    df,
    discharge_col="Discharge",
    threshold=1.0,       # m3/s; counts months <= threshold
)
```

---

## Seasonality Detection

HydroSeason uses a two-stage approach to classify the seasonal regime before delineating seasons:

### Stage 1 — STL Seasonality Strength

STL (Seasonal-Trend decomposition using Loess) decomposes the time series into Trend + Seasonal + Remainder components. The strength metric is:

$$F_S = \max\!\left(0,\; 1 - \frac{\mathrm{Var}(R)}{\mathrm{Var}(R + S)}\right)$$

where $R$ is the Remainder and $S$ is the Seasonal component. $F_S$ close to 1 indicates the seasonal component explains most of the variance.

### Stage 2 — Walsh-Lawler Seasonality Index (override)

Raw monthly rainfall is highly right-skewed: a few extreme wet-season months inflate the STL Remainder variance, pushing $F_S$ below the 0.60 threshold even for strongly monsoonal catchments. The Walsh-Lawler SI provides an independent, distribution-free check:

$$\mathrm{SI} = \frac{1}{\bar{R}} \sum_{i=1}^{12} \left| r_i - \frac{\bar{R}}{12} \cdot i \right|$$

A catchment with all rain in one month gives SI = 1.833; perfectly uniform gives SI = 0. **SI >= 0.80 is considered strongly seasonal.**

When STL returns `borderline` (F_S >= 0.30) and SI >= 0.80, the regime is promoted to `seasonal`. Non-seasonal results (F_S < 0.30) are never promoted. Set `rainfall_si_override=False` to use STL alone.

---

## Configuration Reference

All parameters can be set either in the `delineate_monthly_dataframe()` call or via the YAML config file under the `algorithm:` key.

| Parameter | Default | Description |
|---|---|---|
| `smooth_window` | `3` | Centred rolling window (months) for zero-preserving smoothing |
| `firstpass_quantile` | `0.20` | Quantile threshold for first-pass Wet/Dry boundary |
| `secondpass_quantile` | `0.10` | Quantile threshold for wet-tail refinement |
| `long_period_threshold` | `16` | Maximum gap between accepted Wet onsets before inserting a fallback year boundary |
| `fallback_month` | `None` | Override start month when circular stats are ambiguous |
| `method` | `"circular"` | Climatology method: `"circular"` (default) or `"kmeans"` |
| `onset_window_months` | `1` | Only accept Wet onsets within +/- N months of anchor month |
| `rainfall_si_override` | `True` | Enable Walsh-Lawler SI promotion of borderline STL results |
| `rainfall_si_threshold` | `0.80` | SI value above which borderline -> seasonal |
| `max_fraction_missing` | `0.10` | Maximum fraction of missing values before raising an error |
| `max_gap_to_interpolate` | `2` | Maximum consecutive missing months to interpolate |

---

## ERA5 Fetch (optional)

HydroSeason can download and aggregate monthly ERA5 precipitation (or other variables) from the Google Cloud public ERA5 Zarr archive for a catchment polygon:

```python
import geopandas as gpd
from hydroseason import get_monthly_variable

ERA5_ZARR = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
gdf = gpd.read_file("catchment.shp")

df = get_monthly_variable(
        path=ERA5_ZARR,
        gdf=gdf,
    start_year=1985,
    end_year=2023,
        variable="rainfall",      # rainfall, temperature, or evaporation
        cache_dir="data/era5_cache",
)

df.to_csv("monthly_rainfall.csv", index=False)
```

Requires the `[fetch]` extras: `pip install hydroseason[fetch]`.

---

## Notebooks

| Notebook | Description |
|---|---|
| [hydroseason_quickstart.ipynb](notebooks/hydroseason_quickstart.ipynb) | Short end-to-end workflow on the bundled example dataset |
| [hydroseason_era5_fetch_example.ipynb](notebooks/hydroseason_era5_fetch_example.ipynb) | ERA5 catchment rainfall fetch, delineation, plotting, and report export |
| [hydroseason_tayer2026_example.ipynb](tests/hydroseason_tayer2026_example.ipynb) | Advanced reproduction of Tayer et al. (2026) results, including diagnostics and end-of-dry morphology metrics |

---

## Citation

If you use HydroSeason in your research, please cite:

> Tayer, T.C., Hall, R.L. et al. (2026). *An automated framework for hydrological season and year delineation from monthly time series*. Journal of Hydrology. https://doi.org/10.1016/j.jhydrol.2025.XXXXXX

BibTeX:

```bibtex
@article{tayer2026hydroseason,
  title   = {An automated framework for hydrological season and year delineation from monthly time series},
  author  = {Tayer, Thiago C. and Hall, Robert Lester and others},
  journal = {Journal of Hydrology},
  year    = {2026},
  doi     = {10.1016/j.jhydrol.2025.XXXXXX}
}
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.
