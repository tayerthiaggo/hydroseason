# Scalable WOfS Zarr Processing Optimization Design

**Date:** 2026-07-23
**Status:** Approved design, pending implementation plan
**Scope:** DEA Water Observations (`ga_ls_wo_3`) acquisition, canonical monthly-mask caching, monthly extent CSV generation, and hydrological-state analysis. CSV remains the only non-WOfS user input in scope.

## Problem

Current WOfS extraction repeats expensive work:

- Wet-AOI precomputation materialises the full lazy cube, tiled extent extraction reads source data again, and denominator reconciliation materialises the full cube again.
- Tiled loading rebuilds `odc.stac.stac_load`, classification, monthly-composition, and clipping graphs for every loaded tile.
- Each calendar year performs another STAC query.
- Reprocessing an AOI requires remote STAC/COG access even when identical canonical monthly masks were already produced previously.
- The proposed adaptive-tile heuristic considers bounding-box span but not the number of pixels in tiles intersecting the actual AOI, so it can slow compact AOIs.

The workflow must remain bounded, resumable, portable across machines, and reusable for catchments with different shapes and sizes.

## Goals

1. Query and materialise each required WOfS source region no more than once during acquisition.
2. Build one lazy parent load graph per calendar year, then compute only AOI-intersecting spatial slices.
3. Persist canonical 30 m monthly masks to a resumable Zarr cache.
4. Generate extent CSV and hydrological-state results locally from completed Zarr years without STAC access.
5. Keep 30 m extent CSV output byte-identical to the existing mode-resampled WOfS path.
6. Improve median cold acquisition runtime by at least 20% on the thin Gilbert benchmark, target at least 35%, and stretch to at least 40%.
7. Improve a cached local rerun by at least 80% and prove that it makes zero STAC calls.
8. Avoid more than 10% median regression on the compact Fitzroy benchmark.

## Non-Goals

- No public TIFF, NetCDF, Zarr, or generic raster input expansion.
- No plugin framework or general storage abstraction.
- No nearest-neighbour replacement for `resampling="mode"`.
- No process-pool parallelism across years.
- No committed WOfS Zarr data.
- No detector, seasonal-pattern, or hydrological-state algorithm changes.

## Supported Sources

- **DEA/WOfS:** remote acquisition and internal Zarr cache.
- **CSV:** already-aggregated monthly extent input; it bypasses raster, Dask, STAC, and Zarr dependencies.

Zarr is an internal WOfS cache, not a new public input mode in this work.

## Architecture

### 1. Full-interval query and annual partitioning

The acquisition layer queries the STAC catalog once for the requested interval. Returned items are partitioned by calendar year in memory. Each annual partition remains a bounded unit for graph construction, execution, cache completion, retry, and progress reporting.

The query result is metadata only. It must not retain open raster handles and must remain serialisable.

### 2. One parent graph per year

For each year, construct one `odc.stac.stac_load` graph over the stable parent GeoBox. Classification and monthly composition also occur once in that graph.

The loader then exposes spatial slices from the shared lazy cube. It never calls `stac_load` again for an individual tile. Computing one slice must only execute source tasks needed by that slice.

The source scenes remain in their native UTM CRSs and are genuinely reprojected to EPSG:3577. `resampling="mode"` remains mandatory because omitting it selects nearest-neighbour behavior and changes classified values.

### 3. Geometry-aware cost planner

The planner is a pure function. Inputs are:

- AOI geometry in target CRS;
- output-grid shape and transform;
- candidate tile sizes `(None, 2048, 1024, 512)` where `None` means one parent slice;
- estimated cost per loaded pixel;
- fixed overhead per loaded slice;
- minimum predicted improvement, default 15%.

For every candidate it computes:

- total grid tiles;
- tiles intersecting actual AOI geometry;
- pixels contained by intersecting tiles;
- predicted cost `intersecting_pixels * pixel_cost + intersecting_tiles * tile_overhead`;
- predicted improvement relative to the parent slice.

It chooses the lowest predicted cost only when improvement is at least 15%; otherwise it keeps the parent slice. It records all candidate scores and the selection reason. No constants may be fitted specifically to Gilbert or another named catchment.

Default cost coefficients are portable fallbacks. Benchmark output may supply measured overrides without changing planner code.

### 4. Canonical monthly-mask Zarr cache

Cache layout:

```text
output/wofs_cache/<identity>.zarr/
  root attributes and manifest
  years/
    2015/
      water_mask(time=12, y, x)
    2016/
      water_mask(time=12, y, x)
```

`water_mask` is `int8` with canonical values:

- water: `1`
- dry: `0`
- invalid: `-1`
- outside AOI: `-2`

Storage requirements:

- Zarr v2, matching the repository dependency pin;
- chunks `(time=1, y=512, x=512)`;
- Blosc compression using Zstandard level 5 with bit-shuffle (`cname="zstd"`, `clevel=5`, `shuffle=BITSHUFFLE`);
- stable EPSG:3577 parent grid;
- outside-AOI fill value `-2`;
- wholly outside chunks left unwritten when supported, so they remain sparse fill chunks;
- one independently completable group per year.

