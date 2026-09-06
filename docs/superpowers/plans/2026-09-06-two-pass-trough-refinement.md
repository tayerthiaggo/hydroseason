# Two-Pass Trough Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate an interpretable retrospective trough challenger that preserves pass-1 peaks, represents uncertainty honestly, and applies accepted shared-boundary changes atomically.

**Architecture:** A new `_trough_refinement.py` module owns immutable evidence types and the deterministic robust valley model. `_dynamic_year.py` remains responsible for pass-1 detection and performs only eligibility routing plus atomic recomputation of the two cycles sharing an accepted boundary. Separate synthetic/calibration and blinded-cohort tooling keeps scientific selection out of operational detection.

**Tech Stack:** Python 3.10+, NumPy, Pandas, pytest, existing HydroSeason calibration/report infrastructure

**Spec:** `docs/superpowers/specs/2026-09-06-two-pass-trough-refinement-design.md`

## Global Constraints

- Pass 2 never changes or rediscovers a pass-1 peak.
- Public detection defaults remain pass 1 until every promotion gate passes.
- Core fitting uses NumPy and Pandas only.
- No record-wide amplitude, percentage-above-minimum, raw-value, station-specific, or fixed-rising-month gate.
- Missing months are structural barriers and cannot be bridged.
- Low-quality observations remain visible and receive support weight; they are never silently deleted from nominal evidence.
- All candidate settings are global, frozen before untouched validation, sensitivity-tested, fingerprinted, and versioned.
- A boundary change is applied to both sharing cycles or rolled back from both.
- Existing unrelated modifications in `_scientific_defaults.py`, calibration outputs, result directories, and temporary directories remain untouched.

---

### Task 1: Restore the Safe Pass-1 Default and Define Challenger Types

**Files:**
- Create: `tests/test_trough_refinement.py`
- Create: `hydroseason/_trough_refinement.py`
- Modify: `tests/test_dynamic_year.py`
- Modify: `hydroseason/_dynamic_year.py`

**Interfaces:**
- Consumes: prepared monthly frames from `prepare_monthly_extent`; `TimingStatus` from `_timing_identifiability.py`.
- Produces: `PeakBoundary`, `TroughRefinementPolicy`, `TroughRefinementResult`, and `refine_trough_span(...)`.

- [ ] **Step 1: Write a failing regression test proving default detection is pass 1**

Add a test using a compact monthly frame whose uncommitted tolerance prototype moves the trough. Assert that default `detect_dynamic_hydrological_years` retains the pass-1 date and does not expose an applied challenger.

```python
def test_default_detection_does_not_apply_unvalidated_trough_refinement():
    frame = _two_cycle_extent_with_flat_dry_tail()
    years = detect_dynamic_hydrological_years(
        frame,
        config=DynamicHydroYearConfig(expected_trough_month=9),
    )
    assert years.loc[years["hy_year"] == 2020, "trough_month"].item() == pd.Timestamp("2020-09-01")
```

- [ ] **Step 2: Run the regression and verify RED**

Run: `python -m pytest tests/test_dynamic_year.py::test_default_detection_does_not_apply_unvalidated_trough_refinement -q`

Expected: FAIL because the current uncommitted pass-2 prototype applies unconditionally.

- [ ] **Step 3: Remove the unsafe prototype path**

Delete `TROUGH_EQUIVALENCE_REL_TOLERANCE`, `_refine_troughs_by_recession`, its `_epsilon_pp` import, and the unconditional mutation/reassembly block. Do not change pass-1 logic.

- [ ] **Step 4: Verify GREEN and run focused pass-1 regressions**

Run: `python -m pytest tests/test_dynamic_year.py -q`

Expected: all existing dynamic-year tests plus the new default-authority test pass.

- [ ] **Step 5: Write failing API tests for immutable evidence types**

```python
def test_missing_peak_makes_refinement_unavailable():
    result = refine_trough_span(
        _simple_span(),
        left_peak=PeakBoundary.missing(),
        right_peak=_point_peak("2021-02-01"),
        policy=_policy(),
    )
    assert result.status == "unavailable"
    assert result.reason == "missing_or_unresolved_peak"
    assert result.boundary is None


def test_open_span_awaits_next_peak():
    result = refine_trough_span(
        _simple_span(),
        left_peak=_point_peak("2020-02-01"),
        right_peak=None,
        policy=_policy(),
    )
    assert result.status == "awaiting_next_peak"
```

- [ ] **Step 6: Run the API tests and verify RED**

