# Native WOfS Spatial Tiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract exact monthly WOfS counts for whole catchments at 30 m while bounding memory and Dask graph size with non-overlapping Albers pixel tiles.

**Architecture:** Keep the existing one-search-per-catchment-year boundary. Refactor the STAC loader so one item list can be reused, derive one EPSG:3577 output `GeoBox`, slice it into aligned `1024 x 1024` pixel windows, load and reduce one window at a time, then sum integer counts and recompute percentages. Annual CSV caches remain method-independent; partial tile CSVs make interrupted years resumable.

**Tech Stack:** Python, pandas, NumPy, xarray, Dask, GeoPandas/Shapely, `odc-stac`, `odc-geo`, rioxarray, pytest.

## Global Constraints

- Default output CRS is EPSG:3577 (Australian Albers).
- Default resolution for the catchment CSV command is exactly 30 m.
- Default tile edge is 1024 pixels (30.72 km at 30 m).
- Query STAC exactly once for each catchment/year, never once per tile.
- Reuse the same annual STAC item list for every tile in that year.
- Tiles are slices of one parent `GeoBox`; they never overlap and leave no gaps.
- Canonical pixel values are `1=water`, `0=dry`, `-1=invalid inside AOI`, and `-2=outside AOI`.
- Pixels outside the AOI contribute to no count, including `n_invalid` and `n_aoi`.
- For every month, enforce `n_aoi == n_valid + n_invalid`.
- Sum `n_water`, `n_valid`, `n_invalid`, and `n_aoi`; never sum percentages.
- Compute `extent_pct = 100 * n_water / n_valid` only when `n_valid > 0`.
- Compute `invalid_pct = 100 * n_invalid / n_aoi` only when `n_aoi > 0`.
- A year with no STAC items produces all requested months with zero counts and `NaN` percentages, then processing continues.
- Existing complete annual caches remain reusable because tiling changes execution, not results.
- No test may require live DEA network access; real-data validation is an explicit smoke test.

---

## File Map

- Modify `hydroseason/_io_geo.py`: separate annual STAC search from item loading and add aligned tiled-mask iteration.
- Modify `hydroseason/_io_extent_cache.py`: cache tile reductions, aggregate integer counts, and retain annual cache behavior.
- Modify `hydroseason/io.py`: re-export the internal tiling seam needed by tests and the cache orchestrator.
- Modify `scripts/build_real_extent_fixture.py`: expose native resolution and tile size through the CLI.
- Modify `tests/test_io.py`: cover one-search item reuse, aligned non-overlapping windows, and AOI masking.
- Modify `tests/test_io_extent_cache.py`: cover tile resume, exact count aggregation, empty years, and cache compatibility.
- Modify `tests/test_real_fixture_builder.py`: cover CLI/build propagation of 30 m and 1024-pixel tiling.

---

### Task 1: Make Annual STAC Items Reusable

**Files:**
- Modify: `hydroseason/_io_geo.py`
- Modify: `hydroseason/io.py`
- Test: `tests/test_io.py`

**Interfaces:**
- Produces: `_query_wofs_items(stac_url, collection, aoi, start_date, end_date) -> tuple[list, GeoDataFrame]`
- Produces: `_load_wofs_items(items, aoi_gdf, start_date, end_date, *, crs, resolution, geobox, chunk_x, chunk_y, time_chunk, majority, duplicate_month_policy) -> xarray.DataArray`
- Preserves: the existing public `load_wofs_from_stac` signature and `xarray.DataArray` return value.

- [ ] **Step 1: Add a failing test proving the wrapper searches once and delegates the returned items**

Add to `tests/test_io.py`:

```python
def test_stac_wrapper_queries_once_and_loads_the_returned_items(monkeypatch):
    from unittest.mock import Mock

    pytest.importorskip("xarray")
    pytest.importorskip("dask")
    pytest.importorskip("pystac_client")
    pytest.importorskip("odc.stac")
    pytest.importorskip("rioxarray")
    import hydroseason._io_geo as geo

    items = [object(), object()]
    query = Mock(return_value=(items, _aoi()))
    loaded = object()
    load_items = Mock(return_value=loaded)
    monkeypatch.setattr(geo, "_query_wofs_items", query)
    monkeypatch.setattr(geo, "_load_wofs_items", load_items)

    result = geo.load_wofs_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2020-02-29", crs=3577, resolution=30,
    )

    query.assert_called_once()
    assert load_items.call_args.args[0] is items
    assert load_items.call_args.kwargs["geobox"] is None
    assert result is loaded
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest tests\test_io.py::test_stac_wrapper_queries_once_and_loads_the_returned_items -q
```

