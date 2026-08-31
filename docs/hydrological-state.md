# Dynamic hydrological years and surface-water condition

Use this workflow for monthly remotely sensed surface-water extent in a fixed river reach, pool complex, wetland, or count-aggregated basin. It measures observed extent timing and historical condition. It does not estimate discharge, depth, volume, drought, ecological condition, or cause.

## Minimal workflow

```python
from hydroseason import analyze_hydrological_state

result = analyze_hydrological_state(monthly_extent)
result.pattern          # advisory seasonal shape
result.config           # inspect the suggested phase and tolerance
result.hydro_years      # peak, temporal mid-dry, half-loss, trough, condition
result.monthly_condition
result.monthly_phase    # labelled by default; pass phase_scheme="none" to disable
```

Pass `DynamicHydroYearConfig(expected_trough_month=...)` when local knowledge should override the advisory phase. The configured month centres the annual search; it is not a fixed hydrological-year boundary.

## Annual interpretation

- `peak_extent_pct`: maximum observed extent in the dynamic trough-to-trough cycle. The observed maximum is retained for review even when its `invalid_pct` exceeds the configured quality threshold; inspect `peak_selection_status` and `peak_invalid_pct` before treating it as trusted evidence.
- `temporal_mid_dry_extent_pct`: observed extent nearest the temporal midpoint between peak and trough.
- `half_loss_extent_pct`: first observed post-peak extent at or below half the peak-to-trough loss.
- `trough_extent_pct`: ending low-water extent selected from that year's search opportunity.
- Recharge condition ranks annual peaks; refuge condition independently ranks annual troughs.
- Continuous percentiles are primary. Public labels are compact interpretation aids.

## Monthly phases

Monthly phases are descriptive labels attached after annual cycle detection.
They never alter `hydro_years`, annual condition baselines, peaks, troughs, or
cycle boundaries. HydroSeason 0.2.0 provides two phase schemes via `phase_scheme`:

- `phase_scheme="two_phase"` (default): labels months inside detected cycles as `rising` or `receding`.
- `phase_scheme="none"`: disables phase labelling and returns `phase="unspecified"` with `phase_status="disabled"`.
- `phase_scheme="four_phase"` is a deprecated alias accepted for compatibility; it produces the same two labels.

Each detected cycle is split at its observed peak:

- `rising`: the cycle start through the observed peak;
- `receding`: the month after the peak through the observed trough.

The annual `half_loss_month` field remains the separate peak-to-trough
diagnostic. These are descriptive surface-water phases, not discharge or
baseflow separation.

Labels are anchored to the selected robust trough boundaries and `peak_month`;
months outside complete cycles remain
`unspecified` with `phase_status="outside_cycle"`, and months in partial cycles
are marked `phase_status="unresolved_cycle"`. Unusable months keep their
positional phase label for continuity, but use `phase_status="unusable"` with
lower confidence.

The stable columns are `hy_year`, `phase`, `phase_status`,
`phase_confidence`, `phase_method`, `boundary_basis`, `extent_pct`, and
`candidate_usable`. `monthly_condition` and `monthly_phase` are separate products:
condition ranks historical wet/dry extremeness, while phase describes within
cycle timing.

Legacy parameter `phase_model` maps to `phase_scheme` with a deprecation warning (`rule_based` and `cycle_relative` -> `two_phase`, `none` -> `none`). Legacy aliases are targeted for removal in 0.3.0. Phase selection cannot change regime, route, extrema, boundaries, events, or low spells.

HydroSeason 0.2.0 also evaluates an experimental challenger model for harmonic evidence and boundary recoverability; this experimental challenger does not control public regime, route, extrema, or hydrological-year boundaries.

```python
from hydroseason import DynamicHydroYearConfig, analyze_hydrological_state

config = DynamicHydroYearConfig(expected_trough_month=11, phase_scheme="two_phase")
result = analyze_hydrological_state(monthly, config=config)
result.monthly_phase[["hy_year", "phase", "phase_status", "phase_confidence"]]
```

## Regime behaviour

Monsoonal intermittent systems are the primary case. Bimodal systems retain a caller-selected primary trough and report secondary extrema descriptively. Perennial-like low-variability systems retain timing and extent metrics but suppress extreme labels by default. Low-variability, weak, or irregular records require a user-supplied expected trough month because their fitted phase is not a defensible automatic boundary.

## Trough boundary detection and mid-dry rainfall pulses

The default detector (`detector="robust_extrema"`) selects, for each year's
expected trough window, the raw observed minimum (`raw_trough_month`,
`raw_trough_extent_pct`) plus its contiguous "equivalent low run" — the
adjacent months within measurement-noise tolerance of that minimum
(`low_run_start_month`/`low_run_end_month`). A sequence-consistent optimizer
(`select_boundary_sequence`) may resolve an exact-value tie within that same
equivalent run so consecutive years' cycle lengths stay coherent. The released
detector never shifts onto a materially higher month; any exact-tie shift is
labelled `coherence_adjusted`, while the raw observed minimum remains
separately auditable.

