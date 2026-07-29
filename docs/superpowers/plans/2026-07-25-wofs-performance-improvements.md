# WOfS Performance Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce cold WOfS acquisition wall-clock time as far as exact-output and bounded-memory constraints allow, while making cached resumes effectively immediate.

**Architecture:** Keep the existing one-STAC-query, one-shared-Dask-graph-per-year architecture. First remove work that is provably unnecessary: plan directly on the 512-pixel execution/storage grid, stop forcing a losing worker count, reuse larger bounded compute batches, and emit monthly extent counts during the existing write pass. Then promote polygon STAC search, metadata caching, same-grid resampling bypass, and AOI concurrency only after repeatable exact-output benchmarks pass.

**Tech Stack:** Python 3.10+, pandas, NumPy, xarray, Dask, odc-stac, pystac-client, rasterio/rioxarray, Zarr v2, pytest, tqdm.

## Global Constraints

- Preserve exact canonical mask values `{-2, -1, 0, 1}` and exact monthly extent DataFrame equality.
- Preserve WOfS categorical semantics: majority composition and `mode` resampling whenever an actual grid change occurs.
- Preserve one STAC catalog query per uncached request and zero STAC calls on a complete cache hit.
- Preserve one shared `odc.stac.stac_load` graph per non-empty calendar year; do not rebuild it once per spatial tile.
- Preserve atomic annual publication, resumability, offline behavior, and existing cache compatibility.
- Keep peak resident memory within 125% of the current implementation in real-data benchmarks.
- Do not make network performance tests part of the default unit-test run.
- Do not alter existing user changes outside files named by a task.

## Delivery Phases

- **Phase A — deterministic safe wins:** Tasks 1–4. Each task can merge independently.
- **Phase B — benchmark-gated wins:** Tasks 5–7. Promote each optimization only when its stated gate passes.
- **Phase C — production proof:** Task 8. No performance claim is complete before this task.

## Deliberate Non-Goals

- Do not replace the shared annual graph with one `stac_load` call per tile; existing real evidence shows repeated tile setup can erase pruning gains.
- Do not add cross-year process concurrency in this plan. First measure CPU, network, and memory saturation after batch and AOI concurrency changes. If one-AOI throughput remains under-saturated, write a separate plan that centralizes annual publication and manifest updates before introducing parallel year writers.
- Do not change scientific resolution. Coarser products belong to the existing resolution-fidelity workflow and require separate acceptance gates.

---

### Task 1: Persist Per-Year Performance Diagnostics

**Files:**
- Modify: `hydroseason/_io_wofs_zarr.py:540-930`
- Modify: `hydroseason/_io_wofs_acquire.py:130-424`
- Modify: `tests/test_io_wofs_zarr.py`
- Modify: `tests/test_io_wofs_acquire.py`

**Interfaces:**
- Consumes: existing `AnnualWriteStats`, `write_annual_group`, `_diagnostics_payload`, and acquisition manifest.
- Produces: `AnnualWriteStats.compute_seconds`, `encode_write_seconds`, and `validation_seconds`; per-year diagnostics persisted after each published year.

- [ ] **Step 1: Write failing timing-field tests**

Add assertions to `tests/test_io_wofs_zarr.py`:

```python
def test_annual_writer_reports_non_negative_phase_timings(tmp_path):
    mask = _canonical_cube(shape=(12, 512, 512), fill=1).chunk(
        {"time": 1, "y": 512, "x": 512}
    )
    handle = _handle_for_cube(tmp_path, mask)

    stats = write_annual_group(
        handle,
        2015,
        mask,
        windows=(GridWindow("r0c0", 0, 512, 0, 512),),
        item_ids=("a",),
    )

    assert stats.compute_seconds >= 0.0
    assert stats.encode_write_seconds >= 0.0
    assert stats.validation_seconds >= 0.0
```

Add a test to `tests/test_io_wofs_acquire.py` that mocks two annual writes with distinct timing values and asserts `manifest.json` contains both years under `acquisition.year_diagnostics`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_io_wofs_zarr.py::test_annual_writer_reports_non_negative_phase_timings tests/test_io_wofs_acquire.py -q
```

Expected: FAIL because timing fields and `year_diagnostics` do not exist.

- [ ] **Step 3: Add timing fields and phase accounting**

Extend `AnnualWriteStats` without breaking tests that construct it directly:

```python
@dataclasses.dataclass(frozen=True)
class AnnualWriteStats:
    year: int
    task_count: int
    chunks_considered: int
    chunks_written: int
    loaded_pixels: int
    item_digest: str
    compute_seconds: float = 0.0
    encode_write_seconds: float = 0.0
    validation_seconds: float = 0.0
```

In `write_annual_group`, accumulate `time.perf_counter()` durations around:

```python
compute_started = time.perf_counter()
computed_blocks = dask.compute(*blocks_to_compute, **compute_kwargs)
compute_seconds += time.perf_counter() - compute_started

write_started = time.perf_counter()
# Start this timer immediately before content_hasher.update for the block.
# Stop it immediately after the block's clear_count assignment.
encode_write_seconds += time.perf_counter() - write_started

