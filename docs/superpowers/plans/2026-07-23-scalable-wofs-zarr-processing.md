# Scalable WOfS Zarr Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace repeated per-tile/per-year DEA reads with one query, one shared annual Dask graph, bounded spatial materialisation, and a resumable canonical 30 m WOfS Zarr cache that supports zero-network reruns.

**Architecture:** A pure geometry-cost planner selects logical AOI windows. One full-interval STAC query is partitioned by year; each uncached year builds one `odc.stac.stac_load` graph, and aligned 512-pixel storage chunks are computed once from that shared graph into an atomic annual Zarr group. The existing extent API reads completed local groups and keeps CSV as the only non-WOfS user input.

**Tech Stack:** Python 3.10+, pandas, NumPy, Xarray, Dask Array, Zarr 2 (`zarr>=2.16,<3`), Numcodecs Blosc, GeoPandas/Shapely, Rasterio/Affine, rioxarray, `pystac-client`, `odc-stac`, pytest.

## Global Constraints

- Public inputs remain DEA/WOfS and already-aggregated extent CSV only.
- Canonical mask values are exactly `water=1`, `dry=0`, `invalid=-1`, `outside=-2`, stored as `int8`.
- Output grid is stable EPSG:3577; explicit 30 m mode retains `resampling="mode"`.
- Zarr format is v2; chunks are exactly `(time=1, y=512, x=512)`.
- Compression is `numcodecs.Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)`.
- A request performs one STAC search, then at most one `stac_load` graph build per uncached calendar year.
- Source data are never recomputed for wet-AOI or denominator reconciliation.
- Memory is bounded by one annual lazy graph and one selected spatial compute window; years remain sequential.
- Planner constants are portable defaults and contain no named-catchment fitting.
- Offline mode never imports or contacts STAC.
- Existing CSV-only imports keep working without raster, Dask, Zarr, or STAC installed.
- Default CI uses structural counters and exact equality, never wall-clock thresholds.
- Opt-in real benchmark hard gates: Gilbert cold median improvement `>=20%`; target `>=35%`; stretch `>=40%`; Fitzroy median regression `<=10%`; cached rerun improvement `>=80%` and zero STAC calls.
- Generated stores, timings, and reports stay under git-ignored `output/`.

---

## File Map

- Create `hydroseason/_spatial_plan.py`: serialisable, dataset-independent geometry-cost planner.
- Create `hydroseason/_io_wofs_zarr.py`: cache request/identity, atomic annual groups, validation, lookup, lock, and lazy reader.
- Create `hydroseason/_io_wofs_acquire.py`: one-query partitioning, one shared graph per year, bounded cache materialisation, and diagnostics.
- Modify `hydroseason/_io_geo.py`: expose a single-year graph builder without adding another query.
- Modify `hydroseason/_wet_aoi.py`: derive ever-wet state from locally accumulated wet/clear counts.
- Modify `hydroseason/_io_extent_cache.py`: prefer canonical Zarr, implement explicit offline behavior, and retain annual extent CSV output.
- Modify `hydroseason/io.py`: private seam imports plus the public cache result type/function.
- Modify `hydroseason/__init__.py`: export only the supported high-level WOfS cache entry point; do not expose generic Zarr input.
- Modify `scripts/extract_water_extent_csv.py`: 30 m default, cache/offline switches, and planner diagnostics.
- Modify `scripts/run_multi_catchment_report.py`: reuse a probe-produced cache on forced final runs.
- Create `scripts/benchmark_wofs_cache.py`: repeatable subprocess benchmark with digest/equality gates.
- Create `tests/test_spatial_plan.py`.
- Create `tests/test_io_wofs_zarr.py`.
- Create `tests/test_io_wofs_acquire.py`.
- Create `tests/test_wofs_cache_performance.py` (opt-in real benchmark wrapper).
- Modify `tests/test_io.py`, `tests/test_io_extent_cache.py`, `tests/test_wet_aoi.py`, `tests/test_package_surface.py`, `tests/test_run_multi_catchment_report.py`.
- Modify `pyproject.toml`: register `network` and `performance` pytest markers.
- Modify `docs/guide.md`: document cache lifecycle, offline use, and benchmark command.

---

### Task 1: Add the Pure Geometry-Cost Planner

**Files:**
- Create: `hydroseason/_spatial_plan.py`
- Create: `tests/test_spatial_plan.py`

**Interfaces:**
- Produces: `GridWindow(tile_id: str, y_start: int, y_stop: int, x_start: int, x_stop: int)`.
- Produces: `CandidateScore` with tile size, tile/pixel counts, cost, relative improvement, and an immutable sequence of `GridWindow` values.
- Produces: `SpatialPlan` with selected tile size, immutable selected windows/candidate scores, reason, and `planner_version=1`.
- Produces: `plan_spatial_slices(geometry, *, shape, transform, candidate_tile_pixels=(None, 2048, 1024, 512), pixel_cost=1.0, tile_overhead=262144.0, min_improvement=0.15) -> SpatialPlan`.

- [ ] **Step 1: Write planner tests**

Create `tests/test_spatial_plan.py`:

```python
from affine import Affine
from shapely.geometry import box

from hydroseason._spatial_plan import plan_spatial_slices


def test_thin_aoi_selects_1024_windows():
    plan = plan_spatial_slices(
        box(0, -4096, 600, 0),
        shape=(4096, 4096),
        transform=Affine(1, 0, 0, 0, -1, 0),
    )

    assert plan.selected_tile_pixels == 1024
    assert len(plan.windows) == 4
    assert plan.reason == "predicted improvement meets 15.0% minimum"
    assert plan.candidates[0].tile_pixels is None
    assert plan.to_dict()["planner_version"] == 1


def test_compact_aoi_keeps_parent_when_savings_are_below_threshold():
    plan = plan_spatial_slices(
        box(0, -2048, 2048, 0),
        shape=(2048, 2048),
        transform=Affine(1, 0, 0, 0, -1, 0),
    )

    assert plan.selected_tile_pixels is None
    assert [(w.y_start, w.y_stop, w.x_start, w.x_stop) for w in plan.windows] == [
        (0, 2048, 0, 2048)
    ]
    assert plan.reason == "best candidate is below 15.0% minimum improvement"


def test_planner_is_deterministic_and_json_serialisable():
    kwargs = dict(
        geometry=box(0, -100, 50, 0),
        shape=(100, 100),
        transform=Affine(1, 0, 0, 0, -1, 0),
        candidate_tile_pixels=(None, 50),
        tile_overhead=10.0,
    )
    assert plan_spatial_slices(**kwargs).to_dict() == plan_spatial_slices(**kwargs).to_dict()


def test_planner_rejects_invalid_cost_inputs():
    for kwargs, message in [
        ({"shape": (0, 10)}, "shape"),
        ({"pixel_cost": 0.0}, "pixel_cost"),
        ({"tile_overhead": -1.0}, "tile_overhead"),
        ({"min_improvement": 1.1}, "min_improvement"),
    ]:
        base = dict(
            geometry=box(0, -10, 10, 0),
            shape=(10, 10),
            transform=Affine(1, 0, 0, 0, -1, 0),
        )
        base.update(kwargs)
        try:
            plan_spatial_slices(**base)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_spatial_plan.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'hydroseason._spatial_plan'`.

