# Plan — Re-platform hydroseason to be remote-sensing (WOfS) first; branch off the rainfall engine as legacy

**Audience:** an agent executing this in a conversation rooted at `D:\RLH\5.6\repos\hydroseason` (this repo).
**Source repo (read-only reference):** `D:\RLH\5.6\repos\WaterMask-TSFill`
**Date:** 2026-07-13
**Supersedes:** an earlier draft of this same plan that proposed additive integration (`wofs_hydro_year.py` alongside the rainfall engine). That approach is REJECTED per user decision below. This version is authoritative.

---

## 0. Why this plan exists — read before doing anything

`hydroseason` was built rainfall-first (SILO/CHIRPS/ERA5/BOM fetchers → season/hydro-year detection → validation → reporting, all keyed on rainfall time series). In practice, applied across several catchments, the rainfall-driven approach **did not work well**. The decision is to make the package **remote-sensing (binary water-mask) first** instead, using the detection method from `WaterMask-TSFill` as the new primary engine.

User's explicit decisions (already made — do not re-litigate):
1. **Branch it off, strip main.** Create a `legacy/rainfall` branch that preserves the current repo exactly as-is. Then remove/gut the rainfall code from `main` so `main` becomes remote-sensing-first. Rainfall code is not deleted from history — it lives on in the legacy branch for possible future reuse.
2. **Rename in place on `main`.** After stripping, the ported hydro-year module becomes `hydroseason/hydro_year.py` (not a `wofs_`-prefixed side-module). Its public names (`detect_hydrological_years`, `HydroYearConfig`, etc.) become **the** hydro-year API, with no prefix — because on `main`, this water-mask-based approach is the only modality left, so no disambiguation is needed.
3. **Source-agnostic by design, not WOfS-only.** WOfS/STAC is the *first and easiest* source to wire up (STAC protocol integration is convenient), but it must be one option among several, not baked in as the only path. The package must also accept: (a) other binary water masks in the same raster shape WOfS produces (e.g. from other remote-sensing products, or pre-processed masks the user already has on disk), and (b) a plain CSV of monthly water-extent values, bypassing raster ingestion entirely when a user already has extent numbers. See §1.5 for the architecture this implies.
4. **Dask-first for efficiency.** Any raw or pre-processed binary-mask ingestion (STAC/WOfS or otherwise) should be lazy and Dask-backed end to end — chunked reads, lazy compositing, no premature `.compute()`. This is a performance requirement, not a nice-to-have: the detection workload (monthly extent summarization + hydro-year window search) is small and should run fast with no friction. Flag any step in the ported/rewritten code that forces an eager compute where a lazy one is possible.
5. **Keep the HTML report's look and structure — but not yet.** The current `hydroseason/report.py` and the WaterMask-TSFill Martuwarra pools report are both good and worth preserving as *design references*. They are not being ported or adapted in this pass (their current code is coupled to inputs — rainfall `DiagnosticsReport` / pre-computed QGIS artifacts — that won't exist in the new shape). `report.py` strips to `legacy/rainfall` along with everything else in §1's table. A follow-up plan rebuilds a report against the new source-agnostic data model, explicitly targeting the old report's visual/structural quality as the bar to match. See §5.2 (updated).
6. **Strongly recommend gapfilling before hydro-year detection.** Water-mask gaps, cloud/shadow contamination, and missing months can move wet/dry boundaries. User-facing docs must explicitly recommend running the WaterMask-TSFill gapfilling workflow first, then applying `hydroseason` to the completed monthly mask/extent series. Raw masks may still be accepted, but the docs and warnings should be clear: incomplete masks can produce misleading dry/wet classifications.
7. **AOI is required for raster workflows.** Users start raster/STAC processing by providing an AOI. `hydroseason` must therefore port the minimal AOI-loading and AOI-rasterization support needed to clip/mask WOfS and generic raster inputs. CSV extent input is the exception: it may skip AOI only because the extent values are already assumed to have been computed for a known AOI upstream.

This is a large, repo-shape-changing operation. **Confirm you are on a feature/working branch, not `main`, before making destructive edits** — the branch-and-strip sequence in §2 handles this, follow it in order.

## 0.1. Audit amendments - must be folded into execution

These are non-optional corrections from the plan audit:

1. **Dirty working tree must be preserved deliberately.** `git branch legacy/rainfall` only snapshots committed HEAD, not the current dirty working tree. Before creating `legacy/rainfall`, inventory dirty files, decide whether each dirty change belongs in the rainfall legacy snapshot, commit the intended legacy state, then branch/tag that exact commit. Do not rely on stash as "preserve exactly as-is."
2. **Invalid/cloud pixels must not silently count as dry.** Source `monthly_water_extent()` counts invalid pixels in the denominator and detection ignores `invalid_pct`. That can manufacture dry months when coverage is poor. The port must either exclude invalid pixels from the water-extent denominator, or carry `invalid_pct` into detection and reject/downweight months above a configured invalid threshold. Default must be conservative and documented.
3. **The Dask boundary in the old draft was wrong.** Source `monthly_water_extent()` performs multiple `.compute()` calls. Replace with one shared `dask.compute(...)` call for all small summary arrays, per current Dask guidance, so common work is shared and full rasters are not materialized.
4. **Core dependency policy must support CSV-only use.** Do not make `xarray`, `rioxarray`, `rasterio`, `geopandas`, `dask`, `zarr`, `pystac-client`, or `odc-stac` unavoidable for users who only call `load_extent_csv()` + `detect_hydrological_years()`. Keep detection core importable with only `numpy`/`pandas`; put raster/STAC/Zarr imports behind optional extras and module-local imports.
5. **Climate-window assumptions must be explicit.** The source algorithm assumes cross-year wet seasons and same-year dry windows. Validate configs and fail fast for unsupported wet/dry window shapes, or fix the window builder before claiming climate-agnostic support.
6. **Source-agnostic does not mean dtype guessing.** Do not infer WOfS vs binary masks from dtype. Require an explicit `encoding=` or `classifier=` argument for raster masks, with safe named choices such as `"canonical"`, `"binary"`, and `"wofs"`.
7. **Missing/duplicate month behavior must be strict by default.** Detection should not silently drop missing months or keep the first duplicate. Default to raising on duplicates and missing months unless the caller explicitly chooses a permissive policy.
8. **Do not export unused validation config.** `ValidationSeasonConfig` is unused in the source detection port. Do not expose it in `hydroseason.__init__` until the new validation module exists.
9. **Packaging entry points must be cleaned up.** If `hydroseason/cli.py` strips, remove `[project.scripts] hydroseason = ...` from `pyproject.toml`, remove the conda entry point, and remove package tests/docs that call `hydroseason --version`.
10. **Docs cannot be half-rainfall, half-water-mask.** The minimum docs gate is: README coherent, mkdocs strict build green, nav has no broken rainfall pages, package metadata no longer advertises rainfall, and examples teach the three supported input paths plus the gapfilling recommendation.
11. **Pin source provenance.** Record the exact `WaterMask-TSFill` source commit in this plan and in ported module comments where helpful: `90983c1559e7c08951096bbf196c0daedead6b4f`.
12. **Zarr version strategy must be explicit.** Current Zarr-Python migration guidance recommends `zarr>=2,<3` before migration and `zarr>=3,<4` after migration. Until the code is migrated/tested against Zarr v3, pin raster extra to `zarr>=2,<3`. Add a follow-up note for `zarr>=3,<4` migration.

