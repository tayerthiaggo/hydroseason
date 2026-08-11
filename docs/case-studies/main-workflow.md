# Main Workflow Case Study

New extraction uses this exact default sequence:

`user AOI acquisition boundary -> cached DEA Multi-Year Statistics -> fixed unfiltered count_wet > 0 raster -> separate planning superset -> monthly WOfS -> percentage-based analysis -> four CSVs`

The mask source is one pinned `ga_ls_wo_fq_myear_3` artifact, not a Calendar
Year union. Its verified manifest records product/version, item IDs, lineage,
and exact coverage; the source observed at design time covered 1987--2025. A
requested analysis end after the manifest's `coverage_end` fails closed. The
scientific raster has no frequency threshold, closing, or buffer, while the
separate coarse/dilated planning superset only limits reads.

No network re-extraction or case-study regeneration was performed for this
documentation update, so the committed inputs and results remain unchanged.

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
> In newly extracted records, `n_aoi` is the fixed historical-mask pixel count. `invalid_pct` uses that denominator, so invalid pixels outside the historical mask have no effect. `extent_pct` uses valid pixels inside the same mask, and all routing/date/event selections remain percentage-based.
> - Surface water extent is **not** river discharge, stream depth, total storage volume, ecological health, or causal water allocation attribution.
> - Whole-catchment extent percentages dilute narrow river channels and localized floodplain inundation across broad dry landscapes.
> - Optical water detection (WOfS) can miss water under dense vegetation or during persistent cloud cover.

## Main Study Results

<!-- BEGIN GENERATED MAIN RESULTS -->
| Catchment | Regime | Route | SNR | Peak-month IQR (months) | Hydro Years | Events | Longest Low Spell (months) | Peak Month | Trough Month |
|---|---|---|---|---|---|---|---|---|---|
| Daly River (NT) | marginal | fixed_climatological_window | 2.46 | 2.0 | 21 | 21 | 6 | Mar | Nov |
| Fitzroy River (WA) | seasonal | per_year_detection | 2.65 | 1.0 | 21 | 18 | 8 | Feb | Nov |
| Gilbert River (QLD) | seasonal | per_year_detection | 3.62 | 1.0 | 21 | 24 | 10 | Feb | Nov |
| Lachlan River (NSW) | aseasonal | event_characterisation | 0.67 | 4.0 | 0 | 5 | 55 | N/A | N/A |
| Moonie River (QLD/NSW) | aseasonal | event_characterisation | 0.62 | 3.0 | 0 | 14 | 22 | N/A | N/A |
<!-- END GENERATED MAIN RESULTS -->

### Why Daly River is marginal, not seasonal

HydroSeason requires **both** a strong annual swing and reproducible timing
before it permits independently detected boundaries for each year. Daly
passes the strength gate: its water-extent SNR is 2.46, above the seasonal minimum of 2.0.
It misses the timing gate: the circular IQR of its per-year
peak months is 2.0 months, above the seasonal maximum of 1.5 months. It is
therefore `marginal`, not `seasonal`, and uses one explicitly imposed
climatological window instead of claiming that each year's boundaries are
independently reproducible.

The low-confidence March 2011 maximum (87.2% invalid pixels) is a separate
boundary-quality warning. It does not explain the record-level regime label;
the marginal label comes from year-to-year peak timing across the full
record. Likewise, Daly's rainfall SNR of 5.81 cannot promote its water route:
rainfall is ancillary, while routing is decided from observed water extent.

## Findings

1. **Monsoonal/Northern Catchments (Daly, Fitzroy, Gilbert):** Fitzroy and
   Gilbert support independently detected per-year boundaries. Daly retains
   a clear average monsoonal cycle but misses the peak-timing reproducibility
   gate, so it uses the imposed fixed window explained above. Its March 2011
   observed maximum remains visible but low confidence because 87.2% of
   pixels were invalid.
2. **Inland/Low-Relief Catchments (Lachlan, Moonie):** SNR below 0.7 and broad
   year-to-year peak timing route both records to event characterisation.
   Lachlan has 5 wet events and a 55-month longest low spell; Moonie has 14
   events and a 22-month longest low spell. No annual boundaries are forced.