- [ ] **Step 3: Implement the planner**

Create `hydroseason/_spatial_plan.py` with frozen dataclasses, `to_dict()` methods using primitive values, row-major grid generation, tile polygons computed from `transform * Affine.translation(x_start, y_start)`, exact AOI intersection, and this selection rule:

```python
parent = scores[0]
best = min(scores, key=lambda score: (score.predicted_cost, score.tile_pixels is not None))
improvement = 0.0 if parent.predicted_cost == 0 else (
    parent.predicted_cost - best.predicted_cost
) / parent.predicted_cost
if best.tile_pixels is not None and improvement >= min_improvement:
    selected = best
    reason = f"predicted improvement meets {min_improvement:.1%} minimum"
else:
    selected = parent
    reason = f"best candidate is below {min_improvement:.1%} minimum improvement"
```

Use `rasterio.transform.array_bounds` and `shapely.geometry.box` inside the function. For `tile_pixels=None`, create one full-grid window. For tiled candidates, retain only windows whose polygon intersects `geometry`; calculate `intersecting_pixels` from full window areas, including partial edge windows.

- [ ] **Step 4: Run planner tests**

Run: `python -m pytest tests\test_spatial_plan.py -q`

Expected: `4 passed`.

- [ ] **Step 5: Commit planner**

```powershell
git add hydroseason\_spatial_plan.py tests\test_spatial_plan.py
git commit -m "feat: plan WOfS work from AOI geometry"
```

---

### Task 2: Define Cache Request, Full Identity, Lookup, Lock, and Preflight

**Files:**
- Create: `hydroseason/_io_wofs_zarr.py`
- Create: `tests/test_io_wofs_zarr.py`

**Interfaces:**
- Produces: `WOfSCacheRequest` containing known request semantics and `request_digest()`.
- Produces: `WOfSCacheIdentity` extending the request with `shape`, six-value `transform`, and `grid_anchor`; property `digest` is the full store identity.
- Produces: `WOfSCacheHandle(path: Path, identity: str, request_digest: str)`.
- Produces: `cache_writer_lock(cache_root: Path, request_digest: str)`.
- Produces: `create_cache_handle(cache_root: Path, identity: WOfSCacheIdentity) -> WOfSCacheHandle`.
- Produces: `resolve_cached_request(cache_root, request, *, offline) -> WOfSCacheHandle | None`.
- Produces: `preflight_cache_space(path, *, shape, months, headroom=1.5) -> int`.
- Produces: `preflight_request_space(path, aoi, *, crs, resolution, months, headroom=1.5) -> int`, a conservative bbox estimate usable before STAC access.

- [ ] **Step 1: Add identity, lock, lookup, and disk tests**

Create `tests/test_io_wofs_zarr.py` with these imports and fixture:

```python
import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from hydroseason._io_wofs_zarr import (
    WOfSCacheHandle,
    WOfSCacheIdentity,
    WOfSCacheRequest,
    cache_writer_lock,
    create_cache_handle,
    preflight_cache_space,
    require_cached_request,
    resolve_cached_request,
)


def _request() -> WOfSCacheRequest:
    return WOfSCacheRequest(
        stac_url="https://example.invalid/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="2015-01-01",
        end_date="2025-12-31",
        crs="EPSG:3577",
        resolution=30.0,
        classifier_version=1,
        groupby="solar_day",
        majority=True,
        planner_version=1,
        schema_version=1,
    )
```

Then add these assertions:

```python
def test_every_data_semantic_changes_request_digest():
    base = _request()
    for field, changed in {
        "stac_url": "https://other.invalid/stac",
        "collection": "other",
        "aoi_sha256": "b" * 64,
        "start_date": "2016-01-01",
        "end_date": "2024-12-31",
        "crs": "EPSG:4326",
        "resolution": 60.0,
        "classifier_version": 2,
        "groupby": "time",
        "majority": False,
        "planner_version": 2,
        "schema_version": 2,
    }.items():
        assert dataclasses.replace(base, **{field: changed}).request_digest() != base.request_digest()


def test_transform_changes_full_identity_not_request_digest():
    request = _request()
    left = WOfSCacheIdentity.from_request(request, shape=(10, 20), transform=(30, 0, 0, 0, -30, 0))
    right = WOfSCacheIdentity.from_request(request, shape=(10, 20), transform=(30, 0, 30, 0, -30, 0))
    assert left.request_digest == right.request_digest
    assert left.digest != right.digest


def test_same_request_writer_is_rejected(tmp_path):
    with cache_writer_lock(tmp_path, "abc"):
        with pytest.raises(RuntimeError, match="already being written"):
            with cache_writer_lock(tmp_path, "abc"):
                pass


def test_offline_lookup_uses_local_index_without_network(tmp_path):
    identity = WOfSCacheIdentity.from_request(
        _request(), shape=(10, 20), transform=(30, 0, 0, 0, -30, 0)
    )
    handle = create_cache_handle(tmp_path, identity)
    assert resolve_cached_request(tmp_path, _request(), offline=True) == handle


def test_offline_lookup_lists_missing_dates(tmp_path):
    with pytest.raises(FileNotFoundError, match="2015-01-01.*2025-12-31"):
        require_cached_request(tmp_path, _request(), offline=True)


def test_preflight_fails_before_work_when_free_space_is_too_small(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: shutil._ntuple_diskusage(100, 99, 1))
    with pytest.raises(OSError, match="requires 1,800 bytes"):
        preflight_cache_space(tmp_path, shape=(10, 10), months=12, headroom=1.5)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_io_wofs_zarr.py -q`

