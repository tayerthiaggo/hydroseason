# Final scientific hardening — handoff for Codex review

This document summarizes a completed, bounded implementation pass so Codex can review it
against the originating audit and plan without relying on an implementer's narrative alone.
The source diff, tests, and generated comparisons are the evidence; this file is a guide to
them, not a substitute for reading them.

- **Audit:** [`docs/audits/2026-09-08-scientific-audit.md`](../../../docs/audits/2026-09-08-scientific-audit.md)
- **Plan:** [`docs/superpowers/plans/2026-09-08-final-scientific-hardening.md`](../../../docs/superpowers/plans/2026-09-08-final-scientific-hardening.md)
  (this file is local/gitignored process material, not tracked in the repository)
- **Input manifest:** [`case_studies/data/manifest.json`](../../data/manifest.json)
- **This bundle's manifest:** [`manifest.json`](manifest.json)
- **Five-catchment index:** [`index.html`](index.html)
- **Smoke-case index:** [`smoke/index.html`](smoke/index.html)

---

## 1. Scope and source identity

- **Base commit:** `aaf231a655a22ad1e4698a6fea25199f373c9784` (branch `development`). This is
  also the audit's own reviewed commit. **No commits were made during this pass** — every
  change below is an uncommitted working-tree edit on top of this commit.
- **Working tree is dirty and is the authoritative source.** `git status --short` currently
  shows modified tracked files and several new untracked files (full list in
  `manifest.json:finalize_time_source.porcelain_status`). `git diff HEAD` never touches
  untracked files, so a patch hash alone cannot establish identity for new files — new
  evaluation scripts and their tests included (Codex final review, finding C3). The manifest
  now archives the actual content, not only a hash, of every untracked `*.py` source file
  (`manifest.json:finalize_time_source.untracked_python_sources` /
  `...untracked_python_source_hashes`), and separates three distinct source snapshots instead
  of conflating them: `before_source` and `after_source` are each stage's own capture at the
  moment it generated its numbers; `finalize_time_source` is only a stamp of the tree when this
  top-level manifest was last (re)written (typically last, by `finalize`, possibly after further
  edits) — it is not proof of what generated the before/after numbers, and should not be read as
  such. This bundle's current `manifest.json:finalize_time_source.dirty_patch_hash` is
  `259228524716cc115c55a422d5a76bdef7bfe927e7bd60be198272f39b94ed07`, also carried in full as
  `finalize_time_source.tracked_diff_patch`. (`after_source.dirty_patch_hash`,
  `7be3e3851a86c0552df0d756866e5c0c6eda7ba710e29bc986253061861c871e`, is the earlier
  after-stage capture — a distinct snapshot, not this one; see below for why the two differ.) A
  commit ID alone does **not** reproduce this working tree; the archived diff and
  untracked-file contents are the record.
- **`before_source` has no archived patch or new-file contents, only revision/branch/dirty
  flag/patch hash/porcelain status.** Its historical baseline tree cannot be reconstructed from
  this manifest — treat it as a fixed reference point, not a fully archived snapshot like
  `after_source`/`finalize_time_source`. This gap is deliberate and is not backfilled (Codex
  fix-review C3, 2026-09-09): regenerating the historical baseline after the fact would not
  prove anything about what actually produced the before-numbers.
- **Pre-existing, unrelated uncommitted work was present before this pass started** and is
  explicitly out of scope — untouched by any change described here:
  `hydroseason/_recurrence_calibration.py`, `hydroseason/_scientific_defaults.py`,
  `scripts/audit_recurrence_impact.py`, `scripts/build_recurrence_identifiability_cohort.py`,
  `docs/decision-policy.md`, `docs/migrations/0.2.0-timing-identifiability.md`, `CHANGELOG.md`
  (one unrelated pre-existing edit; this pass added its own separate `[Unreleased]` entries
  above it), and `docs/superpowers/specs/2026-09-06-two-pass-trough-refinement-design.md`. Both
  Opus reviews independently confirmed these files as pre-existing and excluded them from
  review.
- **Two Opus reviews were performed in this same pass**, both by a fresh, independent Opus
  session with no access to the implementer's conversation — only the diff, the audit, the
  plan, and the live repository:
  - Checkpoint 1 (Tasks 2–3, mathematical/validation review):
    [`reviews/opus-math-validation.md`](reviews/opus-math-validation.md)
  - Checkpoint 2 (Tasks 4–6, final integration review):
    [`reviews/opus-final.md`](reviews/opus-final.md)
- **A subsequent, separate Codex review** (also fresh, diff/audit/plan/live-repository only) of
  this same working tree found six further substantiated findings (C1–C6), all now fixed and
  verified — see [`reviews/codex-final.md`](reviews/codex-final.md) for the original review and
  §9 / [`reviews/fixes-for-codex-astra-6.md`](reviews/fixes-for-codex-astra-6.md) for the fixes.

---

## 2. Changes by task and deviations

**Task 1 — Freeze current behaviour, establish the real reporting path.** Added
`trough_refinement_policy: TroughRefinementPolicy | None = None` as a trailing keyword-only
argument to `analyze_catchment` (`hydroseason/_catchment.py`), forwarded only to the real
`DynamicHydroYearConfig` construction on the per-year-detection path — an event-route case
never constructs a `DynamicHydroYearConfig` at all (test-enforced:
`test_event_route_never_constructs_dynamic_detector_config`). Built
`scripts/build_final_review.py` (new) with SHA-256-verified input loading, a baseline
(`before/`) capture that refuses to overwrite itself unless input hashes still match, and
`run_cases`/`generate_catchment_report` reuse (no second route implementation). Captured the
`before/` baseline **before** any Task 2/3 code changes, as required. No deviations.

**Task 2 — Correct refinement gaps, scale units, and support semantics.**
`hydroseason/_trough_refinement.py`:
- Loss-unit fix (audit 6.1): at zero scale, endpoint plausibility now uses exact-minimum
  support up to a magnitude-relative numerical tolerance instead of applying the dimensionless
  `profile_loss_cutoff` to a raw L1 loss. New `TroughRefinementResult.loss_basis` field
  (`standardized_huber` / `exact_l1` / `unavailable`) records which regime applied.
