# Opus checkpoint 2 — final integration review (Tasks 4–6)

**Reviewed source snapshot:** commit `aaf231a655a22ad1e4698a6fea25199f373c9784` (branch `development`),
**working tree, uncommitted**. Verified by the reviewer:

```
$ git rev-parse HEAD
aaf231a655a22ad1e4698a6fea25199f373c9784
```

The working tree is the authoritative source: `git diff HEAD` hashes to
`7467661ca318f8205a1de025a2c06f3b485914d9cc7c6e6e9a731cd6d7633a42`, which is **bit-identical** to
`manifest.json:source.dirty_patch_hash` in this bundle. The five-catchment reports, the smoke bundle
and `index.html` were therefore generated from exactly the source state under review. (One class of
artifact was *not*: see finding **G1**.)

Out of scope by instruction and not reviewed: `hydroseason/_recurrence_calibration.py`,
`hydroseason/_scientific_defaults.py`, `scripts/audit_recurrence_impact.py`,
`scripts/build_recurrence_identifiability_cohort.py`, `docs/decision-policy.md`,
`docs/migrations/0.2.0-timing-identifiability.md` (pre-existing user edits). Task 7's
`handoff-for-codex.md` is not written yet and is not reviewed. The scientific validity of the
underlying detection algorithm is out of scope.

**Review instruction applied (verbatim from the plan):** *Review correctness, mathematical consistency,
regression risk, and compliance with the plan. Require evidence for findings. Separate blocking defects
from optional improvements. Do not expand scope or request architectural changes without a demonstrated
failure.*

---

## Test evidence gathered by this reviewer

All numbers below were read or produced by the reviewer, not copied from a prior summary.

### `validation/pytest.xml`, parsed with `xml.etree.ElementTree`

```
testsuite attrib: {'name': 'pytest', 'errors': '0', 'failures': '2', 'skipped': '2',
                   'tests': '1593', 'time': '1020.521',
                   'timestamp': '2026-09-08T13:38:44.977856+08:00', 'hostname': 'DEP68634'}
testcase count: 1593
failures: 2   errors: 0   skipped: 2
  FAIL -> tests.test_decision_policy_docs :: test_recurrence_identifiability_promotion_docs
  FAIL -> tests.test_package_surface :: test_package_import_exposes_only_migration_safe_surface
```

`validation/test-results.html` states `total=1593 passed=1589 failures=2 errors=0 skipped=2` and
**"Software test status: NOT A PASS"** — the rendered counts match the XML exactly, and the honest
non-pass state is not hidden.

**The two failures are exactly the two claimed as pre-existing, and no others.**

- `test_package_surface` — reproduced live by the reviewer:
  `AssertionError ... At index 30 diff: 'TroughRefinementPolicy' != 'HydrologicalStateResult'`,
  `Left contains one more item: 'run_hydroseason_many'`. `git status --short -- hydroseason/__init__.py
  tests/test_package_surface.py` prints **nothing** and `git diff --stat HEAD` on those two paths is
  **empty**; `hydroseason/__init__.py` was last touched in commit `3dadd29`, which precedes the audit
  baseline `aaf231a`. `__init__.py` uses explicit imports and an explicit `__all__` (no star imports),
  so no module changed by this pass can influence the surface list. Pre-existing at `aaf231a`, confirmed.
- `test_decision_policy_docs::test_recurrence_identifiability_promotion_docs` — the XML failure message
  shows the assertion is against the text of `docs/migrations/0.2.0-timing-identifiability.md`, which is
  on the excluded pre-existing-user-edit list. Unrelated to this plan, confirmed.

### Coverage

`--cov-fail-under=80` was requested by the plan. The bundle carries no coverage log, but the run's
`.coverage` data file (written `2026-09-08 13:55`, the same minute as `pytest.xml`) is present in the
repo root and the reviewer read it directly:

```
$ .venv/Scripts/python.exe -m coverage report
TOTAL   8655   916   89%
$ .venv/Scripts/python.exe -m coverage report --format=total
89
```

**Coverage 89%, at or above the 80% floor.** (See optional finding **G7** — this number is not captured
in the bundle itself.)

### Lint

`validation/ruff.txt` records `Found 10 errors.` The reviewer re-ran
`.venv/Scripts/python.exe -m ruff check hydroseason tests scripts` and got a **byte-for-byte identical
finding list**:

```
scripts\audit_recurrence_impact.py:23:1        (E402 — pre-existing user-edited file)
tests\test_catchment_analysis.py:492:5         (I001)
tests\test_catchment_analysis.py:492:22
tests\test_timing_identifiability.py:478/494/510/526/542/563/580:5   (×7)
Found 10 errors.
```

`tests/test_timing_identifiability.py` is untouched by this pass (absent from `git status`), and
`tests/test_catchment_analysis.py:492` was confirmed identical to `HEAD` at checkpoint 1.
**No lint finding is attributable to this diff.**

### Docs build

`validation/docs-build.txt` ends `INFO - Documentation built in 2.27 seconds` with no WARNING/ERROR
lines — `mkdocs build --strict` succeeded. One INFO-level broken anchor is recorded; see **G6**.

### Reviewer's own runtime probes

```
=== F1 counterexample (nominal production path, gap on the recession limb) ===
status = unresolved | reason = gap_before_low_state | boundary = None
candidates = ()   low_state = None None

=== F1 control (gap genuinely AFTER the low state must still resolve) ===
status = provisional | reason = recovery_crosses_gap | boundary = 2000-06-01
```

