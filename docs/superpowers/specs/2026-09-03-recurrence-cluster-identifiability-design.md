# Recurrence-Cluster Timing Identifiability Design

**Date:** 2026-09-03

**Status:** proposed for review

**Target release and policy:** HydroSeason 0.2.0 under
`established_0_2_0`. Version 0.2.0 has not launched, so this correction does
not create a 0.2.1 policy or package version. Existing 0.2.0 promotion evidence
is reopened until this design's gates pass.

**Source handoff:**
`docs/superpowers/handoffs/2026-09-03-recurrence-cluster-false-point.md`

## Problem

`assess_window_timing()` first classifies the complete set of equivalent peak
or trough dates. When that set is too wide, it calls
`_most_recent_recurrence_cluster()`, which splits dates at gaps larger than
`max_boundary_interval_months` and returns the last cluster. The helper does
not establish that the dates contain repeated annual occurrences. Missing or
masked months can therefore split one diffuse low-water set into clusters and
turn its last fragment into a false `"point"` or `"interval"`.

The defect is broader than the handoff's synthetic example. The helper's
docstring limits its rationale to cycles unusually longer than a year, but the
caller invokes it for every unresolved window. It therefore narrows ordinary
8--12 month cycles that cannot contain two complete annual occurrences.

## Audit Corrections

These findings supersede conflicting statements in the handoff.

1. The minimal reproduction is invalid verbatim. With only `n_valid` present
   and `pixel_support_status="available"`, `peak_n_water` is unavailable and
   detectability is gated off. The reproduction works with
   `pixel_support_status="unavailable"`, or with the complete count columns
   `n_water`, `n_valid`, `n_invalid`, and `n_aoi`.
2. The end-to-end `generate_trough_geometry_record(30035,
   partition="calibration")` reproduction is valid: HY1993 reports a raw
   1993-04 point trough although its truth label is unidentifiable.
3. `_most_recent_recurrence_cluster()` was added in commit `d6d508d` during
   real-cohort validation. It was not part of the frozen 0.2.0 design, the
   timing-identifiability grid, or its synthetic calibration and untouched
   validation.
4. `timing_identifiability_fingerprint()` hashes calendar-year assessment but
   not `assess_window_timing()` or the recurrence helper. The existing
   fingerprint therefore cannot attest to this behavior.
5. A read-only comparison on the local 34-record stress bundle found that
   disabling narrowing changes 115 peak/trough classifications across all 15
   records that currently retain per-year output. It changes record category
   or route for all 15; 9 are members of the existing 21-station cohort.
6. On protected 30 m fixtures, disabling narrowing leaves all five routes
   unchanged but changes 20 annual classifications: Daly 6, Fitzroy 8, and
   Gilbert 6. Lachlan and Moonie remain event-routed.
7. Among the motivating records, Taroom has 10 affected extrema. Denison and
   Nebo remain event-routed and expose no annual rows.
8. Existing cohort labels are record-level labels. They neither identify the
   affected annual cycles nor distinguish genuine recurrence from a
   gap-fragmented plateau. They cannot select a replacement recurrence rule.
9. `TIMING_IDENTIFIABILITY_FINGERPRINT` is a live tripwire, not documentation.
   `tests/test_scientific_defaults.py` asserts that
   `timing_identifiability_fingerprint()` still equals the frozen constant and
   that both the frozen calibration and validation report payloads carry it.
   The fingerprint hashes `asdict(thresholds)` plus the source of
   `_validate_tolerance`, `_resolution_pp`, `_peak_water_pixels`,
   `prepare_monthly_extent`, and `robust_scale` --- all shared with the window
   path. Touching any of them, or adding a field to
   `TimingIdentifiabilityThresholds`, invalidates the frozen threshold
   provenance and forces a full timing recalibration this design does not
   authorise.
10. `hydroseason/_scientific_defaults.py` is generated, and its two writers
    disagree by design. `_write_timing_identifiability_defaults()` rewrites the
    whole module, re-emitting the evidence and recoverability constants from
    the previously imported values; `_write_trough_geometry_defaults()`
    appends a block to whatever is already on disk. A recurrence writer must
    therefore be ordered and shaped deliberately, or it will silently drop the
    appended geometry block.
11. `linear_span_months()` returns the month *difference* between the earliest
    and latest date, not a count of positions: a singleton is `0` and two
    adjacent months are `1`. Every window-length condition in this design must
    be stated against that convention.
