# Impl plan: Lazy, bounded, signal-safe multi-catchment extent

**Spec:** [2026-07-17-lazy-bounded-multi-catchment-extent-design.md](../specs/2026-07-17-lazy-bounded-multi-catchment-extent-design.md)
**Method:** TDD, RED first each task. Small commits, one task = one commit.
**Scope guard:** extent feeder + runner only. No detection / pattern / (semi-)Markov change.

## Decisions locked before code

1. **Signal-bound fraction = existing `_boundary.py` constant, not new ⅓.**
   `_boundary.py:75` hardcodes `0.10 * amplitude_pp` as the tolerance cap — repo's
   existing answer to "amplitude vs floor". Reuse it. Extract to module constant
   `SIGNAL_FLOOR_FRACTION = 0.10`, export, reference from both `_boundary._epsilon_pp`
   and the new gate. Veto rule: **coarsening allowed only if
   `projected_noise_floor_pp <= SIGNAL_FLOOR_FRACTION * amplitude_pp`** (floor stays under
   10% of amplitude). Kills two-constants-same-meaning drift.

2. **`plan_resolution` stays pure arithmetic. Probe is separate I/O.**
   Signature per spec takes `observed_amplitude_pp=None`. The coarse probe that produces
   amplitude lives in runner, not inside `plan_resolution`. Two functions, clean seam.

3. **Probe = two passes, not one.** Thin-channel guard (§4) needs water-fraction at chosen
   res vs one-step-coarser. Fold both into `probe_amplitude` so probe returns
   `(amplitude_pp, water_fraction_by_res)`. Still ~100x cheaper than full native run.

4. **Probe result checkpoints.** Chosen res + amplitude + floor land in result dict and
   pickle so rerun skips re-probe.

## Task graph

```
T1 SIGNAL_FLOOR_FRACTION constant  (no dep)
T2 monthly_water_extent streaming  (no dep) ── independent of T1/T3, parallel-safe
T3 plan_resolution pure gate       (dep T1)
T4 resolution passthrough load     (no dep) ── independent, parallel-safe
T5 probe_amplitude + guard         (dep T3, T4)
T6 runner wiring                   (dep T3, T5)
T7 html stamp + caveat             (dep T6)
```

---

## T1 — Extract signal-floor constant

**File:** `hydroseason/_boundary.py`

RED: test `SIGNAL_FLOOR_FRACTION == 0.10` importable; `_epsilon_pp` still caps at
`SIGNAL_FLOOR_FRACTION * amplitude_pp` (existing behaviour unchanged).

GREEN:
- Add `SIGNAL_FLOOR_FRACTION = 0.10` at module top.
- `_epsilon_pp` line 75: `min(0.10 * amplitude_pp, ...)` → `min(SIGNAL_FLOOR_FRACTION * amplitude_pp, ...)`.
- Export in `__all__` (add if absent).

Existing `_boundary` tests must stay green — pure refactor, no numeric change.

---

## T2 — Per-month streaming in `monthly_water_extent`

**File:** `hydroseason/hydro_year.py` (`monthly_water_extent`, lines 151-201)

RED (perf regression test, `tests/` new file):
- Synthetic lazy dask cube, large-ish time (e.g. 120), small y/x.
- Assert result DataFrame **identical** to old all-at-once path (numeric equality — same
  numbers, spec §3).
- Assert peak concurrent chunk load **bounded and independent of `time` length**: run at
  time=24 and time=120, assert peak footprint proxy does not scale with time.
  Mechanism: fake scheduler / chunk-load counter or `dask.diagnostics` — count max
  concurrent y/x chunks in flight. (Pick counter over wall-memory — deterministic.)

GREEN:
- Replace single `dask.compute(n_aoi, n_valid, n_water, n_invalid)` (line 180) with bounded
  loop over `time` in blocks of `time_block` (new param, default 1).
- Each block: `.isel(time=slice(i, i+time_block))`, build the 4 reductions over spatial
  dims, `dask.compute`, collect scalar arrays. Spatial chunks release before next block.
- Concat per-block scalar arrays back to full-length before the `np.divide` /
  DataFrame assembly (lines 182-201 unchanged downstream).
- Reductions already reduce only over `spatial_dims`, keeping `time` — slicing time then
  concatenating is arithmetically identical. Verify `n_aoi`/`n_valid`/`n_water`/`n_invalid`
  order preserved by index.

Signature: add `time_block: int = 1`. Doc: "trades scheduler overhead for locality."

---

## T3 — `plan_resolution` pure gate

**File:** `hydroseason/io.py` (new function)

RED (signal-preservation test, partial — pure-arith half):
- Known bbox + crs + budget → asserts finest-that-fits picked.
- With `observed_amplitude_pp` small enough that projected floor at that res violates
  `floor <= SIGNAL_FLOOR_FRACTION * amplitude` → asserts veto in `reason`.
- Budget so tight even 300 m fails → `reason` flags catchment (exclude from pattern claims).

GREEN:
```
plan_resolution(bounds_wgs84, target_crs, *, memory_budget_gb,
                observed_amplitude_pp=None,
                candidate_res_m=(30, 60, 100, 150, 300),
                bytes_per_scratch=..., time_chunk=24)
  -> (resolution_m, projected_peak_gb, projected_noise_floor_pp, reason)
```
- Reproject bbox → target_crs, area m². `n_pixels = area / res²`.
- `peak_gb = n_pixels * time_chunk * bytes_per_scratch / 1e9`. (int8 mask + reduction
  accumulators — set `bytes_per_scratch` to cover mask+accum, document the multiplier.)