Expected: FAIL because `_query_wofs_items` and `_load_wofs_items` do not exist.

- [ ] **Step 3: Extract search and item-loading helpers without changing behavior**

In `hydroseason/_io_geo.py`:

```python
def _query_wofs_items(stac_url, collection, aoi, start_date, end_date):
    import pystac_client

    aoi_gdf = load_aoi(aoi)
    aoi_4326 = aoi_gdf.to_crs("EPSG:4326")
    client = pystac_client.Client.open(stac_url)
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    items = _collect_stac_items(
        client,
        collections=[collection],
        datetime=f"{start:%Y-%m-%d}/{end:%Y-%m-%d}",
        bbox=list(aoi_4326.total_bounds),
    )
    if not items:
        raise ValueError("No STAC items found for requested AOI and date range.")
    return items, aoi_gdf
```

Move the existing grouping, `stac_load`, classification, monthly composition, AOI clipping, monthly-axis completion, and rechunking code into:

```python
def _load_wofs_items(
    items,
    aoi_gdf,
    start_date,
    end_date,
    *,
    crs=3577,
    resolution=None,
    geobox=None,
    chunk_x=512,
    chunk_y=512,
    time_chunk=24,
    majority=True,
    duplicate_month_policy="raise",
):
    import xarray as xr
    import odc.stac
    import hydroseason.io as _io

    groups = {}
    for item in items:
        date = pd.Timestamp(
            item.properties.get("datetime")
            or item.properties.get("start_datetime")
        )
        if date.tzinfo is not None:
            date = date.tz_convert(None)
        groups.setdefault(date.to_period("M").to_timestamp(), []).append(item)

    annual_groups = {}
    for month, month_items in sorted(groups.items()):
        annual_groups.setdefault(month.year, []).append((month, month_items))

    target = aoi_gdf.to_crs(_crs_value(crs)) if crs is not None else aoi_gdf
    masks, dates, reference = [], [], None
    for year, year_groups in sorted(annual_groups.items()):
        year_items = [item for _month, month_items in year_groups for item in month_items]
        spatial = {"geobox": geobox} if geobox is not None else {
            "geopolygon": target.geometry,
            **({"crs": _crs_value(crs)} if crs is not None else {}),
            **({"resolution": resolution} if resolution is not None else {}),
        }
        ds = odc.stac.stac_load(
            year_items,
            bands=["water"],
            chunks={"x": chunk_x, "y": chunk_y},
            **({"resampling": "mode"} if resolution is not None else {}),
            **spatial,
        )
        classified = _classify(ds["water"], "wofs", None)
        loaded_months = pd.DatetimeIndex(classified["time"].values).to_period("M")

        for month, _month_items in year_groups:
            indices = np.flatnonzero(loaded_months == month.to_period("M"))
            if not len(indices):
                raise ValueError(f"loaded STAC batch has no observations for {month:%Y-%m}")
            observations = classified.isel(time=indices)
            mask = _combine_observations(observations, majority)
            mask = _io._clip_to_aoi(mask, target)
            if reference is not None:
                _assert_compatible_georef(reference, mask, context=f"month {month:%Y-%m}")
            reference = mask if reference is None else reference
            masks.append(mask)
            dates.append(month)

    completed = complete_monthly_axis(
        xr.concat(masks, dim="time").assign_coords(time=("time", dates)),
        start_date,
        end_date,
        duplicate_month_policy=duplicate_month_policy,
    )
    return completed.chunk({
        "time": min(time_chunk, completed.sizes["time"]),
        "x": chunk_x,
        "y": chunk_y,
    })
```

Retain the current `AOIRasterizationError` exception boundaries around annual loading and monthly clipping when moving this body; the code above specifies the data flow, while the existing exception messages remain unchanged.

Build `stac_load` spatial arguments exactly as follows so tiled calls use only their supplied grid:

```python
spatial = {"geobox": geobox} if geobox is not None else {
    "geopolygon": target.geometry,
    **({"crs": _crs_value(crs)} if crs is not None else {}),
    **({"resolution": resolution} if resolution is not None else {}),
}
ds = odc.stac.stac_load(
    year_items,
    bands=["water"],
    chunks={"x": chunk_x, "y": chunk_y},
    **({"resampling": "mode"} if resolution is not None else {}),
    **spatial,
)
```

