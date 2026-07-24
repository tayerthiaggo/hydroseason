# WOfS Extraction Performance Investigation — Handoff

**Purpose of this document:** a cold agent (or human) should be able to read this, understand everything measured and ruled out this session, judge whether the conclusions are sound, and find gaps or errors we missed — without re-deriving the whole investigation from scratch.

**Status:** one proven fix committed (auto-tiling degrade → untiled), one proven fix *planned but not yet implemented* (adaptive tile sizing), and a live regression fixed mid-session (read_workers). Read the "Open questions and possible gaps" section at the end before trusting any conclusion here as final.

---

## 1. The complaint that started this

`scripts/extract_water_extent_csv.py` extracting a single small AOI (`data/Gilbert_river_buffer.geojson`, 196 km², a river buffer) over a 20-year window was taking **~43 minutes** (2569s). User: "even 10 minutes to do this area I find not efficient at all."

## 2. Environment facts (verify these still hold)

- Windows, conda. Two environments exist: `odc_env` (original, GDAL 3.10.3 via rasterio 1.4.4) and `hydroseason` (new, created this session via `environment.yml` at repo root, GDAL 3.12.3).
- STAC source: `https://explorer.dea.ga.gov.au/stac`, collection `ga_ls_wo_3` (DEA Water Observations, WOfS). Public S3 bucket `dea-public-data`, unsigned access required (`AWS_NO_SIGN_REQUEST=YES`).
- WOfS band `water` is a single uint8 bit-flag layer: `nodata=1` (bit 0), `wet=128` (bit 7, "clear and wet"), `dry=0`. Native resolution 30 m, native CRS behaves as EPSG:3577/Albers-equal-area (confirmed via `proj:transform: [30.0, 0.0, ..., -30.0, ...]`) but **`proj:epsg` is `None` in the STAC metadata** — this fact mattered (see §4.3).
- Test AOI: `data/Gilbert_river_buffer.geojson`, bbox ~55×55 km (2945 km²), actual polygon area 196 km² (**7% fill, 15× bbox/polygon ratio**). A second test AOI exists: `data/fitzroy_kimberley_aoi.geojson` (448 km², more compact, less bbox waste) — **this second AOI was profiled early but NOT re-profiled after the later fixes; that's a gap, see §6.**

## 3. Chronological log of what was tried, in order

Each entry: hypothesis → measurement → verdict → commit (if any).

