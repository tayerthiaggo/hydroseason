# Fixes for Codex final review (2026-09-08) — report for Codex Astra 6

**Purpose of this document:** [`reviews/codex-final.md`](codex-final.md) found six substantiated
findings (C1–C6) against the working tree described in
[`../handoff-for-codex.md`](../handoff-for-codex.md). This document records what was changed to
fix each one, how each fix was verified, and what evidence in this bundle was regenerated as a
result — so Codex Astra 6 can audit the fixes independently, the same way `codex-final.md`
audited the original implementation. Nothing here should be taken on the implementer's word;
every claim below names a file, a command, or a number that can be re-checked.

**Scope discipline:** only the six findings in `codex-final.md` were addressed. No retuning, no
new detector behaviour, no unrelated cleanup. Where a finding's own reproduction script
(`reviews/codex-final-probes.py`) could be re-run against the fix, it was, and the new output is
quoted below.

**Base state before this fix pass:** commit `aaf231a655a22ad1e4698a6fea25199f373c9784` plus the
same uncommitted working tree `codex-final.md` reviewed (component fingerprint
`4d745ac70783ff8fe22bf6d2d3fa2a43e1126cf30255e4dd4827bb86a17a5041`, pipeline fingerprint
`23a2e070838cc6d21830fc6ab205b0a0a4c14f773f6dbd9e7f4e3e461bf6086c`). No commits were made during
this fix pass either — every change below is still an uncommitted working-tree edit.

---

## C1 — post-gap return to an equivalent low excluded from support

**Root cause.** `hydroseason/_trough_refinement.py`'s `_refine_gap_after_low_state` fits the
pre-gap segment, then had two separate post-gap checks: (a) reject if any post-gap value is
*materially below* the fitted low (`gap_before_low_state`), and (b) treat the case as an
unresolved overlap only if the **first** post-gap value sits *at* the low
(`gap_overlaps_low_state`). Neither check looked at post-gap values *after* the first one for a
return to-equivalent-low. A single-month gap followed by a value above the low (looks like
recovery) and then, later, a value back at the low was therefore scored as a clean
`recovery_crosses_gap` with pre-gap-only support — silently dropping real evidence that the low
state extends past the gap.

**Fix** (`hydroseason/_trough_refinement.py`, the block right after `after_values` is
computed). Instead of testing only `values_series.iloc[gap_end + 1]`, the whole `after_values`
array is now tested for the low-equivalence band (exact numerical equality when
`scale == 0.0`, the Huber-loss cutoff otherwise — the same tolerance definitions as before, just
applied elementwise instead of to one element):

- index `0` at the low → unchanged behaviour, `unresolved` / `gap_overlaps_low_state`.
- any **later** index at the low → new: `unresolved` / `post_gap_return_to_low_state`. This is
  the fix — previously this case fell through to `recovery_crosses_gap`.
- no post-gap value at the low anywhere → unchanged, `provisional` / `recovery_crosses_gap`.

This is a strictly more conservative change: it can only turn a previous `recovery_crosses_gap`
into an abstention, never the reverse, and it does not touch the separate
`gap_before_low_state` ("materially below") check at all.

**Verification.**

1. Codex's own reproduction (`reviews/codex-final-probes.py`, C1 section), re-run against the
   fix:

   ```text
   {'missing_may': False, 'status': 'confirmed', 'reason': 'accepted', 'boundary': '2020-05-01 00:00:00', 'support': ['2020-04-01', '2020-05-01', '2020-06-01', '2020-07-01'], 'scale_pp': 1.0}
   {'missing_may': True, 'status': 'unresolved', 'reason': 'post_gap_return_to_low_state', 'boundary': 'None', 'support': ['2020-04-01'], 'scale_pp': 1.0}
   ```

   Previously the second line read `status: provisional, reason: recovery_crosses_gap, boundary:
   2020-04-01, support: ['2020-04-01']` — the exact defect quoted in `codex-final.md`. It now
   abstains instead of asserting the unsupported singleton.

2. Two new regression tests in `tests/test_trough_refinement.py`:
   `test_gap_with_exact_later_return_to_low_abstains_instead_of_pre_gap_only_support` (exact
   equality case, mirrors the probe) and
   `test_gap_with_within_tolerance_later_return_to_low_abstains` (9.8% vs. a 10% low under 1pp
   measurement tolerance — a near-miss, not an exact match). Both assert
   `status == "unresolved"`, `reason == "post_gap_return_to_low_state"`, `boundary is None`.

