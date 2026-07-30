# Wet-AOI Precompute + Tile Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Precompute a "wet AOI" (union of all ever-wet pixels over the full time series) once, then use it to prune whole STAC tile fetches that never touch water — a bandwidth win layered on the existing native tiler.

**Architecture:** A pure reducer collapses a canonical mask cube to an "ever wet" 2D raster, which is vectorized and buffered (in meters, via shapely geometry ops) into a wet-AOI polygon. That polygon feeds `iter_wofs_tiles_from_stac` as a *second* tile-skip predicate beside the existing `_tile_intersects_aoi` gate. Wet AOI prunes which tiles load; it never replaces the user-AOI clip, so extent denominators are unchanged. The wet-AOI content hash enters the extent cache identity so a stale wet AOI cannot poison cached results.

**Tech Stack:** Python 3.10+, numpy, pandas, xarray, rioxarray, rasterio, shapely, geopandas, odc.stac (all already in the `raster`/`stac` extras — **no new dependency**).

## Global Constraints

- **No new dependencies.** `scipy` is NOT in the raster extra. Morphology (closing) MUST be done in geometry space via `shapely` buffer±, never `scipy.ndimage`.
- All geospatial imports stay **inside function bodies** (module import must not require optional deps) — matches the existing `_io_geo.py` convention.
- Canonical mask values: water `1`, dry `0`, invalid `-1`, outside `-2`.
- Buffer and closing distances are expressed in **meters** (scale-invariant), never pixels.
- Default `persistence_min = 0.0` (any wet obs ⇒ included; preserves the superset guarantee). Default `close_m = 150.0`. Default `buffer_m = 300.0`.
- Preserve georeferencing on every raster op via the existing `_preserve_georef` helper in `_io_geo.py`.
- Target working CRS for wet AOI is the same as the tiler's `target` (EPSG:3577 Albers by default) so geometries compose with tile geoboxes.
- TDD, DRY, YAGNI, frequent commits. All new tests run offline (synthetic cubes / geometries, no live STAC).

---

## File Structure

- **Create** `hydroseason/_wet_aoi.py` — wet-AOI computation: reducer (`compute_ever_wet`), vectorize+buffer (`wet_aoi_polygon`), top-level `compute_wet_aoi`, and the tile-intersection predicate (`tile_intersects_wet_aoi`). One responsibility: turning a mask cube into a wet-AOI polygon and testing tiles against it.
- **Modify** `hydroseason/_io_geo.py` — add `wet_aoi=None` param to `iter_wofs_tiles_from_stac`; add the second skip predicate at the existing tile loop.
- **Modify** `hydroseason/io.py` — re-export the new public names through the facade.
- **Modify** `hydroseason/_io_extent_cache.py` — add `wet_aoi_hash` to cache identity, bump schema version, add `wet_aoi`/`precompute_wet_aoi` params, add `wet_fill_pct` column.
- **Create** `tests/test_wet_aoi.py` — reducer + morphology + vectorize + predicate tests.
- **Modify** `tests/test_io.py` (or a new `tests/test_io_wet_aoi_pruning.py`) — tiler pruning + anti-drift integration test.
- **Modify** `tests/test_io_extent_cache.py` — cache-identity + `wet_fill_pct` tests.

---

### Task 1: Ever-wet reducer

**Files:**
- Create: `hydroseason/_wet_aoi.py`
- Test: `tests/test_wet_aoi.py`

**Interfaces:**
- Consumes: a canonical `xarray.DataArray` mask cube with dims `(time, y, x)` and int8 values in `{-2,-1,0,1}`, georeferenced (rioxarray `.rio` accessor).
- Produces: `compute_ever_wet(mask, *, persistence_min: float = 0.0) -> xr.DataArray` — a 2D boolean DataArray (dims `(y, x)`, georef preserved) that is `True` where a pixel is part of the wet AOI. At `persistence_min == 0.0` it is `(mask == 1).any("time")`. At `persistence_min > 0.0` it is `wet_count / clear_count >= persistence_min` where `clear_count = (mask == 0) | (mask == 1)` summed over time, and pixels with `clear_count == 0` are `False`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wet_aoi.py
import numpy as np
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("rioxarray")

from hydroseason._wet_aoi import compute_ever_wet


def _cube(values):
    """values: list of 2D int8 arrays, one per time step."""
    arr = np.stack(values).astype(np.int8)
    da = xr.DataArray(arr, dims=("time", "y", "x"),
                      coords={"time": range(len(values)),
                              "y": [0, 1], "x": [0, 1]})
    return da.rio.write_crs("EPSG:3577")


def test_ever_wet_default_includes_pixel_wet_once():
    # pixel (0,0) wet exactly once across 3 steps; rest always dry
    dry = np.zeros((2, 2), np.int8)
    wet_once = dry.copy()
    wet_once[0, 0] = 1
    cube = _cube([dry, wet_once, dry])

    result = compute_ever_wet(cube)  # persistence_min defaults to 0.0

    assert result.dims == ("y", "x")
    assert bool(result.sel(y=0, x=0)) is True
    assert bool(result.sel(y=1, x=1)) is False


