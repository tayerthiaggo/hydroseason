# Codex closure review — 2026-09-09

**Accepted within the bounded review scope. C3 and C4 are now closed; all six original findings are closed. No further blocking finding was demonstrated.** This accepts the corrections and their evidence, not default-policy promotion or release readiness.

Reviewed `fixes-for-codex-fix-review-2026-09-09.md` against the preceding review, current source, published pipeline artifacts, source manifests, and briefing. Existing implementation and submitted artifacts were not edited. A separate [source snapshot for this review](codex-closure-source-2026-09-09.json) preserves the reviewed tracked patch, new Python sources, briefing text, and relevant file hashes.

## C3: closed

- Live pipeline fingerprint exactly matches published `validation/pipeline.json`:

  ```text
  9e61e98c9195eec90dedd9721643545ed420f9b35ab6f83bfa66f46efa74c104
  ```

- Both partition summaries and the policy are identical to the preceding review's independent rerun. Published `pipeline-cycles.csv` is **byte-identical** to that rerun's CSV. The evaluation covers 100 calibration and 100 validation records, 200 total.
- Independently traversed local relative imports using Python AST, starting from `_dynamic_year` and `_synthetic`. Every discovered package module is covered by the revised list or, for `_trough_refinement`, the component fingerprint. `_calibration` additionally supplies the evaluator's scoring threshold. No missing module was found in that checked local import closure. The documented limitation that this is a maintained list, not automatic future dependency discovery, is appropriate.
- `test_published_pipeline_evaluation_is_not_stale` passes with current source. A separate in-memory check changed the actual scoring threshold, invoked that test, and confirmed it raises `AssertionError`; restoring the threshold makes the test pass again. No source file was modified for that check.
- Handoff §1 now cites the value actually stored in `manifest.json:finalize_time_source.dirty_patch_hash`, and explicitly states that historical `before_source` cannot be reconstructed from its hash-only record. The original baseline remains untouched.

The submitted `finalize_time_source` is a historical stage stamp, as documented; it is not a snapshot of this newest review state. Its evaluator text predates this round's fingerprint changes, and its tracked patch predates the added metadata test. The reviewed current tracked-patch hash is `0a051b98f650a5c34246b73204ce29aac5c14e5f0105d926feafdb830c0ae5b2`, preserved in the separate closure source snapshot linked above. This distinction is retained rather than overwriting historical provenance.

## C4: closed

Briefing Step 2 now defines `sigma_noise^{boundary}` as the deseasonalized MAD-of-differences estimator divided by `sqrt(2)`, without autocorrelation correction. Step 7 separately defines `sigma_noise^{event}` using raw-series differences and the `1/sqrt(1-phi)` correction with phi clamped to `[0, 0.9]`.

The event entry, exit, and low-spell equations use the event symbol; the low-spell minus sign is preserved. The two definitions agree with `_boundary.robust_scale` and `_events._noise_scale`. This resolves the remaining estimator conflation without changing numerical implementation. Other briefing topics were not reopened as a general scientific audit.

## Verification and limits

**44 targeted tests passed**, independently rerun in 113.91 seconds:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_final_pipeline.py tests/test_final_review.py tests/test_release_metadata.py -q --disable-warnings
```

**Lint passed** for `scripts/evaluate_final_pipeline.py` and `tests/test_release_metadata.py`. Component fingerprint remains unchanged at `0f4d5432617064cf3c918bee397efdf0c2e0de036bf702b34ed0021b1944c716`.

The latest fix report states a full-suite rerun of 1594 passed, 2 failed, 1 skipped, and 2 xfailed. That latest result is **implementer-reported**, not independently reproduced here. The saved `validation/pytest.xml` still describes the previous run: 1598 total, 1592 passed, 3 failed, 3 skipped. Do not cite that XML as evidence for the new full-suite counts. The two known unrelated failures therefore remain a release-status limitation; closure of C1–C6 is not a claim that the entire suite is green.

This round did not repeat the full component calibration, the full 200-record pipeline computation, or browser inspection. Direct hash checks, byte/numerical comparisons to the previous independent pipeline rerun, targeted tests, and the unchanged scientific implementation were sufficient for these provenance/documentation corrections. Manual report feedback remains pending.

The bounded correction loop can stop. Proceed with the planned manual catchment-report inspection; keep refinement opt-in and unpromoted.
