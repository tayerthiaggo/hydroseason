# Preflight

Whether an AOI's record can support the analysis, decided before any monthly
acquisition. See [Preflight: what the record can support](../preflight.md)
for narrative context and the current calibration status of the threshold
profiles.

## Entry point

::: hydroseason.preflight
    options:
      members:
        - preflight
        - PreflightProfileUnavailable
      show_root_heading: true
      show_source: false
      heading_level: 3

## Results

::: hydroseason._preflight_feasibility
    options:
      members:
        - FeasibilityResult
      show_root_heading: true
      show_source: false
      heading_level: 3

::: hydroseason._preflight_types
    options:
      members:
        - PreflightResult
        - PreflightThresholds
      show_root_heading: true
      show_source: false
      heading_level: 3

## Workflow integration

`run_hydroseason` runs the recurrent-water screen on every regular DEA run.
A rejection is raised as `HydroSeasonPreflightError`, carrying the
`FeasibilityResult` as `.result`; a successful run exposes the same object as
`HydroSeasonRunResult.preflight_result`.

::: hydroseason.workflow
    options:
      members:
        - HydroSeasonPreflightError
      show_root_heading: true
      show_source: false
      heading_level: 3
