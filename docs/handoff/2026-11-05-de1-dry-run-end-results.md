# DE1: where the dry season ends, against known truth, results

Run 2026-11-05 under the frozen plan ([plan](2026-11-05-de1-dry-run-end-plan.md), [receipt](2026-11-05-de1-dry-run-end-receipt.json)). The scorer output is [2026-11-05-de1-dry-run-end-results.json](2026-11-05-de1-dry-run-end-results.json). It cites receipt SHA-256 `94f290058e28b2a26f01ac7cb4fbc42ebf0f22a37d23c0f2c26039de7c2bd1fa` and script SHA-256 `8e591be9554aaca531289e746d70ec9e516c7a9f2773a07d3b08827a75447a2b`. The main run took 2 h 29 min (8,944 s) for 3,148 records, with no errors and one method fingerprint (`4d11d348…`, `hydroseason-v0.3.0`).

## Summary

**Rules 1 and 2 hold in both arms; rule 3 fails in both.** Under the reading fixed in advance, A (report the dry run) and B (move a tied boundary to the end of its run) go to implementation and the implementation checks, then to the lead as candidate changes for `hydroseason-v0.4.0`. Because rule 3 failed, the end status is reported as `interval` or `censored` only, never `point`.

- **Rule 1 holds: the run end dates the end of the dry season better on ephemeral seasons.** Share within one month of the truth: 0.204 → 0.396, difference +0.192 [+0.178, +0.205] in arm S (6,953 pairs, 502 records); 0.255 → 0.516, +0.260 [+0.227, +0.296] in arm I (3,617 pairs, 181 records). The floor was above 0.
- **Rule 2 holds: smooth seasons are not made worse.** On `sine`: 0.897 → 0.901, +0.004 [−0.001, +0.009] in arm S; 0.895 → 0.892, −0.003 [−0.011, +0.006] in arm I. The floor was −0.05.
- **Rule 3 fails: a `point` end is not safe.** Candidate ends with status `point` are wrong by more than a month in 4,947 of 11,488 pairs (0.431, Wilson upper 0.440) in arm S and 2,213 of 9,045 (0.245, upper 0.254) in arm I. The bound was 0.05.
- **`pulse` seasons improve too** (reported): +0.050 [+0.042, +0.058] in arm S, +0.093 [+0.073, +0.114] in arm I. Ending the run at a mid-dry pulse did not cost accuracy overall.
- **The fix roughly doubles accuracy but does not finish the job.** The candidate still dates 59.5% (arm S) and 46.9% (arm I) of ephemeral ends two or more months early, against 79.6% and 74.1% today. In most of those, a dry month a little above the tolerance ended the run (see extras): noise, not rain.
- **Most ephemeral records never reach B.** 698 of 1,200 ephemeral records in arm S and 393 of 574 in arm I route to event characterisation and have no boundaries to move. Fitzroy tiles 05 and 13 are not among them: they route to per-year detection.

## Decision rules

Intervals are 95% bootstrap intervals over records (2,000 draws). A pair is the last reported boundary before a reported, dated peak inside a true wet season; correct means within one month of the truth.

| Rule | Arm S | Arm I | Bound | Outcome |
| --- | --- | --- | --- | --- |
| 1. `ephemeral`, share correct, current → candidate | 0.204 → 0.396 (6,953 pairs, 502 records) | 0.255 → 0.516 (3,617 pairs, 181 records) | | |
| 1. Difference [95% interval] | +0.192 [+0.178, +0.205] | +0.260 [+0.227, +0.296] | lower > 0 | Holds in both |
| 2. `sine`, share correct, current → candidate | 0.897 → 0.901 (3,116 pairs, 257 records) | 0.895 → 0.892 (4,275 pairs, 158 records) | | |
| 2. Difference [95% interval] | +0.004 [−0.001, +0.009] | −0.003 [−0.011, +0.006] | lower ≥ −0.05 | Holds in both |
| 3. `point` ends not correct, all shapes | 4,947 of 11,488 (0.431), upper 0.440 | 2,213 of 9,045 (0.245), upper 0.254 | upper ≤ 0.05 | Fails in both |

**Reading, fixed in advance:** rules 1 and 2 hold in both arms, so A and B go to implementation and the implementation checks; rule 3 fails, so whatever is adopted reports the end status as `interval` or `censored` only. An end that would have been `point` is reported `interval`.

## Reported, not used to decide

### `pulse` seasons

