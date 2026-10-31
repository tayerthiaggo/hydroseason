# Provisional trough analysis: falsification results

Date: 2026-10-30. Repository baseline: `048a1b6`.
Plan: `docs/superpowers/plans/2026-10-30-trough-falsification-tests.md` (local working file, not tracked).
Verdict this answers: `docs/provisional-trough-verdict-2026-10-30.md` (local working file, not tracked), steps 3 and 5.

No library code was changed. Environment: Python 3.12.13, NumPy 2.4.6, pandas 3.0.3.

## 1. Pre-registered checks (tests/test_trough_falsification_slow.py)

Bounds were fixed in the plan before the first run.

| Check | Bound | Observed | Result |
| --- | --- | --- | --- |
| Trough test false-positive rate, drifting trough, floods 0.3, 12 y, 100 seeds | <= 10 | 4/100 | PASS |
| Trough test power, recurrent trough, floods 0.3, 12 y, 100 seeds | >= 90 | 99/100 | PASS |
| Trough test under uniform null, 12 y, 200 seeds | <= 17 | 7/200 | PASS |
| Peak test under uniform null, 12 y, 200 seeds | <= 17 | 17/200 | PASS |
| Peak test under uniform null, 12 y, 1000 seeds (Task 7 Step 2b) | none; null mean 50, sd 6.9 | 62/1000 | recorded |
| Trough test under uniform null, 12 y, 1000 seeds (Task 7 Step 2b) | none; null mean 50, sd 6.9 | 51/1000 | recorded |

All four pre-registered bounds held; the 200-seed peak count landed on its bound. The 1,000-seed check has no pre-registered threshold.

## 2. Sweep (scripts/trough_falsification_sweep.py, 30 seeds per cell)

Default grid: stable, stable_sharp, drift, plateau and uniform; 7, 12 and 30 years; flood rates 0.0 and 0.3; gaps none, dry20 and wet20; no counts.