Run: `python -m pytest tests/test_trough_refinement.py -q`

Expected: collection error because `_trough_refinement` does not exist.

- [ ] **Step 7: Implement result types and terminal eligibility branches**

Implement frozen dataclasses and validation:

```python
RefinementStatus = Literal["confirmed", "provisional", "unresolved", "unavailable", "awaiting_next_peak"]

@dataclass(frozen=True)
class TroughRefinementPolicy:
    huber_k: float
    profile_loss_cutoff: float
    pulse_z: float
    version: str = "trough_refinement_candidate_0_1"

@dataclass(frozen=True)
class PeakBoundary:
    selected: pd.Timestamp | None
    candidates: tuple[pd.Timestamp, ...]
    timing_status: TimingStatus
    quality: Literal["normal", "low", "unknown", "missing"]

@dataclass(frozen=True)
class TroughRefinementResult:
    status: RefinementStatus
    reason: str
    boundary: pd.Timestamp | None
    boundary_candidates: tuple[pd.Timestamp, ...]
    low_state_start: pd.Timestamp | None
    low_state_end: pd.Timestamp | None
    recovery_start: pd.Timestamp | None
    pulse_months: tuple[pd.Timestamp, ...]
    local_scale_pp: float
    best_loss: float
    effective_support: float
    policy_version: str
```

- [ ] **Step 8: Verify GREEN and commit Task 1**

Run: `python -m pytest tests/test_trough_refinement.py tests/test_dynamic_year.py -q`

Commit: `git commit -m "refactor: isolate unvalidated trough challenger"`

---

### Task 2: Implement the Robust Shape-Constrained Valley Profile

**Files:**
- Modify: `tests/test_trough_refinement.py`
- Modify: `hydroseason/_trough_refinement.py`

**Interfaces:**
- Consumes: `PeakBoundary`, `TroughRefinementPolicy`, prepared frame columns `extent_pct`, `observed_fraction`, `quality_state`, `candidate_usable`, and optional pixel counts.
- Produces: private `_CandidateFit`; public `refine_trough_span(...)` returning a confirmed point/interval/broad result or unresolved evidence.

- [ ] **Step 1: Write failing point-trough and interval tests**

Use literal monthly values. The first curve has one supported turning month. The second has a low-state run with several endpoint dates inside the configured profile cutoff. Assert boundary candidates, last-month operational boundary, low-state occupancy, and recovery start separately.

```python
def test_point_trough_is_last_low_month_before_continuous_recovery():
    result = refine_trough_span(
        _prepared([90, 60, 30, 10, 20, 45, 80], "2020-01-01"),
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )
    assert result.boundary == pd.Timestamp("2020-04-01")
    assert result.recovery_start == pd.Timestamp("2020-05-01")


def test_boundary_interval_uses_latest_supported_endpoint():
    result = refine_trough_span(
        _prepared([90, 50, 10, 10, 10, 30, 80], "2020-01-01"),
        left_peak=_point_peak("2020-01-01"),
        right_peak=_point_peak("2020-07-01"),
        policy=_policy(profile_loss_cutoff=0.0),
    )
    assert result.boundary_candidates == tuple(pd.date_range("2020-03-01", "2020-05-01", freq="MS"))
    assert result.boundary == pd.Timestamp("2020-05-01")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_trough_refinement.py -q`

Expected: FAIL because eligible spans are not fitted.

- [ ] **Step 3: Implement weighted PAVA and fixed-block valley fitting**

Implement a deterministic weighted isotonic primitive. For a fixed low-state block `[s, e]`, solve recession and recovery branches against their shared valley level. Use support weights, return fitted values on the original monthly index, and never connect across missing observations.

- [ ] **Step 4: Implement common local scale and Huber IRLS**

Enumerate every `[s, e]`, obtain the preliminary weighted-absolute-loss winner, calculate the shared local scale using the frozen hierarchy, then refit every candidate with Huber IRLS. Use `sqrt(np.finfo(float).eps)` relative convergence and 200 iterations; mark non-converged candidates inadmissible.

- [ ] **Step 5: Implement endpoint profiling**

For each `e`, retain the minimum loss over starts. Compute `(loss_e - loss_best) / effective_support`, retain endpoints at or below `profile_loss_cutoff`, split them into contiguous clusters, and classify span using existing timing thresholds.

- [ ] **Step 6: Verify GREEN**

Run: `python -m pytest tests/test_trough_refinement.py -q`

Expected: point and interval tests pass.

- [ ] **Step 7: Add RED tests for zero-scale and deterministic output**

