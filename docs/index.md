# HydroSeason

Hydrological seasons do not always follow the calendar.

HydroSeason turns rainfall records into Wet/Dry seasons, hydrological years, rainfall metrics, diagnostics, plots, and self-contained HTML report. Bring your own rainfall table, or provide catchment/AOI polygon and let HydroSeason fetch monthly rainfall from SILO, CHIRPS, or ERA5.

[Open the example report](report.md){ .md-button .md-button--primary }
[Start with the quick guide](quickstart.md){ .md-button }

![HydroSeason example report preview](assets/images/hydroseason-report-preview.png)

## Why Use It?

Calendar years are easy, but rainfall seasons often shift. Wet season can start early, end late, or cross reporting boundary — changing annual rainfall totals, dry-season length, annual classifications, surface-water/ecological interpretations.

HydroSeason uses rainfall record itself to label Wet/Dry seasons and assign hydrological years. Reports season onsets, data-quality notes, and method diagnostics — inspectable, not a black-box label.

| Common static approach | HydroSeason |
| --- | --- |
| Uses calendar years or one fixed water-year start | Assigns hydrological years from rainfall season timing |
| Assumes Wet/Dry months are fixed | Refines Wet/Dry labels year by year |
| Can split one wet season across two reporting years | Keeps rainfall grouped by hydrological season |
| Requires rainfall data prepared separately | Can fetch area-averaged rainfall from polygon |
| Gives limited method diagnostics | Exports thresholds, confidence notes, plots, and report |

![Static calendar seasons compared with HydroSeason dynamic hydrological years](assets/images/static-vs-hydroseason.png)

Top panel: one fixed climatology-derived Wet/Dry template, one fixed hydrological-year start. Bottom panel: rainfall record decides where wet/dry seasons and hydrological years begin.

## What HydroSeason Produces

High-level API returns `PipelineArtifacts` with:

| Artifact | Meaning |
| --- | --- |
| `result` | Labelled monthly DataFrame with `SeasonType`, `Hydro_Year`, diagnostics, and annual wet/dry metrics. |
| `fixed_monthly` | 12-month climatology table defining fixed baseline Wet/Dry seasons. |
| `wet_boundaries` | Per-year dynamic wet-season start/end dates when seasonal regime detected. |
| `seasonality` | STL and Walsh-Lawler seasonality diagnostics. |
| `diagnostics` | Compact report of method decisions, thresholds, validation warnings, hydrological-year start month. |

## Two Ways To Start

### I already have rainfall data

```bash
pip install hydroseason
```

```python
import pandas as pd
from hydroseason import classify_rainfall, generate_html_report

df = pd.read_csv("data/monthly_rainfall.csv")
artifacts = classify_rainfall(df)
generate_html_report(artifacts, "output/hydroseason_report.html")
```

### I have a polygon and need rainfall

```bash
pip install "hydroseason[fetch]"
```

```python
from hydroseason import (
    classify_rainfall,
    generate_html_report,
    get_monthly_aoi_rainfall,
    load_vector,
)

gdf = load_vector("catchment.geojson")

monthly = get_monthly_aoi_rainfall(
    gdf,
    start_year=1985,
    end_year=2023,
    source="auto",
    cache_dir="data/fetch_cache",
)

artifacts = classify_rainfall(monthly)
generate_html_report(artifacts, "output/hydroseason_report.html")
```

Auto fetch uses SILO for Australian catchments, CHIRPS v3 monthly rainfall elsewhere. ERA5 available as explicit path or backup when CHIRPS cannot cover requested range.
See [Rainfall Fetch](fetch.md) for full Python and CLI examples.

## Install

Core install includes rainfall validation, classification, local rainfall readers, diagnostics, metrics, CLI, interactive Plotly plots, and self-contained HTML reports.

```bash
pip install hydroseason
```

Optional extras:

```bash
pip install "hydroseason[fetch]"    # SILO/CHIRPS/ERA5 polygon rainfall fetch
pip install "hydroseason[all]"      # everything
```

Static PNG/SVG figure export planned for future release.

For local development:

```bash
pip install -e ".[dev,docs,all]"
```

Continue with [Quick Start](quickstart.md) for Python, pandas accessor, CLI, and YAML examples.
