# Where the dry season ends on flat-bottomed records: analysis

Date: 2026-11-05. Exploratory; nothing here changes the method. Prompted by Fitzroy tiles 05 and 13, where the report ends the dry season in June (tile05) or May–August (tile13) although the channel holds no water until December–February.

## The cases

Tiles 05 and 13 are HydroChannel tiles in the Fitzroy (307 and 31 channel pixels in the counts inputs). Water appears for one to three months between December and April in most years, then none for eight to nine months. In a quarter (tile05) to a third (tile13) of years no water is detected at all. hydropools' clock-anchor analysis lists both among the tiles that fail most often.

In the hydro-years output the trough boundary falls in the same calendar month nearly every year (June in tile05; August in the production run of tile13, May in its counts run). The hydrological year is split there, so the months from July to the next wet are drawn as `rising` although no water is present, and hydropools reads that boundary as the end of the dry season.

## Mechanism

1. **The search window caps the run.** The trough is searched within ±3 months (±5 on retry) of one calendar month per record, `expected_trough_month` (`_find_robust_trough_opportunities`). On these tiles the window is March–September (tile05) or May–November (tile13). The low run (months within the boundary's tolerance of the minimum, `_select_window_extreme`) is cut at the window edge.
2. **A tie goes to the window centre.** Every month of a zero run is an equal minimum. The cross-year boundary sequence (`select_boundary_sequence`) scores candidates by their distance from the expected month, so a tied run resolves to the expected month every year (`selection_status = coherence_adjusted`).

Nothing is wrong with the minimum: the boundary is a lowest month. The choice among equal lowest months is arbitrary, and it lands at the start of the dry run rather than its end.

## How common it is

**Fitzroy tiles** (`scripts/dry_run_end_exploratory.py`; output `data_local/intermediate/hydroseason_dry_run_end/dry_run_tiles.csv`). Each cycle's low run was followed forward past the window, with the library's own frame and tolerance, to the first observed month above it.

| | Counts (41 tiles) | Production (40 tiles) |
| --- | --- | --- |
| Cycles | 1,602 | 1,564 |
| Boundary before the end of its low run | 54.4% | 53.9% |
| … by 3 months or more | 19.2% | 19.2% |
| … by 6 months or more | 8.2% | 7.4% |
| End of the low run beyond the search window | 29.4% | 30.2% |
| Low runs spanning a year or more (no wet season between) | 68 | 53 |

Where the boundary is early by 1–11 months, the boundary month is mostly September–November and the end of the dry run mostly November–January. The large gaps concentrate in tiles 13, 46, 05, 18 and 54 (median gap 5–9 months), the near-ephemeral tiles.

**Real-record runs** (v0.3.0 rerun of the real-record impact records, within the search window only, so a lower bound):

| Units | Low run at the window's right edge | Boundary before the run's end |
| --- | --- | --- |
| G1 core / quadrant windows | 30.0% / 36.6% | 41.2% / 49.6% |
| Level-8 subbasins; 22 km tiles | 27.2%; 27.2% | 34.0%; 33.6% |
| Level-6/7 subbasins; 69/41 km tiles | 3.5–14.9%; 17.1–19.4% | 13.3–22.1%; 19.9–25.3% |
| Whole catchments | 0% | 1.6% |

## Related evidence

- **R1** ([results](2026-11-03-l2-r1-results.md)): on the `pulse` shape (a sharp rise after a long low tail) the trough boundary was within a month of the true end of the dry season in 0.54 of pairs (arm S), against 0.80 for a 20%-amplitude rise. R1 failed overall because the rise lost on smooth seasons. No generator so far has an ephemeral shape: months of exact zero, a one-to-three-month wet, and years with no wet.
- **hydropools** asked for a dry-side end date with its own status (`docs/handoff/2026-11-02-hydroseason-handoff-u1-u2.md` in hydropools, section 4, item 1).
- **Literature.** Intermittent-river hydrology describes the dry period as a run of zero-flow time steps and reports its start, end and duration (Snelder et al. 2013, https://doi.org/10.5194/hess-17-2685-2013; Tramblay et al. 2020, https://doi.org/10.1080/02626667.2020.1849708; Alcaraz-Hernández et al. 2022, https://doi.org/10.1002/rra.4095), and the dry-down period from peak to zero flow (Zipper et al. 2021, https://doi.org/10.1088/1748-9326/ac14ec). Busch et al. 2020 (https://doi.org/10.3390/w12071980) separate ephemeral (water only in response to rain events) from intermittent (seasonal drying). Wasko et al. 2020 (https://doi.org/10.1029/2020WR027233) start the water year at the month of lowest mean flow, which is ambiguous when many months tie at zero.

## Options

- **A. Report the dry run.** Add per-cycle `dry_start_date`, `dry_end_date`, `dry_months` and a `dry_end_status` (whether the month after the run is observed with water). Follow the run past the search window with the existing tolerance. Boundaries do not move. The report and hydropools can read the end of the dry season directly.
- **B. Move a tied boundary to the end of its run.** When the trough is a tied run, place the boundary at the run's last month, so the hydrological year starts at re-wetting. Boundaries, year membership and monthly phases change on the affected cycles. Runs spanning a year or more (no wet season) need an explicit rule.
- **C. A separate ephemeral route.** Not needed for the dating problem; an ephemeral/intermittent descriptor (dry months per year, share of years with no wet) can be reported instead.

Any of these is a method change (a new policy version), and B needs a pre-registered known-truth test with an ephemeral generator before it is decided.