```
=== _state_input dtype forcing ===
float64 input : values bit-identical to the old `pd.to_numeric` result (True), dtype float64 -> float64
int64  input  : dtype int64 -> float64, values equal to raw ints cast to float (True)
float32 input : dtype -> float64, max abs delta vs lossless widening = 0.0
Float64 (nullable) : -> float64, pd.NA -> NaN (20 of 60)
```

---

## Disposition of every checkpoint-1 finding

Each "Fixed" claim was checked against the current source, not against the prose.

| ID | Sev | Checkpoint-1 disposition | Verified by this reviewer |
|---|---|---|---|
| **F1** | Blocking | Fixed — applicability guard + regression test | **Holds.** `hydroseason/_trough_refinement.py:642–666` adds the guard, comparing every fully-observed post-gap value against the pre-gap fitted low level using the same `scale`/`huber_k` machinery already in the function, and returns `_empty_result("unresolved", "gap_before_low_state", policy)`. Reviewer ran checkpoint 1's own counterexample end-to-end through the real `prepare_monthly_extent` + `refine_trough_span`: the old wrong `provisional / boundary=2000-03-01` is now `unresolved / gap_before_low_state / boundary=None`. Critically, the guard is **not over-broad**: a control case with the gap genuinely *after* the low state still resolves to `provisional / recovery_crosses_gap / boundary=2000-06-01`, so the branch was not neutered into blanket abstention. Regression test `test_gap_before_the_true_low_state_does_not_answer_from_the_recession_limb` exists at `tests/test_trough_refinement.py:278`. |
| **F2** | Blocking | Fixed — narrow the dtype-widening guard | **Holds.** `hydroseason/_dynamic_year.py:1354–1358` is exactly the correction checkpoint 1 specified: `if isinstance(value, pd.Timestamp) and not (pd.api.types.is_datetime64_any_dtype(rows[column]) or rows[column].dtype == object)`. Independently corroborated at the artifact level: `before/default/*/full_hydro_years.csv` and `after/default/*/full_hydro_years.csv` differ **only** by the added all-null `trough_loss_basis` column, with all 104 shared columns comparing `equals()`-identical and no `00:00:00` ISO-time contamination anywhere in the date cells (see "Route preservation" below). |
| **F3** | Optional | Fixed — docstring corrected to the real mechanism | **Holds.** `tests/test_trough_refinement.py:347–361` now names the `gap_start <= 1` edge exclusion and `reason="gap_overlaps_low_state"`. |
| **F4** | Optional | Deferred with recorded rationale (1e-9 data-scale, physically irrelevant) | **Deferral stands.** `_RELATIVE_CONVERGENCE * max(1.0, abs(best_loss))` is still present at three sites (`_refine_selected_span`; `_refine_gap_after_low_state:623–626, 673–676`). Rationale is sound for `extent_pct ∈ [0,100]`. Not re-raised. |
| **F5** | Optional | Fixed in Task 4 — dataclass default bumped, baseline label pinned | **Holds.** `TroughRefinementPolicy(1.345, 0.05, 1.5).version == 'trough_refinement_candidate_0_2'`; `scripts/build_final_review.py:73–78` pins `CURRENT_CANDIDATE_POLICY` to `version="trough_refinement_candidate_0_1"` and `CORRECTED_CANDIDATE_POLICY` to `…_0_2` explicitly, so neither label depends on the default. **Side effect the implementer did not account for: this edit is one of the two that invalidated the component fingerprint — see G1.** |
| **F6** | Optional | Fixed — `structural_diff_totals` in `pipeline.json` | **Holds.** Read from `validation/pipeline.json`: both partitions carry `structural_diff_totals` with `peak_changes: 0`, `newly_uncomputable: 0`, `before/after_duplicate_or_nonmonotonic_boundaries: 0`, over `matched_rows: 1200` each. |
| **F7** | Optional | Fixed — `_split_wrong_cycle`, wrong-cycle events excluded from the accuracy pool | **Holds.** `scripts/evaluate_final_pipeline.py:269–281` uses the established scorer's `_GEOMETRY_MAX_MATCH_MONTHS` (imported at line 28). Regenerated `pipeline.json` matches the claimed numbers exactly: `p90_abs_error_months = 0.0` in both partitions and both sides; `mean_abs_error_months` off/on = `0.3666/0.2933` (calibration) and `0.3660/0.2928` (validation); `wrong_cycle = 60` per partition per side, reported separately rather than silently dropped. |
| **F8** | Optional | Fixed — "computable" dropped from the docstring | **Holds.** `scripts/evaluate_final_pipeline.py:82–86` now reads "Count rows with a non-null boundary…". |
| **F9** | Optional | Deferred to Task 4 (documentation) | **Delivered.** `docs/migrations/trough-refinement-candidate.md:81–85` states that containment and overlap coincide on this corpus, that the formulas genuinely differ, and that this is not a coding error. |
| **F10** | Optional | Fixed — `recovers` renamed | **Holds.** `post_value_still_at_low_level` at `hydroseason/_trough_refinement.py:679, 685, 686`, with a clarifying comment; both branches otherwise unchanged. |
| **F11** | Optional | Deferred to Task 4 (stale "all ten gates pass" claim) | **Delivered.** The string "all ten frozen gates" no longer appears anywhere in `docs/migrations/trough-refinement-candidate.md`. It is replaced by an explicit **"Not every gate passes; this is reported honestly, not adjusted to pass"** plus a bolded statement that `boundary_set_overlap = 0.923` is below the informal 0.95 mark and was not retuned, and a row marking the three integration metrics "not evaluated by this harness". |

**No checkpoint-1 "Fixed" claim was found to be overstated or absent from the source.**

---

## Changed call site: `prepare_monthly_extent` forcing float64