3. All 28 pre-existing tests in `tests/test_trough_refinement.py` still pass unmodified
   (`test_gap_after_observed_low_state_keeps_provisional_boundary`,
   `test_daly_gap_keeps_full_pre_gap_low_state_and_uses_november_boundary`, and
   `test_gap_overlapping_possible_low_state_is_unresolved` in particular exercise the two
   *unchanged* branches and still pass) — 30/30 total with the two new ones.

4. **Real-data and synthetic-corpus impact: none measured.** The 5000-seed trough-refinement
   calibration cohort and 5000-seed validation cohort (regenerated below, C6) are **numerically
   byte-identical** to the pre-fix run on every metric except the new C6 fields. The five real
   catchments' `comparisons/catchments.csv` numbers (regenerated below, C5) are also unchanged.
   This defect is real and the fix is correct, but it does not manifest in either corpus this
   pass measures — it is a narrow edge case (a post-gap excursion followed by a later exact
   return), not one that happened to be exercised here. This is stated plainly, not
   downplayed: the fix is verified by direct reproduction (points 1–2), not by "the numbers
   didn't move."

---

## C2 — per-cycle diff drops real recovery changes

**Root cause.** `scripts/evaluate_final_pipeline.py`'s `compare_cycle_tables` computed
`_DIFF_VALUE_COLUMNS` (which includes `recovery_start_month`, `raw_trough_month`,
`trough_refinement_applied`, `annual_condition`, etc.) but only ever *copied* those columns into
a diff row after a **smaller**, separately-named set of counters (`peak_changed`,
`boundary_shifted`, `interval_width_changed`, `status_changed`, `newly_(un)computable`) had
already found a change. A change confined to a column outside that smaller set — the demonstrated
case was `recovery_start_month` — produced `row_changes == []`, so the row was never appended to
the diff DataFrame at all, even though the promised column set includes it.

**Fix** (`scripts/evaluate_final_pipeline.py`, `compare_cycle_tables`, right before
`if row_changes:`). Added one more check, after all the existing ones: does *any* column in
`_DIFF_VALUE_COLUMNS` (+ the boundary column), using the same missing-aware `_nan_eq`, differ
between `before_row` and `after_row`? If so, `"value_changed"` is appended to `row_changes`,
guaranteeing the row is emitted. No named counter was added, changed, or removed — the existing
`counts` dict is untouched, as the bounded correction required.

**Verification.**

1. Codex's own reproduction (`reviews/codex-final-probes.py`, C2 section) printed nothing when
   re-run — meaning the loop that flags "a recovery date changed but the year isn't in the diff"
   found zero such rows, across all three seasonal catchments' full real hydro-year tables.

2. Direct check of the regenerated `comparisons/cycles.csv`
   (`old_refinement_vs_corrected_refinement`), the five rows `codex-final.md` cited by name:

   | catchment | hy_year | change | recovery_before | recovery_after |
   |---|---:|---|---|---|
   | daly_river_nt | 2006 | `value_changed` | 2007-01-01 | *(null)* |
   | daly_river_nt | 2014 | `value_changed` | 2015-01-01 | *(null)* |
   | daly_river_nt | 2017 | `value_changed` | 2018-01-01 | *(null)* |
   | daly_river_nt | 2022 | `value_changed` | 2023-01-01 | *(null)* |
   | fitzroy_river_wa | 2013 | `value_changed` | 2013-12-01 | *(null)* |

   All five now appear (previously absent, per `codex-final.md`'s own table).

---

## C3 — source identity does not cover the new evaluation code

Three sub-issues, each with its own fix.

**C3a — `git diff HEAD` misses untracked files.** New evaluation scripts and their tests
(`scripts/build_final_review.py`, `scripts/evaluate_final_pipeline.py`,
`tests/test_final_pipeline.py`, `tests/test_final_review.py`) are untracked, so the previous
patch-hash-only identity claim never covered their content at all.

*Fix* (`scripts/build_final_review.py`, `_git_info`): now walks `git status --porcelain`'s `??`
entries, and for every untracked `*.py` file (source, not the untracked generated-evidence
directories, which are outputs), reads and embeds its full text plus a SHA-256 of that text —
`untracked_python_sources` / `untracked_python_source_hashes` — into the git-info dict every
stage's manifest carries. The tracked diff is now also embedded as literal text
(`tracked_diff_patch`), not only as a hash — "a hash is not the diff itself" (`codex-final.md`),
so the diff itself is now archived alongside its hash.

**C3b — the top-level bundle manifest conflated three different moments.** `build_bundle_manifest`
(called by `build_index`, which runs at the end of every stage — most often last, as part of
`finalize`, possibly after further edits) stamped one `_git_info(REPO_ROOT)` call under the key
`"source"` and let readers treat it as proof of what generated the before/after numbers, when it
is really only a stamp of whatever the tree looked like the last time `build_index` ran.

*Fix*: the top-level manifest now carries three separate keys — `before_source` and
`after_source`, each copied verbatim from that stage's own manifest (captured *at that stage's
generation time*), and `finalize_time_source`, the (renamed, same mechanism) live-tree stamp,
explicitly documented as only that.

