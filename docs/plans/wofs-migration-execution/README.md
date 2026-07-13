# WOfS Migration Execution Reports

This folder stores cross-conversation handoff reports for the WOfS hydro-year migration.

Each task writes one report here before returning. The next task reads all earlier reports before starting, so model changes and separate conversations still have durable context.

Report files:

- `task-a-legacy-snapshot.md`
- `task-b-strip-manifest.md`
- `task-c-detection-core.md`
- `task-d-loaders-aoi.md`
- `task-e-packaging.md`
- `task-f-science-acceptance.md`
- `task-g-docs.md`
- `task-h-final-review.md`
- `task-i-final-commit.md`

