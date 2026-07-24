# Performance Optimization Design: Full Optimization Bundle

Date: 2026-07-24

## Overview
This specification details a 3-part performance optimization bundle for WOfS water extent time series calculations in `hydroseason`. It targets the high per-year runtime (~268s-734s/year) caused by redundant spatial mask allocations, deep nested Dask graph expressions, and uncached wet-AOI precomputing passes.

## Proposed Changes

### 1. Static Spatial AOI Reduction & Single-Pass Monthly Extent
**Location:** [hydro_year.py](file:///d:/RLH/5.6/repos/hydroseason/hydroseason/hydro_year.py#L225-L287)

- **Static Spatial Precomputation:**
  - Compute `n_aoi_spatial = (water_mask.isel(time=0) != -2).sum(dim=("y", "x"))` once before the monthly loop. Because spatial boundaries (`outside_value = -2`) are constant over time across all months, `n_aoi` is time-invariant.
  - If `wet_aoi` is supplied, rasterize `inside_wet` spatial mask once on `isel(time=0)`.

- **Optimized Monthly Block Loop:**
  - For each time block, compute `n_water_block = (block == 1).sum(dim=("y", "x"))`.
  - Compute `n_invalid_block = (block == -1).sum(dim=("y", "x"))`.
  - Derive `n_valid_block = n_aoi_spatial - n_invalid_block`.
  - Derive `n_dry_block = n_valid_block - n_water_block`.
  - If `inside_wet` is present, evaluate `n_wet_aoi_block = ((block != -2) & inside_wet).sum(dim=("y", "x"))`.

- **Impact:** Eliminates 3D boolean allocations for `outside_value` and `dry_value` per month. Reduces Dask graph size by ~60% and cuts memory overhead per chunk.

### 2. Dask Graph Simplification in Monthly Compositing
**Location:** [_io_geo.py](file:///d:/RLH/5.6/repos/hydroseason/hydroseason/_io_geo.py#L756-L763)

- **Flat Condition Evaluation in `_combine_observations`:**
  - Replace 3-nested `xr.where` calls:
    ```python
    water_wins = (water > 0) & ((water > dry) if majority else True)
    combined = xr.where(
        water_wins, np.int8(1),
        xr.where(dry > 0, np.int8(0), xr.where(invalid > 0, np.int8(-1), np.int8(-2)))
    )
    ```
  - Use `dask.array.select` / `np.select` or direct 2-stage boolean assignment on raw arrays to avoid deep `xr.where` graph nesting.

- **Impact:** Reduces Dask graph complexity and avoids allocating 3 nested intermediate DataArrays per monthly composite.

### 3. Persistent Wet-AOI Disk Cache
**Location:** [_io_extent_cache.py](file:///d:/RLH/5.6/repos/hydroseason/hydroseason/_io_extent_cache.py#L465-L487)

- **Disk Sidecar Persistence:**
  - When `precompute_wet_aoi=True` derives `wet_aoi`, write the resulting GeoDataFrame to a sidecar file (e.g., `wet_aoi.geojson`) inside `cache_dir`.
- **Cache Lookup:**
  - On entry to `load_wofs_monthly_extent`, check if `wet_aoi.geojson` exists for the request identity.
  - If found, load `wet_aoi` from disk without executing the multi-year STAC read pass.

- **Impact:** Instant skip of the expensive `load_wofs_from_stac` precompute pass on repeat runs.

## Verification Plan

### Automated Tests
- Run `pytest` across existing test suite:
  - `tests/test_hydro_year.py`
  - `tests/test_io.py`
  - `tests/test_io_extent_cache.py`
  - `tests/test_extract_water_extent_csv.py`
- Ensure bit-identical output values for `n_water`, `n_valid`, `n_aoi`, `n_invalid`, `extent_pct`, `wet_fill_pct`.

### Performance Benchmark
- Run `python scripts/extract_water_extent_csv.py --only gilbert_river_qld --profile` to verify runtime reduction per year.
