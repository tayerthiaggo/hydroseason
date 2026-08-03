# Historical Maximum-Water Mask and Absolute Area Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DEA WO Multi-Year `count_wet > 0` inside the user AOI the fixed default scientific footprint, calculate observed monthly water area in km² during extraction, and carry matching absolute values through the four user-facing CSVs without changing percentage-based classifications or HTML.

**Architecture:** Introduce an immutable `HistoricalWaterMask` raster artifact with pinned DEA provenance, a verified sidecar cache, and a separate conservative planning derivative. Apply the exact raster before annual masks and count sidecars are written; derive percentages and km² from the same canonical counts; preserve `water_extent_km2` through analysis as aligned context while every decision continues to use `extent_pct`.

**Tech Stack:** Python 3.10+, pandas, NumPy, xarray, rioxarray, rasterio, GeoPandas, odc-stac, Dask, Zarr v2, pytest.

## Global Constraints

- [ ] Treat `docs/superpowers/specs/2026-08-03-historical-water-mask-and-area-design.md` as authoritative. If implementation exposes a contradiction, stop and amend the design with the user before changing semantics.
- [ ] Preserve all unrelated dirty-worktree changes. Stage and commit only the files named by the current task; inspect `git diff -- <files>` before every commit.
- [ ] Use TDD for every behavior change: add one focused failing test, run it and observe the intended failure, implement the smallest behavior, rerun the focused test, then run the affected module suite.
- [ ] Keep the user AOI as the acquisition boundary. Use one exact fixed `count_wet > 0 AND AOI` raster as the scientific denominator for the entire requested monthly period.
- [ ] Keep the coarse/dilated planning mask performance-only. It may choose read windows but must never supply `n_aoi`, `invalid_pct`, `extent_pct`, or area.
- [ ] Keep regime, HY, phase, wet-event, and low-spell decisions percentage-based. Do not substitute raw or coverage-adjusted km² into selection logic.
- [ ] Calculate `water_extent_km2` as observed water only: `n_water * abs(a * e - b * d) / 1_000_000`, using the raster affine coefficients. Do not infer water under invalid pixels.
- [ ] Fail closed if the Multi-Year Statistics source is unavailable, stale for the requested end date, incompatible with the monthly lineage, empty inside the AOI, or mismatched to the analysis grid. Never fall back to the full AOI in the default path.
- [ ] Preserve lower-level full-AOI and legacy `wet_aoi` behavior for explicit compatibility use and for the benchmark reference mode.
- [ ] Do not edit HTML rendering, HTML plots, HTML KPIs, or HTML copy in this implementation.
- [ ] Do not add a summary CSV. The default output remains monthly, hydro-years, wet-event, and low-spells CSVs.
- [ ] Run network acquisition and performance benchmarks only as explicit opt-in commands. Unit and ordinary integration tests must use synthetic or monkeypatched data.

---

## Task 1: Add the metric-grid and observed-area primitive

**Files:**

- Create: `hydroseason/_water_area.py`
- Modify: `hydroseason/hydro_year.py`
- Test: `tests/test_hydro_year.py`

- [ ] Add a failing test with an EPSG:3577, 30 m synthetic canonical mask containing known counts. Assert that `monthly_water_extent()` adds `pixel_area_m2 == 900.0` and `water_extent_km2 == n_water * 0.0009` while all existing counts and percentages stay unchanged.
- [ ] Run `python -m pytest tests/test_hydro_year.py -k "water_extent_km2" -q` and confirm failure because the new columns do not exist.
- [ ] Add `metric_pixel_area_m2(array) -> float` in `_water_area.py`. Read the affine through the raster accessor, compute `abs(a * e - b * d)`, require a projected CRS with metre linear units, and raise `ValueError("water area requires a projected metric CRS")` for missing, geographic, or non-metric CRS metadata.
- [ ] Add focused rotated-affine coverage proving the determinant is used rather than `resolution_x * resolution_y` or a hard-coded 900 m².
- [ ] Add focused error tests for EPSG:4326 and missing CRS. Observe their failure, implement the validation, and rerun them.
- [ ] In `monthly_water_extent()`, calculate pixel area once per input cube, add the scalar `pixel_area_m2` column, and add `water_extent_km2` directly from `n_water`. Leave `extent_pct`, `invalid_pct`, and `wet_fill_pct` formulas untouched.
- [ ] Ensure empty and all-invalid months retain a numeric pixel area and `water_extent_km2 == 0.0` when `n_water == 0`; do not emit an extrapolated value.
- [ ] Run `python -m pytest tests/test_hydro_year.py tests/test_hydro_year_geometry.py -q`.
- [ ] Commit only these files: `git add hydroseason/_water_area.py hydroseason/hydro_year.py tests/test_hydro_year.py && git commit -m "feat: calculate observed monthly water area"`.

