# HydroSeason 0.3.0 decision-policy design: trough window geometry

**Status:** frozen design, not yet implemented. No default has changed.

**Scope:** the geometry that decides *where* the annual trough boundary may be
found — the climatological search window radius, the adaptive retry radius, and
the relaxed minimum cycle coverage that the retry grants. Nothing in this
document changes how zero-water observations are treated or how timing
identifiability is assessed; `established_0_2_0` remains authoritative for
those, and this design consumes its outputs unchanged.

**Relationship to `established_0_2_0`:** this design is *conditional*. It
predeclares a sweep whose null result — the shipped geometry wins — is a
publishable outcome that retains `established_0_2_0` and ships diagnostics
only. A new policy identifier `established_0_3_0` is created only if the frozen
selector chooses a tuple other than the shipped one.

---

## 1. The problem

`_dynamic_year.py` anchors every year's trough search at
`pd.Timestamp(year, config.expected_trough_month, 1)` — a single month derived
from the pooled monthly climatology — and searches
`± trough_search_radius_months`. The shipped value is `3`.

That value, the private adaptive radius `_ADAPTIVE_TROUGH_SEARCH_RADIUS_MONTHS
= 5`, and the private relaxed coverage `_ADAPTIVE_MIN_USABLE_MONTHS_PER_CYCLE =
6` are all **inherited geometry**. They were carried forward from the first
dynamic-year implementation. None appears in any calibration grid, and none
appears in `CALIBRATION_FINGERPRINT` or
`TIMING_IDENTIFIABILITY_FINGERPRINT`. They have never been selected against
truth.

When a lower continuation lies outside the window, the detector cannot consider
it and may return an in-window surrogate. Selection is not simply "closest month
to the anchor": quality screening, equivalent-low runs, and the cross-year
sequence optimiser all participate.

### 1.1 Development evidence, with its limits stated

An audit reran 34 cached stress bundles after stripping prior decision columns.
These are **development evidence, not truth-labelled validation data**. They
motivated this design; they may not select its parameters.

| metric | value |
|---|---|
| total cycles (20 per-year-detection catchments) | 420 |
| final rows at or beyond the base radius (`abs(phase_shift_months) >= 3`) | 62 (14.8%) |
| final shift distribution | `+3: 46`, `-3: 9`, `-4: 6`, `-5: 1` |
| final rows at their *effective* search edge | 56 (13.3%) |
| cycles dropped for `insufficient_cycle_coverage` | 5 |
| catchments with >= 25% base-edge-or-beyond rows | 1 (130302a Taroom, 33%) |

`abs(phase_shift_months) >= 3` is **not** a clipping rate. A separate radius-5
challenge audit found 373 interior rows with both adjacent operational
boundaries present and all four outer months (`±4`, `±5`) observed. Of those, 68
had a lower raw extent outside the base radius-3 window; 45 of the 68 were not
base-window edge hits. Among the 62 base-pass edge hits, 24 met the same
neighbour and coverage gates and had a lower outer value (10 left, 14 right).

An exploratory radius sweep on the same bundle:

| radius | edge-or-beyond rows | `insufficient_cycle_coverage` | dates changed vs radius 3 |
|---:|---:|---:|---:|
| 3 | 62/420 (14.8%) | 5 | — |
| 4 | 56/420 (13.3%) | 18 | 49 |
| 5 | 24/420 (5.7%) | 26 | 63 |

**The binding constraint is cycle coverage, not edge rate.** Radius 5 cuts edge
hits by a factor of 2.6 while multiplying `insufficient_cycle_coverage` by 5.2.
Any sweep over radius alone, holding coverage fixed, selects radius 3 by
construction and answers nothing. This is why the grid in §4 is
three-dimensional.

### 1.2 Why the existing adaptive retry does not resolve it

`_adaptive_edge_retry_years()` is **left-edge only**:

```python
base_start = expected - pd.DateOffset(months=config.trough_search_radius_months)
if pd.Timestamp(row["trough_month"]) != base_start:
    continue
```

It fires only when the trough sits at the earliest window month, and only ever
looks further back. The 46 right base-edge hits have no counterpart path.

A mirrored helper is not a sufficient fix, and this design does not adopt one
(see §7):

- The flagship 130327a case (HY2016) is selected at `shift=+2`, so an
  exact-right-edge trigger would miss it.
- The recompute path enforces `not_later_than`, accepts only dates earlier than
  the base boundary, and rolls back on the retried cycle alone. A later move
  needs the directional inverse plus validation of *both* cycles sharing the
  moved boundary.
- If a calibrated base radius is 5, the current retry cap (`min(5, ...)`) cannot
  widen it at all.

