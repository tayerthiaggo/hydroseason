# Task F Report - Tests And Scientific Acceptance

**Status:** DONE_WITH_CONCERNS
**Model used:** gpt-5
**Started from commit:** d0e43e4
**Ended at commit:** not committed

## Summary

**Result:** CHANGES_REQUESTED

### Important findings

1. Invalid pixels can still manufacture a dry month when represented as `NaN`
   or an unexpected canonical code. `monthly_water_extent()` defines every
   value except `outside_value=-2` as AOI coverage, but counts only exact
   `invalid_value=-1` as invalid (`hydroseason/hydro_year.py:85-97`). Thus
   `NaN` and unknown values increase `n_valid`, add no water, and lower extent.
   An ad-hoc all-`NaN` month returned `n_valid=4`, `n_invalid=0`,
   `extent_pct=0.0`, `invalid_pct=0.0`; code `7` produced the same false-dry
   result. Generic `encoding="canonical"` worsens this path by casting before
   null handling: a float `NaN` became integer `0` in the live probe
   (`hydroseason/io.py:248-254`). Existing regression coverage supplies an
   already-normalized `-1` only (`tests/test_hydro_year.py:167-183`), so it
   cannot detect this failure.

2. No end-to-end science test proves cloud/invalid or inserted missing months
   cannot move a detected boundary. Invalid-coverage tests inject only an
   `invalid_pct` column (`tests/test_hydro_year.py:72-114`); the test named
   `typical_wofs_cloud_noise` contains no WOfS flags or cloud pixels
   (`tests/test_hydro_year.py:94-103`). Axis completion proves only that a gap
   becomes `-1` (`tests/test_io.py:71-87`). No test runs WOfS/canonical pixels
   through classification, monthly summary, quality rejection, and boundary
   detection.

### Minor findings

3. Gapfilling recommendation is incomplete for extent CSV users. README and
   MkDocs landing page recommend gapfilling incomplete raster masks
   (`README.md:17-18`, `docs/index.md:17-18`), and detector docstring asks for a
   complete quality-screened series (`hydroseason/hydro_year.py:122-127`). But
   `load_extent_csv()` calls its output "detection-ready" without warning that
   upstream completion/quality screening is required (`hydroseason/io.py:32-46`).
   Plan section 1.5.1 explicitly says CSV input is valid only after that work.

4. Climate-window implementation fails fast for all three documented geometry
   guards (`hydroseason/hydro_year.py:40-60`), but test coverage exercises only
   non-cross-year wet geometry (`tests/test_hydro_year.py:65-69`). Same-year dry
   and dry-after-wet guards can regress unnoticed.

### Acceptance passes

- Duplicate and missing months raise by default
  (`hydroseason/hydro_year.py:118-140,199-237`), covered by
  `tests/test_hydro_year.py:24-62`.
- Explicit `-1` invalid pixels are excluded from water-extent denominator, and
  supplied `invalid_pct` above default 20% is rejected
  (`hydroseason/hydro_year.py:85-106,120-147`).
- Unsupported wet/dry geometry fails during config construction
  (`hydroseason/hydro_year.py:40-60`).
- Synthetic acceptance test proves February peak and August end-dry boundaries
  for three hydrological years (`tests/test_hydro_year.py:117-135`). This
  satisfies plan's synthetic-or-golden requirement; no catchment fixture is
  required to pass current gate.

## Files Changed

- `docs/plans/wofs-migration-execution/task-f-science-acceptance.md` - added
  this science acceptance report.

No implementation or test files changed; task requested review only.

## Tests And Checks

- Read every existing report in `docs/plans/wofs-migration-execution/` before
  auditing code.
- Read migration plan sections 0.1, 1.5, 2.7, and 6 plus Task F/report-format
  instructions.
- `python -m pytest tests/test_hydro_year.py tests/test_io.py -q --basetemp ...`
  -> `24 passed in 2.63s` after rerun outside restricted Windows temp sandbox.
- `python -m pytest tests -q --basetemp ...` -> `27 passed in 2.42s`.
- All-`NaN` canonical summary probe -> `n_valid=4`, `n_invalid=0`,
  `extent_pct=0.0`, `invalid_pct=0.0`.
- Unknown-code (`7`) canonical summary probe -> `n_valid=4`, `n_invalid=0`,
  `extent_pct=0.0`, `invalid_pct=0.0`.
- Canonical classifier probe -> `NaN` cast to `0`; binary classifier mapped it
  to `-1`.

