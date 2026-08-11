# CLI Recipes and Case-Study Maps Design

**Status:** Approved for specification
**Date:** 2026-08-11
**Release policy:** Documentation and case-study asset follow-up; keep project version at `0.1.0` and do not create a new release.

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
spatial layers.

## Goals

1. Add a dedicated `CLI Recipes` documentation page.
2. Make common extraction, reproducibility, documentation, and validation
   commands easy to find and copy.
3. Add stable, offline-renderable case-study maps showing all five testing
   sites and the whole-catchment boundaries considered by the checked studies.
4. Show both approved spatial contexts where data are available:
   - the fixed multiyear water mask used for the scientific denominator;
   - the max-water extent as a translucent contextual overlay.
5. Preserve provenance, reproducibility checks, accessibility, and the current
   `0.1.0` release metadata.

## Non-goals

- Do not add a new public `hydroseason` shell command in this change.
- Do not change HydroSeason analysis, API behavior, case-study CSV values, or
  spatial denominators.
- Do not make interactive web maps a runtime or documentation requirement.
- Do not silently fetch map data during MkDocs builds or CI documentation
  checks.
- Do not move or replace the published `v0.1.0` tag or its assets.

## Alternatives

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

The static generated approach is selected.

## Documentation structure

### New CLI page

Create `docs/cli-recipes.md` and add it to `mkdocs.yml` under the main usage
navigation, adjacent to `guide.md`.

Page sections:

1. **Install** — core, raster/STAC, case-study, and documentation extras.
2. **Extract one AOI** — network-backed DEA WOfS extraction using
   `scripts/extract_water_extent_csv.py`, including `--resolution`, date range,
   output path, and `--profile`.
3. **Run from an existing CSV** — point readers to the Python quickstart and
   explain that this repository currently exposes Python API calls rather than
   a package console command.
4. **Verify or rebuild checked case studies** —
   `prepare_case_study_data.py`, the offline main and rainfall builders, the
   resolution study, and `render_case_study_docs.py`.
5. **Render and serve documentation** — `python -m mkdocs serve` and
   `python -m mkdocs build --strict`.
6. **Useful flags and failure modes** — explain `--only`, `--offline`,
   `--full-aoi`, `--force`, cache requirements, and which commands require
   network access.

Commands use portable `python` invocation and explicit repository-relative
paths. Recipes distinguish read-only `--check` commands from commands that
write outputs. `--full-aoi` receives a warning because it is a compatibility or
diagnostic denominator, not the release-standard scientific path.

The page will include these core command families:

```text
python scripts/extract_water_extent_csv.py ...
python scripts/prepare_case_study_data.py --check
python scripts/_build_study_case_offline.py --check
python scripts/_build_study_case_rainfall.py --check
python scripts/run_resolution_case_study.py --check --output-dir case_studies/results/resolution
python scripts/render_case_study_docs.py --check
python scripts/render_case_study_maps.py --check
python -m mkdocs serve
python -m mkdocs build --strict
```

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

Do not edit `pyproject.toml` version, `CITATION.cff` release metadata, release
tags, or published assets. Keep `hydroseason.__version__` at `0.1.0`.

This is a post-release documentation and case-study-asset follow-up on the
development branch. It can update the documentation site without creating a
new release. The immutable `v0.1.0` package and case-study archive remain
unchanged; no new archive is promised by this work.

## Acceptance criteria

- `CLI Recipes` appears in site navigation and renders under strict MkDocs.
- Recipes match current script names and flags; no nonexistent package CLI is
  documented.
- Overview map shows all five testing sites and whole-catchment boundaries.
- Main workflow map shows multiyear-mask and max-water layers with clear legend
  and caveat.
- Resolution and rainfall pages reuse spatial context without implying that
  their analyses use different AOIs.
- Map inputs and outputs have local provenance and deterministic checks.
- Existing case-study result checks remain unchanged and pass.
- Version remains `0.1.0`; no release action occurs.