Expected: FAIL because the cache types do not exist.

- [ ] **Step 3: Implement canonical JSON identities**

In `hydroseason/_io_wofs_zarr.py`, use `dataclasses.asdict`, `json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)`, and SHA-256. Store CRS as a string and dates as `YYYY-MM-DD`. Define schema constants:

```python
WOFS_CACHE_SCHEMA_VERSION = 1
WOFS_CLASSIFIER_VERSION = 1
WOFS_PLANNER_VERSION = 1
CANONICAL_VALUES = (-2, -1, 0, 1)
MASK_CHUNKS = (1, 512, 512)
```

The request index is `cache_root / "index" / f"{request_digest}.json"`; write it with `tempfile.mkstemp` plus `os.replace`. It contains `identity`, relative `store`, and the complete requested date range. `create_cache_handle` creates the root Zarr group, writes the root manifest and request index atomically, and returns the three-field handle. Offline resolution reads this index only and validates that the pointed store manifest matches both digests.

- [ ] **Step 4: Implement exclusive lock and disk preflight**

Use `os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)` at `cache_root / ".locks" / f"{request_digest}.lock"`. Write PID and creation time, close the descriptor, and unlink in `finally`. Never automatically delete an existing lock. Calculate projected bytes as `height * width * months * np.dtype("int8").itemsize`; require `ceil(projected * headroom)` free bytes.

`preflight_request_space` loads/reprojects the AOI locally, calculates conservative bbox width/height with `ceil(span / resolution)`, and calls `preflight_cache_space` before `_query_wofs_items`. After STAC supplies the exact GeoBox and the planner supplies intersecting windows, run a second exact check based on de-duplicated planned pixels. Neither check opens a COG; insufficient space fails before source imagery is read.

- [ ] **Step 5: Run cache-contract tests**

Run: `python -m pytest tests\test_io_wofs_zarr.py -q`

Expected: all identity, lock, lookup, and preflight tests PASS.

- [ ] **Step 6: Commit cache contract**

```powershell
git add hydroseason\_io_wofs_zarr.py tests\test_io_wofs_zarr.py
git commit -m "feat: define canonical WOfS cache identity"
```

---

### Task 3: Write and Validate Atomic Sparse Annual Zarr Groups

**Files:**
- Modify: `hydroseason/_io_wofs_zarr.py`
- Modify: `tests/test_io_wofs_zarr.py`

**Interfaces:**
- Produces: `AnnualWriteStats(year, task_count, chunks_considered, chunks_written, loaded_pixels, item_digest)`.
- Produces: `write_annual_group(handle, year, mask, *, windows, item_ids, overwrite=False) -> AnnualWriteStats`.
- Produces: `validate_annual_group(path, *, expected_year, expected_shape, expected_transform) -> dict`.
- Produces: `open_completed_mask_cache(handle, start_date, end_date, *, chunk_x=512, chunk_y=512, time_chunk=12) -> xarray.DataArray`.

- [ ] **Step 1: Add sparse/atomic/validation tests**

Append these imports and helper to `tests/test_io_wofs_zarr.py`:

```python
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from affine import Affine

from hydroseason._spatial_plan import GridWindow
from hydroseason._io_wofs_zarr import (
    completed_years,
    open_completed_mask_cache,
    write_annual_group,
)

pytest.importorskip("rioxarray")


def _canonical_cube(*, shape: tuple[int, int, int], fill: int) -> xr.DataArray:
    time, height, width = shape
    transform = Affine(30, 0, 1000, 0, -30, 2000)
    values = np.full(shape, fill, dtype=np.int8)
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={
            "time": pd.date_range("2015-01-01", periods=time, freq="MS"),
            "y": transform.f + (np.arange(height) + 0.5) * transform.e,
            "x": transform.c + (np.arange(width) + 0.5) * transform.a,
        },
        name="water_mask",
    ).rio.write_crs(3577).rio.write_transform(transform)


def _handle_for_cube(tmp_path: Path, cube: xr.DataArray) -> WOfSCacheHandle:
    identity = WOfSCacheIdentity.from_request(
        _request(),
        shape=(cube.sizes["y"], cube.sizes["x"]),
        transform=tuple(cube.rio.transform())[:6],
    )
    return create_cache_handle(tmp_path, identity)
```

Then add these tests:

```python
def test_annual_writer_skips_wholly_outside_chunks_and_reads_fill(tmp_path):
    mask = _canonical_cube(shape=(12, 512, 1024), fill=-2)
    mask.loc[{"x": mask.x[:512]}] = 1
    handle = _handle_for_cube(tmp_path, mask)

    stats = write_annual_group(
        handle, 2015, mask.chunk({"time": 1, "y": 512, "x": 512}),
        windows=(GridWindow("parent", 0, 512, 0, 1024),), item_ids=("a", "b"),
    )

    opened = open_completed_mask_cache(handle, "2015-01-01", "2015-12-31")
    assert stats.chunks_considered == 24
    assert stats.chunks_written == 12
    assert (opened.isel(x=slice(512, 1024)).compute().values == -2).all()
    assert set(np.unique(opened.compute())) == {-2, 1}


def test_partial_annual_directory_is_not_a_cache_hit(tmp_path):
    mask = _canonical_cube(shape=(12, 2, 2), fill=0)
    handle = _handle_for_cube(tmp_path, mask)
    partial = handle.path / "years" / ".2015.incomplete-test"
    partial.mkdir(parents=True)
    assert completed_years(handle) == set()


def test_writer_renames_only_after_validation(monkeypatch, tmp_path):
    mask = _canonical_cube(shape=(12, 2, 2), fill=0).chunk({"time": 1, "y": 2, "x": 2})
    handle = _handle_for_cube(tmp_path, mask)
    monkeypatch.setattr("hydroseason._io_wofs_zarr.validate_annual_group", Mock(side_effect=ValueError("bad domain")))
    with pytest.raises(ValueError, match="bad domain"):
        write_annual_group(handle, 2015, mask, windows=(GridWindow("parent", 0, 2, 0, 2),), item_ids=("a",))
    assert not (handle.path / "years" / "2015").exists()


def test_reader_rejects_duplicate_or_out_of_order_months(tmp_path):
    import zarr

    mask = _canonical_cube(shape=(12, 2, 2), fill=0)
    handle = _handle_for_cube(tmp_path, mask)
    write_annual_group(
        handle, 2015, mask.chunk({"time": 1, "y": 2, "x": 2}),
        windows=(GridWindow("parent", 0, 2, 0, 2),), item_ids=("a",),
    )
    group = zarr.open_group(handle.path / "years" / "2015", mode="r+")
    encoded = group["time"][:]
    group["time"][:] = encoded[::-1]
    with pytest.raises(ValueError, match="strict monthly order"):
        open_completed_mask_cache(handle, "2015-01-01", "2015-12-31")
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m pytest tests\test_io_wofs_zarr.py -k "annual or partial or reader" -q`

