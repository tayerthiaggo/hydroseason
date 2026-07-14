# HydroSeason

Source-agnostic hydrological-year detection from **monthly surface-water extent**.

HydroSeason used to be rainfall-first. Applied across several catchments, the
rainfall approach did not work well in practice, so the package has been
re-platformed as **remote-sensing (water-mask) first**: hydro-year boundaries
are detected from monthly water-extent series, not rainfall. The previous
rainfall implementation is preserved, unchanged, on the `legacy/rainfall`
branch (tag `v0-rainfall-legacy`) for anyone who still needs it.

## Three supported input paths

All three converge on the same monthly water-extent representation before
detection runs — nothing downstream branches on source type.

| Path | Loader | Core deps only? |
|---|---|---|
| Monthly extent CSV (already computed) | `load_extent_csv` | Yes — pandas/numpy only |
| Generic binary or canonical water-mask rasters (incl. Zarr cubes) | `load_monthly_masks`, `load_monthly_masks_zarr` | No — needs `[raster]` |
| WOfS / STAC catalog | `load_wofs_from_stac` | No — needs `[stac]` |

Raster paths require an AOI (`load_aoi`) and fail closed if AOI
clipping/rasterization cannot be applied — they never fall back to
processing an unclipped raster.

> **Strongly recommended:** if you are starting from raw or incomplete water
> masks, run WaterMask-TSFill gapfilling first, then
> feed the completed masks (or a completed monthly-extent series) into
> HydroSeason. Cloud/shadow gaps and missing months can shift detected
> wet/dry boundaries. The CSV path is only safe when the upstream extent
> series has already been completed and quality-screened.

## Install

```bash
pip install hydroseason              # core: CSV-only detection (pandas, numpy)
pip install hydroseason[raster]      # + xarray/rioxarray/rasterio/geopandas/dask/zarr
pip install hydroseason[stac]        # + pystac-client/odc-stac
pip install hydroseason[all]         # raster + stac
```

## Quickstart (extent CSV path)

```python
from hydroseason import load_extent_csv, detect_hydrological_years, label_hydrological_months

extent = load_extent_csv("monthly_extent.csv", date_col="date", value_col="extent_pct")
hydro_years = detect_hydrological_years(extent)
labels = label_hydrological_months(extent.index, hydro_years)
```

For the raster/WOfS paths, canonical mask values, and AOI requirements, see
the [usage guide](docs/guide.md).

## Public API

```python
from hydroseason import (
    # detection core — source-agnostic, operates on canonical shapes
    HydroYearConfig,
    detect_hydrological_years,
    label_hydrological_months,
    monthly_water_extent,
    # loaders — one per source, all converging on the canonical shape
    load_aoi,
    load_wofs_from_stac,
    load_monthly_masks,
    load_monthly_masks_zarr,
    load_extent_csv,
    complete_monthly_axis,
)
```

`detect_hydrological_years` and `label_hydrological_months` import with only
`numpy`/`pandas` — no raster extra required for the CSV path.

## Documentation

Full usage guide, canonical mask values, and examples: [`docs/`](docs/index.md)
(or the built site at the URL in `pyproject.toml`).

## Citation

See [`CITATION.cff`](CITATION.cff) and [`docs/citation.md`](docs/citation.md).
