# Stress-Trust Layer Design

Date: 2026-07-20
Status: Approved (pending spec self-review)

## Problem

`classify_annual_surface_water_condition` (`hydroseason/_condition.py`) labels each
hydrological year's peak/trough extent as `low` / `typical` / `high` against a
baseline, and combines those into `annual_condition` (e.g. `dry_low_refuge`,
`wet_persistent`). Three gaps make this label untrustworthy as a stress signal:

1. **Baseline is not adaptive.** Only `full_record` or a fixed
   `reference_start`/`reference_end` window exist. A baseline built from the
   whole record (or a hand-picked window) mixes pre- and post-drought regimes,
   so "low" can mean "low relative to a non-stationary 40-year mix" rather
   than "low relative to recent conditions."
2. **No uncertainty on the label.** `extent_pct` carries per-month pixel
   counts (`n_valid`, `observed_fraction`) already, but `_condition.py` never
   uses them. A year whose peak sits inside the measurement noise floor gets
   the same confident `low`/`high` label as a year with a clear, well-observed
   departure.
3. **No resolution-timing caveat.** Prior analysis
   (`scripts/compare_catchment_resolution_windows.py`,
   `output/resolution_window_comparison/hy_summary.csv`) found that for
   low-amplitude catchments (moonie, paroo), the *month* picked as peak or
   end-dry flips between native and coarse resolution even when the
   magnitude label wouldn't. That risk currently isn't surfaced per-HY.

## Goals

- Every hydrological year in a record gets a condition label — no large
  unlabelled gap at the start of the series.
- The baseline adapts to non-stationarity (recent conditions weighted, not
  a 40-year blend).
- A label that falls inside measurement noise is explicitly marked uncertain
  rather than reported as confident stress.
- Years whose peak/trough timing is resolution-fragile are flagged, so a
  user doesn't over-read a specific month as physically meaningful.

## Non-goals

- `compute_monthly_surface_water_condition` (the monthly-grain anomaly
  function) is **out of scope**. It keeps its current full-record /
  fixed-window baseline. The same adaptive-window baseline can be applied to
  it later by reusing the helper introduced here.
- No JRC/GSW fallback data source work (separate spec).
- No gauge-data validation (separate spec).
- No re-running catchments at multiple resolutions to detect timing risk —
  the timing flag is amplitude-based, not a second load.
- Existing `full_record` and fixed-window (`reference_start`/`reference_end`)
  behavior does not change. All new behavior is additive (`reference="rolling"`
  is a new opt-in value) or new columns.

## Design

### 1. Adaptive rolling baseline

`classify_annual_surface_water_condition` gains `reference="rolling"` with
parameters `window_cycles: int = 10` and `min_baseline_cycles: int = 5`
(the existing `min_baseline_cycles` parameter is reused for this new floor).

For each HY row, in chronological order:

- Candidate baseline = all **complete, confirmed-boundary** cycles strictly
  *before* the current year (leave-one-out is automatic — the current year
  is never in its own baseline).
- `prior_n = len(candidate baseline)`
- `prior_n < min_baseline_cycles` (default 5) → `annual_condition = "insufficient_baseline"`,
  same as today's insufficient-baseline path.
- `min_baseline_cycles <= prior_n < window_cycles` → **expanding phase**:
  baseline = all prior cycles. `baseline_mode = "expanding"`,
  `baseline_uncertain = True`.
- `prior_n >= window_cycles` → **rolling phase**: baseline = the most recent
  `window_cycles` prior cycles. `baseline_mode = "rolling"`,
  `baseline_uncertain = False`.

New columns on the output frame: `baseline_mode` (`"insufficient"` /
`"expanding"` / `"rolling"`), `baseline_n` (count actually used),
`baseline_uncertain` (bool).

Percentiles (`peak_percentile`, `trough_percentile`) and the existing
`recharge_condition`/`refuge_condition`/`annual_condition` columns are
computed exactly as today, just against this per-row adaptive baseline
instead of the single global `reference_mask`. `full_record` and fixed-window
modes are unaffected — this is a new branch, not a change to existing ones.

