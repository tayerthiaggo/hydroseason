# WOfS Migration Agent Task Prompts

**Primary plan:** `docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md`

**Recommendation:** execute in parts with `superpowers:subagent-driven-development`, not as one giant plan execution. Run one task, review it, fix blockers, then continue. Task A is a hard preflight gate: do not start Task B until the dirty worktree and legacy snapshot decision is settled.

**Available models considered:** `gpt-5.3`, `gpt-5.4`, `gpt-5.5`, `gpt-5.6`, `claude sunnet`, `opus`, `fable`, `composer 2.5`, `grok 4.5`, `kimi 2.7`.

## Model Strategy

Use `gpt-5.6` for scientific/geospatial correctness and final blocking reviews. Use `gpt-5.5` for broad repo/package implementation. Use `gpt-5.4` for low-risk final commit/handoff mechanics. Use `claude sunnet` for docs rewrite. Keep `opus` as an optional second final reviewer if you want extra confidence. Do not use `fable`, `composer 2.5`, `grok 4.5`, or `kimi 2.7` as primary executors for this migration; they are not the best fit for package/science correctness work here.

## Execution Reports

Store every task result in `docs/plans/wofs-migration-execution/`. Create the folder before Task A if it does not exist. Each task must read all earlier reports before starting, then write its own report before returning.

Use these exact report paths:

- Task A: `docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md`
- Task B: `docs/plans/wofs-migration-execution/task-b-strip-manifest.md`
- Task C: `docs/plans/wofs-migration-execution/task-c-detection-core.md`
- Task D: `docs/plans/wofs-migration-execution/task-d-loaders-aoi.md`
- Task E: `docs/plans/wofs-migration-execution/task-e-packaging.md`
- Task F: `docs/plans/wofs-migration-execution/task-f-science-acceptance.md`
- Task G: `docs/plans/wofs-migration-execution/task-g-docs.md`
- Task H: `docs/plans/wofs-migration-execution/task-h-final-review.md`
- Task I: `docs/plans/wofs-migration-execution/task-i-final-commit.md`

Each report must use this structure:

```markdown
# Task X Report - Short Name

**Status:** DONE | DONE_WITH_CONCERNS | BLOCKED
**Model used:** model name
**Started from commit:** short SHA or "not committed"
**Ended at commit:** short SHA or "not committed"

## Summary

## Files Changed

## Tests And Checks

## Decisions Made

## Blockers Or Concerns

## Next Task Notes
```

When reviewing a task, append a `## Review` section to that task's report instead of creating a separate file. If a fix pass is needed, append `## Fix Pass` and then append the re-review under `## Re-Review`.

## Reviewer Prompt Template

Use this template after any implementer task that changed files. Replace `[TASK]`, `[TASK REPORT]`, and `[TASK SCOPE]` with the task-specific values below.

```text
Review [TASK] for the WOfS hydro-year migration.

Read:
- docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md
- docs/plans/2026-07-13-wofs-migration-agent-tasks.md
- [TASK REPORT]
- all earlier reports in docs/plans/wofs-migration-execution/
- the git diff for this task

Review scope: [TASK SCOPE]

Check spec compliance first, then code quality. Focus on behavioral bugs, missed requirements, unsafe file/git operations, broken public API, package/docs/test regressions, and missing tests. Do not review unrelated pre-existing code unless the task changed or depends on it.

Append your review to [TASK REPORT] under `## Review`.

Return:
- APPROVED if no Critical or Important findings remain.
- CHANGES_REQUESTED if fixes are needed, with findings ordered by severity and exact file/line references.
```

## Controller Prompt

**Model:** `gpt-5.6`

```text
Use superpowers:subagent-driven-development to execute docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md task-by-task. Do not execute the whole plan as one task. Use docs/plans/2026-07-13-wofs-migration-agent-tasks.md as the execution prompt map. Store task results in docs/plans/wofs-migration-execution/ using the report paths and report format from the Execution Reports section. Run tasks in order, dispatch one implementer per task, review after each task, fix Critical/Important findings before continuing, and do not push. Stop only for dirty legacy snapshot decisions, branch/tag publishing decisions, missing golden acceptance data, or an unrecoverable blocker.
```

## Task A - Legacy Snapshot And Branch Safety

**Implementer model:** `gpt-5.5`

**Reviewer model:** `gpt-5.5`

**Implementer prompt:**

```text
You are in D:\RLH\5.6\repos\hydroseason. Execute only the legacy snapshot safety work from docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0.1 and 2.1. Inventory the dirty worktree with git status/diff, classify which dirty files must be preserved in the rainfall legacy snapshot, and stop before any destructive action or push. Do not create/delete branches until the dirty-file decision is explicit. Return: dirty-file table, recommended action per file, current HEAD SHA, and any branch/tag name collisions.