Expected: FAIL because annual write/read functions do not exist.

- [ ] **Step 3: Initialise an Xarray-compatible annual group**

Create a sibling temporary directory named `years/.<year>.incomplete-<uuid4 hex>`. Initialise metadata with `xr.Dataset({"water_mask": mask_template}).to_zarr(temp_path, mode="w", compute=False, consolidated=False, encoding=encoding)`, where:

```python
compressor = Blosc(cname="zstd", clevel=5, shuffle=Blosc.BITSHUFFLE)
encoding = {
    "water_mask": {
        "dtype": "int8",
        "chunks": (1, 512, 512),
        "compressor": compressor,
        "_FillValue": -2,
        "write_empty_chunks": False,
    }
}
```

The template contains eager `time`, `x`, and `y` coordinates, CRS/transform attributes, and a Dask `empty` data variable. Open the created Zarr v2 array with `zarr.open_group(temp_path, mode="r+")["water_mask"]`.

- [ ] **Step 4: Materialise aligned chunks once from the shared mask graph**

Intersect each logical planner window with the 512-pixel storage grid. De-duplicate `(time_index, y_start, x_start)` keys in a set. For every key, compute exactly one `mask.isel(time=slice(t, t + 1), y=slice(y_start, y_stop), x=slice(x_start, x_stop)).data` value. Reject values outside `{-2,-1,0,1}`. Skip assignment when every value is `-2`; otherwise assign the NumPy block to the Zarr array. Accumulate `wet_count=(values==1).sum(axis=0)` and `clear_count=((values==0)|(values==1)).sum(axis=0)` into annual `uint16` arrays with spatial chunks `(512,512)` and fill `0`; these are local derived arrays, not public inputs.

Record Dask task count before compute as `len(block.__dask_graph__())` when the graph method exists. `loaded_pixels` is the sum of computed block sizes, not the AOI polygon area estimate.

- [ ] **Step 5: Validate then publish atomically**

Validation must check `.zgroup`, variable names, dtype, canonical domain by chunk, exact 12-or-requested-partial monthly timestamps, strictly increasing unique time, shape, chunks, CRS, transform, and item digest. Write `complete.json` last inside the temporary group, then publish with `os.replace(temp_path, final_year_path)`. Update the root manifest and request index atomically after the rename. A corrupt final group is excluded by `completed_years()` and may be rebuilt only in network-enabled mode.

- [ ] **Step 6: Implement lazy multi-year open**

Open each requested annual directory using `xr.open_zarr(year_path, consolidated=False, mask_and_scale=False, chunks={"time": time_chunk, "y": chunk_y, "x": chunk_x})["water_mask"]`, concatenate in year order, slice requested dates, and call `complete_monthly_axis`. Validate that completed years cover every requested month before opening data.

- [ ] **Step 7: Run storage tests**

Run: `python -m pytest tests\test_io_wofs_zarr.py -q`

Expected: all tests PASS; the outside half has no written chunk payloads and reads as `-2`.

- [ ] **Step 8: Commit annual Zarr storage**

```powershell
git add hydroseason\_io_wofs_zarr.py tests\test_io_wofs_zarr.py
git commit -m "feat: persist resumable annual WOfS Zarr groups"
```

---

### Task 4: Build One Query and One Shared Annual Graph

**Files:**
- Create: `hydroseason/_io_wofs_acquire.py`
- Modify: `hydroseason/_io_geo.py`
- Create: `tests/test_io_wofs_acquire.py`
- Modify: `tests/test_io.py`

**Interfaces:**
- Produces: `partition_items_by_year(items) -> dict[int, tuple]`.
- Produces: `build_wofs_year_graph(items, aoi_gdf, start_date, end_date, *, geobox, chunk_x=512, chunk_y=512, time_chunk=12, majority=True, groupby="solar_day") -> DataArray`.
- Produces: `acquire_wofs_cache(stac_url, collection, aoi, start_date, end_date, *, cache_root, crs=3577, resolution=30.0, chunk_x=512, chunk_y=512, time_chunk=12, majority=True, offline=False, force=False) -> WOfSCacheHandle`.

- [ ] **Step 1: Add structural counter tests**

Create `tests/test_io_wofs_acquire.py` with these helpers and tests:

```python
from types import SimpleNamespace
from unittest.mock import Mock

import dask
import dask.array as da
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import box

from hydroseason._io_wofs_acquire import acquire_wofs_cache


def _item(date: str, item_id: str):
    return SimpleNamespace(id=item_id, properties={"datetime": date})


def _aoi():
    return gpd.GeoDataFrame(geometry=[box(0, 0, 120, 120)], crs="EPSG:3577")


def _cube(year: int):
    return xr.DataArray(
        np.zeros((12, 4, 4), dtype=np.int8),
        dims=("time", "y", "x"),
        coords={"time": pd.date_range(f"{year}-01-01", periods=12, freq="MS")},
    ).chunk({"time": 1, "y": 4, "x": 4})


def _stats():
    return SimpleNamespace(
        year=2015, task_count=1, chunks_considered=12,
        chunks_written=12, loaded_pixels=192, item_digest="abc",
    )


def test_multi_year_acquisition_queries_once_and_builds_one_graph_per_year(monkeypatch, tmp_path):
    items = [_item("2015-01-15", "a"), _item("2015-07-15", "b"), _item("2016-02-15", "c")]
    query = Mock(return_value=(items, _aoi()))
    graph = Mock(side_effect=[_cube(2015), _cube(2016)])
    writer = Mock(return_value=_stats())
    monkeypatch.setattr("hydroseason._io_wofs_acquire._query_wofs_items", query)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", graph)
    monkeypatch.setattr("hydroseason._io_wofs_acquire.write_annual_group", writer)

    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2016-12-31", cache_root=tmp_path, resolution=30,
    )

    query.assert_called_once()
    assert graph.call_count == 2
    assert writer.call_count == 2
    assert [tuple(item.id for item in call.args[0]) for call in graph.call_args_list] == [("a", "b"), ("c",)]


def test_completed_year_is_not_rebuilt(monkeypatch, tmp_path):
    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    monkeypatch.setattr("hydroseason._io_wofs_acquire.resolve_cached_request", Mock(return_value=handle))
    monkeypatch.setattr("hydroseason._io_wofs_acquire.completed_years", Mock(return_value={2015}))
    graph = Mock()
    monkeypatch.setattr("hydroseason._io_wofs_acquire.build_wofs_year_graph", graph)
    acquire_wofs_cache(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
    )
    graph.assert_not_called()


def test_shared_graph_consumers_execute_delayed_source_once():
    calls = {"source": 0}

    @dask.delayed
    def source():
        calls["source"] += 1
        return np.arange(16, dtype=np.int8).reshape(4, 4)

    parent = da.from_delayed(source(), shape=(4, 4), dtype=np.int8)
    left, right = dask.compute(parent[:, :2], parent[:, 2:])
    assert calls["source"] == 1
    assert left.shape == right.shape == (4, 2)


def test_storage_preflight_fails_before_stac_query(monkeypatch, tmp_path):
    query = Mock()
    monkeypatch.setattr("hydroseason._io_wofs_acquire._query_wofs_items", query)
    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.preflight_request_space",
        Mock(side_effect=OSError("insufficient cache space")),
    )
    with pytest.raises(OSError, match="insufficient cache space"):
        acquire_wofs_cache(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2015-01-01", "2015-12-31", cache_root=tmp_path, resolution=30,
        )
    query.assert_not_called()
```

The real annual-completion marker is covered in Task 3; this acquisition unit test isolates the skip decision by patching `completed_years` to `{2015}`.

- [ ] **Step 2: Run structural tests and verify RED**

Run: `python -m pytest tests\test_io_wofs_acquire.py -q`

Expected: FAIL because acquisition functions do not exist.

- [ ] **Step 3: Add the single-year graph wrapper**

In `hydroseason/_io_geo.py`, add `build_wofs_year_graph` as a validating wrapper around `_load_wofs_items`. Require all supplied item timestamps to match the requested calendar year, require a supplied parent `geobox`, and delegate once with `resolution=None` because the geobox already fixes CRS/resolution; pass an explicit `resampling="mode"` flag into `_load_wofs_items` through a new keyword so geobox-based loading keeps mode resampling.

Refactor `_load_wofs_items` to accept `resampling: str | None = None` and build loader kwargs as:

```python
load_kwargs = {
    "bands": ["water"],
    "chunks": {"x": chunk_x, "y": chunk_y},
    "groupby": groupby,
    **({"resampling": resampling} if resampling is not None else {}),
    **spatial,
}
ds = odc.stac.stac_load(year_items, **load_kwargs)
```

Keep `load_wofs_from_stac` behavior unchanged by passing `resampling="mode"` exactly when `resolution is not None`.

- [ ] **Step 4: Implement acquisition orchestration**

`acquire_wofs_cache` must:

1. Validate dates/resolution and build `WOfSCacheRequest` before optional STAC imports.
2. Return `require_cached_request(cache_root, request, offline=True)` immediately in offline mode.
3. Run the conservative local AOI/disk preflight.
4. Query `_query_wofs_items` once for the full interval.
5. Derive one parent GeoBox with `_output_geobox_for_aoi(items, target, crs, resolution)`.
6. Build the full identity from `parent_geobox.shape` and affine transform.
7. Create/validate the store under `<cache_root>/<identity>.zarr` while holding the request lock.
8. Partition items by calendar year.
9. For each missing year, build one shared graph, obtain a plan from actual target geometry, run the exact planned-pixel disk check, and call `write_annual_group` once.
10. Preserve completed years after any STAC/COG failure.
11. Write query count, graph count, plan diagnostics, item IDs/digest, package versions, elapsed phases, and output digest into the manifest.

An interval year with zero items is written as 12 (or requested partial-year) all-invalid `-1` inside AOI and `-2` outside AOI, matching the existing missing-month policy without a `stac_load` call.

- [ ] **Step 5: Run acquisition and legacy loader tests**

Run:

```powershell
python -m pytest tests\test_io_wofs_acquire.py -q
python -m pytest tests\test_io.py -k "stac or resampling or groupby" -q
```

Expected: PASS; `resampling="mode"` remains asserted.

- [ ] **Step 6: Commit shared acquisition graph**

```powershell
git add hydroseason\_io_wofs_acquire.py hydroseason\_io_geo.py tests\test_io_wofs_acquire.py tests\test_io.py
git commit -m "feat: acquire WOfS through one shared annual graph"
```

---

### Task 5: Derive and Persist Wet-AOI Locally

**Files:**
- Modify: `hydroseason/_wet_aoi.py`
- Modify: `hydroseason/_io_wofs_acquire.py`
- Modify: `tests/test_wet_aoi.py`
- Modify: `tests/test_io_wofs_acquire.py`

**Interfaces:**
- Produces: `compute_ever_wet_from_counts(wet_count, clear_count, *, persistence_min=0.0)`.
- Produces: `load_or_build_cached_wet_aoi(handle, *, persistence_min, close_m, buffer_m)`.

- [ ] **Step 1: Add count-equivalence tests**

Append to `tests/test_wet_aoi.py`:

```python
def test_count_based_ever_wet_matches_cube_reduction():
    cube = _cube([
        np.array([[1, 0], [-1, -2]], dtype=np.int8),
        np.array([[0, 0], [1, -2]], dtype=np.int8),
    ])
    wet = (cube == 1).sum("time")
    clear = ((cube == 0) | (cube == 1)).sum("time")
    expected = compute_ever_wet(cube, persistence_min=0.5)
    actual = compute_ever_wet_from_counts(wet, clear, persistence_min=0.5)
    xr.testing.assert_identical(actual, expected)


def test_count_based_ever_wet_rejects_invalid_threshold():
    counts = xr.DataArray(np.ones((2, 2)), dims=("y", "x"))
    with pytest.raises(ValueError, match="0.0 through 1.0"):
        compute_ever_wet_from_counts(counts, counts, persistence_min=1.1)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_wet_aoi.py -k "count_based" -q`

Expected: FAIL because `compute_ever_wet_from_counts` is missing.

