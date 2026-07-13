# Task C Report - Detection Core Port

**Status:** DONE
**Model used:** gpt-5
**Started from commit:** d0e43e4
**Ended at commit:** not committed

## Summary

Ported WaterMask-TSFill hydro-year detection core from source commit
`90983c1559e7c08951096bbf196c0daedead6b4f`, verified in sibling
`D:/RLH/5.6/repos/WaterMask-TSFill` checkout. New core accepts monthly extent
Series/DataFrames without raster dependencies. Package exports only
`HydroYearConfig`, `detect_hydrological_years`, `label_hydrological_months`,
and `monthly_water_extent`; `ValidationSeasonConfig` is not defined/exported.

Strict defaults now reject duplicate months, missing months, and supplied
invalid coverage above `max_invalid_pct=0`. Unsupported season-window shapes
fail during config construction. Raster summary excludes invalid pixels from
water denominator and materializes all summary arrays through one shared
`dask.compute(...)` boundary.

## Files Changed

- `hydroseason/hydro_year.py` - source-agnostic detection port and safety amendments.
- `hydroseason/__init__.py` - hydro-year public exports only.
- `tests/test_hydro_year.py` - focused test-first coverage for importability, strict month policies, season geometry, invalid coverage, and invalid-pixel extent handling.
- `tests/test_package_surface.py` - verifies public API and no validation config export.
- `docs/plans/wofs-migration-execution/task-c-detection-core.md` - this handoff.

## Tests And Checks

- Wrote tests before implementation; initial `python -m pytest tests/test_hydro_year.py -q` result: 7 expected failures because `hydroseason.hydro_year` had been stripped by Task B.
- Added duplicate-with-null-value regression test; initial result: expected failure, then fixed duplicate validation before null filtering.
- Added warn-policy duplicate-collapse regression test; initial result: expected failure, then fixed first-wins collapse.
- `python -m pytest tests -q` - 12 passed.
- `python -c "from hydroseason import HydroYearConfig, detect_hydrological_years, label_hydrological_months, monthly_water_extent; print('core api ok')"` - passed.
- `python -m compileall -q hydroseason` - passed.
- `git diff --check` - passed.
- `git -C D:/RLH/5.6/repos/WaterMask-TSFill rev-parse 90983c1559e7c08951096bbf196c0daedead6b4f` - passed.

## Decisions Made

- Kept raster imports local to `monthly_water_extent`; CSV detection and month labelling need only NumPy/Pandas.
- Used strict `duplicate_month_policy="raise"` and `missing_month_policy="raise"` defaults; callers can opt into documented permissive policies.
- Made explicit warn-mode duplicate handling first-wins, matching its warning text and avoiding ambiguous monthly lookups.
- Treated present but unknown `invalid_pct` as invalid coverage, preventing silent invalid-as-dry classification.
- No Git ref, commit, reset, checkout, deletion, or push action performed.

## Blockers Or Concerns

- Working tree already contains broad Task B strip/docs/package changes outside Task C scope. They remain unmodified except public surface/test updates needed by this task.
- Loader API is intentionally not exported yet: Task D creates the new `hydroseason/io.py` source-agnostic loaders.

## Next Task Notes

Task D should retain `hydro_year.py` core-only imports. It must place raster/STAC dependencies in module-local loader imports and preserve canonical mask values expected by `monthly_water_extent`.

## Review

**Result:** CHANGES_REQUESTED

**Reviewer model:** opus (fallback reviewer)

**Reviewed:** working-tree diff for `hydroseason/hydro_year.py`, `hydroseason/__init__.py`, `tests/test_hydro_year.py`, `tests/test_package_surface.py`, cross-checked against WaterMask-TSFill source `90983c1559e7c08951096bbf196c0daedead6b4f:watermask_tsfill/hydro_year.py`. Ran `pytest tests/test_hydro_year.py tests/test_package_surface.py -q` → 12 passed. Ran an ad-hoc synthetic detection check (3-year cosine series) → 3 hydro-years detected with correct Feb peaks / Aug end-dry.

### Scope verdict (each required item)