| | Arm S | Arm I |
| --- | --- | --- |
| Share correct, current → candidate | 0.566 → 0.616 (3,167 pairs, 242 records) | 0.630 → 0.723 (4,808 pairs, 162 records) |
| Difference [95% interval] | +0.050 [+0.042, +0.058] | +0.093 [+0.073, +0.114] |

### `ephemeral` by group (share correct, current → candidate, difference [95% interval], pairs)

| Group | Arm S | Arm I |
| --- | --- | --- |
| Ratio 3–4 | 0.161 → 0.292, +0.131 [+0.098, +0.165] (329) | 0.281 → 0.522, +0.242 [+0.167, +0.315] (178) |
| Ratio 4–6 | 0.154 → 0.291, +0.136 [+0.116, +0.159] (1,187) | 0.238 → 0.464, +0.225 [+0.182, +0.275] (772) |
| Ratio 6–10 | 0.190 → 0.341, +0.152 [+0.136, +0.168] (2,311) | 0.247 → 0.498, +0.251 [+0.212, +0.296] (1,349) |
| Ratio 10 and up | 0.238 → 0.486, +0.249 [+0.228, +0.267] (3,126) | 0.270 → 0.563, +0.293 [+0.242, +0.345] (1,318) |
| Area under 100 pixels | 0.261 → 0.439, +0.178 [+0.132, +0.229] (353) | none |
| Area 100–1,000 pixels | 0.203 → 0.381, +0.178 [+0.155, +0.200] (1,869) | none |
| Area 1,000 pixels and up | 0.200 → 0.398, +0.198 [+0.182, +0.215] (4,731) | 0.255 → 0.516, +0.260 [+0.226, +0.295] (3,617) |
| Mid-dry pulse before the onset | 0.191 → 0.318, +0.127 [+0.099, +0.157] (550) | 0.277 → 0.420, +0.143 [+0.100, +0.190] (231) |
| Neither a pulse nor a missed year | 0.205 → 0.402, +0.197 [+0.183, +0.212] (6,403) | 0.254 → 0.523, +0.269 [+0.232, +0.303] (3,380) |
| Boundary a year or more early (no wet season before) | no pairs | 0 of 6 correct under both |

The gain grows with the amplitude-to-noise ratio and holds in every group. A pulse before the onset ends the run early, as chosen (choice 2), but the candidate still gains there.

### Signed errors on `ephemeral` (candidate or current date minus the truth)

| | Arm S, current | Arm S, candidate | Arm I, current | Arm I, candidate |
| --- | ---: | ---: | ---: | ---: |
| Two or more months early | 5,534 (79.6%) | 4,135 (59.5%) | 2,680 (74.1%) | 1,695 (46.9%) |
| Within one month | 1,417 (20.4%) | 2,750 (39.6%) | 923 (25.5%) | 1,865 (51.6%) |
| Exact month | 798 (11.5%) | 2,022 (29.1%) | 572 (15.8%) | 1,447 (40.0%) |
| Two or more months late | 2 (0.03%) | 68 (1.0%) | 14 (0.4%) | 57 (1.6%) |

Today's boundary is early and almost never late, as the analysis found on the Fitzroy tiles. The candidate removes a quarter (arm S) and over a third (arm I) of the early ends and adds a small late tail.

### How far the date moves

| | Arm S `ephemeral` | Arm S `pulse` | Arm S `sine` | Arm I `ephemeral` | Arm I `pulse` | Arm I `sine` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pairs whose date moves | 42.1% | 13.9% | 19.0% | 42.6% | 21.2% | 32.3% |
| By three months or more | 19.6% | 1.3% | 1.2% | 24.7% | 5.5% | 2.8% |
| By six months or more | 4.6% | 0.3% | 0.1% | 8.3% | 1.2% | 0.6% |

On `sine` most moves are one month (444 of 592 in arm S), which rule 2 shows costs nothing.

### End status

| Status | Arm S pairs, share correct | Arm I pairs, share correct |
| --- | --- | --- |
| `point` | 11,488, 0.569 | 9,045, 0.755 |
| `interval` | 1,192, 0.598 | 2,447, 0.665 |
| `censored` | 556, 0.460 | 1,208, 0.577 |

A `point` end is no more accurate than an `interval` end in arm S. The end status says whether the re-wetting month was observed right after the run, not whether the run ended at the right month.

### Coverage and peaks outside wet seasons

