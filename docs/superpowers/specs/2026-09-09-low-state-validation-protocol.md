# Low-state validation protocol

**Date:** 2026-09-09

**Status:** Stage A, Step 2 deliverable. Freezes truth, scoring, and the
development/validation partition for the direct-profile hypothesis (Step 3).
No new solver is run against this protocol before it is recorded, per its
exit criterion.

**Depends on:** the endpoint contract
([Step 1](2026-09-09-low-state-endpoint-contract.md)) for target definitions
(`sigma_pp`, `delta_pp`, equivalence-state endpoint, latent change point,
representative-date convention).

**New experimental directory:** `case_studies/results/low-state-direct-profile-v2/`
(created alongside this document; reserved for the Step 3/4 numerical
candidate's outputs, kept separate from the frozen
`low-state-refinement-2026-09-09/` prototype evidence so neither directory's
manifest or hashes are disturbed).

## 1. Truth fields: latent change point vs. declared low-state endpoint

The frozen first experiment
(`case_studies/results/low-state-refinement-2026-09-09/evaluate_endpoint.py`)
stores exactly one `truth_index` per synthetic record. Its `FAMILIES` table
truth values (e.g. `"plateau": (..., 6)`) are **latent change-point** truth:
the last month exactly at the family's programmed minimum, independent of
any margin. The post-inspection supplement
(`supplement/assess_estimand.py`) overwrites that same field with an
**equivalence-band** truth (`last index with latent <= min(latent) +
sigma_pp`), using the generator's own noise sigma as the margin.

Per Step 1 §2 and §5, these are different quantities and neither may
overwrite the other. This protocol requires two separate truth fields in
every new synthetic record:

- `latent_change_point_index`: the family's programmed last-month-at-minimum
  index (what `evaluate_endpoint.py`'s `FAMILIES` table currently calls
  `truth`), always computed from the generator's latent series, never from a
  fitted or predicted value.
- `declared_endpoint_index`: the equivalence-state truth under a
  **protocol-fixed** `delta_pp` (Step 1 §6) applied to the generator's own
  latent series and minimum — structurally the supplement's computation, but
  using the protocol's declared `delta_pp` rather than each scenario's own
  injected noise sigma, so the margin is fixed independently of the noise
  level being tested (Step 1 §6, and see §6 below on `sigma_pp` vs.
  `delta_pp` reuse).
- Both fields are populated for every record, including `None` where a
  family has no departure at all (`no_recovery`-type families) or where the
  declared endpoint is not interior (excluded by construction, see §2).

`declared_endpoint_index` (not `latent_change_point_index`) is the primary
scoring truth (Step 1 §5). `latent_change_point_index` is retained as a
secondary diagnostic column in every summary table so a reviewer can see,
per case, how far the equivalence target and the change-point target
diverge — this is exactly the check the endpoint contract's Example 2
(gradual recovery) requires evaluators to make explicit.

## 2. Truth provenance and oracle flagging

- Truth (`latent_change_point_index`, `declared_endpoint_index`) is computed
  only from the generator's own latent array and the protocol's declared
  `delta_pp`. It is never derived from a candidate's fitted `L`, its
  estimated scale, or its predicted boundary.
