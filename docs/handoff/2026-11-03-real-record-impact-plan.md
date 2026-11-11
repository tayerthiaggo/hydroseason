# Real-record impact: the baseline timing requirement, and the trough label/date mismatch (measurement plan)

Status: written 2026-11-03, before any run. The script records this file's SHA-256 in its results, and later edits are reported as deviations. This is a measurement plan, not a pass/fail test. There is no known truth on real records, so it measures coverage, agreement between independent pixel halves, and frequency. The project lead decides.

## Why

Two candidates for `hydroseason-v0.3.0` came out of B1 and L2 ([B1/D1 results](2026-11-03-l1-followups-results.md), [L2/R1 results](2026-11-03-l2-r1-results.md)). Each needs its effect on real records measured first.

- **Baseline timing requirement.** Today a cycle can anchor the condition baseline only if its aggregate `timing_status` is `point` (rule E0). On known-truth records, allowing any dated status (`point`, `interval` or `broad`; rule E1) labelled far more cycles and was at least as accurate.
- **Label/date mismatch.** In 13% of injected `point` trough cycles, the one-month trough interval was an earlier, cloudy month that the trough selection screened out. The row still reported `point` for the later boundary month (`trough_date`).

## Records

All runs use the current library, unchanged, with `analyze_catchment(..., phase_scheme="two_phase", quality_policy="flag")` on count input. They go through `scripts/l1_followups.py`'s `_run`, which also recomputes the condition labels under E0, E1 and E2 exactly as the library calls them.

| Source | Records | Years |
| --- | --- | --- |
| G1 windows ([G1 plan](2026-11-02-g1-gate-calibration-plan.md)) | 319 windows × 5 units (core, about 236 km²; four quadrants, about 59 km²) × 2 independent pixel halves = 3,190 | 1988–2025 |
| Spatial unit study | 1,278 units in the five case-study catchments (whole catchment, HydroBASINS levels 6–8, tiles at matching sizes) | 2005–2025 |

## M1. The baseline timing requirement (E0 against E1)

Rule E2 (no timing requirement) is reported alongside.

1. **Coverage.** Among units routed to per-year detection, by source and unit scale:
   - the share of units with a baseline, that is, at least `min_baseline_cycles` eligible cycles;
   - the share of cycles with a recharge label and with a refuge label (`low`, `typical` or `high`);
   - the median number of eligible cycles per unit.
2. **Agreement between pixel halves (G1 windows only).** Cycles of the two halves of one unit are matched by peak month, within 6 months, as in G1. For each matched pair labelled in both halves, the labels either agree or not. Recharge and refuge labels are scored separately. The following are reported:
   - agreement on pairs labelled under E0;
   - agreement on pairs labelled under E1;
   - agreement on pairs labelled under E1 but not under E0 (the added pairs);
   - chance agreement, from each half's label shares.

   The difference, added pairs minus E0 pairs, gets a 95% interval from a 2,000-draw bootstrap over windows (seed 0).
3. **Case-study tables.** For each whole case-study catchment: route, cycles, eligible cycles and labelled years under E0 and E1, with each year's labels.
4. **Label stability.** On cycles labelled under both E0 and E1 in the same record, the share whose recharge or refuge label changes.

**Reading, fixed in advance (M1.2):**
- If the 95% interval of added minus E0 lies wholly below −0.05, relaxing adds labels that repeat less often between halves. That is evidence against E1.
- If its lower end is at least −0.05, there is no evidence of a reproducibility cost.
- Otherwise the measurement is inconclusive.

Agreement between halves measures repeatability, not accuracy. The lead decides.

**Amendment, made before the main run (2026-11-03 14:20).** A 20-record smoke run (two G1 windows, both halves) gave no E0 baseline at all, so the E0 comparison above may have too few pairs to read. Only the record counts and the 20 smoke records had been seen. Two measures are added; the reading above still applies where it can be evaluated.
- **Primary for M1.2 if E0 has fewer than 100 labelled pairs.** Among pairs labelled under E1, compare agreement on pairs where both halves' cycles have aggregate timing `point` against pairs where at least one does not. The difference is non-`point` minus `point`, with the same bootstrap and the same reading: an interval wholly below −0.05 is evidence that the `point` requirement guards repeatability; a lower end of at least −0.05 means no evidence of a cost; anything else is inconclusive.
- **Reported:** Cohen's kappa between halves for E1 labels, with a bootstrap interval over windows.

## M2. The trough label/date mismatch

Among `point` trough cycles (`trough_timing_status == "point"`) of units routed to per-year detection, by source and unit scale:
1. the share whose trough interval is not the boundary month alone (`trough_interval_start` or `trough_interval_end` differs from `trough_month`);
2. of those, the share whose interval month is more than 20% invalid, the side it falls on (before or after the boundary), and the `selection_status`.

This is reported as frequencies only, with no threshold.

## Checks

- Every record ran without error, or the errors are counted and listed.
- The E0 recomputation reproduces every library label and eligibility flag.
- The G1 series files match the hashes in the G1 receipt.

## Limits

- Agreement between halves is not accuracy. Two halves share the same weather, cloud and season, so they can agree on a wrong label.
- The G1 halves are half-resolution records of one place; the spatial-unit-study units are whole records.
- The case-study catchments are large. Three of them are tropical, and the other two (Lachlan, Moonie) route to event characterisation as whole catchments.
