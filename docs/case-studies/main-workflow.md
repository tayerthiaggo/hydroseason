# Main Workflow Case Study

This case study demonstrates the single route-aware HydroSeason workflow across five representative Australian catchments using committed 30 m whole-catchment monthly surface-water extent series (2005–2025).

## Methodology and Routing Authority

HydroSeason uses `analyze_catchment` as the single routing authority. Before extracting annual boundaries or summary metrics, the pipeline assesses whether a catchment exhibits a stable, reproducible annual seasonal cycle (`per_year_detection`) or an irregular, non-seasonal hydrological regime (`event_characterisation`).

The checked case-study build uses `quality_policy="flag"`: finite monthly
observations remain available for cycle mapping, while `invalid_pct` is carried
through as a quality state and can make a boundary provisional/low confidence.
Months with no observed extent or 100% invalid coverage remain unusable.

Each generated report bundle now has compact, stable CSVs: a monthly timeline,
hydrological-year markers, wet events, and low-extent spells. Routing, counts,
and interpretation remain in the HTML report. The complete column dictionary
and event definitions are documented
in [Report CSV columns](../report-columns.md).

The checked case-study results currently retain CSVs only. HTML and manually
generated graph images are deferred until the separate HTML pass is finalised.

- **Seasonal catchments** (`per_year_detection`): Hydrological year boundaries are anchored to climatological troughs, and annual recharge/trough metrics are computed for complete hydrological years.
- **Marginal catchments** (`fixed_climatological_window`): A fixed climatological window is retained as an explicitly imposed frame; boundary rows can still be provisional when observed markers have high invalid coverage.
- **Aseasonal catchments** (`event_characterisation`): No hydrological years are forced. The workflow reports discrete water inundation events, low-water spell durations, and overall extent variability.

> [!IMPORTANT]
> **Scientific Denominator and Extent Caveats:**
> Surface extent percentage (`extent_pct`) measures the proportion of unmasked catchment area covered by surface water.
> - Surface water extent is **not** river discharge, stream depth, total storage volume, ecological health, or causal water allocation attribution.
> - Whole-catchment extent percentages dilute narrow river channels and localized floodplain inundation across broad dry landscapes.
> - Optical water detection (WOfS) can miss water under dense vegetation or during persistent cloud cover.

## Main Study Results

<!-- BEGIN GENERATED MAIN RESULTS -->
| Catchment | Regime | Route | SNR | Hydro Years | Events | Longest Low Spell (months) | Peak Month | Trough Month |
|---|---|---|---|---|---|---|---|---|
| Daly River (NT) | marginal | fixed_climatological_window | 2.46 | 21 | 21 | 6 | Mar | Nov |
| Fitzroy River (WA) | seasonal | per_year_detection | 2.65 | 21 | 18 | 8 | Feb | Nov |
| Gilbert River (QLD) | seasonal | per_year_detection | 3.62 | 21 | 24 | 10 | Feb | Nov |
| Lachlan River (NSW) | aseasonal | event_characterisation | 0.67 | 0 | 5 | 55 | N/A | N/A |
| Moonie River (QLD/NSW) | aseasonal | event_characterisation | 0.62 | 0 | 14 | 22 | N/A | N/A |
<!-- END GENERATED MAIN RESULTS -->

## Findings

1. **Monsoonal/Northern Catchments (Daly, Fitzroy, Gilbert):** The records retain all finite observations for review. Fitzroy and Gilbert remain seasonal with per-year detected boundaries; Daly is routed to an imposed climatological window under the flagged-quality view. Its 2011 cycle is retained, with the March observed maximum marked low confidence because 87.2% of pixels were invalid.
2. **Inland/Low-Relief Catchments (Lachlan, Moonie):** Low signal-to-noise ratio (SNR < 1.0) and high year-to-year peak month dispersion indicate aseasonal regimes. Routing correctly disables annual hydrological year partitioning and characterizes ephemeral wet events (12–14 events) and prolonged dry spells (up to 30 months).
