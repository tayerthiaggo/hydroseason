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
    max_point_span_months: int,
    max_boundary_interval_months: int,
    policy: RecurrencePolicy,
) -> tuple[pd.Timestamp, ...]:
    """Return dates unchanged unless the selected policy proves recurrence."""
```

All candidates use the same deterministic cluster split as the current helper:
consecutive equivalent dates join when their gap is at most
`max_boundary_interval_months`.

Candidate semantics are frozen as follows:

- `no_narrowing`: always return the original tuple.
- `long_window_last_cluster`: require the inclusive window to contain at
  least 13 calendar positions and at least two clusters; then return the last
  cluster only when that cluster's total span is at most
  `max_boundary_interval_months`.
- `annual_shape_match`: require the same 13-position window and cluster
  conditions; require both latest clusters to have total span at most
  `max_boundary_interval_months`; shift every date in the penultimate cluster
  forward 12 months; require symmetric nearest-date distance between shifted
  and latest clusters to be at most `max_boundary_interval_months`; return the
  latest cluster only when its final status is `point` or `interval`.

Symmetric distance means every shifted earlier date must have a latest-date
match within the limit and every latest date must have a shifted-earlier match
within the limit. This prevents a large cluster plus unrelated singleton from
passing merely because one pair is annual-shaped.

`legacy_last_cluster` remains available only inside calibration reports as the
known-unsafe baseline. It is never eligible for selection or production.

### Window boundary plumbing

Extend `assess_window_timing()` with optional keyword-only `window_start` and
`window_end`. When omitted, derive them from the first and last value index for
direct callers. `_cycle_timing_evidence()` must pass the full cycle's first and
last calendar positions, not the first and last usable observations. Missing
edge observations must not make a 13-month cycle appear shorter.

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
window lengths. Truth contains the expected full status and, for genuine
recurrences, the expected latest date tuple. Calibration and validation
generators share code but use independent RNG namespaces and seed ranges.

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

The calibration runner writes the selected policy and SHA-256 fingerprint to
`hydroseason/_scientific_defaults.py`. The fingerprint includes generator,
calibration seed list, candidate implementations, metrics, selector, selected
policy, and authority scope. Validation truth and validation seeds are excluded.

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
  selection rules, results, and corrected promotion checklist;
- preserve the original timing-threshold reports and fingerprint as threshold
  provenance;
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

1. Replace the bug-pinning `8/64` assertion in `tests/test_calibration.py` with
   the corrected safety contract; never weaken the 0.05 gate.
2. Add recurrence policy source and fingerprint to
   `trough_geometry_fingerprint()` because geometry scoring consumes window
   timing status.
3. Rebuild the geometry calibration cache from calibration seeds. Prior cache
   outcomes are stale.
4. Resume Task 8 of
   `docs/superpowers/plans/2026-09-02-trough-window-geometry.md`.
5. Keep `GEOMETRY_VALIDATION_SEEDS` untouched until that plan's Task 9 gate.
6. Keep all geometry work under version 0.2.0 unless its own frozen design
   later selects a boundary-changing tuple and requires 0.3.0 promotion.

## Error Handling and Invariants

- Reject non-month-start or non-monotonic window bounds.
- Return original dates for empty/singleton sets, one cluster, short windows,
  unresolved latest clusters, or failed annual-shape matching.
- Never return dates outside the original tuple.
- Never allow selected recurrence policy and recorded fingerprint to disagree.
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