## Task 2: Model and build the exact historical water mask

**Files:**

- Create: `hydroseason/_historical_water_mask.py`
- Modify: `hydroseason/_io_dea_stats.py`
- Test: `tests/test_io_dea_stats.py`

- [ ] Add tests constructing a tiny DEA Statistics dataset with `count_wet`, CRS, transform, AOI, source item IDs, version/lineage, and coverage. Assert that `build_historical_water_mask()` produces exactly `(count_wet > 0) AND rasterized_AOI`, excluding zero-wet cells without closing, buffering, dilation, or polygon round-tripping.
- [ ] Assert the value object records `pixel_count`, `area_km2`, CRS, transform, shape, resolution, product, version, item IDs, lineage, coverage start/end, AOI digest, and exact-mask digest.
- [ ] Run `python -m pytest tests/test_io_dea_stats.py -k "historical_water_mask" -q` and observe import/API failures.
- [ ] Add frozen dataclass `HistoricalWaterMask` in `_historical_water_mask.py` with these fields and exact public properties:

  ```python
  @dataclass(frozen=True)
  class HistoricalWaterMask:
      mask: Any
      crs: str
      transform: tuple[float, ...]
      shape: tuple[int, int]
      resolution: tuple[float, float]
      pixel_count: int
      area_km2: float
      source_product: str
      source_version: str
      source_item_ids: tuple[str, ...]
      source_lineage: tuple[str, ...]
      coverage_start: str
      coverage_end: str
      aoi_sha256: str
      mask_sha256: str
  ```

- [ ] Add `build_historical_water_mask(stats, aoi, *, analysis_end) -> HistoricalWaterMask`. Require product `ga_ls_wo_fq_myear_3`, extract and normalize existing `open_wo_statistics()` provenance attrs, rasterize the AOI on the Statistics grid, make the exact boolean mask, and calculate its digest from canonical grid metadata plus row-major boolean bytes.
- [ ] Reuse `metric_pixel_area_m2()` for mask area. Raise clear errors containing `no historically observed water`, `does not cover analysis end`, or `incompatible WOfS lineage` for the three fail-closed cases.
- [ ] Add failing tests, then implementations, for empty mask, insufficient coverage, incompatible lineage, geographic grid, and repeatable digest.
- [ ] Add `build_planning_footprint_from_historical_mask(historical_mask, *, factor=4, safety_cells=1) -> WetPlanningFootprint` in `_io_dea_stats.py`. Reuse `active_windows_from_mask`; set `native_mask` to the exact boolean array; only max-pool/dilate `coarse_mask`; include the exact mask digest in the planning-footprint digest.
- [ ] Add a test proving safety dilation can expand the coarse mask but cannot change `HistoricalWaterMask.mask`, `pixel_count`, or digest.
- [ ] Run `python -m pytest tests/test_io_dea_stats.py tests/test_spatial_plan.py -q`.
- [ ] Commit only the task files: `git add hydroseason/_historical_water_mask.py hydroseason/_io_dea_stats.py tests/test_io_dea_stats.py && git commit -m "feat: model exact historical water mask"`.

## Task 3: Persist and verify the historical-mask sidecar

**Files:**

- Modify: `hydroseason/_historical_water_mask.py`
- Test: `tests/test_io_dea_stats.py`

