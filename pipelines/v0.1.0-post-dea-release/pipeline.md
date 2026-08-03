# HydroSeason `0.1.0` Post-DEA Release Pipeline

> Source: `docs/superpowers/specs/2026-07-31-post-dea-release-readiness-design.md` and its two implementation plans.
> Copy and paste one block at a time into the selected executor. Never paste unrelated backlog/context.
> Replace every prior-stage placeholder with the actual preceding output before running that block.
> No stage may publish, push, tag, approve an environment, or invent a DOI.

## Reconciliation

### Stage 0 - Worktree Recovery and Version Alignment (implementation)

Option A: GPT-5.5, high — strongest shell/Git recovery choice. Run with `codex --model gpt-5.5 -e high "<prompt>"`.

Option B: Claude Sonnet 5, high — strong semantic merge review; set high effort in Claude Code session, then run `claude --model claude-sonnet-5`.

```text
/caveman

Mode: implementation.
Execute only Tasks 1-2 of `docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`.
Recommended model: GPT-5.5, high. Alternative: Claude Sonnet 5, high.

Objective:
Recover merged DEA files from HEAD without losing post-Task-9 user changes, restore HydroSeason release version 0.1.0, and align HydroFragments' active dependency requirement with 0.1.0.

Read before acting:
1. `docs/superpowers/specs/2026-07-31-post-dea-release-readiness-design.md`
2. `docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`
3. `docs/superpowers/plans/2026-07-31-dea-zones-plan-merge-handoff.md`

Scope:
- Follow path-scoped preconditions and recovery commands exactly.
- Preserve every unrelated staged, unstaged, and untracked change.
- Reconcile `hydroseason/__init__.py`, `tests/test_package_surface.py`, and `tests/test_spatial_plan.py` semantically.
- Change HydroFragments only in files named by Task 2 and commit it separately.
- Do not use broad reset/restore/checkout; do not push or publish.

Method:
- Run every precondition before mutation; stop on mismatch.
- Execute focused tests after reconciliation and metadata tests after version alignment.
- Inspect `git status --short` before every commit.

Required outputs:
- requested code/test/dependency changes and scoped commits;
- commands run with exit status;
- preserved user-change inventory;
- exact remaining dirty-tree inventory;
- write handoff to `pipelines/v0.1.0-post-dea-release/outputs/stage-00-recovery.md` using:
  # Worktree recovery output
  ## Task
  ## What this stage did
  ## Handoff to next stage
  ## Open questions / risks
```

### Stage 1 - Independent DEA Scientific and Cache Review (review)

Option A: Claude Opus 4.8, high — deeper scientific-contract review. Set high effort in Claude Code, then run `claude --model claude-opus-4-8`.

Option B: GPT-5.5, high — stronger shell/cache/infra verification. Run with `codex --model gpt-5.5 -e high "<prompt>"`.

```text
/caveman

Mode: review. Read-only: do not edit or commit.
Review the reconciled DEA/statistics/planning/acquisition/cache implementation against Tasks 3-4 of `docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`.
Recommended model: Claude Opus 4.8, high. Alternative: GPT-5.5, high.

Read before acting:
1. `docs/superpowers/specs/2026-07-31-post-dea-release-readiness-design.md`
2. `docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`
3. `docs/superpowers/plans/2026-07-31-dea-zones-plan-merge-handoff.md`
4. reconciled DEA/I/O source and focused tests

Review priorities:
- true blocking-search deadline and lazy COG environment;
- native-mask superset through coarse windows and fine clipping;
- full-AOI denominator under pruning;
- cache identity separation/tamper detection;
- legacy-default compatibility;
- one-graph dual-composite semantics;
- top-level API and core-only import isolation;
- no HydroFragments imports.

Method:
- Inspect code and run narrow offline probes/tests.
- Rank findings P0-P3 with file/line evidence, concrete repro, and required fix.
- Distinguish confirmed bugs from questions and documentation gaps.

Required output:
- write `pipelines/v0.1.0-post-dea-release/outputs/stage-01-dea-review.md` using:
  # DEA review output
  ## Task
  ## What this stage did
  ## Findings
  ## Handoff to next stage
  ## Open questions / risks

## Output from Stage 0 - paste it here before running this prompt
<PASTE stage-00-recovery.md HERE>
```

