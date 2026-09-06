# Two-Pass Trough Refinement Design

**Date:** 2026-09-06

**Status:** approved design; implementation and calibration not yet started

**Authority:** candidate policy only until every promotion gate in this document passes

## 1. Purpose

HydroSeason currently uses seasonal context to select annual trough candidates and
then derives peaks and hydrological-year rows from those boundaries. That first
pass is useful for finding the annual frame, but it can place a trough at the first
or strict-lowest month of a prolonged dry state instead of at the end of the dry
season.

This design adds a retrospective second pass that refines troughs inside closed,
peak-to-peak spans. Pass 2 fits the observed recession, low-water state, and
recovery. It consumes the primary peaks settled by pass 1 and never rediscovers or
moves them.

The operational trough boundary is the last supported low-state month before the
final uninterrupted recovery toward the next identifiable primary peak. The first
recovery month belongs to the next hydrological year.

The design replaces the uncommitted relative-to-minimum tolerance prototype. It
does not retain `TROUGH_EQUIVALENCE_REL_TOLERANCE`, a record-wide amplitude rule,
a percentage-above-minimum rule, a raw-value cutoff, or a fixed number of rising
months.

## 2. Scientific contract

### 2.1 Pass responsibilities

- **Pass 1:** establishes seasonal context, trough candidates, cycle context, and
  primary peaks. Its output remains the baseline and fallback.
- **Pass 2:** examines each eligible closed peak-to-peak span and challenges only
  the shared trough boundary. It is retrospective and cannot operate on the open
  span after the last peak.
- **Peak-first invariant:** all pass-2 computations use the same peak evidence as
  pass 1. A pass-2 result that changes any peak date is invalid.

Pass 1 is not a lower or upper bound. An accepted pass-2 boundary may move in
either direction within the adjacent ordered peaks.

### 2.2 Low state, boundary, and recovery

The fitted low-water state is a contiguous interval from `low_state_start` through
`low_state_end`. A one-month low state is permitted. Low-state occupancy and
uncertainty in its endpoint are separate objects:

- `low_state_start` and `low_state_end` describe the selected fitted state.
- The profile-loss candidate set contains statistically plausible
  `low_state_end` dates.
- One final contiguous cluster of candidate endpoint dates is published as the
  trough boundary interval.
- `trough_boundary_date` is the last month of that interval.
- `recovery_start_month` is the following calendar month when observed continuous
  recovery is confirmable.

The boundary may legitimately widen from a point to an interval or broad result.
Honest loss of precision is not a regression. Existing calibrated timing-span
thresholds retain their meanings: point has span 0, interval has span at most 2
months, broad has span at most 5 months, and a wider or incoherent set is
unresolved.

### 2.3 Recovery and pulses

Recovery begins after the final departure from the statistically supported
low-water state before the next primary peak. A rise that later returns to the
low-state uncertainty set is a rewetting pulse, not recovery, regardless of its
magnitude. No fixed `N`-rising-month rule is used.

A pulse is retained as diagnostic evidence and may populate the existing
secondary-peak fields. Pulse magnitude never ends recession. A pulse is supported
when a positive excursion above the fitted local shape is followed by observed
return to the final low state before the accepted recovery. Significance is based
on local residual scale and a globally calibrated standardized-residual rule, not
on raw extent.

One cycle with two pulses is a rare stress case, not the assumed data-generating
pattern. The detector must nevertheless map it correctly.

### 2.4 Separated candidate clusters

Pass 2 never joins separated plausible endpoint clusters into a single trough
interval. It selects the later cluster only when the intervening rise returns to
the low-state uncertainty set and is therefore supported as a pulse. If that
interpretation is not supported, pass 2 is unresolved and pass 1 remains the
operational result.

## 3. Eligibility and evidence states

### 3.1 Peak eligibility

Pass 2 runs only when both adjacent primary peak dates are present,
chronologically ordered, and timing-identifiable under the existing calibrated
policy.

- Point peaks permit confirmed refinement when all other evidence is confirmable.
- Interval peaks are propagated by evaluating every chronologically valid pair of
  plausible peak dates. Their refinement is provisional.
- A low-quality peak remains eligible when its date is identifiable. It can only
  support provisional replacement, and only when the trough result is stable
  across peak-date and quality sensitivity scenarios.
- A missing or timing-unresolved peak disables pass 2 for the shared span.
- The open span after the final peak receives status `awaiting_next_peak`; no
  estimated future peak may be used.

Filtering null peaks and pairing the remaining rows is forbidden because it
would bridge a missing result row into another peak.

