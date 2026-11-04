# L1 follow-ups: does a misdated trough matter for the baseline (B1), and why the boundary skips a lower month (D1)

Run 2026-11-03 on the L1 seasonal records (600 synthetic, 574 injected) with the current library. These are measurements, not pre-registered tests: they inform decisions and decide nothing. Script `scripts/l1_followups.py`; output [2026-11-03-l1-followups-results.json](2026-11-03-l1-followups-results.json). The run reused the L1 corpus, checked against its receipt, and changed nothing in the library. No run raised an error; 669 of 1,174 records were routed to per-year detection.

## Summary

- **B1. A misdated trough boundary does not change the dry level the baseline reads.** Where the true dry level is known (arm S), misdated boundaries report it as closely as correctly dated ones. The median error is 0.48 floors against 0.52 floors, and 19.5% against 20.1% are more than one floor off. The boundary sits at the lowest observed month, so it reads the season's low wherever that falls.
- **B1. The `point` requirement buys no accuracy in the condition labels, and it costs most of their coverage.** Under today's rule, only 4.9% (arm S) and 21.7% (arm I) of cycles get a peak (recharge) condition label. Most records have too few eligible cycles: 18 of 369 records in arm S have any label, and 65 of 300 in arm I. Counting any dated timing status instead labels 36.3% and 66.1% of cycles. On the cycles both rules label, the relaxed rule agrees with the known truth as often or slightly more often: 0.723 against 0.682 in arm S, and 0.503 against 0.479 in arm I.
- **D1. The boundary step skips a lower month for two designed reasons, and neither costs accuracy overall.**
  - Usually the lower month is cloudy (more than 20% invalid), and the trough selection screens cloudy months out (`selection_status="quality_adjusted"`).
  - Otherwise the lower month lies beyond the trough search window, which the library flags (`outside_window_lower`).
  - Across every cycle where the cloud screen moved the boundary, the screened month is right as often as the cloudy one in arm S (63.1% against 62.4%), and more often in arm I (65.3% against 58.3%).

## B1. The baseline and a misdated boundary

The condition baseline ranks each cycle's `peak_extent_pct` and `trough_extent_pct` against the baseline-eligible cycles (`_condition.classify_annual_surface_water_condition`). Eligibility requires a complete cycle, a `confirmed` boundary, a peak that is not `anomalous`, and aggregate `timing_status == "point"`. So a misdated boundary could matter in two ways: through the trough level it reads, or through which cycles are allowed into the baseline.

### The trough level

Reported `trough_extent_pct` minus the true dry level, in detectability floors. This is arm S only, where every season has the same noise-free dry level.

| Trough boundary | Cycles | Median | Median absolute | More than 1 floor off |
| --- | ---: | ---: | ---: | ---: |
| Correct (within a month) | 5,078 | −0.45 | 0.52 | 20.1% |
| Misdated | 2,007 | −0.43 | 0.48 | 19.5% |
| Correct, baseline-eligible today | 416 | −0.61 | 0.66 | 27.9% |
| Misdated, baseline-eligible today | 129 | −0.75 | 0.78 | 34.9% |

Both sit slightly below the truth, as the minimum of noisy months does. In arm I the true dry level includes the real background and is unknown. There, a misdated boundary reads a month that is genuinely lower than the true trough month (median 1.0 floor lower; 2.3 floors for baseline-eligible cycles). That is a real low in the observed water, not an error in the level.

### Which cycles enter the baseline

Peak (recharge) condition labels were recomputed under three eligibility rules. Each was called exactly as the library calls it, and the recomputation of today's rule reproduces every library label.
- E0: today's rule, aggregate `point` only.
- E1: any dated aggregate status (`point`, `interval` or `broad`).
- E2: no timing requirement.

The truth is each season's known year factor, ranked across the record's seasons and cut at the 20th and 80th percentiles, as the library cuts.

