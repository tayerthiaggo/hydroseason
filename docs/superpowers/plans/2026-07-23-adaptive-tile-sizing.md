# Adaptive Tile Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make auto-tiling pick a tile size that actually splits a thin-AOI bounding box into several tiles (so empty tiles get pruned), instead of disabling tiling whenever the AOI fits in one 2048px tile.

**Architecture:** Today `load_wofs_monthly_extent` calls `_aoi_spans_multiple_tiles`; when the AOI's bbox fits in one tile at the requested `tile_pixels`, it sets `tile_pixels = None` (untiled whole-bbox load). For a thin river in a large bbox this is the worst case: we decode the whole rectangle, ~93% of which is outside the AOI polygon and discarded by the clip. This plan replaces the "disable tiling" branch with an adaptive tile-size chooser that shrinks `tile_pixels` until the bbox spans a target number of tiles (measured sweet spot: a tile size yielding roughly 3-10 tiles), keeping the tiled + pruned path active so empty tiles are skipped.

**Tech Stack:** Python 3.11, numpy, pandas, geopandas (AOI bbox), odc.stac / rasterio (loaders, not touched here), pytest, ruff.

## Global Constraints

- Python `>=3.10`; target-version `py310` (from `pyproject.toml [tool.ruff]`).
- ruff config: `line-length = 100`, `select = ["E", "F", "I"]`, `ignore = ["E501"]`. Do NOT chase the IDE's 79-col E501 warnings; the repo ignores E501.
- Never break byte-identical extent output: a tiled+pruned run must aggregate to the same `n_water/n_aoi/n_valid/n_invalid/extent_pct/invalid_pct` as an untiled whole-bbox run over the same data (this is an existing repo invariant; see `test_tiled_reduction_matches_whole_cube_reduction_*`).
- Geospatial imports (geopandas, odc.stac, rasterio) stay inside function bodies, never module scope — established pattern in `hydroseason/_io_geo.py` and `_io_extent_cache.py`.
- Run tests with the `hydroseason` conda env active (`conda activate hydroseason`); the loaders need the stac/raster extras. Pure-geometry tests here do not hit the network.

**Measured baseline (Gilbert_river_buffer.geojson, 2015, res=30):** untiled whole-bbox = 40.4s/yr; tiled @1024px (3 tiles) = 24.1s/yr; @512px (10 tiles) = 27.3s; @256px (18 tiles) = 43.2s (per-tile overhead dominates). AOI polygon is 196 km² inside a 2945 km² bbox (7% fill, 15:1 waste). Target: keep tile count in the low single digits to low tens.

---

### Task 1: Add `_choose_tile_pixels` heuristic

**Files:**
- Modify: `hydroseason/_io_extent_cache.py` (add function near `_aoi_spans_multiple_tiles`, around line 133)
- Test: `tests/test_io_extent_cache.py` (append)

**Interfaces:**
- Consumes: `_crs_value_local(crs)` (existing, `_io_extent_cache.py:135`), `hydroseason.io.load_aoi` (existing).
- Produces: `_choose_tile_pixels(aoi, *, crs, resolution, requested_tile_pixels, target_tiles_max=12, min_tile_pixels=512) -> int | None`. Returns a tile-pixel size (<= `requested_tile_pixels`) chosen so the AOI bbox spans more than one tile but tiles stay >= `min_tile_pixels`; returns `None` when it cannot introspect the AOI (same fail-open contract as `_aoi_spans_multiple_tiles`). Never returns a value larger than `requested_tile_pixels`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_io_extent_cache.py`. Reuse the existing `_write_box_aoi` helper already in that file (writes a square AOI GeoJSON of a given metre span in a given CRS).

```python
def test_choose_tile_pixels_shrinks_for_single_tile_aoi(tmp_path):
    """A bbox that fits in one requested tile gets a smaller tile size so it
    splits into several tiles (enabling pruning), not disabled tiling."""
    pytest.importorskip("geopandas")
    from hydroseason._io_extent_cache import _choose_tile_pixels

    # 55 km bbox at 30 m: one 2048px tile spans ~61 km, so the bbox fits in
    # one tile at the default request -> must shrink.
    aoi = _write_box_aoi(tmp_path, "wide.geojson", crs="EPSG:3577", span_m=55_000)

    chosen = _choose_tile_pixels(
        aoi, crs=3577, resolution=30, requested_tile_pixels=2048,
    )

    assert chosen is not None
    assert chosen <= 2048
    # 55 km / (chosen * 30 m) must be > 1 on at least one axis (splits).
    assert 55_000 > chosen * 30
    # ...but not shrunk below the floor.
    assert chosen >= 512