def test_persistence_threshold_excludes_rare_pixel():
    dry = np.zeros((2, 2), np.int8)
    wet_once = dry.copy()
    wet_once[0, 0] = 1
    cube = _cube([dry, wet_once, dry])  # (0,0) wet 1 of 3 clear = 0.333

    included = compute_ever_wet(cube, persistence_min=0.3)
    excluded = compute_ever_wet(cube, persistence_min=0.5)

    assert bool(included.sel(y=0, x=0)) is True
    assert bool(excluded.sel(y=0, x=0)) is False


def test_persistence_denominator_is_clear_not_scene_count():
    # (0,0): wet once, invalid once, no dry -> clear_count=1, wet/clear=1.0
    dry = np.zeros((2, 2), np.int8)
    wet = dry.copy(); wet[0, 0] = 1
    invalid = dry.copy(); invalid[0, 0] = -1
    cube = _cube([wet, invalid, dry])
    # If denominator were scene_count (3): 1/3=0.33 -> excluded at 0.5
    # With clear denominator (wet+dry at that pixel = 1+1=2): 1/2=0.5 -> included at 0.5
    result = compute_ever_wet(cube, persistence_min=0.5)
    assert bool(result.sel(y=0, x=0)) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_wet_aoi.py -v`
Expected: FAIL with `ImportError` / `ModuleNotFoundError: hydroseason._wet_aoi`.

- [ ] **Step 3: Write minimal implementation**

```python
# hydroseason/_wet_aoi.py
"""Wet-AOI precompute: collapse a mask cube to an ever-wet region and buffer it.

All geospatial imports stay inside function bodies so importing this module
never requires the raster/stac extras -- only calling a function that needs
one does. Distances are meters (scale-invariant). Morphology is done in
geometry space via shapely buffer, never scipy (not a dependency).
"""

from __future__ import annotations

import numpy as np

from hydroseason._io_geo import _preserve_georef


def compute_ever_wet(mask, *, persistence_min: float = 0.0):
    """Collapse a canonical (time, y, x) mask cube to a 2D wet-AOI boolean.

    At ``persistence_min == 0.0`` a pixel is in the wet AOI if it was water in
    *any* time step -- this preserves the superset guarantee (no ever-wet pixel
    is dropped). A positive ``persistence_min`` is an opt-in denoise knob: a
    pixel is kept only when ``wet_count / clear_count >= persistence_min``,
    where ``clear_count`` counts explicitly water-or-dry observations at that
    pixel (matching the ``n_valid`` denominator semantics of
    ``monthly_water_extent``). Pixels never observed clear are excluded.

    WARNING: any ``persistence_min > 0`` breaks the superset guarantee by
    design -- rare-but-real floods below the threshold are cut from the AOI and
    will read as zero water there forever. Leave at 0.0 unless you explicitly
    want denoising.
    """
    ever_wet = (mask == 1).any("time")
    if persistence_min <= 0.0:
        return _preserve_georef(ever_wet, mask)

    wet_count = (mask == 1).sum("time")
    clear_count = ((mask == 0) | (mask == 1)).sum("time")
    persistence = wet_count / clear_count.where(clear_count > 0)
    kept = (persistence >= persistence_min).fillna(False)
    return _preserve_georef(kept, mask)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_wet_aoi.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_wet_aoi.py tests/test_wet_aoi.py
git commit -m "feat: add ever-wet reducer for wet-AOI precompute"
```

---

### Task 2: Vectorize + close + buffer to a wet-AOI polygon

**Files:**
- Modify: `hydroseason/_wet_aoi.py`
- Test: `tests/test_wet_aoi.py`

**Interfaces:**
- Consumes: the 2D boolean DataArray from `compute_ever_wet` (georeferenced, CRS in meters e.g. EPSG:3577).
- Produces: `wet_aoi_polygon(ever_wet, *, close_m: float = 150.0, buffer_m: float = 300.0) -> "geopandas.GeoDataFrame"` — a single-row (dissolved) GeoDataFrame in the raster's CRS whose geometry is the ever-wet region morphologically **closed** (fill gaps / connect thin channels) then buffered outward by `buffer_m`. Closing is `buffer(+close_m).buffer(-close_m)` in geometry space; the outward buffer is a final `buffer(+buffer_m)`. Returns an empty-geometry GeoDataFrame (not an error) when no pixel is wet.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wet_aoi.py  (append)
def _wet_grid(bool_2d, *, res=30.0):
    """Build a georeferenced boolean DataArray on a res-meter grid at origin."""
    h, w = bool_2d.shape
    da = xr.DataArray(
        np.asarray(bool_2d, dtype=bool),
        dims=("y", "x"),
        coords={"y": np.arange(h) * -res, "x": np.arange(w) * res},
    )
    return da.rio.write_crs("EPSG:3577").rio.write_transform()


def test_wet_aoi_polygon_buffers_outward_in_meters():
    from hydroseason._wet_aoi import wet_aoi_polygon
    grid = np.zeros((5, 5), bool)
    grid[2, 2] = True  # single wet pixel
    gdf = wet_aoi_polygon(_wet_grid(grid), close_m=0.0, buffer_m=300.0)
    assert len(gdf) == 1
    assert str(gdf.crs).endswith("3577")
    # one 30m pixel (~900 m2) buffered by 300m must be far larger than raw pixel
    assert gdf.geometry.area.iloc[0] > 300.0 ** 2


def test_wet_aoi_closing_connects_gap():
    from hydroseason._wet_aoi import wet_aoi_polygon
    # two wet pixels separated by one dry pixel horizontally, 30m apart
    grid = np.zeros((3, 5), bool)
    grid[1, 1] = True
    grid[1, 3] = True
    # closing radius >= the 30m gap should merge into ONE polygon; buffer 0
    gdf = wet_aoi_polygon(_wet_grid(grid), close_m=60.0, buffer_m=0.0)
    assert len(gdf) == 1
    assert gdf.geometry.iloc[0].geom_type in ("Polygon", "MultiPolygon")
    # merged extent spans both pixels: bounds width > 2 pixels
    minx, _, maxx, _ = gdf.total_bounds
    assert maxx - minx >= 60.0


def test_wet_aoi_polygon_empty_when_no_wet():
    from hydroseason._wet_aoi import wet_aoi_polygon
    grid = np.zeros((4, 4), bool)
    gdf = wet_aoi_polygon(_wet_grid(grid), buffer_m=300.0)
    assert gdf.empty or gdf.geometry.is_empty.all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_wet_aoi.py -k wet_aoi_polygon -v`
