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
- Peak selection. The challenger never moves a peak; measured zero peak
  changes across 2400 matched cycle rows in the full-pipeline evaluator
  (see Evidence below) — not a gate in the per-span component harness,
  which cannot measure this property at all.

## Authority scope

`TROUGH_REFINEMENT_AUTHORITY_SCOPE` is `trough_refinement_candidate_0_2` (bumped from
`trough_refinement_candidate_0_1` in the 2026-09-08 final scientific hardening pass, which
corrected the calendar-gap, loss-unit, and support-truncation defects listed below; the fixed
tuple itself was never retuned across either pass).

A subsequent Codex review of that same pass
(`case_studies/results/final-review-2026-09-08/reviews/codex-final.md`) found a further defect
in the gap-handling fix: it only checked the *first* post-gap value for a return to the pre-gap
low, so a *later* equivalent-low return could still be silently excluded from the reported
support set. This is now fixed (see
`case_studies/results/final-review-2026-09-08/reviews/fixes-for-codex-astra-6.md`, finding C1);
it does not manifest on this synthetic corpus or the inspected real catchments (see below), but
the fingerprint changes because the fix is inside its hashed dependency closure regardless.

Calibration fingerprint (calibration and validation share it):

```
0f4d5432617064cf3c918bee397efdf0c2e0de036bf702b34ed0021b1944c716
```

Selected policy (unchanged, fixed tuple, no grid search this pass): `huber_k=1.345`,
`profile_loss_cutoff=0.05`, `pulse_z=1.5`, version `trough_refinement_candidate_0_2`.

## Evidence so far

Synthetic calibration (seeds 70000–74999) and untouched synthetic validation (seeds
80000–84999) both ran with `reselection: 0` — the frozen tuple was scored directly, never
selected from the grid. **Not every gate passes; this is reported honestly, not adjusted to
pass.**

Component harness (`_trough_refinement_calibration`, challenges one isolated peak-to-peak
span at a time — see below for what it cannot measure):

| Metric | Calibration | Validation |
|---|---|---|
| Boundary set overlap (predicted/truth intervals intersect) | 0.923 | 0.923 |
| Truth set containment (predicted bounds enclose truth) | 0.923 | 0.923 |
| False-precise boundary rate | 0/1176 | 0/1177 |
| False-precise Wilson upper | 0.0033 | 0.0033 |
| Median distance (months) | 0.0 | 0.0 |
| p90 distance (months) | 0.0 | 0.0 |
| Synthetic-reference-comparator p90 distance (months) | 1.0 | 1.0 |
| Coverage (applied / **resolvable-truth** spans only) | 0.923 (3530/3824) | 0.923 (3529/3823) |
| Abstention rate (same, resolvable-truth-only denominator) | 0.077 | 0.077 |
| All-case coverage (applied / **every** span, resolvable or not) | 0.706 (3530/5000) | 0.706 (3529/5000) |
| All-case abstention rate (same, all-case denominator) | 0.294 | 0.294 |
| Wrong-cycle boundaries (genuinely measured) | 0 | 0 |
| Peak changes / duplicate-or-nonmonotonic / new-uncomputable | not evaluated by this harness (see below) | not evaluated by this harness |

`coverage`/`abstention_rate` and `all_case_coverage`/`all_case_abstention_rate` answer different
questions and were previously conflated under one ambiguous "Abstention rate" label with an
unstated denominator — a further Codex finding (C6) on this same pass. Both are now always
published together; see `fixes-for-codex-astra-6.md` for the fix and the corpus's unresolvable
count (1176 calibration / 1177 validation, out of 5000 spans each).

**`boundary_set_overlap = 0.923` is below the informal 0.95 mark this doc previously quoted
as a pass, and that is the honest number, not a regression to fix by retuning.** One synthetic
family (`low_quality_interior`) now correctly abstains on some low-quality-month scenarios
instead of returning a boundary that a downstream disagreement check merely happened to catch
before; see the audit and Opus checkpoint-1 review for the mechanism
(`case_studies/results/final-review-2026-09-08/reviews/opus-math-validation.md`, finding F1).
No support set was narrowed and no threshold was changed to move this number.

