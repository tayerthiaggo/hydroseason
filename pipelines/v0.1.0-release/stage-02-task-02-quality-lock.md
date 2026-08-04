/caveman

Mode: implementation. Recommended model: GPT-5.5 medium (`codex --model gpt-5.5 -e medium`).

Use superpowers:executing-plans. Execute only Task 2, "Make Static Quality and Lockfile Reproducibility Green", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`; treat it as the entire plan. Do not start Task 3 or use subagents.

## Output from Stage 1 — paste it here
[PASTE TASK 1 REPORT]

Verify non-main workspace and Task 1 commit. Read Goal, Global Constraints and complete Task 2. Inspect dirty state and preserve unrelated work. Fix real Ruff defects rather than suppressing them; update the lock only from final dependencies. Run all specified verification and regression tests. Commit only Task 2 scope.

Write the same final report to `pipelines/v0.1.0-release/outputs/stage-02.md` and return it: status, commit, files, Ruff before/after, lock/test results, risks/deviations and Task 3 prerequisite. Do not commit the report.
