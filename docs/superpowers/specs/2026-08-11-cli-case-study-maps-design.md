# CLI Recipes and Case-Study Maps Design

**Status:** Deferred follow-up
**Date:** 2026-08-11
**Release policy:** CLI, documentation, and case-study asset follow-up; keep project version at `0.1.0` and do not create a new release.

> **0.1.1 scope note (2026-08-13):** The committed static map-input bundle under
> `case_studies/data/maps/` and the `render_case_study_maps.py` rendering
> pipeline described below are **not** 0.1.1 acceptance criteria. Interactive AOI
> boundary maps in notebook previews and HTML reports remain in 0.1.1 per
> [`2026-08-13-hydroseason-0.1.1-release-readiness-design.md`](2026-08-13-hydroseason-0.1.1-release-readiness-design.md).
> This document preserves the design history for a later follow-up.

## Context

HydroSeason documentation currently teaches the Python API and describes the
case studies, but does not provide one focused place for command-line
workflows. The case-study pages contain results and scientific caveats, but no
spatial figures showing the five testing sites, the boundaries used, or the
relationship between the scientific multiyear mask and the broadest observed
water footprint.

The repository already contains reproducibility scripts and checked case-study
results. It does not contain a public `hydroseason` console entry point, nor a
complete committed set of map-ready boundary and water-footprint layers for all
five published catchments. Aggregate extent CSVs cannot reconstruct those
spatial layers. The new CLI must expose the high-level `run_hydroseason`
orchestrator so long DEA/raster runs can execute in a separate Python process
instead of inside a notebook kernel.

## Goals

1. Add a high-level `hydroseason run` CLI that wraps `run_hydroseason`.
2. Add a dedicated `CLI Recipes` documentation page with paired kernel and CLI
   examples for every documented orchestrator input path.
3. Make long-running CLI behavior, logging, caching, and exit status clear.
4. Keep maintainer/reproducibility commands available as a secondary section,
   not as the primary user-facing CLI.
5. Add stable, offline-renderable case-study maps showing all five testing
   sites and the whole-catchment boundaries considered by the checked studies.
6. Show both approved spatial contexts where data are available:
   - the fixed multiyear water mask used for the scientific denominator;
   - the max-water extent as a translucent contextual overlay.
7. Preserve provenance, reproducibility checks, accessibility, and the current
   `0.1.0` release metadata.

## Non-goals

- Do not duplicate `run_hydroseason` analysis logic in the CLI.
- Do not expose maintainer scripts as a replacement for the high-level
  orchestrator command.
- Do not add a background scheduler or notebook-control feature; the CLI
  process boundary is the isolation mechanism.
- Do not change `run_hydroseason` analysis behavior, case-study CSV values, or
  spatial denominators.
- Do not make interactive web maps a runtime or documentation requirement.
- Do not silently fetch map data during MkDocs builds or CI documentation
  checks.
- Do not move or replace the published `v0.1.0` tag or its assets.

## CLI approaches

### Recommended: thin installed console command plus module entry point

Implement one argument parser and one execution path. Expose it as both
`hydroseason run ...` for installed environments and `python -m hydroseason run
...` for source-tree or controlled environments. Both forms call
`run_hydroseason` exactly once and print a concise result summary.

This gives notebook-equivalent inputs while moving execution into a fresh
process. It also keeps the command usable in shell scripts, schedulers, and
remote sessions without adding a second analysis implementation.

### Repository wrapper script only

Add a `scripts/run_hydroseason.py` wrapper without a package entry point. This
would work from a checkout, but would be less ergonomic for installed users and
would not provide the expected high-level `hydroseason` command.

### CLI-specific pipeline

Reimplement input resolution, analysis, rainfall, and reporting in a CLI
pipeline. This could expose every internal option, but would create behavior
drift from `run_hydroseason` and duplicate failure handling.

The thin console/module approach is selected.

## Map approaches

### Recommended: generated static maps

Add a repository map-rendering script that consumes committed, hashed vector
and spatial-layer inputs and emits static SVG/PNG assets. Embed those assets in
MkDocs pages. This keeps the published documentation offline-friendly,
diffable, and stable across browsers.