`hydroseason/_state_input.py:58–72` now applies `.astype(float)` to both `extent_pct` and `invalid_pct`
after `pd.to_numeric(...)`. This function is on every route and every detector path, so it was checked
directly rather than by inspection alone.

- **All-float input (the overwhelmingly common case): provably inert.** For a 60-month float64 frame the
  reviewer compared the new output against a literal re-implementation of the old line
  (`pd.to_numeric(col, errors="coerce")`): values **bit-identical** (`np.array_equal` → `True`) and dtype
  unchanged (`float64 → float64`) for both columns. `.astype(float)` on a float64 Series is the identity.
- **All-integer percentages: exactly the previously-crashing edge case, now fixed.** `int64 → float64`,
  values equal to the ints cast to float. This is what the smoke fixtures need (`np.tile([60, 80, 60, …])`
  is int64), and it is the only behavioural change on a valid input.
- **Adjacent dtypes widen losslessly, never narrow.** `float32 → float64` with max abs delta `0.0`;
  nullable `Float64 → float64` with `pd.NA` becoming `NaN` (20 of 60 rows), which is the representation
  the rest of the pipeline already assumes. No input is narrowed and no validation bound moved: the
  `[0, 100]` range checks still run on the same values.
- **Confirmed empirically on real data.** `before/` was generated at 11:27 from a source state whose
  patch hash is `cbd67d08…` — i.e. *before* this edit existed — and `after/default` at 13:27 from the
  current tree. All four public CSVs, the HTML report, and `full_events.csv` / `full_low_spells.csv` /
  `full_monthly.csv` are **byte-identical across that code change for all five real catchments**. On real
  DEA input this change is a measured no-op.

The same reasoning covers the synthetic partitions: `generate_trough_refinement_record(...).frame` carries
`extent_pct: float64` / `invalid_pct: float64` derived from `int64` count columns via `100.0 * n_water /
n_valid`, so `.astype(float)` cannot move a single value there either. This is the basis for saying G1 is
a provenance defect and not a numbers defect.

---

## Route preservation and paired-cycle rollback (from the generated evidence)

Read from `comparisons/catchments.csv` (15 rows, 3 comparisons × 5 catchments):

**`old_default_vs_new_default` — every counter is zero for all five catchments.**

| catchment | matched | added | dropped | peak_chg | bnd_shift | width_chg | status_chg | new_uncomp | new_comp | qual_up | qual_down | dup_before | dup_after |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| daly_river_nt | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fitzroy_river_wa | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| gilbert_river_qld | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| lachlan_river_nsw | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| moonie_river_qld_nsw | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

**`current_default_vs_corrected_refinement` — the three required safety counters are zero everywhere,
including where refinement genuinely moved boundaries.**

| catchment | matched | peak_changes | newly_uncomputable | dup_or_nonmonotonic_after | boundary_shifted | width_changed | status_changed | quality_downgraded |
|---|---|---|---|---|---|---|---|---|
| daly_river_nt | 21 | **0** | **0** | **0** | 4 | 10 | 15 | 13 |
| fitzroy_river_wa | 21 | **0** | **0** | **0** | 3 | 18 | 12 | 7 |
| gilbert_river_qld | 21 | **0** | **0** | **0** | 2 | 15 | 12 | 8 |
| lachlan_river_nsw | 0 | **0** | **0** | **0** | 0 | 0 | 0 | 0 |
| moonie_river_qld_nsw | 0 | **0** | **0** | **0** | 0 | 0 | 0 | 0 |

Both claims verified against the actual CSV. Honest read of the two event-route rows: `matched_rows = 0`
for lachlan and moonie because they route to `event_characterisation` and publish no hydrological years,
so their zeros are *vacuously* true for cycles — `months_compared = 252` shows the month-level comparison
did run for them. `index.html` labels them `not_run_for_event_route`, so nothing is misrepresented, but
Task 7 should not present these two as five-catchment evidence of paired-cycle safety; the substantive
evidence is the three seasonal catchments plus the 2400 synthetic matched rows.

### Independent byte-identity spot check (not derived from the CSV summary)

Reviewer SHA-256'd **every** CSV in `before/default/<catchment>/` against `after/default/<catchment>/`
for all five catchments — 40 file pairs generated by two different code states:

```
IDENTICAL   all 4 public compact CSVs   ×5 catchments   (hydro_years, monthly, low_spells, wet_event)
IDENTICAL   full_events.csv, full_low_spells.csv, full_monthly.csv   ×5 catchments
*** DIFFERS ***  full_hydro_years.csv   (daly, fitzroy, gilbert only)
IDENTICAL        full_hydro_years.csv   (lachlan, moonie)
IDENTICAL   the rendered HTML report    ×5 catchments  (sha256 equal)
```

The three differing files were diffed column-wise: the **only** difference is one added column,
`trough_loss_basis`, which is all-null in the default run; all 104 shared columns are `equals()`-identical
and the frame shape goes `(21, 104) → (21, 105)`. That is the plan-sanctioned Task 2 diagnostic field, and
Task 6's acceptance is explicitly "after excluding added diagnostics". **Default-route byte-identity holds.**

That the rendered HTML is sha256-identical across the code change is also the strongest available check on
F2: had the datetime columns still been widened to `object`, the HTML year tables would render
`1990-07-01T00:00:00.000` and the hashes would differ.

Related consistency check on the `_report_export.py` change (`trough_boundary_date = trough_date`
unconditionally): in `before/default/daly_river_nt/full_hydro_years.csv`, `trough_month ==
trough_interval_end` in **21 of 21** rows (9 `interval`, 8 `point`, 4 `broad`), so on these default runs
the change is a demonstrated no-op rather than a silent shift.

