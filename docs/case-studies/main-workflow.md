# Main Workflow Case Study

This study runs the standard `hydroseason-v0.2.0` workflow on five Australian
catchments using committed 30 m whole-catchment monthly surface-water extent
series from DEA Water Observations (2005–2025, 252 months each). The reports
are rebuilt offline from those committed series.

## Method

`analyze_catchment` decides each route from the water record alone:

- **Seasonal** (`per_year_detection`): circular Kuiper tests reject uniform
  timing for both annual peaks and troughs (p < 0.05), and at least seven
  peak and trough cycles are resolved. Each hydrological year runs from one
  dynamically detected trough to the next.
- **Aseasonal** (`event_characterisation`): recurrence is not established. No
  hydrological years are forced; the report gives wet events, low-extent
  spells, and overall variability.

The build uses `quality_policy="flag"`: finite monthly observations stay
available for cycle mapping, while `invalid_pct` is carried as a quality state
that can make a boundary provisional. Months with no observed extent or 100%
invalid coverage remain unusable. The CSV columns are documented in
[Report CSV columns](../report-columns.md).

Each report also shows peak and trough timing concentration (R, the mean
resultant length) with bootstrap confidence intervals and the timing IQR.
These are descriptive; they do not set the route.

!!! note "What extent can and cannot tell you"
    `invalid_pct` uses the fixed historical-mask pixel count as its
    denominator, and `extent_pct` uses valid pixels inside the same mask.
    Surface-water extent is **not** discharge, depth, storage volume, or
    ecological condition. Whole-catchment percentages dilute narrow channels
    across broad dry landscapes, and optical detection can miss water under
    dense vegetation or persistent cloud.

## Results

<!-- BEGIN GENERATED MAIN RESULTS -->
| Catchment | Regime | Route | Peak R | Trough R | Trough R CI low | Peak-month IQR (months) | Hydro Years | Events | Longest Low Spell (months) | Peak Month | Trough Month |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Daly River (NT) | seasonal | per_year_detection | 0.878 | 0.777 | 0.684 | 2.0 | 21 | 21 | 6 | Mar | Nov |
| Fitzroy River (WA) | seasonal | per_year_detection | 0.900 | 0.892 | 0.866 | 2.0 | 21 | 18 | 8 | Feb | Nov |
| Gilbert River (QLD) | seasonal | per_year_detection | 0.934 | 0.908 | 0.892 | 1.0 | 21 | 24 | 10 | Feb | Nov |
| Lachlan River (NSW) | aseasonal | event_characterisation | 0.393 | 0.607 | 0.313 | 4.0 | 0 | 5 | 55 | N/A | N/A |
| Moonie River (QLD/NSW) | aseasonal | event_characterisation | 0.444 | 0.605 | 0.423 | 3.0 | 0 | 14 | 22 | N/A | N/A |
<!-- END GENERATED MAIN RESULTS -->

Kuiper p-values (peak / trough): Daly 0.001 / 0.002, Fitzroy 0.001 / 0.001,
Gilbert 0.001 / 0.001, Lachlan 0.262 / 0.139, Moonie 0.232 / 0.009.

## Findings

1. **Daly, Fitzroy, and Gilbert are seasonal.** Both peak and trough timing
   recur in the same calendar months (all p ≤ 0.002), and each record
   clears the seven-cycle guard, yielding 21 hydrological years. Daly's March 2011 maximum is kept but marked
   `anomalous` because 87.2% of its pixels were invalid; that flags the
   cycle as provisional without changing the regime or route.
2. **Lachlan and Moonie are aseasonal.** Lachlan fails both tests. Moonie's
   troughs recur (p = 0.009) but its peaks do not (p = 0.232), and the method
   requires both. Both records route to event characterisation: Lachlan has
   5 wet events and a 55-month longest low spell; Moonie has 14 events and a
   22-month longest low spell. No annual boundaries are forced.