### 3.2 Monthly evidence

The regular monthly index created by `prepare_monthly_extent` is authoritative.
Evidence states are:

- **normal:** finite extent and normal quality;
- **low quality:** finite extent with incomplete support above the existing
  quality limit;
- **unknown quality:** finite extent without support metadata;
- **missing:** no finite extent or no valid supporting pixels.

Normal, low-quality, and unknown-quality observations remain in the nominal fit.
Known support weight is `observed_fraction`, bounded naturally to `[0, 1]` with
no pass-2-specific floor. Unknown support uses equal numerical weight but forces
at least provisional status. Missing observations receive no weight and are
structural barriers. Raw pixel count is not treated as a number of independent
samples because neighbouring pixels are spatially dependent.

Low-quality months do not automatically break continuity. A result is confirmed
only when normal-quality observations establish the continuous departure and the
same final endpoint cluster survives quality sensitivity analysis. If a
low-quality or unknown-quality month is essential to bridge recovery, the result
is provisional.

### 3.3 Gap rules

Pass 2 never infers recovery through a missing month.

- A gap after an observed low-state interval but before recovery confirmation
  retains the last observed low-state month as a provisional operational
  boundary.
- A gap overlapping a plausible low-state interval makes refinement unresolved.
- If no defensible observed low state exists, refinement is unresolved.
- An unresolved pass-2 result may retain pass 1 only as an explicitly provisional
  fallback. It is never labelled as a pass-2 result.

For Daly-style evidence, statistically equivalent observed September-November
low-state months followed by a gap yield a September-November boundary interval
and provisional November operational boundary. For Fitzroy-style uninterrupted
December-January-February recovery, December remains the final low-state month
and January belongs to the next hydrological year.

## 4. Statistical model

### 4.1 Candidate shape

For every eligible ordered peak-date pair, pass 2 evaluates the full monthly span
including both peak observations. For every candidate contiguous low-state block
`[s, e]` strictly between the peaks, it fits a latent valley shape:

1. a non-increasing recession from the left peak through `s`;
2. a constant latent low-state block from `s` through `e`;
3. a non-decreasing recovery from `e` through the right peak.

The segments meet at the same latent low-state value. Observations need not be
monotonic; residuals carry noise and rewetting pulses. A single-month block
represents a point trough. Candidate enumeration is exhaustive because monthly
peak-to-peak spans are short.

Shape constraints never cross a missing month. A gapped span is partitioned into
contiguous observed blocks for diagnostic fitting, and evidence after a gap cannot
confirm departure from a pre-gap low state. Section 3.3 determines whether the
remaining evidence supports a provisional pre-gap boundary or requires an
unresolved result.

The fit uses deterministic weighted isotonic regression implemented with NumPy
and Pandas. Core detection acquires no SciPy or machine-learning dependency.

### 4.2 Robust objective

Each candidate minimizes support-weighted Huber loss. Huber loss behaves like
squared error for ordinary residuals and absolute error for extremes, limiting a
short real pulse's leverage without deleting it.

Every candidate in one peak-to-peak span uses the same local robust scale so that
candidate losses remain comparable. The common scale is estimated once. First,
all candidates are fitted using scale-free weighted absolute loss and the
minimum-loss preliminary shape is selected. The scale hierarchy is then:

1. `1.4826 * MAD` of the preliminary shape's residuals;
2. `1.4826 * MAD(first differences of preliminary residuals) / sqrt(2)`
   within contiguous observed blocks;
3. the existing local measurement/detectability floor, including one-pixel
   resolution where counts exist;
4. an exact-fit path when all three are zero.

No record-wide wet-season amplitude enters the scale. The Huber transition
constant is global, selected only on the synthetic/design calibration partition,
then frozen, sensitivity-tested, fingerprinted, and versioned.

Huber fitting uses deterministic iteratively reweighted isotonic regression. It
stops when fitted-value change is within `sqrt(machine epsilon)` relative to the
larger of local scale and local extent, with an absolute floor of machine epsilon.
The iteration limit is 200. These are numerical safeguards, not hydrological
selection parameters, and are fingerprinted but never tuned against truth.

### 4.3 Endpoint profile and uncertainty

For each endpoint `e`, the endpoint profile loss is the minimum candidate loss
over every valid low-state start `s <= e`. The normalized profile delta is the
endpoint's excess loss above the global best endpoint, divided by effective
support. Because residuals are already scaled locally, this quantity is
dimensionless.

