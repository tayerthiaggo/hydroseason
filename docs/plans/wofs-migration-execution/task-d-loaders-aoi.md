# Task D Report - Source-Agnostic Loaders And AOI

**Status:** DONE_WITH_CONCERNS
**Model used:** gpt-5
**Started from commit:** d0e43e4
**Ended at commit:** not committed

## Summary

Created `hydroseason/io.py` from the bounded loader portions of
WaterMask-TSFill commit `90983c1559e7c08951096bbf196c0daedead6b4f`.
CSV extent loading remains NumPy/Pandas-only. Raster/STAC imports are local,
all generic raster and STAC paths require an AOI, and any AOI clip,
rasterization, reprojection, or georeferencing failure raises rather than
continuing with an unclipped raster.

Generic TIFF masks now require explicit `encoding="canonical"`, `"binary"`,
or `"wofs"`, unless a callable classifier is supplied. No dtype-based WOfS
guessing remains. `uint8` binary values retain their binary meaning.

## Files Changed

- `hydroseason/io.py` - source-agnostic CSV, AOI, TIFF, Zarr, and STAC loaders;
  local optional imports; canonical mask conversion and fail-closed AOI helpers.
- `hydroseason/__init__.py` - exports the six planned loader functions.
- `tests/test_io.py` - test-first AOI, CSV-only import, lazy axis/TIFF/Zarr,
  STAC AOI gate, AOI failure, and uint8 binary regression coverage.
- `tests/test_package_surface.py` - checks public loader exports.

## Tests And Checks

- Wrote loader tests before `hydroseason/io.py`; initial run:
  `python -m pytest tests/test_io.py -q` -> 8 expected failures because module
  did not exist.
- `python -m pytest tests/test_io.py tests/test_package_surface.py -q` ->
  `13 passed` after implementation.
- `python -m pytest tests/test_hydro_year.py tests/test_package_surface.py -q`
  -> `17 passed`.
- `python -m compileall -q hydroseason` -> passed.
- `git diff --check` -> passed.

## Decisions Made

- Zarr loader treats cubes as already canonical and AOI-clipped, as permitted
  by plan section 1.5.2; it therefore has no AOI parameter.
- `load_monthly_masks` requires explicit encoding even for canonical data. This
  is stricter than a canonical default and satisfies the audit requirement to
  remove dtype guessing.
- `load_wofs_from_stac` performs WOfS flag classification explicitly and
  creates lazy Dask-backed monthly canonical masks.
- No Git ref, commit, reset, checkout, deletion, or push action was performed.

## Blockers Or Concerns

- A complete one-command suite rerun was blocked by Windows permissions on
  pytest temporary directories (`PermissionError` creating/reading `.lock` in
  the pytest base temp directory). Focused loader and core suites completed
  successfully before/after that infrastructure failure. The blocked temp
  directory is untracked and was not deleted.
- Raster/STAC dependency declarations and Zarr version pinning remain Task E.

## Next Task Notes

- Task E should add the documented raster/STAC extras and pin `zarr>=2,<3`.
- Task G should document canonical values (`0`, `1`, `-1`, `-2`), required AOI
  behavior, explicit raster encodings, and WaterMask-TSFill gapfilling.

## Review

**Result:** APPROVED

**Reviewer model:** opus (fallback reviewer)

**Reviewed:** working-tree diff for `hydroseason/io.py`, `tests/test_io.py`,
`hydroseason/__init__.py`, `tests/test_package_surface.py`; cross-checked the
port against WaterMask-TSFill source `90983c1559e7c08951096bbf196c0daedead6b4f`
(`watermask_tsfill/io/loaders.py`, `watermask_tsfill/wofs.py`). Ran
`pytest tests/test_io.py tests/test_package_surface.py -q` -> 13 passed;
`pytest tests -q` -> 27 passed. Ran two ad-hoc checks: (a) `load_monthly_masks`
returns a dask-backed `DataArray` (`hasattr(m.data,"dask")` True, no eager
compute) and (b) full CSV-only path with `xarray/dask/rioxarray/rasterio/`
`geopandas/zarr/odc/pystac_client/affine` all blocked in `sys.modules` still
imports the package + `hydroseason.io` and runs `load_extent_csv`.

### Scope verdict (each required item)

- **`load_aoi` implemented and exported** - PASS. Defined `hydroseason/io.py:49`,
  in `__all__` (`hydroseason/io.py:369`), re-exported from package
  (`hydroseason/__init__.py:16-23,36`). Validates path/GeoDataFrame, rejects
  missing file, empty frame, and all-empty/NaN geometry; optional `to_crs`.
  Covered by `test_load_aoi_validates_geometry_and_reprojects` and
  `test_load_aoi_rejects_empty_geometry_frame` (`tests/test_io.py:54-68`).
- **Raster loaders require AOI** - PASS. `load_monthly_masks` raises when
  `aoi is None` (`hydroseason/io.py:130-131`); `load_wofs_from_stac` raises
  before any optional STAC import (`hydroseason/io.py:191-192`). This is
  stricter than source, where AOI was optional (source
  `loaders.py:404 aoi is not None`) - correct tightening per plan §1.5.2. Zarr
  loader intentionally has no AOI param (cube assumed pre-clipped, plan §1.5.2).
  Covered by `test_generic_raster_loader_requires_aoi` (`tests/test_io.py:90-96`)
  and `test_stac_loader_requires_aoi_before_optional_stac_imports`
  (`tests/test_io.py:145-149`).