Expected: FAIL with `ImportError: cannot import name 'wet_aoi_polygon'`.

- [ ] **Step 3: Write minimal implementation**

```python
# hydroseason/_wet_aoi.py  (append)
def wet_aoi_polygon(ever_wet, *, close_m: float = 150.0, buffer_m: float = 300.0):
    """Vectorize an ever-wet boolean raster, morphologically close it, and buffer.

    Closing (dilate-then-erode, ``buffer(+close_m).buffer(-close_m)``) fills mask
    gaps and reconnects thin channels *without* deleting them -- doing raw erosion
    first would permanently drop 1-2px rivers. The final outward ``buffer_m``
    grows a safety margin. All distances are meters, so the result is invariant
    to pixel size. Returns a single dissolved GeoDataFrame row in the raster CRS.
    """
    import geopandas as gpd
    import rasterio.features
    from shapely.geometry import shape
    from shapely.ops import unary_union

    crs = ever_wet.rio.crs
    transform = ever_wet.rio.transform()
    data = np.asarray(ever_wet.values, dtype=np.uint8)

    geometries = [
        shape(geom)
        for geom, value in rasterio.features.shapes(data, transform=transform)
        if value == 1
    ]
    if not geometries:
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)

    merged = unary_union(geometries)
    if close_m > 0.0:
        merged = merged.buffer(close_m).buffer(-close_m)
    if buffer_m > 0.0:
        merged = merged.buffer(buffer_m)
    return gpd.GeoDataFrame({"geometry": [merged]}, geometry="geometry", crs=crs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_wet_aoi.py -v`
Expected: PASS (all wet-AOI tests).

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_wet_aoi.py tests/test_wet_aoi.py
git commit -m "feat: vectorize, close, and buffer ever-wet raster to wet-AOI polygon"
```

---

### Task 3: `compute_wet_aoi` top-level + tile-intersection predicate

**Files:**
- Modify: `hydroseason/_wet_aoi.py`
- Test: `tests/test_wet_aoi.py`

**Interfaces:**
- Consumes: a mask cube (for `compute_wet_aoi`); a tile geobox and a wet-AOI GeoDataFrame (for the predicate).
- Produces:
  - `compute_wet_aoi(mask, *, persistence_min=0.0, close_m=150.0, buffer_m=300.0) -> "geopandas.GeoDataFrame"` — convenience composition of `compute_ever_wet` then `wet_aoi_polygon`.
  - `tile_intersects_wet_aoi(tile_geobox, wet_aoi) -> bool` — `True` when `wet_aoi` is falsy/empty (fail-open: no wet AOI ⇒ never prune) OR the tile's bounding box intersects the wet-AOI geometry (reprojected to the tile CRS). Mirrors the existing `_tile_intersects_aoi` shape in `_io_geo.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wet_aoi.py  (append)
class _FakeBox:
    def __init__(self, left, bottom, right, top):
        self.left, self.bottom, self.right, self.top = left, bottom, right, top


class _FakeExtent:
    def __init__(self, bbox):
        self.boundingbox = bbox


class _FakeGeoBox:
    def __init__(self, bounds, crs="EPSG:3577"):
        self.extent = _FakeExtent(_FakeBox(*bounds))
        self.crs = crs


def test_tile_intersects_wet_aoi_true_and_false():
    from hydroseason._wet_aoi import tile_intersects_wet_aoi, wet_aoi_polygon
    grid = np.zeros((5, 5), bool)
    grid[2, 2] = True
    wet = wet_aoi_polygon(_wet_grid(grid), close_m=0.0, buffer_m=30.0)
    overlapping = _FakeGeoBox((0, -150, 150, 0))       # covers the wet pixel area
    far_away = _FakeGeoBox((1_000_000, -1_000_000, 1_000_030, -999_970))
    assert tile_intersects_wet_aoi(overlapping, wet) is True
    assert tile_intersects_wet_aoi(far_away, wet) is False