- [ ] Add failing round-trip tests for a chunked boolean Zarr sidecar and JSON manifest under `cache_root / "historical-water-masks" / "artifacts" / <artifact_digest> /`, plus an index pointer under `historical-water-masks/index/<request_digest>.json` keyed by AOI, grid, product, and Statistics endpoint. Derive `artifact_digest` from exact-mask digest plus normalized source provenance, so a source-version change never overwrites a pinned artifact. Requested monthly dates must not create duplicate mask artifacts.
- [ ] Define `HistoricalWaterMaskRequest` as a frozen dataclass containing AOI digest, product, Statistics STAC URL, CRS, and resolution. Its canonical SHA-256 request digest must not include mutable filesystem paths or analysis start/end dates; the resolved source coverage in the manifest is what determines whether the artifact can serve a requested end date.
- [ ] Implement atomic `write_historical_water_mask(cache_root, request, mask)` and verified `read_historical_water_mask(cache_root, request, *, analysis_end)`. Store `mask.zarr` as a two-dimensional boolean array and `manifest.json` with every `HistoricalWaterMask` metadata field; publish the request-index pointer only after artifact verification succeeds.
- [ ] On read, recompute and compare the boolean mask digest, grid metadata, pixel count, and area. Reject tampered mask bytes or manifest fields with `ValueError("historical water mask cache verification failed")`.
- [ ] Implement `load_or_build_historical_water_mask(aoi, *, analysis_end, cache_root=None, offline=False, stac_url=DEFAULT_WO_STATISTICS_STAC_URL, product=DEFAULT_WO_STATISTICS_PRODUCT, crs="EPSG:3577", resolution=30)`. Resolution order is verified cache, then one `open_wo_statistics()` load and build. In offline mode or after a Statistics failure, return only a verified cache; otherwise raise `DEAStatsUnavailable` and do not construct a full-AOI mask.
- [ ] Add tests proving a warm/offline call makes zero Statistics calls, a stale source cannot satisfy a later analysis end, product/item/version changes produce a distinct verified artifact, and no cache plus offline fails closed.
- [ ] Run `python -m pytest tests/test_io_dea_stats.py -q`.
- [ ] Commit only the task files: `git add hydroseason/_historical_water_mask.py tests/test_io_dea_stats.py && git commit -m "feat: cache verified historical water masks"`.

## Task 4: Apply the exact raster mask to normal and missing months

**Files:**

- Modify: `hydroseason/_io_geo.py`
- Modify: `hydroseason/_io_wofs_acquire.py`
- Test: `tests/test_io.py`
- Test: `tests/test_io_wofs_acquire.py`

- [ ] Add a failing `_clip_to_aoi()` test with water (`1`), dry (`0`), invalid (`-1`), and outside (`-2`) cells. Pass a `HistoricalWaterMask` and assert values inside it are preserved while every cell outside it is exactly `-2`.
- [ ] Add mismatch tests for CRS, shape, transform, resolution, and coordinate ordering. Require an error before any raster values are written or counted.
- [ ] Extend `_clip_to_aoi(mask, aoi_gdf, wet_aoi=None, historical_water_mask=None)` and `_resolve_aoi_inside_mask()` so the exact grid-aligned boolean array is combined with the AOI raster mask without vectorization. Retain the legacy polygon path when the new argument is `None`.
- [ ] Thread `historical_water_mask` through `_load_wofs_items()` and `build_wofs_year_graph()`. Apply it after monthly compositing and AOI clipping but before returning the canonical cube.
- [ ] Add a failing no-source-year test asserting that every historical-mask cell is `-1`, every other cell is `-2`, and reduction gives constant `n_aoi == historical_mask.pixel_count`, `n_invalid == n_aoi`, and zero water area.
- [ ] Extend `_empty_year_mask()` to accept and apply the same exact mask; do not let a missing year revert to the user-AOI denominator.
- [ ] Run `python -m pytest tests/test_io.py tests/test_io_wofs_acquire.py -q`.
- [ ] Commit only the task files: `git add hydroseason/_io_geo.py hydroseason/_io_wofs_acquire.py tests/test_io.py tests/test_io_wofs_acquire.py && git commit -m "feat: apply exact analysis mask to monthly cubes"`.

## Task 5: Pin scientific-mask semantics in the WOfS cache

**Files:**

- Modify: `hydroseason/_io_wofs_zarr.py`
- Test: `tests/test_io_wofs_zarr.py`

