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
