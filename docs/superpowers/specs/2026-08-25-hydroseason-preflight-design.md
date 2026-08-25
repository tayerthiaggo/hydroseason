# HydroSeason Preflight Design

## Status

Approved design. Implementation has not started.

This design supersedes the exploratory handoff in
`docs/superpowers/specs/hydroseason_preflight_handoff.md` where the two
documents differ. It records the decisions made during the design review:

- v1 targets arbitrary AOIs using DEA WOfS, not arbitrary remote-sensing
  products or sensors;
- one public `preflight()` entry point exposes two internal stages;
- the first stage is a cheap, high-recall WOfS Statistics candidate screen;
- the second stage checks the exact monthly analysis record;
- `candidate_eligible`, `run_eligible`, and `timing_eligible` are distinct;
- timing eligibility checks data support, not whether the catchment is
  seasonal;
- detectable support uses absolute reliable WOfS pixels, never a fraction of
  catchment area;
- arbitrary requested dates are supported;
- weak calendar-month support warns, while a calendar month with no usable
  observations fails timing eligibility;
- threshold calibration and operational threshold application are separate
  modes.

## Problem

HydroSeason is intended for arbitrary areas of interest, but a valid AOI is
not necessarily observable at the spatial and temporal scale of DEA WOfS.
Narrow channels, sub-canopy water, rare inundation, and fragmented detections
can leave too little reliable surface-water evidence for a meaningful monthly
extent series.

Starting monthly WOfS acquisition for every AOI is expensive. The package
needs a fast candidate screen before acquisition, followed by a quality check
against the actual monthly record before HydroSeason is applied.

The preflight is an observability assessment. It must not select catchments
because their eventual HydroSeason result agrees with rainfall or discharge,
and it must not decide whether a catchment is seasonal. Those are separate
scientific questions handled after the data-support gate.

## Decision

Expose one public function, `hydroseason.preflight()`, with staged behavior:

```python
result = hydroseason.preflight(
    aoi,
    start_date,
    end_date,
    *,
    monthly_observations=None,
    thresholds="default",
)
```

The exact type annotations and optional I/O arguments should follow existing
HydroSeason conventions, including STAC endpoint and cache configuration.
The public contract is:

- `aoi`, `start_date`, and `end_date` define the requested analysis window;
- omission of `monthly_observations` runs only the cheap Statistics candidate
  stage and never starts monthly WOfS acquisition;
- supplying `monthly_observations` runs the candidate stage and the monthly
  stage in one call;
- `monthly_observations` may be a supported monthly mask/cache input or a
  precomputed monthly extent record;
- `thresholds="diagnostic"` computes metrics without making eligibility
  decisions;
- `thresholds="default"` applies a versioned, explicitly provisional
  operational profile;
- a caller can invoke the same public function before and after monthly
  acquisition without a second public candidate/monthly API.

`run_hydroseason()` does not automatically call `preflight()` in v1. Existing
behavior remains backward-compatible; callers explicitly run preflight and
decide whether to continue.

## Terminology

### Candidate eligibility

`candidate_eligible` means WOfS Statistics show enough likely reliable water
support to justify spending resources on monthly acquisition. It is a
high-recall candidate decision, not proof that HydroSeason can run.

### Run eligibility

`run_eligible` means the supplied monthly record contains enough validated,
detectable surface-water information to produce a usable HydroSeason extent
series or event characterization.

### Timing eligibility

`timing_eligible` means the monthly record has enough temporal support to run
HydroSeason regime and timing diagnostics. It does not mean that a seasonal
signal exists.

A flat, permanent, aseasonal, or irregular record may pass timing eligibility
and subsequently be routed by HydroSeason as `aseasonal`, `marginal`, or
event-scale. A record with inadequate temporal support should be reported as
`timing_eligible=False` or `indeterminate`, not as evidence of aseasonality.

### Reliable pixel

For a WOfS Statistics pixel in a complete calendar year, a reliable pixel is
one satisfying:

```text
count_clear >= min_clear_count
frequency_fraction >= min_frequency_fraction
```

`count_wet` remains a retained diagnostic and can be used to verify the
frequency derivation. `count_wet > 0` alone is not sufficient evidence of a
reliable detection because isolated low-frequency classifications may be
noise.

The preflight uses `frequency_fraction` in the canonical `[0, 1]` scale. It
derives this value from `count_wet / count_clear` rather than trusting a
possibly differently scaled convenience band. Display/export code may also
provide percentage form.