### Stage 2 - DEA Fixes and Integrated Baseline (implementation)

Option A: GPT-5.5, high — best fit for test-driven integration and artifact commands. Run with `codex --model gpt-5.5 -e high "<prompt>"`.

Option B: Claude Sonnet 5, high — strong multi-file implementation with careful contract preservation. Set high effort, then run `claude --model claude-sonnet-5`.

```text
/caveman

Mode: implementation.
Execute Tasks 3-5 of `docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`, consuming the independent review below.
Recommended model: GPT-5.5, high. Alternative: Claude Sonnet 5, high.

Read before acting:
1. `docs/superpowers/specs/2026-07-31-post-dea-release-readiness-design.md`
2. `docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`
3. actual Stage 1 review pasted below

Scope:
- Fix every accepted P0/P1 and release-blocking P2 finding.
- Reject incorrect findings explicitly with code/test evidence.
- Keep planning footprint recommended and legacy polygon path compatibility-only.
- Produce integrated audit and exact 0.1.0 wheel/HydroFragments test evidence.
- Preserve unrelated changes; no push/publish/tag.

Method:
- TDD for every behavioral fix.
- Run focused tests, full offline gates, Ruff, lock, docs, build, Twine, wheel contents, then exact-wheel HydroFragments integration.
- Record warning ledger without blanket suppression.

Required outputs:
- scoped fixes and commits;
- `docs/superpowers/audits/2026-07-31-dea-merge-audit.md`;
- write `pipelines/v0.1.0-post-dea-release/outputs/stage-02-integrated-baseline.md` using:
  # Integrated baseline output
  ## Task
  ## What this stage did
  ## Verification
  ## Handoff to next stage
  ## Open questions / risks

## Output from Stage 1 - paste it here before running this prompt
<PASTE stage-01-dea-review.md HERE>
```

## Evidence and Documentation

### Stage 3 - Case Studies and Generated Documentation (implementation)

Option A: Claude Sonnet 5, medium — coherent multi-file data/docs implementation at moderate cost. Set medium effort, then run `claude --model claude-sonnet-5`.

Option B: GPT-5.5, medium — stronger shell/reproducibility handling. Run with `codex --model gpt-5.5 -e medium "<prompt>"`.

```text
/caveman

Mode: implementation.
Execute Tasks 10-12 of `docs/superpowers/plans/2026-07-31-v0.1.0-post-dea-release-readiness.md`.
Recommended model: Claude Sonnet 5, medium. Alternative: GPT-5.5, medium.

Read before acting:
1. `docs/superpowers/specs/2026-07-31-post-dea-release-readiness-design.md`
2. `docs/superpowers/plans/2026-07-31-v0.1.0-post-dea-release-readiness.md`
3. `docs/superpowers/audits/2026-07-31-dea-merge-audit.md`
4. actual Stage 2 output pasted below

Scope:
- Rebuild main study from committed 30 m inputs and public route-aware APIs only.
- Keep exactly two studies.
- Separate scientific resolution fidelity, pruning speed, and composite validation.
- Generate docs tables from checked CSVs; replace stale hand-written study drafts.
- Network benchmarks are opt-in; never fabricate missing performance evidence.

Method:
- Follow each task's TDD/check/commit sequence.
- Stop with an explicit external-benchmark gate if network evidence is unavailable.
- Run all offline checks and strict MkDocs before handoff.

Required outputs:
- checked result CSVs, scripts, tests, docs, and scoped commits;
- commands/results and any external benchmark gap;
- write `pipelines/v0.1.0-post-dea-release/outputs/stage-03-evidence-docs.md` using:
  # Evidence and docs output
  ## Task
  ## What this stage did
  ## Verification
  ## Handoff to next stage
  ## Open questions / risks

## Output from Stage 2 - paste it here before running this prompt
<PASTE stage-02-integrated-baseline.md HERE>
```