Keep `load_wofs_from_stac` as a compatibility wrapper that imports optional dependencies, sets `AWS_NO_SIGN_REQUEST`, calls `_query_wofs_items` once, and passes the returned objects to `_load_wofs_items` with `geobox=None`.

- [ ] **Step 4: Re-export the two helpers through the facade**

Add `_query_wofs_items` and `_load_wofs_items` to the `_io_geo` import block in `hydroseason/io.py`. They remain private and do not enter `__all__`.

- [ ] **Step 5: Run focused and existing STAC loader tests**

Run:

```powershell
python -m pytest tests\test_io.py -k "stac_loader or stac_wrapper" -q
```

Expected: PASS; the existing annual batching, resolution, retry, and AOI tests remain green.

- [ ] **Step 6: Commit the reusable-item refactor**

```powershell
git add hydroseason\_io_geo.py hydroseason\io.py tests\test_io.py
git commit -m "refactor: reuse annual STAC items"
```

---

### Task 2: Generate Exact Albers Pixel Tiles

**Files:**
- Modify: `hydroseason/_io_geo.py`
- Modify: `hydroseason/io.py`
- Test: `tests/test_io.py`

**Interfaces:**
- Consumes: `_query_wofs_items` and `_load_wofs_items` from Task 1.
- Produces: `_tile_slices(shape: tuple[int, int], tile_pixels: int) -> Iterator[tuple[str, slice, slice]]`
- Produces: `iter_wofs_tiles_from_stac` with required keyword arguments `resolution: float`, `tile_pixels: int`, and optional `skip_tile_ids: Collection[str] = ()`; returns `Iterator[tuple[str, DataArray]]`.

- [ ] **Step 1: Add failing tests for complete, non-overlapping pixel coverage**

Add to `tests/test_io.py`:

```python
def test_tile_slices_cover_parent_once_without_overlap():
    from hydroseason.io import _tile_slices

    coverage = np.zeros((2050, 1030), dtype=np.uint8)
    tiles = list(_tile_slices(coverage.shape, 1024))
    for _tile_id, ys, xs in tiles:
        coverage[ys, xs] += 1

    assert len(tiles) == 6
    assert coverage.min() == 1
    assert coverage.max() == 1
    assert tiles[-1] == ("r0002_c0001", slice(2048, 2050), slice(1024, 1030))


@pytest.mark.parametrize("tile_pixels", [0, -1])
def test_tile_slices_reject_non_positive_edge(tile_pixels):
    from hydroseason.io import _tile_slices

    with pytest.raises(ValueError, match="tile_pixels"):
        list(_tile_slices((100, 100), tile_pixels))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests\test_io.py -k "tile_slices" -q
```

Expected: FAIL because `_tile_slices` is not defined.

- [ ] **Step 3: Implement deterministic pixel slices**

Add to `hydroseason/_io_geo.py`:

```python
def _tile_slices(shape, tile_pixels):
    if tile_pixels < 1:
        raise ValueError("tile_pixels must be at least 1.")
    height, width = shape
    for row, y0 in enumerate(range(0, height, tile_pixels)):
        for column, x0 in enumerate(range(0, width, tile_pixels)):
            yield (
                f"r{row:04d}_c{column:04d}",
                slice(y0, min(y0 + tile_pixels, height)),
                slice(x0, min(x0 + tile_pixels, width)),
            )
```

- [ ] **Step 4: Add a failing orchestration test proving one query and skipped-tile resume**

Add a test that supplies a fake parent geobox supporting `shape`, slicing, and `extent`, patches `odc.stac.parse_items`/`output_geobox`, and patches `_load_wofs_items`:

```python
def test_tiled_stac_iterator_queries_once_reuses_items_and_skips_cached_tiles(monkeypatch):
    from unittest.mock import Mock

    import hydroseason._io_geo as geo

    class FakeGeoBox:
        def __init__(self, shape, origin=(0, 0)):
            self.shape = shape
            self.origin = origin

        def __getitem__(self, roi):
            ys, xs = roi
            return FakeGeoBox(
                (ys.stop - ys.start, xs.stop - xs.start),
                (ys.start, xs.start),
            )

    items = [object(), object()]
    parent = FakeGeoBox(shape=(2048, 2048))
    query = Mock(return_value=(items, _aoi()))
    load_items = Mock(return_value="mask")
    monkeypatch.setattr(geo, "_query_wofs_items", query)
    monkeypatch.setattr(geo, "_output_geobox_for_aoi", Mock(return_value=parent))
    monkeypatch.setattr(geo, "_tile_intersects_aoi", Mock(return_value=True))
    monkeypatch.setattr(geo, "_load_wofs_items", load_items)

    result = list(geo.iter_wofs_tiles_from_stac(
        "https://example.invalid/stac", "wofs", _aoi(),
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=1024,
        skip_tile_ids={"r0000_c0001"},
    ))

    query.assert_called_once()
    assert [tile_id for tile_id, _mask in result] == [
        "r0000_c0000", "r0001_c0000", "r0001_c0001",
    ]
    assert load_items.call_count == 3
    assert all(call.args[0] is items for call in load_items.call_args_list)
    assert all(call.kwargs["geobox"] is not None for call in load_items.call_args_list)
```

