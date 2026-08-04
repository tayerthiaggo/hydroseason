/caveman

Mode: CI/release engineering implementation. Recommended model: GPT-5.5 high (`codex --model gpt-5.5 -e high`).

Use superpowers:executing-plans. Execute only Task 13, "Add Release-Blocking CI and Artifact Smoke Tests", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`; treat it as the entire plan. Do not start Task 14 or use subagents.

## Output from Stage 14 — paste it here
[PASTE TASK 12 REPORT]

Read Goal, all Global Constraints and complete Task 13. Use TDD for artifact smoke where applicable. Gate lint, lock, Python/core/all-extras, coverage, strict docs, metadata, build, Twine, wheel contents and fresh install. Exclude network/performance tests. Use concrete artifact names and pinned actions. Run feasible local equivalents/YAML validation; commit only Task 13 scope.

Write the same final report to `pipelines/v0.1.0-release/outputs/stage-15.md` and return it: status, commit, CI matrix/gates, local and CI-only checks, risks/deviations and Task 14 prerequisite. Do not commit the report.
