# Loading Data

Loaders, DEA/STAC acquisition, and local cache surfaces. See [Usage Guide: The four ways to run it](../guide.md#the-four-ways-to-run-it)
and [Advanced: DEA acquisition internals](../guide.md#advanced-dea-acquisition-internals)
for narrative context before diving into individual signatures below.

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
        - probe_wo_statistics_coverage
        - HistoricalWaterMask
        - HistoricalMaskCoverageWarning
        - HistoricalMaskRefreshedWarning
        - build_historical_water_mask
        - load_or_build_historical_water_mask
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

`load_wofs_monthly_extent(..., refresh_historical_mask=True)` and
`load_or_build_historical_water_mask(..., refresh_historical_mask=True)` refresh
a compatible cache hit when DEA advertises wider coverage. Pass `False` to pin
the compatible cached vintage. A coverage overhang emits
`HistoricalMaskCoverageWarning`; an adopted wider vintage emits
`HistoricalMaskRefreshedWarning`. Use `probe_wo_statistics_coverage` for the
same metadata-only coverage check without loading the statistics raster.
