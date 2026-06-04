# Configuration

The CLI reads a YAML file into `RunConfig`. The same algorithm and validation parameters can be passed directly to `classify_rainfall()`.

Set `fetch.enabled: true` to fetch monthly AOI data before delineation. In that mode `input.csv_path` is optional; the fetched table becomes the pipeline input.

## Example

```yaml
input:
  csv_path: data/monthly_rainfall.csv
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
  shoulder_month_quantile: 0.60
  core_climatology_alpha: 0.05
  shoulder_residual_quantile: 0.95
  climatology_window: rolling
  climatology_window_years: 10
  climatology_window_mode: trailing
  climatology_min_month_observations: 5
  climatology_min_wet_year_fraction: 0.60
  cap_rolling_tail_at_global: true
  keep_debug_columns: false
  require_low_floor_break_for_pruning: true

validation:
  max_fraction_missing: 0.1
  max_gap_to_interpolate: 2
  max_consecutive_imputation_gap: 12
  raise_on_error: true

fetch:
  enabled: false
  source: auto
  era5_zarr_path: gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3
  silo_base_url: null
  chirps_base_url: null
  vector_path: data/fitzroy_catchment.geojson
  start_year: 1985
  end_year: 2025
  variable: rainfall
  cache_dir: data/fetch_cache
  spatial_chunk: auto
  time_chunk: auto
  temporal_batch_years: auto
  era5_fallback: true
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
| `long_period_threshold` | `16` | Maximum accepted interval between wet-season onsets before trying to recover a filtered real Wet onset. |
| `fallback_month` | `None` | Optional target month for choosing a recovered Wet onset. When omitted, HydroSeason derives one from the long-term minimum. |
| `method` | `"circular"` | Fixed baseline method: `"circular"` or `"kmeans"`. |
| `report_kmeans_silhouette` | `False` | Opt-in legacy KMeans silhouette diagnostic for backward-compatible reports. Normal runs leave this disabled. |
| `min_core_length` | `None` | Minimum wet-core length required before tail refinement can cross a fixed hydrological-year boundary. `None` resolves from circular concentration `R` (2 to 5 months). |
| `onset_window_months` | `"auto"` | Only accept dynamic onsets near the fixed start month for unimodal records. `"auto"` disables the filter for bimodal/uniform records; use `None` to always disable. |
| `rainfall_si_override` | `True` | Promote borderline STL records to seasonal when Walsh-Lawler SI is strong. |
| `rainfall_si_threshold` | `0.80` | Walsh-Lawler SI threshold for promotion. |
| `shoulder_climatology_alpha` | `0.10` | Shoulder absorption floor as a fraction of the site's median wet-month climatology. |
| `shoulder_month_quantile` | `0.60` | Calendar-month rainfall quantile used as a month-aware shoulder extension floor. Lower values accept more shoulders; higher values are stricter; `None` disables. |
| `core_climatology_alpha` | `0.05` | First-pass wet-core floor as a fraction of the site's median wet-month climatology. |
| `shoulder_residual_quantile` | `0.95` | Positive STL-residual quantile used to reject isolated shoulder storm anomalies. Use `None` to disable. |
| `climatology_window` | `"rolling"` | Guardrail climatology source: `"rolling"` uses recent local normal by fixed hydrological year; `"global"` uses the full record. |
| `climatology_window_years` | `10` | Number of fixed hydrological years in each rolling local climatology window. |
| `climatology_window_mode` | `"trailing"` | Rolling-window alignment: `"trailing"` for recent/operational normal, `"centered"` for retrospective analysis. |
| `climatology_min_month_observations` | `5` | Minimum observed values per calendar month before a local rolling window is trusted; otherwise global fallback is used. |
| `climatology_min_wet_year_fraction` | `0.60` | Fraction of observed years in a rolling window that must clear the local tail floor before a locally labelled Wet month is treated as persistent. |
| `cap_rolling_tail_at_global` | `True` | Cap the local rolling tail floor at the global tail floor. |
| `keep_debug_columns` | `False` | Preserve intermediate columns `_TailFloor`, `_ExtensionFloor`, `_BaselineWetMonth`, and `_STL_Residual` in the results table when `True`. |
| `require_low_floor_break_for_pruning` | `True` | Dissolve out-of-season short fragments only when they touch an interior low floor break. When `False`, all short out-of-season fragments are pruned. |

## Validation Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `max_fraction_missing` | `0.10` | Maximum tolerated missing fraction before validation reports an error. |
| `max_gap_to_interpolate` | `2` | Warning threshold for consecutive missing-month gaps (gaps larger than this trigger a data quality warning; missing months are filled using climatology). |
| `max_consecutive_imputation_gap` | `12` | Maximum consecutive missing-month gap HydroSeason will automatically impute. Longer gaps are left unresolved and reported as errors. |
| `raise_on_validation_error` | `True` | If `True`, a validation failure raises a ValueError; otherwise it is recorded as a warning. |
| `raise_on_error` | `True` | Deprecated alias of `raise_on_validation_error`. |

## Fetch Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `enabled` | `False` | Fetch monthly AOI data before running the pipeline. |
| `source` | `"auto"` | Fetch source: `"auto"`, `"silo"`, `"chirps"`, or `"era5"`. Auto uses SILO for Australian AOIs and CHIRPS elsewhere. |
| `era5_zarr_path` | `None` | ERA5 Zarr store URI. Required when `source: era5`; used as backup for CHIRPS ranges before 1981, outside 60S-60N, or missing recent monthly products. |
| `silo_base_url` | `None` | Optional override for the SILO monthly rainfall NetCDF base URL. Leave `null` for the public SILO AWS location. |
| `chirps_base_url` | `None` | Optional override for the CHIRPS v3 monthly raster base URL. Leave `null` for UCSB CHIRPS v3 global monthly COGs. |
| `vector_path` | `None` | AOI vector path. GeoJSON, SHP, KML, KMZ, GPKG, GPCK, and other GeoPandas-readable formats are supported. |
| `start_year`, `end_year` | `None` | Inclusive fetch range. Required when fetch is enabled. |
| `variable` | `"rainfall"` | ERA5 variable adapter key. SILO and CHIRPS return rainfall only. |
| `cache_dir` | `None` | Optional cache directory for final monthly Parquet outputs and SILO annual NetCDF downloads. |
| `spatial_chunk` | `"auto"` | Spatial chunk size for xarray/dask computation where relevant. |
| `time_chunk` | `"auto"` | ERA5 hourly time chunk size. Lower this for large AOIs or low-memory machines. |
| `temporal_batch_years` | `"auto"` | ERA5 compute batch size in years. Lower this for long records, large AOIs, or low-memory machines. |
| `era5_fallback` | `True` | Allow ERA5 to fill years, AOIs, or recent months not covered by CHIRPS when `era5_zarr_path` is available. |

Config-driven fetches route through the AOI wrapper, so output tables retain
`Data_Source`, `Data_Product`, and `Fetch_Note` even when `source: silo` or
`source: era5` is selected explicitly.

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