- Measurement floor (audit 6.1): `_local_scale` now takes
  `max(residual_estimator, pixel_floor, measurement_tolerance_pp)` unconditionally, not only
  when the residual estimator is exactly zero. New keyword-only `measurement_tolerance_pp`
  threaded from `config.measurement_tolerance_pct` through all internal fit calls.
- Support-set untruncation (audit 6.3): `boundary` (operational date) still selects the latest
  exact optimum; `boundary_candidates` now retains the **full** admissible cluster instead of
  being truncated to that optimum. Interval-width/breadth classification uses the full set.
- Calendar-gap fix (audit 6.4): `_refine_selected_span` reindexes onto the complete monthly
  calendar at span entry; `_quality_sensitivity`'s removal scenarios mark a month
  `extent_pct=NaN, observed_fraction=0.0, quality_state="missing", candidate_usable=False`
  **in place** (`_masked_missing`) instead of `frame.drop`-ing the row, which previously closed
  the calendar gap and made neighbouring months look falsely consecutive.
- `_combine_sensitivity_results` bug (found during implementation, not in the audit's own
  list): fixed to report a real scenario's own selected operational boundary rather than the
  union support-set's last date, which differ once support-set untruncation is in effect.
- **Opus checkpoint-1 finding, fixed in this pass:** `_refine_gap_after_low_state` had no
  check that the low state actually precedes a data gap — it always fitted the pre-gap segment
  only. Added an applicability guard: if any fully-observed post-gap value sits materially
  below the pre-gap fitted low level, the function now abstains
  (`reason="gap_before_low_state"`) instead of answering from the wrong limb. This is a
  pre-existing defect that Task 2's own calendar-gap fix promoted from dormant to load-bearing
  (see review for the full mechanism and a demonstrated counterexample). Regression test:
  `test_gap_before_the_true_low_state_does_not_answer_from_the_recession_limb`.
- **Opus checkpoint-1 finding, fixed in this pass:** the `.at[]`-based per-cell assignment
  introduced to work around a pandas 3.0.3 dtype-coercion crash in
  `hydroseason/_dynamic_year.py:_apply_trough_refinement` was widening *every* Timestamp-bound
  column to `object` dtype, including already-`datetime64` columns that never had the crash —
  this corrupted rendered dates (`1990-07-01` → `1990-07-01T00:00:00.000`) whenever refinement
  was accepted. Narrowed the guard to widen only columns that cannot already hold a Timestamp.
- **Genuine no-op fixed for a different reason:** `hydroseason/_state_input.py`'s
  `prepare_monthly_extent` now forces `extent_pct`/`invalid_pct` to `float64` unconditionally.
  Without this, an all-integer-percentage input (which never occurs in real DEA data, but does
  in the Task 5 synthetic smoke fixtures) hit the same pandas 3.0.3 dtype-coercion crash the
  moment a refinement scenario tried to write a fractional or NaN value into it. Provably inert
  on all-float input (bit-identical, independently verified by Opus checkpoint 2).

**Task 3 — Replace misleading validation claims with measured comparisons.**
`hydroseason/_trough_refinement_calibration.py`: renamed `boundary_set_inclusion` →
`boundary_set_overlap` (same interval-overlap math; the old name overclaimed full inclusion),
added a genuinely new `truth_set_containment` metric (predicted bounds enclose both truth
endpoints — different formula, reported separately). Renamed the synthetic truth-derived
comparator throughout (`hydroseason/_synthetic.py`'s `TroughRefinementSyntheticRecord`,
`_cache_row`, score fields, report keys) from `pass1_boundary`/`pass1_*` to
`synthetic_reference_boundary`/`synthetic_reference_*` — it was never real pass-1 output.
`peak_changes`/`duplicate_or_nonmonotonic`/`new_uncomputable` are now `None`
("not evaluated in span harness") rather than hardcoded `0`/`False`: this per-span component
harness structurally never reassembles adjacent cycles, so it cannot measure these
integration-level properties, and reporting a constant `0` as if measured was the audit's
6.6 finding. Removed these from `_admissible()`'s gating (gating on an always-constant value
is tautological); the genuinely measured `wrong_cycle` gate remains. Bumped the candidate
scope/version to `trough_refinement_candidate_0_2`; extended `trough_refinement_fingerprint`
to additionally hash `TIMING_IDENTIFIABILITY_DEFAULTS`, `_month_delta`, `_timing_status`
(previously outside its hashed scope despite being load-bearing). Added `--fixed-trough-policy`
to `scripts/run_calibration.py`: evaluates only the frozen tuple, never calls
`select_trough_refinement_policy`, sets `selection_counts={"reselection": 0}`.

Built `scripts/evaluate_final_pipeline.py` (new): a genuinely new full-pipeline comparator that
runs `detect_dynamic_hydrological_years` twice (refinement off, then the frozen candidate on)
on complete synthetic 12-year records with **no supplied truth peaks** — the detector finds its
own peaks, same as production. `compare_cycle_tables` measures changed peaks, boundary shift,
interval-width/status changes (with a widened/narrowed split), newly-uncomputable/computable
cycles, added/dropped rows, and duplicate/non-monotonic boundary sequences, via outer join on
`hy_year` with NaN-aware equality. `evaluate_records` matches singleton predictions to truth by
year and reports median/p90/mean-absolute-error/signed-bias with explicit `n` denominators,
`None` for an empty population.

