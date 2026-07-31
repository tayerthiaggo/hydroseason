# WOfS Wet-Mask Pruning and Write-Path Performance Implementation Plan

> **Superseded pruning route (2026-07-31):** polygon pruning in this plan is
> compatibility history for `wet_mask="dea_stats"`. New callers should use the
> conservative max-pooled `WetPlanningFootprint` /
> `planning_footprint` route, which proves native wet pixels remain inside
> the analysis footprint through both coarse windows and fine clipping. The
> default remains unpruned. Independent write-path wins from this plan remain
> authoritative, including blake2b content hashing, per-year STAC cache
> identity, empty-year fast path, and other Zarr write-path improvements.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut WOfS acquisition wall-clock time by pruning reads to a pre-computed ever-wet mask derived from DEA Water Observation Statistics, and by removing three independent hot-spots in the Zarr write path.

**Architecture:** A new module `hydroseason/_io_dea_stats.py` fetches the DEA `ga_ls_wo_fq_myear_3` all-time summary (unioned with per-year `ga_ls_wo_fq_cyear_3` for every requested year) and reduces it to a buffered wet-AOI polygon. `acquire_wofs_cache` intersects that polygon with the caller's AOI and threads the result through two levels: the existing 512px `plan_storage_aligned_slices` window selection (coarse), and the per-pixel AOI rasterisation inside `_load_wofs_items` -> `_clip_to_aoi` (fine). Pixels outside the wet mask become `-2`, which the existing all-`-2` block skip in `write_annual_group` already turns into zero Zarr writes. A `wet_mask_sha256` field on `WOfSCacheRequest` keeps pruned and unpruned stores at distinct request digests so they can never mix.

**Tech Stack:** Python 3.11+, xarray, dask, odc-stac, pystac-client, rioxarray, rasterio, geopandas, shapely, zarr, numcodecs, pytest.

## Global Constraints

- All geospatial imports (`geopandas`, `rasterio`, `odc.stac`, `xarray`, `rioxarray`, `pystac_client`) stay **inside function bodies**, never at module top level. This is an established repo rule stated in `hydroseason/_wet_aoi.py`'s module docstring: importing a module must never require the raster/stac extras.
- Canonical mask domain is `CANONICAL_VALUES` with `-2` = outside AOI, `-1` = invalid/nodata, `0` = dry, `1` = water. Never introduce a new sentinel.
- Distances are **metres** (the working CRS is EPSG:3577, Australian Albers). Never express a buffer in pixels.
- The wet mask MUST be a **superset** of every pixel that is ever water in the requested period. A pruned pixel reads as permanently dry with no way to distinguish it from real dry, so the mask must fail *open* (prune nothing) on any doubt.
- `WOFS_CACHE_SCHEMA_VERSION` currently `2` in `hydroseason/_io_wofs_zarr.py:63`. Task 4 bumps it to `3`. Do not bump it in any other task.
- Existing constants, do not change: `MASK_CHUNKS = (1, 512, 512)`, `_STORAGE_CHUNK = 512`, `WOFS_CLASSIFIER_VERSION = 1`, `WOFS_PLANNER_VERSION = 1`.
- Run tests with `python -m pytest` from the repo root `d:\RLH\5.6\repos\hydroseason`.
- No new third-party dependencies. Everything needed is already imported somewhere in the package.

---

## File Structure

**New files:**
- `hydroseason/_io_dea_stats.py` — DEA Water Observation Statistics STAC query and reduction to a wet-AOI polygon. Owns everything specific to the `ga_ls_wo_fq_*` products; nothing else in the package knows those collection names.
- `tests/test_io_dea_stats.py` — unit tests for the above, fully offline (STAC client and raster load are injected).

**Modified files:**
- `hydroseason/_io_wofs_zarr.py` — add `wet_mask_sha256` to `WOfSCacheRequest`; bump schema version; swap the content hasher to blake2b; add the empty-year fast path helper.
- `hydroseason/_io_geo.py` — thread an optional `wet_aoi` through `_load_wofs_items` and `build_wofs_year_graph` into the clip step; make the STAC item cache key per-year.
- `hydroseason/_io_stac_cache.py` — no signature change; the per-year keying happens in `_io_geo._query_wofs_items`.
- `hydroseason/_io_wofs_acquire.py` — resolve the wet mask, put its digest in the request, pass it to the year graph, short-circuit empty years.
- `scripts/extract_water_extent_csv.py` — `--wet-mask` flag; fix the stale `--year-workers` help text.

**Task ordering rationale:** Tasks 1–3 are independent write-path wins with no interface coupling; they land first so the pruning work (Tasks 4–7) is measured against an already-faster baseline. Task 8 is the CLI surface.

---

### Task 1: Replace the per-block content hash with blake2b

`write_annual_group` hashes every loaded pixel with SHA-256 (`hydroseason/_io_wofs_zarr.py:874`), plus an `np.ascontiguousarray` copy per block. For a 40-year continental catchment that is hundreds of GB through a single-threaded hash, and it holds the GIL, which serialises the `year_workers` threads. blake2b is 2–4x faster for the same collision resistance here (the digest is a cache-invalidation fingerprint, not a security boundary).

**Files:**
- Modify: `hydroseason/_io_wofs_zarr.py:823-833` (hasher construction), `hydroseason/_io_wofs_zarr.py:869-876` (per-block update)
- Test: `tests/test_io_wofs_zarr.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a new module-level constant `CONTENT_DIGEST_ALGORITHM: str = "blake2b"` in `hydroseason/_io_wofs_zarr.py`, and a new module-level helper `_content_hasher()` returning a fresh hash object. Task 3 reuses `_content_hasher()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_io_wofs_zarr.py`:

```python
def test_content_hasher_is_blake2b_and_is_fresh_each_call():
    from hydroseason._io_wofs_zarr import CONTENT_DIGEST_ALGORITHM, _content_hasher

    assert CONTENT_DIGEST_ALGORITHM == "blake2b"

    first = _content_hasher()
    assert first.name == "blake2b"

    # Each call must return an independent hasher, never a shared module-level
    # object -- write_annual_group runs concurrently under year_workers, and a
    # shared hasher would interleave two years' bytes into one digest.
    first.update(b"year-1986")
    second = _content_hasher()
    assert second.hexdigest() != first.hexdigest()
    assert second.hexdigest() == _content_hasher().hexdigest()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_io_wofs_zarr.py::test_content_hasher_is_blake2b_and_is_fresh_each_call -v`

Expected: FAIL with `ImportError: cannot import name 'CONTENT_DIGEST_ALGORITHM' from 'hydroseason._io_wofs_zarr'`

- [ ] **Step 3: Add the constant and helper**

In `hydroseason/_io_wofs_zarr.py`, immediately after the `WOFS_PLANNER_VERSION = 1` line (currently line 75), add:

```python
# The per-year content digest is a cache-invalidation fingerprint over the
# pixels actually loaded, not a security boundary, so it is chosen for speed.
# blake2b is 2-4x faster than sha256 on the multi-hundred-GB byte volume a
# continental 40-year acquisition pushes through it, and because hashing holds
# the GIL, that directly unblocks the year_workers threads in
# _io_wofs_acquire.acquire_wofs_cache.
CONTENT_DIGEST_ALGORITHM = "blake2b"


def _content_hasher():
    """A fresh content-digest hash object. Never share one across years."""
    return hashlib.blake2b()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_io_wofs_zarr.py::test_content_hasher_is_blake2b_and_is_fresh_each_call -v`

Expected: PASS

- [ ] **Step 5: Use the helper in write_annual_group and drop the redundant copy**

In `hydroseason/_io_wofs_zarr.py`, replace line 823:

```python
        content_hasher = hashlib.sha256()
```

with:

```python
        content_hasher = _content_hasher()
```

Then replace lines 869-876 (the per-block hash update inside the write loop):

```python
                content_hasher.update(
                    _canonical_json_bytes(
                        {"y_start": cy, "x_start": cx, "shape": list(values.shape)}
                    )
                )
                content_hasher.update(np.ascontiguousarray(values).tobytes())
```

with:

```python
                content_hasher.update(
                    _canonical_json_bytes(
                        {"y_start": cy, "x_start": cx, "shape": list(values.shape)}
                    )
                )
                # dask.compute already returns C-contiguous arrays here, so
                # ascontiguousarray was allocating a full second copy of every
                # block. Assert-and-use instead of copy-always; the fallback
                # covers any future non-contiguous producer.
                content_hasher.update(
                    values.tobytes() if values.flags["C_CONTIGUOUS"]
                    else np.ascontiguousarray(values).tobytes()
                )
```

- [ ] **Step 6: Run the full Zarr test module**

Run: `python -m pytest tests/test_io_wofs_zarr.py -v`

Expected: PASS. Any test asserting a hard-coded `content_digest` hex string will now fail — that is correct, the digest algorithm changed. Update those expected values to the new digests produced by the test run, and add a comment on each noting the blake2b switch. Do **not** revert the algorithm to keep an old constant green.

- [ ] **Step 7: Commit**

```bash
git add hydroseason/_io_wofs_zarr.py tests/test_io_wofs_zarr.py
git commit -m "perf: hash annual content with blake2b and skip redundant block copy"
```

---

### Task 2: Key the STAC item cache per calendar year

`_query_wofs_items` keys its cache on the exact `(start_date, end_date)` pair (`hydroseason/_io_stac_cache.py:26-34`). `acquire_wofs_cache` computes that range from the *missing* years (`hydroseason/_io_wofs_acquire.py:320`), so every resume after a partial failure produces a different range, misses the cache, and refetches all ~18,000 items over the network. Keying per calendar year makes a resume reuse every year it already fetched.

**Files:**
- Modify: `hydroseason/_io_geo.py:205-285` (`_query_wofs_items`)
- Test: `tests/test_io_stac_cache.py`

**Interfaces:**
- Consumes: `STACItemCacheKey`, `load_cached_items`, `write_cached_items` from `hydroseason._io_stac_cache` (unchanged signatures).
- Produces: `_query_wofs_items` keeps its exact existing signature and `(items, aoi_gdf)` return. Only its internal caching granularity changes. No caller changes.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_io_stac_cache.py`:

```python
def test_query_caches_per_year_so_a_narrower_rerun_hits(tmp_path, monkeypatch):
    """A second query over a sub-range must reuse the first query's cached years.

    This is the resume path: acquire_wofs_cache derives its query range from
    the years still missing, so after a partial failure the range narrows and
    a whole-range cache key would always miss.
    """
    import geopandas as gpd
    import pystac
    from shapely.geometry import box

    import hydroseason._io_geo as io_geo

    aoi = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 1.0, 1.0)]}, crs="EPSG:4326")

    def _dated_item(item_id: str, date: str) -> pystac.Item:
        payload = _item_dict(item_id)
        payload["properties"]["datetime"] = date
        return pystac.Item.from_dict(payload)

    remote_items = [
        _dated_item("i2014", "2014-06-15T00:00:00Z"),
        _dated_item("i2015", "2015-06-15T00:00:00Z"),
    ]

    calls = []

    def _fake_collect(client, **kwargs):
        calls.append(kwargs["datetime"])
        start, end = kwargs["datetime"].split("/")
        return [
            item
            for item in remote_items
            if start <= item.properties["datetime"][:10] <= end
        ]

    monkeypatch.setattr(io_geo, "_collect_stac_items", _fake_collect)
    monkeypatch.setattr(
        io_geo.__dict__["pystac_client"] if "pystac_client" in io_geo.__dict__ else io_geo,
        "_noop",
        None,
        raising=False,
    )

    class _FakeClient:
        @staticmethod
        def open(url):
            return _FakeClient()

    import sys, types
    fake_module = types.ModuleType("pystac_client")
    fake_module.Client = _FakeClient
    monkeypatch.setitem(sys.modules, "pystac_client", fake_module)

    first, _ = io_geo._query_wofs_items(
        "https://example.test/stac", "ga_ls_wo_3", aoi,
        "2014-01-01", "2015-12-31", item_cache_root=tmp_path,
    )
    assert {item.id for item in first} == {"i2014", "i2015"}
    assert len(calls) == 2  # one network query per calendar year

    calls.clear()
    second, _ = io_geo._query_wofs_items(
        "https://example.test/stac", "ga_ls_wo_3", aoi,
        "2015-01-01", "2015-12-31", item_cache_root=tmp_path,
    )
    assert {item.id for item in second} == {"i2015"}
    assert calls == []  # fully served from the per-year cache
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_io_stac_cache.py::test_query_caches_per_year_so_a_narrower_rerun_hits -v`

Expected: FAIL — `assert len(calls) == 2` fails with `len(calls) == 1` (the current code issues one whole-range query), and the second assertion `calls == []` fails because the narrower range misses the cache.

- [ ] **Step 3: Rewrite `_query_wofs_items` to loop per year**

In `hydroseason/_io_geo.py`, replace the body of `_query_wofs_items` from the `cache_key = STACItemCacheKey(` line through the final `return items, aoi_gdf` (currently lines 231-285) with:

```python
    # Cache per calendar year, not per requested range. acquire_wofs_cache
    # derives its query range from the years still missing, so after a partial
    # failure the range narrows and a whole-range key would miss every time,
    # refetching every item. Per-year keys make a resume reuse everything the
    # previous attempt already fetched.
    def _year_key(year: int) -> STACItemCacheKey:
        return STACItemCacheKey(
            stac_url=stac_url,
            collection=collection,
            aoi_sha256=aoi_hash,
            start_date=f"{year}-01-01",
            end_date=f"{year}-12-31",
        )

    def _year_bounds(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Clamp a calendar year to the caller's requested window."""
        return (
            max(start, pd.Timestamp(f"{year}-01-01")),
            min(end, pd.Timestamp(f"{year}-12-31")),
        )

    years = list(range(start.year, end.year + 1))
    pending: list[int] = []
    items: list = []
    for year in years:
        if item_cache_root is not None and not force_item_refresh:
            cached_items = load_cached_items(item_cache_root, _year_key(year))
            if cached_items is not None:
                items.extend(cached_items)
                continue
        pending.append(year)

    if pending:
        try:
            aoi_4326 = aoi_gdf.to_crs("EPSG:4326")
            geometry = (
                aoi_4326.geometry.union_all()
                if hasattr(aoi_4326.geometry, "union_all")
                else aoi_4326.geometry.unary_union
            )
            import pystac_client

            client = pystac_client.Client.open(stac_url)
            for year in pending:
                year_start, year_end = _year_bounds(year)
                year_items = _collect_stac_items(
                    client,
                    collections=[collection],
                    datetime=f"{year_start:%Y-%m-%d}/{year_end:%Y-%m-%d}",
                    intersects=geometry.__geo_interface__,
                    limit=1000,
                    # DEA STAC supports the Fields extension.  Keep only the
                    # WOfS asset and timestamp fields needed by
                    # odc-stac/classification; geometry, id, bbox and other
                    # STAC core fields remain automatic.
                    fields={
                        "include": [
                            "assets.water",
                            "properties.datetime",
                            "properties.start_datetime",
                            "properties.end_datetime",
                        ]
                    },
                )
                items.extend(year_items)
                if item_cache_root is not None:
                    # Cache even an empty year: "this year genuinely has no
                    # items" is a real, reusable answer, and re-querying it on
                    # every resume is exactly the waste this task removes.
                    write_cached_items(item_cache_root, _year_key(year), list(year_items))
        except Exception as exc:
            raise AOIRasterizationError(
                "STAC AOI query failed; refusing to load an unclipped raster."
            ) from exc

    if not items:
        raise ValueError("No STAC items found for requested AOI and date range.")
    # STAC APIs do not promise a stable order. Same-day overlapping scenes can
    # otherwise reach odc-stac in different orders across repeated queries,
    # making categorical mosaic tie-breaks change by a pixel or two.
    items = sorted(items, key=_stac_item_sort_key)
    return items, aoi_gdf
```

Delete the now-unused `import pystac_client` at the top of the function body (it moved inside the `if pending:` block), keeping the `from hydroseason._io_stac_cache import (...)` and `from hydroseason._io_wofs_acquire import _aoi_digest` imports as they are.

- [ ] **Step 4: Guard against the empty-list cache miss**

`load_cached_items` currently returns a list, and the old call site treated an empty list as a miss via `len(cached_items) > 0`. The new code treats `[]` as a valid cached answer, so `load_cached_items` must distinguish "no entry" (`None`) from "cached empty year" (`[]`). It already does — it returns `None` on a missing file and on a malformed payload. But `hydroseason/_io_stac_cache.py:56` rejects a cached empty list:

```python
    if not fetched_at_str or not items_dict:
        return None
```

`items_dict` for an empty `ItemCollection` is a truthy dict (`{"type": "FeatureCollection", "features": []}`), so this is already correct and needs no change. Verify with a test — add to `tests/test_io_stac_cache.py`:

```python
def test_cached_empty_year_round_trips_as_empty_not_missing(tmp_path):
    key = STACItemCacheKey(
        stac_url="https://example.test/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="1987-01-01",
        end_date="1987-12-31",
    )
    write_cached_items(tmp_path, key, [], fetched_at="2026-07-25T00:00:00Z")
    loaded = load_cached_items(tmp_path, key, now="2026-07-25T01:00:00Z")
    assert loaded == []
    assert loaded is not None
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_io_stac_cache.py tests/test_io.py -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add hydroseason/_io_geo.py tests/test_io_stac_cache.py
git commit -m "perf: cache STAC items per calendar year so resumes reuse prior fetches"
```

---

### Task 3: Short-circuit years with no STAC items

When a year has no items, `acquire_wofs_cache` builds a full-grid empty mask via `_empty_year_mask` (`hydroseason/_io_wofs_acquire.py:388`) and walks every 512px window in `write_annual_group`, computing and hashing all-`-2` blocks that produce zero Zarr writes. The result is fully determined by the geobox and the date range, so it can be written directly.

**Files:**
- Modify: `hydroseason/_io_wofs_zarr.py` (add `write_empty_annual_group`)
- Modify: `hydroseason/_io_wofs_acquire.py:369-436` (`_process_one_year`)
- Test: `tests/test_io_wofs_zarr.py`

**Interfaces:**
- Consumes: `_content_hasher` from Task 1; `AnnualWriteStats`, `_year_dir`, `_years_dir`, `_zarr_store`, `_long_path`, `_write_json_atomic`, `_item_digest`, `_record_completed_year`, `MASK_CHUNKS`, `_STORAGE_CHUNK`, `WOFS_CACHE_SCHEMA_VERSION` — all already in `hydroseason/_io_wofs_zarr.py`.
- Produces:

```python
def write_empty_annual_group(
    handle: WOfSCacheHandle,
    year: int,
    mask,
    *,
    overwrite: bool = False,
) -> AnnualWriteStats
```

