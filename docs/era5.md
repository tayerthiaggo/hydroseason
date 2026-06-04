# Rainfall Fetch

HydroSeason can either read local rainfall files or fetch AOI-averaged monthly rainfall from gridded products. All rainfall acquisition paths return the same tidy schema: `Date`, `Year`, `Month`, and `Rainfall_mm`.

Local rainfall readers (`read_rainfall`, `classify_rainfall_from_file`) are included in the **core** install:

```bash
pip install hydroseason
```

AOI-based fetching from SILO, CHIRPS, or ERA5 requires the **fetch** extra:

```bash
pip install "hydroseason[fetch]"
```

## Local Rainfall Files

`read_rainfall()` auto-detects common local formats and falls back to `pandas.read_csv()` for ordinary CSV files.

```python
from hydroseason import read_rainfall, classify_rainfall_from_file

monthly = read_rainfall("IDCJAC0001_003018_Data1.csv", source="auto")
artifacts = classify_rainfall_from_file("IDCJAC0001_003018_Data1.csv", source="auto")
```

Supported local sources:

| Source | Notes |
| --- | --- |
| `csv` | Already tidy monthly CSV with `Rainfall_mm`, or pass `value_col`. |
| `bom` | BoM monthly rainfall product `IDCJAC0001`; rows with `Quality != 'Y'` are dropped by default. |
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

AOI fetch accepts any vector format supported by GeoPandas plus explicit handling for KMZ and GPCK aliases. Common inputs include GeoJSON, SHP, KML, KMZ, GPKG, and GPCK.

Use `cache_dir` / `--cache-dir` for repeated work. HydroSeason stores the final monthly table as Parquet plus a small metadata JSON. For SILO, downloaded annual NetCDF files are also cached under `cache_dir/silo_netcdf`.

## Auto AOI Rainfall

`get_monthly_aoi_rainfall(..., source="auto")` is the recommended default. It uses SILO for Australian AOIs, CHIRPS v3 monthly rainfall elsewhere, and ERA5 only when explicitly selected or when an `era5_zarr_path` is provided as a backup for ranges CHIRPS cannot cover.

Returned fetch tables include `Data_Source`, `Data_Product`, and `Fetch_Note` columns so mixed CHIRPS/ERA5 series are visible downstream.

```python
from hydroseason import get_monthly_aoi_rainfall, load_vector

ERA5_ZARR = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
gdf = load_vector("data/catchment.geojson")

monthly = get_monthly_aoi_rainfall(
    gdf,
    start_year=1985,
    end_year=2023,
    source="auto",
    era5_zarr_path=ERA5_ZARR,
    cache_dir="data/fetch_cache",
)
```

```bash
hydroseason fetch \
  --source auto \
  --path gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3 \
  --vector data/catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --cache-dir data/fetch_cache \
  --output output/monthly_rainfall.csv
```

## SILO Polygon Rainfall

SILO polygon fetch is Australia-only and uses the public SILO gridded monthly rainfall NetCDF files on AWS.

```python
from hydroseason import get_monthly_silo_rainfall, load_vector

gdf = load_vector("data/fitzroy_catchment.geojson")
monthly = get_monthly_silo_rainfall(
    gdf,
    start_year=1985,
    end_year=2023,
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

Use `--silo-base-url` only when mirroring or testing against a non-default SILO NetCDF location.

## ERA5 Polygon Rainfall (Exact/Backup)

ERA5 fetch aggregates rainfall from the public Google Cloud ERA5 Zarr archive for a catchment polygon. It works globally and returns a tidy monthly `Rainfall_mm` table, but it is slower because hourly data must be aggregated to monthly rainfall.

```python
from hydroseason import get_monthly_era5_rainfall, load_vector

ERA5_ZARR = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
gdf = load_vector("data/fitzroy_catchment.geojson")

monthly = get_monthly_era5_rainfall(
    path=ERA5_ZARR,
    gdf=gdf,
    start_year=1985,
    end_year=2023,
    variable="rainfall",
    cache_dir="data/era5_cache",
)
```

```bash
hydroseason fetch \
  --source era5 \
  --path gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3 \
  --vector data/fitzroy_catchment.geojson \
  --start-year 1985 \
  --end-year 2023 \
  --variable rainfall \
  --cache-dir data/era5_cache \
  --output output/era5_monthly_rainfall.csv
```

Rainfall is resolved through `hydroseason.era5_variables`, which maps ERA5 total precipitation to monthly millimetres.

For large AOIs or memory-constrained machines, reduce the ERA5 hourly chunk
size, for example `time_chunk=6` in Python or `--time-chunk 6` in the CLI.
