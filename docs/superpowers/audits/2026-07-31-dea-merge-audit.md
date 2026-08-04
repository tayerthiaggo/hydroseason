# DEA Merge Reconciliation Audit

Date: 2026-07-31

## Scope

Integrated Tasks 3-5 of `docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md` after Stage 1 review.
No push, publish, tag, or release action was performed.

## Commit And Dirty-State Boundary

HydroSeason baseline before this stage: `2c925ac`.

HydroSeason commit created:

- `dc344c0 fix: harden DEA planning and cache contracts`
- `809b61f fix: fail closed on pruned extent denominators`
- `af20e95 fix: reject pruned mask extent fallbacks`

HydroFragments commit created:

- `e20cf58 fix: align hydroseason manifest version expectation`

HydroSeason still has unrelated pre-existing dirty/untracked release docs/core work, including README/docs/report/catchment/dynamic-year files and `pipelines/`. Those were preserved and not swept into the DEA fix commit.

HydroFragments still has unrelated untracked docs:

- `docs/final_metrics_covered.md`
- `docs/superpowers/plans/2026-07-20-user-ready-implementation.md`

## Accepted Findings Fixed

- P0-1: pruned Zarr extent fast path no longer publishes analysis-footprint or inferred full-AOI denominators. When a store records pruning and the analysis footprint is smaller than the full AOI, `open_completed_extent_counts` returns `None`; `load_wofs_monthly_extent` then raises rather than reducing pruned masks into scientific extent percentages. Regressions: `tests/test_io_wofs_zarr.py::test_pruned_extent_counts_do_not_infer_full_aoi_denominator_from_footprints`, `tests/test_io_wofs_zarr.py::test_pruned_extent_counts_fail_closed_when_footprints_are_missing`, and `tests/test_io_wofs_zarr.py::test_load_wofs_monthly_extent_rejects_pruned_zarr_without_exact_counts`.
- P0-2: `open_wo_statistics` now passes `timeout=(STAC_CONNECT_TIMEOUT_S, STAC_READ_TIMEOUT_S)` to `pystac_client.Client.open` and wraps `list(search.items())` in `_run_with_timeout`. Regression: `tests/test_io_dea_stats.py::test_open_wo_statistics_stops_waiting_after_search_deadline`.
- P1-1: `active_windows_from_mask` now rejects `storage_chunk` values that are not multiples of `factor`, avoiding silent dropped native pixels. Regression: `tests/test_spatial_plan.py::test_active_windows_from_mask_rejects_unaligned_storage_chunk`.
- P1-2: fine clipping now has an end-to-end proof over isolated, diagonal, orthogonal, and partial-block wet shapes. `_wet_aoi_from_planning_footprint` also makes the `buffer_m >= close_m` margin explicit.
- P2-1: `composite_bundle="legacy"` is omitted from request digests so pre-composite caches remain reachable; non-legacy bundle values still separate stores.
- P2-2: Ruff import/static findings on reviewed surface were fixed.
- P3-1: accepted as public API gap. `build_wet_planning_footprint` and `WetPlanningFootprint` are exported through `hydroseason.io` and top-level `hydroseason`.

## Rejected Or No-Op Findings

Stage 1 priorities marked PASS were not changed:

- Cache identity separation: retained and rechecked by focused suites; full, legacy-pruned, planning-footprint, and dual requests remain distinct.
- Tamper detection: retained in `verify_cache_footprints`; focused cache-footprint tests pass.
- One-graph dual composite: retained; `tests/test_io.py::test_hydrofragments_v1_builds_one_source_graph_not_one_per_composite` passed during the 105-test Task 3 gate.
- Full-AOI footprint recording: retained through `record_cache_footprints`; exact extent readers verify that metadata for pruned stores and fail closed when it proves analysis pixels are smaller than the full AOI.
- Core-only import isolation and no HydroFragments imports in HydroSeason: package-surface/focused suites pass; no HydroFragments import was added.
- Legacy `wet_mask="off"` default and fail-open pruning discipline: existing focused acquisition suites pass.
- `frequency = 100 * count_wet / count_clear`, zero-clear NaN, and provenance: existing DEA stats tests pass.