### Interactive embedded maps

Generate self-contained Leaflet, Plotly, or similar HTML maps. This would allow
zooming and layer toggles, but adds larger assets, JavaScript/runtime concerns,
more CI surface, and less predictable rendering in the documentation site.

### Manual figures

Add hand-produced images without a renderer or input manifest. This is fastest,
but weakens provenance and makes boundary or layer updates hard to verify.

The generated static map approach is selected.

## Documentation structure

### New CLI page

Create `docs/cli-recipes.md` and add it to `mkdocs.yml` under the main usage
navigation, adjacent to `guide.md`.

Page sections:

1. **Install** — core, raster/STAC, case-study, and documentation extras.
2. **Run an existing CSV** — show the kernel `run_hydroseason` example beside
   the equivalent `hydroseason run` and `python -m hydroseason run` commands.
3. **Run rasters, NetCDF, or Zarr** — preserve the documented
   `water_mask_variable` example in CLI form.
4. **Fetch DEA WOfS** — omit `--water-source`, provide `--aoi`, dates, and
   output settings, matching the kernel example.
5. **Add rainfall context** — show both `--rainfall-csv` and
   `--fetch-rainfall` forms, with the same ancillary-failure semantics.
6. **Long-running process guidance** — explain kernel isolation, cache reuse,
   log redirection, interruption/retry, and exit status.
7. **Repository checks** — place case-study, map, and MkDocs maintenance
   commands after the orchestrator recipes.

The high-level CLI supports path-oriented `run_hydroseason` inputs:
`--water-source`, `--output-dir`, `--aoi`, `--aoi-name`, `--start-date`,
`--end-date`, `--water-mask-variable`, `--rainfall-csv`,
`--fetch-rainfall`, `--stac-url`, `--stac-collection`, `--cache-dir`,
`--report-title`, and `--report-subtitle`. In-memory DataFrames and xarray
objects remain kernel-only. Advanced `analysis_options` remain Python-only
until a separate serialization contract is designed.

Recipes use explicit, portable paths. Long runs can be detached from notebook
lifetimes through normal shell redirection:

```powershell
hydroseason run ... *> hydroseason.log
```

```bash
hydroseason run ... > hydroseason.log 2>&1
```

The page also documents secondary repository commands:

```text
python scripts/prepare_case_study_data.py --check
python scripts/_build_study_case_offline.py --check
python scripts/_build_study_case_rainfall.py --check
python scripts/run_resolution_case_study.py --check --output-dir case_studies/results/resolution
python scripts/render_case_study_docs.py --check
python scripts/render_case_study_maps.py --check
python -m mkdocs serve
python -m mkdocs build --strict
```

## CLI architecture and runtime behavior

Add `hydroseason/cli.py` containing the parser and process entry point, plus
`hydroseason/__main__.py` delegating to the same `main()` function. Add the
`project.scripts` entry point:

```toml
[project.scripts]
hydroseason = "hydroseason.cli:main"
```

The `run` subcommand translates path and scalar arguments into one
`run_hydroseason(...)` call. It prints source kind, regime, route, rainfall
status, output directory, and HTML report path on success. It writes warnings
to standard error while preserving the orchestrator's existing best-effort
rainfall behavior.

Fatal water-input, analysis, or report-writing errors return a nonzero exit
status. Ancillary rainfall failure follows `run_hydroseason`: report creation
can still succeed, with warning/status recorded in the result and surfaced by
the CLI. `--cache-dir` is passed through unchanged so rerunning an interrupted
DEA command can reuse compatible cached work; the CLI does not promise a new
checkpoint protocol.

## Map content and placement

### Overview map

Add one overview figure to `docs/case-studies/index.md` showing:

- Daly River (NT);
- Fitzroy River (WA);
- Gilbert River (QLD);
- Lachlan River (NSW);
- Moonie River (QLD/NSW);
- one representative site marker per catchment;
- the whole-catchment boundary used for each checked case study.

Markers use a guaranteed-on-surface representative point so labels remain
inside their polygons. The figure includes north arrow, scale bar, legend,
short caption, and accessible alternative text.

### Main workflow map