**`truth_set_containment` reads identically to `boundary_set_overlap` on this corpus.** The
two metrics are genuinely different formulas (overlap = intervals intersect; containment =
predicted bounds enclose both truth endpoints), but on this synthetic corpus every applied
prediction that overlapped its truth also fully contained it, so they coincide here. This is
not a coding error; a corpus with more partial-overlap cases would separate them.

**"Peak changes", "duplicate/nonmonotonic boundaries", and "new uncomputable cycles" are
`null` ("not evaluated in span harness"), not `0`.** This component harness challenges one
isolated peak-to-peak span at a time and structurally never reassembles adjacent cycles, so it
cannot measure these integration-level properties at all — a prior version of this document
reported them as `0`, which read as "measured and clean" when they were never measured.

A separate, new full-pipeline harness (`scripts/evaluate_final_pipeline.py`) actually runs the
real detector twice (refinement off, then on) on complete synthetic 12-year records with no
supplied truth peaks, and does measure these properties at the integration level:

| Metric | Calibration | Validation |
|---|---|---|
| Matched cycle rows | 1200 | 1200 |
| Peak changes | 0 | 0 |
| Newly uncomputable cycles | 0 | 0 |
| Duplicate/non-monotonic boundaries (before / after) | 0 / 0 | 0 / 0 |
| Boundary precision, off (median / p90 / mean abs error, months; wrong-cycle events excluded) | 0.0 / 0.0 / 0.367 | 0.0 / 0.0 / 0.366 |
| Boundary precision, on | 0.0 / 0.0 / 0.293 | 0.0 / 0.0 / 0.293 |
| Wrong-cycle events excluded from the above (out of 742/743 singleton predictions) | 60 | 60 |

Structural safety holds across both partitions: zero peak changes, zero newly-uncomputable
cycles, zero duplicate/non-monotonic boundary sequences over 2400 matched cycle rows total.
Refinement's mean absolute boundary error is lower than the default detector's in both
partitions (0.293 vs 0.367 months) once wrong-cycle year-misattribution events — a boundary
landing in a neighbouring year, not a precision error — are correctly excluded from the
accuracy pool rather than inflating it.

## `direct_profile_combined`: a second candidate algorithm

A second, algorithmically distinct Pass-2 candidate, addressing a specific
gap `shape_fit` (`trough_refinement_candidate_0_2`) has: it maps a finite set
of best-fitting valley shapes to an exact-loss-optimum endpoint, using one
fixed reference level per shape. `endpoint-findings.md`
(`case_studies/results/low-state-refinement-2026-09-09/`) found that this
does not calibrate reliable timing support for a directly-profiled
low-state-departure target. `direct_profile_combined` instead profiles the
departure directly over a bounded grid of the low-state reference level
itself (`docs/superpowers/specs/2026-09-09-low-state-direct-profile-numerics.md`).

**Still off by default, still not promoted.** Select it explicitly:

```python
TroughRefinementPolicy(
    huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5,
    version="direct_profile_combined_v1",
    candidate="direct_profile_combined",
    delta_pp=0.02,       # required -- no default; see below
    l_uncertainty_k=2.0, # optional, shown at its default
    scale_mode="combined",
)
```

or import the frozen default,
`hydroseason._trough_refinement_direct_profile_defaults.TROUGH_REFINEMENT_DIRECT_PROFILE_POLICY`.
Everything under [What did not change](#what-did-not-change) above holds
identically for this candidate: same off-by-default gate, same unaffected
compact CSV bundle, same unmoved peaks (same atomic two-pass wiring, same
`_quality_sensitivity`/peak-perturbation ensemble — see Wiring below), and
the export column *set* is identical to `shape_fit`'s (report-columns.md's
trough-refinement section covers both).

### `delta_pp` has no default