def test_choose_tile_pixels_keeps_request_for_large_multi_tile_aoi(tmp_path):
    """An AOI already spanning many tiles at the requested size is left as-is."""
    pytest.importorskip("geopandas")
    from hydroseason._io_extent_cache import _choose_tile_pixels

    # 200 km bbox at 30 m already spans several 2048px (~61 km) tiles.
    aoi = _write_box_aoi(tmp_path, "huge.geojson", crs="EPSG:3577", span_m=200_000)

    chosen = _choose_tile_pixels(
        aoi, crs=3577, resolution=30, requested_tile_pixels=2048,
    )

    assert chosen == 2048  # no change needed


def test_choose_tile_pixels_returns_none_when_aoi_not_introspectable():
    """Fail-open: an un-loadable AOI yields None (caller keeps requested size)."""
    from hydroseason._io_extent_cache import _choose_tile_pixels

    chosen = _choose_tile_pixels(
        object(), crs=3577, resolution=30, requested_tile_pixels=2048,
    )

    assert chosen is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda activate hydroseason && python -m pytest tests/test_io_extent_cache.py::test_choose_tile_pixels_shrinks_for_single_tile_aoi -v`
Expected: FAIL with `ImportError: cannot import name '_choose_tile_pixels'`.

- [ ] **Step 3: Write minimal implementation**

Add to `hydroseason/_io_extent_cache.py` immediately after `_crs_value_local` (after line 138):

```python
def _choose_tile_pixels(
    aoi,
    *,
    crs,
    resolution,
    requested_tile_pixels,
    target_tiles_max: int = 12,
    min_tile_pixels: int = 512,
) -> int | None:
    """Pick a tile size that splits the AOI bbox into several prunable tiles.

    A thin AOI (e.g. a river buffer) can sit inside a large bounding box; at
    the default ``requested_tile_pixels`` the whole bbox may be a single tile,
    so tiling prunes nothing and we decode the entire rectangle (~93% of which
    a thin AOI discards on clip). Shrinking the tile size until the bbox spans
    more than one tile lets the tile-skip gate drop the empty tiles.

    Profiling (Gilbert_river_buffer, 2015, res=30): whole-bbox = 40.4s/yr,
    ~1024px (3 tiles) = 24.1s, ~512px (10 tiles) = 27.3s, ~256px (18 tiles) =
    43.2s -- per-tile overhead (graph build, COG opens) dominates once tiles
    get small/numerous, so we cap tile COUNT via ``target_tiles_max`` and floor
    the tile SIZE via ``min_tile_pixels`` rather than shrinking without bound.

    Returns a size in ``[min_tile_pixels, requested_tile_pixels]`` (halving
    ``requested_tile_pixels`` until the bbox spans >1 tile per axis or the
    floor is hit), or ``requested_tile_pixels`` unchanged when the bbox already
    spans multiple tiles there. Returns ``None`` when the AOI cannot be
    introspected without a STAC query -- same fail-open contract as
    :func:`_aoi_spans_multiple_tiles`, letting the caller keep the requested
    size.
    """
    if (
        resolution is None
        or resolution <= 0
        or requested_tile_pixels is None
        or requested_tile_pixels < 1
    ):
        return None
    try:
        import hydroseason.io as _io

        aoi_gdf = _io.load_aoi(aoi)
        target = aoi_gdf.to_crs(_crs_value_local(crs)) if crs is not None else aoi_gdf
        minx, miny, maxx, maxy = (float(v) for v in target.total_bounds)
    except Exception:
        return None

    span_m = max(maxx - minx, maxy - miny)
    tile_pixels = int(requested_tile_pixels)
    # Shrink (halving) while the whole span still fits in one tile, staying at
    # or above the size floor and not exceeding the tile-count cap.
    while (
        tile_pixels // 2 >= min_tile_pixels
        and span_m <= tile_pixels * float(resolution)
    ):
        halved = tile_pixels // 2
        # Stop if halving would push the tile count over the cap on the long
        # axis (each axis contributes ceil(span / tile_span_m) tiles).
        tile_span_m = halved * float(resolution)
        tiles_long_axis = int(-(-span_m // tile_span_m))  # ceil division
        if tiles_long_axis > target_tiles_max:
            break
        tile_pixels = halved
    return tile_pixels
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_io_extent_cache.py -k choose_tile_pixels -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_io_extent_cache.py tests/test_io_extent_cache.py
git commit -m "feat: add _choose_tile_pixels adaptive tile-size heuristic"
```

---

### Task 2: Use the heuristic in the auto-tiling branch

**Files:**
- Modify: `hydroseason/_io_extent_cache.py:461-474` (the `if auto_tiling ...` block)
- Test: `tests/test_io_extent_cache.py` (append)

**Interfaces:**
- Consumes: `_choose_tile_pixels` (Task 1), `_aoi_spans_multiple_tiles` (existing).
- Produces: behavioural change only — `load_wofs_monthly_extent(..., tile_pixels=2048, auto_tiling=True)` on a single-tile-bbox AOI now keeps the tiled path with a smaller `tile_pixels`, instead of setting `tile_pixels = None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_io_extent_cache.py`. This asserts the tiled iterator IS called (tiling stays on) and receives a smaller `tile_pixels` than requested.

```python
def test_auto_tiling_shrinks_tile_size_instead_of_disabling(monkeypatch, tmp_path):
    """A thin AOI whose bbox fits one 2048px tile keeps the tiled path with a
    smaller tile size (so pruning can skip empty tiles), not the untiled path
    -- AND precompute_wet_aoi is suppressed, since a shrunk-and-pruned tiled
    grid no longer needs a whole-cube precompute pass to know which tiles to
    skip (bbox-intersect pruning is sufficient on its own). Failing to suppress
    it would reintroduce the exact whole-cube double-read this investigation
    started from (see docs/superpowers/plans/2026-07-23-perf-investigation-handoff.md
    section 6.1)."""
    pytest.importorskip("dask")
    import hydroseason.io as hio

    # 55 km AOI bbox: one 2048px tile at 30 m spans ~61 km, so it fits in one
    # tile at the request and must be shrunk rather than disabled.
    aoi = _write_box_aoi(tmp_path, "thin.geojson", crs="EPSG:3577", span_m=55_000)

    seen_tile_pixels = []

    def fake_tiles(*args, tile_pixels=None, wet_aoi=None, skip_tile_ids=(), **kwargs):
        seen_tile_pixels.append(tile_pixels)
        yield "r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01")

    # load_wofs_from_stac is the ONE function both the old untiled-fallback
    # path AND the precompute_wet_aoi whole-cube pass would call -- so this
    # single mock's call count proves BOTH "did not fall back to untiled" AND
    # "precompute_wet_aoi's whole-cube read did not fire" at once.
    whole_cube_load = Mock(side_effect=lambda *a, **k: _fake_monthly_cube("2020-01-01", "2020-12-31"))
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", fake_tiles)
    monkeypatch.setattr(hio, "load_wofs_from_stac", whole_cube_load)
    monkeypatch.setattr(hio, "compute_wet_aoi", lambda mask, **k: _fake_wet_aoi())

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=2048, precompute_wet_aoi=True,
    )

    assert seen_tile_pixels, "tiled path was disabled instead of shrunk"
    assert seen_tile_pixels[0] is not None
    assert seen_tile_pixels[0] < 2048  # shrunk to enable pruning
    # Neither the old untiled fallback NOR the precompute_wet_aoi whole-cube
    # pass may fire: the shrunk tiled grid prunes via bbox-intersect alone.
    assert not whole_cube_load.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_io_extent_cache.py::test_auto_tiling_shrinks_tile_size_instead_of_disabling -v`
Expected: FAIL — `seen_tile_pixels` is empty and `untiled.called` is True (current code disables tiling).

- [ ] **Step 3: Replace the auto-tiling branch**

In `hydroseason/_io_extent_cache.py`, replace the block at lines 461-474 (the `if auto_tiling and tile_pixels is not None and wet_aoi is None:` block) with:

```python
    if auto_tiling and tile_pixels is not None and wet_aoi is None:
        chosen = _choose_tile_pixels(
            aoi, crs=crs, resolution=resolution,
            requested_tile_pixels=tile_pixels,
        )
        if chosen is not None and chosen != tile_pixels:
            if _profile_enabled():
                import sys
                print(
                    f"  [profile] auto-tiling: shrinking tile_pixels "
                    f"{tile_pixels} -> {chosen} so the AOI bbox splits into "
                    f"prunable tiles (thin-AOI-in-large-bbox optimisation)",
                    file=sys.stderr, flush=True,
                )
            tile_pixels = chosen
