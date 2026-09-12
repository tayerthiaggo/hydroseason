# Timing-recurrence candidate: validation findings

Run commit `5ac3003`. 54,000 synthetic records (18 families x 3 lengths x 5 variants
x 200 replicates), each scored under `established_0_2_0` and under
`candidate_timing_recurrence`, plus the five protected real records. Criteria were
fixed in the design before any record was drawn and were not altered in response to
any result.

## 1. Acceptance verdict: both criteria PASS

| Criterion | Result | Worst case |
|---|---|---|
| 1. False seasonal, one-sided 95% Wilson upper bound <= 0.05 per non-seasonal family, pooled over lengths (n=600) | **PASS**, 0 of 8 families over bound | `ar1_0_5` and `ar1_0_8`, 14/600, bound 0.0358 |
| 2. Detection >= 0.80 per seasonal family at 15 and 30 years, base variant (n=200) | **PASS**, 0 of 14 cells under floor | `narrow_pulse` at 15 y, 194/200 = 0.970; every other cell 1.000 |
| 3. Criterion 1 still holds under 25% missing months | **PASS** | `ar1_0_8` missing_25, 8/600, bound 0.0235 |
| 4. Status accounting: insufficiency never reported as aseasonal | **PASS** | 3,659 insufficient records, all reported separately |

## 2. Where insufficiency falls, and why it is benign

3,659 of 54,000 records (6.8%) returned `insufficient_record` with reason
`trend_unavailable`. Every one is in a gap variant:

| length | missing_10 | missing_25 |
|---|---|---|
| 7 y | 440 | 3,171 |
| 15 y | 0 | 48 |
| 30 y | 0 | 0 |

None in `base`, and **zero in the detection cells** (0 of 2,800 seasonal base records
at 15 and 30 years), so no detection denominator is contaminated.

The cause is structural and was predicted: the centred 2x12 moving average leaves the
first and last six months without a trend, so a 7-year record has exactly 5
trend-eligible years — the minimum. Any blanked month pushes it under. **Practical
floor: roughly 8 or more calendar years for a record with appreciable gaps.**

## 3. Protected records: no baseline change

| record | established | candidate | peak p | trough p | agrees |
|---|---|---|---|---|---|
| Daly | seasonal / per_year | seasonal / per_year | 0.001 | 0.002 | yes |
| Fitzroy | seasonal / per_year | seasonal / per_year | 0.001 | 0.001 | yes |
| Gilbert | seasonal / per_year | seasonal / per_year | 0.001 | 0.001 | yes |
| Lachlan | aseasonal / events | aseasonal / events | 0.262 | 0.139 | yes |
| Moonie | aseasonal / events | aseasonal / events | 0.232 | 0.009 | yes |

All five protected outcomes are unchanged, so promotion-gate item 5 (evidence for a
protected-baseline change) requires nothing.

Moonie is instructive: its trough timing does recur (p = 0.009) while its peak timing
does not (p = 0.232). The conjunction rule therefore declines it. A dry season that
returns on schedule is not on its own evidence of one interpretable annual cycle.

## 4. Where the two policies disagree

16,950 of 54,000 records (31.4%). **17 of the 18 families disagree somewhere**; only
`all_zero` never does. Direction matters more than volume.

| family | disagreements | candidate seasonal, established not | established annual, candidate not | of which insufficient |
|---|---|---|---|---|
| white_noise | 2,057 | 0 | 2,057 | 116 |
| annual_plus_strong_trend | 1,958 | **1,458** | 500 | 84 |
| events | 1,779 | 3 | 1,776 | 97 |
| ar1_0_5 | 1,662 | 16 | 1,646 | 115 |
| amplitude_curve | 1,287 | 9 | 1,278 | 112 |
| phase_drift | 1,272 | 61 | 1,211 | 118 |
| two_cycles | 1,157 | 141 | 1,016 | 108 |
| ar1_0_8 | 1,115 | 13 | 1,102 | 106 |
| narrow_pulse | 1,098 | 0 | 1,098 | 112 |
| timing_jitter | 813 | 0 | 813 | 106 |
| annual_plus_trend | 722 | 113 | 609 | 100 |
| asymmetric | 652 | 0 | 652 | 105 |
| sinusoid | 532 | 0 | 532 | 108 |
| step | 276 | 2 | 274 | 91 |
| trend | 267 | 5 | 262 | 95 |
| strong_trend | 198 | 2 | 196 | 69 |
| zero_dominated_pulse | 105 | 0 | 105 | 105 |
| all_zero | 0 | 0 | 0 | 0 |

Two effects the candidate gets right:

- **It recovers trended annual records the established gate loses.** 1,458
  `annual_plus_strong_trend` records are seasonal to the candidate and not annual to
  the established policy, plus 113 more in `annual_plus_trend`. This is the design's
  counterexample reproduced at scale: the SNR denominator absorbs trend, so a real
  annual cycle plus a trend reads as flat.
