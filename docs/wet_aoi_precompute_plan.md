# Wet-AOI Precompute + Tile Pruning — Implementation Plan

## Goal

Precompute a "wet AOI" mask (union of all ever-wet pixels over the full time
series) once, then use it to **prune whole STAC tile fetches** that never touch
water. Bandwidth win, not just compute win. Feeds the existing tiler
(`iter_wofs_tiles_from_stac`) as a second tile-skip predicate.

## Flaws fixed from original 6-step idea

| # | Original | Fix |
|---|----------|-----|
| 1 | `>1% persistence` filter | **Default threshold = 0 (any wet obs).** Superset guarantee only holds at 0. `persistence_min` is an opt-in denoise knob, off by default. Named, not silent. |
| 2 | `1% of what?` denominator | Persistence = `wet_count / clear_count` **per pixel** (matches `n_valid` semantics in `monthly_water_extent`, not scene count). |
| 3 | "dilation erosion" order | Operation is **closing** (dilate→erode) to fill mask gaps / connect thin channels, NOT opening. Erosion-first would delete 1–2px rivers permanently. |
| 4 | `5px + 5px` in pixels | Buffer expressed in **meters** (`buffer_m`), converted to pixels via `resolution`. Scale-invariant across resample. Default: closing radius `close_m`, then outward `buffer_m`. |
| 5 | `%` denominator ambiguity | Cache **both** ratios: `extent_pct` (vs user AOI, existing) AND `wet_fill_pct` (vs wet AOI). Clipping to wet AOI must NOT silently change the `n_aoi` denominator — see Task 4 invariant. |
| 6 | one-shot = no gain | True. Precompute pays a full-TS pass. Win realised only on **repeat monthly reprocessing** or when tile pruning drops enough tiles to beat the precompute cost. Document as such; make wet AOI cacheable + reusable. |

## Architecture: where it plugs in

Three existing seams, no new subsystem:

1. **`_io_geo.py:398`** — `_tile_intersects_aoi(tile_geobox, target)` is the
   current tile-skip predicate inside `iter_wofs_tiles_from_stac`. The wet-AOI
   test goes **right beside it**: `and _tile_intersects_wet_aoi(tile_geobox, wet_aoi)`.
   A skipped tile is a skipped `_load_wofs_items` call = skipped STAC read.
2. **`skip_tile_ids`** (already in the signature) — proves the tiler already
   supports "don't process these tiles". Wet-AOI pruning is the same shape,
   just computed from geometry instead of a resume cache.
3. **`_io_extent_cache.py:55`** `_cache_path` identity dict — the wet-AOI mask
   is a **data-affecting input**. Its digest MUST enter cache identity or a
   stale wet AOI poisons results. This is the one correctness landmine.

## Tasks (TDD, each independently testable)

### Task 1 — `compute_wet_aoi` (pure reducer, no STAC)
New fn in `hydroseason/_wet_aoi.py`. Input: a canonical time/y/x mask cube
(same shape `_load_wofs_items` yields). Output: a boolean/int8 2D "ever wet"
raster + its georef.

- `ever_wet = (mask == 1).sum("time")` ; `clear = (mask.isin([0,1])).sum("time")`
- `persistence = ever_wet / clear` (guard clear==0 → False)
- `wet = ever_wet > 0` if `persistence_min == 0` else `persistence >= persistence_min`
- Preserve georef via existing `_preserve_georef`.
- **Test:** synthetic cube, pixel wet once in N → included at threshold 0,
  excluded at threshold `>1/N`. Locks flaw 1+2.

### Task 2 — morphology: `close_and_buffer`
- Convert `close_m`, `buffer_m` → pixel radii via `resolution` (round up).
- **Closing** = binary dilation then erosion (`scipy.ndimage`), then outward
  dilation by `buffer_m` px. Order asserted in test (thin-channel survival case).
- **Test:** 1px-wide diagonal channel survives closing; isolated speck removed
  only if `persistence_min` set (not by morphology — closing keeps specks).
  Locks flaw 3.

### Task 3 — vectorize to polygon(s)
- `rasterio.features.shapes` on the buffered mask → GeoDataFrame in raster CRS.
- Return in same CRS as `target` (Albers 3577) so it composes with tile geoboxes.
- **Test:** two disjoint wet blobs → 2 polygons; buffer merges near ones → 1.

### Task 4 — wire into `iter_wofs_tiles_from_stac`
Add `wet_aoi=None` param. When set:
- `_tile_intersects_wet_aoi(tile_geobox, wet_aoi)` beside the AOI test at line 398.
- **INVARIANT (flaw 5):** wet AOI prunes *which tiles load*; it does NOT
  replace the user-AOI `_clip_to_aoi`. `n_aoi` denominator stays user-AOI so
  `extent_pct` meaning is unchanged. A pruned tile contributes zeros
  (`_missing`-style), not a shrunk denominator.
- **Test:** tile fully outside wet AOI but inside user AOI → skipped, and its
  pixels still count as dry-not-water in the user-AOI denominator (extent
  identical to unpruned run). This is the critical no-silent-drift test.

### Task 5 — cache identity + precompute reuse
- Add `wet_aoi_hash` to `_cache_path` identity dict (`_io_extent_cache.py`).
  Bump `_CACHE_SCHEMA_VERSION` 1→2.
- Persist computed wet AOI (GeoJSON/parquet) keyed by
  `(stac_url, collection, aoi_hash, start, end, crs, resolution, persistence_min, close_m, buffer_m)`.
- `load_wofs_monthly_extent` grows `wet_aoi=` / `precompute_wet_aoi=bool`.
  When precompute on and no cached wet AOI: run one full-TS pass → wet AOI →
  reuse for the tiled monthly passes.
- **Test:** changing `persistence_min` changes cache path (no stale hit);
  identical inputs hit cache.

### Task 6 — `wet_fill_pct` second ratio (flaw 5, drought signal)
- In extent aggregation, add `wet_fill_pct = n_water / n_wet_aoi` alongside
  `extent_pct`. `n_wet_aoi` = pixel count inside wet AOI per tile.
- New column in `_EXTENT_COLUMNS` (schema bump already covers it).
- **Test:** drought month (small water, large wet AOI) → low `wet_fill_pct`,
  `extent_pct` vs user AOI unchanged.

## Workflow fit / honest cost

- **Pass 1** (precompute): full-TS `any(wet)` reduce → wet AOI polygon. One
  full pass, cached.
- **Pass 2..N** (monthly): tiled, wet-AOI-pruned. `tile_grid ∩ wet_aoi` → only
  fetch tiles touching wet mask. **This is the bandwidth win** — combines with
  the merged native tiler (`5c5afc4`).
- Net gain **iff** pruned-tile savings × runs > one full precompute pass.
  Sparse wetland in big bbox = big win. Wall-to-wall water = no win. Document.

## Non-goals / risks
- Does NOT change STAC bbox (still rectangular) — pruning is at tile granularity.
- `persistence_min > 0` breaks superset guarantee **by design**; loud docstring
  warning + default 0.
- Morphology needs `scipy`; already implied by raster extra? **Verify** — if
  not, add to `stac`/`raster` extra or implement closing via `rioxarray`/binary
  ops to avoid a new dep.

## Test/verify
- Full suite green (currently 224 pass, 2 pre-existing unrelated fails).
- New tests per task above, all offline (synthetic cubes, no live STAC).
- One integration test: pruned run `extent_pct` == unpruned run `extent_pct`
  (the anti-drift guarantee).