12. Candidate C is already known to preserve the one positive test the current
    helper exists for. In
    `test_window_timing_recovers_a_recurring_peak_in_an_oversized_cycle` the
    two peaks fall on 1990-04 and 1991-03 --- 11 months apart, not 12 ---
    so shifting the earlier cluster forward 12 months leaves a nearest-date
    distance of 1, inside both the test threshold (3) and the production
    threshold (2). This is a pre-existing property of the fixture, not
    evidence, and does not license tuning against it.
13. The handoff reproduction and its correction in item 1 were confirmed by
    execution, not by reading: `pixel_support_status="available"` yields
    `detectable=False`, `trough_status="unresolved"`, `trough_dates=()`;
    `"unavailable"` yields `"point"` and `(1993-04-01,)`.

The stress bundle, protected fixtures, motivating records, seed 30035, and the
existing cohort are development evidence because they have now been inspected.
None may select the replacement rule.

## Goals

1. Prevent missing-data fragmentation from producing a false point or short
   interval.
2. Preserve a most-recent occurrence only when independent evidence supports
   an annual recurrence inside a longer-than-annual window.
3. Make a conservative no-narrowing result publishable if no safe recovery
   rule survives calibration and validation.
4. Keep every change under version 0.2.0 and policy ID
   `established_0_2_0`.
5. Reopen and rerun affected 0.2.0 evidence before launch.
6. Unblock trough-geometry calibration without inspecting its untouched
   validation partition early.

## Non-Goals

- Do not change the calibrated timing-identifiability threshold tuple.
- Do not tune against seed 30035, the 34-record stress bundle, the protected
  catchments, the motivating records, or existing cohort labels.
- Do not change boundary search geometry in this work.
- Do not infer values for missing months or convert observed zeroes to missing.
- Do not promise recovery of every long-cycle recurrence. Safe abstention is a
  valid outcome.

## Considered Approaches

### A. Remove recurrence narrowing

Always retain the complete equivalent-extremum set. This guarantees the known
false point becomes unresolved, but the audit shows substantial utility loss:
all 15 stress records with per-year output change category or route. This is a
required candidate and the conservative tie-break, not an automatic choice.

### B. Add only a longer-than-annual window guard

Apply the legacy last-cluster rule only when a window contains at least 13
calendar positions. This fixes impossible recurrence claims in ordinary
cycles, but a long diffuse plateau can still be fragmented into a plausible
last cluster. This is a useful ablation candidate, not sufficient evidence by
itself.

### C. Require a longer window and annual shape agreement

Apply narrowing only when the latest two clusters are independently resolved
and match after shifting the earlier cluster forward by 12 months. This tests
the physical justification stated by the existing docstring. It is the
recommended recoverable candidate, but it must beat no-narrowing on frozen
synthetic truth and untouched validation before production integration.

## Architecture

### Pure recurrence policy

Create `hydroseason/_recurrence_identifiability.py`. It owns no detector state
and imports no timing dataclasses. Its production interface is:

```python
RecurrencePolicy = Literal[
    "no_narrowing",
    "long_window_last_cluster",
    "annual_shape_match",
]

def narrow_most_recent_recurrence(
    dates: tuple[pd.Timestamp, ...],
    *,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    max_boundary_interval_months: int,
    policy: RecurrencePolicy,
) -> tuple[pd.Timestamp, ...]:
    """Return dates unchanged unless the selected policy proves recurrence."""
```

The module imports `linear_span_months` from `_circular_timing` and uses it for
every span, gap, and window measurement, so clustering is bit-identical to the
current helper and to `_window_status()`. It imports nothing from
`_timing_identifiability`, which is what keeps the dependency acyclic once
`assess_window_timing()` imports this module.

`max_point_span_months` is deliberately absent from the signature. No candidate
condition depends on it: a returned cluster's split between `point` and
`interval` is decided by the caller's existing `_window_status()` call, and
every gate below is expressed against `max_boundary_interval_months` alone.
Adding it would imply a second, silent copy of the point/interval rule.

All candidates use the same deterministic cluster split as the current helper:
consecutive equivalent dates join when their gap is at most
`max_boundary_interval_months`.

Window length is measured as
`linear_span_months((window_start, window_end))`, which is a month
*difference*. "At least 13 calendar positions" therefore means
**`linear_span_months((window_start, window_end)) >= 12`**. State the
condition that way in code; the position count is prose only.