## Public DEA/Cache API

Top-level public surface now includes:

- `open_wo_statistics`
- `build_wet_planning_footprint`
- `WetPlanningFootprint`
- `acquire_wofs_cache`
- `open_completed_mask_cache`
- `open_completed_dual_extent_counts`
- `verify_cache_footprints`
- `WOfSCacheHandle`

Recommended pruning path: caller-built `WetPlanningFootprint` passed as `planning_footprint`.

Compatibility-only path: `wet_mask="dea_stats"` polygon pruning. `docs/superpowers/plans/2026-07-27-wofs-wet-mask-pruning.md` now carries a supersession banner.

## Verification

- Red tests first: six new regressions failed on old behavior; final-review denominator tests then failed because the reader returned inferred pruned counts and the facade did not raise for every pruned fallback path.
- New regression set after fixes: 11 passed before final review; final-review denominator regressions: 4 passed.
- Task 3 gate: `python -m pytest tests\test_io_dea_stats.py tests\test_io.py tests\test_package_surface.py -q` -> 105 passed.
- Task 4/final-review gate: `python -m pytest tests\test_io_wofs_zarr.py tests\test_io.py tests\test_io_dea_stats.py tests\test_spatial_plan.py tests\test_io_wofs_acquire.py tests\test_io_cache_footprints.py -q` -> 209 passed.
- Metadata: `python scripts\check_release_metadata.py` -> exit 0.
- Ruff: `python -m ruff check hydroseason tests scripts` -> all checks passed.
- Lock: `uv lock --check` -> resolved 159 packages, exit 0.
- Offline full tests: `python -m pytest -q -m "not experimental and not network and not performance"` -> 580 passed, 2 deselected, 15 warnings.
- Case study data: `python scripts\prepare_case_study_data.py --check` -> all 20 files and hashes intact.
- Docs: `python -m mkdocs build --strict` -> exit 0.
- Build: `python -m build` -> built `hydroseason-0.1.0.tar.gz` and `hydroseason-0.1.0-py3-none-any.whl`.
- Twine: `python -m twine check dist\*` -> both artifacts passed.
- Wheel contents: `python -m check_wheel_contents dist\hydroseason-0.1.0-py3-none-any.whl` -> OK.
- Sdist listing: `tar -tf dist\hydroseason-0.1.0.tar.gz` -> package files only; docs/scripts/data/case_studies excluded, assets included.
- Exact-wheel HydroFragments: temp venv installed `dist\hydroseason-0.1.0-py3-none-any.whl`; import printed `0.1.0` from temp venv `site-packages`; named HydroFragments tests -> 47 passed.

## Warning Ledger

- Offline HydroSeason pytest: 12 NumPy `RuntimeWarning: invalid value encountered in divide` from correlation paths.
- Offline HydroSeason pytest: 3 Zarr `SerializationWarning` messages from `_io_wofs_coarsen.py:185`.
- MkDocs strict build: Material for MkDocs advisory about future MkDocs 2.0 incompatibility; build still exited 0.
- HydroFragments exact-wheel tests: 3 NumPy correlation divide warnings.
- HydroFragments exact-wheel install: pip resolver warning from system-site existing `hydrofragments` metadata requiring `hydroseason==0.1.1`; the test process imported `hydroseason==0.1.0` from the temp venv wheel path and passed.

## Remaining Risks

- Live DEA STAC/network behavior and performance timings were not run; they remain outside offline reconciliation gates.
- Case-study generated docs/results still need the release-readiness continuation to ensure no committed numbers came from old pruned-denominator behavior.
- The temp exact-wheel integration used `--system-site-packages` to reuse installed heavy geospatial dependencies; HydroSeason itself was verified from the temp venv wheel path.
