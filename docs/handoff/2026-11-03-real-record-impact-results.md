# Real-record impact: the baseline timing requirement, and the trough label/date mismatch (results)

Measured 2026-11-03 under the [plan](2026-11-03-real-record-impact-plan.md). This is a measurement, not a pass/fail test, and nothing in the library changed. The measures are in [2026-11-03-real-record-impact-results.json](2026-11-03-real-record-impact-results.json). It records plan SHA-256 `d2bd9b3843af143504309becc9f3c6f153451f3b13ff671ced2c656e9f00a42f` and script SHA-256 `27df9b82fb37f960490bc266e0800eb5e5a6b6141945db45e70cbbe84955137f`, both matching the files. Exploratory checks that the plan did not name are in [2026-11-03-real-record-impact-exploratory.json](2026-11-03-real-record-impact-exploratory.json) and are marked as such below.

## Summary

- **Allowing any dated status (E1) gives about ten times as many units a condition baseline.**
  - On the G1 windows: 5.4% to 62.3% of core units, and 4.7% to 45.4% of quadrant units.
  - On the spatial-unit-study subbasins and tiles: from 0–5% to 30–61%.
  - Dropping the timing requirement altogether (E2) adds almost nothing beyond E1. On real records, nearly every cycle that passes the other baseline checks already has a dated status.
- **Repeatability between pixel halves: the pre-registered comparison is inconclusive for both labels.**
  - Agreement on the pairs E1 adds, minus agreement on the pairs today's rule labels:
    - recharge (peak) labels: −0.025 [−0.104, +0.052];
    - refuge (trough) labels: −0.014 [−0.096, +0.069].
  - Both point estimates are small. The intervals are wide because today's rule labels so few places: its 637 pairs come from 16 of the 256 windows.
- **Recharge labels show no sign of a cost.**
  - The amendment's measure finds no evidence of one: −0.001 [−0.034, +0.028].
  - Chance-corrected agreement is the same with or without `point` timing (exploratory).
- **Refuge labels may repeat less well in the units E1 adds. This is not resolved.**
  - On the amendment's measure, `point` pairs agree more: −0.039 [−0.073, −0.004], which the plan's reading calls inconclusive.
  - Chance-corrected agreement (exploratory) is lower in the added units: kappa 0.41 against 0.51, difference −0.10 [−0.22, +0.02].
  - Within today's labelled units, non-`point` cycles agree as well as `point` ones.
  - No test so far has a known truth for refuge labels (B1 had none). These between-half numbers are the only evidence on them.
- **Case studies: only the Gilbert gains a baseline.** Under E1 it has 9 eligible cycles, up from 1, and all 21 years (2005–2025) get labels. The Daly (4 eligible) and the Fitzroy (3) stay below five. The Lachlan and the Moonie route to event characterisation.
- **The label/date mismatch is common on small windows, and the months are often far apart.**
  - Share of `point` trough cycles affected:
    - 472 of 3,843 (12.3%) on G1 core units;
    - 1,008 of 10,918 (9.2%) on G1 quadrants;
    - 3–5% on subbasins and tiles;
    - none of 22 on whole catchments.
  - The label's month always lies before the reported `trough_date`.
  - On the G1 windows, only a quarter of these cases are one month apart. The median gap is 3 months and the largest is 14.

## Checks

| Check | Outcome |
| --- | --- |
| Records run | 4,468 (G1: 3,190; spatial-unit study: 1,278) |
| Errors | 0 |
| The E0 recomputation reproduces every library label and eligibility flag | Yes, 0 mismatches |
| G1 series files match the hashes in the G1 receipt | Yes |
| Routed to per-year detection | G1 2,001 of 3,190; spatial-unit study 1,009 of 1,278 |

## M1.1 Coverage

Units routed to per-year detection. "Baseline" means at least five eligible cycles. The table counts recharge labels; refuge labels differ by at most two points from them.