- [ ] **Step 3: Implement the shared count reducer**

Implement:

```python
def compute_ever_wet_from_counts(wet_count, clear_count, *, persistence_min=0.0):
    if not 0.0 <= persistence_min <= 1.0:
        raise ValueError("persistence_min must be 0.0 through 1.0.")
    if persistence_min == 0.0:
        kept = wet_count > 0
    else:
        kept = ((wet_count / clear_count.where(clear_count > 0)) >= persistence_min).fillna(False)
    return _preserve_georef(kept, wet_count)
```

Refactor `compute_ever_wet` to calculate counts and delegate, so cube and cached-count paths cannot drift.

- [ ] **Step 4: Build the wet geometry from annual local count arrays**

Open every completed annual `wet_count`/`clear_count` lazily, sum across years with Dask, call `compute_ever_wet_from_counts`, then `wet_aoi_polygon`. Write GeoJSON plus a JSON identity containing cache identity, persistence, close, and buffer values. Use atomic file replacement. A matching sidecar is reused; a mismatch creates a new sidecar filename. No STAC function is imported or called.

- [ ] **Step 5: Prove no source reread**

In `tests/test_io_wofs_acquire.py`, patch `_query_wofs_items` and `build_wofs_year_graph` to raise after a completed cache exists, call `load_or_build_cached_wet_aoi`, and assert a non-empty GeoDataFrame plus zero patched calls.

- [ ] **Step 6: Run wet-AOI tests**

Run: `python -m pytest tests\test_wet_aoi.py tests\test_io_wofs_acquire.py -q`

Expected: PASS.

- [ ] **Step 7: Commit local wet-AOI derivation**

```powershell
git add hydroseason\_wet_aoi.py hydroseason\_io_wofs_acquire.py tests\test_wet_aoi.py tests\test_io_wofs_acquire.py
git commit -m "feat: derive wet AOI from local WOfS counts"
```

---

### Task 6: Integrate Canonical Cache, Offline Mode, and Existing CSV API

**Files:**
- Modify: `hydroseason/_io_extent_cache.py`
- Modify: `hydroseason/io.py`
- Modify: `hydroseason/__init__.py`
- Modify: `tests/test_io_extent_cache.py`
- Modify: `tests/test_io.py`
- Modify: `tests/test_package_surface.py`

**Interfaces:**
- Extends the existing `load_wofs_monthly_extent` signature with keyword-only `mask_cache_dir: str | os.PathLike[str] | None = None` and `offline: bool = False`; return type remains `pd.DataFrame`.
- Exposes: `acquire_wofs_cache` and `WOfSCacheHandle`; no generic Zarr input is added.
- Preserves: `cache_dir` as the annual extent CSV cache and the existing returned columns/order.

- [ ] **Step 1: Add cache-hit, miss, equality, and import tests**

Append focused tests:

```python
def test_offline_cache_hit_performs_zero_stac_calls(monkeypatch, tmp_path):
    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    cube = _mixed_canonical_cube()
    monkeypatch.setattr(hio, "acquire_wofs_cache", Mock(return_value=handle))
    monkeypatch.setattr(hio, "open_completed_mask_cache", Mock(return_value=cube))
    monkeypatch.setattr(hio, "_query_wofs_items", Mock(side_effect=AssertionError("network")), raising=False)
    result = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2020-01-01", "2020-12-31", resolution=30,
        mask_cache_dir=tmp_path, offline=True,
    )
    assert len(result) == 12


def test_offline_cache_miss_is_explicit(tmp_path):
    with pytest.raises(FileNotFoundError, match="offline WOfS cache miss"):
        hio.load_wofs_monthly_extent(
            "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
            "2020-01-01", "2020-12-31", resolution=30,
            mask_cache_dir=tmp_path, offline=True,
        )


def test_canonical_cache_extent_is_exactly_equal_to_legacy(monkeypatch, tmp_path):
    cube = _mixed_canonical_cube()
    expected = monthly_water_extent(cube, time_block=3)
    handle = SimpleNamespace(path=tmp_path / "store.zarr", identity="id", request_digest="request")
    monkeypatch.setattr(hio, "acquire_wofs_cache", Mock(return_value=handle))
    monkeypatch.setattr(hio, "open_completed_mask_cache", Mock(return_value=cube))
    actual = hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "ga_ls_wo_3", _aoi(),
        "2020-01-01", "2020-12-31", resolution=30,
        mask_cache_dir=tmp_path,
    )
    pd.testing.assert_frame_equal(actual, expected)


def test_csv_import_does_not_import_raster_stack(monkeypatch, tmp_path):
    csv_path = tmp_path / "extent.csv"
    csv_path.write_text("date,extent_pct\n2020-01-01,10\n", encoding="utf-8")
    for name in ("xarray", "dask", "zarr", "pystac_client", "odc.stac"):
        monkeypatch.setitem(sys.modules, name, None)
    assert load_extent_csv(csv_path).iloc[0]["extent_pct"] == 10
```

At the top of `tests/test_io_extent_cache.py`, add:

```python
from types import SimpleNamespace


def _mixed_canonical_cube():
    xr = pytest.importorskip("xarray")
    values = np.resize(np.array([-2, -1, 0, 1], dtype=np.int8), (12, 4, 4))
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={"time": pd.date_range("2020-01-01", periods=12, freq="MS")},
    ).chunk({"time": 1, "y": 2, "x": 2})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_io_extent_cache.py tests\test_package_surface.py -q`

Expected: FAIL because `mask_cache_dir` and `offline` are not accepted.

- [ ] **Step 3: Route through acquisition and local masks**

At the start of `load_wofs_monthly_extent`, after pure argument validation and existing complete annual CSV-cache checks:

```python
if mask_cache_dir is not None or offline:
    handle = _io.acquire_wofs_cache(
        stac_url, collection, aoi, start_date, end_date,
        cache_root=mask_cache_dir,
        crs=crs,
        resolution=resolution,
        chunk_x=chunk_x,
        chunk_y=chunk_y,
        time_chunk=time_block,
        majority=majority,
        offline=offline,
        force=force,
    )
    masks = _io.open_completed_mask_cache(
        handle, start_date, end_date,
        chunk_x=chunk_x, chunk_y=chunk_y, time_chunk=time_block,
    )
    effective_wet_aoi = wet_aoi
    if precompute_wet_aoi and effective_wet_aoi is None:
        effective_wet_aoi = _io.load_or_build_cached_wet_aoi(
            handle, persistence_min=persistence_min, close_m=close_m, buffer_m=buffer_m,
        )
    extent = monthly_water_extent(
        masks, time_block=time_block, wet_aoi=effective_wet_aoi, read_workers=read_workers,
    )
    _write_requested_annual_extent_parts(extent, existing_cache_arguments)
    return extent
```