---

## Generated reports are genuine

Bundle contents confirmed present on disk:

- `before/{default,refinement}/` and `after/{default,refinement}/`, each with all five catchments
  (`daly_river_nt`, `fitzroy_river_wa`, `gilbert_river_qld`, `lachlan_river_nsw`, `moonie_river_qld_nsw`)
  — 20 report directories, each with its HTML plus the four standard CSV siblings plus four `full_*.csv`
  diagnostic tables.
- `smoke/` with all nine cases (`all-zero`, `clean-seasonal`, `constant-water`, `gap-at-low`,
  `gap-at-recovery`, `late-trough-short-following`, `long-plateau`, `low-quality`, `two-pulses`) plus
  `smoke/index.html`.
- `comparisons/{catchments,cycles,months}.csv`, `review-notes.md`, `index.html`, `manifest.json`,
  `reviews/`, and `validation/{pytest.xml,test-results.html,ruff.txt,docs-build.txt,
  component-calibration.json,component-validation.json,pipeline.json,pipeline-cycles.csv}`.
- `handoff-for-codex.md` is absent, as expected (Task 7 not yet written).

HTML integrity (sampled: two real-catchment reports incl. an event-route one, three smoke reports,
`index.html`, `smoke/index.html`, `validation/test-results.html`):

- Sizes: the 20 catchment reports are **1.39–1.50 MB** each; the nine smoke reports **1.28–1.35 MB**.
  No stub, no truncation.
- Every sampled file begins `<!doctype html>` / `<html lang="en" data-theme="light">` and ends
  `…})();</script></body></html>` — complete documents.
- **5 `Plotly.newPlot` blocks per report**, in every sampled report including `all-zero` and the
  event-route `moonie` report.
- **Offline: zero external references.** No `<script src=`, `<link href=`, `<img src=` or `<iframe src=`
  points at any `http(s)://` host in any sampled file. The only `http(s)` strings present are license and
  attribution text inside the embedded `plotly.js` bundle (`getify.mit-license.org`,
  `github.com/d3/d3-format`, …), which are inert comment content.
- All 49 local links in `index.html`, `smoke/index.html` and `validation/test-results.html` were resolved
  against the filesystem: **0 missing**.

Smoke-case outcomes are honest against the plan's stated expectations:

| case | route | hydro-year rows | notable |
|---|---|---|---|
| all-zero | `event_characterisation` | **0** | `event_route_has_no_events_or_low_spells` — flat case publishes no hydrological years |
| constant-water | `event_characterisation` | **0** | same |
| clean-seasonal | `per_year_detection` | 15 | 13 `confirmed`, 1 `unavailable`, 1 `awaiting_next_peak` |
| gap-at-low | `per_year_detection` | 15 | the perturbed year is `unresolved`, not confirmed |
| gap-at-recovery | `per_year_detection` | 15 | the perturbed year is `provisional` with **`recovery_start_month` null** — no observed confirmation claimed in a gap |
| long-plateau / low-quality / two-pulses / late-trough-short-following | `per_year_detection` | 15 each | `late-trough-short-following` degrades to 2 `unavailable` rather than forcing a December boundary |

`manifest.json` records identical SHA-256 input hashes for `before` and `after` for all five catchments
(inputs preserved), the frozen policy `{huber_k: 1.345, profile_loss_cutoff: 0.05, pulse_z: 1.5,
version: trough_refinement_candidate_0_2}`, the interpreter/dependency versions, and the source revision +
dirty patch hash.

---

## Plan global constraints

| Constraint | Verdict | Evidence |
|---|---|---|
| Refinement stays opt-in; default byte-identical to before the pass | **Held** | `analyze_catchment(..., trough_refinement_policy=None)` default (`_catchment.py:219`); `DynamicHydroYearConfig.trough_refinement_policy = None` (`_dynamic_year.py:110`); `_apply_trough_refinement` returns unchanged rows when the policy is `None` (`_dynamic_year.py:605`). Byte-identity measured across the actual code change on 40 CSV pairs and 5 HTML reports (above). |
| Fixed tuple `1.345 / 0.05 / 1.5`, no grid search or retuning | **Held** | Present verbatim in `_trough_refinement_defaults.py:8–10`, `manifest.json:after_policy`, `pipeline.json:policy`, both component JSONs, and `docs/migrations/trough-refinement-candidate.md:46–47`. `scripts/build_final_review.py:73–78` builds both policies from one `_FIXED_TUPLE`. No selector is invoked in the fixed-policy path. |
| Nothing narrowed or re-thresholded to recover a number | **Held** | The 0.923 `boundary_set_overlap` is reported as a failing gate in both JSONs and is now stated as a failure in the migration doc; F1's fix is strictly more conservative; F7's correction *removed* 60 favourable-looking matches per partition from the accuracy pool rather than keeping them. No threshold constant changed anywhere in the diff. |
| No promotion to default/production; `ESTABLISHED_POLICY` unchanged | **Held** | `hydroseason/_decision_policy.py` does not appear in `git status` at all; `ESTABLISHED_POLICY = "established_0_2_0"` unchanged, and `analyze_catchment`'s `decision_policy` still defaults to it. No deployment or release action in the diff. |
| No new architecture | **Held** | New code is confined to two scripts (`build_final_review.py`, `evaluate_final_pipeline.py`) and their tests, per the plan's own file map. `_regime.py`'s diff is wording-only (two copy strings; the `aseasonal` enum, routing thresholds and returned values are untouched). `_synthetic.py`'s diff is the `pass1_boundary → synthetic_reference_boundary` rename plus a comment; the generator arithmetic `max(1, low_start - (1 if seed % 3 == 0 else 0))` is byte-for-byte unchanged, so validation truth is genuinely untouched. |
| `.gitignore` narrow exceptions | **Held** | The diff replaces the single `docs/superpowers/` rule with exactly the eight-line block the plan specifies, preserving all unrelated patterns. Nothing untracked or deleted. |

