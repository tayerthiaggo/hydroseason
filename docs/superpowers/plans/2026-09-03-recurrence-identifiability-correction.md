# Recurrence Identifiability Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace uncalibrated last-cluster narrowing with a truth-tested recurrence policy, validate it without contaminating frozen evidence, and recertify unlaunched HydroSeason 0.2.0.

**Architecture:** Put recurrence geometry in one pure module, drive its three eligible policies through the existing window assessor, and select a frozen default on a new disjoint synthetic corpus. Keep timing thresholds and their fingerprint unchanged; add separate recurrence calibration, validation, impact, and blinded-cohort evidence before 0.2.0 launch readiness is restored.

**Tech Stack:** Python 3.10+, pandas, NumPy, dataclasses, pytest, JSON, SHA-256, MkDocs.

**Spec:** `docs/superpowers/specs/2026-09-03-recurrence-cluster-identifiability-design.md`

## Global Constraints

- Target remains package version `0.2.0` and policy ID `established_0_2_0`; do not create 0.2.1.
- Do not change `TIMING_IDENTIFIABILITY_DEFAULTS` or any field on `TimingIdentifiabilityThresholds`.
- `timing_identifiability_fingerprint()` must remain exactly `e6cdf3ce960aa011711dc90e3ef4fb0135513eadaf471f4ac9e0656f80884735`.
- Do not edit any source hashed by `timing_identifiability_fingerprint()`: `_validate_tolerance`, `_resolution_pp`, `_peak_water_pixels`, `_timing_status`, `assess_timing_identifiability`, `prepare_monthly_extent`, `robust_scale`, `equivalent_extremum_months`, or `shortest_circular_span`.
- Seed 30035, the 34-record stress bundle, five protected catchments, three motivating records, and existing 21-station cohort are development evidence only. They must not select a policy.
- Recurrence calibration uses exactly seeds `50000..50959`; untouched validation uses exactly `60000..60959` once.
- Never inspect recurrence validation truth or run validation before calibration policy and fingerprint are frozen.
- Existing timing calibration/validation reports are immutable historical provenance. New recurrence reports are separate files.
- Missing months remain missing; observed zeroes remain observations. Do not impute either.
- Real cohort resampling unit is catchment, never cycle.
- A safety-gate failure stops promotion. Do not relax gates or relabel truth after results are known.
- Trough geometry stays unchanged and paused throughout this plan.
- Preserve user changes in the approved spec and unrelated untracked `case_studies/results/stress-test-full/` files.

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `docs/superpowers/specs/2026-09-03-recurrence-cluster-identifiability-design.md` | Approved design and audit corrections. | 1 |
| `tests/test_decision_policy_docs.py` | Pins approved recurrence design and unchanged 0.2.0 identity. | 1, 12 |
| `hydroseason/_recurrence_identifiability.py` | Pure candidate policy and clustering logic. | 2 |
| `tests/test_recurrence_identifiability.py` | Unit, invariant, corpus, calibration, and integration contracts. | 2-9 |
| `hydroseason/_timing_identifiability.py` | Window-level caller and final default-policy resolution. | 3, 9 |
| `hydroseason/_dynamic_year.py` | Full-cycle bounds and policy transport. | 3, 9 |
| `hydroseason/_recurrence_synthetic.py` | Independent truth-labelled recurrence corpus. | 4 |
| `hydroseason/_recurrence_calibration.py` | Metrics, selector, scoring, and fingerprint. | 5 |
| `scripts/run_calibration.py` | Recurrence calibration/validation CLI and generated-default writer. | 6-8 |
| `hydroseason/_scientific_defaults.py` | Generated selected recurrence policy, fingerprint, and scope. | 7, 12 |
| `docs/calibration/2026-09-03-recurrence-identifiability-calibration.json` | Frozen calibration evidence. | 7 |
| `docs/calibration/2026-09-03-recurrence-identifiability-validation.json` | Untouched validation evidence. | 8 |
| `docs/calibration/2026-09-03-recurrence-identifiability-promotion.json` | Scope-only fingerprint transition from validated candidate to established 0.2.0. | 12 |
| `scripts/audit_recurrence_impact.py` | Development-only before/after annual and record diff. | 10 |
| `docs/calibration/2026-09-03-recurrence-identifiability-impact.json` | Development impact report. | 10 |
| `case_studies/recurrence-identifiability/cohort-protocol.json` | Independent cycle-cohort inclusion, exclusion, sampling, and blinding contract. | 11 |
| `case_studies/recurrence-identifiability/review-rubric.md` | Frozen cycle labels and adjudication. | 11 |
| `scripts/build_recurrence_identifiability_cohort.py` | Builds observation-only cycle packets. | 11 |
| `scripts/evaluate_recurrence_identifiability_cohort.py` | Joins frozen labels after review and computes catchment-level evidence. | 11 |
| `tests/test_recurrence_identifiability_cohort.py` | Cohort blinding, hash, contradiction, and bootstrap tests. | 11 |
| `case_studies/results/recurrence-identifiability/` | Manifest, packets, frozen labels, hashes, and comparison report. | 11 |
| `docs/decision-policy-0.2.0.md` | Recurrence addendum and corrected evidence record. | 12 |
| `docs/decision-policy.md` | Launch-readiness record for corrected 0.2.0. | 12 |
| `docs/migrations/0.2.0-timing-identifiability.md` | Downstream effect of recurrence correction. | 12 |
| `docs/report-columns.md`, `CHANGELOG.md`, `mkdocs.yml` | User-facing semantics, release history, and navigation. | 12 |

---

### Task 1: Freeze Approved Design and Reopen the 0.2.0 Evidence Gate

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-recurrence-cluster-identifiability-design.md`
- Modify: `tests/test_decision_policy_docs.py`

**Interfaces:**
- Consumes: user-approved revised spec already present in the worktree.
- Produces: a committed design contract and a test that later documentation changes cannot silently erase its gates.

- [ ] **Step 1: Add the design-contract test**

Append:

```python
def test_recurrence_identifiability_design_freezes_the_020_correction():
    text = (
        ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-09-03-recurrence-cluster-identifiability-design.md"
    ).read_text(encoding="utf-8")
    required = {
        'RECURRENCE_CALIBRATION_SEEDS = range(50000, 55000)',
        'RECURRENCE_VALIDATION_SEEDS = range(60000, 65000)',
        '"no_narrowing"',
        '"long_window_last_cluster"',
        '"annual_shape_match"',
        "false-point Wilson upper bound <= 0.05",
        "false-resolution Wilson upper bound <= 0.05",
        "at least 0.90 genuine-recurrence status accuracy",
        "keep `ESTABLISHED_POLICY == \"established_0_2_0\"` throughout",
        "timing_identifiability_fingerprint()` must remain byte-identical",
    }
    missing = sorted(phrase for phrase in required if phrase not in text)
    assert not missing, f"approved recurrence design is missing: {missing}"
```

- [ ] **Step 2: Run the design test**

Run: `python -m pytest tests/test_decision_policy_docs.py -q -k recurrence_identifiability_design`

Expected: PASS. Failure means the approved user revision and test disagree; fix transcription only, never the approved rule.

- [ ] **Step 2b: Confirm the equal-span amendment is present and understood**

The spec carries **Audit Correction 13 (equal span)**, which adds one condition
to `annual_shape_match` beyond symmetric nearest-date distance. This changed an
already-approved rule, so verify with the user before building on it rather than
discovering it in Task 2.

Run: `python -m pytest tests/test_decision_policy_docs.py -q -k recurrence_identifiability_design`
and confirm the spec text contains `Audit Correction 13 (equal span)`.

If the user reverses the amendment, `annual_shape_match` fails the
false-resolution gate on `annual_aligned_fragment_trap` and the calibration
outcome is `no_narrowing` by construction; in that case say so in the Task 7
report rather than presenting a foregone result as a selection.

- [ ] **Step 3: Verify only approved design and test are staged**

Run:

```powershell
git diff --check
git status --short
git add -f docs/superpowers/specs/2026-09-03-recurrence-cluster-identifiability-design.md docs/superpowers/plans/2026-09-03-recurrence-identifiability-correction.md docs/superpowers/plans/2026-09-03-trough-geometry-reentry.md
git add tests/test_decision_policy_docs.py
git diff --cached --name-only
```

Expected staged paths: approved spec, both plans, and `tests/test_decision_policy_docs.py`; no stress-bundle files.

- [ ] **Step 4: Commit**

```bash
git commit -m "docs: freeze recurrence identifiability correction"
```

---

### Task 2: Implement Pure Recurrence Policies

**Files:**
- Create: `hydroseason/_recurrence_identifiability.py`
- Create: `tests/test_recurrence_identifiability.py`

**Interfaces:**
- Consumes: `linear_span_months(dates) -> int | None` from `hydroseason._circular_timing`.
- Produces: `RecurrencePolicy`, `ELIGIBLE_RECURRENCE_POLICIES`, and `narrow_most_recent_recurrence(...)` for production and calibration.

- [ ] **Step 1: Write failing policy tests**

Create the test module with these direct contracts:

```python
import pandas as pd
import pytest

from hydroseason._recurrence_identifiability import (
    ELIGIBLE_RECURRENCE_POLICIES,
    narrow_most_recent_recurrence,
)


def _dates(*values: str) -> tuple[pd.Timestamp, ...]:
    return tuple(pd.Timestamp(value) for value in values)


def _narrow(dates, *, policy, start="1990-01-01", end="1991-06-01", limit=2):
    return narrow_most_recent_recurrence(
        dates,
        window_start=pd.Timestamp(start),
        window_end=pd.Timestamp(end),
        max_boundary_interval_months=limit,
        policy=policy,
    )


def test_eligible_policy_order_is_frozen():
    assert ELIGIBLE_RECURRENCE_POLICIES == (
        "no_narrowing",
        "annual_shape_match",
        "long_window_last_cluster",
    )


def test_no_narrowing_returns_original_tuple_verbatim():
    dates = _dates("1991-04-01", "1990-04-01")
    assert _narrow(dates, policy="no_narrowing") is dates


def test_short_window_never_narrows():
    dates = _dates("1990-01-01", "1990-11-01")
    assert _narrow(
        dates, policy="long_window_last_cluster", end="1990-12-01"
    ) == dates


def test_long_window_legacy_ablation_keeps_last_resolved_cluster():
    dates = _dates("1990-04-01", "1991-03-01")
    assert _narrow(dates, policy="long_window_last_cluster") == _dates("1991-03-01")


def test_annual_shape_match_accepts_one_month_phase_drift():
    dates = _dates("1990-04-01", "1991-03-01")
    assert _narrow(dates, policy="annual_shape_match") == _dates("1991-03-01")


def test_annual_shape_match_rejects_large_cluster_plus_singleton():
    dates = _dates(
        "1992-05-01", "1992-06-01", "1992-07-01", "1992-08-01",
        "1992-09-01", "1993-01-01", "1993-04-01",
    )
    assert _narrow(
        dates,
        policy="annual_shape_match",
        start="1992-05-01",
        end="1993-10-01",
    ) == dates


def test_annual_shape_match_is_symmetric_for_interval_shapes():
    # An interval in the earlier year and a point in the later one is not the
    # same annual shape: the later year's remaining equivalent months may just
    # be missing.  Symmetric nearest-date distance alone accepts this pair
    # (every distance is <= 1); the equal-span requirement is what rejects it.
    dates = _dates("1990-03-01", "1990-04-01", "1991-03-01")
    assert _narrow(dates, policy="annual_shape_match") == dates


