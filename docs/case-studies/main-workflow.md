# Main Workflow Case Study

This case study demonstrates the single route-aware HydroSeason workflow across five representative Australian catchments using committed 30 m whole-catchment monthly surface-water extent series (2005–2025).

## Methodology and Routing Authority

HydroSeason uses `analyze_catchment` as the single routing authority. Before extracting annual boundaries or summary metrics, the pipeline assesses whether a catchment exhibits a stable, reproducible annual seasonal cycle (`per_year_detection`) or an irregular, non-seasonal hydrological regime (`event_characterisation`).

- **Seasonal catchments** (`per_year_detection`): Hydrological year boundaries are anchored to climatological troughs, and annual recharge/trough metrics are computed for complete hydrological years.
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
| Daly River (NT) | seasonal | per_year_detection | 3.80 | 21 | 22 | 6 | Feb | Nov |
| Fitzroy River (WA) | seasonal | per_year_detection | 3.64 | 21 | 19 | 8 | Feb | Nov |
| Gilbert River (QLD) | seasonal | per_year_detection | 3.26 | 21 | 30 | 8 | Jan | Oct |
| Lachlan River (NSW) | aseasonal | event_characterisation | 0.96 | 0 | 12 | 30 | N/A | N/A |
| Moonie River (QLD/NSW) | aseasonal | event_characterisation | 0.61 | 0 | 14 | 21 | N/A | N/A |
<!-- END GENERATED MAIN RESULTS -->

## Findings

1. **Monsoonal/Northern Catchments (Daly, Fitzroy, Gilbert):** High amplitude signal-to-noise ratio (SNR > 3.0) confirms strong seasonal predictability. All 21 hydrological years (2005–2025) were successfully detected with peak water extents occurring in monsoonal summer (Jan–Feb) and dry-season troughs in late spring (Oct–Nov).
2. **Inland/Low-Relief Catchments (Lachlan, Moonie):** Low signal-to-noise ratio (SNR < 1.0) and high year-to-year peak month dispersion indicate aseasonal regimes. Routing correctly disables annual hydrological year partitioning and characterizes ephemeral wet events (12–14 events) and prolonged dry spells (up to 30 months).