**C3c — the pipeline fingerprint hashed a hand-picked function list, not the real dependency
closure.** `_pipeline_manifest_hash` hashed five specific `hydroseason` modules plus four
specific functions from `evaluate_final_pipeline.py` itself — omitting `_split_wrong_cycle`
(named explicitly in `codex-final.md`), its threshold constant `_GEOMETRY_MAX_MATCH_MONTHS`
(imported by name from `hydroseason._calibration`, so hashing `_calibration`'s source wasn't
even in the list), and the `hydroseason._synthetic` corpus generator.

*Fix* (`scripts/evaluate_final_pipeline.py`, `_pipeline_manifest_hash`): now hashes this whole
module's own file bytes (covers every helper it defines, present or future, not a maintained
list), plus the full source of `_boundary`, `_calibration`, `_catchment`, `_condition`, `_phase`,
`_dynamic_year`, and `_synthetic`, plus the **runtime value** of `_GEOMETRY_MAX_MATCH_MONTHS` as
used by this module (not just its source — see verification below).

**Verification.**

1. Codex's own runtime-mutation probe (`reviews/codex-final-probes.py`, C3 section), re-run:

   ```text
   before: ([1.0], 0)
   after: ([], 1)
   same fingerprint: False
   ```

   Previously this printed `same fingerprint: True` — mutating
   `evaluator._GEOMETRY_MAX_MATCH_MONTHS` changed scoring but not the fingerprint. It now
   changes both.

2. `manifest.json:finalize_time_source.untracked_python_source_hashes` (regenerated bundle
   manifest) lists all four untracked `.py` files with content and hash; `before_source` and
   `after_source` are both present and distinct keys from `finalize_time_source`.

3. `ruff check .` on the touched files is clean (an import-line-length/sort issue the C3c fix
   introduced in `evaluate_final_pipeline.py` was caught and reformatted into a parenthesized
   multi-line import before this report was written).

---

## C4 — required briefing corrections were omitted

**Root cause.** `docs/superpowers/audit_briefing.md` (a project-internal scientific-methods
reference, not the code) still described five things that no longer matched the current source,
each corrected against the exact function that actually implements it:

| # | Was | Now (source of truth) |
|---|---|---|
| 1 | `extent_pct = n_water / n_aoi × 100` | `extent_pct = n_water / n_valid × 100` (`hydroseason/_state_input.py:58`); `n_aoi` denominates `invalid_pct`, not `extent_pct` |
| 2 | Noise scale "corrected for temporal autocorrelation (AR(1) parameter φ)" | Seasonal-median-removed MAD, no autocorrelation term at all (`hydroseason/_boundary.py:robust_scale`) |
| 3 | Kuiper test yields "an exact empirical p-value" | Monte Carlo p-value against ≥999 simulated-null draws (`hydroseason/_circular_timing.py`) |
| 4 | `annual_shape_match` "narrows to the most recent cluster matching the catchment's typical annual profile span" | Narrows only if the immediately preceding cluster, shifted forward 12 months, has the same span and mutually covers the latest cluster — a year-over-year self-consistency check, not a comparison to any computed "typical" shape (`hydroseason/_recurrence_identifiability.py:narrow_most_recent_recurrence`) |
| 5 | Low spells: `median + 1.0·σ_noise` | `median − 1.0·σ_noise` (`hydroseason/_events.py:248`, `low_threshold = baseline - low_k * noise`) |