The local `FakeGeoBox` deliberately implements only `shape` and slicing because `_tile_intersects_aoi` is patched in this unit test.

- [ ] **Step 5: Run the orchestration test and verify RED**

Run:

```powershell
python -m pytest tests\test_io.py::test_tiled_stac_iterator_queries_once_reuses_items_and_skips_cached_tiles -q
```

Expected: FAIL because the tiled iterator does not exist.

- [ ] **Step 6: Implement parent GeoBox creation and tile iteration**

In `hydroseason/_io_geo.py`, create the parent grid from parsed annual items:

```python
def _output_geobox_for_aoi(items, target, *, crs, resolution):
    import odc.stac

    parsed = list(odc.stac.parse_items(items))
    geobox = odc.stac.output_geobox(
        parsed,
        crs=_crs_value(crs),
        resolution=resolution,
        geopolygon=target.geometry,
    )
    if geobox is None:
        raise AOIRasterizationError("Cannot derive an output GeoBox for the AOI.")
    return geobox
```

Reject `resolution is None` in tiled mode. For every slice from `_tile_slices(parent.shape, tile_pixels)`, obtain `tile_geobox = parent[ys, xs]`, skip tiles whose extent does not intersect the AOI, skip IDs in `skip_tile_ids`, then call `_load_wofs_items` with the same item list and `geobox=tile_geobox`.

At iterator entry, import the same optional raster/STAC dependencies as `load_wofs_from_stac` and call `os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")` before any lazy S3 reads are created.

Use a Shapely box in the Albers CRS for the cheap intersection test:

```python
def _tile_intersects_aoi(tile_geobox, target):
    from shapely.geometry import box

    bounds = tile_geobox.extent.boundingbox
    tile_polygon = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
    return bool(target.to_crs(tile_geobox.crs).geometry.intersects(tile_polygon).any())
```

Do not intersect the AOI polygon to create a new load geometry. `_load_wofs_items` must clip the full tile against the original AOI so canonical `-2` and `-1` semantics remain centralized.

- [ ] **Step 7: Re-export the tiling seams and run tests**

Add `_tile_slices` and `iter_wofs_tiles_from_stac` to the private import block in `hydroseason/io.py`, then run:

```powershell
python -m pytest tests\test_io.py -k "tile or stac" -q
```

Expected: PASS.

- [ ] **Step 8: Commit aligned tiling**

```powershell
git add hydroseason\_io_geo.py hydroseason\io.py tests\test_io.py
git commit -m "feat: load WOfS in aligned Albers tiles"
```

---

### Task 3: Aggregate Tile Counts with Strict AOI Semantics

**Files:**
- Modify: `hydroseason/_io_extent_cache.py`
- Test: `tests/test_io_extent_cache.py`

**Interfaces:**
- Produces: `_aggregate_extent_parts(parts: Iterable[pd.DataFrame], index: pd.DatetimeIndex) -> pd.DataFrame`
- Guarantees: output columns remain `_EXTENT_COLUMNS` in their current order.

- [ ] **Step 1: Add a failing aggregation test with outside pixels excluded**

Add to `tests/test_io_extent_cache.py`:

```python
def test_tile_extent_aggregation_sums_counts_then_recomputes_percentages():
    from hydroseason._io_extent_cache import _aggregate_extent_parts

    index = pd.DatetimeIndex(["2020-01-01"])
    left = pd.DataFrame({
        "n_water": [3], "n_aoi": [8], "n_valid": [6], "n_invalid": [2],
        "extent_pct": [50.0], "invalid_pct": [25.0],
    }, index=index)
    right = pd.DataFrame({
        "n_water": [1], "n_aoi": [2], "n_valid": [2], "n_invalid": [0],
        "extent_pct": [50.0], "invalid_pct": [0.0],
    }, index=index)

    result = _aggregate_extent_parts([left, right], index)

    assert result.loc[index[0], "n_water"] == 4
    assert result.loc[index[0], "n_valid"] == 8
    assert result.loc[index[0], "n_invalid"] == 2
    assert result.loc[index[0], "n_aoi"] == 10
    assert result.loc[index[0], "extent_pct"] == 50.0
    assert result.loc[index[0], "invalid_pct"] == 20.0
    assert result.loc[index[0], "n_aoi"] == (
        result.loc[index[0], "n_valid"] + result.loc[index[0], "n_invalid"]
    )
```