def test_tile_intersects_wet_aoi_fail_open_when_empty():
    from hydroseason._wet_aoi import tile_intersects_wet_aoi
    box = _FakeGeoBox((0, -30, 30, 0))
    assert tile_intersects_wet_aoi(box, None) is True  # no wet AOI -> never prune


def test_compute_wet_aoi_composes():
    from hydroseason._wet_aoi import compute_wet_aoi
    dry = np.zeros((2, 2), np.int8)
    wet = dry.copy(); wet[0, 0] = 1
    da = xr.DataArray(
        np.stack([dry, wet]).astype(np.int8),
        dims=("time", "y", "x"),
        coords={"time": [0, 1], "y": [0.0, -30.0], "x": [0.0, 30.0]},
    ).rio.write_crs("EPSG:3577").rio.write_transform()
    gdf = compute_wet_aoi(da, buffer_m=30.0)
    assert len(gdf) == 1
    assert not gdf.geometry.is_empty.all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_wet_aoi.py -k "intersects or composes" -v`
Expected: FAIL with `ImportError` for `tile_intersects_wet_aoi` / `compute_wet_aoi`.

- [ ] **Step 3: Write minimal implementation**

```python
# hydroseason/_wet_aoi.py  (append)
def compute_wet_aoi(mask, *, persistence_min: float = 0.0,
                    close_m: float = 150.0, buffer_m: float = 300.0):
    """End-to-end: mask cube -> ever-wet boolean -> closed+buffered wet-AOI polygon."""
    ever_wet = compute_ever_wet(mask, persistence_min=persistence_min)
    return wet_aoi_polygon(ever_wet, close_m=close_m, buffer_m=buffer_m)


def tile_intersects_wet_aoi(tile_geobox, wet_aoi) -> bool:
    """True if the tile bbox intersects the wet AOI; fail-open when wet AOI absent.

    A missing or empty ``wet_aoi`` means "no pruning information" -- return True
    so the caller never drops a tile it should have loaded. Mirrors the bbox
    test in ``_io_geo._tile_intersects_aoi``.
    """
    if wet_aoi is None or len(wet_aoi) == 0 or bool(wet_aoi.geometry.is_empty.all()):
        return True
    from shapely.geometry import box

    bounds = tile_geobox.extent.boundingbox
    tile_polygon = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
    return bool(wet_aoi.to_crs(tile_geobox.crs).geometry.intersects(tile_polygon).any())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_wet_aoi.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_wet_aoi.py tests/test_wet_aoi.py
git commit -m "feat: add compute_wet_aoi and tile_intersects_wet_aoi predicate"
```

---

### Task 4: Wire wet-AOI pruning into `iter_wofs_tiles_from_stac`

**Files:**
- Modify: `hydroseason/_io_geo.py:354-414` (the `iter_wofs_tiles_from_stac` signature and tile loop)
- Modify: `hydroseason/io.py:15-44` (facade re-exports)
- Test: `tests/test_io.py`

**Interfaces:**
- Consumes: `compute_wet_aoi` is NOT called here — the caller passes an already-computed `wet_aoi` GeoDataFrame (or `None`). `tile_intersects_wet_aoi` from `_wet_aoi`.
- Produces: `iter_wofs_tiles_from_stac(..., wet_aoi=None)` — new keyword-only param appended to the existing signature. When `wet_aoi` is not `None`, a tile is loaded only if it passes BOTH `_tile_intersects_aoi(tile_geobox, target)` AND `tile_intersects_wet_aoi(tile_geobox, wet_aoi)`. **Invariant:** wet AOI decides *which tiles load*; the per-tile `_clip_to_aoi` still clips to the user AOI (`target`), so the `n_aoi` denominator in downstream extent is unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_io.py  (append; reuse existing STAC monkeypatch fixtures/helpers in this file)
def test_iter_tiles_prunes_tiles_outside_wet_aoi(monkeypatch, tmp_path):
    """A tile inside the user AOI but outside the wet AOI must be skipped,
    and the wet AOI must NOT alter the user-AOI clip of loaded tiles."""
    import geopandas as gpd
    from shapely.geometry import box
    import hydroseason._io_geo as geo

    loaded_tile_ids = []
    real_load = geo._load_wofs_items

    def _spy_load(items, aoi_gdf, *args, **kwargs):
        # record every tile actually loaded via its geobox extent
        gb = kwargs.get("geobox")
        loaded_tile_ids.append(tuple(round(v) for v in (
            gb.extent.boundingbox.left, gb.extent.boundingbox.bottom)))
        return real_load(items, aoi_gdf, *args, **kwargs)

    monkeypatch.setattr(geo, "_load_wofs_items", _spy_load)

    # Build a wet AOI that covers only the left half of the AOI bbox.
    # (Use the same synthetic AOI + fake STAC client the other tiler tests use.)
    # ... set up aoi, fake client returning items over a 2-tile-wide extent ...
    # wet AOI = left tile only:
    wet = gpd.GeoDataFrame({"geometry": [box(LEFT, BOTTOM, MID_X, TOP)]},
                           geometry="geometry", crs="EPSG:3577")

    tiles = list(geo.iter_wofs_tiles_from_stac(
        STAC_URL, COLLECTION, aoi, "2020-01-01", "2020-12-31",
        crs=3577, resolution=30.0, tile_pixels=TILE_PX, wet_aoi=wet,
    ))

    # right-half tile center must never appear in loaded ids
    assert all(x < MID_X for (x, _y) in loaded_tile_ids)
    # and at least the left tile WAS produced
    assert len(tiles) >= 1
```