---

## Findings

### G1 — Blocking — the published trough-refinement provenance hashes are stale relative to the reviewed source, and `run_calibration --partition validation` now refuses to run

**Affected artifacts and code:**

- `hydroseason/_trough_refinement_defaults.py:6` — `TROUGH_REFINEMENT_FINGERPRINT = 'da0ab47d…'`
- `case_studies/results/final-review-2026-09-08/validation/component-calibration.json:12`
- `case_studies/results/final-review-2026-09-08/validation/component-validation.json:12`
- `case_studies/results/final-review-2026-09-08/validation/pipeline.json` — `manifest_hash`
- `docs/calibration/2026-09-08-trough-refinement-calibration.json:12` and `…-validation.json:12`
- `docs/migrations/trough-refinement-candidate.md:43`

**Failure.** All of these record a source fingerprint that no longer describes the shipped source:

```
frozen (all six artifacts): da0ab47d2d8e63efb812c007855fb746f36344261cc846b3b2677dc510cd07b9
recomputed on this tree   : 4d745ac70783ff8fe22bf6d2d3fa2a43e1126cf30255e4dd4827bb86a17a5041
```

The reviewer reproduced the recorded hash exactly by reverting the two source edits that caused the drift,
confirming both the cause and that nothing else moved:

```
cur _trough_refinement / cur prepare_monthly_extent : 4d745ac7…
cur _trough_refinement / OLD prepare_monthly_extent : 2dcf8cdb…
OLD _trough_refinement / cur prepare_monthly_extent : 04779eb2…
OLD _trough_refinement / OLD prepare_monthly_extent : da0ab47d…   <== MATCHES THE PUBLISHED ARTIFACT
```

where "OLD `_trough_refinement`" is only `TroughRefinementPolicy.version`'s dataclass default reverted
`_0_2 → _0_1` (the **F5 fix**, Task 4) and "OLD `prepare_monthly_extent`" is the `.astype(float)` edit
reverted (**Task 5**). `trough_refinement_fingerprint` hashes `inspect.getsource(_trough_refinement)` and
`inspect.getsource(_state_input.prepare_monthly_extent)` (`_trough_refinement_calibration.py:362, 368`),
so both edits were guaranteed to invalidate it. File timestamps corroborate the ordering: the component
JSONs were written at 12:41/12:45 and `pipeline.json` at 12:46, while the Task 4/5 source edits and the
`after/` reports are 13:23–13:28.

**Demonstrated consequence** (not hypothetical — reviewer executed it):

```python
run_calibration.run_trough_refinement_validation(seeds=[80000], out_report=..., workers=1)
# RuntimeError: trough-refinement fingerprint differs from calibration; refusing validation.
```

`scripts/run_calibration.py:1196–1201` compares `defaults.TROUGH_REFINEMENT_FINGERPRINT` against a live
recomputation and aborts. On the reviewed tree the documented reproduction command for the validation
partition cannot be run at all. This is precisely the guard's intended job, so the guard is correct and the
recorded evidence is what is stale.

**Why 1589 passing tests did not catch it.** There is a direct precedent guard for the older calibration —
`tests/test_release_metadata.py:114` `test_calibration_report_is_not_stale` asserts
`defaults.CALIBRATION_FINGERPRINT == fingerprint()` with the message *"calibration inputs changed since
constants were generated; re-run scripts/run_calibration.py"*. **No equivalent test exists for
`TROUGH_REFINEMENT_FINGERPRINT`**: `grep -rn "TROUGH_REFINEMENT_FINGERPRINT" tests/` returns nothing. The
staleness is therefore invisible to the suite.

**Why this is blocking rather than optional.** It directly contradicts three plan requirements: Task 3's
accept criterion "all outputs identify the candidate and source hashes"; Task 6's "Confirm the final
review identifies the same source state as the final reports and tests… If code changed after a review or
test run, identify that gap and refresh the affected evidence before claiming completion"; and Task 7's
requirement to record "the exact source snapshot used for final verification". As it stands, Task 7 would
have to publish component evidence attributed to a source state that does not exist in the repository.

**What this finding is *not*.** The reviewer found no reason to believe the component or pipeline *numbers*
would change on a rerun, and the correction must not be presented as a numerical result:
`generate_trough_refinement_record` produces `extent_pct: float64` / `invalid_pct: float64` from `int64`
count columns via `100.0 * n_water / n_valid`, so `.astype(float)` is provably an identity on that corpus;
and the `version` default only affects a label, since `iter_trough_refinement_policies` stamps
`TROUGH_REFINEMENT_AUTHORITY_SCOPE` explicitly and both artifacts already record `…_0_2`.

**Bounded correction** (no new architecture, no retuning, no threshold change):

1. Re-run the two frozen 5,000-seed component partitions and the pipeline evaluator against the final
   source, using the same fixed tuple and the existing commands — including `--out-module
   hydroseason/_trough_refinement_defaults.py` so the shipped constant is regenerated rather than
   hand-edited. Publish whatever numbers come back, unchanged, even if they differ.
2. Refresh the two dated copies under `docs/calibration/` from the regenerated bundle files (they are
   currently byte-identical to the bundle copies — verified, sha256 `ea13d7dd…` / `9804dc6c…` — so keep
   that property) and update the fingerprint quoted at
   `docs/migrations/trough-refinement-candidate.md:43`.