Assert an exact flat bottom uses the exact-fit path, repeated calls are equal, and no NaN loss escapes.

- [ ] **Step 8: Implement zero-scale behavior and refactor**

Use exact loss comparison when residual MAD, first-difference MAD, and measurement floor are all zero. Keep candidate ordering deterministic.

- [ ] **Step 9: Run focused tests and commit Task 2**

Run: `python -m pytest tests/test_trough_refinement.py -q`

Commit: `git commit -m "feat: fit robust peak-to-peak trough profiles"`

---

### Task 3: Add Pulse, Gap, Peak-Uncertainty, and Quality Sensitivity Semantics

**Files:**
- Modify: `tests/test_trough_refinement.py`
- Modify: `hydroseason/_trough_refinement.py`

**Interfaces:**
- Consumes: nominal endpoint profile and support-derived extent bounds.
- Produces: stable final endpoint cluster, pulse dates, confidence status, and explicit reason codes.

- [ ] **Step 1: Write failing pulse tests**

Cover a large early pulse that returns to low state, two pulses in one span, and two separated modes without a supported return. Assert that magnitude alone cannot end recession, supported pulses are retained, and unsupported separated modes are unresolved.

- [ ] **Step 2: Run pulse tests and verify RED**

Run: `python -m pytest tests/test_trough_refinement.py -k "pulse or separated" -q`

- [ ] **Step 3: Implement pulse-aware cluster selection**

Use standardized positive residuals and `policy.pulse_z` only to label excursions. Select the later endpoint cluster only when observed values return to the low-state uncertainty set before final continuous recovery. Never bridge clusters.

- [ ] **Step 4: Write failing gap tests**

Assert: post-low-state gap gives a provisional last-observed boundary; low-state-overlapping gap gives unresolved; no low state gives unresolved; observations after a gap cannot confirm pre-gap recovery.

- [ ] **Step 5: Implement structural gap routing**

Operate on the regular monthly index, preserve contiguous-block identities, and issue stable reasons `recovery_crosses_gap`, `gap_overlaps_low_state`, or `no_defensible_low_state`.

- [ ] **Step 6: Write failing peak/quality sensitivity tests**

Cover point peaks, interval peak Cartesian propagation, low-quality identifiable peaks, missing/unresolved peaks, a removable low-quality interior month, and an essential low-quality recovery bridge.

- [ ] **Step 7: Implement deterministic sensitivity suite**

Evaluate nominal, all-low-quality-removed, each-low-quality-removed, each support-bound replacement, all ordered peak-date pairs, and unknown-quality-removed scenarios. Require one shared endpoint and combined span no wider than the existing broad threshold.

- [ ] **Step 8: Run all refinement tests and commit Task 3**

Run: `python -m pytest tests/test_trough_refinement.py -q`

Commit: `git commit -m "feat: propagate trough uncertainty and pulse evidence"`

---

### Task 4: Integrate the Challenger with Atomic Two-Cycle Acceptance

**Files:**
- Modify: `hydroseason/_dynamic_year.py`
- Modify: `hydroseason/__init__.py`
- Modify: `tests/test_dynamic_year.py`
- Modify: `tests/test_manual_review_regression.py`
- Modify: `tests/test_report_export.py`

**Interfaces:**
- Consumes: optional `DynamicHydroYearConfig.trough_refinement_policy`; pass-1 annual rows and opportunities.
- Produces: pass-1 evidence columns, challenger evidence columns, and an atomic applied/fallback result.

- [ ] **Step 1: Write failing opt-in and peak-freeze tests**

Default config must remain pass 1. An explicitly supplied candidate policy computes a challenger. Record the complete tuple of peak dates before/after and assert equality.

- [ ] **Step 2: Run integration tests and verify RED**

Run: `python -m pytest tests/test_dynamic_year.py -k "trough_refinement or peak_freeze" -q`

- [ ] **Step 3: Extract one-cycle assembly**

Refactor `_assemble_dynamic_years` so `_assemble_dynamic_cycle(frame, previous, opportunity, ...)` produces one row without changing behavior. Characterization tests must stay green before challenger integration.

- [ ] **Step 4: Add optional candidate policy and evidence columns**

Add `trough_refinement_policy: TroughRefinementPolicy | None = None` with default `None`. Extend `ANNUAL_COLUMNS` exactly as specified in the design. Preserve pass-1 fields before any challenge.

- [ ] **Step 5: Write failing atomic rollback tests**