### 1.3 Rejected alternative: global peak-bounded recession

An earlier proposal replaced the climatology anchor with a peak-bounded
recession search using `scipy.signal.find_peaks` and a prominence expressed as
`k * noise_pp`. A prototype swept `k` from 1x to 8x over all 34 catchments.

The global rule is rejected on its own evidence:

- Median peaks-per-year at 3x noise is 1.00, with 33/34 catchments in
  `[0.7, 1.5]` — the centre is fine.
- Only 10/34 catchments hold a stable count across 2x-5x; median relative
  spread is 0.39. The multiplier needs calibrating exactly as carefully as
  `radius=3`. The knob moves; it does not disappear.
- `noise_pp == 0.0` for 130336a, 130407a, and 130413a — the zero-dominated
  records `established_0_2_0` exists to protect. `k * noise_pp` collapses to
  zero for every `k`, so the multiplier has no calibratable effect at all.
  Meanwhile 130403a has `noise_pp = 2.48`, so 8x finds one peak in 21 years.
  Same rule, opposite failure.

This rejects the tested global rule. It does not establish that every
peak-bounded method is unsuitable; a peak-bounded challenger may return with a
truth-based design of its own.

The reviewed literature supports impartial parameter determination, sensitivity
analysis, and holdout validation. It does not supply a parameter-free method for
monthly extent records:

- Pelletier & Andréassian 2020 — impartial two-parameter determination,
  split-sample temporal coherence, geological validation on 1,664 catchments.
  <https://doi.org/10.5194/hess-24-1171-2020>
- Tarasova et al. 2018 — iterative threshold adjustment for multi-peak event
  separation. <https://doi.org/10.1029/2018WR022587>
- Fischer et al. 2021 — parameter sensitivity analysis with occasional manual
  adjustment. The DOI string contains `2020`; publication year is 2021.
  <https://doi.org/10.1016/j.hydroa.2020.100070>
- Giani et al. 2022 — peer-reviewed objective event separation that still
  retains a physically based tolerance parameter and recommends result checks.
  <https://doi.org/10.1029/2021WR031283>
- Floriancic et al. 2020 — low-flow timing consistency varies across 1,860
  catchments; some switch between winter and summer minima.
  <https://doi.org/10.1029/2019WR026928>
- Seibert et al. 2026 — supports reconsidering fixed national water-year
  starts, but explicitly does not identify the best start for each individual
  catchment. Not direct evidence for moving per-cycle boundaries.
  <https://doi.org/10.1002/hyp.70592>
- Wasko et al. 2020 — defines a local water year from each gauge's lowest
  average monthly streamflow, supporting a local climatological anchor.
  <https://doi.org/10.1029/2020WR027233>

---

## 2. Public diagnostic contract

The following annual fields are added. They are **report-only**: they describe
the geometry that produced a boundary and never participate in selecting one.
Adding them changes no boundary, so they ship under `established_0_2_0`.

| Field | Type | Meaning |
|---|---|---|
| `trough_search_radius_used` | `int` | Radius in months actually used for this year's window. Equals `trough_search_radius_months` unless the adaptive retry widened this year. |
| `boundary_at_search_edge` | `bool` | The published boundary sits exactly at an edge month of its own window. |
| `boundary_search_edge_side` | `"left" \| "right" \| "none"` | Which edge, or `"none"` when not at an edge. |
| `outside_window_observed` | `bool` | Every month in the outside-audit span was present in the prepared frame. |
| `outside_window_lower` | `bool` | A strictly lower **raw observed** extent exists in the outside-audit span, and `outside_window_observed` is true. |
| `retry_outcome` | `"not_attempted" \| "applied" \| "rolled_back"` | Whether the adaptive retry ran for this year and whether its result survived. |

**The outside-audit span never widens the search.** It reaches at most
`_DIAGNOSTIC_AUDIT_RADIUS_MONTHS = 5` — the radius the adaptive retry can
already reach — so a diagnostic can never name a month the shipped detector was
structurally incapable of selecting. When `trough_search_radius_used >= 5` the
span is empty and both outside-window fields are `False`.

**`outside_window_lower` is not a clipping indicator.** It states that a lower
raw value was observed outside the window. It does not state that the outside
month is the correct boundary: a wider search can select a competing event or
damage cycle geometry. The field is a challenge count, and it is excluded from
the selector in §5 for exactly that reason.

### 2.1 Record-level summary

`summarise_boundary_geometry(annual)` returns, for one catchment:

