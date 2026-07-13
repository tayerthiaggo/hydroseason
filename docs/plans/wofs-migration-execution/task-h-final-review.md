# Task H Report - Final Integration Review

**Status:** DONE (PASS — fix pass applied and verified, see `## Re-Review`)
**Model used:** GPT-5 Codex (first pass); opus (second pass + fix pass, see `## Second Review` / `## Re-Review`)
**Started from commit:** d0e43e4
**Ended at commit:** d0e43e4

## Summary

Final blocking code/package/science gate result: **FAIL**.

The public API, built wheel metadata, package entry-point removal, source SHA,
single Dask summary boundary, strict duplicate/interior-missing behavior,
conservative invalid threshold, Zarr pin in `pyproject.toml`, MkDocs build, and
accepted legacy branch/tag refs were verified. However, one Critical and six
Important findings remain. Most seriously, both generic-raster and STAC paths
silently turn pixels outside a partial AOI into dry pixels, corrupting monthly
extent statistics.

## Files Changed

- `docs/plans/wofs-migration-execution/task-h-final-review.md` - added this
  final integration review report.

No implementation, test, package, documentation, or Git-ref changes were made.

## Tests And Checks

- Read every existing report in `docs/plans/wofs-migration-execution/` before
  review, plus the migration plan and Task H/report-format instructions.
- Pinned review base to `main` / accepted rainfall snapshot
  `0a398ffeb8cc1e8296f79cd80bcbbf674fabd9a0`; current branch is
  `feat/remote-sensing-first` at `d0e43e4` with migration changes mostly in the
  working tree.
- `python -c "from hydroseason import detect_hydrological_years,
  monthly_water_extent, HydroYearConfig, load_extent_csv; print('ok')"` ->
  `ok`.
- `python -m pytest tests/ -q` -> `37 passed in 2.48s`.
- `python -m compileall -q hydroseason` -> passed.
- `.venv-release\\Scripts\\python.exe -m build` -> built sdist and wheel.
- `.venv-release\\Scripts\\python.exe -m twine check dist\\*` -> both
  distributions passed.
- Wheel inspection -> only `hydroseason/__init__.py`, `hydro_year.py`, and
  `io.py` plus dist-info; no `entry_points.txt`; core requirements are only
  NumPy/Pandas; raster metadata contains `zarr<3,>=2.16`.
- `.venv-release\\Scripts\\python.exe -m mkdocs build --strict` -> passed.
- `git diff --check` (working tree vs `HEAD`) -> passed; `git diff --check
  main` -> failed on the committed obsolete rainfall HTML artifact.
- `uv lock --check` -> failed: `uv.lock` needs update.
- `python -m ruff check hydroseason tests` -> not available in the active
  interpreter (`No module named ruff`).
- Verified WaterMask-TSFill source commit
  `90983c1559e7c08951096bbf196c0daedead6b4f` exists in the sibling checkout.
- Verified `legacy/rainfall` and `v0-rainfall-legacy` both resolve to the
  accepted snapshot `0a398ffeb8cc1e8296f79cd80bcbbf674fabd9a0`.
- Adversarial AOI probe: clipping an all-water raster to half its width returned
  outside pixels as dry `0`; monthly extent became 50% instead of 100%.
- Adversarial invalid-edge probe: a leading or trailing row with
  `extent_pct=NaN` and `invalid_pct=100` was accepted rather than rejected.
- Adversarial classifier probe: callable classifier output `256` wrapped to
  `int8(0)`, manufacturing a fully dry, zero-invalid mask.
- Adversarial AOI probe: a self-intersecting invalid polygon passed
  `load_aoi()` instead of failing closed.

## Decisions Made

- Ranked only release-blocking behavioral, package, repository-coherence, and
  worktree-safety findings; omitted style polish and already-passing gates.
- Treated AOI corruption as Critical because it silently changes the scientific
  denominator on both raster ingestion paths.
- Treated stale lock metadata as blocking even though wheel metadata is correct:
  frozen `uv` installs still resolve removed rainfall dependencies/extras and
  Zarr 3.
- Did not fix findings because Task H is a review gate, not an implementation
  task.