This fixture deliberately represents only inside-AOI counts. Outside-AOI pixels are absent rather than encoded as invalid.

- [ ] **Step 2: Add a failing zero-denominator test**

```python
def test_tile_extent_aggregation_keeps_empty_month_percentages_nan():
    from hydroseason._io_extent_cache import _aggregate_extent_parts

    index = pd.DatetimeIndex(["2020-01-01"])
    result = _aggregate_extent_parts([], index)

    assert (result[["n_water", "n_aoi", "n_valid", "n_invalid"]] == 0).all().all()
    assert result[["extent_pct", "invalid_pct"]].isna().all().all()
```

- [ ] **Step 3: Run both tests and verify RED**

Run:

```powershell
python -m pytest tests\test_io_extent_cache.py -k "aggregation" -q
```

Expected: FAIL because `_aggregate_extent_parts` is missing.

- [ ] **Step 4: Implement count-only aggregation and invariants**

In `hydroseason/_io_extent_cache.py`:

```python
def _aggregate_extent_parts(parts, index):
    count_columns = ["n_water", "n_aoi", "n_valid", "n_invalid"]
    totals = pd.DataFrame(0, index=index, columns=count_columns, dtype="int64")
    for part in parts:
        aligned = part.reindex(index)
        totals = totals.add(aligned[count_columns].fillna(0).astype("int64"), fill_value=0)

    if not (totals["n_aoi"] == totals["n_valid"] + totals["n_invalid"]).all():
        raise ValueError("tile counts violate n_aoi == n_valid + n_invalid")

    extent_pct = np.full(len(totals), np.nan, dtype=float)
    invalid_pct = np.full(len(totals), np.nan, dtype=float)
    np.divide(
        totals["n_water"].to_numpy(dtype=float) * 100.0,
        totals["n_valid"].to_numpy(dtype=float),
        out=extent_pct,
        where=totals["n_valid"].to_numpy() > 0,
    )
    np.divide(
        totals["n_invalid"].to_numpy(dtype=float) * 100.0,
        totals["n_aoi"].to_numpy(dtype=float),
        out=invalid_pct,
        where=totals["n_aoi"].to_numpy() > 0,
    )
    totals["extent_pct"] = extent_pct
    totals["invalid_pct"] = invalid_pct
    return totals.loc[:, _EXTENT_COLUMNS]
```

Import NumPy as `np` in this module and do not relax the count invariant.

- [ ] **Step 5: Add a raster-level regression for outside versus invalid**

Add a canonical mask test using `monthly_water_extent` with values:

```python
values = np.array([[[-2, -2, -1], [0, 1, 1]]], dtype=np.int8)
```

Assert `n_water=2`, `n_valid=3`, `n_invalid=1`, `n_aoi=4`, `extent_pct=200/3`, and `invalid_pct=25`. This test is the explicit guard that outside-AOI `-2` pixels never enter any count.

- [ ] **Step 6: Run focused tests**

```powershell
python -m pytest tests\test_io_extent_cache.py -k "aggregation" -q
python -m pytest tests\test_io.py -k "outside or invalid" -q
```

Expected: PASS.

- [ ] **Step 7: Commit strict aggregation**

```powershell
git add hydroseason\_io_extent_cache.py tests\test_io_extent_cache.py tests\test_io.py
git commit -m "feat: aggregate tiled extent counts exactly"
```

---

### Task 4: Add Resumable Per-Tile Caching to Annual Extent Loading

**Files:**
- Modify: `hydroseason/_io_extent_cache.py`
- Test: `tests/test_io_extent_cache.py`

**Interfaces:**
- Extends: the existing `load_wofs_monthly_extent` signature with `tile_pixels: int | None = None`; return type remains `pd.DataFrame`.
- Consumes: `iter_wofs_tiles_from_stac`, passing the set of cached tile IDs through `skip_tile_ids`.
- Preserves: existing untiled path when `tile_pixels is None`.