def test_annual_shape_match_declines_the_annual_aligned_fragment_trap():
    # Corpus family ``annual_aligned_fragment_trap`` (offsets 1, 2, 3, 13),
    # truth unresolved.  Candidate C must decline it while the legacy ablation
    # narrows it; that separation is the family's entire purpose.
    dates = _dates("1990-02-01", "1990-03-01", "1990-04-01", "1991-02-01")
    assert _narrow(dates, policy="annual_shape_match") == dates
    assert _narrow(
        dates, policy="long_window_last_cluster"
    ) == _dates("1991-02-01")


@pytest.mark.parametrize("dates", [(), _dates("1990-04-01")])
def test_empty_and_singleton_sets_are_unchanged(dates):
    assert _narrow(dates, policy="annual_shape_match") == dates


def test_one_cluster_is_unchanged():
    dates = _dates("1990-03-01", "1990-04-01", "1990-05-01")
    assert _narrow(dates, policy="annual_shape_match") == dates


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("1990-01-02", "1991-01-01", "month-start"),
        ("1991-01-01", "1990-01-01", "not precede"),
    ],
)
def test_invalid_caller_bounds_are_rejected(start, end, message):
    with pytest.raises(ValueError, match=message):
        _narrow(
            _dates("1990-04-01", "1991-04-01"),
            policy="annual_shape_match",
            start=start,
            end=end,
        )


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError, match="recurrence policy"):
        _narrow(_dates("1990-04-01", "1991-04-01"), policy="legacy_last_cluster")
```

- [ ] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_recurrence_identifiability.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'hydroseason._recurrence_identifiability'`.

- [ ] **Step 3: Implement the pure module**

Create:

```python
"""Pure policy for identifying annual recurrence in equivalent-extremum dates."""
from __future__ import annotations

from numbers import Integral
from typing import Literal, cast

import pandas as pd

from ._circular_timing import linear_span_months

RecurrencePolicy = Literal[
    "no_narrowing",
    "long_window_last_cluster",
    "annual_shape_match",
]

ELIGIBLE_RECURRENCE_POLICIES: tuple[RecurrencePolicy, ...] = (
    "no_narrowing",
    "annual_shape_match",
    "long_window_last_cluster",
)


def _month_start(value: pd.Timestamp, *, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp != stamp.to_period("M").to_timestamp():
        raise ValueError(f"{name} must be a month-start timestamp.")
    return stamp


def _clusters(
    dates: tuple[pd.Timestamp, ...], *, max_gap: int
) -> list[tuple[pd.Timestamp, ...]]:
    ordered = sorted(pd.Timestamp(date) for date in dates)
    if not ordered:
        return []
    result: list[list[pd.Timestamp]] = [[ordered[0]]]
    for date in ordered[1:]:
        gap = linear_span_months((result[-1][-1], date))
        if gap is not None and gap <= max_gap:
            result[-1].append(date)
        else:
            result.append([date])
    return [tuple(cluster) for cluster in result]


def _resolved(cluster: tuple[pd.Timestamp, ...], *, limit: int) -> bool:
    span = linear_span_months(cluster)
    return span is not None and span <= limit


def _covers(
    left: tuple[pd.Timestamp, ...], right: tuple[pd.Timestamp, ...], *, limit: int
) -> bool:
    return all(
        any(linear_span_months((item, candidate)) <= limit for candidate in right)
        for item in left
    )


def narrow_most_recent_recurrence(
    dates: tuple[pd.Timestamp, ...],
    *,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    max_boundary_interval_months: int,
    policy: RecurrencePolicy,
) -> tuple[pd.Timestamp, ...]:
    """Return dates unchanged unless ``policy`` proves an annual recurrence."""
    if policy not in ELIGIBLE_RECURRENCE_POLICIES:
        raise ValueError(f"unknown recurrence policy: {policy!r}")
    if (
        isinstance(max_boundary_interval_months, bool)
        or not isinstance(max_boundary_interval_months, Integral)
        or max_boundary_interval_months < 0
    ):
        raise ValueError("max_boundary_interval_months must be a non-negative integer.")
    start = _month_start(window_start, name="window_start")
    end = _month_start(window_end, name="window_end")
    if end < start:
        raise ValueError("window_end must not precede window_start.")
    if policy == "no_narrowing" or len(dates) < 2:
        return dates
    window_span = linear_span_months((start, end))
    if window_span is None or window_span < 12:
        return dates
    clusters = _clusters(dates, max_gap=int(max_boundary_interval_months))
    if len(clusters) < 2:
        return dates
    previous, latest = clusters[-2], clusters[-1]
    if not _resolved(latest, limit=int(max_boundary_interval_months)):
        return dates
    if policy == "long_window_last_cluster":
        return latest
    if not _resolved(previous, limit=int(max_boundary_interval_months)):
        return dates
    shifted = tuple(date + pd.DateOffset(months=12) for date in previous)
    limit = int(max_boundary_interval_months)
    if linear_span_months(shifted) != linear_span_months(latest):
        return dates
    if not (_covers(shifted, latest, limit=limit) and _covers(latest, shifted, limit=limit)):
        return dates
    return cast(tuple[pd.Timestamp, ...], latest)
```

The equal-span line is Audit Correction 13 in the spec and is load-bearing.
Both clusters are already capped at `max_boundary_interval_months`, so any two
of them a year apart satisfy `_covers` in both directions whatever their widths;
without the span test `annual_shape_match` narrows every
`annual_aligned_fragment_trap` record to a false point and is eliminated by its
own corpus before any evidence is weighed. Do not drop it to "simplify".

- [ ] **Step 4: Run unit tests**

Run: `python -m pytest tests/test_recurrence_identifiability.py -q`

Expected: all policy tests PASS.

- [ ] **Step 5: Check invariant mechanically**

Add this property-style finite sweep:

```python
def test_narrowed_dates_are_always_a_subset_of_input():
    base = pd.date_range("1990-01-01", periods=24, freq="MS")
    for mask in range(1, 1 << 8):
        dates = tuple(base[i] for i in range(8) if mask & (1 << i)) + (base[19],)
        for policy in ELIGIBLE_RECURRENCE_POLICIES:
            result = _narrow(dates, policy=policy, end="1991-12-01")
            assert set(result).issubset(dates)
```

Run: `python -m pytest tests/test_recurrence_identifiability.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add hydroseason/_recurrence_identifiability.py tests/test_recurrence_identifiability.py
git commit -m "feat: define recurrence identifiability policies"
```

---

### Task 3: Expose Candidate Policy Through the Production Window Path

**Files:**
- Modify: `hydroseason/_timing_identifiability.py:11-17,153-252`
- Modify: `hydroseason/_dynamic_year.py:24-33,71-99,652-667`
- Modify: `tests/test_recurrence_identifiability.py`
- Modify: `tests/test_timing_identifiability.py:277-329`
- Modify: `tests/test_dynamic_year.py`

**Interfaces:**
- Consumes: `RecurrencePolicy` and `narrow_most_recent_recurrence()` from Task 2.
- Produces: explicit candidate override on `assess_window_timing()` and `DynamicHydroYearConfig`, plus full-cycle bound forwarding. Omitted policy temporarily retains legacy behavior until Task 9 removes it after validation.

- [ ] **Step 1: Write failing caller tests**

Append to `tests/test_recurrence_identifiability.py`:

```python
import numpy as np

from hydroseason._timing_identifiability import (
    TimingIdentifiabilityThresholds,
    assess_window_timing,
)

WINDOW_THRESHOLDS = TimingIdentifiabilityThresholds(1.5, 1, 0, 2, 2)


def _window_result(values, index, *, policy, window_start=None, window_end=None):
    series = pd.Series(values, index=pd.to_datetime(index), dtype=float)
    rows = pd.DataFrame({"n_valid": 100}, index=series.index)
    return assess_window_timing(
        series,
        rows,
        thresholds=WINDOW_THRESHOLDS,
        measurement_tolerance_pct=1.0,
        noise_pp=0.0,
        pixel_support_status="unavailable",
        recurrence_policy=policy,
        window_start=window_start,
        window_end=window_end,
    )


def test_window_assessor_drives_explicit_candidate_policy():
    index = pd.date_range("1990-02-01", periods=18, freq="MS")
    values = [5.0] * 2 + [10.0] + [5.0] * 10 + [10.0] + [5.0] * 3 + [0.0]
    result = _window_result(values, index, policy="annual_shape_match")
    assert result.peak_status == "point"
    assert result.peak_dates == (pd.Timestamp("1991-03-01"),)


# Both bound tests need a window whose peak set is genuinely ``unresolved``,
# because that is the only branch that calls ``narrow_most_recent_recurrence()``
# at all.  ``[10, 5, 10]`` spans 2 months, which is within
# ``max_boundary_interval_months=2``, so it resolves to ``interval`` and the
# narrowing code is never reached; ``[10, 5, 5, 5, 10]`` spans 4 and is.


def test_derived_bounds_normalise_non_month_start_value_index():
    index = ["1990-01-15", "1990-02-15", "1990-03-15", "1990-04-15", "1990-05-15"]
    result = _window_result(
        [10.0, 5.0, 5.0, 5.0, 10.0], index, policy="no_narrowing"
    )
    assert result.detectable is True
    assert result.peak_status == "unresolved"
    assert result.peak_dates == (
        pd.Timestamp("1990-01-15"),
        pd.Timestamp("1990-05-15"),
    )


def test_explicit_non_month_start_bound_is_rejected():
    with pytest.raises(ValueError, match="month-start"):
        _window_result(
            [10.0, 5.0, 5.0, 5.0, 10.0],
            pd.date_range("1990-01-01", periods=5, freq="MS"),
            policy="no_narrowing",
            window_start=pd.Timestamp("1990-01-02"),
            window_end=pd.Timestamp("1990-05-01"),
        )
```

In `tests/test_dynamic_year.py`, add a monkeypatch test that captures bounds:

```python
def test_cycle_timing_passes_full_bounds_when_edge_months_are_unusable(monkeypatch):
    seen = []
    real = dynamic_year.assess_window_timing

    def capture(*args, **kwargs):
        seen.append((kwargs["window_start"], kwargs["window_end"]))
        return real(*args, **kwargs)

    monkeypatch.setattr(dynamic_year, "assess_window_timing", capture)
    frame = _anchored_frame_with_missing_cycle_edges()
    detect_dynamic_hydrological_years(
        frame,
        config=DynamicHydroYearConfig(
            expected_trough_month=7,
            recurrence_policy="no_narrowing",
        ),
    )
    assert seen
    assert all(start.day == end.day == 1 for start, end in seen)
    assert any((end.year - start.year) * 12 + end.month - start.month >= 12 for start, end in seen)
```

Implement `_anchored_frame_with_missing_cycle_edges()` beside existing dynamic-year frame helpers by creating 36 monthly rows with a July trough, December peak, and `invalid_pct=100.0` on the first and last observation inside the middle detected cycle. Do not omit the rows; the test proves bounds come from the full reindexed cycle.

- [ ] **Step 2: Run tests and verify red**

Run:

```powershell
python -m pytest tests/test_recurrence_identifiability.py tests/test_dynamic_year.py -q -k "candidate_policy or derived_bounds or explicit_non_month or full_bounds"
```

