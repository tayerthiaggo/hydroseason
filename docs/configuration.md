# Configuration

The CLI reads a YAML file into `RunConfig`. The same algorithm and validation parameters can be passed directly to `classify_rainfall()`.

Set `fetch.enabled: true` to fetch monthly AOI data before delineation. In that mode `input.csv_path` is optional; the fetched table becomes the pipeline input.

## Example

```yaml
input:
  csv_path: data/DATASET.csv
  date_col: Date
  year_col: Year
  month_col: Month
  value_col: Rainfall_mm

output:
  output_csv: output/hydroseason_results.csv

algorithm:
  # Leave adaptive parameters unset for automatic resolution.
  # Set explicit values only when you need exact reproducibility.
  firstpass_quantile: 0.2
  secondpass_quantile: 0.1
  long_period_threshold: 16
  fallback_month: null
  method: circular
  smooth_window: null
  min_core_length: null
  onset_window_months: auto
  rainfall_si_override: true
  rainfall_si_threshold: 0.8
  shoulder_climatology_alpha: 0.10
  core_climatology_alpha: 0.05
  shoulder_residual_quantile: 0.95

validation:
  max_fraction_missing: 0.1
  max_gap_to_interpolate: 2
  max_consecutive_imputation_gap: 12
  raise_on_error: true

fetch:
  enabled: false
  source: era5
  era5_zarr_path: gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3
  silo_base_url: null
  vector_path: data/fitzroy_catchment.geojson
  start_year: 1985
  end_year: 2025
  variable: rainfall
  cache_dir: data/era5_cache
  spatial_chunk: 50
```

Run it with:

```bash
hydroseason run --config config/example.yaml
```

## Algorithm Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `smooth_window` | `None` | Centred rolling window, in months, for zero-preserving smoothing. `None` resolves from circular concentration `R` (3 to 5 months). |
| `firstpass_quantile` | `0.20` | Quantile of non-zero values used for first-pass wet-season core detection. |
| `secondpass_quantile` | `0.10` | Lower quantile used for wet-season tail refinement. |
| `long_period_threshold` | `16` | Maximum accepted interval between wet-season onsets before inserting a fallback boundary. |
| `fallback_month` | `None` | Optional fallback start month. When omitted, HydroSeason derives one from the long-term minimum. |
| `method` | `"circular"` | Fixed baseline method: `"circular"` or `"kmeans"`. |
| `min_core_length` | `None` | Minimum wet-core length required before tail refinement can cross a fixed hydrological-year boundary. `None` resolves from circular concentration `R` (2 to 5 months). |
| `onset_window_months` | `"auto"` | Only accept dynamic onsets near the fixed start month for unimodal records. `"auto"` disables the filter for bimodal/uniform records; use `None` to always disable. |
| `rainfall_si_override` | `True` | Promote borderline STL records to seasonal when Walsh-Lawler SI is strong. |
| `rainfall_si_threshold` | `0.80` | Walsh-Lawler SI threshold for promotion. |
| `shoulder_climatology_alpha` | `0.10` | Shoulder absorption floor as a fraction of the site's median wet-month climatology. |
| `core_climatology_alpha` | `0.05` | First-pass wet-core floor as a fraction of the site's median wet-month climatology. |
| `shoulder_residual_quantile` | `0.95` | Positive STL-residual quantile used to reject isolated shoulder storm anomalies. Use `None` to disable. |

## Validation Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `max_fraction_missing` | `0.10` | Maximum tolerated missing fraction before validation reports an error. |
| `max_gap_to_interpolate` | `2` | Maximum consecutive missing-month gap to interpolate. |
| `max_consecutive_imputation_gap` | `12` | Maximum consecutive missing-month gap HydroSeason will automatically impute. Longer gaps are left unresolved and reported as errors. |
| `raise_on_error` | `True` | Raise validation errors instead of returning warnings only. |

## Fetch Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `enabled` | `False` | Fetch monthly AOI data before running the pipeline. |
| `source` | `"era5"` | Fetch source: `"era5"` or `"silo"`. |
| `era5_zarr_path` | `None` | ERA5 Zarr store URI. Required when `source: era5`. |
| `silo_base_url` | `None` | Optional override for the SILO monthly rainfall NetCDF base URL. Leave `null` for the public SILO AWS location. |
| `vector_path` | `None` | AOI vector path. GeoJSON, SHP, KML, KMZ, GPKG, GPCK, and other GeoPandas-readable formats are supported. |
| `start_year`, `end_year` | `None` | Inclusive fetch range. Required when fetch is enabled. |
| `variable` | `"rainfall"` | ERA5 variable adapter key. SILO MVP always returns monthly rainfall. |
| `cache_dir` | `None` | Optional cache directory for final monthly Parquet outputs and SILO annual NetCDF downloads. |
| `spatial_chunk` | `50` | Spatial chunk size for xarray/dask computation. |

Fetch-only SILO config:

```yaml
output:
  output_csv: output/silo_hydroseason_results.csv

fetch:
  enabled: true
  source: silo
  vector_path: data/fitzroy_catchment.geojson
  start_year: 1985
  end_year: 2023
  cache_dir: data/silo_cache
```