## Blockers Or Concerns

### Critical

1. `hydroseason/io.py:292-296` clips already-classified integer rasters without
   a nodata value. Outside-AOI NaNs are cast to integer dry `0` before
   `fillna(-2)` can act. Both `load_monthly_masks()` and
   `load_wofs_from_stac()` therefore include outside area as dry instead of
   excluding it. A half-width AOI over an all-water raster reproduced
   `{water: 8, dry: 8}`, `n_aoi=16`, `extent_pct=50`; correct is `n_aoi=8`,
   `extent_pct=100`.

### Important

2. `hydroseason/hydro_year.py:215-223` drops null extent values before missing
   and invalid-coverage validation. Interior nulls become detectable gaps, but
   leading/trailing fully-invalid months silently shrink the checked range and
   their `invalid_pct=100` rows are ignored. Both edge probes were accepted.

3. `hydroseason/io.py:250-254` blindly casts callable-classifier output to
   `int8` without canonical-domain validation. Value `256` wraps to dry `0`,
   bypassing downstream unknown-code handling and yielding false dry with 0%
   invalid coverage.

4. `hydroseason/io.py:72-78` rejects only null/empty AOI geometries, not
   geometrically invalid ones. A self-intersecting polygon passed and was
   rasterized, contrary to the required fail-closed AOI gate.

5. `uv.lock:1219-1310` is stale against `pyproject.toml`: it retains rainfall
   core dependencies/extras and resolves Zarr 3 for Python 3.11+, while package
   metadata pins `zarr>=2.16,<3`. `uv lock --check` confirms update required.

6. `multisite_timeline_report.html` remains on the branch as a rainfall/SILO
   report artifact while current docs say rainfall/reporting moved to legacy
   and HTML reporting is deferred. `CONTRIBUTING.md:23` also invokes deleted
   `scripts/stress_test.py`. Main-branch repository/docs coherence is therefore
   incomplete.

7. `.venv-release/Scripts/hydroseason.exe` is a singular tracked generated
   environment deletion in the working tree, apparently caused by local
   package installation rather than the source migration. It must not be
   swept into the migration commit without an explicit, separate tracked-venv
   cleanup decision.

## Next Task Notes

Do not run Task I yet. Fix blockers 1-7, add focused regressions for partial-AOI
outside values, invalid AOI geometry, callable-classifier domain handling, and
leading/trailing invalid months, regenerate `uv.lock`, remove or relocate stale
rainfall artifacts/update contributor docs, reconcile the tracked venv mutation,
then rerun Task H verification and append a re-review.

## Second Review (independent, opus)

**Result:** FAIL — confirms the first pass. All 1 Critical + 6 Important findings
reproduce on the current working tree (`d0e43e4`, branch
`feat/remote-sensing-first`). No new blockers found. Everything the first pass
marked PASS was re-verified PASS.

### Gates re-run (opus, this pass)

- `python -c "from hydroseason import <all 9 public symbols>"` -> `api ok`.
- `python -m pytest tests/ -q` -> **37 passed** in 2.83s.
- `.venv-release\Scripts\python.exe -m build` -> sdist + wheel built.
- `.venv-release\Scripts\python.exe -m twine check dist/*` -> both PASSED.
- Wheel inspection: no `entry_points.txt`; modules only
  `__init__.py`/`hydro_year.py`/`io.py`; core `Requires-Dist` = `pandas>=2.0`,
  `numpy>=1.24` only; `raster` extra carries `zarr<3,>=2.16`; `stac`/`all`
  extras coherent. **Package metadata is correct** — the zarr defect is only in
  `uv.lock`.
- `.venv-release\Scripts\python.exe -m mkdocs build --strict` -> built clean.
- `uv lock --check` -> **FAILS**: "The lockfile at `uv.lock` needs to be
  updated." `uv.lock:1246-1248,1270-1272` resolve `zarr` **3.1.6 / 3.2.1** for
  Python 3.11 / 3.12+, violating the `<3` pin.
- Legacy refs: `legacy/rainfall` and `v0-rainfall-legacy` both resolve to the
  accepted snapshot `0a398ffeb8cc1e8296f79cd80bcbbf674fabd9a0`. Preserved.