- [ ] **Step 1: Add a failing test for tile caching and resume**

Use a fake tiled iterator that yields three canonical cubes and records `skip_tile_ids`:

```python
def test_tiled_extent_resume_skips_completed_tiles(monkeypatch, tmp_path):
    import hydroseason.io as hio

    calls = []
    fail_once = {"value": True}

    def fake_tiles(*args, skip_tile_ids=(), **kwargs):
        calls.append(set(skip_tile_ids))
        for tile_id in ["r0000_c0000", "r0000_c0001", "r0001_c0000"]:
            if tile_id in skip_tile_ids:
                continue
            if tile_id == "r0001_c0000" and fail_once["value"]:
                fail_once["value"] = False
                raise RuntimeError("interrupted")
            yield tile_id, _fake_monthly_cube("2020-01-01", "2020-12-01")

    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    kwargs = dict(
        stac_url="https://example.invalid/stac",
        collection="wofs",
        aoi=object(),
        start_date="2020-01-01",
        end_date="2020-12-31",
        cache_dir=tmp_path / "cache",
        crs=3577,
        resolution=30,
        tile_pixels=1024,
    )

    with pytest.raises(RuntimeError, match="interrupted"):
        hio.load_wofs_monthly_extent(**kwargs)
    result = hio.load_wofs_monthly_extent(**kwargs)

    assert calls[0] == set()
    assert calls[1] == {"r0000_c0000", "r0000_c0001"}
    assert (result["n_water"] == 12).all()
```

Adjust the final expected pixel count to the fake cube dimensions (`3 tiles * 4 water pixels = 12`).

- [ ] **Step 2: Run the resume test and verify RED**

```powershell
python -m pytest tests\test_io_extent_cache.py::test_tiled_extent_resume_skips_completed_tiles -q
```

Expected: FAIL because `tile_pixels` is not accepted.

- [ ] **Step 3: Include tiled mode in validation without invalidating annual caches**

Add `tile_pixels: int | None = None` to `load_wofs_monthly_extent`. Validate:

```python
if tile_pixels is not None:
    if tile_pixels < 1:
        raise ValueError("tile_pixels must be at least 1.")
    if resolution is None or resolution <= 0:
        raise ValueError("tiled loading requires a positive resolution.")
```

Do not add `tile_pixels` to `_cache_path` identity. A complete annual result is mathematically independent of tile shape and should reuse the current cache. Derive a partial cache directory from the annual cache path:

```python
tile_cache_dir = cache_path.parent / f"{cache_path.stem}_tiles_{tile_pixels}"
```

When no annual `cache_dir` was supplied, use no partial tile cache.

- [ ] **Step 4: Implement atomic tile reduction and resume**

For the tiled branch of each annual window:

1. Build the expected monthly index.
2. Read valid `*.csv` tile files with `_read_cached_extent`.
3. Pass their stems as `skip_tile_ids` to `iter_wofs_tiles_from_stac`.
4. Reduce every yielded mask immediately with `monthly_water_extent`.
5. Verify its index equals the expected annual index.
6. Write each tile frame atomically before requesting the next tile.
7. Aggregate cached and newly computed frames with `_aggregate_extent_parts`.
8. Write the existing complete annual cache atomically.

Use this control shape:

```python
tile_parts = {}
if tile_cache_dir is not None:
    for path in sorted(tile_cache_dir.glob("*.csv")):
        cached_tile = _read_cached_extent(path)
        if cached_tile is not None and cached_tile.index.equals(expected_index):
            tile_parts[path.stem] = cached_tile

tiles = _io.iter_wofs_tiles_from_stac(
    stac_url, collection, aoi,
    year_start.strftime("%Y-%m-%d"),
    year_end.strftime("%Y-%m-%d"),
    crs=crs,
    resolution=resolution,
    tile_pixels=tile_pixels,
    chunk_x=chunk_x,
    chunk_y=chunk_y,
    time_chunk=time_block,
    majority=majority,
    skip_tile_ids=set(tile_parts),
)
for tile_id, water_mask in tiles:
    tile_extent = monthly_water_extent(water_mask, time_block=time_block)
    if not tile_extent.index.equals(expected_index):
        raise ValueError(f"tile {tile_id} has an unexpected monthly index")
    if tile_cache_dir is not None:
        _write_extent_atomic(tile_extent, tile_cache_dir / f"{tile_id}.csv")
    tile_parts[tile_id] = tile_extent
extent = _aggregate_extent_parts(tile_parts.values(), expected_index)
```

