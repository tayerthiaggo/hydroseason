# HydroSeason

HydroSeason is a Python package for delineating hydrological seasons and hydrological years from monthly environmental time series.

It is designed for rainfall-driven wet/dry systems but can be applied to other monthly variables when Wet/Dry labels and hydrological-year boundaries are meaningful. The core workflow validates monthly data, detects seasonality, builds a fixed seasonal baseline, refines dynamic wet-season boundaries, assigns hydrological years, and returns diagnostics and metrics that can be exported to CSV, JSON, Plotly figures, or a self-contained HTML report. HydroSeason can also read common Australian rainfall formats and fetch AOI-averaged rainfall from ERA5 or SILO.

## What HydroSeason Produces

The high-level API returns a `PipelineArtifacts` object with:

| Artifact | Meaning |
| --- | --- |
| `result` | The labelled monthly DataFrame with `SeasonType`, `Hydro_Year`, diagnostics copied onto rows, and annual wet/dry metrics. |
| `fixed_monthly` | The 12-month climatology table used to define the fixed baseline Wet/Dry seasons. |
| `wet_boundaries` | Per-year dynamic wet-season start/end dates when a seasonal regime is detected. |
| `seasonality` | STL and Walsh-Lawler seasonality diagnostics. |
| `diagnostics` | A compact report of method decisions, thresholds, validation warnings, and hydrological-year start month. |

## Install

```bash
pip install hydroseason
```

For AOI fetch support (ERA5 globally, SILO in Australia):

```bash
pip install "hydroseason[fetch]"
```

For local development from this repository:

```bash
pip install -e ".[dev]"
```

## Minimal Example

```python
import pandas as pd
from hydroseason import delineate_monthly_dataframe

df = pd.read_csv("data/DATASET.csv")
artifacts = delineate_monthly_dataframe(df)

artifacts.result[["Date", "SeasonType", "Hydro_Year"]].head()
```

Continue with the [Quick Start](quickstart.md) for Python, pandas accessor, CLI, and YAML examples.