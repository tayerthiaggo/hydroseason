# Configuration

CLI reads YAML into `RunConfig`. Same algorithm and validation parameters can be passed directly to `classify_rainfall()`.

Set `fetch.enabled: true` to fetch monthly AOI data before delineation. In that mode `input.csv_path` is optional; fetched table becomes pipeline input.

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
  era5_zarr_path: null
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

Run with:

```bash
hydroseason run --config config/example.yaml
```

## Algorithm Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `smooth_window` | `None` | Centred rolling window (months) for zero-preserving smoothing. `None` resolves from circular concentration `R` (3–5 months). |
| `firstpass_quantile` | `0.20` | Quantile of non-zero values for first-pass wet-season core detection. |
| `secondpass_quantile` | `0.10` | Lower quantile for wet-season tail refinement. |
| `long_period_threshold` | `16` | Max accepted interval between wet-season onsets before attempting recovery of filtered real Wet onset. |
| `fallback_month` | `None` | Optional target month for choosing recovered Wet onset. When omitted, HydroSeason derives from long-term minimum. |
| `method` | `"circular"` | Fixed baseline method: `"circular"` or `"kmeans"`. |
| `report_kmeans_silhouette` | `False` | Opt-in legacy KMeans silhouette diagnostic for backward-compatible reports. |
| `min_core_length` | `None` | Min wet-core length before tail refinement can cross fixed hydrological-year boundary. `None` resolves from `R` (2–5 months). |
| `onset_window_months` | `"auto"` | Only accept dynamic onsets near fixed start month for unimodal records. `"auto"` disables for bimodal/uniform; use `None` to always disable. |
| `rainfall_si_override` | `True` | Promote borderline STL records to seasonal when Walsh-Lawler SI is strong. |
| `rainfall_si_threshold` | `0.80` | Walsh-Lawler SI threshold for promotion. |
| `shoulder_climatology_alpha` | `0.10` | Shoulder absorption floor as fraction of site's median wet-month climatology. |
| `shoulder_month_quantile` | `0.60` | Calendar-month rainfall quantile for month-aware shoulder extension floor. Lower = more shoulders; `None` disables. |
| `core_climatology_alpha` | `0.05` | First-pass wet-core floor as fraction of site's median wet-month climatology. |
| `shoulder_residual_quantile` | `0.95` | Positive STL-residual quantile to reject isolated shoulder storm anomalies. `None` disables. |
| `climatology_window` | `"rolling"` | Guardrail climatology source: `"rolling"` uses recent local normal; `"global"` uses full record. |
| `climatology_window_years` | `10` | Fixed hydrological years per rolling local climatology window. |
| `climatology_window_mode` | `"trailing"` | Rolling-window alignment: `"trailing"` for recent/operational, `"centered"` for retrospective. |
| `climatology_min_month_observations` | `5` | Min observed values per calendar month before local rolling window trusted; else global fallback. |
| `climatology_min_wet_year_fraction` | `0.60` | Fraction of observed years in rolling window that must clear local tail floor before locally labelled Wet month treated as persistent. |
| `cap_rolling_tail_at_global` | `True` | Cap local rolling tail floor at global tail floor. |
| `keep_debug_columns` | `False` | Preserve intermediate columns `_TailFloor`, `_ExtensionFloor`, `_BaselineWetMonth`, `_STL_Residual` when `True`. |
| `require_low_floor_break_for_pruning` | `True` | Dissolve out-of-season short fragments only when touching interior low floor break. `False` prunes all short out-of-season fragments. |

## Validation Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `max_fraction_missing` | `0.10` | Max tolerated missing fraction before validation errors. |
| `max_gap_to_interpolate` | `2` | Warning threshold for consecutive missing-month gaps (larger gaps trigger data quality warning; missing months filled using climatology). |
| `max_consecutive_imputation_gap` | `12` | Max consecutive missing-month gap auto-imputed. Longer gaps left unresolved and reported as errors. |
| `raise_on_validation_error` | `True` | Raise ValueError on validation failure; else record as warning. |
| `raise_on_error` | `True` | Deprecated alias of `raise_on_validation_error`. |

## Fetch Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `enabled` | `False` | Fetch monthly AOI data before running pipeline. |
| `source` | `"auto"` | Fetch source: `"auto"`, `"silo"`, `"chirps"`, or `"era5"`. Auto uses SILO for Australian AOIs, CHIRPS elsewhere. |
| `era5_zarr_path` | `None` | Optional ERA5 Zarr store override. `null` uses HydroSeason's public ERA5 default. |
| `silo_base_url` | `None` | Optional override for SILO monthly rainfall NetCDF base URL. `null` = public SILO AWS. |
| `chirps_base_url` | `None` | Optional override for CHIRPS v3 monthly raster base URL. `null` = UCSB CHIRPS v3 global monthly COGs. |
| `vector_path` | `None` | AOI vector path. GeoJSON, SHP, KML, KMZ, GPKG, GPCK, other GeoPandas-readable formats supported. |
| `start_year`, `end_year` | `None` | Inclusive fetch range. Required when fetch enabled. |
| `variable` | `"rainfall"` | Legacy ERA5 selector. Only `"rainfall"` supported. SILO and CHIRPS return rainfall only. |
| `cache_dir` | `None` | Optional cache dir for final monthly Parquet outputs and SILO annual NetCDF downloads. |
| `spatial_chunk` | `"auto"` | Spatial chunk size for xarray/dask computation. |
| `time_chunk` | `"auto"` | ERA5 hourly time chunk size. Lower for large AOIs or low-memory machines. |
| `temporal_batch_years` | `"auto"` | ERA5 compute batch size in years. Lower for long records, large AOIs, or low memory. |
| `era5_fallback` | `True` | Allow ERA5 to fill years, AOIs, or recent months not covered by CHIRPS, unless `era5_zarr_path` overrides. |
| `large_era5_fallback` | `"ask"` | Behaviour before implicit ERA5 fallback larger than 60 months: `"ask"` requests approval (5 min timeout); `"allow"` proceeds; `"error"` fails fast. |

Config-driven fetches route through AOI wrapper, so output tables retain
`Data_Source`, `Data_Product`, `Fetch_Note` even when `source: silo` or
`source: era5` selected explicitly. Set `output.output_csv` to any project path; HydroSeason does not write outputs inside the package.

Fetch-only auto config:

```yaml
output:
  output_csv: output/my_project/hydroseason_results.csv

fetch:
  enabled: true
  source: auto
  vector_path: data/fitzroy_catchment.geojson
  start_year: 1985
  end_year: 2023
  cache_dir: data/fetch_cache
```