```

**CRITICAL — do not skip this:** the OLD code being replaced set `precompute_wet_aoi = False` alongside `tile_pixels = None`, because a whole-cube precompute pass makes no sense once there's nothing to prune. The new code no longer disables tiling, so `precompute_wet_aoi` (if the caller requested it) is now left `True` and WILL still run — meaning a thin AOI with `precompute_wet_aoi=True` would pay for BOTH a whole-cube precompute read AND the (now-shrunk, faster) tiled pass, reintroducing the exact double-read cost this whole investigation started from (see `docs/superpowers/plans/2026-07-23-perf-investigation-handoff.md` §6.1 for the full history of this gap being caught).

This is intentional and correct, NOT a bug to fix by re-adding `precompute_wet_aoi = False`: the whole point of shrinking the tile size is that the tiled+pruned path can now skip empty tiles on its own, without needing a precomputed wet-AOI mask to know which tiles to skip (`_tile_intersects_aoi`'s bbox-intersect gate is enough — see `hydroseason/_io_geo.py`'s `iter_wofs_tiles_from_stac`, and recall Probe 7 in the handoff found bbox-intersect pruning and true polygon-footprint pruning performed identically). So the fix is to also suppress `precompute_wet_aoi` here, since it is no longer needed for this AOI shape and its cost is pure waste:

```python
    if auto_tiling and tile_pixels is not None and wet_aoi is None:
        chosen = _choose_tile_pixels(
            aoi, crs=crs, resolution=resolution,
            requested_tile_pixels=tile_pixels,
        )
        if chosen is not None and chosen != tile_pixels:
            if _profile_enabled():
                import sys
                print(
                    f"  [profile] auto-tiling: shrinking tile_pixels "
                    f"{tile_pixels} -> {chosen} so the AOI bbox splits into "
                    f"prunable tiles (thin-AOI-in-large-bbox optimisation); "
                    f"precompute_wet_aoi is no longer needed to prune this "
                    f"grid and is skipped to avoid its whole-cube read cost",
                    file=sys.stderr, flush=True,
                )
            tile_pixels = chosen
            precompute_wet_aoi = False
