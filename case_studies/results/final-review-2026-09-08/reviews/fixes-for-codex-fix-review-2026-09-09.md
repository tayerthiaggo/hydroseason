# Fixes for Codex fix-review (2026-09-09) — report for Codex Astra 6

**Purpose of this document:** [`codex-fix-review-2026-09-09.md`](codex-fix-review-2026-09-09.md)
independently re-reviewed [`fixes-for-codex-astra-6.md`](fixes-for-codex-astra-6.md) (the fix for
the original six findings, C1–C6) against current source, and confirmed C1, C2, C5, C6 closed
with **no new scientific defect**. It found two remaining items, both scoped as
provenance/documentation, not detector behaviour:

- **C3 (P2):** the published pipeline-evaluation `manifest_hash` did not match current source,
  and a stale hash label plus an under-described `before_source` gap remained in
  `handoff-for-codex.md` §1.
- **C4 (P2):** `docs/superpowers/audit_briefing.md` still used one unqualified `sigma_noise`
  symbol for two numerically different estimators (boundary vs. event noise).

Both are fixed below. **No component recalibration, no gate change, no detector-behaviour
change** was made — the reviewing Codex pass explicitly said neither was required, and this pass
did not go looking for one.

---

## C3 — pipeline provenance: wrong/incomplete fingerprint module list, stale hash citation

**Root cause, part 1 (the fingerprint itself).** `scripts/evaluate_final_pipeline.py`'s
`_pipeline_manifest_hash` hashed `(_boundary, _calibration, _catchment, _condition, _phase,
_dynamic_year, _synthetic)`. Three of those — `_catchment`, `_condition`, `_phase` — are not
imported anywhere in `evaluate_final_pipeline.py`, `_dynamic_year.py`, or `_synthetic.py`; they
were never part of this evaluation's real call graph. Meanwhile `_dynamic_year.py` (whose
`detect_dynamic_hydrological_years` this evaluation calls twice per record) actually imports
`_timing_identifiability`, `_recurrence_identifiability`, `_scientific_defaults`, `_seasonality`,
`_state_input`, and `_phase_scheme` — none of which were hashed. `_timing_identifiability` itself
imports `_circular_timing`, also unhashed; `_seasonality` imports `_harmonic`, also unhashed. The
practical consequence the reviewing Codex pass hit: a later, purely cosmetic edit to this
module's own `from hydroseason import ...` formatting changed the fingerprint (because the whole
file's bytes are hashed), while the published `manifest_hash`
(`9b1589977236cb50fe53b1e6b2079be2c35bf291b48dba0b35d705ec82cf311a`) no longer matched what
current source computed (`cd912ce20882a5663a9641719df515100e529dbe5fc4d56f54576f5fb616bd5f`) —
confirmed by the reviewer to be a provenance mismatch only (an independent rerun reproduced
identical numbers under both).

**Root cause, part 2 (the handoff text).** `handoff-for-codex.md` §1 quoted
`7be3e3851a86c0552df0d756866e5c0c6eda7ba710e29bc986253061861c871e` as
`manifest.json:finalize_time_source.dirty_patch_hash`; that value is actually
`after_source.dirty_patch_hash` — an earlier stage's own capture, not `finalize_time_source`'s.
The real `finalize_time_source.dirty_patch_hash` is
`259228524716cc115c55a422d5a76bdef7bfe927e7bd60be198272f39b94ed07`. Separately, §1 described
`before_source`, `after_source`, and `finalize_time_source` as three distinct snapshots without
noting that `before_source` alone carries no archived patch or new-file contents — it cannot be
reconstructed from the manifest the way the other two can.

**Fix.**

