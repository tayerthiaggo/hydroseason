# Task 9 Review: Per-row multi-AOI workflow

## Verdict: Needs fixes

### P1 - Required behavioural tests are missing

Task 9 explicitly requires tests for preview-before-workers and `show_map=False`,
preview warnings/failure isolation, outcome conversion and `KeyboardInterrupt`,
resource delegation/scheduling, progress prefixing, and import surface.

The diff adds one execution test at
`tests/test_workflow_many.py:252` and extends package-surface assertions at
`tests/test_package_surface.py:29`. The execution test covers the three row calls,
their order, one-row GeoDataFrames, child output/cache paths, and `show_map=False`.
It does not exercise preview order or warnings, failed `run_hydroseason` calls and
continued AOIs, batch-level resource delegation/memory admission, progress events,
or `KeyboardInterrupt` propagation through `run_hydroseason_many`.

Existing `tests/test_batch_scheduler.py` tests scheduler primitives, including
resources and `KeyboardInterrupt`, but not that this public API delegates to them
with the required prepared rows and worker arguments. Add the missing public-API
contract tests before approval.

## Implemented-contract evidence

- Public signature and result annotation are present in
  `hydroseason/batch.py:104`; its merged progress type is
  `bool | Callable[[ProgressEvent], None]`.
- All four exact public exports are imported and included in `__all__` at
  `hydroseason/__init__.py:49` and `hydroseason/__init__.py:81`.
- `_prepare_batch_aois` builds exactly one copied row per source position and assigns
  `<root>/<safe-id>` output/cache paths (`hydroseason/batch.py:275`).
- Preview runs after all rows are prepared and before work items are scheduled;
  it concatenates the rows, supplies safe-ID labels, and converts preview exceptions
  to warnings (`hydroseason/batch.py:198`). `show_map=False` is forwarded to every
  single-AOI call (`hydroseason/batch.py:218`).
- The public API resolves resources, estimates each prepared AOI, and calls the
  memory-bounded scheduler (`hydroseason/batch.py:138-163`).
- Ordinary worker exceptions become ordered outcomes (`hydroseason/batch.py:257`);
  the scheduler catches `Exception`, not `BaseException`, so `KeyboardInterrupt`
  propagates. Progress labels are prefixed without changing step numbers
  (`hydroseason/batch.py:250`).
- `hydroseason.batch` has no module-level `geopandas`, `psutil`, or `pyproj` import.
  Its existing optional-import test passed.

## Standards

No documented coding-standard violation found. The public API follows the
keyword-only convention after its leading AOI argument, uses modern annotations,
and limits new top-level exports to user-facing API. `git diff --check` passed.

## Verification

- Passed: `python -m pytest tests/test_batch_scheduler.py tests/test_package_surface.py -q -p no:cacheprovider` - 29 passed.
- Passed: `python -m pytest tests/test_workflow_many.py::test_batch_module_import_does_not_eagerly_import_geopandas -q -p no:cacheprovider` - 1 passed.
- The requested full focused command did not complete within 64 seconds in this
  worktree. Existing Task 9 evidence and current worktree warnings point to Windows
  temporary-directory ACL/cleanup locks; per the review instruction, this is treated
  as environmental rather than a code finding.
- `ruff` is not installed on this runner, so lint was not executed.

## Review round 1 update

### Added public-API coverage

`tests/test_workflow_many.py` now exercises the missing Task 9 contracts:

- one combined safe-ID-labelled preview before the first worker;
- no preview for `show_map=False`;
- preview failure warning while all workers still run;
- `resolve_batch_resources` delegation, estimated work items, and explicit
  `workers=4` scheduler semantics;
- one `ValueError` converted to its source-ordered failed outcome while its
  neighbours succeed;
- `KeyboardInterrupt` propagation; and
- per-AOI-prefixed progress events that retain the single workflow's five steps.

### Test isolation correction

The first focused full-suite attempt after adding coverage exposed a test-only
isolation issue. `test_batch_module_import_does_not_eagerly_import_geopandas`
temporarily reloads `hydroseason.batch`; its monkeypatch cleanup restores the
`sys.modules` entry while the package attribute still refers to the reload.
String-target monkeypatches therefore modified the reload while the tests
invoked functions from the restored module, allowing a fake worker test to
enter real DEA I/O. The tests now acquire the active module via
`importlib.import_module("hydroseason.batch")` and patch that exact object.

The shared GeoDataFrame fixture was also corrected to produce one default
geometry per supplied id; tests using one or three explicit IDs previously
failed while constructing their input, before calling the public API.

### Evidence and remaining verification

- Passed before the full-suite isolation correction:
  `python -m pytest tests/test_workflow_many.py -k run_many -q -p no:cacheprovider --timeout=20`
  — `8 passed, 18 deselected in 0.88s`.
- A bounded full focused command with `-p no:cacheprovider` reached the
  pre-existing row-isolation test and timed out only because its stale module
  patch called real DEA I/O. This was corrected as described above.
- Per the user's stop-retry instruction, the focused suite was not rerun after
  that test-isolation correction. The earlier Windows pytest temporary-lock ACL
  limitation remains documented above.
- No production implementation change was required in this round. Ruff was not
  run after the stop-retry instruction; the runner previously reported that
  `ruff` is not installed.