Catch only `ValueError("No STAC items found for requested AOI and date range.")` and convert it with `_missing_year_extent`. Do not swallow tile read, raster, clipping, or aggregation failures.

- [ ] **Step 5: Add a failing test that no-data years continue in tiled mode**

Patch `iter_wofs_tiles_from_stac` to raise the existing no-items `ValueError` for 2020 and yield a valid cube for 2021. Assert 24 output months, zero/`NaN` values in 2020, and valid counts in 2021.

- [ ] **Step 6: Add a failing test that `force=True` ignores annual and tile caches**

Run tiled loading twice, then once with `force=True`. Assert the ordinary second call uses the annual cache and the forced call invokes the tile iterator with an empty `skip_tile_ids` set.

- [ ] **Step 7: Run extent-cache tests**

```powershell
python -m pytest tests\test_io_extent_cache.py -q
```

Expected: PASS, including existing untiled cache behavior and resolution invalidation.

- [ ] **Step 8: Commit resumable tiled loading**

```powershell
git add hydroseason\_io_extent_cache.py tests\test_io_extent_cache.py
git commit -m "feat: resume annual extent from tile caches"
```

---

### Task 5: Make the Catchment CLI Native and Tiled by Default

**Files:**
- Modify: `scripts/build_real_extent_fixture.py`
- Modify: `tests/test_real_fixture_builder.py`

**Interfaces:**
- Extends: `build` with keyword defaults `resolution: float = 30.0` and `tile_pixels: int = 1024`; return type remains `None`.
- Adds CLI: `--tile-pixels`, default `1024`
- Changes CLI default: `--resolution`, default `30.0`

- [ ] **Step 1: Add a failing propagation test**

Update the existing builder test to pass `resolution=30` and `tile_pixels=1024`, then assert:

```python
assert calls["crs"] == build_real_extent_fixture.DEA_ALBERS_CRS
assert calls["resolution"] == 30
assert calls["tile_pixels"] == 1024
```

- [ ] **Step 2: Add a failing parser-default test**

Extract parser construction to `build_parser() -> argparse.ArgumentParser`, then test:

```python
def test_cli_defaults_to_native_tiled_loading():
    args = build_real_extent_fixture.build_parser().parse_args([
        "--aoi", "data/catchments/example_boundary.geojson",
        "--output", "output/example.csv",
    ])
    assert args.resolution == 30.0
    assert args.tile_pixels == 1024
```

- [ ] **Step 3: Run builder tests and verify RED**

```powershell
python -m pytest tests\test_real_fixture_builder.py -q
```

Expected: FAIL because `tile_pixels` and `build_parser` do not exist.

- [ ] **Step 4: Implement CLI options and propagation**

Change the builder signature and loader call:

```python
def build(
    aoi_path: Path,
    output: Path,
    start: str,
    end: str,
    cache_dir: Path,
    *,
    resolution: float = 30.0,
    tile_pixels: int = 1024,
) -> None:
    aoi = load_aoi(aoi_path)
    extent = load_wofs_monthly_extent(
        "https://explorer.dea.ga.gov.au/stac",
        "ga_ls_wo_3",
        aoi,
        start,
        end,
        crs=DEA_ALBERS_CRS,
        resolution=resolution,
        tile_pixels=tile_pixels,
        cache_dir=cache_dir,
        time_block=12,
    )
    extent = add_provenance(
        extent,
        source="DEA Water Observations ga_ls_wo_3",
        aoi=aoi_path.as_posix(),
    )
    expected = pd.date_range(start, end, freq="MS")
    if not extent.index.equals(expected):
        raise RuntimeError("DEA fixture does not contain exactly one row per requested month")
    output.parent.mkdir(parents=True, exist_ok=True)
    extent.to_csv(output, date_format="%Y-%m-%d")
```

Define parser defaults:

```python
parser.add_argument("--resolution", type=float, default=30.0)
parser.add_argument(
    "--tile-pixels",
    type=int,
    default=1024,
    help="non-overlapping Albers tile edge in pixels (default: 1024)",
)
```

Keep `--start` and `--end` accepted as ISO dates. The production invocation remains explicit:

```powershell
python scripts\build_real_extent_fixture.py `
  --aoi data\catchments\example_boundary.geojson `
  --output output\water_extent_csv\example_monthly_extent_1986-01_2026-06.csv `
  --start 1986-01-01 `
  --end 2026-06-01 `
  --resolution 30 `
  --tile-pixels 1024 `
  --cache-dir output\real_extent_cache\example