An endpoint is statistically plausible when its normalized profile delta is at
or below one globally calibrated cutoff. Calibration targets 95% inclusion of a
known synthetic boundary or at least one reviewer-acceptable boundary month.
This is an empirical repeated-case coverage target, not a posterior probability
for an individual record.

For the chosen operational endpoint, `low_state_start` comes from its
minimum-loss candidate block. Exact start-date ties select the earliest supported
start so an observed flat low state is not collapsed to one month. Endpoint ties follow the scientific
convention and select the latest supported endpoint.

### 4.4 Quality and peak sensitivity

The nominal fit is challenged by a deterministic sensitivity suite:

1. remove all low-quality observations from the fit;
2. remove each low-quality observation individually;
3. replace each low-quality observation individually by its support-derived
   lower and upper extent bound;
4. evaluate every ordered pair of plausible adjacent peak dates;
5. repeat without unknown-quality observations when support is unavailable.

For extent `x` observed over fraction `f` of the AOI, the support-derived bounds
are `x * f` and `x * f + 100 * (1 - f)`. These are sensitivity bounds, not a
probability interval.

A result is stable when every admissible sensitivity scenario yields one final
contiguous endpoint cluster, the clusters share at least one endpoint, and their
combined span does not exceed the existing broad threshold. Otherwise the
challenger is diagnostic only and pass 1 remains operational.

## 5. Challenger result and atomic acceptance

Pass 2 is a pure challenger. It returns evidence without mutating annual rows,
opportunity rows, peaks, or the input frame. Integration evaluates the challenger
against pass 1 and either applies the whole shared-boundary change or applies none
of it.

### 5.1 Pass-2 status

`trough_refinement_status` has exactly five values:

- `confirmed`: continuous normal-quality recovery and stable point-peak evidence;
- `provisional`: identifiable but weakened by a post-low-state gap, interval or
  low-quality peak, unknown quality, or an essential low-quality recovery month;
- `unresolved`: conflicting, separated, overly broad, gap-overlapped, or absent
  low-state evidence;
- `unavailable`: an adjacent peak is missing or timing-unresolved;
- `awaiting_next_peak`: the span is open.

`trough_refinement_reason` is a separate stable reason code. Multiple diagnostic
reasons may be retained internally, but the annual table reports the
highest-priority reason in this order: missing/timing-unresolved peak, open span,
gap-overlapped low state, no defensible low state, disjoint modes, unstable peak
sensitivity, unstable quality sensitivity, recovery crosses gap, low-quality
peak, interval peak, essential low-quality recovery, unknown quality, accepted.

When status is `unresolved`, `unavailable`, or `awaiting_next_peak`, pass 1 is
retained only if its own coverage and timing evidence remains admissible. That
fallback is explicitly provisional. If pass 1 is not independently admissible,
the published boundary is unresolved rather than filled from the challenger.

### 5.2 Per-span acceptance

A challenger may replace pass 1 only when all conditions hold:

1. status is `confirmed` or `provisional`;
2. its endpoint evidence forms one permissible final cluster under the pulse rule;
3. the proposed boundary lies strictly between the same frozen adjacent peaks;
4. annual boundary dates remain unique and strictly ordered;
5. both cycles sharing the boundary retain their required usable coverage;
6. neither adjacent cycle becomes uncomputable;
7. neither adjacent cycle loses peak timing identifiability;
8. both adjacent peak dates and their evidence remain unchanged;
9. timing and coverage checks use existing calibrated policy;
10. the result passes all required peak and quality sensitivity scenarios.

The two affected cycles are recomputed together on copies. If any condition
fails, both copies are discarded and both original pass-1 rows survive. Rerunning
global `_assemble_dynamic_years` after overwriting an opportunity is forbidden:
it can alter unrelated peaks, stale metadata, and cycle assignment.

Pass 2 does not have access to truth during normal operation. "Worse than pass 1"
therefore means structurally inadmissible, unstable, unsupported, or unresolved
under these predeclared checks. On labelled development and holdout data, pass 2
must additionally beat or match pass 1 under Section 8.

## 6. Evidence representation

Existing meanings are preserved:

- `trough_month` is the operational last-low-state boundary used to assemble
  cycles.
- `trough_interval_start` and `trough_interval_end` are the pass-2 boundary
  uncertainty interval when pass 2 is applied.
- `low_run_start_month` and `low_run_end_month` represent selected low-state
  occupancy.
- `trough_timing_status` uses `point`, `interval`, `broad`, or `unresolved`.
- `secondary_peak_month` and `secondary_peak_extent_pct` retain the strongest
  supported rewetting pulse.