Candidate semantics are frozen as follows:

- `no_narrowing`: always return the original tuple.
- `long_window_last_cluster`: require a window span of at least 12 months and
  at least two clusters; then return the last cluster only when that cluster's
  total span is at most `max_boundary_interval_months`.
- `annual_shape_match`: require the same window-span and cluster conditions;
  require both latest clusters to have total span at most
  `max_boundary_interval_months`; shift every date in the penultimate cluster
  forward 12 months; require the shifted and latest clusters to have *equal*
  total span; require symmetric nearest-date distance between shifted and
  latest clusters to be at most `max_boundary_interval_months`; return the
  latest cluster.

The latest cluster's span is already constrained to at most
`max_boundary_interval_months`, so it is by construction `point` or `interval`;
there is no separate final-status test to apply.

Symmetric distance means every shifted earlier date must have a latest-date
match within the limit and every latest date must have a shifted-earlier match
within the limit. This prevents a large cluster plus unrelated singleton from
passing merely because one pair is annual-shaped.

**Audit Correction 13 (equal span).** Symmetric distance alone is not a shape
test. Both clusters are already constrained to a span of at most
`max_boundary_interval_months`, so any two of them separated by roughly twelve
months satisfy the symmetric-distance condition regardless of their widths: a
three-month plateau in the earlier year and a one-month point in the later year
pass, and the policy then publishes a point for a year whose remaining
equivalent months may simply be missing. That is the exact failure this design
exists to remove, so `annual_shape_match` additionally requires the shifted and
latest clusters to have equal total span. Equal span, not equal cardinality:
masking an interior month of a cluster leaves its span intact, so the test does
not punish ordinary gaps. The corpus family `annual_aligned_fragment_trap`
(offsets 1, 2, 3, 13; truth unresolved) exists to enforce this: without the
equal-span requirement `annual_shape_match` narrows it to a false point on
every one of its 120 calibration seeds, which fails the false-resolution gate
and eliminates the candidate before any evidence is weighed. With the
requirement, that family separates `annual_shape_match` (declines) from
`long_window_last_cluster` (narrows), which is what the family is for.

Reusing `max_boundary_interval_months` as the annual-alignment tolerance is a
deliberate choice, not an oversight. Within-cluster tie width and year-over-year
phase drift are different physical quantities, but introducing a separate drift
tolerance would add a free parameter that this design is not authorised to
calibrate (see Non-Goals). The reuse is recorded in the calibration report so a
later design can revisit it with its own evidence.

### Caller contract

`assess_window_timing()` keeps its current gating exactly:

1. compute `peak_dates`/`trough_dates` and their `_window_status()`;
2. call `narrow_most_recent_recurrence()` only when that status is
   `"unresolved"`;
3. recompute `_window_status()` on the returned tuple and adopt the narrowed
   dates only when the returned tuple differs from the original **and** the
   recomputed status is not `"unresolved"`.

No policy may narrow an already-resolved set, and no policy result is adopted
without the caller's own status recomputation. This is the one place the
narrowed dates enter the record.

`legacy_last_cluster` remains available only inside calibration reports as the
known-unsafe baseline. It is never eligible for selection or production.

### Window boundary plumbing

Extend `assess_window_timing()` with optional keyword-only `window_start` and
`window_end`. When omitted, derive them from the first and last value index and
normalise each to month start via `to_period("M").to_timestamp()`. Deriving
rather than rejecting preserves the function's documented contract that
`values` may carry any index; only caller-supplied bounds are validated
strictly. Update the docstring to say so.

`_cycle_timing_evidence()` must pass the full cycle's first and last calendar
positions, not the first and last usable observations. It already receives the
whole `cycle` frame, and `prepare_monthly_extent()` reindexes to a gap-free
`freq="MS"` range, so `cycle.index[0]` and `cycle.index[-1]` are exactly those
positions and no `_assemble_dynamic_years()` signature change is needed.
Missing edge observations must not make a 13-position cycle appear shorter.

### Policy transport

The selected policy must **not** become a field of
`TimingIdentifiabilityThresholds`. That dataclass is hashed by
`timing_identifiability_fingerprint()` through `asdict(selected)`, and
`tests/test_scientific_defaults.py` asserts the frozen fingerprint still
matches; adding a field silently invalidates the frozen threshold provenance
and the frozen calibration and validation report payloads (Audit Correction 9).

Instead:

- `hydroseason/_scientific_defaults.py` gains `RECURRENCE_POLICY`,
  `RECURRENCE_FINGERPRINT`, and
  `RECURRENCE_AUTHORITY_SCOPE = 'candidate_for_established_0_2_0'`, matching
  the existing `TIMING_IDENTIFIABILITY_AUTHORITY_SCOPE` spelling. The scope
  string is promoted to `established_0_2_0` only by the launch gate below.
- `assess_window_timing()` gains a keyword-only `recurrence_policy:
  RecurrencePolicy | None = None`, defaulting to the frozen constant when
  omitted, so calibration can drive candidates through the identical
  production path without a global.
- `DynamicHydroYearConfig` gains the same optional field and
  `_cycle_timing_evidence()` forwards it. This changes
  `trough_geometry_fingerprint()`, which already hashes
  `DynamicHydroYearConfig`; that change is intended and is why the geometry
  cache is rebuilt.
- No function hashed by `timing_identifiability_fingerprint()` may be edited:
  `_validate_tolerance`, `_resolution_pp`, `_peak_water_pixels`,
  `_timing_status`, `assess_timing_identifiability`, `prepare_monthly_extent`,
  `robust_scale`, `equivalent_extremum_months`, and `shortest_circular_span`.
  Re-run `timing_identifiability_fingerprint()` and confirm it is byte-identical
  to the frozen constant before the correction is considered complete.

Both peak and trough narrowing consume the same selected recurrence policy.
No route, boundary, or date-selection code may implement a second copy.

### Independent synthetic corpus

Create `hydroseason/_recurrence_synthetic.py` with disjoint partitions:

```python
RECURRENCE_CALIBRATION_SEEDS = range(50000, 55000)
RECURRENCE_VALIDATION_SEEDS = range(60000, 65000)
```

Use the first 960 seeds from each partition for the frozen runs. Eight families
cycle evenly, giving 120 records per family:

1. `annual_point_recurrence`: two point occurrences in a 13--20 month window.
2. `annual_interval_recurrence`: two one-to-three-month occurrences with the
   same shifted shape.
3. `annual_phase_drift`: genuine recurrence shifted within the existing
   interval threshold.
4. `ordinary_gap_fragmented_plateau`: diffuse set in a window of at most 12
   positions.
5. `long_gap_fragmented_plateau`: diffuse set across a 13--20 month window.
6. `annual_aligned_fragment_trap`: a diffuse set containing an accidental
   12-month pair but mismatched cluster shapes.
7. `scattered_equivalent_ties`: several resolved-looking clusters with no
   annual match.
8. `single_diffuse_cluster`: one wide unbroken cluster.

Each family rotates between peak and trough, count-backed and percentage-only
input, point and interval thresholds, missing-month positions, and 13--20 month
window lengths.

Truth is the generator's construction, recorded at generation time from the
shape the generator was asked to build --- never the output of any policy,
including `no_narrowing`. Families 1--3 are constructed as genuine recurrences
and carry both the intended status and the intended latest date tuple; families
4--8 are constructed as non-recurrences and carry `unresolved`. Deriving truth
from the complete equivalent set instead would make `no_narrowing` correct by
definition and the whole comparison circular.

`RECURRENCE_CALIBRATION_SEEDS` and `RECURRENCE_VALIDATION_SEEDS` do not overlap
the existing `CALIBRATION_SEEDS` (10000--14999), `VALIDATION_SEEDS`
(20000--24999), `GEOMETRY_CALIBRATION_SEEDS` (30000--34999), or
`GEOMETRY_VALIDATION_SEEDS` (40000--44999) declared in
`hydroseason/_synthetic.py`. The recurrence corpus lives in its own module
rather than alongside them because it is scored against a policy rather than a
threshold tuple; the seed constants stay disjoint so a future merge is
mechanical.

Calibration and validation generators share code but use independent RNG
namespaces and seed ranges.

### Calibration and selection

Create `hydroseason/_recurrence_calibration.py`. It runs the four policies
(`legacy_last_cluster` report-only plus three eligible candidates) through the
same pure production helper.

Report these metrics by candidate and family:

- false-point count, rate, and Wilson interval: predicted `point` when truth is
  `interval` or `unresolved`;
- false-resolution count, rate, and Wilson interval: predicted `point` or
  `interval` when truth is `unresolved`;
