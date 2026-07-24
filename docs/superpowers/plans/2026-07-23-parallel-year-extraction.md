# Parallel Year Extraction Implementation Plan (Outline)

> **For agentic workers:** This is an OUTLINE, not a step-by-step plan. Expand to full task detail (via superpowers:writing-plans) before executing. Sequenced AFTER `2026-07-23-adaptive-tile-sizing.md` — measure that win first, since it changes the per-year cost this plan parallelizes.

**Goal:** Cut wall-clock for multi-year extractions by running the independent per-calendar-year loads concurrently across processes, instead of the current strictly-sequential year loop.

**Why processes, not threads:** Session profiling proved the per-AOI decode already saturates dask's threaded scheduler (synchronous=125s vs threaded=18s for one year; forcing more threads made it *worse*). So there is no thread headroom left *within* a year. But the years themselves are independent (each has its own STAC query, cache file, and reduction), so the remaining parallelism is *across* years — and because a single year already maxes the thread pool, additional years must run in separate **processes** to get their own decode budget.

## Key facts from the session

- `load_wofs_monthly_extent` loops `_year_windows(start, end)` sequentially (`hydroseason/_io_extent_cache.py`, the `for year_start, year_end in year_iter:` loop).
- Each year writes its own atomic per-year cache CSV (`_cache_path` / `_write_extent_atomic`) and is resumable independently — so concurrent years do not race on a shared file, as long as each writes only its own year's path.
- A full 21-year Gilbert run is ~21 × (~24s after adaptive tiling) ≈ 8-9 min, dominated by summing independent years.

## Realistic approach

1. Add an optional `year_workers: int = 1` parameter to `load_wofs_monthly_extent`. `1` (default) preserves today's exact sequential behaviour and byte-for-byte output — no regression risk for existing callers.
2. When `year_workers > 1`, dispatch the per-year work (the body currently inside the year loop) to a `concurrent.futures.ProcessPoolExecutor`. Each worker computes one year's extent DataFrame and writes its own cache file; the parent collects results and concatenates in index order (existing `pd.concat(parts).sort_index()`).
3. Windows requires the `if __name__ == "__main__"` guard for `ProcessPoolExecutor` — the extract script already runs under `main()`, so this holds, but document it.

## Risks / open questions to resolve during full planning

- **Picklability:** the per-year closure must not capture unpicklable objects (open rasterio handles, lazy dask cubes). The worker should take only plain args (stac_url, collection, aoi *path or serialisable GDF*, dates, crs, resolution, tile_pixels, wet_aoi geometry, cache_dir) and do its own loading inside the process. Verify the AOI and wet_aoi cross the process boundary as geometry/paths, not live objects.
- **STAC query duplication:** each year already does its own STAC query today, so process isolation adds no *extra* queries — but confirm the wet-AOI precompute (if used) is done once in the parent and its resulting polygon passed to workers, not recomputed per process.
- **Oversubscription:** each process spins up its own dask thread pool. With N processes × M threads you can oversubscribe cores. Size `year_workers` to `cpu_count // (threads_per_year)` or expose it and document the tradeoff; default sequential avoids the issue entirely.
- **Progress reporting:** the current tqdm year bar assumes sequential iteration; with a process pool, tick on future completion instead.
- **Error propagation:** a failing year in a worker must surface the real exception (and its year) to the parent, matching today's fail-loud behaviour.

## Task shape (to expand)

1. Add `year_workers` param, default 1, thread through the script as `--year-workers`. Prove default path unchanged (existing tests still green).
2. Extract the per-year loop body into a module-level, picklable `_load_one_year(...)` function taking only serialisable args. Test it in isolation returns the same DataFrame the inline body did.
3. Add the `ProcessPoolExecutor` dispatch behind `year_workers > 1`. Test (with a mocked loader) that N years dispatch concurrently and the concatenated result equals the sequential result.
4. End-to-end timing on the real multi-year Gilbert run; confirm speedup and byte-identical output vs `year_workers=1`.

## Definition of done

- `year_workers=1` is byte-identical to today (regression-proof default).
- `year_workers>1` produces identical output to sequential, measurably faster on a multi-year run.
- No unpicklable-object crashes on Windows.