The annual result adds:

- `pass1_trough_month`
- `pass1_trough_interval_start`
- `pass1_trough_interval_end`
- `pass1_trough_timing_status`
- `trough_challenger_month`
- `trough_challenger_interval_start`
- `trough_challenger_interval_end`
- `trough_challenger_timing_status`
- `trough_challenger_low_state_start`
- `trough_challenger_low_state_end`
- `trough_refinement_status`
- `trough_refinement_reason`
- `trough_refinement_applied`
- `recovery_start_month`
- `trough_local_scale_pp`
- `trough_profile_best_loss`
- `trough_profile_cutoff`
- `trough_effective_support`
- `trough_pulse_months`
- `trough_refinement_policy_version`

Candidate-by-candidate scores, sensitivity scenarios, all pulse residuals, and
all reason codes belong in calibration/debug artifacts rather than individual
wide annual columns. Exports and report documentation must identify pass-1
fallbacks explicitly; a fallback is never presented as a pass-2 estimate.

## 7. Implementation architecture

The implementation uses focused internal modules instead of adding the model to
the already large `_dynamic_year.py`:

- `hydroseason/_trough_refinement.py`: immutable result types, candidate
  enumeration, weighted robust valley fitting, profile construction, gap/pulse
  interpretation, and sensitivity evaluation.
- `hydroseason/_dynamic_year.py`: eligibility routing and atomic two-cycle
  acceptance only.
- `hydroseason/_trough_refinement_calibration.py`: candidate policy values,
  metrics, fingerprints, calibration selection, and validation evaluation.
- `hydroseason/_trough_refinement_defaults.py`: generated selected candidate
  tuple and fingerprint; it carries candidate authority and never changes the
  public pass-1 default.
- `hydroseason/_synthetic.py`: independent trough-refinement corpus and truth
  labels.
- `scripts/run_calibration.py`: explicit calibration, validation, comparison,
  and promotion commands.

The current uncommitted `_refine_troughs_by_recession` implementation is replaced,
not incrementally patched. Its `TROUGH_EQUIVALENCE_REL_TOLERANCE`, filtered-peak
pairing, direct opportunity mutation, and global reassembly path are prohibited
by this design.

Until promotion, public defaults remain pass 1. Calibration and diagnostic code
may call the challenger explicitly, but ordinary detection does not apply it.
After promotion, changing the default requires a new established policy identifier
and migration note; `established_0_2_0` or `established_0_3_0` must not silently
name changed scientific output.

The initial internal authority string is
`trough_refinement_candidate_0_1`. It conveys no established-policy authority.

## 8. Calibration and validation

### 8.1 Frozen labels

Primary truth uses only monthly extent and the same quality/support fields
available to the detector. The reviewer records:

- low-state occupancy interval;
- acceptable operational boundary interval;
- confidence;
- gaps and whether they overlap low state or recovery;
- rewetting pulses;
- peak timing identifiability without changing the detector's frozen peak date.

Rainfall, discharge, ecology, and local knowledge form a separate external-
validity layer. They never select or tune the detector.

Daly, Fitzroy, and Gilbert are re-reviewed under this convention for development.
Existing first-touch manual labels are not silently rewritten and are not treated
as end-of-dry truth.

### 8.2 Synthetic/design partitions

A new corpus uses disjoint seed ranges and does not change existing frozen
synthetic artifacts:

- calibration seeds: `70000..74999`;
- untouched validation seeds: `80000..84999`.

Balanced families cover ordinary seasonal cycles, gradual recovery, long flat
low states, low variability, a false early rise, one pulse, two pulses, disjoint
modes, gap after low state, gap overlapping low state, low-quality interior
months, low-quality peaks, interval peaks, missing peaks, short/long cycles, and
open spans.

Calibration may select only global Huber, profile-loss, and standardized-pulse
settings. The frozen candidate grid is:

- Huber transition constant: `(1.0, 1.345, 1.5, 2.0)`;
- normalized profile-loss cutoff: `(0.0, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)`;
- standardized positive-residual pulse cutoff: `(1.5, 2.0, 2.5, 3.0)`.

Candidate grid, selection order, numerical safeguards, corpus source, truth
source, seed lists, metric code, and dataset hashes are fingerprinted before
untouched validation. Validation never reselects a value.