1. `scripts/evaluate_final_pipeline.py`: `_pipeline_manifest_hash` now hashes the real static
   import closure — `_boundary`, `_calibration`, `_circular_timing`, `_dynamic_year`,
   `_harmonic`, `_phase_scheme`, `_recurrence_identifiability`, `_scientific_defaults`,
   `_seasonality`, `_state_input`, `_synthetic`, `_timing_identifiability` — dropping
   `_catchment`/`_condition`/`_phase`, which were never real dependencies.
   `_trough_refinement.py` remains covered separately via
   `trough_refinement_fingerprint(policy)`, not duplicated in this list. A new code comment
   states explicitly that this is a **named list, not a computed call graph**: a future new
   import inside any of these modules is not automatically covered, and this deliberately does
   not claim exhaustiveness (per the reviewer's own instruction to stop making that claim).
2. `validation/pipeline.json` and `validation/pipeline-cycles.csv` re-published from current
   source with `scripts/evaluate_final_pipeline.py --output-dir
   case_studies/results/final-review-2026-09-08/validation`.
3. New staleness guard `tests/test_release_metadata.py::test_published_pipeline_evaluation_is_not_stale`,
   mirroring the existing `test_trough_refinement_report_is_not_stale` /
   `test_calibration_report_is_not_stale` component checks the reviewer referenced by name — it
   loads the published `pipeline.json`, recomputes `_pipeline_manifest_hash` against current
   source, and fails if they diverge.
4. `handoff-for-codex.md` §1: corrected the quoted hash to `finalize_time_source`'s actual value,
   parenthetically noted what the old (now-removed) citation actually was, and added an explicit
   line stating `before_source`'s reconstruction is unavailable — not regenerated, per the
   reviewer's instruction not to backfill the historical baseline.
5. `handoff-for-codex.md` new §10 and `reviews/fixes-for-codex-astra-6.md`'s "Regenerated
   evidence" section updated to cite the new hash and the corrected seed-count phrasing (see
   below).

**Verification.**

1. New fingerprint: `9e61e98c9195eec90dedd9721643545ed420f9b35ab6f83bfa66f46efa74c104`.
2. **Byte-for-byte numerical identity check:** compared the pre-fix `pipeline-cycles.csv`
   (`reviews/codex-fix-verification-2026-09-09/pipeline-cycles.csv`, the reviewer's own
   independent rerun) against the re-published `validation/pipeline-cycles.csv` — both 200 rows
   × 24 columns, and every cell equal after normalizing NaNs to a common sentinel. Structural
   safety fields (`peak_changes`, `newly_uncomputable`,
   `before/after_duplicate_or_nonmonotonic_boundaries`) are `0` in both partitions, and
   `matched_rows: 1200` each, matching every number already cited in the handoff. This confirms
   the reviewer's own finding: broadening the fingerprint changed provenance metadata only, zero
   detector output changed.
3. `tests/test_release_metadata.py::test_published_pipeline_evaluation_is_not_stale` passes
   against the re-published bundle.
4. Full targeted suite:
   ```powershell
   .venv\Scripts\python.exe -m pytest tests/test_final_pipeline.py tests/test_final_review.py tests/test_release_metadata.py -q --disable-warnings
   ```
   `44 passed`.
5. `ruff check scripts/evaluate_final_pipeline.py tests/test_release_metadata.py`: clean.

**Scope note carried into the code and this report, per the reviewer's explicit instruction:**
this fingerprint is now the real static-import closure of the code path this evaluation actually
runs, not a claim of exhaustive coverage of `evaluate_records`'s entire transitive call graph
(numpy/pandas internals, or any future new import added inside one of the twelve hashed modules,
are outside what a source-hash list like this can promise). `before_source` remains a fixed
reference point with no archived patch/new-file contents, by design — it is not backfilled.

---

## C4 — boundary noise and event noise still shared one symbol

**Root cause.** `docs/superpowers/audit_briefing.md` Step 2 defined `sigma_noise` as
`_boundary.robust_scale`'s deseasonalized, uncorrected MAD-of-differences estimator. Step 7 then
used the same bare `sigma_noise` symbol in the event entry/exit/low-spell threshold formulas —
but those thresholds are actually computed from `_events._noise_scale`, which differences the
**raw** (not deseasonalized) series and applies an **AR(1) correction**
(`scale / sqrt(1 - phi)`, `phi` clamped to `[0, 0.9]`). The two estimators are numerically
unrelated; conflating them under one symbol misdescribes Step 7's actual math, a defect the prior
C4 fix (removing every literal `AR(1)` mention from the document) made worse rather than better.

**Fix** (`docs/superpowers/audit_briefing.md`):

- Step 2's estimator relabelled `sigma_noise^{boundary}` everywhere it's used through Steps 2–6
  (detectability floor, extrema identifiability, `n_rewetting_pulses`), with an explicit note
  that Step 7 uses a different, separately defined estimator.