Task 3 is the only consumer. Signature deliberately mirrors `write_annual_group` minus the parameters that only matter when there is data to read (`windows`, `item_ids`, `compute_batch_size`, `read_workers`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_io_wofs_zarr.py`:

```python
def test_write_empty_annual_group_matches_full_path_output(tmp_path):
    """The no-items fast path must produce a group indistinguishable from the
    general path, so a year written either way validates and reads back the
    same."""
    import numpy as np
    import xarray as xr

    from hydroseason._io_wofs_zarr import (
        WOfSCacheIdentity,
        WOfSCacheRequest,
        WOFS_CACHE_SCHEMA_VERSION,
        WOFS_CLASSIFIER_VERSION,
        WOFS_PLANNER_VERSION,
        completed_years,
        create_cache_handle,
        validate_annual_group,
        write_empty_annual_group,
    )

    times = pd.date_range("1987-01-01", "1987-12-01", freq="MS")
    empty = xr.DataArray(
        np.full((len(times), 64, 64), -2, dtype=np.int8),
        dims=("time", "y", "x"),
        coords={
            "time": times,
            "y": np.arange(64) * -30.0,
            "x": np.arange(64) * 30.0,
        },
    ).rio.write_crs("EPSG:3577").rio.write_transform()

    request = WOfSCacheRequest(
        stac_url="https://example.test/stac",
        collection="ga_ls_wo_3",
        aoi_sha256="a" * 64,
        start_date="1987-01-01",
        end_date="1987-12-31",
        crs="3577",
        resolution=30.0,
        classifier_version=WOFS_CLASSIFIER_VERSION,
        groupby="solar_day",
        majority=True,
        planner_version=WOFS_PLANNER_VERSION,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
        wet_mask_sha256=None,
    )
    identity = WOfSCacheIdentity.from_request(
        request, shape=(64, 64), transform=tuple(empty.rio.transform())[:6]
    )
    handle = create_cache_handle(tmp_path, identity)

    stats = write_empty_annual_group(handle, 1987, empty)

    assert stats.year == 1987
    assert stats.chunks_written == 0
    assert stats.loaded_pixels == 0
    assert 1987 in completed_years(handle)
    validate_annual_group(
        Path(handle.path) / "years" / "1987",
        expected_year=1987,
        expected_shape=(len(times), 64, 64),
        expected_transform=tuple(empty.rio.transform())[:6],
    )

    counts = json.loads(
        (Path(handle.path) / "years" / "1987" / "extent_counts.json").read_text(encoding="utf-8")
    )
    assert counts["n_water"] == [0] * len(times)
    assert counts["n_valid"] == [0] * len(times)
    assert counts["n_aoi"] == [0] * len(times)
```

Note: this test uses `wet_mask_sha256=None`, a field Task 4 adds. Run Task 4 before Task 3 if you prefer strict ordering, or write the test now with the field omitted and add it in Task 4. The recommended order is: implement Task 3 with the field omitted, then Task 4 adds the field and updates this test alongside every other `WOfSCacheRequest(` construction.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_io_wofs_zarr.py::test_write_empty_annual_group_matches_full_path_output -v`

Expected: FAIL with `ImportError: cannot import name 'write_empty_annual_group'`

- [ ] **Step 3: Implement `write_empty_annual_group`**

In `hydroseason/_io_wofs_zarr.py`, add immediately after `write_annual_group` (after its `return AnnualWriteStats(...)` block, before `def _record_completed_year`):

```python
def write_empty_annual_group(
    handle: WOfSCacheHandle,
    year: int,
    mask,
    *,
    overwrite: bool = False,
) -> AnnualWriteStats:
    """Write a completed annual group for a year with no source observations.

    When STAC returned no items for ``year``, every pixel of every month is
    ``-2`` (outside/no-data) by construction. ``write_annual_group`` would
    still compute and hash every 512px block to discover that, then write
    none of them -- pure waste proportional to AOI area. This produces the
    identical on-disk group directly: the same Zarr layout, the same
    all-zero ``wet_count``/``clear_count``, the same zeroed
    ``extent_counts.json``, and a ``complete.json`` carrying an empty
    ``item_ids``. ``validate_annual_group`` accepts the result unchanged.
    """
    import shutil as _shutil

    import zarr
    from numcodecs import Blosc

    store_path = Path(handle.path)
    years_dir = _years_dir(store_path)
    Path(_long_path(years_dir)).mkdir(parents=True, exist_ok=True)
    final_year_path = _year_dir(store_path, year)
    if Path(_long_path(final_year_path)).exists() and not overwrite:
        raise FileExistsError(
            f"annual group for year {year} already exists at {final_year_path} "
            "(pass overwrite=True to replace it)"
        )

    temp_path = years_dir / f".{int(year)}.incomplete-{uuid.uuid4().hex}"
    Path(_long_path(temp_path)).mkdir(parents=True, exist_ok=True)

    try:
        dataset, year_mask = _mask_template(mask, year)

        compressor = Blosc(cname="zstd", clevel=1, shuffle=Blosc.BITSHUFFLE)
        encoding = {
            "water_mask": {
                "dtype": "int8",
                "chunks": MASK_CHUNKS,
                "compressor": compressor,
                "_FillValue": -2,
                "write_empty_chunks": False,
            }
        }
        dataset.to_zarr(
            _zarr_store(temp_path), mode="w", compute=False, consolidated=False, encoding=encoding
        )

        height = year_mask.sizes["y"]
        width = year_mask.sizes["x"]
        time_len = year_mask.sizes["time"]

        group = zarr.open_group(_zarr_store(temp_path), mode="r+")
        # No data to write into water_mask: every chunk stays unwritten, which
        # with write_empty_chunks=False and _FillValue=-2 reads back as -2
        # everywhere -- exactly what the general path would have produced.
        for derived_name in ("wet_count", "clear_count"):
            derived_array = group.create_dataset(
                derived_name,
                shape=(height, width),
                dtype=np.uint16,
                chunks=(_STORAGE_CHUNK, _STORAGE_CHUNK),
                fill_value=0,
                overwrite=True,
            )
            derived_array.attrs["_ARRAY_DIMENSIONS"] = ["y", "x"]

        digest = _item_digest(())
        time_values = pd.DatetimeIndex(np.asarray(year_mask.time.values))
        zeros = [0] * time_len

        content_hasher = _content_hasher()
        content_hasher.update(
            _canonical_json_bytes(
                {
                    "dtype": "int8",
                    "shape": [time_len, height, width],
                    "spatial_chunks": [],
                }
            )
        )

        extent_counts_payload = {
            "schema_version": WOFS_CACHE_SCHEMA_VERSION,
            "year": int(year),
            "dates": [d.strftime("%Y-%m-%d") for d in time_values],
            "n_aoi": list(zeros),
            "n_valid": list(zeros),
            "n_water": list(zeros),
            "n_invalid": list(zeros),
        }
        extent_counts_payload["content_digest"] = _sha256_digest(extent_counts_payload)
        _write_json_atomic(temp_path / "extent_counts.json", extent_counts_payload)

        complete_payload = {
            "schema_version": WOFS_CACHE_SCHEMA_VERSION,
            "year": int(year),
            "start_date": time_values[0].strftime("%Y-%m-%d"),
            "end_date": time_values[-1].strftime("%Y-%m-%d"),
            "month_count": int(len(time_values)),
            "item_ids": [],
            "item_digest": digest,
            "content_digest": content_hasher.hexdigest(),
            "chunks_considered": 0,
            "chunks_written": 0,
            "loaded_pixels": 0,
            "written_chunk_keys": [],
        }
        _write_json_atomic(temp_path / _COMPLETE_FILENAME, complete_payload)

        validate_annual_group(
            temp_path,
            expected_year=year,
            expected_shape=(time_len, height, width),
            expected_transform=tuple(year_mask.rio.transform())[:6],
        )

        del group
        import gc

        gc.collect()
        if Path(_long_path(final_year_path)).exists():
            _shutil.rmtree(_long_path(final_year_path))
        os.rename(_long_path(temp_path), _long_path(final_year_path))
    except BaseException:
        _shutil.rmtree(_long_path(temp_path), ignore_errors=True)
        raise

    _record_completed_year(store_path, year)

    return AnnualWriteStats(
        year=int(year),
        task_count=0,
        chunks_considered=0,
        chunks_written=0,
        loaded_pixels=0,
        item_digest=digest,
        compute_seconds=0.0,
        encode_write_seconds=0.0,
        validation_seconds=0.0,
    )
```

Add `write_empty_annual_group` to the module's `__all__` if one exists.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_io_wofs_zarr.py::test_write_empty_annual_group_matches_full_path_output -v`

Expected: PASS

- [ ] **Step 5: Route empty years to the fast path**

In `hydroseason/_io_wofs_acquire.py`, add `write_empty_annual_group` to the existing import of write helpers from `hydroseason._io_wofs_zarr`.

Then in `_process_one_year`, replace lines 407-419:

```python
            item_ids = tuple(item.id for item in year_items)
            final_year_path = Path(handle.path) / "years" / str(int(year))
            try:
                stats = write_annual_group(
                    handle,
                    year,
                    mask,
                    windows=plan.windows,
                    item_ids=item_ids,
                    overwrite=force or Path(_long_path(final_year_path)).exists(),
                    compute_batch_size=compute_batch_size,
                    read_workers=read_workers,
                )
            finally:
                del mask
                gc.collect()
```

with:

```python
            item_ids = tuple(item.id for item in year_items)
            final_year_path = Path(handle.path) / "years" / str(int(year))
            overwrite = force or Path(_long_path(final_year_path)).exists()
            try:
                if year_items:
                    stats = write_annual_group(
                        handle,
                        year,
                        mask,
                        windows=plan.windows,
                        item_ids=item_ids,
                        overwrite=overwrite,
                        compute_batch_size=compute_batch_size,
                        read_workers=read_workers,
                    )
                else:
                    # No source observations: every pixel is -2 by
                    # construction, so skip computing and hashing every block
                    # only to write none of them.
                    stats = write_empty_annual_group(
                        handle, year, mask, overwrite=overwrite
                    )
            finally:
                del mask
                gc.collect()
```

- [ ] **Step 6: Run the acquisition tests**

Run: `python -m pytest tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add hydroseason/_io_wofs_zarr.py hydroseason/_io_wofs_acquire.py tests/test_io_wofs_zarr.py
git commit -m "perf: write no-item years directly instead of computing empty blocks"
```

---

### Task 4: Add `wet_mask_sha256` to the cache request identity

A year built under a wet mask has permanent `-2` outside that mask, indistinguishable from genuinely dry. If pruned and unpruned years share a store, the store's spatial coverage becomes unknowable. Putting the mask digest in `WOfSCacheRequest` gives pruned and unpruned runs distinct request digests, so they land in different stores and can never mix. Existing full-coverage caches keep working: `wet_mask_sha256=None` must reproduce the pre-change digest byte-for-byte.

**Files:**
- Modify: `hydroseason/_io_wofs_zarr.py:63` (schema version), `hydroseason/_io_wofs_zarr.py:114-150` (`WOfSCacheRequest`)
- Test: `tests/test_io_wofs_zarr.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `WOfSCacheRequest` gains a trailing field `wet_mask_sha256: str | None = None`. Because it has a default, every existing positional/keyword construction keeps working unchanged. Tasks 6 and 7 set it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_io_wofs_zarr.py`:

```python
def _base_request(**overrides):
    from hydroseason._io_wofs_zarr import (
        WOFS_CACHE_SCHEMA_VERSION,
        WOFS_CLASSIFIER_VERSION,
        WOFS_PLANNER_VERSION,
        WOfSCacheRequest,
    )

    fields = {
        "stac_url": "https://example.test/stac",
        "collection": "ga_ls_wo_3",
        "aoi_sha256": "a" * 64,
        "start_date": "1986-05-01",
        "end_date": "2026-06-01",
        "crs": "3577",
        "resolution": 30.0,
        "classifier_version": WOFS_CLASSIFIER_VERSION,
        "groupby": "solar_day",
        "majority": True,
        "planner_version": WOFS_PLANNER_VERSION,
        "schema_version": WOFS_CACHE_SCHEMA_VERSION,
    }
    fields.update(overrides)
    return WOfSCacheRequest(**fields)


def test_wet_mask_digest_separates_pruned_from_unpruned_stores():
    """A pruned cache must never share a store with an unpruned one: outside
    the mask a pruned year is permanently -2, which is indistinguishable from
    genuinely dry."""
    unpruned = _base_request()
    pruned = _base_request(wet_mask_sha256="b" * 64)
    other_mask = _base_request(wet_mask_sha256="c" * 64)

    assert unpruned.wet_mask_sha256 is None
    assert pruned.request_digest() != unpruned.request_digest()
    assert pruned.request_digest() != other_mask.request_digest()
    # Same mask, same digest -- a second pruned run reuses the first's store.
    assert pruned.request_digest() == _base_request(wet_mask_sha256="b" * 64).request_digest()


def test_absent_wet_mask_preserves_the_legacy_request_digest():
    """Existing full-coverage caches on disk must stay reachable: with no wet
    mask the digest payload must be byte-identical to the pre-field version."""
    request = _base_request()
    payload = request._digest_payload()
    assert "wet_mask_sha256" not in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_io_wofs_zarr.py::test_wet_mask_digest_separates_pruned_from_unpruned_stores tests/test_io_wofs_zarr.py::test_absent_wet_mask_preserves_the_legacy_request_digest -v`

Expected: FAIL with `TypeError: WOfSCacheRequest.__init__() got an unexpected keyword argument 'wet_mask_sha256'`

- [ ] **Step 3: Add the field**

In `hydroseason/_io_wofs_zarr.py`, add to `WOfSCacheRequest` after the `schema_version: int` line (currently line 142):

```python
    # Digest of the wet mask a pruned acquisition read under, or None for a
    # full-coverage read. Outside the mask a pruned year is permanently -2,
    # which no reader can distinguish from genuinely dry, so pruned and
    # unpruned results must never share a store. Omitted from the digest
    # payload entirely when None, so every cache written before this field
    # existed keeps its original request_digest and stays reachable.
    wet_mask_sha256: str | None = None
```

Then in `_digest_payload` (line 144), make the field conditional. Read the current implementation and adapt; if it returns `dataclasses.asdict(self)`, change it to:

```python
    def _digest_payload(self) -> dict:
        payload = dataclasses.asdict(self)
        if payload.get("wet_mask_sha256") is None:
            # Absent, not null: keeps pre-existing full-coverage caches at
            # their original digest.
            payload.pop("wet_mask_sha256", None)
        return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_io_wofs_zarr.py::test_wet_mask_digest_separates_pruned_from_unpruned_stores tests/test_io_wofs_zarr.py::test_absent_wet_mask_preserves_the_legacy_request_digest -v`

Expected: PASS

- [ ] **Step 5: Bump the schema version**

In `hydroseason/_io_wofs_zarr.py`, change line 63:

```python
WOFS_CACHE_SCHEMA_VERSION = 2
```

to:

```python
# 3: WOfSCacheRequest gained wet_mask_sha256 (spatial pruning provenance).
WOFS_CACHE_SCHEMA_VERSION = 3
```

- [ ] **Step 6: Run the full suite and fix fallout**

Run: `python -m pytest tests/ -x -q`

Expected: PASS. Tests asserting a hard-coded `schema_version` of `2` or a hard-coded request digest will fail; update them to `3` and to the new digests. Add `wet_mask_sha256=None` explicitly to the `WOfSCacheRequest(...)` construction in the Task 3 test if you deferred it.

- [ ] **Step 7: Commit**

```bash
git add hydroseason/_io_wofs_zarr.py tests/
git commit -m "feat: record wet-mask provenance in the WOfS cache request identity"
```

---

### Task 5: Fetch the DEA Water Observation Statistics wet mask

New module. Queries `ga_ls_wo_fq_myear_3` (all-time summary) and `ga_ls_wo_fq_cyear_3` (per calendar year) for the requested years, unions every `count_wet > 0` region, and reduces to a buffered polygon via the existing `wet_aoi_polygon`.

**Why both products:** `myear` is one small raster covering all time, so it is the cheap primary source. But its temporal extent may lag the requested end date, and it can be regenerated with different filtering. Unioning the per-year `cyear` rasters for every requested year guarantees the mask covers exactly the period being acquired. Union, never intersect — the mask must be a superset.

**Files:**
- Create: `hydroseason/_io_dea_stats.py`
- Test: `tests/test_io_dea_stats.py`

**Interfaces:**
- Consumes: `wet_aoi_polygon` from `hydroseason._wet_aoi`; `_query_wofs_items` is **not** used (different collection semantics, no per-year partitioning needed).
- Produces:

```python
DEA_STATS_ALLTIME_COLLECTION: str = "ga_ls_wo_fq_myear_3"
DEA_STATS_ANNUAL_COLLECTION: str = "ga_ls_wo_fq_cyear_3"

class DEAStatsUnavailable(RuntimeError): ...

def fetch_dea_stats_wet_aoi(
    stac_url: str,
    aoi_gdf,
    years: list[int],
    *,
    crs: int | str = 3577,
    resolution: float = 30.0,
    close_m: float = 150.0,
    buffer_m: float = 300.0,
    cache_root: str | Path | None = None,
    _loader=None,
) -> "geopandas.GeoDataFrame"

def wet_mask_digest(wet_aoi) -> str
```

`fetch_dea_stats_wet_aoi` raises `DEAStatsUnavailable` on any failure — never returns a partial or empty mask, because an empty mask would prune everything. `_loader` is a test seam: a callable `(collection, items, geobox) -> xarray.DataArray` of `count_wet`. Task 6 consumes both functions.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_io_dea_stats.py`:

```python
"""Tests for the DEA Water Observation Statistics wet-mask fetch.

Fully offline: the STAC client and the raster loader are both injected, so
these tests never touch the network.
"""
import numpy as np
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("rioxarray")
gpd = pytest.importorskip("geopandas")

from shapely.geometry import box

from hydroseason._io_dea_stats import (
    DEA_STATS_ALLTIME_COLLECTION,
    DEA_STATS_ANNUAL_COLLECTION,
    DEAStatsUnavailable,
    fetch_dea_stats_wet_aoi,
    wet_mask_digest,
)


def _aoi():
    # 3 km x 3 km AOI at the EPSG:3577 origin.
    return gpd.GeoDataFrame({"geometry": [box(0.0, -3000.0, 3000.0, 0.0)]}, crs="EPSG:3577")


def _count_wet(grid, *, res=30.0):
    """A georeferenced count_wet raster from a 2D integer array."""
    h, w = np.asarray(grid).shape
    return xr.DataArray(
        np.asarray(grid, dtype=np.uint16),
        dims=("y", "x"),
        coords={"y": np.arange(h) * -res, "x": np.arange(w) * res},
    ).rio.write_crs("EPSG:3577").rio.write_transform()


def test_wet_aoi_covers_every_pixel_wet_in_any_source_year():
    """The mask must be a union across years, never an intersection: a pixel
    wet only in 1998 must survive, or 1998's flood reads as permanently dry."""
    wet_in_alltime = np.zeros((10, 10), np.uint16)
    wet_in_alltime[1, 1] = 5

    wet_only_1998 = np.zeros((10, 10), np.uint16)
    wet_only_1998[8, 8] = 1

    loaded = {
        (DEA_STATS_ALLTIME_COLLECTION, None): _count_wet(wet_in_alltime),
        (DEA_STATS_ANNUAL_COLLECTION, 1998): _count_wet(wet_only_1998),
    }

    def _loader(collection, year, geobox):
        return loaded[(collection, year)]

    wet_aoi = fetch_dea_stats_wet_aoi(
        "https://example.test/stac", _aoi(), [1998],
        close_m=0.0, buffer_m=0.0, _loader=_loader,
    )

    geometry = wet_aoi.geometry.iloc[0]
    # Pixel (1,1) -> centre (45, -45); pixel (8,8) -> centre (255, -255).
    assert geometry.contains(box(30.0, -60.0, 60.0, -30.0).centroid)
    assert geometry.contains(box(240.0, -270.0, 270.0, -240.0).centroid)


def test_zero_wet_pixels_raises_rather_than_pruning_everything():
    """An all-dry mask would prune the entire AOI. That is never a valid
    answer -- it must fail open at the call site instead."""
    def _loader(collection, year, geobox):
        return _count_wet(np.zeros((10, 10), np.uint16))

    with pytest.raises(DEAStatsUnavailable, match="no wet pixels"):
        fetch_dea_stats_wet_aoi(
            "https://example.test/stac", _aoi(), [1998], _loader=_loader,
        )


def test_loader_failure_raises_dea_stats_unavailable():
    def _loader(collection, year, geobox):
        raise ConnectionError("S3 unreachable")

    with pytest.raises(DEAStatsUnavailable):
        fetch_dea_stats_wet_aoi(
            "https://example.test/stac", _aoi(), [1998], _loader=_loader,
        )


def test_alltime_failure_alone_still_succeeds_from_annual_years():
    """myear is the cheap primary source but not required: if only the annual
    product resolves, the per-year union is still a valid superset."""
    wet = np.zeros((10, 10), np.uint16)
    wet[4, 4] = 3

    def _loader(collection, year, geobox):
        if collection == DEA_STATS_ALLTIME_COLLECTION:
            raise ConnectionError("myear unavailable")
        return _count_wet(wet)

    wet_aoi = fetch_dea_stats_wet_aoi(
        "https://example.test/stac", _aoi(), [1998],
        close_m=0.0, buffer_m=0.0, _loader=_loader,
    )
    assert not wet_aoi.empty
    assert wet_aoi.geometry.iloc[0].area > 0


def test_digest_is_stable_for_identical_geometry_and_differs_otherwise():
    left = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")
    same = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")
    other = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 200.0, 100.0)]}, crs="EPSG:3577")

    assert wet_mask_digest(left) == wet_mask_digest(same)
    assert wet_mask_digest(left) != wet_mask_digest(other)
    assert len(wet_mask_digest(left)) == 64
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_io_dea_stats.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'hydroseason._io_dea_stats'`

- [ ] **Step 3: Create the module**

Create `hydroseason/_io_dea_stats.py`:

```python
"""DEA Water Observation Statistics -> wet-AOI mask.

Fetches Geoscience Australia's pre-computed WOfS frequency summaries
(``ga_ls_wo_fq_myear_3``, all-time; ``ga_ls_wo_fq_cyear_3``, per calendar
year) and reduces them to a buffered ever-wet polygon. Acquiring
``ga_ls_wo_3`` daily observations only where that polygon says water has
ever been observed is the whole point: a catchment bounding box is mostly
land that never floods, and every pixel of it currently costs an S3 range
GET plus a reprojection.

The mask must be a SUPERSET of every pixel ever water in the requested
period. Outside it, a pruned acquisition writes -2 forever, and no reader
can tell that apart from genuinely dry. Two consequences drive the design:

* Years are UNIONED, never intersected. A pixel wet in one year only must
  survive.
* Any doubt fails open. Every failure path raises ``DEAStatsUnavailable``
  rather than returning a small or empty mask, so the caller falls back to
  a full-coverage read instead of silently pruning real water away.

All geospatial imports stay inside function bodies, per the package rule.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# The all-time summary: one small raster covering the full WOfS archive.
# Cheap, and the primary source.
DEA_STATS_ALLTIME_COLLECTION = "ga_ls_wo_fq_myear_3"
# The per-calendar-year summary. Unioned over the requested years so the mask
# provably covers the period being acquired even when the all-time product
# lags it or was regenerated under different filtering.
DEA_STATS_ANNUAL_COLLECTION = "ga_ls_wo_fq_cyear_3"

# The band carrying the number of water observations per pixel. > 0 means
# "water was observed here at least once", which is exactly the superset
# condition. Deliberately NOT the `frequency` band: frequency is a ratio that
# rounds small counts toward zero.
COUNT_WET_BAND = "count_wet"


class DEAStatsUnavailable(RuntimeError):
    """The wet mask could not be established, so pruning must not be attempted.

    Raised for every failure mode -- unreachable STAC, no matching items, a
    load error, or a mask with no wet pixels at all. The caller's only correct
    response is to fall back to a full-coverage read.
    """


def _load_count_wet(stac_url: str, collection: str, year: int | None, geobox):
    """Load the ``count_wet`` band for one collection over ``geobox``.

    ``year=None`` requests the all-time product (no datetime filter).
    """
    import odc.stac
    import pystac_client

    from hydroseason._io_geo import _configure_cog_read_env

    _configure_cog_read_env()

    search_kwargs = {
        "collections": [collection],
        "bbox": list(geobox.extent.to_crs("EPSG:4326").boundingbox),
        "limit": 1000,
    }
    if year is not None:
        search_kwargs["datetime"] = f"{year}-01-01/{year}-12-31"

    client = pystac_client.Client.open(stac_url)
    items = list(client.search(**search_kwargs).items())
    if not items:
        raise DEAStatsUnavailable(
            f"no {collection} items for {'all time' if year is None else year}"
        )

    dataset = odc.stac.stac_load(
        items,
        bands=[COUNT_WET_BAND],
        geobox=geobox,
        chunks={"x": 2048, "y": 2048},
        # Summary rasters are counts, and this is a presence test (> 0), so
        # any resampling that can only preserve or raise a nonzero count is
        # safe. Nearest never invents zeros where data exists.
        resampling="nearest",
    )
    # Collapse the (usually length-1) time axis: a pixel wet in ANY returned
    # summary is wet.
    return dataset[COUNT_WET_BAND].max("time") if "time" in dataset.dims else dataset[COUNT_WET_BAND]


def fetch_dea_stats_wet_aoi(
    stac_url: str,
    aoi_gdf,
    years: list[int],
    *,
    crs: int | str = 3577,
    resolution: float = 30.0,
    close_m: float = 150.0,
    buffer_m: float = 300.0,
    cache_root: str | Path | None = None,
    _loader=None,
):
    """Build a buffered ever-wet polygon for ``aoi_gdf`` over ``years``.

    Unions ``count_wet > 0`` from the all-time summary with each requested
    year's annual summary, then closes and buffers the result via
    :func:`hydroseason._wet_aoi.wet_aoi_polygon` (the same vectoriser the
    local-counts path uses, so both wet-AOI sources produce identically
    shaped geometry).

    ``_loader`` is a test seam: a callable ``(collection, year, geobox) ->
    DataArray`` of ``count_wet``. Production callers leave it ``None``.

    Raises ``DEAStatsUnavailable`` if no source resolves, or if the union
    contains no wet pixels at all -- an empty mask would prune the entire
    AOI, which is never a correct answer.
    """
    import numpy as np

    from hydroseason._io_geo import _crs_value, _output_geobox_for_aoi
    from hydroseason._wet_aoi import wet_aoi_polygon

    if not years:
        raise DEAStatsUnavailable("no years requested")

    crs_value = _crs_value(crs)
    target = aoi_gdf.to_crs(crs_value) if crs_value is not None else aoi_gdf
    geobox = _output_geobox_for_aoi([], target, crs=crs_value, resolution=float(resolution))

    loader = _loader if _loader is not None else (
        lambda collection, year, gb: _load_count_wet(stac_url, collection, year, gb)
    )

    sources = [(DEA_STATS_ALLTIME_COLLECTION, None)]
    sources.extend((DEA_STATS_ANNUAL_COLLECTION, year) for year in sorted(set(years)))

    union = None
    failures = []
    for collection, year in sources:
        try:
            count_wet = loader(collection, year, geobox)
            # A source that resolves but is entirely zero contributes nothing;
            # that is fine as long as SOME source contributes.
            wet = count_wet > 0
        except DEAStatsUnavailable as exc:
            failures.append(f"{collection}/{year}: {exc}")
            continue
        except Exception as exc:
            failures.append(f"{collection}/{year}: {type(exc).__name__}: {exc}")
            continue
        union = wet if union is None else (union | wet)

    if union is None:
        raise DEAStatsUnavailable(
            "no DEA Water Observation Statistics source could be loaded "
            f"({'; '.join(failures) if failures else 'no sources tried'})"
        )

    if not bool(np.asarray(union.values).any()):
        raise DEAStatsUnavailable(
            "DEA Water Observation Statistics returned no wet pixels for this "
            "AOI; refusing to prune (an empty mask would drop the entire AOI)"
        )

    wet_aoi = wet_aoi_polygon(union, close_m=close_m, buffer_m=buffer_m)
    if wet_aoi.empty or bool(wet_aoi.geometry.is_empty.all()):
        raise DEAStatsUnavailable("wet-AOI vectorisation produced an empty geometry")
    return wet_aoi


def wet_mask_digest(wet_aoi) -> str:
    """A stable SHA-256 over a wet-AOI's geometry and CRS.

    Feeds ``WOfSCacheRequest.wet_mask_sha256`` so a store built under one
    mask is never confused with a store built under another. Uses WKB at
    fixed precision rather than the GeoDataFrame's repr so the digest is
    stable across geopandas versions.
    """
    from shapely import wkb

    geometry = (
        wet_aoi.geometry.union_all()
        if hasattr(wet_aoi.geometry, "union_all")
        else wet_aoi.geometry.unary_union
    )
    hasher = hashlib.sha256()
    hasher.update(str(wet_aoi.crs).encode("utf-8"))
    hasher.update(wkb.dumps(geometry, rounding_precision=3))
    return hasher.hexdigest()


__all__ = [
    "COUNT_WET_BAND",
    "DEA_STATS_ALLTIME_COLLECTION",
    "DEA_STATS_ANNUAL_COLLECTION",
    "DEAStatsUnavailable",
    "fetch_dea_stats_wet_aoi",
    "wet_mask_digest",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_io_dea_stats.py -v`

Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_io_dea_stats.py tests/test_io_dea_stats.py
git commit -m "feat: derive a wet-AOI mask from DEA Water Observation Statistics"
```

---

### Task 6: Apply the wet mask at pixel granularity in the load path

Coarse 512px window pruning already exists via `plan_storage_aligned_slices`. At 30 m a 512px tile is 15.4 km across, so a 100 m river crossing one keeps the whole tile — coarse pruning alone captures only a fraction of the available saving. The fine-grain win comes from intersecting the wet mask into the AOI rasterisation in `_clip_to_aoi`: pixels outside the mask become `-2`, and the existing all-`-2` block skip at `hydroseason/_io_wofs_zarr.py:891` then drops entire blocks from the Zarr write.

**Files:**
- Modify: `hydroseason/_io_geo.py:296-449` (`_load_wofs_items`), `hydroseason/_io_geo.py:564-647` (`build_wofs_year_graph`)
- Test: `tests/test_io.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: both `_load_wofs_items` and `build_wofs_year_graph` gain a keyword-only parameter `wet_aoi=None` (a GeoDataFrame in any CRS, or `None` for no pruning). Task 7 passes it from `acquire_wofs_cache`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_io.py`:

```python
def test_wet_aoi_prunes_pixels_to_outside_value():
    """Pixels outside the wet mask must read as -2 (outside), so
    write_annual_group's all-(-2) block skip drops them from the Zarr write.

    Pixels inside the AOI but outside the wet mask are pruned; the mask is a
    superset of ever-wet, so this is the intended data loss.
    """
    import numpy as np
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    import hydroseason.io as io_module

    times = pd.date_range("2015-01-01", periods=1, freq="MS")
    # 0/1 water mask, all dry, over a 300m x 300m grid at 30m.
    cube = xr.DataArray(
        np.zeros((1, 10, 10), dtype=np.int8),
        dims=("time", "y", "x"),
        coords={"time": times, "y": np.arange(10) * -30.0, "x": np.arange(10) * 30.0},
    ).rio.write_crs("EPSG:3577").rio.write_transform()

    aoi = gpd.GeoDataFrame({"geometry": [box(0.0, -300.0, 300.0, 0.0)]}, crs="EPSG:3577")
    # Wet mask covers only the left third of the AOI.
    wet_aoi = gpd.GeoDataFrame({"geometry": [box(0.0, -300.0, 100.0, 0.0)]}, crs="EPSG:3577")

    clipped = io_module._clip_to_aoi(cube, aoi, wet_aoi=wet_aoi)
    values = np.asarray(clipped.isel(time=0).values)

    # Left column (x=15m centre) is inside both AOI and wet mask -> stays dry (0).
    assert values[5, 0] == 0
    # Right column (x=285m centre) is inside the AOI but outside the wet mask
    # -> pruned to -2.
    assert values[5, 9] == -2


def test_clip_without_wet_aoi_is_unchanged():
    """No mask means no pruning: the existing full-coverage behaviour must be
    byte-identical."""
    import numpy as np
    import geopandas as gpd
    import xarray as xr
    from shapely.geometry import box

    import hydroseason.io as io_module

    times = pd.date_range("2015-01-01", periods=1, freq="MS")
    cube = xr.DataArray(
        np.zeros((1, 10, 10), dtype=np.int8),
        dims=("time", "y", "x"),
        coords={"time": times, "y": np.arange(10) * -30.0, "x": np.arange(10) * 30.0},
    ).rio.write_crs("EPSG:3577").rio.write_transform()
    aoi = gpd.GeoDataFrame({"geometry": [box(0.0, -300.0, 300.0, 0.0)]}, crs="EPSG:3577")

    baseline = np.asarray(io_module._clip_to_aoi(cube, aoi).isel(time=0).values)
    explicit_none = np.asarray(
        io_module._clip_to_aoi(cube, aoi, wet_aoi=None).isel(time=0).values
    )
    assert np.array_equal(baseline, explicit_none)
    assert (baseline == 0).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_io.py::test_wet_aoi_prunes_pixels_to_outside_value tests/test_io.py::test_clip_without_wet_aoi_is_unchanged -v`

Expected: FAIL with `TypeError: _clip_to_aoi() got an unexpected keyword argument 'wet_aoi'`

- [ ] **Step 3: Add `wet_aoi` to `_clip_to_aoi`**

In `hydroseason/_io_geo.py`, replace `_clip_to_aoi` (lines 898-920) with:

```python
def _clip_to_aoi(mask, aoi_gdf, *, wet_aoi=None):
    """Clip ``mask`` to the AOI, optionally intersected with a wet mask.

    ``wet_aoi`` narrows the kept region to pixels where water has ever been
    observed. Pixels inside the AOI but outside ``wet_aoi`` become ``-2``
    (outside), which lets ``write_annual_group`` skip entire 512px blocks it
    would otherwise read, reproject, and hash. This is the fine-grain half of
    spatial pruning; ``plan_storage_aligned_slices`` handles the coarse half
    at 512px window granularity, and a 512px tile is 15.4 km at 30 m, far too
    coarse to prune around a river on its own.

    ``wet_aoi`` MUST be a superset of ever-wet: pixels it excludes read as
    permanently outside, indistinguishable from genuinely dry. ``None``
    disables pruning entirely and preserves the original behaviour exactly.
    """
    outside_value = np.int8(-2)
    invalid_value = np.int8(-1)
    try:
        mask = mask.rio.set_spatial_dims(x_dim="x", y_dim="y")
        crs = _resolve_raster_crs(mask)
        if crs is None:
            raise GeoreferencingError("raster is missing CRS")
        inside = _inside_aoi_mask_like(mask, aoi_gdf.to_crs(crs))
        if wet_aoi is not None and len(wet_aoi) and not bool(wet_aoi.geometry.is_empty.all()):
            wet_inside = _inside_aoi_mask_like(mask, wet_aoi.to_crs(crs))
            inside = inside & wet_inside
    except Exception as exc:
        if isinstance(exc, (AOIRasterizationError, GeoreferencingError)):
            raise
        raise AOIRasterizationError("AOI clip failed; refusing to process an unclipped raster.") from exc

    import xarray as xr

    res = (
        xr.where(inside, xr.where(mask == outside_value, invalid_value, mask), outside_value)
        .astype(np.int8)
        .transpose(*mask.dims)
    )
    return _preserve_georef(res, mask)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_io.py::test_wet_aoi_prunes_pixels_to_outside_value tests/test_io.py::test_clip_without_wet_aoi_is_unchanged -v`

Expected: PASS

- [ ] **Step 5: Thread `wet_aoi` through the two callers**

In `hydroseason/_io_geo.py`, add the parameter to `_load_wofs_items`. Change its signature (line 296-312) to add after `resampling=None,`:

```python
    wet_aoi=None,
```

Then change the clip call (line 428):

```python
        clipped_cube = _io._clip_to_aoi(stacked, target)
```

to:

```python
        clipped_cube = _io._clip_to_aoi(stacked, target, wet_aoi=wet_aoi)
```

Next, `build_wofs_year_graph`. Add after `resampling_policy: Literal[...] = "categorical_safe",` in its signature (line 576):

```python
    wet_aoi=None,
```

and add to its delegating `_load_wofs_items(...)` call (line 632-647), after `resampling=resampling,`:

```python
        wet_aoi=wet_aoi,
```

Append to the `build_wofs_year_graph` docstring, before the closing `"""`:

```
    ``wet_aoi``, when given, is intersected with the AOI during the final
    clip so pixels outside the ever-wet region become ``-2``. It must be a
    superset of ever-wet -- see :func:`_clip_to_aoi`.
