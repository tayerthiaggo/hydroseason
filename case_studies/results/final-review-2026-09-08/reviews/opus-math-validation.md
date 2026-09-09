# Opus checkpoint 1 — mathematical / validation review of Tasks 2–3

**Reviewed source snapshot:** commit `aaf231a655a22ad1e4698a6fea25199f373c9784` (branch `development`),
**working tree, uncommitted**. Tasks 2–3 changes are unstaged edits on top of that commit; no commits were made.
Out of scope by instruction and not reviewed: `hydroseason/_recurrence_calibration.py`,
`hydroseason/_scientific_defaults.py`, `scripts/audit_recurrence_impact.py`,
`scripts/build_recurrence_identifiability_cohort.py` (pre-existing user edits).

**Review instruction applied (verbatim from the plan):** *Review correctness, mathematical consistency,
regression risk, and compliance with the plan. Require evidence for findings. Separate blocking defects from
optional improvements. Do not expand scope or request architectural changes without a demonstrated failure.*

---

## Test evidence (run by the reviewer, not quoted from a prior summary)

```
.venv\Scripts\python.exe -m pytest tests/test_trough_refinement.py tests/test_dynamic_year.py \
  tests/test_trough_refinement_calibration.py tests/test_final_pipeline.py \
  tests/test_catchment_analysis.py tests/test_report_export.py -q
```

```
178 passed, 10 warnings in 103.90s (0:01:43)
```

All 10 warnings are pre-existing `DeprecationWarning`s for `phase_model` / `phase_scheme='four_phase'`.

```
.venv\Scripts\python.exe -m ruff check hydroseason tests scripts
Found 10 errors.
```

All 10 ruff findings were verified to be pre-existing (`scripts/audit_recurrence_impact.py:23`,
`tests/test_timing_identifiability.py` ×8, `tests/test_catchment_analysis.py:492` — the last confirmed
identical in `git show HEAD:tests/test_catchment_analysis.py`). **No lint finding is attributable to Tasks 2–3.**

### Independent audit-probe reproduction

```
.venv\Scripts\python.exe docs\audits\2026-09-08-audit-probes.py
```

```json
"zero_scale_profile": [
  {"factor": 1.0,  "local_scale_pp": 0.0, "status": "confirmed", "boundary_candidates": ["2020-04-01"]},
  {"factor": 0.01, "local_scale_pp": 0.0, "status": "confirmed", "boundary_candidates": ["2020-04-01"]}
],
"dropped_month_scenario": {"status": "provisional", "recovery_start": "None", "recovery_start_present": false}
```

Both audit reproductions are corrected. The probe script's inputs are unchanged from the audit
(`docs/audits/2026-09-08-audit-probes.py:104,116-117` still carry `[90,60,30,10,10.2,45,80]` and
`.drop(index=index[4])`); only the newly required `measurement_tolerance_pp=0.0` keyword was added, which the
plan permits.

---

## Verified-correct claims (evidence recorded so the record is complete)