- genuine-recurrence status accuracy;
- exact latest-date-tuple accuracy;
- conservative-abstention rate;
- counts by peak/trough and pixel-support basis.

Eligible candidates must satisfy both safety gates on calibration:

```text
false-point Wilson upper bound <= 0.05
false-resolution Wilson upper bound <= 0.05
```

Among survivors, maximize exact latest-date accuracy, then status accuracy,
then conservative abstention. Final tie-break order is
`no_narrowing`, `annual_shape_match`, `long_window_last_cluster`; equal evidence
therefore chooses the least inferential rule.

Read that ordering honestly: `no_narrowing` recovers no latest dates on
families 1--3, so it wins only when every narrowing candidate fails a safety
gate, or when a narrowing candidate ties it on all three ranked metrics. Goal 3
makes a `no_narrowing` outcome *publishable*; it does not bias selection toward
it. Conservative abstention is ranked last and is maximised only to break ties
between candidates of identical accuracy.

The calibration runner writes the selected policy and SHA-256 fingerprint to
`hydroseason/_scientific_defaults.py`. The fingerprint includes generator,
the explicit list of the 960 calibration seeds actually run (not the declared
5000-wide range), candidate implementations, metrics, selector, selected
policy, and authority scope. Hashing metrics is a deliberate departure from
`timing_identifiability_fingerprint()` and `trough_geometry_fingerprint()`,
which hash inputs only; record the reason in the report so the divergence is
not read as an error. Validation truth and validation seeds are excluded.

The writer must respect the generated module's existing two-writer convention
(Audit Correction 10). Add `_write_recurrence_defaults()` as an **appending**
writer modelled on `_write_trough_geometry_defaults()`, and order the runner so
any full regeneration by `_write_timing_identifiability_defaults()` happens
first. Add a test that runs the timing, recurrence, and geometry writers in the
runner's own order against a temporary module and asserts all three blocks
survive; the current pair has no such test and the failure mode is silent.

Untouched validation runs once with the frozen policy and fingerprint. It does
not search candidates. A narrowing policy may proceed only when validation
meets both safety gates and at least 0.90 genuine-recurrence status accuracy.
If `no_narrowing` is selected, low recurrence recovery is recorded as a null
result, not a failed safety correction.

### Real-data evidence

Produce two distinct reports:

1. A development impact report over the already-inspected 34-record bundle,
   protected catchments, motivating records, and existing cohort. It lists
   every changed annual status, interval endpoint, route, record category, and
   downstream condition-baseline eligibility. It cannot select a policy.
2. A blinded cycle-level cohort drawn from a source not used anywhere in this
   audit or prior timing work. Review packets contain observation dates,
   extents, quality/missingness, and cycle bounds but no policy output. Labels
   are `point_supported`, `interval_supported`, `unresolved`, or `uncertain`.
   Freeze labels before joining candidate outputs. Catchments, not cycles, are
   the bootstrap unit.

A non-disabled policy cannot be promoted without zero direct contradictions in
the blinded cohort: reviewer `unresolved` paired with a published point. If no
eligible independent source is available, `no_narrowing` is the only
promotable policy; recovery remains deferred.

## 0.2.0 Evidence and Documentation

Because 0.2.0 has not launched, retain package version `0.2.0` and policy ID
`established_0_2_0`. Reopen the existing promotion record rather than creating
a patch-version policy:

- amend `docs/decision-policy-0.2.0.md` with recurrence policy, corpus,
  selection rules, results, and corrected promotion checklist, preserving every
  phrase `tests/test_decision_policy_docs.py` pins --- including the grid
  lines, `"promoted to public policy identifier \`established_0_2_0\`"`, and
  `"false precise-boundary Wilson upper bound <= 0.05"`. Amend by addition;
  do not restructure sections those assertions read;
- preserve the original timing-threshold reports and fingerprint as threshold
  provenance, and confirm `timing_identifiability_fingerprint()` still returns
  `e6cdf3ce960aa011711dc90e3ef4fb0135513eadaf471f4ac9e0656f80884735`;
- amend the existing dated `## [0.2.0] - 2026-08-31` CHANGELOG entry in place
  rather than opening a `0.2.1` section; the entry is dated but no `v0.2.0` tag
  exists, which is what "has not launched" means here. Reset or annotate the
  date to the corrected freeze date;
- add separate recurrence calibration and validation reports and fingerprint;
- regenerate the 21-station comparison under the selected rule without
  changing frozen labels;