> Note for the implementer: this test must be fleshed out against the existing
> fake-STAC scaffolding already present in `tests/test_io.py` (the same fixtures
> used by the current `iter_wofs_tiles_from_stac` tests). Reuse those helpers for
> `STAC_URL`, `COLLECTION`, `aoi`, the fake client, `TILE_PX`, and the
> `LEFT/MID_X/RIGHT/BOTTOM/TOP` bbox constants rather than inventing new ones.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_io.py -k prunes_tiles_outside_wet_aoi -v`
Expected: FAIL — `iter_wofs_tiles_from_stac() got an unexpected keyword argument 'wet_aoi'`.

- [ ] **Step 3: Write minimal implementation**

Edit `hydroseason/_io_geo.py`. Add the param to the signature (append keyword-only, after `duplicate_month_policy`):

```python
def iter_wofs_tiles_from_stac(
    stac_url: str, collection: str, aoi, start_date: str, end_date: str, *, crs: int | str | None = 3577,
    resolution: float, tile_pixels: int, skip_tile_ids: Collection[str] = (),
    chunk_x: int = 512, chunk_y: int = 512, time_chunk: int = 24, majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise",
    wet_aoi=None,
) -> Iterator[tuple[str, "object"]]:
```

Then change the tile loop (the block currently at lines 394-414) so the wet-AOI predicate gates loading alongside the existing AOI-bbox test:

```python
    from hydroseason._wet_aoi import tile_intersects_wet_aoi

    for tile_id, ys, xs in _tile_slices(parent_geobox.shape, tile_pixels):
        if tile_id in skip_tile_ids:
            continue
        tile_geobox = parent_geobox[ys, xs]
        if not _tile_intersects_aoi(tile_geobox, target):
            continue
        # Wet-AOI pruning: skip tiles the full-TS water union never touches.
        # This decides which tiles load; the user-AOI clip below is unchanged,
        # so extent denominators (n_aoi) stay measured against the user AOI.
        if not tile_intersects_wet_aoi(tile_geobox, wet_aoi):
            continue
        mask = _load_wofs_items(
            items,
            aoi_gdf,
            start_date,
            end_date,
            crs=crs,
            resolution=resolution,
            geobox=tile_geobox,
            chunk_x=chunk_x,
            chunk_y=chunk_y,
            time_chunk=time_chunk,
            majority=majority,
            duplicate_month_policy=duplicate_month_policy,
        )
        yield tile_id, mask
```

No facade change is strictly required for `iter_wofs_tiles_from_stac` (already re-exported at `io.py:43`), but add `compute_wet_aoi` and `tile_intersects_wet_aoi` re-exports so callers reach them through `hydroseason.io`:

```python
# hydroseason/io.py  (add near the other _io_geo imports, ~line 44)
from hydroseason._wet_aoi import compute_wet_aoi, tile_intersects_wet_aoi  # noqa: F401
```

And append `"compute_wet_aoi"` to `io.py`'s `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_io.py -k prunes_tiles_outside_wet_aoi -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_io_geo.py hydroseason/io.py tests/test_io.py
git commit -m "feat: prune tiles outside wet AOI in iter_wofs_tiles_from_stac"
```

---

### Task 5: Cache identity + precompute reuse in `load_wofs_monthly_extent`

**Files:**
- Modify: `hydroseason/_io_extent_cache.py:17` (schema version), `:43-67` (`_cache_path`), `:147-320` (`load_wofs_monthly_extent`)
- Test: `tests/test_io_extent_cache.py`

**Interfaces:**
- Consumes: `iter_wofs_tiles_from_stac(..., wet_aoi=...)` (Task 4); `compute_wet_aoi` (Task 3); `load_wofs_from_stac` for the precompute full-TS pass.
- Produces: `load_wofs_monthly_extent(..., wet_aoi=None, precompute_wet_aoi=False, persistence_min=0.0, close_m=150.0, buffer_m=300.0)`. When `precompute_wet_aoi=True` and no `wet_aoi` is passed, one full-TS `load_wofs_from_stac` pass computes the wet AOI (via `compute_wet_aoi`), which is then passed into the tiled per-year loads. The wet-AOI content hash enters `_cache_path` identity so a different wet AOI never reads a stale cache. `precompute_wet_aoi` requires `tile_pixels` (raises `ValueError` otherwise — pruning only exists on the tiled path).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_io_extent_cache.py  (append)
def test_cache_path_depends_on_wet_aoi_hash(tmp_path):
    from hydroseason._io_extent_cache import _cache_path
    import pandas as pd
    common = dict(
        cache_dir=tmp_path, stac_url="s", collection="c", aoi_hash="a",
        start=pd.Timestamp("2020-01-01"), end=pd.Timestamp("2020-12-31"),
        crs=3577, resolution=30.0, majority=True,
    )
    p_none = _cache_path(**common, wet_aoi_hash="")
    p_wet = _cache_path(**common, wet_aoi_hash="deadbeef")
    assert p_none != p_wet  # wet AOI is data-affecting -> distinct cache file


def test_precompute_requires_tile_pixels(tmp_path):
    from hydroseason._io_extent_cache import load_wofs_monthly_extent
    import pytest
    with pytest.raises(ValueError, match="tile_pixels"):
        load_wofs_monthly_extent(
            "s", "c", AOI_FIXTURE, "2020-01-01", "2020-12-31",
            cache_dir=tmp_path, resolution=30.0,
            precompute_wet_aoi=True,  # no tile_pixels -> error
        )
```