```

- [ ] **Step 6: Run the I/O tests**

Run: `python -m pytest tests/test_io.py -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add hydroseason/_io_geo.py tests/test_io.py
git commit -m "feat: prune loaded pixels to a wet mask during the AOI clip"
```

---

### Task 7: Resolve and apply the wet mask in `acquire_wofs_cache`

Wire the pieces together. Order of preference for the mask: caller-supplied `wet_aoi` > local cached counts (free, and a guaranteed superset for years already acquired) > DEA statistics > no pruning.

**Why local counts rank above DEA stats:** `load_or_build_cached_wet_aoi` derives the mask from `wet_count` arrays this package already wrote, needs no network, and is exact for the years it covers. It is only usable when the store already has completed years and those years cover the request, so DEA stats remain the cold-start path.

**Files:**
- Modify: `hydroseason/_io_wofs_acquire.py:186-350` (`acquire_wofs_cache`)
- Test: `tests/test_io_wofs_acquire.py`

**Interfaces:**
- Consumes: `fetch_dea_stats_wet_aoi`, `wet_mask_digest`, `DEAStatsUnavailable` from Task 5; `wet_aoi=` on `build_wofs_year_graph` from Task 6; `WOfSCacheRequest.wet_mask_sha256` from Task 4.
- Produces: `acquire_wofs_cache` gains a keyword-only parameter `wet_mask: Literal["off", "dea_stats"] = "off"`. The existing `wet_aoi` parameter keeps its meaning (explicit caller-supplied mask) and now also sets `wet_mask_sha256`. New module-level helper:

```python
def _resolve_wet_aoi(
    stac_url: str, aoi_gdf, years: list[int], *,
    wet_aoi, wet_mask: str, crs, resolution: float, progress: bool, aoi_name: str,
) -> tuple[object | None, str | None]
```

returning `(wet_aoi_or_None, digest_or_None)`. Task 8 passes `wet_mask` from the CLI.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_io_wofs_acquire.py`:

```python
def test_resolve_wet_aoi_prefers_explicit_mask_over_dea_stats(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    import hydroseason._io_wofs_acquire as acquire

    explicit = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("DEA stats must not be queried when wet_aoi is explicit")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", _must_not_be_called)

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", explicit, [2015],
        wet_aoi=explicit, wet_mask="dea_stats",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
    )
    assert resolved is explicit
    assert digest is not None and len(digest) == 64


def test_resolve_wet_aoi_falls_open_when_dea_stats_unavailable(monkeypatch):
    """A failed stats fetch must yield NO pruning, never partial pruning:
    pruning on a bad mask silently deletes real water."""
    import geopandas as gpd
    from shapely.geometry import box

    import hydroseason._io_wofs_acquire as acquire
    from hydroseason._io_dea_stats import DEAStatsUnavailable

    aoi = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")

    def _unavailable(*args, **kwargs):
        raise DEAStatsUnavailable("collection unreachable")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", _unavailable)

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", aoi, [2015],
        wet_aoi=None, wet_mask="dea_stats",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
    )
    assert resolved is None
    assert digest is None


def test_resolve_wet_aoi_off_never_queries_stats(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    import hydroseason._io_wofs_acquire as acquire

    aoi = gpd.GeoDataFrame({"geometry": [box(0.0, 0.0, 100.0, 100.0)]}, crs="EPSG:3577")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("wet_mask='off' must not query DEA stats")

    monkeypatch.setattr(acquire, "fetch_dea_stats_wet_aoi", _must_not_be_called)

    resolved, digest = acquire._resolve_wet_aoi(
        "https://example.test/stac", aoi, [2015],
        wet_aoi=None, wet_mask="off",
        crs=3577, resolution=30.0, progress=False, aoi_name="test",
    )
    assert resolved is None
    assert digest is None


def test_pruned_and_unpruned_requests_use_distinct_stores(tmp_path):
    """The whole point of wet_mask_sha256: a pruned store must not be mistaken
    for a full-coverage one."""
    from hydroseason._io_wofs_zarr import (
        WOFS_CACHE_SCHEMA_VERSION,
        WOFS_CLASSIFIER_VERSION,
        WOFS_PLANNER_VERSION,
        WOfSCacheRequest,
    )

    common = {
        "stac_url": "https://example.test/stac",
        "collection": "ga_ls_wo_3",
        "aoi_sha256": "a" * 64,
        "start_date": "2015-01-01",
        "end_date": "2015-12-31",
        "crs": "3577",
        "resolution": 30.0,
        "classifier_version": WOFS_CLASSIFIER_VERSION,
        "groupby": "solar_day",
        "majority": True,
        "planner_version": WOFS_PLANNER_VERSION,
        "schema_version": WOFS_CACHE_SCHEMA_VERSION,
    }
    full = WOfSCacheRequest(**common)
    pruned = WOfSCacheRequest(**common, wet_mask_sha256="d" * 64)
    assert full.request_digest() != pruned.request_digest()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_io_wofs_acquire.py::test_resolve_wet_aoi_prefers_explicit_mask_over_dea_stats -v`

