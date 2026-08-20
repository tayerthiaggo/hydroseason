# Changelog

All notable changes to HydroSeason are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-08-20

### Added
- **Multi-AOI batch orchestration**: `run_hydroseason_many`, `HydroSeasonBatchResult`,
  `HydroSeasonAOIOutcome`, and `HydroSeasonBatchError` for executing independent
  DEA/STAC or local analyses row-by-row across vector AOIs with isolated output
  directories.
- **Memory-bounded batch scheduler**: `_batch_scheduler` dynamically budgets
  concurrency and admits work based on available RAM (`workers="auto"` uses up to
  2 workers and 80% available RAM).
- **Self-contained AOI boundary map rendering**: `AOIContext`, `build_aoi_context`,
  `render_aoi_map_html`, and `display_aoi_map` for accessible, dependency-light
  inline HTML map generation with vendored Leaflet CSS/JS.
- **Seasonality and circular timing**: Refined circular timing and Kuiper
  uniformity statistics for unimodal vs complex/irregular seasonality classification.
- **Process-isolated CLI**: `hydroseason run` for running the orchestrator in its
  own process with `--cache-dir` resumption support, and `hydroseason doctor` for
  probing the Python environment, dependencies, and netCDF4/NumPy ABI compatibility.
- **Five-step progress reporting**: `ProgressCallback`, `StepProgressEvent`, and
  terminal progress indicators in `run_hydroseason`.
- **Python 3.13 support**: Python 3.13 added to CI test matrices and package
  classifiers, with `requires-python = ">=3.10,<3.14"`.
- `HistoricalMaskCoverageWarning`; `HistoricalMaskRefreshedWarning`;
  automatic adoption of a refreshed statistics vintage when a run's window
  overhangs its cached mask's coverage, with the denominator delta reported
  (`refresh_historical_mask=False` to pin); `probe_wo_statistics_coverage`;
  `HydroSeasonRunResult.warnings` now carries water-input provenance
  notices; `load_wofs_monthly_extent(on_warning=...)` and
  `resolve_water_input(on_warning=...)`. `load_or_build_historical_water_mask`
  gains a new keyword-only `end_date: str | None = None` parameter, which is
  what triggers the refresh check when supplied; direct callers of
  `load_or_build_historical_water_mask` (as opposed to `run_hydroseason`,
  which supplies it automatically) must pass it to opt into the refresh
  behavior, and the default `None` preserves the prior strict-pinning
  behavior unchanged.

### Changed
- Historical water-mask coverage no longer gates whether a run can proceed.
  A run whose requested window falls outside the statistics product's
  recorded `[coverage_start, coverage_end]` now succeeds with a
  `HistoricalMaskCoverageWarning` instead of raising
  `HistoricalWaterMaskUnavailable`. Two user-visible consequences: (a)
  previously-failing requests now succeed; (b) a request past
  `coverage_end` cannot count water first inundated after that date.
  Supplying a precomputed `historical_water_mask=` whose coverage falls
  short is likewise no longer a `ValueError`.
- Adopting a refreshed statistics vintage (see `### Added` above) changes
  `n_aoi` and therefore `extent_pct` across the entire record, not only the
  newly-covered months. This is the change most likely to surprise someone
  comparing two runs.

### Fixed
- Raster and STAC installs now constrain `numcodecs<0.16` while Zarr 2.x is
  supported, preventing the import failure caused when older Zarr 2 releases
  resolve against NumCodecs 0.16's removed compatibility aliases.
- Suppressed rasterio's `NotGeoreferencedWarning` during CLI runs on
  STAC-georeferenced DEA WOfS assets.
- Declared `*.css` in `MANIFEST.in` to ensure vendored Leaflet stylesheet
  inclusion in source distribution archives.

### Removed
- **Breaking for direct callers.** The `analysis_end` keyword is gone from
  `build_historical_water_mask`, `read_historical_water_mask`, and
  `load_or_build_historical_water_mask`. The mask is an all-time footprint;
  nothing in its construction or retrieval ever depended on the requested
  window, and the parameter only fed the coverage gate this release
  removes. Callers should delete the argument — there is no replacement and
  no behavior to preserve. This is a signature break shipped in a patch
  release, permitted under SemVer clause 4 (pre-1.0); both
  `build_historical_water_mask` and `load_or_build_historical_water_mask`
  are re-exported from the package root.
- Removed precursor method paper citation from `CITATION.cff`, `README.md`, and
  `docs/citation.md` in favor of software-only citation pending dedicated method
  paper publication.

## [0.1.0] - 2026-08-10

First public release: the remote-sensing-first rewrite of HydroSeason.

### Added
- Public `run_hydroseason` orchestration for extent CSV/DataFrame, canonical
  NetCDF/Zarr/xarray masks, or DEA WOfS fetching. Optional supplied-CSV or
  SILO rainfall is ancillary and non-fatal, enriches only the monthly CSV,
  and adds a collapsible rainfall-regime comparison to the HTML report
  without changing water routing, boundaries, phases, events, or low spells.
