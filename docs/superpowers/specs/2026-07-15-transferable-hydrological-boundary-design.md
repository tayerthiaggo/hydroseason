# Transferable Hydrological Boundary Detection Design

Date: 2026-07-15
Status: Approved through review discussion on 2026-07-15
Supersedes detector sections of: `2026-07-15-hydrological-state-design.md`

## 1. Purpose

Build reliable trough-to-trough hydrological boundaries from monthly remotely
sensed surface-water extent. Immediate output must unblock downstream analysis,
while preserving uncertainty and observation provenance. Fitzroy/Kimberley and
Gilbert River are real-data acceptance cases; neither is sufficient alone to
claim universal transferability.

## 2. Decisions

1. Default engine is an explainable robust observed-extrema detector.
2. Raw observations and inferred boundaries remain separate. Raw extrema are
   never silently overwritten.
3. A singleton low is not called a glitch from its value alone. It is selected
   with an ambiguity flag unless independent quality evidence rejects it.
4. Low-water plateaus are contiguous runs, not unordered tolerance sets.
5. Thresholds use observation resolution, robust residual noise, and seasonal
   amplitude rather than a fixed five-percentage-point rule.
6. Boundary status reports evidence: full window, truncation, ambiguity,
   observation quality, and selection stability.
7. Peak detection uses the same robust and quality-aware framework as troughs.
8. One nominal opportunity remains per year. Missing opportunities break cycle
   continuity and never merge neighboring years.
9. A hidden semi-Markov engine is implemented as an opt-in challenger. It does
   not become default unless predeclared validation gates beat the robust engine.
10. No new mandatory runtime dependency is added; NumPy and pandas remain enough.

## 3. Architecture

### 3.1 Boundary candidate module

New `hydroseason/_boundary.py` owns:

- robust amplitude and noise estimation;
- per-window coverage diagnostics;
- raw extrema extraction;
- contiguous equivalent-low/equivalent-high runs;
- anomaly flags;
- one-candidate-per-year sequence selection;
- bootstrap stability.

`hydroseason/_dynamic_year.py` remains cycle assembly: consecutive selected
troughs define a cycle, then peak, midpoint, half-loss, drawdown, persistence,
and pulse metrics are computed.

### 3.2 Observation and inference layers

Each trough opportunity reports:

- raw observed minimum date and extent;
- selected boundary date and extent;
- contiguous low-run start and end;
- expected and usable window counts;
- full/left-truncated/right-truncated/internal-gap window status;
- raw/ambiguous/quality-adjusted selection status;
- numeric support in `[0, 1]`;
- expected-phase shift.

The selected date equals the raw minimum unless another within-uncertainty
candidate gives a more coherent annual sequence. Values outside the
equivalence tolerance never replace the raw minimum without independent
quality evidence.

### 3.3 Adaptive equivalence tolerance

For each series:

```text
amplitude = Q90(extent) - Q10(extent)
residual = extent - calendar_month_median
noise = 1.4826 * MAD(diff(residual)) / sqrt(2)
resolution_t = 100 / n_valid_t when pixel counts exist, else 0
epsilon_t = min(0.10 * amplitude,
                max(resolution_t, noise))
```

If amplitude is zero, only exact ties are equivalent. The 10% cap prevents a
high-noise series from turning most of a window into one plateau. All units are
percentage points and use `_pp` names.

### 3.4 Candidate selection

Within each nominal window:

1. Require configured usable count and coverage fraction.
2. Record raw minimum.
3. Find contiguous months within their adaptive tolerance of the raw minimum.
4. Flag singleton residuals above three robust noise scales as ambiguous; do
   not exclude them solely for this reason.
5. Build equivalent candidates from the contiguous low run.
6. Across years, minimize phase and cycle-length deviation among equivalent
   candidates. Missing year remains an explicit unresolved state.

Sequence optimization is dynamic programming over at most eleven candidates
per year, `O(years * candidates^2)`. Sites are independent and parallelizable.

### 3.5 Peak symmetry

Peak candidates are derived strictly after the previous trough and strictly
before the current trough. They use adaptive high-run tolerance, anomaly flags,
quality diagnostics, and support calculations. Raw maximum and selected peak
are both retained.

### 3.6 Boundary status and downstream use

- `confirmed`: full search window, sufficient coverage, selected support at or
  above 0.80, and no unresolved anomaly.
- `provisional`: a date exists but window is truncated, coverage is incomplete,
  support is below 0.80, or anomaly remains ambiguous.
- `unresolved`: no defensible candidate exists.

