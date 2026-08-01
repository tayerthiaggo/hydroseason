# Post-DEA Merge and `0.1.0` Release Readiness Design

**Status:** Approved in conversation on 2026-07-31.

## Purpose

Recover the live HydroSeason worktree after merge commit `36f3919`, preserve
the completed release-readiness work through Task 9, integrate and audit the
DEA-zones functionality, and finish the first public remote-sensing release as
`0.1.0`. Update HydroFragments to consume `hydroseason==0.1.0`; the `0.1.1`
version introduced on the merged branch was an unpublished coordination bump,
not the intended public HydroSeason version.

## Why the Existing Plan Is Replaced

`docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md` correctly
describes Tasks 1-9, which landed in commits `4d4488c` through `c2a98ba`.
It does not describe merge commit `36f3919`, its public DEA APIs, its cache
semantics, or the current index/worktree split. Continuing at Task 10 would
permit the staged pre-merge snapshot to delete about 3,668 lines of merged
code and tests.

The replacement therefore consists of two plans:

1. A short merge-reconciliation plan that restores one coherent tree, audits
   the merged scientific and cache contracts, resolves the version, updates
   HydroFragments' dependency contract, and establishes a green baseline.
2. A release-readiness continuation that records Tasks 1-9 as complete and
   replaces Tasks 10-15 with DEA-aware case-study, documentation, CI, and
   publication work.

## Authoritative Version Decision

- HydroSeason release target: `0.1.0`.
- HydroSeason metadata, fallback version, changelog, artifact names, tags,
  TestPyPI/PyPI smoke tests, and citation examples must agree on `0.1.0`.
- HydroFragments runtime dependency changes from `hydroseason==0.1.1` to
  `hydroseason==0.1.0`.
- No `0.1.1` HydroSeason release or tag is created as part of this work.
- Historical plans may mention `0.1.1` when describing the superseded design,
  but active dependency and execution instructions must not require it.

## Plan 1 Boundary: Merge Reconciliation

### Worktree recovery

The live index matches pre-merge commit `c2a98ba` for the DEA-touched files,
while `HEAD` is merge commit `36f3919`. Recovery must preserve the unstaged
post-Task-9 review fixes, then restore the merged DEA implementation and tests
as a semantic union. It must not use a broad reset or checkout that discards
user changes.

The three merge-conflict surfaces receive explicit review:

- `hydroseason/__init__.py`
- `tests/test_package_surface.py`
- `tests/test_spatial_plan.py`

### DEA contract audit

Audit both pruning mechanisms now present:

- legacy `wet_mask="dea_stats"` / `fetch_dea_stats_wet_aoi` polygon pruning;
- conservative `WetPlanningFootprint` / `planning_footprint` pruning.

The new planning footprint is the recommended cross-repository route. Legacy
behavior may remain for compatibility, but docs and tests must not present the
two as equivalent scientific contracts. The full AOI remains the denominator;
the analysis footprint is an I/O optimization and must be independently
verifiable.

Audit these specific risks before release:

- native wet pixels remain a subset of the expanded coarse planning mask;
- converting a planning footprint for fine clipping cannot shrink the proven
  native-mask superset;
- cache identity distinguishes full-AOI, legacy-pruned, planning-footprint,
  and composite-bundle runs;
- `composite_bundle="legacy"` preserves default behavior;
- dual max-water/median counts share one source graph and persist auditable
  sidecars;
- `open_wo_statistics` documents its real timeout behavior. An elapsed-time
  check after a blocking STAC search is not described as a hard deadline;
- unsigned-COG/GDAL environment scope is sufficient for downstream lazy reads;
- no HydroFragments imports enter HydroSeason.

### Cross-repository dependency update

HydroFragments changes are limited to its dependency contract and associated
version expectations. Known active locations are:

- `D:/RLH/5.6/repos/HydroFragments/pyproject.toml`
- `D:/RLH/5.6/repos/HydroFragments/tests/output/test_manifest.py`
- `D:/RLH/5.6/repos/HydroFragments/tests/output/test_manifest_hydroseason.py`
- `D:/RLH/5.6/repos/HydroFragments/docs/superpowers/plans/2026-07-27-dea-zones-and-catchment-speed.md`

Version-provenance tests should compare automatic values with
`hydroseason.__version__` instead of hard-coding an unpublished version.
Tests intentionally verifying arbitrary supplied provenance may retain a
synthetic version value when the value itself is not a package requirement.