- Step 7 gained a new opening item defining `sigma_noise^{event}` (`_events._noise_scale`)
  **before** it is used: states plainly that it is a separate estimator from Step 2's, computed
  on the raw series, AR(1)-corrected, with the correction formula given. All three threshold
  formulas (entry, exit, low-spell) now reference `sigma_noise^{event}` instead of the bare
  symbol.
- The previously corrected low-spell minus sign (`median - 1.0 * sigma_noise`) is unchanged —
  only the noise symbol it multiplies was touched.
- No implementation change; this is a documentation-only fix, as the reviewer required
  ("No numerical implementation change is required").

**Verification.** Independently reproduced the reviewer's own numerical probe against current
source, on the same synthetic 20-year seasonal series (`y[t] = 50 + 20*sin(2*pi*t/12)`, monthly,
run through `prepare_monthly_extent` for the boundary estimator):

```text
boundary robust_scale noise: 4.469412632149564e-14
event _noise_scale:          15.401243706694842
```

Matches the review's cited `4.4694e-14 pp` / `15.4012 pp` exactly — the two estimators are
confirmed numerically distinct on identical input, which is exactly what the two-symbol
correction now documents. A repository-wide check confirms `docs/superpowers/audit_briefing.md`
no longer uses a bare, unqualified `sigma_noise` anywhere in Steps 2–7.

---

## Regenerated evidence

- `validation/pipeline.json`, `validation/pipeline-cycles.csv` — re-published from current
  source (new `manifest_hash` `9e61e98c9195eec90dedd9721643545ed420f9b35ab6f83bfa66f46efa74c104`,
  numbers unchanged from the pre-fix run, verified byte-for-byte).
- `docs/superpowers/audit_briefing.md` — Steps 2 and 7 corrected (documentation only).
- `handoff-for-codex.md` — §1 hash citation and `before_source` scope note corrected; new §10
  added summarizing this round.
- `reviews/fixes-for-codex-astra-6.md` — "Regenerated evidence" pipeline bullet updated to the
  new hash, corrected module list, and corrected seed-count phrasing (100 seeds per partition,
  200 total — the reviewer's own correction of the prior "200 seeds × 2 partitions" wording).
- New test: `tests/test_release_metadata.py::test_published_pipeline_evaluation_is_not_stale`.

**Test/lint status after this round:**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_final_pipeline.py tests/test_final_review.py tests/test_release_metadata.py -q --disable-warnings
```
`44 passed`. `ruff check` clean on every file this round touched.

**Full suite, re-run for this round** (not skipped this time):
```powershell
.venv\Scripts\python.exe -m pytest -q --disable-warnings
```
`1594 passed, 2 failed, 1 skipped, 2 xfailed` (1599 total, up from the prior round's 1598 by
exactly the one new test added here). Both failures are the same two pre-existing, unrelated
ones already recorded in `handoff-for-codex.md` §9 —
`tests/test_decision_policy_docs.py::test_recurrence_identifiability_promotion_docs` (against the
pre-existing `docs/migrations/0.2.0-timing-identifiability.md` edit) and
`tests/test_package_surface.py::test_package_import_exposes_only_migration_safe_surface` (against
`hydroseason/__init__.py`, untouched by this or the prior fix pass) — neither file was touched by
C3 or C4. The previously-reported third, intermittent `tests/test_io_dea_stats.py` full-suite
flake did not reproduce in this run, consistent with the reviewing Codex pass's own
"intermittent/untriaged" characterization rather than a deterministic defect.

---

## Suggested checklist for Codex Astra 6

- [ ] C3: confirm `_pipeline_manifest_hash`'s twelve-module list is `_dynamic_year.py`'s actual
      `from .` import closure (it is meant to be exactly that, not a superset or subset).
- [ ] C3: confirm `handoff-for-codex.md` §1 now cites `finalize_time_source.dirty_patch_hash`
      correctly against `manifest.json`.
- [ ] C4: confirm Step 7's `sigma_noise^{event}` formula matches `_events._noise_scale` and that
      no bare `sigma_noise` remains anywhere in Steps 2–7.
- [ ] Confirm `test_published_pipeline_evaluation_is_not_stale` actually fails if
      `_pipeline_manifest_hash`'s module list is reverted (spot-check, not required to re-run
      unless doubted).