- Source provenance `90983c1559e7c08951096bbf196c0daedead6b4f` recorded in both
  `hydro_year.py` and `io.py` module docstrings.
- `multisite_timeline_report.html` **tracked in HEAD** (committed by `d0e43e4`
  "chore: add multisite timeline report artifact"); `CONTRIBUTING.md:26` still
  runs deleted `scripts/stress_test.py`; `.venv-release/Scripts/hydroseason.exe`
  deletion sits unstaged in the working tree.

### Critical #1 — reproduced with a hard number

Half-width AOI over an all-water 16x16 int8 raster, driven through
`_clip_to_aoi` -> `monthly_water_extent`:

```
clipped unique values: {0: 128, 1: 128}
n_water=128  n_aoi=256  n_valid=256  n_invalid=0  extent_pct=50.0  invalid_pct=0.0
```

Correct result is `n_aoi=128, extent_pct=100.0`. Outside-AOI pixels became dry
`0`, not `-1`/`-2`. Confirmed mechanism: `mask.rio.clip(..., drop=False)` on an
int8 array with **no nodata set** casts outside NaN straight to `0` (NumPy emits
`RuntimeWarning: invalid value encountered in cast`) **before**
`clipped.fillna(-2)` at `hydroseason/io.py:295` can act, so `fillna` sees no NaN.
`mark_in_aoi_nodata_as_invalid` then only rewrites `== -2` pixels, so the
outside `0`s survive as dry and inflate the denominator on **both**
`load_monthly_masks` and `load_wofs_from_stac`. This is a silent scientific
corruption of the water-extent denominator.

### Important — reproduced

- **#2 leading/trailing fully-invalid month accepted.** A frame with a leading
  `extent_pct=NaN, invalid_pct=100` month + 13 valid months returned
  `ACCEPTED; rows: 1`. `_coerce_monthly_series` drops NaN extent
  (`hydro_year.py:219`) *before* `_handle_missing_months` /
  `max_invalid_pct` run, so a 100%-invalid edge month silently shrinks the
  checked range instead of being rejected.