Before returning, write docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md using the report format in docs/plans/2026-07-13-wofs-migration-agent-tasks.md.

Additionally, address these CHANGES_REQUESTED findings from the reviewer (see ## Review in task-a-legacy-snapshot.md)
Append your fix under ## Fix Pass in task-a-legacy-snapshot.md, do not overwrite ## Review.
```

**Reviewer prompt:**

```text
Review Task A for the WOfS hydro-year migration.

Read:
- docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md
- docs/plans/2026-07-13-wofs-migration-agent-tasks.md
- docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md
- the git status and any diff created by Task A

Review scope: legacy snapshot safety only. Confirm the dirty worktree was inventoried, dirty files were classified, current HEAD SHA was recorded, branch/tag collisions were checked, and no destructive action, branch creation, tag creation, or push happened without an explicit decision.

Append your review to docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md under `## Review`.

Return:
- APPROVED if no Critical or Important findings remain.
- CHANGES_REQUESTED if fixes are needed, with findings ordered by severity and exact file/line references.
```

## Task B - Rainfall Strip Manifest

**Implementer model:** `gpt-5.5`

**Reviewer model:** `gpt-5.5`

**Implementer prompt:**

```text
Read docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 1, 2.3, and 0.1. Build the exact strip/keep manifest for hydroseason/, tests/, docs/, notebooks/, config/, scripts/, pyproject.toml, conda/meta.yaml, mkdocs.yml, README.md, CITATION.cff, MANIFEST.in, and GitHub workflows. Verify cross-references with rg before editing. Implement only the manifest changes needed to remove rainfall APIs and broken entry points. Do not port WaterMask-TSFill code in this task. Add or update tests only if needed to prove imports/package metadata do not reference stripped modules.

Before starting, read docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md. Before returning, write docs/plans/wofs-migration-execution/task-b-strip-manifest.md using the report format in docs/plans/2026-07-13-wofs-migration-agent-tasks.md.
```

**Reviewer prompt:**

```text
Review Task B for the WOfS hydro-year migration.

Read:
- docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md
- docs/plans/2026-07-13-wofs-migration-agent-tasks.md
- docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md
- docs/plans/wofs-migration-execution/task-b-strip-manifest.md
- the git diff for Task B

Review scope: rainfall strip manifest and rainfall API removal only. Confirm stripped modules/tests/docs/config references match the plan, no WaterMask-TSFill code was ported in this task, public/package entry points are not left pointing at removed modules, and tests or import checks cover the changed surface.

Append your review to docs/plans/wofs-migration-execution/task-b-strip-manifest.md under `## Review`.

Return:
- APPROVED if no Critical or Important findings remain.
- CHANGES_REQUESTED if fixes are needed, with findings ordered by severity and exact file/line references.
```

## Task C - Detection Core Port

**Implementer model:** `gpt-5.6`

**Reviewer model:** `gpt-5.6`

**Implementer prompt:**

```text
Port WaterMask-TSFill commit 90983c1559e7c08951096bbf196c0daedead6b4f watermask_tsfill/hydro_year.py into hydroseason/hydro_year.py per docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0.1, 1.5, and 2.4. Keep detect_hydrological_years and label_hydrological_months importable with only numpy/pandas. Do not export ValidationSeasonConfig. Add strict duplicate/missing month policies, supported season-window validation, invalid coverage handling, and conservative max_invalid_pct behavior. Fix monthly_water_extent to avoid invalid-as-dry behavior and use one shared dask.compute boundary. Write focused tests for each behavior before implementation.

Before starting, read docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md and docs/plans/wofs-migration-execution/task-b-strip-manifest.md. Before returning, write docs/plans/wofs-migration-execution/task-c-detection-core.md using the report format in docs/plans/2026-07-13-wofs-migration-agent-tasks.md.
```

**Reviewer prompt:**

```text
Review Task C for the WOfS hydro-year migration.

Read:
- docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md
- docs/plans/2026-07-13-wofs-migration-agent-tasks.md
- docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md
- docs/plans/wofs-migration-execution/task-b-strip-manifest.md
- docs/plans/wofs-migration-execution/task-c-detection-core.md
- the git diff for Task C

Review scope: detection core only. Confirm CSV-only importability, no exported ValidationSeasonConfig, strict duplicate/missing month behavior, season-window validation, invalid coverage handling, no invalid-as-dry bug, one shared dask.compute boundary for monthly summaries, and focused tests for each behavior.

Append your review to docs/plans/wofs-migration-execution/task-c-detection-core.md under `## Review`.

Return:
- APPROVED if no Critical or Important findings remain.
- CHANGES_REQUESTED if fixes are needed, with findings ordered by severity and exact file/line references.
```

## Task D - Source-Agnostic Loaders

**Implementer model:** `gpt-5.6`

**Reviewer model:** `gpt-5.6`

**Implementer prompt:**

```text
Create the new hydroseason/io.py loaders from docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 1.5 and 2.4a. Port only the needed loader code from WaterMask-TSFill commit 90983c1559e7c08951096bbf196c0daedead6b4f. Implement load_aoi, the minimal private AOI/georeferencing helpers, load_extent_csv, complete_monthly_axis, load_monthly_masks, load_monthly_masks_zarr, and load_wofs_from_stac. Require AOI for STAC and generic raster mask loaders; fail closed if AOI clipping/rasterization fails. Keep raster imports module-local so CSV-only detection does not require xarray/rasterio/dask/zarr/geopandas. Remove dtype guessing: require encoding="canonical"|"binary"|"wofs" or classifier=callable. Add load_aoi tests, lazy-shape smoke tests, AOI-failure tests, and a uint8 binary-not-WOfS regression test.

Before starting, read docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md, docs/plans/wofs-migration-execution/task-b-strip-manifest.md, and docs/plans/wofs-migration-execution/task-c-detection-core.md. Before returning, write docs/plans/wofs-migration-execution/task-d-loaders-aoi.md using the report format in docs/plans/2026-07-13-wofs-migration-agent-tasks.md.
```

**Reviewer prompt:**

```text
Review Task D for the WOfS hydro-year migration.

Read:
- docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md
- docs/plans/2026-07-13-wofs-migration-agent-tasks.md
- all earlier reports in docs/plans/wofs-migration-execution/
- docs/plans/wofs-migration-execution/task-d-loaders-aoi.md
- the git diff for Task D

Review scope: source-agnostic loaders and AOI support only. Confirm load_aoi is implemented and exported as planned, raster loaders require AOI, AOI clipping/rasterization fails closed, raster imports stay module-local for CSV-only detection, dtype guessing was removed, explicit encoding/classifier is required, Dask laziness is preserved, and tests cover AOI load/reject behavior, AOI failure, lazy shape, and uint8 binary-not-WOfS behavior.

Append your review to docs/plans/wofs-migration-execution/task-d-loaders-aoi.md under `## Review`.

Return:
- APPROVED if no Critical or Important findings remain.
- CHANGES_REQUESTED if fixes are needed, with findings ordered by severity and exact file/line references.
```

## Task E - Dependency And Packaging Cleanup

**Implementer model:** `gpt-5.5`

**Reviewer model:** `gpt-5.5`

**Implementer prompt:**

```text
Update pyproject.toml, uv.lock if required, conda/meta.yaml, MANIFEST.in, GitHub workflows, and package metadata per docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0.1, 2.6, and 2.7. Keep core dependencies minimal for CSV-only detection. Move raster/STAC deps to extras, pin zarr>=2,<3 until a v3 migration is tested, remove rainfall-only dependencies and CLI entry points, and remove tests that call hydroseason --version if cli.py is gone. Verify python -m build, twine check, package import smoke, and mkdocs strict when available.

Before starting, read all existing reports in docs/plans/wofs-migration-execution/. Before returning, write docs/plans/wofs-migration-execution/task-e-packaging.md using the report format in docs/plans/2026-07-13-wofs-migration-agent-tasks.md.
```

**Reviewer prompt:**

```text
Review Task E for the WOfS hydro-year migration.

Read:
- docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md
- docs/plans/2026-07-13-wofs-migration-agent-tasks.md
- all earlier reports in docs/plans/wofs-migration-execution/
- docs/plans/wofs-migration-execution/task-e-packaging.md
- the git diff for Task E

Review scope: dependencies, packaging, entry points, workflows, and package metadata. Confirm CSV-only core dependencies remain minimal, raster/STAC extras contain the required geospatial stack, zarr is pinned >=2,<3, rainfall-only dependencies and CLI entry points are removed, conda/GitHub workflow/package metadata are coherent, and build/twine/import/mkdocs checks were run or clearly reported as unavailable.

Append your review to docs/plans/wofs-migration-execution/task-e-packaging.md under `## Review`.

Return:
- APPROVED if no Critical or Important findings remain.
- CHANGES_REQUESTED if fixes are needed, with findings ordered by severity and exact file/line references.
```

## Task F - Tests And Scientific Acceptance

**Implementer/reviewer model:** `gpt-5.6`

**Optional second reviewer:** `opus`

**Review prompt:**

```text
Review the implemented hydroseason water-mask detection behavior against docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0.1, 1.5, 2.7, and 6. Focus only on scientific correctness and test gaps. Verify invalid/cloud pixels cannot create false dry months, missing/duplicate months are strict by default, unsupported climate windows fail fast, gapfilled/completed series are recommended, and at least one synthetic or golden catchment test proves expected boundary detection. Return findings first with file/line references and exact missing tests.

Before starting, read all existing reports in docs/plans/wofs-migration-execution/. Before returning, write docs/plans/wofs-migration-execution/task-f-science-acceptance.md using the report format in docs/plans/2026-07-13-wofs-migration-agent-tasks.md.
```

## Task G - Docs Rewrite

**Implementer model:** `claude sunnet`

**Reviewer model:** `gpt-5.5`

**Implementer prompt:**

```text
Rewrite README.md, docs/, mkdocs.yml nav, CHANGELOG.md, CITATION.cff, and examples per docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0, 0.1, 2.8, 4, and 5. Remove current rainfall workflow promises from main docs. Document the three supported input paths: extent CSV, generic binary/canonical rasters, and WOfS/STAC. Strongly advise users to run WaterMask-TSFill gapfilling before applying hydroseason to incomplete/raw masks. Explain that rainfall implementation lives on legacy/rainfall. Keep docs concise and ensure mkdocs build --strict passes.

Before starting, read all existing reports in docs/plans/wofs-migration-execution/. Before returning, write docs/plans/wofs-migration-execution/task-g-docs.md using the report format in docs/plans/2026-07-13-wofs-migration-agent-tasks.md.
```

**Reviewer prompt:**

```text
Review Task G for the WOfS hydro-year migration.

Read:
- docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md
- docs/plans/2026-07-13-wofs-migration-agent-tasks.md
- all earlier reports in docs/plans/wofs-migration-execution/
- docs/plans/wofs-migration-execution/task-g-docs.md
- the git diff for Task G

Review scope: docs, examples, navigation, changelog, citation, and user-facing migration language. Confirm rainfall workflow promises are removed from current docs, all three input paths are documented, WaterMask-TSFill gapfilling is strongly recommended before incomplete/raw mask detection, AOI is explained for raster/STAC workflows, legacy/rainfall is mentioned accurately, and mkdocs strict was run or clearly reported as unavailable.

Append your review to docs/plans/wofs-migration-execution/task-g-docs.md under `## Review`.

Return:
- APPROVED if no Critical or Important findings remain.
- CHANGES_REQUESTED if fixes are needed, with findings ordered by severity and exact file/line references.
```

## Task H - Final Integration Review

**Reviewer model:** `gpt-5.6`

**Optional second reviewer:** `opus`

**Review prompt:**

```text
Perform a final review of the branch implementing docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md. Review as a blocking code/package/science gate, not style polish. Check public API, dependency extras, package entry points, docs coherence, Dask laziness, invalid coverage handling, missing/duplicate month behavior, source provenance, zarr pin, AOI-required raster ingestion, fail-closed AOI clipping/rasterization, and legacy rainfall preservation. Run the verification commands if possible. Return only findings ordered by severity, then a short pass/fail recommendation.

Before starting, read all existing reports in docs/plans/wofs-migration-execution/. Before returning, write docs/plans/wofs-migration-execution/task-h-final-review.md using the report format in docs/plans/2026-07-13-wofs-migration-agent-tasks.md.
```

## Task I - Final Commit

**Implementer model:** `gpt-5.4`

**Reviewer model:** `gpt-5.5`

**Implementer prompt:**

```text
After all tests/docs/package gates are green and final review blockers are resolved, create small logical commits for the migration described in docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md. Do not push. Use a breaking-change commit message for the public API pivot. Include the legacy rainfall branch/tag SHA and WaterMask-TSFill source SHA in the final handoff.

Before starting, read all existing reports in docs/plans/wofs-migration-execution/. Before returning, write docs/plans/wofs-migration-execution/task-i-final-commit.md using the report format in docs/plans/2026-07-13-wofs-migration-agent-tasks.md.
```

**Reviewer prompt:**

```text
Review Task I for the WOfS hydro-year migration.

Read:
- docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md
- docs/plans/2026-07-13-wofs-migration-agent-tasks.md
- all reports in docs/plans/wofs-migration-execution/
- docs/plans/wofs-migration-execution/task-i-final-commit.md
- git log for the new commits
- git status

Review scope: final commit and handoff only. Confirm all final-review blockers were resolved before committing, commits are small/logical, no push occurred, the breaking-change message is present, git status is expected, and the final handoff includes the legacy rainfall branch/tag SHA and WaterMask-TSFill source SHA.

Append your review to docs/plans/wofs-migration-execution/task-i-final-commit.md under `## Review`.

Return:
- APPROVED if no Critical or Important findings remain.
- CHANGES_REQUESTED if fixes are needed, with findings ordered by severity and exact file/line references.
```

## Notes

`gpt-5.3` is acceptable only for small follow-up fixes after review, not for the main migration tasks. `grok 4.5` or `kimi 2.7` can be useful for a separate brainstorming pass, but not as the implementation lead here. `composer 2.5` and `fable` are not recommended for this package migration.