- **CSV-only importability** — PASS. Module-level imports are only `numpy`/`pandas`; `xarray` behind `TYPE_CHECKING` (`hydroseason/hydro_year.py:15-16`); `dask` imported inside `monthly_water_extent` (`hydroseason/hydro_year.py:80-83`). Covered by `test_csv_detection_imports_without_raster_dependencies` (`tests/test_hydro_year.py:14-21`).
- **No exported `ValidationSeasonConfig`** — PASS. Symbol removed entirely; not in `__all__` (`hydroseason/hydro_year.py:283`) nor package surface. Asserted in `tests/test_package_surface.py:19`.
- **Strict duplicate/missing month behavior** — PASS. Defaults `duplicate_month_policy="raise"` / `missing_month_policy="raise"` (`hydroseason/hydro_year.py:118-119`). Duplicate check runs on the full index *before* NaN-dropping (`hydroseason/hydro_year.py:207-210`), so a duplicate with a null value still raises. Covered by `tests/test_hydro_year.py:24-62`.
- **Season-window validation** — PASS. `HydroYearConfig.__post_init__` rejects non-cross-year wet windows, same-year-violating dry windows, and dry-before-wet geometry (`hydroseason/hydro_year.py:40-64`). Covered by `test_unsupported_season_window_geometry_fails_fast` (`tests/test_hydro_year.py:65-69`).
- **No invalid-as-dry bug** — PASS. Water denominator is now `n_valid = n_aoi - n_invalid` (`hydroseason/hydro_year.py:89`, `:96`), vs source which divided by `n_aoi` including invalid pixels. Regression-tested by `test_monthly_water_extent_excludes_invalid_pixels_from_water_denominator` (`tests/test_hydro_year.py:94-110`); detection path also carries + rejects `invalid_pct`.
- **One shared `dask.compute` boundary** — PASS (code). Single `dask.compute(n_aoi, n_valid, n_water, n_invalid)` (`hydroseason/hydro_year.py:90`), replacing the source's three separate `.compute()` calls. See Minor 4 re: no explicit test.
- **Invalid coverage handling** — PARTIAL, see Important 1.
- **Focused tests per behavior** — MOSTLY. Validation/error paths well covered; positive detection + `label_hydrological_months` not covered (Minor 2, Minor 3).

### Important

1. **`max_invalid_pct` default `0.0` breaks the canonical raster→detection flow and diverges from the plan's recommended default.** `detect_hydrological_years(..., max_invalid_pct=0.0)` (`hydroseason/hydro_year.py:120`) rejects any month whose `invalid_pct > 0` (`hydroseason/hydro_year.py:140-146`). The plan's canonical raster path is `monthly_water_extent(mask) → detect_hydrological_years(df)` (§1.5.1), and `monthly_water_extent` always emits an `invalid_pct` column (`hydroseason/hydro_year.py:97,106`). Confirmed empirically: feeding a `monthly_water_extent`-shaped frame with a realistic `invalid_pct=5.0` raises `"Invalid coverage exceeds max_invalid_pct or is unknown..."`. Real WOfS data effectively always has some cloud/invalid pixels, so the primary raster pipeline errors out of the box. The plan explicitly recommends a conservative default of `max_invalid_pct=20.0` (`docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md:306`; window handling in §2.4 at `:160`). The port chose `0.0` without recording that deviation or the §6.2 recommendation in `## Decisions Made`. Note: behavior is fail-closed (safe, not silent), so this is a reconciliation/usability issue, not a data-correctness bug. Fix (either): set the default to `20.0` per §6.2, or explicitly record the user's decision to keep `0.0` in the report and update user-facing docs so the raster→detect flow documents passing `max_invalid_pct` explicitly. Add a test that pins whichever default is chosen against a `monthly_water_extent`-shaped input.

### Minor

2. **No positive/golden detection test.** Every core test in `tests/test_hydro_year.py` exercises validation/error paths or `monthly_water_extent`; none asserts that `detect_hydrological_years` returns correct `hy_year`/`peak_month`/`end_dry_month`/`amplitude` on a known seasonal series. `test_warn_duplicate_policy_collapses_to_first_month_value` (`:44-53`) and `test_invalid_coverage_can_be_explicitly_permitted` (`:83-91`) only assert `isinstance(result, pd.DataFrame)`. A hand-built synthetic series with known boundaries would lock in the happy path. (Task F covers scientific acceptance, but a focused Task-C unit test is cheap.)

3. **`label_hydrological_months` has no test.** It is ported, exported public API (`hydroseason/hydro_year.py:177-195`, `:283`) yet untested — Wet/Dry split at `peak_month` and the before-first / after-last edge assignment are unverified.

4. **Single-`dask.compute` boundary is not asserted by any test.** The code is correct (`hydroseason/hydro_year.py:90`), but nothing guards against a regression to per-statistic `.compute()`. Optional: a test using a `dask` scheduler callback / compute counter, or a monkeypatched `dask.compute`, to assert exactly one call.

5. **`_month_nearest_midpoint` lost the source's empty-`dates` guard.** Source returned `pd.Timestamp(end)` when `dates` was empty; the port calls `np.argmin` on a possibly-empty array (`hydroseason/hydro_year.py:253-255`), which would raise `ValueError`. Safe in current call sites because `span` always contains both `peak_month` and `end_dry_month` (peak ≤ end-dry, both in `series`), so it is never empty — but the defensive guard was dropped without note. Restore the guard or add a comment documenting the invariant.