```python
@dataclass(frozen=True)
class BoundaryGeometrySummary:
    n_boundaries: int
    n_at_search_edge: int
    boundary_search_edge_rate: float
    boundary_search_edge_interval: tuple[float, float]
    interval_method: str
    n_outside_window_observed: int
    n_outside_window_lower: int
    outside_window_lower_rate: float
    radius_used_counts: dict[int, int]
    retry_outcome_counts: dict[str, int]
```

Both rates publish numerator, denominator, and interval — never a bare
percentage. Within one catchment the interval is Wilson and
`interval_method == "wilson_within_catchment"`, which is reported honestly as
an understatement: cycles are serially dependent within a catchment. Across a
cohort, the interval is a catchment-level bootstrap and `interval_method ==
"catchment_bootstrap"`. **Never bootstrap cycles as independent observations.**
The 420 cycles in §1.1 are clustered within 20 catchments.

Their denominators differ and must not be compared:
`boundary_search_edge_rate` is over published boundaries;
`outside_window_lower_rate` is over boundaries with `outside_window_observed`.

---

## 3. Geometry policy under selection

Three parameters are selected jointly. They are not independent: widening the
window moves boundaries, which changes cycle lengths, which changes how many
cycles clear the minimum-coverage gate.

| Parameter | Shipped | Where |
|---|---|---|
| `trough_search_radius_months` | `3` | `DynamicHydroYearConfig`, public |
| `adaptive_trough_search_radius_months` | `5` | `_ADAPTIVE_TROUGH_SEARCH_RADIUS_MONTHS`, private |
| `adaptive_min_usable_months_per_cycle` | `6` | `_ADAPTIVE_MIN_USABLE_MONTHS_PER_CYCLE`, private |

`min_usable_months_per_cycle` (base, `8`) is **held fixed**. It governs the
non-retry path and is entangled with record-length and coverage policy outside
this design's scope. Only the relaxed value the retry grants is swept.

### 3.1 Why the radius cap of 5 is derivable, not inherited

`DynamicHydroYearConfig.__post_init__` enforces `0 <= trough_search_radius_months
<= 5`. That bound has a structural derivation and should be documented as such
rather than left reading as a legacy constant:

A symmetric radius `r` spans `2r + 1` months. At `r = 6` the span is 13 months.
Consecutive years' anchors are exactly 12 months apart, so consecutive windows
overlap by one month, and a single calendar month becomes selectable as the
boundary of two different hydrological years. That produces duplicate or
non-monotonic boundaries — a structural failure the sequence optimiser is not
designed to arbitrate. `r = 5` gives an 11-month span with a one-month guard
between adjacent windows.

The feasible symmetric base grid is therefore `[3, 4, 5]`. Candidates narrower
than 3 are excluded: they cannot represent the phase excursions already observed
in the development evidence, and no mechanism in this design would recover a
boundary they exclude.

### 3.2 Asymmetric windows: ruled out this iteration, with a re-entry condition

The development evidence is asymmetric — 46 right-edge hits against 16 left. An
asymmetric window such as `(-3, +4)` lies inside the feasible space and is
deliberately **not** in the grid. Reasons:

1. The observed asymmetry is confounded. The existing retry is left-only and
   already moved seven left-edge boundaries earlier, so the residual left count
   is depressed by the very mechanism under review.
2. `phase_shift_months` and the edge diagnostics in §2 assume a symmetric
   window. An asymmetric window makes "at the edge" side-dependent and requires
   reworking the cross-year coherence optimiser's distance term.
3. The anchor is a pooled climatological month. An asymmetric window encodes a
   directional prior that the anchor estimator does not supply.

**Re-entry condition, predeclared:** if the symmetric sweep leaves a residual
`boundary_signed_bias` on the untouched synthetic validation partition with
`abs(bias) >= 0.5` months, asymmetric windows are opened as a follow-up design
with their own grid and corpus. Below that threshold, symmetry stands.

---

## 4. Frozen calibration grid

Every geometry parameter must come from this predeclared grid. No hand-tuning
after viewing validation, the protected catchments, the three motivating
records, or the 34-catchment bundle.

```python
TROUGH_GEOMETRY_GRID = {
    "trough_search_radius_months": [3, 4, 5],
    "adaptive_trough_search_radius_months": [3, 4, 5],
    "adaptive_min_usable_months_per_cycle": [5, 6, 7, 8],
}
```

Invalid combinations are rejected before scoring:

- `adaptive_trough_search_radius_months < trough_search_radius_months` — the
  retry must never narrow the search.
- `adaptive_min_usable_months_per_cycle > 8` — the relaxation must never
  tighten the base minimum.