Extract `_write_requested_annual_extent_parts` from the existing annual CSV write logic with explicit parameters; it writes only missing/forced annual frames and preserves `_EXTENT_COLUMNS` order. Keep the legacy no-mask-cache branch for controlled A/B benchmarking until the hard gates pass.

- [ ] **Step 4: Export supported high-level symbols**

Import the new internals through `hydroseason/io.py`. Add `acquire_wofs_cache` and `WOfSCacheHandle` to `io.__all__` and top-level `hydroseason.__all__`. Do not add `open_completed_mask_cache`, `write_annual_group`, or generic `load_monthly_masks_zarr` behavior beyond its existing compatibility role.

- [ ] **Step 5: Run deterministic I/O suite**

Run:

```powershell
python -m pytest tests\test_io.py tests\test_io_extent_cache.py tests\test_io_wofs_zarr.py tests\test_io_wofs_acquire.py tests\test_package_surface.py -q
```

Expected: PASS; exact DataFrame equality and zero-network offline assertions are green.

- [ ] **Step 6: Commit loader integration**

```powershell
git add hydroseason\_io_extent_cache.py hydroseason\io.py hydroseason\__init__.py tests\test_io.py tests\test_io_extent_cache.py tests\test_package_surface.py
git commit -m "feat: serve WOfS extent from canonical local cache"
```

---

### Task 7: Wire CLI Defaults and Eliminate Forced Duplicate Final Work

**Files:**
- Modify: `scripts/extract_water_extent_csv.py`
- Modify: `scripts/run_multi_catchment_report.py`
- Modify: `tests/test_run_multi_catchment_report.py`
- Create: `tests/test_extract_water_extent_csv.py`
- Modify: `docs/guide.md`

**Interfaces:**
- CLI default resolution: exactly `30.0`.
- Adds extraction switches: `--mask-cache-dir`, `--offline`, `--legacy-remote-path`.
- `--force` refreshes acquisition once; a final load at a probe-produced resolution reuses that fresh cache.

- [ ] **Step 1: Add parser and force-reuse tests**

Create `tests/test_extract_water_extent_csv.py` with the loader fixture and assertions:

```python
import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_water_extent_csv.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("extract_water_extent_csv_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_parser_defaults_to_30m_canonical_cache(tmp_path):
    args = mod._build_arg_parser().parse_args(["--aoi", "data/Gilbert_river_buffer.geojson"])
    assert args.resolution == 30.0
    assert args.offline is False
    assert args.legacy_remote_path is False


def test_offline_and_legacy_remote_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        mod._build_arg_parser().parse_args([
            "--aoi", "data/Gilbert_river_buffer.geojson", "--offline", "--legacy-remote-path"
        ])
```

Append to `tests/test_run_multi_catchment_report.py`:

```python
def test_forced_final_load_reuses_cache_refreshed_by_probe(mod, monkeypatch, tmp_path):
    mocks = _patch_common(
        mod, monkeypatch,
        plan_resolution_return=(300.0, 1.0, 0.01, "ok"),
        guard_return={
            "amplitude_pp": 5.0, "guard_caveat": None,
            "refuse_coarsen_past": None,
        },
    )
    mod.run_one_catchment(_spec(), force=True, resolution_override=300.0)
    assert mocks["probe"].call_args.kwargs["force"] is True
    assert mocks["load"].call_args.kwargs["force"] is False
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_extract_water_extent_csv.py tests\test_run_multi_catchment_report.py -q`

Expected: parser default/flags and final `force=False` assertions fail.

- [ ] **Step 3: Implement CLI cache routing**

Set `--resolution` default to `30.0`. Add a mutually exclusive group for `--offline` and `--legacy-remote-path`; add `--mask-cache-dir` defaulting to `output/wofs_cache`. Pass `mask_cache_dir=None` only for the legacy flag. In offline mode pass `offline=True` and never set STAC-specific environment values after argument parsing.

Print the returned handle identity/store path and planner diagnostics under `--profile`. Keep output CSV paths unchanged.

- [ ] **Step 4: Prevent forced final recomputation**

In `run_multi_catchment_report.py`, let the existing `probe_amplitude` call retain `force=force` so it refreshes probe caches. Pass `force=False` to the final `load_wofs_monthly_extent`; if its resolution differs, the identity misses and acquisition occurs, while an identical resolution reuses the freshly produced cache. Include mask-cache identity in `run_config` so state checkpoints cannot mix inputs.

- [ ] **Step 5: Document exact commands**

Add to `docs/guide.md`:

```powershell
python scripts\extract_water_extent_csv.py --aoi data\Gilbert_river_buffer.geojson --resolution 30
python scripts\extract_water_extent_csv.py --aoi data\Gilbert_river_buffer.geojson --resolution 30 --offline
python scripts\extract_water_extent_csv.py --aoi data\Gilbert_river_buffer.geojson --resolution 30 --legacy-remote-path
```

Explain annual completion, cache identity, explicit offline misses, interruption recovery, same-store writer rejection, and that `output/wofs_cache` is internal rather than a public Zarr-input mode.

- [ ] **Step 6: Run CLI/report tests**

Run: `python -m pytest tests\test_extract_water_extent_csv.py tests\test_run_multi_catchment_report.py -q`

Expected: PASS.

- [ ] **Step 7: Commit CLI integration**

```powershell
git add scripts\extract_water_extent_csv.py scripts\run_multi_catchment_report.py tests\test_extract_water_extent_csv.py tests\test_run_multi_catchment_report.py docs\guide.md
git commit -m "feat: run WOfS workflow through reusable cache"
```

---

### Task 8: Add Deterministic Regression Guards and Opt-In Real Benchmarks

**Files:**
- Create: `scripts/benchmark_wofs_cache.py`
- Create: `tests/test_wofs_cache_performance.py`
- Modify: `pyproject.toml`
- Modify: `docs/guide.md`

**Interfaces:**
- Benchmark emits JSON containing raw runs, medians, improvements, graph/query/source counts, peak RSS when available, cache bytes, package versions, and SHA-256 output digests.
- Exit code is nonzero only for execution errors, exactness failures, or hard-gate failures; missing target/stretch is reported without failing once the 20% hard gate passes.