- [ ] Add failing identity tests proving two otherwise-identical `WOfSCacheRequest` objects differ when exact mask digest, Statistics product/version/item IDs/lineage/coverage, planning factor, or planning safety cells differ.
- [ ] Bump `WOFS_CACHE_SCHEMA_VERSION` from 3 to 4 and add optional request fields `historical_mask_sha256`, `historical_mask_product`, `historical_mask_version`, `historical_mask_item_ids`, `historical_mask_lineage`, `historical_mask_coverage_start`, `historical_mask_coverage_end`, `historical_mask_pixel_count`, `historical_mask_area_km2`. Omit all of them from legacy request payloads when no historical mask is supplied so explicit legacy caches remain addressable.
- [ ] Add frozen `CacheAnalysisMask` metadata and `record_cache_analysis_mask()`, `read_cache_analysis_mask()`, and `verify_cache_analysis_mask()`. Persist a copy of the exact boolean sidecar under the WOfS store as `analysis-mask/mask.zarr` plus `analysis-mask/manifest.json`; never serialize it to a polygon.
- [ ] Add tamper tests for raster bytes, digest, CRS/transform/shape, source lineage, coverage, pixel count, and area. A mismatch must invalidate derived count sidecars.
- [ ] Extend `write_annual_group()` and `write_empty_annual_group()` validation to enforce for every month:

  ```text
  n_water <= n_valid
  n_valid + n_invalid == n_aoi
  n_aoi == historical_mask_pixel_count
  water_extent_km2 == n_water * pixel_area_m2 / 1_000_000
  ```

- [ ] Add `pixel_area_m2` and `water_extent_km2` to `extent_counts.json`; ensure backfill derives them only from a verified metric grid and verified annual mask.
- [ ] Change `open_completed_extent_counts()` to accept scientifically pruned counts only when the request and verified `CacheAnalysisMask` agree. Continue refusing a smaller polygon/planning-only footprint because it still lacks a valid scientific denominator.
- [ ] Add tests for successful scientific-mask count reads, refusal of unverified pruning, and exact warm-cache area replay.
- [ ] Run `python -m pytest tests/test_io_wofs_zarr.py -q`.
- [ ] Commit only the task files: `git add hydroseason/_io_wofs_zarr.py tests/test_io_wofs_zarr.py && git commit -m "feat: pin analysis mask in WOfS cache"`.

## Task 6: Integrate the scientific and planning masks into acquisition

**Files:**

- Modify: `hydroseason/_io_wofs_acquire.py`
- Test: `tests/test_io_wofs_acquire.py`

- [ ] Add failing tests for the exact lower-level signature:

  ```python
  acquire_wofs_cache(
      ...,
      historical_water_mask: HistoricalWaterMask | None = None,
      planning_footprint: WetPlanningFootprint | None = None,
  )
  ```

  Assert that planned windows limit reads while the exact historical mask—not the planning superset—sets stored `-2` pixels and counts.
- [ ] Remove `_wet_aoi_from_planning_footprint()` from the new path. Keep it only if a legacy caller still depends on polygon planning; never use it for the scientific mask.
- [ ] Verify that `planning_footprint.native_mask` and digest derive from the supplied `historical_water_mask`. Reject independently supplied mismatched artifacts before STAC access.
- [ ] Populate all new cache request fields and call `record_cache_analysis_mask()` before annual writes. On resume, verify the stored sidecar before accepting completed years or count sidecars.
- [ ] Thread `historical_water_mask` to every `build_wofs_year_graph()` and `_empty_year_mask()` call. Keep the planning footprint confined to active-window selection and diagnostic counts.
- [ ] Add diagnostics for `statistics_prepare_seconds`, `stac_read_seconds`, `active_window_count`, `planned_native_pixels`, and `local_reduction_seconds`, without changing existing callback keys.
- [ ] Add tests proving no-source months preserve constant `n_aoi`, planning dilation does not increase `n_aoi`, and a mask/source coverage error occurs before any monthly WOfS call.
- [ ] Run `python -m pytest tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py -q`.
- [ ] Commit only the task files: `git add hydroseason/_io_wofs_acquire.py tests/test_io_wofs_acquire.py && git commit -m "feat: acquire WOfS with fixed historical footprint"`.

## Task 7: Make the high-level default resolve one Multi-Year mask

**Files:**

- Modify: `hydroseason/_io_extent_cache.py`
- Modify: `hydroseason/io.py`
- Modify: `hydroseason/__init__.py`
- Modify: `tests/test_io_extent_cache.py`
- Modify: `tests/test_package_surface.py`

- [ ] Add failing high-level tests for this compatibility-preserving API:

  ```python
  load_wofs_monthly_extent(
      ...,
      use_historical_water_mask: bool = True,
      historical_water_mask: HistoricalWaterMask | None = None,
      historical_mask_cache_dir: str | os.PathLike[str] | None = None,
      statistics_stac_url: str = DEFAULT_WO_STATISTICS_STAC_URL,
  ) -> pd.DataFrame
  ```

  The default must resolve DEA Multi-Year once. `use_historical_water_mask=False` is the explicit compatibility/reference mode. Reject `historical_water_mask` when the boolean is false.
