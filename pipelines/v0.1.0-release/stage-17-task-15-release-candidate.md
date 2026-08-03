/caveman

Mode: release-candidate preparation. Recommended model: GPT-5.5 high (`codex --model gpt-5.5 -e high`).

Use superpowers:executing-plans. Execute only Task 15, "Prepare and Verify the 0.1.0 Release Candidate", from `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`; treat it as the entire plan. Do not use subagents.

## Output from Stage 16 — paste it here
[PASTE TASK 14 REPORT]

Read Goal, all Global Constraints, Task 15 and Final Success Checklist. Verify prerequisites/external account gates. Prepare metadata/notes and run every RC command cleanly. Stop before TestPyPI/PyPI/GitHub/Zenodo mutation unless explicitly authorized in this session. Never invent DOI, move tags, replace immutable artifacts or bypass failures. Commit only verified pre-publication scope.

Write the same final report to `pipelines/v0.1.0-release/outputs/stage-17.md` and return it: READY/BLOCKED/PUBLISHED; commit, full gate table, artifact hashes, external actions performed/withheld, remaining human actions, risks/deviations and final-review evidence. Do not commit the report.
