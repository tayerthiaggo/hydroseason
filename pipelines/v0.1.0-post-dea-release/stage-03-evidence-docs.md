/caveman

# Stage 3 - Case Studies and Generated Documentation

Mode: implementation.

Model options:

1. Claude Sonnet 5, medium — coherent multi-file data/docs implementation. Set medium effort; `claude --model claude-sonnet-5`
2. GPT-5.5, medium — stronger shell/reproducibility handling. `codex --model gpt-5.5 -e medium "<prompt>"`

## Task

Execute Tasks 10-12 of
`docs/superpowers/plans/2026-07-31-v0.1.0-post-dea-release-readiness.md`.

## Read before acting

1. design spec
2. post-DEA release plan
3. integrated DEA audit
4. Stage 2 output below
5. committed case-study manifest and 20 extent inputs

## Scope

- Main study uses committed 30 m `extent_pct` and public route-aware workflow.
- Aseasonal catchments produce no hydrological years.
- Keep exactly two public studies.
- Separate resolution fidelity, pruning speed, and composite validation.
- Generate documentation tables from checked CSVs.
- Treat existing untracked builder/manual study page as source material only.
- Never fabricate unavailable network benchmark data.

## Method

- Execute task TDD/check/commit sequences.
- If controlled network benchmark cannot run, finish offline work, preserve schema,
  and stop with an explicit external evidence gate.
- Run generated-data checks, focused tests, and strict MkDocs.

## Required output

Write `pipelines/v0.1.0-post-dea-release/outputs/stage-03-evidence-docs.md`:

```markdown
# Evidence and docs output

## Task
Build two studies and generated DEA-aware user documentation.

## What this stage did
Scripts, results, docs, tests, commits.

## Verification
Offline checks, docs build, and controlled benchmark/composite evidence status.

## Handoff to next stage
Exact commands/artifacts CI must gate.

## Open questions / risks
Missing external runs, scientific vetoes, or documentation limitations.
```

## Output from Stage 2 - paste it here before running this prompt

<PASTE stage-02-integrated-baseline.md HERE>
