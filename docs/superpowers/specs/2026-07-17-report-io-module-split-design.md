# Design: split `report.py` and `io.py` by concern

**Date:** 2026-07-17
**Scope:** `hydroseason/report.py`, `hydroseason/io.py` only. No behavior change.

## Context

Requested a codebase-architecture improvement pass. The session-start hook
context carried an architecture map (`compute/`, `metrics/`, `ecofragments`
coupling, etc.) — that map is for a different repository and does not apply
to `hydroseason`. Re-scanned this package fresh instead.

`hydroseason/` is a flat package: 13 modules, 4184 lines total. The
`__init__.py` facade is real (not a stub) and correctly used by all external
consumers (scripts, notebooks, docs, tests) — no facade-bypass problem here.

Two files carry multiple unrelated concerns stacked into one module:

- **`report.py`** (1328 lines) — two self-contained SVG-builder functions
  plus one ~900-line `generate_html_report` that mixes KPI/summary
  arithmetic with raw HTML string assembly in a single flat function body.
- **`io.py`** (658 lines) — extent-CSV loading (pandas-only), geospatial
  AOI/raster loading, georeferencing helpers, raster classification/masking,
  and resolution-planning (`plan_resolution`, `probe_amplitude`) all in one
  file under one name.

## Problem found during investigation

`io.py`'s internals are already a de facto public surface, not just an
implementation detail:

- `scripts/run_multi_catchment_report.py` imports
  `hydroseason.io._DEFAULT_CANDIDATE_RES_M` directly — a private-by-convention
  name used externally.
- `tests/test_io.py` imports private helpers (`_clip_to_aoi`, `_classify`)
  directly by submodule path.
- `tests/test_run_multi_catchment_report.py:428` does
  `import hydroseason.io as hio` and reaches into it.

Any split must keep every name currently reachable at `hydroseason.io.X`
resolvable after the split — via re-export from a facade, not by simply
relocating the file.

`io.py`'s module docstring also states a deliberate constraint: "Optional
geospatial imports stay inside raster/AOI functions so extent-CSV users need
only pandas and NumPy." This is implemented as lazy imports inside function
bodies (`import geopandas`, `import rioxarray`, etc.), not at module level.
Splitting into separate files is orthogonal to this guarantee — Python does
not import geo-heavy packages until the function body executes regardless of
which file the function lives in — so the split does not need special
handling to preserve it.

## Design

### `report.py` → orchestrator + 2 new modules

- **`_report_metrics.py`** (new) — pure functions computing KPI/summary
  values (`total_months`, `mean_peak`, `mean_end`, `mean_amp`, `mean_len`,
  confidence counts, min/max, year-card row data, etc.) from the input
  DataFrames. No HTML, no I/O. Independently unit-testable without touching
  any rendering path.
- **`_report_svg.py`** (new) — `_generate_svg_chart` and
  `_generate_seasonal_context_svg`, moved verbatim. Already self-contained,
  no logic change.
- **`report.py`** — retained as the public module. `generate_html_report`
  becomes a thin orchestrator: compute metrics → generate SVGs → assemble
  HTML template from the results. Same public signature
  (`generate_html_report(extent, hydro_years, output_path, title=...)`),
  same import path (`from hydroseason import generate_html_report`).

Only consumer of `report.py` internals is `tests/test_report.py`, plus the
package facade re-export. No external script reaches past `report.py` —
lowest-risk half of this change.

### `io.py` → facade + 3 new modules

- **`_io_extent.py`** (new) — `load_extent_csv`, `complete_monthly_axis`.
  Pandas-only, no geo dependency.
- **`_io_geo.py`** (new) — `load_aoi`, `load_wofs_from_stac`,
  `load_monthly_masks`, `load_monthly_masks_zarr`; georeferencing helpers
  (`_resolve_raster_crs`, `_resolve_raster_transform`,
  `_spatial_transform_from_xy`, `_is_identity_transform`,
  `_assert_compatible_georef`, `_preserve_georef`, `_parse_date_from_name`,
  `_crs_value`); raster classification/masking (`_classify`,
  `_validate_classifier`, `_combine_observations`, `_clip_to_aoi`,
  `mark_in_aoi_nodata_as_invalid`, `_inside_aoi_mask_like`); and the
  exception classes `AOIRasterizationError`, `GeoreferencingError`,
  `IrregularGridError`. These all serve the raster-loading path as one
  cohesive concern.
- **`_io_resolution.py`** (new) — `plan_resolution`, `probe_amplitude`,
  `_next_coarser_res_m`, `_mean_water_fraction`, `_DEFAULT_CANDIDATE_RES_M`.
  Pure arithmetic (depends only on `hydroseason._boundary`), no geo/raster
  dependency.
- **`io.py`** — becomes a re-export facade importing every name (public
  and the already-externally-leaked private ones) from the three new
  modules, so `hydroseason.io.<name>` keeps resolving unchanged for every
  current caller.

### Non-goals

- No behavior change to any function.
- No new abstractions beyond the file split (no wrapper classes, no config
  objects).
- No changes to `_semi_markov.py`, `_dynamic_year.py`, `_boundary.py`, or any
  other module — out of scope, not exhibiting this smell.
- No change to the lazy-import-for-geo-deps pattern.

### Testing / acceptance

`tests/test_io.py`, `tests/test_report.py`, and
`tests/test_run_multi_catchment_report.py` must pass **unmodified** — their
existing `from hydroseason.io import X` / `import hydroseason.io as hio`
statements are the acceptance check that the facade re-export is complete.
Full test suite must stay green. `scripts/run_multi_catchment_report.py` and
`scripts/compare_resolution_signal_fidelity.py` must still run without
import errors (their direct `hydroseason.io.X` imports are the other
acceptance check).