- Robust-extrema trough/peak boundary detector (`detector="robust_extrema"`,
  the new default) on `detect_dynamic_hydrological_years`, gated on real
  Fitzroy/Kimberley and Gilbert River evidence. It identifies the raw observed
  extremum in each year's expected window plus its contiguous "equivalent low
  run". Public trough selection preserves the true observed minimum; only
  exact-value ties may receive `coherence_adjusted` provenance for cycle
  consistency. Observed high-invalid extrema remain visible but are marked
  `low_quality`.
- New additive diagnostic columns on the annual output for both raw/selected
  boundary auditability and confidence grading: `raw_trough_month`,
  `raw_trough_extent_pct`, `raw_peak_month`, `raw_peak_extent_pct`,
  `low_run_start_month`, `low_run_end_month`, `window_status`,
  `selection_status`, `selection_support`, `window_n_expected`,
  `window_n_usable`, `peak_selection_status`, `peak_selection_support`, and
  `phase_shift_months`. `selection_support` is a 0-1 quality grade, not yet a
  calibrated probability.
- Experimental, internal-only semi-Markov boundary challenger (a four-state
  hidden semi-Markov model), reachable only through the underscore-prefixed
  `_detect_dynamic_hydrological_years_experimental` dispatcher used by the
  experimental promotion-gate comparison harness
  (`tests/test_detector_comparison.py::test_semi_markov_promotion_gate`). It
  is **not** selectable through the public `DynamicHydroYearConfig.detector`
  field (which accepts only `"robust_extrema"` and rejects anything else at
  construction), is **not** promoted to default, and is not part of the
  released public API.
- Robust-anchored monthly phases, `phase_model="rule_based"`, **the default**
  (pass `phase_model="none"` to disable). The labels are descriptive
  (`recovery`, `wet`, `recession`, `dry`), use the existing robust extrema
  annual cycles as fixed anchors, and do not change annual hydrological-year
  outputs. `monthly_phase` is kept separate from `monthly_condition`; its
  confidence values are quality grades, not calibrated probabilities.
  Constrained semi-Markov phase labeling remains post-release research and is
  not a hidden released mode.
- Marginal `analyze_catchment` routing now imposes a fixed climatological
  window for **every** climatological peak phase (all twelve calendar months),
  not only tropical year-boundary wet seasons. Emitted rows remain labelled
  `boundary_basis="imposed_fixed_window"` with `state=None`.
- Observed maxima and minima from partially masked months remain visible for
  review, but are marked `selection_status="low_quality"`; low-quality peaks
  make annual rows provisional and prevent condition-baseline activation.
- `quality_policy="flag"` now propagates through catchment/report exports: all
  finite, partially observed months remain usable for cycle mapping, while
  invalid coverage is retained as a low-confidence/provisional diagnostic.
  Public trough sequence selection now preserves the true observed minimum,
  allowing only exact-value ties to receive `coherence_adjusted` provenance.

### Fixed
- **DEA WOfS fetching for an AOI no longer fails with a grid-misalignment
  error.** `run_hydroseason(aoi=..., start_date=..., end_date=...)` and
  `load_wofs_monthly_extent` left `resolution` unset by default, which made
  the monthly WOfS load fall back to the STAC items' own native pixel
  alignment while the historical water mask was always built on an
  explicitly-anchored grid. The two did not line up, raising
  `GeoreferencingError: historical water mask transform ... does not match
  raster transform ...`. The monthly load is now pinned to the historical
  mask's own grid whenever the caller does not request a resolution; an
  explicit `resolution` is still honoured unchanged.
- `build_historical_water_mask` used the `.rio` accessor without importing
  `rioxarray` itself, so it only worked when another module happened to
  import it first, and crashed in a fresh process.
- **Bimodal/complex catchments no longer crash with a `KeyError` during
  hydrological-year assembly.** `_secondary_extrema` looked its primary
  peak and trough up in the cycle's *usable* months with an exact index
  lookup, but the peak may legitimately be a `low_quality` month and the
  trough is the cycle's end month — neither is guaranteed to survive the
  usability filter. Secondary extrema are now positioned against the series
  they are searched in, so the "at least 2 months clear of the primary
  extremum" rule still applies when that month was filtered out. Reachable
  only for `pattern="bimodal_or_complex"`, which is why no existing fixture
  covered it; observed on a live DEA WOfS fetch of the Fitzroy/Kimberley AOI.
- **`open_wo_statistics` no longer re-arms a broken PROJ database on the
  lazy cube it returns.** It restored the caller's `PROJ_LIB`/`PROJ_DATA` on
  the way out, but the cube it returns is lazy — the reprojection that reads
  that PROJ database runs later, on compute. On a machine with a system-wide
  `PROJ_LIB` (a PostGIS install sets one on Windows) pointing at a `proj.db`
  too old for `pyproj`, every lazy read then failed with
  `pyproj.exceptions.ProjError: Error creating Transformer from CRS`. The
  known-good database the loader installs is now left in place; the GDAL/AWS
  variables are still restored, since `odc.stac.configure_rio` carries those
  into the lazy reads independently.

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
- Rainfall is ancillary only: `run_hydroseason` can fetch or accept rainfall
  as additive context, but rainfall never sets water routing, boundaries,
  phases, events, or low spells.