validation_started = time.perf_counter()
validate_annual_group(
    temp_path,
    expected_year=year,
    expected_shape=expected_shape,
    expected_transform=expected_transform,
)
validation_seconds = time.perf_counter() - validation_started
```

Return all three values in `AnnualWriteStats`.

- [ ] **Step 4: Persist progress after every completed year**

In `_io_wofs_acquire.py`, write a compact progress payload after `write_annual_group` returns:

```python
year_diagnostic = {
    "year": int(year),
    "item_count": len(item_ids),
    "selected_tile_pixels": plan.selected_tile_pixels,
    "n_windows": len(plan.windows),
    "task_count": stats.task_count,
    "chunks_considered": stats.chunks_considered,
    "chunks_written": stats.chunks_written,
    "loaded_pixels": stats.loaded_pixels,
    "compute_seconds": stats.compute_seconds,
    "encode_write_seconds": stats.encode_write_seconds,
    "validation_seconds": stats.validation_seconds,
}
```

Add `_write_acquisition_progress(handle, query_seconds, year_diagnostics)` using the existing atomic JSON writer. Preserve prior completed diagnostics when a resumed invocation adds another year. The final `_write_acquisition_manifest` must use the same schema instead of replacing it.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m pytest tests/test_io_wofs_zarr.py tests/test_io_wofs_acquire.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit diagnostics**

```powershell
git add hydroseason/_io_wofs_zarr.py hydroseason/_io_wofs_acquire.py tests/test_io_wofs_zarr.py tests/test_io_wofs_acquire.py
git commit -m "perf: persist annual WOfS phase timings"
```

---

### Task 2: Plan Directly on the 512-Pixel Execution Grid

**Files:**
- Modify: `hydroseason/_spatial_plan.py`
- Modify: `hydroseason/_io_wofs_acquire.py:325-405`
- Modify: `tests/test_spatial_plan.py`
- Modify: `tests/test_io_wofs_acquire.py`

**Interfaces:**
- Consumes: `GridWindow`, parent grid shape/transform, AOI or supplied wet-AOI geometry, `_STORAGE_CHUNK=512`.
- Produces: `plan_storage_aligned_slices(geometry, *, shape, transform, storage_chunk=512) -> SpatialPlan`.

- [ ] **Step 1: Write failing storage-plan tests**

Add to `tests/test_spatial_plan.py`:

```python
def test_storage_aligned_plan_returns_only_intersecting_execution_chunks():
    geometry = box(0, 0, 20, 100)
    plan = plan_storage_aligned_slices(
        geometry,
        shape=(100, 100),
        transform=Affine(1, 0, 0, 0, -1, 100),
        storage_chunk=25,
    )

    assert plan.selected_tile_pixels == 25
    assert [window.tile_id for window in plan.windows] == [
        "r0c0", "r1c0", "r2c0", "r3c0"
    ]
    assert all(window.x_start == 0 and window.x_stop == 25 for window in plan.windows)


def test_storage_aligned_plan_never_expands_back_to_coarser_windows():
    geometry = box(0, 0, 20, 100)
    plan = plan_storage_aligned_slices(
        geometry,
        shape=(100, 100),
        transform=Affine(1, 0, 0, 0, -1, 100),
        storage_chunk=25,
    )

    assert sum(
        (w.y_stop - w.y_start) * (w.x_stop - w.x_start)
        for w in plan.windows
    ) == 4 * 25 * 25
```

- [ ] **Step 2: Run tests and verify failure**

```powershell
python -m pytest tests/test_spatial_plan.py -q
```

Expected: FAIL because `plan_storage_aligned_slices` is undefined.

- [ ] **Step 3: Implement exact execution-grid planning**

Add this entry point to `_spatial_plan.py`:

```python
def plan_storage_aligned_slices(
    geometry,
    *,
    shape: tuple[int, int],
    transform: Affine,
    storage_chunk: int = 512,
) -> SpatialPlan:
    if storage_chunk < 1:
        raise ValueError("storage_chunk must be at least 1")
    height, width = shape
    if height < 1 or width < 1:
        raise ValueError(f"shape must have positive dimensions, got {shape!r}")

    windows = tuple(
        window
        for window in _grid_windows(storage_chunk, height, width)
        if _window_polygon(window, transform).intersects(geometry)
    )
    selected_pixels = sum(
        (window.y_stop - window.y_start) * (window.x_stop - window.x_start)
        for window in windows
    )
    score = CandidateScore(
        tile_pixels=storage_chunk,
        n_tiles=len(windows),
        intersecting_pixels=selected_pixels,
        predicted_cost=float(selected_pixels),
        relative_improvement=0.0,
        windows=windows,
    )
    return SpatialPlan(
        selected_tile_pixels=storage_chunk,
        windows=windows,
        candidates=(score,),
        reason="storage-aligned shared-graph execution",
        planner_version=_PLANNER_VERSION,
    )