| Source, scale | Units | With a baseline, E0 | E1 | E2 | Cycles with a recharge label, E0 | E1 | Median eligible cycles, E0 → E1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| G1 core (about 236 km²) | 446 | 24 (5.4%) | 278 (62.3%) | 278 (62.3%) | 877 of 16,948 (5.2%) | 10,212 (60.3%) | 1 → 5 |
| G1 quadrant (about 59 km²) | 1,555 | 73 (4.7%) | 706 (45.4%) | 711 (45.7%) | 2,686 of 59,090 (4.5%) | 25,819 (43.7%) | 1 → 4 |
| Whole catchment | 3 | 0 | 1 | 1 | 0 of 63 | 21 (33.3%) | 1 → 4 |
| HydroBASINS level 6 | 23 | 1 (4.3%) | 14 (60.9%) | 14 (60.9%) | 21 of 483 (4.3%) | 294 (60.9%) | 1 → 5 |
| HydroBASINS level 7 | 101 | 3 (3.0%) | 51 (50.5%) | 52 (51.5%) | 63 of 2,121 (3.0%) | 1,065 (50.2%) | 1 → 5 |
| HydroBASINS level 8 | 292 | 5 (1.7%) | 92 (31.5%) | 95 (32.5%) | 105 of 6,132 (1.7%) | 1,909 (31.1%) | 1 → 3 |
| Tiles, level 6 size | 44 | 0 | 16 (36.4%) | 17 (38.6%) | 0 of 924 | 333 (36.0%) | 1 → 4 |
| Tiles, level 7 size | 121 | 6 (5.0%) | 53 (43.8%) | 54 (44.6%) | 123 of 2,541 (4.8%) | 1,093 (43.0%) | 1 → 4 |
| Tiles, level 8 size | 425 | 11 (2.6%) | 129 (30.4%) | 132 (31.1%) | 228 of 8,925 (2.6%) | 2,668 (29.9%) | 1 → 3 |

## M1.2 Agreement between pixel halves (G1 windows)

31,085 cycle pairs were matched by peak month across 256 windows. A pair counts when both halves have a label. Chance is the agreement expected from each half's label shares.

| Pairs | Recharge agree | Chance | Refuge agree | Chance |
| --- | --- | ---: | --- | ---: |
| Labelled under E0 | 475 of 637 (74.6%) | 0.370 | 433 of 637 (68.0%) | 0.340 |
| Labelled under E1 | 8,555 of 11,837 (72.3%) | 0.359 | 7,932 of 11,837 (67.0%) | 0.426 |
| Added by E1 (labelled under E1, not E0) | 8,075 of 11,200 (72.1%) | 0.359 | 7,458 of 11,200 (66.6%) | 0.430 |
| E1, both halves `point` | 712 of 984 (72.4%) | 0.374 | 695 of 984 (70.6%) | 0.372 |
| E1, at least one half not `point` | 7,843 of 10,853 (72.3%) | 0.368 | 7,237 of 10,853 (66.7%) | 0.433 |
| Labelled under E2 | 8,654 of 11,951 (72.4%) | 0.359 | 8,054 of 11,951 (67.4%) | 0.429 |

Differences use a 2,000-draw bootstrap over windows (seed 0). Each reading is the plan's: an interval wholly below −0.05 is evidence of a cost; a lower end of at least −0.05 is no evidence of a cost; anything else is inconclusive.

| Difference | Recharge | Reading | Refuge | Reading |
| --- | --- | --- | --- | --- |
| Added minus E0 (primary: E0 has 637 pairs, at least 100) | −0.025 [−0.104, +0.052] | inconclusive | −0.014 [−0.096, +0.069] | inconclusive |
| Not `point` minus `point`, within E1 (amendment) | −0.001 [−0.034, +0.028] | no evidence of a cost | −0.039 [−0.073, −0.004] | inconclusive |

Cohen's kappa between halves for E1 labels is 0.57 [0.54, 0.59] for recharge and 0.43 [0.39, 0.46] for refuge.

The amendment's measure does not isolate the baseline rule. Once a unit has a baseline, both rules label every cycle in it, `point` or not. The rule decides which units get labels, not which cycles. The added-minus-E0 comparison is the one that measures the rule.

### Exploratory: chance-corrected agreement by group

The groups differ in their label shares. For example, 58% of refuge labels on added pairs are `typical`, against 38% under E0. So raw agreement and chance move together. Kappa corrects for that. These measures were not in the plan.

| Group | Recharge kappa | Refuge kappa |
| --- | ---: | ---: |
| Labelled under E0 (637 pairs, 16 windows) | 0.60 | 0.51 |
| Added by E1 (11,200 pairs, 163 windows) | 0.56 | 0.41 |
| E1, both `point` (984 pairs) | 0.56 | 0.53 |
| E1, not both `point` (10,853 pairs) | 0.56 | 0.41 |
| E0, both `point` (156 pairs) | 0.53 | 0.50 |
| E0, not both `point` (481 pairs) | 0.59 | 0.52 |

| Kappa difference | Recharge | Refuge |
| --- | --- | --- |
| Added minus E0 | −0.03 [−0.15, +0.08] | −0.10 [−0.22, +0.02] |
| Not `point` minus `point`, within E1 | +0.003 [−0.048, +0.049] | −0.12 [−0.18, −0.06] |