- update migration notes, report-column semantics, changelog, and launch
  evidence;
- keep `ESTABLISHED_POLICY == "established_0_2_0"` throughout.

No result may claim 0.2.0 launch readiness until recurrence validation,
protected checks, motivating checks, the blinded cycle cohort when required,
full tests, and strict docs all pass.

## Trough-Geometry Re-entry

Trough-geometry calibration remains paused until the recurrence policy is
frozen and integrated. Then:

1. Replace the bug-pinning `8/64` assertions in
   `test_selector_composes_with_a_real_cache_from_the_calibration_partition`
   (`tests/test_calibration.py`: `metrics["n_false"] == 8.0`,
   `metrics["n_unidentifiable"] == 64.0`, and the surrounding
   `pytest.raises(RuntimeError, match="false precise-boundary")`) with the
   corrected safety contract; never weaken the 0.05 gate. Also correct the
   stale `8/64` narrative in that test's docstring and in the docstring of
   `test_geometry_runner_writes_defaults_and_a_report`, which repeats the
   claim without asserting it. Keep the `tied_low_plateau_wide` published-count
   assertion --- it pins a different, still-valid fix.
2. Add recurrence policy source and fingerprint to
   `trough_geometry_fingerprint()` because geometry scoring consumes window
   timing status. Note that `inspect.getsource()` does not follow callees, so
   `assess_window_timing`, `_window_status`, and
   `narrow_most_recent_recurrence` must be listed explicitly; hashing
   `detect_dynamic_hydrological_years` does not cover them today.
3. Rebuild the geometry calibration cache from calibration seeds. Prior cache
   outcomes are stale.

   This step carries a falsifiable prediction, recorded now so it cannot be
   rationalised afterwards. The current 8 false-precise boundaries are traced
   entirely to `missing_outer_months` seeds 30005, 30015, 30025, and 30035 ---
   the first year of each two-year masked gap --- which is the same
   gap-fragmentation mechanism this design corrects. If a narrowing-suppressing
   policy is selected, `n_false` is expected to fall toward 0 and
   `select_trough_geometry_defaults()` may stop raising. If it does not fall,
   the residual is a corpus-labelling disagreement rather than this bug, and
   must be reported as an open question rather than absorbed into the
   geometry selection.
4. Resume Task 8 of
   `docs/superpowers/plans/2026-09-02-trough-window-geometry.md`.
5. Keep `GEOMETRY_VALIDATION_SEEDS` untouched until that plan's Task 9 gate.
6. Keep all geometry work under version 0.2.0 unless its own frozen design
   later selects a boundary-changing tuple and requires 0.3.0 promotion. That
   conditional is already frozen in `docs/decision-policy-0.3.0.md` and pinned
   by `tests/test_decision_policy_docs.py`; leave
   `TROUGH_GEOMETRY_AUTHORITY_SCOPE = "candidate_for_established_0_3_0"`
   exactly as it stands. This design does not reopen that question.

## Error Handling and Invariants

- Reject caller-supplied window bounds that are non-month-start or
  non-monotonic. Bounds derived from the value index are normalised to month
  start instead of rejected, so existing direct callers keep working.
- Return original dates for empty/singleton sets, one cluster, windows shorter
  than 12 months of span, latest clusters wider than
  `max_boundary_interval_months`, or failed annual-shape matching.
- Never return dates outside the original tuple.
- Never narrow a set whose initial `_window_status()` is already `point` or
  `interval`.
- Never allow selected recurrence policy and recorded fingerprint to disagree.
- `timing_identifiability_fingerprint()` must remain byte-identical across this
  work. A change there means a hashed function was edited and the correction is
  out of scope until reverted.
- Validation exits before reading its corpus when the calibration fingerprint
  is stale.
- Reports are append-only evidence. Preserve original 0.2.0 reports rather
  than overwriting their historical contents.
- Any synthetic or real safety-gate failure stops promotion; do not relax a
  threshold or relabel truth after viewing the result.

## Plan Decomposition

After approval, write two implementation plans:

1. **Recurrence-identifiability correction:** corpus, candidate rule,
   calibration, untouched validation, production integration, real evidence,
   0.2.0 documentation, and release gates.
2. **Trough-geometry re-entry:** fingerprint correction, stale-test cleanup,
   calibration restart, and precise handoff back to Tasks 8--11 of the existing
   geometry plan.

The first plan must finish before the second begins.