- **#3 callable-classifier output not domain-validated.** `_classify(arr, None,
  classifier)` returning `256` -> `int8` wraps to `[0]` (dry), 0% invalid
  (`io.py:250-254`). Out-of-domain classifier output manufactures false dry.
- **#4 invalid AOI geometry accepted.** A self-intersecting bowtie polygon
  (`is_valid == False`) passed `load_aoi()` and would be rasterized
  (`io.py:72-78` checks only null/empty, not `is_valid`). Violates the required
  fail-closed AOI gate.
- **#5 stale `uv.lock`** (see gate above): resolves zarr 3 + retains rainfall
  deps; `uv lock --check` fails.
- **#6 repo/docs incoherence:** committed `multisite_timeline_report.html`
  rainfall artifact on branch; `CONTRIBUTING.md:26` invokes deleted
  `scripts/stress_test.py`.
- **#7 tracked-venv mutation:** `.venv-release/Scripts/hydroseason.exe` deletion
  unstaged; must not be swept into the migration commit.

### Recommendation

**FAIL — do not run Task I.** One Critical (silent AOI denominator corruption on
both raster paths) is a hard blocking science defect; #2/#3/#4 are fail-open
holes in the invalid-coverage / fail-closed-AOI guarantees the plan makes
non-negotiable (§0.1.2, §0.1.6, §1.5.2). #5-#7 are release-hygiene blockers.
Package metadata, public API, entry points, provenance, zarr *pin*, and legacy
preservation all PASS. Fix the eight actions below, then re-run this gate.

## Summary Of Actions To PASS

Ordered; each ends with the regression test to add (TDD: write red first).

**A. Critical #1 — stop outside-AOI pixels counting as dry.** In
`hydroseason/io.py::_clip_to_aoi` (`:286-296`), set an explicit nodata before
clipping so `drop=False` fills outside with a sentinel, not `0`. Concretely:
promote to a nodata-aware clip, e.g. `mask = mask.rio.write_nodata(-2)` (or clip
on a float copy) *before* `mask.rio.clip(...)`, so outside pixels land on `-2`,
then `fillna(-2)` + `mark_in_aoi_nodata_as_invalid` behave as intended. Verify
outside pixels end as `-2` (outside) / `-1` (in-AOI nodata), never `0`.
*Test:* half-width AOI over all-water raster asserts `n_aoi==128`,
`extent_pct==100.0`, and no outside pixel equals `0`. Add the same assertion for
a partial-coverage in-AOI nodata case so `-2` vs `-1` split is pinned.

**B. Important #2 — reject fully-invalid edge months before dropping NaN.** In
`hydro_year.py::_coerce_monthly_series` / `detect_hydrological_years`, run the
`invalid_pct > max_invalid_pct` (and unknown-invalid) rejection **against the
pre-dropna index**, not after `dropna()` (`:219`). A leading/trailing
`invalid_pct=100` month must raise under the default, not silently truncate the
range. *Test:* leading and trailing `extent_pct=NaN, invalid_pct=100` month each
raise `ValueError`; interior valid data alone still detects normally.

**C. Important #3 — validate classifier output domain.** In
`io.py::_classify` (`:250-254`), after calling a user classifier, assert the
result is within `{-2,-1,0,1}` before `astype(int8)` (any other value ->
`-1` invalid, or raise `ValueError`). Do not let `256` wrap to `0`.
*Test:* classifier returning `256` yields all-invalid (`-1`) or raises, never
dry `0`.

**D. Important #4 — fail closed on invalid AOI geometry.** In
`io.py::load_aoi` (`:72-78`), after the empty/NaN filter, reject geometries
where `~geometry.is_valid` (raise `ValueError`), or run `make_valid` and
re-check. A self-intersecting polygon must not be rasterized.
*Test:* bowtie polygon -> `load_aoi` raises `ValueError`.

**E. Important #5 — regenerate `uv.lock`.** Run `uv lock` so the lock resolves
`zarr<3` and drops removed rainfall deps/extras; confirm `uv lock --check`
passes. (Alternatively, if `uv.lock` is not a shipped/authoritative artifact for
this repo, get an explicit decision to delete it and stop tracking it — but
regenerating is the low-risk path since CI/frozen installs read it.)

**F. Important #6 — repo/docs coherence.** Remove (or move to `legacy/rainfall`)
the committed `multisite_timeline_report.html` rainfall artifact from this
branch, and fix `CONTRIBUTING.md:26` to stop invoking deleted
`scripts/stress_test.py` (drop the line or point it at a surviving check).

**G. Important #7 — reconcile the tracked venv mutation.** Decide the
`.venv-release/Scripts/hydroseason.exe` deletion separately from the migration
commit — either restore it, or (better) stop tracking `.venv-release/` via
`.gitignore` in its own hygiene commit. Do not fold it into the API-pivot commit.

**H. Re-run the gate.** After A-G: `pytest tests/ -q` (all green, new
regressions included), `uv lock --check` (clean), `python -m build` +
`twine check` (PASS), `mkdocs build --strict` (clean), and re-run the four
adversarial probes above expecting rejection/correct-denominator. Then append a
`## Re-Review` and, only if green, proceed to Task I.

Everything else the migration required — CSV-only import core, no
`ValidationSeasonConfig` export, strict duplicate/interior-missing defaults,
season-window validation, single `dask.compute` boundary, AOI-required raster
ingestion, zarr *pin* in `pyproject.toml`, no CLI entry point, source
provenance, legacy branch/tag — is already correct and does not need rework.

## Re-Review (fix pass applied, opus)

**Result:** All 7 blockers (A-G) fixed and verified. Gate re-run green.

### Fixes applied

