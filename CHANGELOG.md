# Changelog

All notable changes to HydroSeason are documented here. This project follows
[Semantic Versioning](https://semver.org/).

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