Expected: FAIL with `AttributeError: module 'hydroseason._io_wofs_acquire' has no attribute 'fetch_dea_stats_wet_aoi'`

- [ ] **Step 3: Add the resolver**

In `hydroseason/_io_wofs_acquire.py`, add a module-level import near the other `hydroseason` imports at the top:

```python
from hydroseason._io_dea_stats import (
    DEAStatsUnavailable,
    fetch_dea_stats_wet_aoi,
    wet_mask_digest,
)
```

(These are safe at module level: `_io_dea_stats` itself keeps all geospatial imports inside function bodies.)

Then add before `def acquire_wofs_cache`:

```python
def _resolve_wet_aoi(
    stac_url: str,
    aoi_gdf,
    years: list[int],
    *,
    wet_aoi,
    wet_mask: str,
    crs,
    resolution: float,
    progress: bool,
    aoi_name: str,
):
    """Decide which wet mask (if any) to prune this acquisition with.

    Returns ``(wet_aoi, wet_mask_sha256)``. Both are ``None`` when no
    pruning applies -- the full-coverage path, byte-identical to the
    behaviour before pruning existed.

    Preference order:

    1. An explicit caller-supplied ``wet_aoi``. The caller has asserted this
       is a valid superset; trust it and never spend a network call.
    2. ``wet_mask="dea_stats"``: fetch the DEA Water Observation Statistics
       summaries.
    3. Nothing -- no pruning.

    Fails OPEN in every failure case. A mask that is wrong, partial, or
    empty would silently prune real water into permanent ``-2``, so any
    doubt drops back to a full read rather than pruning on a bad mask.
    """
    if wet_aoi is not None:
        return wet_aoi, wet_mask_digest(wet_aoi)

    if wet_mask != "dea_stats":
        return None, None

    try:
        resolved = fetch_dea_stats_wet_aoi(
            stac_url, aoi_gdf, years, crs=crs, resolution=float(resolution)
        )
    except DEAStatsUnavailable as exc:
        if progress:
            print(
                f"[{aoi_name}] DEA statistics wet mask unavailable ({exc}); "
                "falling back to a full-coverage read.",
                flush=True,
            )
        return None, None
    except Exception as exc:
        if progress:
            print(
                f"[{aoi_name}] DEA statistics wet mask failed "
                f"({type(exc).__name__}: {exc}); falling back to a full-coverage read.",
                flush=True,
            )
        return None, None

    if progress:
        print(f"[{aoi_name}] Pruning reads to the DEA statistics wet mask.", flush=True)
    return resolved, wet_mask_digest(resolved)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_io_wofs_acquire.py -k resolve_wet_aoi -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Call the resolver from `acquire_wofs_cache`**

In `hydroseason/_io_wofs_acquire.py`, add to the signature after `wet_aoi: Any = None,` (line 206):

```python
    wet_mask: Literal["off", "dea_stats"] = "off",
