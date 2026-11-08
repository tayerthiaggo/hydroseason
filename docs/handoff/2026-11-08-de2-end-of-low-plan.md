# DE2: the year boundary at the end of the low, against known truth (pre-registration draft)

Status: draft for the project lead's approval (2026-11-08). Nothing is frozen and no known-truth record has been run. Exploration code: `scripts/refinement_eol_explore.py`, `scripts/refinement_eol_anchor_probe.py`, branch `research/refinement-end-of-low`.

## Why

HydroSeason's definition (Methods section 4): the year boundary marks the final month of the supported low state before sustained recovery, the end of the dry season. The lead confirmed (2026-11-08) that this is the definition everywhere. On the ephemeral Fitzroy tiles hydropools uses, the boundary misses it: in 727 of 1,600 production tile-years the dry run (`dry_run_end_month`, DE1 change A, in 0.3.0) ends after the boundary, by three months or more in 251. On tile 05 the boundary sits in June in most years and the dry season ends in January.

## What the exploration found (real records, no truth)

**Why the boundary misses** (`scripts/refinement_eol_explore.py`, the 251 tile-years three or more months early):

| Cause | Tile-years |
| --- | ---: |
| The pass-2 refinement never ran: a neighbouring peak is unresolved or missing | 131 |
| The refinement held back (cloud or peak sensitivity, gaps, span not evaluable) | 76 |
| The refinement found the month (equal to the dry-run end in 61 of 71 late years) and was rolled back | 37 |
| The refinement was applied and stops one or two months earlier | 7 |

**Two fixes inside the refinement do not help** (C1: visit boundaries last to first; C2: let a peak with a known month but an unresolved label bound the refinement span). Together they moved 19 of 1,600 boundaries. A move is refused whenever a neighbouring boundary cannot move, because the year between them becomes a short stub (February to June); this is the same failure that withdrew DE1's change B.

**The cause is upstream: the search anchor.** Every year's search is centred on one month, the month with the lowest mean extent. On a flat-bottomed record every dry month averages near zero and the lowest is the first of them (June on tile 05, August on tile 13), months before the dry season ends. The search window (three, at most five, months either side) cannot reach the end, and ties break toward the anchor.

**The candidate below, on the tiles** (`scripts/refinement_eol_anchor_probe.py` and the explore script):

| | v0.3.0 | Candidate |
| --- | ---: | ---: |
| Tile-years three or more months early | 251 | 104 |
| Tile 05 / 13 / 54 / 46 | 33 / 35 / 34 / 32 | 10 / 16 / 13 / 10 |
| Tiles routed to event characterisation | 0 | 0 |
| Boundaries moved (343 of 347 later) | | 347 |
| Peaks changed | | 78 |
| Years with unresolved timing | 408 | 533 |
| Reviewed Gilbert and Fitzroy trough gates | pass | pass, every boundary identical |
| Case studies (Daly, Fitzroy, Gilbert, 4 resolutions) | | 248 of 252 boundaries identical (4 differ, Fitzroy 300 m); 39 trough labels change (R2) |

Without the label rule (R2 below), tile 13 drops to event characterisation: a flat zero run leaves the trough label unresolved, and fewer than seven dated trough cycles remain. The 129 newly unresolved years are trough labels where the boundary lands one month short of the end of its run, so R2 does not apply; this is a cost the test weighs.

## The candidate

Two rules, both in the method manifest under a new rule id; everything else is v0.3.0.