## Result contract

`PreflightResult` should be an immutable structured result, following existing
HydroSeason dataclass conventions. It must contain at least:

```text
candidate_eligible: bool | None
run_eligible: bool | None
timing_eligible: bool | None
candidate_decision
monthly_decision
candidate_metrics
monthly_metrics
warnings
reasons
thresholds
provenance
```

Each stage decision uses four states:

```text
pass
fail
indeterminate
not_assessed
```

Interpretation:

- `pass`: stage criteria were evaluated and passed;
- `fail`: stage criteria were evaluated and failed for the AOI/record;
- `indeterminate`: a scientific decision could not be made because required
  source coverage, provenance, or complete-year evidence was unavailable;
- `not_assessed`: the stage needs an input modality that was not supplied.

Boolean eligibility fields are `True` for `pass`, `False` for `fail`, and
`None` for `indeterminate` or `not_assessed`. This prevents a service outage
or missing pixel-level input from being mislabeled as scientific AOI failure.

The result must support:

```python
result.to_dict()
result.summary()
```

`to_dict()` must be flat enough for a one-row-per-AOI DataFrame while retaining
nested metric/provenance data when requested. Reason codes are stable machine-
readable identifiers; human-readable explanations are separate fields or
generated at presentation time.

## Stage 1: WOfS Statistics candidate screen

### Purpose

Screen potential candidates before monthly WOfS acquisition. Optimize for
recall: reject only AOIs with clearly inadequate reliable support. Monthly QC
is allowed to reject false positives.

### Analysis window

The requested `[start_date, end_date]` is authoritative.

`ga_ls_wo_fq_cyear_3` provides one summary per calendar year. For arbitrary
requested dates:

- evaluate only complete calendar years fully contained in the requested
  window;
- record partial start/end periods as `partial_window` warnings;
- do not use all-time `ga_ls_wo_fq_myear_3` metrics to silently extend the
  scientific window;
- if too few complete years remain for an annual decision, return
  `indeterminate` rather than treating the AOI as ineligible;
- monthly QC remains responsible for exact edge-month handling.

This avoids using observations outside the study window while retaining an
arbitrary-date public API.

### Required Statistics data path

The existing general Statistics loader collapses its time axis. Candidate
screening needs a temporal-preserving loader for `cyear` data:

- one annual plane per complete calendar year;
- `count_wet` and `count_clear` retained per year and pixel;
- no summation across distinct calendar years;
- source item IDs, product, processing version, time coverage, CRS, and
  resolution retained as provenance;
- only the requested complete interior years loaded;
- no monthly WOfS acquisition performed.

The loader may share STAC and raster acquisition helpers with
`open_wo_statistics()`, but must have a distinct contract so spatial tile
overlap is reduced correctly without destroying the annual time axis.

### Pixel metrics

For every complete year, create a reliable-pixel mask using the configured
clear-count and frequency thresholds. Compute at least:

```text
reliable_pixel_count_by_year
reliable_pixels_ever
reliable_pixels_persistent
reliable_area_m2_by_year
reliable_area_m2_ever
years_with_reliable_support
pixel_clear_count_quantiles
pixel_frequency_quantiles
```

`reliable_pixels_persistent` counts pixels reliable in at least the configured
number of complete years. This distinguishes a repeatable observable feature
from one isolated classification. The default profile determines the
repeat-year requirement; diagnostics mode reports the full distribution.

Spatial eligibility uses an absolute native-grid reliable-pixel count. It must
not use:

- reliable pixels divided by catchment pixels;
- water area divided by catchment area;
- catchment area alone;
- `count_wet > 0` without clear-count/frequency qualification.

Physical area is reported as a diagnostic using the Statistics grid metadata:

```text
reliable_area_m2 = reliable_pixel_count * native_pixel_area_m2
```

This keeps v1 transferable across WOfS AOIs while retaining a path to future
product profiles with different native resolutions.

### Candidate decision

Under a threshold profile, `candidate_eligible=True` requires:

1. enough complete-year Statistics coverage to evaluate the profile;
2. at least the configured absolute number of reliable pixels at the required
   repeat level;
3. enough complete years with reliable support.

The candidate decision does not inspect monthly phase, annual seasonality,
HydroSeason convergence, rainfall, discharge, or expected wet/dry timing.

Candidate failure reasons include:

```text
invalid_input
statistics_unavailable
statistics_provenance_unavailable
insufficient_complete_years
insufficient_reliable_pixels
insufficient_repeated_year_support
```