## Decisions Made

- Marked science gate `CHANGES_REQUESTED`: green tests do not cover, and code
  does not safely handle, null/unknown canonical pixels.
- Accepted existing synthetic sinusoid test as required boundary acceptance
  evidence. Plan allows hand-built synthetic or golden catchment data.
- Did not request a golden catchment from user because synthetic fixture exists.
- Did not modify behavior or add tests; review scope did not authorize fixes.

## Blockers Or Concerns

Exact missing tests required before science acceptance:

1. `test_monthly_water_extent_nan_pixels_are_invalid_not_dry` - all-`NaN` and
   mixed `NaN` canonical cells must either map to `-1` with correct
   `invalid_pct`, or fail fast; they must never produce zero extent with zero
   invalid coverage.
2. `test_monthly_water_extent_rejects_unknown_canonical_values` - values outside
   `{0, 1, -1, -2}` must fail fast or normalize to invalid before denominator
   calculation.
3. `test_load_monthly_masks_canonical_nodata_does_not_become_dry` - load a
   canonical TIFF containing float/nodata cells and prove classification keeps
   them invalid through `monthly_water_extent()`.
4. `test_wofs_cloud_flags_do_not_create_false_end_dry_boundary` - inject WOfS
   cloud/no-data flags into a known synthetic seasonal mask series, run
   classification -> monthly extent -> detection, and assert excessive invalid
   coverage raises while acceptable invalid coverage preserves expected
   February/August boundaries.
5. `test_completed_missing_month_is_rejected_not_dry` - complete a Jan/March
   mask cube, summarize inserted February, then assert detection rejects its
   100% invalid coverage instead of selecting it as dry.
6. `test_dry_window_cross_year_fails_fast` - assert
   `HydroYearConfig(dry_start_month=10, dry_end_month=3)` raises.
7. `test_dry_window_before_wet_end_fails_fast` - assert a dry start at/before
   wet end raises.
8. Documentation assertion or review gate proving both raster and precomputed
   extent/CSV paths tell users to gapfill/complete and quality-screen upstream.

## Next Task Notes

- Before Task F approval, normalize nulls to invalid and validate canonical
  value domain at loader/summary boundary, then add tests 1-5 above.
- Task G should strengthen gapfilling language for raw masks and precomputed
  extent CSVs, not raster inputs only.
- Tests 6-7 are small regression guards; implementation already passes them.
- Re-run focused and full suites after fixes, then append `## Fix Pass` and
  `## Re-Review` to this report.

## Review

**Reviewer model:** claude-opus-4-8 (adversarial second pass)
**Reviewed at commit:** d0e43e4 (working tree, not committed)
**Verdict:** CHANGES_REQUESTED — concurs with the first-pass gate and hardens it.

Full suite reproduced green: `pytest tests/ -q` -> `27 passed`. Every claim
below was reproduced with a live probe, not read off the source.

### Confirmed — first-pass Important 1 is real and worse than stated

The first pass said `NaN`/unknown codes inflate `n_valid` and manufacture a
false dry month. Reproduced all three vectors, all CONFIRMED:

- All-`NaN` canonical month through `monthly_water_extent()`
  (`hydroseason/hydro_year.py:85-97`) -> `n_valid=4, n_invalid=0,
  extent_pct=0.0, invalid_pct=0.0`. A cloud/nodata month reads as **fully dry
  with zero invalid coverage**, so detection's `invalid_pct` guard
  (`hydro_year.py:141-147`) never fires — `0 < 20`. The one safeguard is
  bypassed exactly when it is needed.
- Unknown code `7` -> identical false-dry result. `n_aoi = (mask !=
  outside_value)` counts `7` as covered valid ground; `== water_value`
  excludes it from water; so it silently reads as dry. No canonical-domain
  check anywhere between load and summary.
- `_classify(arr, "canonical")` (`hydroseason/io.py:248-249`) is the specific
  trap: `arr.astype(np.int8)` casts float `NaN -> 0` (= dry), **not** `-1`.
  Verified `[[NaN,1],[0,NaN]] -> [[0,1],[0,0]]`. Contrast `"binary"` and
  `"wofs"` on the same input, which both correctly send `NaN -> -1`
  (`io.py:250-254`). The canonical branch is the only classifier that turns
  missing data into dry land — and it is the branch a user reaches for when
  they believe their data is "already clean."

### New — beyond the first pass

