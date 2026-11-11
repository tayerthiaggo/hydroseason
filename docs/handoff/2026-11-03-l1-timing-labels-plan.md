# L1: do the trough timing labels mean what they say? A known-truth test (pre-registration)

Status: **frozen before any outcome**, 2026-11-03. The project lead asked for the next steps after G2. The SHA-256 of this file goes into the receipt before the main runs. Later edits are reported as deviations.

## Background

G2 ([results](2026-11-02-g2-known-truth-gates-results.md)) found, in data it was not designed to decide on, that `point` trough dates miss by more than a month far more often than 5%:
- under the current gates, in their weakest band (ratio 3–6), 42% of `point` dates missed in the synthetic arm and 39% in the injected arm;
- across all ratios, about 29% missed in the synthetic arm and 27% in the injected arm.

The documentation says a `point` status "resolves to an exact month". Baseline eligibility requires an aggregate `point` timing status, because the boundary must be "a defensible exact date".

A rerun of 140 G2 records (discovery only) showed where the trough label comes from:
- About 65% of dated cycles keep the pass-1 label. That label counts the months whose value is within one detectability floor of the cycle minimum (`_timing_identifiability.assess_window_timing`, through `equivalent_extremum_dates`). One floor is about one standard deviation of a single month's noise.
- The other 35% are relabelled by trough refinement, from its own candidate set.
- `point` dates were wrong more often with the pass-1 label than after refinement.

L1 tests two things on fresh records. First, it checks whether the G2 finding holds on records it was not discovered on. Second, it asks whether one simple, standard change to the pass-1 tolerance makes `point` trustworthy without making dates worse or losing records.

The change: two months count as equally low unless they differ by more than a test of the difference between two months allows. Each month's value carries noise of about one floor, so the difference of two months has a standard deviation of √2 floors. The tolerance becomes z × √2 floors, with z taken from the standard normal:

| Setting | z | Tolerance (floors) | Meaning |
| --- | --- | ---: | --- |
| current | — | 1 | today's rule |
| k1 | 1 | √2 = 1.414 | one standard deviation of the difference |
| k2 | 1.645 | 2.326 | one-sided 95% test of the difference |
| k3 | 1.960 | 2.772 | two-sided 95% test of the difference |

These are standard values. None is fitted to the data.

## Principles

- **Known answer.** Every record's trough month is set before any method sees it.
- **Not referenced to gauges.**
- **Fresh records.** No seed overlaps G2's. The G2 corpus found the problem, so it is not used here.
- **Library untouched.** The tolerance is changed only inside worker processes, by wrapping `hydroseason._timing_identifiability.equivalent_extremum_dates` so that, for the trough (`kind="min"`), the tolerance it receives is multiplied by the setting's factor.
  - The peak tolerance is not changed.
  - Each run records the factor it used and a self-test of the wrapper.
  - The identifiability gates stay at 3.0 and 5 pixels.
- **Default is no change.** L1 cannot change the library. A setting that passes becomes a candidate for a later method policy (`hydroseason-v0.3.0`), and only after the checks listed under "If a setting passes".

## Records

The generators are imported unchanged from `scripts/known_truth_gates.py` (G2): `synthetic_record` and `injection_record`, with the same distributions, noise model, borrowed gaps and backgrounds. Every record runs with `analyze_catchment(..., phase_scheme="two_phase", quality_policy="flag")` on count input, once under each of the four settings.

| Set | Seeds | Records |
| --- | --- | ---: |
| Arm S, seasonal | 200000–200599 | 600 (`sine` for even seeds, `pulse` for odd) |
| Arm S, null | 210000–210199 | 200 (100 `flat`, 100 `random_pulse`) |
| Arm I | 220000–220573 | 574 (2 per background: one `sine`, one `pulse`) |
| Pilot (never scored for accuracy) | 230000–230059 (S); 231000–231039 (I) | 100 |

**Truth** is as in G2:
- `pulse`: the true trough month is m;
- `sine`: the true trough month is m or m + 1, and the error is measured to the nearer;
- correct means within 1 month.

## Checks before the freeze (no accuracy computed)