**Worked example (21-year record, defaults):** years 1–4 →
`insufficient_baseline`. Years 5–10 → labelled, `baseline_mode="expanding"`,
`baseline_n` from 5 to 9. Years 11–21 → `baseline_mode="rolling"`,
`baseline_n=10`, baseline slides forward each year.

### 2. Noise-floor hedge on the label

Reuses `n_valid` (or `observed_fraction`) already present per month in the
prepared extent frame. For each HY row:

- `noise_floor_pp_peak = 100 / n_valid_at_peak_month`
- `noise_floor_pp_trough = 100 / n_valid_at_trough_month`
  (falls back to `NaN` if pixel counts aren't available, e.g. percentage-only
  input — in that case the hedge is skipped and `*_qualified` columns equal
  the unhedged columns.)

New columns `recharge_condition_qualified`, `refuge_condition_qualified`,
`annual_condition_qualified` mirror the unhedged columns, except: if
`abs(extent_pct - baseline_median) < noise_floor_pp` for peak or trough, that
side's qualified condition becomes `"typical_uncertain"` instead of its
unhedged `low`/`high` value. `annual_condition_qualified` is recomputed from
the qualified peak/trough pair using the same combination mapping as today.

The original `recharge_condition` / `refuge_condition` / `annual_condition`
columns are never modified — existing consumers (report.py, tests) keep
seeing exactly what they see today.

### 3. Timing-confidence flag (resolution sensitivity)

Reuses `probe_amplitude` (`hydroseason/_io_resolution.py`). Per HY row:

- `amplitude_pp = peak_extent_pct - trough_extent_pct`
- `timing_confidence = "low"` if `amplitude_pp < k * noise_floor_pp_peak`
  (default `k=2`), else `"high"`.

This flags that the *specific month* chosen as peak/end-dry is fragile to
resolution/noise (the moonie/paroo effect from the prior comparison run),
independent of whether the magnitude label itself is trustworthy. No second
resolution load is performed — this is a cheap arithmetic check using values
already computed.

### New columns (all additive, all on `classify_annual_surface_water_condition`'s output)

| Column | Meaning |
|---|---|
| `baseline_mode` | `insufficient` / `expanding` / `rolling` |
| `baseline_n` | number of prior cycles actually used |
| `baseline_uncertain` | True during expanding phase |
| `noise_floor_pp_peak`, `noise_floor_pp_trough` | `100/n_valid` at that month |
| `recharge_condition_qualified`, `refuge_condition_qualified`, `annual_condition_qualified` | hedged labels |
| `timing_confidence` | `low`/`high`, resolution-fragility of the peak/trough month |

### report.py

The per-catchment HY table gains `annual_condition_qualified` and
`timing_confidence` columns alongside the existing condition column, so a
report reader sees both the plain label and its trust qualifiers side by
side.

## Testing

- **Rolling baseline:** synthetic 25-year series with a step change at year
  15 (regime shift). Assert: years 1–4 `insufficient_baseline`; years 5–10
  `expanding`; years 11+ `rolling`; by year 25 (window=10 fully past the
  shift, i.e. `prior_n` years 15–24 are all post-shift) the baseline contains
  no pre-shift values, so a post-shift year that matches the new regime's
  typical extent is labelled `typical`, not `low`/`high`.
- **Noise floor hedge:** two years with identical `extent_pct` deviation from
  baseline median, one with high `n_valid` (small noise floor, stays
  `low`/`high`) and one with low `n_valid` (large noise floor, downgrades to
  `typical_uncertain`).
- **Timing confidence:** flat/low-amplitude synthetic series →
  `timing_confidence="low"`; strong monsoonal-amplitude series →
  `"high"`.
- **Regression:** existing `full_record` and fixed-window callers (current
  test suite) produce byte-identical values for all pre-existing columns.

## Open questions for implementation

- None — all decisions above were confirmed during design (window=10,
  floor=5, k=2 for timing threshold, monthly-condition function out of
  scope).
