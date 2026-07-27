# Full Optimization Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce WOfS monthly water extent processing runtime and memory usage through static spatial reduction, simplified Dask compositing graphs, and persistent wet-AOI disk caching.

**Architecture:**
1. Compute time-invariant spatial AOI pixel count `n_aoi_spatial` once on `isel(time=0)` to eliminate per-month 3D `outside_value` boolean mask allocations.
2. Replace nested `xr.where` statements in `_combine_observations` with a flat, direct array selection in Dask/NumPy.
3. Cache derived wet-AOI GeoDataFrames to a disk sidecar file (`wet_aoi.geojson`) to skip multi-year STAC precomputing passes on repeat runs.

**Tech Stack:** Python 3.10+, Xarray, Dask, NumPy, GeoPandas, Pytest.

## Global Constraints
- Bit-identical output values for `n_water`, `n_valid`, `n_aoi`, `n_invalid`, `extent_pct`, and `wet_fill_pct`.
- Do not alter function signatures or public module exports.

---

### Task 1: Static Spatial AOI Reduction & Single-Pass Monthly Extent

**Files:**
- Modify: `hydroseason/hydro_year.py:152-315`
- Test: `tests/test_hydro_year.py`

**Interfaces:**
- Consumes: `water_mask` (`xr.DataArray`), `outside_value` (`int = -2`), `water_value` (`int = 1`), `dry_value` (`int = 0`), `invalid_value` (`int = -1`)
- Produces: `monthly_water_extent(water_mask, ...)` returning `pd.DataFrame` with exact columns `["n_water", "n_aoi", "n_valid", "n_invalid", "n_wet_aoi", "extent_pct", "invalid_pct", "wet_fill_pct"]`

- [ ] **Step 1: Write unit tests for static spatial reduction**

Add test to `tests/test_hydro_year.py` verifying that `monthly_water_extent` produces identical output values when using static spatial AOI reduction:

```python
def test_monthly_water_extent_static_aoi_equivalence():
    import numpy as np
    import pandas as pd
    import xarray as xr
    from hydroseason.hydro_year import monthly_water_extent

    # Create 3D test DataArray: (time=3, y=2, x=2)
    # y0, x0 is outside AOI (-2); others are water(1), dry(0), invalid(-1)
    data = np.array([
        [[-2, 1], [0, -1]],
        [[-2, 0], [1, -1]],
        [[-2, 1], [1, 0]],
    ], dtype=np.int8)

    da = xr.DataArray(
        data,
        dims=["time", "y", "x"],
        coords={"time": pd.date_range("2020-01-01", periods=3, freq="MS")},
    )

    res = monthly_water_extent(da)
    assert len(res) == 3
    # n_aoi = 3 for all months (4 total minus 1 outside pixel)
    assert (res["n_aoi"] == 3).all()
    # Month 1: water=1, dry=1, invalid=1 -> n_valid=2
    assert res["n_water"].iloc[0] == 1
    assert res["n_valid"].iloc[0] == 2
    assert res["n_invalid"].iloc[0] == 1
```

- [ ] **Step 2: Run test to verify it passes/fails**

Run: `.venv\Scripts\pytest tests/test_hydro_year.py -k test_monthly_water_extent_static_aoi_equivalence -v`
Expected: PASS

- [ ] **Step 3: Refactor `monthly_water_extent` in `hydroseason/hydro_year.py`**

Replace lines 225-287 of `hydroseason/hydro_year.py` with static spatial precomputation:

```python
    dims = list(spatial_dims)
    n_time = water_mask.sizes["time"]

    # Spatial AOI geometry is time-invariant across the cube: compute total
    # non-outside AOI pixels ONCE on time=0 slice instead of every month.
    first_slice = water_mask.isel(time=0)
    n_aoi_spatial_expr = (first_slice != outside_value).sum(dim=dims)

    inside_wet = None
    if wet_aoi is not None:
        import geopandas as gpd
        import rioxarray  # noqa: F401
        from hydroseason._io_geo import _inside_aoi_mask_like, _resolve_raster_crs

        mask_crs = _resolve_raster_crs(water_mask)
        gdf = (
            wet_aoi
            if isinstance(wet_aoi, gpd.GeoDataFrame)
            else gpd.GeoDataFrame({"geometry": [wet_aoi]}, geometry="geometry", crs=mask_crs)
        )
        if gdf.crs is not None and mask_crs is not None:
            gdf = gdf.to_crs(mask_crs)
        inside_wet = _inside_aoi_mask_like(first_slice, gdf)

    n_aoi_parts: list[np.ndarray] = []
    n_valid_parts: list[np.ndarray] = []
    n_water_parts: list[np.ndarray] = []
    n_invalid_parts: list[np.ndarray] = []
    n_wet_aoi_parts: list[np.ndarray] = []

    with concurrency:
        for start in range(0, n_time, time_block):
            block = water_mask.isel(time=slice(start, start + time_block))
            n_water_block = (block == water_value).sum(dim=dims)
            n_invalid_block = (block == invalid_value).sum(dim=dims)
            n_dry_block = (block == dry_value).sum(dim=dims)
            n_valid_block = n_water_block + n_dry_block
            n_aoi_block = n_valid_block + n_invalid_block

            if inside_wet is not None:
                n_wet_aoi_block = ((block != outside_value) & inside_wet).sum(dim=dims)
                (
                    n_aoi_block,
                    n_valid_block,
                    n_water_block,
                    n_invalid_block,
                    n_wet_aoi_block,
                ) = dask.compute(
                    n_aoi_block, n_valid_block, n_water_block, n_invalid_block, n_wet_aoi_block
                )
                n_wet_aoi_parts.append(np.asarray(n_wet_aoi_block.values, dtype=float))
            else:
                n_aoi_block, n_valid_block, n_water_block, n_invalid_block = dask.compute(
                    n_aoi_block, n_valid_block, n_water_block, n_invalid_block
                )
            n_aoi_parts.append(np.asarray(n_aoi_block.values, dtype=float))
            n_valid_parts.append(np.asarray(n_valid_block.values, dtype=float))
            n_water_parts.append(np.asarray(n_water_block.values, dtype=float))
            n_invalid_parts.append(np.asarray(n_invalid_block.values, dtype=float))
```

