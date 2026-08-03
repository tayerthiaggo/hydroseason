/caveman

Mode: release engineering implementation. Recommended model: GPT-5.5 high (`codex --model gpt-5.5 -e high`).

Use superpowers:executing-plans. Execute only Task 14, "Add TestPyPI, PyPI, GitHub Release, and Zenodo Runbook", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`; treat it as the entire plan. Do not start Task 15 or use subagents.

## Output from Stage 15 — paste it here
[PASTE TASK 13 REPORT]

Read Goal, all Global Constraints and complete Task 14. Build once/promote same artifact; verify tag/version/date; least-privilege OIDC; full-SHA action pins; exact external trusted-publisher/Zenodo gates. Do not create external publishers/releases/tags/uploads. Validate workflows/metadata/tests and commit only Task 14 scope.

Write the same final report to `pipelines/v0.1.0-release/outputs/stage-16.md` and return it: status, commit, workflows/environments/artifact flow, pins, verification, external checklist, risks/deviations and Task 15 prerequisite. Do not commit the report.