Each annual group is written to an incomplete temporary location and becomes visible as complete only after data and metadata validation succeed. A stopped process therefore resumes at annual granularity without trusting partial data.

The cache is local output and must remain git-ignored. A lightweight provenance manifest may be exported separately.

### 5. Cache identity and provenance

Cache identity includes every data-affecting input:

- schema and planner-model version;
- STAC URL and collection;
- AOI content digest;
- output CRS, resolution, transform, and grid anchor;
- WOfS classifier version;
- `groupby="solar_day"` semantics;
- monthly majority/compositing semantics;
- acquisition date coverage.

Root and annual metadata record item IDs or a stable digest of sorted item IDs, software versions, creation timestamp, and selected tile-plan diagnostics. A mismatch creates a different cache identity; it never silently reuses incompatible data.

### 6. Local analysis path

After acquisition:

1. Open completed annual groups lazily.
2. Concatenate them in time order.
3. Slice requested dates.
4. Run `monthly_water_extent` locally.
5. Write annual extent CSV cache and requested final CSV.
6. Run `analyze_hydrological_state` when requested.

Offline mode is explicit. It may read completed local cache only. Missing coverage raises a clear error and never silently contacts STAC.

### 7. Wet-AOI without remote rereads

The remote acquisition path does not perform a separate wet-AOI precompute pass. Ever-wet state is either:

- computed jointly with monthly canonical-mask materialisation so source tasks are shared; or
- derived later from the completed local Zarr cache.

After wet geometry exists, `n_wet_aoi` is derived geometrically from the stable output grid. It must not trigger another STAC/COG read. Positive persistence thresholds may require accumulated wet and clear counts; those counts are local derived-cache work, not remote acquisition work.

## Scalability and Transferability

- Planning logic is dataset-agnostic even though this implementation wires only DEA/WOfS.
- Memory is bounded by one annual graph and selected spatial chunks, not total requested years.
- Different catchments and years use independent cache groups and can be orchestrated separately.
- Same-cache concurrent writers are rejected. Different AOI stores remain concurrency-safe.
- No correctness or performance behavior depends on Windows, a fixed CPU count, or process pools.
- Planner diagnostics make machine-specific recalibration observable and reproducible.
- Benchmark records runtime, graph/task count, estimated loaded pixels, cache size, peak memory, software versions, and output digest.

## Error Handling

- Missing/corrupt annual group is incomplete, never a cache hit.
- In network-enabled mode, incomplete coverage may be rebuilt.
- In offline mode, incomplete coverage fails with the missing dates listed.
- CRS, transform, chunk schema, canonical-domain, time ordering, and duplicate-month validation run before a group is marked complete.
- Same-store concurrent acquisition fails before writing.
- Preflight storage estimation requires projected uncompressed intersecting data plus scratch headroom; insufficient free space fails before remote reads.
- A STAC or COG failure leaves existing completed years intact.

## Testing Strategy

### Default deterministic suite

- Planner selects 1024-like useful tiling for a thin synthetic AOI.
- Planner keeps parent/untiled execution for a compact AOI without enough predicted savings.
- Exactly one STAC query occurs for a multi-year request.
- Exactly one `stac_load` graph is built per uncached year.
- A delayed source counter proves shared graph consumers execute source tasks once.
- Shared-graph and legacy 30 m monthly extent frames are byte-identical.
- Partial annual group is never trusted and resumes safely.
- Sparse outside chunks read back as `-2`.
- Cache identity changes for every data-affecting semantic input.
- Offline cache hit performs zero STAC calls; offline cache miss fails.
- CSV-only import works with raster/STAC/Zarr modules unavailable.

### Opt-in real performance suite

Performance and network tests run in fresh subprocesses and fresh application-cache directories. They do not flush privileged operating-system caches, so environment and raw timings are always retained.

- Thin AOI: `data/Gilbert_river_buffer.geojson`, three cold runs, median improvement at least 20%, target 35%, stretch 40%.
- Compact AOI: `data/fitzroy_kimberley_aoi.geojson`, three cold runs, median regression no worse than 10%.
- Cached rerun: median local runtime at least 80% faster than legacy remote path and zero STAC calls.
- Every benchmark compares an exact output digest and full DataFrame equality.

Wall-clock tests are excluded from ordinary CI. Structural source-read, query-count, and graph-count assertions remain hard CI regressions.

## Acceptance Criteria

- All default tests pass.
- Gilbert median cold improvement is at least 20%; measured target and stretch status reported.
- Fitzroy compact regression is no worse than 10%.
- Cached rerun improves by at least 80% and uses no STAC calls.
- 30 m output is byte-identical to legacy output.
- Interrupted acquisition resumes without recomputing completed years.
- Cache/provenance mismatch cannot produce a silent hit.
