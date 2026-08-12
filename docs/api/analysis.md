# Analysis

Regime assessment, catchment routing, hydrological-year detection, wet
events, and dynamic hydrological state. See
[Which route did my catchment take?](../guide.md#which-route-did-my-catchment-take)
and [Dynamic Hydrological State](../hydrological-state.md) for narrative
context.

## Catchment Routing (start here)

::: hydroseason._catchment
    options:
      members:
        - CatchmentAnalysis
        - analyze_catchment
      show_root_heading: true
      show_source: false
      heading_level: 3

## Regime Assessment

### Annual timing evidence

`WaterRegimeAssessment` and `CatchmentAnalysis.summary_row()` expose the
following peak and trough timing fields. They are calculated from one peak and
one trough month in each qualifying year (at least `min_months_per_year`,
default 9, usable months). `n_timing_years` is a count of **years**, not
months.

| Field | Units / range | `None` or zero when | Meaning |
|---|---|---|---|
| `amplitude_snr` | Unitless, >=0 (may be `inf`) | `0.0` for insufficient records | Climatological amplitude divided by mean within-month interannual SD. |
| `peak_timing_concentration`, `trough_timing_concentration` | Unitless mean resultant length, 0–1 | `None` for insufficient records | Concentration of annual peak/trough months. |
| `*_timing_concentration_ci_low`, `*_ci_high` | Unitless 0–1 | `None` for insufficient records | Percentile 95% bootstrap bounds for the corresponding `R`. |
| `peak_timing_uniformity_p`, `trough_timing_uniformity_p` | Probability 0–1 | `None` for insufficient records | Deterministic Monte Carlo Kuiper p-value for the discrete 12-month uniform null. |
| `peak_phase_iqr_months`, `trough_phase_iqr_months` | Months, 0–12 approximately | `None` when fewer than four timings or insufficient | Circular IQR; descriptive only and never a regime decision. |
| `n_timing_years` | Integer >=0 years | `0` for insufficient records | Number of qualifying annual timing observations. |
| `climatological_peak_month`, `climatological_trough_month` | Calendar month 1–12 | `None` for aseasonal/insufficient records | Pooled monthly-climatology extrema when the record supports reporting them. |

The classifier uses peak evidence: seasonal requires SNR >= 2.0 and peak `R`
CI low >= 0.70; aseasonal is SNR < 0.70 or a peak Kuiper p >= 0.10 with at
least 10 timing years; marginal is otherwise; fewer than five usable annual
timings is insufficient. Trough `R` CI low >= 0.70 separately authorises
per-year boundaries. `R` can be small because of cancellation by bimodal
timing, so the Kuiper result is a complement rather than a replacement.

::: hydroseason._regime
    options:
      members:
        - Regime
        - WaterRegimeAssessment
        - assess_water_regime
      show_root_heading: true
      show_source: false
      heading_level: 3

## Wet Events and Low Spells

::: hydroseason._events
    options:
      members:
        - WaterEventResult
        - extract_water_events
      show_root_heading: true
      show_source: false
      heading_level: 3

## Hydrological-Year Detection Core

::: hydroseason.hydro_year
    options:
      members:
        - HydroYearConfig
        - detect_hydrological_years
        - label_hydrological_months
        - monthly_water_extent
        - suggest_hydro_year_config
      show_root_heading: true
      show_source: false
      heading_level: 3

## Dynamic Hydrological State

::: hydroseason.hydrological_state
    options:
      members:
        - DynamicHydroYearConfig
        - HydrologicalStateResult
        - SeasonalPatternResult
        - analyze_hydrological_state
        - detect_dynamic_hydrological_years
        - suggest_dynamic_hydro_year_config
        - classify_seasonal_pattern
        - classify_annual_surface_water_condition
        - compute_monthly_surface_water_condition
        - aggregate_basin_monthly_extent
      show_root_heading: true
      show_source: false
      heading_level: 3
