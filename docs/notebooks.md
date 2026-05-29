# Notebooks

The repository includes executable notebooks for end-to-end examples and advanced reproduction workflows.

| Notebook | Description |
| --- | --- |
| [hydroseason_quickstart.ipynb](https://github.com/tayerthiaggo/hydroseason/blob/main/notebooks/hydroseason_quickstart.ipynb) | End-to-end local workflow using the bundled example dataset, summary card, Plotly figures, and HTML report export. |
| [hydroseason_rainfall_io_example.ipynb](https://github.com/tayerthiaggo/hydroseason/blob/main/notebooks/hydroseason_rainfall_io_example.ipynb) | Local rainfall ingestion examples for tidy CSV, BoM monthly rainfall CSV, SILO point files, and the `run_rainfall()` convenience wrapper. |
| [hydroseason_aoi_fetch_example.ipynb](https://github.com/tayerthiaggo/hydroseason/blob/main/notebooks/hydroseason_aoi_fetch_example.ipynb) | AOI rainfall fetch examples for SILO and ERA5 using GeoJSON/SHP/KML/KMZ/GPKG/GPCK vectors and Parquet caching. |
| [hydroseason_era5_fetch_example.ipynb](https://github.com/tayerthiaggo/hydroseason/blob/main/notebooks/hydroseason_era5_fetch_example.ipynb) | ERA5 catchment rainfall fetch, delineation, plotting, and report export. |
| [hydroseason_tayer2026_example.ipynb](https://github.com/tayerthiaggo/hydroseason/blob/main/tests/hydroseason_tayer2026_example.ipynb) | Advanced reproduction workflow for the Tayer et al. (2026) dataset and end-of-dry metrics. |

The quickstart notebook mirrors the recommended package workflow: import HydroSeason, load monthly rainfall, run `delineate_monthly_dataframe()`, inspect `PipelineArtifacts`, render Plotly charts, and export a self-contained HTML report. The rainfall IO and AOI fetch notebooks focus on acquiring data before the same pipeline step.