# Codex fix review — 2026-09-09

**Verdict: C1, C2, C5, and C6 closed. C3 and C4 remain partly resolved. No new P1 scientific defect found.** The remaining corrections concern provenance and scientific explanation; they do not call for retuning or another detector redesign.

Scope: independently reviewed `fixes-for-codex-astra-6.md` against the six findings in `codex-final.md`, current implementations, archived source snapshots, tests, and regenerated artifacts. Scientific source and the submitted evidence were left unchanged. This review and a separate independent pipeline rerun were added under `reviews/`.

## Remaining finding: C3 — P2, final provenance is still inconsistent

**Locations:** `scripts/evaluate_final_pipeline.py:454–477`, `validation/pipeline.json:manifest_hash`, `handoff-for-codex.md:35–37`.

The source archiving and stage separation are useful corrections. The four new scripts/tests are archived with content hashes, the tracked patch is embedded, and `before_source`, `after_source`, and `finalize_time_source` are distinct. The original threshold-mutation probe now correctly changes the pipeline fingerprint.

However, the delivered pipeline fingerprint does not match the current evaluator:

```text
published: 9b1589977236cb50fe53b1e6b2079be2c35bf291b48dba0b35d705ec82cf311a
current:   cd912ce20882a5663a9641719df515100e529dbe5fc4d56f54576f5fb616bd5f
```

The cause is established, not speculative. Comparing `after_source.untracked_python_sources["scripts/evaluate_final_pipeline.py"]` with the live file shows only the later formatting of the `from hydroseason import ...` statement into a multiline import. Recomputing the fingerprint with that archived evaluator text and the current dependency sources reproduces the **published** hash exactly. Using the current evaluator reproduces the **current** hash. The formatting edit occurred after the evaluated source snapshot.

I independently reran both pipeline partitions on the current source. **All partition metrics are identical, and `pipeline-cycles.csv` is byte-identical.** Therefore this is a provenance mismatch, not a demonstrated numerical regression. The independent results are saved in [codex-fix-verification-2026-09-09/pipeline.json](codex-fix-verification-2026-09-09/pipeline.json) and [pipeline-cycles.csv](codex-fix-verification-2026-09-09/pipeline-cycles.csv).

The handoff's claimed current `finalize_time_source.dirty_patch_hash` is also stale: it says `7be3e385...`, which is the after-stage patch. Both the current tree and the actual finalize snapshot have:

```text
259228524716cc115c55a422d5a76bdef7bfe927e7bd60be198272f39b94ed07
```

Two scope qualifications are still needed:

- The widened pipeline fingerprint is **not the complete call graph** requested in the fix report's checklist. For example, `_dynamic_year.py:698` calls `assess_window_timing`, but `_timing_identifiability.py` is not hashed; its `_circular_timing` and recurrence implementation dependencies are not hashed either. Hashing the text of an import does not hash the imported implementation. A tracked-source snapshot can provide the broader identity, but the standalone fingerprint must not be described as complete. This review found no evidence that those omitted modules changed during this fix pass.
- `before_source` still contains only revision, branch, dirty flag, patch hash, and porcelain status. It has no archived patch or new-file contents. Preserving this historical baseline is correct; explicitly label its source reconstruction as unavailable rather than describing all three stages as fully archived snapshots. Do not regenerate the historical baseline to fill the gap.

**Bounded correction:** publish a pipeline evaluation from the final frozen source, update the handoff's actual manifest reference/hash, and add a pipeline-artifact staleness check alongside the component check. Either bind the pipeline artifact explicitly to the complete archived source snapshot or finish covering the relevant package source in its fingerprint; avoid another claim that the current selected module list is exhaustive. No component recalibration is needed solely for an evaluator import-formatting edit.

## Remaining finding: C4 — P2, boundary and event noise remain conflated

**Locations:** `docs/superpowers/audit_briefing.md:68–69`, `:167–172`; compare `hydroseason/_events.py:78–99`.

The five cited edits are present: observed-pixel denominator, corrected boundary-noise formula, Monte Carlo Kuiper wording, temporal recurrence description, and the low-spell minus sign. The boundary-noise correction is accurate in isolation.

But Step 2 now defines the document's only `sigma_noise` as the deseasonalized, uncorrected boundary estimator. Step 7 still uses that same symbol for event and low-spell thresholds without defining their **different** estimator. The event code actually differences the raw series and applies the AR(1) correction. Removing every `AR(1)` occurrence, as the fix report celebrates, leaves the event equations referring to the wrong definition.