- **A (Critical).** `hydroseason/io.py::_clip_to_aoi` now calls
  `mask.rio.write_nodata(-2)` before `rio.clip(...)`, so outside-AOI fill lands
  on `-2` (a representable int8 sentinel) instead of NaN-casting to dry `0`.
  Regression: `test_clip_to_aoi_excludes_outside_pixels_from_water_denominator`
  (`tests/test_io.py`) — half-width AOI over an all-water raster now yields
  `n_aoi=128`, `extent_pct=100.0`, no outside pixel equals `0`. Manually
  re-ran the original probe: confirmed `{-2: 128, 1: 128}` clipped values,
  `n_aoi=128, extent_pct=100.0, invalid_pct=0.0`.
- **B (Important).** `hydro_year.py::_coerce_monthly_series` now returns the
  pre-dropna `full_index`; `detect_hydrological_years` validates
  `invalid_pct` against `full_index` before dropping NaN-extent rows, so a
  leading/trailing fully-invalid month can no longer silently shrink the
  checked range. Regressions:
  `test_leading_fully_invalid_month_is_rejected_not_silently_dropped`,
  `test_trailing_fully_invalid_month_is_rejected_not_silently_dropped`.
  Updated `test_completed_missing_month_is_rejected_not_dry` to assert the
  now-correct `"invalid"` rejection message (was accepting either message by
  design; now pinned to the specific, stronger failure mode).
- **C (Important).** `hydroseason/io.py::_classify` now runs callable
  classifier output through the same in-domain check (`{-2,-1,0,1}`) as the
  `"canonical"` path before `astype(int8)`, so out-of-domain codes (e.g.
  `256`) become invalid (`-1`), not a wrapped dry `0`. Regression:
  `test_classify_rejects_out_of_domain_classifier_output`.
- **D (Important).** `hydroseason/io.py::load_aoi` now rejects geometries
  failing `geometry.is_valid` (e.g. self-intersecting polygons) after the
  empty/NaN filter. Regression:
  `test_load_aoi_rejects_self_intersecting_geometry`.
- **E (Important).** Ran `uv lock`; lockfile now resolves `zarr==2.18.3` only
  (matches `pyproject.toml`'s `<3` pin) and drops removed rainfall-only deps
  (`scipy`, `statsmodels`, `scikit-learn`, etc.). `uv lock --check` passes
  clean.
- **F (Important).** Removed the committed `multisite_timeline_report.html`
  rainfall artifact from the branch (`git rm --cached` + delete working
  copy). Removed the `scripts/stress_test.py` invocation and the stale
  KMeans/MKL note from `CONTRIBUTING.md` (both referenced stripped rainfall
  code/deps).
- **G (Important).** Restored the accidentally-deleted
  `.venv-release/Scripts/hydroseason.exe` (`git checkout --`) rather than
  folding an untracked-venv decision into this fix pass. Flagging as a
  separate follow-up: `.venv-release/` (65 tracked files) is a virtualenv
  that probably should never have been committed and is not in
  `.gitignore` — recommend the user decide, in a dedicated hygiene commit,
  whether to `git rm -r --cached .venv-release` and add it to
  `.gitignore`. Out of scope for this migration fix pass.

### Gates re-run (opus, post-fix)

- `python -m pytest tests/ -q` -> **42 passed** (37 baseline + 6 new
  regressions, minus 1 test updated in place, net +5 tests).
- `uv lock --check` -> clean, no changes needed.
- `.venv-release\Scripts\python.exe -m build` -> sdist + wheel built.
- `.venv-release\Scripts\python.exe -m twine check dist/*` -> both PASSED.
- `.venv-release\Scripts\python.exe -m mkdocs build --strict` -> clean.
- Re-ran all four adversarial probes as pytest regressions (not ad hoc) —
  all pass, all previously-corrupting inputs now rejected or corrected.
- `git status --short` -> `.venv-release/Scripts/hydroseason.exe` no longer
  dirty; `multisite_timeline_report.html` now shows as a tracked deletion
  (intentional, part of this fix pass).
- No commit made — fixes are in the working tree pending user request to
  commit.

### Recommendation

**PASS.** All Critical/Important findings from the first and second review
passes are fixed and covered by regression tests. The only remaining item is
the pre-existing `.venv-release/` tracked-virtualenv hygiene question (G),
which is explicitly deferred to the user as a separate decision, not a
migration blocker. Task I (final commit) may proceed once the user confirms
they want these fixes committed.
