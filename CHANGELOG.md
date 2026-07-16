# Changelog

All notable changes to HydroSeason are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Robust-extrema trough/peak boundary detector (`detector="robust_extrema"`,
  the new default) on `detect_dynamic_hydrological_years`, gated on real
  Fitzroy/Kimberley and Gilbert River evidence. It identifies the raw observed
  extremum in each year's expected window plus its contiguous "equivalent low
  run", then a sequence-consistent optimizer (`select_boundary_sequence`) may
  select another month from within that same run to keep consecutive cycle
  lengths coherent; a raw observed extremum is never silently replaced.
- New additive diagnostic columns on the annual output for both raw/selected
  boundary auditability and confidence grading: `raw_trough_month`,
  `raw_trough_extent_pct`, `raw_peak_month`, `raw_peak_extent_pct`,
  `low_run_start_month`, `low_run_end_month`, `window_status`,
  `selection_status`, `selection_support`, `window_n_expected`,
  `window_n_usable`, `peak_selection_status`, `peak_selection_support`, and
  `phase_shift_months`. `selection_support` is a 0-1 quality grade, not yet a
  calibrated probability.
- Experimental, opt-in semi-Markov boundary challenger
  (`detector="semi_markov"`, a four-state hidden semi-Markov model) selectable
  via the same `DynamicHydroYearConfig.detector` field, producing the same
  output schema as the default detector. It remains experimental and is
  **not** promoted to default: its own promotion gate
  (`tests/test_detector_comparison.py::test_semi_markov_promotion_gate`) did
  not pass on available fixtures.

### Deprecated
- `DynamicHydroYearConfig.sustained_rise_months`,
  `pulse_rejection_window_months`, and `dry_plateau_rule="last_before_confirmed_recovery"`
  are deprecated and emit `DeprecationWarning`. They are retained, functional,
  for one minor release for backward compatibility, but are ignored by the new
  default `robust_extrema` detector. The new default `dry_plateau_rule` is
  `"raw_minimum"`.

### Changed (breaking)
- **Re-platformed from rainfall-first to remote-sensing (water-mask) first.**
  Rainfall-based season/hydro-year detection did not generalize well across
  catchments in practice. The public API is now a source-agnostic hydro-year
  detection engine driven by monthly water-extent, ported from
  WaterMask-TSFill: `HydroYearConfig`, `detect_hydrological_years`,
  `label_hydrological_months`, `monthly_water_extent`, plus loaders
  (`load_aoi`, `load_wofs_from_stac`, `load_monthly_masks`,
  `load_monthly_masks_zarr`, `load_extent_csv`, `complete_monthly_axis`).
  Three input paths are supported: extent CSV, generic binary/canonical
  water-mask rasters (incl. Zarr cubes), and WOfS/STAC.
- Core runtime dependencies are now only `pandas`/`numpy`; raster/STAC
  dependencies moved to the `raster`/`stac`/`all` extras.

### Removed
- All rainfall-based modules, CLI, pandas accessor, HTML report, and rainfall
  fetchers (CHIRPS/SILO/ERA5/BoM) were removed from `main`. The previous
  rainfall implementation is preserved, unmodified, on the `legacy/rainfall`
  branch (tag `v0-rainfall-legacy`).

## [0.1.0] — 2026-06-02

First public release.

### Added
- Rainfall-based Wet/Dry season and hydrological-year delineation
  (`classify_rainfall`), building upon and extending the workflow introduced
  in Tayer et al. (2026).
- Adaptive parameter resolution: `smooth_window`, `min_core_length`, and
  `onset_window_months` resolve from the circular concentration `R` when left at
  their sentinel defaults; explicit overrides always take precedence.
- Circular-climatology fixed-season detection (default) with a legacy KMeans
  method retained for parity.
- STL seasonality strength and Walsh-Lawler Seasonality Index diagnostics, with a
  rainfall-SI override for borderline monsoonal regimes.
- Pandas `df.hydroseason` accessor for inline workflows.
- YAML-driven CLI (`hydroseason run | demo | fetch | rainfall`) with a
  `--version` flag.
- Local rainfall readers for BoM and SILO formats (`read_rainfall`).
- ERA5 and SILO AOI-averaged monthly rainfall fetch helpers.
- Interactive Plotly plots and a self-contained HTML report
  (`generate_html_report`, `export_bundle`).
- Validation with imputation controls, data-confidence reporting, and a
  diagnostics sidecar (`<output>.HydroSeason.json`).
- MkDocs Material documentation site.

### Changed
- Validation errors are now more actionable (missing-column errors list the
  available columns; conflicting-duplicate errors show example dates).

### Notes for advanced users (breaking)
- Algorithm building blocks are no longer re-exported from the top-level
  package. Import them from their submodules instead:
  - `circular_climatology`, `circular_stats`, `CircularStats` →
    `hydroseason.fixed_season`
  - `segment_main_wet_season_fixed_threshold`,
    `harmonize_with_zero_preservation`, `refine_season_tails` →
    `hydroseason.dynamic_season`
  - `PLOTLY_CONFIG` → `hydroseason.plot`
- Removed the unused `matplotlib` runtime dependency.

[0.1.0]: https://github.com/tayerthiaggo/hydroseason/releases/tag/v0.1.0
