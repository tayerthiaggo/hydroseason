# DE2: the year boundary at the end of the low, results

Run 2026-11-08 under the frozen plan ([plan](2026-11-08-de2-end-of-low-plan.md), [receipt](2026-11-08-de2-end-of-low-receipt.json)). Scorer output: [2026-11-08-de2-end-of-low-results.json](2026-11-08-de2-end-of-low-results.json), citing receipt SHA-256 `d46836e0f20638c530feab2149e0a07b165ab562be7ffcb756e93fc486da1689` and script SHA-256 `f2bf39eeb1b15e9c4b57dec1c31e9fbc940461d141cd2e0ae7101b042e271e3d`. Both libraries ran all 3,148 records with no errors, each under one fingerprint (current `aba922a9eac2…`, candidate `915addae5fa1…`).

## Summary

**All four rules hold in both arms.** Under the reading fixed in advance, R1 (anchor the search at the end of the typical low) and R2 (date a boundary at the end of a dry low by where the low ends) go to the implementation checks and then to the lead for `hydroseason-v0.3.0`.

- **Rule 1 holds: the boundary dates the end of the dry season better on ephemeral seasons.** Share of true ends hit within a month, over all ephemeral records (a record without boundaries misses all its ends): 0.070 → 0.109, +0.039 [+0.033, +0.044] in arm S; 0.085 → 0.103, +0.019 [+0.013, +0.025] in arm I. Among records routed to per-year detection: 0.175 → 0.269 (arm S) and 0.259 → 0.315 (arm I).
- **Rules 2 and 3 hold: smooth and pulse seasons are no worse.** `sine` +0.002 [−0.006, +0.010] (arm S) and +0.003 [−0.007, +0.015] (arm I); `pulse` +0.018 [+0.011, +0.026] and +0.014 [+0.004, +0.027].
- **Rule 4 holds:** the reviewed Gilbert and Fitzroy trough tests pass under the candidate.
- **R2's labels are often wrong; this is the main caution.** On ephemeral seasons the true end lies within a month of an R2 label in 687 of 2,417 cases (0.284) in arm S and 304 of 502 (0.606) in arm I. Most R2 labels are one month wide, and the true end usually lies two to six months after the boundary: a noisy dry month ends the run early (DE1's main remaining error), so a label reading `interval` claims more than the run supports. Not a decision rule; the lead decides with it.
- **The absolute level stays low.** With the candidate about one ephemeral dry-season end in ten is hit within a month (one in four to one in three among per-year records). Most ephemeral records route to event characterisation, and noise ends many runs early.

## Decision rules

Intervals are 95% bootstrap intervals over records (2,000 draws).

| Rule | Arm S | Arm I | Bound | Outcome |
| --- | --- | --- | --- | --- |
| 1. `ephemeral`, share of true ends hit | 0.070 → 0.109, +0.039 [+0.033, +0.044] (1,200 records, 20,163 true ends) | 0.085 → 0.103, +0.019 [+0.013, +0.025] (574 records, 18,390 true ends) | lower > 0 | Holds in both |
| 2. `sine` | 0.552 → 0.554, +0.002 [−0.006, +0.010] (400 records, 7,932 true ends) | 0.433 → 0.437, +0.003 [−0.007, +0.015] (287 records, 10,859 true ends) | lower ≥ −0.05 | Holds in both |
| 3. `pulse` | 0.331 → 0.349, +0.018 [+0.011, +0.026] (400 records, 7,942 true ends) | 0.340 → 0.354, +0.014 [+0.004, +0.027] (287 records, 10,856 true ends) | lower ≥ −0.05 | Holds in both |
| 4. Reviewed Gilbert and Fitzroy trough tests | | | pass | Holds (3 passed in 11.01s) |

**Reading, fixed in advance:** all four hold, so R1 and R2 go to the implementation checks (case studies, Fitzroy tiles, real-record rerun, docs, full suite) and then to the lead.

## Reported, not used to decide

### Ephemeral seasons by noise band (amplitude over noise, k)

| k | Arm S | Arm I |
| --- | --- | --- |
| 0.5–2 | 0.006 → 0.006, +0.000 [+0.000, +0.000] | 0.022 → 0.026, +0.004 [−0.000, +0.010] |
| 2–5 | 0.059 → 0.075, +0.016 [+0.009, +0.024] | 0.056 → 0.064, +0.007 [−0.001, +0.017] |
| 5–10 | 0.097 → 0.141, +0.044 [+0.032, +0.058] | 0.085 → 0.105, +0.020 [+0.005, +0.042] |
| 10–31 | 0.149 → 0.255, +0.106 [+0.090, +0.122] | 0.184 → 0.229, +0.045 [+0.028, +0.063] |

The gain grows with k. At the noisiest band (k below 2) neither library dates ephemeral ends.

### Labels, routes and peaks

