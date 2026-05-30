# HydroSeason

**Rainfall-based hydrological Wet/Dry season and hydrological-year delineation.**

HydroSeason turns monthly rainfall records into labelled Wet/Dry seasons,
hydrological years, rainfall metrics, diagnostics, plots, and self-contained HTML
reports. It packages the rainfall-based dynamic wet/dry period workflow from the
Tayer et al. (2026) supplementary methodology as a reusable Python API, pandas
accessor, YAML-driven CLI, local rainfall reader, and ERA5/SILO AOI rainfall
fetch workflow.

Full documentation: https://tayerthiaggo.github.io/hydroseason/

[![HydroSeason example report preview](docs/assets/images/hydroseason-report-preview.png)](https://tayerthiaggo.github.io/hydroseason/report/)

## Install

```bash
pip install hydroseason
```

Once available on conda-forge:

```bash
conda install -c conda-forge hydroseason
```

The standard install includes the core pipeline, Plotly reporting, local rainfall
readers, and ERA5/SILO AOI rainfall fetch support. It pulls in the geospatial
stack (`xarray`, `dask`, `geopandas`, `rasterio`, `netCDF4`, `gcsfs`), which most
remote-sensing environments already provide.

## Quick Example

```python
import pandas as pd
from hydroseason import delineate_monthly_dataframe, generate_html_report

df = pd.read_csv("data/DATASET.csv")
artifacts = delineate_monthly_dataframe(df)

result = artifacts.result
print(result[["Date", "SeasonType", "Hydro_Year"]].head())
print(artifacts.diagnostics.regime)

generate_html_report(artifacts, "output/hydroseason_report.html")
```

Input data should contain monthly `Date`, `Year`, `Month`, and `Rainfall_mm`
columns.

### Pandas accessor

Importing `hydroseason` registers a `.hydroseason` accessor on every DataFrame,
so you can run the same workflow inline:

```python
import hydroseason  # registers df.hydroseason
import pandas as pd

df = pd.read_csv("data/DATASET.csv")
result = df.hydroseason.classify()              # labelled DataFrame
artifacts = df.hydroseason.delineate()          # full PipelineArtifacts
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
hydroseason rainfall --input data/DATASET.csv --source csv --output output/rainfall_results.csv
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
pip install -e ".[dev,docs]"
python -m pytest -q
python scripts/stress_test.py --cases 100 --seed 42
```

## Citation

If you use HydroSeason in research, cite the associated Tayer et al. manuscript
when its final bibliographic details are available, and cite the software
repository or release used for your analysis.

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