Partial/provisional cycles may feed timing workflows but do not enter default
historical condition baselines. `confidence` is retained for compatibility but
documented as a quality grade until held-out calibration demonstrates that it
estimates timing correctness.

### 3.7 Hidden semi-Markov challenger

New `hydroseason/_semi_markov.py` models four cyclic latent states:

```text
wet -> recession -> dry -> recovery -> wet
```

Inputs are robust-scaled extent, monthly slope, observed fraction, and seasonal
phase. State emissions use robust Gaussian costs with quality-dependent scale.
Explicit duration distributions prevent one noisy month from creating a state
transition. Log-space forward recursion, backward recursion, and Viterbi decode
return posterior state probabilities and most likely path.

Trough boundary is highest-posterior final month of the dry state near expected
phase. Peak is highest-posterior wet-state maximum inside consecutive troughs.
Posterior boundary mass within plus/minus one month becomes selection support.

Engine is selected by:

```python
DynamicHydroYearConfig(detector="robust_extrema")
DynamicHydroYearConfig(detector="semi_markov")
```

`semi_markov` remains experimental unless it improves held-out total error,
tail error, coverage, and calibration without worsening false singleton
rejection.

## 4. Real-data fixtures

### 4.1 Fitzroy/Kimberley

Existing frozen monthly fixture remains immutable. Legacy results remain a
regression comparator, not ground truth. Event alignment uses trough-to-trough
intervals rather than raw `hy_year` equality.

### 4.2 Gilbert River

`data/Gilbert_river_buffer.geojson` is one CRS84 Polygon named
`Gilbert_river_buffer_1000`, approximately bounded by longitude
142.8304-143.3327 and latitude -18.6183--18.1203.

A reproducible script uses DEA `ga_ls_wo_3` through the existing STAC loader to
freeze monthly counts and extent. Network access never occurs in ordinary
tests. A reviewed-event CSV stores accepted trough/peak dates, detectability,
reviewer, and notes. Algorithm output must not create its own truth file.

## 5. Validation design

Every eligible year counts in denominators. Missing detections count as timing
failures, while coverage is also reported separately.

Required metrics:

- resolved coverage and abstention;
- exact and within-one-month timing accuracy;
- signed error, MAE, median, P90, and maximum error;
- false boundary, missed boundary, split, and merge counts;
- false rejection of genuine singleton extrema and missed artifact rate;
- normalized peak/trough extent error and downstream metric changes;
- support calibration, Brier score, interval coverage, and interval width;
- runtime and memory per million site-months.

Inference uses paired site/year block-bootstrap confidence intervals. Parameter
selection uses leave-one-site-out or leave-one-basin-out evaluation; final
claims require untouched climate/sensor holdouts beyond Fitzroy and Gilbert.

Synthetic tests vary phase drift, amplitude, plateau width, genuine singleton
extrema, low/high artifacts lasting one to three months, rainfall pulses,
autocorrelated and heteroskedastic noise, AOI quantization, missingness linked
to wet season, truncated records, bimodality, and low variability.

## 6. Acceptance gates

### 6.1 Immediate downstream-unblocking gate

Robust engine may ship when:

- all unit and synthetic invariants pass;
- no nominal years merge or duplicate;
- at least 90% of detectable synthetic events are within one month, using all
  detectable years as denominator;
- Fitzroy and reviewed Gilbert tables achieve at least 80% within one month,
  P90 timing error no greater than two months, and no 11-12 month alignment
  errors after interval matching;
- every adjustment and provisional result is auditable;
- full package and documentation verification passes.

These are release gates for this package iteration, not proof of universal
scientific validity.

### 6.2 Semi-Markov promotion gate

Compared with robust engine on identical folds, semi-Markov must:

- reduce paired total absolute timing error with bootstrap 95% interval not
  crossing zero;
- not reduce coverage by more than two percentage points;
- reduce or preserve P90 error;
- not increase false singleton rejection;
- produce better Brier score and empirical 80% interval coverage between 70%
  and 90%;
- stay within five times robust-engine runtime.

Otherwise it remains opt-in experimental.

## 7. Compatibility and migration

Old recovery fields and `last_before_confirmed_recovery` remain accepted for
one minor release and emit `DeprecationWarning`. They never silently change
detector behavior. New output columns are additive. Legacy fixed-calendar APIs
remain unchanged.

## 8. Operational milestone

Tasks implementing the robust engine, Gilbert/Fitzroy gates, diagnostics, and
documentation form the downstream-unblocking milestone. Semi-Markov work
follows behind the same interface and benchmark harness; downstream consumers
do not wait for its promotion decision.