### Notes / non-blocking

- Source provenance recorded in the module docstring (`hydroseason/hydro_year.py:1-6`) matches the pinned commit. Good.
- `_assign_end_dry_spans` inlines `pd.date_range(start, end, freq="MS")` instead of the source's `_inclusive_month_range`; with `start > end`, `pd.date_range` returns an empty index (length 0) rather than erroring, so behavior matches. Fine.
- `n_valid` added as an extra `monthly_water_extent` output column — additive, harmless.

### Recommendation

CHANGES_REQUESTED — resolve Important 1 (align the `max_invalid_pct` default with §6.2 or record the explicit user decision + docs, plus a pinning test). Minors 2-5 are recommended but non-blocking; addressing 2 and 3 would meaningfully close the "focused tests for each behavior" gap.

## Fix Pass

**Fix result:** RESOLVED (Important 1) + Minors 2, 3, 5 addressed. Minor 4 left open (optional, non-blocking).

### Important 1 — `max_invalid_pct` default

Changed default from `0.0` to `20.0` per plan §6.2 recommendation
(`docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md:306`).
`hydroseason/hydro_year.py:120` now reads `max_invalid_pct: float = 20.0`;
docstring updated to state the conservative-default rationale and cite §6.2.

Added two pinning tests before the change (red first, confirmed via
`pytest tests/test_hydro_year.py -q`):

- `test_default_max_invalid_pct_permits_typical_wofs_cloud_noise` — a
  `monthly_water_extent`-shaped frame with realistic `invalid_pct=5.0` must
  pass detection with the default threshold. Failed against old `0.0` default
  with `ValueError: Invalid coverage exceeds max_invalid_pct...`; passes now.
- `test_default_max_invalid_pct_still_rejects_above_twenty_percent` — a month
  at `invalid_pct=20.1` must still raise under the default, proving the fix
  is a threshold change, not a removal of the safety check.

### Minor 2 — golden detection path

Added `test_detect_hydrological_years_golden_path_peak_and_end_dry`: a
3-year synthetic cosine series with a known Feb peak / Aug end-dry asserts
`hy_year` sequence `[2018, 2019, 2020]`, `peak_month.month == 2`,
`end_dry_month.month == 8`, and positive amplitude for every row. Passed on
first run — locks in existing correct behavior, no implementation change
needed.

### Minor 3 — `label_hydrological_months` coverage

Added `test_label_hydrological_months_splits_wet_dry_and_edges` against the
same synthetic series: asserts `peak_month` labelled `"Wet"`, the month after
`peak_month` labelled `"Dry"`, no unlabelled (`NaN`) `hy_year` rows, and the
after-last-year tail labelled with the last detected `hy_year` / `"Dry"`.
Passed on first run — locks in existing correct behavior, no implementation
change needed.

### Minor 5 — `_month_nearest_midpoint` empty-dates guard

Restored the source's empty-`dates` guard: `hydroseason/hydro_year.py:255-256`
now returns `pd.Timestamp(end)` when `dates` is empty, before the
`np.argmin` call. Added `test_month_nearest_midpoint_empty_dates_guard`
(direct unit test on the private helper) — failed with
`ValueError: attempt to get argmin of an empty sequence` before the fix,
passes now. Current call sites still never hit this path (span always
contains `peak_month`/`end_dry_month`), so this is defense-in-depth restoring
parity with the source, not a live bug fix.

### Minor 4 — not addressed

Left open. No test added to assert the single-`dask.compute` boundary
(`hydroseason/hydro_year.py:90`) via call-count/monkeypatch. Non-blocking per
reviewer; flagging for Task D/E if raster-path regression coverage is
prioritized later.

### Tests and checks (fix pass)

- Wrote 4 new tests before implementation; 2 red as expected
  (`test_default_max_invalid_pct_permits_typical_wofs_cloud_noise`,
  `test_month_nearest_midpoint_empty_dates_guard`), 2 green on first run
  (`test_detect_hydrological_years_golden_path_peak_and_end_dry`,
  `test_label_hydrological_months_splits_wet_dry_and_edges`).
- `python -m pytest tests/test_hydro_year.py -q` → 12 passed before this fix
  pass's new tests were added; after adding all 4, 2 failed as expected
  (red), then 17 passed after the two code fixes.
- `python -m pytest tests -q` → 17 passed.
- `python -m compileall -q hydroseason` → passed.
- `python -c "from hydroseason import HydroYearConfig, detect_hydrological_years, label_hydrological_months, monthly_water_extent; print('core api ok')"` → passed.
- `git diff --check -- hydroseason/hydro_year.py tests/test_hydro_year.py` → only pre-existing LF/CRLF warnings, no conflict markers/whitespace errors.
- No Git ref, commit, reset, checkout, deletion, or push action performed in this fix pass.