**Verification.** Each correction was re-derived directly from the cited source function (quoted
in the table above) rather than from memory of what it should say. A repository-wide search for
the old phrasings (`n_aoi` as the `extent_pct` denominator, `AR(1)`, `exact empirical`, `typical
annual profile`, the `+`-sign low-spell formula) inside `audit_briefing.md` returns no remaining
hits.

---

## C5 — handoff comparison label misattributes changes to this pass

**Root cause.** `handoff-for-codex.md` §6's table was headed "boundaries shifted
(old→corrected refinement)" but its data rows (4/3/2 shifts; 3/7, 2/16, 1/14 wider/narrower;
0/13, 0/7, 0/8 quality up/down) were actually the `current_default_vs_corrected_refinement`
numbers, not `old_refinement_vs_corrected_refinement`. The real old-refinement-to-corrected
comparison has **zero** quality changes in all three seasonal catchments. The following
paragraph then attributed the 13/7/8 downgrades to "the pre-fix code" without saying which
pre-fix baseline (old refinement, or the current no-refinement default) — ambiguous exactly
where it mattered.

**Fix** (`handoff-for-codex.md` §6): replaced the single mislabelled table with two, each
explicitly named and each carrying only its own comparison's numbers — **Table A** (old
refinement `trough_refinement_candidate_0_1` vs. corrected refinement, this pass's actual
before/after) and **Table B** (current default vs. corrected refinement, a different question).
The explanatory paragraphs were rewritten to name which table each statistic comes from,
including an explicit note that Table A shows zero quality changes while Table B shows the
13/7/8 downgrades — so a reader cannot attribute Table B's numbers to this pass's fixes.

**Verification.** Both tables' numbers were read directly from the freshly regenerated
`comparisons/catchments.csv` (not simulated) and match `codex-final.md`'s own cited numbers
exactly:

- Table A (`old_refinement_vs_corrected_refinement`): daly 3 shifts (3 wider/0 narrower, 0
  up/0 down); fitzroy 3 (3/0, 0/0); gilbert 2 (5/0, 0/0).
- Table B (`current_default_vs_corrected_refinement`): daly 4 shifts (3/7, 0/13); fitzroy 3
  (2/16, 0/7); gilbert 2 (1/14, 0/8).

