# Outputs & Metrics

## Pipeline Artifacts

`classify_rainfall()` returns `PipelineArtifacts`:

| Attribute | Description |
| --- | --- |
| `result` | Main labelled monthly DataFrame. |
| `fixed_monthly` | Twelve-row climatology table with baseline season labels. |
| `wet_boundaries` | Per-hydrological-year wet-season boundaries for seasonal records, or `None`. |
| `seasonality` | STL, Walsh-Lawler SI, and regime classification result. |
| `diagnostics` | Dataclass with thresholds, method choices, validation warnings, and record counts. |

## Result Columns

Input columns preserved; hydrological labels and diagnostics appended.

| Column | Description |
| --- | --- |
| `SeasonType` | `Wet`, `Dry`, or `Unclassified`. |
| `SeasonShift` | `True` where `SeasonType` changes from previous row. |
| `Hydro_Year` | Dynamic hydrological year using ending-year convention. |
| `Hydro_Year_fixed` | Baseline hydrological year from fixed climatological start month. |
| `Seasonality_SI` | Walsh-Lawler Seasonality Index copied onto each row. |
| `Seasonality_STL` | STL seasonality strength copied onto each row. |
| `Seasonality_Regime` | Final detected regime copied onto each row. |
| `Imputed` | `True` for missing months filled by validation using calendar-month climatological means. |
| `wet_total`, `dry_total` | Annual wet/dry totals for default rainfall column. |
| `wet_month_count`, `dry_month_count` | Annual wet/dry month counts. |
| `dry_event_count` | Dry-season months with values above `nonzero_threshold`. |
| `Smoothed` | Three-month centred rolling-mean rainfall (rainfall workflow only). |
| `Rain_wet_season_mm`, `Rain_dry_season_mm` | Per-hydro-year wet/dry rainfall totals (Tayer et al. 2026 aliases). |
| `Dry_month_count`, `Dry_season_rain_count` | Per-hydro-year dry-month and rainy-dry-month counts (Tayer et al. 2026 aliases). |
| `Annual_SPI` | Z-score of annual rainfall across record (rainfall workflow). |
| `Year_Class_SPI` | Annual class from `Annual_SPI`: `Dry` (SPI < −1), `Regular` (−1 ≤ SPI ≤ +1), `Wet` (SPI > +1). |
| `Drought_Category` | Categorical bin from `Dry_month_count`: `No dry` (0), `Minimal` (1–2), `Regular` (3–6), `Prolonged` (≥7). |
| `_TailFloor` | Local/global tail-floor guardrail values (preserved when `keep_debug_columns=True`). |
| `_ExtensionFloor` | Local/global shoulder-extension guardrail values (preserved when `keep_debug_columns=True`). |
| `_BaselineWetMonth` | Boolean flag for stable climatological wet months in rolling window (preserved when `keep_debug_columns=True`). |
| `_STL_Residual` | STL residual values for shoulder extension filtering (preserved when `keep_debug_columns=True`). |

## Diagnostics

| Field | Description |
| --- | --- |
| `regime` | `seasonal`, `borderline`, or `non_seasonal`. |
| `regime_source` | `stl` or `rainfall_si_override`. |
| `stl_strength` | STL seasonal strength `F_S`. |
| `walsh_lawler_si` | Walsh-Lawler Seasonality Index. |
| `hydro_year_start_month` | Fixed hydrological-year start month, 1–12. |
| `fallback_month_used` | Target month used when choosing recovered real Wet onset after long accepted-onset gap. |
| `threshold_firstpass` | First-pass wet-season threshold. |
| `threshold_secondpass` | Tail-refinement threshold. |
| `tail_floor` | Global fallback raw-rainfall floor for first pass. Rolling runs may use per-row `_TailFloor` values. |
| `tail_floor_source` | `scalar` when active tail floor is one value, `per_row` when rolling/month-aware guardrails produced multiple, or `null` when skipped. |
| `tail_floor_min`, `tail_floor_max`, `tail_floor_unique_count` | Summary of active `_TailFloor` values used in seasonal run. |
| `extension_floor_min`, `extension_floor_max`, `extension_floor_unique_count` | Summary of active `_ExtensionFloor` values for shoulder absorption. |
| `smooth_window_used` | Resolved centred smoothing window used by seasonal pipeline. |
| `min_core_length_used` | Resolved minimum wet-core length to cross fixed hydrological-year boundaries. |
| `onset_window_months_used` | Resolved onset acceptance window; `null` = disabled. |
| `core_climatology_floor` | Site-scaled floor for first-pass wet-core detection. |
| `shoulder_climatology_floor` | Site-scaled floor for shoulder absorption. |
| `shoulder_month_quantile` | Calendar-month quantile for month-aware shoulder extension; `null` = disabled. |
| `shoulder_month_floor_source` | Source for month-aware floors: `observed`, `observed_with_fallback`, `disabled_low_confidence`, or `null`. |
| `climatology_window` | Guardrail climatology mode: `rolling` or `global`. |
| `climatology_window_years` | Hydrological years per rolling guardrail window. |
| `climatology_window_mode` | Rolling-window alignment: `trailing` or `centered`. |
| `climatology_min_month_observations` | Min observed values per calendar month before rolling window trusted. |
| `climatology_min_wet_year_fraction` | Min fraction of observed years clearing local tail floor before local Wet month treated as persistent. |
| `climatology_guardrail_source` | Actual guardrail source: global, rolling, fallback, or mixed. |
| `climatology_guardrail_fallback_count` | Fixed hydrological years whose rolling guardrail fell back to global. |
| `climatology_unstable_month_count` | Locally labelled Wet months rejected by persistence guard across rolling windows. |
| `shoulder_residual_threshold` | Positive STL-residual threshold for rejecting isolated shoulder storm anomalies; `null` = disabled/unavailable. |
| `validation_warnings` | Data-quality warnings from validation. |
| `n_imputed` | Missing months filled during validation. |
| `n_unimputed` | Missing months left unresolved. |
| `max_consecutive_missing` | Longest consecutive missing-month run before imputation. |
| `data_confidence` | `high`, `medium`, or `low`, based on missing fraction and longest missing run. |

## Derived Metrics

`compute_season_metrics()` appends annual Wet/Dry totals and counts to each row.

```python
from hydroseason import compute_season_metrics

result = compute_season_metrics(result, value_col="Rainfall_mm")
```

`compute_annual_spi_categories()` appends annual rainfall SPI z-score (`Annual_SPI`), wet/regular/dry year class (`Year_Class_SPI`), and dry-month drought bin (`Drought_Category`). `Annual_SPI` computed from hydrological-year rainfall totals using sample standard deviation (`ddof=1`). Runs automatically inside `classify_rainfall()` for rainfall workflows.

```python
from hydroseason.metrics import compute_annual_spi_categories

result = compute_annual_spi_categories(result, value_col="Rainfall_mm")
```

`compute_end_dry_metrics()` appends end-of-dry state variables by hydrological year. `terminal_minimum` anchor useful when final dry-labelled month has already rebounded from true dry-season minimum.

```python
from hydroseason import compute_end_dry_metrics

result = compute_end_dry_metrics(
    result,
    metric_cols=["wet_area_ha", "npools", "AWMPA"],
    anchor="terminal_minimum",
    anchor_col="wet_area_ha",
    last_n=2,
)
```

## Planned Export Enhancements

Static image export for report figures deferred from first public release. Current export bundle: self-contained interactive HTML plus CSV/JSON; PNG/SVG export can be added once image backend, browser requirements, and figure sizing defaults settled.
