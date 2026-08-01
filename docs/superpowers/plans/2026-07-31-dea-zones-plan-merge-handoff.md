# DEA Zones Plan Merge Handoff

> **Note:** Consumed by reconciliation audit (`2026-07-31-dea-merge-reconciliation.md`).

**For:** reassessing the hydroseason audit given what just landed on `development`.
**Merge commit:** `36f3919` (development), 8 new commits on top of `b37ce3b`.
**Companion plan:** `HydroFragments/docs/superpowers/plans/2026-07-27-dea-zones-and-catchment-speed.md`
(the full cross-repo plan; this doc is the hydroseason-side summary of what actually shipped).

## What landed, in one paragraph

A native DEA Water Observation Statistics loader (`open_wo_statistics`) and a
conservative coarse wet-pixel planning footprint built from it
(`build_wet_planning_footprint`), wired into `acquire_wofs_cache` as new
optional parameters (`wet_mask="dea_stats"`, `planning_footprint=...`,
`composite_bundle="hydrofragments_v1"`) that prune remote WOfS reads to the
footprint and write a second, distinguishable "analysis footprint" alongside
the existing full-AOI footprint in cache metadata. Package version bumped
0.1.0 → 0.1.1. All new acquisition parameters default to today's existing
behavior — no existing caller's output changes unless they opt in.

## Relationship to `2026-07-27-wofs-wet-mask-pruning.md`

That earlier plan (Shapely polygon buffer over `ga_ls_wo_fq_myear_3` +
`ga_ls_wo_fq_cyear_3`, unioned and buffered) is a **different, earlier
approach to the same problem** — pruning WOfS reads to a wet-pixel mask. The
DEA-zones plan's own text explicitly supersedes it:

> "Replace only the unsafe scientific/planning coupling: the current
> `max(resolution, 100)` plus nearest-resampled polygon must become one
> native statistics read followed by conservative max pooling and
> storage-aligned windows."

Confirm whether `2026-07-27-wofs-wet-mask-pruning.md`'s work is (a) already
superseded and safe to archive, (b) partially landed and now redundant with
`_io_dea_stats.py`, or (c) an unrelated write-path optimisation (the blake2b
hashing, empty-year fast path) that's still independently valid regardless
of which pruning approach wins. Worth resolving explicitly rather than
carrying two competing pruning mechanisms forward silently.

## New files

- `hydroseason/_io_dea_stats.py` (528 lines) — `open_wo_statistics()`,
  `WetPlanningFootprint`, `build_wet_planning_footprint()`,
  `DEAStatsUnavailable`, `WoStatisticsUnavailable`.

## Modified files, by what actually changed

- **`_io_wofs_acquire.py`** — `acquire_wofs_cache()` gained: `wet_mask:
  Literal["off", "dea_stats"] = "off"`, `planning_footprint:
  WetPlanningFootprint | None = None`, `composite_bundle: Literal["legacy",
  "hydrofragments_v1"] = "legacy"`, plus several performance/concurrency
  knobs (`compute_batch_size`, `read_workers`, `resampling_policy`,
  `year_workers` — some of these may already have existed pre-plan, check
  the real diff if the exact origin matters for your audit).
- **`_io_wofs_zarr.py`** — cache metadata now persists a second "analysis
  footprint" (geometry, pixel count, digest) alongside the existing full-AOI
  footprint, independently verifiable via the new `verify_cache_footprints`.
  Optional dual (max-water + median) extent counts persisted per year when
  `composite_bundle="hydrofragments_v1"`, read back via
  `open_completed_dual_extent_counts`.
- **`_io_geo.py`, `_spatial_plan.py`** — smaller additive helpers
  (`_configure_cog_read_env`, `active_windows_from_mask`, `GridWindow`)
  supporting the above.
- **`io.py`, `__init__.py`** — new public exports: `open_wo_statistics`,
  `open_completed_mask_cache`, `verify_cache_footprints`,
  `open_completed_dual_extent_counts`. (Merged into your report-bundle
  work's own `__init__.py`/`__all__` additions during this merge — both
  sides' exports are present, see the merge commit `36f3919` for the exact
  resolution if you want to check it wasn't botched.)
- **`pyproject.toml`, `CITATION.cff`** — version 0.1.0 → 0.1.1. (`CITATION.cff`
  and the `__version__` fallback string in `__init__.py` needed a
  controller-added fix during the merge — `test_release_metadata.py`'s
  consistency gate caught both; worth spot-checking those two files if you
  want independent confirmation.)

## What did NOT change

- `WOFS_CACHE_SCHEMA_VERSION`, `MASK_CHUNKS`, `_STORAGE_CHUNK`,
  `WOFS_CLASSIFIER_VERSION`, `WOFS_PLANNER_VERSION` — untouched (matching
  `2026-07-27-wofs-wet-mask-pruning.md`'s own "do not change" list, for
  whichever parts of this plan's work overlaps with it).
- Canonical mask domain (`-2`/`-1`/`0`/`1`) — untouched, this plan's new
  pruning logic reuses it, does not introduce a new sentinel.
- No HydroFragments imports anywhere in hydroseason — verified per-commit
  across all 8 commits during the final whole-branch review (see
  HydroFragments' own plan doc's ledger for detail), not just spot-checked.
- Every existing `acquire_wofs_cache` caller's behavior is unchanged when
  the new parameters are omitted (`wet_mask="off"`, `composite_bundle="legacy"`
  are both the pre-existing defaults).

## Test status at merge time

271 passed, 106 skipped, 1 deselected, 1 pre-existing failure
(`test_prepare_case_study_data.py::test_committed_case_study_data_matrix_is_complete`
— confirmed via an isolated checkout of `development` alone, before this
merge, to fail identically; not caused by this merge, and not investigated
further here since it's your own in-progress case-study data work, not
DEA-zones-plan territory).

## Merge mechanics, if it matters for your audit trail

`development` had moved 17 commits since this plan's branch point (your own
report-bundle, regime-classification, and phase-model work). The merge was
performed in an isolated clone (never touching your live working tree or its
uncommitted changes), with three textual conflicts — all in shared
`__all__`/export lists (`hydroseason/__init__.py`,
`tests/test_package_surface.py`, `tests/test_spatial_plan.py`'s import
header) — resolved as straightforward unions of both sides' additions, not
semantic rewrites. Full diff of the merge commit (`36f3919`) shows exactly
what was touched if you want to review the conflict resolutions yourself.

## Suggested audit entry points

1. `hydroseason/_io_dea_stats.py` — new, self-contained, the core of what
   changed. `build_wet_planning_footprint`'s docstring states its own
   correctness contract (`native_mask <= expand(coarse_mask)`); its test
   suite (`tests/test_io_dea_stats.py`) proves this on several adversarial
   cases (isolated single pixel, thin diagonal/orthogonal channels, partial
   edge blocks).
2. `acquire_wofs_cache`'s new parameters in `_io_wofs_acquire.py` — check
   the default-path no-op claim yourself if you want independent
   verification beyond this doc's summary.
3. The dual-footprint cache metadata in `_io_wofs_zarr.py` — this is the
   piece HydroFragments' own APSEC/LPI denominator correctness depends on
   (a real bug was found and fixed on the HydroFragments side late in this
   plan precisely because a mask wasn't being read correctly downstream —
   see that plan's own ledger, "Final whole-branch review" section, if you
   want the full story of what that bug was and how it was caught).
