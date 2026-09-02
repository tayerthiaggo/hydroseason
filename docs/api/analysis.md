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
| `amplitude_snr` | Unitless, >=0 (finite float) | `0.0` for insufficient records | Climatological amplitude divided by mean within-month interannual SD. |
| `peak_timing_concentration`, `trough_timing_concentration` | Unitless mean resultant length, 0–1 | `None` for insufficient records | Concentration of annual peak/trough months. |
| `*_timing_concentration_ci_low`, `*_ci_high` | Unitless 0–1 | `None` for insufficient records | Percentile 95% bootstrap bounds for the corresponding `R`. |
| `peak_timing_uniformity_p`, `trough_timing_uniformity_p` | p-value 0–1 | `None` for insufficient records | Deterministic Monte Carlo Kuiper p-value for the discrete 12-month uniform null. |
| `peak_phase_iqr_months`, `trough_phase_iqr_months` | Months, 0–12 approximately | `None` when fewer than four timings or insufficient | Circular IQR; descriptive only and never a regime decision. |
| `n_timing_years` | Integer >=0 years | `0` for insufficient records | Number of qualifying annual timing observations. Equals `n_peak_timing_years`; kept as a separate published field from the conservative `min()` used in the route gate. |
| `n_peak_timing_years`, `n_trough_timing_years` | Integer >=0 years | -- | Count of calendar years whose peak/trough extremum is independently identifiable under the calibrated timing-identifiability thresholds. |
| `n_zero_months` | Integer >=0 months | -- | Total usable months with exact-zero observed extent. Descriptive only; never a route or timing predicate. |
| `zero_month_fraction` | Unitless, 0–1 | -- | Fraction of usable months that are exact zero. |
| `n_whole_zero_years` | Integer >=0 years | -- | Count of years whose usable months are all exact zero. Contributes to dry-duration/event summaries but no timing observation. |
| `pixel_support_status` | `"available"` \| `"unavailable"` | -- | Whether pixel counts (`n_water`/`n_valid`/`n_invalid`/`n_aoi`) are present. Percentage-only inputs report `"unavailable"`, and the calibrated `min_peak_water_pixels` threshold is not consulted for them. |
| `timing_evidence` | `"supported"` \| `"insufficient"` \| `"unsupported"` | -- | `insufficient` when `min(n_peak_timing_years, n_trough_timing_years) < min_informative_years`; `unsupported` when established seasonality/uniformity evidence rejects an annual cycle; otherwise `supported`. |
| `climatological_peak_month`, `climatological_trough_month` | Calendar month 1–12 | `None` for aseasonal/insufficient records | Pooled monthly-climatology extrema when the record supports reporting them. |

Public regime assessment and routing operate under the `established_0_2_0` decision policy using exact empirical monthly extrema, circular timing statistics, and calibrated timing-identifiability thresholds. Extent is observed surface-water availability, not rainfall, discharge, storage volume, a climate variable, or natural-condition hydrology. A record's route is `per_year_detection` only when its regime is seasonal or marginal *and* its timing evidence is supported; a seasonal or marginal record with insufficient identifiable timing keeps its regime label but routes to `event_characterisation`. See [Decision Policy](../decision-policy.md) and the [0.2.0 migration notes](../migrations/0.2.0-timing-identifiability.md) for the full contract.

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
