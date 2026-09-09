# Codex bounded final review — 2026-09-08

**Verdict: changes requested.** Six substantiated findings remain. C1 is a scientific support-set defect; C2–C6 concern comparison completeness, provenance, and explicitly required documentation/measurement work. These warrant bounded corrections, not another detector redesign or parameter search.

Reviewed the live dirty tree at `aaf231a655a22ad1e4698a6fea25199f373c9784`, the originating plan and audit, both checkpoint reviews, changed scientific code, new evaluation scripts/tests, and generated evidence. No implementation or existing evidence was edited during this review. Only this review and its reproduction script were added.

## C1 — P1: post-gap return to an equivalent low is excluded from support

**Location:** `hydroseason/_trough_refinement.py:650–666`, and the first-post-gap check at `:673–715`.

The new guard rejects post-gap values materially **below** the fitted pre-gap low. The subsequent overlap check examines only the **first** post-gap value. A later return to the same low therefore bypasses both checks: the function labels the gap as recovery and returns pre-gap-only support, despite directly observed equivalent low evidence after the gap.

Reproduction uses the frozen `(1.345, 0.05, 1.5)` policy, default measurement tolerance, 100 valid pixels in each observed month, and January–September percentages:

```text
90, 60, 30, 10, missing, 11, 10, 30, 80
```

Output: `provisional / recovery_crosses_gap`, boundary April, support **April only**, scale 1 pp. July is an observed return to exactly 10%. Fill May with the same low value, changing nothing else, and the full fit retains **April–July** support. Thus removing an observation collapses support and excludes an observed equivalent later low. `provisional` prevents a confirmed-recovery claim, but does not repair the unsupported singleton timing set.

A separate percentage-only reproduction with explicit 1 pp measurement tolerance and July 9.8% also returns April-only support; July 9.6% correctly triggers `gap_before_low_state`. The defect is within the intended equivalence tolerance, not an extreme floating-point case.

**Bounded correction:** before accepting `recovery_crosses_gap`, examine the whole post-gap segment for a return to the pre-gap low/equivalence band. Conservatively abstain when the assumption that the low state is entirely pre-gap fails. Preserve the existing true-after-low recovery control. Add an exact-return and a within-tolerance-return regression, then regenerate affected evidence. No threshold retuning is needed.

## C2 — P2: per-cycle diff drops real recovery changes

**Location:** `scripts/evaluate_final_pipeline.py:243–249`.

`_DIFF_VALUE_COLUMNS` contains recovery, raw trough, refinement, and condition fields, but those fields do not trigger row emission. They are copied only after a smaller set of counters has already found a change. Recovery-only changes therefore produce an empty diff and all-zero change counters.

This occurs in the delivered `old_refinement_vs_corrected_refinement` evidence:

| Catchment | hy_year | Before recovery | After recovery |
|---|---:|---|---|
| Daly | 2006 | 2007-01-01 | null |
| Daly | 2014 | 2015-01-01 | null |
| Daly | 2017 | 2018-01-01 | null |
| Daly | 2022 | 2023-01-01 | null |
| Fitzroy | 2013 | 2013-12-01 | null |

All five rows are absent from that comparison in `comparisons/cycles.csv`. These are directly relevant corrections to unsupported recovery evidence, so the handoff's claim that this file answers what changed is incomplete.

**Bounded correction:** compare every promised field using missing-value-aware equality and emit a row whenever any differs. Preserve the existing separate structural counters. Add a recovery-only regression and regenerate comparison CSVs/index summaries as applicable.

## C3 — P2: source identity does not cover the new evaluation code

**Locations:** `scripts/build_final_review.py:709–728`; `scripts/evaluate_final_pipeline.py:432–451`; handoff §1.

The saved tracked-patch hash matches the live tree:

```text
6751cf9e46bc58cc09c16ca5a0e3854893a4013b9e4886ee963e7424635e958d
```

However, `git diff HEAD` excludes untracked files, including both new evaluation scripts and their tests. The manifest records their names in porcelain status, but no content hashes or source snapshot. The plan explicitly required source-file hashes. Consequently, matching this patch hash does not establish the handoff's claimed exact source identity or reproduce the original baseline source. No archived dirty patch is recorded by the runner either; a hash is not the diff itself.

The separate pipeline fingerprint also hashes selected evaluator functions rather than its complete evaluator/dependencies. `_split_wrong_cycle`, its threshold value, and geometry-corpus generation helpers are omitted. In a read-only in-memory probe, changing `_GEOMETRY_MAX_MATCH_MONTHS` from 6 to 0 changes scoring of a one-month error from accuracy to wrong-cycle while leaving the fingerprint unchanged. A source edit inside the omitted split helper is likewise outside the selected-function list.

**Bounded correction:** archive/hash the actual relevant source files, including new files, and retain a reproducible dirty snapshot. Hash the whole evaluator plus its actual corpus/scoring dependencies. Bind generation manifests to their source snapshots rather than treating `finalize`'s live-tree stamp as proof of when reports were generated. Historical baseline provenance that cannot be recovered must be labelled unavailable, not retrospectively reconstructed as certain.

Current component and pipeline hashes do match their published values; this finding concerns incomplete identity coverage, not evidence that current numerical results were fabricated or changed.

## C4 — P2: required briefing corrections were omitted

**Location:** `docs/superpowers/audit_briefing.md:62–69`, `:90–96`, `:172`; plan Task 4, second checkbox.