- [ ] Treat `historical_mask_cache_dir` as the parent cache root. If it is omitted, use `mask_cache_dir`, else `cache_dir`; `load_or_build_historical_water_mask()` owns the internal `historical-water-masks/` subdirectory. When no cache root exists, build one in memory. Pass the requested `end_date` to the coverage validator.
- [ ] Resolve or validate exactly one `HistoricalWaterMask`, derive exactly one planning footprint, and reuse both across all calendar-year pieces. Do not query Calendar Year Statistics and do not rebuild the mask per year.
- [ ] In the mask-cache path, pass both artifacts to `acquire_wofs_cache()` and accept `open_completed_extent_counts()` only after exact-mask verification. In the older per-year CSV path, apply the exact raster before `monthly_water_extent()` so the two paths share semantics.
- [ ] Preserve `water_extent_km2` and `pixel_area_m2` in cached CSV identity/content. Add the historical mask digest and provenance to the per-year CSV cache key to prevent a full-AOI hit under new semantics.
- [ ] Add tests proving different start dates with the same AOI/grid/source reuse the same fixed mask, different end dates may reuse it only when coverage suffices, offline replay makes no STAC call, and the explicit full-AOI mode preserves legacy behavior.
- [ ] Re-export `HistoricalWaterMask`, `build_historical_water_mask`, and `load_or_build_historical_water_mask` from `hydroseason.io` and top-level `hydroseason`. Update the exact package-surface test deliberately.
- [ ] Run `python -m pytest tests/test_io_extent_cache.py tests/test_package_surface.py -q`.
- [ ] Commit only the task files: `git add hydroseason/_io_extent_cache.py hydroseason/io.py hydroseason/__init__.py tests/test_io_extent_cache.py tests/test_package_surface.py && git commit -m "feat: default to DEA historical water footprint"`.

## Task 8: Preserve absolute area through preparation and event analysis

**Files:**

- Modify: `hydroseason/_state_input.py`
- Modify: `hydroseason/_events.py`
- Test: `tests/test_state_input.py`
- Test: `tests/test_events.py`
- Test: `tests/test_events_definition.py`

- [ ] Add a failing state-input test proving `prepare_monthly_extent()` preserves aligned `n_water`, `n_valid`, `pixel_area_m2`, and `water_extent_km2` through reindexing and quality classification without using area to set `candidate_usable`.
- [ ] Implement numeric coercion and consistency validation for those optional columns. Preserve percentage-only inputs; do not synthesize area from `extent_pct` alone.
- [ ] Add event tests with varying `n_valid` and invalid coverage. Assert event membership, event dates, thresholds, and `magnitude_pp_months` are identical with or without area columns.
- [ ] Extend `_empty_events()` with `peak_water_extent_km2`, `mean_water_extent_km2`, and `magnitude_km2_months`; extend `_empty_low_spells()` with `min_water_extent_km2`.
- [ ] In `extract_water_events()`, calculate `baseline_water_extent_km2` as the median usable observed area and include it in `summary`. For each existing percentage-selected event, use the aligned months for peak and mean observed area and calculate:

  ```python
  exit_area = exit_threshold_pct / 100 * n_valid * pixel_area_m2 / 1_000_000
  magnitude_km2_months = (water_extent_km2 - exit_area).clip(lower=0).sum()
  ```

- [ ] For each low spell, select `min_water_extent_km2` from the same first `idxmin()` month that supplies `min_extent_pct`; do not independently minimize area.
- [ ] When optional area/count columns are absent, keep event detection working and return the new area values as `NaN`. The default extraction/report path must supply complete values.
- [ ] Run `python -m pytest tests/test_state_input.py tests/test_events.py tests/test_events_definition.py -q`.
- [ ] Commit only the task files: `git add hydroseason/_state_input.py hydroseason/_events.py tests/test_state_input.py tests/test_events.py tests/test_events_definition.py && git commit -m "feat: attach absolute area to events and low spells"`.

## Task 9: Add km² fields to the four CSV projections

**Files:**

- Modify: `hydroseason/_report_export.py`
- Modify: `hydroseason/report.py`
- Test: `tests/test_report_export.py`
- Test: `tests/test_generate_catchment_report.py`

