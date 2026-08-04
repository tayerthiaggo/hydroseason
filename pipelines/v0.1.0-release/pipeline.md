# HydroSeason v0.1.0 Manual Execution Pipeline

> **Superseded after Task 9 by**
> `pipelines/v0.1.0-post-dea-release/pipeline.md`. Do not continue this
> pipeline against merge `36f3919` or the current live index/worktree state.

> Source: `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`.
> First put the plan and intended existing changes on a non-main branch/worktree. Then copy one block at a time into a fresh session using the stated model. Do not paste unrelated history. Replace each prior-output placeholder with the preceding stage's short report.
> Every implementation run treats its named task as the complete plan for that run. It must not continue into the next task.

## Preflight

### Stage 0 - Safe execution workspace

Model: GPT-5.5, medium. CLI: `codex --model gpt-5.5 -e medium`

```text
/caveman

Mode: read-only release-workspace preflight.
Use superpowers:using-git-worktrees to inspect and propose the safe workspace for executing `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Do not implement plan tasks and do not use subagents.

Inspect branch, worktrees, `git status --short`, ignored files and whether the plan plus its four audited source documents are tracked and available from the intended base commit. This repository already contains user changes: do not commit, stash, discard, move or overwrite any of them without explicit approval. Never start implementation on main/master.

Write the same report to `pipelines/v0.1.0-release/outputs/stage-00.md` and return it: current branch/worktree state; changes that must be preserved; whether a new worktree can see every required file; recommended branch/worktree setup; exact safe commands requiring approval; blockers. Stop before mutating git state.
```

## Foundation

### Task 1 - Release truth and metadata gate

Model: GPT-5.5, medium. CLI: `codex --model gpt-5.5 -e medium`

```text
/caveman

Mode: implementation.
Use superpowers:executing-plans. Execute only Task 1, "Correct Release Truth and Add Metadata Gate", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 1 as the entire plan for this run; do not begin Task 2. Do not use subagents.

## Output from Stage 0 — paste it here before running
[PASTE APPROVED PREFLIGHT SETUP/RESULT]

Before acting: verify this is a non-main branch/worktree; read the plan's Goal, Global Constraints, Audit Baseline, and complete Task 1; inspect `git status --short` and relevant existing diffs. Preserve all unrelated user changes. If prior work conflicts with Task 1, stop and report the exact conflict.

Follow every Task 1 checkbox in order. Use test-driven development for the metadata checker. Run every specified verification plus focused tests. Commit only Task 1 files using the plan's commit message after verification. Do not invent a DOI or release date and do not publish anything.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-01.md` without committing it, then return: status; commit hash; files changed; commands with pass/fail counts; decisions; risks/deviations; exact prerequisite for Task 2.
```

### Task 2 - Static quality and lockfile

Model: GPT-5.5, medium. CLI: `codex --model gpt-5.5 -e medium`

```text
/caveman

Mode: implementation.
Use superpowers:executing-plans. Execute only Task 2, "Make Static Quality and Lockfile Reproducibility Green", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 2 as the entire plan for this run; do not begin Task 3. Do not use subagents.

## Output from Task 1 — paste it here before running
[PASTE TASK 1 REPORT]

Before acting: verify non-main branch/worktree; confirm Task 1 commit exists; read Goal, Global Constraints, and complete Task 2; inspect dirty state and preserve unrelated changes. Follow the task literally. Fix real Ruff defects rather than suppressing them; update the lock only from final declared dependencies. Run all Task 2 verification commands and regression tests. Commit only Task 2 scope after green verification.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-02.md` without committing it, then return: status; commit hash; files changed; Ruff error count before/after; lock check; tests run/results; risks/deviations; Task 3 prerequisite.
```

## Scientific core

### Task 3 - Monthly phase schema

Model: GPT-5.5, high. CLI: `codex --model gpt-5.5 -e high`