Independent numerical check using the same 20-year seasonal series from the original audit:

```text
y[t] = 50 + 20*sin(2*pi*t/12)
boundary robust_scale noise: 4.4694e-14 pp
event _noise_scale:          15.4012 pp
```

These cannot share one unqualified estimator definition. Correcting the boundary formula alone does not finish the plan's explicit requirement to distinguish boundary and event noise.

**Bounded correction:** label Step 2's estimator as boundary noise, and define a separate event-noise symbol in Step 7 using `_events._noise_scale` before using it in event/low-spell thresholds. Preserve the newly corrected minus sign. No numerical implementation change is required.

## Closed findings

| Finding | Independent verification | Disposition |
|---|---|---|
| C1 | Original count-based reproduction now returns `unresolved / post_gap_return_to_low_state`, boundary null. Additional zero-scale exact-return and positive-scale within-tolerance-return probes abstain. Clean-recovery controls remain `provisional / recovery_crosses_gap` in both loss regimes. Existing/new tests pass. | Closed |
| C2 | Recovery-only change now emits `value_changed`, while structural counters remain unchanged. All five previously missing Daly/Fitzroy years appear in the submitted regenerated `comparisons/cycles.csv` with correct recovery before/after values. Original missing-row probe reports none. | Closed |
| C5 | Both handoff tables match their corresponding comparison CSV rows: old-to-corrected shifts 3/3/2, widths 3/0, 3/0, 5/0, no complete/partial downgrades; default-to-corrected shifts 4/3/2 and downgrades 13/7/8. | Closed |
| C6 | All-case fields use every cache row; conditional fields retain the resolvable-truth denominator. Migration table labels both explicitly. Calibration reports 3530/5000 and validation 3529/5000 all-case coverage, distinct from 3530/3824 and 3529/3823 conditional coverage. The dedicated differing-denominators regression passes. | Closed |

For C1, an unresolved result still retains the pre-gap support as diagnostic evidence, but the operational boundary is null and the result is not accepted as a refinement. That is the conservative abstention requested by the original review, not the prior unsupported committed singleton.

## Verification

- **89 focused tests passed** in 115.02 seconds:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_trough_refinement.py tests/test_trough_refinement_calibration.py tests/test_final_pipeline.py tests/test_final_review.py tests/test_release_metadata.py -q --disable-warnings
  ```

- **Touched-file lint passed:** refinement implementation/calibration, both review/evaluation scripts, and their four test files.
- **Independent full pipeline rerun passed:** 100 calibration plus 100 validation records, not 200 per partition. Both partition summaries exactly match the submitted numerical results. Per-record CSV is byte-identical. Command:

  ```powershell
  .\.venv\Scripts\python.exe scripts/evaluate_final_pipeline.py --output-dir .tmp-codex-fix-review-20260909/pipeline
  ```

  Copies of this review's output are linked above; the submitted `validation/` files were not overwritten.
- Current component fingerprint is `0f4d5432617064cf3c918bee397efdf0c2e0de036bf702b34ed0021b1944c716`, matching the generated defaults/artifacts. Both dated component JSON copies are byte-identical to bundle copies. I did not rerun the two 5000-seed component campaigns.
- The five default report directories retain the same byte-comparison result as the earlier review: all shared outputs identical; the three seasonal full annual CSVs differ from the historical baseline only by the previously added diagnostic column. Both event-route bundles are unchanged. Comparison counters remain as reported.
- Parsed submitted JUnit: **1598 total, 1592 passed, 3 failed, 3 skipped, 0 errors**. Submitted coverage report has 8664 statements, 911 missed, displayed as 89%. I did not rerun the full suite or coverage campaign.
- The newly observed `test_io_dea_stats` failure is an `os.replace` **PermissionError: [WinError 5] Access is denied**, not a failing digest assertion. Its isolated rerun passes (1 test, 2.60 seconds). This is consistent with an intermittent filesystem/environment issue, but does **not** establish the report's categorical claim of a pre-existing test-order defect. Unmodified files alone cannot prove independence from changed callers. Record the failure as intermittent/untriaged unless there is stronger causal evidence; no unrelated repair is requested here.
- The fix report's “200 seeds × 2 partitions” should read **100 seeds per partition, 200 total**. Its numerical table already uses the correct 1200 matched rows per partition.
- No new browser verification was performed in this follow-up. The earlier unavailable-browser check and pending manual feedback remain the recorded limits.

The C1 scientific correction is accepted. Finish the two remaining provenance/documentation items, preserve the frozen tuple and baseline, and recheck only the affected artifacts/claims.