Unlike `shape_fit`'s hyperparameters, `delta_pp` (the equivalence-state
margin — see the endpoint contract,
`docs/superpowers/specs/2026-09-09-low-state-endpoint-contract.md`, section
3) is not something this package can pick safely for an arbitrary caller: a
sensible value depends on the catchment's own trough-region extent scale.
The frozen default (`0.02` percentage points) was validated only against
catchments whose low-state region sits roughly in the 0.01–2% range (the
five development catchments, Roper River NT, and Kakadu National Park all
fall inside it). A catchment with a materially different trough-region scale
needs its own `delta_pp`, not this default — constructing the policy without
one raises `ValueError` rather than silently defaulting.

### Wiring: real dependency injection, not a monkeypatch

The Stage B research module
(`case_studies/results/low-state-direct-profile-v2/direct_profile.py`) drove
this candidate through production's peak/quality sensitivity ensemble by
temporarily reassigning `hydroseason._trough_refinement._refine_selected_span`
and restoring it in `finally` — explicitly flagged in that module's own
numerics spec (section 8) as a stopgap, not package architecture. The
integrated version replaces that: `_refine_selected_span` is now itself a
small dispatcher keyed on `TroughRefinementPolicy.candidate`, routing to
either the renamed `_refine_selected_span_shape_fit` or
`hydroseason._trough_refinement_direct_profile.refine_selected_span_direct_profile`.
Both are called identically by `refine_trough_span`'s nominal call, its
per-scenario ensemble loop, and `_quality_sensitivity` — so a candidate gets
the real sensitivity ensemble automatically, with no per-candidate
monkeypatching and no risk of leaking a reassigned module attribute across
threads.

### Quality-reliability boundary fallback