### Reconciliation success

- No staged deletion of merged DEA functionality remains.
- HydroSeason metadata consistently reports `0.1.0`.
- Ruff, metadata validation, focused DEA/cache tests, full offline tests, lock
  verification, and strict documentation build pass.
- Known NumPy correlation and Zarr fill warnings remain recorded for the later
  CI task unless reconciliation touches their cause.
- A HydroSeason `0.1.0` wheel can be installed into an isolated
  HydroFragments environment and its integration tests pass.

## Plan 2 Boundary: Release Readiness Continuation

### Completed history

Tasks 1-9 remain complete and are not reimplemented. Their outputs are
revalidated after reconciliation because the merge touched shared package,
I/O, metadata, and test surfaces.

### Main case study

Rewrite `scripts/_build_study_case_offline.py` around committed
`case_studies/data/extent/*_30m.csv` inputs and one public
`analyze_catchment` route. It must:

- use whole-catchment `extent_pct` only;
- never force hydrological years for aseasonal records;
- create complete route-aware report bundles;
- write checked results under `case_studies/results/main/`;
- support `--check` and fail on drift;
- run from a fresh clone without `output/`.

The current untracked builder and hand-written `docs/study-case.md` are input
material only; they are not accepted as completed Task 10 work.

### Resolution and acquisition evidence

Keep exactly two public case studies. The second study covers resolution and
acquisition performance without conflating experimental factors:

1. Offline scientific fidelity compares 30, 60, 90, and 300 metre committed
   extent inputs for all five catchments.
2. Controlled cold acquisition compares pruning off versus the conservative
   planning footprint at a fixed analysis resolution.
3. Composite bundle behavior is reported separately from resolution and
   pruning; it is not credited as a resolution speedup.

Every timing run uses an empty cache, fixed date/AOI/worker settings, randomized
order, repeated trials, machine/package provenance, and explicit failure rows.

### Documentation

Generated result tables replace hand-copied numbers. User documentation covers:

- `open_wo_statistics`;
- `WetPlanningFootprint` and its superset guarantee;
- `planning_footprint` versus legacy `wet_mask="dea_stats"`;
- full-AOI versus analysis-footprint metadata;
- `open_completed_mask_cache`, `verify_cache_footprints`, and
  `open_completed_dual_extent_counts`;
- `composite_bundle="legacy"` and `"hydrofragments_v1"`;
- route-aware report columns and nullable behavior.

Repository and documentation URLs use lowercase `hydroseason` consistently.

### CI and publication

CI restores the merged tests and gates Ruff, synchronized lock data, supported
Python versions, core/all-extras tests, coverage, generated documentation,
strict MkDocs, wheel/sdist contents, and fresh-wheel smoke tests. Release
workflows derive versioned filenames from validated package metadata rather
than embedding stale `0.1.1` or duplicated literals.

Publication order remains TestPyPI, reviewed release commit, annotated
`v0.1.0` tag, GitHub Release, human-approved PyPI publication, then Zenodo.
No model or automation may publish, move a tag, approve an environment, or
invent a DOI without the maintainer's explicit action.

## Error Handling and Preservation Rules

- Any uncertain pruning condition fails open to full-AOI acquisition.
- Missing or corrupt footprint metadata fails verification; consumers do not
  infer a replacement footprint.
- Generated case-study drift fails `--check` without rewriting files.
- Existing user changes are inventoried before each reconciliation edit.
- No broad `git reset` or recursive checkout is used.
- Recovery commits include only reviewed files from their named repository;
  unrelated user changes and cross-repository edits are never swept into the
  same commit.

## Verification Strategy

Verification proceeds from narrow to broad:

1. metadata/version consistency;
2. package-surface and merge-conflict tests;
3. DEA statistics, spatial planning, acquisition, Zarr, and footprint tests;
4. route/phase/report regression tests;
5. full offline suite with warning accounting;
6. Ruff, lock check, generated-doc checks, and strict MkDocs;
7. wheel/sdist validation and isolated HydroFragments integration;
8. controlled network/performance evidence outside ordinary CI;
9. final release audit against built artifacts.

## Pipeline Shape

Use six stages: worktree recovery; independent DEA review; integration fixes;
case studies and generated docs; CI and publishing automation; final release
audit and human packet. Each stage emits a standalone Markdown contract for
the next stage. No separate judge stage is required unless implementation and
independent review produce a material unresolved disagreement.