Partial edge years are warnings unless they leave insufficient complete years
for a decision.

## Stage 2: monthly quality control

### Purpose

Verify that actual monthly observations support HydroSeason after a candidate
has passed the cheap screen.

### Input capabilities

Raw monthly masks or cache-level pixel data allow full spatial and temporal
QC. A monthly extent DataFrame supports temporal QC and aggregate signal
metrics, but cannot reconstruct unique reliable pixels. For extent-only input:

- inherit candidate spatial support only when a candidate result is available;
- otherwise mark pixel-level spatial support `not_assessed`;
- never invent unique-pixel metrics from `n_water` totals.

### Exact monthly window

Normalize and evaluate months exactly within `[start_date, end_date]`,
including partial edge months. Existing HydroSeason quality conventions remain
authoritative for invalid coverage and finite partial observations.

### Pooled coverage

Do not require every calendar year to have nine usable months. Compute pooled
and distributed coverage metrics:

```text
n_usable_months_total
n_supported_years
overall_observed_fraction
calendar_month_support[1..12]
calendar_month_observed_fraction[1..12]
largest_temporal_gap
```

`n_supported_years` counts distinct years contributing usable observations.
The threshold profile also carries a minimum pooled-month requirement so five
years with only a handful of observations cannot pass accidentally.

Calendar-month rules:

- any calendar month with zero usable observations across the requested record
  is a hard timing failure;
- weak but non-zero calendar-month support is a warning;
- higher invalid coverage in wet-season months is retained in diagnostics and
  handled through existing quality-aware weighting;
- no requirement exists for equal support across all calendar months.

### Monthly detectable support

When pixel-level monthly data are available, compute:

```text
monthly_detectable_pixel_count
months_with_detectable_water
detectable_pixel_count_quantiles
monthly_support_area_m2
```

The monthly stage verifies that candidate support is represented in the
requested record. A monthly series with only a handful of noisy pixels can
therefore fail `run_eligible` even when the annual candidate screen passed.

When only aggregate extent is available, use the candidate's reliable-pixel
decision if present and report the missing pixel-level monthly diagnostics.

### Run decision

`run_eligible=True` requires:

1. valid monthly input and exact-window normalization;
2. enough pooled usable monthly support under the threshold profile;
3. enough detectable spatial support to form the extent series, either from
   pixel-level monthly data or a previously passed candidate screen;
4. no fatal input-quality or complete-observation failure.

This gate permits records that HydroSeason may later classify as aseasonal or
event-scale. It is not a seasonality test.

### Timing decision

`timing_eligible=True` requires:

1. `run_eligible=True`;
2. at least five supported years;
3. the configured pooled-month support;
4. no calendar month with zero usable observations.

It does not require a non-zero dynamic range, annual harmonic, stable peak,
stable trough, or any other evidence that the record is seasonal. HydroSeason
must discover and report that outcome after this gate.

Monthly failure and warning codes include:

```text
monthly_data_not_supplied
no_valid_months
insufficient_pooled_month_support
insufficient_supported_years
calendar_month_unobserved
weak_calendar_month_support
insufficient_monthly_detectable_support
largest_temporal_gap_warning
```

## Threshold configuration

Thresholds are a first-class, serializable configuration object. It must
contain at least:

```text
profile_name
profile_version
min_clear_count
min_frequency_fraction
min_reliable_pixels
min_reliable_years
min_candidate_years
min_pooled_usable_months
min_supported_years
min_monthly_detectable_pixels
```

The zero-calendar-month rule is a v1 policy, not a tunable threshold. Weak
non-zero calendar-month support remains a warning.

Numeric values are calibration outputs, not unexplained constants embedded in
metric functions. The calibration workflow must inspect distributions across
representative AOIs, exercise sensitivity, and record the resulting profile
version. A provisional default may be shipped for operational use, but must be
labeled provisional in the result and documentation until scientifically
frozen.

`thresholds="diagnostic"`:

- computes all available metrics;
- records no pass/fail eligibility decision;
- supports batch distribution analysis and threshold calibration.

`thresholds="default"`:

- loads the centrally defined versioned WOfS profile;
- applies candidate and monthly gates;
- stores the exact profile in `PreflightResult`.

Explicit threshold objects must be accepted for sensitivity analysis. Changing
one threshold must change only the decisions that depend on it, not the raw
metrics.

## Provenance and reproducibility

Every result must record:

- requested start/end dates;
- complete calendar years evaluated by Stage 1;
- partial edge periods;
- WOfS Statistics product and processing version;
- STAC endpoint and resolved item IDs;
- frequency derivation and canonical units;
- CRS, native resolution, and pixel area;
- monthly source kind and cache identity when available;
- quality policy and invalid-coverage settings;
- threshold profile and version;
- stage decisions and reason codes.

Stats service failure, missing item coverage, malformed provenance, and cache
identity mismatch produce `indeterminate` or `not_assessed`, never a false
scientific exclusion.

## Efficiency and batch behavior

The candidate stage is the performance boundary:

- it makes no monthly WOfS acquisition;
- it requests only the Statistics bands required for candidate metrics;
- it preserves annual time rather than loading a monthly raster cube;
- raw metrics can be cached independently of threshold profiles so repeated
  sensitivity runs do not repeat network reads;
- AOI, product, year range, resolution, and source item IDs form the cache
  identity.

The v1 public API remains one AOI per `preflight()` call. Batch research code
can map this pure result-producing function over AOIs and concatenate
`to_dict()` records. No separate public `preflight_many()` API is required for
the first implementation, provided the candidate metric evaluator is isolated
from I/O and can be tested and reused efficiently.

## Testing strategy

Tests must separate data acquisition, metric calculation, and policy
evaluation.

### Statistics loader contract tests

- annual `cyear` time axis is preserved;
- distinct calendar years are not summed together;
- partial requested edge years are excluded from annual metrics;
- source provenance and frequency units are retained;
- fake STAC items and datasets exercise the loader without network access;
- missing or malformed Statistics provenance returns `indeterminate`.

### Candidate metric tests

- reliable pixels require both clear-count and frequency criteria;
- one low-frequency speckle does not satisfy repeated support;
- repeated pixels are distinguished from one-year detections;
- absolute pixel support is independent of catchment-area percentage;
- physical area uses native grid metadata;
- threshold changes alter decisions without changing raw metrics;
- diagnostic mode returns metrics without eligibility decisions.

### Monthly policy tests

- pooled months across many years are accepted when only some years are weak;
- five supported years pass the year-count criterion;
- no nine-month requirement is imposed on every year;
- weak wet-season coverage produces warnings, not automatic failure;
- zero usable observations for one calendar month fails timing eligibility;
- extent-only input reports pixel-level monthly support as `not_assessed`;
- raw monthly pixel input can fail insufficient detectable support;
- permanent and aseasonal synthetic records can pass data support without
  being preclassified as seasonal;
- rainfall and discharge inputs cannot affect any preflight decision.

### Integration and compatibility tests

- candidate-only call does not invoke monthly WOfS acquisition;
- candidate-plus-monthly call evaluates both stages;
- exact arbitrary dates reach both stages consistently;
- service outage is distinguishable from AOI scientific failure;
- existing `run_hydroseason()` behavior remains unchanged;
- result serialization is DataFrame-compatible and provenance-complete.

## Non-goals

V1 does not:

- classify catchments as seasonal, aseasonal, or marginal;
- guarantee HydroSeason accuracy;
- compare against rainfall or discharge;
- use catchment area as a spatial eligibility proxy;
- infer hydrological-year phase during preflight;
- require annual harmonic strength or dynamic amplitude;
- support arbitrary remote-sensing products through one universal threshold;
- automatically alter or abort existing HydroSeason runs;
- add a separate public batch API;
- freeze final scientific thresholds before calibration.

## Acceptance criteria

The design is implemented when:

1. one public `preflight()` supports candidate-only and candidate-plus-monthly
   calls;
2. candidate screening uses temporal-preserving annual WOfS Statistics;
3. arbitrary date windows are handled without annual-window leakage;
4. reliable-pixel support uses clear-count/frequency criteria and absolute
   native pixel counts;
5. monthly QC uses pooled support plus distributed calendar-month diagnostics;
6. `candidate_eligible`, `run_eligible`, and `timing_eligible` remain distinct;
7. timing eligibility does not test seasonality;
8. zero calendar-month support fails while weak non-zero support warns;
9. diagnostic and provisional-default threshold modes exist;
10. all decisions are serializable with thresholds, provenance, metrics, and
    reason codes;
11. synthetic, loader-contract, and fake-STAC tests cover the stated edge
    cases;
12. existing HydroSeason behavior remains backward-compatible.

After this spec is reviewed and accepted, the next artifact is a separate
implementation plan. No implementation work is authorized by this document
alone.