Rewetting pulses are still counted: `n_rewetting_pulses` records rises,
adjacent in whole months after the peak, that later recede. Pulse counting no
longer *gates* the trough boundary — the old recovery-confirmation state
machine (which required a fixed number of consecutive rising months followed
by a fixed rejection window with no return to the plateau) has been removed.

### Diagnostic columns

Each year's trough opportunity carries diagnostics that separate what was
*observed* from what was *selected*, so the boundary choice stays auditable:

- `raw_trough_month` / `raw_trough_extent_pct`: the true observed minimum in
  the expected window. It is always reported, including when an exact-value tie
  month within the equivalent low run is ultimately chosen as `trough_month` —
  this value is never silently replaced.
- `low_run_start_month` / `low_run_end_month`: the contiguous run of months
  within measurement-noise tolerance of the raw minimum (the "equivalent low
  run"). `trough_month` may be any month drawn from this run, and only from
  this run.
- `window_status`: `full` when the complete expected window was observed;
  `left_truncated` or `right_truncated` when the record starts or ends inside
  the expected window; `internal_gap` when too few usable months fall inside
  the window even though the window itself is not truncated.
- `selection_status`: `raw` when the raw minimum itself was selected with no
  ambiguity; `ambiguous` when a singleton or anomalous low was retained but
  flagged uncertain; `low_quality` when the observed extremum comes from a
  month above the configured invalid-coverage threshold;
  `coherence_adjusted` when an exact-value tie was chosen for cycle consistency;
  `unresolved` when too few observed candidates existed to select anything that
  year. `quality_adjusted` remains reserved for explicit quality-based
  reselection.
- `selection_support`: a 0-1 confidence-like value combining window coverage
  and ambiguity. It is a quality grade, not yet a calibrated probability.
- `boundary_status`: `confirmed` when the window is full, the raw minimum was
  selected, and `selection_support` is at least 0.80; `provisional` otherwise.
  Downstream condition-baseline logic (`hydroseason/_condition.py`) uses this
  gate to decide whether a cycle may anchor a historical baseline — only
  `confirmed` cycles are eligible.
- `peak_selection_status` / `peak_selection_support`: the same quality
  diagnostics for the observed within-cycle maximum. A `low_quality` peak is
  retained, but forces the annual row to `status="partial"` and
  `boundary_status="provisional"`.
- `detector` (a `DynamicHydroYearConfig` field, not an annual output column):
  `"robust_extrema"` is the only supported value, gated on real Fitzroy and
  Gilbert River evidence; any other value is rejected at construction.

```python
config = DynamicHydroYearConfig(
    expected_trough_month=11,
    detector="robust_extrema",
)
annual = detect_dynamic_hydrological_years(monthly, config=config)
annual[[
    "raw_trough_month", "trough_month", "window_status",
    "selection_status", "selection_support", "boundary_status",
]]
```

## Quality and aggregation

`invalid_pct` is a percentage: observed fraction is `1 - invalid_pct / 100`.
For default high-level DEA acquisition, `n_aoi` is the constant pixel count of
the fixed `(Multi-Year count_wet > 0) AND user AOI` historical mask, and
`invalid_pct = 100 * n_invalid / n_aoi`. Pixels outside that exact raster are
outside (`-2`), so cloud, shadow, or no-data values there cannot change
`invalid_pct`. `extent_pct` remains `100 * n_water / n_valid` among valid
observations inside the mask.

Observed extrema from low-quality months remain visible for auditability, but
they are flagged `low_quality`, reduce support, and cannot produce a confirmed
annual boundary. Use `quality_policy="flag"` when finite observations with
partial invalid coverage should remain `candidate_usable`/`usable_month` for
cycle identification; their invalid counts still lower confidence. A 100%
invalid month (or a month with no observed extent) remains ineligible. Aggregate
basins with summed `n_water` and `n_valid` counts, or explicit AOI area weights;
unweighted percentage means are rejected. Regime routing, hydrological-year
boundaries, peaks, mid-dry markers, troughs, phases, wet events, and low spells
remain selected from percentages; the workflow does not derive area or km2
values.

## Limitations

Surface extent is not volume or depth. Extent-discharge relationships may be lagged or hysteretic. Optical classifiers under-detect narrow, shaded, turbid, or vegetated water. Monthly composites miss short events. AOI changes alter the series meaning. Managed releases, barriers, and groundwater can decouple extent from flow. High trough extent alone does not prove ecological resilience. Basin aggregation can hide local refuge failure, so report AOI results alongside basin results.

## Validation direction for Australia

Use the frozen Fitzroy/Kimberley comparison first. Next replicate the Gilbert River dynamic hydrological-year and persistent-pool work (Tayer et al. 2023, 2026; open dataset DOI `10.26182/866c-5c36`). Use Warrego-Darling/Toorale event records for dry-sequence and reconnection direction, Macquarie Marshes as a vegetated-water limitation test, and nearby BoM Hydrologic Reference Stations only where gauge and mapped reach processes are spatially comparable.