- Walk candidate res ascending (finest first). First res with `peak_gb <= budget` = memory pick.
- Signal veto: `projected_noise_floor_pp = 100 / n_valid_at_res`
  (`n_valid ≈ n_pixels`, in-AOI fraction ~1 for estimate). If
  `observed_amplitude_pp` given and pick is coarser than the finest res satisfying
  `floor <= SIGNAL_FLOOR_FRACTION * observed_amplitude_pp` → step finer until both clear,
  else if none clears both → `reason="signal_veto_no_fit"` flag.
- `reason` strings: `"ok"`, `"coarsened"`, `"signal_veto_no_fit"`, `"native_no_fit"`.
- Import `SIGNAL_FLOOR_FRACTION` from `_boundary`.

No I/O. bbox reproject via pyproj/geopandas already available (raster extra).

---

## T4 — `resolution` passthrough in `load_wofs_from_stac`

**File:** `hydroseason/io.py` (line 197-254)

RED (passthrough test):
- Mock/patch `odc.stac.stac_load`, call loader with `resolution=100`.
- Assert `stac_load` received `resolution=100, resampling="mode"`.
- Assert `resolution=None` → neither kwarg forces change (behaviour unchanged path).

GREEN:
- Add param `resolution: float | None = None` to signature (line 197-201).
- In `stac_load` call (line 242) add `resolution=resolution, resampling="mode"` — but only
  when `resolution is not None` (None → native default, unchanged). Use same kwarg-splat
  idiom as existing `crs`:
  `**({"resolution": resolution, "resampling": "mode"} if resolution is not None else {})`.

---

## T5 — `probe_amplitude` + thin-channel guard

**File:** `hydroseason/io.py` (new function) — I/O, uses T3+T4.

RED (signal-preservation test, guard half):
- Synthetic braided/thin-channel cube: water fraction collapses disproportionately from
  chosen res → one coarser. Assert guard fires (`refuse_coarsen_past=<res>`, caveat string).
- Normal cube: guard silent.

GREEN:
```
probe_amplitude(stac_url, collection, aoi, start, end, *, crs,
                probe_res_m=300, guard_step_m=... )
  -> {amplitude_pp, water_fraction_by_res, guard_caveat, refuse_coarsen_past}
```
- Load at `probe_res_m` via `load_wofs_from_stac(..., resolution=probe_res_m)` →
  `monthly_water_extent` → amplitude (reuse `_boundary.robust_scale` for the same amplitude
  definition, or 10-90 pctl spread — match `_boundary` so gate + detector agree).
- Second pass at one coarser step. Compare mean water fraction. If coarser drops fraction
  by more than threshold (channels sub-pixel) → set `guard_caveat` + `refuse_coarsen_past`.
- Guard threshold: define + document (e.g. water fraction retention < X). Labelled caveat
  string for the report, not just log.

---

## T6 — Runner wiring

**File:** `scripts/run_multi_catchment_report.py`

- Args: `--resolution N` (override gate), `--allow-large` (bypass memory veto),
  `--memory-budget-gb` (default e.g. 12).
- Per catchment, before full load:
  1. `probe_amplitude(...)` → amplitude + guard.
  2. `plan_resolution(geo["bounds_wgs84"], OUTPUT_CRS, memory_budget_gb=...,
     observed_amplitude_pp=amplitude)` → chosen res, peak_gb, floor, reason.
  3. Respect `--resolution` override; respect `refuse_coarsen_past` from guard (never
     coarser than guard allows).
  4. `--allow-large` bypasses memory veto for native run.
- **Print exact cost, no interactive prompt** (spec §2 — batch stays non-interactive):
  chosen res, projected peak GB, floor, reason, guard caveat.
- Full load: `load_wofs_from_stac(..., resolution=chosen_res)`.
- If `reason` flags catchment (signal_veto_no_fit) → still load if forced, but stamp
  `pattern_claim_excluded=True` so html frames it honestly.
- Stamp into result dict + checkpoint (§4): `resolution_m`, `n_valid`,
  `projected_noise_floor_pp`, `reason`, `guard_caveat`, `pattern_claim_excluded`.
- Checkpoint carries probe result → rerun skips re-probe.

No interactive prompt anywhere. Print-and-proceed.

---

## T7 — HTML stamp + thin-channel caveat

**File:** `scripts/build_multi_catchment_html.py`

- Per-catchment chart: show `resolution_m`, `n_valid`, `projected_noise_floor_pp`.
- If `guard_caveat` present → labelled caveat block in report (not log).
- If `pattern_claim_excluded` → frame catchment as "resolution-flagged, regime-shape only",
  exclude from pattern claims.
- Comparison section: framed regime-shape, resolution stamp visible per catchment
  (mixed per-catchment res accepted **only if stamped** — spec §guiding principle).

---

## Verification (before "done")

- Full pytest green (perf regression, signal-preservation both halves, passthrough).
- `_boundary` existing tests green (T1 refactor safe).
- Run runner `--only <one small catchment>` end-to-end (Moonie ~14,700 km²), confirm:
  probe fires, cost printed, no prompt, stamp in html, checkpoint has probe fields, rerun
  skips probe.
- ruff / import-sort gate green (repo has one — see git log `7063abe`).

## Commit sequence

`test:`+`feat:` pair per task. Suggested:
1. `refactor: extract SIGNAL_FLOOR_FRACTION in _boundary`
2. `feat: per-month streaming in monthly_water_extent`
3. `feat: plan_resolution memory+signal gate`
4. `feat: resolution passthrough to stac_load`
5. `feat: probe_amplitude + thin-channel guard`
6. `feat: wire gate/probe/stamp into multi-catchment runner`
7. `feat: render resolution stamp + thin-channel caveat in report`
