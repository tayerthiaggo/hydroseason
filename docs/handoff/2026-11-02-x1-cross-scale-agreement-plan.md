# X1: cross-scale agreement of HydroSeason dates (pre-registered)

Date: 2026-11-02. Branch `spatial-unit-study`. Written before any per-year date of any unit was computed. The SHA-256 of this file is recorded in the run receipt before the analysis stage; later edits are reported as deviations.

Background: decision X1 in [2026-11-02-decisions-units-dates-hydropools.md](2026-11-02-decisions-units-dates-hydropools.md). The spatial unit study compared routing and typical (climatological) timing. This step compares the dates themselves, year by year. It uses only the water extent; no gauge enters.

## Question

When HydroSeason runs on an area and on the areas inside it, how often do the inner areas' dates for a year agree with the outer area's? How does that depend on the inner area's size? Do peaks and trough boundaries differ in how widely they are shared?

## Units and series

These are the series built in the spatial unit study (receipt `2026-11-02-spatial-unit-study-receipt.json`):
- the five catchment units;
- HydroBASINS level-6, level-7 and level-8 units.

Grid tiles are left out: the study found them equivalent to subbasins of the same size, and they do not nest. Each series is analysed exactly as in that study, with `analyze_catchment(extent, phase_scheme="two_phase", quality_policy="flag")`, and the hydrological-years table is kept.

**Pairs.** Each subbasin is paired with two containing areas:
- its **parent**: the subbasin one level up whose Pfafstetter code is its own minus the last digit (level 6's parent is the catchment);
- its **catchment**.

A unit whose parent was not kept in the study (fewer than 3% of units) is compared with its catchment only.

## Matching cycles

Both units of a pair must route to `per_year_detection`. Each inner-area cycle is matched to the outer-area cycle whose operational peak (`peak_month`) is closest, if that is within 6 months. Each outer cycle is used at most once, closest first. Unmatched inner cycles count towards a reported match rate and not towards agreement.

## Outcomes

For each matched pair of cycles:
- **Peak agreement:** |inner `peak_month` − outer `peak_month`| ≤ 1 month.
- **Trough agreement:** |inner `trough_month` − outer `trough_month`| ≤ 1 month. `trough_month` is the operational boundary exported as `trough_boundary_date`; `start_date` is that plus one month, so it agrees exactly when the boundary does.

Shares are reported by:
- relation (parent, catchment);
- inner unit level;
- the inner unit's median monthly water pixels, in the study's bins: [0, 100), [100, 1,000), [1,000, 10,000), [10,000, 100,000), [100,000, ∞).

Uncertainty: 2,000 bootstrap draws (seed 0), resampling inner units with replacement within each catchment; 95% percentile intervals. A secondary table repeats the agreement shares using only cycles whose timing status is `point` in both units.

## Decision rules

**R1. Where a catchment's dates represent its parts.** For each date (peak, trough) and relation, find the smallest water-pixel bin such that it and every larger bin with at least 30 matched cycles reach an agreement share of at least 0.80. That bin's lower edge is the size above which a containing area's dates stand in for the areas inside it. If no bin qualifies, no such size is stated.

**R2. Peaks versus troughs.** Pooled agreement with the catchment, peak minus trough.
- **Peaks more widely shared:** difference ≥ 0.10, interval lower bound > 0, and the same sign in at least 3 of the 5 catchments that contribute pairs.
- **Troughs more widely shared:** the mirror rule.
- **Similar:** the interval lies inside ±0.10.
- **Inconclusive:** anything else.

**R3. Parent versus catchment.** Agreement with the parent minus agreement with the catchment, pooled over inner units that have both. Stated if the interval excludes 0.

## What each result means for the advice

| Result | Advice |
| --- | --- |
| R1 size found | Above that size, one run of a containing area can stand in for the places inside it for that date; below it, run the places themselves. |
| R1 no size | Run the area the question is about; do not borrow a larger area's dates. |
| R2 peaks more widely shared | A larger area's peak dates transfer to its parts more safely than its trough dates. |
| R2 similar | The same caution applies to both dates. |
| R3 parent closer | Borrow dates from the nearest containing subbasin, not the whole catchment. |

The thresholds (0.80, 30 cycles, 6-month matching window, 0.10, 3 catchments) are judgement calls fixed here, not derived from data.

## Limits stated in advance

- Five catchments, 2005–2025, one product, one composite rule (the cube's per-scene majority; see the spatial unit study).
- Agreement is not correctness: two areas can agree and both be off. This step only asks when one area's dates can stand in for another's.
- Lachlan and Moonie catchments route aseasonal, so they contribute no catchment-relation pairs, only parent pairs where both subbasins are seasonal.