- Recharge labels repeat the same with or without `point` timing, and in added units as in today's.
- Refuge labels repeat less beyond chance in the units E1 adds, and on their non-`point` cycles. Within today's 16 labelled windows, non-`point` cycles do not repeat less.
- So the drop may belong to the kind of units E1 adds (fewer clearly timed cycles) rather than to non-`point` cycles as such. Sixteen windows cannot separate the two.

## M1.3 Case-study tables

Whole catchments from the spatial-unit-study records (2005–2025), not the published 1988–2025 case-study runs.

| Catchment | Route | Cycles | Eligible, E0 | Labelled years, E0 | Eligible, E1 | Labelled years, E1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Daly River NT | per-year detection | 21 | 3 | 0 | 4 | 0 |
| Fitzroy River WA | per-year detection | 21 | 1 | 0 | 3 | 0 |
| Gilbert River QLD | per-year detection | 21 | 1 | 0 | 9 | 21 |
| Lachlan River NSW | event characterisation | none | | | | |
| Moonie River QLD/NSW | event characterisation | none | | | | |

Gilbert under E1 (recharge/refuge). The baseline is the nine complete cycles of 2013–2022 (2019 is partial). The partial cycles of 2005–2012 and 2023–2025 are ranked against it.

| Year | Labels | Year | Labels | Year | Labels |
| --- | --- | --- | --- | --- | --- |
| 2005 | typical/typical | 2012 | high/typical | 2019 | typical/typical |
| 2006 | typical/typical | 2013 | low/low | 2020 | high/typical |
| 2007 | high/high | 2014 | typical/typical | 2021 | high/high |
| 2008 | typical/typical | 2015 | low/low | 2022 | typical/high |
| 2009 | high/typical | 2016 | typical/typical | 2023 | high/typical |
| 2010 | high/high | 2017 | typical/typical | 2024 | high/high |
| 2011 | high/high | 2018 | typical/typical | 2025 | typical/high |

Nine of the 21 years read high recharge. Seven of them are partial or anomalous-peak cycles, which are kept out of the baseline under either rule and ranked against it.

## M1.4 Label stability

On cycles labelled under both rules in the same record, relaxing changes 534 of 4,103 recharge labels (13.0%) and 700 of 4,232 refuge labels (16.5%). The baseline grows, so some ranks move across the 20th or 80th percentile.

## M2 The trough label/date mismatch

A mismatch is a `point` trough cycle whose one-month trough interval is not the reported boundary month (`trough_month`, exported as `trough_date`).

| Source, scale | `point` troughs | Mismatch | Label month more than 20% invalid | Selection status of the mismatches |
| --- | ---: | --- | --- | --- |
| G1 core | 3,843 | 472 (12.3%) | 418 of 472 (88.6%) | quality-adjusted 330, raw 122, low-quality 10, ambiguous 9, coherence-adjusted 1 |
| G1 quadrant | 10,918 | 1,008 (9.2%) | 858 of 1,008 (85.1%) | quality-adjusted 678, raw 296, low-quality 15, ambiguous 15, coherence-adjusted 4 |
| Whole catchment | 22 | 0 | | |
| HydroBASINS level 6 | 138 | 7 (5.1%) | 5 of 7 | quality-adjusted 6, raw 1 |
| HydroBASINS level 7 | 558 | 18 (3.2%) | 14 of 18 | quality-adjusted 14, raw 4 |
| HydroBASINS level 8 | 1,343 | 40 (3.0%) | 31 of 40 | quality-adjusted 31, raw 9 |
| Tiles, level 6 size | 233 | 10 (4.3%) | 9 of 10 | quality-adjusted 7, raw 3 |
| Tiles, level 7 size | 623 | 20 (3.2%) | 14 of 20 | quality-adjusted 14, raw 6 |
| Tiles, level 8 size | 1,871 | 62 (3.3%) | 49 of 62 | quality-adjusted 44, raw 18 |

In every case the label's month lies before the boundary.

### Exploratory: why the months differ, and how far apart they are

| | G1 windows (1,480) | Spatial-unit study (157) |
| --- | --- | --- |
| The label's month is the raw minimum that the cloud screen removed | 701 (47.4%) | 65 (41.4%) |
| The record flags a lower month outside the boundary's search window (`outside_window_lower`) | 489 (33.0%) | 49 (31.2%) |
| Neither | 290 (19.6%) | 43 (27.4%) |
| Months apart: one | 367 (24.8%) | 44 (28.0%) |
| Months apart: median, largest | 3, 14 | 4, 10 |