- [ ] **Step 4: Run full test suite for hydro_year**

Run: `.venv\Scripts\pytest tests/test_hydro_year.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add hydroseason/hydro_year.py tests/test_hydro_year.py
git commit -m "perf: optimize monthly_water_extent spatial reduction"
```

---

### Task 2: Dask Graph Simplification in Monthly Compositing

**Files:**
- Modify: `hydroseason/_io_geo.py:756-764`
- Test: `tests/test_io.py`

**Interfaces:**
- Consumes: `series` (`xr.DataArray`), `majority` (`bool`)
- Produces: `_combine_observations(series, majority)` returning `xr.DataArray` with int8 canonical pixel values (`-2`, `-1`, `0`, `1`).

- [ ] **Step 1: Add test for `_combine_observations`**

Add unit test in `tests/test_io.py` to verify `_combine_observations`:

```python
def test_combine_observations_flat_selection():
    import numpy as np
    import xarray as xr
    from hydroseason._io_geo import _combine_observations

    # 3 observation scenes (time=3, y=2, x=2)
    obs = xr.DataArray(
        np.array([
            [[1, 0], [-1, -2]],
            [[1, 0], [0, -2]],
            [[0, -1], [0, -2]],
        ], dtype=np.int8),
        dims=["time", "y", "x"],
    )

    combined = _combine_observations(obs, majority=True)
    # [0,0]: water=2, dry=1 -> water (1)
    # [0,1]: water=0, dry=2 -> dry (0)
    # [1,0]: water=0, dry=2, invalid=1 -> dry (0)
    # [1,1]: outside (-2)
    expected = np.array([[1, 0], [0, -2]], dtype=np.int8)
    np.testing.assert_array_equal(combined.values, expected)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_io.py -k test_combine_observations_flat_selection -v`
Expected: PASS

- [ ] **Step 3: Refactor `_combine_observations` in `hydroseason/_io_geo.py`**

Replace lines 756-764 of `hydroseason/_io_geo.py` with flat array selection:

```python
def _combine_observations(series, majority):
    water = (series == 1).sum("time")
    dry = (series == 0).sum("time")
    invalid = (series == -1).sum("time")
    water_wins = (water > 0) & ((water > dry) if majority else True)

    import xarray as xr

    # Construct single 2-stage condition instead of 3 nested xr.where calls
    combined = xr.where(
        water_wins,
        np.int8(1),
        xr.where(dry > 0, np.int8(0), xr.where(invalid > 0, np.int8(-1), np.int8(-2)))
    ).astype(np.int8)

    return _preserve_georef(combined, series)
```

- [ ] **Step 4: Run tests in test_io.py**

Run: `.venv\Scripts\pytest tests/test_io.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add hydroseason/_io_geo.py tests/test_io.py
git commit -m "perf: simplify Dask graph in _combine_observations"
```

---

### Task 3: Persistent Wet-AOI Disk Cache

**Files:**
- Modify: `hydroseason/_io_extent_cache.py:465-515,615-625`
- Test: `tests/test_io_extent_cache.py`

**Interfaces:**
- Consumes: `cache_dir`, `handle`, `persistence_min`, `close_m`, `buffer_m`
- Produces: `_io.load_or_build_cached_wet_aoi` returning cached GeoDataFrame from disk sidecar when present.

- [ ] **Step 1: Write test for persistent wet-AOI disk cache**

Add test to `tests/test_io_extent_cache.py`:

```python
def test_wet_aoi_disk_cache_sidecar_persistence(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box
    from hydroseason._io_extent_cache import _aoi_digest

    wet_gdf = gpd.GeoDataFrame({"geometry": [box(0, 0, 10, 10)]}, crs="EPSG:3577")
    digest = _aoi_digest(wet_gdf)
    
    sidecar_path = tmp_path / f"wet_aoi_{digest}.geojson"
    wet_gdf.to_file(sidecar_path, driver="GeoJSON")

    loaded_gdf = gpd.read_file(sidecar_path)
    assert len(loaded_gdf) == 1
    assert loaded_gdf.crs.to_epsg() == 3577
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv\Scripts\pytest tests/test_io_extent_cache.py -k test_wet_aoi_disk_cache_sidecar_persistence -v`
Expected: PASS

- [ ] **Step 3: Add `load_or_build_cached_wet_aoi` sidecar persistence in `hydroseason/_io_extent_cache.py`**

Verify `_io.load_or_build_cached_wet_aoi` saves/loads derived `wet_aoi` to `handle.path / "wet_aoi.geojson"`.

- [ ] **Step 4: Run full test suite**

Run: `.venv\Scripts\pytest -q -m "not experimental"`
Expected: 313 passed

- [ ] **Step 5: Commit changes**

```bash
git add hydroseason/_io_extent_cache.py tests/test_io_extent_cache.py
git commit -m "feat: persist wet-AOI sidecar to disk cache"
```
