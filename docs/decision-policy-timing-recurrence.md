# Timing-recurrence candidate: opt-in, not promoted

## Status

`candidate_timing_recurrence` is an opt-in, unpromoted seasonality-classification
candidate, selected with `seasonality_policy="timing_recurrence"` and off by
default. `ESTABLISHED_POLICY remains established_0_2_0`; nothing about this
candidate changes any published regime, route, boundary, or date for an
existing caller who does not opt in.

## The rule

The candidate detrends the monthly record with a
`centred 2x12 moving average`, then works on the detrended series. For each calendar year it takes
the tie-aware set of months attaining that year's annual peak and annual
trough, with the tie tolerance widened by the year's own trend range (so a
year crossing a strong trend does not spuriously narrow to a single month).
Each of the two month-sets — peak timing across years and trough timing
across years — is tested for calendar recurrence with a weighted Kuiper
uniformity test. The record is classified `seasonal` when both the peak test
and the trough test reject uniformity at `alpha = 0.05`; otherwise it is
`aseasonal`, and `aseasonal means recurrence was not established` — it is not
a claim that the record has no cycle, only that this test could not confirm
one recurs on the calendar.

The anchor months used elsewhere in the pipeline are unchanged: they remain
the peak and trough of `mean monthly extent` across the whole record, exactly
as under `established_0_2_0`. This candidate only changes how `seasonal`
versus `aseasonal` is decided; it does not touch anchor-month selection, the
per-year boundary detector, trough refinement, or the resolved-cycle check.

## Validation

Run directory: `case_studies/results/seasonality-timing-recurrence/2026-09-12/`.

Seeds: `SEASONALITY_VALIDATION_SEEDS = range(90000, 95000)`, 54,000 synthetic
records (18 families x 3 lengths x 5 variants x 200 replicates), scored under
both `established_0_2_0` and `candidate_timing_recurrence`, plus the five
protected real records. Acceptance criteria were fixed before any record was
drawn and were not altered in response to a result.

Both acceptance criteria **passed**:

- **false-seasonal Wilson upper bound <= 0.05** per non-seasonal family,
  pooled over lengths (n=600). 0 of 8 non-seasonal families exceeded the
  bound. Worst case: `ar1_0_5` and `ar1_0_8`, 14/600, Wilson upper bound
  0.0358 against the 0.05 gate.
- **detection >= 0.80 at 15 and 30 years**, base variant (n=200) per seasonal
  family. 0 of 14 cells fell under the floor. Worst case: `narrow_pulse` at
  15 years, 194/200 = 0.970, against the 0.80 floor.

All five protected catchments were unchanged: Daly, Fitzroy, and Gilbert
remain seasonal on the per-year route; Lachlan and Moonie remain aseasonal.

The full suite passed (1673 passed) apart from one pre-existing failure
unrelated to this work.

## Limitations

These three findings come directly from the validation run and are recorded
here without softening:

1. **The gate does not distinguish one annual cycle from two.** Records
   carrying two cycles per year are classified `seasonal` 98.5% of the time
   at 15 years and 100% at 30 years, and a six-month phase drift likewise
   passes (96% and 100%). This is correct behaviour for a test of calendar
   recurrence — a twice-yearly signal does recur on the calendar — but it
   means the one-cycle-per-year question belongs to the downstream boundary
   machinery, which still applies its own resolved-cycle requirement, not to
   this gate.
2. **Pixel quantisation is the hardest positive case.** A cycle whose
   amplitude is about one pixel is declined by the calibrated detectability
   floor even at 30 years. This is the floor doing its job against a
   genuinely marginal signal, not a defect, but it is real power loss and
   must be read as such.
3. **Persistent noise consumes most of the false-positive budget.**
   `alpha = 0.05` was load-bearing, not a conservative default with room to
   spare: at `alpha = 0.10`, six family/variant cells breach the
   false-seasonal bound while detection gains almost nothing. The AR(1)
   families are this test's hardest negative case.

## What promotion still requires

This candidate is **not promoted**. `ESTABLISHED_POLICY remains
established_0_2_0`. Promotion would still require the independent CAMELS-AUS
cohort, migration notes, and removal of the deprecated `climatological_*`
aliases, in addition to every other item in the promotion gate in
[`decision-policy.md`](decision-policy.md).