```

Export it in `__all__`. Keep `plan_spatial_slices` unchanged for legacy independent-tile loading.

- [ ] **Step 4: Route canonical acquisition through storage-aligned planning**

In `_io_wofs_acquire.py`, replace the canonical call to `plan_spatial_slices`:

```python
plan = plan_storage_aligned_slices(
    pruning_geom,
    shape=tuple(int(v) for v in parent_geobox.shape),
    transform=parent_geobox.affine,
    storage_chunk=512,
)
```

Do not change `build_wofs_year_graph`: it must still receive `parent_geobox` once per year. Do not call `stac_load` once per returned window.

- [ ] **Step 5: Assert writer receives exact 512 windows**

Update `tests/test_io_wofs_acquire.py` so the mocked writer captures `windows`. Assert every non-edge window starts at a multiple of 512 and is at most 512 pixels in each direction. Assert a synthetic thin AOI produces fewer windows than the former 1024 selection.

- [ ] **Step 6: Run planner and acquisition tests**

```powershell
python -m pytest tests/test_spatial_plan.py tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py -q
```

Expected: PASS.

- [ ] **Step 7: Record production geometry proof**

Run the existing six local catchment geometries through both planners without network access. Store JSON at `output/wofs_planner_comparison.json`; do not commit generated output. Required new-plan counts:

```text
daly_river_nt: 287
fitzroy_river_wa: 489
gilbert_river_qld: 142
lachlan_river_nsw: 395
moonie_river_qld_nsw: 96
paroo_river_qld_nsw: 379
```

Expected: 12.5–26.0% fewer execution chunks than the current planner.

- [ ] **Step 8: Commit storage-aligned planning**

```powershell
git add hydroseason/_spatial_plan.py hydroseason/_io_wofs_acquire.py tests/test_spatial_plan.py tests/test_io_wofs_acquire.py
git commit -m "perf: prune WOfS reads on storage chunk grid"
```

---

### Task 3: Remove Forced Worker Count and Tune Bounded Compute Batches

**Files:**
- Modify: `hydroseason/_io_wofs_zarr.py:703-930`
- Modify: `hydroseason/_io_wofs_acquire.py:186-424`
- Modify: `hydroseason/_io_extent_cache.py:380-644`
- Modify: `hydroseason/io.py`
- Modify: `scripts/extract_water_extent_csv.py`
- Modify: `scripts/benchmark_wofs_cache.py`
- Modify: `tests/test_io_wofs_zarr.py`
- Modify: `tests/test_io_wofs_acquire.py`
- Modify: `tests/test_extract_water_extent_csv.py`

**Interfaces:**
- Consumes: storage-aligned windows from Task 2.
- Produces: keyword parameters `compute_batch_size: int = 16` and `read_workers: int | None = None` on `write_annual_group`; matching parameters threaded through acquisition and CLI.

- [ ] **Step 1: Write failing scheduler tests**

Add tests that monkeypatch `dask.compute` and capture keyword arguments:

```python
def test_annual_writer_leaves_dask_worker_count_unset_by_default(monkeypatch, tmp_path):
    seen = []
    real_compute = dask.compute

    def capture(*args, **kwargs):
        seen.append(kwargs.copy())
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(dask, "compute", capture)
    mask = _canonical_cube(shape=(12, 512, 512), fill=1).chunk(
        {"time": 1, "y": 512, "x": 512}
    )
    write_annual_group(
        _handle_for_cube(tmp_path, mask),
        2015,
        mask,
        windows=(GridWindow("r0c0", 0, 512, 0, 512),),
        item_ids=("a",),
    )

    assert seen
    assert all("num_workers" not in kwargs for kwargs in seen)


def test_annual_writer_honours_explicit_worker_override(monkeypatch, tmp_path):
    seen = []
    real_compute = dask.compute

    def capture(*args, **kwargs):
        seen.append(kwargs.copy())
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(dask, "compute", capture)
    mask = _canonical_cube(shape=(12, 512, 512), fill=1).chunk(
        {"time": 1, "y": 512, "x": 512}
    )
    write_annual_group(
        _handle_for_cube(tmp_path, mask),
        2015,
        mask,
        windows=(GridWindow("r0c0", 0, 512, 0, 512),),
        item_ids=("a",),
        read_workers=3,
    )

    assert any(kwargs.get("num_workers") == 3 for kwargs in seen)
```

Add a test with 17 spatial windows and `compute_batch_size=8`; assert `dask.compute` is invoked three times with output counts 8, 8, and 1.

- [ ] **Step 2: Run tests and verify failure**

```powershell
python -m pytest tests/test_io_wofs_zarr.py -q
```

Expected: FAIL because batching and worker settings are hardcoded.

- [ ] **Step 3: Add validated scheduling parameters**

Change the writer signature:

```python
def write_annual_group(
    handle,
    year,
    mask,
    *,
    windows,
    item_ids,
    overwrite=False,
    compute_batch_size: int = 16,
    read_workers: int | None = None,
) -> AnnualWriteStats:
    if compute_batch_size < 1:
        raise ValueError("compute_batch_size must be at least 1")
    if read_workers is not None and read_workers < 1:
        raise ValueError("read_workers must be positive or None")
```

Replace fixed scheduling:

```python
compute_kwargs = {}
if read_workers is not None:
    compute_kwargs = {"scheduler": "threads", "num_workers": read_workers}

for i in range(0, len(keys_list), compute_batch_size):
    batch_keys = keys_list[i : i + compute_batch_size]
    computed_blocks = dask.compute(*blocks_to_compute, **compute_kwargs)