---

## 1. Inventory — what's rainfall-coupled (strip) vs modality-neutral (keep) vs to-be-replaced (WOfS content)

Checked file-by-file at planning time (`hydroseason/*.py`, line counts):

| File | Lines | Disposition | Why |
|---|---|---|---|
| `hydro_year.py` | 461 | **REPLACE** | Current content is 100% rainfall (`assign_hydro_year`, `assign_fixed_hydro_year`, `assign_hydro_years` — wet-onset detection from `SeasonType`/`Rainfall_mm`). New content: ported WOfS water-extent detection from `WaterMask-TSFill/watermask_tsfill/hydro_year.py`. |
| `fetch.py` | 1919 | **STRIP** | Entirely rainfall-source I/O: `get_monthly_chirps_rainfall`, `get_monthly_silo_rainfall`, `get_daily_silo_rainfall`, `get_monthly_era5_rainfall`, `get_monthly_aoi_rainfall`, plus CHIRPS/SILO/ERA5 caching/chunking helpers. Confirmed via full function listing — no WOfS/remote-sensing-water content at all. |
| `io.py` | 588 | **STRIP** | `read_silo`, `read_bom_monthly`, `read_rainfall`, SILO CSV/fixed-width parsing. All rainfall-format readers. |
| `dynamic_season.py` | 860 | **STRIP** | Wet/dry segmentation from rainfall anomaly (`segment_by_cumulative_anomaly`, `harmonize_with_zero_preservation`, `refine_season_tails`, `repair_short_dry_gaps`). Rainfall-specific. |
| `fixed_season.py` | 281 | **STRIP** | `circular_climatology`, `CircularStats`, `identify_fixed_hydro_year`, `hydro_year_start_driest_6_months` — all operate on monthly rainfall climatology. |
| `seasonality.py` | 427 | **STRIP** | `stl_seasonality_strength`, `walsh_lawler_seasonality_index` (Walsh-Lawler SI is explicitly a rainfall-specific diagnostic per its own docstring), `detect_seasonality_regime`. Rainfall regime classification. |
| `metrics.py` | 220 | **STRIP** | `compute_annual_spi_categories`, `classify_drought`, `classify_year_spi`, `compute_season_metrics`, and `compute_end_dry_metrics` are rainfall/SPI/season-label metrics. Do not carry them into the water-mask package. New water-extent metrics belong in a follow-up design. |
| `validate.py` | 637 | **STRIP** | `validate_monthly_input`, `validate_daily` — validates rainfall input schemas (`Rainfall_mm` columns etc). Not the same as `WaterMask-TSFill`'s `validate.py` (which is fill-accuracy validation) — neither is a direct fit; WOfS validation needs its own design, out of scope for this plan (see §6). |
| `pipeline.py` | 1955 | **STRIP** (orchestrator, will be rewritten) | Wires together every rainfall module (`dynamic_season`, `fixed_season`, `hydro_year`, `metrics`, `seasonality`, `validate`). Its shape (config-driven `run_pipeline`, `DiagnosticsReport` sidecar) is worth preserving as a *pattern* for a future WOfS pipeline, but its content must be rewritten around the new `hydro_year.py`. Do not attempt a line-level port — this needs a fresh, smaller pipeline built for the WOfS inputs actually available (see §5, optional follow-up, not this plan's job). |
| `accessor.py` | 135 | **STRIP** | Pandas `.hydroseason` DataFrame accessor wrapping the rainfall pipeline (`classify_rainfall` etc). Rainfall-shaped API. |
| `cli.py` | 216 | **STRIP** | CLI entry point driving `run_pipeline` / rainfall config. Rewrite later once a WOfS pipeline exists; not this plan's job. |
| `config.py` | 219 | **STRIP** (dataclasses are rainfall-shaped) | `RunConfig`, `InputConfig`, `FetchConfig`, `AlgorithmConfig`, `ValidationConfig`, `DailyDetectionConfig` are all built around rainfall inputs/fetch sources. A new, smaller config belongs with the new pipeline, not created preemptively here. |
| `daily_detection.py` | 216 | **STRIP** | Daily-rainfall-specific onset detection. |
| `stress.py` | 227 | **STRIP** | Rainfall-specific (`Rainfall_mm`, daily detection, rainfall stress assumptions). Preserve only on `legacy/rainfall`. |
| `plot.py` | 1016 | **STRIP** | Rainfall-specific plots (`plot_agg_monthly_rainfall`, `plot_monthly_climatology`, `plot_stl_decomposition`, `plot_imputation_overview`) and report helpers. Future water-extent plots should be rebuilt against the new output model, using the legacy branch as design reference only. |
| `report.py` | 1385 | **STRIP — preserved as design reference only, see §5.2** | Current content (`generate_html_report`, `generate_multisite_timeline_report`, `display_summary`, `export_bundle`) is built around the rainfall `DiagnosticsReport`/`HydroSeasonResult`. Not adapted or ported in this pass — its HTML/visual quality is worth keeping as a *reference* for a future report rebuilt against the new source-agnostic data model. Do not attempt to adapt its signatures now; strip it clean like everything else and revisit in a dedicated follow-up (§5.2). |
| `__init__.py` | 158 | **REWRITE** | Public API surface — see §4. |

**Tests, notebooks, docs, config/** mirror this split — `tests/test_hydro_year.py` (rainfall) vs the new `tests/test_hydro_year.py` (ported, will replace it after the rename), and similarly for the rainfall-only test files (`test_dynamic_season.py`, `test_fixed_season.py`, `test_seasonality.py`, `test_fetch.py`, `test_daily_detection.py`, `test_io.py` (rainfall readers), `test_cli.py`, `test_pipeline.py`, `test_accessor.py`, `test_validate.py`, `test_config.py`, `test_stress.py`, `test_plot.py`, `test_metrics.py`, `test_australia_stress.py`, `test_cumulative_anomaly.py`, `test_end_dry_metrics.py`). All of these strip from main along with their source modules unless a test is rewritten around the new water-mask API in this plan.

---

## 1.5. Architecture requirement: source-agnostic ingestion, Dask-first

The package must not be "a WOfS package." WOfS/STAC is the first source wired up because it's convenient (direct STAC protocol integration), but the design must treat it as one interchangeable option. Confirmed by the user: three source shapes need to be supported, all converging on the same canonical representation before `hydro_year.py` ever sees the data.

### 1.5.1 — Canonical shape, one boundary
Adopt a **common loader interface** (user-confirmed, not the config-registry alternative): each source gets its own loader function that adapts *into* one of two canonical shapes; nothing downstream (`hydro_year.py`, the future report) branches on source type at all.

- **Raster sources** (WOfS/STAC, or any other pre-processed binary water-mask raster) → require a user-provided AOI, clip/mask to that AOI, then return a lazy, Dask-backed `xr.DataArray` shaped exactly like what `monthly_water_extent()` expects after adaptation (time/y/x, canonical values: dry `0`, water `1`, invalid `-1`, outside AOI `-2`). Match `WaterMask-TSFill/watermask_tsfill/hydro_year.py`'s convention but document all four values, including dry.
- **Pre-computed extent sources** (a CSV of monthly water-extent percentages) → skip raster ingestion and `monthly_water_extent()` entirely; feed straight into `detect_hydrological_years()`, which already accepts a plain `pd.Series`/`pd.DataFrame` (see its signature — `extent: pd.Series | pd.DataFrame`). This path already exists in the ported code; you mainly need a small CSV-reading convenience loader (parse dates, coerce a value column) rather than new detection logic.

**Strong recommendation for users:** if they start from raw/incomplete water masks, run WaterMask-TSFill gapfilling first, then feed the completed masks or completed monthly extents into this package. The CSV path is valid only if the upstream extent series already handled data completion/quality screening.

### 1.5.2 — Concrete loaders to build/port (source repo has most of the raster-side building blocks already)
`WaterMask-TSFill/watermask_tsfill/io/loaders.py` already separates source-specific loading from generic loading — reuse this split rather than inventing a new one:

| New loader | Role | Port from / base on |
|---|---|---|
| `load_wofs_from_stac(...)` | STAC/WOfS-specific: queries a STAC catalog, groups items by month, classifies WOfS pixel flags | `watermask_tsfill/io/loaders.py:601 load_wofs_from_stac` — already Dask-lazy (chunked `rxr.open_rasterio`), port with minimal changes |
| `load_monthly_masks(...)` | Generic binary-raster loader: globs `water_*.tif`-style files in a directory, reclassifies only by explicit user-selected encoding/classifier | `watermask_tsfill/io/loaders.py:388 load_monthly_masks` — preserve lazy/chunked reads (`chunks={"x":..., "y":...}` on `rxr.open_rasterio`), but remove unsafe dtype-based WOfS inference. Require `encoding="canonical"`, `encoding="binary"`, `encoding="wofs"`, or a `classifier=` callable. |
| `load_monthly_masks_zarr(...)` | Loads a pre-built zarr cube (already-canonical, already lazy via `dask`/`zarr`) | `watermask_tsfill/io/loaders.py:694 load_monthly_masks_zarr` |
| `load_aoi(...)` | Public AOI convenience loader: accepts OGR-readable vector paths or a `geopandas.GeoDataFrame`, validates non-empty geometries, optionally reprojects | `watermask_tsfill/io/loaders.py:213 load_aoi` |
| AOI rasterization helpers | Private support used by raster loaders to apply AOI masks safely and fail closed when clipping fails | Port the minimal called helpers from `watermask_tsfill/io/loaders.py`: `AOIRasterizationError`, `GeoreferencingError`, `IrregularGridError`, `_inside_aoi_mask_like`, `mark_in_aoi_nodata_as_invalid`, and the small CRS/transform helpers those functions call. Do not port unrelated loader features. |
| `load_extent_csv(path, ...)` (new, small) | Reads a CSV of monthly water-extent values straight into the `pd.Series`/`pd.DataFrame` shape `detect_hydrological_years` already accepts | New — no direct source equivalent, but trivial given `detect_hydrological_years`'s existing `value_col`/`date_col` parameters (see ported `hydro_year.py::detect_hydrological_years`) |
| `complete_monthly_axis(...)` | Fills missing months in a time axis so downstream window search doesn't silently skip gaps | `watermask_tsfill/io/loaders.py:249 complete_monthly_axis` — source-agnostic already, port as-is |

AOI support is required for raster ingestion. Port it deliberately and minimally: users must be able to pass an AOI path or `GeoDataFrame` to `load_wofs_from_stac(...)` and `load_monthly_masks(...)`; the loaders must refuse to proceed if AOI clipping/rasterization fails, because processing unclipped rasters would corrupt water-extent statistics. `load_monthly_masks_zarr(...)` may accept `aoi=None` only when the Zarr cube is already canonical and AOI-clipped; if it accepts AOI, apply the same mask/validation path.

### 1.5.3 — Dask-first, no premature `.compute()`
User flagged this explicitly as a performance requirement: the detection workload itself is small (monthly summarization + a window search over at most a few hundred months) and must run with zero friction. When porting/adapting the loaders above:
- Keep every raster read chunked (`rxr.open_rasterio(..., chunks=...)`) — already true in the source loaders, preserve it.
- `monthly_water_extent()` in the source calls `.compute()` separately for each summarized statistic (`n_aoi.compute()`, `n_water.compute()`, `n_invalid.compute()`). Fix this during the port: build lazy summary arrays first, then call `dask.compute(n_aoi, n_valid, n_water, n_invalid)` once so common graph work is shared and only the small per-month scalars materialize.
- Default extent calculation must be quality-aware: compute `valid_pct`/`invalid_pct`; do not let invalid pixels act like dry pixels. Detection must reject or mark months with invalid coverage above `max_invalid_pct` unless the user explicitly opts into permissive behavior.
- Any new generic-raster classification/reclassification step (§1.5.2's `load_monthly_masks` generalization) must stay dask-array-compatible — use `xr.apply_ufunc`/dask-aware numpy ops, not a forced `.compute()` mid-pipeline.
- If profiling during Step 2.7's verification shows any surprising slowness, flag it back to the user rather than silently working around it — this is meant to be fast, and a slowdown likely indicates an accidental eager compute crept in.

Notebooks (`hydroseason_aoi_fetch_example.ipynb`, `hydroseason_quickstart.ipynb`, `hydroseason_rainfall_io_example.ipynb`, `hydroseason_report.html`, `tests/hydroseason_tayer2026_example.ipynb`) are all rainfall-workflow demos — strip from main, preserved on `legacy/rainfall`.

---

## 2. Execution sequence

### Step 2.1 — Snapshot current state as the legacy branch
```bash
cd "D:/RLH/5.6/repos/hydroseason"
git status --short              # inventory dirty files; branch pointer alone will not save them
git diff --stat
git diff --name-status
```
If dirty changes are present, stop and classify each file:
- belongs in rainfall legacy snapshot -> commit it before branching;
- unrelated local work -> move to a separate branch/commit before continuing;
- generated artifact not meant for history -> get explicit user approval before deleting/ignoring it.

Then create collision-safe refs from the exact committed rainfall snapshot:
```bash
git branch --list legacy/rainfall
git tag --list v0-rainfall-legacy
git branch legacy/rainfall
git tag v0-rainfall-legacy
git rev-parse HEAD
```
Record the resulting SHA in this plan before implementation begins.
Do NOT push either yet — ask the user before pushing `legacy/rainfall` or the tag to `origin` (this repo has a public GitHub remote `tayerthiaggo/hydroseason`). Pushing publishes a permanent branch/tag on a repo that isn't just local.

### Step 2.2 — Create the working branch for the re-platform
```bash
git checkout -b feat/remote-sensing-first
```
All destructive edits happen here, never directly on `main`.

### Step 2.3 — Strip rainfall modules
Remove (via `git rm`) every file marked **STRIP** in §1's table, from `hydroseason/`, `tests/`, `notebooks/`, and any rainfall-only `config/*.yaml`/docs that reference them exclusively. Before deleting each, grep for cross-references from files NOT being stripped (e.g. does `hydro_year.py` (old) get imported anywhere outside the strip list? does `plot.py` import anything worth extracting first?). Do this check file-by-file — don't bulk-delete blind.

There are no remaining **CHECK** files after the audit. `stress.py`, `metrics.py`, `plot.py`, and `report.py` strip from `main`; their useful ideas remain available on `legacy/rainfall` as design references.

### Step 2.4 — Port the hydro-year detection engine, replacing `hydro_year.py`
1. Delete the current `hydroseason/hydro_year.py` (rainfall version — already snapshotted on `legacy/rainfall`).
2. Copy `WaterMask-TSFill/watermask_tsfill/hydro_year.py` (325 lines) to `hydroseason/hydro_year.py` verbatim, then adapt:
   - Module docstring: describe this as the hydro-year/season detection engine driven by monthly water-extent — source-agnostic (WOfS, other binary water masks, or a plain extent CSV all converge here; see §1.5). Drop any "vs rainfall" framing — there's no rainfall path on `main` anymore to disambiguate against.
   - Replace the cross-repo import:
     ```python
     from .io.loaders import DuplicateMonthPolicy, _handle_duplicate_months
     ```
     `hydroseason/io.py` is being stripped (it's rainfall-CSV reading), so there is no natural home left in this repo for a shared IO module unless you create one. Two options:
     - **(preferred, simpler)** Inline `DuplicateMonthPolicy` (a `Literal["warn","raise"]` type alias) and `_handle_duplicate_months` (~25 lines, pandas + warnings only — see `WaterMask-TSFill/watermask_tsfill/io/loaders.py:11,172-194`) directly into the new `hydro_year.py` as private module-level helpers.
     - **(if a new lightweight `io.py` is wanted, since Step 2.4a below needs one anyway for the loaders)** create `hydroseason/io.py` from scratch containing these two symbols plus the ported loaders from §1.5.2/Step 2.4a — this is the natural shared home once loaders exist. Do not resurrect the rainfall `io.py`'s content.
   - Public names stay: `monthly_water_extent`, `detect_hydrological_years`, `label_hydrological_months`, `HydroYearConfig`. Do **not** export `ValidationSeasonConfig`; it is unused until a real validation module exists.
   - Keep `detect_hydrological_years()` and `label_hydrological_months()` importable with core dependencies only (`numpy`, `pandas`). Put `xarray`/`dask` imports behind `TYPE_CHECKING` or inside `monthly_water_extent()` so the CSV-only path works without raster extras installed.
   - Add config fields or parameters for `max_invalid_pct`, duplicate-month policy, missing-month policy, and supported wet/dry window validation. Conservative defaults: raise on duplicate months, raise on missing months, reject months above `max_invalid_pct`, and fail fast for unsupported season-window geometry.

### Step 2.4a — Build the source-agnostic loaders (see §1.5 for full design)
Create `hydroseason/io.py` (fresh — the rainfall `io.py` is fully stripped, this is a new file with a new purpose) containing:
1. `load_aoi(...)` — ported from `watermask_tsfill/io/loaders.py:213`, public. Accept file path or `GeoDataFrame`, reject missing/empty/invalid geometry inputs, optionally reproject via `to_crs`.
2. Minimal private AOI/georeferencing support — port only the helpers needed by `load_aoi`, `load_wofs_from_stac(...)`, and `load_monthly_masks(...)`: `AOIRasterizationError`, `GeoreferencingError`, `IrregularGridError`, `_inside_aoi_mask_like`, `mark_in_aoi_nodata_as_invalid`, `_spatial_transform_from_xy`, `_resolve_raster_crs`, `_resolve_raster_transform`, `_is_identity_transform`, and `_assert_compatible_georef` if used by the loader code. Keep these private unless a user-facing exception class is needed for tests/docs.
3. `load_wofs_from_stac(...)` — ported from `watermask_tsfill/io/loaders.py:601`, minimal changes, keep it Dask-lazy, require `aoi`.
4. `load_monthly_masks(...)` — ported from `watermask_tsfill/io/loaders.py:388`. Require `aoi`. Remove dtype guessing. Require explicit `encoding="canonical"`, `encoding="binary"`, `encoding="wofs"`, or `classifier=callable`. The default should be `encoding="canonical"` only when the documented canonical values are present.
5. `load_monthly_masks_zarr(...)` — ported from `watermask_tsfill/io/loaders.py:694`, already canonical/lazy. Treat Zarr as already AOI-clipped by default; if an `aoi` parameter is added, apply the same private AOI masking helper and fail closed on rasterization errors.
6. `load_extent_csv(path, ...)` — new, small. Reads a CSV into the shape `detect_hydrological_years` already accepts (a `pd.Series`/`pd.DataFrame` with a date index or `date_col`, plus a `value_col`). No raster/Dask involvement in this path at all — it's the deliberately-lightweight option for users who already have extent numbers, and docs must state those extents are assumed to belong to a known AOI.
7. `complete_monthly_axis(...)` — ported from `watermask_tsfill/io/loaders.py:249`, source-agnostic already.

Do not port the whole `loaders.py` file wholesale. AOI support is required, but the scope is the minimal AOI path that lets raster loaders load, reproject, rasterize, clip/mask, and fail closed.

Write smoke tests confirming `load_aoi(...)` accepts a valid vector path/GeoDataFrame and rejects empty geometry. Write a small smoke test per loader confirming it returns the canonical lazy shape (chunked `xr.DataArray` for the raster loaders, plain `pd.Series`/`DataFrame` for the CSV loader) without forcing a compute. Also test that binary `uint8` masks are not treated as WOfS flags unless `encoding="wofs"` is explicit, and that AOI rasterization failure refuses to process an unclipped raster.

### Step 2.5 — Port the test file, replacing the old one
1. Delete `tests/test_hydro_year.py` (rainfall version).
2. Copy `WaterMask-TSFill/tests/test_hydro_year.py` → `hydroseason/tests/test_hydro_year.py`, update imports from `watermask_tsfill.hydro_year` → `hydroseason.hydro_year`.
3. Check whether it depends on fixtures/conftest helpers from the source repo; port any that are missing into this repo's `tests/conftest.py` / `tests/fixtures/` without clobbering fixtures still needed by whatever test files remain.

### Step 2.6 — Rewrite `__init__.py` and `pyproject.toml`
`__init__.py`: drop every import/export tied to stripped modules. What remains as the public surface:
```python
from .hydro_year import (
    HydroYearConfig,
    detect_hydrological_years,
    label_hydrological_months,
    monthly_water_extent,
)
from .io import (
    load_aoi,
    load_wofs_from_stac,
    load_monthly_masks,
    load_monthly_masks_zarr,
    load_extent_csv,
    complete_monthly_axis,
)
```
Update the module docstring (currently `"""HydroSeason: rainfall-based hydrological wet/dry season delineation."""`) to describe the source-agnostic, remote-sensing-first framing — mention explicitly that WOfS/STAC is one supported source among several (raster masks, extent CSV), not the only one. Update `__all__` to match. Remove the `try/except ImportError` blocks for `plot`/`report` re-exports since those modules are stripped this pass (§5.2) — don't leave dead imports.

`pyproject.toml`:
- Remove rainfall-only deps that only `fetch.py`/`io.py`/`plot.py`'s rainfall plots needed (e.g. `gcsfs`, `netCDF4`, `pyarrow` if nothing else uses them — check first), remove `statsmodels` if nothing outside `seasonality.py` used it.
- Keep core deps minimal: `numpy`, `pandas`, and any already-required packaging/test basics. CSV extent detection must import and run without raster/geospatial dependencies installed.
- Add extras:
  - `raster`: `xarray`, `rioxarray`, `dask[array]` or `dask[complete]`, `rasterio`, `geopandas`, `shapely`, `affine`, `zarr>=2,<3`.
  - `stac`: include `raster` plus `pystac-client>=0.8`, `odc-stac>=0.3`, and any additional deps actually required by the STAC code.
  - `all`: include `raster` + `stac` + docs/dev extras as appropriate.
- Check `WaterMask-TSFill/pyproject.toml` for version floors (`xarray>=2024.1`, `rioxarray>=0.15`, `rasterio>=1.4`, `geopandas>=1.0`, `dask[complete]>=2024.1`, `zarr>=2.0,<3.0`) versus this repo's current floors (`xarray>=2023.8`, `rasterio>=1.3`, `geopandas>=0.14`, `zarr>=2.16`) — reconcile to whichever floor is actually needed, don't just take the higher one blindly.
- Remove `[project.scripts] hydroseason = "hydroseason.cli:main"` if `cli.py` strips. Also update `conda/meta.yaml`, package tests, and docs that expect `hydroseason --version`.
- Update `description`/`keywords`/`classifiers` to reflect remote-sensing/surface-water framing (source repo uses `keywords = ["remote-sensing", "surface-water", "gap-filling", "geospatial", "xarray"]` — adapt, don't copy `gap-filling` since that's WaterMask-TSFill's fill algorithm, not this repo's job).

### Step 2.7 — Verify
```bash
python -c "from hydroseason import detect_hydrological_years, monthly_water_extent, HydroYearConfig, load_extent_csv; print('ok')"
pytest tests/ -q
python -m build
python -m twine check dist/*
mkdocs build --strict
```
Expect the surviving test suite (new `test_hydro_year.py` + new loader smoke tests + package/docs checks) to be green. There is no rainfall regression suite to protect anymore on this branch — that's intentional, it lives on `legacy/rainfall`. Also sanity-check the Dask laziness requirement from §1.5.3: constructing a loader call should not itself trigger a large compute — only the small summarized-statistics step in `monthly_water_extent` should.

Add specific verification tests before declaring done:
- CSV-only import smoke in an environment without raster extras, or at least a test that imports detection while monkeypatching missing raster packages.
- `monthly_water_extent()` excludes/rejects invalid-heavy months according to `max_invalid_pct`.
- duplicate months raise by default.
- missing months raise by default.
- unsupported wet/dry season-window geometry raises with a clear message.
- `load_monthly_masks(..., encoding="binary")` preserves binary masks and does not run WOfS bit classification.
- `load_aoi(...)` validates AOI files/GeoDataFrames, raster loaders require AOI, and AOI rasterization/clipping failures stop processing instead of falling back to unclipped rasters.
- Dask graph materializes only at the monthly summary boundary; no loader calls `.compute()`.
- Known/golden catchment or hand-built synthetic series returns expected hydro-year boundaries.

### Step 2.8 — Update repo-level docs
`README.md`, `docs/`, `mkdocs.yml` nav, `CHANGELOG.md`: rewrite the framing from rainfall-first to source-agnostic remote-sensing-first — explicitly document all three supported input paths (STAC/WOfS, other binary water-mask rasters, extent CSV), not just WOfS. Add a note pointing to `legacy/rainfall` branch for the previous rainfall-based approach, so future readers know it exists and why.

Minimum docs gate for this pass:
- README no longer teaches rainfall workflow as current behavior.
- MkDocs nav has no missing pages and no current-page rainfall promises.
- Install docs show `pip install hydroseason` for CSV/detection core and extras for raster/STAC usage.
- Usage docs explicitly and strongly recommend running WaterMask-TSFill gapfilling before hydro-year detection when starting from incomplete/raw masks.
- Package metadata, `CITATION.cff`, examples, and config snippets do not advertise stripped rainfall APIs.

### Step 2.9 — Commit
Commit on `feat/remote-sensing-first` with a clear, scoped message describing the pivot, e.g.:
```
feat!: re-platform hydroseason as remote-sensing water-mask first

Rainfall-based hydro-year/season detection underperformed across
multiple catchments in practice. Replace it with a source-agnostic
water-extent detection engine (ported from WaterMask-TSFill), supporting
STAC/WOfS, other binary water-mask rasters, and extent-CSV input via a
common lazy/Dask-backed loader interface. Full rainfall implementation
preserved on legacy/rainfall branch / v0-rainfall-legacy tag for
potential future reuse.
```
The `!` signals a breaking change (public API surface changes entirely). Do not push or open a PR unless the user explicitly asks — this branch replaces the entire public API of a repo with a public GitHub remote.

---

## 3. What does NOT move (confirmed out of scope)

- `watermask_tsfill/fill_stgf.py`, `stages.py`, `quick_tune.py`, `validation_summary.py`, and any `seasonal_radius` code — that's the STGF gap-fill candidate-weighting radius, an unrelated algorithm (temporal donor-pixel weighting for filling water-mask gaps), not season/hydro-year detection. Do not port any of it.
- `watermask_tsfill/validate.py`'s `wet_months`/`dry_months` stratified accuracy-metrics config — that's fill-accuracy validation stratified by season, a different concern from hydro-year *detection*. Not part of this plan.

---

## 4. Public API after this plan (on `main`, post-merge)

```python
from hydroseason import (
    # detection core — source-agnostic, operates on canonical shapes
    HydroYearConfig,
    detect_hydrological_years,
    label_hydrological_months,
    monthly_water_extent,
    # loaders — one per source, all converging on the canonical shape (§1.5)
    load_aoi,
    load_wofs_from_stac,
    load_monthly_masks,
    load_monthly_masks_zarr,
    load_extent_csv,
    complete_monthly_axis,
)
```
No `Wofs*`/`wofs_` prefixing on the detection core — confirmed by user as the desired naming once rainfall is gone from main. The loaders keep source-descriptive names (`load_wofs_from_stac` etc.) since, unlike the detection core, *which loader you call* is exactly how the source is selected — that's the source-agnostic design's seam, not something to hide. `ValidationSeasonConfig` remains deferred until a real water-mask validation module exists.

---

## 5. Explicitly deferred (do not do in this pass — separate future plan/conversation)

1. **A new pipeline/orchestration layer** replacing what `pipeline.py`/`config.py`/`cli.py` did for rainfall — i.e. a config-driven `run_pipeline` equivalent that goes from any of the three supported inputs (§1.5) straight through to a hydro-year/season-labelled, validated, reported output, likely via the config-driven-source-registry shape the user did NOT pick for the core loader interface but which may still suit a higher-level orchestrator. This plan only ports the detection core + loaders; building the new orchestration layer is real design work and deserves its own brainstorming/planning pass, not a mechanical port.
2. **A new HTML report, using the old `report.py` and `martuwarra_pools.py` as design references.** Both are good and confirmed worth preserving *as a bar to match*, not as code to adapt in this pass:
   - `hydroseason/report.py` (1385 lines, this repo) — strips to `legacy/rainfall` per §1's table. Its plotly-based dashboard/timeline structure (`generate_html_report`, `plot_dashboard`, `plot_season_timeline`, etc.) is the reference for overall report shape and interactivity.
   - `watermask_tsfill/reporting/martuwarra_pools.py` + `figures.py` + `html.py` (~550 lines + helpers, WaterMask-TSFill) — a genuinely different, self-contained-HTML report generator (Leaflet map, GeoTIFF overlays, classified point layers). Reference for the geospatial/mapping half of a future report, but note it currently reads pre-computed QGIS artifacts rather than driving off the canonical in-memory data model — a rebuild would need to go the other way (report reads directly from `detect_hydrological_years`/`monthly_water_extent` output, or from a future pipeline's result object).
   When this follow-up is scoped, the task is: design a report against the new source-agnostic data model (canonical `xr.DataArray`/extent series → `detect_hydrological_years` output), targeting the visual/structural quality of both references above, not a literal merge of their code.
3. **A water-mask-equivalent validation module** to replace the stripped rainfall `validate.py`. Neither repo has an off-the-shelf fit (`WaterMask-TSFill/validate.py` validates *fill accuracy*, not season/hydro-year detection quality) — needs its own design.
4. Rewriting `plot.py` for water-extent-relevant visualizations (season timelines over water-extent instead of rainfall climatology) — feeds into item 2 above, likely the same follow-up effort.

Flag all four to the user as follow-up work once this plan lands; do not scope-creep into them now.

---

## 6. Decision points to confirm with the user during/after execution

1. **Which dirty files belong in the legacy rainfall snapshot** — must be resolved before `legacy/rainfall` is created, because the current worktree has uncommitted changes.
2. **Invalid-coverage default threshold** — recommend conservative default `max_invalid_pct=20.0` for monthly extent detection, with docs explaining users should gapfill first; tune if domain evidence suggests a different threshold.
3. **Pushing `legacy/rainfall` / `v0-rainfall-legacy` to `origin`** — this repo has a public remote (`github.com/tayerthiaggo/hydroseason`). Confirm before pushing anything, including the legacy branch/tag.
4. **Golden catchment acceptance data** — ask user which catchment/month series should be the scientific acceptance target if no fixture already exists.

---

## 7. Agent task map: models and exact prompts

Use this map if implementing with agentic workers. Do not spawn all tasks blindly; run in order, review after each task, and keep commits small. Model picks are optimized for accuracy per token:

- **Default implementation model:** `gpt-5.5` — best balance for codebase edits, tests, and package plumbing.
- **High-risk review/science gates:** `gpt-5.6` — use for short, targeted audits where correctness matters more than token cost.
- **Docs/mechanical cleanup:** `claude sonnet` — efficient for coherent docs rewrites and cross-reference cleanup.
- **Avoid as primary executor here:** `fable`, `composer 2.5`, `grok 4.5`, `kimi 2.7` unless a specific local workflow requires them. This migration is package/science correctness work, not broad ideation.
- **Use `opus` only as fallback reviewer** if `gpt-5.6` is unavailable.

### Task A - legacy snapshot and branch safety

**Model:** `gpt-5.5`

**Prompt:**
```text
You are in D:\RLH\5.6\repos\hydroseason. Execute only the legacy snapshot safety work from docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0.1 and 2.1. Inventory the dirty worktree with git status/diff, classify which dirty files must be preserved in the rainfall legacy snapshot, and stop before any destructive action or push. Do not create/delete branches until the dirty-file decision is explicit. Return: dirty-file table, recommended action per file, current HEAD SHA, and any branch/tag name collisions.
```

### Task B - rainfall strip manifest

**Model:** `gpt-5.5`

**Prompt:**
```text
Read docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 1, 2.3, and 0.1. Build the exact strip/keep manifest for hydroseason/, tests/, docs/, notebooks/, config/, scripts/, pyproject.toml, conda/meta.yaml, mkdocs.yml, README.md, CITATION.cff, MANIFEST.in, and GitHub workflows. Verify cross-references with rg before editing. Implement only the manifest changes needed to remove rainfall APIs and broken entry points. Do not port WaterMask-TSFill code in this task. Add or update tests only if needed to prove imports/package metadata do not reference stripped modules.
```

### Task C - detection core port

**Model:** `gpt-5.5`

**Prompt:**
```text
Port WaterMask-TSFill commit 90983c1559e7c08951096bbf196c0daedead6b4f watermask_tsfill/hydro_year.py into hydroseason/hydro_year.py per docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0.1, 1.5, and 2.4. Keep detect_hydrological_years and label_hydrological_months importable with only numpy/pandas. Do not export ValidationSeasonConfig. Add strict duplicate/missing month policies, supported season-window validation, invalid coverage handling, and conservative max_invalid_pct behavior. Fix monthly_water_extent to avoid invalid-as-dry behavior and use one shared dask.compute boundary. Write focused tests for each behavior before implementation.
```

### Task D - source-agnostic loaders

**Model:** `gpt-5.5`

**Prompt:**
```text
Create the new hydroseason/io.py loaders from docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 1.5 and 2.4a. Port only the needed loader code from WaterMask-TSFill commit 90983c1559e7c08951096bbf196c0daedead6b4f. Implement load_aoi, the minimal private AOI/georeferencing helpers, load_extent_csv, complete_monthly_axis, load_monthly_masks, load_monthly_masks_zarr, and load_wofs_from_stac. Require AOI for STAC and generic raster mask loaders; fail closed if AOI clipping/rasterization fails. Keep raster imports module-local so CSV-only detection does not require xarray/rasterio/dask/zarr/geopandas. Remove dtype guessing: require encoding="canonical"|"binary"|"wofs" or classifier=callable. Add load_aoi tests, lazy-shape smoke tests, AOI-failure tests, and a uint8 binary-not-WOfS regression test.
```

### Task E - dependency and packaging cleanup

**Model:** `gpt-5.5`

**Prompt:**
```text
Update pyproject.toml, uv.lock if required, conda/meta.yaml, MANIFEST.in, GitHub workflows, and package metadata per docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0.1, 2.6, and 2.7. Keep core dependencies minimal for CSV-only detection. Move raster/STAC deps to extras, pin zarr>=2,<3 until a v3 migration is tested, remove rainfall-only dependencies and CLI entry points, and remove tests that call hydroseason --version if cli.py is gone. Verify python -m build, twine check, package import smoke, and mkdocs strict when available.
```

### Task F - tests and scientific acceptance

**Model:** `gpt-5.6`

**Prompt:**
```text
Review the implemented hydroseason water-mask detection behavior against docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0.1, 1.5, 2.7, and 6. Focus only on scientific correctness and test gaps. Verify invalid/cloud pixels cannot create false dry months, missing/duplicate months are strict by default, unsupported climate windows fail fast, gapfilled/completed series are recommended, and at least one synthetic or golden catchment test proves expected boundary detection. Return findings first with file/line references and exact missing tests.
```

### Task G - docs rewrite

**Model:** `claude sonnet`

**Prompt:**
```text
Rewrite README.md, docs/, mkdocs.yml nav, CHANGELOG.md, CITATION.cff, and examples per docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md sections 0, 0.1, 2.8, 4, and 5. Remove current rainfall workflow promises from main docs. Document the three supported input paths: extent CSV, generic binary/canonical rasters, and WOfS/STAC. Strongly advise users to run WaterMask-TSFill gapfilling before applying hydroseason to incomplete/raw masks. Explain that rainfall implementation lives on legacy/rainfall. Keep docs concise and ensure mkdocs build --strict passes.
```

### Task H - final integration review

**Model:** `gpt-5.6`

**Prompt:**
```text
Perform a final review of the branch implementing docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md. Review as a blocking code/package/science gate, not style polish. Check public API, dependency extras, package entry points, docs coherence, Dask laziness, invalid coverage handling, missing/duplicate month behavior, source provenance, zarr pin, and legacy rainfall preservation. Run the verification commands if possible. Return only findings ordered by severity, then a short pass/fail recommendation.
```

### Task I - final commit

**Model:** `gpt-5.5`

**Prompt:**
```text
After all tests/docs/package gates are green and final review blockers are resolved, create small logical commits for the migration described in docs/plans/2026-07-13-migrate-wofs-hydroyear-from-watermask.md. Do not push. Use a breaking-change commit message for the public API pivot. Include the legacy rainfall branch/tag SHA and WaterMask-TSFill source SHA in the final handoff.
```

---

## Appendix — exact source file references (WaterMask-TSFill)

| Concept | Source path | Lines |
|---|---|---|
| Hydro-year detection core (→ new `hydroseason/hydro_year.py`) | `watermask_tsfill/hydro_year.py` | 325 |
| Duplicate-month helper (inline or → new `hydroseason/io.py`) | `watermask_tsfill/io/loaders.py` | `_handle_duplicate_months` L172-194; `DuplicateMonthPolicy` L11 |
| STAC/WOfS loader (→ new `hydroseason/io.py`) | `watermask_tsfill/io/loaders.py` | `load_wofs_from_stac` L601 |
| Generic binary-raster loader (→ new `hydroseason/io.py`, generalize classifier) | `watermask_tsfill/io/loaders.py` | `load_monthly_masks` L388-500 |
| Zarr cube loader (→ new `hydroseason/io.py`) | `watermask_tsfill/io/loaders.py` | `load_monthly_masks_zarr` L694 |
| AOI loader and minimal AOI masking helpers (→ new `hydroseason/io.py`) | `watermask_tsfill/io/loaders.py` | `load_aoi` L213; `_inside_aoi_mask_like`; `mark_in_aoi_nodata_as_invalid`; AOI/georef errors and transform helpers used by those functions |
| Monthly-axis completion (→ new `hydroseason/io.py`) | `watermask_tsfill/io/loaders.py` | `complete_monthly_axis` L249 |
| Detection-core tests (→ replaces `tests/test_hydro_year.py`) | `tests/test_hydro_year.py` | — |
| Dependency version floors to reconcile | `pyproject.toml` | `xarray>=2024.1`, `rioxarray>=0.15`, `rasterio>=1.4`, `geopandas>=1.0`, `dask[complete]>=2024.1`, `zarr>=2.0,<3.0`, `pystac-client>=0.8`, `odc-stac>=0.3` |
| Report design references only, NOT ported (deferred, §5.2) | `watermask_tsfill/reporting/martuwarra_pools.py` + `figures.py` + `html.py`; and this repo's own (pre-strip) `hydroseason/report.py` + `plot.py` | ~550 + helpers; 1385 + 1016 |

Public functions being ported/exported (names preserved, no prefix on `main`): `monthly_water_extent`, `detect_hydrological_years`, `label_hydrological_months`, `HydroYearConfig`, plus the new loader set: `load_aoi`, `load_wofs_from_stac`, `load_monthly_masks`, `load_monthly_masks_zarr`, `load_extent_csv` (new), `complete_monthly_axis`. `ValidationSeasonConfig` is not exported until a real water-mask validation module exists.