```

Use THIS version (with `precompute_wet_aoi = False` inside the `if chosen != tile_pixels` branch) as the actual code change, not the first snippet above. The first snippet is shown only to make the diff against the old code clear; it is NOT what should ship.

Note: `_choose_tile_pixels` only ever *shrinks* (never enlarges) tile size, and returns the request unchanged for already-multi-tile AOIs — for those, `chosen == tile_pixels`, the `if` body never runs, and `precompute_wet_aoi` is left exactly as the caller set it (correct: a genuinely multi-tile AOI still benefits from precompute-driven pruning across its many real tiles).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_io_extent_cache.py -v`
Expected: all pass, including the new test. NOTE: the older test `test_auto_tiling_degrades_single_tile_aoi_to_untiled_path` (which asserted the untiled fallback) will now FAIL because that behaviour is intentionally removed — proceed to Step 5.

- [ ] **Step 5: Update the now-obsolete degrade test**

The old `test_auto_tiling_degrades_single_tile_aoi_to_untiled_path` encodes the behaviour we are deliberately replacing. Rewrite its body to assert the NEW behaviour (tiling stays on, shrunk) — find it in `tests/test_io_extent_cache.py` and replace its assertions:

```python
def test_auto_tiling_degrades_single_tile_aoi_to_untiled_path(monkeypatch, tmp_path):
    """Single-tile-bbox AOIs now keep the tiled path at a shrunk tile size
    (superseding the old 'degrade to untiled' behaviour -- kept under the same
    name to preserve the regression's history)."""
    pytest.importorskip("dask")
    import hydroseason.io as hio

    aoi = _write_box_aoi(tmp_path, "small.geojson", crs="EPSG:3577", span_m=55_000)

    tiles = Mock(side_effect=lambda *a, **k: iter(
        [("r0000_c0000", _fake_monthly_cube("2020-01-01", "2020-12-01"))]
    ))
    untiled = Mock(side_effect=lambda *a, **k: _fake_monthly_cube("2020-01-01", "2020-12-01"))
    monkeypatch.setattr(hio, "iter_wofs_tiles_from_stac", tiles)
    monkeypatch.setattr(hio, "load_wofs_from_stac", untiled)
    monkeypatch.setattr(hio, "compute_wet_aoi", lambda mask, **k: _fake_wet_aoi())

    hio.load_wofs_monthly_extent(
        "https://example.invalid/stac", "wofs", aoi,
        "2020-01-01", "2020-12-31",
        crs=3577, resolution=30, tile_pixels=2048, precompute_wet_aoi=True,
    )

    assert tiles.called  # tiled path stays on
    assert not untiled.called  # no untiled whole-bbox fallback
```

