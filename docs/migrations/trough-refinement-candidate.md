# Trough refinement: candidate policy, not promoted

This note describes an **additive, opt-in, non-authoritative** addition. The
public decision policy remains `established_0_2_0`. No hydrological-year
boundary, peak date, trough date, regime, or route changes for any existing
caller.

## What was added

A two-pass trough refinement challenger. Pass 1 is the shipped detector,
unchanged. Pass 2 fits a robust, shape-constrained valley profile between the
peaks bracketing a trough, and may propose a better-supported boundary.

The challenger is **off by default**. It runs only when a caller passes an
explicit `trough_refinement_policy` to `DynamicHydroYearConfig`. With no policy
supplied, every output is byte-identical to before this work, and the evidence
columns report `trough_refinement_status="unavailable"` with reason
`not_requested`.

New diagnostic columns are documented in
[Export Columns](../report-columns.md#trough-refinement-evidence-candidate--not-authoritative).

## What did not change

- `ESTABLISHED_POLICY` remains `established_0_2_0`.
- The compact CSV bundle. `STABLE_HY_COLUMNS` is unchanged, so code reading the
  default CSVs sees no new columns.
- Every boundary, date, regime, and route on the default path.
- Peak selection. The challenger never moves a peak; zero peak changes is a
  frozen gate, verified on both calibration and validation partitions.

## Authority scope

`TROUGH_REFINEMENT_AUTHORITY_SCOPE` is `candidate_for_established_0_2_0`.

Calibration fingerprint (calibration and validation share it):

```
049f16f04035d6d1dadf805192bce57b7c0750cab283c9410881d9302cb9ea2d
```

Selected policy: `huber_k=1.345`, `profile_loss_cutoff=0.05`, `pulse_z=1.5`,
version `trough_refinement_candidate_0_1`.

## Evidence so far

Synthetic calibration (seeds 70000–74999) and untouched synthetic validation
(seeds 80000–84999) both pass all ten frozen gates. Validation ran with
`reselection: 0` — it scored the frozen tuple rather than selecting one.

| Metric | Calibration | Validation |
|---|---|---|
| Boundary set inclusion | 1.000 | 1.000 |
| False-precise boundary rate | 0/1176 | 0/1177 |
| False-precise Wilson upper | 0.0033 | 0.0033 |
| Median distance (months) | 0.0 | 0.0 |
| p90 distance (months) | 0.0 | 0.0 |
| Pass-1 p90 distance (months) | 1.0 | 1.0 |
| Coverage | 1.000 | 1.000 |
| Abstention rate | 0.000 | 0.000 |
| Peak changes | 0 | 0 |
| Duplicate/nonmonotonic boundaries | 0 | 0 |
| Wrong-cycle boundaries | 0 | 0 |
| New uncomputable cycles | 0 | 0 |

## Why promotion is still unavailable

**Synthetic evidence alone cannot promote this policy.** Promotion additionally
requires a blinded real-catchment holdout, and that holdout does not exist yet.

The protocol, review rubric, builder, and evaluator are in place
(`case_studies/trough-refinement/`, `scripts/build_trough_refinement_cohort.py`,
`scripts/evaluate_trough_refinement_cohort.py`). What is missing is an
**eligible, previously uninspected source root**. Every real bundle this project
holds has already been inspected — the 34-catchment stress bundle underpins the
radius audit, the geometry work, and the recurrence investigation, and the
protected catchments and motivating records are development evidence by
definition. All are in the protocol's `excluded_sources`, and the builder exits
nonzero rather than sampling one.

The cohort must also yield at least **73 algorithm point predictions** with
adjudicated truth for the zero-error false-precision gate to be evaluable at a
0.05 Wilson upper bound. A smaller cohort reports `unavailable`, never
`passed`, and **is not enlarged after results are seen**.

Until that holdout runs and passes, this policy stays a candidate regardless of
how good the synthetic numbers look. Diagnostic success on Daly, Fitzroy,
Gilbert, or any inspected stress record cannot substitute for it.

## Rollback

Because the challenger is opt-in, rollback is simply not passing a
`trough_refinement_policy`. To remove it entirely, revert the commits
implementing the challenger and its calibration; nothing on the default path
depends on them.

## Downstream impact

Code that enumerates diagnostic hydrological-year columns positionally, or
asserts an exact column count on `build_hydro_years_export`, needs updating.
Code reading columns by name, and any code reading the compact CSV bundle, is
unaffected.
