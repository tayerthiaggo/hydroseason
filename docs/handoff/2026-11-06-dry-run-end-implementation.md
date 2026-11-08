# Dry-season end in hydroseason-v0.3.0: implementation and checks

Date: 2026-11-06. Branch `method-v0.3.0`. Follows [DE1](2026-11-05-de1-dry-run-end-results.md), whose reading sent A and B to implementation and the implementation checks. The lead decided (2026-11-05) that approved changes join the pending release, so this is part of `hydroseason-v0.3.0`, not a new version. The method fingerprint becomes `aba922a9eac29cea8498a30794110c80de340b0f6a2fb76d64f60f93855aeb66`.

## Outcome

**A ships; B was implemented, failed its checks and is withdrawn. The lead confirmed A only on 2026-11-08.** Every cycle now reports where its dry season ends. The boundary, and so the hydrological year, does not move.

| Change | Result |
| --- | --- |
| A. Report the dry run | Shipped. Five new columns; every existing column identical on the case studies and the Fitzroy tiles; full suite passes |
| B. Move a tied boundary to the end of its run | Withdrawn. It failed two checks (below). Code and evidence kept on branch `research/dry-run-end-b` (commit `60e627c`) for a redesign |

## A: what ships

`analysis.hydro_years` gains `dry_run_start_month`, `dry_run_end_month`, `rewetting_month`, `dry_run_months` and `dry_end_status`; the hydro-years CSV gains `dry_run_start_date`, `dry_run_end_date`, `rewetting_date`, `dry_run_months` and `dry_end_status`. The run is DE1's candidate, unchanged (`hydroseason/_dry_run.py`), with one addition that DE1's extras asked for: the run cannot pass a reported peak of the next cycle whose month is too cloudy to be observed (208 of 25,936 DE1 pairs ran through such a peak). `dry_end_status` is `interval` or `censored`, never `point` (DE1 rule 3). The rule is in the method manifest as `dry_season_end` (`report_dry_run`, version 1, boundary unchanged).

### Checks

Script [`scripts/dry_run_end_checks.py`](../../scripts/dry_run_end_checks.py); output [2026-11-06-dry-run-end-implementation-checks.json](2026-11-06-dry-run-end-implementation-checks.json). "Before" is the stored `hydroseason-v0.3.0` runs (fingerprint `4d11d348…`), made by the same library code as the commit DE1 ran on.

- **Five case studies, 4 resolutions each:** every existing column of the hydro-years, monthly-phase and report tables is identical in all 20 series. The hydro-years tables add the five columns; nothing else differs. No dry end is `point`.
- **Fitzroy tiles, both input sets (81 series):** every existing column of the hydro-years, monthly, wet-event and low-spell tables is identical.
- **Regression gates:** the reviewed Fitzroy and Gilbert trough gates pass, as before.
- **Full test suite:** passes (see the commit).

### Where the run end lies against the boundary

| | Cycles | Run end after the boundary | By 3+ months | By 6+ months |
| --- | ---: | ---: | ---: | ---: |
| Fitzroy tiles, production inputs | 1,564 | 727 (46%) | 251 (16%) | 113 (7%) |
| Fitzroy tiles, count inputs | 1,602 | 794 (50%) | 269 (17%) | 133 (8%) |
| Case studies (12 per-year series) | 252 | 71 (28%) | 6 (2%) | 0 |

On tile 05 the boundary sits in June most years; the run end now gives the end of the dry season, for example 2015: boundary June 2015, dry run ending January 2016, water back in February 2016. Long runs (more than a year) are years with no wet season, where the dry season genuinely continues.

**For hydropools:** read `dry_run_end_date` as the end-of-dry clock, and `dry_end_status` for how sure it is. `trough_boundary_date` stays the cycle boundary.

## B: why it was withdrawn

B moved each boundary to its run end and rebuilt the two cycles sharing it, keeping a move only if neither cycle's peak month changed and neither lost its coverage (evidence: [2026-11-06-dry-run-end-b-checks.json](2026-11-06-dry-run-end-b-checks.json)).

1. **It missed the target.** On Fitzroy tile 05 one boundary of 40 moved, on tile 13 eight. When every boundary of a record sits months before its run end, moving one leaves the following cycle too short (for example February to June) until the next boundary moves too; checked one boundary at a time, the moves roll back along the record from its last year. Over the production tiles 586 of 1,600 boundaries moved.
2. **It moved boundaries on ordinary rivers.** The run takes in every month within the boundary's tolerance (up to a tenth of the amplitude), which on a slowly rising river includes the months just after the minimum. On the reviewed Gilbert fixture 7 of 11 boundaries moved by one or two months away from the reviewed lowest month, and the gate failed (within one month 0.36 against 0.80; median error 9 months after interval alignment). On the reviewed Fitzroy fixture two boundaries moved by one month and the gate failed through alignment (p90 12 months). The five case studies moved 4 to 8 of 21 boundaries each, mostly by one month.

The plan's checks exist to catch this. DE1's rule 2 tested smooth synthetic seasons scored within one month either way; the reviewed fixtures define the boundary as the lowest month, and B changes that definition on every river, not only on flat bottoms.

**A redesign would need:** moves decided for the whole record at once rather than one boundary at a time, and a run that stops at a real rise rather than at a tenth of the amplitude on non-flat troughs, each tested against known truth and the reviewed fixtures before adoption.

## Deviations

- From the DE1 plan: B is not adopted although DE1's rules held, because it failed the plan's own implementation checks; A ships as the plan allowed for a reported column. The lead approved A + B on 2026-11-05 and confirmed A only on 2026-11-08, after these checks.
- From DE1's candidate: the run stops at an unobserved reported peak of the next cycle (found by DE1's extras; at most 0.8% of DE1's pairs).
- No real-record rerun: A changes no existing column, which the case studies, the tiles and the full suite show. DE1's real-record stage already reports the run ends on the G1 windows and spatial-unit units.

## Still open

- Noise ending runs early (DE1's main remaining error).
- Ephemeral records routed to event characterisation (58–68% in DE1).
- A redesigned B is not planned: the lead chose A only. The design notes above stand if the hydrological year itself should ever start at re-wetting.