- [ ] **Step 1: Register markers and add subprocess contract test**

Add to `pyproject.toml` markers:

```toml
  "network: requires external DEA/STAC access",
  "performance: opt-in wall-clock performance gate",
```

Create `tests/test_wofs_cache_performance.py`:

```python
import json
import os
import subprocess
import sys

import pytest


@pytest.mark.network
@pytest.mark.performance
def test_real_wofs_cache_performance_gates(tmp_path):
    if os.environ.get("HYDROSEASON_RUN_WOFS_PERF") != "1":
        pytest.skip("set HYDROSEASON_RUN_WOFS_PERF=1")
    output = tmp_path / "benchmark.json"
    completed = subprocess.run(
        [sys.executable, "scripts/benchmark_wofs_cache.py", "--output", str(output), "--runs", "3"],
        check=False, text=True, capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["gilbert"]["cold_median_improvement"] >= 0.20
    assert result["fitzroy"]["cold_median_regression"] <= 0.10
    assert result["gilbert"]["cached_median_improvement"] >= 0.80
    assert result["gilbert"]["cached_stac_calls"] == 0
    assert result["exact_output_equality"] is True
```

- [ ] **Step 2: Run the opt-in test without the environment flag**

Run: `python -m pytest tests\test_wofs_cache_performance.py -q`

Expected: `1 skipped`.

- [ ] **Step 3: Implement the benchmark harness**

The script runs each command in a fresh subprocess and distinct application-cache directory. Benchmark exactly:

- Gilbert: `data/Gilbert_river_buffer.geojson`, 2015, 30 m, current shared-item tiled baseline with explicit `tile_pixels=1024` and `precompute_wet_aoi=True` versus canonical-cache cold acquisition, three runs.
- Fitzroy: `data/fitzroy_kimberley_aoi.geojson`, 2015, 30 m, the same explicit current baseline versus canonical-cache cold acquisition, three runs.
- Gilbert cached: completed canonical cache, three offline runs.

Before fixing GDAL defaults, run the Gilbert and Fitzroy cold cases with the inherited environment, `VSI_CACHE=FALSE`, and `VSI_CACHE=TRUE` plus `VSI_CACHE_SIZE=8388608`. Promote a non-default setting only when its three-run median improves both AOIs by at least 5%, exact output digests match, and peak RSS does not rise by more than 10%; otherwise retain caller-overridable current defaults. Record every A/B result in the benchmark JSON.

Use `time.perf_counter()` around the full acquisition-plus-extent call. Serialize each DataFrame with stable column order, index format `%Y-%m-%d`, newline `\n`, and float format `%.17g`; SHA-256 those bytes and assert `pd.testing.assert_frame_equal(legacy, cached, check_exact=True)`. Count calls by enabling a benchmark-only callback passed into acquisition diagnostics; do not parse log text.

Compute:

```python
cold_improvement = (median(legacy_seconds) - median(cache_cold_seconds)) / median(legacy_seconds)
cold_regression = (median(cache_cold_seconds) - median(legacy_seconds)) / median(legacy_seconds)
cached_improvement = (median(legacy_seconds) - median(cache_warm_seconds)) / median(legacy_seconds)
```

Write the JSON atomically even when a gate fails, then return exit code `2` for hard performance gates and `3` for equality/source-count failures. Record target `>=0.35` and stretch `>=0.40` booleans separately.

- [ ] **Step 4: Add deterministic source-read and graph-count regression tests**

Use a Dask delayed source counter shared by cache writes and local count outputs. Assert one execution when passed to one `dask.compute` call, one query for 2015-2016, and one graph build for each uncached year. Keep these in `tests/test_io_wofs_acquire.py`; no timing assertion enters default CI.

- [ ] **Step 5: Run the full deterministic focused suite**

Run:

```powershell
python -m pytest tests\test_spatial_plan.py tests\test_io_wofs_zarr.py tests\test_io_wofs_acquire.py tests\test_io.py tests\test_io_extent_cache.py tests\test_wet_aoi.py tests\test_extract_water_extent_csv.py tests\test_run_multi_catchment_report.py tests\test_package_surface.py -q
```

Expected: PASS, with the real performance test skipped unless explicitly selected.

- [ ] **Step 6: Run the real three-run gate**

Run:

```powershell
$env:HYDROSEASON_RUN_WOFS_PERF='1'
python -m pytest tests\test_wofs_cache_performance.py -m "network and performance" -v
```

Expected: exact output equality; Gilbert hard `>=20%`; target/stretch status recorded; Fitzroy regression `<=10%`; cached improvement `>=80%`; cached STAC calls `0`.

- [ ] **Step 7: Commit benchmark and gates**

```powershell
git add scripts\benchmark_wofs_cache.py tests\test_wofs_cache_performance.py tests\test_io_wofs_acquire.py pyproject.toml docs\guide.md
git commit -m "test: gate WOfS cache correctness and performance"
```

---

## Final Verification

- [ ] Run `python -m pytest -q`; expected: all default tests PASS, network/performance test SKIPPED.
- [ ] Run `git diff --check`; expected: no whitespace errors.
- [ ] Run `git status --short`; expected: only intentional implementation files, while pre-existing user changes remain untouched.
- [ ] Inspect one store and confirm layout `output/wofs_cache/<identity>.zarr/years/<year>/water_mask` plus manifest/index and wet-AOI sidecar.
- [ ] Disconnect network or block the STAC seam, run the extraction CLI with `--offline`, and confirm byte-identical CSV plus zero STAC calls.
- [ ] Interrupt a multi-year acquisition, rerun it, and confirm completed annual groups are not recomputed.
- [ ] Confirm benchmark JSON reports hard/target/stretch results, exact digest equality, task/chunk counts, cache bytes, and environment versions.

## Completion Criteria

- One full-interval STAC query.
- One shared `stac_load` graph per uncached year.
- No per-tile `stac_load` rebuild.
- No remote wet-AOI or reconciliation reread.
- Completed annual cache groups resume safely.
- Offline hit uses zero STAC calls; offline miss is explicit.
- 30 m extent frame is exactly equal to the legacy mode-resampled result.
- Gilbert/Fitzroy/cached hard performance gates pass; target and stretch are reported.
- CSV-only use remains independent of raster/STAC imports.