**Task 4 — Align scientific explanations, preserve policy compatibility.**
`hydroseason/_regime.py`: replaced two copy strings that described a non-significant Kuiper
p-value as if it proved uniform timing ("no reproducible annual cycle… any value would reflect
noise") with "annual timing was not established by the current evidence" framing that
distinguishes genuine absence of a cycle from insufficient evidence to establish one. The
`aseasonal` enum, routing thresholds, and returned regime values are unchanged. `.gitignore`:
replaced the single `docs/superpowers/` blanket-ignore with the plan's exact narrow-exception
block, resolving the known tracked/ignored metadata test failure without untracking or
deleting anything (`test_no_gitignored_or_process_files_are_tracked_in_git` now passes).
Published dated component copies at `docs/calibration/2026-09-08-trough-refinement-{calibration,validation}.json`
(old 2026-09-06 dated files kept as historical record, untouched). Rewrote
`docs/migrations/trough-refinement-candidate.md` with the actual measured numbers from this
pass (previously stale, claiming "both pass all ten frozen gates" — false; see Opus
checkpoint-1 finding F11).
- **Opus checkpoint-1 finding, fixed in this pass:** `TroughRefinementPolicy.version`'s
  dataclass default still said `trough_refinement_candidate_0_1` after the scope bump, so any
  caller constructing a policy without an explicit version silently mislabeled corrected `0_2`
  behaviour. Bumped the default to `0_2`; pinned `scripts/build_final_review.py`'s
  `CURRENT_CANDIDATE_POLICY` (used only to label the frozen pre-fix baseline) to an explicit
  `version="trough_refinement_candidate_0_1"` so its meaning no longer depends on the default.

**Task 5 — Five real-catchment reports and nine smoke cases.** Completed
`scripts/build_final_review.py`: `make_smoke_frames` (the plan's nine literal deterministic
15-year cases), `run_smoke_cases`, `build_comparisons` (three-way matrix: old-default-vs-new-default,
old-refinement-vs-corrected-refinement, current-default-vs-corrected-refinement — never only
against previously stored HTML), `write_review_notes`, and a fully rebuilt `build_index`
linking every artifact with the required "development review; not blinded validation" note and
"unchanged" (never manufactured-improvement) language for controls. All five real catchments'
`before/{default,refinement}` and `after/{default,refinement}` variants and all nine smoke
cases were generated for real against the frozen inputs — not simulated. No deviations from
the plan's smoke-case specification.

**Task 6 — Verification and Opus checkpoint 2.** Ran the full required check sequence (below).
Opus checkpoint 2 found one blocking finding (a stale provenance fingerprint — see §4) and six
optional findings; all were addressed in this same pass (§4 has the full table). Re-ran the
full non-network/non-performance suite with coverage a final time after all checkpoint-2 fixes
so the published `pytest.xml`/`coverage.txt` describe the actual final source state, not an
intermediate one — this was a direct lesson from the fingerprint-staleness finding itself.

**Task 7 (this document).** Written after both checkpoints closed and every actionable finding
was resolved or explicitly deferred with recorded rationale.

**Deviations from the plan:** none identified. Two defects were found and fixed that the audit
did not itself name (`_combine_sensitivity_results`'s boundary-selection bug, and two pandas
3.0.3 dtype-coercion crashes) — these are implementation-level correctness fixes uncovered
while doing the audit-specified work, not scope expansion; both are documented above with their
mechanism and are covered by regression tests.

---

## 3. Scientific behaviour and compatibility

- **Refinement remains strictly opt-in.** `analyze_catchment(..., trough_refinement_policy=None)`
  (the default) is **measured byte-identical** to the pre-pass baseline across all five real
  catchments — see §6. `_apply_trough_refinement` returns pass-1 rows unchanged when the policy
  is `None`.
- **Fixed refinement tuple, no retuning.** `huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5`
  appears unchanged in every generated artifact. No grid search or parameter selection ran
  against this pass's own results at any point; `--fixed-trough-policy` structurally cannot call
  the selector.
- **Gap treatment changed:** a data gap is now always represented as an explicit unobserved
  calendar month, never as a silently shortened, falsely-consecutive record. A gap whose
  low state plausibly continues past it now correctly abstains rather than answering from the
  wrong segment.
- **Loss basis changed:** `exact_l1` (zero scale) now uses exact-minimum support up to
  numerical tolerance instead of a dimensionless cutoff misapplied to a raw pp loss; this
  changes which dates are admissible only when scale is genuinely zero, and is now invariant
  to how the input data happens to be scaled (verified: identical candidate sets at 1×, 0.01×,
  down to 1e-7×; see Opus checkpoint-1 finding F4 for the noted 1e-9× edge, deferred as
  physically irrelevant to `[0,100]` percentage data).
- **Support intervals vs. operational dates are now genuinely independent.** An operational
  boundary can sit strictly inside its own support interval; `trough_boundary_date` in the
  compact export is now unconditionally the operational date, never silently substituted with
  the interval's end (confirmed measured: 16 of 152 sampled interval/broad rows previously
  reported a `trough_boundary_date` that did not equal the actual cycle-segmentation date).
- **Validation denominators changed meaning, not just labels**, where the audit found them
  misleading (§2, Task 3) — `boundary_set_overlap` vs `truth_set_containment` are genuinely
  different questions; the synthetic comparator is now honestly labelled as synthetic;
  integration-only metrics are `null` rather than a misleading `0`.
- **Corrected uncertainty legitimately widened in places and did not uniformly "improve" any
  number** — see §6's honest, mixed widened/narrowed and upgraded/downgraded counts. No
  threshold was changed and no support set was narrowed anywhere in this pass to recover a
  previously-published number; the `boundary_set_overlap = 0.923` result (below the informal
  0.95 mark this candidate previously appeared to clear) is reported as-is.

---

## 4. Opus findings and resolutions