> `AOI_FIXTURE` = reuse the AOI fixture already used by other tests in this file.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_io_extent_cache.py -k "wet_aoi_hash or precompute_requires" -v`
Expected: FAIL — `_cache_path() got an unexpected keyword argument 'wet_aoi_hash'` and no `precompute_wet_aoi` param.

- [ ] **Step 3: Write minimal implementation**

In `_io_extent_cache.py`:

Bump the schema version (line 17):

```python
_CACHE_SCHEMA_VERSION = 2
```

Add `wet_aoi_hash` to `_cache_path` (signature + identity dict):

```python
def _cache_path(
    cache_dir: Path,
    *,
    stac_url: str,
    collection: str,
    aoi_hash: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    crs,
    resolution,
    majority: bool,
    wet_aoi_hash: str = "",
) -> Path:
    identity = {
        "schema": _CACHE_SCHEMA_VERSION,
        "stac_url": stac_url,
        "collection": collection,
        "aoi_sha256": aoi_hash,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "crs": crs,
        "resolution": resolution,
        "majority": majority,
        "wet_aoi_sha256": wet_aoi_hash,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"extent_{start:%Y%m%d}_{end:%Y%m%d}_{digest}.csv"
```

Add params + precompute to `load_wofs_monthly_extent`. New keyword args after `tile_pixels`:

```python
    tile_pixels: int | None = None,
    wet_aoi=None,
    precompute_wet_aoi: bool = False,
    persistence_min: float = 0.0,
    close_m: float = 150.0,
    buffer_m: float = 300.0,
```

Immediately after the `tile_pixels` validation block (~line 186), add:

```python
    if precompute_wet_aoi and tile_pixels is None:
        raise ValueError("precompute_wet_aoi requires tile_pixels (pruning is tiled-only).")
```

After `import hydroseason.io as _io` (~line 197), compute the wet AOI once if requested and not supplied:

```python
    if precompute_wet_aoi and wet_aoi is None:
        from hydroseason._wet_aoi import compute_wet_aoi
        full_ts = _io.load_wofs_from_stac(
            stac_url, collection, aoi,
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
            crs=crs, resolution=resolution,
            chunk_x=chunk_x, chunk_y=chunk_y, time_chunk=time_block, majority=majority,
        )
        wet_aoi = compute_wet_aoi(
            full_ts, persistence_min=persistence_min, close_m=close_m, buffer_m=buffer_m,
        )
```

Compute a wet-AOI hash for cache identity (near where `aoi_hash` is set, ~line 192):

```python
    wet_aoi_hash = _aoi_digest(wet_aoi) if (cache_root is not None and wet_aoi is not None) else ""
```

Thread `wet_aoi_hash=wet_aoi_hash` into every `_cache_path(...)` call, and pass `wet_aoi=wet_aoi` into the `_io.iter_wofs_tiles_from_stac(...)` call inside the tiled branch (~line 238).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_io_extent_cache.py -k "wet_aoi_hash or precompute_requires" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_io_extent_cache.py tests/test_io_extent_cache.py
git commit -m "feat: wet-AOI hash in extent cache identity + optional precompute"
```

---

### Task 6: `wet_fill_pct` second ratio (drought signal)

**Files:**
- Modify: `hydroseason/_io_extent_cache.py:18-25` (`_EXTENT_COLUMNS`), `:95-144` (`_missing_year_extent`, `_aggregate_extent_parts`)
- Modify: `hydroseason/hydro_year.py:152+` (`monthly_water_extent`) — add `n_wet_aoi` count + `wet_fill_pct`
- Test: `tests/test_io_extent_cache.py`, `tests/test_hydro_year.py`

**Interfaces:**
- Consumes: the per-tile water mask (already clipped to user AOI) plus the wet-AOI polygon, so `monthly_water_extent` can count pixels inside the wet AOI (`n_wet_aoi`).
- Produces: two new columns propagated through caching and aggregation:
  - `n_wet_aoi` — per-month count of pixels inside the wet AOI (integer, summable across tiles like `n_aoi`).
  - `wet_fill_pct` — `100 * n_water / n_wet_aoi` (NaN when `n_wet_aoi == 0`). Low value in a month with a large wet AOI = drought signal. `extent_pct` (vs user AOI) is untouched.

> **Decision required at implementation time:** `monthly_water_extent` currently
> takes only a mask. To count `n_wet_aoi` it needs the wet-AOI geometry OR a
> precomputed per-tile "inside wet AOI" boolean. Simplest DRY approach: pass an
> optional `wet_aoi=None` to `monthly_water_extent`; when given, rasterize it
> against the mask grid via the existing `_inside_aoi_mask_like` helper in
> `_io_geo.py` and count `(inside_wet & (mask != outside_value))`. When `None`,
> set `n_wet_aoi = n_aoi` and `wet_fill_pct = extent_pct` (backward compatible).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hydro_year.py  (append)
def test_monthly_extent_wet_fill_pct_drought_signal():
    import numpy as np, pytest
    xr = pytest.importorskip("xarray")
    pytest.importorskip("rioxarray")
    import geopandas as gpd
    from shapely.geometry import box
    from hydroseason.hydro_year import monthly_water_extent

    # 4x4 user AOI; wet AOI = whole grid; one water pixel this month
    mask = xr.DataArray(
        np.full((1, 4, 4), 0, np.int8),  # all dry
        dims=("time", "y", "x"),
        coords={"time": [np.datetime64("2020-01-01")],
                "y": np.arange(4) * -30.0, "x": np.arange(4) * 30.0},
    ).rio.write_crs("EPSG:3577").rio.write_transform()
    mask[0, 0, 0] = 1  # single wet pixel

    wet = gpd.GeoDataFrame({"geometry": [box(-15, -105, 105, 15)]},
                           geometry="geometry", crs="EPSG:3577")
    df = monthly_water_extent(mask, wet_aoi=wet)
    # 1 water / 16 wet-aoi pixels -> ~6.25%
    assert df["wet_fill_pct"].iloc[0] == pytest.approx(6.25, abs=0.5)
    # extent_pct (vs user AOI = all 16 valid) also 6.25 here, but column exists distinctly
    assert "n_wet_aoi" in df.columns


def test_monthly_extent_wet_fill_defaults_to_extent_when_no_wet_aoi():
    import numpy as np, pytest
    xr = pytest.importorskip("xarray")
    pytest.importorskip("rioxarray")
    from hydroseason.hydro_year import monthly_water_extent
    mask = xr.DataArray(
        np.array([[[1, 0], [0, 0]]], np.int8),
        dims=("time", "y", "x"),
        coords={"time": [np.datetime64("2020-01-01")],
                "y": [0.0, -30.0], "x": [0.0, 30.0]},
    ).rio.write_crs("EPSG:3577").rio.write_transform()
    df = monthly_water_extent(mask)  # no wet_aoi
    assert df["n_wet_aoi"].iloc[0] == df["n_aoi"].iloc[0]
    assert df["wet_fill_pct"].iloc[0] == df["extent_pct"].iloc[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_hydro_year.py -k wet_fill -v`
Expected: FAIL — `KeyError: 'wet_fill_pct'` / `monthly_water_extent() got an unexpected keyword argument 'wet_aoi'`.

- [ ] **Step 3: Write minimal implementation**

In `hydroseason/hydro_year.py`, add `wet_aoi=None` param to `monthly_water_extent`. After computing `n_aoi_block`/`n_water_block` per block, compute the inside-wet count. When `wet_aoi is None`, set `n_wet_aoi = n_aoi` and `wet_fill_pct = extent_pct`. Otherwise rasterize once (grid is time-invariant):

```python
    inside_wet = None
    if wet_aoi is not None:
        from hydroseason._io_geo import _inside_aoi_mask_like
        import geopandas as gpd
        gdf = wet_aoi if isinstance(wet_aoi, gpd.GeoDataFrame) else gpd.GeoDataFrame(
            {"geometry": [wet_aoi]}, geometry="geometry", crs=water_mask.rio.crs)
        inside_wet = _inside_aoi_mask_like(water_mask.isel(time=0), gdf.to_crs(water_mask.rio.crs))
```

Then per block: `n_wet_aoi_block = ((block != outside_value) & inside_wet).sum(dim=dims)` when `inside_wet` is set, else `= n_aoi_block`. After assembling the frame, add:

```python
    frame["n_wet_aoi"] = n_wet_aoi_series
    with np.errstate(invalid="ignore", divide="ignore"):
        frame["wet_fill_pct"] = np.where(
            frame["n_wet_aoi"] > 0,
            100.0 * frame["n_water"] / frame["n_wet_aoi"],
            np.nan,
        )
```

In `_io_extent_cache.py`, extend `_EXTENT_COLUMNS`:

```python
_EXTENT_COLUMNS = (
    "n_water", "n_aoi", "n_valid", "n_invalid",
    "n_wet_aoi", "extent_pct", "invalid_pct", "wet_fill_pct",
)
```

Add `n_wet_aoi` to the `count_columns` summed in `_aggregate_extent_parts`, recompute `wet_fill_pct` from summed totals there (same pattern as `extent_pct`), and add `n_wet_aoi=0` / `wet_fill_pct=float("nan")` to `_missing_year_extent`. Thread `wet_aoi=wet_aoi` into the `monthly_water_extent(...)` call in the tiled branch (~line 274).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_hydro_year.py -k wet_fill tests/test_io_extent_cache.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/hydro_year.py hydroseason/_io_extent_cache.py tests/test_hydro_year.py tests/test_io_extent_cache.py
git commit -m "feat: add n_wet_aoi and wet_fill_pct drought-signal ratio"
```

---

### Task 7: Anti-drift integration test + full-suite verification

**Files:**
- Test: `tests/test_io.py` (or `tests/test_io_wet_aoi_pruning.py`)

**Interfaces:**
- Consumes: everything above. No new production code — this task is the guarantee that pruning does not change results.

- [ ] **Step 1: Write the failing test**

The critical no-silent-drift guarantee: an extent run WITH wet-AOI pruning must produce the **same `extent_pct`** (user-AOI denominator) as the same run WITHOUT pruning, because a pruned tile is all-dry-not-water in the union anyway.

```python
# tests/test_io.py  (append)
def test_wet_aoi_pruning_does_not_change_extent_pct(monkeypatch, tmp_path):
    """extent_pct with pruning == extent_pct without pruning.

    Uses the same fake-STAC scaffolding as the other tiler tests. Build items
    where the right-half tiles are ALWAYS dry (never water). Their union
    contributes no wet pixel, so wet-AOI pruning drops them -- and because they
    were only dry, the user-AOI extent_pct is identical with or without them.
    """
    # ... reuse fake STAC + AOI fixtures; construct a full-TS where the wet
    #     union covers only the left tiles ...
    unpruned = load_wofs_monthly_extent(
        STAC_URL, COLLECTION, aoi, "2020-01-01", "2020-12-31",
        cache_dir=tmp_path / "a", resolution=30.0, tile_pixels=TILE_PX,
    )
    pruned = load_wofs_monthly_extent(
        STAC_URL, COLLECTION, aoi, "2020-01-01", "2020-12-31",
        cache_dir=tmp_path / "b", resolution=30.0, tile_pixels=TILE_PX,
        precompute_wet_aoi=True,
    )
    pd.testing.assert_series_equal(
        unpruned["extent_pct"], pruned["extent_pct"], check_names=False
    )
```

- [ ] **Step 2: Run test to verify it fails (or drives out bugs)**

Run: `.venv_hydroseason/Scripts/python -m pytest tests/test_io.py -k pruning_does_not_change_extent_pct -v`
Expected: FAIL initially if any denominator leak exists; the goal is to make it PASS by construction (Task 4 invariant). If it fails because pruning altered `extent_pct`, the wet-AOI clip leaked into the denominator — fix in Task 4's tile loop, not here.

- [ ] **Step 3: (no new production code — this test validates the invariant)**

If the test fails, the bug is a denominator leak; the fix is ensuring `_clip_to_aoi` in `_load_wofs_items` still clips to `target` (user AOI), never to the wet AOI. Re-read `_io_geo.py` tile loop.

- [ ] **Step 4: Run the full suite**

Run: `.venv_hydroseason/Scripts/python -m pytest -q`
Expected: All previously-passing tests still pass (baseline was 224 passed, 2 pre-existing unrelated failures — those 2 may remain failing; no NEW failures). New wet-AOI tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_io.py
git commit -m "test: wet-AOI pruning preserves user-AOI extent_pct (anti-drift)"
```

---

## Self-Review Notes

- **Flaw 1 (superset)** → Task 1: default `persistence_min=0.0` = `any` reduce; loud docstring warning. Covered.
- **Flaw 2 (denominator)** → Task 1: persistence uses `wet/clear` per pixel; `test_persistence_denominator_is_clear_not_scene_count` locks it. Covered.
- **Flaw 3 (closing vs opening)** → Task 2: closing = `buffer(+close_m).buffer(-close_m)`; `test_wet_aoi_closing_connects_gap` locks it; thin channels never eroded away first. Covered.
- **Flaw 4 (meters not pixels)** → Task 2: `close_m`/`buffer_m` in meters via shapely geometry ops, no pixel rounding. Covered.
- **Flaw 5 (two denominators + no drift)** → Task 6 (`wet_fill_pct`) + Task 4 invariant + Task 7 anti-drift test. Covered.
- **Flaw 6 (one-shot no gain)** → Task 5: precompute is opt-in (`precompute_wet_aoi=False` default), cacheable/reusable; documented as a win only on repeat/prune-heavy runs. Covered.
- **No new dep:** confirmed `scipy` absent from `raster` extra; morphology is shapely-only. Covered by Global Constraints.
- **Cache poison risk:** Task 5 puts `wet_aoi_sha256` in identity + schema bump 1→2. Covered.
- **Type consistency:** `compute_ever_wet` → `wet_aoi_polygon` → `compute_wet_aoi` → `tile_intersects_wet_aoi` → `iter_wofs_tiles_from_stac(wet_aoi=)` → `load_wofs_monthly_extent(wet_aoi=, precompute_wet_aoi=)` → `monthly_water_extent(wet_aoi=)`. Names consistent across tasks.

**Open item for implementer (Task 4 & 7):** the two integration tests reference the existing fake-STAC scaffolding in `tests/test_io.py`. Before writing them, read the current `iter_wofs_tiles_from_stac` tests in that file and reuse their fixtures/constants rather than inventing new ones.
