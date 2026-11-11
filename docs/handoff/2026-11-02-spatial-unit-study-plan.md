# Spatial unit study: plan and decision rules (pre-registered)

Date: 2026-11-02. Branch `spatial-unit-study`, off `fix/0.2.1-axis-and-csv-diagnostics` (study files only; no library change). Written before any unit-level series was built or analysed. The SHA-256 of this file is recorded in the run receipt before the analysis stage; any later edit to this plan must be listed in the results as a deviation.

## Question

HydroSeason is run on whatever area a user supplies. Does the kind of area change what it reports, and what should the library advise users to supply?

Three kinds of area are compared on the same pixels:

1. **Whole catchment**: one unit per catchment.
2. **Subbasins**: hydrologically defined units that follow drainage divides.
3. **Grid tiles**: square tiles of the same nominal size as the subbasins, which ignore drainage.

The comparison separates two explanations that a plain "small units do worse" result would confound: **size** (fewer water pixels, so a weaker signal above the detectability floor) and **hydrological coherence** (a unit that follows a drainage divide carries one connected response; a tile can cut across several).

## Data

- **Water observations**: per-pixel monthly counts of raw DEA WOfS flags (`ga_ls_wo_3`), 30 m, EPSG:3577, in `D:\RLH\5.6\data_local\raw\WaterMask-TSFill\cache\raw_wofs_flags_<cube>_1986_2026.zarr`. Variables used: `n_clear_water` (scenes with flag exactly 128) and `n_clear_dry` (flag exactly 0), the same scene classification as `hydroseason._io_geo._classify`.
- **Catchments**: the five case-study catchments (Daly, Fitzroy WA, Gilbert, Lachlan, Moonie), boundaries `D:\RLH\5.6\data_local\raw\catchments\<key>_boundary.geojson`. Fitzroy's cube was built on the WA DWER outline (`shp\Fitzroy_catchment_DWER.shp`), which misses 3,946 km² (4%) of the BoM boundary; the Fitzroy study area is therefore the intersection of the two (93,255 km²). The other four cubes cover their boundaries exactly.
- **Subbasins**: HydroBASINS v1c standard, Australia, levels 6, 7 and 8 (Lehner and Grill 2013, Pfafstetter coding), `D:\RLH\5.6\data_local\raw\HydroBASINS\hybas_au_lev01-12_v1c.zip`, SHA-256 `0d92e803d5b18837c811d133be87ea1fc4a1b7362c974a694e423c9bbcb479b8`. Median subbasin areas inside the five catchments are about 4,800, 1,800 and 500 km².
- **Period**: 2005-01 to 2025-12 (252 months), the case-study window.

## Units

All geometry in EPSG:3577.

- **Catchment** (`catchment`): the study area above, one unit.
- **Subbasins** (`hb6`, `hb7`, `hb8`): every HydroBASINS polygon at that level with at least 50% of its area inside the study area; the unit is its intersection with the study area.
- **Tiles** (`tile6`, `tile7`, `tile8`): a square grid with origin (0, 0) and side `round(sqrt(m_L))` km, where `m_L` is the median area of the level-L subbasin units (after clipping to the study area) pooled over the five catchments. A tile is kept if at least 50% of its area is inside the study area; the unit is its intersection with the study area.

Each scheme is rasterised on the cube grid (pixel centres, `all_touched=False`).

## Series

For each unit and month: a pixel is valid when `n_clear_water + n_clear_dry > 0` and water when `n_clear_water > n_clear_dry` (ties dry), which is the library's majority rule (`_combine_observations`, `majority=True`). `n_aoi` is the unit's pixel count, `n_valid` and `n_water` the valid and water pixel counts. `extent_pct = 100 * n_water / n_valid` (missing when `n_valid = 0`) and `invalid_pct = 100 * (n_aoi - n_valid) / n_aoi`.

## Analysis call

Each unit series is analysed exactly as the case-study main workflow does: `analyze_catchment(extent, phase_scheme="two_phase", quality_policy="flag")`, library defaults otherwise, at the commit recorded in the receipt. A unit whose analysis raises is recorded as `error` with its message. A unit with no pixels on the cube grid (a sliver smaller than one 30 m pixel after rasterising) is listed and excluded.

## Validation gates (checked before outcomes are read)

- **V1, series.** For each catchment, the cube-derived catchment series is compared with the committed `case_studies/data/extent/<key>_30m.csv`. Pass: Pearson r of monthly `extent_pct` ≥ 0.995 over months finite in both, and `n_aoi` within 1% (Fitzroy is expected to differ by about 4% because of its outline and is judged on r alone). A catchment that fails is excluded from all comparisons and the failure is investigated and reported.
- **V2, outcomes.** The catchment unit's regime, route, number of hydrological years and climatological peak and trough months are compared with the case-study fixture (`tests/fixtures/v020/case_studies/main_summary.csv`). Differences are reported; they do not stop the study.
- **Errors.** If more than 5% of units raise, the cause is reported before outcomes are read.
- **Order.** Each catchment is analysed once its aggregation has finished and passed V1, so analysis of early catchments can overlap aggregation of later ones. Outcomes are not read until the evaluate stage, after every catchment has been analysed.

