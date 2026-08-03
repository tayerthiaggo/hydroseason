/caveman

Mode: final whole-branch release audit. Recommended model: GPT-5.6 Sol high (`codex --model gpt-5.6-sol -e high`). Read-only; no subagents.

Use superpowers:requesting-code-review and superpowers:verification-before-completion.

## Output from Stage 17 — paste it here
[PASTE TASK 15 REPORT]

Review the full branch diff from merge base against `docs/superpowers/plans/2026-07-31-v0.1.0-release-readiness.md`, all four audited source plans/specs and the Final Success Checklist. Check scientific invariants/routes, report security/offline behavior, reproducibility/claims, package metadata/contents, CI artifact provenance, release immutability and Zenodo/PyPI readiness. Independently run the highest-value gates needed to verify evidence.

Write the same final report to `pipelines/v0.1.0-release/outputs/stage-18.md` and return it: RELEASE PASS or RELEASE BLOCK; Critical/Important/Minor findings with file:line evidence; gate table; external prerequisites; exact single fix-wave instructions. Do not modify product files, commit, tag or publish.