Create cases where a bidirectional move succeeds, and where ordering, coverage, computability, or peak timing fails in either sharing cycle. Assert both rows change or neither changes.

- [ ] **Step 6: Implement local two-cycle recomputation and acceptance**

Pair adjacent annual rows without filtering missing rows. Build `PeakBoundary` from frozen pass-1 evidence. Challenge the intervening trough, recompute only the ending cycle and following cycle on copies, assert all ten acceptance rules, then replace both rows together. Never call global `_assemble_dynamic_years` after mutation.

- [ ] **Step 7: Add Daly/Fitzroy/Gilbert development regressions**

Encode the newly approved convention separately from old first-touch fixtures. Assert Daly's September-November interval with provisional November boundary in the gap case and Fitzroy's December boundary before continuous January recovery.

- [ ] **Step 8: Run integration and export tests**

Run: `python -m pytest tests/test_dynamic_year.py tests/test_manual_review_regression.py tests/test_report_export.py -q`

- [ ] **Step 9: Commit Task 4**

Commit: `git commit -m "feat: apply trough refinement atomically"`

---

### Task 5: Build Independent Synthetic Calibration and Untouched Validation

**Files:**
- Modify: `hydroseason/_synthetic.py`
- Create: `hydroseason/_trough_refinement_calibration.py`
- Create after successful calibration: `hydroseason/_trough_refinement_defaults.py`
- Modify: `scripts/run_calibration.py`
- Create: `tests/test_trough_refinement_calibration.py`
- Create after successful runs: `docs/calibration/2026-09-06-trough-refinement-calibration.json`
- Create after successful runs: `docs/calibration/2026-09-06-trough-refinement-validation.json`

**Interfaces:**
- Consumes: frozen policy grid, seeds `70000..74999` and `80000..84999`, truth intervals, and the pure challenger.
- Produces: deterministic cache rows, `TroughRefinementScore`, selected policy, fingerprint, calibration artifact, and report-only validation artifact.

- [ ] **Step 1: Write failing corpus partition tests**

Assert deterministic generation, disjoint seed enforcement, every frozen family, correct point/interval/unresolved truth, and no perturbation of existing synthetic generators.

- [ ] **Step 2: Implement trough-refinement truth and generators**

Add independent seed constants, frozen family ordering, monthly count frames, point/interval truth, gaps, quality, peaks, and pulses. Do not reuse validation truth in fingerprints.

- [ ] **Step 3: Write failing score/selector tests**

Use literal cache rows to test interval distance, false-precision denominator, Wilson gating, structural gating, coverage/abstention separation, pass-1 tie preference, and refusal when every candidate is inadmissible.

- [ ] **Step 4: Implement policy grid, cache, metrics, selector, and fingerprint**

Enumerate the 128 frozen tuples. Select lexicographically using the design order. Hash model source, generator source, truth type, grid, calibration seeds, metric source, numerical safeguards, selected tuple, and authority string.

- [ ] **Step 5: Extend the calibration CLI**

Add mutually exclusive `--trough-refinement`, calibration/validation partitions, bounded `--num-trough-refinement-seeds`, explicit output paths, and validation refusal on fingerprint mismatch. Validation cannot call the selector.

- [ ] **Step 6: Run calibration unit tests**

Run: `python -m pytest tests/test_trough_refinement.py tests/test_trough_refinement_calibration.py tests/test_calibration.py -q`

- [ ] **Step 7: Run full calibration and freeze selected candidate**

Run: `python scripts/run_calibration.py --trough-refinement --partition calibration --num-trough-refinement-seeds 5000 --out-report docs/calibration/2026-09-06-trough-refinement-calibration.json --out-module hydroseason/_trough_refinement_defaults.py`

Expected: one selected global tuple, all calibration gates recorded, fingerprint emitted.

- [ ] **Step 8: Run untouched synthetic validation exactly once**

Run: `python scripts/run_calibration.py --trough-refinement --partition validation --num-trough-refinement-seeds 5000 --out-report docs/calibration/2026-09-06-trough-refinement-validation.json`

Expected: no reselection, matching fingerprint, every validation gate recorded.

- [ ] **Step 9: Commit Task 5**

Commit: `git commit -m "feat: calibrate trough refinement policy"`

---

### Task 6: Add Blinded Real-Cohort Protocol and Evaluation

**Files:**
- Create: `case_studies/trough-refinement/cohort-protocol.json`
- Create: `case_studies/trough-refinement/review-rubric.md`
- Create: `scripts/build_trough_refinement_cohort.py`
- Create: `scripts/evaluate_trough_refinement_cohort.py`
- Create: `tests/test_trough_refinement_cohort.py`