```text
/caveman

Mode: scientific implementation.
Use superpowers:executing-plans. Execute only Task 3, "Add Stable Monthly Phase Schema and Disabled Path", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 3 as the entire plan; do not begin Task 4. Do not use subagents.

## Output from Task 2 — paste it here before running
[PASTE TASK 2 REPORT]

Verify non-main branch/worktree and prerequisites. Read the plan's Goal, all Global Constraints, and complete Task 3. Inspect relevant current code/tests and preserve unrelated work. Follow strict red-green-refactor. Keep phase helpers internal, enforce the robust-extrema pairing, retain the exact stable schema, and do not change annual hydrological-year outputs. Run every specified test and commit only Task 3 scope when green.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-03.md` without committing it, then return: status; commit hash; API/schema changes; tests and results; explicit annual-invariance evidence; risks/deviations; Task 4 prerequisite.
```

### Task 4 - Robust-anchored rule-based phases

Model: GPT-5.5, high. CLI: `codex --model gpt-5.5 -e high`

```text
/caveman

Mode: scientific implementation.
Use superpowers:executing-plans. Execute only Task 4, "Implement Robust-Anchored Rule-Based Phases", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 4 as the entire plan; do not begin Task 5. Do not use subagents.

## Output from Task 3 — paste it here before running
[PASTE TASK 3 REPORT]

Verify branch/worktree and Task 3 commit. Read Goal, all Global Constraints, and complete Task 4. Use TDD and the exact phase definitions/columns in the plan. Robust extrema remain authoritative; phase labels are descriptive and must never alter annual assembly. Do not implement constrained HSMM behavior. Run focused plus invariance tests and commit only the task scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-04.md` without committing it, then return: status; commit hash; algorithm summary; tests/results; before/after annual-frame equality evidence; risks/deviations; Task 5 prerequisite.
```

### Task 5 - Single route authority

Model: GPT-5.5, high. CLI: `codex --model gpt-5.5 -e high`

```text
/caveman

Mode: scientific integration.
Use superpowers:executing-plans. Execute only Task 5, "Make analyze_catchment the Single Route Authority", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 5 as the entire plan; do not begin Task 6. Do not use subagents.

## Output from Task 4 — paste it here before running
[PASTE TASK 4 REPORT]

Verify branch/worktree and Tasks 1-4. Read Goal, all Global Constraints, and complete Task 5. Use TDD. Seasonal routing may own robust dynamic state; marginal routing remains explicitly imposed; aseasonal routing must expose no years, spans, peaks/troughs, or phase claims. Rainfall must not determine boundaries. Preserve compatibility unless the plan explicitly changes it. Run all specified tests and the relevant full routing suite; commit only Task 5 scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-05.md` without committing it, then return: status; commit hash; exact route-to-product mapping; tests/results; compatibility notes; risks/deviations; evidence ready for Scientific Review A.
```

### Review A - Scientific routing gate

Model: GPT-5.6 Sol, high. CLI: `codex --model gpt-5.6-sol -e high`

```text
/caveman

Mode: independent scientific review; read-only unless the user later authorizes fixes.
Review Tasks 3-5 against `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Do not implement new features and do not use subagents.

## Output from Task 5 — paste it here before running
[PASTE TASK 5 REPORT]

Read the plan Goal, Global Constraints, Tasks 3-5, commits/diffs for Tasks 3-5, and affected tests. Verify: robust extrema remain the sole dynamic-boundary authority; toggling phases cannot change any annual value; aseasonal output contains no HY/phase claims; marginal imposed timing is labeled honestly; rainfall cannot affect routing/boundaries; public/internal API boundaries are intentional. Run focused tests only where evidence is missing.

Write the review to `pipelines/v0.1.0-release/outputs/stage-06.md` without committing it, then return: PASS or BLOCK; findings ordered Critical/Important/Minor with file:line evidence; missing tests; exact remediation; explicit verdict for proceeding to Task 6. Do not modify or commit product files.
```

## Reporting

### Task 6 - Route-aware export frames

Model: GPT-5.5, medium. CLI: `codex --model gpt-5.5 -e medium`

