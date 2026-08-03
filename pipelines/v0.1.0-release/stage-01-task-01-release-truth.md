/caveman

Mode: implementation. Recommended model: GPT-5.5 medium (`codex --model gpt-5.5 -e medium`).

Use superpowers:executing-plans. Execute only Task 1, "Correct Release Truth and Add Metadata Gate", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`; treat it as the entire plan for this run. Do not start Task 2 or use subagents.

## Output from Stage 0 — paste it here
[PASTE APPROVED PREFLIGHT SETUP/RESULT]

Verify a non-main branch/worktree. Read the plan Goal, Global Constraints, Audit Baseline and complete Task 1. Inspect `git status --short` and relevant diffs; preserve unrelated changes. Follow every checkbox, use TDD for the checker, run every verification, and commit only Task 1 scope with its planned message. Never invent a DOI/date or publish.

Write the same final report to `pipelines/v0.1.0-release/outputs/stage-01.md` and return it: status, commit, files, command results, decisions, risks/deviations and Task 2 prerequisite. Do not commit the report.
