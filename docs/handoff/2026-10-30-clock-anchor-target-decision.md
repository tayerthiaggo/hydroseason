# Clock-anchor target decision record

Status: **awaiting lead**. Date opened: 2026-10-30. Decided: ____ (date, name).

Basis: [independent verdict](2026-10-30-clock-anchor-independent-verdict.md) §9 and §10. Stage 0 (frozen rise-rule synchrony test) and stage A (input repair attribution) run without this record. Target-dependent choices in stages B and C require the lead's decision.

## 1. Scientific target of the end-of-dry reading

Choose one, or name several products explicitly.

| Option | Definition | What the end-dry date means | Consequence |
| --- | --- | --- | --- |
| T1 minimum availability | Lowest supported extent in the post-peak window; may be an interval | Aggregate only; circular per pool | y is read at the band end as today; `start_date` and X unchanged |
| T2 pre-replenishment state | Occupancy in the last month of the supported low state (month before `rise_date`) | Needs a rise rule with status and interval; uncertainty `[L-1, U-1]` | HydroSeason additive fields (§9 contract); hydropools endpoint policy; refit |
| T3 continuous survival | No supported drying between recession start and replenishment | Interval-censored trajectory, not a date | New product; `pool_years.csv` drying fields are the starting point |

Decision: ____

## 2. Years without a sustained rise (failed wet season)

| Option | Effect |
| --- | --- |
| Censor into the next rise | One window spanning two years; one reading in the far tail of X; `refuge_2yr` and carry-over A partly redundant |
| One row per year, interim reading at the last observed low month, flagged `season_not_ended` | Keeps one reading per year; flag must propagate to identity, X, refuges |

Decision: ____

## 3. Hydropools and HydroSeason's own gates

Today hydropools consumes every cycle regardless of `boundary_status` (provisional in 1,257 of 1,558 tile-years), `status` (partial in 1,269) and `confidence` (low in 840); only `trough_timing_status` and date presence are consulted.

| Option | Effect |
| --- | --- |
| Keep ignoring the gates | No change; quality discarded before the anchor question |
| Honour `boundary_status == confirmed` | 301 tile-years keep a local clock; the rest need the donor policy below |
| Honour a named subset (state which columns and values) | ____ |

Decision: ____

## 4. Donor policy for tile-years without a local clock (rule (c))

Needed whatever the anchor: pixel counts will route tiles 05, 13, 18 and probably 46 out of per-year detection (verdict finding 10; 151 tile-years), and 135 windows already fall to `hy_boundary`.

Required fields in any implementation: `endpoint_source ∈ {local, donor_median, catchment}`, donor tile IDs, donor spread in months, year alignment, `endpoint_status`. No silent replacement of an unknown local date by a neighbour's.

Decision on donor set (network neighbours via AHGF up/downstream, then catchment; or other): ____
Decision on minimum donors and maximum spread before abstaining: ____

## 5. Referee for the chosen target

| Target | Admissible referee |
| --- | --- |
| T2 on gauge-connected reaches | First flow after a zero-flow spell at 802003, 802006, 802007, 802008, 802055, under a protocol written and hashed before any discharge file is opened for this purpose |
| Extent change anywhere | Independent imagery or field observation, blinded labels, "not identifiable" allowed |
| T3 | Drying and rewetting evidence per pool |

Decision: ____

## 6. Holdout

Jul–Dec 2026 counts as a holdout only with (a) a statement of what 2026 imagery has been viewed through any channel (DEA services, TSFill, Planet) and by whom, and (b) a hashed, frozen rule. The local WOfS cache ends 2026-06.

Statement: ____
