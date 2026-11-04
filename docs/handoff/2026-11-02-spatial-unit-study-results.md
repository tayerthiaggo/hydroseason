# Spatial unit study: results

Date: 2026-11-02. Plan and decision rules: [2026-11-02-spatial-unit-study-plan.md](2026-11-02-spatial-unit-study-plan.md), frozen before any outcome was read (SHA-256 of LF bytes `8840a23f1e344fa881c616f7c4d0a7176d60ece5996a294ec25fb68403af0c11`, recorded in the [receipt](2026-11-02-spatial-unit-study-receipt.json)). Numbers below come from [2026-11-02-spatial-unit-study-results.json](2026-11-02-spatial-unit-study-results.json) (pre-registered) and [2026-11-02-spatial-unit-study-exploratory.json](2026-11-02-spatial-unit-study-exploratory.json) (post hoc, labelled as such).

## Summary

The same 30 m pixels were summed into 1,278 areas across the five case-study catchments and each area was run through HydroSeason exactly as the case studies are.

1. **Unit type: equivalent.** At the same size, HydroBASINS subbasins and square grid tiles route to per-year detection at the same rate and confirm the same share of cycle boundaries. Following drainage divides does not change what HydroSeason reports.
2. **Size: no minimum by routing.** In the seasonal catchments, at least 92.5% of areas routed seasonal in every water-pixel class, down to areas with under 100 water pixels in a typical month. Exploratory: those smallest areas date the season less consistently.
3. **Timing asynchrony: below the threshold.** 24.7% of level-7 subbasins in the seasonal catchments have a climatological trough more than one month from their catchment's, just under the 25% rule.
4. **Hidden seasonality: material.** The Lachlan routes aseasonal as a whole, but 16 of its 36 level-7 subbasins route seasonal. The Moonie stays aseasonal when split.

Advice for the library documentation follows the pre-registered table: no preference for subbasins over tiles; check subbasins before concluding a large catchment has no season. Two exploratory observations are added as cautions, not rules.

## Units

| Scheme | Units | Median area (km²) | Notes |
| --- | ---: | ---: | --- |
| Catchment | 5 | 54,670 | Fitzroy is the BoM boundary ∩ WA DWER outline (93,255 km²) |
| HydroBASINS level 6 / 7 / 8 | 33 / 128 / 369 | 4,807 / 1,693 / 476 | ≥ 50% inside the catchment, clipped to it |
| Grid tiles, 69 / 41 / 22 km | 54 / 152 / 537 | 4,275 / 1,681 / 484 | Origin (0, 0) in EPSG:3577, ≥ 50% inside, clipped |

No unit raised an error and every unit had pixels on the cube grid.

## Validation

**V1, series.** Each catchment series rebuilt from the cube matches the committed case-study CSV:

| Catchment | Pearson r (monthly `extent_pct`) | `n_aoi` cube / case |
| --- | ---: | ---: |
| Daly | 0.99983 | 0.9993 |
| Fitzroy | 0.99944 | 0.9589 (outline, expected) |
| Gilbert | 0.99948 | 0.9988 |
| Lachlan | 0.99975 | 0.9994 |
| Moonie | 0.99935 | 0.9985 |

All five pass. Water-pixel counts are not identical: the cube counts every scene, while the library's DEA loader merges overlapping scenes from the same solar day before the monthly vote (`groupby="solar_day"`), so votes differ slightly where scene footprints overlap. Every unit in the study uses the same cube rule, so the comparison is unaffected.

**V2, outcomes.** The rebuilt catchments reproduce the case-study regime, route, number of hydrological years (21, 21, 21, 0, 0) and climatological peak month. The only difference is Gilbert's climatological trough month (10 against 11).

## Pre-registered results

### C1. Subbasins versus tiles at matched size: equivalent

Mantel–Haenszel weighted differences, subbasin minus tile, over catchment × area-bin strata; 95% intervals from 2,000 within-catchment bootstrap draws.

| Outcome | Difference | 95% interval | Catchments positive / negative |
| --- | ---: | --- | --- |
| Routed seasonal (primary) | −0.012 | −0.051 to 0.025 | 3 / 2 |
| Confirmed boundary share (primary) | +0.009 | −0.006 to 0.025 | 3 / 1 |
| Trough point-timing share | +0.014 | −0.008 to 0.037 | 2 / 2 |
| Baseline-eligible share | +0.003 | −0.006 to 0.012 | 1 / 3 |

Both primary intervals lie inside ±0.10, so the decision is **Equivalent**. The two aseasonal catchments lean the other way on routing (Lachlan −0.078, Moonie −0.099: tiles route seasonal slightly more often there); the three seasonal catchments lean towards subbasins by 0.010 to 0.036.

### C2. Size: no minimum by routing

Share of units routed seasonal in the seasonal catchments (Daly, Fitzroy, Gilbert), by median monthly water pixels:

| Water pixels | Subbasins | Tiles |
| --- | --- | --- |
| < 100 | 0.948 (n = 174) | 0.925 (n = 293) |
| 100 – 1,000 | 1.000 (103) | 0.982 (113) |
| 1,000 – 10,000 | 0.985 (65) | 1.000 (68) |
| 10,000 – 100,000 | 1.000 (9) | 1.000 (9) |

Every bin is at or above 0.80, so the rule gives a minimum of 0 water pixels for both types: no minimum is recommended on routing. By area, subbasins also give no minimum; tiles give 300 km² because the 12 tiles under 300 km² (edge tiles cut by the catchment boundary) route seasonal at 0.75.