The label is judged on the usable months from the peak to the boundary, cloudy ones included. The boundary is chosen from the clear months within its search window. When the two disagree, the label has singled out a month the boundary rejected, and the row reports a later month that the label did not single out.

## What follows

1. **Candidate 4, relaxing the baseline to any dated status.**
   - **For recharge labels the evidence now points one way.** B1 found the relaxed rule at least as accurate on known truth. On real records it repeats as well between halves, and it labels about ten times as many units.
   - **Refuge labels are the gap.**
     - They have never been scored against a known truth.
     - On real records, the pre-registered comparison is inconclusive and an exploratory measure hints at a cost.
     - More real-record runs will not settle this. Today's rule labels too few places to compare against.
   - **The lead's options:**
     1. Relax for both labels, and document that refuge labels in newly labelled units are less repeatable.
     2. First run a small pre-registered known-truth refuge test: inject seasons whose dry level varies between years into the flat real records, as in arm I, and score refuge labels under E0 and E1.
     3. Keep today's rule.
   - **Recommendation: option 2.** It fills the one evidence gap without a new method.
   - Whatever is chosen, E1 and E2 behave alike on real records. In practice, relaxing means dropping the timing requirement.
2. **Candidate 5, making the label and `trough_date` refer to the same month.** It matters on small units: about 1 in 8 `point` troughs on 236 km² windows, usually several months apart. The decision record names two fixes.
   - Judging the label only on the cloud-screened months the boundary uses would cover the cloud cases. That is at least the 47% where the label's month is the screened raw minimum, and at most the 85–89% where it is cloudy. Cases outside the boundary's search window could remain.
   - Dropping `point` whenever the boundary month falls outside the label's own interval covers every case by construction. It costs 9–12% of `point` troughs on small windows, 3–5% on subbasins and tiles, and none on whole catchments.
   - **Recommendation: the second fix.** It is a consistency rule, not a new estimator.
   - Until a fix ships, the column docs could say that a `point` trough label can refer to an earlier month than `trough_date`. That needs the lead's sign-off, like the earlier doc changes.
3. **Candidate 1**, the gates in the manifest, is unaffected.

Each change is `hydroseason-v0.3.0` and needs the lead's approval.

## Limits

- Agreement between halves is not accuracy. Two halves share the same weather, cloud and season, so they can agree on a wrong label.
- The E0 comparisons rest on 16 windows. The two largest carry 145 of the 637 pairs.
- The kappa-by-group tables and the mismatch causes are exploratory and were chosen after the main measures were seen. In the cause breakdown, 20–27% of cases fit neither named cause.
- The G1 halves are half-resolution records of one place. The spatial-unit-study units are whole records, but cover only 2005–2025. That is why the routed whole catchments have 22 `point` troughs here, against 85 in the published case-study runs.
- Labels are relative to each unit's own baseline. A change in the baseline changes labels without any change in the record (M1.4).

## Audit

- **Plan amendment.** The amendment was added after a 20-record smoke run and before the main run.
  - The smoke run logged the pre-amendment plan (SHA-256 `72baa3ab…`) at 14:15:05.
  - The plan file was last saved at 14:17:06.
  - The main run logged the amended plan (`d2bd9b38…`) at 14:17:22.
  - The amendment's own stamp, 14:20, is a few minutes late and should read 14:17. The plan is left as frozen.
- **The amendment's fallback did not trigger.** E0 has 637 labelled pairs, so the original comparison is primary, as the plan says. The amendment's measures are reported as secondary.
- **Library state.** The library is unchanged since 2026-11-02 14:39, before the plan was written.
- **No other deviations.**

## Provenance

- Smoke run: 20 records, 14:15:05–14:16:15. They were kept, and the main run resumed from them.
- Main run: 4,448 records, 16 workers, 14:17:22–16:15:15 (7,073 s).
- Analysis: `scripts/real_record_impact.py analyse`, 16:16:34. Results SHA-256 `7c008521697f19fb6ae1afa923f3c094d6b5534677a2dd4406a6ddf0e3e93ea7`.
- Exploratory: `scripts/real_record_impact_explore.py` (SHA-256 `7bd6d49b94a1fa3e307f94b79666edfa80f01524ebc714b43ab85942846aafe8`), 16:28.
- Per-record outputs: `D:\RLH\5.6\data_local\intermediate\hydroseason_real_record_impact\runs.jsonl`.
- Log: `impact.log` in the same folder.
