# Changelog

All notable changes to HydroSeason are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-08-31

### Added
- **Preflight**: `preflight`, `PreflightResult`, `PreflightThresholds`,
  `FeasibilityResult`, `PreflightProfileUnavailable`, and
  `HydroSeasonPreflightError` report whether an AOI's record can support the
  analysis before any monthly acquisition is paid for. Regular DEA runs apply
  the WOfS recurrent-water screen automatically (`>=10%` frequency with the
  established contiguous-cluster rule), hand the same Statistics read on as
  the reusable maximum-water mask, and raise `HydroSeasonPreflightError` for
  an AOI with no recurrent water. A Statistics outage never becomes a
  no-water result: `run_hydroseason` warns and continues, and the standalone
  `feasibility_only=True` path re-raises instead. The broader
  detection-support decisions (`candidate`, `monthly`, `timing`) are
  available under `thresholds="diagnostic"` or a caller-supplied
  `PreflightThresholds`; `thresholds="default"` raises
  `PreflightProfileUnavailable` because the reviewed profile is not
  calibrated yet. Documented in
  [Preflight](https://tayerthiaggo.github.io/hydroseason/preflight/).
- `HistoricalMaskRefreshedWarning` is now re-exported from the top-level
  package alongside `HistoricalMaskCoverageWarning`, so both mask-provenance
  warnings can be filtered without importing `hydroseason.io`.
- `hydroseason doctor` now probes `scipy` and `dask_image` (both required by
  the recurrent-water screen) and `psutil` (the batch scheduler's memory
  admission), so an incomplete raster/STAC install is reported before a run
  fails on the missing import rather than after.
- **Calibrated Scientific Defaults**: Frozen defaults for `EvidenceThresholds`, `RecoverabilityThresholds`, and `PhaseThresholds` derived from lexicographic optimization across 190,080 evidence grid points and 144 phase grid points over 5,000 synthetic calibration seeds (`10000..14999`).
- **Untouched Validation Report**: Independent validation across 5,000 validation seeds (`20000..24999`) under frozen constants, documenting evidence confusion matrices, false annualisation rates with Wilson score intervals, stratified length performance, boundary recoverability MAE and coverage, phase macro-accuracy, and sensitivity matrices (`docs/calibration/2026-08-21-validation-report.json`).
- **Calibration Pipeline and Gating**: `scripts/run_calibration.py` with multi-worker ProcessPool execution, SHA-256 parameter and generator fingerprinting, and automated staleness assertion in `tests/test_release_metadata.py`.
- **Distribution Packaging**: Calibration and validation JSON reports bundled into Python wheel (`share/hydroseason/calibration/`) and source distributions (`docs/calibration/`).

### Changed
- Restored conservative dynamic-year defaults (`trough_search_radius_months=3`,
  `min_usable_months_per_cycle=8`) and added an anchored adaptive retry for
  short interior cycles, so isolated six-month years can be classified without
  widening neighbouring years or crossing data gaps.
- Uncached untiled DEA extent reads now overlap independent calendar years with
  two workers by default; `year_workers=1` retains serial execution.
- `DynamicHydroYearConfig` and `assess_water_regime` now use calibrated `EVIDENCE_DEFAULTS`, `RECOVERABILITY_DEFAULTS`, and `PHASE_DEFAULTS` by default.
- Removed legacy uncalibrated bridge and fallback classifications.
- Clarified four distinct uncertainty concepts across documentation, stating that `seasonal_cv_skill` is post-selection cross-validation skill and distinguishing empirical benchmark error bounds from real-world field validation.

### Fixed
- `uv.lock` now records `scipy` and `dask-image`. Both were already declared
  in the `raster` extra, but an environment installed from the lockfile
  omitted them, so the recurrent-water screen failed with
  `ModuleNotFoundError` at run time.
- `import hydroseason` no longer imports `xarray` eagerly. It is resolved on
  first use by the raster-backed monthly inputs that need it, which is the
  only path that ever did.
- Regenerated the checked case-study results, the documentation example
  reports, and `notebooks/01_quickstart.ipynb` against the current detection
  defaults and two-phase (`rising`/`receding`) vocabulary. The example
  reports and the quickstart notebook's stored output still showed the
  superseded `recovery`/`recession` labels.
- **Calibration constants re-derived (`0.2.0-audit.1` -> `0.2.0-audit.2`).**
  `4036213` restructured the calibration objective -- folding `_evidence` and
  `_boundary_recoverability` into `_calibration.py` -- without re-running the
  search, so `audit.1`'s constants and every metric printed beside them
  described a superseded implementation. The recorded fingerprint was edited
  by hand in both directions (`4036213` and `7e65985`) rather than
  regenerated, which kept the staleness test quiet. Re-running the 5,000-seed
  calibration partition on the current source moves two evidence thresholds:
  `seasonal_cv_skill` `0.8` -> `0.3` and `periodicity_alpha` `0.1` -> `0.025`.
  Recoverability and phase constants are unchanged. Released behaviour is
  unaffected: evidence and recoverability are scoped
  `experimental_challenger` and do not drive routing, the authoritative
  `PHASE_DEFAULTS` did not move, and every checked case-study result is
  byte-identical across the change. The validation report was regenerated
  against the new constants. Its headline figures move materially, but only
  some of that is the recalibration, and the two causes should not be
  conflated:

  *Changed by the new constants.* Every figure that flows through the
  publish decision. False annualisation falls to `0.0` (20 events -> 0,
  Wilson high `0.0108` -> `0.0013`), correct abstention rises slightly, and
  per-year route coverage falls at every record length -- to zero below ten
  years, where `min_timing_years=10` makes the challenger abstain outright.
  The challenger now commits less often and is not wrong when it does.

  *Not changed by the new constants.* Boundary recoverability
  (within-one-month `0.837` -> `0.586`, MAE `0.78` -> `1.29` months, p90 `2`
  -> `3`) and phase accuracy (`0.732` -> `0.719`). These are computed from
  ground-truth boundary errors with no threshold in the path, and are
  byte-identical when the same cache is evaluated under the old and new
  constants. They did not regress; they had simply never been measured
  against this implementation before. The old figures described the
  pre-`4036213` code, so the two sets were never comparable -- visible in
  `boundary_metrics.n` moving `29936` -> `30928`, which a fixed truth set
  with cached errors cannot do.

  No documentation quoted any of these values. The result reproduces
  byte-for-byte across independent runs, and the evidence cache is identical
  on Python 3.12 and 3.14, across processes, and under both the serial and
  parallel build paths.
- **`min_timing_years` shipped as 5, overriding the search's own answer of 10.**
  The 190,080-point search reproducibly selects 10: `correct_abstention`
  (favours a higher floor) is pruned before `min_timing_years` is ever
  reached as a tie-break, so a higher floor keeps winning on the search's
  own stated priority order. But a per-record-length sweep shows the floor
  is a hard cliff at its own value with no effect above it -- 10 buys zero
  coverage on 7-30 year records and removes all challenger coverage on 5-9
  year records, while negative-control false annualisation is identical
  (`0.0`) at 5, 7, and 10. `hydroseason/_regime.py`'s released
  `_MIN_USABLE_YEARS=5` answers the same question for the path users
  actually run; a challenger floor of 10 made the experimental second
  opinion stricter than the tool it exists to check, for a benefit that
  does not measurably exist above the floor it would remove. The search and
  its objective are unchanged -- `select_evidence_defaults` still reports
  10, recorded verbatim as `evidence_searched` in the calibration report --
  and `_apply_min_timing_years_override` applies a documented, tested
  override on top, recorded as `evidence_override` alongside the reasoning
  and the false-annualisation comparison at both values. This is a policy
  call about acceptable risk, not a correction to the search.
- **Removed the unreachable four-phase labeller and its calibration.**
  `assign_cycle_relative_phases` (dry/recovery/wet/recession, collapsed to
  rising/receding) had no caller: `assign_monthly_phases` only ever
  dispatched to `"none"` or `"two_phase"`, and `"four_phase"` has mapped to
  `"two_phase"` with a deprecation warning since before this release. Its
  removal also drops three declared-but-dead export columns
  (`p_rising`, `p_receding`, `phase_stability` -- always NaN, silently
  dropped by every CSV writer) and the `PHASE_DEFAULTS`/`PhaseThresholds`
  calibration: a 144-point grid search, phase evidence cache, and
  `phase_accuracy`/`phase_stability_calibration` validation metrics scoring a
  path nothing could reach. `PHASE_AUTHORITY_SCOPE` was the calibration's only
  `authoritative` scope; both remaining groups (evidence, recoverability) are
  `experimental_challenger`. Released phase labelling is unaffected: two-phase
  `rising`/`receding`, split at the observed peak, is unchanged, and it never
  depended on calibrated constants. Confirmed on a freshly generated report:
  rising/receding remain in the chart traces, legend, table filter, CSV, and
  embedded payload exactly as before.
- **Calibration selector picked from the unpruned candidate set.**
  `select_evidence_defaults` narrowed a `survivors` array through fifteen
  lexicographic pruning stages, then took its answer by sorting
  `candidate_indices` -- still the whole stage-1 set. Every pruning stage was
  dead work, and the counts published as `selection_survivors` described a set
  the selection never used. The stages are not equivalent to the sort:
  `_retain_metric` retains points within `np.isclose` of each stage optimum,
  so a candidate whose routing recall is worse only by float noise stays
  eligible and can win on the next metric, whereas sorting the unpruned set
  applies exact ordering and lets that noise decide the outcome. The pick now
  comes from `survivors`, the surviving count is recorded as
  `final_survivors` rather than asserted, and a regression test requires the
  recorded stages to narrow monotonically. On the shipped cache the corrected
  selector reproduces the same constants.
- The calibration staleness fingerprint no longer hashes the interpreter and
  NumPy/pandas versions. Doing so made it environment-specific, so
  `test_fingerprint_is_current` and `test_calibration_report_is_not_stale`
  could hold on at most one row of a CI matrix spanning Python 3.10-3.13 plus
  the pinned minimum-dependency floor. Those versions are now recorded as
  provenance instead -- `CALIBRATION_ENVIRONMENT` in the generated defaults
  module and `environment` in the calibration report -- and the fingerprint
  tracks only the generator, grids, objectives, seed manifest, and selected
  constants. The shipped constants are unchanged; the recorded fingerprint
  value changes because the scheme did.

### Removed
- Removed the internal-only semi-Markov boundary challenger and promotion-gate
  harness. `robust_extrema` is the only released boundary detector.

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
- **Five-step progress reporting**: `ProgressEvent`, `WorkflowProgress`, and
  `resolve_progress_reporter` in `run_hydroseason`.
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
  hidden semi-Markov model) was included for research comparison only. It was
  **not** selectable through the public `DynamicHydroYearConfig.detector`
  field (which accepted only `"robust_extrema"`), was **not** promoted to
  default, and was not part of the released public API.
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
