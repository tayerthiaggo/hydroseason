# Coarse-Resolution Load Option Implementation Plan (Outline)

> **For agentic workers:** This is an OUTLINE, not a step-by-step plan. Expand to full task detail (via superpowers:writing-plans) before executing. Independent of the other two 2026-07-23 plans; can be done any time.

**Goal:** Let callers load WOfS at a coarser analysis resolution (e.g. 60 m or 90 m) than the 30 m native, for a proportional cut in decoded data volume, where the science tolerates coarser pixels.

**Why this is a real lever:** Session profiling found the per-year cost is dominated by decoding pixel volume: 291.7 MB decompressed for one year of the Gilbert AOI at 30 m. Data volume scales with the square of resolution — 60 m is ~4× fewer pixels, 90 m is ~9× fewer — so a coarser load is a near-proportional wall-clock cut on the decode-bound step. This is *already supported* by the loaders (`resolution=` flows through `stac_load` with `resampling="mode"` when set); the work here is making it a first-class, well-documented, correctly-cached analysis choice rather than an ad-hoc override.

## Critical constraint: this CHANGES output

Unlike adaptive tiling (byte-identical) and parallel years (byte-identical), coarser resolution produces **different extent values** — pixels are aggregated, `n_aoi`/`n_valid`/`extent_pct` all shift. Therefore:
- It must be **opt-in per analysis**, never a default.
- The cache key already includes `resolution` (`_cache_path` in `hydroseason/_io_extent_cache.py` hashes it), so a coarse run cannot collide with a 30 m run — good, no schema bump needed.
- Documentation must be explicit that coarse extent series are not comparable to 30 m ones and are for speed/preview or genuinely coarse analyses.

## Key facts from the session

- `load_wofs_monthly_extent(..., resolution=None)` today: `None` means "native", passed through to `stac_load` without a `resampling` kwarg.
- When `resolution` is set, `_load_wofs_items` adds `resampling="mode"` — mode (majority) resampling is the correct kernel for a categorical water mask (never average/bilinear, which would fabricate fractional water). Preserve this.
- WOfS native transform is 30 m (`proj:transform: [30.0, ...]`, `gsd: 30.0`). A coarse load at 60/90 m warps from that.

## Realistic approach

1. No new machinery is strictly required — `resolution` already works. The deliverable is (a) validation that only mode-resampling is used for coarse loads, (b) a documented, tested path, and (c) a convenience surface.
2. Add a guard: if a caller passes a `resolution` finer than native (< 30 m) it is upsampling noise — warn or reject, since it inflates data volume for no signal gain.
3. Optionally add a `--resolution` preset note to the extract script help (the flag already exists) and a short section to the README / docs on the speed/accuracy tradeoff with a measured example.

## Risks / open questions to resolve during full planning

- **Resampling correctness:** confirm `mode` is applied on the *canonical* classified values, not raw WOfS bit-flags, or that mode over raw flags still yields correct water/dry/invalid majorities. Trace `_classify` vs the `resampling="mode"` point in `_load_wofs_items` — resampling happens inside `stac_load` (before `_classify`), so mode operates on raw uint8 WOfS values. Verify that mode over raw WOfS flag values is meaningful (e.g. 128=wet vs 0=dry majority) and does not blend flag bits into nonsense codes. THIS IS THE KEY CORRECTNESS QUESTION and must be settled with a test before shipping.
- **`all_touched` / edge effects:** coarser pixels straddling the AOI boundary interact with the clip differently; confirm `n_aoi` still counts sensibly.
- **Minimum useful resolution:** past some coarseness a thin river is sub-pixel and reads as zero water. Document the floor for channel-scale AOIs.

## Task shape (to expand)

1. Add a native-resolution floor guard (reject/warn on `resolution < native`), with a test.
2. Add a test proving a 60 m load produces a valid, self-consistent extent series (`n_aoi == n_valid + n_invalid`, percentages in range) and that its cache key differs from a 30 m load.
3. Settle the mode-over-raw-flags correctness question with an explicit test on a synthetic mixed-flag tile.
4. Document the tradeoff (docs + script help), with one measured speed example (e.g. 60 m ≈ Nx faster than 30 m on Gilbert).

## Definition of done

- Coarse loads are opt-in, correctly mode-resampled, and provably self-consistent.
- Cache never mixes resolutions.
- Mode-resampling correctness on raw WOfS flags is tested, not assumed.
- Docs state plainly that coarse series are not comparable to native-resolution series.
