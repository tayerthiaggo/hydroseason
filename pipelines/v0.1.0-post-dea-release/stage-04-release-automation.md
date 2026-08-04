/caveman

# Stage 4 - Release Gates and Publishing Automation

Mode: implementation.

Model options:

1. GPT-5.5, high — strongest CI/shell/artifact choice. `codex --model gpt-5.5 -e high "<prompt>"`
2. Claude Sonnet 5, high — strong workflow/runbook implementation. Set high effort; `claude --model claude-sonnet-5`

## Task

Execute Tasks 13-14 of
`docs/superpowers/plans/2026-07-31-v0.1.0-post-dea-release-readiness.md`.

## Read before acting

1. post-DEA release plan
2. integrated DEA audit
3. Stage 3 output below
4. current workflows, release checker, dependencies, and generated checks

## Scope

- Eliminate known first-party warnings.
- Gate lint, lock, supported Python/core/all-extras, coverage, docs, and artifacts.
- Smoke exact wheel and rebuilt-from-sdist wheel.
- Derive artifact/version names from validated metadata.
- Pin actions by reviewed SHA with tag comments.
- Write TestPyPI/PyPI/GitHub/Zenodo runbook.
- Do not dispatch, publish, push, tag, or approve.

## Method

1. Add focused warning regressions and fixes.
2. Implement CI jobs and artifact smokes.
3. Implement TestPyPI/PyPI workflows without external execution.
4. Validate metadata, YAML/actionlint in CI, and all local release gates.
5. Commit task scopes separately.

## Required output

Write `pipelines/v0.1.0-post-dea-release/outputs/stage-04-release-automation.md`:

```markdown
# Release automation output

## Task
Implement release-blocking CI and human-gated publication automation.

## What this stage did
Warning fixes, jobs, workflows, runbook, commits.

## Verification
Local gates and syntax validation with exact results.

## Handoff to next stage
External setup and final audit inputs.

## Open questions / risks
Unavailable CI-only validation or maintainer configuration.
```

## Output from Stage 3 - paste it here before running this prompt

<PASTE stage-03-evidence-docs.md HERE>
