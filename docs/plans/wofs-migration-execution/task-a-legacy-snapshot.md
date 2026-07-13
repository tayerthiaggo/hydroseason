# Task A Report - Legacy Snapshot And Branch Safety

**Status:** BLOCKED
**Model used:** claude-sonnet-5
**Started from commit:** 07f3666
**Ended at commit:** 07f3666 (not committed — no commits made this task)

## Summary

Ran preflight inventory only, per plan §0.1 and §2.1. Worktree on branch `development` (not `main`) is dirty across 16 tracked-modified files and 10 untracked paths. No destructive action, no branch/tag creation, no push performed. Task stops here per instructions — dirty-file classification is presented for explicit user sign-off before `legacy/rainfall` is cut.

## Files Changed

None. Read-only inventory task.

## Tests And Checks

- `git status --short`
- `git diff --stat`
- `git rev-parse HEAD`
- `git branch --show-current`
- `git branch --list legacy/rainfall` / `git tag --list v0-rainfall-legacy` / `git branch --list feat/remote-sensing-first` (collision check)
- Read diff content for ambiguous docs (`docs/task.md`, `docs/plan.md`, `docs/hydroseason_refactor.md`, `docs/science_summary.md`, `DOCS_REPRODUCIBILITY_GUIDE.md`) to classify rainfall-coupling.

## Decisions Made

**Current HEAD SHA:** `07f3666d93c7bae8b348a80522aaa31857b95c9e` (`feat(pipeline): implement hybrid and true Liebmann methods`)
**Current branch:** `development` (plan assumed a feature branch would be cut from a clean state; note plan §2.2 expects `feat/remote-sensing-first` to branch off — confirm whether it should branch from `development` or `main`).

**Branch/tag collisions:** none. `legacy/rainfall`, `v0-rainfall-legacy` tag, and `feat/remote-sensing-first` all currently unused — safe to create once dirty-file decision is made.

### Dirty-file table and recommended action