The briefing still defines extent using `n_aoi` rather than `n_valid`, describes boundary noise using the event AR(1) estimator, calls Kuiper's Monte Carlo p-value exact, describes `annual_shape_match` as matching a typical annual profile, and gives the low-spell threshold a plus sign instead of a minus sign.

These were specifically named deliverables, not optional research extensions. Updating two `_regime.py` strings and the candidate migration note does not complete them. The handoff's “no deviations” statement is therefore inaccurate.

**Bounded correction:** complete the planned explanatory edits, preserving unrelated user work, or explicitly record the unfinished deliverable. Preserve the dated audit as a historical record. No numerical change is required.

## C5 — P2: handoff comparison label misattributes changes to this pass

**Location:** `handoff-for-codex.md:317–339`.

The §6 table labels boundary shifts as old-to-corrected refinement, but contains current-default-to-corrected numbers. It also assigns the 13/7/8 quality downgrades to corrected versus pre-fix confidence in the following paragraph. The actual old-refinement comparison has **zero complete-to-partial downgrades** in all three seasonal catchments.

Correct old-refinement-to-corrected values, read from `comparisons/catchments.csv`:

| Catchment | Boundary shifts | Wider / narrower | Quality upgrades / downgrades |
|---|---:|---|---|
| Daly | 3 | 3 / 0 | 0 / 0 |
| Fitzroy | 3 | 3 / 0 | 0 / 0 |
| Gilbert | 2 | 5 / 0 | 0 / 0 |

The existing 4/3/2 shift and 13/7/8 downgrade counts belong to enabling corrected refinement versus the current default. The later width explanation does not correct the earlier mislabelled table or quality attribution.

**Bounded correction:** label the table explicitly as current default versus corrected refinement and correct its explanatory paragraph, or show separate tables for both comparisons. A worked example is optional; correct labels are necessary.

## C6 — P2: required all-case abstention measure is still missing

**Location:** `hydroseason/_trough_refinement_calibration.py:249–253`, `:284–285`; published component metrics and migration evidence table; plan Task 3.

`coverage` is applied predictions on **resolvable truth only**, divided by resolvable truth count. `abstention_rate = 1 - coverage` is therefore also resolvable-truth-only, although the documentation labels it simply “Abstention rate.” Task 3 explicitly required keeping resolvable-truth abstention and all-case abstention separate.

For validation, the shown 0.076903 is **294/3823 resolvable spans**; the corpus has 5000 spans, including 1177 unresolvable spans. No separate all-case numerator/denominator is emitted. Calibration analogously reports 294/3824. These values are valid conditional measurements but do not fulfil the specified all-case reporting requirement.

**Bounded correction:** name the conditional metrics and their denominators explicitly; additionally compute all-case applied/abstained counts and rates from all cache rows. Retain existing frozen gate meaning and thresholds. Do not infer all-case abstention from the current summary alone.

## Verified evidence and limits

- **211 focused tests passed**, 10 warnings, 216.38 seconds. Command:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_trough_refinement.py tests/test_trough_refinement_calibration.py tests/test_final_pipeline.py tests/test_final_review.py tests/test_dynamic_year.py tests/test_report_export.py tests/test_catchment_analysis.py tests/test_release_metadata.py -q --disable-warnings
  ```

- Independently reran both reported full-suite failures; both still fail with the reported assertions. The package-surface paths remain unmodified; the recurrence documentation failure concerns excluded pre-existing work. This review did not rerun the entire 1594-test suite, coverage campaign, or both 5000-seed calibration partitions.
- All five before/default versus after/default directories have byte-identical public reports and shared outputs. The three seasonal full annual CSVs differ only by the added `trough_loss_basis` diagnostic column; shared annual columns compare equal. Both event-route annual CSVs are byte-identical too. This supports preservation on these five inputs, not an unrestricted proof for every caller.
- Component overlap and containment use different, correctly oriented interval comparisons. Integration-only component fields and their gate statuses remain JSON null; the three unmeasured structural claims were not silently restored to zero in the active component artifacts. Dated component copies exactly match bundle copies. The frozen tuple remains unchanged and unpromoted.
- Current component fingerprint is `4d745ac70783ff8fe22bf6d2d3fa2a43e1126cf30255e4dd4827bb86a17a5041`; pipeline fingerprint is `23a2e070838cc6d21830fc6ab205b0a0a4c14f773f6dbd9e7f4e3e461bf6086c`. Both match stored artifacts, subject to C3.
- Paired-cycle acceptance/rollback remains in place, and focused dynamic tests passed. Delivered comparisons report no changed peaks, newly uncomputable cycles, or duplicate/nonmonotonic boundaries in the evaluated seasonal cases. C1 is a timing-support defect, not a demonstrated violation of those structural counters.
- The integer-to-float cast is exact for valid integer percentages in `[0,100]`. No substantive integer-input regression was demonstrated; missing-value/dtype representation changes are expected. This does not claim arbitrary exotic numeric dtypes are covered.
- Browser setup was attempted using the browser skill. Runtime returned `No browser is available`; documented discovery returned `[]`. Interactive/visual report verification remains **unperformed**. User manual feedback remains pending.

Reproduce C1–C3 from the repository root:

```powershell
.\.venv\Scripts\python.exe case_studies/results/final-review-2026-09-08/reviews/codex-final-probes.py
```

The targeted next step is to correct these demonstrated defects and incomplete deliverables, regenerate affected evidence, and recheck changed areas. Preserve the frozen policy, baseline artifacts, candidate-only status, and unrelated user work.