- **AOI clipping/rasterization fails closed** - PASS. `_clip_to_aoi` wraps
  `rio.clip` and re-raises any failure as `AOIRasterizationError`
  (`hydroseason/io.py:277-285`); `mark_in_aoi_nodata_as_invalid` and
  `_inside_aoi_mask_like` likewise convert rasterization failures to
  `AOIRasterizationError` (`hydroseason/io.py:290-301,304-313`); STAC query and
  per-month clip failures become `AOIRasterizationError`
  (`hydroseason/io.py:204-205,219-222`). No fallback to an unclipped raster on
  any path. Covered by `test_raster_loader_fails_closed_when_aoi_cannot_reproject`
  (`tests/test_io.py:127-142`), which drives a no-CRS AOI and asserts the raise.
- **Raster imports stay module-local (CSV-only detection)** - PASS. Only
  `numpy`/`pandas` at module scope (`hydroseason/io.py:14-15`); every
  `xarray`/`rioxarray`/`rasterio`/`geopandas`/`odc.stac`/`pystac_client`/`affine`
  import is inside a function body. Verified empirically with the whole raster
  stack set to `None` in `sys.modules`: package import, `hydroseason.io` import,
  and `load_extent_csv` all succeed. Covered by
  `test_csv_loader_imports_without_raster_dependencies` (`tests/test_io.py:40-51`).
- **Dtype guessing removed** - PASS. Source inferred WOfS-vs-binary from dtype
  (`arr.dtype != np.int8` -> `_classify_wofs_pixel`, source `loaders.py:428-431`).
  Port deletes that; `_validate_classifier` requires explicit
  `encoding="canonical"|"binary"|"wofs"` or a `classifier=` callable, rejects
  both-supplied, rejects non-callable classifier (`hydroseason/io.py:231-237`).
  A uint8 binary mask under `encoding="binary"` stays `{0,1}` and is not run
  through WOfS bit classification. Covered by
  `test_generic_raster_loader_requires_explicit_encoding_or_classifier` and
  `test_uint8_binary_masks_are_not_misclassified_as_wofs`
  (`tests/test_io.py:99-124`).
- **Explicit encoding/classifier required** - PASS (as above). WOfS branch
  (`hydroseason/io.py:252-254`) faithfully reproduces source semantics from
  `wofs.py:classify_wofs_pixels` (RAW_DRY=0 -> 0, RAW_WATER=128 -> 1,
  no-data bit 1 set or NaN -> -1, all else -> -1).
- **Dask laziness preserved** - PASS. Raster reads keep
  `chunks={"x":...,"y":...}` (`hydroseason/io.py:147,177,216`); loaders return
  chunked `DataArray`s and re-`chunk` at the end
  (`hydroseason/io.py:162-165,182,228`); no `.compute()` anywhere in `io.py`.
  Confirmed empirically the returned array is dask-backed and unmaterialized.
- **Tests cover AOI load/reject, AOI failure, lazy shape, uint8 binary-not-WOfS**
  - PASS. All four classes present and green (see item-by-item citations above);
  lazy-shape smoke tests assert `.chunks is not None` for
  `complete_monthly_axis`, `load_monthly_masks`, and `load_monthly_masks_zarr`
  (`tests/test_io.py:71-88,108-124,152-168`).

### Minor (non-blocking)

1. **No STAC happy-path / monkeypatched lazy-shape test for `load_wofs_from_stac`.**
   Only its AOI-required guard is exercised (`tests/test_io.py:145-149`); the
   monthly-compose + clip body is untested (understandable - it needs a STAC
   catalog or heavy mocking). The shared `_classify`/`_combine_observations`/
   `_clip_to_aoi` helpers it depends on are exercised via the TIFF path, so risk
   is limited. Optional: a monkeypatched `pystac_client`/`odc.stac` test to lock
   in the lazy monthly-mask shape. Task F/H may cover.

2. **Redundant AOI reprojection in `_clip_to_aoi` -> `mark_in_aoi_nodata_as_invalid`.**
   `_clip_to_aoi` passes the original (unprojected) `aoi_gdf`
   (`hydroseason/io.py:287`), and `mark_in_aoi_nodata_as_invalid` re-runs
   `load_aoi(aoi)` + `.to_crs(crs)` (`hydroseason/io.py:291,296`). Functionally
   correct (idempotent reproject), just an avoidable re-read/reproject per month.
   Not a bug; flagging for a possible efficiency pass.

### Notes / non-blocking

- Source provenance recorded in the module docstring
  (`hydroseason/io.py:3-5`) matches the pinned commit. Good.
- Making AOI mandatory for `load_monthly_masks`/`load_wofs_from_stac` is a
  deliberate, plan-required divergence from source (where it was optional) -
  correct, not a regression.
- Raster/STAC dependency declarations + zarr pin are correctly deferred to
  Task E, as the report states.

### Recommendation

APPROVED - no Critical or Important findings remain. All eight review-scope
requirements verified in code and by passing tests (13 Task-D, 27 total).
Minors 1-2 are optional and non-blocking. Proceed to Task E.