| | Arm S | Arm I |
| --- | --- | --- |
| `point` trough labels more than a month off, current | 1,830 of 4,799 (0.381) | 2,289 of 5,812 (0.394) |
| `point` trough labels more than a month off, candidate | 1,462 of 4,593 (0.318) | 2,182 of 5,756 (0.379) |
| R2 labels on ephemeral seasons with the truth within a month | 687 of 2,417 (0.284) | 304 of 502 (0.606) |
| Ephemeral records routed to per-year detection, current → candidate | 472 → 477 of 1,200 | 184 → 185 of 574 |
| `sine` records routed to per-year detection | 257 → 255 of 400 | 143 → 146 of 287 |
| `pulse` records routed to per-year detection | 233 → 234 of 400 | 163 → 163 of 287 |
| Share of cycles with dated timing, ephemeral | 0.634 → 0.633 | 0.579 → 0.577 |
| Share of cycles with dated timing, `sine` | 0.602 → 0.601 | 0.701 → 0.689 |
| Records whose anchor month moved (ephemeral / `sine` / `pulse`) | 270 / 145 / 69 | 86 / 73 / 45 |
| Records with any peak change (ephemeral / `sine` / `pulse`) | 202 / 28 / 36 | 83 / 40 / 36 |

R1 moves the anchor on many `sine` records too (usually by a month); rule 2 shows it costs nothing there.

### Real records: Fitzroy tiles (production inputs, 40 tiles)

| | v0.3.0 | Candidate |
| --- | ---: | ---: |
| Tile-years whose dry run ends after the boundary | 727 | 602 |
| … by three months or more | 251 | 104 |
| Tiles 05 / 13 / 54 / 46, three or more months | 33 / 35 / 34 / 32 | 10 / 16 / 13 / 10 |
| Tiles routed to event characterisation | 0 | 0 |
| Years with unresolved timing | 408 | 533 |
| Boundaries moved / peaks changed | | 347 / 78 |

The case studies were measured on the exploratory candidate (R2 on any flat low): 248 of 252 boundaries identical. The implementation checks rerun them on the frozen candidate.

## Deviations

- **The frozen script's evaluate stage stopped on a non-integer bootstrap seed** (400 + 0.5 for the first noise band, a reported breakdown). It was run through [`scripts/known_truth_de2_evaluate.py`](../../scripts/known_truth_de2_evaluate.py), which leaves the frozen script byte-identical and turns that seed into 4005. Every decision rule's seed is an integer and passes through unchanged. The scorer ran once after the fix; the library runs were not repeated.
- The extras ([`scripts/de2_reported_extras.py`](../../scripts/de2_reported_extras.py), [2026-11-08-de2-end-of-low-extras.json](2026-11-08-de2-end-of-low-extras.json)) were written after scoring and decide nothing.

## For the lead

The rules pass, so R1 and R2 go forward by the reading. R1 is what improves the boundary; R2 only relabels, and on noisy ephemeral records its `interval` labels are more often wrong than right in arm S. The choice before the implementation checks:

1. **R1 + R2 as tested.** Labels at the end of dry lows read `interval` and are often wrong by more than a month.
2. **R1 + R2 with `broad` instead of `interval`.** Keeps those years dated (the seven-cycle check, phases, baselines) with a weaker claim; not tested, needs a short check of its own.
3. **R1 only.** Labels stay `unresolved` where the low is flat, which is honest; some records (tile 13 among them) then route to event characterisation. Not tested as such: the rules were scored with R2 in place.

## Limits (stated in advance)

- The `ephemeral` generator was designed after seeing Fitzroy tiles 05 and 13.
- R1's tenth of the range and R2's conditions were chosen while exploring the tiles.
- Not accuracy for real places, and not referenced to gauges.

## Follow-up: revised R2 (post hoc, 2026-11-08)

After reading these results the lead chose to revise R2 before the implementation checks. The revised label runs from the run end to the month before the next peak and is graded by width (`interval` up to two months apart, `broad` up to five, never `point`); a span wider than that leaves the label as it was. R1 is unchanged (commit `128c771`, fingerprint `59756dfe895f…`).

[`scripts/de2_r2_revised_check.py`](../../scripts/de2_r2_revised_check.py) reran the frozen corpus under the revised candidate and scored it with DE2's frozen functions against the same current-library runs ([2026-11-08-de2-r2-revised-check.json](2026-11-08-de2-r2-revised-check.json)). **This is a post-hoc check, not a pre-registered test.**

| | Arm S | Arm I |
| --- | --- | --- |
| Rule 1, `ephemeral` | +0.038 [+0.033, +0.044] | +0.019 [+0.013, +0.025] |
| Rule 2, `sine` | +0.002 [−0.006, +0.010] | +0.003 [−0.007, +0.015] |
| Rule 3, `pulse` | +0.018 [+0.011, +0.026] | +0.014 [+0.004, +0.027] |
| R2 labels with the true end within a month | 1,371 of 1,747 (0.785) | 328 of 430 (0.763) |
| R2 labels `interval` / `broad` | 1,009 / 738 | 344 / 86 |

The rules give the same results as before (R2 changes labels, not boundaries; one ephemeral record in arm S changes route). The reviewed gates pass. The revised labels hold the true end within a month about three times in four in both arms, against 0.284 and 0.606 for DE2's R2. The revised candidate goes to the implementation checks.