```text
/caveman

Mode: implementation.
Use superpowers:executing-plans. Execute only Task 6, "Build Complete Route-Aware Export Frames", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 6 as the entire plan; do not begin Task 7. Do not use subagents.

## Output from Review A — paste it here before running
[PASTE REVIEW A VERDICT; MUST BE PASS]

Verify Review A passed and Tasks 1-5 exist. Read Goal, Global Constraints, and complete Task 6. Use TDD. Preserve every source month, stable empty schemas, explicit closed-interval membership, nullable identifiers, route authority, and optional rainfall month alignment. Do not infer membership by row position. Run all task verifications and commit only Task 6 scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-07.md` without committing it, then return: status; commit hash; schemas/interfaces; tests/results; edge cases; risks/deviations; Task 7 prerequisite.
```

### Task 7 - Verdict copy and Plotly dictionaries

Model: GPT-5.5, medium. CLI: `codex --model gpt-5.5 -e medium`

```text
/caveman

Mode: implementation.
Use superpowers:executing-plans. Execute only Task 7, "Build Verdict Copy and Light Plotly Figure Dictionaries", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 7 as the entire plan; do not begin Task 8. Do not use subagents.

## Output from Task 6 — paste it here before running
[PASTE TASK 6 REPORT]

Verify prerequisites. Read Goal, Global Constraints, and complete Task 7. Use TDD. Keep copy route-aware, KPI count bounded, figures plain-dict/JSON-safe/light-theme, and rainfall optional on a secondary axis without analytical influence. Do not add CDN or HTML assembly here. Run specified tests and commit only Task 7 scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-08.md` without committing it, then return: status; commit hash; interfaces; tests/results; representative route behavior; risks/deviations; Task 8 prerequisite.
```

### Task 8 - Self-contained manager report

Model: GPT-5.5, high. CLI: `codex --model gpt-5.5 -e high`

```text
/caveman

Mode: integration and packaging implementation.
Use superpowers:executing-plans. Execute only Task 8, "Ship Self-Contained Manager Report Bundle and Compatibility API", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 8 as the entire plan; do not begin Task 9. Do not use subagents.

## Output from Task 7 — paste it here before running
[PASTE TASK 7 REPORT]

Verify prerequisites. Read Goal, all Global Constraints, and complete Task 8. Use TDD. Vendor the exact pinned Plotly basic bundle and license, escape user-controlled HTML, serialize strict JSON, write CSVs atomically and HTML last, preserve the compatibility API, and prove wheel/sdist asset inclusion. No CDN/network dependency. Run unit, offline report, build, Twine, wheel-content and isolated-install checks. Commit only Task 8 scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-09.md` without committing it, then return: status; commit hash; public API; artifact contents; tests/build/smoke results; security/offline evidence; risks/deviations; Task 9 prerequisite.
```

## Reproducible case studies

### Task 9 - Case-study inputs and provenance

Model: GPT-5.5, medium. CLI: `codex --model gpt-5.5 -e medium`

```text
/caveman

Mode: data/provenance implementation.
Use superpowers:executing-plans. Execute only Task 9, "Commit Reproducible Case-Study Inputs and Provenance", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 9 as the entire plan; do not begin Task 10. Do not use subagents.

## Output from Task 8 — paste it here before running
[PASTE TASK 8 REPORT]

Verify prerequisites. Read Goal, all Global Constraints, and complete Task 9. Preserve existing source outputs. Implement deterministic normalization/manifests with hashes, date/resolution completeness checks, DEA WOfS attribution and license separation. Case data belong in source/GitHub/Zenodo archives but not wheel/sdist. Network reacquisition or substantial external data access requires explicit approval. Run all checks and commit only Task 9 scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-10.md` without committing it, then return: status; commit hash; input matrix completeness; manifest/hash evidence; licensing/provenance; package exclusion evidence; tests/results; risks/deviations; Task 10 prerequisite.
```

### Task 10 - Main HydroSeason workflow study

Model: GPT-5.5, medium. CLI: `codex --model gpt-5.5 -e medium`