| File | Git state | §1 disposition | Recommended action |
|---|---|---|---|
| `hydroseason/config.py` | Modified | STRIP | Commit into legacy snapshot — rainfall `AlgorithmConfig`/`DailyDetectionConfig` edits |
| `hydroseason/dynamic_season.py` | Modified | STRIP | Commit into legacy snapshot — true-Liebmann/hybrid segmentation edits (this session's active work) |
| `hydroseason/fetch.py` | Modified | STRIP | Commit into legacy snapshot — daily SILO fetch additions |
| `hydroseason/io.py` | Modified | STRIP (rainfall `io.py`; will be replaced by new loader `io.py` later in the migration) | Commit into legacy snapshot |
| `hydroseason/pipeline.py` | Modified | STRIP | Commit into legacy snapshot — hybrid/true-Liebmann wiring |
| `hydroseason/plot.py` | Modified | STRIP | Commit into legacy snapshot |
| `hydroseason/report.py` | Modified | STRIP (design-reference only per §5.2) | Commit into legacy snapshot |
| `hydroseason/validate.py` | Modified | STRIP | Commit into legacy snapshot — daily validation additions |
| `hydroseason/__init__.py` | Modified | REWRITE (later, on `feat/remote-sensing-first`) | Commit into legacy snapshot as-is first; rewritten separately in Step 2.6, not part of this task |
| `hydroseason/daily_detection.py` | Untracked (new) | STRIP | Commit into legacy snapshot |
| `hydroseason/stress.py` | Untracked (new) | STRIP | Commit into legacy snapshot |
| `tests/test_australia_stress.py` | Modified | STRIP | Commit into legacy snapshot |
| `tests/test_cumulative_anomaly.py` | Modified | STRIP | Commit into legacy snapshot |
| `tests/test_pipeline.py` | Modified | STRIP | Commit into legacy snapshot |
| `tests/test_plot.py` | Modified | STRIP | Commit into legacy snapshot |
| `tests/test_daily_detection.py` | Untracked (new) | STRIP | Commit into legacy snapshot |
| `tests/test_stress.py` | Untracked (new) | STRIP | Commit into legacy snapshot |
| `scripts/australia_stress_test.py` | Modified | STRIP | Commit into legacy snapshot |
| `scripts/evaluate_against_gt.py` | Untracked (new) | STRIP | Commit into legacy snapshot — rainfall ground-truth evaluation tooling |
| `scripts/generate_gt_template.py` | Untracked (new) | STRIP | Commit into legacy snapshot — rainfall ground-truth template generator |
| `data/australia_50_sites_ground_truth_template.csv` | Untracked (new) | STRIP | Commit into legacy snapshot — rainfall GT data |
| `multisite_timeline_report.html` | Untracked (new) | Generated artifact, not source | **Needs explicit user call**: generated rainfall-pipeline report output. Recommend excluding from any commit (add to `.gitignore` or leave untracked) rather than committing a build artifact into history — confirm with user before either committing or deleting |
| `docs/science_summary.md` | Modified | Rainfall-algorithm science doc (Liebmann/CUSUM/HMM design notes) | Commit into legacy snapshot |
| `docs/task.md` | Deleted | Rainfall implementation task checklist (all items already `[x]` done, superseded by this session's work) | Confirm deletion is intended (looks like cleanup of a finished checklist) — commit the deletion into legacy snapshot; the completed checklist content itself is not needed on `main` after strip regardless |
| `docs/plan.md` | Untracked (new) | Rainfall "daily-first stress window detector" refactor plan — an *earlier*, now-superseded rainfall design doc, not the WOfS migration plan | Commit into legacy snapshot |
| `docs/hydroseason_refactor.md` | Untracked (new) | Rainfall "hydrological stress first" reframe brief | Commit into legacy snapshot |
| `DOCS_REPRODUCIBILITY_GUIDE.md` | Untracked (new) | Repo-agnostic documentation/UX standards template — **not rainfall-coupled** | Keep on both `legacy/rainfall` and the post-strip working branch; not part of the rainfall-vs-water-mask split |
| `docs/plans/` (dir: `2026-07-13-migrate-wofs-hydroyear-from-watermask.md`, `2026-07-13-wofs-migration-agent-tasks.md`, `wofs-migration-execution/`) | Untracked (new) | This is the WOfS migration's own control/plan documentation — **not rainfall content** | Must be committed and must survive on the working branch that continues the migration (`development`/`feat/remote-sensing-first`), independent of the legacy/rainfall split. Also fine to carry into `legacy/rainfall` (harmless), but must not be legacy-only |

### Summary recommendation

Two commits before branching, in this order:

1. **Legacy-scoped commit** (on current branch, before cutting `legacy/rainfall`): everything in the STRIP rows above — all 21 rainfall-coupled files/dirs. This becomes the exact snapshot `legacy/rainfall` and `v0-rainfall-legacy` point at.
2. **Migration-plan commit** (separate, or same commit — user's call): `docs/plans/` + `DOCS_REPRODUCIBILITY_GUIDE.md`, since these must persist on the working branch regardless of the rainfall strip and are not "legacy-only" content.

`multisite_timeline_report.html` is the one item that isn't a clean STRIP/KEEP call — it's a build artifact, not source. Flagging for explicit user decision per plan §0.1 rule 1 ("generated artifact not meant for history → get explicit user approval before deleting/ignoring it").

## Blockers Or Concerns

1. **Branch base mismatch**: plan §2.2 says `git checkout -b feat/remote-sensing-first` (implying off current branch), but current branch is `development`, not `main`. Plan text elsewhere (§0 intro) frames this as stripping "main". User must confirm: does `legacy/rainfall` / `feat/remote-sensing-first` branch from `development` (current HEAD, `07f3666`), or should `main` be checked out first? This changes what "exact snapshot" means.
2. **`multisite_timeline_report.html` disposition** — generated artifact, needs explicit user approval per plan rule, not auto-classified here.
3. **`docs/task.md` deletion** — deletion looks intentional/correct (finished checklist) but is being surfaced for confirmation since deletions are irreversible-in-worktree without recovery from git history.
4. No branch/tag creation, commit, or push has been performed. Awaiting the dirty-file decision to be made explicit before Task A can proceed to actually cutting `legacy/rainfall` / `v0-rainfall-legacy`.

## Next Task Notes

Task B (rainfall strip manifest) must not start until: (a) the two commits above (or equivalent) land, (b) `legacy/rainfall` branch + `v0-rainfall-legacy` tag are cut from that commit with explicit user go-ahead, and (c) `feat/remote-sensing-first` is created for the strip work. None of that has happened yet — this report is inventory/classification only, per instructions to stop before any destructive action.