## Outcomes per unit

- `routed_seasonal`: `route == "per_year_detection"` (errors count as not seasonal).
- For routed-seasonal units, over their hydrological years: `confirmed_share` (`boundary_status == "confirmed"`), `trough_point_share` (`trough_timing_status == "point"`), `baseline_eligible_share`.
- Climatological peak and trough months (`mean_monthly_peak_month`, `mean_monthly_trough_month`).
- Covariates: unit area (km²) and median monthly `n_water` (water pixels).

Primary outcomes: `routed_seasonal` and `confirmed_share`. Secondary: `trough_point_share`, `baseline_eligible_share`.

## Comparisons and decision rules

Area bins (km²): [0, 300), [300, 1000), [1000, 3000), [3000, 10000), [10000, ∞). Water-pixel bins (median monthly `n_water`): [0, 100), [100, 1,000), [1,000, 10,000), [10,000, 100,000), [100,000, ∞).

Uncertainty: 2,000 bootstrap draws (seed 0), resampling units with replacement within each catchment, recomputing the statistic each time; 95% percentile intervals. Units within a catchment are spatially correlated, so a consistency requirement across catchments is added to every decision.

**C1. Unit type at matched size (subbasins versus tiles).** Strata are catchment × area bin, kept only when both types are present. The statistic is the Mantel–Haenszel weighted difference, subbasins minus tiles, with stratum weight `n_s * n_t / (n_s + n_t)`: a risk difference for `routed_seasonal` over all units, and a weighted mean difference for `confirmed_share` (and the secondaries) over routed-seasonal units. Per-catchment differences use the same weights within the catchment.

- **Supported** (subbasins better): for at least one primary outcome, difference ≥ 0.10, interval lower bound > 0, and the same sign in at least 3 of the catchments that have a valid stratum.
- **Reversed** (tiles better): the mirror rule.
- **Equivalent**: both primary differences have intervals inside (−0.10, 0.10).
- **Inconclusive**: anything else.

**C2. Size.** Within each unit type (subbasins pooled over levels; tiles pooled over levels), in catchments whose catchment unit routes seasonal in this study, the share of units routed seasonal per water-pixel bin and per area bin. The **minimum recommended size** is the lower edge of the smallest bin such that it and every larger bin with at least 5 units have a seasonal share ≥ 0.80. Computed for subbasins, and for tiles if C1 is not Supported. No bin qualifying means no minimum is recommended.

**C3. Timing asynchrony inside seasonal catchments.** Among `hb7` units routed seasonal in catchments whose catchment unit routes seasonal, the share whose climatological trough month differs from the catchment's by more than 1 month (circular distance), and the same for the peak. A share ≥ 0.25 for either means the catchment's timing does not represent a material share of its subbasins.

**C4. Seasonality hidden by aggregation.** Among `hb7` units in catchments whose catchment unit does not route seasonal, the share routed seasonal. A share ≥ 0.25 means an aseasonal catchment can contain seasonal subbasins.

## Advice each result maps to

| Result | Advice for the library documentation |
| --- | --- |
| C1 Supported | Prefer hydrologically defined units (catchments, subbasins) to grid tiles of the same size. |
| C1 Equivalent | The unit's size matters more than whether it follows drainage; tiles are acceptable above the minimum size. |
| C1 Reversed | Report as found; no advice to prefer subbasins. |
| C1 Inconclusive | No advice on unit type; say the evidence does not separate them. |
| C2 minimum found | State the minimum (in water pixels, with the area equivalent) below which seasonal routing is unreliable. |
| C3 ≥ 0.25 | Catchment-scale timing can misrepresent its subbasins; report subbasin results alongside the catchment. |
| C4 ≥ 0.25 | An aseasonal catchment can contain seasonal subbasins; check subbasins before concluding there is no season. |

The thresholds (0.10, 0.80, 0.25, 5 units) are judgement calls fixed here, not derived from data.

## Limits stated in advance

- Five catchments, one period, one product. Results describe these landscapes; the advice is phrased as conditions to check, not universal rules.
- HydroBASINS is derived from 15 arc-second (about 450 m) terrain data, so its divides are coarser than the 30 m pixels.
- One tile origin is used. A different origin would move individual tiles, but not the size-matched comparison as a whole.
- Conditioning `confirmed_share` on routed-seasonal units compares only units that already pass the regime gate.