Expected: FAIL because new keywords/config field do not exist.

- [ ] **Step 3: Add explicit policy and bound parameters**

Change the window signature only; do not edit hashed helpers:

```python
def assess_window_timing(
    values: pd.Series,
    rows: pd.DataFrame,
    *,
    thresholds: TimingIdentifiabilityThresholds,
    measurement_tolerance_pct: float,
    noise_pp: float,
    pixel_support_status: PixelSupportStatus,
    recurrence_policy: RecurrencePolicy | None = None,
    window_start: pd.Timestamp | None = None,
    window_end: pd.Timestamp | None = None,
) -> WindowTimingEvidence:
```

Resolve bounds lazily, so a window that never narrows keeps the documented
"any index, not necessarily calendar-aligned" contract:

```python
    def _recurrence_bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
        start = (
            pd.Timestamp(values.index.min()).to_period("M").to_timestamp()
            if window_start is None
            else pd.Timestamp(window_start)
        )
        end = (
            pd.Timestamp(values.index.max()).to_period("M").to_timestamp()
            if window_end is None
            else pd.Timestamp(window_end)
        )
        return start, end
```

Call it inside each unresolved branch, not at the top of the function: deriving
bounds unconditionally would make every non-datetime-indexed caller raise even
when no narrowing is attempted.

At both unresolved branches, use the explicit candidate when supplied; retain the current helper only as the temporary omitted-policy path:

```python
        if recurrence_policy is None:
            narrowed = _most_recent_recurrence_cluster(peak_dates, thresholds)
        else:
            recurrence_start, recurrence_end = _recurrence_bounds()
            narrowed = narrow_most_recent_recurrence(
                peak_dates,
                window_start=recurrence_start,
                window_end=recurrence_end,
                max_boundary_interval_months=thresholds.max_boundary_interval_months,
                policy=recurrence_policy,
            )
```

Repeat identically for trough dates. Keep caller `_window_status()` recomputation unchanged.

- [ ] **Step 4: Thread full cycle bounds through dynamic-year configuration**

Import `RecurrencePolicy`, then add to `DynamicHydroYearConfig`:

```python
    recurrence_policy: RecurrencePolicy | None = None
```

Forward from `_cycle_timing_evidence()`:

```python
        recurrence_policy=config.recurrence_policy,
        window_start=pd.Timestamp(cycle.index[0]),
        window_end=pd.Timestamp(cycle.index[-1]),
```

Do not change `_assemble_dynamic_years()` or any boundary selector.

- [ ] **Step 5: Make existing positive test explicit**

In `test_window_timing_recovers_a_recurring_peak_in_an_oversized_cycle`, add:

```python
        recurrence_policy="annual_shape_match",
```

The test now pins Candidate C, not the temporary legacy default.

- [ ] **Step 6: Run focused and regression tests**

Run:

```powershell
python -m pytest tests/test_recurrence_identifiability.py tests/test_timing_identifiability.py tests/test_dynamic_year.py -q
python -m pytest tests/test_catchment_analysis.py tests/test_hydro_year.py tests/test_hydro_year_geometry.py -q
```

Expected: PASS. Existing omitted-policy behavior remains unchanged until Task 9.

- [ ] **Step 7: Prove timing threshold fingerprint did not move**

Run:

```powershell
python -c "from hydroseason._calibration import timing_identifiability_fingerprint; print(timing_identifiability_fingerprint())"
```

Expected exact output: `e6cdf3ce960aa011711dc90e3ef4fb0135513eadaf471f4ac9e0656f80884735`.

- [ ] **Step 8: Commit**

```bash
git add hydroseason/_timing_identifiability.py hydroseason/_dynamic_year.py tests/test_recurrence_identifiability.py tests/test_timing_identifiability.py tests/test_dynamic_year.py
git commit -m "feat: evaluate recurrence candidates through window timing"
```

---

### Task 4: Build Independent Recurrence Truth Corpus

**Files:**
- Create: `hydroseason/_recurrence_synthetic.py`
- Modify: `tests/test_recurrence_identifiability.py`

**Interfaces:**
- Consumes: existing `TimingIdentifiabilityThresholds` and `assess_window_timing()` explicit policy override.
- Produces: `RECURRENCE_CALIBRATION_SEEDS`, `RECURRENCE_VALIDATION_SEEDS`, `RECURRENCE_FAMILIES`, `RecurrenceTruth`, `RecurrenceSyntheticRecord`, and `generate_recurrence_record()`.

- [ ] **Step 1: Write failing corpus tests**

Append:

```python
from hydroseason._recurrence_synthetic import (
    RECURRENCE_CALIBRATION_SEEDS,
    RECURRENCE_FAMILIES,
    RECURRENCE_VALIDATION_SEEDS,
    generate_recurrence_record,
)
from hydroseason._synthetic import (
    CALIBRATION_SEEDS,
    GEOMETRY_CALIBRATION_SEEDS,
    GEOMETRY_VALIDATION_SEEDS,
    VALIDATION_SEEDS,
)


def test_recurrence_seed_partitions_are_disjoint_from_every_existing_corpus():
    groups = [
        set(CALIBRATION_SEEDS), set(VALIDATION_SEEDS),
        set(GEOMETRY_CALIBRATION_SEEDS), set(GEOMETRY_VALIDATION_SEEDS),
        set(RECURRENCE_CALIBRATION_SEEDS), set(RECURRENCE_VALIDATION_SEEDS),
    ]
    assert all(left.isdisjoint(right) for i, left in enumerate(groups) for right in groups[i + 1 :])


def test_first_960_seeds_balance_eight_families_exactly():
    records = [generate_recurrence_record(seed, partition="calibration") for seed in range(50000, 50960)]
    counts = pd.Series([record.family for record in records]).value_counts().to_dict()
    assert set(counts) == set(RECURRENCE_FAMILIES)
    assert set(counts.values()) == {120}


def test_recurrence_truth_is_generator_owned_and_reachable():
    for offset, family in enumerate(RECURRENCE_FAMILIES):
        record = generate_recurrence_record(50000 + offset, partition="calibration")
        assert record.family == family
        assert record.window_start <= record.values.index.min()
        assert record.values.index.max() <= record.window_end
        if family.startswith("annual_") and family != "annual_aligned_fragment_trap":
            assert record.truth.status in {"point", "interval"}
            assert record.truth.latest_dates
        else:
            assert record.truth.status == "unresolved"
            assert record.truth.latest_dates == ()


def test_corpus_is_deterministic_and_partitions_differ():
    first = generate_recurrence_record(50007, partition="calibration")
    again = generate_recurrence_record(50007, partition="calibration")
    validation = generate_recurrence_record(60007, partition="validation")
    pd.testing.assert_series_equal(first.values, again.values)
    pd.testing.assert_frame_equal(first.rows, again.rows)
    assert first.truth == again.truth
    assert not first.values.equals(validation.values) or first.window_end != validation.window_end
```

- [ ] **Step 2: Run corpus tests and verify red**

Run: `python -m pytest tests/test_recurrence_identifiability.py -q -k "seed_partitions or 960 or generator_owned or corpus_is"`

Expected: import failure for `_recurrence_synthetic`.

- [ ] **Step 3: Define corpus types and frozen families**

Create the module with these public structures:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._timing_identifiability import (
    PixelSupportStatus,
    TimingIdentifiabilityThresholds,
    TimingStatus,
)

RECURRENCE_CALIBRATION_SEEDS = range(50000, 55000)
RECURRENCE_VALIDATION_SEEDS = range(60000, 65000)

RECURRENCE_FAMILIES = (
    "annual_point_recurrence",
    "annual_interval_recurrence",
    "annual_phase_drift",
    "ordinary_gap_fragmented_plateau",
    "long_gap_fragmented_plateau",
    "annual_aligned_fragment_trap",
    "scattered_equivalent_ties",
    "single_diffuse_cluster",
)


@dataclass(frozen=True)
class RecurrenceTruth:
    kind: Literal["peak", "trough"]
    status: TimingStatus
    latest_dates: tuple[pd.Timestamp, ...]


@dataclass(frozen=True)
class RecurrenceSyntheticRecord:
    seed: int
    family: str
    values: pd.Series
    rows: pd.DataFrame
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    thresholds: TimingIdentifiabilityThresholds
    measurement_tolerance_pct: float
    noise_pp: float
    pixel_support_status: PixelSupportStatus
    truth: RecurrenceTruth
