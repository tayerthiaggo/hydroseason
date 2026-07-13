# HydroSeason

Source-agnostic hydrological-year detection from **monthly surface-water extent**.

HydroSeason was originally rainfall-first. Applied across several catchments,
the rainfall approach did not work well in practice, so the package is now
**remote-sensing (water-mask) first**: hydro-year boundaries are detected from
monthly water-extent series (WOfS/STAC, other binary water-mask rasters, or a
plain extent CSV), not rainfall. The detection engine is ported from
WaterMask-TSFill.

The previous rainfall implementation still exists, unchanged, on the
`legacy/rainfall` branch (tag `v0-rainfall-legacy`) of this repository.

## Install

```bash
pip install hydroseason              # core: CSV-only detection (pandas, numpy)
pip install hydroseason[raster]      # + xarray/rioxarray/rasterio/geopandas/dask/zarr
pip install hydroseason[stac]        # + pystac-client/odc-stac
pip install hydroseason[all]         # raster + stac
```

## Three supported input paths

| Path | Loader | Requires |
|---|---|---|
| Monthly extent CSV (already computed) | [`load_extent_csv`](guide.md#path-1-extent-csv) | core only |
| Generic binary/canonical water-mask rasters or Zarr cubes | [`load_monthly_masks`, `load_monthly_masks_zarr`](guide.md#path-2-generic-water-mask-rasters) | `[raster]` |
| WOfS / STAC catalog | [`load_wofs_from_stac`](guide.md#path-3-wofs-stac) | `[stac]` |

All three converge on the same canonical monthly water-extent representation
before `detect_hydrological_years` ever runs — see the [usage guide](guide.md)
for details, canonical mask values, and the AOI requirement.

!!! warning "Gapfill before detecting"
    Water-mask gaps, cloud/shadow contamination, and missing months can shift
    detected wet/dry boundaries. Strongly run WaterMask-TSFill gapfilling on
    raw/incomplete masks (or ensure a precomputed extent CSV was already
    completed and quality-screened) before running hydro-year detection. See
    the [gapfilling recommendation](guide.md#gapfill-before-detecting).

## Quickstart

```python
from hydroseason import load_extent_csv, detect_hydrological_years, label_hydrological_months

extent = load_extent_csv("monthly_extent.csv", date_col="date", value_col="extent_pct")
hydro_years = detect_hydrological_years(extent)
labels = label_hydrological_months(extent.index, hydro_years)
```

See the [usage guide](guide.md) for the raster and WOfS/STAC paths.

## Citation

See [Citation](citation.md).