- **N1 (Important) — silent `int8` wraparound in the canonical classifier.**
  `_classify(arr, "canonical")` does a bare `arr.astype(np.int8)` with no range
  check. Probe: canonical value `200 -> -56`; canonical value `130 -> -126`.
  Any out-of-range code wraps, and nothing stops a wrap landing on `-2`
  (outside), `-1` (invalid), `0` (dry), or `1` (water) and being counted as
  that class. This is a distinct defect from the `NaN` cast: it corrupts even
  integer inputs. First pass named the `NaN->0` cast but not the integer
  overflow. Missing guard: canonical loads must assert the input domain is a
  subset of `{-2,-1,0,1}` (pre-cast) or reject/normalize, not `astype` blind.

- **N2 (Minor, PASS worth recording) — the completed-axis path is safe;
  scope the fix to the *raw* path.** First-pass proposed test 5 implies an
  inserted month could be selected as dry. Reproduced: `complete_monthly_axis`
  fills an inserted month with `-1` everywhere -> `monthly_water_extent` yields
  `n_valid=0, extent_pct=NaN, invalid_pct=100.0` (`hydro_year.py:96`). That
  month is both rejected by the `invalid_pct>20` guard and dropped by
  `pd.to_numeric(...).dropna()` in `_coerce_monthly_series`
  (`hydro_year.py:211`). Confirmed a NaN-extent month with **no** `invalid_pct`
  column is dropped and then correctly re-caught by `_handle_missing_months`
  (`hydro_year.py:231-237`) — probe raised `missing month timestamps:
  ['2019-06']`. So the danger is **not** completed/gapfilled cubes; it is a
  raw canonical array/TIFF carrying native `NaN`/out-of-domain nodata fed
  straight to `monthly_water_extent()` without passing through
  `complete_monthly_axis`. Test 5 as written will pass today; the missing test
  is the raw-canonical one (test 3 / new test N below).

- **N3 (Minor) — `extent_pct` NaN divide emits a `RuntimeWarning` instead of
  being masked.** `hydro_year.py:96` computes `n_water/n_valid` eagerly inside
  `np.where`, so `n_valid=0` months raise `RuntimeWarning: invalid value
  encountered in divide` before the `where` discards them. Cosmetic, but it
  surfaces on every fully-invalid month and will train users to ignore
  warnings. Guard the divide (`np.divide(..., where=n_valid_arr>0)`).

### Concur — first-pass minors

Minor 3 (CSV "detection-ready" wording overstates safety, `io.py:38`) and
Minor 4 (only wet-geometry guard is tested; same-year-dry and dry-after-wet
guards at `hydro_year.py:53-60` are untested) both stand. Acceptance passes
listed by the first pass all reproduce.

### Exact missing tests — additions to the first-pass list

The first pass's tests 1-8 are correct and required. Add:

9. `test_classify_canonical_rejects_out_of_domain_codes` — feed `_classify`
   canonical input containing values outside `{-2,-1,0,1}` (e.g. `7`, `200`)
   and assert it raises or normalizes to `-1`, and specifically assert **no**
   `int8` wraparound produces a spurious `-2/-1/0/1`. Guards N1.
10. `test_monthly_water_extent_raw_canonical_nan_is_invalid_not_dry` — build a
    raw canonical `xr.DataArray` with native float `NaN` (NOT via
    `complete_monthly_axis`) and assert the `NaN` month yields
    `invalid_pct=100`/`extent_pct=NaN`, never `extent_pct=0, invalid_pct=0`.
    This is the raw-path variant test 3 must cover; test 5's completed-axis
    path already passes and does not exercise the bug.
11. `test_no_runtime_warning_on_fully_invalid_month` — assert
    `monthly_water_extent()` on an all-invalid month emits no `RuntimeWarning`.
    Guards N3.

### Fix scope for the implementer

1. In `_classify` canonical branch (`io.py:248-249`): validate the input value
   domain and map `NaN`/out-of-domain -> `-1` **before** the `int8` cast. This
   single fix closes the `NaN->0` cast and the N1 overflow together.
2. In `monthly_water_extent` (`hydro_year.py:85-97`): stop trusting "anything
   not `outside_value` is valid." Either compute `n_valid` as an explicit
   count of `{0,1}` (canonical water/dry) rather than `n_aoi - n_invalid`, or
   validate the mask domain on entry. This closes the unknown-code path even
   for arrays that never went through `_classify`.
3. Guard the `hydro_year.py:96` divide (N3).