```

- [ ] **Step 4: Implement construction from frozen offset recipes**

Use this exact family table; offsets are months from the window start and list every equivalent extremum before masking:

```python
_RECIPES = {
    "annual_point_recurrence": ((3,), (15,), "point"),
    "annual_interval_recurrence": ((2, 3), (14, 15), "interval"),
    "annual_phase_drift": ((3,), (14,), "point"),
    "ordinary_gap_fragmented_plateau": ((0, 1, 2, 3, 4, 8, 11), (), "unresolved"),
    "long_gap_fragmented_plateau": ((0, 1, 2, 6, 9, 13, 17), (), "unresolved"),
    "annual_aligned_fragment_trap": ((1, 2, 3, 13), (), "unresolved"),
    "scattered_equivalent_ties": ((1, 5, 9, 16), (), "unresolved"),
    "single_diffuse_cluster": ((4, 5, 6, 7, 8), (), "unresolved"),
}
```

Assign the family by `RECURRENCE_FAMILIES[seed % len(RECURRENCE_FAMILIES)]`.
Both partition bases are multiples of eight, so seeds `50000..50959` and
`60000..60959` each give exactly 120 records per family, which is what
`test_first_960_seeds_balance_eight_families_exactly` and the fixed
family/seed pairings in the other corpus tests assume.

For families 1--3, the two tuples are prior/latest clusters and `truth.latest_dates` is built from the second tuple. For families 4--8, the first tuple is the complete truth-unresolved equivalent set and latest dates stays empty. Apply deterministic variations without changing family truth:

```python
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0x52454355]))
    kind = "peak" if (seed // len(RECURRENCE_FAMILIES)) % 2 == 0 else "trough"
    pixel_support_status = "available" if (seed // 16) % 2 == 0 else "unavailable"
    max_interval = 2 + int((seed // 32) % 2)
    window_positions = 12 if family == "ordinary_gap_fragmented_plateau" else 13 + int(rng.integers(0, 8))
```

For any recipe offset outside a randomly selected window, increase `window_positions` to `max_offset + 1`; never truncate truth. Set baseline to 40, peaks to 70, troughs to 10, and the equivalent constructed dates to 70 for peak records or 10 for trough records. Put the opposite single extremum six months away where possible so amplitude remains detectable. Remove two non-extremum interior observation dates on every third seed; retain `window_start`/`window_end` separately. For count-backed records emit all four count columns with `n_valid=n_aoi=100`, `n_invalid=0`, and `n_water` equal to integer extent. For percentage-only records emit only `n_valid` so the assessor is called with `pixel_support_status="unavailable"`.

Use `TimingIdentifiabilityThresholds(1.5, 1, 0, max_interval, 2)`, `measurement_tolerance_pct=1.0`, and `noise_pp=0.0`. Reject seeds outside the requested partition before constructing any RNG.

- [ ] **Step 5: Add corpus-level behavioral separation tests**

Append:

```python
def _assess_record(record, policy):
    result = assess_window_timing(
        record.values,
        record.rows,
        thresholds=record.thresholds,
        measurement_tolerance_pct=record.measurement_tolerance_pct,
        noise_pp=record.noise_pp,
        pixel_support_status=record.pixel_support_status,
        recurrence_policy=policy,
        window_start=record.window_start,
        window_end=record.window_end,
    )
    return (
        (result.peak_status, result.peak_dates)
        if record.truth.kind == "peak"
        else (result.trough_status, result.trough_dates)
    )


def test_legacy_ablation_fails_fragmented_negative_control():
    record = generate_recurrence_record(50003, partition="calibration")
    status, _dates = _assess_record(record, "long_window_last_cluster")
    assert record.family == "ordinary_gap_fragmented_plateau"
    assert status == "unresolved"  # short-window gate must defeat legacy narrowing


def test_annual_shape_candidate_recovers_positive_families():
    for offset in range(3):
        record = generate_recurrence_record(50000 + offset, partition="calibration")
        status, dates = _assess_record(record, "annual_shape_match")
        assert status == record.truth.status
        assert dates == record.truth.latest_dates
```

Run: `python -m pytest tests/test_recurrence_identifiability.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add hydroseason/_recurrence_synthetic.py tests/test_recurrence_identifiability.py
git commit -m "test: add independent recurrence truth corpus"
```

---

### Task 5: Implement Recurrence Scoring, Selection, and Fingerprint

**Files:**
- Create: `hydroseason/_recurrence_calibration.py`
- Modify: `tests/test_recurrence_identifiability.py`

**Interfaces:**
- Consumes: Task 3 production assessor and Task 4 corpus.
- Produces: `RecurrencePolicyScore`, `score_recurrence_policy()`, `select_recurrence_policy()`, and `recurrence_fingerprint()`.

- [ ] **Step 1: Write failing score and selector tests**

Append tests using hand-built `RecurrenceEvaluation` rows:

```python
from hydroseason._recurrence_calibration import (
    RecurrenceEvaluation,
    recurrence_fingerprint,
    score_recurrence_policy,
    select_recurrence_policy,
)


def _evaluation(policy, truth, predicted, exact=False, family="fixture"):
    return RecurrenceEvaluation(
        policy=policy,
        family=family,
        kind="trough",
        pixel_support_status="unavailable",
        truth_status=truth,
        predicted_status=predicted,
        exact_latest_dates=exact,
    )


def test_false_point_and_false_resolution_denominators_are_distinct():
    rows = [
        _evaluation("annual_shape_match", "interval", "point"),
        _evaluation("annual_shape_match", "unresolved", "interval"),
        _evaluation("annual_shape_match", "point", "point", exact=True),
    ]
    score = score_recurrence_policy(rows, "annual_shape_match")
    assert (score.false_point_k, score.false_point_n) == (1, 2)
    assert (score.false_resolution_k, score.false_resolution_n) == (1, 1)
    # Denominator is every genuine-recurrence row, not just the ones the policy
    # got right: the interval row predicted as a point counts against it.
    assert score.exact_latest_date_accuracy == 0.5


def test_selector_rejects_unsafe_accuracy_winner():
    safe = [_evaluation("no_narrowing", "unresolved", "unresolved") for _ in range(120)]
    unsafe = [_evaluation("annual_shape_match", "unresolved", "point") for _ in range(120)]
    policy, score, counts = select_recurrence_policy(safe + unsafe)
    assert policy == "no_narrowing"
    assert score.false_point_k == 0
    assert counts["false_point_wilson"] == 1


def test_selector_prefers_exact_recovery_after_safety_gates():
    rows = []
    for policy, exact in (("no_narrowing", False), ("annual_shape_match", True)):
        rows.extend(_evaluation(policy, "unresolved", "unresolved") for _ in range(120))
        rows.extend(_evaluation(policy, "point", "point" if exact else "unresolved", exact=exact) for _ in range(120))
    policy, _score, counts = select_recurrence_policy(rows)
    assert policy == "annual_shape_match"
    assert counts["exact_latest_date_accuracy"] == 1


def test_fingerprint_changes_with_metrics_seed_or_policy():
    metrics = {"false_point_k": 0, "false_point_n": 120}
    base = recurrence_fingerprint("annual_shape_match", seeds=list(range(50000, 50960)), metrics=metrics)
    assert base != recurrence_fingerprint("no_narrowing", seeds=list(range(50000, 50960)), metrics=metrics)
    assert base != recurrence_fingerprint("annual_shape_match", seeds=list(range(50000, 50959)), metrics=metrics)
    assert base != recurrence_fingerprint("annual_shape_match", seeds=list(range(50000, 50960)), metrics={"false_point_k": 1, "false_point_n": 120})
```

- [ ] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_recurrence_identifiability.py -q -k "denominators or selector or fingerprint"`

Expected: import failure for `_recurrence_calibration`.

- [ ] **Step 3: Implement evaluation and score records**

Define:

```python
@dataclass(frozen=True)
class RecurrenceEvaluation:
    policy: RecurrencePolicy
    family: str
    kind: Literal["peak", "trough"]
    pixel_support_status: PixelSupportStatus
    truth_status: TimingStatus
    predicted_status: TimingStatus
    exact_latest_dates: bool


@dataclass(frozen=True)
class RecurrencePolicyScore:
    policy: RecurrencePolicy
    false_point_k: int
    false_point_n: int
    false_point_rate: float
    false_point_wilson: tuple[float, float]
    false_resolution_k: int
    false_resolution_n: int
    false_resolution_rate: float
    false_resolution_wilson: tuple[float, float]
    genuine_recurrence_status_accuracy: float
    exact_latest_date_accuracy: float
    conservative_abstention_rate: float
    by_family: dict[str, dict[str, int | float]]
    by_kind: dict[str, dict[str, int | float]]
    by_pixel_support: dict[str, dict[str, int | float]]
```

`evaluate_recurrence_records(records, policies)` must call `assess_window_timing(..., recurrence_policy=policy, window_start=..., window_end=...)` for every pair and compare the peak or trough fields named by truth. Do not call `narrow_most_recent_recurrence()` directly in calibration.

Compute Wilson intervals with existing `hydroseason._calibration.wilson_interval`. A false-point denominator contains truth `interval` or `unresolved`; a false-resolution denominator contains truth `unresolved`; genuine recurrence metrics contain truth `point` or `interval`; conservative abstention is correct `unresolved` over truth-unresolved rows.

State both genuine-recurrence denominators explicitly, because the selector
ranks on them:

- `genuine_recurrence_status_accuracy` = rows whose `predicted_status` equals
  `truth_status`, over **all** rows with truth `point` or `interval`.
- `exact_latest_date_accuracy` = rows with `predicted_status == truth_status`
  **and** `exact_latest_dates`, over **all** rows with truth `point` or
  `interval`.

Both denominators are the full genuine-row count, never "rows the policy
resolved correctly". Conditioning on the policy's own successes would let a
candidate that resolves one record exactly and abstains on the other 119 score
1.0 and outrank a candidate that recovers 119 of 120. Return `0.0` when a
denominator is zero; do not return `nan`, which would silently defeat the
`np.isclose` tie-break.

- [ ] **Step 4: Implement exact selector**

Use:

```python
def select_recurrence_policy(
    evaluations: Sequence[RecurrenceEvaluation],
) -> tuple[RecurrencePolicy, RecurrencePolicyScore, dict[str, int]]:
    scores = [score_recurrence_policy(evaluations, policy) for policy in ELIGIBLE_RECURRENCE_POLICIES]
    survivors = [score for score in scores if score.false_point_wilson[1] <= 0.05]
    counts = {"candidates": len(scores), "false_point_wilson": len(survivors)}
    survivors = [score for score in survivors if score.false_resolution_wilson[1] <= 0.05]
    counts["false_resolution_wilson"] = len(survivors)
    if not survivors:
        raise RuntimeError("no recurrence policy satisfies both false-precision safety gates")
    for name in (
        "exact_latest_date_accuracy",
        "genuine_recurrence_status_accuracy",
        "conservative_abstention_rate",
    ):
        best = max(getattr(score, name) for score in survivors)
        survivors = [score for score in survivors if np.isclose(getattr(score, name), best)]
        counts[name] = len(survivors)
    rank = {policy: index for index, policy in enumerate(ELIGIBLE_RECURRENCE_POLICIES)}
    selected = min(survivors, key=lambda score: rank[score.policy])
    counts["conservative_policy_order"] = 1
    return selected.policy, selected, counts
```

- [ ] **Step 5: Implement fingerprint including calibration metrics**

`recurrence_fingerprint(policy, *, seeds, metrics, authority_scope="candidate_for_established_0_2_0")` hashes, in stable order:

```python
for item in (
    recurrence_synthetic.RecurrenceTruth,
    recurrence_synthetic.RecurrenceSyntheticRecord,
    recurrence_synthetic.generate_recurrence_record,
    recurrence_metrics.narrow_most_recent_recurrence,
    recurrence_metrics._clusters,
    recurrence_metrics._covers,
    RecurrenceEvaluation,
    RecurrencePolicyScore,
    evaluate_recurrence_records,
    score_recurrence_policy,
    select_recurrence_policy,
):
    hasher.update(inspect.getsource(item).encode("utf-8"))
hasher.update(json.dumps(list(seeds)).encode("utf-8"))
hasher.update(json.dumps(metrics, sort_keys=True).encode("utf-8"))
hasher.update(policy.encode("utf-8"))
hasher.update(authority_scope.encode("utf-8"))
```

Set `RECURRENCE_AUTHORITY_SCOPE = "candidate_for_established_0_2_0"` in `_recurrence_calibration.py` and use it as the call-site default during calibration and validation. Validation seeds and truth must not enter the hash.

- [ ] **Step 6: Run focused tests**

Run: `python -m pytest tests/test_recurrence_identifiability.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add hydroseason/_recurrence_calibration.py tests/test_recurrence_identifiability.py
git commit -m "feat: score and select recurrence policies"
```

---

### Task 6: Add Calibration Runner and Safe Generated-Defaults Writer

**Files:**
- Modify: `scripts/run_calibration.py:345-388,391-480,573-632`
- Modify: `tests/test_calibration.py`
- Modify: `tests/test_scientific_defaults.py`

**Interfaces:**
- Consumes: Task 5 selector/fingerprint and Task 4 seed partitions.
- Produces: `_write_recurrence_defaults()`, `run_recurrence_calibration()`, `run_recurrence_validation()`, and CLI `--recurrence-identifiability`.

- [ ] **Step 1: Write failing runner tests**

Add tests that load `scripts/run_calibration.py` using the existing module loader pattern:

```python
def test_recurrence_runner_writes_report_and_appends_defaults(tmp_path):
    module = _load_run_calibration_module()
    defaults_path = tmp_path / "_scientific_defaults.py"
    defaults_path.write_text("# GENERATED\nKEEP = 1\n", encoding="utf-8")
    report_path = tmp_path / "recurrence.json"
    module.run_recurrence_calibration(
        seeds=list(range(50000, 50080)),
        out_report=report_path,
        out_module=defaults_path,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    text = defaults_path.read_text(encoding="utf-8")
    assert payload["partition"] == "calibration"
    assert payload["selected_policy"] in {
        "no_narrowing", "annual_shape_match", "long_window_last_cluster"
    }
    assert "KEEP = 1" in text
    assert "RECURRENCE_POLICY" in text
    assert payload["fingerprint"] in text


def test_recurrence_validation_refuses_stale_fingerprint_before_building_corpus(tmp_path, monkeypatch):
    module = _load_run_calibration_module()
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(
        json.dumps(
            {
                "selected_policy": "annual_shape_match",
                "fingerprint": "frozen",
                "seeds": list(range(50000, 50960)),
                "metrics": {"false_point_k": 0, "false_point_n": 120},
                "authority_scope": "candidate_for_established_0_2_0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "recurrence_fingerprint", lambda *args, **kwargs: "changed")
    monkeypatch.setattr(
        module,
        "generate_recurrence_record",
        lambda *args, **kwargs: pytest.fail("validation corpus was read before staleness check"),
    )
    with pytest.raises(RuntimeError, match="recurrence fingerprint"):
        module.run_recurrence_validation(
            seeds=list(range(60000, 60960)),
            out_report=tmp_path / "validation.json",
            calibration_report=calibration_path,
            frozen_policy="annual_shape_match",
            frozen_fingerprint="frozen",
        )
```

Add a writer-order regression using the real writer functions and `TroughGeometry(3, 5, 6)`; run timing writer first, recurrence writer second, geometry writer third, then assert the temporary module contains `TIMING_IDENTIFIABILITY_DEFAULTS`, `RECURRENCE_POLICY`, and `TROUGH_GEOMETRY_DEFAULTS` exactly once each.

- [ ] **Step 2: Run runner tests and verify red**

Run: `python -m pytest tests/test_calibration.py tests/test_scientific_defaults.py -q -k "recurrence_runner or recurrence_validation or writer_order"`

Expected: FAIL because recurrence runner/writer do not exist.

- [ ] **Step 3: Implement idempotent appending writer**

Add fixed markers and replace only the recurrence block on repeat runs:

```python
_RECURRENCE_BLOCK_START = "# BEGIN RECURRENCE IDENTIFIABILITY DEFAULTS"
_RECURRENCE_BLOCK_END = "# END RECURRENCE IDENTIFIABILITY DEFAULTS"


def _write_recurrence_defaults(
    out_module: Path,
    *,
    policy: str,
    recurrence_fingerprint_value: str,
    authority_scope: str = "candidate_for_established_0_2_0",
) -> None:
    path = Path(out_module)
    text = path.read_text(encoding="utf-8")
    block = (
        f"{_RECURRENCE_BLOCK_START}\n"
        "from hydroseason._recurrence_identifiability import RecurrencePolicy\n\n"
        f"RECURRENCE_AUTHORITY_SCOPE = {authority_scope!r}\n"
        f"RECURRENCE_FINGERPRINT = {recurrence_fingerprint_value!r}\n"
        f"RECURRENCE_POLICY: RecurrencePolicy = {policy!r}\n"
        f"{_RECURRENCE_BLOCK_END}"
    )
    if _RECURRENCE_BLOCK_START in text:
        prefix, remainder = text.split(_RECURRENCE_BLOCK_START, 1)
        _old, suffix = remainder.split(_RECURRENCE_BLOCK_END, 1)
        text = prefix.rstrip() + "\n\n" + block + suffix
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Give the geometry writer markers, then preserve both blocks**

`_write_trough_geometry_defaults()` (`scripts/run_calibration.py:376-388`) is
append-only and has no delimiters, so there is nothing for a preserve step to
capture and a second geometry calibration run appends a duplicate
`TROUGH_GEOMETRY_DEFAULTS` rather than replacing it. Fix the geometry writer
first, exactly as the recurrence writer is written above:

```python
_GEOMETRY_BLOCK_START = "# BEGIN TROUGH GEOMETRY DEFAULTS"
_GEOMETRY_BLOCK_END = "# END TROUGH GEOMETRY DEFAULTS"
```

Wrap the existing geometry block in those markers and use the same
split-on-marker replace-or-append body. The emitted constants
(`TROUGH_GEOMETRY_AUTHORITY_SCOPE`, `TROUGH_GEOMETRY_FINGERPRINT`,
`TROUGH_GEOMETRY_DEFAULTS`) and their values must not change: no fingerprint
hashes `scripts/run_calibration.py`, but `TROUGH_GEOMETRY_AUTHORITY_SCOPE` stays
exactly `candidate_for_established_0_3_0`.

Then, before `_write_timing_identifiability_defaults()` overwrites its output,
capture any existing recurrence and geometry blocks and append them after the
newly generated timing text, recurrence first and geometry second.

The writer-order test must call the functions in runner order, then call the
timing writer a second time, then call the geometry writer a second time; after
all of it `TIMING_IDENTIFIABILITY_DEFAULTS`, `RECURRENCE_POLICY`, and
`TROUGH_GEOMETRY_DEFAULTS` must each occur exactly once.

- [ ] **Step 5: Implement report payload and runners**

Calibration builds 960 records, evaluates all eligible policies plus a report-only local `legacy_last_cluster`, selects only eligible policies, serializes `asdict(score)`, computes fingerprint from the explicit 960 seeds and selected score metrics, writes report, then appends defaults.

`candidate_scores` in the payload below is the list of `RecurrencePolicyScore`
records for `ELIGIBLE_RECURRENCE_POLICIES`, in that frozen order. The
report-only ablation is added to the same dict afterwards under the separate
key `legacy_last_cluster_report_only`; it is never an element of
`candidate_scores` and never reaches `select_recurrence_policy()`.

Keep the ablation out of `RecurrencePolicy` and `ELIGIBLE_RECURRENCE_POLICIES`. Implement it only in `_recurrence_calibration.py`:

```python
def legacy_last_cluster(
    dates: Sequence[pd.Timestamp], *, max_boundary_interval_months: int
) -> tuple[pd.Timestamp, ...]:
    ordered = tuple(sorted(pd.Timestamp(value) for value in dates))
    if len(ordered) <= 1:
        return ordered
    clusters = recurrence_metrics._clusters(
        ordered, max_gap=max_boundary_interval_months
    )
    latest = clusters[-1]
    return latest if recurrence_metrics._resolved(
        latest, limit=max_boundary_interval_months
    ) else ordered
```

`evaluate_legacy_records(records)` must use that helper in place of candidate narrowing, then call the same `_window_status` recomputation and truth-comparison adapter used by `evaluate_recurrence_records()`. Serialize its score under `candidate_metrics["legacy_last_cluster_report_only"]`; never pass it to `select_recurrence_policy()` and never write it as a default.

Use report keys:

```python
{
    "calibration_version": "0.2.0-recurrence-identifiability.1",
    "partition": "calibration" | "validation",
    "seeds": seeds,
    "generated": _utc_timestamp(),
    "environment": calibration_environment(),
    "authority_scope": RECURRENCE_AUTHORITY_SCOPE,
    "selected_policy": policy,
    "fingerprint": fingerprint,
    "selection_counts": counts,
    "metrics": asdict(score),
    "candidate_metrics": {score.policy: asdict(score) for score in candidate_scores},
    "inputs": {
        "inspected_stress_bundle": "excluded",
        "protected_catchments": "excluded",
        "motivating_records": "excluded",
        "existing_cohort": "excluded",
        "annual_alignment_tolerance": "max_boundary_interval_months",
        "fingerprint_includes_metrics": True,
    },
}
```

Validation accepts `calibration_report: Path`, loads its frozen calibration metrics to recompute the fingerprint before generating any validation record, evaluates only the frozen policy, sets `candidate_metrics` to one policy, and sets `selection_counts={"reselection": 0}`.

- [ ] **Step 6: Add CLI dispatch**

Add:

```python
parser.add_argument("--recurrence-identifiability", action="store_true")
parser.add_argument("--num-recurrence-seeds", type=int, default=960)
```

Dispatch before trough geometry:

```python
if args.recurrence_identifiability:
    base = 60000 if args.partition == "validation" else 50000
    recurrence_seeds = list(range(base, base + args.num_recurrence_seeds))
    if args.partition == "validation":
        run_recurrence_validation(
            seeds=recurrence_seeds,
            out_report=Path(args.out_report or "docs/calibration/2026-09-03-recurrence-identifiability-validation.json"),
            calibration_report=Path("docs/calibration/2026-09-03-recurrence-identifiability-calibration.json"),
        )
    else:
        run_recurrence_calibration(
            seeds=recurrence_seeds,
            out_report=Path(args.out_report or "docs/calibration/2026-09-03-recurrence-identifiability-calibration.json"),
            out_module=Path(args.out_module),
        )
```

Make recurrence, geometry, timing, and legacy calibration flags mutually exclusive; raise parser error when more than one is supplied.

- [ ] **Step 7: Run runner/default tests**

Run:

```powershell
python -m pytest tests/test_calibration.py tests/test_scientific_defaults.py tests/test_recurrence_identifiability.py -q -k "recurrence or writer_order or timing_calibration_and_untouched"
```

Expected: PASS, including unchanged timing artifact freshness.

- [ ] **Step 8: Commit**

```bash
git add scripts/run_calibration.py tests/test_calibration.py tests/test_scientific_defaults.py tests/test_recurrence_identifiability.py
git commit -m "feat: add recurrence calibration workflow"
```

---

### Task 7: Run Calibration and Freeze the Candidate Policy

**Gate:** run calibration, report exact output, and stop for user approval before touching validation.

**Files:**
- Modify (generated): `hydroseason/_scientific_defaults.py`
- Create: `docs/calibration/2026-09-03-recurrence-identifiability-calibration.json`
- Modify: `tests/test_scientific_defaults.py`

**Interfaces:**
- Consumes: Tasks 2-6 and seeds `50000..50959`.
- Produces: frozen `RECURRENCE_POLICY`, `RECURRENCE_FINGERPRINT`, candidate scope, and calibration report.

- [ ] **Step 1: Run exactly 960 calibration seeds**

Run:

```powershell
python scripts\run_calibration.py --recurrence-identifiability --partition calibration --num-recurrence-seeds 960 --out-report docs\calibration\2026-09-03-recurrence-identifiability-calibration.json
```

Expected: exit 0; report and generated recurrence block written. If no candidate survives both Wilson gates, stop: do not run validation and do not alter gates.

- [ ] **Step 2: Print exact selected evidence**

Run:

```powershell
python -c "import json; p=json.load(open('docs/calibration/2026-09-03-recurrence-identifiability-calibration.json')); print(p['selected_policy']); print(p['fingerprint']); print(json.dumps(p['selection_counts'], indent=2)); print(json.dumps(p['metrics'], indent=2))"
```

Record exact selected policy, fingerprint, both Wilson intervals, exact-date accuracy, status accuracy, abstention, and selector survivor counts. A `no_narrowing` result is publishable and must be called a null recovery result.

- [ ] **Step 3: Add artifact freshness test without inventing literals**

Append:

```python
RECURRENCE_CALIBRATION_REPORT = Path(
    "docs/calibration/2026-09-03-recurrence-identifiability-calibration.json"
)


def test_recurrence_calibration_artifact_matches_generated_defaults():
    from hydroseason._recurrence_calibration import recurrence_fingerprint

    payload = json.loads(RECURRENCE_CALIBRATION_REPORT.read_text(encoding="utf-8"))
    assert payload["selected_policy"] == defaults.RECURRENCE_POLICY
    assert payload["fingerprint"] == defaults.RECURRENCE_FINGERPRINT
    assert payload["authority_scope"] == "candidate_for_established_0_2_0"
    assert payload["seeds"] == list(range(50000, 50960))
    assert recurrence_fingerprint(
        defaults.RECURRENCE_POLICY,
        seeds=payload["seeds"],
        metrics=payload["metrics"],
    ) == defaults.RECURRENCE_FINGERPRINT
```

- [ ] **Step 4: Reconfirm threshold fingerprint**

Run:

```powershell
python -m pytest tests/test_scientific_defaults.py -q
python -c "from hydroseason._calibration import timing_identifiability_fingerprint; assert timing_identifiability_fingerprint() == 'e6cdf3ce960aa011711dc90e3ef4fb0135513eadaf471f4ac9e0656f80884735'"
```

Expected: PASS.

- [ ] **Step 5: Report and stop**

Do not commit yet and do not run validation. Ask user to approve opening untouched validation with the frozen candidate.

---

### Task 8: Run Untouched Validation Once

**Gate:** requires explicit Task 7 approval. Run once; any failure stops production integration.

**Files:**
- Create: `docs/calibration/2026-09-03-recurrence-identifiability-validation.json`
- Modify: `tests/test_scientific_defaults.py`

**Interfaces:**
- Consumes: frozen Task 7 policy/fingerprint and seeds `60000..60959`.
- Produces: report-only validation evidence with no reselection.

- [ ] **Step 1: Run untouched validation**

Run:

```powershell
python scripts\run_calibration.py --recurrence-identifiability --partition validation --num-recurrence-seeds 960 --out-report docs\calibration\2026-09-03-recurrence-identifiability-validation.json
```

Expected: exit 0. Runner must verify fingerprint before generating a validation record and evaluate one policy only.

- [ ] **Step 2: Evaluate fixed gates**

Run:

```powershell
python -c "import json; p=json.load(open('docs/calibration/2026-09-03-recurrence-identifiability-validation.json')); m=p['metrics']; print(json.dumps(m, indent=2)); assert m['false_point_wilson'][1] <= .05; assert m['false_resolution_wilson'][1] <= .05; assert p['selection_counts'] == {'reselection': 0}; assert p['candidate_metrics'].keys() == {p['selected_policy']}; assert p['selected_policy'] == 'no_narrowing' or m['genuine_recurrence_status_accuracy'] >= .90"
```

Expected: all assertions pass. If not, stop and retain candidate scope.

- [ ] **Step 3: Pin validation linkage**

Append:

```python
RECURRENCE_VALIDATION_REPORT = Path(
    "docs/calibration/2026-09-03-recurrence-identifiability-validation.json"
)


def test_recurrence_untouched_validation_uses_frozen_policy_once():
    calibration = json.loads(RECURRENCE_CALIBRATION_REPORT.read_text(encoding="utf-8"))
    validation = json.loads(RECURRENCE_VALIDATION_REPORT.read_text(encoding="utf-8"))
    assert validation["partition"] == "validation"
    assert validation["selected_policy"] == calibration["selected_policy"]
    assert validation["fingerprint"] == calibration["fingerprint"]
    assert validation["seeds"] == list(range(60000, 60960))
    assert validation["selection_counts"] == {"reselection": 0}
    assert set(validation["candidate_metrics"]) == {calibration["selected_policy"]}
    assert validation["metrics"]["false_point_wilson"][1] <= 0.05
    assert validation["metrics"]["false_resolution_wilson"][1] <= 0.05
```

- [ ] **Step 4: Run tests and commit evidence**

Run: `python -m pytest tests/test_scientific_defaults.py tests/test_recurrence_identifiability.py -q`

Expected: PASS.

```bash
git add hydroseason/_scientific_defaults.py docs/calibration/2026-09-03-recurrence-identifiability-calibration.json docs/calibration/2026-09-03-recurrence-identifiability-validation.json tests/test_scientific_defaults.py
git commit -m "test: freeze recurrence calibration and validation"
```

---

### Task 9: Replace Legacy Narrowing With the Frozen Policy

**Files:**
- Modify: `hydroseason/_timing_identifiability.py:153-252`
- Modify: `hydroseason/_dynamic_year.py:24-99,652-667`
- Modify: `tests/test_timing_identifiability.py`
- Modify: `tests/test_recurrence_identifiability.py`
- Modify: `tests/test_dynamic_year.py`

**Interfaces:**
- Consumes: validated `RECURRENCE_POLICY` from generated defaults.
- Produces: one production narrowing implementation, corrected minimal/end-to-end regressions, and no legacy default path.

- [ ] **Step 1: Add corrected count-backed reproduction**

Append to `tests/test_timing_identifiability.py`:

```python
def test_gap_fragmented_equivalent_trough_does_not_become_a_false_point():
    index = pd.to_datetime([
        "1992-05-01", "1992-06-01", "1992-07-01", "1992-08-01",
        "1992-09-01", "1992-10-01", "1993-01-01", "1993-04-01",
    ])
    extent = np.array([40, 40, 40, 40, 40, 70, 40, 40], dtype=float)
    rows = pd.DataFrame(
        {
            "extent_pct": extent,
            "n_water": extent.astype(int),
            "n_valid": 100,
            "n_invalid": 0,
            "n_aoi": 100,
        },
        index=index,
    )
    result = assess_window_timing(
        rows["extent_pct"],
        rows,
        thresholds=TIMING_IDENTIFIABILITY_DEFAULTS,
        measurement_tolerance_pct=1.0,
        noise_pp=0.0,
        pixel_support_status="available",
        window_start=pd.Timestamp("1992-05-01"),
        window_end=pd.Timestamp("1993-04-01"),
    )
    assert result.detectable is True
    assert result.trough_status == "unresolved"
    assert result.trough_dates == tuple(index.delete(5))
```

Import `TIMING_IDENTIFIABILITY_DEFAULTS`. Add a mirrored peak fixture by replacing 40 with 70 and the single 70 with 40; expect unresolved full peak dates.

- [ ] **Step 2: Add end-to-end seed regression**

In `tests/test_recurrence_identifiability.py`:

```python
def test_geometry_seed_30035_no_longer_publishes_hy1993_false_point():
    from hydroseason._dynamic_year import DynamicHydroYearConfig, detect_dynamic_hydrological_years
    from hydroseason._synthetic import generate_trough_geometry_record

    record = generate_trough_geometry_record(30035, partition="calibration")
    annual = detect_dynamic_hydrological_years(
        record.frame,
        config=DynamicHydroYearConfig(
            expected_trough_month=record.truth.climatological_trough_month,
            trough_search_radius_months=3,
            adaptive_trough_search_radius_months=5,
            adaptive_min_usable_months_per_cycle=6,
        ),
    )
    row = annual.loc[annual["hy_year"] == 1993].iloc[0]
    assert row["trough_timing_status"] == "unresolved"
    assert pd.isna(row["trough_interval_start"]) is False
    assert pd.isna(row["trough_interval_end"]) is False
```

This test may reveal that reports intentionally retain full unresolved endpoints rather than blanking them; assert current `WindowTimingEvidence` transport, not a new export policy.

- [ ] **Step 3: Run regressions and verify red under omitted legacy default**

Run:

```powershell
python -m pytest tests/test_timing_identifiability.py tests/test_recurrence_identifiability.py -q -k "gap_fragmented or 30035"
```

Expected: FAIL with current false point.

- [ ] **Step 4: Remove legacy helper and resolve frozen default**

Delete `_most_recent_recurrence_cluster()`. Add:

```python
def _resolved_recurrence_policy(
    recurrence_policy: RecurrencePolicy | None,
) -> RecurrencePolicy:
    if recurrence_policy is not None:
        return recurrence_policy
    from ._scientific_defaults import RECURRENCE_POLICY

    return RECURRENCE_POLICY
```

Resolve once near the start of a non-empty `assess_window_timing()` call and send that value through `narrow_most_recent_recurrence()` for both peak and trough. No legacy branch remains.

Keep `DynamicHydroYearConfig.recurrence_policy: RecurrencePolicy | None = None`; `None` means frozen generated default. Explicit candidates remain available for calibration and tests.

- [ ] **Step 5: Run focused suites**

Run:

```powershell
python -m pytest tests/test_recurrence_identifiability.py tests/test_timing_identifiability.py tests/test_dynamic_year.py tests/test_condition.py tests/test_phase.py -q
```

Expected: PASS.

- [ ] **Step 6: Verify original threshold provenance remains exact**

Run:

```powershell
python -m pytest tests/test_scientific_defaults.py -q
python -c "from hydroseason._calibration import timing_identifiability_fingerprint; value=timing_identifiability_fingerprint(); print(value); assert value == 'e6cdf3ce960aa011711dc90e3ef4fb0135513eadaf471f4ac9e0656f80884735'"
```

Expected: PASS and exact fingerprint.

- [ ] **Step 7: Commit**

```bash
git add hydroseason/_timing_identifiability.py hydroseason/_dynamic_year.py tests/test_timing_identifiability.py tests/test_recurrence_identifiability.py tests/test_dynamic_year.py
git commit -m "fix: require evidence for recurrence narrowing"
```

---

### Task 10: Produce Development-Only Impact Report

**Files:**
- Create: `scripts/audit_recurrence_impact.py`
- Create: `tests/test_recurrence_impact.py`
- Create: `docs/calibration/2026-09-03-recurrence-identifiability-impact.json`

**Interfaces:**
- Consumes: selected production policy, stored legacy annual CSVs, and already-inspected sources.
- Produces: non-selecting diff covering annual extrema, endpoints, routes, categories, and baseline eligibility.

- [ ] **Step 1: Write failing pure diff tests**

Create fixtures with one unchanged and one changed year, then assert:

```python
def test_compare_annual_rows_reports_every_public_timing_change():
    legacy = pd.DataFrame({
        "hy_year": [2001],
        "peak_timing_status": ["point"],
        "trough_timing_status": ["point"],
        "trough_interval_start": ["2001-10-01"],
        "trough_interval_end": ["2001-10-01"],
        "timing_status": ["point"],
        "status_reason": ["ok"],
        "baseline_uncertain": [False],
    })
    selected = legacy.copy()
    selected.loc[0, ["trough_timing_status", "timing_status", "status_reason", "baseline_uncertain"]] = [
        "unresolved", "unresolved", "unresolved_timing", True,
    ]
    changes = compare_annual_rows("station-a", legacy, selected)
    assert changes == [{
        "station_id": "station-a",
        "hy_year": 2001,
        "field": "trough_timing_status",
        "legacy": "point",
        "selected": "unresolved",
    }, {
        "station_id": "station-a",
        "hy_year": 2001,
        "field": "timing_status",
        "legacy": "point",
        "selected": "unresolved",
    }, {
        "station_id": "station-a",
        "hy_year": 2001,
        "field": "status_reason",
        "legacy": "ok",
        "selected": "unresolved_timing",
    }, {
        "station_id": "station-a",
        "hy_year": 2001,
        "field": "baseline_uncertain",
        "legacy": False,
        "selected": True,
    }]
```

Normalize timestamps and NumPy scalars to JSON-safe ISO strings/bools before comparison.

- [ ] **Step 2: Implement audit script**

CLI:

```text
--stress-root PATH
--protected-root case_studies/data/extent
--legacy-results-root PATH
--cohort-manifest case_studies/results/timing-identifiability/cohort-manifest.csv
--output docs/calibration/2026-09-03-recurrence-identifiability-impact.json
```

For each source, strip known decision columns using the existing cohort builder allowlist, run `analyze_catchment()` under the frozen selected default, load matching stored legacy `_hydro_years.csv`, and diff these fields:

```python
ANNUAL_FIELDS = (
    "peak_timing_status", "peak_interval_start", "peak_interval_end",
    "trough_timing_status", "trough_interval_start", "trough_interval_end",
    "timing_status", "status_reason", "boundary_status", "confidence",
    "baseline_uncertain",
)
RECORD_FIELDS = ("route", "route_reason", "publication_category")
```

Report exact counts by source group, station, year, field, cohort membership, and motivating/protected status. Include fixed metadata `selection_use="forbidden"` and the recurrence/timing fingerprints.

- [ ] **Step 3: Run unit tests**

Run: `python -m pytest tests/test_recurrence_impact.py -q`

Expected: PASS.

- [ ] **Step 4: Generate development report from named inspected roots**

Run against the local stress source/results root used in the audit and `case_studies/data/extent`. Never substitute an uninspected source intended for Task 11. Example for current workspace:

```powershell
python scripts\audit_recurrence_impact.py --stress-root case_studies\results\stress-test-full\reports --protected-root case_studies\data\extent --legacy-results-root case_studies\results\stress-test-full\reports --cohort-manifest case_studies\results\timing-identifiability\cohort-manifest.csv --output docs\calibration\2026-09-03-recurrence-identifiability-impact.json
```

Expected: report names 34 stress records, five protected catchments, three motivating IDs, and 21 cohort IDs; missing source/artifact counts are explicit, never silently dropped.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_recurrence_impact.py tests/test_recurrence_impact.py docs/calibration/2026-09-03-recurrence-identifiability-impact.json
git commit -m "test: record recurrence policy impact"
```

---

### Task 11: Build and Evaluate Independent Blinded Cycle Cohort

**Gate:** required when `RECURRENCE_POLICY != "no_narrowing"`. Source must be uninspected and excluded from all prior timing, geometry, protected, motivating, and stress evidence. If no eligible source exists, stop 0.2.0 promotion; do not substitute inspected data.

Surface this at Task 7, not here. With the equal-span amendment,
`annual_shape_match` is a live contender rather than a candidate its own corpus
eliminates, so a narrowing winner is the expected outcome and this task becomes
mandatory. It needs a real, uninspected source root that the user must
authorise, and no such root is identified anywhere in this plan. Report the
Task 7 selection together with whether an eligible root exists; if it does not,
the choice is the user's between stopping 0.2.0 promotion and adopting the
`no_narrowing` runner-up, and it is not a choice to make silently at Task 11.

**Files:**
- Create: `case_studies/recurrence-identifiability/cohort-protocol.json`
- Create: `case_studies/recurrence-identifiability/review-rubric.md`
- Create: `scripts/build_recurrence_identifiability_cohort.py`
- Create: `scripts/evaluate_recurrence_identifiability_cohort.py`
- Create: `tests/test_recurrence_identifiability_cohort.py`
- Create after review: `case_studies/results/recurrence-identifiability/*`

**Interfaces:**
- Consumes: an eligible user-authorized source root and frozen recurrence policy/fingerprint.
- Produces: blinded packets, frozen labels/hash, catchment-bootstrap metrics, and direct-contradiction list.

- [ ] **Step 1: Freeze protocol before reading eligible source**

Write protocol with:

```json
{
  "protocol_id": "recurrence-identifiability-cycle-cohort-v1",
  "seed": 20260903,
  "sampling_unit": "catchment",
  "review_unit": "detected_cycle",
  "quota_policy": "min_8_catchments_or_available_per_stratum",
  "strata": ["window_span_0_11", "window_span_12_plus_complete", "window_span_12_plus_gapped"],
  "labels": ["point_supported", "interval_supported", "unresolved", "uncertain"],
  "excluded_sources": [
    "case_studies/results/stress-test-full",
    "case_studies/results/timing-identifiability",
    "case_studies/data/extent protected catchments",
    "130413a", "130407a", "130302a",
    "recurrence calibration and validation synthetic corpora",
    "trough geometry calibration and validation synthetic corpora"
  ],
  "packet_allowlist": [
    "anonymous_catchment_id", "anonymous_cycle_id", "date", "extent_pct",
    "invalid_pct", "quality_state", "n_water", "n_valid", "n_invalid", "n_aoi",
    "window_start", "window_end"
  ],
  "hidden_fields": [
    "station_id", "regime", "route", "timing_status", "peak_timing_status",
    "trough_timing_status", "selected_policy", "fingerprint", "model_output"
  ]
}
```

Write rubric defining each label, one primary reviewer, adjudication for disputed labels, and exclusion of `uncertain` from rate denominators.

- [ ] **Step 2: Write failing blinding and evaluation tests**

Import these pure seams from the two scripts: `validate_protocol()`, `assert_source_eligible()`, `anonymous_id()`, `write_identity_mapping()`, `freeze_labels_hash()`, `classify_comparison()`, `bootstrap_catchment_ids()`, and `summarize_comparisons()`. Tests must contain complete bodies:

```python
def test_packet_allowlist_is_disjoint_from_hidden_fields(protocol):
    validated = validate_protocol(protocol)
    assert set(validated["packet_allowlist"]).isdisjoint(validated["hidden_fields"])


def test_builder_rejects_any_excluded_source_token(tmp_path, protocol):
    source = tmp_path / "stress-test-full" / "fresh-copy"
    source.mkdir(parents=True)
    with pytest.raises(ValueError, match="excluded source"):
        assert_source_eligible(source, protocol["excluded_sources"])


def test_builder_hashes_identity_mapping_without_putting_it_in_packets(tmp_path):
    anonymous = anonymous_id(20260903, "station-a")
    mapping = {anonymous: "station-a"}
    mapping_path, hash_path = write_identity_mapping(tmp_path, mapping)
    packet = {"anonymous_catchment_id": anonymous, "anonymous_cycle_id": "cycle-1"}
    assert "station-a" not in json.dumps(packet, sort_keys=True)
    expected = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
    assert hash_path.read_text(encoding="ascii").strip() == expected


def test_labels_hash_cannot_change_after_first_evaluation(tmp_path):
    labels = tmp_path / "labels.csv"
    sidecar = tmp_path / "labels.sha256"
    labels.write_text("anonymous_cycle_id,label\ncycle-1,unresolved\n", encoding="utf-8")
    frozen = freeze_labels_hash(labels, sidecar)
    assert frozen == hashlib.sha256(labels.read_bytes()).hexdigest()
    labels.write_text("anonymous_cycle_id,label\ncycle-1,point_supported\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="frozen label hash"):
        freeze_labels_hash(labels, sidecar)


def test_unresolved_label_plus_predicted_point_is_direct_contradiction():
    row = classify_comparison("unresolved", "point", exact_endpoints=False)
    assert row["direct_contradiction"] is True
    assert row["false_point"] is True


def test_interval_label_plus_predicted_point_counts_as_false_point():
    row = classify_comparison("interval_supported", "point", exact_endpoints=False)
    assert row["direct_contradiction"] is False
    assert row["false_point"] is True


def test_bootstrap_resamples_catchments_not_cycles():
    class RecordingRng:
        def choice(self, values, *, size, replace):
            assert list(values) == ["catchment-a", "catchment-b"]
            assert size == 2
            assert replace is True
            return np.array(["catchment-b", "catchment-b"])

    rows = pd.DataFrame(
        {
            "anonymous_catchment_id": ["catchment-a"] + ["catchment-b"] * 5,
            "anonymous_cycle_id": ["a-1"] + [f"b-{index}" for index in range(5)],
        }
    )
    sampled = bootstrap_catchment_ids(rows, rng=RecordingRng())
    assert sampled == ["catchment-b", "catchment-b"]


def test_uncertain_labels_are_reported_but_excluded_from_rates():
    rows = pd.DataFrame(
        [
            {"reviewer_label": "uncertain", "false_point": True, "status_match": False},
            {"reviewer_label": "unresolved", "false_point": False, "status_match": True},
        ]
    )
    summary = summarize_comparisons(rows)
    assert summary["reviewed_n"] == 2
    assert summary["uncertain_n"] == 1
    assert summary["rate_denominator_n"] == 1
    assert summary["false_point_k"] == 0
```

Use two catchments with unequal cycle counts in the bootstrap test; monkeypatch the resampler and assert draws index two catchments, not concatenated cycle rows.

- [ ] **Step 3: Run tests and verify red**

Run: `python -m pytest tests/test_recurrence_identifiability_cohort.py -q`

Expected: missing script/module failures.

- [ ] **Step 4: Implement builder**

Builder requires `--source-root`, `--protocol`, and `--output-dir`. Before discovering data, casefold the resolved source path and reject every path-like exclusion token. Generate anonymous IDs from `sha256(f"{seed}:{station_id}")`; write the identity map separately with a SHA-256 sidecar and never inside `packets/`.

Use boundary detection only to define cycle bounds; strip every decision column before packet writing. Include all calendar positions from `window_start` through `window_end`, including missing observations as rows with null extent, so reviewers see gaps. Select catchments by seeded hash inside each frozen stratum; retain all selected cycles from each selected catchment to preserve clustering.

- [ ] **Step 5: Implement evaluator**

Freeze label hash on first evaluation. Join identities only after verifying hash. Re-run selected production policy, report counts and rates for false point, false resolution, status agreement, and exact endpoint agreement. Compute intervals by resampling catchments with replacement using seed 20260903. Emit every disagreement and:

```python
direct_contradiction = (
    (reviewer_label == "unresolved") & (predicted_status == "point")
)
false_point = (
    reviewer_label.isin(["interval_supported", "unresolved"])
    & predicted_status.eq("point")
)
```

- [ ] **Step 6: Run structural tests**

Run: `python -m pytest tests/test_recurrence_identifiability_cohort.py -q`

Expected: PASS.

- [ ] **Step 7: Commit protocol and tooling before source inspection**

```bash
git add case_studies/recurrence-identifiability/cohort-protocol.json case_studies/recurrence-identifiability/review-rubric.md scripts/build_recurrence_identifiability_cohort.py scripts/evaluate_recurrence_identifiability_cohort.py tests/test_recurrence_identifiability_cohort.py
git commit -m "feat: freeze blinded recurrence cycle cohort"
```

- [ ] **Step 8: Build, review, freeze, and evaluate**

Run builder against only the user-confirmed eligible root. Give `packets/` to reviewer without identity map or model results. Store returned labels, freeze SHA-256, then run evaluator. Expected promotion gate: zero direct contradictions. Any contradiction stops promotion; uncertain labels remain in report but not denominators.

- [ ] **Step 9: Commit evidence separately**

```bash
git add case_studies/results/recurrence-identifiability
git commit -m "test: validate recurrence policy on blinded cycles"
```

---

### Task 12: Recertify Unlaunched 0.2.0 and Run Full Verification

**Files:**
- Modify: `hydroseason/_scientific_defaults.py` (generated scope only)
- Modify: `scripts/run_calibration.py`
- Create: `docs/calibration/2026-09-03-recurrence-identifiability-promotion.json`
- Modify: `docs/decision-policy-0.2.0.md`
- Modify: `docs/decision-policy.md`
- Modify: `docs/migrations/0.2.0-timing-identifiability.md`
- Modify: `docs/report-columns.md`
- Modify: `CHANGELOG.md`
- Modify: `mkdocs.yml`
- Modify: `tests/test_decision_policy_docs.py`
- Modify: `tests/test_scientific_defaults.py`
- Modify: `tests/test_calibration.py`

**Interfaces:**
- Consumes: all synthetic, impact, protected, motivating, cohort, and regression evidence.
- Produces: corrected 0.2.0 promotion record; `RECURRENCE_AUTHORITY_SCOPE="established_0_2_0"`; geometry plan remains paused for its separate re-entry plan.

- [ ] **Step 1: Confirm every gate before promoting scope**

Verify:

```text
calibration false-point Wilson high <= 0.05
calibration false-resolution Wilson high <= 0.05
validation false-point Wilson high <= 0.05
validation false-resolution Wilson high <= 0.05
validation status accuracy >= 0.90 when policy != no_narrowing
zero blinded-cohort direct contradictions when policy != no_narrowing
protected five-catchment routes reviewed
three motivating records reviewed
timing fingerprint == e6cdf3ce960aa011711dc90e3ef4fb0135513eadaf471f4ac9e0656f80884735
```

If any applicable line fails, stop with candidate scope.

- [ ] **Step 2: Promote recurrence scope without rewriting frozen evidence**

Load the frozen calibration and validation reports, verify their candidate fingerprints agree, then recompute `recurrence_fingerprint()` from the calibration report's exact selected policy, 960 seeds, and selected metrics with `authority_scope="established_0_2_0"`. Extend the fingerprint function with an explicit keyword-only `authority_scope` argument defaulting to candidate scope so promotion never depends on mutable module state.

Invoke `_write_recurrence_defaults()` with the selected policy, the new established fingerprint, and established scope. Write a new promotion attestation—never edit either frozen input report—with this exact shape:

```python
promotion = {
    "promotion_version": "0.2.0-recurrence-identifiability.1",
    "generated": _utc_timestamp(),
    "selected_policy": calibration["selected_policy"],
    "candidate_authority_scope": calibration["authority_scope"],
    "candidate_fingerprint": calibration["fingerprint"],
    "established_authority_scope": "established_0_2_0",
    "established_fingerprint": established_fingerprint,
    "calibration_report": "docs/calibration/2026-09-03-recurrence-identifiability-calibration.json",
    "validation_report": "docs/calibration/2026-09-03-recurrence-identifiability-validation.json",
    "calibration_report_sha256": sha256_file(calibration_path),
    "validation_report_sha256": sha256_file(validation_path),
    "metrics_changed": False,
    "policy_changed": False,
}
```

Implement this as:

```python
def promote_recurrence_defaults(
    *,
    calibration_report: Path,
    validation_report: Path,
    out_report: Path,
    out_module: Path,
) -> dict[str, object]:
```

The function must verify the two candidate fingerprints and selected policies agree, verify validation gates, snapshot both source byte hashes, write defaults and the attestation, then recheck the source hashes before returning. Add mutually exclusive CLI flag `--promote-recurrence-identifiability` and run:

```powershell
python scripts\run_calibration.py --promote-recurrence-identifiability --out-report docs\calibration\2026-09-03-recurrence-identifiability-promotion.json
```

Add a test that snapshots both source-report byte hashes before promotion, runs `promote_recurrence_defaults()`, asserts both hashes are unchanged, and independently recomputes the established fingerprint from the attested policy, seeds, metrics, and scope.

- [ ] **Step 2b: Retarget the Task 7 freshness test at the promotion record**

Promotion rewrites `RECURRENCE_FINGERPRINT` in the generated module to the
established-scope value, while the frozen calibration report keeps the
candidate-scope one. Task 7's `test_recurrence_calibration_artifact_matches_generated_defaults`
asserts those two are equal and recomputes the fingerprint at the default
candidate scope, so it fails the moment promotion lands. Neither report may be
edited to make it pass.

Add the report path beside the existing two:

```python
RECURRENCE_PROMOTION_REPORT = Path(
    "docs/calibration/2026-09-03-recurrence-identifiability-promotion.json"
)
```

Then change the two fingerprint assertions to go through the attestation:

```python
def test_recurrence_calibration_artifact_matches_generated_defaults():
    from hydroseason._recurrence_calibration import recurrence_fingerprint

    payload = json.loads(RECURRENCE_CALIBRATION_REPORT.read_text(encoding="utf-8"))
    promotion = json.loads(RECURRENCE_PROMOTION_REPORT.read_text(encoding="utf-8"))
    assert payload["selected_policy"] == defaults.RECURRENCE_POLICY
    assert payload["authority_scope"] == "candidate_for_established_0_2_0"
    assert payload["seeds"] == list(range(50000, 50960))
    assert promotion["candidate_fingerprint"] == payload["fingerprint"]
    assert promotion["established_fingerprint"] == defaults.RECURRENCE_FINGERPRINT
    assert recurrence_fingerprint(
        defaults.RECURRENCE_POLICY,
        seeds=payload["seeds"],
        metrics=payload["metrics"],
        authority_scope=defaults.RECURRENCE_AUTHORITY_SCOPE,
    ) == defaults.RECURRENCE_FINGERPRINT
```

Both the candidate and the established fingerprint stay independently
recomputable from the frozen calibration report; only the scope differs.

- [ ] **Step 3: Amend 0.2.0 decision and migration docs**

Add a recurrence-identifiability section to `docs/decision-policy-0.2.0.md` covering exact candidates, 960/960 seeds, metrics, selected result, validation, cohort status, known limitations, and separate fingerprint. Preserve all phrases pinned by existing tests.

In `docs/decision-policy.md`, replace the old claim that existing evidence alone completed promotion with a corrected paragraph naming both original timing and new recurrence reports. In migration notes, state which annual timing statuses/endpoints/routes can change and that complete equivalent sets remain visible when unresolved.

Document `peak_interval_start/end` and `trough_interval_start/end` as bounds of equivalent evidence even when status is unresolved; never describe them as exact published points.

Amend the existing `## [0.2.0] - 2026-08-31` changelog entry in place. State 0.2.0 was unlaunched, name corrected freeze date, and add no 0.2.1 section. Add any new decision-policy page to MkDocs navigation only if created; this plan amends existing pages and normally needs no new nav entry.

- [ ] **Step 4: Add final documentation tests**

Assert decision docs contain selected policy, recurrence fingerprint, both Wilson gates, validation report path, cohort outcome/null-result statement, unchanged policy ID, and unchanged package version.

- [ ] **Step 5: Run protected and motivating checks**

Run:

```powershell
python -m pytest tests\test_fitzroy_regression.py tests\test_gilbert_regression.py tests\test_manual_review_regression.py tests\test_scientific_baseline_0_1_1.py tests\test_catchment_analysis.py -q
python scripts\check_motivating_records.py --stress-root case_studies\results\stress-test-full\reports --stations 130413a,130407a,130302a --output $env:TEMP\hydroseason-recurrence-motivating-check
```

Expected: protected routes remain Daly/Fitzroy/Gilbert per-year and Lachlan/Moonie event-only. Record exact annual changes; do not rewrite expected fixtures without evidence.

- [ ] **Step 6: Run full suite and strict docs**

Run:

```powershell
python -m pytest -q
python -m mkdocs build --strict
git diff --check
```

Expected: all tests pass, docs exit 0, no whitespace errors. Inspect MkDocs INFO output for unlisted pages.

- [ ] **Step 7: Commit**

```bash
git add hydroseason/_scientific_defaults.py scripts/run_calibration.py docs/calibration/2026-09-03-recurrence-identifiability-promotion.json docs/decision-policy-0.2.0.md docs/decision-policy.md docs/migrations/0.2.0-timing-identifiability.md docs/report-columns.md CHANGELOG.md mkdocs.yml tests/test_decision_policy_docs.py tests/test_scientific_defaults.py tests/test_calibration.py
git commit -m "fix: recertify recurrence timing for 0.2.0"
```

- [ ] **Step 8: Hand off to geometry re-entry plan**

Record verified commit and exact test counts. Next plan is `docs/superpowers/plans/2026-09-03-trough-geometry-reentry.md`; do not resume geometry Task 8 directly because its fingerprint and bug-pinning test are stale.

---

## Self-Review Notes

- Spec goals 1-3: Tasks 2-9 define, select, validate, and integrate safe/no-narrowing outcomes.
- Unchanged 0.2.0 identity: Global Constraints and Task 12.
- Threshold provenance tripwire: Tasks 3, 7, 9, and 12.
- Generated writer ordering: Task 6.
- Full-cycle bounds and month-difference convention: Tasks 2-3.
- Eight-family 960/960 independent corpus: Task 4.
- Exact metrics, safety selector, conservative tie-break, and metric-bearing fingerprint: Tasks 5-8.
- Development-only audit separation: Task 10.
- Independent cycle-level cohort and catchment bootstrap: Task 11.
- No eligible real source behavior: Task 11 gate blocks non-disabled promotion.
- Append-only reports and untouched validation: Global Constraints and Tasks 7-8.
- Geometry remains paused: Global Constraints and Task 12 handoff.
- Completeness scan: every implementation seam has a concrete signature or explicit test, while runtime-selected values are read from generated reports and linked by freshness tests.
- Type consistency: `RecurrencePolicy | None` is used by both `assess_window_timing()` and `DynamicHydroYearConfig`; pure helper always receives resolved `RecurrencePolicy`.

## Audit Fixes (2026-09-03)

- **Candidate C was self-defeating.** Symmetric nearest-date distance accepts any
  two clusters roughly twelve months apart whatever their widths, so
  `annual_shape_match` narrowed the `annual_aligned_fragment_trap` family on all
  120 of its calibration seeds and failed its own false-resolution gate;
  `no_narrowing` would then have won by construction rather than on evidence.
  Task 2 now requires equal cluster span, recorded as Audit Correction 13 in the
  spec, and Task 1 Step 2b flags that this changed an approved rule.
- **Two Task 3 bound tests never reached the code they test.** `[10, 5, 10]`
  spans two months, inside `max_boundary_interval_months=2`, so it resolves to
  `interval` and never enters the unresolved branch that calls
  `narrow_most_recent_recurrence()`: the rejection test could not raise and the
  derived-bounds test asserted nothing. Both now use a five-month fixture.
- **Bounds are resolved lazily.** Deriving them at the top of
  `assess_window_timing()` would break its documented "any index" contract for
  every caller, including ones that never narrow.
- **`exact_latest_date_accuracy` had no stated denominator** and the plan's own
  fixture implied conditioning on the policy's own successes, which would let a
  candidate that resolves one record and abstains on 119 outrank one that
  recovers 119 of 120. Denominator is now all genuine rows.
- **The geometry writer has no markers**, so Task 6 Step 4 had nothing to
  capture and a geometry re-run would append a duplicate block. Task 6 now
  fixes that writer before adding the third one.
- **Promotion breaks the Task 7 freshness test**, because the generated module
  moves to the established fingerprint while the frozen report keeps the
  candidate one. Task 12 Step 2b retargets it at the promotion attestation.
- **A narrowing winner makes Task 11 mandatory** and no eligible uninspected
  source root is identified anywhere in this plan. Task 7 must report that
  alongside the selection.