## CI and Release Automation

### Stage 4 - Release Gates and Publishing Automation (implementation)

Option A: GPT-5.5, high — strongest CI/shell/artifact choice. Run with `codex --model gpt-5.5 -e high "<prompt>"`.

Option B: Claude Sonnet 5, high — strong workflow and runbook implementation. Set high effort, then run `claude --model claude-sonnet-5`.

```text
/caveman

Mode: implementation.
Execute Tasks 13-14 of `docs/superpowers/plans/2026-07-31-v0.1.0-post-dea-release-readiness.md`.
Recommended model: GPT-5.5, high. Alternative: Claude Sonnet 5, high.

Read before acting:
1. release-readiness plan
2. integrated DEA audit
3. actual Stage 3 output pasted below
4. current GitHub workflows and release metadata checker

Scope:
- Eliminate known first-party warnings.
- Add lint/lock/core/all-extras/docs/build artifact gates.
- Build once and publish exact verified artifacts.
- Derive workflow artifact names from validated metadata.
- Pin third-party actions to reviewed SHAs with tag comments.
- Write TestPyPI/PyPI/Zenodo runbook.
- Do not dispatch workflows, publish, tag, push, or approve environments.

Method:
- Test warning fixes first.
- Validate YAML and commands locally where possible.
- Run complete offline release gate.

Required outputs:
- CI/workflow/runbook changes and scoped commits;
- local verification results and external setup requirements;
- write `pipelines/v0.1.0-post-dea-release/outputs/stage-04-release-automation.md` using:
  # Release automation output
  ## Task
  ## What this stage did
  ## Verification
  ## Handoff to next stage
  ## Open questions / risks

## Output from Stage 3 - paste it here before running this prompt
<PASTE stage-03-evidence-docs.md HERE>
```

## Final Gate

### Stage 5 - Final Release Audit and Human Packet (release-audit)

Option A: Claude Opus 4.8, xhigh — strongest independent final judgment. Set xhigh effort, then run `claude --model claude-opus-4-8`.

Option B: GPT-5.5, xhigh — stronger artifact and shell verification. Run with `codex --model gpt-5.5 -e xhigh "<prompt>"`.

```text
/caveman

Mode: release-audit and human-packet preparation. Do not publish, tag, push, or approve anything.
Audit Task 15 of `docs/superpowers/plans/2026-07-31-v0.1.0-post-dea-release-readiness.md`.
Recommended model: Claude Opus 4.8, xhigh. Alternative: GPT-5.5, xhigh.

Read before acting:
1. both implementation plans
2. DEA merge audit
3. outputs from Stages 0-4, including actual Stage 4 output below
4. current diff, commit history, workflows, metadata, checked evidence, and built artifacts

Scope:
- Independently rerun every local release gate from exact source state.
- Verify version 0.1.0, no active 0.1.1 dependency, artifact contents, generated-data cleanliness, warning status, and HydroFragments exact-wheel integration.
- If maintainer has not supplied release date, do not edit date/changelog; list it as human gate.
- Produce PASS/FAIL verdict. Any release blocker means FAIL.

Required output:
- write `pipelines/v0.1.0-post-dea-release/outputs/stage-05-final-release-audit.md` using:
  # Final release audit output
  ## Task
  ## What this stage did
  ## Gate matrix
  ## Verdict
  ## Human release packet
  ## Open questions / risks
- Human packet must list exact TestPyPI, merge/tag, GitHub Release, PyPI approval, public smoke, Zenodo, and DOI-follow-up actions.

## Output from Stage 4 - paste it here before running this prompt
<PASTE stage-04-release-automation.md HERE>
```
