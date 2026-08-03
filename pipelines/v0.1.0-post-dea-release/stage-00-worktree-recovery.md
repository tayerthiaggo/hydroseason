/caveman

# Stage 0 - Worktree Recovery and Version Alignment

Mode: implementation.

Model options:

1. GPT-5.5, high — strongest shell/Git recovery choice. `codex --model gpt-5.5 -e high "<prompt>"`
2. Claude Sonnet 5, high — strong semantic merge review. Set high effort in session; `claude --model claude-sonnet-5`

## Task

Execute only Tasks 1-2 of
`docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`.

Recover the live HydroSeason tree so it contains merge `36f3919` plus all
post-Task-9 review fixes. Restore authoritative release version `0.1.0` and
align HydroFragments' active requirement with `hydroseason==0.1.0`.

## Read before acting

1. `docs/superpowers/specs/2026-07-31-post-dea-release-readiness-design.md`
2. `docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`
3. `docs/superpowers/plans/2026-07-31-dea-zones-plan-merge-handoff.md`
4. `git status --short`, staged diff, unstaged diff, and recent log

## Scope

- Run Task 1 preconditions exactly; stop if HEAD/index assumptions differ.
- Restore only named reverse-merge paths.
- Preserve unrelated staged, unstaged, and untracked work.
- Reapply internal semi-Markov package-surface assertions without losing DEA exports.
- Modify HydroFragments only in Task 2 named paths and commit separately.
- No broad reset/checkout/restore. No push, publish, tag, or release.

## Method

1. Inventory and verify preconditions.
2. Restore named DEA files/tests from HEAD.
3. Reconcile three conflict surfaces semantically.
4. Run focused tests.
5. Set all HydroSeason version surfaces to `0.1.0`.
6. Update HydroFragments dependency/version expectations.
7. Run both repositories' focused tests.
8. Commit only reviewed files, separately per repository.

## Required output

Write `pipelines/v0.1.0-post-dea-release/outputs/stage-00-recovery.md`:

```markdown
# Worktree recovery output

## Task
Recover merge `36f3919`, preserve post-Task-9 changes, and align both repositories on HydroSeason `0.1.0`.

## What this stage did
- files restored/reconciled;
- version/dependency changes;
- commits created;
- commands and exit results;
- preserved dirty-tree inventory.

## Handoff to next stage
Review the actual reconciled DEA/statistics/planning/acquisition/cache code. Do not trust the merge handoff without verification.

## Open questions / risks
- unresolved failures;
- inaccessible sibling-repository work;
- deviations from the plan.
```

Do not continue into Task 3.