- True ephemeral wet seasons with a scored pair: 6,953 of 20,363 (34%) in arm S, 3,617 of 18,322 (20%) in arm I. Most of the gap is routing (extras, below).
- Pairs whose reported peak lies outside every true wet season (reported, not scored; wrong by construction): 410 pairs in 217 records in arm S, 1,235 pairs in 167 records in arm I.

### Interaction with `hydroseason-v0.3.0`: the timing of moved pairs

All shapes; one row per grading of the cycle that owns a moved boundary.

| Grading | Arm S (3,958 moved pairs) | Arm I (3,937 moved pairs) |
| --- | --- | --- |
| Today (boundary not moved) | `point` 431, `interval` 1,093, `broad` 964, `unresolved` 1,251, none 219 | `point` 636, `interval` 1,313, `broad` 618, `unresolved` 1,198, none 172 |
| By the widened span (0.3.0's `covers_trough_boundary`) | `interval` 697, `broad` 897, `unresolved` 2,364 | `interval` 1,133, `broad` 814, `unresolved` 1,990 |
| By the end status, as proposed | `point` 2,194, `interval` 665, `unresolved` 1,099 | `point` 1,852, `interval` 1,026, `unresolved` 1,059 |
| By the end status, after rule 3 (`point` read as `interval`) | `interval` 2,859, `unresolved` 1,099 | `interval` 2,878, `unresolved` 1,059 |

Grading by the widened span nearly doubles the `unresolved` cycles among moved pairs (1,251 → 2,364 in arm S), and an `unresolved` year has no monthly phases and cannot anchor a baseline. Grading by the end status, capped at `interval` as rule 3 requires, keeps `unresolved` slightly below today (1,099 and 1,059) but turns the 431 and 636 moved cycles graded `point` today into `interval`. The plan leaves this choice to the lead at implementation.

## Extras, written after scoring (reported only)

[`scripts/de1_reported_extras.py`](../../scripts/de1_reported_extras.py) reads the frozen corpus and runs through the frozen script's own functions (imported, not edited) and writes [2026-11-05-de1-dry-run-end-extras.json](2026-11-05-de1-dry-run-end-extras.json). None of it feeds a rule.

### Routing

| Arm, shape | Per-year detection | Event characterisation |
| --- | ---: | ---: |
| S `ephemeral` | 502 | 698 |
| S `pulse` | 242 | 158 |
| S `sine` | 257 | 143 |
| I `ephemeral` | 181 | 393 |
| I `pulse` | 162 | 125 |
| I `sine` | 158 | 129 |

B can only move a boundary that exists. On 58% (arm S) and 68% (arm I) of ephemeral records the library reports events, not seasons; whether that routing is right for such records is a separate question, not tested here.

### What ends the run early

Ephemeral pairs the candidate still dates two or more months early, by the kind of month that ended the run (the re-wetting month):

| Re-wetting month | Arm S (4,135) | Arm I (1,695) |
| --- | ---: | ---: |
| A dry month above the tolerance (noise, a spike or, in arm I, the background) | 3,632 (87.8%) | 1,300 (76.7%) |
| A true mid-dry pulse | 116 (2.8%) | 52 (3.1%) |
| A true wet-season month | 178 (4.3%) | 120 (7.1%) |
| None: the record ends dry (`censored`) | 209 (5.1%) | 223 (13.2%) |

The dry month that ends the run sits a median 2.3 tolerances above the run's level (quartiles 1.5–3.7 in arm S, 1.5–4.1 in arm I). The tolerance is the library's own (`_epsilon_pp`, at most a tenth of the amplitude), so on noisy flat bottoms a single noisy month ends the run. This is the largest remaining error. Changing it means a new candidate and a new known-truth test; the removed `last_before_confirmed_recovery` rule, which waited for a sustained rise, failed on mid-dry pulses.

### Candidate ends at or after their own peak

208 of 25,936 scored pairs (0.8%): 78 in arm S (66 `ephemeral`, 10 `pulse`, 2 `sine`) and 130 in arm I (43, 57, 30). In 77 of the 78 (arm S) and 101 of the 130 (arm I) the peak month is above 20% invalid: the library reports it as the peak under the `flag` policy, but the run treats it as unobserved (choice 1) and runs through it. A boundary after its own peak would move the peak into another year, which implementation check 2 forbids ("peaks must not move"); the implementation needs the run to stop before the cycle's peak. This changes the frozen candidate in at most 0.8% of pairs and is reported at implementation.

### Rule 3 by shape

| | `point` ends not correct, all pairs | `point` ends not correct, moved pairs only |
| --- | --- | --- |
| Arm S `ephemeral` | 3,681 of 6,162 (0.597) | 1,230 of 2,675 (0.460) |
| Arm S `pulse` | 1,003 of 2,695 (0.372) | 80 of 399 (0.201) |
| Arm S `sine` | 263 of 2,631 (0.100) | 33 of 541 (0.061) |
| Arm I `ephemeral` | 1,147 of 2,651 (0.433) | 337 of 1,230 (0.274) |
| Arm I `pulse` | 796 of 3,386 (0.235) | 147 of 816 (0.180) |
| Arm I `sine` | 270 of 3,008 (0.090) | 96 of 1,157 (0.083) |

Rule 3 pooled every candidate end, including boundaries that did not move. Today's boundary is wrong by more than a month on about a tenth of `sine` pairs, so rule 3 could not have passed even with a perfect move. The reading is unaffected: on moved ephemeral pairs alone, `point` ends are wrong in 46% (arm S) and 27% (arm I), far above 5%.

## Real records

From the stored `hydroseason-v0.3.0` runs, with the same code ([2026-11-05-de1-dry-run-end-real-records.json](2026-11-05-de1-dry-run-end-real-records.json); 3,010 records):

| Source | Cycles | Boundary moves | By 3+ months | By 6+ months |
| --- | ---: | ---: | ---: | ---: |
| G1 core windows | 16,939 | 52.1% | 25.5% | 13.3% |
| G1 quadrants | 59,053 | 57.9% | 34.8% | 18.7% |
| Spatial units, catchment | 63 | 25.4% | 0.0% | 0.0% |
| Spatial units, HydroBASINS 6 | 483 | 38.5% | 3.9% | 0.8% |
| Spatial units, HydroBASINS 7 | 2,121 | 45.8% | 10.3% | 3.3% |
| Spatial units, HydroBASINS 8 | 6,132 | 49.7% | 18.2% | 6.5% |
| Spatial units, tile 6 | 924 | 47.1% | 8.1% | 2.7% |
| Spatial units, tile 7 | 2,541 | 48.8% | 11.9% | 4.4% |
| Spatial units, tile 8 | 8,925 | 49.7% | 17.7% | 5.9% |

- **Real records move more, and further, than the synthetic `sine` and `pulse` records** (up to 18.7% by six months or more on G1 quadrants, against at most 1.2%). Small units move most. The implementation checks must look at these cycles on the case studies and tiles.
- **End-of-dry agreement between the two pixel halves of a G1 window** (within one month, 33,533 pairs): 0.732 today, 0.724 with the candidate. No interval was computed; the candidate is not more reproducible than today's boundary.
- **On the Fitzroy tiles** (exploratory, from the [analysis](2026-11-05-dry-run-end-analysis.md)): the boundary would move in about 50% of cycles.

## Deviations

None from the frozen plan or scripts. The plan, the DE1 script and the G2 and G1 scripts match the receipt; the scorer ran once on the main corpus. The extras script was written after scoring, reads only, and decides nothing. Rule 3's pooling of unmoved boundaries is a limit of the rule as written (above), not a deviation.

## What goes to implementation (the lead decides)

1. **A and B under a new policy id**, with end status `interval` or `censored` only, as the reading requires.
2. **The run stops before its cycle's peak** (208 pairs, 0.8%), so peaks do not move.
3. **How a moved boundary's timing is graded:** by the end status capped at `interval` (keeps `unresolved` at or below today; loses `point` on moved cycles) or by 0.3.0's widened span (nearly doubles `unresolved` on moved cycles).
4. **Then the implementation checks of the plan:** five case studies and the Fitzroy tiles before against after, the real-record rerun (routing, cycle counts, baseline coverage, the hydropools end-of-dry clock on the tiles), docs, CHANGELOG, manifest and the full suite.

Not addressed by DE1, each needing its own test: noise ending runs early (the main remaining error), and the routing of ephemeral records to event characterisation.

## Limits (stated in advance)

- The truth is the generator's. The `ephemeral` shape was designed after seeing Fitzroy tiles 05 and 13; its parameters were set in the plan, not fitted.
- One candidate. The last low month before the next peak (which would span mid-dry pulses) was not tested.
- Monthly resolution.
- Arm I's truth leaves out the background's own wet and dry years.
- Not accuracy for real places, and not referenced to gauges.
