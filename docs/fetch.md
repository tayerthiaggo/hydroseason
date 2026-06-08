# Rainfall Fetch

HydroSeason reads local rainfall files or fetches AOI-averaged monthly rainfall from gridded products. All acquisition paths return same tidy schema: `Date`, `Year`, `Month`, `Rainfall_mm`.

Local rainfall readers (`read_rainfall`, `classify_rainfall_from_file`) included in **core** install:

```bash
pip install hydroseason
```

AOI-based fetching from SILO, CHIRPS, or ERA5 requires **fetch** extra:

```bash
pip install "hydroseason[fetch]"
```

## Local Rainfall Files

`read_rainfall()` auto-detects common local formats, falls back to `pandas.read_csv()` for ordinary CSV.

```python
from hydroseason import read_rainfall, classify_rainfall_from_file

monthly = read_rainfall("IDCJAC0001_003018_Data1.csv", source="auto")
artifacts = classify_rainfall_from_file("IDCJAC0001_003018_Data1.csv", source="auto")
```

Supported local sources:

| Source | Notes |
| --- | --- |
| `csv` | Already tidy monthly CSV with `Rainfall_mm`, or pass `value_col`. |
| `bom` | BoM monthly rainfall product `IDCJAC0001`; rows with `Quality != 'Y'` dropped by default. |
| `silo` | SILO point files: fixed space-separated formats with metadata headers, and custom CSV exports. |
| `auto` | Detects BoM and SILO fixed files before falling back to CSV. |

CLI one-liner:

```bash
hydroseason rainfall \
  --input IDCJAC0001_003018_Data1.csv \
  --source auto \
  --output output/myroodah_results.csv
```

## AOI Vector Inputs

AOI fetch accepts any vector format supported by GeoPandas plus explicit handling for KMZ and GPCK aliases. Common inputs: GeoJSON, SHP, KML, KMZ, GPKG, GPCK.

Use `cache_dir` / `--cache-dir` for repeated work. HydroSeason stores final monthly table as Parquet plus small metadata JSON. Cache keys include normalized AOI geometry, bounds, source path/product key, and requested years — different polygons with same bounding box do not share cached rainfall. For SILO, downloaded annual NetCDF files also cached under `cache_dir/silo_netcdf`.

Python fetch API returns a DataFrame; you choose whether and where to save it. In CLI and YAML pipeline, output path is explicit.

## Auto AOI Rainfall

`get_monthly_aoi_rainfall(..., source="auto")` is recommended default. Uses SILO for Australian AOIs, CHIRPS v3 monthly rainfall elsewhere, public default ERA5 Zarr store only when ERA5 explicitly selected or needed as fallback.

AOI wrapper and `hydroseason fetch` CLI include `Data_Source`, `Data_Product`, `Fetch_Note` columns so mixed CHIRPS/ERA5/SILO series visible downstream. Lower-level helpers (`get_monthly_silo_rainfall()`, `get_monthly_era5_rainfall()`) return tidy monthly columns only unless called through wrapper.

Mixed-source series can be useful for coverage but are not climatologically identical. Treat `Fetch_Note` as part of analysis record; consider sensitivity checks when wet/dry labels or hydrological-year boundaries change near source transitions.

```python
from pathlib import Path

from hydroseason import get_monthly_aoi_rainfall, load_vector

gdf = load_vector("data/catchment.geojson")
out_dir = Path("output") / "my_aoi_run"
out_dir.mkdir(parents=True, exist_ok=True)

monthly = get_monthly_aoi_rainfall(
    gdf,
    start_year=1985,
    end_year=2023,
    source="auto",
    cache_dir="data/fetch_cache",
)
monthly.to_csv(out_dir / "monthly_rainfall.csv", index=False)
```

```bash
hydroseason fetch \
  --source auto \
  --vector data/catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --cache-dir data/fetch_cache \
  --output output/monthly_rainfall.csv
```

## Force SILO

Use only to force SILO instead of letting `source="auto"` choose it. SILO polygon fetch is Australia-only using public SILO gridded monthly rainfall NetCDF on AWS.

```python
from hydroseason import get_monthly_aoi_rainfall, load_vector

gdf = load_vector("data/fitzroy_catchment.geojson")
monthly = get_monthly_aoi_rainfall(
    gdf,
    start_year=1985,
    end_year=2023,
    source="silo",
    cache_dir="data/silo_cache",
)
```

```bash
hydroseason fetch \
  --source silo \
  --vector data/fitzroy_catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --cache-dir data/silo_cache \
  --output output/silo_monthly_rainfall.csv
```

Use `--silo-base-url` only when mirroring or testing against non-default SILO NetCDF location.

## Force ERA5

Use only to force ERA5 instead of `source="auto"`. ERA5 fetch aggregates rainfall from public Google Cloud ERA5 Zarr archive for catchment polygon. Works globally, returns tidy monthly `Rainfall_mm` table; slower because hourly data must be aggregated.

```python
from hydroseason import get_monthly_aoi_rainfall, load_vector

gdf = load_vector("data/fitzroy_catchment.geojson")

monthly = get_monthly_aoi_rainfall(
    gdf,
    start_year=1985,
    end_year=2023,
    source="era5",
    variable="rainfall",
    cache_dir="data/era5_cache",
)
```

```bash
hydroseason fetch \
  --source era5 \
  --vector data/fitzroy_catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --variable rainfall \
  --cache-dir data/era5_cache \
  --output output/era5_monthly_rainfall.csv
```

ERA5 exact mode reads total precipitation inside `hydroseason.fetch` and converts monthly totals from metres to millimetres. Supported ERA5 fetch variable: rainfall. Uses default public Zarr store unless `era5_zarr_path` passed in Python or `--path` in CLI. Local Zarr paths and alternate `gs://` stores supported; anonymous GCS options applied only to Google Cloud paths.

For large AOIs or memory-constrained machines, reduce ERA5 hourly chunk size (`time_chunk=6` in Python or `--time-chunk 6` in CLI). Long requests can be split with `temporal_batch_years=1` or `--temporal-batch-years 1`.

CHIRPS v3 starts 1981, land-only, covers ~60S–60N. If configured, ERA5 can fill pre-1981 years, AOIs outside CHIRPS latitude coverage, or unavailable CHIRPS rasters/recent months.
