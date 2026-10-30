# The dry-season clock: tile, trough and rise (analysis, 2026-10-30)

For the project lead and the HydroSeason session that will define the wet-season rise. Discussion B of
[2026-10-29-decisions-and-open-questions.md](2026-10-29-decisions-and-open-questions.md), continued. Nothing in the
pipeline or the outputs changed. Every number here is post-hoc and read-only, from `outputs/rerun/fitzroy`,
`work/rerun/fitzroy` and the HydroSeason source at `D:/RLH/5.6/repos/hydroseason`. No test was pre-registered or run.

## 1. Where the discussion stands

- **Region rule, provisional (lead, 2026-10-30):** option (c). A tile keeps its own clock where HydroSeason can
  identify the event; otherwise it takes the same-year median of the identifiable neighbours along the channel network
  (AHGF up- and downstream), and the catchment clock after that. One stated rule, replacing D8's pixel threshold and the
  silent basis chain (`point` → `interval_end` → `hy_boundary`). Not final: the lead first wants the unit question
  explored (section 4).
- **Open (Q2):** locate the end of the dry season from the minimum (the trough point, now) or from the rise edge of the
  trough band (the last bottom month before the sustained rise). Same event, two estimators (section 5). Recommendation
  below: the rise edge. The lead is taking this to HydroSeason before deciding.
- Discussions C (floodplain clock) and A (identity) wait on B.

## 2. What hydropools asks of HydroSeason today

`src/hydropools/seasons.py`:

- `extent_series` writes a monthly CSV with `date`, `extent_pct`, `invalid_pct` only. **No `n_valid`, no `n_water`.**
  HydroSeason's monthly preflight accepts `n_water`, `n_valid`, `n_invalid`, `n_aoi`
  (`hydroseason/_preflight_monthly_input.py`, `_COUNT_COLUMNS`), so this is a hydropools-side omission.
- `run_hydroseason(csv, output_dir, aoi_name)` in the HydroSeason venv; hydropools reads the hydro-years CSV.
- Columns consumed: `hy_year`, `start_date`, `mid_dry_date`, `trough_date`, `trough_interval_end_date`,
  `trough_boundary_date`, `trough_timing_status`; `peak_date` (drying table start); `peak_extent_pct`,
  `peak_invalid_pct` (floodplain wet size M); `start_date` again as the "wet onset" of the severity X and the carry-over.
- `dry_windows`: end-dry = `trough_date` if `trough_timing_status == "point"`, else `trough_interval_end_date`, else
  `trough_boundary_date`; then the re-wet guard (`rewet_ratio` 1.5, `rewet_min_obs` 0.8, `rewet_min_pp` 0.01) steps the
  end back to the driest well-observed month if the end month is wetter. The guard fired in 8 of 1,544 windows.
- **`start_date` is the previous trough** (or the boundary), not a rise. Months of `start_date` over 1,558 tile-years:
  Oct 214, Nov 409, Dec 376, Jan 274 (boundary fallbacks), the rest scattered. So "E − P from the wet onset to end-dry"
  is in fact trough-to-trough.

What depends on end-dry (from the 2026-10-29 handoff, §3.2): identity window, X, era-dry years, y, refuges, the drying
table, extents, and the floodplain lags, K and hydroperiod censoring.

## 3. Why the trough fails: three findings

### 3.1 The detectability floor collapses without pixel counts