Both reviews ran independently, with no access to this document or to each other; each
verified the prior state (not the implementer's claims) directly against source and generated
artifacts. Full evidence and reasoning for every row is in the two review files linked above —
this table is a locator, not a replacement.

| finding_id | severity | disposition | fix_or_rationale | verification_reference |
|---|---|---|---|---|
| F1 | Blocking | fixed | `_refine_gap_after_low_state` applicability guard; abstains instead of answering from the wrong (pre-gap) segment when the low state continues past a gap | `hydroseason/_trough_refinement.py:642–670`; `tests/test_trough_refinement.py::test_gap_before_the_true_low_state_does_not_answer_from_the_recession_limb`; re-verified by Opus checkpoint 2 with an independent control case |
| F2 | Blocking | fixed | Narrowed the dtype-widening guard in `_apply_trough_refinement` to skip columns that already hold `datetime64`/`object` | `hydroseason/_dynamic_year.py:1354–1361`; Opus checkpoint 2 independently confirmed via sha256-identical rendered HTML across the code change |
| F3 | Optional | fixed | Corrected a test docstring to name the actual guard/reason (`gap_start<=1`, `gap_overlaps_low_state`) instead of a wrong one | `tests/test_trough_refinement.py:347–361` |
| F4 | Optional | deferred_optional | Zero-scale tolerance is not perfectly scale-invariant below a 1e-9× data-scale factor; practically irrelevant to `extent_pct ∈ [0,100]`. Deferred to avoid touching three interacting tolerance sites for a case that cannot occur on real data | recorded rationale in `reviews/opus-math-validation.md` §F4; not re-raised at checkpoint 2 |
| F5 | Optional | fixed | Bumped `TroughRefinementPolicy.version`'s dataclass default to `0_2`; pinned the baseline-labelling policy in `build_final_review.py` explicitly | `hydroseason/_trough_refinement.py`; `scripts/build_final_review.py:73–82` |
| F6 | Optional | fixed | `evaluate_records` now sums `diff_*` counters per partition into `structural_diff_totals` in `pipeline.json` | `scripts/evaluate_final_pipeline.py`; `validation/pipeline.json` |
| F7 | Optional | fixed | Added `_split_wrong_cycle` (established `_GEOMETRY_MAX_MATCH_MONTHS` convention); wrong-cycle year-misattribution events excluded from the accuracy-distance pool and reported separately | `scripts/evaluate_final_pipeline.py:28,269–284`; `validation/pipeline.json` (`p90_abs_error_months` corrected 5.0 → 0.0 once excluded) |
| F8 | Optional | fixed | Corrected a docstring/code mismatch ("computable" removed; the function's actual, tested contract is "non-null boundary") | `scripts/evaluate_final_pipeline.py:82–86` |
| F9 | Optional | fixed | Migration doc now states containment and overlap coincide on this synthetic corpus, and why | `docs/migrations/trough-refinement-candidate.md` |
| F10 | Optional | fixed | Renamed the inverted-sounding `recovers` variable to `post_value_still_at_low_level`; no behaviour change | `hydroseason/_trough_refinement.py:679,685–686` |
| F11 | Optional | fixed | Removed the stale "both pass all ten frozen gates" claim; migration doc now states measured results including the failing gate, explicitly, without retuning | `docs/migrations/trough-refinement-candidate.md` |
| G1 | Blocking | fixed | Two legitimate late edits (F5, and the `_state_input` float64 fix) fell inside `trough_refinement_fingerprint`'s hashed dependency closure and invalidated six published artifacts. Re-ran both frozen 5,000-seed partitions plus the pipeline evaluator against final source (not a hand-edited hash); numbers unchanged, confirming it was a provenance defect, not a numerical one. Added a missing staleness guard | `hydroseason/_trough_refinement_defaults.py`; `validation/component-{calibration,validation}.json`; `docs/calibration/2026-09-08-*.json`; `docs/migrations/trough-refinement-candidate.md`; new test `tests/test_release_metadata.py::test_trough_refinement_report_is_not_stale` |
| G2 | Optional | fixed | `compare_cycle_tables` now emits `_before`/`_after` value pairs for every plan-named field, not just a flag string; also fixed a real bug found while implementing this (the emitting `pd.DataFrame(...)` call was silently dropping every extra column) | `scripts/evaluate_final_pipeline.py`; `comparisons/cycles.csv` (up to 40 columns) |
| G3 | Optional | fixed | Fixed `run_cases`' relative-path computation (was silently falling back to absolute paths whenever `--output-dir` was passed as a relative CLI argument, and used the wrong directory depth for the five-catchment case); healed the ten already-frozen `before/manifest.json` path strings in place (no scientific content touched) | `scripts/build_final_review.py`; 51/51 bundle-relative links verified resolving |
| G4 | Optional | partially fixed | Added widened/narrowed interval split, a wet-events delta column, and a live software-test-status banner to the index. **Not done:** per-changed-year anchor links from the index into the report/diff — a genuine scope decision (would need per-year HTML anchors added to `generate_catchment_report`, out of this pass), not an oversight; `comparisons/cycles.csv` (widened by G2) already answers "what changed" one click away | `scripts/build_final_review.py`; `index.html` |
| G5 | Optional | fixed | Added `run_audit_probes()` (subprocess, parses JSON, never fails the build if unavailable) and a labelled probe-outcomes table to `smoke/index.html`, explicit that these are seven-month component spans, not full-record reports | `scripts/build_final_review.py`; `smoke/index.html` |
| G6 | Optional | fixed | Added an explicit `attr_list` anchor id to the target heading in `docs/report-columns.md`, matching the existing link exactly | `docs/report-columns.md`; `validation/docs-build.txt` (dead-anchor INFO line gone) |
| G7 | Optional | fixed | Captured `coverage report --show-missing` to `validation/coverage.txt` from the same run that wrote `pytest.xml`, so the 89% figure survives independently of the transient `.coverage` data file | `validation/coverage.txt` |

No finding from either review was rejected or left unresolved.

---

## 5. Verification results and limits

Commands run (from repository root, `.venv\Scripts\python.exe`, Python 3.12.13, numpy 2.4.6,
pandas 3.0.3, scipy 1.18.1):

```powershell
.venv\Scripts\python.exe -m ruff check hydroseason tests scripts
.venv\Scripts\python.exe -m pytest -q -m "not experimental and not network and not performance" `
  --cov=hydroseason --cov-report=term-missing --cov-fail-under=80 `
  --junitxml=case_studies/results/final-review-2026-09-08/validation/pytest.xml
.venv\Scripts\python.exe -m mkdocs build --strict --site-dir .tmp-final-review-docs
.venv\Scripts\python.exe scripts/build_final_review.py --stage finalize --output-dir case_studies/results/final-review-2026-09-08
```

**Test results** (`validation/pytest.xml`, `validation/test-results.html`): **1594 tests total,
1590 passed, 2 failed, 0 errors, 2 skipped.** Software test status is published as **"NOT A
PASS"** — not hidden. The two failures are pre-existing and unrelated to this pass, confirmed
independently by both this implementer and Opus checkpoint 2:

- `tests/test_decision_policy_docs.py::test_recurrence_identifiability_promotion_docs` — fails
  against `docs/migrations/0.2.0-timing-identifiability.md`, one of the pre-existing uncommitted
  files listed in §1, not touched by this pass.
- `tests/test_package_surface.py::test_package_import_exposes_only_migration_safe_surface` —
  fails identically against `hydroseason/__init__.py` and its own test file, both confirmed via
  `git status --short` to carry **zero** changes from this pass (last touched in commit
  `3dadd29`, before the audit baseline).

**Coverage:** 89.46% (`validation/coverage.txt`), above the required 80% floor.

**Lint:** `validation/ruff.txt` — 10 pre-existing findings, all independently confirmed by Opus
checkpoint 2 to be unrelated to this diff (7 in `tests/test_timing_identifiability.py`,
untouched by this pass; 1 in `scripts/audit_recurrence_impact.py`, a pre-existing user edit;
2 in `tests/test_catchment_analysis.py:492`, confirmed identical to `HEAD` at that line). No
lint finding is attributable to this diff.

**Docs build:** `validation/docs-build.txt` — `mkdocs build --strict` exits 0.

**Not performed: interactive/visual browser verification.** The plan's Task 6 asks for opening
the index and all five primary reports in a real browser and interacting with a seasonal, an
event-based, and a gap smoke report. **That specific check was not performed** in this
non-interactive execution environment — this is stated explicitly per the plan's own
instruction ("If browser automation is unavailable, report that specific check as unperformed;
do not claim visual verification from file-size checks"). What **was** verified
programmatically, independently by both this implementer and Opus checkpoint 2: every report
is a complete, non-truncated self-contained document (1.28–1.50 MB), renders 5 `Plotly.newPlot`
chart blocks each, has zero external (`http(s)://`) resource references (fully offline), and
every internal link in the bundle (51 checked) resolves on disk. This is strong structural
evidence, not a substitute for actually opening a page.

---

## 6. Five-catchment before/after outcomes

All numbers below are read directly from `comparisons/catchments.csv` and
`comparisons/cycles.csv`, generated from the actual detector output on the five frozen real
inputs (`case_studies/data/manifest.json`, SHA-256-verified, identical before and after this
pass — see `manifest.json:before_input_hashes` / `after_input_hashes`).

**Default route (refinement off): byte-identical across this entire pass, for all five
catchments.** `old_default_vs_new_default` shows zero of every counter everywhere; independently
spot-checked by Opus checkpoint 2 via direct SHA-256 comparison of all 4 compact CSVs + 3
diagnostic CSVs + the rendered HTML, for all five catchments — identical except one
plan-sanctioned added diagnostic column (`trough_loss_basis`, all-null on the default route).

**Table A — old refinement (candidate `trough_refinement_candidate_0_1`) vs. corrected
refinement (this pass, `trough_refinement_candidate_0_2`).** Isolates what this pass's fixes
(Task 1–3; Codex final review C1–C6) changed relative to the prior refinement candidate.

| catchment | route (unchanged) | boundaries shifted | interval width: wider / narrower | newly uncomputable | quality upgraded / downgraded | duplicate/non-monotonic |
|---|---|---|---|---|---|---|
| daly_river_nt | per_year_detection | 3 | 3 / 0 | **0** | 0 / 0 | **0** |
| fitzroy_river_wa | per_year_detection | 3 | 3 / 0 | **0** | 0 / 0 | **0** |
| gilbert_river_qld | per_year_detection | 2 | 5 / 0 | **0** | 0 / 0 | **0** |
| lachlan_river_nsw | event_characterisation | n/a — 0 hydrological years published | n/a | n/a | n/a | n/a |
| moonie_river_qld_nsw | event_characterisation | n/a — 0 hydrological years published | n/a | n/a | n/a | n/a |

**Table B — current default (no trough refinement) vs. corrected refinement.** Isolates what
enabling refinement at all changes relative to the ad hoc default interval; do not read this as
"what this pass changed" (that is Table A).

| catchment | route (unchanged) | boundaries shifted | interval width: wider / narrower | newly uncomputable | quality upgraded / downgraded | duplicate/non-monotonic |
|---|---|---|---|---|---|---|
| daly_river_nt | per_year_detection | 4 | 3 / 7 | **0** | 0 / 13 | **0** |
| fitzroy_river_wa | per_year_detection | 3 | 2 / 16 | **0** | 0 / 7 | **0** |
| gilbert_river_qld | per_year_detection | 2 | 1 / 14 | **0** | 0 / 8 | **0** |
| lachlan_river_nsw | event_characterisation | n/a — 0 hydrological years published | n/a | n/a | n/a | n/a |
| moonie_river_qld_nsw | event_characterisation | n/a — 0 hydrological years published | n/a | n/a | n/a | n/a |

**Structural safety holds everywhere refinement actually changed something:** zero peak
changes, zero newly-uncomputable cycles, zero duplicate/non-monotonic boundary sequences, in
every one of the three seasonal catchments' comparisons, in **both** tables above. The two
event-route catchments contribute vacuous zero cycle-level rows (no hydrological years exist to
compare) — do not read "five catchments, zero violations" without this caveat; the substantive
cycle-level evidence is the three seasonal catchments plus 2400 matched rows from the synthetic
pipeline evaluation (`validation/pipeline.json`: 1200 matched rows × 2 partitions, zero peak
changes, zero newly-uncomputable, zero duplicate/non-monotonic in both).

**Quality changes are honestly mixed, not uniformly positive, and the two comparisons disagree
sharply.** **Table A (old refinement → corrected refinement)** shows **zero quality changes at
all** in this sample (0 upgrades, 0 downgrades, all three catchments) — this pass's corrections
(C1–C6) did not, on these five real catchments, change which cycles the refinement candidate
was confident enough to call `complete`. **Table B (current default → corrected refinement)**
shows all measured quality changes moving `complete → partial` (13/7/8 downgrades, 0 upgrades)
— enabling trough refinement at all, versus the current no-refinement default, more often
reveals a boundary that cannot be as confidently confirmed as the default's ad hoc interval
claims, not the reverse. This is the expected, sanctioned direction per the plan's global
constraints ("corrected uncertainty may legitimately widen intervals or cause abstention"); it
is reported as measured, not framed as an improvement. Reading the Table B downgrade counts as
something this pass's fixes caused is the exact mislabelling a prior draft of this handoff made
(Codex final review, finding C5) — they are current-default-vs-corrected numbers, not
old-refinement-vs-corrected numbers.

**Interval width changed more often narrower than wider** in **Table B** (fitzroy 16
narrower / 2 wider; gilbert 14/1; daly 7/3) when comparing the corrected refinement against
the **current default** (which does no trough refinement at all and reports a different,
generally wider ad hoc interval). This is not directly comparable to **Table A**
(old refinement vs. corrected refinement), which showed only widening (3/3/5 changes, all
wider, 0 narrower) — the two tables answer different questions and are reported separately in
`comparisons/catchments.csv` (`old_refinement_vs_corrected_refinement` vs.
`current_default_vs_corrected_refinement`); do not conflate them.

**Event counts:** unchanged for all five catchments between default and corrected refinement
(refinement only ever adjusts trough boundaries within already-detected cycles; it does not
touch event detection).

**Links:** [`index.html`](index.html) → "Five primary candidate reports" table; individual
reports at `after/refinement/<catchment>/` and `after/default/<catchment>/`; full diffs at
[`comparisons/cycles.csv`](comparisons/cycles.csv) and
[`comparisons/months.csv`](comparisons/months.csv).

---

## 7. Smoke outcomes and artifact links

All nine deterministic synthetic smoke cases (`scripts/build_final_review.py:make_smoke_frames`)
ran with the candidate policy enabled and produced real reports — see
[`smoke/index.html`](smoke/index.html).

| case | route | outcome |
|---|---|---|
| clean-seasonal | per_year_detection | ok |
| all-zero | event_characterisation | correctly publishes 0 hydrological years and 0 events/low-spells (flat record; not forced into seasonal processing) |
| constant-water | event_characterisation | same as all-zero |
| two-pulses | per_year_detection | ok |
| long-plateau | per_year_detection | ok |
| gap-at-low | per_year_detection | ok — the perturbed year does not claim a confirmed boundary through the missing month |
| gap-at-recovery | per_year_detection | ok — the perturbed year's `recovery_start_month` is null, not a fabricated observed recovery |
| low-quality | per_year_detection | ok (this case previously crashed on pandas 3.0.3 before the `_state_input` float64 fix; see §2) |
| late-trough-short-following | per_year_detection | ok — degrades to abstention rather than forcing a December boundary on the short following cycle |

**Direct audit-probe reproductions** (component-level seven-month spans, not full-record
reports — do not pass the public record-length gate; see `smoke/index.html`'s second table and
`docs/audits/2026-09-08-audit-probes.py`):

- Zero-scale candidate set is now **invariant to data scaling**: factor 1.0× and 0.01× both
  give `boundary_candidates=["2020-04-01"]` (the audit's original finding: these previously
  differed).
- Dropped-month scenario: `status=provisional`, `recovery_start_present=False` — a genuinely
  missing month is never silently treated as an observed recovery (the audit's original finding:
  this previously reported `status=confirmed` with a fabricated recovery date).

No unexpected outcome was found in any smoke case or probe reproduction.

---

## 8. Manual feedback and specific remaining questions

**Manual feedback pending.** The user has not yet reviewed the five real-catchment reports;
[`review-notes.md`](review-notes.md) is prepared with one blank row per catchment and specific
inspection prompts (wet-season split correctness, recovery timing, pulse-vs-new-year
misclassification, unsupported precision, surprising route/condition changes).

**Specific remaining questions for Codex:**

1. Does the resolution of Opus checkpoint 1's F1 (`gap_before_low_state` applicability guard)
   correctly generalize, or is there a plausible real-catchment configuration where the guard's
   "materially below the pre-gap fitted low level" comparison could itself be fooled (e.g. a
   very gradual, multi-month-long recession where no single post-gap value looks "materially"
   different from the pre-gap segment, yet the true low state still lies past the gap)?
2. `_state_input.py`'s new unconditional `.astype(float)` is provably inert on all real and
   synthetic-corpus inputs (both are already float64 by construction upstream). Is there a
   plausible caller path — outside this repository's own test/production surface — that
   supplies a genuinely integer-percentage `extent_pct` Series where this cast could have a
   substantive (not just dtype-representational) effect?
3. Is the `current_default_vs_corrected_refinement` vs. `old_refinement_vs_corrected_refinement`
   distinction in §6 (mixed narrower/wider vs. uniformly wider) presented clearly enough, or
   does it need a more explicit worked example before the user's manual review?
4. Are there other integration-level properties (beyond peak changes, duplicate/non-monotonic
   boundaries, and newly-uncomputable cycles) that the component calibration harness's `None`
   fields should also be checked don't quietly reappear as `0`/`False` somewhere else in the
   codebase or its generated documentation?

Please check: plan compliance, mathematical semantics of every changed formula, whether the
measured validation claims in `validation/*.json` and `docs/migrations/trough-refinement-candidate.md`
actually match their stated definitions, that defaults are genuinely unchanged (§6), paired-cycle
safety (§6), and whether the artifacts linked from this document match the reviewed code state
(§1's dirty-patch-hash). This is a bounded, bug-fix-and-honest-measurement pass, not an
invitation to a new general improvement audit — please flag scope concerns rather than expand
scope unilaterally.

**No further scientific changes should be made against this bundle without either concrete user
feedback on the reports (via `review-notes.md`) or a demonstrated defect found in this bounded
review.**

---

## 9. Codex final review (C1–C6): findings, fixes, and verification

A separate, bounded Codex review of this same working tree
([`reviews/codex-final.md`](reviews/codex-final.md)) found six substantiated findings (C1–C6)
and requested corrections, not a redesign. All six are now fixed, verified, and the affected
evidence in this bundle has been regenerated from the corrected source (not simulated — every
number below is a fresh run). A detailed fix report for Codex Astra 6 to audit is at
[`reviews/fixes-for-codex-astra-6.md`](reviews/fixes-for-codex-astra-6.md); this section is the
short version integrated into the handoff record.

| # | Finding | Fix | Verified |
|---|---|---|---|
| C1 | `_refine_gap_after_low_state` only checked the *first* post-gap value for a return to the pre-gap low; a *later* return (exact or within measurement tolerance) was silently excluded from support, so `recovery_crosses_gap` could commit to an unsupported pre-gap-only boundary/support set. Directly answers open question 1 above: yes, a real gap in this exact shape was answered from the wrong limb. | `hydroseason/_trough_refinement.py`: the whole post-gap segment is now checked for an equivalence-band return, not just the first value; a later-only return now abstains (`unresolved` / `post_gap_return_to_low_state`) instead of asserting a narrowed support set. | Codex's exact repro (`reviews/codex-final-probes.py`) now abstains instead of returning April-only support. Two new regression tests (exact return, within-tolerance return). 5000-seed calibration + 5000-seed validation cohorts: numerically **byte-identical** to the pre-fix run except for new fields (C6) — this defect does not manifest in the synthetic corpus or the five real catchments; it is real but narrow. |
| C2 | `evaluate_final_pipeline.compare_cycle_tables` only emitted a diff row when a smaller, named subset of counters changed; a change confined to a promised-but-uncounted field (`recovery_start_month` was the demonstrated case) produced an empty diff and hid a real change. | Added a whole-field-set equality check (`_DIFF_VALUE_COLUMNS` + boundary column, missing-aware) that emits the row whenever *any* promised field differs, tagged `value_changed`. Named structural counters are untouched, as required. | Codex's exact repro (5 Daly/Fitzroy rows previously silently dropped) now shows `value_changed` with correct before/after values in the regenerated `comparisons/cycles.csv`. |
| C3 | Source-identity claims didn't cover new/untracked files: `git diff HEAD` never sees untracked files (the new evaluation scripts/tests); the separate pipeline fingerprint hashed a hand-picked function list, not the whole evaluator or its real corpus/scoring dependencies (`_calibration._GEOMETRY_MAX_MATCH_MONTHS`, `_synthetic`) — a runtime probe showed it missing a real scoring-affecting change. | `build_final_review._git_info` now archives the full content (not just a hash) of every untracked `*.py` file, and the bundle manifest surfaces `before_source`/`after_source`/`finalize_time_source` as three distinct snapshots instead of one finalize-time stamp standing in for all of them (§1 above). `evaluate_final_pipeline._pipeline_manifest_hash` now hashes this module's own full source plus `_calibration`, `_synthetic`, and the other real dependency modules, plus the runtime value of `_GEOMETRY_MAX_MATCH_MONTHS`. | Codex's exact runtime-mutation probe now reports `same fingerprint: False`. `manifest.json:finalize_time_source.untracked_python_source_hashes` lists all four new files with content and hash. |
| C4 | `docs/superpowers/audit_briefing.md` still described: `extent_pct` denominated by `n_aoi` (actual: `n_valid`); boundary noise as AR(1)-corrected (actual: seasonal-median-removed MAD, no autocorrelation term); Kuiper's Monte Carlo p-value as "exact"; `annual_shape_match` as matching a computed "typical" seasonal profile (actual: matches the immediately preceding year's cluster shifted by 12 months); the low-spell threshold with a `+` sign (actual: `median − 1.0·σ_noise`). | All five corrected against the current source (`_state_input.py`, `_boundary.robust_scale`, `_circular_timing.py`, `_recurrence_identifiability.narrow_most_recent_recurrence`, `_events.py`), with the module/function cited inline. | Re-derived each formula directly from the cited source (quoted above); no remaining stale-description grep hits for the old wording. |
| C5 | Handoff §6's table was labelled "old→corrected refinement" but held the current-default-vs-corrected numbers (4/3/2 shifts, 13/7/8 downgrades); the real old-refinement-vs-corrected comparison has **zero** quality downgrades in all three seasonal catchments (3/3/2 shifts, all widening, 0/0 quality changes). Directly answers open question 3 above: no, it was not clear enough — it was actively mislabelled. | §6 now shows two explicitly labelled tables (Table A: old refinement vs. corrected; Table B: current default vs. corrected) plus explanatory paragraphs that attribute each statistic to the correct table by name. | Read directly from the freshly regenerated `comparisons/catchments.csv`; matches Codex's own cited numbers exactly (Table A: 3/3/2 shifts, all widening, 0/0 up/down; Table B: 4/3/2 shifts, 13/7/8 down, 0 up). |
| C6 | `coverage`/`abstention_rate` are conditional on resolvable truth only (`abstention_rate = 1 − applied/resolvable`); the plan required an *additional*, separately reported all-case measure. Validation: 0.076903 was 294/3823 resolvable spans out of 5000 total (1177 unresolvable), with no all-case numerator/denominator published. | `TroughRefinementScore` gained `resolvable_truth_n`, `all_case_coverage`, `all_case_abstention_rate`, `all_case_applied_n`, `all_case_total_n`, computed from every cache row regardless of `truth_resolvable`. No gate added or changed (existing gates retained verbatim, as required). | New regression test constructs a cache where the two rates provably diverge (1.0 vs 0.5) and asserts both. Regenerated 5000-seed calibration/validation: `all_case_coverage = 0.706` (cal.) / `0.7058` (val.), `all_case_total_n = 5000`, `resolvable_truth_n = 3824`/`3823` — matches Codex's own cited 1177 unresolvable count exactly (`5000 − 3823`). |

**Regenerated evidence** (all from the corrected source, real runs, not simulated):
`docs/calibration/2026-09-08-trough-refinement-{calibration,validation}.json` and
`hydroseason/_trough_refinement_defaults.py` (fingerprint `0f4d5432617064cf3c918bee397efdf0c2e0de036bf702b34ed0021b1944c716`,
frozen tuple unchanged: `huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5`); this bundle's
`validation/component-{calibration,validation}.json` (synced copies); `after/{default,refinement}`
for all five catchments and `comparisons/{catchments,cycles,months}.csv`;
`validation/pipeline.json` / `pipeline-cycles.csv`; `validation/pytest.xml`,
`test-results.html`, `coverage.txt`, `ruff.txt`; `manifest.json` and `index.html`.

**Test/lint status after the fix pass:** 1592 passed, 3 failed (0 errors), full suite
(`validation/pytest.xml`). All three failures are pre-existing and unrelated to C1–C6, confirmed
via `git status` showing zero working-tree diff on every file each failure touches:
`tests/test_decision_policy_docs.py::test_recurrence_identifiability_promotion_docs` (against
the pre-existing `docs/decision-policy.md` edit noted in §1), and
`tests/test_package_surface.py::test_package_import_exposes_only_migration_safe_surface` (both
already reported before this round). A third,
`tests/test_io_dea_stats.py::test_artifact_digest_differs_when_source_version_changes_despite_identical_mask`,
newly surfaced in this full run: it passes in complete isolation and passes running its whole
file alone, so it is a full-suite test-order-dependent flake in an untouched module
(`hydroseason/_historical_water_mask.py`), not a regression from this fix pass — the prior
Task 6 full-suite run evidently did not hit the same ordering. Coverage 89% (`coverage.txt`,
line-for-line consistent with the prior 89.46%). Lint: `ruff check .` clean on every file this
fix pass touched (a stray import-formatting issue introduced by the C3 fix was caught and
corrected before this report); only pre-existing findings remain elsewhere.

**This round is the "demonstrated defect" this document's closing gate (immediately above)
already anticipated** — no scope expansion beyond Codex's own six findings was made. The same
gate applies again going forward: no further scientific changes without either user feedback via
`review-notes.md` or another demonstrated defect.

---

## 10. Codex fix-review (2026-09-09): remaining C3/C4 items closed

A follow-up, independent Codex review
([`reviews/codex-fix-review-2026-09-09.md`](reviews/codex-fix-review-2026-09-09.md)) audited the
§9 fixes against current source and confirmed C1, C2, C5, C6 closed with no new scientific
defect. It found two remaining provenance/documentation gaps, both now closed — detailed fix
report at
[`reviews/fixes-for-codex-fix-review-2026-09-09.md`](reviews/fixes-for-codex-fix-review-2026-09-09.md):

| # | Finding | Fix | Verified |
|---|---|---|---|
| C3 | `_pipeline_manifest_hash`'s module list was both wrong and incomplete: it hashed `_catchment`/`_condition`/`_phase`, none of which `detect_dynamic_hydrological_years` actually imports, while omitting real dependencies it does import (`_timing_identifiability`, `_circular_timing`, `_recurrence_identifiability`, `_state_input`, `_phase_scheme`, `_seasonality`, `_harmonic`, `_scientific_defaults`) — an evaluator import-formatting edit alone made the published `manifest_hash` unreproducible from current source. Separately, `handoff-for-codex.md` §1 quoted `after_source.dirty_patch_hash` under the `finalize_time_source` label, and `before_source` was described alongside two fully-archived-snapshot stages without flagging that it has no archived patch or new-file contents. | `scripts/evaluate_final_pipeline.py`'s `_pipeline_manifest_hash` now hashes the real static-import closure instead, with an explicit code comment stating this is a named list, not a computed call graph (scope, not exhaustiveness, is claimed). `validation/pipeline.json` / `pipeline-cycles.csv` re-published from current source. §1 above corrected to cite `finalize_time_source.dirty_patch_hash` (`259228524716cc115c55a422d5a76bdef7bfe927e7bd60be198272f39b94ed07`) and to flag `before_source`'s reconstruction as unavailable. New staleness guard added. | New fingerprint `9e61e98c9195eec90dedd9721643545ed420f9b35ab6f83bfa66f46efa74c104`; `pipeline-cycles.csv` confirmed byte-for-byte identical to the pre-fix run (200 rows) — provenance-only, no numerical change, matching Codex's own independent rerun. New test `tests/test_release_metadata.py::test_published_pipeline_evaluation_is_not_stale`. |
| C4 | `docs/superpowers/audit_briefing.md` Step 2 defined the document's only `sigma_noise` as the boundary estimator (`_boundary.robust_scale`); Step 7 kept using the same unqualified symbol for event/low-spell thresholds, which actually use the differently-defined, AR(1)-corrected `_events._noise_scale`. | Step 2's symbol renamed `sigma_noise^{boundary}` throughout Steps 2–6 (including the Step 5 rewetting-pulse bullet); Step 7 gained an explicit `sigma_noise^{event}` definition (`_events._noise_scale`, stated as a separate estimator with its formula) before it is used in the entry/exit/low-spell threshold formulas. The corrected low-spell minus sign from §9/C4 is untouched. | Re-derived directly against `hydroseason/_events.py:_noise_scale` and `hydroseason/_boundary.py:robust_scale`; the two are confirmed numerically distinct on the same series (boundary ≈ 4.5e-14 pp vs. event ≈ 15.4 pp on the original audit's 20-year seasonal probe, matching the review's own numbers). No implementation change. |

No component recalibration, gate change, or detector behavior change was made in this round —
both items were documentation/provenance corrections, as the review itself concluded.
