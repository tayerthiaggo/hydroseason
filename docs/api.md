# API Reference

Public symbols re-exported from `hydroseason` and `hydroseason.io`.
Internals (`hydroseason._*`) are not part of the stable public API surface.

## Package Top-Level Exports

::: hydroseason
    options:
      members: true
      show_root_heading: true
      show_source: false
      heading_level: 2

## Detection Core

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
      heading_level: 2

## Loaders, DEA, and Cache Surfaces

::: hydroseason.io
    options:
      members:
        - load_aoi
        - load_extent_csv
        - load_monthly_masks
        - load_monthly_masks_zarr
        - load_wofs_from_stac
        - load_wofs_monthly_extent
        - complete_monthly_axis
        - open_wo_statistics
        - build_wet_planning_footprint
        - WetPlanningFootprint
        - acquire_wofs_cache
        - open_completed_mask_cache
        - open_completed_extent_counts
        - open_completed_dual_extent_counts
        - verify_cache_footprints
        - WOfSCacheHandle
      show_root_heading: true
      show_source: false
      heading_level: 2

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
      heading_level: 2

## Regime, Events, and Catchment Routing

::: hydroseason._regime
    options:
      members:
        - Regime
        - WaterRegimeAssessment
        - assess_water_regime
      show_root_heading: true
      show_source: false
      heading_level: 2

::: hydroseason._events
    options:
      members:
        - WaterEventResult
        - extract_water_events
      show_root_heading: true
      show_source: false
      heading_level: 2

::: hydroseason._catchment
    options:
      members:
        - CatchmentAnalysis
        - analyze_catchment
      show_root_heading: true
      show_source: false
      heading_level: 2

## HTML Report and CSV Bundle

::: hydroseason.report
    options:
      members:
        - generate_catchment_report
        - generate_html_report
        - CatchmentReportPaths
      show_root_heading: true
      show_source: false
      heading_level: 2