- **R1. Anchor at the end of the typical low.** The trough search is centred on the last month of the climatological low: starting from today's anchor (the month of lowest mean monthly extent), follow the following months while their mean extent stays within a tenth of the climatological range of the minimum, and take the last. When the next month already rises above that, the anchor is unchanged. On a V-shaped season it is the lowest month or the one after.
- **R2. A boundary at the end of a flat low is dated by where the low ends.** When a boundary is the last month of its dry run (DE1's run, as reported in `dry_run_end_month`), the run is longer than one month, the re-wetting month was observed (`dry_end_status` `interval`) and the trough label is `broad` or `unresolved`, the label becomes `interval` from the run end to the month before re-wetting. It is never `point` (DE1 rule 3). This is the grading by end status the lead chose for DE1's change B.

## Records

As DE1, with fresh seeds (no overlap with G2, L1, L2/R1, B2 or DE1):

- arm S (synthetic, G2's generator): 1,200 `ephemeral` (DE1's generator), 400 `pulse`, 400 `sine`; seeds 310000–311999;
- arm I (injection into real G1 backgrounds): 1,148 records, slots as DE1; seeds 315000–316147;
- pilot: 200 + 80 records, seeds 318000–318199 and 319000–319079.

Each record is analysed twice: by the current library (`method-v0.3.0`, fingerprint `aba922a9…`) and by the candidate (fingerprint recorded at the freeze).

## Scoring

One score per true dry-season end, so a library cannot gain by reporting fewer boundaries.

- **True ends.** `ephemeral`: the month before each true wet-season onset inside the record. `sine` and `pulse`: G2's boundary truth for each year.
- **Hit.** A reported boundary (`trough_month`) within one month of the true end (G2's `truth_error` for `sine` and `pulse`). A record routed to event characterisation has no boundaries; its true ends are misses.
- **Share.** Hits over true ends, per library; differences candidate minus current with 95% bootstrap intervals over records (2,000 draws).

## Decision rules

1. **The boundary dates the end of the dry season better on ephemeral seasons:** lower bound above 0, in each arm.
2. **No worse on smooth seasons:** `sine`, lower bound at least −0.05, in each arm.
3. **No worse on pulse seasons:** `pulse`, lower bound at least −0.05, in each arm.
4. **The reviewed gates pass:** the Gilbert and Fitzroy reviewed-trough tests pass under the candidate.

## Reading, fixed in advance

- **All four hold:** R1 and R2 go to the implementation checks (case studies, Fitzroy tiles, real-record rerun, docs, full suite) and then to the lead for `hydroseason-v0.3.0`.
- **Rule 1 fails in either arm, or rule 2, 3 or 4 fails:** no change. The reported dry run (change A) stays.
- **Anything else:** inconclusive, no change.

## Reported, not used to decide

- The share of cycles with dated timing (`point`, `interval`, `broad`), current against candidate, and the share of seasonal records routed to per-year detection.
- R2 labels: how often the true end lies outside the label's interval by more than one month.
- `point` trough labels: share more than a month from the truth, both libraries.
- Peaks that change, and boundary moves by size.
- By ratio band, area, mid-dry pulse and missing wet season, as DE1.
- Real records: the Fitzroy tiles (late years, routes, unresolved years), the five case studies, and end-of-dry agreement between G1 pixel halves.

## Checks before the freeze

1. Generator identity: `pulse` and `sine` equal G2's output for 20 seeds; `ephemeral` equals DE1's for 20 seeds.
2. Construction: on noise-free, cloud-free `ephemeral` records the candidate's boundary equals the true end of the dry season in every wet year.
3. Pilot, once: run times, record counts and routes only; no accuracy.
4. Freeze receipt: SHA-256 of this plan and the scripts, both library fingerprints, seed ranges and the corpus digest.

Two library runs per record: about twice DE1's 2.5 hours.

## Limits stated in advance

- The `ephemeral` generator was designed after seeing Fitzroy tiles 05 and 13 (as DE1).
- R1's tenth of the range and R2's conditions were chosen while exploring the tiles; the test is on fresh records.
- Not accuracy for real places, and not referenced to gauges.

## Choices for the lead

1. **The candidate is R1 + R2** (recommended). C1 and C2 are dropped: they moved 19 boundaries. A third option, breaking pass-1 ties toward the last month of a run of zero-extent months, was not explored.
2. **Score per true dry-season end, with unrouted records as misses** (recommended), rather than DE1's per-pair share, because R1 can change routes and peaks.
3. **Margins −0.05** for rules 2 and 3, as DE1 and B2.
4. **`pulse` decides** (rule 3), unlike DE1 where it was reported, because R1 moves the anchor on every record.
5. **Sizes and generators as DE1**, fresh seeds.
6. **Where R2 applies.** As drafted it applies to any flat low within the boundary's tolerance, so it also relabels ordinary rivers (39 trough labels on the case studies, mostly `broad` to `interval`). The alternative restricts it to lows at zero extent (at or below the measurement floor), which touches only channels that actually dry out. Recommended: restrict it to zero-extent lows, the case that motivated it.