```text
/caveman

Mode: case-study implementation.
Use superpowers:executing-plans. Execute only Task 10, "Build Case Study 1 - Main HydroSeason Workflow", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 10 as the entire plan; do not begin Task 11. Do not use subagents.

## Output from Task 9 — paste it here before running
[PASTE TASK 9 REPORT]

Verify Task 9 completeness. Read Goal, all Global Constraints, and complete Task 10. Use TDD. Consume only committed normalized whole-catchment `extent_pct`; call `analyze_catchment` once per catchment and pass that exact result to reporting. Remove heuristic series choice, forced state, fallback troughs and swallowed failures. Aseasonal catchments must never receive synthetic HY products. Regenerate checked results/docs and run drift checks. Commit only Task 10 scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-11.md` without committing it, then return: status; commit hash; per-catchment regime/route/output summary; reproducibility commands/results; drift status; risks/deviations; Task 11 prerequisite.
```

### Task 11 - Resolution speed and fidelity study

Model: GPT-5.5, high. CLI: `codex --model gpt-5.5 -e high`

```text
/caveman

Mode: scientific benchmark implementation.
Use superpowers:executing-plans. Execute only Task 11, "Build Case Study 2 - Resolution Speed and Fidelity", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 11 as the entire plan; do not begin Task 12. Do not use subagents.

## Output from Task 10 — paste it here before running
[PASTE TASK 10 REPORT]

Verify prerequisites. Read Goal, all Global Constraints, and complete Task 11. Use TDD for metrics/decision logic. Fidelity must cover all five catchments at 30/60/90/300 m. Performance evidence must use only the controlled cold protocol, record failures and environment, and never mix cache hits with cold runs. Do not claim coarse resolution is acceptable unless every stated fidelity and performance threshold passes. Network/performance execution requires explicit approval and stays outside ordinary CI. Commit only Task 11 scope after checks.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-12.md` without committing it, then return: status; commit hash; fidelity matrix; benchmark protocol/run count; threshold decisions; raw-result locations; tests/results; limitations/risks; evidence ready for Review B.
```

### Review B - Case-study evidence gate

Model: GPT-5.6 Sol, high. CLI: `codex --model gpt-5.6-sol -e high`

```text
/caveman

Mode: independent scientific/reproducibility review; read-only unless fixes are later authorized.
Review Tasks 9-11 against `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Do not use subagents.

## Output from Task 11 — paste it here before running
[PASTE TASK 11 REPORT]

Read Goal, Global Constraints, Tasks 9-11, their commits/diffs, manifests and generated results. Verify fresh-clone reproducibility, input completeness/hashes/provenance/license, route-consistent main-study outputs, controlled cold benchmarking, metric validity, declared thresholds and claim wording. Check that cache-hit timing never supports speed claims and that case data are excluded from distributions as specified.

Write the review to `pipelines/v0.1.0-release/outputs/stage-13.md` without committing it, then return: PASS or BLOCK; Critical/Important/Minor findings with file:line or data-row evidence; unsupported claims; missing evidence; exact remediation; explicit verdict for proceeding to Task 12. Do not modify or commit product files.
```

## Documentation and release machinery

### Task 12 - User documentation

Model: GPT-5.5, medium. CLI: `codex --model gpt-5.5 -e medium`

```text
/caveman

Mode: documentation implementation.
Use superpowers:executing-plans. Execute only Task 12, "Restructure User Documentation Around the Two Studies", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 12 as the entire plan; do not begin Task 13. Do not use subagents.

## Output from Review B — paste it here before running
[PASTE REVIEW B VERDICT; MUST BE PASS]

Verify prerequisites. Read Goal, Global Constraints, and complete Task 12. Organize docs around exactly two case studies. Keep quickstart/API/report-column definitions accurate and generated result regions drift-checked. Explain route semantics plainly, distinguish phase from condition, state benchmark limitations, and remove pre-release or contradictory claims. Run strict docs build, link/drift checks and relevant tests. Commit only Task 12 scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-14.md` without committing it, then return: status; commit hash; navigation/content changes; generated regions; docs/tests results; remaining user-confusion risks; Task 13 prerequisite.
```

### Task 13 - Release-blocking CI and artifact smoke

Model: GPT-5.5, high. CLI: `codex --model gpt-5.5 -e high`

