# HydroSeason

HydroSeason is a Python package for delineating hydrological Wet/Dry seasons and hydrological years from monthly rainfall records.

The core workflow validates monthly rainfall data, detects seasonality, builds a fixed seasonal baseline, refines dynamic wet-season boundaries, assigns hydrological years, and returns diagnostics and metrics that can be exported to CSV, JSON, Plotly figures, or a self-contained HTML report. HydroSeason can also read common Australian rainfall formats and fetch AOI-averaged rainfall from ERA5 or SILO.

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

The core install includes the rainfall validation, classification, hydrological-year assignment, local rainfall readers, diagnostics, metrics, CLI, interactive Plotly plots, and self-contained HTML reports.

Optional extras:

```bash
pip install "hydroseason[fetch]"    # ERA5/SILO AOI rainfall fetch
pip install "hydroseason[all]"      # everything
```

Static PNG/SVG figure export is planned for a future release.

For local development from this repository:

```bash
pip install -e ".[dev,docs,all]"
```

## Minimal Example

```python
import pandas as pd
from hydroseason import classify_rainfall

df = pd.read_csv("data/monthly_rainfall.csv")
artifacts = classify_rainfall(df)

artifacts.result[["Date", "SeasonType", "Hydro_Year"]].head()
```

Continue with the [Quick Start](quickstart.md) for Python, pandas accessor, CLI, and YAML examples.

For a visual sense of the final output, open the [Example Report](report.md).
