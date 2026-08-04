/caveman

Mode: case-study implementation. Recommended model: GPT-5.5 medium (`codex --model gpt-5.5 -e medium`).

Use superpowers:executing-plans. Execute only Task 10, "Build Case Study 1 - Main HydroSeason Workflow", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`; treat it as the entire plan. Do not start Task 11 or use subagents.

## Output from Stage 10 — paste it here
[PASTE TASK 9 REPORT]

Read Goal, all Global Constraints and complete Task 10. Use TDD. Consume committed whole-catchment `extent_pct`; call `analyze_catchment` once and reuse its result. Remove heuristic selection, forced state/fallbacks and swallowed failures. Never synthesize HY output for aseasonal routes. Regenerate checked results/docs, run drift checks and commit only Task 10 scope.

Write the same final report to `pipelines/v0.1.0-release/outputs/stage-11.md` and return it: status, commit, catchment route/output summary, reproducibility/drift results, risks/deviations and Task 11 prerequisite. Do not commit the report.