```

Default batch 16 bounds materialized int8 output near 48 MiB for 12 full 512×512 blocks, before scheduler working memory.

- [ ] **Step 4: Thread parameters through public acquisition**

Add `compute_batch_size=16` and `read_workers=None` to `acquire_wofs_cache`, then pass both to `write_annual_group`. In the canonical mask-cache branch of `load_wofs_monthly_extent`, pass the existing `read_workers` value into acquisition and add a `compute_batch_size=16` keyword. Export signatures through `hydroseason/io.py` without changing positional arguments.

- [ ] **Step 5: Make CLI flags control the actual remote acquisition**

Add:

```python
parser.add_argument(
    "--compute-batch-size",
    type=int,
    default=16,
    help="spatial 512px blocks per bounded Dask compute call (default: 16)",
)
```

Pass `compute_batch_size=args.compute_batch_size`. Update `--read-workers` help to say it controls both canonical acquisition and local reduction. Keep `0` mapped to `None` before calling the API.

- [ ] **Step 6: Extend benchmark configuration**

Add hidden child arguments and public repeatable settings to `scripts/benchmark_wofs_cache.py`:

```text
--compute-batch-size 4,8,16,32
--read-workers 0,4,8
--cases gilbert,fitzroy
```

Record selected values in every run payload. Preserve exact DataFrame/digest and RSS gates.

- [ ] **Step 7: Run unit tests**

```powershell
python -m pytest tests/test_io_wofs_zarr.py tests/test_io_wofs_acquire.py tests/test_io_extent_cache.py tests/test_extract_water_extent_csv.py tests/test_wofs_cache_performance.py -q
```

Expected: PASS, real performance test skipped unless explicitly enabled.

- [ ] **Step 8: Run real one-year scheduling matrix**

Run three isolated repetitions for Gilbert and Fitzroy. Promotion rule:

- exact DataFrame equality for every candidate;
- median cold runtime at least 5% faster on Gilbert;
- Fitzroy regression no worse than 5%;
- median peak RSS no more than 125% of batch 4;
- select lowest median runtime satisfying every gate.

If batch 16 fails a gate, retain batch 4 as default but keep configurable parameters. Always retain `read_workers=None` as default unless an explicit count wins both AOIs by at least 5%.

- [ ] **Step 9: Commit scheduling changes**

```powershell
git add hydroseason/_io_wofs_zarr.py hydroseason/_io_wofs_acquire.py hydroseason/_io_extent_cache.py hydroseason/io.py scripts/extract_water_extent_csv.py scripts/benchmark_wofs_cache.py tests/test_io_wofs_zarr.py tests/test_io_wofs_acquire.py tests/test_extract_water_extent_csv.py tests/test_wofs_cache_performance.py
git commit -m "perf: tune bounded WOfS compute scheduling"
```

---

### Task 4: Emit Monthly Extent Counts During Annual Writes

**Files:**
- Modify: `hydroseason/_io_wofs_zarr.py`
- Modify: `hydroseason/_io_extent_cache.py:571-644`
- Modify: `tests/test_io_wofs_zarr.py`
- Modify: `tests/test_io_extent_cache.py`

**Interfaces:**
- Consumes: canonical int8 `values` already materialized by `write_annual_group`.
- Produces: optional backward-compatible `extent_counts.json` inside each annual group; `open_completed_extent_counts(handle, start_date, end_date) -> pd.DataFrame | None`.

- [ ] **Step 1: Write failing annual-count exactness test**

Add to `tests/test_io_wofs_zarr.py`:

```python
def test_annual_writer_persists_exact_monthly_extent_counts(tmp_path):
    mask = _canonical_cube(shape=(2, 2, 3), fill=-2)
    mask.values[0] = [[1, 0, -1], [-2, 1, 0]]
    mask.values[1] = [[0, 0, -1], [-2, 1, 1]]
    handle = _handle_for_cube(tmp_path, mask)

    write_annual_group(
        handle,
        2015,
        mask.chunk({"time": 1, "y": 2, "x": 3}),
        windows=(GridWindow("r0c0", 0, 2, 0, 3),),
        item_ids=("a",),
    )
    extent = open_completed_extent_counts(handle, "2015-01-01", "2015-02-01")

    assert extent["n_aoi"].tolist() == [5, 5]
    assert extent["n_valid"].tolist() == [4, 4]
    assert extent["n_water"].tolist() == [2, 2]
    assert extent["n_invalid"].tolist() == [1, 1]
    assert extent["extent_pct"].tolist() == [50.0, 50.0]
    assert extent["invalid_pct"].tolist() == [20.0, 20.0]