| cell | n | harmonic accept | harmonic wrong month | trough p<0.05 | peak p<0.05 | seasonal | median set width |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| drift/7/0.0/dry20/False | 30 | 2 | 0 | 1 | 1 | 0 | 1.0 |
| drift/7/0.0/none/False | 30 | 2 | 0 | 2 | 2 | 0 | 1.0 |
| drift/7/0.0/wet20/False | 30 | 0 | 0 | 2 | 1 | 0 | 1.0 |
| drift/7/0.3/dry20/False | 30 | 0 | 0 | 0 | 1 | 0 | 1.0 |
| drift/7/0.3/none/False | 30 | 0 | 0 | 2 | 4 | 0 | 1.0 |
| drift/7/0.3/wet20/False | 30 | 0 | 0 | 1 | 4 | 1 | 1.0 |
| drift/12/0.0/dry20/False | 30 | 2 | 0 | 3 | 6 | 0 | 1.0 |
| drift/12/0.0/none/False | 30 | 1 | 0 | 3 | 4 | 0 | 1.0 |
| drift/12/0.0/wet20/False | 30 | 1 | 0 | 4 | 2 | 0 | 1.0 |
| drift/12/0.3/dry20/False | 30 | 1 | 0 | 2 | 1 | 0 | 1.0 |
| drift/12/0.3/none/False | 30 | 1 | 0 | 2 | 0 | 0 | 2.0 |
| drift/12/0.3/wet20/False | 30 | 0 | 0 | 2 | 2 | 0 | 1.5 |
| drift/30/0.0/dry20/False | 30 | 0 | 0 | 1 | 12 | 1 | 1.0 |
| drift/30/0.0/none/False | 30 | 0 | 0 | 1 | 1 | 0 | 1.0 |
| drift/30/0.0/wet20/False | 30 | 0 | 0 | 2 | 7 | 1 | 1.0 |
| drift/30/0.3/dry20/False | 30 | 0 | 0 | 3 | 5 | 1 | 1.0 |
| drift/30/0.3/none/False | 30 | 0 | 0 | 1 | 2 | 0 | 1.0 |
| drift/30/0.3/wet20/False | 30 | 0 | 0 | 1 | 2 | 0 | 1.0 |
| plateau/7/0.0/dry20/False | 30 | 30 | 4 | 30 | 24 | 24 | 3.0 |
| plateau/7/0.0/none/False | 30 | 30 | 7 | 30 | 18 | 18 | 4.0 |
| plateau/7/0.0/wet20/False | 30 | 30 | 5 | 29 | 16 | 16 | 4.0 |
| plateau/7/0.3/dry20/False | 30 | 26 | 3 | 29 | 13 | 13 | 4.0 |
| plateau/7/0.3/none/False | 30 | 29 | 2 | 30 | 9 | 9 | 4.0 |
| plateau/7/0.3/wet20/False | 30 | 29 | 2 | 30 | 10 | 10 | 4.0 |
| plateau/12/0.0/dry20/False | 30 | 30 | 2 | 30 | 30 | 30 | 3.0 |
| plateau/12/0.0/none/False | 30 | 30 | 1 | 30 | 30 | 30 | 4.0 |
| plateau/12/0.0/wet20/False | 30 | 30 | 1 | 30 | 30 | 30 | 4.0 |
| plateau/12/0.3/dry20/False | 30 | 28 | 0 | 30 | 20 | 20 | 4.0 |
| plateau/12/0.3/none/False | 30 | 29 | 0 | 30 | 17 | 17 | 4.0 |
| plateau/12/0.3/wet20/False | 30 | 29 | 0 | 30 | 16 | 16 | 4.0 |
| plateau/30/0.0/dry20/False | 30 | 30 | 0 | 30 | 30 | 30 | 3.0 |
| plateau/30/0.0/none/False | 30 | 30 | 0 | 30 | 30 | 30 | 4.0 |
| plateau/30/0.0/wet20/False | 30 | 30 | 0 | 30 | 30 | 30 | 4.0 |
| plateau/30/0.3/dry20/False | 30 | 30 | 0 | 30 | 25 | 25 | 4.0 |
| plateau/30/0.3/none/False | 30 | 30 | 0 | 30 | 25 | 25 | 4.0 |
| plateau/30/0.3/wet20/False | 30 | 30 | 0 | 30 | 25 | 25 | 4.0 |
| stable/7/0.0/dry20/False | 30 | 22 | 0 | 19 | 4 | 4 | 1.0 |
| stable/7/0.0/none/False | 30 | 30 | 0 | 30 | 3 | 3 | 1.0 |
| stable/7/0.0/wet20/False | 30 | 30 | 0 | 30 | 3 | 3 | 1.0 |
| stable/7/0.3/dry20/False | 30 | 2 | 0 | 15 | 4 | 4 | 1.0 |
| stable/7/0.3/none/False | 30 | 3 | 0 | 28 | 2 | 2 | 1.0 |
| stable/7/0.3/wet20/False | 30 | 3 | 0 | 29 | 1 | 1 | 1.0 |
| stable/12/0.0/dry20/False | 30 | 24 | 0 | 30 | 10 | 10 | 1.0 |
| stable/12/0.0/none/False | 30 | 30 | 0 | 30 | 6 | 6 | 1.0 |
| stable/12/0.0/wet20/False | 30 | 30 | 0 | 30 | 4 | 4 | 1.0 |
| stable/12/0.3/dry20/False | 30 | 5 | 1 | 30 | 4 | 4 | 1.0 |
| stable/12/0.3/none/False | 30 | 12 | 5 | 29 | 2 | 2 | 1.0 |
| stable/12/0.3/wet20/False | 30 | 12 | 2 | 29 | 3 | 3 | 1.0 |
| stable/30/0.0/dry20/False | 30 | 30 | 0 | 30 | 26 | 26 | 1.0 |
| stable/30/0.0/none/False | 30 | 30 | 0 | 30 | 21 | 21 | 1.0 |
| stable/30/0.0/wet20/False | 30 | 30 | 0 | 30 | 16 | 16 | 1.0 |
| stable/30/0.3/dry20/False | 30 | 8 | 4 | 30 | 8 | 8 | 1.0 |
| stable/30/0.3/none/False | 30 | 27 | 3 | 30 | 5 | 5 | 1.0 |
| stable/30/0.3/wet20/False | 30 | 27 | 3 | 30 | 7 | 7 | 1.0 |
| stable_sharp/7/0.0/dry20/False | 30 | 23 | 4 | 27 | 3 | 3 | 1.0 |
| stable_sharp/7/0.0/none/False | 30 | 30 | 3 | 30 | 3 | 3 | 1.0 |
| stable_sharp/7/0.0/wet20/False | 30 | 30 | 3 | 29 | 4 | 4 | 1.0 |
| stable_sharp/7/0.3/dry20/False | 30 | 2 | 0 | 15 | 2 | 1 | 2.0 |
| stable_sharp/7/0.3/none/False | 30 | 3 | 0 | 27 | 2 | 1 | 1.0 |
| stable_sharp/7/0.3/wet20/False | 30 | 3 | 0 | 28 | 2 | 1 | 1.0 |
| stable_sharp/12/0.0/dry20/False | 30 | 28 | 2 | 30 | 4 | 4 | 1.0 |
| stable_sharp/12/0.0/none/False | 30 | 30 | 0 | 30 | 3 | 3 | 1.0 |
| stable_sharp/12/0.0/wet20/False | 30 | 30 | 0 | 30 | 4 | 4 | 1.0 |
| stable_sharp/12/0.3/dry20/False | 30 | 8 | 1 | 27 | 5 | 4 | 1.2 |
| stable_sharp/12/0.3/none/False | 30 | 9 | 2 | 29 | 4 | 4 | 1.0 |
| stable_sharp/12/0.3/wet20/False | 30 | 7 | 2 | 30 | 5 | 5 | 1.0 |
| stable_sharp/30/0.0/dry20/False | 30 | 30 | 0 | 30 | 1 | 1 | 1.0 |
| stable_sharp/30/0.0/none/False | 30 | 30 | 0 | 30 | 1 | 1 | 1.0 |
| stable_sharp/30/0.0/wet20/False | 30 | 30 | 0 | 30 | 4 | 4 | 1.0 |
| stable_sharp/30/0.3/dry20/False | 30 | 13 | 1 | 30 | 6 | 6 | 2.0 |
| stable_sharp/30/0.3/none/False | 30 | 29 | 3 | 30 | 1 | 1 | 1.0 |
| stable_sharp/30/0.3/wet20/False | 30 | 27 | 1 | 30 | 1 | 1 | 1.0 |
| uniform/7/0.0/dry20/False | 30 | 0 | 0 | 4 | 2 | 0 | 1.0 |
| uniform/7/0.0/none/False | 30 | 1 | 0 | 2 | 2 | 0 | 1.0 |
| uniform/7/0.0/wet20/False | 30 | 0 | 0 | 3 | 2 | 0 | 1.0 |
| uniform/7/0.3/dry20/False | 30 | 0 | 0 | 2 | 2 | 0 | 2.5 |
| uniform/7/0.3/none/False | 30 | 0 | 0 | 1 | 1 | 0 | 3.0 |
| uniform/7/0.3/wet20/False | 30 | 0 | 0 | 1 | 1 | 0 | 3.0 |
| uniform/12/0.0/dry20/False | 30 | 1 | 0 | 1 | 2 | 0 | 1.0 |
| uniform/12/0.0/none/False | 30 | 1 | 0 | 3 | 2 | 0 | 1.0 |
| uniform/12/0.0/wet20/False | 30 | 0 | 0 | 4 | 3 | 0 | 1.0 |
| uniform/12/0.3/dry20/False | 30 | 0 | 0 | 4 | 3 | 0 | 2.2 |
| uniform/12/0.3/none/False | 30 | 0 | 0 | 3 | 4 | 0 | 1.8 |
| uniform/12/0.3/wet20/False | 30 | 0 | 0 | 5 | 1 | 0 | 2.2 |
| uniform/30/0.0/dry20/False | 30 | 1 | 0 | 2 | 2 | 0 | 1.0 |
| uniform/30/0.0/none/False | 30 | 2 | 0 | 3 | 2 | 0 | 1.0 |
| uniform/30/0.0/wet20/False | 30 | 0 | 0 | 5 | 4 | 1 | 1.0 |
| uniform/30/0.3/dry20/False | 30 | 0 | 0 | 2 | 3 | 1 | 2.0 |
| uniform/30/0.3/none/False | 30 | 0 | 0 | 3 | 1 | 0 | 2.0 |
| uniform/30/0.3/wet20/False | 30 | 0 | 0 | 6 | 1 | 0 | 2.0 |