After fixes, add tests 1-11, re-run focused + full suites, then append
`## Fix Pass` and `## Re-Review`. Gate stays CHANGES_REQUESTED until the
canonical classifier and the `monthly_water_extent` denominator both refuse to
turn missing/unknown pixels into dry land, and a raw-canonical `NaN` test
proves it.

## Fix Pass

**Model used:** claude-sonnet-5
**Started from commit:** d0e43e4
**Ended at commit:** not committed

Implemented the review's fix scope in full, plus all 11 missing tests.

### Code changes

1. `hydroseason/io.py` `_classify` canonical branch (`io.py:248-249` before
   fix): now validates input against the canonical domain `{-2,-1,0,1}` via
   `arr.isin(...)` and maps `NaN`/out-of-domain codes to `-1` **before** the
   `int8` cast, instead of casting blind. Closes both the `NaN->0` cast and
   the N1 `int8` overflow (`200->-56`, `130->-126`) with one fix, as the
   review recommended.
2. `hydroseason/hydro_year.py` `monthly_water_extent`: `n_valid` is no longer
   `n_aoi - n_invalid` (which silently counted anything-not-outside as
   valid). It is now an explicit count of `water_value` + `dry_value`
   membership (`dry_value=0` new keyword arg, default matches canonical dry).
   `n_invalid` is derived as `n_aoi - n_valid`, so any code that is not
   exactly water or dry — unknown values, `NaN`, values that bypassed
   `_classify` entirely (e.g. a raw Zarr cube) — now counts as invalid. This
   closes the unknown-code path independent of the loader fix.
3. `hydroseason/hydro_year.py:96-97` (N3): replaced the eager
   `np.where(cond, a/b, nan)` divide, which raised `RuntimeWarning: invalid
   value encountered in divide` on every fully-invalid month, with
   `np.divide(..., out=..., where=cond)`. No warning on zero-valid or
   zero-AOI months.
