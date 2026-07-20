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
2. **No uncertainty on the label.** The monthly extent frame carries the
   information needed for a noise scale (pixel counts / `observed_fraction`),
   and `robust_scale` already distills it into a record-level `noise_pp` for
   the boundary detector — but `_condition.py` never sees `noise_pp`. A year
   whose peak sits inside the measurement noise floor gets the same confident
   `low`/`high` label as a year with a clear, well-observed departure. (The
   *annual* frame handed to `_condition.py` does **not** carry `n_valid` — only
   `*_invalid_pct` — so the hedge must take `noise_pp` from the caller, who
   computed it from the monthly frame; see Design §2.)
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
parameters `rolling_window_cycles: int = 10` and `rolling_min_cycles: int = 5`.

> **Audit correction (2026-07-20).** An earlier draft said the existing
> `min_baseline_cycles` parameter would be reused for the floor. It cannot:
> `min_baseline_cycles` defaults to **10** (`DynamicHydroYearConfig`) and
> `tests/test_condition.py` depends on that value for the `full_record`
> activation gate. The rolling floor is therefore a **separate**
> `rolling_min_cycles` parameter (default 5), leaving `min_baseline_cycles`
> untouched.

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

> **Audit correction (2026-07-20).** The original draft derived the noise
> floor as `100 / n_valid_at_peak_month`. That is **not reconstructable from
> the annual frame**: `ANNUAL_COLUMNS` (`hydroseason/_dynamic_year.py`) carries
> `peak_invalid_pct` / `trough_invalid_pct` (percentages), not the `n_valid`
> pixel count. The codebase already computes a principled record-level noise
> scale — `robust_scale(prepared_monthly_frame)` returns `(amplitude_pp,
> noise_pp)` where `noise_pp` is a MAD-based month-to-month noise estimate
> (`hydroseason/_boundary.py`), and `_epsilon_pp` already blends it with the
> `100/n_valid` resolution floor when pixel counts are present. We reuse that
> machinery rather than reinventing it.

The hedge uses `noise_pp` from `robust_scale`, computed once from the
prepared **monthly** extent frame (the same frame the detector already
prepares) and passed into `classify_annual_surface_water_condition` as a new
optional `noise_pp: float | None = None` argument. When `noise_pp is None`
(caller didn't supply it — e.g. percentage-only annual input with no monthly
frame available), the hedge is skipped and `*_qualified` columns equal the
unhedged columns, preserving backward compatibility.

New columns `recharge_condition_qualified`, `refuge_condition_qualified`,
`annual_condition_qualified` mirror the unhedged columns, except: if
`abs(peak_extent_pct - baseline_median) < noise_pp` (peak) or the trough
analogue, that side's qualified condition becomes `"typical_uncertain"`
instead of its unhedged `low`/`high` value. `annual_condition_qualified` is
recomputed from the qualified peak/trough pair using the same combination
mapping as today. `noise_pp` is recorded on the output as `noise_floor_pp`
(single record-level value, not separate peak/trough) for transparency.

The original `recharge_condition` / `refuge_condition` / `annual_condition`
columns are never modified — existing consumers (report.py, tests) keep
seeing exactly what they see today.

### 3. Timing-confidence flag (resolution sensitivity)

> **Audit correction (2026-07-20).** The original draft said this "reuses
> `probe_amplitude`… no second resolution load." That is wrong:
> `probe_amplitude` (`hydroseason/_io_resolution.py`) **loads WOfS twice from
> STAC** — it is an I/O function, not arithmetic. We do not call it. The
> per-HY amplitude we need already exists as `drawdown_pct`
> (`peak_extent_pct - trough_extent_pct`) in `ANNUAL_COLUMNS`, and the noise
> scale is the same `noise_pp` from §2.

Per HY row, using values already on the annual frame plus the `noise_pp`
from §2:

- `amplitude_pp = drawdown_pct` (already computed:
  `peak_extent_pct - trough_extent_pct`).
- `timing_confidence = "low"` if `amplitude_pp < k * noise_pp` (default
  `k=2`), else `"high"`. If `noise_pp is None`, `timing_confidence = "unknown"`.

This flags that the *specific month* chosen as peak/end-dry is fragile to
resolution/noise (the moonie/paroo effect from the prior comparison run),
independent of whether the magnitude label itself is trustworthy. It is pure
arithmetic on values already computed — no load, no `probe_amplitude`.

**Relationship to existing `confidence` column.** `_dynamic_year.py` already
emits a per-HY `confidence` (high/medium/low) measuring *data availability*
(usable-month fraction × observed fraction × boundary penalty). The new
`timing_confidence` is orthogonal — it measures *signal-vs-noise amplitude*,
i.e. whether the seasonal swing is large enough that the peak/trough month is
robustly located. Both are kept; the report shows them as distinct columns so
a low-`timing_confidence` year with high data-availability `confidence` (the
moonie/paroo case: well-observed but flat) is legible.

### New columns (all additive, all on `classify_annual_surface_water_condition`'s output)

| Column | Meaning |
|---|---|
| `baseline_mode` | `insufficient` / `expanding` / `rolling` |
| `baseline_n` | number of prior cycles actually used |
| `baseline_uncertain` | True during expanding phase |
| `noise_floor_pp` | record-level `noise_pp` from `robust_scale` (single value; `NaN` if not supplied) |
| `recharge_condition_qualified`, `refuge_condition_qualified`, `annual_condition_qualified` | hedged labels |
| `timing_confidence` | `low`/`high`/`unknown`, resolution-fragility of the peak/trough month |

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
- **Noise floor hedge:** call with a small `noise_pp` (deviation exceeds it →
  label stays `low`/`high`) and with a large `noise_pp` (deviation falls
  inside it → downgrades to `typical_uncertain`); and with `noise_pp=None`
  (hedge skipped, `*_qualified` equals unhedged).
- **Timing confidence:** HY rows where `drawdown_pct < 2 * noise_pp` →
  `timing_confidence="low"`; `drawdown_pct >= 2 * noise_pp` → `"high"`;
  `noise_pp=None` → `"unknown"`.
- **Regression:** existing `full_record` and fixed-window callers (current
  test suite) produce byte-identical values for all pre-existing columns.

## Data flow / wiring

`noise_pp` is produced by `robust_scale(prepared_monthly_frame)` — already
called inside `detect_dynamic_hydrological_years`
(`hydroseason/_dynamic_year.py`, as `amplitude_pp, noise_pp = robust_scale(frame)`).
The wiring is: whoever calls `classify_annual_surface_water_condition` (report
pipeline, notebooks) computes or forwards this `noise_pp` and passes it in.
Because the detector already computes it, the cheapest path is to surface
`noise_pp` (and `amplitude_pp`) as an attribute/return alongside the annual
frame, or recompute it once at the call site from the same monthly frame. The
implementation plan picks the exact seam; the function contract is only
`noise_pp: float | None = None`.

## Open questions for implementation

- **Where `noise_pp` is threaded from.** Options: (a) `detect_dynamic_hydrological_years`
  attaches `noise_pp` to the returned frame's `.attrs`; (b) the report pipeline
  recomputes `robust_scale` at the call site; (c) a thin wrapper computes it.
  Decide in the plan. All are backward-compatible since the parameter defaults
  to `None`.
- Otherwise settled: window=10, floor=5, k=2 for timing threshold,
  monthly-condition function out of scope.
