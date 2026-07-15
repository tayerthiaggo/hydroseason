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

## Mid-dry rainfall pulses

The default boundary is the last low plateau before confirmed recovery. Recovery needs two rising months followed by four months without return to the plateau. A temporary rise that recedes remains inside the same hydrological year and is counted as a rewetting pulse. The final boundary is provisional when the record ends before confirmation.

## Quality and aggregation

`invalid_pct` is a percentage: observed fraction is `1 - invalid_pct / 100`. Missing, low-quality, and unknown-quality months are not boundary candidates by default. Aggregate basins with summed `n_water` and `n_valid` counts, or explicit AOI area weights; unweighted percentage means are rejected.

## Limitations

Surface extent is not volume or depth. Extent-discharge relationships may be lagged or hysteretic. Optical classifiers under-detect narrow, shaded, turbid, or vegetated water. Monthly composites miss short events. AOI changes alter the series meaning. Managed releases, barriers, and groundwater can decouple extent from flow. High trough extent alone does not prove ecological resilience. Basin aggregation can hide local refuge failure, so report AOI results alongside basin results.

## Validation direction for Australia

Use the frozen Fitzroy/Kimberley comparison first. Next replicate the Gilbert River dynamic hydrological-year and persistent-pool work (Tayer et al. 2023, 2026; open dataset DOI `10.26182/866c-5c36`). Use Warrego-Darling/Toorale event records for dry-sequence and reconnection direction, Macquarie Marshes as a vegetated-water limitation test, and nearby BoM Hydrologic Reference Stations only where gauge and mapped reach processes are spatially comparable.
