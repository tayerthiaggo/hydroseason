# Task B Report - Rainfall Strip Manifest

**Status:** DONE_WITH_CONCERNS
**Model used:** gpt-5
**Started from commit:** d0e43e4
**Ended at commit:** d0e43e4

## Summary

Built and applied the Task B strip/keep manifest from the migration plan sections
0.1, 1, and 2.3. The rainfall implementation, rainfall tests, rainfall docs,
rainfall notebooks, rainfall config, rainfall scripts, package data, and broken
CLI entry points were removed from `main`.

No WaterMask-TSFill code was ported in this task. The package surface is
intentionally minimal (`hydroseason.__version__` only) until Task C and Task D
add the water-extent detection engine and source-agnostic loaders.

## Files Changed

### Stripped

- `hydroseason/`: removed `accessor.py`, `cli.py`, `config.py`,
  `daily_detection.py`, `dynamic_season.py`, `fetch.py`, `fixed_season.py`,
  `hydro_year.py`, `io.py`, `metrics.py`, `pipeline.py`, `plot.py`,
  `report.py`, `seasonality.py`, `stress.py`, `validate.py`, and
  `hydroseason/data/monthly_rainfall.csv`.
- `tests/`: removed all rainfall test modules, rainfall fixtures, and the
  rainfall example notebook.
- `docs/`: removed rainfall workflow pages, generated rainfall report example,
  and rainfall report preview images. Kept migration plans and replaced the
  public docs index/citation pages with minimal remote-sensing-first migration
  text.
- `notebooks/`: removed tracked rainfall notebooks and ignored generated
  rainfall notebook exports.
- `config/`: removed `config/example.yaml`.
- `scripts/`: removed rainfall stress, reporting, ground-truth, and comparison
  scripts.

### Kept Or Rewritten

- `hydroseason/__init__.py`: rewritten to expose only `__version__`.
- `README.md`, `docs/index.md`, `docs/citation.md`: rewritten as concise
  migration placeholders that point to `legacy/rainfall` for the old rainfall
  implementation and describe the planned water-extent input paths.
- `pyproject.toml`: removed rainfall description, rainfall keywords, rainfall
  dependencies/extras, package data, and `[project.scripts]`.
- `conda/meta.yaml`: removed CLI entry point, `hydroseason --version` command,
  and rainfall-only runtime dependencies.
- `mkdocs.yml`: removed deleted rainfall pages from nav.
- `MANIFEST.in`: removed stripped config/package-data includes.
- `.github/workflows/test.yml`: changed install target from `.[dev,all]` to
  `.[dev]` because the rainfall/geospatial `all` extra was removed in this
  strip task.
- `CITATION.cff`: updated software title/keywords to remote-sensing-first
  framing while preserving the cited paper metadata.
- `tests/test_package_surface.py`: added focused import/package metadata tests
  proving stripped public names and CLI hooks are not exported or advertised.

### Pre-Existing Dirty Files Carried Forward

- `docs/plans/2026-07-13-wofs-migration-agent-tasks.md`
- `docs/plans/wofs-migration-execution/task-a-legacy-snapshot.md`

These were already dirty from Task A bookkeeping before Task B began and were
not reverted.

## Tests And Checks

- `git status --short --branch`
- `git ls-files hydroseason tests docs notebooks config scripts pyproject.toml conda/meta.yaml mkdocs.yml README.md CITATION.cff MANIFEST.in .github`
- `rg -n "rainfall|Rainfall|chirps|CHIRPS|silo|SILO|era5|ERA5|hydroseason --version|hydroseason\.cli|classify_rainfall|run_pipeline|read_rainfall|plot_|generate_html_report|fetch|daily_detection|dynamic_season|fixed_season|seasonality|metrics|validate|stress|accessor|config" hydroseason tests docs notebooks config scripts pyproject.toml conda/meta.yaml mkdocs.yml README.md CITATION.cff MANIFEST.in .github`
- `rg -n "classify_rainfall|run_pipeline|read_rainfall|get_monthly_.*rainfall|generate_html_report|hydroseason\.cli|hydroseason --version|daily_detection|dynamic_season|fixed_season|seasonality|metrics|validate|stress|accessor|Rainfall_mm|CHIRPS|SILO|ERA5|chirps|silo|era5" hydroseason tests docs notebooks config scripts pyproject.toml conda/meta.yaml mkdocs.yml README.md CITATION.cff MANIFEST.in .github --glob '!docs/plans/**'`
- `rg -n "rainfall|Rainfall" hydroseason pyproject.toml conda/meta.yaml mkdocs.yml MANIFEST.in .github --glob '!docs/plans/**'`
- `python -m pytest tests -q` -> `3 passed`
- `python -c "import hydroseason; print(hydroseason.__all__, hydroseason.__version__)"` -> `['__version__'] 0.1.0`
- `mkdocs build --strict` -> passed
- `python -m build` -> not run successfully; current `python` reports `No module named build`
- `git diff --name-status`
- `git diff --stat`
- `git rev-parse --short HEAD`