- A candidate that receives the generator's own noise sigma as an input
  (`oracle_scale` in `evaluate_endpoint.py`'s `predictions()`) is tagged
  `oracle_input: true` in every record it produces. Oracle-tagged candidates
  are reported in development tables for diagnostic comparison only and are
  explicitly excluded from the deployable-candidate gate evaluation (§7);
  they are not eligible for Step 4/5 promotion regardless of their scores.
- **Latent identifiability vs. observation identifiability:** a case's
  `declared_endpoint_index` can be a known, fixed integer while the noisy or
  gapped *observed* sequence still cannot resolve it. This protocol records
  both: `declared_endpoint_index` (latent, always defined when a departure
  exists) and, per candidate, whether that record was `resolvable_from_observation`
  — true only when the case's declared truth index is a real, non-gap month
  in the observed series and not inside a family's engineered unobservable
  region (e.g. `gap_at_endpoint`, where the true index may fall inside the
  masked window). A synthetic case with defined latent truth but an
  engineered gap over that exact month is `resolvable_from_observation:
  false`; scoring must not fault a correct abstention on such a case as an
  error.

## 3. Truth-set taxonomy: point, acceptable-set, and no-boundary cases

Every synthetic and real case is assigned exactly one of three truth
categories, reported separately rather than pooled into one coverage number:

- **Point truth:** `declared_endpoint_index` is a single, resolvable month
  (the common case above).
- **Acceptable-date set:** cases where the endpoint contract itself defines
  more than one equally valid declared date (e.g. an engineered exact-tie
  scenario, or a real-cohort span where the reviewer's interval is the
  ground truth rather than a point — see §8). Truth is the full set; a
  prediction scores as correct if its point prediction lies in the set, and
  as "contained" if its own support set is a subset of the truth set.
- **No-supported-boundary case:** cases with no interior departure at all
  (Step 1 Example 3) or where the protocol declares the case fundamentally
  unresolvable (Step 1 Example 5, gap-adjacent). Truth is `None`.

Two distinct statistics are reported for these categories and must never be
merged into one "accuracy" number:

- **Overlap:** for acceptable-date-set cases, whether the algorithm's single
  predicted date is a member of the truth set.
- **Containment:** whether the algorithm's reported support set is a subset
  of (contained within) the truth set — a stricter property than overlap,
  since a broad support set can overlap the truth set while also covering
  implausible months.

## 4. Coverage, abstention, and error statistics

Carried forward from `evaluate_endpoint.py::score_records`, made explicit
and required for every summary row (by family and overall, per candidate):

- `resolvable_n`: count of cases with non-`None` `declared_endpoint_index`.
- `unconditional_support_coverage`: fraction of `resolvable_n` cases where
  the truth index is contained in the algorithm's support set, **counting
  every abstention on a resolvable case as noncoverage** (an abstention is
  never dropped from this denominator).
- `applied_only_coverage`: the same overlap/containment check restricted to
  cases where the algorithm applied a prediction at all (matches the
  existing `resolvable_applied_n`/`resolvable_coverage` split) — reported
  alongside, never in place of, `unconditional_support_coverage`, since
  applied-only coverage can look artificially high when a candidate
  abstains on its hardest cases.
- `all_case_application_rate`: fraction of **all** records (resolvable and
  no-supported-boundary) where the algorithm produced a prediction — this
  is the complementary abstention-rate view across the whole population,
  not just resolvable cases.
- `signed_error_months`: `predicted_index - declared_endpoint_index` for
  every resolved, applied, resolvable case; reported as `median_error_months`
  and `p90_error_months` on absolute value (existing gates), plus
  `early_n`/`late_n` counts on the signed value (existing fields).
- `incorrect_point_predictions_n`: count of applied predictions whose
  support set is a single month (`len(support_indexes) == 1`) that is wrong
  — either the case is a no-supported-boundary case (truth `None`) or the
  single predicted month is not in the truth set. This generalizes
  `evaluate_endpoint.py`'s existing `wrong_point`, which only checked
  against a single point-truth field.
- `support_width_months`: reported per applied case and aggregated
  (`mean`/`median`) so a candidate cannot improve apparent coverage merely
  by reporting wider support.

## 5. Component vs. full-pipeline cases

`evaluate_endpoint.py::evaluate_synthetic` supplies synthetic `PeakBoundary`
objects directly to `refine_trough_span`/`refine_experimental`, bypassing
regime routing and peak detection entirely — a **component** test of the
low-state/endpoint logic only. This protocol keeps that distinction explicit
in every record and summary:

- `evaluation_scope: "component"` for any case built by supplying peaks
  directly (as today), regardless of family.
- `evaluation_scope: "full_pipeline"` reserved for cases that run the
  complete `analyze_hydrological_state`/`detect_dynamic_hydrological_years`
  path, including regime routing and peak detection, on synthetic or real
  monthly series.
- Component-scope results must never be reported as evidence of
  regime-routing or peak-detection performance. Any claim about full-pipeline
  behavior (Stage C, Step 6) requires `full_pipeline`-scope cases.

## 6. Independent realizations, shared seeds, and denominators

`evaluate_endpoint.py`'s `CONFIG["seeds"] = list(range(8))` and its zero-noise
variants (`noise_sigma_pp` including `0.0`) reuse the same latent family
across every `(seed, sigma, phi)` combination, and a `sigma=0.0` case is
identical across all 8 "seeds" (no noise is drawn). This protocol requires:

- **Independent realization groups**: a case is counted as an independent
  sample for any inferential statistic (coverage confidence interval, Wilson
  bound) only if it differs from every other counted case in at least one of
  {random noise draw, shape family, temporal-dependence setting}. All
  `sigma=0.0` variants across the 8 "seeds" for one family collapse into a
  single independent realization for interval-width purposes; they may still
  all be listed in the descriptive summary table, but the inferential
  denominator used for any confidence interval must use the deduplicated
  count.
- Reported descriptive counts (`n`, `resolvable_n`, etc.) may keep the full
  per-record granularity; only interval-width/confidence-bound
  denominators must use the deduplicated independent count. Both the raw
  count and the deduplicated independent count are reported side by side so
  neither is silently substituted for the other.

## 7. Frozen test matrix, budget, and gates (frozen before Step 4 solver code runs)

- **Test matrix**: the existing eight `FAMILIES` shapes plus two additional
  reserved shape/noise families held out from development (§9), each
  crossed with independent noise draws, at least two `noise_sigma_pp`
  levels including `0.0`, and both `ar1_phi` settings — carried forward from
  `evaluate_endpoint.py::CONFIG` with the taxonomy fields of §1-§5 added.
- **Candidate budget**: at most the existing seven named candidates
  (`existing`, `existing_oracle_scale`, and five `project_*` variants) plus
  exactly one new direct-profile candidate family (with at most 3 named
  configurations, e.g. differing only in the automatic-scale hypothesis) may
  be evaluated in the frozen development comparison. A failed candidate is
  not resubmitted under a new name inside the same budget (plan's "do not
  automatically rerun a failed candidate with different constants").
- **Tie-breaking**: identical to the endpoint contract's representative-date
  convention (Step 1 §7) — latest exact-optimum month within the final
  plausible cluster. No new tie-break rule is introduced by this protocol.
- **Evidence gates** (development, Step 4) — preserved from the design note
  and `endpoint-findings.md`, with denominators made explicit per §4/§6:
  - `unconditional_support_coverage >= 0.95` over the deduplicated
    independent resolvable population.
  - `median_error_months <= 1` and `p90_error_months <= 2` over resolved,
    applied, resolvable cases.
  - Zero wrong-cycle results (no candidate places a boundary outside its own
    peak-to-peak span).
  - False-precision criterion: reported the same way as
    `evaluate_endpoint.py::score_records`'s `false_precise_unresolvable_n`
    (§8 distinguishes this from the real-cohort false-precision gate).
  - `support_width_months` and `all_case_application_rate` are always
    reported alongside the above so a broad-interval or high-abstention
    candidate cannot appear to pass by hiding those costs (design note,
    "Evaluate all outputs together").
- **Disjoint development/validation partitions**: the reserved synthetic
  seeds already noted in `evaluate_endpoint.py::CONFIG`
  (`"reserved_validation_seeds": "100000 and above; not run by this
  script"`) remain reserved for Step 5 and are not accessed, inspected, or
  used for any constant selection before Step 5. The two held-out
  shape/noise families of §9 are likewise not accessed before Step 5.

## 8. Synthetic vs. real-cohort false-precision denominators are not interchangeable

These two existing evaluators compute superficially similar
"false-precision" statistics from structurally different denominators, and
this protocol requires both to be reported with their own name and
denominator — never merged or substituted for one another:

- **Synthetic (`evaluate_endpoint.py::score_records`)**:
  `false_precise_unresolvable_n` is counted over `unresolvable` records —
  synthetic cases where `truth_index is None` (no declared endpoint exists)
  but the candidate reported a single-month support set. Its implicit
  denominator is `unresolvable_n`, a **synthetic no-boundary population**,
  and it is a raw count, not a rate.
- **Blinded real-cohort (`scripts/evaluate_trough_refinement_cohort.py`)**:
  `false_precise_rate = false_precise_k / point_prediction_n`, where the
  denominator is `point_prediction_n` — the count of the algorithm's
  **point** predictions among *reviewed, rated* (non-`uncertain`) spans —
  and a case counts as `false_precise` when the algorithm predicted `point`
  but the human reviewer's label was `interval_supported` or
  `no_boundary_supported`. This denominator requires `MIN_POINT_PREDICTIONS
  = 73` algorithm point predictions before the Wilson-bound gate is even
  evaluable, and is gated by `false_precise_wilson_upper_at_most_0_05`
  (two-sided 95% Wilson upper bound), not a raw count.
- Consequence: a low synthetic `false_precise_unresolvable_n` count is not
  evidence toward the real-cohort's `false_precise_wilson_upper_at_most_0_05`
  gate, and vice versa. Step 5's evaluation report must label each
  false-precision figure with which evaluator and denominator produced it.

## 9. Reserved held-out families and seeds

In addition to the reserved synthetic seeds (`100000` and above, §7), this
protocol reserves two full shape/noise families not present in the current
`FAMILIES` table (to be named and fixed in Step 3's numerical specification,
not selected here from any observed candidate behavior) — one with a
temporal-dependence structure beyond `ar1_phi in {0.0, 0.7}` and one with a
noise amplitude beyond `noise_sigma_pp in {0.0, 0.001, 0.004}`. Both are
excluded from every Step 3/4 development comparison and become accessible
only at Step 5.

## 10. Existing regression tests carried forward

Every currently passing test in `tests/test_trough_refinement.py`,
`tests/test_trough_refinement_calibration.py`, and the twelve
prototype/scoring tests already recorded in `endpoint-findings.md`
(`case_studies/results/low-state-refinement-2026-09-09/test_endpoint_experiment.py`)
remains a required regression check for any Step 4 candidate — passing them
is necessary, never sufficient, evidence (per `endpoint-findings.md`:
"Passing numerical tests does not imply that the statistical gates pass").

## 11. Hand-scored worked example (exit-criterion check)

Using Step 1 Example 2 (`latent = [0.40, 0.20, 0.120, 0.121, 0.123, 0.125,
0.14, 0.40]`, `delta_pp = 0.004`):

- `latent_change_point_index = 3` (last exact plateau month before the
  fitted branch begins moving, per the contract's diagnostic definition).
- `declared_endpoint_index = 4` (`0.123 <= 0.120 + 0.004`; `0.125 > 0.124`
  fails at index 5).
- Truth category: point truth (single resolvable month).
- `resolvable_from_observation`: true (no engineered gap over index 4).
- `evaluation_scope`: `component` (as constructed above).

A planned evaluator run over this record must reproduce
`declared_endpoint_index = 4` and classify the case as point-truth,
resolvable, component-scope. Any evaluator implementation that instead
reproduces `3` (the change point) has confused the two truth fields defined
in §1 and fails this protocol's exit criterion.

## Exit check

- The hand-scored example in §11 gives the same result a planned evaluator
  would give it; the process is auditable, not just asserted.
- §1-§2 give `declared_endpoint_index` (numerator target) an explicit
  population (§4's `resolvable_n`) and denominator behavior (§4's coverage
  definitions), satisfying "the 95% claim has an explicit numerator,
  denominator and population."
- No new solver is run against this protocol before it is recorded (Step 3
  begins after this document and its companion numerics spec exist).