```

- [ ] **Step 5: Run builder tests**

```powershell
python -m pytest tests\test_real_fixture_builder.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the CLI change**

```powershell
git add scripts\build_real_extent_fixture.py tests\test_real_fixture_builder.py
git commit -m "feat: default catchment extraction to tiled 30m"
```

---

### Task 6: Verify Exactness, Compatibility, and Practical Performance

**Files:**
- Modify only if a regression is found: files from Tasks 1-5
- Test: `tests/test_io.py`
- Test: `tests/test_io_extent_cache.py`
- Test: `tests/test_real_fixture_builder.py`

**Interfaces:**
- Verifies all public behavior; produces no new API.

- [ ] **Step 1: Add a synthetic equivalence test**

Construct one canonical 4-month raster with dimensions that force four tiles. Reduce it once as a whole and once by non-overlapping windows, aggregate tile frames, and assert exact frame equality:

```python
whole = monthly_water_extent(cube, time_block=2)
parts = [
    monthly_water_extent(cube.isel(y=ys, x=xs), time_block=2)
    for _tile_id, ys, xs in _tile_slices(cube.shape[-2:], 2)
]
tiled = _aggregate_extent_parts(parts, whole.index)
pd.testing.assert_frame_equal(tiled, whole)
```

The cube must contain all four canonical values and place `-2` and `-1` on tile boundaries. This proves exact global counts and inside/outside semantics independently of STAC mocking.

- [ ] **Step 2: Run the complete focused suite**

```powershell
python -m pytest tests\test_io.py tests\test_io_extent_cache.py tests\test_real_fixture_builder.py -q
```

Expected: all tests PASS with no warnings introduced by this feature.

- [ ] **Step 3: Inspect the diff for accidental scope**

```powershell
git diff --check
git diff --stat
git status --short
```

Expected: no whitespace errors; only the files listed in this plan are part of the feature. Preserve unrelated user changes.

- [ ] **Step 4: Run a bounded real DEA smoke test**

Use one existing catchment boundary and a two-month range at 30 m:

```powershell
python scripts\build_real_extent_fixture.py `
  --aoi data\catchments\daly_river_nt_boundary.geojson `
  --output output\water_extent_csv\daly_river_nt_smoke_30m.csv `
  --start 2020-01-01 `
  --end 2020-02-01 `
  --resolution 30 `
  --tile-pixels 1024 `
  --cache-dir output\real_extent_cache\daly_river_nt_smoke_30m
```

Expected:

- One STAC search for the requested year.
- Multiple sequential tile loads, each no larger than `1024 x 1024` pixels.
- Two CSV rows.
- For each row, `n_aoi == n_valid + n_invalid`.
- No outside-AOI pixel contributes to any count.
- Peak memory stays bounded as tile count grows.

- [ ] **Step 5: Verify resume behavior manually**

Interrupt the same smoke command after at least one tile CSV appears, rerun it, and confirm completed tile IDs are skipped while the year finishes and writes its annual cache.

- [ ] **Step 6: Compare tile sizes before the full 1986-2026 run**

Run the same two-month smoke range with `--tile-pixels 512`, `1024`, and `2048`, each with a separate cache directory. Record wall time and peak memory. Keep `1024` unless `2048` is materially faster and remains comfortably within available memory. Tile size must not change any output count.

- [ ] **Step 7: Commit final tests or fixes**

```powershell
git add hydroseason\_io_geo.py hydroseason\_io_extent_cache.py hydroseason\io.py scripts\build_real_extent_fixture.py tests\test_io.py tests\test_io_extent_cache.py tests\test_real_fixture_builder.py
git commit -m "test: verify exact native tiled WOfS extent"
```

---

## Completion Criteria

- The catchment CLI defaults to EPSG:3577, 30 m, and 1024-pixel tiles.
- A catchment/year causes exactly one STAC metadata search.
- Every annual item list is reused across its tiles.
- No tile exceeds the configured pixel edge.
- Tile windows cover the parent grid exactly once.
- Tiled and whole-cube synthetic counts are identical.
- `-2` outside-AOI pixels enter no count.
- `-1` pixels count as invalid only when inside the AOI.
- Every non-empty monthly row satisfies `n_aoi == n_valid + n_invalid`.
- Percentages are recomputed from summed counts.
- Missing years produce rows and do not stop later years.
- Interrupted years resume from atomic tile CSVs.
- Existing complete annual caches are reused.
- The focused automated suite passes.
- The bounded real-data smoke test completes and resumes successfully.
