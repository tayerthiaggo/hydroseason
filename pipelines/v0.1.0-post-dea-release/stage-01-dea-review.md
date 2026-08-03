/caveman

# Stage 1 - Independent DEA Scientific and Cache Review

Mode: review. Read-only; do not edit or commit.

Model options:

1. Claude Opus 4.8, high — deeper scientific-contract review. Set high effort; `claude --model claude-opus-4-8`
2. GPT-5.5, high — stronger shell/cache/infra verification. `codex --model gpt-5.5 -e high "<prompt>"`

## Task

Independently review the reconciled implementation against Tasks 3-4 of
`docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`.

## Read before acting

1. `docs/superpowers/specs/2026-07-31-post-dea-release-readiness-design.md`
2. `docs/superpowers/plans/2026-07-31-dea-merge-reconciliation.md`
3. `docs/superpowers/plans/2026-07-31-dea-zones-plan-merge-handoff.md`
4. reconciled `_io_dea_stats.py`, `_spatial_plan.py`, `_io_geo.py`, `_io_wofs_acquire.py`, `_io_wofs_zarr.py`, public exports, and focused tests

## Review priorities

- blocking-search timeout returns control at deadline;
- lazy Dask/COG reads retain unsigned/cloud Rasterio configuration;
- native wet pixels survive coarse max pooling and fine clipping;
- full AOI remains denominator;
- request/cache identity separates all acquisition modes;
- persisted footprints detect geometry/count/digest tampering;
- `legacy` defaults remain compatible;
- dual composite uses one source graph and produces auditable sidecars;
- core-only imports work;
- HydroSeason contains no HydroFragments import.

## Method

- Inspect source and tests.
- Run narrow offline probes.
- For each finding, include severity P0-P3, location, repro/evidence,
  consequence, and exact required fix.
- Separate confirmed bugs, test gaps, docs gaps, and questions.

## Required output

Write `pipelines/v0.1.0-post-dea-release/outputs/stage-01-dea-review.md`:

```markdown
# DEA review output

## Task
Independent post-reconciliation scientific/API/cache review.

## What this stage did
Files inspected and commands run.

## Findings
Ordered P0-P3. Each finding contains location, evidence, consequence, and required fix.

## Handoff to next stage
Accepted blockers to fix and verification probes to rerun.

## Open questions / risks
Unproven behavior and external/network-only evidence.
```

## Output from Stage 0 - paste it here before running this prompt

<PASTE stage-00-recovery.md HERE>