- [ ] Update schema tests first so populated and empty exports require these exact additions:

  ```text
  monthly: water_extent_km2, baseline_water_extent_km2
  hydro-years: peak_water_extent_km2, mid_dry_water_extent_km2,
               trough_water_extent_km2, drawdown_km2
  wet-event: baseline_water_extent_km2, peak_water_extent_km2,
             mean_water_extent_km2, magnitude_km2_months
  low-spells: baseline_water_extent_km2, min_water_extent_km2
  ```

- [ ] Run `python -m pytest tests/test_report_export.py tests/test_generate_catchment_report.py -q` and observe stable-header/value failures.
- [ ] Insert the fields beside their percentage companions in `MONTHLY_CSV_COLUMNS`, `HY_CSV_COLUMNS`, `EVENT_CSV_COLUMNS`, and `LOW_SPELL_CSV_COLUMNS`. Do not add a fifth/summary output.
- [ ] Extend `build_user_monthly_export()` to copy monthly observed area and repeat `analysis.events.summary["baseline_water_extent_km2"]` as the baseline companion.
- [ ] Change the HY projector to `build_user_hydro_years_export(hydro_years, *, monthly)`. Normalize monthly dates once, look up the selected peak/mid-dry/trough dates, copy their observed areas, and calculate `drawdown_km2 = peak - trough`. Never choose dates from the area column.
- [ ] Extend event and low-spell projectors with keyword `baseline_water_extent_km2` and copy the new internal columns. Empty inputs must still return the complete stable header.
- [ ] Update only the CSV wiring in `generate_catchment_report()`: pass monthly into the HY projector and the event summary's area baseline into both event/spell projectors. Do not modify `_report_html.py`, `_report_plotly.py`, `_report_svg.py`, HTML templates, or HTML-facing frame selection.
- [ ] Add a report-generation assertion that there are exactly four CSVs named `<stem>_monthly.csv`, `<stem>_hydro_years.csv`, `<stem>_wet_event.csv`, and `<stem>_low_spells.csv`, with no `<stem>_summary.csv`.
- [ ] Add a sentinel HTML snapshot/substring assertion proving this task does not introduce the new area column labels into rendered HTML.
- [ ] Run `python -m pytest tests/test_report_export.py tests/test_generate_catchment_report.py -q`.
- [ ] Commit only the task files: `git add hydroseason/_report_export.py hydroseason/report.py tests/test_report_export.py tests/test_generate_catchment_report.py && git commit -m "feat: add absolute water area to CSV outputs"`.

## Task 10: Prove percentage classifications and mask denominators remain correct

**Files:**

- Modify: `tests/test_io_extent_cache.py`
- Modify: `tests/test_catchment_analysis.py`
- Review: `tests/test_manual_review_regression.py`

- [ ] Add a synthetic integration fixture with water pixels inside the exact mask and invalid land pixels outside it. Compare explicit full-AOI and historical-mask reductions: require identical `n_water` and `water_extent_km2`, a smaller fixed `n_aoi`, and `invalid_pct` changed only by the intended denominator.
- [ ] Add a varying-invalid-coverage series proving adding raw `water_extent_km2` does not change regime, HY start/end, peak, mid-dry, trough, phase, wet-event, or low-spell selections. This is the regression guard against accidentally making absolute area authoritative.
- [ ] Add normal, all-invalid, and no-source months and assert one constant `n_aoi == historical_mask.pixel_count` across all rows.
- [ ] Run `python -m pytest tests/test_io_extent_cache.py tests/test_catchment_analysis.py tests/test_manual_review_regression.py -q`.
- [ ] Run the analysis regression group: `python -m pytest tests/test_dynamic_year.py tests/test_phase.py tests/test_phase_regression.py tests/test_detector_comparison.py tests/test_manual_review_regression.py -q`.
- [ ] Commit only changed task files: `git add tests/test_io_extent_cache.py tests/test_catchment_analysis.py && git commit -m "test: lock historical-mask analysis semantics"`.

## Task 11: Update extraction entry points, case-study data, and CSV documentation

**Files:**

