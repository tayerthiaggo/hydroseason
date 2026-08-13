# HydroSeason 0.1.1 Release Readiness and Hybrid User Notebook Design

**Status:** Approved for implementation

**Date:** 2026-08-13

**Release:** 0.1.1

## Purpose

Turn the current `development` branch into a reproducible, user-ready 0.1.1
candidate and replace the illustrative 0.1.1 notebook with a real user journey.
The candidate must be validated from a supported Python interpreter, built as
0.1.1, installed from TestPyPI, and exercised through public Python and CLI
interfaces before tagging.

## Canonical release contract

This document resolves conflicts and stale requirements in the earlier 0.1.1
design documents.

- The approved ten-year circular-uniformity power guard remains: a strong
  record with 5-9 usable annual timings stays `marginal` when a non-significant
  Kuiper result has too little power. Fewer than five timings remains
  `insufficient_record`.
- Automatic batch scheduling uses 80% of currently available RAM, capped at
  two outer workers and available logical CPUs. This deliberately supersedes
  the earlier 60% proposal; 60% made ordinary catchments oversized and removed
  useful concurrency.
- One oversized-AOI warning per batch is the supported warning contract. It is
  emitted before work and identifies all affected source positions; it does
  not expand each immutable per-AOI result type.
- `doctor`, JSON CLI output, and progress reporting are accepted 0.1.1
  additions. They are useful user-facing extensions of the thin CLI and are
  not removed as scope creep.
- Interactive AOI boundary maps in notebook previews and HTML reports remain
  in 0.1.1. The separate static five-catchment map-input bundle and rendering
  pipeline from the unapproved CLI/case-study-map follow-up are deferred. No
  0.1.1 documentation may claim those static assets exist.

## Product fixes required before release

### Historical-mask provenance

Both `HistoricalMaskCoverageWarning` and `HistoricalMaskRefreshedWarning` are
public. `probe_wo_statistics_coverage` is public. A refresh notice must be
emitted through Python warnings and copied into `HydroSeasonRunResult.warnings`.
The `refresh_historical_mask=False` pin must be accepted by
`run_hydroseason`, `run_hydroseason_many`, `resolve_water_input`,
`load_wofs_monthly_extent`, and the CLI.

### Batch and map behavior

All docs and tests must agree on the 80% memory budget. AOI maps must expose
the display name and per-feature identifier in accessible text and bound
popups. An explicit `show_map=True` outside a display-capable Jupyter kernel
must warn and continue without attempting inline display.

### CLI behavior

Successful text and JSON summaries include the requested output directory as
well as the generated artifact paths. Expected rasterio
`NotGeoreferencedWarning` suppression is regression-tested and narrowly scoped
to the orchestrator call.

## Hybrid notebook

`notebooks/05_0_1_improvements.ipynb` becomes an executable release-candidate
acceptance journey.

Default path is offline and deterministic:

1. locate the repository and output directory;
2. preflight Python support, installed HydroSeason version/API, and import
   location with actionable kernel-install guidance;
3. run the public CSV + AOI workflow with progress and a self-contained report;
4. inspect regime/timing evidence, warnings, AOI context, HTML, and all four
   CSV artifacts;
5. invoke `python -m hydroseason run --json` in a subprocess and validate its
   output directory and artifacts;
6. demonstrate the approved 5-9-year low-power guard;
7. state what was and was not exercised.

Optional live path is disabled by default and enabled with
`HYDROSEASON_RUN_LIVE_DEA=1`:

1. run `hydroseason doctor` and require a successful supported environment;
2. fetch one small, one-year DEA AOI with a persistent cache;
3. run a real two-row `run_hydroseason_many` batch using committed AOI files;
4. inspect every source-ordered outcome and raise on failures;
5. print all water-input provenance warnings.

No private `hydroseason._*` import and no fabricated batch result table are
allowed. Notebook output defaults under `notebooks/output`, but automated
execution overrides it with `HYDROSEASON_NOTEBOOK_OUTPUT` so checks leave the
working tree clean.

## Automated notebook acceptance

Add a small `nbclient` runner that executes the notebook from its own
directory, defaults live DEA off, checks every code cell completes, and writes
no executed notebook back into the repository. Notebook execution becomes a
release/docs gate on Python 3.12 and a post-TestPyPI smoke against the installed
candidate.

## Release freeze and promotion

Only after behavior, docs, notebook, and checked scientific outputs agree:

- set package, fallback, citation, changelog, tests, and workflow expectations
  to 0.1.1;
- use release date 2026-08-13;
- remove the old version-specific Zenodo DOI from `CITATION.cff` until Zenodo
  mints the 0.1.1 DOI; retain the concept DOI badge;
- refresh `uv.lock`;
- build and validate wheel/sdist in a clean output directory;
- require green CI for Python 3.10-3.13, strict docs, reproducibility, notebook,
  wheel, and sdist-rebuild gates;
- publish to TestPyPI, execute clean-install CLI and notebook smokes, then tag
  the exact tested commit as `v0.1.1`.

No tag, PyPI upload, GitHub Release, or environment approval is automated by
implementation work.

## Acceptance criteria

- `python scripts/check_release_metadata.py --tag v0.1.1 --require-released`
  passes.
- Ruff, lock, non-network tests with at least 80% coverage, all case-study
  checks, notebook execution, and strict docs pass.
- Resolution fidelity drift is regenerated and reviewed; no resolution becomes
  recommended and all documentation matches the checked CSVs.
- Wheel and sdist are named 0.1.1, pass Twine and wheel-content validation, and
  expose the expected public APIs and CLI.
- Offline notebook passes from top to bottom on a clean 0.1.1 install.
- Optional live cells remain skipped unless explicitly enabled.
- TestPyPI installation and smoke checks pass before the immutable tag is
  created.