**Interfaces:**
- Consumes: previously uninspected source root, frozen sampling seed, adjudicated labels, pass-1 and frozen pass-2 outputs.
- Produces: blinded manifest, reviewer sheet, label hash, comparison report, Wilson/cluster-bootstrap statistics, and promotion eligibility decision.

- [ ] **Step 1: Write failing builder tests**

Assert stratification, whole-catchment sampling, no algorithm columns in reviewer output, source/manifest fingerprints, immutable sampling seed, and refusal to use known development records.

- [ ] **Step 2: Implement cohort builder and protocol**

Include normal seasonal, low-variability, missing-data, low-quality, and two-pulse strata. Export monthly detector inputs plus blank label columns only. Freeze all cycles from sampled catchments.

- [ ] **Step 3: Write failing evaluator tests**

Assert label-schema validation, at least 20% and at least 30 double-reviewed spans, adjudication completion, minimum 73 algorithm point predictions, interval-distance metrics, Wilson upper bound, structural metrics, separate abstention, catchment bootstrap, and no post-unblinding cohort expansion.

- [ ] **Step 4: Implement evaluator**

Reject labels with algorithm fields, incomplete adjudication, changed hashes, inadequate double review, inadequate denominator, or mismatched calibration fingerprint. Emit pass/fail per frozen gate without changing policy.

- [ ] **Step 5: Run tests and available dry-run checks**

Run: `python -m pytest tests/test_trough_refinement_cohort.py -q`

If no eligible untouched source exists, verify the builder exits nonzero with an explicit external-evidence error and record promotion as unavailable rather than passed.

- [ ] **Step 6: Commit Task 6**

Commit: `git commit -m "feat: add blinded trough refinement cohort gate"`

---

### Task 7: Reporting, Migration, and Full Verification

**Files:**
- Modify: `hydroseason/_report_export.py`
- Modify: `hydroseason/_report_html.py`
- Modify: `hydroseason/_report_plotly.py`
- Modify: `tests/test_report_export.py`
- Modify: `tests/test_report_html.py`
- Modify: `tests/test_report_plotly.py`
- Modify: `docs/report-columns.md`
- Create: `docs/migrations/trough-refinement-candidate.md`

**Interfaces:**
- Consumes: annual pass-1/challenger/applied evidence columns.
- Produces: explicit exported fallback status, interval display, pulse diagnostics, and candidate-authority documentation.

- [ ] **Step 1: Write failing report/export tests**

Assert point versus interval rendering, last-month operational boundary, provisional fallback wording, unavailable/unresolved distinction, pulse dates, and unchanged legacy columns.

- [ ] **Step 2: Implement export and presentation changes**

Expose evidence without claiming unpromoted authority. Show the applied boundary interval and operational endpoint; retain challenger evidence when pass 1 wins.

- [ ] **Step 3: Update documentation**

Document every new column, status, reason, candidate authority, calibration fingerprint, gap semantics, and rollback path. State that promotion remains unavailable without a passing blinded real cohort.

- [ ] **Step 4: Run focused reporting tests**

Run: `python -m pytest tests/test_report_export.py tests/test_report_html.py tests/test_report_plotly.py -q`

- [ ] **Step 5: Run formatter/linter and full suite**

Run: `ruff check hydroseason tests scripts`

Run: `python -m pytest -q`

Expected: zero new failures. Any pre-existing failure must be reproduced against the pre-task commit and documented; no failure is dismissed without that comparison.

- [ ] **Step 6: Run protected development comparison**

Generate pass-1/pass-2 tables for Daly, Fitzroy, Gilbert, Lachlan, Moonie, and available stress records. Assert zero peak changes, zero duplicate/nonmonotonic boundaries, zero new uncomputable cycles, and report resolved/abstained results separately.

- [ ] **Step 7: Verify repository scope**

Run: `git status --short` and `git diff --check`.

Confirm unrelated `_scientific_defaults.py`, pre-existing calibration output, result directories, and temporary directories were not staged or modified by this plan.

- [ ] **Step 8: Commit Task 7**

Commit: `git commit -m "docs: expose trough refinement evidence"`

- [ ] **Step 9: Complete branch verification**

Use `superpowers:verification-before-completion`, then `superpowers:finishing-a-development-branch`. Because the user pre-authorized the recommended path and requested no questions, retain commits on the current `development` branch and do not push or open a pull request.