Counts variant (stable, drift; 12 years):

| cell | n | harmonic accept | harmonic wrong month | trough p<0.05 | peak p<0.05 | seasonal | median set width |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| drift/12/0.0/dry20/True | 30 | 2 | 0 | 3 | 5 | 0 | 1.0 |
| drift/12/0.0/none/True | 30 | 1 | 0 | 3 | 2 | 0 | 1.0 |
| drift/12/0.0/wet20/True | 30 | 1 | 0 | 4 | 3 | 0 | 1.0 |
| drift/12/0.3/dry20/True | 30 | 1 | 0 | 2 | 1 | 0 | 1.0 |
| drift/12/0.3/none/True | 30 | 1 | 0 | 2 | 0 | 0 | 2.0 |
| drift/12/0.3/wet20/True | 30 | 0 | 0 | 2 | 3 | 0 | 1.8 |
| stable/12/0.0/dry20/True | 30 | 24 | 0 | 30 | 11 | 11 | 1.0 |
| stable/12/0.0/none/True | 30 | 30 | 0 | 30 | 5 | 5 | 1.0 |
| stable/12/0.0/wet20/True | 30 | 30 | 0 | 30 | 6 | 6 | 1.0 |
| stable/12/0.3/dry20/True | 30 | 5 | 1 | 30 | 4 | 4 | 1.0 |
| stable/12/0.3/none/True | 30 | 12 | 5 | 29 | 2 | 2 | 1.0 |
| stable/12/0.3/wet20/True | 30 | 12 | 2 | 29 | 3 | 3 | 1.0 |