1. **Construction.** G2's 24 noise-free records run under all four settings. Interior trough boundaries must fall at the truth in at least 95% of cycles. A setting that fails is dropped before the freeze, and that is recorded.
2. **Pilot.** The 100 pilot records run under the current setting and k3. Only run times and counts of dated trough boundaries and `point` dates are looked at. If the pilot predicts fewer than 150 `point` trough dates under k3 in either arm of the main corpus, that arm is scaled up before the freeze.

**Construction check outcome (recorded before the freeze).** All four settings put 216 of 216 interior trough boundaries at the truth for each shape, so all four are kept. Every wrapper self-test read back as expected: trough probe counts 2, 3, 4 and 5 for current, k1, k2 and k3, and the peak probe 1 for all.

**Pilot outcome (recorded before the freeze).** The pilot predicts about 1,470 `point` trough dates under k3 in arm S and about 3,230 in arm I, against the 150 required, so the sample sizes stand. Only counts and run times were looked at. A main run takes about 7 s per arm S record and 14 s per arm I record.

## Definitions

- **Trough boundary:** a cycle's `trough_month`. It is the date the cycle uses, whatever its label.
- **Dated:** `trough_timing_status` is `point`, `interval` or `broad`, as in G1 and G2.
- **Point date:** `trough_timing_status` is `point`.
- **Seasonal cycles:** cycles from seasonal records in the arm.

## Decision rules

**C. Confirmation (current setting).** In each arm, the 95% Wilson lower bound of the share of `point` trough dates that are not correct is above 0.05. If this holds in both arms, the G2 finding is confirmed.

A setting **passes** only if all three of the following hold in both arms:

1. **`point` dates are safe.** The 95% Wilson upper bound of the share of `point` trough dates that are not correct is at most 0.05.
2. **Dates are not worse.** Accuracy of all trough boundaries in seasonal cycles, under the setting minus under the current setting, is:
   - at least −0.02 as a point estimate;
   - and at least −0.05 at the lower end of its 95% interval, from a 2,000-draw bootstrap over records (seed 0).
3. **Records are not lost.** The share of seasonal records routed to per-year detection, under the setting minus under the current setting, is at least −0.02. The trough label feeds the route through `min_informative_years`.

A rule whose case count is below 100 in an arm cannot be evaluated, and the setting then does not pass.

**The candidate** is the passing setting with the smallest factor. If none passes, the answer is that changing this tolerance alone does not make `point` trustworthy.

## If a setting passes

Nothing changes in the library. Before any `hydroseason-v0.3.0`:
- the candidate's effect on real records (the G1 windows) is measured: how labels, routes and the number of baseline-eligible cycles change;
- the case-study impact tables are rebuilt;
- the docs are updated;
- the project lead decides.

## Reported, not used to decide

Each item is reported under every setting, by arm and by shape:
- the share of each label (`point`, `interval`, `broad`, `unresolved`, or none) among seasonal cycles that have a trough boundary;
- accuracy by label, and the share of `point` dates at exactly the right month;
- the share of `point` dates that miss by more than a month, by ratio band (3–4, 4–6, 6–10, 10 and up);
- for `interval` and `broad` labels, the share whose reported interval, widened by one month on each side, contains the true month;
- baseline-eligible cycles: how many there are and how accurate they are, using the library's rule (`status == "complete"`, boundary `confirmed`, `peak_quality` not `anomalous`, aggregate `timing_status == "point"`);
- the signed error of `pulse` trough boundaries and of the interval end;
- under the current setting, whether each label came from refinement (`trough_refinement_status` `confirmed` or `provisional`) or from pass 1, and accuracy by source;
- null records: `point` trough dates and routes.

The library's own rise date (`recovery_start_month`, not exported) is the trough boundary plus one month. Its accuracy against the true rise of a `pulse` record (m + 1) therefore equals the trough boundary's accuracy against m, and it is not computed separately.

## Limits stated in advance

- **The noise and the seasons are modelled,** as in G2. Arm I keeps real noise.
- **Only the pass-1 trough tolerance is varied.** Labels set by refinement change only through what pass 1 passes on. The peak tolerance is unchanged.
- **Three standard values are tested, not a fitted optimum.**
- **Not accuracy for real places.**