Add a larger figure to `docs/case-studies/main-workflow.md` with the same five
boundaries and markers, plus the two approved spatial layers:

- fixed multiyear water mask: solid teal fill or outline, labelled as the
  scientific denominator mask;
- max-water extent: translucent blue overlay, labelled as broadest observed
  water context.

Caption must state that the overlays are spatial context for interpretation and
do not replace the checked monthly extent inputs or alter routing.

### Resolution and rainfall pages

`resolution-and-acquisition.md` reuses the overview/main spatial figure and
states that the spatial AOIs remain fixed while pixel resolution changes.
`rainfall-context.md` reuses the main spatial figure and states that rainfall
adds temporal context only; it does not change spatial boundaries.

Avoid duplicate binary figures when an existing figure communicates the same
spatial fact.

## Map data and asset contract

Add a versioned map-input bundle under `case_studies/data/maps/` with:

- five full-catchment boundary vectors;
- representative-site metadata or a deterministic point derivation rule;
- the fixed multiyear mask footprints;
- max-water footprints or simplified vector equivalents;
- source, CRS, date range, layer semantics, and SHA-256 metadata.

The current repository has only three demo AOI GeoJSON files, so the
implementation must add a committed five-catchment map fixture bundle before
rendering the final figures. Fixtures may be simplified for display, but must
preserve the canonical whole-catchment coverage and the required mask-layer
semantics. Every map input must be committed and hashed; docs builds must
never depend on live DEA access.

Use a geographic output projection suitable for web documentation, while
preserving source CRS and reprojection details in the map manifest. Map layer
provenance must identify `ga_ls_wo_3`, the 2005–2025 case-study period, and the
multiyear-mask definition used by the release workflow.

## Rendering and verification

Add `scripts/render_case_study_maps.py` with two modes:

- normal mode: render the approved static assets from local map inputs;
- `--check`: render to a temporary directory or compare deterministic output
  metadata, then fail on missing inputs, stale hashes, missing layers, or asset
  drift.

The renderer owns layout, labels, legends, colors, and captions. It must not
modify case-study result CSVs or analysis code.

Add focused tests for:

- CLI parser mapping of path/scalar arguments to one `run_hydroseason` call;
- `hydroseason --help` and `python -m hydroseason --help` smoke behavior;
- nonzero CLI exit status for fatal orchestrator failures;
- successful CLI completion when rainfall is ancillary and unavailable;
- all five site keys and boundary assets being present;
- map manifest hashes and CRS metadata being valid;
- both required overlays appearing in the main-workflow asset metadata;
- `--check` detecting missing or stale map assets;
- documentation links and image alternative text being present.

Required verification after implementation:

```text
python scripts/render_case_study_maps.py --check
python scripts/render_case_study_docs.py --check
python -m mkdocs build --strict
python -m pytest -q
```

## Release and compatibility

Do not edit the `pyproject.toml` version, `CITATION.cff` release metadata,
release tags, or published assets. Add the console entry point without changing
the version; keep `hydroseason.__version__` at `0.1.0`.

This is an unreleased CLI, documentation, and case-study-asset follow-up on the
development branch. It can be implemented and tested without creating a new
release. The immutable `v0.1.0` package and case-study archive remain
unchanged; they do not claim to contain this new CLI.

## Acceptance criteria

- `CLI Recipes` appears in site navigation and renders under strict MkDocs.
- `hydroseason run` and `python -m hydroseason run` execute the high-level
  orchestrator with the documented CSV, raster, DEA, and rainfall examples.
- Kernel and CLI examples show equivalent inputs and outputs.
- Long-running CLI execution occurs in a separate process, supports cache reuse,
  and reports fatal failures through exit status.
- Maintainer commands remain documented as secondary repository recipes.
- Overview map shows all five testing sites and whole-catchment boundaries.
- Main workflow map shows multiyear-mask and max-water layers with clear legend
  and caveat.
- Resolution and rainfall pages reuse spatial context without implying that
  their analyses use different AOIs.
- Map inputs and outputs have local provenance and deterministic checks.
- Existing case-study result checks remain unchanged and pass.
- Version remains `0.1.0`; no release action occurs.