Run: `python -m pytest tests/test_io_extent_cache.py -v`
Expected: all pass.

- [ ] **Step 6: Run the full affected suite**

Run: `python -m pytest tests/test_io_extent_cache.py tests/test_io.py tests/test_hydro_year.py tests/test_run_multi_catchment_report.py -q`
Expected: all pass.

- [ ] **Step 7: Lint**

Run: `python -m ruff check hydroseason/_io_extent_cache.py tests/test_io_extent_cache.py`
Expected: `All checks passed!` (fix import order with `--fix` if I001 appears).

- [ ] **Step 8: Commit**

```bash
git add hydroseason/_io_extent_cache.py tests/test_io_extent_cache.py
git commit -m "perf: shrink tile size for thin AOIs instead of disabling tiling"
```

---

### Task 3: Update docstring and remove the stale "degrade to untiled" rationale

**Files:**
- Modify: `hydroseason/_io_extent_cache.py` (the `load_wofs_monthly_extent` docstring `auto_tiling` paragraph, ~line 301-309)

**Interfaces:**
- Consumes: nothing new.
- Produces: documentation only.

- [ ] **Step 1: Replace the `auto_tiling` docstring paragraph**

Find the paragraph in the `load_wofs_monthly_extent` docstring beginning ``auto_tiling=True`` (the default) degrades a requested tiled load...`` and replace it with:

```
    ``auto_tiling=True`` (the default) adapts a requested ``tile_pixels`` to
    the AOI's bounding box: when the bbox would otherwise fit in a single tile
    at the requested size, the tile size is shrunk (via
    :func:`_choose_tile_pixels`) so the bbox splits into several tiles and the
    tile-skip gate can prune the ones the AOI never touches. This is the
    thin-AOI-in-large-bbox win: a river buffer whose polygon is a small
    fraction of its bounding box no longer forces a whole-rectangle decode.
    Shrinking is capped (tile count and a size floor) because per-tile overhead
    overtakes the decode saved once tiles get small and numerous -- see the
    measurements in :func:`_choose_tile_pixels`. It is suppressed when a
    ``wet_aoi`` is caller-supplied (that path has its own pruning semantics),
    and turned off entirely with ``auto_tiling=False`` to use ``tile_pixels``
    exactly as given.
```