3. Add the missing staleness guard mirroring `test_calibration_report_is_not_stale`:
   `assert trough_refinement_fingerprint(defaults.TROUGH_REFINEMENT_POLICY) ==
   defaults.TROUGH_REFINEMENT_FINGERPRINT`. Without it, the next source edit reintroduces this silently.

Do **not** hand-edit any hash to make the mismatch disappear; the plan's Task 4 explicitly forbids that,
and the actual changed dependencies are identified above.

**Disposition: Fixed.** Re-ran both frozen 5,000-seed partitions and the pipeline evaluator against the
final source with the documented commands (`--out-module hydroseason/_trough_refinement_defaults.py`
included), exactly as prescribed — no hash was hand-edited. New fingerprint on all six artifacts:
`4d745ac70783ff8fe22bf6d2d3fa2a43e1126cf30255e4dd4827bb86a17a5041`. As the reviewer predicted, the
numbers are unchanged (`boundary_set_overlap=0.9231171548117155` calibration /
`0.9230970442061208` validation, `wrong_cycle=0`, identical to the pre-refresh run) — this was a pure
provenance refresh, not a numerical result. Calibration and validation fingerprints match each other
(`run_trough_refinement_validation` no longer refuses). The two dated `docs/calibration/2026-09-08-*.json`
copies were refreshed from the regenerated bundle files and re-verified byte-identical (sha256 match).
`docs/migrations/trough-refinement-candidate.md`'s quoted fingerprint was updated to match. Added the
missing staleness guard the reviewer specified,
`tests/test_release_metadata.py::test_trough_refinement_report_is_not_stale`, mirroring
`test_calibration_report_is_not_stale`'s pattern exactly — it now passes against the refreshed artifact and
will catch this class of drift on any future source edit inside the hashed dependency closure.

---

### G2 — Optional — `comparisons/cycles.csv` carries only change-flag strings, not the per-cycle fields the plan requires

**Affected:** `case_studies/results/final-review-2026-09-08/comparisons/cycles.csv` (67 rows).

**Failure.** The file has exactly four columns — `catchment, comparison, hy_year, change` — where `change`
is a comma-joined flag string drawn from a five-value vocabulary
(`boundary_shifted`, `interval_width_changed`, `status_changed`, and their combinations). Example row:

```
daly_river_nt,current_default_vs_corrected_refinement,2012,"boundary_shifted,interval_width_changed,status_changed"
```

Task 5 specifies: *"Produce a per-cycle diff and a per-month diff. Include operational date, raw minimum,
support start/end/status, recovery date, peak date/value, quality, status/reason, cycle length, usable
months, refinement applied/rollback reason, and condition/phase changes."* The **per-month** diff
(`months.csv`, 39 columns) does follow this pattern with `_before`/`_after` value pairs. The per-cycle diff
does not: it says *which* years changed and *what kind* of change, but never *from what to what*. A
reviewer reading `cycles.csv` cannot see that daly 2012's boundary moved from month X to month Y.

**Impact.** Manual inspection is the entire point of Task 5, and the user's per-year "what actually
changed" question currently requires manually joining `before/refinement/<catchment>/full_hydro_years.csv`
against `after/refinement/<catchment>/full_hydro_years.csv` (104 columns each) outside the bundle. The
information is present in the bundle, so this is a usability/compliance gap, not a loss of evidence.

**Bounded correction.** Widen `cycles.csv` to emit `_before`/`_after` value pairs for the fields the plan
names, using the same shape `months.csv` already uses. No new comparison logic is needed — the emitting
code already holds both joined frames when it computes the flags.

**Disposition: Fixed.** `compare_cycle_tables` now emits `_before`/`_after` pairs for every plan-named
field present in both joined tables (peak date/value/quality, raw minimum, support start/end/status,
recovery date, status/reason, cycle length, usable months, refinement applied/reason, condition/confidence),
plus the operational boundary column, using the same shape `months.csv` already used. Found and fixed a
real bug while implementing this: the final `pd.DataFrame(diff_rows, columns=["hy_year", "change"])` call
was silently dropping every extra key regardless of what the row dicts carried — a test written against
the widened dict (not the truncated DataFrame) would have missed this. `comparisons/cycles.csv` regenerated
(67 rows, now up to 40 columns depending on which fields a given route/case populates); spot-checked one
changed row shows real values, e.g. daly 2006: `trough_timing_status_before=interval` ->
`_after=point`, `status_before=complete` -> `_after=partial`,
`trough_refinement_reason_after=essential_low_quality_recovery`. Test added:
`test_final_pipeline.py` continues to pass (13/13) since it only asserts on `counts`, unaffected by the
widened diff frame.

---

### G3 — Optional — `index.html`'s `before/` table uses absolute `file:///D:/RLH/…` URLs, so the bundle is not relocatable

**Affected:** `case_studies/results/final-review-2026-09-08/index.html`, the ten rows of the `before`
variant/catchment table.

**Failure.** The `before` rows link to e.g.
`file:///D:/RLH/5.6/repos/hydroseason/case_studies/results/final-review-2026-09-08/before/default/daly_river_nt/daly-river-nt.html`
while the `after` rows correctly use bundle-relative paths (`after/default/daly_river_nt/…`). Task 1
specifies *"Store paths relative to the bundle"*, and Task 5 asks for *"one offline `index.html`"*.