### C3. Timing asynchrony: not material by the rule

Among the 85 level-7 subbasins routed seasonal in the seasonal catchments, 24.7% have a climatological trough more than one month from the catchment's and 16.5% a peak. The threshold was 25%, so the result is recorded as not material, with the note that it falls 0.3 points short.

### C4. Hidden seasonality: material

Among the 43 level-7 subbasins of the catchments that route aseasonal, 37.2% route seasonal: Lachlan 16 of 36 (44.4%), Moonie 0 of 7. The threshold was 25%, so the result is material.

## Exploratory (post hoc)

Not part of the decisions; thresholds here were chosen after seeing the data.

**Small areas date the season less consistently.** For units routed seasonal in the seasonal catchments:

| Water pixels | Type | n | Confirmed share | Trough point share | Peak within 1 month of catchment | Trough within 1 month of catchment |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| < 100 | subbasin | 165 | 0.155 | 0.172 | 0.715 | 0.376 |
| 100 – 1,000 | subbasin | 103 | 0.233 | 0.276 | 0.942 | 0.864 |
| 1,000 – 10,000 | subbasin | 64 | 0.262 | 0.372 | 0.906 | 0.938 |
| < 100 | tile | 271 | 0.156 | 0.165 | 0.734 | 0.450 |
| 100 – 1,000 | tile | 111 | 0.245 | 0.289 | 0.829 | 0.802 |
| 1,000 – 10,000 | tile | 68 | 0.229 | 0.356 | 0.882 | 0.912 |

Below about 100 water pixels in a typical month (about 0.09 km² of open water at 30 m), fewer boundaries are confirmed and the trough agrees with the catchment's far less often. The data cannot separate real local timing (small headwater channels drying earlier) from noise.

**The Lachlan's seasonal parts are upstream.** At level 8, 76% of the subbasins in the eastern (upper) third route seasonal, against 35% in the western (lower) third; tiles show the same gradient (79% against 41%). The seasonal level-7 subbasins peak in winter and spring (July to September for 11 of 16) and bottom out in summer (January and February for 13 of 16). The subbasins that stay aseasonal hold more water (median 1,808 water pixels a month against 488), so they dominate the catchment total.

**Aggregation did not blur the trough.** The catchment-scale trough is resolved to a single month at least as often as in its level-7 subbasins (Daly 0.52 against a subbasin median of 0.24; Fitzroy 0.29 against 0.24; Gilbert 0.24 against 0.24). The concern that summing asynchronous subbasins flattens the dry-season low is not supported here.

## Advice for the library documentation

| Result | Advice |
| --- | --- |
| C1 Equivalent | Grid tiles, planning zones or other polygons are acceptable; there is no need to redraw areas along drainage divides for the method to behave. Choose the area for the question being asked. |
| C2 no minimum | No minimum area is recommended on routing grounds. Exploratory caution: below about 100 water pixels in a typical month, treat dates as indicative and compare them with a larger enclosing area. |
| C3 not material | No rule. Descriptive note: a quarter of subbasins have a trough more than a month from their catchment's; analyse a specific reach or refuge directly when its timing matters. |
| C4 material | An aseasonal catchment can contain seasonal subbasins; run the subbasins before concluding there is no season. |

The guide section "Choosing the area to analyse" carries this advice.

## Limits

- Five catchments, one period (2005–2025), one product. Three are monsoonal tropical, two semi-arid Murray–Darling. Strongly seasonal tropics make routing robust at every size; the size effect shows up in timing instead.
- Areas used the whole unit as the denominator, as the case studies do; the default DEA workflow uses the fixed historical water mask. Water-pixel counts, the size measure used here, do not depend on the denominator.
- HydroBASINS divides come from 15 arc-second (about 450 m) terrain, coarser than the 30 m pixels.
- One tile origin; tiles at the catchment edge are clipped and smaller.
- `confirmed_share` and the timing comparisons are conditioned on routing seasonal.

## Provenance and process

- Receipt `docs/handoff/2026-11-02-spatial-unit-study-receipt.json` (LF SHA-256 `95ed565a1bc98a8ce8aced0aade0b326d715a79da8211654b6c09e6421da5040`): plan hash, script hash (`303a9761047e…`), git head `d32dd47`, library 0.2.0, input hashes (boundaries, DWER outline, HydroBASINS archive and shapefiles, cube metadata), unit counts, tile sides, and V1 for the catchments validated by then. The results JSON cites the receipt hash and records the hashes of all five series files and the final V1 table.
- Scripts: `scripts/spatial_unit_study.py` (stages `units`, `aggregate`, `validate`, `analyze`, `evaluate`) and `scripts/spatial_unit_study_explore.py` (post hoc tables). Intermediate data (unit polygons, label rasters, unit series, per-unit outcomes) are in `D:\RLH\5.6\data_local\intermediate\hydroseason_spatial_unit_study`.
- Order: Gilbert and Moonie were analysed while the other catchments were still aggregating, as the plan allows; a Daly batch was stopped after three minutes to restart all remaining units with more workers, and the resumed run skipped the units already written. The outcomes file had no partial lines.
- Deviations from the plan: none in the decision rules. The two rules added to the plan before the receipt (zero-pixel units, analysis order) did not affect any unit: no unit had zero pixels.