```text
/caveman

Mode: CI/release engineering implementation.
Use superpowers:executing-plans. Execute only Task 13, "Add Release-Blocking CI and Artifact Smoke Tests", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 13 as the entire plan; do not begin Task 14. Do not use subagents.

## Output from Task 12 — paste it here before running
[PASTE TASK 12 REPORT]

Verify prerequisites. Read Goal, all Global Constraints, and complete Task 13. Use TDD for artifact smoke behavior where applicable. Gate lint, lock, supported Python/core/all-extras, coverage, strict docs, metadata, build, Twine, wheel contents and fresh-install smoke. Use concrete artifact names and exclude network/performance tests from normal CI. Pin third-party actions as required by the plan. Run every feasible local equivalent and validate workflow syntax. Commit only Task 13 scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-15.md` without committing it, then return: status; commit hash; job/gate matrix; local verification results; CI-only checks; risks/deviations; Task 14 prerequisite.
```

### Task 14 - TestPyPI, PyPI and Zenodo runbook

Model: GPT-5.5, high. CLI: `codex --model gpt-5.5 -e high`

```text
/caveman

Mode: release engineering implementation.
Use superpowers:executing-plans. Execute only Task 14, "Add TestPyPI, PyPI, GitHub Release, and Zenodo Runbook", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 14 as the entire plan; do not begin Task 15. Do not use subagents.

## Output from Task 13 — paste it here before running
[PASTE TASK 13 REPORT]

Verify prerequisites. Read Goal, all Global Constraints, and complete Task 14. Build once and promote the same artifact; verify tag/version/date; use least-privilege OIDC environments; pin every third-party action to a reviewed full SHA; document exact external trusted-publisher and Zenodo gates. Do not create publishers, releases, tags, uploads or other external state in this task. Validate YAML/metadata/tests locally and commit only Task 14 scope.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-16.md` without committing it, then return: status; commit hash; workflows/environments/artifact flow; SHA pins; validation results; external setup checklist; risks/deviations; Task 15 prerequisite.
```

### Task 15 - Release candidate and publication

Model: GPT-5.5, high. CLI: `codex --model gpt-5.5 -e high`

```text
/caveman

Mode: release-candidate preparation.
Use superpowers:executing-plans. Execute only Task 15, "Prepare and Verify the 0.1.0 Release Candidate", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`. Treat Task 15 as the entire plan. Do not use subagents.

## Output from Task 14 — paste it here before running
[PASTE TASK 14 REPORT]

Verify prerequisites and external-account gates. Read Goal, all Global Constraints, complete Task 15 and the Final Success Checklist. Prepare metadata/release notes and run every release-candidate command from a clean state. Stop before TestPyPI/PyPI/GitHub Release/Zenodo publication unless the user explicitly authorizes those external mutations in this session. Never invent a DOI, move a published tag, overwrite immutable artifacts or bypass a failing gate. Commit only pre-publication Task 15 scope when verified.

Write the required report to `pipelines/v0.1.0-release/outputs/stage-17.md` without committing it, then return: READY, BLOCKED, or PUBLISHED; commit hash; complete gate table with commands/results; artifact hashes; external actions performed or withheld; exact remaining human actions; risks/deviations; evidence ready for Final Review.
```

### Final Review - Whole release branch

Model: GPT-5.6 Sol, high. CLI: `codex --model gpt-5.6-sol -e high`

```text
/caveman

Mode: final whole-branch release audit; read-only unless a separate fix request is authorized.
Use superpowers:requesting-code-review and superpowers:verification-before-completion. Do not use subagents.

## Output from Task 15 — paste it here before running
[PASTE TASK 15 REPORT]

Review the full branch diff from its merge base against `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`, all four audited source plans/specs, and the Final Success Checklist. Check scientific invariants, route truth, report security/offline behavior, case-study reproducibility and claims, package contents/metadata, CI artifact provenance, release immutability and Zenodo/PyPI readiness. Independently run the highest-value release gates needed to validate evidence.

Write the review to `pipelines/v0.1.0-release/outputs/stage-18.md` without committing it, then return: RELEASE PASS or RELEASE BLOCK; findings ordered Critical/Important/Minor with file:line evidence; gate table; unresolved external prerequisites; exact single fix-wave instructions if blocked. Do not modify product files, commit, tag or publish.
```