## 3. Observations

All counts below are out of 30 unless stated otherwise; comparisons use no pixel counts.
The table?s ?harmonic wrong month? counts anchors outside the union of strict
annual minimum months. On plateau records this can count a month inside the
July?October near-minimum plateau as wrong; it is not a test of plateau membership.

- With floods and no gaps, trough rejection on stable records was 28, 29 and 30 at 7, 12 and 30 years. On drift it was 2, 2 and 1, respectively.
- With floods and no gaps, harmonic acceptance on stable records was 3, 12 and 27; wrong-month counts were 0, 5 and 3, respectively.
- With floods, dry20 changed stable trough rejections from 28 to 15, 29 to 30, and 30 to 30 at 7, 12 and 30 years; seasonal counts changed from 2 to 4, 2 to 4, and 5 to 8.
- Pixel counts changed outcomes in this grid: among 360 paired records, six regime classifications changed. For example, stable/12/0.0/none had six seasonal records without counts and five with counts; stable/12/0.0/dry20 had 10 without counts and 11 with counts.
- Without floods or gaps, stable records were seasonal 3, 6 and 21 times at 7, 12 and 30 years; plateau records were seasonal 18, 30 and 30 times. With floods and no gaps the corresponding counts were 2, 2 and 5 for stable and 9, 17 and 25 for plateau. Other gap cells are in the table.
- Without floods or gaps, peak rejections for stable versus stable_sharp were 3 versus 3 at 7 years, 6 versus 3 at 12 years, and 21 versus 1 at 30 years. The gap persists at 30 years.
- At 30 years without floods, wet20 changed peak rejections from 1 to 7 for drift and from 21 to 16 for stable. With floods, the corresponding changes were 2 to 2 and 5 to 7.

## 4. Deviations from the plan

- Task 3: the initial parallel pytest command failed with `PermissionError: [Errno 13] Permission denied: 'C:\Users\00101125\AppData\Local\Temp\pytest-of-00101125\pytest-46991\.lock'`. A workspace `--basetemp` allowed the slow run to pass. Other tests using temporary files ran outside the sandbox.
- Task 7: the counts command generated 12 cells, not the expected 8, because its default gaps include wet20. The default grid also includes stable_sharp and wet20, contrary to the shorter list in the Task 8 template; the description above reflects the actual 90-cell grid.
- Task 7: PowerShell's combined stdout/stderr redirection reported `NativeCommandError` for progress lines written to stderr and returned exit code 1. All three sweep commands wrote their complete CSV and summary files. The default output contains 90 cells, counts output 12, and null output one.
- Task 7: the 30-year drift/0.0/wet20 peak count was 7/30, not the pilot reference 12/30. The counts variant changed classifications on six paired records, contrary to the plan's expectation of no effect.
- MkDocs build emitted a Material for MkDocs advisory about MkDocs 2.0; build completed successfully.
- Review added a warning to the frozen-window summary for missing rank comparisons, and clarified strict-minimum membership in the sweep documentation. The pre-registered decision rule and recorded counts remain unchanged.

## 5. What this does and does not establish

All records are synthetic, 12 calendar months per year, with at most one flood
per year and no classification error. Nothing here validates the external
windows; that is step 2 of the verdict and waits on frozen fixtures
(`scripts/frozen_window_recurrence.py` is ready for them). The broad-tie-set
hole mechanism (peak sets that are wide, plus a calendar month that can never
hold a peak) is a hypothesis from one pilot; peak-set widths on real records
are unknown, and the runner now reports them.
The frozen runner?s pre-registered rule treats a missing external rank as
agreement: outcome A without ranks does not establish agreement with an external
rank. Supply ranks for every window to assess that part of the rule.