These are also unchanged from the pre-C1-fix numbers (see C1's verification point 4) — C5 is a
pure labelling correction, not a numeric one.

---

## C6 — required all-case abstention measure is still missing

**Root cause.** `coverage` (and therefore `abstention_rate = 1 - coverage`) in
`hydroseason/_trough_refinement_calibration.py:score_trough_refinement_policy` divides applied
predictions by `len(resolvable)` — resolvable-truth spans only. The plan's Task 3 required this
kept separate from an *all-case* measure (every span, resolvable or not). No such measure was
computed or published; the validation report's `abstention_rate` (0.076903) was silently
294/3823 resolvable spans out of a 5000-span corpus containing 1177 unresolvable spans, with the
"Abstention rate" label not naming its own denominator.

**Fix** (`hydroseason/_trough_refinement_calibration.py`): `TroughRefinementScore` gained five
new fields — `resolvable_truth_n`, `all_case_coverage`, `all_case_abstention_rate`,
`all_case_applied_n`, `all_case_total_n` — computed in `score_trough_refinement_policy` from
`subset` (every cache row for the policy) rather than `resolvable`. The existing frozen gates
(`_admissible`) are untouched — no new gate, no threshold change, as required. Because
`select_trough_refinement_policy` builds its returned score via `**asdict(selected)`, and
`_trough_refinement_report_payload` (in `scripts/run_calibration.py`) builds its `"metrics"` dict
via `asdict(score)`, the new fields flow automatically into both the calibration/validation JSON
reports without any change to either of those functions.

**Verification.**

1. New regression test
   `test_all_case_abstention_uses_every_row_not_only_resolvable_truth` in
   `tests/test_trough_refinement_calibration.py`: builds a cache with 80 resolvable rows (all
   applied) and 80 unresolvable rows (none applied) per policy, and asserts
   `all_case_coverage == 0.5` while `abstention_rate == 0.0` for the same score object — the two
   denominators provably disagree.

2. Regenerated 5000-seed validation cohort
   (`docs/calibration/2026-09-08-trough-refinement-validation.json`):
   `resolvable_truth_n: 3823`, `all_case_total_n: 5000` → `1177` unresolvable, matching
   `codex-final.md`'s own cited count exactly. `all_case_applied_n: 3529`,
   `all_case_coverage: 0.7058`, `all_case_abstention_rate: 0.2942` — now published alongside the
   pre-existing `coverage`/`abstention_rate` fields, not inferable from them alone.

3. Every other metric and every gate boolean in both the calibration and validation reports is
   **byte-identical** to the pre-fix run — this fix only adds fields, it does not change any
   existing measurement.

---

## Regenerated evidence

Every item below was generated by actually running the corrected code against real inputs —
none of it is hand-edited or simulated.

- **Component calibration/validation** (5000 seeds each, frozen tuple `huber_k=1.345,
  profile_loss_cutoff=0.05, pulse_z=1.5`, no retuning):
  `docs/calibration/2026-09-08-trough-refinement-calibration.json`,
  `docs/calibration/2026-09-08-trough-refinement-validation.json`,
  `hydroseason/_trough_refinement_defaults.py` — new fingerprint
  `0f4d5432617064cf3c918bee397efdf0c2e0de036bf702b34ed0021b1944c716` (was `4d745ac7...`; changed
  because the hashed source changed — C1's fix to `_trough_refinement.py` and C6's fix to
  `score_trough_refinement_policy` are both inside the hashed dependency closure). This bundle's
  `validation/component-calibration.json` / `component-validation.json` were synced to match.
  Command:
  ```powershell
  .venv\Scripts\python.exe scripts/run_calibration.py --trough-refinement --fixed-trough-policy `
    --partition calibration --out-report docs/calibration/2026-09-08-trough-refinement-calibration.json `
    --out-module hydroseason/_trough_refinement_defaults.py
  .venv\Scripts\python.exe scripts/run_calibration.py --trough-refinement --partition validation `
    --out-report docs/calibration/2026-09-08-trough-refinement-validation.json
  ```
- **Five-catchment `after` stage** (real Daly/Fitzroy/Gilbert/Lachlan/Moonie inputs,
  SHA-256-verified unchanged): `after/{default,refinement}/<catchment>/…`,
  `comparisons/{catchments,cycles,months}.csv`, `smoke/`, `review-notes.md`. `before/` was left
  untouched (it is the frozen historical baseline captured before Task 1–3's fixes; the script
  refuses to overwrite it while input hashes still match — regenerating it would defeat its
  purpose as a "before" arm). Command:
  ```powershell
  .venv\Scripts\python.exe scripts/build_final_review.py --stage after --output-dir case_studies/results/final-review-2026-09-08
  ```
- **Synthetic detector-off/on pipeline evaluation** (100 seeds per partition, 200 total across
  both partitions, real detector, no supplied truth peaks): `validation/pipeline.json`,
  `validation/pipeline-cycles.csv` — `manifest_hash`
  `9e61e98c9195eec90dedd9721643545ed420f9b35ab6f83bfa66f46efa74c104` (re-published 2026-09-09
  per Codex fix-review C3: the prior `9b158997...` fingerprint's module list included
  `_catchment`/`_condition`/`_phase`, none of which `detect_dynamic_hydrological_years` actually
  imports, while omitting real dependencies it does import —
  `_timing_identifiability`/`_circular_timing`/`_recurrence_identifiability`/`_state_input`/
  `_phase_scheme`/`_seasonality`/`_harmonic`/`_scientific_defaults`. The fingerprint now hashes
  the real static-import closure instead; see `scripts/evaluate_final_pipeline.py`'s
  `_pipeline_manifest_hash` comment for the explicit scope note that this is a named list, not a
  computed call graph. A byte-for-byte comparison of `pipeline-cycles.csv` before and after this
  re-publish confirms zero numerical change — this was a provenance-only correction, matching
  Codex's own independent rerun.) Structural safety unchanged: `peak_changes: 0`,
  `before/after_duplicate_or_nonmonotonic_boundaries: 0`, `newly_uncomputable: 0`, both
  partitions, `matched_rows: 1200` each. Command:
  ```powershell
  .venv\Scripts\python.exe scripts/evaluate_final_pipeline.py --output-dir case_studies/results/final-review-2026-09-08/validation
  ```
- **Full test suite, coverage, lint, bundle finalize:**
  ```powershell
  .venv\Scripts\python.exe -m pytest -q --junitxml=case_studies/results/final-review-2026-09-08/validation/pytest.xml `
    --cov=hydroseason --cov-report=term-missing
  .venv\Scripts\python.exe -m ruff check .
  .venv\Scripts\python.exe scripts/build_final_review.py --stage finalize --output-dir case_studies/results/final-review-2026-09-08
  ```
  Result: **1592 passed, 3 failed, 0 errors** (`validation/pytest.xml`,
  `validation/test-results.html`; published honestly as "NOT A PASS", not hidden). Coverage 89%
  (`validation/coverage.txt`). `ruff check .`: 18 pre-existing findings, zero in any file this
  fix pass touched (`validation/ruff.txt`).

### The three test failures, and why none are attributable to C1–C6

All three fail identically whether or not any of C1–C6's changes are present, because none of
the three failing tests, and none of the source files they exercise, appear anywhere in the
C1–C6 diff:

1. `tests/test_decision_policy_docs.py::test_recurrence_identifiability_promotion_docs` — fails
   against `docs/migrations/0.2.0-timing-identifiability.md`, one of the pre-existing
   unrelated uncommitted files already listed in `handoff-for-codex.md` §1 (present before this
   fix pass and before the original implementation pass).
2. `tests/test_package_surface.py::test_package_import_exposes_only_migration_safe_surface` —
   fails against `hydroseason/__init__.py` and its own test file; `git status --porcelain`
   shows **zero** diff on either against `HEAD` (`hydroseason/__init__.py` was last touched in
   commit `3dadd29`, four commits before the audit's own reviewed commit).
3. `tests/test_io_dea_stats.py::test_artifact_digest_differs_when_source_version_changes_despite_identical_mask`
   — newly observed in this full-suite run (not previously reported). Passes in complete
   isolation (`pytest tests/test_io_dea_stats.py::test_artifact_digest_differs...`) and passes
   running its entire file alone (70/70). `hydroseason/_historical_water_mask.py` and
   `tests/test_io_dea_stats.py` both show zero `git status` diff against `HEAD`. This is a
   full-suite test-order-dependent flake in an untouched module, unrelated to C1–C6 or to
   anything else in this fix pass — not investigated further, as fixing unrelated pre-existing
   test-isolation issues is outside this bounded review's scope.

---

## Suggested checklist for Codex Astra 6

- [ ] C1: confirm the elementwise low-equivalence check in `_refine_gap_after_low_state` is
      correct for both the `scale == 0.0` and Huber-loss branches, and that it cannot itself
      introduce a false abstention on a genuinely clean recovery (see the "clean-recovery
      sanity" case verified during development: `[90,60,30,10,10,40,70,80,85]` with May missing
      still returns `provisional`/`recovery_crosses_gap`).
- [ ] C2: confirm `_DIFF_VALUE_COLUMNS` is still the right complete field list, and that the new
      `value_changed` tag does not double-count or interact oddly with the existing named
      counters (it should not — counters are computed independently, before this check).
- [ ] C3: confirm the `_pipeline_manifest_hash` dependency list is now actually complete (every
      module/function `evaluate_records`'s call graph touches), not just larger than before.
- [ ] C4: spot-check the five corrected formulas against the cited source lines directly.
- [ ] C5: confirm Table A and Table B in handoff §6 are each internally consistent with
      `comparisons/catchments.csv`.
- [ ] C6: confirm no downstream consumer (report generation, other docs) reads `abstention_rate`
      expecting it to already be the all-case figure.
- [ ] Re-run `reviews/codex-final-probes.py` independently and confirm the three outputs above.
- [ ] Everything in this bundle's `manifest.json` and `handoff-for-codex.md` §9 is consistent
      with what is actually on disk (no further scientific changes were made after the
      regeneration commands above completed).