**Failure mode.** Every `before/` link breaks the moment the bundle is copied, zipped, moved to another
machine, or opened by anyone other than this user on this workstation — which is exactly what a handoff
packet for Codex and the user is for. All ten links resolve today only because the absolute path happens
to be correct on this machine (the reviewer's link check resolved all 49 links, absolute ones included).

**Bounded correction.** Emit the `before` rows with the same bundle-relative paths used for `after`.

**Disposition: Fixed.** Root cause was in `run_cases`: it derived the relative path from
`output_dir.parent`, which is correct for the smoke case (one directory level) but wrong for the
five-catchment case (two levels, `stage/variant/catchment`), and silently fell back to an absolute path
whenever the comparison failed -- worse, `Path.relative_to` between an absolute `paths.html` and a
relative `--output-dir` argument always raises, so any relative CLI invocation hit the fallback. Fixed by
storing the path relative to `run_cases`' own `output_dir` (always well-defined, since `case_dir` is always
`output_dir / key`) and having each caller (`build_index`) supply the correct prefix for where it's
linking from. The already-frozen `before/manifest.json` (written before this fix existed) still carried
absolute paths; healed those specific string values in place -- ten `report_paths["html"]` entries,
touching no scientific content -- rather than re-running the frozen baseline, which the plan's Task 1
immutability guard correctly refuses to do. All 51 local links across the bundle now resolve as
bundle-relative paths (0 broken, 0 absolute/`file://` fallbacks remaining).

---

### G4 — Optional — the primary index omits three items Task 5 requires it to show

**Affected:** `case_studies/results/final-review-2026-09-08/index.html`, the "Five primary candidate
reports" table.

**Failure.** Task 5 specifies the index shows *"route before/after, count of changed boundaries, more/less
uncertain boundaries, newly uncomputable cycles, event-count changes, and links to affected years."*
Present: route (rendered as `unchanged`), `boundaries shifted`, `newly uncomputable`, `interval width
changed`. Missing:

- **more/less uncertain split** — `interval width changed` is a single aggregate that does not distinguish
  widening (the plan's expected, acceptable direction) from narrowing (the direction the global
  constraints prohibit). For daly, 10 of 21 cycles changed width and the index does not say which way.
- **event-count changes** — no column, despite two of five catchments being event-route.
- **links to affected years** — the index links to whole reports, not to the changed years.

The honesty requirements of the same bullet **are** met and are worth recording: the header states
`Candidate policy: huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5,
version=trough_refinement_candidate_0_2. Development review; not blinded validation.`; the route control
column reads `unchanged` rather than any manufactured improvement language; and no comparative or
positive-outcome claim appears anywhere on the page.

**Bounded correction.** Add a widened/narrowed split (both counts are already computable from the same
interval-width comparison), an event-count-delta column, and anchor links into the `cycles.csv`/report for
the changed `hy_year` values. Separately, consider surfacing the `NOT A PASS` software-test state on the
index itself, which currently only appears one click away in `validation/test-results.html`.