- **It rejects noise the established gate admits.** All 2,057 `white_noise`
  disagreements, and nearly all `events` and AR(1) disagreements, are records the
  established policy calls seasonal or marginal while the candidate declines them.

### 4.1 Correction: genuine power loss under pixel quantisation

An earlier draft of this section claimed the `narrow_pulse` and `timing_jitter`
disagreements were not candidate misses but short-record and gap-variant records
returning `insufficient_record`. **That was wrong**, and the correction matters:

| family | disagreements | actually insufficient | confident ok/aseasonal |
|---|---|---|---|
| narrow_pulse | 1,098 | 112 (10%) | 986 |
| timing_jitter | 813 | 106 (13%) | 707 |

Their distribution by variant and length:

| narrow_pulse | 7 y | 15 y | 30 y |
|---|---|---|---|
| base | 104 | 6 | 0 |
| low_state_gap | 135 | 9 | 0 |
| missing_10 | 125 | 4 | 0 |
| missing_25 | 100 | 73 | 0 |
| **pixel_rounded** | 199 | 192 | **151** |

`timing_jitter` behaves the same way: 196 / 181 / 95 across 7, 15 and 30 years under
`pixel_rounded`, against 51 / 0 / 0 in `base`.

The bulk of these disagreements are **confident candidate rejections of records whose
truth is seasonal**, concentrated in `pixel_rounded` — a quantisation stressor, not a
gap variant — and persisting at a full 30 years, where neither a short record nor
missing months can explain them. Scaling extent by 0.02 onto a 1,000-pixel grid leaves
a narrow pulse spanning about one pixel, and the calibrated detectability floor then
declines the year. That is the floor doing its job rather than a bug, but it is real
power loss and must not be described as bookkeeping.

It does not disturb the acceptance verdict: both families clear the 0.80 detection
floor comfortably on the base variant at 15 and 30 years, which is what criterion 2
measures. `pixel_rounded` is reported, not gated.

## 5. Alpha sensitivity: 0.05 was the right pre-registered choice

| alpha | worst false-seasonal bound | families over 0.05 | worst detection |
|---|---|---|---|
| 0.05 | 0.0358 | 0 | 0.970 |
| 0.10 | 0.0891 | 6 | 0.995 |

At alpha = 0.10 six family/variant cells breach the false-seasonal bound — both AR(1)
families, worst `ar1_0_8` at 42/600 (0.0891) — while detection gains almost nothing
(0.970 to 0.995). Persistent noise is what the margin is spent on, and 0.10 would have
failed criterion 1.

## 6. Finding that contradicts the design's stated limitation

The design states that twice-yearly regimes are "mostly aseasonal (5-22% seasonal in
the pilot)". **The full run refutes this**, on the base variant:

| reported-only family | 7 y | 15 y | 30 y |
|---|---|---|---|
| two_cycles | 0.42 | 0.985 | 1.000 |
| phase_drift | 0.27 | 0.960 | 1.000 |
| amplitude_curve | 0.55 | 0.670 | 0.825 |

The pilot ran a weaker variant of the rule: informative years only, no widened
tolerance. The approved rule uses every detectable year with tie-aware month sets,
which is materially more powerful — including on records with two cycles per year,
whose peaks and troughs both recur perfectly well on the calendar.

This is correct behaviour for a *recurrence* test and it is not a defect. But the
consequence must be stated plainly rather than buried:

- **The gate does not distinguish one annual cycle from two.** A six-month cycle passes
  it at 15 years or more.
- The one-cycle-per-year question belongs to the downstream boundary machinery, which
  still applies its own resolved-cycle requirement.
- The design's section 7 limitation text and the draft Methods paragraph both need
  correcting before the manuscript uses them. Phase drift of six months across a record
  likewise passes at 15 years or more, where the design implied it would not.

## 7. Other limits observed

- Short records are weak: at 7 years no seasonal family exceeds 0.42 on the
  reported-only set, and detection is not claimed there. 7-year results are reported,
  never used for acceptance.
- `amplitude_curve` at 0.670 (15 y) is the weak-signal regime behaving as expected: a
  cycle whose amplitude is comparable to the noise is often not established.
- The AR(1) families consume most of the false-positive budget. Persistent noise, not
  trend, is this test's hardest negative.
- Low extent on a coarse pixel grid is the hardest positive: see section 4.1. A cycle
  whose amplitude is about one pixel is declined by the detectability floor even at 30
  years.
- Only the five protected records were scored. Kakadu and Roper, which the design lists
  as descriptive-only, are not in `case_studies/data/extent/` — Roper lives under
  `output/water_extent_csv/` and Kakadu under a stress-test report directory — so the
  run's `*_30m.csv` glob did not reach them. They remain unscored.
- The per-record dump `synthetic_records.csv` is 10.3 MB, about seven times the next
  largest tracked file under `case_studies/results/`. The run is fully reproducible
  from the frozen commit and seed range in `protocol.json`, so a future policy could
  keep only the summary CSVs in git.
