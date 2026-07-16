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
```

Pass `DynamicHydroYearConfig(expected_trough_month=...)` when local knowledge should override the advisory phase. The configured month centres the annual search; it is not a fixed hydrological-year boundary.

## Annual interpretation

- `peak_extent_pct`: maximum observed extent in the dynamic trough-to-trough cycle.
- `temporal_mid_dry_extent_pct`: observed extent nearest the temporal midpoint between peak and trough.
- `half_loss_extent_pct`: first observed post-peak extent at or below half the peak-to-trough loss.
- `trough_extent_pct`: ending low-water extent selected from that year's search opportunity.
- Recharge condition ranks annual peaks; refuge condition independently ranks annual troughs.
- Continuous percentiles are primary. Public labels are compact interpretation aids.

## Regime behaviour

Monsoonal intermittent systems are the primary case. Bimodal systems retain a caller-selected primary trough and report secondary extrema descriptively. Perennial-like low-variability systems retain timing and extent metrics but suppress extreme labels by default. Low-variability, weak, or irregular records require a user-supplied expected trough month because their fitted phase is not a defensible automatic boundary.

## Trough boundary detection and mid-dry rainfall pulses

The default detector (`detector="robust_extrema"`) selects, for each year's
expected trough window, the raw observed minimum (`raw_trough_month`,
`raw_trough_extent_pct`) plus its contiguous "equivalent low run" — the
adjacent months within measurement-noise tolerance of that minimum
(`low_run_start_month`/`low_run_end_month`). A sequence-consistent optimizer
(`select_boundary_sequence`) may then shift the reported `trough_month` onto
another month *within that same equivalent run* so consecutive years' cycle
lengths stay coherent. It never shifts onto a materially higher or otherwise
different month: the raw observed minimum is always reported and is never
silently replaced.

A second, opt-in engine (`detector="semi_markov"`, a four-state hidden
semi-Markov model) is available for experimentation and produces the same
output schema, but it is not the default — its own promotion gate has not yet
passed on available fixtures.

Rewetting pulses are still counted: `n_rewetting_pulses` records rises,
adjacent in whole months after the peak, that later recede. Pulse counting no
longer *gates* the trough boundary — the old recovery-confirmation state
machine (which required a fixed number of consecutive rising months followed
by a fixed rejection window with no return to the plateau) has been removed.

### Diagnostic columns

Each year's trough opportunity carries diagnostics that separate what was
*observed* from what was *selected*, so the boundary choice stays auditable:

- `raw_trough_month` / `raw_trough_extent_pct`: the true observed minimum in
  the expected window. It is always reported, even in years where a different
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
  flagged uncertain; `unresolved` when too few usable candidates existed to
  select anything that year. `quality_adjusted` is reserved for future
  quality-based reselection and is not currently produced by either detector.
- `selection_support`: a 0-1 confidence-like value combining window coverage
  and ambiguity. It is a quality grade, not yet a calibrated probability.
- `boundary_status`: `confirmed` when the window is full, the raw minimum was
  selected, and `selection_support` is at least 0.80; `provisional` otherwise.
  Downstream condition-baseline logic (`hydroseason/_condition.py`) uses this
  gate to decide whether a cycle may anchor a historical baseline — only
  `confirmed` cycles are eligible.
- `detector` (a `DynamicHydroYearConfig` field, not an annual output column):
  `"robust_extrema"` is the default, shipped and gated on real Fitzroy and
  Gilbert River evidence; `"semi_markov"` is opt-in and experimental, and
  should not be treated as ready to replace the default. Both choices produce
  the same annual output schema.

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

`invalid_pct` is a percentage: observed fraction is `1 - invalid_pct / 100`. Missing, low-quality, and unknown-quality months are not boundary candidates by default. Aggregate basins with summed `n_water` and `n_valid` counts, or explicit AOI area weights; unweighted percentage means are rejected.

## Limitations

Surface extent is not volume or depth. Extent-discharge relationships may be lagged or hysteretic. Optical classifiers under-detect narrow, shaded, turbid, or vegetated water. Monthly composites miss short events. AOI changes alter the series meaning. Managed releases, barriers, and groundwater can decouple extent from flow. High trough extent alone does not prove ecological resilience. Basin aggregation can hide local refuge failure, so report AOI results alongside basin results.

## Validation direction for Australia

Use the frozen Fitzroy/Kimberley comparison first. Next replicate the Gilbert River dynamic hydrological-year and persistent-pool work (Tayer et al. 2023, 2026; open dataset DOI `10.26182/866c-5c36`). Use Warrego-Darling/Toorale event records for dry-sequence and reconnection direction, Macquarie Marshes as a vegetated-water limitation test, and nearby BoM Hydrologic Reference Stations only where gauge and mapped reach processes are spatially comparable.
