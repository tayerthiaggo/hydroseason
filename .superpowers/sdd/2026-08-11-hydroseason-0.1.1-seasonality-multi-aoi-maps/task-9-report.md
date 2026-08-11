# Task 9 Report: Per-row multi-AOI workflow

## Delivered

- Added `run_hydroseason_many` in `hydroseason.batch`.
- Preserves source rows: each prepared AOI is scheduled independently and invokes
  `run_hydroseason(None, ...)` with its one-row GeoDataFrame, safe child output/cache
  paths, and `show_map=False`.
- Validates output/cache paths, the date range, map mode, progress mode, and batch
  resources before scheduling futures.  Per-row preparation remains complete before
  scheduler admission.
- Uses `estimate_aoi_peak_gb`, `resolve_batch_resources`, and `run_memory_bounded`.
  Worker results and ordinary exceptions become ordered `HydroSeasonAOIOutcome`
  values; scheduler interruption semantics remain intact.
- Adds a best-effort combined AOI preview when the Task 6 map mode resolves true.
  Its display/context failure warns without preventing AOI work.
- Merges progress by passing each single run a callback that prefixes the AOI id while
  retaining the single-workflow five-step event numbering.
- Exports `HydroSeasonAOIOutcome`, `HydroSeasonBatchError`,
  `HydroSeasonBatchResult`, and `run_hydroseason_many` from the package surface.

## Tests added

- Row-isolation integration contract: three distant source rows make three single
  workflow calls in input order, retain their original geometry, use independent
  report/cache children, and suppress per-row maps.
- Strict top-level package-surface assertions for all four batch exports.

## TDD evidence

1. The new row-isolation test initially failed as intended with:
   `ImportError: cannot import name 'run_hydroseason_many'`.
   After implementation it passed: `1 passed in 0.57s`.
2. The package-surface test initially failed as intended because the required four
   names were absent from `hydroseason.__all__`.  After adding exports it passed:
   `1 passed in 0.47s`.

## Focused-test evidence and limitation

- Before Task 9 changes, the requested focused baseline command completed with
  `47 passed in 0.88s`:

  `python -m pytest tests/test_workflow_many.py tests/test_batch_scheduler.py tests/test_package_surface.py -q -p no:cacheprovider`

- After changes, the same command with `-p no:cacheprovider` started successfully
  but pytest could not create cleanup locks below its default Windows temp directory:
  `PermissionError: [Errno 13] Permission denied: ... pytest-...\\.lock`.
  The observable result was `5 passed, 14 errors in 3.14s`; these errors occur in
  pytest's `tmp_path` fixture setup, before the affected tests execute.
- A worktree-local `--basetemp` retry was attempted to avoid that external ACL, but
  the runner stalled and timed out.  It was not retried after the user requested that
  test retries stop.  Consequently the full required focused suite and workflow
  regressions were not freshly green after the final edits.

## Scope and concerns

- Changed only the Task 9 implementation, public exports, Task 9 tests, and this
  report.
- No module-level `geopandas`, `psutil`, or `pyproj` imports were introduced in
  `hydroseason.batch`; map/geospatial imports remain inside the preview/preflight
  paths.
- Remaining concern: rerun the two user-specified pytest commands in an environment
  where pytest can create its temporary-directory cleanup locks.