Calibration first retains only candidates with 95% boundary-set inclusion, a
false-precise-boundary Wilson upper bound at or below 0.05, zero peak changes,
zero duplicate/nonmonotonic/wrong-cycle boundaries, and zero new uncomputable
cycles. It then selects the candidate with the lowest median distance to the truth
interval, then lowest p90 distance, then lowest abstention. Remaining ties prefer
the least change from pass 1, the wider honest uncertainty interval, and finally
the Huber constant nearest 1.345. A calibration with no admissible candidate fails
rather than weakening a gate.

### 8.3 Blinded real holdout

The real holdout is sampled and fingerprinted before pass-2 output is exposed to
the reviewer. It is stratified across normal seasonal, low-variability,
missing-data, low-quality, and rare two-pulse records. The reviewer cannot see
either algorithm's result. All cycles in sampled catchments are labelled to avoid
outcome-dependent cycle selection.

At least 20% of labelled spans, and never fewer than 30 spans, receive an
independent second blind review. Disagreements are adjudicated and the label file
is frozen before unblinding algorithm results.

The cohort must yield at least 73 algorithm point predictions with adjudicated
reviewer truth for the false-precision gate to be evaluable with zero errors under
a two-sided 95% Wilson interval. If it yields fewer, promotion is unavailable; the
cohort is not expanded after viewing results. Catchment-level bootstrap intervals
are reported because cycles within a catchment are dependent. Cycle-level Wilson
intervals are also reported and labelled as potentially optimistic.

### 8.4 Untouched-holdout promotion gates

Every gate is mandatory:

1. zero changed primary peak dates;
2. zero duplicate, nonmonotonic, or wrong-cycle boundaries;
3. zero new uncomputable cycles;
4. predicted boundary scored against the reviewer interval, with distance zero
   inside the interval and calendar-month distance to the nearest edge outside;
5. false-precise-boundary two-sided 95% Wilson upper bound `<= 0.05`, where a
   false-precise result is an algorithm `point` prediction when adjudicated truth
   does not support a point boundary, divided by all algorithm `point`
   predictions;
6. median distance to the reviewer interval `<= 1` month;
7. p90 distance to the reviewer interval `<= 2` months;
8. coverage and abstention reported on all eligible truth-labelled spans,
   separately from resolved-only accuracy;
9. pass 2 beats or matches pass 1 on median and p90 distance without worsening
   any structural metric;
10. all thresholds, source files, truth labels, and dataset fingerprints were
    frozen before holdout evaluation.

An unmet or unevaluable gate prevents promotion. Diagnostic success on Daly,
Fitzroy, Gilbert, or inspected stress records cannot override a holdout failure.

## 9. Required tests

Unit tests establish the model before integration:

- exact point trough;
- contiguous equivalent endpoint interval with latest-month boundary;
- long low-state occupancy distinct from endpoint uncertainty;
- gradual uninterrupted recovery;
- early rise followed by return to low state;
- large pulse exceeding early recovery values;
- two pulses within one annual frame;
- separated endpoint modes that cannot be joined;
- local MAD zero and exact-flat cases;
- support weighting and unknown support;
- low-quality removal/bound sensitivity;
- post-low-state gap provisional result;
- low-state-overlapping gap unresolved result;
- point, interval, low-quality, missing, and unresolved peaks;
- open span awaiting next peak;
- deterministic repeated output.

Integration tests assert:

- Daly September-November interval with provisional November boundary under the
  agreed gap case;
- Fitzroy December boundary with January in the next hydrological year under
  continuous recovery;
- Gilbert and all re-reviewed development labels under the new convention;
- no peak changes;
- no pairing across missing result rows;
- bidirectional boundary movement;
- atomic two-cycle rollback on coverage, ordering, computability, or peak-timing
  failure;
- honest widening from point to interval/broad without rollback;
- unchanged pass-1 results while the challenger is not promoted;
- report/export columns and fallback wording.

Calibration tests assert partition separation, deterministic generation, frozen
fingerprints, no validation-time selection, Wilson calculations, interval-distance
scoring, and gate refusal when evidence is insufficient.

## 10. Rollback and release

Implementation proceeds behind challenger authority. The existing pass-1 output
is the operational rollback state at every level: candidate, span, record, and
release.

If calibration, validation, or real holdout fails, pass 2 remains diagnostic and
no public default changes. If promotion succeeds, the release records:

- the new policy identifier;
- model and threshold fingerprint;
- calibration and untouched-validation artifacts;
- blinded-cohort protocol and result;
- pass-1 versus pass-2 comparison;
- migration notes for changed trough boundaries and added evidence columns.

Rollback after promotion selects the prior versioned policy; it never deletes or
rewrites historical calibration evidence.