- Modify: `scripts/extract_water_extent_csv.py`
- Modify: `scripts/_build_study_case_offline.py`
- Modify: `README.md`
- Modify: `docs/guide.md`
- Modify: `docs/hydrological-state.md`
- Modify: `docs/report-columns.md`
- Modify: `docs/case-studies/main-workflow.md`
- Modify: `case_studies/data/extent/*.csv` only for successfully re-extracted study inputs
- Modify: `case_studies/results/main/<study>/*.csv`
- Modify: `case_studies/results/main/summary.csv` only if the case-study index still consumes it internally; do not restore per-study summary CSVs
- Modify only if the corrected extraction changes reviewed classifications: `tests/fixtures/fitzroy_river_wa_manual_review.csv`
- Modify only if the corrected extraction changes reviewed classifications: `tests/fixtures/gilbert_river_qld_manual_review.csv`

- [ ] Change the extraction script's default to the high-level historical-mask workflow. Retain an explicitly named `--full-aoi` compatibility flag for diagnostics/benchmarking; do not expose Calendar Year union, frequency thresholds, closing, or buffered scientific masks.
- [ ] Add script-level argument tests if a parser test module exists; otherwise extract parser construction into a testable function and add `tests/test_extract_water_extent_csv.py` covering defaults, `--full-aoi`, and offline cache failure.
- [ ] Document the workflow exactly: user AOI acquisition boundary → cached DEA Multi-Year Statistics → fixed unfiltered `count_wet > 0` raster → separate planning superset → monthly WOfS → percentage-based analysis → four CSVs.
- [ ] Document the pinned source coverage returned by the actual manifest, the coverage-end fail-closed rule, affine area formula, observed-only meaning of km², and the fact that invalid pixels outside the historical mask do not affect `invalid_pct`.
- [ ] Update the report-column reference for every new field and explicitly state that dates/events are chosen from percentages, not absolute area. Keep `max_invalid_pct` documented as a user-configurable within-month threshold over the historical-mask denominator.
- [ ] Run a bounded smoke extraction first on `data/fitzroy_kimberley_aoi.geojson` for one month; inspect manifest, mask count, constant denominator, and area before spending time on case studies.
- [ ] Re-extract each case-study source over the same start/end period as its monthly analysis using the default fixed mask. Never derive km² from the old aggregate percentage CSV alone because it lacks the corrected exact-mask counts.
- [ ] Rebuild the four CSV bundles with `scripts/_build_study_case_offline.py`. Delete obsolete per-study summary or old plural-event CSVs only after confirming their replacements exist and are referenced correctly; use explicit paths and report what was removed.
- [ ] Compare Fitzroy and Gilbert against the manual-review fixtures. Inspect every changed selected date/flag rather than accepting wholesale fixture churn.
- [ ] Run `python -m pytest tests/test_generate_catchment_report.py tests/test_manual_review_regression.py -q`.
- [ ] Run documentation validation: `mkdocs build --strict` using a temporary site directory outside the repository.
- [ ] Commit scripts/docs separately from regenerated data:

  ```text
  git commit -m "docs: explain fixed water footprint and area outputs"
  git commit -m "data: rebuild case studies with historical water mask"
  ```

## Task 12: Extend the bounded performance and containment benchmark

**Files:**

- Modify: `scripts/benchmark_wofs_cache.py`
- Create or modify: `tests/test_benchmark_wofs_cache.py`
- Modify: `docs/case-studies/resolution-and-acquisition.md`
- Modify: `case_studies/results/resolution/acquisition-runs.csv`
- Modify: `case_studies/results/resolution/acquisition-summary.csv`