This leaves 24 valid tuples: six radius pairs `(3,3) (3,4) (3,5) (4,4) (4,5)
(5,5)` times four coverage values. The shipped geometry `(3, 5, 6)` is one of
the 24 and competes on equal terms.

Unlike the timing-identifiability cache, this grid is **not**
threshold-independent. Changing a radius changes detection itself, so the cache
runs full boundary detection once per `(record, tuple)` pair.

---

## 5. Predeclared metrics and lexicographic selection

Scored on the synthetic geometry calibration partition (§6) only.

| Metric | Definition |
|---|---|
| `false_precise_boundary_rate` | Published boundary on a year whose truth carries no identifiable point trough. Reported with a Wilson interval. |
| `duplicate_or_nonmonotonic_rate` | Boundaries within a record that repeat or fail to increase strictly. |
| `boundary_mae` | Median absolute error in months between the published boundary and the truth trough date, over truth-identifiable years with a published boundary. |
| `boundary_signed_bias` | Mean signed error in months, same denominator. Positive means late. |
| `wrong_cycle_rate` | Published boundary whose nearest truth trough belongs to a different truth year. |
| `short_long_cycle_rate` | Published cycles with `cycle_months` outside `[10, 14]`. |
| `coverage_drop_rate` | Years failing with `status_reason == "insufficient_cycle_coverage"`. |
| `abstention_rate` | Truth-identifiable years with no published boundary. |
| `outside_window_lower_rate` | Report-only. **Excluded from selection.** |

`outside_window_lower_rate` is excluded because it is a challenge count against
an unlabelled alternative, not an error rate against truth. Selecting on it
would reward any tuple that widens the window regardless of whether the wider
choice is correct — the exact error §1.1 warns against.

**Selection is lexicographic. Stages run in this order and never reorder:**

1. Retain candidates whose `false_precise_boundary_rate` Wilson upper bound is
   `<= 0.05`.
2. Retain candidates with `duplicate_or_nonmonotonic_rate == 0`. This is a hard
   structural gate: a policy that can emit non-monotonic boundaries is
   inadmissible at any accuracy.
3. Minimise `boundary_mae`.
4. Minimise `wrong_cycle_rate`.
5. Minimise `abstention_rate`.
6. Minimise `abs(boundary_signed_bias)`.
7. **Status-quo tie-break.** Among remaining ties, prefer in order: the shipped
   tuple `(3, 5, 6)` exactly; then smaller `trough_search_radius_months`; then
   smaller `adaptive_trough_search_radius_months`; then larger
   `adaptive_min_usable_months_per_cycle`.

Stage 7 exists so that a geometry change must be *earned*. A tie does not
justify republishing every hydrological year in every downstream record.

If stage 1 or 2 empties the candidate set, calibration raises rather than
relaxing a gate.

Untouched synthetic validation is report-only and cannot trigger reselection.

---

## 6. Synthetic geometry corpus

A new corpus, deliberately independent of `generate_record` and
`generate_timing_identifiability_record`, so that adding it perturbs neither
frozen artifact. Disjoint seed ranges:

```python
GEOMETRY_CALIBRATION_SEEDS = range(30000, 35000)
GEOMETRY_VALIDATION_SEEDS  = range(40000, 45000)
```

Existing partitions cannot calibrate this choice: legacy timing jitter and
phase drift reach only about `±2`, and the timing-identifiability corpus uses
fixed extrema. Neither corpus contains a year whose true trough lies outside a
radius-3 window, so neither can distinguish radius 3 from radius 5.

Ten families, each 12 years of monthly counts:

| Family | What it tests |
|---|---|
| `stationary_trough` | Control. Fixed trough month; every radius should be equal. |
| `wide_phase_excursion` | Truth trough wanders to `±5` from the anchor. Radius 3 structurally cannot reach it. |
| `abrupt_phase_shift` | Step of 4 months at the record midpoint. |
| `competing_secondary_minimum` | A near-equal second low six months away. Punishes indiscriminate widening. |
| `tied_low_plateau_wide` | Five-month equivalent-low plateau. No point truth; a published point date is a false precise boundary. |
| `missing_outer_months` | Outer `±4`/`±5` months absent. Widening buys nothing; coverage cost is pure loss. |
| `quality_loss_outer_months` | Outer months present but invalid. |
| `zero_dominated_wide_excursion` | Zero-dominated record plus excursion. Guards the `established_0_2_0` interaction. |
| `short_cycle_stress` | True troughs nine months apart. Stresses minimum coverage. |
| `long_cycle_stress` | True troughs fifteen months apart. |

Truth labels:

```python
@dataclass(frozen=True)
class TroughGeometryTruthLabels:
    climatological_trough_month: int
    n_years: int
    trough_date_by_year: tuple[pd.Timestamp | None, ...]
    identifiable_by_year: tuple[bool, ...]
    max_abs_excursion_months: int
```

`identifiable_by_year` is `False` for plateau and fully-masked years, where no
point truth exists and abstention is the correct answer.

### 6.1 Fingerprint

`trough_geometry_fingerprint()` hashes the corpus generator, the truth type, the
detector entry points, the cache and selector sources, the grid, the calibration
seed list, the selected tuple, and the authority scope — mirroring
`timing_identifiability_fingerprint()`. Validation truth is excluded from the
hash. Calibration, validation, and cohort artifacts must all report the same
fingerprint.

---

## 7. Out of scope, with the condition that would bring it back

**Bidirectional adaptive retry is deliberately not in this design.** A
right-moving retry needs the directional inverse of `not_later_than`,
validation of *both* cycles sharing the moved boundary, ordered-unique result
checks, and atomic rollback of both on failure. It is the highest-complexity
item available here and it may be unnecessary: a calibrated base radius may
subsume it entirely.

**Re-entry condition, predeclared:** open a bidirectional-retry design only if
the selected tuple from §5 still leaves, on the untouched synthetic validation
partition, a `boundary_mae` above 1.0 month on the `wide_phase_excursion` and
`abrupt_phase_shift` families combined. Building both mechanisms in one pass
would make it impossible to attribute the improvement to either.

If that design does open, it must satisfy: adjacent operational boundaries
present; complete raw outer-span observations; a materially lower outer value
under a predeclared noise and resolution rule; fixed non-target boundaries;
ordered unique results; and no coverage or timing regression in either cycle
sharing the moved boundary — with rollback of both on failure. A mirrored
helper alone does not satisfy this.

---

## 8. Promotion checklist

The sweep has two admissible outcomes, and both are publishable.

### 8.1 Null result — shipped tuple `(3, 5, 6)` wins

1. Diagnostics from §2 ship, boundaries unchanged.
2. `ESTABLISHED_POLICY` remains `established_0_2_0`.
3. Public schema addition still requires `docs/report-columns.md` updates and a
   migration note for the new columns.
4. The calibration report records that the shipped tuple was selected against
   truth, converting three inherited constants into calibrated ones. This is a
   real result and is reported as such, not as "no change".

### 8.2 A different tuple wins

Every gate in `docs/decision-policy.md` applies, plus:

1. `false_precise_boundary_rate` Wilson upper bound `<= 0.05` on untouched
   synthetic validation.
2. `duplicate_or_nonmonotonic_rate == 0` on untouched synthetic validation.
3. Calibration, validation, and cohort artifacts share one
   `TROUGH_GEOMETRY_FINGERPRINT`.
4. Protected Daly, Fitzroy, Gilbert, Lachlan, and Moonie outcomes reviewed. A
   changed boundary here is admissible only with explicit reviewed evidence, and
   is recorded in the comparison report either way.
5. The three motivating records (130413a Denison, 130407a Nebo, 130302a Taroom)
   pass qualitative checks with no station-specific code.
6. An **independent, previously uninspected** real cohort reports outcomes,
   disagreements, and uncertain labels without changing any parameter.
7. A new versioned policy identifier `established_0_3_0`, a new
   `docs/decision-policy-0.3.0.md` promotion record, and migration notes
   describing that published hydrological-year boundaries change.

`established_0_2_0` must **not** be silently retained across a geometry change.

---

## 9. Evidence limits frozen in advance

- **The 34-catchment stress bundle is development evidence only.** It motivated
  this design and its exploratory sweep is reported in §1.1. It may not select
  any parameter. Selecting geometry from outputs already inspected for this
  issue would be in-sample fitting.
- **The existing 21-station timing-identifiability cohort is no longer
  untouched for this question.** It was inspected during the radius audit.
  Promotion under §8.2 needs a new independent cohort.
- **The protected and motivating records are diagnostic, not selective.** They
  are checked only after the tuple is frozen.
- **Real stress CSVs carry no pixel counts.** They report
  `pixel_support_status="unavailable"`; any pixel-count-dependent evidence is
  synthetic-only, as already recorded for `established_0_2_0`.
- **SciPy is optional** under the `raster` extra. Core boundary logic must not
  acquire a SciPy dependency. No part of this design adds one.
- **Within-catchment cycles are serially dependent.** Every cohort interval is a
  catchment-level bootstrap. Cycle-level Wilson intervals are reported only
  within a single catchment and labelled as understatements.
- Every stochastic run records package version, input fingerprint, threshold
  fingerprint, and seed.