HydroSeason's floor is `max(measurement_tolerance, robust noise, 100 / n_valid at the peak, 100 / n_valid at the trough,
machine epsilon)` (`_timing_identifiability.annual_detectability`). `_resolution_pp` returns 0 when `n_valid` is absent;
`_peak_water_pixels` returns `None` when `n_water` is absent, so the "≥ 5 wet pixels at the peak" rule is skipped
(`pixel_support_status == "unavailable"`). On the hydropools runs the floor came out at machine epsilon
(2.2e-16) wherever the robust noise was 0, i.e. on series that are 0 in most months. The calibrated gate
(`min_amplitude_to_floor_ratio` 3.0, `min_peak_water_pixels` 5; `_scientific_defaults.py`) never had a chance to say
"unresolved". Open question for the HydroSeason session: `measurement_tolerance_pct` defaults to 1.0 in
`DynamicHydroYearConfig`, yet the observed floor is epsilon, so the tolerance was 0 on this path. Why?

Examples (`work/rerun/fitzroy/hydroseason/<tile>/*_hydro_years.csv`):

| tile | channel px | floor (pp) | amplitude / floor | what HydroSeason returns |
|---|---|---|---|---|
| 05 | 971 | 2.2e-16 | 3e15–1e16 | `interval` trough ending June every year, on peaks of 1–3 % |
| 46 | 2,764 | 2.2e-16 | 2e14–2e16 | `broad`/`interval` ending Aug, peaks 0.04–4 % |
| 13 | 73 | 2.2e-16 | 0 or 1e16 | zeros most years → `unresolved`, boundary ends |
| 11 | 16,104 | 4.02 (noise) | 4–12 | `point` troughs Jul–Sep with 8–13 % still wet: a real early trough |

So D8 (tiles with too few pixels) is mostly this input gap, not tile size. Tile 11 is a different case: a genuine
mid-year minimum that a gauge, not a threshold, has to judge.

Across the 1,545 tile-years that carry windows (`clock_quality.py`):

| HydroSeason field | n | end in Jan–Aug | ≥ 3 months off the catchment median |
|---|---|---|---|
| no amplitude (ratio NaN) | 80 | 82.5 % | 82.5 % |
| ratio 1–2 | 26 | 23 % | 27 % |
| ratio 2–5 | 102 | 16 % | 12 % |
| ratio 5–10 | 332 | 11 % | 6 % |
| ratio > 10 | 913 | 6.5 % | 3.6 % |
| trough `unresolved` | 264 | 39 % | 33 % |
| trough `point` | 352 | 14 % | 8 % |
| trough `broad` / `interval` | 477 / 452 | 12 % / 13 % | 9 % / 12 % |

Two sources of Jan–Aug ends: no signal (fixable by the floor) and real early troughs (6–14 % even where the ratio is
> 10). A catchment median would bury both.

### 3.2 What is at stake, in pool-years (`stake.py`)

| tile-years where | pool-years | pools touched | refuges touched | wet share of y |
|---|---|---|---|---|
| no amplitude | 86 (0.3 %) | 42 | 13 | 0.09 |
| trough `unresolved` | 1,533 (5.8 %) | 587 | 143 | 0.25 |
| end in Jan–Aug | 1,630 (6.1 %) | 628 | 164 | 0.31 |
| ≥ 3 months off the catchment median | 454 (1.7 %) | 260 | 69 | 0.41 |
| all | 26,644 | 709 | 179 | 0.41 |

The tiny tiles hold 1 pool. The `unresolved` years in big tiles are where B bites: tile 21 alone has 280 pool-years
(40 pools, 91 refuge pool-years), then tiles 38, 27, 35, 15. Those years score dry (0.25 vs 0.41), so they are the era-dry
years that decide identity and refuges. Any borrowed date lands exactly there. The cause of `unresolved` in big tiles is
not diagnosed (flat high trough in wet years? the 1-SE rule?).

### 3.3 The peak is synchronous; the trough is not (`sync.py`)

Channel series, 1,558 tile-years; "big" = tiles with ≥ 3,000 channel px; deviation from the pixel-weighted catchment
median of that year, `point` events only:

| event | HydroSeason `point` | big tiles within ±1 month | ≥ 3 months off | tiles per year with a point |
|---|---|---|---|---|
| wet peak | 1,213 (78 %) | 93.1 % | 1.4 % | 26 |
| trough | 352 (23 %) | 84.8 % | 5.9 % | 7.5 |
| end-dry as run (all bases) | — | 83.2 % | 3.3 % | 41 |

Peak months: Jan 201, Feb 476, Mar 428, Apr 66, Dec 26, others ≤ 10. Only two of 38 years have fewer than 70 % of the
big tiles agreeing on the peak within ±1 month (1989, 1999). Floods synchronise a catchment in days; drying does not.

### 3.4 y is soft inside the window and a cliff past it

From the 2026-10-29 post-hoc check (`clock_check.py`) and `ymin.py` on `pool_months.csv` (26,633 pool-years, window
mid-dry to end-dry, median 5 observed months):

| y read at | changes vs end-dry | wet → dry | dry → wet |
|---|---|---|---|
| end-dry − 1 month | 19.4 % | 588 | 4,301 |
| end-dry + 1 month | 32.6 % | 759 | 6,764 |
| catchment-median month | 8.9 % | 545 | 1,681 |
| "no observed dry month anywhere in the window" | 4.0 % | 1,055 | 0 |

- Wet share: 0.422 at end-dry, 0.382 under the no-dry-month rule. The gap is 0.040 / 0.046 / 0.033 across the eras
  1988–99 / 2000–12 / 2013–25 while observed months per window rise 4.65 → 4.98 → 5.30, so a within-window minimum is not
  observation-density biased at these window lengths.
- Dry then wet again inside the window, both observed: 9.2 % of pool-years (dry-season storms, or a month in which the
  few wet pixels were missed).
- The month after end-dry flips 33 %, nearly all dry → wet. That is the rise.

Reading: the exact trough month barely matters (4 %). Crossing the rise matters (33 %). The clock's one job is to not
cross the onset.

## 4. Is the tile the flaw?

No. The anchor is. The current method anchors on the weakest, least synchronous event of an extent series (a flat
bottom at the noise floor, reached upstream before downstream), patches crossings with the re-wet guard, and falls
through `interval_end` → `hy_boundary` when the bottom is flat. The unit question exists because the trough is
asynchronous. Anchor on the rise and tiles, catchment and reaches agree within a month in 93 % of cases.

Units compared:

- **Catchment.** Fine for a rise anchor; poor for a trough anchor. Pixel-weighted, 86 % of tile-years already sit within
  ±1 month of the catchment median end; locality buys about a month.
- **Network reaches or sub-basins** (AHGF here; HydroBASINS or MERIT-Basins elsewhere). The hydrological unit and
  transferable. Sizes vary, small ones have no signal, so an aggregation rule returns. A big change for a month of gain.
- **Tiles.** Processing boxes, wall-to-wall, already computed. The seam problem is HydroChannel's channel-polygon jump
  (5–7 of 46 edges) and exists under any clock.
- **Per pool.** Circular for a trough (y at the pool's own minimum is always the minimum). Undefined for a rise: refuges
  stay full and never show one. The rise must come from an aggregate.

The TSFill phase rule (`WaterMask-TSFill/experiments/gapfill/scene_phase.py`, 2026-10-30: dry end = driest 30.5-day bin
plus the bin before, from a 12-bin day-of-year climatology smoothed over 3 bins) is a climatology for stratifying
gap-fill accuracy: one month per window, the same every year. TSFill's own HydroSeason fallback is the calendar month of
lowest mean extent, which its feedback note calls "crude: an arithmetic mean over a heavy-tailed series, and no
uncertainty" (`WaterMask-TSFill/docs/next_steps/hydroseason-feedback-2026-10-30.md`). Neither is a per-year clock, and
on a zero series the driest bin is a tie. The same note found a rank transform resolved 17 of 24 failing windows; that
is a HydroSeason-side lead worth carrying into the same session.

## 5. The rise as the anchor: what it would mean

**Same event, two estimators.** In a clean series the trough is the month before the rise, and the two coincide. They
part in exactly the failing cases. The minimum is the weak edge: on a flat bottom it is a tie broken by noise, a
dry-season blip pulls it early, and it is reached upstream before downstream. The rise is the strong edge: a large,
sustained change, synchronous across the catchment. So the proposal is not a new event. It is to locate the same date
from the rise side.

**HydroSeason already has the rise-side estimator, half-hidden.** `_timing_identifiability.py` searches the trough after
the peak and takes every month within the floor of the minimum (`equivalent_extremum_dates`, non-contiguous, so a bump
inside the band does not break it). `trough_interval_end` is the last of those months: the last bottom month before
the series leaves the band for good, i.e. the month before the rise. Two things stop hydropools from using it:

1. The floor is machine epsilon on these runs (section 3.1), so the band is "exactly the minimum" and its end is noise.
2. Status comes from the band's span (`point` 0 months, `interval` ≤ 2, `broad` ≤ `max_broad_interval_months`, else
   `unresolved`), and an `unresolved` band is narrowed to the most recent recurrence window
   (`narrow_most_recent_recurrence`), which can cut the rise edge off. A long flat bottom is exactly the case where
   the minimum cannot be localised but the rise edge is sharp. "Unresolved trough" conflates the two.

**Ask of the HydroSeason session, made precise.** Expose the rise edge of the bottom band with a status of its own,
judged by the size of the departure (rise amplitude against the floor) and not by the span of the bottom:
`rise_date` (first month after the band, or equivalently `trough_band_end` = the month before), `rise_timing_status`
∈ {point, interval, unresolved}, `rise_extent_pp` (the departure). Thresholds from the floor and the calibrated
identifiability defaults only. If the calibration partitions behind those defaults include the Fitzroy, say so: the
method rule is no constant tuned here.

**Both estimators, with different jobs (lead's question, 2026-10-30).** The rise edge is the date: end-dry, where y is
read. The trough point is the start of the bottom band; the band's length (months at the minimum) is a product in its
own right. Point and rise edge more than a month apart = a quality flag, and the gauge test reports agreeing and
disagreeing tile-years separately, since agreeing years are a tie by construction. Not a fallback chain: a year with no
sustained rise is a failed wet season, the dry season has not ended, and the window is censored into the next year's
rise rather than closed at the minimum (this touches `refuge_2yr` and the carry-over A, which already encode back-to-back
dry seasons). Not an average: a mid-band date means nothing. For Discussion A: "water throughout the bottom band" is the
data-defined form of the fixed identity window `end_dry_months = 3` (D2).

**No observed water goes unread (lead's concern, 2026-10-30).** Three cases. (1) A tile with no signal in its own
series: 67 of the 80 no-amplitude tile-years are tiles 18, 13, 05, 01, 46; 86 pool-years, 42 pools, 13 refuges in all.
Rule (c) borrows the rise from network neighbours, else the catchment; safe because the rise is synchronous. Read on a
borrowed date, flagged. (2) A tile with signal but a year with no sustained rise (failed wet season; rare here, 36 of
38 years have > 70 % of big tiles agreeing on a peak, but it matters for transfer): either censor into the next rise
(one long window, one reading in the far tail of X, the drought-scenario region; one row for two years; `refuge_2yr`
and A partly redundant) or keep one row per year with an interim reading at the last observed bottom month, X to that
date, flagged `season_not_ended` (any (y, X) pair informs the same logit curve). Recommendation: censor. Lead's call.
(3) Rise hidden by cloud: read y at the last observed bottom month, interval-censored, as the drying table already does.

hydropools would then set **end-dry = the month before `rise_date`**, and:

- pass `n_valid` and `n_water` (and `n_aoi`) in `extent_series` so the floor is real;
- delete the basis chain, the re-wet guard (three parameters) and D8's pixel threshold from the ledger;
- keep region rule (c), now with a synchronous event, so the fallback is nearly harmless;
- decide X's span in the ledger (rise-to-rise, i.e. the whole hydrological year up to the reading, is the natural form);
- start the drying walk and the extents walk from the month before the rise;
- give the floodplain its own peak (it already has one: `point` in 79 % of its tile-years) and no trough: its trough is
  `point` in 13 %, `unresolved` in 19 %, and its trough extent is literally 0 in 46 % of tile-years (median 0.003 %).
  Discussion C decides whether floodplain lags run to the channel rise or to the floodplain's own last water.

**Costs, stated against the proposal:**

- HydroSeason has no rise column. Adding one is a change to a frozen 0.2 contract.
- The rise sits in the cloudy months; the trough sits in the clearest. The month before the rise may be unobserved, so
  more y are censored. Fewer, more meaningful readings.
- y goes drier by construction, so refuges fall. Direction known, size not measured (needs `states.npz`, not
  `pool_months.csv`).
- Everything validated so far (V1 Oct 2019 refuges 76–80 %, T2r 89.9 %, the leave-year-out Brier) was built on the
  trough clock. A re-validation would be post-hoc: the manual Planet maps are spent as a test referee.

**Referee, sharp and already allowed.** First flow after a zero-flow spell at the Fitzroy gauges (802003, 802006,
802007, 802008, 802055; daily Q in `data/gauges/`). First flow is a cliff in a hydrograph; cease-to-flow is a smear.
Test shape, to be pre-registered in the lab notebook before anything is run: for each gauge and each year with a
zero-flow spell (the `zero_flow_days` rule: Q ≤ 0.01 m³/s for ≥ 14 days), the tile holding the gauge places
`rise_date` within ±1 month of the first-flow month in ≥ 70 % of years, pooled over gauges (E30's own bar, 2026-10-24
audit); baseline = the current end-dry + 1 month against the same event. Years in which the river flowed through are
reported separately. The 2026 wet season is a clean out-of-sample check only if the predictions are frozen before
Jul–Dec 2026 imagery is read.

## 6. Questions for the HydroSeason session

1. Can the rise edge of the trough band carry its own status, judged by the departure's size against the floor rather
   than by the band's span, so that a long flat bottom (trough `unresolved`, 264 channel tile-years; floodplain trough
   extent 0 in 46 % of tile-years) still yields an end-of-dry-season date? Does `narrow_most_recent_recurrence` need to
   leave the band's end alone?
2. Why is the floor machine epsilon on near-zero series when `measurement_tolerance_pct` defaults to 1.0?
3. Should `start_date` keep meaning "previous trough", or should a `rise_date` become the hydrological-year start for
   callers that accumulate exposure?
4. Were the Fitzroy or its tiles in the calibration partitions behind `min_amplitude_to_floor_ratio` 3.0 and
   `min_peak_water_pixels` 5?
5. TSFill's open questions (rank transform, provisional trough instead of raising, event-based phases) overlap with
   this; one answer should serve both callers.

## 7. Reproduce

All scripts are untracked, in the session scratchpads, and read only. Run from the hydropools root with `python <path>`.

- `C:\Users\00101125\AppData\Local\Temp\claude\d--RLH-5-6-repos-hydropools\4cd19c48-b06d-4fa8-9850-dca5f0a7ea55\scratchpad\b\clock_quality.py`
  (floor, ratio and status tables; writes `clock_quality.csv` beside it)
- `C:\Users\00101125\AppData\Local\Temp\claude\d--RLH-5-6-repos-hydropools\4cd19c48-b06d-4fa8-9850-dca5f0a7ea55\scratchpad\b\stake.py`
  (pool-years at stake; floodplain HydroSeason status)
- `C:\Users\00101125\AppData\Local\Temp\claude\d--RLH-5-6-repos-hydropools\4cd19c48-b06d-4fa8-9850-dca5f0a7ea55\scratchpad\b\sync.py`
  (peak vs trough synchrony)
- `C:\Users\00101125\AppData\Local\Temp\claude\d--RLH-5-6-repos-hydropools\4cd19c48-b06d-4fa8-9850-dca5f0a7ea55\scratchpad\b\ymin.py`
  (y at end-dry vs no-dry-month rule)
- `C:\Users\00101125\AppData\Local\Temp\claude\d--RLH-5-6-repos-hydropools\6178f782-30fd-4431-9911-e40fb9941b1a\scratchpad\figsrc\clock_check.py`
  (2026-10-29: ±1 month and catchment-median y flips; outputs in `..\fig\clock_check.json`, `clock_tile_years.csv`)

Inputs: `work/rerun/fitzroy/hydroseason/<tile>/*_hydro_years.csv`, `work/rerun/fitzroy/floodplain_hydroseason/<tile>/`,
`outputs/rerun/fitzroy/{pool_years,pool_months,persistence}.csv`, `configs/fitzroy.toml`.