| | Arm S, E0 | Arm S, E1 | Arm I, E0 | Arm I, E1 |
| --- | ---: | ---: | ---: | ---: |
| Cycles with a known true peak | 7,065 | 7,065 | 10,921 | 10,921 |
| Cycles with a label | 343 (4.9%) | 2,566 (36.3%) | 2,374 (21.7%) | 7,216 (66.1%) |
| Records with any label | 18 of 369 | 134 of 369 | 65 of 300 | 198 of 300 |
| Median eligible cycles per record | 1 | 4 | 2 | 6 |
| Agreement with truth, cycles labelled under both | 0.682 | 0.723 | 0.479 | 0.503 |
| Agreement if labels were independent of truth | | 0.440 | | 0.423 |

E2 gives the same labels as E1 on these records.

The labels themselves are weak here, close to chance in arm I. Arm I's truth leaves out the real background's own wet and dry years, so it understates their accuracy there. The trough (refuge) labels have no truth in this corpus, because the dry level does not vary between seasons.

**Reading.** Requiring `point` does not make the labels more accurate. It leaves most records with an `insufficient_baseline`. This matches the published Fitzroy example, where 1 cycle of 21 is eligible.

## D1. Why the boundary step passed over a lower month

L1 found that some missed `point` troughs had a strictly lower month among the next three, more often in arm I. Each such case was matched against the library's own diagnostic columns.

| | Arm S | Arm I |
| --- | ---: | ---: |
| Missed `point` troughs with a strictly lower month in the next 3 | 59 | 310 |
| The lower month is more than 20% invalid (screened out as cloudy) | 54 | 240 |
| The lower month lies beyond the trough search window | 5 | 88 |
| Median depth of the lower month below the boundary | 0.6 floors | 2.1 floors |

The two reasons can overlap. Trough refinement never moved one of these boundaries earlier.

Among these misses, the cloudy month was the true trough month in 40 of 54 (arm S) and 151 of 240 (arm I) cases. That subset was chosen on misses, so it says little about the screen. The fair comparison is every cycle where the selection moved off the raw minimum:

| Selection status | Arm S cycles | Selected month correct | Raw minimum correct | Arm I cycles | Selected month correct | Raw minimum correct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `quality_adjusted` (cloud screen) | 631 | 398 | 394 | 2,134 | 1,393 | 1,245 |
| `coherence_adjusted` (tie resolved for sequence) | 351 | 237 | 95 | 816 | 707 | 325 |

The cloud screen is neutral in arm S and helps in arm I. The sequence tie-break helps in both. Nothing here argues for a change. The search-window cases (88 in arm I) are already reported by `outside_window_lower`.

## What follows

**Proposed for `hydroseason-v0.3.0`; each needs the project lead's decision.**
1. **Relax the baseline's timing requirement from `point` to any dated status (E1).** On these records it labels about seven times as many cycles in arm S, and three times as many in arm I. On the cycles both rules label, it is at least as accurate. Before adoption:
   - measure its effect on real records (the G1 windows) and on the case-study tables;
   - and update the docs, which call `point` "a defensible exact date".
2. **No change to the cloud screen or the sequence tie-break.**

## Limits

- **Not pre-registered.** These were measured after L1 and are reported as measurements. A baseline change would need its own pre-registered check on fresh records.
- **Modelled seasons.** The truth is the generator's year factor. Arm I's truth leaves out the real background's own variation.
- **Peak labels only.** The trough labels have no truth in this corpus.
- **Not accuracy for real places.**

## Provenance

- **Code:** `scripts/l1_followups.py` (stages `run`, `analyse`), run with `./.venv/Scripts/python.exe`. It reads the L1 corpus and checks it against the L1 receipt. It redraws each record's hidden generator parameters and asserts that they match the corpus.
- **Runs:** `D:\RLH\5.6\data_local\intermediate\hydroseason_l1_followups\runs.jsonl` and `followups.log`, 2026-11-03 10:53 to 12:10. Analysis 12:13.
- **Guards:** `tests/test_l1_followups.py`.
