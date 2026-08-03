/caveman

# Stage 2 - DEA Fixes and Integrated Baseline

Mode: implementation.

Model options:

1. GPT-5.5, high — strongest test-driven integration/artifact choice. `codex --model gpt-5.5 -e high "<prompt>"`
2. Claude Sonnet 5, high — strong multi-file contract-preserving implementation. Set high effort; `claude --model claude-sonnet-5`

## Task

Execute Tasks 3-5 of
`docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`, consuming the
independent review pasted below.

## Read before acting

1. design spec
2. reconciliation plan
3. actual Stage 1 review below
4. current diff/status and Stage 0 output

## Scope

- Fix all accepted P0/P1 and release-blocking P2 findings.
- Reject incorrect review findings only with code/test evidence.
- Preserve public signatures/defaults unless plan explicitly changes them.
- Planning footprint remains recommended; polygon pruning remains compatibility-only.
- Establish exact `0.1.0` wheel and HydroFragments integration evidence.
- No push, publish, tag, release, or unrelated cleanup.

## Method

1. Write failing test for every behavior change.
2. Implement minimal fix.
3. Run focused DEA/cache suites.
4. Fix all Ruff failures.
5. Run metadata, lock, full offline tests, case-data check, strict docs.
6. Build/Twine/wheel-content check.
7. Install exact wheel into isolated HydroFragments environment and run focused integration.
8. Write integrated audit.

## Required output

Create `docs/superpowers/audits/2026-07-31-dea-merge-audit.md` and write
`pipelines/v0.1.0-post-dea-release/outputs/stage-02-integrated-baseline.md`:

```markdown
# Integrated baseline output

## Task
Finish DEA reconciliation and establish a green `0.1.0` baseline.

## What this stage did
Accepted/rejected findings, files changed, commits, audit path.

## Verification
Every command, exit status, test count, warning ledger, artifact names, and HydroFragments wheel result.

## Handoff to next stage
Confirmed baseline and constraints for case studies/docs.

## Open questions / risks
Network/performance evidence and any unresolved non-blocker.
```

## Output from Stage 1 - paste it here before running this prompt

<PASTE stage-01-dea-review.md HERE>