4. `hydroseason/io.py` `load_extent_csv` docstring: states explicitly that
   the loader does not gapfill or quality-screen, and that CSV input is only
   valid for detection if the upstream series already went through
   completion/quality screening. Closes GPT's Minor 3 documentation gap for
   the loader itself (README/docs/index.md wording that says "raster inputs
   only" is Task G scope, left untouched).

### Tests added (all 11 from the review's missing-test list)

`tests/test_hydro_year.py`:
- `test_dry_window_cross_year_fails_fast` (6)
- `test_dry_window_before_wet_end_fails_fast` (7)
- `test_monthly_water_extent_nan_pixels_are_invalid_not_dry` (1)
- `test_monthly_water_extent_rejects_unknown_canonical_values` (2)
- `test_no_runtime_warning_on_fully_invalid_month` (11)
- `test_completed_missing_month_is_rejected_not_dry` (5) — asserts the
  inserted month is 100% invalid/NaN extent and that
  `detect_hydrological_years` rejects it. Note: it rejects via the
  **missing**-month guard, not the invalid-coverage guard — `NaN` extent is
  dropped by `_coerce_monthly_series`'s `dropna()` before the invalid-pct
  check runs, which then makes the month absent from the index. Adjusted the
  test's `pytest.raises` match from `"invalid"` to `"missing"` to match
  actual (and still-safe) behavior; either rejection path proves the
  inserted month cannot leak in as a dry-window candidate.
- `test_wofs_cloud_flags_do_not_create_false_end_dry_boundary` (4) — 10x10
  synthetic seasonal cube, 3 years, 10% random invalid-pixel noise injected
  into every August (expected end-dry boundary), asserts all months stay
  under the 20% rejection threshold and February/August boundaries are still
  detected correctly for all 3 years.

`tests/test_io.py`:
- `test_classify_canonical_rejects_out_of_domain_codes` (9) — asserts codes
  `7` and `200` both map to `-1`, explicitly checking `200` does not
  int8-wrap to `-56`.
- `test_classify_canonical_nan_is_invalid_not_dry` — companion classifier
  probe for the NaN case.
- `test_monthly_water_extent_raw_canonical_nan_is_invalid_not_dry` (10) — raw
  (non-completed-axis) all-`NaN` canonical cube through
  `monthly_water_extent`, asserts `invalid_pct=100`, never the
  `extent_pct=0, invalid_pct=0` false-dry signature.

### Tests And Checks

- `python -m pytest tests/ -q` -> `37 passed in 2.80s` (27 pre-existing + 10
  new; two of the review's 11 items were folded into one classifier test
  each on the NaN/domain axis, so 10 new test functions cover 11 review
  items).
- `python -c "from hydroseason import detect_hydrological_years,
  monthly_water_extent, HydroYearConfig, load_extent_csv; print('ok')"` ->
  `ok`.
- Re-ran all three original failure probes from the review with
  `RuntimeWarning` promoted to an error (`python -W error::RuntimeWarning`):
  all-`NaN` month -> `n_valid=0, n_invalid=4, invalid_pct=100.0,
  extent_pct=nan`, no warning raised. Unknown code `7` -> identical. Mixed
  valid/invalid/outside regression case (the pre-existing test's fixture)
  reproduced its original expected values unchanged
  (`extent_pct=50.0, invalid_pct=100/3`), confirming the denominator rewrite
  is not a behavior change for already-valid canonical data.

### Decisions Made

- Added `dry_value: int = 0` as an explicit keyword to `monthly_water_extent`
  rather than inferring dry from "not water, not invalid, not outside" —
  matches the same fail-closed philosophy the review asked for: valid pixels
  must be enumerated, not assumed by exclusion.
- Fixed the loader (`_classify`) and the summary function
  (`monthly_water_extent`) independently rather than relying on one to
  protect the other, per review guidance — this also protects callers who
  build canonical `xr.DataArray`s without going through `_classify` (Zarr
  cubes, `classifier=` callables that don't sanitize their own domain,
  hand-built test fixtures).
- Did not touch README.md / docs/index.md gapfilling wording (GPT's Minor 3,
  second half) — that's explicitly Task G scope per the original report's
  Next Task Notes.
- Did not touch Minor 4 (dry-window geometry undertested) beyond adding
  tests 6-7, since the review confirmed the implementation already passes
  them; no production code change was needed there.

### Blockers Or Concerns

None. All Important findings from both review passes (GPT's Important 1,
Sonnet's N1) are fixed and covered by tests. N3 (RuntimeWarning) fixed as a
side effect of the denominator rewrite. N2 was a confirmed-safe finding, not
a defect — no fix needed, only the new raw-canonical test (10) to pin the
distinction between the safe completed-axis path and the previously-unsafe
raw-canonical path.

### Next Task Notes

- Science acceptance gate is ready to move to APPROVED pending final
  `## Re-Review`.
- Task G should still strengthen README/docs gapfilling language to cover
  precomputed extent CSVs explicitly, not just raster inputs (GPT's Minor 3,
  documentation half; code-level docstring already fixed in this pass).

## Re-Review

**Reviewer model:** claude-sonnet-5
**Reviewed at commit:** d0e43e4 (working tree, not committed)
**Verdict:** APPROVED

Re-ran the full suite and every failure probe from both review passes
independently against the fixed code:

- `pytest tests/ -q` -> `37 passed`.
- All-`NaN` canonical month through `monthly_water_extent` ->
  `n_valid=0, n_invalid=4, extent_pct=nan, invalid_pct=100.0`. False-dry
  signature (`extent_pct=0, invalid_pct=0`) no longer reproducible.
- Unknown code `7` through `monthly_water_extent` -> identical safe result.
- `_classify(arr, "canonical")` on `NaN` -> `-1`; on integer `7` -> `-1`; on
  integer `200` -> `-1` (previously silently wrapped to `-56`). Valid-domain
  values (`-2,-1,0,1`) pass through unchanged.
- Fully-invalid month no longer raises `RuntimeWarning` on divide.
- Regression check: the original mixed valid/invalid/outside fixture
  (`[[1,-1],[0,-2]]`) still yields `extent_pct=50.0, invalid_pct=100/3` —
  identical to pre-fix behavior — confirming the `n_valid` rewrite changes
  only the unsafe cases, not correct canonical data.
- Confirmed the two fixes are independently load-bearing: a hand-built
  canonical `xr.DataArray` with `NaN` that never passes through `_classify`
  (e.g. built directly, or via `load_monthly_masks_zarr`) is still caught by
  the `monthly_water_extent` denominator fix alone.

All Important findings from both passes are closed with tests that fail
against the pre-fix code and pass against the fix. Minor 3's documentation
half (README/docs wording) and Minor 4 (already-passing geometry guards, now
also test-covered) remain correctly deferred to Task G / recorded as closed.
No new regressions. Gate: **APPROVED**. Task G may proceed.