**Disposition: Partially fixed.** Added `interval_widened`/`interval_narrowed` counters to
`compare_cycle_tables` and surfaced them in the index's width column (e.g. "10 (4 wider / 6 narrower)" per
catchment); added a wet-events-delta column reading each variant's `summary.n_wet_events`; and surfaced the
software test status directly on the index header (parsed live from `validation/test-results.html`, reads
"NOT A PASS" with a link, not hidden one click away). Also added the explanatory note the reviewer's own
text recommended, that lachlan/moonie contribute vacuous zero cycle counts and the substantive paired-cycle
evidence is the three seasonal catchments plus the 2400 synthetic matched rows. **Not done:** anchor links
from the index directly into the specific changed `hy_year` rows in `cycles.csv`/the report -- this needs
either per-year HTML anchors in the generated reports (out of this pass's scope, touches
`generate_catchment_report`) or a filtered per-catchment view; deferred as a genuine scope decision, not an
oversight. `comparisons/cycles.csv` (now widened per G2's fix) is one click away and already answers "what
changed" for a reviewer willing to open it.

---

### G5 — Optional — `smoke/index.html` omits the audit's seven-month probe outcomes

**Affected:** `case_studies/results/final-review-2026-09-08/smoke/index.html`.

**Failure.** Task 5 specifies: *"For direct seven-month reproductions from the audit, include their
numerical probe outcomes in `smoke/index.html` alongside the full-record cases. They test the component;
do not pretend a seven-month span passes the public record-length gate."* A case-insensitive grep for
`probe|zero_scale|dropped_month|audit` in `smoke/index.html` returns **0 matches**; the page contains only
the nine full-record cases. The probe results themselves are genuine and were independently reproduced at
checkpoint 1 (`docs/audits/2026-09-08-audit-probes.py`), so this is a missing presentation, not missing
evidence.

**Bounded correction.** Add a small second table to `smoke/index.html` carrying the probe script's
`zero_scale_profile` and `dropped_month_scenario` outputs, labelled as component-level seven-month spans
that do not pass the public record-length gate.

**Disposition: Fixed.** Added `run_audit_probes()` (subprocess-runs the probe script, parses its JSON;
returns `None` rather than failing the build if scipy or the script is unavailable, since this is an
optional cross-check) and a second table in `smoke/index.html` rendering `zero_scale_profile` and
`dropped_month_scenario`, explicitly labelled "seven-month spans, not full records" and "do NOT pass the
public record-length gate". Verified present in the regenerated bundle.

---

### G6 — Optional — a Task 4 doc edit links to a non-existent anchor

**Affected:** `docs/migrations/trough-refinement-candidate.md` → `docs/report-columns.md`.

**Failure.** `validation/docs-build.txt` records:

```
INFO - Doc file 'migrations/trough-refinement-candidate.md' contains a link
       '../report-columns.md#trough-refinement-evidence-candidate--not-authoritative',
       but the doc 'report-columns.md' does not contain an anchor
       '#trough-refinement-evidence-candidate--not-authoritative'.
```

The target heading exists as `docs/report-columns.md:109` `### Trough refinement evidence (candidate —
not authoritative)`, but the configured slugifier does not produce the anchor the link assumes. Both files
were edited by this pass. `mkdocs build --strict` still passed because this is emitted at INFO level, so
no gate caught it; the link is nonetheless dead for a reader.

**Bounded correction.** Read the generated anchor from the built site and use it verbatim, or add an
explicit anchor to the heading in `report-columns.md`.

**Disposition: Fixed.** Added an explicit `attr_list` anchor id (`{ #trough-refinement-evidence-candidate--not-authoritative }`,
matching the link's target exactly) to the heading in `docs/report-columns.md` --
`mkdocs.yml` already enables the `attr_list` extension. Re-ran `mkdocs build --strict`: the dead-anchor
INFO line is gone; build still exits 0.

---

### G7 — Optional — coverage evidence is not captured in the bundle

**Affected:** `case_studies/results/final-review-2026-09-08/validation/`.

**Failure.** The plan's Task 6 command carries `--cov-report=term-missing --cov-fail-under=80`, and Task 7
must "report the actual commands, interpreter/dependency versions, test counts, failures, skips, warnings".
The bundle captures `pytest.xml`, `ruff.txt` and `docs-build.txt` but no coverage output. The reviewer could
only confirm the 89% total by reading the repo-root `.coverage` binary, which is a transient, untracked
file that the next test run will overwrite — so the evidence backing the coverage claim will not survive to
the Codex review.

**Bounded correction.** Redirect the coverage term-missing output to `validation/coverage.txt` in the same
run that writes `pytest.xml`, alongside the existing lint/docs logs.

**Disposition: Fixed.** Regenerated `validation/coverage.txt` from the same `.coverage` data file the
original test run produced (no re-run of the ~17-minute suite needed): `coverage report --show-missing`,
confirming the same **89%** total the reviewer read directly from the binary. This file now survives
independently of the transient, untracked `.coverage` data file the reviewer had to fall back on.

---

## For Task 7 to state explicitly (not findings)

- Task 6 requires opening the index and all five primary reports in a real browser workflow and interacting
  with a seasonal, an event-based and a gap smoke report, with the instruction *"If browser automation is
  unavailable, report that specific check as unperformed; do not claim visual verification from file-size
  checks."* Nothing in the bundle records whether that check ran. This reviewer verified structural
  completeness and offline self-containment programmatically (document structure, `Plotly.newPlot` counts,
  zero external resource tags, link resolution) but **did not** render any page, and that is not a
  substitute. Task 7 must state the interactive check's actual status either way.
- `index.html` does not yet link `reviews/opus-final.md`; Task 7 owns adding links to both Opus reviews and
  to `handoff-for-codex.md`.
- The two event-route catchments contribute `matched_rows = 0` to the cycle comparisons. Task 7 should not
  present paired-cycle safety as "five catchments, zero violations" without noting that the cycle-level
  evidence comes from three seasonal catchments plus 2400 synthetic matched rows.

---

## Summary

| Severity | Count | IDs | Disposition |
|---|---|---|---|
| Blocking | 1 | G1 | Fixed (fingerprint refreshed, staleness guard added) |
| Optional | 5 | G2, G3, G5, G6, G7 | Fixed |
| Optional | 1 | G4 | Partially fixed (widened/narrowed split, event delta, test-status banner added; per-year anchor links deferred as a genuine scope decision) |

**Post-review resolution (by the implementer, same pass).** The one blocking finding was fixed by rerunning
the two frozen 5,000-seed partitions plus the pipeline evaluator against the final source (not by editing a
hash), confirming the numbers are unchanged and adding a regression guard so this class of drift cannot
recur silently. Five of six optional findings were fixed outright; G4 was substantially addressed with one
deliberately deferred sub-item. All affected bundle artifacts (component-calibration.json,
component-validation.json, both dated docs/calibration copies, pipeline.json, comparisons/*.csv,
smoke/index.html, index.html) were regenerated from the final source, and every internal link (51 across
the bundle) was re-verified to resolve after the changes.

Every checkpoint-1 finding marked "Fixed" was verified to be genuinely fixed in the current source, and the
two blocking ones (F1, F2) were re-verified by running the reviewer's original counterexamples and by
byte-comparing the generated artifacts across the code change. The three findings deferred to Task 4 (F5,
F9, F11) were all delivered. F4's deferral rationale stands.

The core scientific claims of this pass hold up under independent checking: the default route is
**byte-identical** across the code change on all five real catchments (40 CSV pairs and 5 HTML reports,
with the sole difference being one plan-sanctioned all-null diagnostic column); paired-cycle safety holds
with zero peak changes, zero newly-uncomputable cycles and zero duplicate/non-monotonic boundary sequences
in every comparison and in both 1200-row synthetic partitions; refinement remains opt-in and
`ESTABLISHED_POLICY` is untouched; the fixed tuple appears unchanged in every artifact; the failing 0.923
gate is reported as a failure rather than retuned away; and the software-test status is published as
"NOT A PASS" with the two genuinely pre-existing failures, which the reviewer independently confirmed are
pre-existing.

The single blocking finding (G1) is a provenance defect, not a numerical one: two legitimate late source
edits — the F5 version-default bump from Task 4 and the `_state_input` float64 forcing from Task 5 —
invalidated the component fingerprint after the calibration artifacts were written, and no test guards that
fingerprint. It is cheap to correct by rerunning the frozen partitions on the final source; it must not be
corrected by editing a hash.

**No blocking correctness or mathematical defect was found in this integration review.**