- [ ] Add parser/unit tests pinning the only benchmark AOIs to `data/fitzroy_kimberley_aoi.geojson` and `data/Gilbert_river_buffer.geojson`, the date window to 2015-01-01 through 2015-12-31, and the grid to EPSG:3577 at 30 m. Reject full-catchment case paths.
- [ ] Replace the old mode vocabulary with three scientific comparisons: `full_aoi`, `planning_only`, and `historical_mask`. Retain cold and warm repetitions where applicable.
- [ ] Record per run: total seconds, Statistics preparation seconds, STAC/read seconds, active windows, planned/loaded pixels, local reduction seconds, peak RSS, cache bytes, exact `n_water`, and exact `water_extent_km2`.
- [ ] Add a full-AOI containment audit for the bounded 2015 data: every monthly primary water pixel must fall inside the exact Multi-Year mask. Report a mismatch count and fail correctness if nonzero; do not add this full scan to production.
- [ ] Make `_assert_exact()` require exact monthly `n_water` and numerically exact/close-at-machine-precision `water_extent_km2` between all modes. Do not require equal `n_aoi` or `invalid_pct`, because the scientific denominator intentionally differs.
- [ ] Preserve measured timings even when no speedup occurs. Exit nonzero only for correctness/containment failure; present performance as measured evidence rather than a hard promised threshold.
- [ ] Run `python -m pytest tests/test_benchmark_wofs_cache.py -q`.
- [ ] Run the opt-in benchmark with its help output first, then execute the configured cold/warm runs. Write the two acquisition CSVs from measured output; never manufacture figures.
- [ ] Update acquisition documentation with the three-mode table and a qualified conclusion. State whether the new approach was faster for each bounded AOI and separate first-run Statistics cost from warm-cache performance.
- [ ] Commit only benchmark code/tests/results/docs: `git add scripts/benchmark_wofs_cache.py tests/test_benchmark_wofs_cache.py docs/case-studies/resolution-and-acquisition.md case_studies/results/resolution/acquisition-runs.csv case_studies/results/resolution/acquisition-summary.csv && git commit -m "perf: benchmark historical water mask workflow"`.

## Task 13: Full verification and release handoff

**Files:**

- Modify only if failures expose an in-scope defect: files already named above
- Review: `CHANGELOG.md`

- [ ] Run `python -m pytest tests/test_io_dea_stats.py tests/test_io.py tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py tests/test_io_extent_cache.py tests/test_hydro_year.py tests/test_state_input.py tests/test_events.py tests/test_report_export.py tests/test_generate_catchment_report.py tests/test_manual_review_regression.py tests/test_package_surface.py -q`.
- [ ] Run the complete suite: `python -m pytest -q`.
- [ ] Build the package: `python -m build`.
- [ ] Validate distributions: `python -m twine check dist/*`.
- [ ] Build docs strictly into a temporary directory and confirm repository HTML artifacts were not regenerated.
- [ ] Inspect all four final CSV headers for Fitzroy, Daly, and Gilbert; verify area fields are populated, filenames are singular `_wet_event.csv`, and no per-study summary CSV remains.
- [ ] Programmatically assert for every extracted monthly frame: count invariants, constant `n_aoi`, exact water-area formula, mask digest presence, and source coverage through the requested end date.
- [ ] Compare pre/post selected classifications for the same corrected percentage series. Explain any changed result only as a consequence of the historical-mask denominator/quality eligibility, never as a consequence of adding km².
- [ ] Inspect `git status --short` and `git diff --check`. Confirm no unrelated dirty files were staged and no HTML renderer/template changed.
- [ ] Add a concise `CHANGELOG.md` entry only if this branch's release policy expects unreleased changes; describe the scientific denominator change as behavior-changing and the km² columns as additive.
- [ ] Use `superpowers:requesting-code-review` for an independent review against the approved design. Resolve only verified in-scope findings, then rerun the focused and complete tests.
- [ ] Use `superpowers:verification-before-completion` before reporting success. The handoff must include test/build results, exact case-study artifacts rebuilt, benchmark evidence, and any network-dependent step that could not be completed.

## Acceptance Criteria

- [ ] A default run queries or reuses one pinned DEA WO Multi-Year Statistics artifact, creates exact `count_wet > 0 AND AOI`, and uses that same raster for every requested month.
- [ ] The exact mask—not its coarse/dilated planning derivative—is the fixed denominator for `n_aoi` and `invalid_pct`; outside it is always `-2`.
- [ ] Missing-source and all-invalid months keep the same historical-mask `n_aoi` and are invalid inside that footprint.
- [ ] Monthly `water_extent_km2` equals observed water-pixel count times affine-derived metric pixel area, with no invalid-pixel extrapolation.
- [ ] Regime, HY, phases, events, and spells remain selected from percentage extent; adding area alone cannot change their dates or labels.
- [ ] The four user-facing CSVs contain all approved km² fields, no summary CSV is emitted, and HTML remains unchanged.
- [ ] Cache identity and verified sidecars prevent reuse across different exact masks, DEA source versions/lineage/coverage, grids, planning settings, or date ranges.
- [ ] Fitzroy and Gilbert manual-review regressions pass after corrected pixel-level re-extraction; case-study bundles contain only current final CSV artifacts.
- [ ] The bounded Fitzroy/Gilbert benchmark reports correctness, containment, cold/warm timings, memory, and cache size without using full catchments or claiming unmeasured speedups.