### Files changed (fix pass)

- `hydroseason/hydro_year.py` — `max_invalid_pct` default `0.0` → `20.0` plus docstring update; restored empty-`dates` guard in `_month_nearest_midpoint`.
- `tests/test_hydro_year.py` — 4 new focused tests (invalid-pct default pin ×2, golden detection path, label Wet/Dry + edges, empty-dates guard).
- `docs/plans/wofs-migration-execution/task-c-detection-core.md` — this Fix Pass section (Review section left untouched).

## Re-Review

**Result:** APPROVED

**Reviewer model:** gpt-5.6

**Reviewed:** post-fix-pass working tree for `hydroseason/hydro_year.py`, `hydroseason/__init__.py`, `tests/test_hydro_year.py`, `tests/test_package_surface.py`, cross-checked against WaterMask-TSFill source `90983c1559e7c08951096bbf196c0daedead6b4f:watermask_tsfill/hydro_year.py` and prior `## Review` / `## Fix Pass`. Ran `pytest tests/test_hydro_year.py tests/test_package_surface.py -q` → 17 passed. Ran `python -c "from hydroseason import ..."` and `python -m compileall -q hydroseason` → passed.

### Scope verdict (each required item)

- **CSV-only importability** — PASS. Module-level imports are only `numpy`/`pandas`; `xarray` behind `TYPE_CHECKING` (`hydroseason/hydro_year.py:15-16`); `dask` imported inside `monthly_water_extent` (`hydroseason/hydro_year.py:80-83`). Covered by `test_csv_detection_imports_without_raster_dependencies` (`tests/test_hydro_year.py:14-21`).
- **No exported `ValidationSeasonConfig`** — PASS. Symbol absent from module and package; `__all__` lists only the four hydro-year APIs (`hydroseason/hydro_year.py:286`, `hydroseason/__init__.py:22-28`). Asserted in `tests/test_package_surface.py:19`.
- **Strict duplicate/missing month behavior** — PASS. Defaults `duplicate_month_policy="raise"` / `missing_month_policy="raise"` (`hydroseason/hydro_year.py:118-119`). Duplicate check on full index before NaN-dropping (`hydroseason/hydro_year.py:207-211`). Covered by `tests/test_hydro_year.py:24-62`.
- **Season-window validation** — PASS. `HydroYearConfig.__post_init__` rejects non-cross-year wet, same-year-violating dry, and dry-before-wet geometry (`hydroseason/hydro_year.py:40-64`). Covered by `test_unsupported_season_window_geometry_fails_fast` (`tests/test_hydro_year.py:65-69`).
- **Invalid coverage handling** — PASS. Default `max_invalid_pct=20.0` per plan §6.2 (`hydroseason/hydro_year.py:120-127`); months with unknown or above-threshold `invalid_pct` raise (`hydroseason/hydro_year.py:141-147`). Pinning tests at `tests/test_hydro_year.py:72-114` cover reject, permit, typical WOfS noise, and >20% boundary.
- **No invalid-as-dry bug** — PASS. Water denominator uses `n_valid = n_aoi - n_invalid` (`hydroseason/hydro_year.py:89`, `:96`), not source's `n_aoi`-only division. Regression-tested by `test_monthly_water_extent_excludes_invalid_pixels_from_water_denominator` (`tests/test_hydro_year.py:167-183`).
- **One shared `dask.compute` boundary** — PASS (code). Single `dask.compute(n_aoi, n_valid, n_water, n_invalid)` at `hydroseason/hydro_year.py:90`; no other `.compute()` in module. See Minor note below.
- **Focused tests per behavior** — PASS. Fix pass closed prior gaps: golden detection (`tests/test_hydro_year.py:124-135`), `label_hydrological_months` Wet/Dry/edges (`tests/test_hydro_year.py:138-156`), empty-dates guard (`tests/test_hydro_year.py:159-164`).

### Prior Important finding — resolved

Important 1 (`max_invalid_pct` default `0.0` blocking raster→detect flow) fixed: default now `20.0`, docstring cites §6.2, pinning tests added and green.

### Minor (non-blocking)

1. **Single-`dask.compute` boundary still not asserted by test** (`hydroseason/hydro_year.py:90`). Code correct; optional regression guard deferred per fix pass. Task D/E may add if raster-path coverage prioritized.

2. **Season-window validation tests cover one geometry case only** (`tests/test_hydro_year.py:65-69`). All three validators exist in code; additional cases would be belt-and-suspenders, not required for Task C gate.

### Recommendation

APPROVED — no Critical or Important findings remain. Proceed Task D.