### 3.1 Baseline
Tiled + `precompute_wet_aoi=True` (the script's original default), `tile_pixels=2048`, 20-year window, Gilbert AOI: **2569.4s** total, ~858.8s of which was the precompute whole-cube pass alone.

### 3.2 Auto-tiling degrade (commit `97d965a`)
**Hypothesis:** at `tile_pixels=2048` and 30 m resolution, one tile spans ~61×61 km — bigger than the whole 55 km AOI bbox. So `precompute_wet_aoi` pays for a full whole-cube read to prune a grid that only ever has 1 cell.
**Fix:** `_aoi_spans_multiple_tiles()` in `hydroseason/_io_extent_cache.py` checks the AOI bbox against `tile_pixels * resolution` before querying STAC; if the bbox fits in one tile, `load_wofs_monthly_extent` degrades to the plain untiled path (`tile_pixels=None`, `precompute_wet_aoi=False`).
**Measured:** `--no-tiling` manual run = **570.5s** (vs 2569s). **4.5× win.**
**Status:** implemented and tested (`test_auto_tiling_degrades_single_tile_aoi_to_untiled_path` and siblings in `tests/test_io_extent_cache.py`). **NOTE: this test/behavior is scheduled for REPLACEMENT by the adaptive-tiling plan (§5) — see §6.1, this is a live tension.**

### 3.3 GDAL/rasterio env tuning (commit `97d965a`, same commit)
Added `_configure_cog_read_env()` in `hydroseason/_io_geo.py`: `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`, `GDAL_HTTP_MULTIPLEX=YES` + `GDAL_HTTP_VERSION=2`, `VSI_CACHE`/`VSI_CACHE_SIZE`, `GDAL_HTTP_MAX_RETRY`/`_RETRY_DELAY`, `CPL_VSIL_CURL_ALLOWED_EXTENSIONS`.
**Measured:** auto-tiling + env-tuning combined = **496.3s** (vs 570.5s manual `--no-tiling`, i.e. ~13% further gain from env tuning alone).

### 3.4 `read_workers` concurrency knob (commit `1f8d2c7`) — LATER PARTIALLY REVERTED
**Hypothesis:** 133 scenes/year, each a separate S3 COG read; dask's threaded scheduler defaults to ~cpu_count workers, too few for a latency-bound workload.
**Fix:** added `read_workers: int | None = 32` (default 32!) to `load_wofs_monthly_extent`, threaded into `monthly_water_extent` (`hydroseason/hydro_year.py`) via `dask.config.set(scheduler="threads", num_workers=read_workers)`.
**User tested `--read-workers 8`:** got WORSE (680.9s vs 496.3s baseline). This was the first hint the model was wrong, but at the time it was attributed to "8 is below the implicit default," not examined further.
**Status: this default (32) was later proven actively harmful and reverted to `None` in commit `1da3031` — see §3.8.** The mechanism (the parameter, the `_read_concurrency` context manager, threading it through 3 call sites) is still in the code and still functional; only the *default value* changed.

### 3.5 `groupby="solar_day"` default (commit `8188e13`)
**Hypothesis:** WOfS scenes are per-Landsat-pass; 133 scenes/year include same-day tile-edge duplicates. `odc.stac.stac_load`'s default `groupby="time"` keeps every timestamp as its own plane; `groupby="solar_day"` mosaics same-day scenes (nodata-aware) before compositing — fewer slices, and arguably more correct (a pixel valid in one tile-edge scene and nodata in its same-day neighbor is one real observation, not two competing votes).
**Verified via Context7 (`/opendatacube/odc-stac` docs):** `solar_day` grouping is nodata-aware — "'nodata' is used when combining multiple items."
**Fix:** default changed in `_load_wofs_items`/`load_wofs_from_stac`/`iter_wofs_tiles_from_stac` (all in `hydroseason/_io_geo.py`). **Cache schema bumped 2→3** (`_CACHE_SCHEMA_VERSION` in `_io_extent_cache.py`) since this changes extent values at same-day-overlap boundaries — old cached CSVs are correctly invalidated, not silently reused.
**Measured:** 496.3s → **429.8s** (~13% further gain). Slice count dropped from 133 to 89 for the 2015 test year (confirmed later in §3.6's probe).
**Test added:** `test_stac_loader_defaults_to_solar_day_grouping` in `tests/test_io.py`.

### 3.6 Deep profiling begins — the GDAL connection-cap chase (mostly a dead end)
User pushed back: "there's still something hurting processing bad." At this point the investigation shifted from applying known STAC/dask levers to first-principles profiling with throwaway scripts (all in the scratchpad, none committed — see §4 for the full list and how to rerun them).

**Probe 1 — split `stac_load` phases** (`probe_stac_load_phases.py`): `parse_items` 0.02s, `output_geobox` 0.00s, graph construction 0.9s, **`.compute()` 28-29s**. All non-compute phases are near-instant. Conclusion: 100% of the cost is in materialization, not metadata/graph-build.

**Hypothesis: GDAL's connection pool caps concurrent S3 connections** below dask's configured worker count, and the fix (`GDAL_HTTP_MAX_TOTAL_CONNECTIONS`) only exists on GDAL ≥3.11 (confirmed via Context7 `/websites/gdal_en_stable` docs). User's env (`odc_env`) had GDAL 3.10.3.
**Action:** created `environment.yml` (conda-forge pinned, GDAL≥3.11) and a new `hydroseason` conda env. User confirmed GDAL 3.12.3 after creating it.
**Result: WORSE, not better — 518.3s total (vs 429.8s on GDAL 3.10.3).** This **falsified the connection-cap hypothesis** cleanly. (The env itself was kept as a legitimate reproducible dev environment regardless of the falsified hypothesis — see `environment.yml` at repo root.)

**Probe 2 — raw HTTP ground truth** (`probe_raw_http.py`): bypassed GDAL/rasterio/dask entirely, did concurrent `requests` HEAD + 16KB range-GET against the same 133 scene URLs (converted `s3://` hrefs to the public HTTPS mirror `https://dea-public-data.s3.ap-southeast-2.amazonaws.com/...`). **Result: 6.16s for all 133 scenes, concurrent, 32 threads.** This proved network/S3 latency is NOT the bottleneck — the gap between 6s (raw HTTP) and ~28s (real pipeline) is entirely inside the GDAL/rasterio/odc.stac/dask stack.

**Probe 3 — warp/resampling isolation** (`probe_stac_load_phases.py`, extended): tested (a) explicit `crs=3577` no `resampling` kwarg: **17.5-17.7s** (down from 28.2-28.9s with `resampling="mode"` — a genuine ~38% cut from dropping the resampling kwarg alone), (b) `resampling="nearest"` (cheapest kernel): **17.4s**, (c) `geobox=` passed directly instead of `geopolygon`+`crs`+`resolution`: **17.3s**. All three land at the same ~17.3-17.7s floor — resampling KERNEL choice and geobox-passing STYLE don't matter once you're past whatever the base "solar_day, explicit CRS" cost is. **Also discovered `proj:epsg: None` in item metadata** — WOfS items don't declare their EPSG code even though `proj:transform` shows they're already in a 30m Albers-like grid, forcing GDAL through its full warp path under an unconfirmed source CRS (the `NotGeoreferencedWarning` from `rasterio/warp.py:387` is this warp firing).

**Probe 4 — `pool=` and dask worker sweep** (`probe_stac_load_phases.py` further extended, then `probe_worker_sweep.py`): `stac_load(pool=ThreadPoolExecutor(32))` (odc.stac's OWN internal pool, separate from dask): **17.47s, no change.** Then swept dask `num_workers` explicitly: **unset/default = 18.20s (BEST), 4=28.86s, 8=20.06s, 16=21.67s, 32=24.47s, 64=29.88s.** Monotonically worse above ~8 workers. **This is what proved the `read_workers=32` default from §3.4 was actively harmful.**

**Probe 5 — data volume + scheduler type** (`probe_worker_sweep.py`, `probe_process_scheduler.py`): confirmed **291.7 MB decompressed for one year** (89 slices × 1983×1653 pixels × int8, at the ~16 MB/s effective throughput this implies ~18s is plausible for genuine CPU decode work, not obviously "too slow for the bytes"). Then tested `scheduler="synchronous"` (single-threaded, zero scheduling overhead): **125.30s** — proving the threaded scheduler DOES deliver real ~5.5× parallelism (rules out GIL-bound decode, since GIL-bound work wouldn't show that gap). Then `scheduler="processes"`: worse at every worker count tried (4→46.27s, 8→28.41s) — attributed to per-task IPC/pickling overhead re-shipping STAC items/geobox to each process.

### 3.7 Clip-once optimization (commit `7dd49fb`)
Independent of the read-cost chase, user pointed out `_clip_to_aoi` was called once per MONTH (12×/year) inside `_load_wofs_items`, and internally it rasterizes the AOI geometry TWICE (`.rio.clip` + `mark_in_aoi_nodata_as_invalid`'s `_inside_aoi_mask_like`) — 24 redundant rasterizations/year of an AOI polygon that's time-invariant.
**Fix:** restructured `_load_wofs_items` (`hydroseason/_io_geo.py`) to concat all months into one unclipped stacked cube first, then clip the whole `(time,y,x)` cube ONCE.
**Correctness proof:** added `test_clip_once_on_cube_matches_per_slice_clip` in `tests/test_io.py` — builds a 3-slice synthetic cube with random water/dry/invalid values, proves `_clip_to_aoi(cube)` is byte-identical to concatenated per-slice `_clip_to_aoi(cube.isel(time=t))`. **This test passed — the optimization is proven safe**, independent of whether it moved the needle on wall-clock (it wasn't isolated in a probe; folded into the same commit as the GDAL connection-limit env var addition).
**Also added in this commit:** `GDAL_HTTP_MAX_TOTAL_CONNECTIONS=64` to `_configure_cog_read_env` (the GDAL≥3.11 knob from §3.6 — later proven not to matter, but left in the env config as a harmless no-op/potential-future-help; not removed).

### 3.8 `read_workers` default reverted (commit `1da3031`)
Direct consequence of Probe 4/5 in §3.6. Changed `load_wofs_monthly_extent`'s `read_workers` default from `32` to `None` in `hydroseason/_io_extent_cache.py`. `monthly_water_extent` in `hydro_year.py` already defaulted to `None` (it was `load_wofs_monthly_extent`'s default of 32 that was propagating the bad value). Script's `--read-workers` CLI default changed 32→0 (same no-op meaning). Extensive docstring rewrite in both files documenting the counter-intuitive finding so nobody re-introduces it. Test `test_read_workers_threads_into_reduction_and_leaves_result_unchanged` updated to assert `None in seen_workers` instead of `32 in seen_workers`.

### 3.9 The bbox-vs-polygon discovery (this is the current frontier, NOT yet implemented in code)
After all read/decode-path optimization was exhausted, re-examined the actual pixel counts: probe showed shape `1983×1653` for the Gilbert AOI load. At 30m that's ~3.28M pixels/slice for a 196 km² AOI — should be ~218K pixels (a 15× discrepancy). Cross-checked: **AOI polygon area 196 km², bbox area 2945 km² → 15.0× waste, 7% fill** (computed directly from the GeoJSON in `probe_tile_pruning.py`).

**Root cause:** `odc.stac.stac_load(geopolygon=...)` computes an axis-aligned GeoBox from the polygon (confirmed via Context7 `/opendatacube/odc-stac` docs and the "Generating Rotated Images to Save Space" wiki page) — it ALWAYS loads the bounding rectangle; COG reads are inherently rectangular. The clip afterward discards everything outside the actual polygon. For a thin river in a big box, ~93% of decoded pixels are wasted.

**The irony:** §3.2's auto-tiling fix DISABLES tiling exactly when this waste is worst (AOI fits in one tile), because there was "nothing to prune" at `tile_pixels=2048`. Tiling with a SMALLER tile size would let the tile-skip pruning gate (`iter_wofs_tiles_from_stac`'s bbox-intersect test, `_tile_intersects_aoi` in `_io_geo.py`) skip the empty tiles around the river.

**Probe 6 — tile-size sweep, geometry only** (`probe_tile_pruning.py`, no network/reads, pure `_tile_slices` + `_tile_intersects_aoi` math): at `tile_pixels=2048`: 1 tile, 0% pruned. `1024`: 4 tiles, 25% pruned. `512`: 16 tiles, 38% pruned. `256`: 56 tiles, 68% pruned. Smaller tiles prune more — as expected geometrically.

**Probe 7 — tile-size sweep, REAL wall-clock** (`probe_tile_size_walltime.py`, actual `iter_wofs_tiles_from_stac` + `monthly_water_extent` calls, real network): baseline (1 tile, whole bbox) = **40.4s**. `tile_pixels=1024` (3 tiles kept) = **24.1s** — the winner, ~40% faster. `512` (10 tiles) = **27.3s** — good but not best. `256` (18 tiles) = **43.2s** — WORSE than baseline; per-tile overhead (graph rebuild + COG re-open per tile) overwhelms the decode saved once tiles get small/numerous. **Also tested true polygon-footprint pruning (`wet_aoi=` set to the AOI polygon itself, not just bbox-intersect): no measurable difference vs bbox-intersect at 512/256px** (27.3 vs 27.7s, 43.2 vs 42.8s) — the pruning GATE type doesn't matter at these sizes; the cost is dominated by per-*loaded*-tile overhead, not which tiles get skipped.

**Conclusion: there is a real, narrow sweet spot (~1024px / ~3 tiles for this AOI) where smaller tiles prune enough to win, before per-tile overhead flips the sign.** This is NOT a monotonic "smaller = faster" relationship, which the naive tiling-count math from Probe 6 alone would have suggested.

### 3.10 Plans written, not yet executed
Three plans written to `docs/superpowers/plans/`:
- **`2026-07-23-adaptive-tile-sizing.md`** — FULL step-by-step TDD plan. Adds `_choose_tile_pixels()` heuristic (shrinks tile size by halving until the AOI bbox spans >1 tile OR a tile-count cap (~12) is hit OR a size floor (512px) is hit) and rewires the §3.2 auto-tiling branch to use it instead of disabling tiling. **This plan's Task 2 explicitly rewrites the §3.2 test** (`test_auto_tiling_degrades_single_tile_aoi_to_untiled_path`) since its asserted behavior (degrade to untiled) is being deliberately replaced by a different behavior (shrink and stay tiled). **NOT YET IMPLEMENTED — this is the next action.**
- **`2026-07-23-parallel-year-extraction.md`** — outline only. Cross-year process-pool parallelism, since per-year decode is already thread-saturated (per §3.6 Probe 5's synchronous-vs-threaded finding).
- **`2026-07-23-coarse-resolution-option.md`** — outline only. Opt-in 60/90m resolution for proportional data-volume cuts. Flags an UNRESOLVED correctness question: does `resampling="mode"` operate correctly over raw uint8 WOfS bit-flags (before `_classify` runs), or does it need to happen after classification? This was never actually checked in this session — flagged as a risk in the plan, not resolved.

## 4. Reproducing the probes

All probe scripts live in the session's scratchpad (NOT in the repo, NOT committed):
`C:\Users\00101125\AppData\Local\Temp\claude\d--RLH-5-6-repos-hydroseason\7fbb5f53-b750-4e14-bffb-ef3756a305af\scratchpad\`

- `probe_year.py` — first fine-grained phase probe (superseded by later ones, kept for reference).
- `probe_stac_load_phases.py` — the main phase-splitting probe (§3.6 Probes 1, 3, 4). Has grown several sections via iterative edits; read top-to-bottom.
- `probe_raw_http.py` — raw concurrent HTTP ground truth (§3.6 Probe 2). Requires `requests` (`pip install requests` — not a repo dependency, diagnostic only).
- `probe_worker_sweep.py` — dask worker count sweep + data volume (§3.6 Probe 5, part 1).
- `probe_process_scheduler.py` — synchronous vs threaded vs processes scheduler comparison (§3.6 Probe 5, part 2). Has an `if __name__ == "__main__":` guard required for the multiprocessing scheduler on Windows.
- `probe_tile_pruning.py` — pure-geometry tile-pruning-percentage sweep, no network (§3.9 Probe 6).
- `probe_tile_size_walltime.py` — real wall-clock tile-size sweep (§3.9 Probe 7). **This is the one that produced the numbers behind the adaptive-tiling plan — if re-verifying only one probe, re-verify this one.**

All probes hardcode `REPO = Path(r"D:\RLH\5.6\repos\hydroseason")` and the Gilbert AOI. They must be run inside the `hydroseason` conda env (`conda activate hydroseason`) since that's where GDAL≥3.11 + all STAC deps live. They talk to the real DEA STAC endpoint over the network — no mocking.

## 5. Current code state (as of commit `1da3031`)

Files touched this session (see `git log --oneline` for the 5 perf commits: `97d965a`, `1f8d2c7`, `8188e13`, `7dd49fb`, `1da3031`):
- `hydroseason/_io_extent_cache.py` — `_aoi_spans_multiple_tiles`, `_read_concurrency`, `_phase`/`_profile_enabled`, `read_workers` param (now defaults `None`), `auto_tiling` param, cache schema bumped to 3.
- `hydroseason/_io_geo.py` — `_configure_cog_read_env`, `groupby` param (defaults `"solar_day"`) on `load_wofs_from_stac`/`iter_wofs_tiles_from_stac`/`_load_wofs_items`, clip-once restructuring in `_load_wofs_items`.
- `hydroseason/hydro_year.py` — `read_workers` param on `monthly_water_extent` (always defaulted `None`, unaffected by the §3.8 revert since the bug was in the CALLER's default).
- `scripts/extract_water_extent_csv.py` — `--aoi`/`--name` (arbitrary AOI support, not just the 6 fixture catchments), `--profile`, `--read-workers` (default 0), tqdm progress bar.
- `pyproject.toml` — added `tqdm>=4.65` to the `stac` extra.
- `environment.yml` — NEW file, conda-forge pinned env (GDAL≥3.11, rasterio≥1.4, etc). Created to test the connection-cap hypothesis (§3.6), which was then falsified, but kept as a legitimate reproducible env regardless.
- Tests added across `tests/test_io.py` and `tests/test_io_extent_cache.py` — all passing as of last full-suite run (113 tests across the 4 affected suites).

**Files explicitly NOT touched by this agent, left as pre-existing uncommitted changes:** `hydroseason/examples.py` and `notebooks/hydroseason_water_extent_example.ipynb`. These showed as modified in `git status` from the start of the session and were flagged to the user but never committed or altered — if you see them dirty, that's not this investigation's doing.

## 6. Open questions and possible gaps — WHERE TO LOOK FOR WHAT WE MISSED

This is the section most worth scrutinizing. Ranked by how likely each is to be a real gap:

### 6.1 RESOLVED (during this handoff's own review) — `precompute_wet_aoi` interaction gap
§3.2's fix (degrade to untiled, also setting `precompute_wet_aoi = False`) and §3.9's plan (shrink tile size, stay tiled) are mutually exclusive behaviors for the same trigger condition (AOI fits in one tile). The plan's ORIGINAL draft only touched `tile_pixels` in the replacement code, silently leaving `precompute_wet_aoi` untouched — meaning a thin AOI with `precompute_wet_aoi=True` would have paid for BOTH the whole-cube precompute pass AND the (shrunk, faster) tiled pass, reintroducing the exact double-read cost this whole investigation started from.

**This has been caught and fixed in `2026-07-23-adaptive-tile-sizing.md` itself** (Task 2, Step 3): the shipped replacement code now also sets `precompute_wet_aoi = False` inside the `if chosen != tile_pixels:` branch, with an explicit comment explaining why (the shrunk tiled grid prunes via bbox-intersect alone — Probe 7 in §3.9 found bbox-intersect and true polygon-footprint pruning perform identically, so precompute-driven pruning buys nothing extra for this AOI shape). Task 2's test (`test_auto_tiling_shrinks_tile_size_instead_of_disabling`) now asserts the whole-cube precompute load is never called, using a single shared mock for both `load_wofs_from_stac` call sites (untiled-fallback and precompute) so one assertion proves both.

**What a fresh agent should still verify:** that this fix is actually correct once implemented (run the test, don't just trust the plan text), and that the "already multi-tile → `chosen == tile_pixels` → `precompute_wet_aoi` left alone" branch genuinely preserves current behavior for the six real fixture catchments (§6.3) — this specific sub-case was reasoned about but not tested end-to-end against a real multi-tile AOI in this session.

### 6.2 The second test AOI (`fitzroy_kimberley_aoi.geojson`) was abandoned early
It was proposed in the same breath as Gilbert (both smaller AOIs for faster iteration) and profiled ONCE (426.7s tiled+precompute vs some baseline, from a much earlier point in the session, before solar_day/clip-once/read_workers-revert). It was never re-run with the final fixes. Its bbox-to-polygon ratio was never computed (unlike Gilbert's 15×) — worth checking whether it has the same waste pattern or a different one (it's described as "more compact" in earlier turns, meaning the bbox-oversizing fix may matter less or more there).

### 6.3 Full multi-catchment / `run_multi_catchment_report.py` never re-profiled
All profiling this session used the small Gilbert/Fitzroy test AOIs specifically because they're fast to iterate on. The six REAL fixture catchments (`gilbert_river_qld`, `fitzroy_river_wa`, `moonie_river_qld_nsw`, `lachlan_river_nsw`, `paroo_river_qld_nsw`, `daly_river_nt` — thousands of km² each, genuinely multi-tile) were never profiled with any of this session's fixes applied. The `read_workers` revert, `groupby=solar_day`, and clip-once changes all apply to them too (they're in the shared load path), but their real-world impact on the ACTUAL production workflow (`run_multi_catchment_report.py`) is unverified. The parallel-year-extraction plan (§3.10) targets exactly this multi-year, larger-AOI case but has not been prototyped at all, even in a throwaway probe.

### 6.4 CONFIRMED GAP (verified during this handoff's own review) — `resampling="mode"` tax is still fully paid in shipped code
Checked directly: `hydroseason/_io_geo.py` line ~299 (`_load_wofs_items`) still unconditionally does `**({"resampling": "mode"} if resolution is not None else {})`. Every real call from `extract_water_extent_csv.py` passes `--resolution 30`, so `resampling="mode"` fires on every single load. **§3.6 Probe 3's 28s→17.5s (~38%) finding from dropping this kwarg was NEVER turned into a code change** — it was found, then the session moved on to chase the (ultimately also-abandoned) `pool=`/worker-count/scheduler-type threads without circling back.

**This is a real, unclaimed win sitting in the code right now**, separate from and additive to the adaptive-tiling plan (§3.9/§3.10) — but it is NOT free to just delete: `resampling="mode"` is the majority-vote kernel, and it is the semantically correct choice for a *categorical* mask (water/dry/invalid) when GDAL warps/resamples across a resolution or grid change. The open question the session left unresolved: does GDAL's warp step, when `resolution` matches (or is a clean multiple of) the native 30m grid and `proj:epsg` happens to already be known/inferred correctly, actually need to resample AT ALL — i.e. is the ~38% cost paying for a real categorical-resampling operation, or for GDAL running its full warp machinery to produce what is actually a no-op nearest-copy? Probe 3 found `resampling="nearest"` (cheapest kernel) gave THE SAME ~17.4s as no-resampling-kwarg-at-all — suggesting the ~38% cost is the WARP MACHINERY firing (independent of kernel choice), not the mode-vs-nearest computation itself. If that reading is right, the fix is not "drop resampling," it's "avoid triggering the warp path when the load is already on a matching grid" (e.g. detect same-CRS-same-resolution and skip the `resampling`/warp kwargs entirely in that case, falling back to `mode` only when an actual grid change is happening). **This needs a targeted probe before touching the code**: compare `resampling="mode"` vs no-kwarg vs `resampling="nearest"` specifically on VALUES (not just timing) for a tile with mixed wet/dry/invalid pixels near a resolution boundary, to confirm mode vs nearest actually produce different (and mode = correct) results before concluding it's safe to skip resampling when grids match.

### 6.5 The `GDAL_HTTP_MAX_TOTAL_CONNECTIONS=64` env var is still set despite being proven useless
Added in commit `7dd49fb`, never removed after the GDAL-3.12 upgrade proved it doesn't help (§3.6). Harmless (a no-op ceiling that's never the binding constraint), but worth a cleanup pass — or worth re-investigating whether it matters combined with the OTHER unimplemented fixes (adaptive tiling changes the concurrency shape — more, smaller tiles being read might change whether connection limits matter again).

### 6.6 No investigation of whether STAC query itself can be shared/cached across years
Each year in `load_wofs_monthly_extent`'s loop calls `_query_wofs_items` independently (§3.9's "irony" section touches this tangentially). At ~3.5s/query × 21 years = ~73s of pure STAC catalog query overhead across a full run, serialized. This was NEVER profiled as its own line item, and no plan addresses it. Small compared to the ~24s/year decode cost, but real and easy to fix (one STAC query for the whole date range instead of one per year) — this may be a legitimate additional lever nobody looked at closely.

### 6.7 Cache-hit path performance never profiled
Every measurement this session was a COLD cache run (`--force` or fresh `--name`). The resumable-cache path (a rerun that hits existing per-year CSV cache files) was never profiled for its own overhead — is reading 21 cached CSVs and reconciling fast, or does it have its own surprising cost? Given how much surprising-cost-in-unexpected-places this session found, this is worth a direct check rather than an assumption.

### 6.8 `time_block` parameter never touched or profiled
`monthly_water_extent`'s `time_block` (default 12, controls how many time-steps get reduced per `dask.compute()` call) was mentioned in passing in its docstring but never varied or profiled this session. Given how much the worker-count and scheduler-type experiments moved the needle unpredictably, `time_block` is an unexplored axis that interacts with the same `dask.compute()` call site.

## 7. Recommendation for the next agent

§6.1 is resolved (fixed directly in the plan during this handoff's review — verify the fix once implemented, don't re-derive it). §6.4 is the sharpest remaining lead: a confirmed, unclaimed ~38% win with one specific correctness question standing between it and being safe to ship (does `resampling="mode"` vs `nearest"` vs no-kwarg actually change VALUES near mixed wet/dry/invalid pixel boundaries, or is the time cost purely from GDAL's warp machinery firing regardless of kernel — in which case the fix is "skip the warp path on a same-grid load," not "drop mode resampling"). Run that targeted values-comparison probe first; it's a fast, decisive check before touching any code. After that, execute `2026-07-23-adaptive-tile-sizing.md` (the proven, output-safe win), then decide on §6.2/§6.3 (re-profile Fitzroy + the real multi-catchment workflow with all fixes applied) before committing to the parallel-years or coarse-resolution plans, since both of those are currently speculative relative to the ACTUAL production workflow.