```

Then replace lines 249-265 (from `aoi_hash = _aoi_digest(aoi_gdf)` through the close of the `WOfSCacheRequest(` construction) with:

```python
    aoi_hash = _aoi_digest(aoi_gdf)
    crs_value = _crs_value(crs)

    # Resolve the wet mask BEFORE building the request: its digest is part of
    # the cache identity, so a pruned run and a full-coverage run of otherwise
    # identical parameters resolve to different stores and can never mix.
    wet_aoi, wet_mask_sha256 = _resolve_wet_aoi(
        stac_url,
        aoi_gdf,
        list(range(start.year, end.year + 1)),
        wet_aoi=wet_aoi,
        wet_mask=wet_mask,
        crs=crs,
        resolution=float(resolution),
        progress=progress,
        aoi_name=aoi_name,
    )

    request = WOfSCacheRequest(
        stac_url=stac_url,
        collection=collection,
        aoi_sha256=aoi_hash,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        crs=str(crs_value),
        resolution=float(resolution),
        classifier_version=WOFS_CLASSIFIER_VERSION,
        groupby="solar_day",
        majority=bool(majority),
        planner_version=WOFS_PLANNER_VERSION,
        schema_version=WOFS_CACHE_SCHEMA_VERSION,
        wet_mask_sha256=wet_mask_sha256,
    )
```

Note the `offline=True` early return sits below this and is unaffected: with `wet_mask="off"` (the default) the resolver makes no network call, so an offline lookup still touches nothing.

- [ ] **Step 6: Pass the mask into the year graph**

In `hydroseason/_io_wofs_acquire.py`, in `_process_one_year`, add to the `build_wofs_year_graph(...)` call after `resampling_policy=resampling_policy,`:

```python
                    wet_aoi=wet_aoi,
```

The coarse 512px pruning at lines 337-343 already consumes `wet_aoi` via `pruning_geom` and needs no change — it now receives a resolved mask where before it usually received `None`.

- [ ] **Step 7: Run the acquisition and I/O tests**

Run: `python -m pytest tests/test_io_wofs_acquire.py tests/test_io.py tests/test_io_wofs_zarr.py -v`

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add hydroseason/_io_wofs_acquire.py tests/test_io_wofs_acquire.py
git commit -m "feat: resolve and apply a wet mask during WOfS cache acquisition"
```

---

### Task 8: Expose the wet mask on the extraction CLI

**Files:**
- Modify: `scripts/extract_water_extent_csv.py:112-135` (arg parser), `scripts/extract_water_extent_csv.py:162-203` (`_process_job`)
- Test: `tests/test_extract_water_extent_csv.py`

**Interfaces:**
- Consumes: `wet_mask` keyword on `acquire_wofs_cache` from Task 7.
- Produces: `--wet-mask {off,dea_stats}` CLI flag, default `off`. No downstream consumer.

**Default is `off`, deliberately:** pruning changes the cache identity, so flipping the default would silently orphan every completed year already on disk (Lachlan, Fitzroy, Daly represent tens of hours of acquisition). Opt in per run, measure, then change the default in a follow-up once the saving is confirmed on a real catchment.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_extract_water_extent_csv.py`:

```python
def test_wet_mask_flag_defaults_off_and_accepts_dea_stats():
    import scripts.extract_water_extent_csv as script

    parser = script._build_arg_parser()

    assert parser.parse_args([]).wet_mask == "off"
    assert parser.parse_args(["--wet-mask", "dea_stats"]).wet_mask == "dea_stats"

    with pytest.raises(SystemExit):
        parser.parse_args(["--wet-mask", "nonsense"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_extract_water_extent_csv.py::test_wet_mask_flag_defaults_off_and_accepts_dea_stats -v`

Expected: FAIL with `AttributeError: 'Namespace' object has no attribute 'wet_mask'`

- [ ] **Step 3: Add the flag and fix the stale help text**

In `scripts/extract_water_extent_csv.py`, add after the `--resampling-policy` argument block (line 117-122):

```python
    parser.add_argument(
        "--wet-mask",
        choices=("off", "dea_stats"),
        default="off",
        help="prune reads to an ever-wet mask. 'dea_stats' derives it from DEA Water "
             "Observation Statistics (ga_ls_wo_fq_myear_3 + ga_ls_wo_fq_cyear_3). "
             "NOTE: a pruned run writes to a DIFFERENT cache store than a full-coverage "
             "run, so it will not reuse years already acquired without the mask "
             "(default: off)",
    )
```

Then fix the `--year-workers` help at line 124-126 — the current text says "worker processes" but `acquire_wofs_cache` uses a `ThreadPoolExecutor`:

```python
    parser.add_argument(
        "--year-workers", type=int, default=1,
        help="number of concurrent worker threads for parallel multi-year acquisition (default: 1)",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_extract_water_extent_csv.py::test_wet_mask_flag_defaults_off_and_accepts_dea_stats -v`

Expected: PASS

- [ ] **Step 5: Pass the flag through to acquisition**

In `scripts/extract_water_extent_csv.py`, `_process_job` reaches acquisition two ways. First, the `load_wofs_monthly_extent` call at lines 169-185 — add after `year_workers=args.year_workers,`:

```python
        wet_mask=args.wet_mask,
```

Then verify `load_wofs_monthly_extent` forwards `wet_mask` to `acquire_wofs_cache`. Read `hydroseason/io.py` and `hydroseason/_io_extent_cache.py`, find where `year_workers` is threaded through, and add `wet_mask` alongside it at every hop using the identical pattern (signature parameter with default `"off"`, forwarded by keyword). If a hop passes `**kwargs` through, no change is needed at that hop.

Second, the `--profile` diagnostic call at lines 191-203 — add after `year_workers=args.year_workers,`:

```python
            wet_mask=args.wet_mask,
```

This one matters: it runs `offline=True`, and without a matching `wet_mask` it would look up the full-coverage store rather than the pruned one just written, reporting the wrong diagnostics.

- [ ] **Step 6: Run the affected tests**

Run: `python -m pytest tests/test_extract_water_extent_csv.py tests/test_io_extent_cache.py -v`

Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest tests/ -q`

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add scripts/extract_water_extent_csv.py hydroseason/io.py hydroseason/_io_extent_cache.py tests/test_extract_water_extent_csv.py
git commit -m "feat: add --wet-mask flag to the water-extent extraction CLI"
```

---

### Task 9: Measure the saving on a real catchment

The plan is a performance change. Without a measured before/after on real data it is unverified. `gilbert_river_qld` is the cheapest fixture catchment (800s for a full 40-year cold run per `output/water_extent_csv/execution_timing.csv`), so it is the right subject.

**Files:**
- Create: `docs/superpowers/plans/2026-07-27-wofs-pruning-measurements.md`

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: a measurements document. No code.

- [ ] **Step 1: Measure the pruned cold run over a 3-year window**

A 3-year window keeps the run to minutes while exercising every code path. Run from the repo root:

```bash
python scripts/extract_water_extent_csv.py \
    --only gilbert_river_qld \
    --start-date 2015-01-01 --end-date 2017-12-31 \
    --wet-mask dea_stats --profile
```

Record the reported elapsed seconds and the printed planner diagnostics.

- [ ] **Step 2: Measure the unpruned cold run over the same window**

```bash
python scripts/extract_water_extent_csv.py \
    --only gilbert_river_qld \
    --start-date 2015-01-01 --end-date 2017-12-31 \
    --wet-mask off --profile
```

These land in different stores (different `wet_mask_sha256`), so neither run warms the other's cache — the comparison is fair without any manual cache clearing.

- [ ] **Step 3: Compare the extent series for agreement**

Both runs wrote to `output/water_extent_csv/gilbert_river_qld_30m_water_extent.csv`, so the second overwrote the first. Re-run each with an explicit `--output-csv` to keep both, then compare:

```bash
python - <<'PY'
import pandas as pd
pruned = pd.read_csv("output/water_extent_csv/gilbert_pruned.csv", index_col=0)
full = pd.read_csv("output/water_extent_csv/gilbert_full.csv", index_col=0)
joined = pruned.join(full, lsuffix="_pruned", rsuffix="_full")
print(joined.head(12))
for column in ("n_water", "n_valid", "n_aoi"):
    if f"{column}_pruned" in joined:
        delta = joined[f"{column}_pruned"] - joined[f"{column}_full"]
        print(column, "max abs delta:", delta.abs().max())
PY
```

**`n_water` must match exactly.** The wet mask is a superset of ever-wet, so no water pixel may be lost. A nonzero `n_water` delta means the mask is not a superset — stop and diagnose before trusting any pruned cache. `n_aoi` and `n_valid` are expected to drop substantially; that is the pruning working.

- [ ] **Step 4: Record the results**

Create `docs/superpowers/plans/2026-07-27-wofs-pruning-measurements.md` with: the two elapsed times and the ratio; the `n_water` max absolute delta (expected `0`); the `n_aoi` reduction ratio (the pruned fraction); and the per-task contribution if you measured Tasks 1–3 separately. State the exact commands run and the machine, so a later run is comparable.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-07-27-wofs-pruning-measurements.md
git commit -m "docs: record WOfS wet-mask pruning measurements"
```

---

## Deferred, deliberately

- **Buffer-distance tuning** (`close_m=150`, `buffer_m=300` in `hydroseason/_wet_aoi.py:76`). At 30 m that is a 10 px dilation on every wet edge, and for a dendritic river network the buffer area can exceed the channel area several times over — so it is a real lever on how much pruning actually saves. But it is the safety margin protecting the superset guarantee, and shrinking it without the Task 9 measurement in hand risks silently dropping real water. Tune it only after `n_water` agreement is confirmed at the current values.
- **`year_workers` process pool.** Threads are correct for the GDAL read phase (GDAL releases the GIL), and Task 1 removes the largest GIL-bound serialisation. Re-measure before considering processes, which would add pickling cost and complicate the shared `cache_writer_lock`.
- **Coarse-pass self-bootstrap** as a fallback when DEA statistics are unavailable. Worth adding only if Task 9 shows the stats product is unreliable in practice; until then the fail-open full read is the correct fallback.

---

## Self-Review Notes

**Spec coverage.** The `DEA_cyear.md` spec's four proposed changes all land: `fetch_dea_stats_wet_aoi` (Task 5, in a new dedicated module rather than `_io_geo.py` — that file is already 43 KB and the DEA-stats collection names belong in one place); `acquire_wofs_cache` pre-fetch and tile pruning (Task 7); a wet-AOI-from-summary-raster helper (Task 5, folded into `fetch_dea_stats_wet_aoi` — the spec's separate `wet_aoi_from_summary_raster` would have been a one-line wrapper over the existing `wet_aoi_polygon`, so YAGNI); the CLI flag (Task 8, defaulting `off` not `True`, because pruning changes the cache identity and a `True` default would orphan every completed year on disk). The spec's verification plan maps to Tasks 5–7 tests plus the Task 9 manual comparison.

**Three spec corrections are implemented rather than followed.** (1) The spec masks per-target-year; that is not a superset across a multi-year request, so Task 5 unions across all requested years plus the all-time product. (2) The spec prunes at tile granularity only; a 512 px tile is 15.4 km at 30 m, so Task 6 adds pixel-granularity pruning in the clip, which is where most of the saving actually is. (3) The spec's graceful fallback leaves no record of which years were pruned; Task 4 puts the mask digest in the cache identity so pruned and unpruned stores are physically separate.

**Interface consistency.** `wet_aoi` is the parameter name at every hop (`_clip_to_aoi`, `_load_wofs_items`, `build_wofs_year_graph`, `acquire_wofs_cache`); `wet_mask` is the string mode selector on `acquire_wofs_cache` and the CLI; `wet_mask_sha256` is the digest field on `WOfSCacheRequest`. `_content_hasher()` is defined in Task 1 and consumed in Task 3.

**One step needs local discovery.** Task 8 Step 5 requires reading `hydroseason/io.py` and `hydroseason/_io_extent_cache.py` to find the `year_workers` forwarding chain, because that chain's exact shape was not established while writing this plan. The step names the files and the pattern to copy.
