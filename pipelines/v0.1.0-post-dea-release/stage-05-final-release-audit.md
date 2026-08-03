/caveman

# Stage 5 - Final Release Audit and Human Packet

Mode: release-audit. Read/verify; only edit audit output. Do not publish, tag,
push, approve, or set a release date without maintainer input.

Model options:

1. Claude Opus 4.8, xhigh — strongest independent final judgment. Set xhigh effort; `claude --model claude-opus-4-8`
2. GPT-5.5, xhigh — stronger artifact/shell verification. `codex --model gpt-5.5 -e xhigh "<prompt>"`

## Task

Independently audit Task 15 of
`docs/superpowers/plans/2026-07-31-v0.1.0-post-dea-release-readiness.md` and
produce a maintainer execution packet.

## Read before acting

1. design spec and both plans
2. DEA merge audit
3. outputs from Stages 0-4, including Stage 4 below
4. current status/diff/log
5. workflows, metadata, generated results/docs, and built artifacts

## Scope

- Rerun every safe local release gate from exact source state.
- Verify `0.1.0` everywhere and no active `0.1.1` dependency.
- Verify generated-data cleanliness, first-party warning status, artifact
  contents, and exact-wheel HydroFragments integration.
- Missing approved release date remains human gate; do not invent it.
- Any release blocker yields FAIL.

## Required output

Write `pipelines/v0.1.0-post-dea-release/outputs/stage-05-final-release-audit.md`:

```markdown
# Final release audit output

## Task
Independent final `0.1.0` release audit.

## What this stage did
Source/commit/artifact scope and commands run.

## Gate matrix
Each gate: PASS, FAIL, or HUMAN; evidence and command/artifact.

## Verdict
PASS or FAIL. No conditional prose verdict.

## Human release packet
Exact ordered TestPyPI, merge/tag, GitHub Release, PyPI approval, public smoke,
Zenodo verification, and DOI follow-up actions.

## Open questions / risks
Only unresolved external/human state.
```

## Output from Stage 4 - paste it here before running this prompt

<PASTE stage-04-release-automation.md HERE>
