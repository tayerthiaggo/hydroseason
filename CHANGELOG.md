# Changelog

All notable changes to HydroSeason are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-11-11

### Added
- Two input warnings. When pixel counts are supplied with an `extent_pct` that
  disagrees with `100 * n_water / n_valid` (for example a share of the whole
  AOI), the percentage is still replaced by the count-based value, now with a
  warning. When a record has no pixel counts and a cycle's detectability floor
  falls to effectively zero, `analyze_catchment` warns that its
  amplitude-to-floor ratios carry no information. Outputs are unchanged.
- The hydro-years CSV now says why a cycle is partial or provisional and
  whether it anchors the condition baseline: `status_reason`,
  `trough_refinement_status`, `trough_refinement_reason`, `baseline_eligible`
  and `baseline_n` are appended after the existing columns. Readers that
  select columns by name are unaffected. `analysis.hydro_years` also carries
  `baseline_eligible`.
- Report: the timeline for aseasonal records now shades wet events and
  low-extent spells and marks event peaks. Each shading has a legend entry with
  its count that hides and shows it. Seasonal timelines are unchanged.

### Changed
- **Method policy `hydroseason-v0.3.0`** replaces `hydroseason-v0.2.0`, so
  every output carries a new policy id and fingerprint. Six changes; only the
  fifth moves boundaries, dates, peaks, routes or cycle status:
  - The trough timing label now covers the trough boundary. A label that
    singled out a different month (usually a cloudy month before the
    boundary) is widened to cover both and graded by its width, so some
    `point` troughs become `interval`, `broad` or `unresolved` and lose their
    single-month `trough_date`. On real records this affected about 10% of
    `point` troughs on small areas and about 3% on subbasins and tiles.
  - Any dated cycle (`point`, `interval` or `broad`) can anchor the annual
    condition baseline; only `point` cycles could before. About ten times as
    many areas get recharge and refuge labels, and some existing labels and
    percentiles shift.
  - The method fingerprint now covers the timing-identifiability gates, the
    condition-baseline rule, the trough-label rule and the dry-run rule.
  - Each cycle reports where its dry season ends: `dry_run_start_month`,
    `dry_run_end_month`, `rewetting_month`, `dry_run_months` and
    `dry_end_status` on `analysis.hydro_years` (`dry_run_start_date`,
    `dry_run_end_date`, `rewetting_date`, `dry_run_months` and
    `dry_end_status` in the hydro-years CSV, appended after the 0.2.0
    columns). On a flat-bottomed trough the
    boundary can sit months before the dry season ends; the run end is the
    better date for it. `dry_end_status` is `interval` or `censored`, never
    `point`. The report timeline marks it as "Dry Season Ends" (an open
    inverted triangle). The trough boundary marker is renamed from
    "HY End Dry" to "HY Trough" (with "Trough (interval)" and "Trough
    Interval" shading), and the year table's "Dry End" key event and
    "End Dry Month" card become "Trough" and "Trough Month", so only one
    marker reads as the end of the dry season.
  - The year boundary reaches the end of the dry season on records with a
    flat low (the method's definition): the trough search is centred on the
    end of the typical low instead of its first month, and a boundary at the
    end of a dry, zero-extent low is dated from the run end to the month
    before the next peak (`trough_label_basis` = `end_of_dry_run`; never
    `point`). On ephemeral channels boundaries move months later, and with
    them the years, phases and baselines; on 40 grid tiles over the Fitzroy
    catchment (WA), years ending three or more months before the dry season
    fall from 251 to 104, of about 1,600 tile-years. Whole
    catchments and most subbasins are unchanged.
  - The fingerprint also covers the trough search (radii, minimum usable
    months and candidates), the boundary-selection thresholds, the
    peak-quality rule and the trough-refinement level grid. Their values are
    unchanged, so nothing computed changes; the fingerprint is
    `07f1eaa1…` instead of `59756dfe…`.
- **Migration:** trough timing labels, `baseline_eligible`, `baseline_n`, the
  percentiles and the condition labels can differ from 0.2.x, and so can the
  monthly `phase` and `phase_status` in years whose timing label changes. On
  records with a flat low the boundaries, year starts and ends, and some peaks
  also move. Compare files
  across versions only on unchanged columns, and use `method_policy_id` or the
  fingerprint to tell them apart. See "Changes from hydroseason-v0.2.0" in the
  Methods Reference.
- `baseline_n` on `analysis.hydro_years` is now the number of cycles each row
  is ranked against for the full-record and fixed-period baselines. It was
  always 0 there before; rolling baselines are unchanged. No condition label
  changes.
- The guide explains the two dates around the dry-season low
  (`trough_boundary_date`, and the following year's `start_date` one month
  later), recommends passing pixel counts, and says how to limit
  numerical-library threads in your own process pools. The docs no longer
  call the identifiability gates calibrated; they say what the gates were
  checked on.
- The guide has a new section, "Choosing the area to analyse": grid tiles
  behave like subbasins of the same size, small areas date the season less
  consistently, and an aseasonal catchment can contain seasonal subbasins.
  It summarises a study of 1,278 areas over the five case-study catchments
  (`docs/handoff/2026-11-02-spatial-unit-study-results.md`).
- Documented every `status_reason` value and the trough-refinement reason
  codes that were missing from `docs/report-columns.md` (including the three
  atomic-rollback codes, `essential_low_quality_recovery`, `unknown_quality`,
  `post_gap_return_to_low_state`, `no_defensible_low_state`,
  `no_converged_candidate` and `not_requested`), why a cleanly selected
  boundary can stay provisional after pass-2 refinement, and why
  `analyze_hydrological_state` can raise on a record that `analyze_catchment`
  routes as seasonal.
- Documented what the advisory pattern labels mean (`low_variability` is a
  statement about the fitted curve against `measurement_tolerance_pct`, not
  about observed variability), when `suggest_dynamic_hydro_year_config` raises,
  which `SeasonalPatternResult` fields are sentinels, and how a record with a
  recurrent trough but irregular peaks is reported by `assess_water_regime`.
- The docs and the report's point-identifiable card no longer say a `point`
  timing status "resolves to an exact month". It means one month stood out by
  more than the detectability floor.
  For the trough, only the months from the cycle's peak to the boundary are
  compared, and the docs now say so. In three tests on records with known
  answers (synthetic seasons, and seasons injected into real records), many `point`
  troughs on weak cycles were more than a month off, and troughs at the end of
  long, flat recessions were dated early. The later tests, on fresh records,
  found that neither widening the trough tolerance nor also comparing the
  months after the trough fixes this, so the method is unchanged. The guide
  says how far to trust a single trough month.
  The docs now list
  the `broad` trough status and say why the default identifiability gates
  stay: looser gates repeated as well between two halves of each test
  window's pixels, but the dates they added were less accurate on records
  with known answers. Outputs are unchanged.
- Monthly `phase_status` is `interval_boundary` in years whose timing is
  `broad` as well as `interval`; `broad` years read `ok` or `provisional`
  before, although their boundary is less certain than an `interval` one.
- `composite_bundle` accepts only `"single_mask"` and
  `"dual_composite_v1"`; any other value raises `ValueError` instead of
  silently acting as `"single_mask"`. Caches written with the old `"legacy"`
  value stay valid.
- `measurement_tolerance_pct` defaults to 0.0 everywhere, as in
  `analyze_catchment`. `DynamicHydroYearConfig`, `classify_seasonal_pattern`
  and `assess_timing_identifiability` defaulted to 1.0, so a direct call could
  disagree with `analyze_catchment` (on Fitzroy, 1 of 21 peaks resolved
  instead of 18). In
  `analyze_catchment` only the advisory seasonal pattern changes: on Daly it
  reads `unimodal_annual` instead of `low_variability`.
- Trough refinement is 2–3 times faster (Daly at 30 m: 36 s to 13 s) with
  identical output.
- `generate_catchment_report` and the CLI refuse to overwrite the run's input
  file, or a bundle written for another catchment, with `FileExistsError`.
  While a bundle is being written its manifest reads
  `{"status": "incomplete"}`, so a crash no longer leaves old and new files
  that look complete. A CSV that cannot be written (for example, open in
  Excel) now raises instead of warning and keeping the old file.
- The run manifest records `catchment`, and under `analysis` the
  `measurement_tolerance_pct`, `min_months_per_year`, `n_bootstrap` and
  `quality_policy` used; `CatchmentAnalysis` carries the first three.
  `pass2_abstained_count` counts refinements that ended `unresolved`; it
  was always 0.
- Download caches treat a year as final only when it was written at least
  60 days after its 31 December. Earlier writes are fetched again, so a year
  cached before its last scenes were ingested no longer keeps the gaps for
  good; such caches are rebuilt once. The write time is stored in the cache
  (`written_at` in each year's `complete.json`, a `.written_at` file next to
  each extent CSV), so a copied cache keeps it; caches written before this
  fall back to the file's modification time.
- The cache writer lock is an operating-system file lock, released when the
  process dies. Two processes could both take over a stale lock, and on
  Linux another user's live lock could be taken. NFS shares may not honour
  the lock; keep a shared cache on a local disk or a Windows share.
- `run_hydroseason_many` warns when several AOIs have no `id_col`: they are
  named by row position (`aoi-0001`, ...), so reordering or filtering the AOI
  file and rerunning into the same `output_dir` would write a different
  area's report under an old name.
- The `raster` extra requires `xarray<2026.9`: xarray 2026.9 writes Zarr
  stores only with zarr 3, and the caches use zarr 2.
- Public functions and result classes that had no docstring now have one, and
  docstrings, comments and messages describe current behaviour.
- Resolution case study: the peak and trough timing medians now cover only
  the seasonal catchments; aseasonal catchments, which have no years to time,
  were scored as 100%. The 300 m trough median falls from 95.2% to 85.7%; no
  decision changes. A 30 m year missing at the coarser resolution now counts
  as a miss, and a timing gate with no seasonal catchment fails instead of
  passing.

### Removed
- `CatchmentAnalysis.public_route` (use `route`),
  `CatchmentReportPaths.events_csv` (use `wet_event_csv`), and
  `WaterRegimeAssessment.supports_per_year_boundaries` (use
  `public_route == "per_year_detection"`), `attempts_per_year_detection` (use
  `regime == "seasonal"`) and `supports_fixed_window` (always `False`). They
  were removed in this release without a deprecation period.
- `phase_model`, deprecated in 0.2.0, from `run_hydroseason`,
  `analyze_catchment` and `DynamicHydroYearConfig`: use `phase_scheme`
  (`rule_based` and `cycle_relative` became `two_phase`). Passing it raises
  `TypeError`.
- `DynamicHydroYearConfig` parameters `dry_plateau_rule`,
  `sustained_rise_months` and `pulse_rejection_window_months`, deprecated in
  0.1.0. Nothing read them; passing them now raises `TypeError`, and
  positional arguments after `trough_search_radius_months` shift.
- `hydroseason.io.probe_amplitude`, which was undocumented and unused.
- `hydroseason.io.mark_in_aoi_nodata_as_invalid`, which was importable but not
  in `__all__`, undocumented and unused.
- The undocumented `composite_bundle="legacy"` input value.
- The `case-study` extra (the same as `stac`) and `playwright` from the `dev`
  extra; `scripts/render_report_preview.py` says how to install it.

### Fixed
- A record without an `invalid_pct` column found no hydrological years
  through `analyze_catchment` (`run_hydroseason` was unaffected): a missing
  invalid share was read as 100% invalid.
- `analyze_catchment(..., value_col=...)` with a column other than
  `extent_pct` crashed.
- `aggregate_basin_monthly_extent` counted areas missing a month as dry (a
  month every area missed read 0%), and a missing area could leave a month
  looking fully observed.
- `complete_monthly_axis(..., duplicate_month_policy="warn")` marked every
  month invalid.
- Extent counts read back from the cache dropped the first month when
  `start_date` was not the 1st, or raised `KeyError` with `cache_dir`.
- NetCDF masks with `_FillValue=-2` were decoded as missing data, which
  overstated the AOI and the invalid share.
- `year_workers` above 1 crashed on Windows and could drop sections of the
  cache manifest.
- `scripts/check_release_metadata.py` accepted a `hydroseason-v0.2.0` receipt
  for any version and skipped its git checks in a git worktree. The release
  workflows now run the tests with every extra installed.
- The report's seasonality-evidence card said both Kuiper tests reject
  12-month uniformity even when recurrence was not established; the wet-events
  and low-extent-spell cards named the wrong thresholds.
- The seasonality caveat named the previous method policy.
- Caches on Windows network shares (`\\server\share\...`) failed with
  `WinError 123`: the long-path prefix is now `\\?\UNC\` for these paths.
- `complete_monthly_axis` no longer turns outside-AOI cells (`-2`) into
  unobserved cells (`-1`) on months it inserts for missing scenes. The AOI
  denominator is now the same in every month, so an inserted month no longer
  fails the annual-group pixel-count check in the DEA loader.
- The build requirement is now `setuptools>=77`. The PEP 639 `license`
  metadata used since 0.2.0 fails to build with older setuptools, which the
  previous `>=68` floor allowed.

## [0.2.0] - 2026-09-24

This release replaces the heuristic regime rules of 0.1.x with one frozen,
versioned method (`hydroseason-v0.2.0`). Regime labels, routes, and some
boundaries can differ from 0.1.1 for the same input.

### Added
- **Frozen method policy `hydroseason-v0.2.0`.** Every run uses the same
  method; its parameters are published in `docs/method-policy-v0.2.0.json`
  and fingerprinted (`4bcfed63ed5f04f82417e0164d531595b349d1d8ea0dc2481ce6dc79d72a64de`).
- **Run manifest.** `run_hydroseason` and `hydroseason run` write
  `<stem>_manifest.json` (schema `hydroseason-run-manifest-v1`) with the
  package and dependency versions, method fingerprint, input SHA-256, and
  output checksums. Output paths are relative to the manifest, so a bundle
  can be moved and still verified. `CatchmentReportPaths.manifest_json`
  points to it.
- **Preflight.** `preflight`, `FeasibilityResult`, `PreflightResult`,
  `PreflightThresholds`, `PreflightProfileUnavailable`, and
  `HydroSeasonPreflightError`. A DEA run first checks that the AOI holds
  recurrent surface water and stops early if it does not.
- **Direct-profile trough refinement.** Seasonal boundaries are refined with a
  Huber-loss profile fit (`huber_k=1.345`, `delta_rel=0.05`) and carry support
  intervals, reason codes, and `BoundaryNotSupported` abstentions.
- **New hydrological-year CSV columns:** `trough_boundary_date`,
  `annual_condition`, `peak_quality`, `timing_status`, `peak_timing_status`,
  `trough_timing_status`, `peak_interval_start_date`/`_end_date`,
  `trough_interval_start_date`/`_end_date`, `detectability_floor_pp`, and
  `amplitude_to_floor_ratio`. The monthly CSV gains `confidence`.
- `CatchmentAnalysis` and `WaterRegimeAssessment` gain provenance and timing
  fields (`method_policy_id`, `method_policy_fingerprint`, `input_fingerprint`,
  `seasonality_test`, `n_peak_timing_years`, `n_trough_timing_years`,
  zero-extent counts, and others).
- `phase_scheme` on `run_hydroseason`, `analyze_catchment`, and
  `DynamicHydroYearConfig`.
- `HistoricalMaskRefreshedWarning` is now exported from the package root.

### Changed
- **Seasonality test.** A record is `seasonal` only when circular Kuiper tests
  reject uniform timing for both annual peaks and troughs (p < 0.05) over at
  least five detectable years; otherwise it is `aseasonal` (or
  `insufficient_record`). The amplitude/SNR rules and the `marginal` regime
  are gone.
- **Routing.** Per-year boundaries also require at least seven resolved peak
  and trough cycles; otherwise the record gets event and low-spell analysis.
- **Monthly phases** are now `rising` / `receding`, split at each cycle's
  observed peak (previously `recovery` / `wet` / `recession` / `dry`).
- **Peak quality** is judged against the record's own per-calendar-month
  invalid coverage (`peak_quality`: `normal` / `anomalous`) instead of a flat
  20% cap, so routine wet-season cloud no longer makes a cycle provisional.
- `peak_date` / `trough_date` in the hydrological-year CSV are blank unless
  the timing resolves to a single month; use the interval columns or
  `trough_boundary_date` otherwise.
- `climatological_peak_month` / `climatological_trough_month` are renamed
  `mean_monthly_peak_month` / `mean_monthly_trough_month` (no alias).
- `phase_model` is deprecated in favour of `phase_scheme` (`rule_based` maps
  to `two_phase`).
- `xarray` and other raster dependencies are imported lazily.

### Fixed
- Cloud-flagged months carry zero weight in the low-state fit, and a boundary
  on a cloud-contaminated month moves to the latest reliable month or abstains.
- Boundary support intervals no longer extend past the adopted boundary into
  the next cycle's rising limb.
- Report route explanations state the actual route reason, including when a
  seasonal record has too few cycles for per-year boundaries.

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