```

- [ ] **Step 2: Write backward-compatibility test**

Create an annual group using `_canonical_cube(shape=(12, 2, 2), fill=0)`, delete only `handle.path / "years" / "2015" / "extent_counts.json"`, then assert `open_completed_extent_counts(handle, "2015-01-01", "2015-12-31") is None` while `completed_years(handle) == {2015}`. This proves existing expensive caches remain valid.

- [ ] **Step 3: Run tests and verify failure**

```powershell
python -m pytest tests/test_io_wofs_zarr.py -q
```

Expected: FAIL because extent-count API and sidecar do not exist.

- [ ] **Step 4: Accumulate counts in the existing write pass**

Initialize `np.int64` arrays of length `time_len` before the block loop:

```python
n_aoi = np.zeros(time_len, dtype=np.int64)
n_valid = np.zeros(time_len, dtype=np.int64)
n_water = np.zeros(time_len, dtype=np.int64)
n_invalid = np.zeros(time_len, dtype=np.int64)
```

For each computed block:

```python
block_water = (values == 1).sum(axis=(1, 2), dtype=np.int64)
block_dry = (values == 0).sum(axis=(1, 2), dtype=np.int64)
block_aoi = (values != -2).sum(axis=(1, 2), dtype=np.int64)
n_water += block_water
n_valid += block_water + block_dry
n_aoi += block_aoi
n_invalid += block_aoi - block_water - block_dry
```

Write `extent_counts.json` atomically inside the temporary annual directory before `complete.json`. Include schema version, dates, four integer arrays, and SHA-256 of canonical JSON payload. Do not bump `WOFS_CACHE_SCHEMA_VERSION`; the artifact is an optional acceleration for old caches.

- [ ] **Step 5: Implement count reader**

Add:

```python
def open_completed_extent_counts(
    handle: WOfSCacheHandle,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
```

Read every requested annual sidecar. Return `None` if any requested completed year lacks one. Validate digest, time axis, non-negative counts, `n_water <= n_valid <= n_aoi`, and `n_invalid == n_aoi - n_valid`. Build columns matching `monthly_water_extent`, setting `n_wet_aoi=n_valid` and `wet_fill_pct=extent_pct` when no wet AOI is requested.

- [ ] **Step 6: Use counts before reopening masks**

In the canonical mask-cache branch of `load_wofs_monthly_extent`:

```python
if wet_aoi is None and not precompute_wet_aoi:
    extent = _io.open_completed_extent_counts(handle, start_date, end_date)
    if extent is not None:
        # Call _write_requested_annual_extent_parts with the same cache_root,
        # request identity, date, majority, wet_aoi_hash, and force keywords
        # used by the existing raster-reduction branch.
        return extent
```

Fall back to `open_completed_mask_cache` plus `monthly_water_extent` for old groups or real wet-AOI calculations.

- [ ] **Step 7: Prove exact equality against raster reduction**

Create randomized canonical cubes spanning multiple 512 chunks, write them, then compare:

```python
pd.testing.assert_frame_equal(
    open_completed_extent_counts(handle, start, end),
    monthly_water_extent(open_completed_mask_cache(handle, start, end), time_block=12),
    check_exact=True,
)
```

- [ ] **Step 8: Run focused tests**

```powershell
python -m pytest tests/test_io_wofs_zarr.py tests/test_io_extent_cache.py tests/test_monthly_water_extent_streaming.py -q
```

Expected: PASS.

- [ ] **Step 9: Avoid validating implicit fill chunks**

Track each assigned water-mask chunk as a Zarr chunk index:

```python
written_chunk_keys.append([t, cy // _STORAGE_CHUNK, cx // _STORAGE_CHUNK])
```

Persist sorted unique keys in `complete.json`. In `validate_annual_group`, retain physical chunk-count verification, then read and validate only listed stored chunks. Unlisted chunks are represented by Zarr's declared int8 fill value `-2`, already inside the canonical domain. For old groups without `written_chunk_keys`, retain the current full logical-grid scan.

Add a test with one written and one implicit-fill spatial chunk. Monkeypatch the helper that yields validation slices and assert only the written chunk is returned for a new payload, while a payload without `written_chunk_keys` returns both chunks.

- [ ] **Step 10: Re-run writer tests**

```powershell
python -m pytest tests/test_io_wofs_zarr.py tests/test_io_extent_cache.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit one-pass counts**

```powershell
git add hydroseason/_io_wofs_zarr.py hydroseason/_io_extent_cache.py tests/test_io_wofs_zarr.py tests/test_io_extent_cache.py
git commit -m "perf: emit extent counts during WOfS cache writes"
```

---

### Task 5: Cache STAC Item Metadata and Search by AOI Polygon

**Files:**
- Create: `hydroseason/_io_stac_cache.py`
- Modify: `hydroseason/_io_geo.py:194-222`
- Modify: `hydroseason/_io_wofs_acquire.py:186-424`
- Modify: `hydroseason/_io_extent_cache.py`
- Modify: `tests/test_io.py`
- Create: `tests/test_io_stac_cache.py`

**Interfaces:**
- Consumes: endpoint, collection, AOI digest, date range, pystac Items.
- Produces: `STACItemCacheKey`; `load_cached_items`; `write_cached_items`; and new `_query_wofs_items` keywords `item_cache_root=None` and `force_item_refresh=False`.

- [ ] **Step 1: Write failing cache-key and round-trip tests**

Create `tests/test_io_stac_cache.py` covering:

```python
def test_item_cache_key_excludes_output_resolution():
    left = STACItemCacheKey(
        stac_url="https://example.test/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="1986-05-01",
        end_date="2026-06-01",
    )
    assert left.digest() == dataclasses.replace(left).digest()


def test_item_cache_round_trip_preserves_item_dicts(tmp_path):
    items = [pystac.Item.from_dict(_item_dict("a")), pystac.Item.from_dict(_item_dict("b"))]
    write_cached_items(tmp_path, key, items, fetched_at="2026-07-25T00:00:00Z")
    loaded = load_cached_items(tmp_path, key, now="2026-07-25T01:00:00Z")
    assert [item.to_dict() for item in loaded] == [item.to_dict() for item in items]
```

Also test corrupt JSON returns `None`, historical ranges do not expire, and a range ending in the current year expires after 24 hours.

- [ ] **Step 2: Run cache tests and verify failure**

```powershell
python -m pytest tests/test_io_stac_cache.py -q
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement atomic item metadata cache**

Define:

```python
@dataclasses.dataclass(frozen=True)
class STACItemCacheKey:
    stac_url: str
    collection: str
    aoi_sha256: str
    start_date: str
    end_date: str

    def digest(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(dataclasses.asdict(self))).hexdigest()
```

Store under `<mask_cache_root>/.stac-items/<digest>.json`. Payload contains key, `fetched_at`, and `pystac.ItemCollection(items).to_dict()`. Historical ranges ending before the current UTC year never expire. Ranges touching the current year expire after 24 hours. Use temporary file plus `os.replace`.

- [ ] **Step 4: Write failing polygon-search test**

In `tests/test_io.py`, mock `pystac_client.Client.open`, call `_query_wofs_items`, and assert:

```python
search.assert_called_once()
kwargs = search.call_args.kwargs
assert "intersects" in kwargs
assert "bbox" not in kwargs
assert kwargs["limit"] == 1000
```

Use a multi-feature AOI and assert the transmitted GeoJSON equals the union geometry in EPSG:4326.

- [ ] **Step 5: Integrate polygon search and cache**

Change `_query_wofs_items` to calculate:

```python
aoi_4326 = aoi_gdf.to_crs("EPSG:4326")
geometry = (
    aoi_4326.geometry.union_all()
    if hasattr(aoi_4326.geometry, "union_all")
    else aoi_4326.geometry.unary_union
)
search_kwargs = {
    "collections": [collection],
    "datetime": f"{start:%Y-%m-%d}/{end:%Y-%m-%d}",
    "intersects": geometry.__geo_interface__,
    "limit": 1000,
}
```

Read exact-range item cache before opening the client. After a successful stable sort, write it. Pass cache root and AOI digest from `acquire_wofs_cache`. Do not use item metadata cache in `offline=True`; offline canonical-mask lookup must remain self-contained and make zero STAC calls.

- [ ] **Step 6: Test query reuse across resolutions**

Call acquisition twice with identical endpoint/collection/AOI/dates but different resolutions and mocked cache handles. Assert `Client.open` and `search.items()` execute once total while both acquisitions receive identical item IDs.

- [ ] **Step 7: Run tests**

```powershell
python -m pytest tests/test_io_stac_cache.py tests/test_io.py tests/test_io_wofs_acquire.py tests/test_io_extent_cache.py -q
```

Expected: PASS.

- [ ] **Step 8: Run real item-count gate**

For Gilbert and Fitzroy 2015, compare bbox versus polygon search. Promotion rules:

- polygon result IDs must equal the subset of bbox result IDs whose item footprint intersects the AOI;
- downstream monthly DataFrame must be exactly equal;
- polygon query median must not be more than 10% slower;
- retain polygon search when it reduces item count or query time for either AOI without failing another gate.

- [ ] **Step 9: Commit STAC query improvements**

```powershell
git add hydroseason/_io_stac_cache.py hydroseason/_io_geo.py hydroseason/_io_wofs_acquire.py hydroseason/_io_extent_cache.py tests/test_io_stac_cache.py tests/test_io.py
git commit -m "perf: cache WOfS STAC items and query AOI polygons"
```

---

### Task 6: Skip Mode Resampling Only on Proven Native-Aligned Grids

**Files:**
- Modify: `hydroseason/_io_geo.py:234-523`
- Create: `scripts/compare_wofs_resampling.py`
- Modify: `tests/test_io.py`
- Modify: `tests/test_wofs_cache_performance.py`

**Interfaces:**
- Consumes: parsed WOfS `water` band source GeoBoxes and destination GeoBox.
- Produces: `_all_sources_native_aligned(items, geobox, band="water") -> bool`; `build_wofs_year_graph` selects omitted/default resampling only when true.

- [ ] **Step 1: Write failing grid-alignment tests**

Add unit tests using synthetic `GeoBox` objects:

```python
@pytest.mark.parametrize(
    "source_crs, source_resolution, x_shift, y_shift, expected",
    [
        (3577, 30, 0, 0, True),
        (3577, 30, 30, -60, True),
        (3577, 30, 15, 0, False),
        (3577, 60, 0, 0, False),
        (4326, 30, 0, 0, False),
    ],
)
def test_native_grid_alignment(
    source_epsg, source_resolution, x_shift, y_shift, expected
):
    destination = GeoBox(
        (10, 10), Affine(30, 0, 0, 0, -30, 300), CRS("EPSG:3577")
    )
    source = GeoBox(
        (10, 10),
        Affine(
            source_resolution,
            0,
            x_shift,
            0,
            -source_resolution,
            300 + y_shift,
        ),
        CRS(f"EPSG:{source_epsg}"),
    )
    assert _geobox_native_aligned(source, destination) is expected
```

Import `Affine` from `affine` and `CRS`, `GeoBox` from `odc.geo` in the test module.

Add a test where any one parsed item lacks a `water` source GeoBox; `_all_sources_native_aligned` must return `False` and preserve `mode`.

- [ ] **Step 2: Run alignment tests and verify failure**

```powershell
python -m pytest tests/test_io.py -k "native_grid_alignment or sources_native_aligned" -q
```

Expected: FAIL because helpers do not exist.

- [ ] **Step 3: Implement conservative alignment detection**

Use `odc.stac.parse_items(items)`, `parsed.resolve_bands([band])[band].geobox`, and require every source to satisfy:

```python
source.crs == destination.crs
math.isclose(abs(source.resolution.x), abs(destination.resolution.x))
math.isclose(abs(source.resolution.y), abs(destination.resolution.y))
x_offset = (destination.affine.c - source.affine.c) / destination.resolution.x
y_offset = (destination.affine.f - source.affine.f) / destination.resolution.y
math.isclose(x_offset, round(x_offset), abs_tol=1e-9)
math.isclose(y_offset, round(y_offset), abs_tol=1e-9)
```

Return `False` on missing metadata, rotated/sheared transforms, differing CRS, differing resolution, or fractional-pixel offset.

- [ ] **Step 4: Add explicit resampling policy**

Add `resampling_policy: Literal["categorical_safe", "native_aligned"] = "categorical_safe"` to `build_wofs_year_graph`. Resolve:

```python
resampling = "mode"
if resampling_policy == "native_aligned" and _all_sources_native_aligned(items, geobox):
    resampling = None
```

Pass the resolved value into `_load_wofs_items`. Keep public legacy AOI+resolution loading on `mode` because its output GeoBox alignment is not proven at that call boundary.

- [ ] **Step 5: Create exact-value real-data comparator**

`scripts/compare_wofs_resampling.py` must:

- query one AOI/year once;
- choose every 512 window intersecting the AOI;
- compute `categorical_safe` and `native_aligned` outputs from the same item snapshot;
- record graph seconds, compute seconds, exact array equality, differing pixels per month, output digests, and package versions;
- exit 0 only when outputs are byte-identical;
- write JSON even on mismatch.

CLI:

```text
python scripts/compare_wofs_resampling.py \
  --aoi data/Gilbert_river_buffer.geojson \
  --year 2015 \
  --output output/gilbert_resampling_2015.json
```

- [ ] **Step 6: Run real promotion gate**

Run three repetitions for Gilbert and Fitzroy 2015. Enable `native_aligned` as canonical-cache default only if:

- all six arrays are byte-identical;
- median compute time improves by at least 15% on Gilbert;
- Fitzroy median does not regress by more than 5%;
- every source passes conservative alignment detection.

If any gate fails, keep `categorical_safe` default and retain comparator as diagnostic evidence.

- [ ] **Step 7: Run tests**

```powershell
python -m pytest tests/test_io.py tests/test_io_wofs_acquire.py tests/test_wofs_cache_performance.py -q
```

Expected: PASS; network test remains opt-in.

- [ ] **Step 8: Commit resampling policy**

```powershell
git add hydroseason/_io_geo.py scripts/compare_wofs_resampling.py tests/test_io.py tests/test_wofs_cache_performance.py
git commit -m "perf: bypass WOfS mode resampling on native grids"
```

---

### Task 7: Add Bounded Parallel AOI Extraction

**Files:**
- Modify: `scripts/extract_water_extent_csv.py:62-245`
- Modify: `tests/test_extract_water_extent_csv.py`
- Modify: `docs/guide.md`

**Interfaces:**
- Consumes: independent `(name, AOI path)` jobs, per-acquisition batch/worker settings from Task 3.
- Produces: `--workers` and `--memory-budget-gb`; concurrent execution preserving output/timing order.

- [ ] **Step 1: Write failing CLI and concurrency tests**

Add tests:

```python
def test_parser_defaults_to_two_parallel_aoi_workers():
    args = _build_arg_parser().parse_args([])
    assert args.workers == 2
    assert args.memory_budget_gb == 12.0


def test_run_jobs_preserves_input_order_when_workers_finish_out_of_order(monkeypatch):
    # Mock _process_job so second job completes first.
    results = _run_jobs(jobs, args=args, tile_kwargs={}, workers=2)
    assert [row["catchment"] for row in results] == ["first", "second"]
```

Add validation tests for workers `<1` and memory budget `<=0`.

- [ ] **Step 2: Run tests and verify failure**

```powershell
python -m pytest tests/test_extract_water_extent_csv.py -q
```

Expected: FAIL because options and `_run_jobs` do not exist.

- [ ] **Step 3: Implement bounded threaded execution**

Add:

```python
parser.add_argument("--workers", type=int, default=2)
parser.add_argument("--memory-budget-gb", type=float, default=12.0)
```

Implement `_run_jobs` using the established `ThreadPoolExecutor` pattern from `run_multi_catchment_report.py`. Use `active_workers = min(workers, len(jobs))`, one progress position per active job, and store each result at its original index. Cancel pending futures only after a failure has been recorded; allow running acquisitions to finish their atomic annual group.

- [ ] **Step 4: Bound per-worker compute batch**

Calculate:

```python
per_worker_budget_bytes = args.memory_budget_gb * (1024**3) / active_workers
bytes_per_output_block = args.time_block * 512 * 512
memory_limited_batch = max(1, int(per_worker_budget_bytes // (bytes_per_output_block * 8)))
effective_batch = min(args.compute_batch_size, memory_limited_batch)
```

Factor 8 reserves headroom for source decode, comparison arrays, compression, and scheduler state. Pass `effective_batch` to each job and record it in execution timing CSV.

- [ ] **Step 5: Clarify legacy-only tile flag**

Update `--tile-pixels` help: canonical cache uses storage-aligned 512 planning; this flag controls only `--legacy-remote-path`. Do not imply it changes canonical acquisition.

- [ ] **Step 6: Run tests**

```powershell
python -m pytest tests/test_extract_water_extent_csv.py tests/test_run_multi_catchment_report.py -q
```

Expected: PASS.

- [ ] **Step 7: Benchmark worker count**

Run two representative AOIs for one recent year with workers 1, 2, and 3. Promote highest worker count satisfying:

- exact output equality;
- total wall-clock at least 10% faster than workers 1;
- per-AOI median not more than 25% slower;
- peak combined RSS below configured memory budget;
- no HTTP retry/error increase.

Keep default 2 unless workers 3 passes every gate by at least 5% over workers 2.

- [ ] **Step 8: Document and commit concurrency**

Document CPU/network/memory tradeoffs and recommended `--workers 2`. Then:

```powershell
git add scripts/extract_water_extent_csv.py tests/test_extract_water_extent_csv.py docs/guide.md
git commit -m "perf: run independent WOfS AOIs concurrently"
```

---

### Task 8: Run Production Benchmark Gates and Update Handoff

**Files:**
- Modify: `scripts/benchmark_wofs_cache.py`
- Modify: `tests/test_wofs_cache_performance.py`
- Modify: `docs/PERFORMANCE_HANDOFF.md`
- Modify: `docs/guide.md`

**Interfaces:**
- Consumes: all prior tasks and their diagnostics.
- Produces: reproducible benchmark JSON, updated factual handoff, final promotion verdict per optimization.

- [ ] **Step 1: Add production benchmark modes**

Support:

```text
--planner legacy-cost|storage-aligned
--resampling-policy categorical_safe|native_aligned
--compute-batch-size N
--read-workers N
--workers N
--cases gilbert,fitzroy,moonie
--years 2015,2020
```

Every result must include query, compute, encode/write, validation, and extent-count seconds; item count; execution chunks; bytes; peak RSS; output digest; package versions; and exact selected configuration.

- [ ] **Step 2: Add hard benchmark assertions**

Extend opt-in performance test assertions:

```python
assert result["exact_output_equality"] is True
assert result["warm"]["stac_calls"] == 0
assert result["warm"]["graph_builds"] == 0
assert result["storage_aligned"]["execution_chunks"] < result["legacy_cost"]["execution_chunks"]
assert result["candidate_peak_rss_bytes"] <= result["baseline_peak_rss_bytes"] * 1.25
```

Hard wall-clock gate:

- Gilbert cold median improves at least 20%; target 35%.
- Fitzroy cold median regression is at most 5%.
- Moonie cold median regression is at most 5%.
- Complete cached invocation improves at least 95% and makes zero STAC calls.

- [ ] **Step 3: Run focused correctness suite**

```powershell
python -m pytest tests/test_io.py tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py tests/test_io_extent_cache.py tests/test_spatial_plan.py tests/test_extract_water_extent_csv.py tests/test_wofs_cache_performance.py -q
```

Expected: PASS, network gate skipped.

- [ ] **Step 4: Run full suite**

```powershell
python -m pytest -q
```

Expected: all non-experimental tests pass. Record any pre-existing experimental failure separately; do not weaken its assertion as part of performance work.

- [ ] **Step 5: Run real benchmark**

```powershell
$env:HYDROSEASON_RUN_WOFS_PERF='1'
python scripts/benchmark_wofs_cache.py --output output/wofs_cache_benchmark.json --runs 3 --cases gilbert,fitzroy,moonie
```

Expected: exit 0 and every hard gate passes. Keep JSON out of git unless repository policy explicitly tracks benchmark artifacts.

- [ ] **Step 6: Run one 40-year production proof**

Run Gilbert 1986-05-01 through 2026-06-01 into a fresh cache. Stop and resume once after at least two completed years. Verify:

- completed years are reused;
- item metadata cache is reused;
- annual timings survive interruption;
- resumed output equals uninterrupted output exactly;
- warm CSV invocation performs no Zarr raster reduction;
- peak RSS stays within gate.

- [ ] **Step 7: Correct performance documentation**

Update `docs/PERFORMANCE_HANDOFF.md` with measured medians and remove unsupported `0.1s/tile` / `3–5 seconds per year` estimates. State that wet-AOI sidecars are post-acquisition unless explicitly supplied. Document shared annual graph, storage-aligned 512 pruning, selected batch size, worker policy, item cache lifetime, resampling gate result, and remaining bottleneck.

- [ ] **Step 8: Commit benchmark and documentation**

```powershell
git add scripts/benchmark_wofs_cache.py tests/test_wofs_cache_performance.py docs/PERFORMANCE_HANDOFF.md docs/guide.md
git commit -m "docs: verify WOfS performance improvements"
```

## Final Completion Criteria

- [ ] Six production AOI geometries use exact 512-aligned execution windows.
- [ ] No canonical acquisition forces `num_workers=8` by default.
- [ ] Batch size is bounded, configurable, and selected by real-data evidence.
- [ ] New annual groups contain exact monthly extent-count sidecars.
- [ ] Existing annual groups without count sidecars remain readable.
- [ ] Repeated resolution probes reuse STAC item metadata.
- [ ] Polygon search and native-aligned resampling meet exact-output gates before promotion.
- [ ] Extraction supports bounded concurrent AOIs.
- [ ] Cold Gilbert median improves at least 20%; Fitzroy and Moonie regress no more than 5%.
- [ ] Warm complete-cache invocation makes zero STAC calls and zero annual graph builds.
- [ ] Relevant tests and all non-experimental full-suite tests pass.
