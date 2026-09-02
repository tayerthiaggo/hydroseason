# HydroSeason 0.2.0 decision-policy design

Status: promoted. Every item in the promotion checklist below has passed
(synthetic calibration, untouched validation, protected-baseline review, the
three motivating records, and an independently reviewed real cohort), and
`established_0_2_0` is the public policy identifier. `established_0_1_1` is
the prior released baseline these gates were measured against.

This document is authoritative with `docs/decision-policy.md` and
`docs/hydrological-state.md` for the v0.2.0 policy. It defines what HydroSeason
may claim about annual timing; it does not turn an operationally selected date
into scientific evidence of a precise boundary.

## Public decision contract

The public timing vocabulary is:

```python
TimingStatus = Literal["point", "interval", "unresolved"]
TimingEvidence = Literal["supported", "insufficient", "unsupported"]
PixelSupportStatus = Literal["available", "unavailable"]
```

`n_usable_years` is the quality/coverage count. It remains distinct from
`n_peak_timing_years` and `n_trough_timing_years`, which count annual extrema
that are informative for each side of the cycle. The existing
`n_timing_years` keeps its peak-derived meaning and equals
`n_peak_timing_years`; the conservative minimum is used only when the route
gate is written explicitly.

For each usable annual record, resolution is count-aware when counts exist:

```text
peak_resolution_pp = 100 / peak_n_valid, or 0 when peak_n_valid is absent/zero
trough_resolution_pp = 100 / trough_n_valid, or 0 when trough_n_valid is absent/zero
detectability_floor_pp = max(measurement_tolerance_pct, robust_noise_pp,
  peak_resolution_pp, trough_resolution_pp, machine epsilon)
amplitude_pp = annual_max_pp - annual_min_pp
amplitude_to_floor_ratio = 0 when amplitude_pp <= detectability_floor_pp,
  otherwise amplitude_pp / detectability_floor_pp
```

The detectability test requires positive amplitude, the calibrated minimum
amplitude-to-floor ratio, and the calibrated minimum peak-water-pixel count
when pixel support is available. With percentage-only inputs, pixel support is
`unavailable` and the pixel-count condition is skipped, not failed.

Equivalent peak and trough month sets include every usable month within the
detectability floor of that extremum. Their shortest circular span determines
the independent status: `point` at or below the point-span threshold,
`interval` at or below the interval-span threshold, and `unresolved` otherwise.
Undetectable years have empty equivalent-month sets and unresolved peak and
trough status. A broad plateau is therefore an interval or unresolved result,
not a fabricated exact date.

Exact-zero diagnostics are reported but never used as a route or timing
predicate: zero frequency is descriptive only. In particular,
`n_zero_months`, `zero_month_fraction`, and `n_whole_zero_years` do not decide
whether a year is detectable.

Record timing evidence is `insufficient` when
`min(n_peak_timing_years, n_trough_timing_years)` is below
`min_informative_years`; it is `unsupported` when the established
seasonality/uniformity evidence rejects an annual cycle; otherwise it is
`supported`. `min_informative_years` is separate from the challenger-path
`EvidenceThresholds.min_timing_years` and its override; neither threshold may
be merged or re-derived from the other.

The established route is `per_year_detection` only for seasonal or marginal
records with supported timing evidence. A seasonal or marginal record with
insufficient identifiable timing retains its regime but routes to
`event_characterisation`. Unsupported timing remains a separate diagnostic.
Flat and below-floor years remain valid dry observations and continue to
contribute to dry-duration and event summaries; they contribute no peak or
trough timing observation.

## Frozen calibration grid and selection

Every numeric policy threshold must come from this predeclared grid:

```python
TIMING_IDENTIFIABILITY_GRID = {
    "min_amplitude_to_floor_ratio": [1.0, 1.5, 2.0, 3.0],
    "min_peak_water_pixels": [1, 2, 3, 5],
    "max_point_span_months": [0, 1, 2],
    "max_boundary_interval_months": [2, 3, 4],
    "min_informative_years": [5, 7, 10],
}
```

Reject combinations where `max_boundary_interval_months` is smaller than
`max_point_span_months`. Select candidates by retaining synthetic candidates
whose false precise-boundary Wilson upper bound is `<= 0.05`, then maximising
correct abstention on all-zero, below-floor, and broad-plateau negatives;
maximising annualisation recall on detectable intermittent-seasonal positives;
minimising median absolute boundary error on retained positives; and finally
choosing the stricter tuple by larger amplitude ratio, larger peak-pixel count,
smaller point span, smaller interval span, and larger informative-year count.

Untouched synthetic validation is report-only: validation cannot trigger threshold reselection. It uses the calibration-selected tuple and its
fingerprint without writing defaults or searching the grid.

The three motivating records—130413A Denison Creek at Braeside, 130407A Nebo
Creek at Nebo, and 130302A Dawson River at Taroom—are diagnostic examples only.
They are excluded from calibration fitting, threshold selection, and untouched
synthetic validation; their qualitative checks occur only after the policy is
frozen.

## Promotion checklist

Promotion to `established_0_2_0` requires:

1. Zero false point dates on flat or broad-plateau validation years.
2. False precise-boundary Wilson upper bound <= 0.05 on untouched synthetic validation.
The gate is recorded as: false precise-boundary Wilson upper bound <= 0.05.
3. Protected Daly, Fitzroy, Gilbert, Lachlan, and Moonie outcomes pass.
4. No confirmed condition-baseline anchor comes from an unresolved annual row.
5. The three motivating records meet their qualitative acceptance checks.
6. An independently reviewed real cohort reports outcomes, disagreements, and uncertain labels without changing thresholds.
7. Calibration, validation, cohort, comparison, migration, fingerprint, and known-limitation evidence is recorded.

The real cohort is corroborating evidence. A wide real-cohort interval does not
alone block promotion, but a direct contradiction does: a reviewer-labelled
`event_only` or `unobservable` record must not receive a published point date.

## Evidence limits frozen in advance

The current stress bundle is dominated by low zero fractions and supplies too
few high-zero records for an eight-per-stratum design. The cohort therefore
stratifies on amplitude-to-floor ratio, requests `min(8, available)` per
stratum, and reports any shortfall rather than treating it as fatal. The real
stress CSVs are HydroSeason output and contain no pixel counts, so real-cohort
records report `pixel_support_status="unavailable"`; minimum peak-water-pixel
evidence is synthetic-only. Review packets must strip policy and result fields
from those outputs before human review.

Every stochastic test and generated report records the package version, input
fingerprint, threshold fingerprint, and seed. These are required reproducibility
metadata for calibration, validation, and cohort artifacts.
