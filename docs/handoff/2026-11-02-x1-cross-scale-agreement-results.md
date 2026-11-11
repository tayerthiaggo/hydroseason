# X1: cross-scale agreement of HydroSeason dates — results

Date: 2026-11-02. Plan: [2026-11-02-x1-cross-scale-agreement-plan.md](2026-11-02-x1-cross-scale-agreement-plan.md), frozen before any per-year date was computed. The plan's SHA-256 of LF bytes, `873181031112…`, is recorded in the [receipt](2026-11-02-x1-cross-scale-agreement-receipt.json), whose own SHA-256 is `5dc37fa69d2e05bf1948702cf1225df6a4a4d26eceb555685942fdd081484e8c`. Numbers come from [2026-11-02-x1-cross-scale-agreement-results.json](2026-11-02-x1-cross-scale-agreement-results.json). Only the water extent was used; no gauge entered.

## Summary

HydroSeason ran year by year on 535 nested areas: the five catchments and HydroBASINS levels 6, 7 and 8 inside them. No run failed. 419 areas route to per-year detection, and 98–99% of inner cycles matched a cycle of the containing area.

1. **Peaks transfer more readily than trough boundaries (R2).** Peaks agree with the whole catchment 0.109 more often than trough boundaries do (95% interval 0.089 to 0.130), and peaks agree more in all three seasonal catchments.
2. **The nearest containing subbasin is the better source (R3).** Agreement with it beats agreement with the whole catchment by 0.039 for peaks (0.029 to 0.051) and 0.083 for trough boundaries (0.068 to 0.099).
3. **Size at which a containing area's dates hold (R1, agreement ≥ 0.80 from that size up):**

| Date | From the nearest containing subbasin | From the whole catchment |
| --- | --- | --- |
| Peak | any size | from 100 water pixels a month |
| Trough boundary | from 100 water pixels a month | no size: even the largest subbasins agree only 0.778 |

## Agreement within one month

| Relation, date | Pooled | 95% interval | Matched cycles | Both `point` only |
| --- | ---: | --- | ---: | ---: |
| Containing subbasin, peak | 0.869 | 0.856–0.880 | 7,607 | 0.908 (5,762) |
| Containing subbasin, trough boundary | 0.808 | 0.787–0.829 | 7,607 | 0.901 (1,054) |
| Whole catchment, peak | 0.836 | 0.825–0.848 | 7,035 | 0.873 (5,503) |
| Whole catchment, trough boundary | 0.727 | 0.705–0.749 | 7,035 | 0.722 (730) |

By the inner area's median monthly water pixels:

| Water pixels | Subbasin, peak | Subbasin, trough | Catchment, peak | Catchment, trough |
| --- | ---: | ---: | ---: | ---: |
| < 100 | 0.809 | 0.697 | 0.781 | 0.621 |
| 100 – 1,000 | 0.907 | 0.896 | 0.866 | 0.810 |
| 1,000 – 10,000 | 0.944 | 0.937 | 0.912 | 0.856 |
| 10,000 – 100,000 | 0.965 | 0.890 | 0.947 | 0.778 |

By catchment, against the whole catchment:

| Catchment | Peak | Trough boundary |
| --- | ---: | ---: |
| Daly | 0.803 | 0.654 |
| Fitzroy | 0.846 | 0.743 |
| Gilbert | 0.881 | 0.843 |

The Lachlan and Moonie catchments route aseasonal, so they contribute only subbasin-to-subbasin pairs. Lachlan agreement with the containing subbasin: peak 0.816, trough boundary 0.813.

## What it means for the advice

Following the plan's table:
- A larger area's **peak** dates can stand in for its parts: from the nearest containing subbasin at any size, and from the whole catchment once the part holds about 100 water pixels a month.
- A larger area's **trough boundary** is less transferable. Borrow it only from the nearest containing subbasin, and only for parts above about 100 water pixels. Do not borrow the whole catchment's.
- Borrow from the nearest containing subbasin, not the whole catchment.

The guide section "Choosing the area to analyse" now carries this.

## Limits

- **Agreement is not correctness.** Two areas can agree and both be off.
- **Scope:** five catchments, 2005–2025, and the cube's per-scene majority rule (see the spatial unit study).
- **Thin bins:** the 10,000–100,000 water-pixel bin has 189–228 matched cycles per relation; nothing larger was available.

## Provenance

- **Script:** `scripts/cross_scale_agreement.py` (receipt hash `0eeecc9e3973…`). It reuses the spatial unit study's series and analysis call. The study's receipt and script hashes are recorded in the X1 receipt.
- **Intermediate files:** in `D:\RLH\5.6\data_local\intermediate\hydroseason_spatial_unit_study\x1` (`cycles.jsonl`, `pairs.csv`).
- **Deviations from the plan:** none.
