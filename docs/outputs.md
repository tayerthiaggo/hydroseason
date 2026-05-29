# Outputs & Metrics

## Pipeline Artifacts

`delineate_monthly_dataframe()` returns `PipelineArtifacts`:

| Attribute | Description |
| --- | --- |
| `result` | Main labelled monthly DataFrame. |
| `fixed_monthly` | Twelve-row climatology table with baseline season labels. |
| `wet_boundaries` | Per-hydrological-year wet-season boundaries for seasonal records, or `None`. |
| `seasonality` | STL, Walsh-Lawler SI, and regime classification result. |
| `diagnostics` | Dataclass with thresholds, method choices, validation warnings, and record counts. |

## Result Columns

The result preserves the input columns and appends hydrological labels and diagnostics.

| Column | Description |
| --- | --- |
| `SeasonType` | `Wet`, `Dry`, or `Unclassified`. |
| `SeasonShift` | `True` where `SeasonType` changes from the previous row. |
| `Hydro_Year` | Dynamic hydrological year using the ending-year convention. |
| `Hydro_Year_fixed` | Baseline hydrological year from the fixed climatological start month. |
| `Seasonality_SI` | Walsh-Lawler Seasonality Index copied onto each row. |
| `Seasonality_STL` | STL seasonality strength copied onto each row. |
| `Seasonality_Regime` | Final detected regime copied onto each row. |
| `Imputed` | `True` for missing months filled by validation using calendar-month climatological means. |
| `wet_total`, `dry_total` | Annual wet/dry totals for the default rainfall column. |
| `wet_month_count`, `dry_month_count` | Annual wet/dry month counts. |
| `dry_event_count` | Dry-season months with values above `nonzero_threshold`. |
| `Rain_Smoothed` | Three-month centred rolling-mean rainfall (alias of `Smoothed`, rainfall workflow only). |
| `Rain_wet_season_mm`, `Rain_dry_season_mm` | Per-hydro-year wet/dry rainfall totals (Tayer et al. 2026 aliases). |
| `Dry_month_count`, `Dry_season_rain_count` | Per-hydro-year dry-month and rainy-dry-month counts (Tayer et al. 2026 aliases). |
| `Annual_SPI` | Z-score of annual rainfall across the record (rainfall workflow). |
| `Year_Class_SPI` | Annual class from `Annual_SPI`: `Dry` (SPI < \u22121), `Regular` (\u22121 \u2264 SPI \u2264 +1), `Wet` (SPI > +1). |
| `Drought_Category` | Categorical bin from `Dry_month_count`: `No dry` (0), `Minimal` (1\u20132), `Regular` (3\u20136), `Prolonged` (\u22657). |

## Diagnostics

| Field | Description |
| --- | --- |
| `regime` | `seasonal`, `borderline`, or `non_seasonal`. |
| `regime_source` | `stl` or `rainfall_si_override`. |
| `stl_strength` | STL seasonal strength `F_S`. |
| `walsh_lawler_si` | Walsh-Lawler Seasonality Index. |
| `hydro_year_start_month` | Fixed hydrological-year start month, 1 to 12. |
| `fallback_month_used` | Fallback month applied when dynamic year continuity needs one. |
| `threshold_firstpass` | First-pass wet-season threshold. |
| `threshold_secondpass` | Tail-refinement threshold. |
| `smooth_window_used` | Resolved centred smoothing window used by the seasonal pipeline. |
| `min_core_length_used` | Resolved minimum wet-core length required to cross fixed hydrological-year boundaries. |
| `onset_window_months_used` | Resolved onset acceptance window; `null` means disabled. |
| `core_climatology_floor` | Site-scaled floor applied to first-pass wet-core detection. |
| `shoulder_climatology_floor` | Site-scaled floor applied to shoulder absorption. |
| `shoulder_residual_threshold` | Positive STL-residual threshold used to reject isolated shoulder storm anomalies; `null` means disabled or unavailable. |
| `validation_warnings` | Data-quality warnings produced during validation. |
| `n_imputed` | Number of missing months filled during validation. |
| `n_unimputed` | Number of missing months left unresolved because validation refused or failed to impute them. |
| `max_consecutive_missing` | Longest consecutive missing-month run detected before imputation. |
| `data_confidence` | `high`, `medium`, or `low`, based on missing fraction and longest missing run. |

## Derived Metrics

`compute_season_metrics()` appends annual Wet/Dry totals and counts to each row of the input DataFrame.

```python
from hydroseason import compute_season_metrics

result = compute_season_metrics(result, value_col="Rainfall_mm")
```

`compute_annual_spi_categories()` appends the annual rainfall SPI z-score (`Annual_SPI`), the wet/regular/dry year class (`Year_Class_SPI`), and the dry-month drought bin (`Drought_Category`). This step runs automatically inside `delineate_monthly_dataframe()` for rainfall workflows.

```python
from hydroseason.metrics import compute_annual_spi_categories

result = compute_annual_spi_categories(result, value_col="Rainfall_mm")
```

`compute_end_dry_metrics()` appends end-of-dry state variables by hydrological year. The `terminal_minimum` anchor is useful when a final dry-labelled month has already rebounded from the true dry-season minimum.

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

