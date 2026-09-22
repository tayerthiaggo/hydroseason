# Main Workflow Case Study

New extraction uses this exact default sequence:

`user AOI acquisition boundary -> cached DEA Multi-Year Statistics -> fixed unfiltered count_wet > 0 raster -> separate planning superset -> monthly WOfS -> percentage-based analysis -> four CSVs`

The mask source is one pinned `ga_ls_wo_fq_myear_3` artifact, not a Calendar
Year union. Its verified manifest records product/version, item IDs, lineage,
and exact coverage; the source observed at design time covered 1987--2025. A
requested analysis end after the manifest's `coverage_end` now proceeds with a
`HistoricalMaskCoverageWarning` instead of failing closed. The
scientific raster has no frequency threshold, closing, or buffer, while the
separate coarse/dilated planning superset only limits reads.

The checked reports are regenerated offline from the committed monthly extent
fixtures; no catchment boundaries or network maps are used in this update.

This case study demonstrates the single route-aware HydroSeason workflow across five representative Australian catchments using committed 30 m whole-catchment monthly surface-water extent series (2005–2025).

## Methodology and Routing Authority

HydroSeason uses `analyze_catchment` under the `hydroseason-v0.2.0` method policy as the single routing authority. Before extracting annual boundaries or summary metrics, the pipeline assesses whether a catchment exhibits a stable, reproducible annual seasonal cycle with identifiable annual timing (`per_year_detection`) or an irregular, non-seasonal hydrological regime (`event_characterisation`).

The checked case-study build uses `quality_policy="flag"`: finite monthly
observations remain available for cycle mapping, while `invalid_pct` is carried
through as a quality state and can make a boundary provisional/low confidence.
Months with no observed extent or 100% invalid coverage remain unusable.

Each generated report bundle now has compact, stable CSVs: a monthly timeline,
hydrological-year markers, wet events, and low-extent spells. Routing, counts,
and interpretation remain in the HTML report. The complete column dictionary
and event definitions are documented
in [Report CSV columns](../report-columns.md).

Each checked report includes circular peak/trough timing concentration (R),
bootstrap confidence intervals, Kuiper uniformity p-values, timing IQR, and
the count of annual timings. IQR remains descriptive; route eligibility uses
the trough timing concentration confidence interval.

- **Seasonal catchments** (`per_year_detection`): Hydrological year boundaries are anchored to climatological troughs, and annual recharge/trough metrics are computed for complete hydrological years.
- **Aseasonal catchments** (`event_characterisation`): No hydrological years are forced. The workflow reports discrete water inundation events, low-water spell durations, and overall extent variability.

> [!IMPORTANT]
> **Scientific Denominator and Extent Caveats:**
> In newly extracted records, `n_aoi` is the fixed historical-mask pixel count. `invalid_pct` uses that denominator, so invalid pixels outside the historical mask have no effect. `extent_pct` uses valid pixels inside the same mask, and all routing/date/event selections remain percentage-based.
> - Surface water extent is **not** river discharge, stream depth, total storage volume, ecological health, or causal water allocation attribution.
> - Whole-catchment extent percentages dilute narrow river channels and localized floodplain inundation across broad dry landscapes.
> - Optical water detection (WOfS) can miss water under dense vegetation or during persistent cloud cover.

## Main Study Results

<!-- BEGIN GENERATED MAIN RESULTS -->
| Catchment | Regime | Route | Peak R | Trough R | Trough R CI low | Peak-month IQR (months) | Hydro Years | Events | Longest Low Spell (months) | Peak Month | Trough Month |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Daly River (NT) | seasonal | per_year_detection | 0.864 | 0.800 | 0.703 | 2.0 | 21 | 21 | 6 | Mar | Nov |
| Fitzroy River (WA) | seasonal | per_year_detection | 0.907 | 0.919 | 0.881 | 1.0 | 21 | 18 | 8 | Feb | Nov |
| Gilbert River (QLD) | seasonal | per_year_detection | 0.934 | 0.975 | 0.967 | 1.0 | 21 | 24 | 10 | Feb | Nov |
| Lachlan River (NSW) | aseasonal | event_characterisation | 0.324 | 0.604 | 0.455 | 4.0 | 0 | 5 | 55 | N/A | N/A |
| Moonie River (QLD/NSW) | aseasonal | event_characterisation | 0.532 | 0.687 | 0.549 | 3.0 | 0 | 14 | 22 | N/A | N/A |
<!-- END GENERATED MAIN RESULTS -->

### Why Daly River is seasonal and supports per-year boundaries

HydroSeason evaluates seasonality strictly by the calendar recurrence of annual
timing. Daly River satisfies the recurrence conjunction: both annual peak
timing (R = 0.864) and trough timing (R = 0.800) reject the discrete uniform
null under circular Kuiper tests. Furthermore, with its trough timing
concentration 95% bootstrap CI lower bound at 0.703, and 21 resolved cycles
satisfying the seven-cycle annualization guard, Daly is classified as `seasonal`
and routed to `per_year_detection`. Its 2.0-month peak IQR is retained as a
descriptive spread, not a route threshold.

The low-confidence March 2011 maximum (87.2% invalid pixels) is a separate
boundary-quality warning. It does not alter the record-level regime label or
the trough-timing route decision. Likewise, Daly's rainfall timing
does not promote its water route: rainfall is ancillary, while routing is decided
from observed water extent.

## Findings

1. **Monsoonal/Northern Catchments (Daly, Fitzroy, Gilbert):** Fitzroy and
   Gilbert support independently detected per-year boundaries. Daly also
   supports per-year boundaries because its trough timing lower confidence
   bound meets the R >= 0.70 route rule. Its March 2011 observed maximum
   remains visible but low confidence because 87.2% of pixels were invalid.
2. **Inland/Low-Relief Catchments (Lachlan, Moonie):** Calendar timing
   recurrence was not established across either record (broad year-to-year
   timing scatter failing the Kuiper recurrence conjunction), routing both
   records to event characterisation. Lachlan has 5 wet events and a 55-month
   longest low spell; Moonie has 14 events and a 22-month longest low spell.
   No annual boundaries are forced.