| Claim | Verdict | Evidence |
|---|---|---|
| 6.1 loss-unit fix: branch on `scale == 0.0`, exact-minimum support up to relative tolerance | **Confirmed** | `_trough_refinement._refine_selected_span` now selects `candidate.loss <= best_loss + tolerance` when `scale == 0.0` and only applies `(loss-best)/effective_support <= profile_loss_cutoff` when `scale > 0`. Probe shows identical candidate sets at factors 1.0 and 0.01; reviewer's own sweep holds to factor 1e-7 (see F4 for the 1e-9 edge). |
| 6.1 measurement floor applied unconditionally | **Confirmed** | `_local_scale` now returns `max(estimator, _measurement_floor(frame), measurement_tolerance_pp)`; the old early `return residual_scale` is gone. `test_tiny_residual_noise_cannot_drive_scale_below_pixel_floor` genuinely exercises it (residual MAD > 0 but < 1 pp pixel floor). |
| `measurement_tolerance_pp` threaded through nominal, gap and sensitivity fits, and validated | **Confirmed** | Forwarded at all six internal call sites; `refine_trough_span` raises on non-finite/negative. Forwarded from `config.measurement_tolerance_pct` in `_dynamic_year._apply_trough_refinement`. The `_pct`/`_pp` naming discrepancy is the audit's own §2 observation about the pre-existing config field; the new argument is honestly named. |
| 6.3 support-set untruncation | **Confirmed** | The `final_cluster = [p for p in final_cluster if p <= departure_position]` truncation is deleted; `boundary_position = departure_position` (latest exact optimum) and `boundary_candidates` is the full cluster. `candidate_span` / breadth classification now uses the untruncated set. |
| 6.4 calendar-gap fix | **Confirmed** | `_refine_selected_span` reindexes onto `pd.date_range(left,right,freq="MS")` and fills `quality_state="missing"`, `candidate_usable=False`, `observed_fraction=0.0`; `_masked_missing` replaces `frame.drop(...)` in `_quality_sensitivity`. Note `prepare_monthly_extent` already grids to MS, so the reindex is MS-safe by construction and is a no-op on the production nominal path — the audit's own scoping ("internal scenario-path finding") holds. `test_absent_recovery_month_cannot_be_confirmed` uses the audit's literal series and literal `frame.drop(index=pd.Timestamp("2020-05-01"))`; without the reindex the dropped row leaves a 6-row consecutive span and the old code reached `confirmed` + `recovery_start=May`, exactly as the audit recorded. |
| `_combine_sensitivity_results` uses a real scenario's operational boundary | **Confirmed** | `boundary=combined[-1]` removed; `selected.boundary` retained, `boundary_candidates=tuple(combined)` only widens the support set. `recovery_start` now derives from `selected.boundary`, which equals `selected.recovery_start` because `_refine_selected_span` always sets `recovery_start = boundary + 1 month` on the fully-observed path — so the change is value-identical and no recovery month can be claimed in a gap (the gap branch always returns `recovery_start=None`, and a scenario with `boundary is None` short-circuits to abstention). |
| `trough_boundary_date` is now unconditionally the operational date | **Confirmed and demonstrably a fix.** | `_report_export.py:438` `out["trough_boundary_date"] = out["trough_date"]`, with `trough_date` aliased from `trough_month` (line 394) before the point-only nulling. Reviewer measured 960 detector rows over seeds 30000–30039 (refinement off and on): `trough_month == hy_end` in **960/960** rows, so `trough_month` *is* the cycle-segmentation date; and **16 of 152** `interval`/`broad` rows had `trough_interval_end != trough_month`, i.e. the old export reported a `trough_boundary_date` that was not the actual cycle end on those rows. Copy-on-write means the later `out.loc[...] = pd.NaT` nulling of `trough_date` does not propagate (confirmed by the passing `test_trough_boundary_date_is_populated_when_a_trough_was_detected`). No downstream consumer treats `trough_interval_end` as a boundary: `_report_html.py:374` and `_report_plotly.py:394` use it only as a displayed uncertainty window; `scripts/evaluate_final_pipeline.py:58` prefers `trough_boundary_date` then `trough_month`. |
| Task 3 metric renames and the new containment metric | **Confirmed** | `boundary_set_overlap` keeps the original intersection math; `truth_set_containment` is genuinely `predicted_start <= truth_start & predicted_end >= truth_end`, with its own `truth_set_containment_n`. Verified non-degenerate by construction: the corpus contains width-2 plateau truths (`gap_after_low_state`, `long_flat_low_state`, ~15% of resolvable seeds) and `_literal_cache` yields overlap 1.0 / containment 0.0. See F9 for what it measured in practice. |
| `pass1_boundary` → `synthetic_reference_boundary` | **Confirmed** | Renamed in `_synthetic.TroughRefinementSyntheticRecord`, `_cache_row`, `score_trough_refinement_policy`, the score fields, the report gate names and the test fixtures. No `pass1_boundary` reference survives in the reviewed files. |
| Component integration metrics are `None`, not `0`/`False`; gates are `null` | **Confirmed** | `_cache_row` writes `None`; `score_trough_refinement_policy` hardcodes `None` (not a `.sum()`); `_admissible` no longer gates on them and retains the genuinely measured `wrong_cycle`. The report emits `{"status": null, "reason": "not_evaluated_in_span_harness"}`. Reviewer grepped all consumers: no code does `all(gates.values())` on this payload (`scripts/evaluate_trough_refinement_cohort.py:291,308` operates on a different, cohort-level gates dict), so the truthy non-empty dict cannot silently be counted as a pass. |
| Candidate version bump and fingerprint scope | **Confirmed** | `TROUGH_REFINEMENT_AUTHORITY_SCOPE = "trough_refinement_candidate_0_2"`; `trough_refinement_fingerprint` now additionally hashes `_month_delta`, `_timing_status` and `asdict(TIMING_IDENTIFIABILITY_DEFAULTS)`. `component-calibration.json` and `component-validation.json` both record `889196cbfafbecb1bbd79b97c780052d3509bff6cab2f85a91dba273b1969de4` — **fingerprints match**, so the validation partition did not run on a stale fingerprint. |
| `--fixed-trough-policy` never retunes | **Confirmed** | `run_trough_refinement_calibration_fixed` builds the cache with `policies=[policy]`, scores that one policy, and never imports or calls `select_trough_refinement_policy`; `_trough_refinement_report_payload(..., reselection=0)` yields `selection_counts={"reselection": 0}` (present in both real reports). CLI guard `--fixed-trough-policy is allowed only with --trough-refinement` is enforced in `__main__`. Reviewer confirmed the frozen tuple is a valid grid point: `iter_trough_refinement_policies()` stamps `version=TROUGH_REFINEMENT_AUTHORITY_SCOPE`, and `TroughRefinementPolicy(1.345, 0.05, 1.5, version="trough_refinement_candidate_0_2")` is grid index 44, so `score_trough_refinement_policy`'s membership check passes. Fixed tuple is `huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5` in every artifact. |
| Pipeline evaluator counters are genuinely measured | **Confirmed** | Aggregating `validation/pipeline-cycles.csv`: calibration / validation = `matched_rows` 1200/1200, `peak_changes` **0/0**, `boundary_shifted` **120/120**, `interval_width_changed` 100/100, `status_changed` 259/261, `newly_uncomputable` **0/0**, `newly_computable` 0/0, `quality_upgraded` 120/120, `quality_downgraded` 137/138, `before/after_duplicate_or_nonmonotonic_boundaries` **0/0**. These are non-constant, asymmetric numbers, not placeholders. The literal-table tests (`test_comparison_detects_duplicate_boundary`, `..._reversed_boundaries`, `..._newly_uncomputable_row`, `..._missing_row`, `..._separates_quality_upgrade_from_downgrade`) each construct the failing condition and assert the counter fires. **Structural safety holds: zero peak changes, zero newly-uncomputable cycles, zero duplicate/non-monotonic boundary sequences across 2400 matched cycle rows.** |
| Refinement stays opt-in / default preserved | **Confirmed** | `_apply_trough_refinement` returns `pass1_rows` unchanged when `policy is None`; `analyze_catchment` gained a trailing keyword-only `trough_refinement_policy: TroughRefinementPolicy \| None = None` forwarded to the single existing `DynamicHydroYearConfig(...)`. `test_explicit_none_preserves_default`, `test_explicit_trough_refinement_policy_reaches_dynamic_config` and `test_event_route_never_constructs_dynamic_detector_config` all pass. The default annual frame gains one all-`None` diagnostic column `trough_loss_basis` (plan-sanctioned in Task 2's interface list); the compact public CSV schema is unchanged. |
| Plan global constraints | **Confirmed** | No grid search or retuning in the reviewed diff; no threshold was changed to recover a number; base geometry `(3,5,6)`, base minimum 8, regime/recurrence thresholds and rainfall's additive role untouched; no asymmetric window, right-edge retry engine, Bayesian/mixture/AR(1) work, or architecture refactor. The 0.923 overlap result is reported with its gate explicitly `false` in both JSON artifacts and is not suppressed anywhere in code. |

---

## Findings

### F1 — Blocking — `_refine_gap_after_low_state` answers from the pre-gap segment only, producing a boundary on the wrong limb

**Affected:** `hydroseason/_trough_refinement.py`, `_refine_gap_after_low_state` (the `before = span.iloc[:gap_start]`
block and everything downstream of it), reached from `_refine_selected_span` and, newly and systematically, from
`_quality_sensitivity` via `_masked_missing`.

**Failure.** The function assumes any single interior gap lies *after* the low state. It fits the valley on
`before = span.iloc[:gap_start]` and consults exactly one post-gap value (`values_series.iloc[gap_end + 1]`);
every other observed month after the gap is discarded. Its only guards are positional
(`gap_start <= 1 or gap_end >= len(span) - 1`) — nothing checks that the low state is actually before the gap.
When the gap falls on the recession limb, the returned boundary is on the wrong limb.

**Counterexample (production nominal path, no sensitivity involved).** A clean V with a single genuinely
missing April, prepared through the real `prepare_monthly_extent`:

```python
vals = [90., 76.33, 62.62, 49., 35.33, 21.66, 8., 20.03, 33.56, 47.18, 60.85, 74.41, 88.]
idx  = pd.date_range('2000-01-01', periods=13, freq='MS')
raw  = pd.DataFrame({'extent_pct': vals, 'invalid_pct': 0.0}, index=idx)
raw.loc['2000-04-01', 'extent_pct'] = np.nan
raw.loc['2000-04-01', 'invalid_pct'] = 100.0
refine_trough_span(prepare_monthly_extent(raw),
                   left_peak=point('2000-01-01'), right_peak=point('2001-01-01'),
                   policy=TroughRefinementPolicy(1.345, 0.05, 1.5))
```

yields

```
provisional  recovery_crosses_gap  boundary=2000-03-01
boundary_candidates=(2000-03-01,)  low_state_start=low_state_end=2000-03-01
```

The observed minimum is **2000-07-01 at 8.0 pp**, and May, June, July, … are all observed. The result places
the operational boundary and the entire "low state" four months early, at 62.62 pp, on the recession limb,
purely because one cloud-obscured April made the function stop looking. This is not honest uncertainty — the
algorithm returns a confident `provisional` boundary that is demonstrably wrong given fully observed evidence.

**This defect pre-dates Task 2** (`_refine_gap_after_low_state`'s segment logic is untouched by the diff), **but
Task 2 makes it load-bearing.** `_quality_sensitivity` previously modelled "this month unobserved" with
`frame.drop`, which closed the calendar gap and kept the scenario on the fully-observed path. With the correct
`_masked_missing`, every low/unknown-quality month now routes its removal scenario through this branch. Traced
on calibration seed 70016 (`low_quality_interior` family, a clean V with one low-quality April at 49 pp and the
trough at July, 8 pp):

```
scenario missing=[]           -> confirmed   accepted             2000-07-01  (2000-07-01,)
scenario missing=[2000-04-01] -> provisional recovery_crosses_gap 2000-03-01  (2000-03-01,)
scenario missing=[2000-04-01] -> provisional recovery_crosses_gap 2000-03-01  (2000-03-01,)
...
FINAL: unresolved / unstable_quality_sensitivity
```

The nominal answer (July) and the scenario answer (March) have disjoint candidate sets, so
`_combine_sensitivity_results` correctly declares instability and the whole span abstains.

**Impact, quantified.** On the 5000-seed calibration partition the `low_quality_interior` family now abstains
**100%** of the time (`refinement_status=unresolved`, `refinement_reason=unstable_quality_sensitivity`, 17/17 in
a 300-seed reviewer sample), which is 1 family of 13 = 0.0769 — exactly the reported
`abstention_rate = 0.07688` and the entire drop from the previous `boundary_set_inclusion = 1.000`
(`docs/calibration/2026-09-06-trough-refinement-calibration.json`) to the new
`boundary_set_overlap = 0.9231`. Every other family is unchanged. The 0.923 is therefore **not** an honest
widening produced by correct uncertainty; it is the footprint of a wrong scenario answer. Real catchments are
affected directly, not only through sensitivity: any cloud gap on a recession limb reaches the same branch on
the nominal path (counterexample above), which is squarely in the path of Task 5's five real-catchment reports.

**Bounded correction (no new engine, no widening of scope).** Add one applicability guard to
`_refine_gap_after_low_state` before it commits to the pre-gap segment. Minimal form: if the minimum observed
value after the gap is materially below the pre-gap fitted low level (using the same `scale`/`huber_k`
comparison already in the function), the low state is not before the gap and the pre-gap analysis is
inapplicable — return `_empty_result("unresolved", "gap_before_low_state", policy)` instead of a pre-gap
boundary. Fuller form (optional, and only if the abstention rate matters scientifically): apply the existing
valley fit symmetrically to the post-gap segment in that case, which would restore resolution for the right
reason. **I am explicitly not asking anyone to recover the 0.95 gate.** The minimal fix is strictly *more*
conservative (a wrong answer becomes an abstention) and may leave `boundary_set_overlap` at 0.923 or lower;
that is fine and must be reported as-is. No support set may be narrowed and no threshold changed for this.

**Disposition: Fixed.** Added the minimal applicability guard: before trusting the pre-gap fit,
`_refine_gap_after_low_state` now checks whether any fully-observed post-gap value sits materially below the
pre-gap fitted low level (same scale/huber_k comparison already used for the recovery check). If so it returns
`_empty_result("unresolved", "gap_before_low_state", policy)` instead of a pre-gap boundary. Regression test
added: `test_gap_before_the_true_low_state_does_not_answer_from_the_recession_limb` in
`tests/test_trough_refinement.py`, using the reviewer's exact counterexample series — asserts
`status not in {"confirmed", "provisional"}` and `boundary is None`.

Re-ran the full 5000-seed calibration + validation partitions after the fix:
`boundary_set_overlap` is **bit-identical** (0.9231171548117155 calibration, 0.9230970442061208 validation) to
the pre-fix numbers, with a new fingerprint (`da0ab47d...`) confirming the code actually changed. This is
expected, not a sign the fix did nothing: in this synthetic corpus, the `low_quality_interior` family's masked
scenario was already being caught by `_combine_sensitivity_results`'s disjoint-candidate-set instability check
(nominal=July vs the old wrong pre-gap answer=March never shared a candidate, so the span already abstained,
just via the wrong mechanism/reason). The fix corrects the *reason* (`gap_before_low_state` instead of a
confidently-wrong `provisional` boundary that only happened to get caught downstream) without moving this
corpus's headline number. The dangerous case the reviewer actually demonstrated — the nominal, no-sensitivity
production path, where there is no downstream disagreement check to catch a wrong pre-gap answer — is exactly
what the new regression test locks in, and it now correctly abstains. No threshold was touched and no support
set was narrowed to produce this result, per the constraint above.

---

### F2 — Blocking — the `.at[]` dtype-widening loop in `_apply_trough_refinement` is not behaviourally inert

**Affected:** `hydroseason/_dynamic_year.py`, `_apply_trough_refinement`, the final per-cell assignment loop:

```python
if isinstance(value, pd.Timestamp) and rows[column].dtype != object:
    rows[column] = rows[column].astype(object)
```

**Values are inert; dtypes are not.** Reviewer verified the value side is safe: `_assemble_dynamic_cycle`
returns a `dict` whose key set is **exactly** `ANNUAL_COLUMNS` (measured: zero keys missing, zero extra), and
`pass1_rows` carries no columns outside `ANNUAL_COLUMNS`, so the per-cell loop writes the same cells the old
whole-row `rows.iloc[position] = pd.Series(...)` wrote, with no column silently left stale.

The dtype side is a real regression. The guard widens on `dtype != object`, which is true for `datetime64`
columns as well as for the all-NaN `float64` column the fix was written for. The pandas 3.0.3 `TypeError` only
affects `float64`: writing a `Timestamp` into a `datetime64[us]` column via `.at` works fine (verified
directly). So the widening is unnecessary for date columns, and it converts **all 17** annual datetime columns
to `object` the first time any refinement is accepted:

```
hy_start, hy_end, peak_month, temporal_mid_dry_month, half_loss_month, trough_month,
raw_trough_month, low_run_start_month, low_run_end_month, raw_peak_month,
peak_interval_start, peak_interval_end, trough_interval_start, trough_interval_end,
pass1_trough_month, pass1_trough_interval_start, pass1_trough_interval_end
    datetime64[us] -> object
```
(seed 30000, refinement applied to 10 rows.)

**Two demonstrated user-visible consequences.**

1. **HTML report tables.** `_report_html._records` formats only `pd.api.types.is_datetime64_any_dtype`
   columns with `.dt.strftime("%Y-%m-%d")`. Object-dtype columns skip that path and fall through to
   `to_json(date_format="iso")`. Measured on seed 30000: `trough_month` renders as `1990-07-01` in the
   default run and `1990-07-01T00:00:00.000` in the refined run. Every refined report in Task 5 — the five
   primary deliverables and the smoke bundle — would show full ISO timestamps in its year tables.
2. **Diagnostic CSVs.** End-to-end through `analyze_catchment` → `build_hydro_years_export` (the tables
   `scripts/build_final_review.py` writes as `full_hydro_years.csv` and Task 5's cycle/month diffs are
   built from):

   ```
   default:    hy_year,trough_month
               2005,2005-08-01
   refinement: hy_year,trough_month
               2005,2005-08-01 00:00:00
   ```

   Every date cell would differ between the default and refinement variants for reasons unrelated to any
   scientific change, contaminating Task 5's per-cycle and per-month diffs.

The compact public four-CSV export is unaffected (`_first_column(...).to_numpy()` re-coerces), and no numeric
value changes anywhere.

**Bounded correction.** Widen only when the target column genuinely cannot hold a `Timestamp`:

```python
if isinstance(value, pd.Timestamp) and not (
    pd.api.types.is_datetime64_any_dtype(rows[column]) or rows[column].dtype == object
):
    rows[column] = rows[column].astype(object)
```

Optionally add a regression assertion that the annual frame's dtypes are identical with refinement off and on
(excluding the added `trough_loss_basis` diagnostic).

**Disposition: Fixed.** Guard changed to widen only when the column is neither already `datetime64`-typed nor
already `object`-typed (`not (pd.api.types.is_datetime64_any_dtype(rows[column]) or rows[column].dtype ==
object)`). Verified directly on the reviewer's own reproduction (seed 30000, refinement applied): `annual['trough_month'].dtype` is `datetime64[us]` after the fix (was `object` before). Full trough-refinement
and dynamic-year test suites re-run clean after the change.

---

### F3 — Optional — the rewritten `test_low_quality_recession_month_adjacent_to_peak_abstains` records the wrong mechanism, and its new expectation is a consequence of F1

**Affected:** `tests/test_trough_refinement.py`, `test_low_quality_recession_month_adjacent_to_peak_abstains`
(renamed from `test_low_quality_recession_month_does_not_prevent_confirmation`, which asserted `"confirmed"`).

The docstring states the removal scenario is refused by "`_refine_gap_after_low_state`'s edge guard …
('no defensible low state' that close to a peak)". Traced: the scenario is refused by the
`if gap_start <= 1 ... return _empty_result("unresolved", "gap_overlaps_low_state", policy)` guard, and the
reason string is `gap_overlaps_low_state`, not `no_defensible_low_state`:

```
scen missing []             -> confirmed  accepted             2020-04-01
scen missing ['2020-02-01'] -> unresolved gap_overlaps_low_state None ()
FINAL unresolved unstable_quality_sensitivity None
```

More substantively: the series is `[90, 60, 30, 10, 20, 45, 80]` with February (60 pp) low-quality. Removing
February cannot make the April trough (10 pp) ambiguous — March, April, May, June are all observed and
unambiguous. The new `"unresolved"` expectation is therefore the same class of artifact as F1, not an
independently-derived contract. As the brief asks: this changed expected value is "whatever the code now
produces", not demonstrably correct.

**Bounded correction.** After F1 is resolved, re-derive this test's expectation from the corrected behaviour
and correct the docstring's reason string. If the corrected code still abstains, keep the abstention but state
the true mechanism.

**Disposition: Fixed.** Confirmed the test's outcome is unaffected by the F1 fix (this scenario is refused by
the pre-existing `gap_start <= 1` edge guard before ever reaching the new applicability check, so the assertion
stands). Corrected the docstring to state the actual mechanism (`gap_start <= 1` edge exclusion,
`reason="gap_overlaps_low_state"`) instead of the wrong guard/reason it previously claimed.

---

### F4 — Optional — the zero-scale plausibility tolerance is not strictly scale-equivariant

**Affected:** `hydroseason/_trough_refinement.py`, `_refine_selected_span`:

```python
tolerance = max(np.finfo(float).eps, _RELATIVE_CONVERGENCE * max(1.0, abs(best_loss)))
```

`_RELATIVE_CONVERGENCE = 1.4901161193847656e-08`. The `max(1.0, …)` term imposes a unit-dependent absolute
floor of ~1.49e-8 pp on the L1 objective, which the audit's §6.1 remedy explicitly asked to avoid
("Numerical tolerance must scale with the L1 data/objective magnitude, not impose a unit-dependent absolute
pp band"). Measured on the audit's own series scaled by a factor:

```
factor 1.0    -> ['2020-04-01']
factor 0.01   -> ['2020-04-01']
factor 1e-4   -> ['2020-04-01']
factor 1e-7   -> ['2020-04-01']
factor 1e-9   -> ['2020-04-01', '2020-05-01']   <- candidate set changes
```

Practically irrelevant for percentage-point data in `[0, 100]`, so this is Optional, not Blocking. But the
claimed invariance is a magnitude-limited invariance, not an exact one.

**Bounded correction.** Replace the `max(1.0, abs(best_loss))` term with a data-magnitude scale, e.g.
`_RELATIVE_CONVERGENCE * max(abs(best_loss), float(np.sum(weights) * np.max(np.abs(values))))`, keeping
`np.finfo(float).eps` as the pure numerical floor. The same pattern appears in the gap branch's
`equality_tolerance` (which is already data-relative via `abs(post_value), abs(low_level)` but carries the same
`max(1.0, …)` floor) and in `_refine_gap_after_low_state`'s `loss_tolerance`.

**Disposition: Deferred.** Confirmed practically irrelevant: the candidate set only changes at a data-scale
factor of 1e-9, far outside any physical extent_pct range (`[0, 100]`, never within 8 orders of magnitude of
that floor). Changing three tolerance formulas across `_refine_selected_span` and
`_refine_gap_after_low_state` carries more regression risk (each interacts with cluster/departure/gap-decision
logic already re-verified against the full existing test suite this pass) than its practical benefit justifies
in this bounded pass. Left for a future pass if a real record is ever found where it matters.

---

### F5 — Optional — `TroughRefinementPolicy.version` still defaults to `trough_refinement_candidate_0_1`

**Affected:** `hydroseason/_trough_refinement.py`, `TroughRefinementPolicy.version: str = "trough_refinement_candidate_0_1"`.

The authority scope, the generated defaults module, the grid (`iter_trough_refinement_policies` stamps
`version=TROUGH_REFINEMENT_AUTHORITY_SCOPE`) and both real component reports are now `…_0_2`, but the dataclass
default is unchanged. Any caller who constructs a policy without an explicit version —
`TroughRefinementPolicy(huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5)`, which is exactly the form used
in `tests/test_catchment_analysis.py`, `tests/test_final_pipeline.py` and
`scripts/build_final_review.py:CURRENT_CANDIDATE_POLICY` — runs corrected `…_0_2` code while stamping
`trough_refinement_policy_version = "trough_refinement_candidate_0_1"` into the annual output and any report
derived from it. In `build_final_review.py` that is deliberate (it labels the pre-fix baseline), which makes the
mislabelling risk sharper: the same constructor call means two different things depending on when it ran.

**Bounded correction.** Either bump the dataclass default to `trough_refinement_candidate_0_2`, or make
`version` a required argument. Task 4 owns "candidate provenance is current", so this can be resolved there —
recording it here so it is not lost.

**Disposition: Fixed in Task 4.** Bumped `TroughRefinementPolicy.version`'s dataclass default to
`trough_refinement_candidate_0_2` (the honest default now that Task 2/3's fixes are the actual shipped code),
and pinned `scripts/build_final_review.py:CURRENT_CANDIDATE_POLICY` to explicitly pass
`version="trough_refinement_candidate_0_1"` so its pre-fix baseline label no longer depends on the default at
all. No test asserted the old default string, so no other call site needed a change; full suite re-run clean.

---

### F6 — Optional — `validation/pipeline.json` omits the aggregate integration counters it was created to report

**Affected:** `scripts/evaluate_final_pipeline.py`, `evaluate_records` summary construction and `main`'s payload.

Audit §6.6's remedy is that `peak_changes`, duplicate/non-monotonic boundaries and newly-uncomputable cycles
must be *measured* at the integration level. They are measured — but only per record, as `diff_*` columns in
`pipeline-cycles.csv`. The headline `pipeline.json` carries only the error summaries. A reader of
`pipeline.json` alone cannot see that peak changes are 0, newly-uncomputable are 0, and duplicate/non-monotonic
boundaries are 0 — precisely the numbers the component harness now honestly reports as `null`.

**Bounded correction.** Sum the `diff_*` counters per partition (and optionally per family) into each
partition's summary dict in `evaluate_records`, so `pipeline.json` states the structural result explicitly.

**Disposition: Fixed.** `evaluate_records` now accumulates a `structural_diff_totals` dict per partition and
includes it in the returned summary. Regenerated `validation/pipeline.json` on the full 100+100 seed
partitions: `structural_diff_totals` shows `peak_changes: 0`, `newly_uncomputable: 0`,
`before/after_duplicate_or_nonmonotonic_boundaries: 0` explicitly in both partitions, across 1200 matched rows
each. Test added: `test_evaluate_records_reports_structural_diff_totals`.

---

### F7 — Optional — `_singleton_errors` folds cross-cycle misattribution into the error distribution

**Affected:** `scripts/evaluate_final_pipeline.py`, `_singleton_errors`.

Errors are matched strictly by `hy_year == base_year + offset` with no bound on the resulting delta, so a
boundary that landed in a neighbouring cycle enters the pool as a large month error rather than being counted
as a wrong-cycle event. The existing established scorer
(`hydroseason/_calibration.py:1795-1814`) deliberately does the opposite: nearest-match among identifiable
truth dates, with `abs(error) > _GEOMETRY_MAX_MATCH_MONTHS` recorded as `wrong_cycle` rather than as accuracy.

Evidence: the `abrupt_phase_shift` family reports `median_abs_error_months = 3.5`, `p90 = 7.0`,
`signed_bias = -3.5` — **identical for refinement off and on** — and drives the overall
`p90_abs_error_months = 5.0` in both partitions. A 7-month error in a 12-month cycle is a year-attribution
event, not a boundary-precision measurement, so the reported p90 should not be read as boundary precision.

**Bounded correction.** Add a `wrong_cycle` counter using the existing `_GEOMETRY_MAX_MATCH_MONTHS` convention
and either exclude those rows from the error pool or report the two populations with separate denominators, and
say so in the JSON.

**Disposition: Fixed.** Added `_split_wrong_cycle` using the same `_GEOMETRY_MAX_MATCH_MONTHS` (6-month)
threshold as the established scorer; wrong-cycle events are excluded from the accuracy pool and counted
separately (`wrong_cycle` in each partition's `off`/`on` summary; `wrong_cycle_off`/`wrong_cycle_on` per
record). Regenerated `pipeline.json`: `p90_abs_error_months` drops from the previous 5.0 to **0.0** in both
partitions once the 60 wrong-cycle events per partition (all in `abrupt_phase_shift`) are excluded, and
`mean_abs_error_months` drops from 0.90/0.83 to 0.37 (off) / 0.29 (on) — this is a materially more honest
precision measurement, exactly the artifact the finding identified.

---

### F8 — Optional — `_duplicate_or_nonmonotonic_boundaries` docstring does not match its code

**Affected:** `scripts/evaluate_final_pipeline.py`, `_duplicate_or_nonmonotonic_boundaries`.

The docstring says "Count **computable** rows, in chronological hy_year order, whose boundary repeats or does
not strictly increase". The implementation takes every non-null boundary regardless of `_is_computable`. The
measured value is 0 everywhere, so nothing is currently mis-stated numerically, but the recorded definition of
a structural-safety counter should match what it counts.

**Bounded correction.** Either filter to computable rows or drop "computable" from the docstring.

**Disposition: Fixed.** Dropped "computable" from the docstring (chose the lower-risk option: the function's
actual, already-tested contract is "any non-null boundary", and changing the filter itself was not
demonstrated to be wrong on any measured output).

---

### F9 — Optional — `truth_set_containment` carried no information beyond `boundary_set_overlap` on this corpus; say so

**Affected:** `case_studies/results/final-review-2026-09-08/validation/component-{calibration,validation}.json`
and any documentation of the new metric.

Both partitions report `truth_set_containment` **bit-identical** to `boundary_set_overlap`
(0.9231171548117155 calibration, 0.9230970442061208 validation). Reviewer verified this is *not* a coding
error — the two formulas differ, plateau truths of width 2 exist (families `gap_after_low_state`,
`long_flat_low_state`) and are `applied`, and on a 300-seed sample every applied prediction that overlapped its
truth also fully enclosed it (`overlap-but-not-contain: 0` of 212). The metric is correctly implemented and is
genuinely new evidence; it simply happens to be non-discriminating on this synthetic corpus. Reporting two
identical numbers without that note risks reading as two independent confirmations.

**Bounded correction.** One sentence in the migration/calibration documentation (Task 4) stating that on this
corpus containment and overlap coincide, and why.

**Disposition: Deferred to Task 4.** Documentation-only; Task 4 owns the migration/calibration docs where this
note belongs.

---

### F10 — Optional — `recovers` in `_refine_gap_after_low_state` is a misnomer that inverts its meaning

**Affected:** `hydroseason/_trough_refinement.py`, `_refine_gap_after_low_state`.

`recovers = abs(post_value - low_level) <= equality_tolerance` (zero-scale branch) or
`post_low_loss <= cutoff + tolerance` (positive-scale branch) is `True` when the post-gap value is
**indistinguishable from the low level** — i.e. when the series has *not* recovered — and `if recovers:`
returns `status="unresolved", reason="gap_overlaps_low_state"`. Behaviour is identical to the pre-change code
(verified by reading both branches); only the name is inverted. Rename to `post_value_still_at_low_level` or
similar before anyone edits this branch on the strength of the name.

**Disposition: Fixed.** Renamed to `post_value_still_at_low_level` at both definition sites and the `if`
check; no behavior change (confirmed by the unchanged test suite).

---

### F11 — Optional (Task 4 scope; recorded for visibility) — a shipped document still claims all gates pass

**Affected:** `docs/migrations/trough-refinement-candidate.md:48` — "both pass all ten frozen gates".

With `boundary_set_overlap_at_least_0_95 = false` and three gates now `null`, that sentence is contradicted by
the artifacts this pass produced. The brief instructed me not to treat the 0.923 itself as a defect, but to
flag anywhere it is contradicted or hidden; the JSON reports it honestly, this document does not. Task 4 owns
documentation, so this is a pointer, not a Task 2/3 defect.

**Disposition: Deferred to Task 4.** Task 4 explicitly owns correcting scientific explanations and candidate
provenance; this stale claim is in that scope.

---

## Summary

| Severity | Count | IDs | Disposition |
|---|---|---|---|
| Blocking | 2 | F1, F2 | Fixed |
| Optional | 9 | F3, F6, F7, F8, F10 | Fixed |
| Optional | — | F4 | Deferred (negligible real-data impact; recorded rationale above) |
| Optional | — | F5, F9, F11 | Deferred to Task 4 (documentation/provenance scope) |

Tasks 2 and 3 do what they claim on every audited point: the loss-unit branch, the unconditional measurement
floor, the untruncated support set, the operational-date/support-set separation in both `_trough_refinement`
and `_report_export`, the calendar-preserving sensitivity scenarios, the `_combine_sensitivity_results`
correction, the honest `null` component metrics, the renamed comparator, the extended fingerprint, and the
fixed-tuple calibration mode. Both audit reproductions pass on the audit's own inputs, the two 5000-seed
component runs share a matching fingerprint, and the new full-pipeline evaluator produces genuine, non-constant
measurements showing zero structural violations across 2400 matched cycle rows.

**Post-review resolution (by the implementer, same pass).** Both blocking findings and five of the nine
optional findings were fixed; three optional findings were deferred to Task 4 (documentation/provenance scope,
matching the reviewer's own recommendation) and one (F4) was deferred with recorded evidence that it is
practically irrelevant to any real percentage-point data. All affected real artifacts were regenerated on the
full 5000-seed calibration and validation partitions plus the full pipeline evaluator after the fixes:

- `boundary_set_overlap` is **bit-identical** before/after the F1 fix (0.9231171548117155 calibration,
  0.9230970442061208 validation) — the fix corrects the mechanism (an honest `gap_before_low_state` abstention
  instead of a confidently-wrong boundary that happened to be caught downstream by a different check), not
  this corpus's headline number. The genuinely dangerous case the reviewer demonstrated — the production
  nominal path with no sensitivity scenario and no downstream disagreement check to catch a wrong answer — now
  correctly abstains, locked in by a new regression test.
- `trough_month` and every other annual datetime column stay `datetime64[us]`-typed with refinement applied
  (confirmed on the reviewer's own seed-30000 reproduction) after the F2 fix.
- `pipeline.json` now states `structural_diff_totals` explicitly (F6) and its `p90_abs_error_months` drops from
  5.0 to the materially more honest 0.0 once wrong-cycle year-misattribution events are correctly excluded from
  the accuracy pool (F7) — 60 such events per partition, all in the `abrupt_phase_shift` family.
- Full regression suite (264 tests across every file this checkpoint touched, plus report HTML/Plotly) passes
  clean after all fixes.

No support set was narrowed and no threshold was changed anywhere in this resolution pass to recover a
passing number, consistent with the plan's global constraints.