The direct-profile support cluster is chosen purely from extent values --
it has no visibility into `quality_state`. A month can be the naive latest
support-cluster member yet be heavily cloud-contaminated (`quality_state ==
"low"`), which is unsafe to publish as the operational boundary: any
downstream step that pulls the extent/raster layer at that exact date
inherits a near-half-invalid observation. `refine_selected_span_direct_profile`
and `_refine_gap_direct_profile` both now walk back from the naive latest
support-cluster (or pre-gap) month to the latest month that is *also*
reliable (`quality_state != "low"`), publishing it as `provisional` with
reason `boundary_deferred_to_reliable_month`, and abstain
(`unresolved`/`no_reliable_boundary_in_support`) if no month in the cluster
is reliable. `shape_fit` is unaffected -- it is frozen (see
[What did not change](#what-did-not-change)).

The gap-path fix was necessary in addition to the main-path fix: the
sensitivity ensemble's own gap-masking scenario can independently reach an
unreliable month via `_refine_gap_direct_profile`, and
`_combine_sensitivity_results` picks the *latest* boundary across all
scenarios as the published result -- so a fix only in the main path left
that ensemble scenario free to smuggle the same unreliable month back in.
Both paths needed the identical reliability walk-back.

Real-catchment effect: Gilbert River 2010 previously reported `2010-12`
(December, heavily cloud-contaminated, with a sharp rise already visible in
November) as `direct_profile_combined`'s boundary; it now correctly defers
to `2010-11`. The five-catchment unblinded bundle below reflects this: 44
identical / 16 differ (previously 45/15, before this fix flipped Gilbert
2010 from "agree" to "disagree" against `shape_fit`, which stays frozen at
`2010-12`).

This fix does not address every "boundary looks early/late" report from
the domain expert's review. Daly River 2016's December-vs-November choice
is *not* a quality issue -- December's own `invalid_pct` is well under the
20% `quality_state` threshold -- and remains open as a separate,
unaddressed question about the equivalence-band/profile math's tolerance
for a real ~2x value jump.

### Evidence

Stage B development matrix (384 synthetic cases, frozen; see
`case_studies/results/low-state-direct-profile-v2/findings.md`): unconditional
support coverage 98.6% (vs. 53.8% for `shape_fit` on the same matrix), median
absolute error 0 months, p90 1 month — the only deployable candidate in that
matrix clearing all three frozen gates. Reserved synthetic seeds and two
held-out shape/noise families never used in development: coverage 97.75%
(vs. 53.9% baseline `shape_fit`) — see the same directory's
`validation-report.json`.

**Informal real-catchment spot check** (not the blinded-cohort protocol —
see [Why promotion is still unavailable](#why-promotion-is-still-unavailable),
which applies to this candidate identically): the domain expert reviewed 17
cycles, across the five development catchments plus Kakadu National Park
(untouched by this work), where `direct_profile_combined` and `shape_fit`
disagreed — labels blinded during review
(`case_studies/results/low-state-direct-profile-v2/blind_review.html`,
`blind_check_all_key.json`). Decoded result: `direct_profile_combined`'s
point answer preferred in 7/17, `shape_fit`'s in 3/17, and in a further 3/17
`direct_profile_combined` correctly abstained
(`unstable_quality_sensitivity`) where `shape_fit` gave a confident but
wrong answer. Of the remaining 4 "both wrong" cases, `direct_profile_combined`'s
*reported support set* (not its point answer) already contained the
reviewer's preferred month in 3 of them. Net: preferred or honestly-uncertain-
in-the-right-place in 13/17.

Five-catchment unblinded bundle
(`case_studies/results/low-state-direct-profile-v2/five_catchment_bundle.csv`,
generated by `five_catchment_bundle.py` from each catchment's frozen pass-1
peaks — pass-1 chronology is unaffected by candidate choice by construction):
60 cycles compared, 44 identical between candidates, 16 differ (see the
quality-reliability fallback above for why this changed from 45/15). The nine
Daly examples the user discussed directly
(`daly_nine_example_disposition.csv`): five cycles (2005, 2011, 2016, 2018,
2020) are identical between candidates (three abstain identically —
`unresolved` on both — and 2016 agrees on `2016-12`, `provisional`); the
other four differ, and were part of the blinded review above — 2008
(`direct_profile_combined`'s `2008-11` preferred over `shape_fit`'s
`2008-10`), 2012 (both wrong; reviewer wanted November, `shape_fit` gave
`2013-02`, `direct_profile_combined` abstained but its support set already
contained the November the reviewer wanted), 2014 (`direct_profile_combined`
abstains with support {Oct, Nov} — the band the reviewer preferred — over
`shape_fit`'s confident `2014-12`), and 2019
(`direct_profile_combined`'s `2019-12` preferred over `shape_fit`'s
`2019-11`). No disagreement was forced to agree, and no case here is claimed
as independently validated real-world evidence — it is a single domain
expert's read of blinded output, recorded honestly with its own limits.

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
Gilbert, or any inspected stress record cannot substitute for it. This
applies identically to `direct_profile_combined`: its dev-matrix and
reserved-seed numbers above, and its informal real-catchment spot check, are
not the blinded real-cohort holdout either, and the existing
`trough-refinement-span-cohort-v1` labels were frozen for `shape_fit`'s
target — reusing them for `direct_profile_combined`'s equivalence-state
target without a fresh blinded round would be scoring one candidate against
labels collected for a different question.

## Rollback

Because every candidate here is opt-in, rollback is simply not passing a
`trough_refinement_policy` (or passing one with `candidate="shape_fit"`, its
default). To remove `direct_profile_combined` entirely, revert the commit
adding `hydroseason/_trough_refinement_direct_profile.py`,
`_trough_refinement_direct_profile_defaults.py`, and the `candidate`/
`delta_pp`/`l_uncertainty_k`/`scale_mode` fields on `TroughRefinementPolicy`;
`shape_fit`'s own commits are unaffected.

## Downstream impact

Code that enumerates diagnostic hydrological-year columns positionally, or
asserts an exact column count on `build_hydro_years_export`, needs updating.
Code reading columns by name, and any code reading the compact CSV bundle, is
unaffected.