- [ ] **Step 2: Lint and full test**

Run: `python -m ruff check hydroseason/_io_extent_cache.py && python -m pytest tests/test_io_extent_cache.py -q`
Expected: `All checks passed!` and all tests pass.

- [ ] **Step 3: Commit**

```bash
git add hydroseason/_io_extent_cache.py
git commit -m "docs: document adaptive tile-sizing in load_wofs_monthly_extent"
```

---

### Task 4: End-to-end verification on the real AOI (manual, gated)

**Files:** none (verification only).

This task confirms the measured win holds end-to-end. It requires the `hydroseason` conda env and network access to DEA's STAC. If the runner has no network, mark this task skipped and note it — the unit tests above already prove the mechanism.

- [ ] **Step 1: Run a fresh single-year extraction with profiling**

```bash
conda activate hydroseason
python scripts/extract_water_extent_csv.py --aoi data/Gilbert_river_buffer.geojson \
  --resolution 30 --profile --start-date 2015-01-01 --end-date 2015-12-31 \
  --name gilbert_tilecheck --force
```

Expected: a `[profile] auto-tiling: shrinking tile_pixels 2048 -> 1024 ...` line, and a per-year time meaningfully below the ~40s untiled baseline (target ~24s, i.e. roughly a third faster).

- [ ] **Step 2: Confirm output is unchanged vs the untiled path**

Compare the new CSV against an untiled run of the same window:

```bash
python scripts/extract_water_extent_csv.py --aoi data/Gilbert_river_buffer.geojson \
  --resolution 30 --start-date 2015-01-01 --end-date 2015-12-31 \
  --name gilbert_untiled --no-tiling --force
python -c "import pandas as pd; a=pd.read_csv('output/water_extent_csv/gilbert_tilecheck_water_extent.csv',index_col=0); b=pd.read_csv('output/water_extent_csv/gilbert_untiled_water_extent.csv',index_col=0); pd.testing.assert_frame_equal(a,b); print('IDENTICAL')"
```

Expected: `IDENTICAL` (adaptive tiling must not change extent values).

- [ ] **Step 3: Record the result**

Note the measured per-year time in the commit message of any follow-up, or report it back. No code commit for this task.

---

## Self-Review

**Spec coverage:** The scope is "make auto-tiling pick a pruning-effective tile size." Task 1 adds the heuristic, Task 2 wires it into the decision point (and updates the one test encoding the old behaviour), Task 3 documents it, Task 4 verifies the measured win end-to-end and the no-output-change invariant. Covered.

**Placeholder scan:** No TBD/TODO; all code blocks are complete; the ceil-division and shrink loop are spelled out; the obsolete test is rewritten in full rather than referenced.

**Type consistency:** `_choose_tile_pixels(aoi, *, crs, resolution, requested_tile_pixels, target_tiles_max=12, min_tile_pixels=512) -> int | None` is defined in Task 1 and called with exactly those keyword names in Task 2. `_crs_value_local` and `load_aoi` names match the existing module. The `iter_wofs_tiles_from_stac` `tile_pixels=` kwarg matches its real signature in `hydroseason/_io_geo.py`.

---

## Related follow-on plans

Two further levers were measured/identified this session but are separate subsystems, each with its own plan:

- `2026-07-23-parallel-year-extraction.md` — run the independent per-year loads concurrently across processes (per-AOI thread decode is already saturated, so cross-year process parallelism is the next axis for multi-year runs).
- `2026-07-23-coarse-resolution-option.md` — opt-in coarser load resolution (60/90 m) for a proportional data-volume cut where the science tolerates it (changes output values, so never a default).