Final product-surface `rg` hits for removed public names are only in
`tests/test_package_surface.py`, where they are asserted absent.

## Decisions Made

- Deleted the old rainfall `hydroseason/hydro_year.py` now, even though the plan
  marks it as **REPLACE**, because leaving it in place would preserve rainfall
  public APIs between Task B and Task C. Task C will create the new
  water-extent `hydro_year.py`.
- Kept `numpy` and `pandas` as core dependencies because Task C detection core
  is specified to depend on them. Removed rainfall-only and fetch/report
  dependencies from core and removed old extras entirely; Task E can add
  raster/STAC extras after Task C/D create the new modules.
- Replaced docs with minimal migration placeholders rather than full
  water-mask usage docs. Full docs rewrite remains Task G.
- Removed ignored generated notebook export artifacts under `notebooks/` because
  they contained rainfall report outputs and Task B scope includes notebooks.

## Blockers Or Concerns

- `python -m build` is unavailable in the current interpreter because the
  `build` package is not installed. Task B verification still has package import
  and focused metadata tests; full package build verification belongs to Task E.
- Public API is intentionally skeletal until Task C/D. Importing `hydroseason`
  works, but detection/loader names are not available yet.
- `uv.lock` was not updated in this task because it is assigned to Task E's
  dependency/package cleanup scope.
- Line-ending warnings (`LF will be replaced by CRLF the next time Git touches
  it`) appeared in Git diff/status output for several rewritten text files.

## Next Task Notes

- Task C should create the new `hydroseason/hydro_year.py` from
  WaterMask-TSFill commit `90983c1559e7c08951096bbf196c0daedead6b4f` and update
  `hydroseason.__init__` exports.
- Task D should create the new source-agnostic `hydroseason/io.py` loaders and
  update exports.
- Task E should add raster/STAC extras, zarr pinning, lockfile/package build
  checks, and any remaining packaging cleanup.
- Task G should replace the placeholder docs with complete user-facing docs for
  extent CSV, generic rasters, and WOfS/STAC workflows.

## Review

**Result:** APPROVED

No Critical or Important findings remain.

### Checks

- Confirmed actual surviving files under `hydroseason/`, `tests/`, `docs/`,
  `notebooks/`, `config/`, `scripts/`, and `.github/` match Task B strip scope:
  only `hydroseason/__init__.py`, minimal docs, migration plans, workflows, and
  `tests/test_package_surface.py` remain in those surfaces.
- Confirmed no WaterMask-TSFill implementation code was ported in Task B.
  References to WaterMask-TSFill are documentation/report provenance only.
- Confirmed removed public/package entry points are absent from product
  surfaces. The only hits for `classify_rainfall`, `run_pipeline`,
  `read_rainfall`, `get_monthly_silo_rainfall`, `generate_html_report`,
  `hydroseason.cli:main`, and `hydroseason --version` are negative assertions in
  `tests/test_package_surface.py`.
- Confirmed `hydroseason` imports with a deliberately minimal `__all__`.
- Confirmed `pyproject.toml` no longer has `[project.scripts]`, rainfall
  description/keywords, or removed rainfall extras.
- Confirmed `conda/meta.yaml` no longer has the removed CLI entry point or
  `hydroseason --version` test command.
- Confirmed `mkdocs build --strict` passes with the reduced nav.

### Residual Risk

- `python -m build` could not run because the active interpreter lacks the
  `build` package. This is acceptable for Task B because the changed surface is
  covered by import/metadata tests and full build verification is assigned to
  Task E.
- Public API remains skeletal until Task C/D add the water-extent engine and
  loaders. This is intentional and documented in the Task B report.
