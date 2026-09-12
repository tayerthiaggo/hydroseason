# Seasonality Timing-Recurrence Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `candidate_timing_recurrence` seasonality policy that classifies a record `seasonal` or `aseasonal` by testing whether annual peak and trough timing recur on the calendar, measured on a detrended series.

**Architecture:** A new `_seasonality_test.py` estimates a centred 2×12 moving-average trend, builds tie-aware annual peak/trough month sets on the detrended series, and runs the existing weighted Kuiper uniformity test on each. A new `decide_timing_recurrence` maps that to regime and route. `assess_water_regime` and `analyze_catchment` gain a `seasonality_policy` keyword whose default (`None`) leaves `established_0_2_0` untouched. A shared `annual_detectability` helper removes the duplicated detectability block so the candidate and the established policy judge detectability identically.

**Tech Stack:** Python 3.10–3.13, pandas ≥ 2.0, numpy ≥ 1.24, pytest, ruff. No new dependencies.

**Design spec:** [`docs/superpowers/specs/2026-09-11-seasonality-timing-recurrence-design.md`](../specs/2026-09-11-seasonality-timing-recurrence-design.md)

## Global Constraints

- No new runtime dependencies. Core code must not import scipy (it is an optional `raster` extra).
- `ESTABLISHED_POLICY` stays `"established_0_2_0"`. The default behaviour of every public entry point must not change.
- `TIMING_IDENTIFIABILITY_DEFAULTS` and `TIMING_IDENTIFIABILITY_FINGERPRINT` are unchanged; no threshold is re-derived.
- α is fixed at `0.05` before any result is seen. Do not tune it, and do not tune anything else in response to a result.
- Public functions take keyword-only arguments after the leading DataFrame.
- Modern type annotations (`int | None`, `tuple[...]`).
- ruff: `line-length = 100`, `select = ["E", "F", "I"]`.
- Tests: `python -m pytest -q` from the repository root.
- Only user-facing entry points are re-exported from `hydroseason/__init__.py`.
- No CAMELS-AUS data is loaded, split, or inspected anywhere in this plan.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: Shared detectability helper

Extract the detectability block duplicated in `assess_window_timing` and `assess_timing_identifiability` into one helper, with no behaviour change.

**Files:**
- Modify: `hydroseason/_timing_identifiability.py:233-257` and `hydroseason/_timing_identifiability.py:371-399`
- Test: `tests/test_timing_identifiability.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `AnnualDetectability(amplitude_pp: float, detectability_floor_pp: float, amplitude_to_floor_ratio: float, peak_n_water: int | None, at_or_below_floor: bool, detectable: bool)` and `annual_detectability(values: pd.Series, rows: pd.DataFrame, *, thresholds: TimingIdentifiabilityThresholds, measurement_tolerance_pp: float, noise_pp: float, pixel_support_status: PixelSupportStatus) -> AnnualDetectability`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_timing_identifiability.py`:

```python
def test_annual_detectability_matches_the_calendar_year_path():
    from hydroseason._timing_identifiability import annual_detectability

    frame = _counts([0, 0, 6, 12, 6, 0, 0, 0, 0, 0, 0, 0])
    prepared = prepare_monthly_extent(frame)
    _amplitude_pp, noise_pp = robust_scale(prepared)
    values = prepared["extent_pct"].astype(float)

    direct = annual_detectability(
        values,
        prepared,
        thresholds=TEST_THRESHOLDS,
        measurement_tolerance_pp=1.0,
        noise_pp=noise_pp,
        pixel_support_status="available",
    )
    via_record = assess_timing_identifiability(
        frame, thresholds=TEST_THRESHOLDS
    ).years[2001]

    assert direct.detectable is via_record.detectable
    assert direct.amplitude_pp == via_record.amplitude_pp
    assert direct.detectability_floor_pp == via_record.detectability_floor_pp
    assert direct.amplitude_to_floor_ratio == via_record.amplitude_to_floor_ratio
    assert direct.peak_n_water == via_record.peak_n_water
    assert direct.at_or_below_floor is via_record.at_or_below_floor


def test_annual_detectability_rejects_a_flat_year():
    from hydroseason._timing_identifiability import annual_detectability

    prepared = prepare_monthly_extent(_counts([4] * 12))
    values = prepared["extent_pct"].astype(float)

    result = annual_detectability(
        values,
        prepared,
        thresholds=TEST_THRESHOLDS,
        measurement_tolerance_pp=1.0,
        noise_pp=0.0,
        pixel_support_status="available",
    )

    assert result.amplitude_pp == 0.0
    assert result.at_or_below_floor is True
    assert result.detectable is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timing_identifiability.py -q -k annual_detectability`
Expected: FAIL with `ImportError: cannot import name 'annual_detectability'`

- [ ] **Step 3: Add the helper**

Insert into `hydroseason/_timing_identifiability.py` immediately after `_peak_water_pixels` (after line 140):

```python
@dataclass(frozen=True)
class AnnualDetectability:
    """Whether one window's annual range is large enough to locate extrema."""

    amplitude_pp: float
    detectability_floor_pp: float
    amplitude_to_floor_ratio: float
    peak_n_water: int | None
    at_or_below_floor: bool
    detectable: bool


def annual_detectability(
    values: pd.Series,
    rows: pd.DataFrame,
    *,
    thresholds: TimingIdentifiabilityThresholds,
    measurement_tolerance_pp: float,
    noise_pp: float,
    pixel_support_status: PixelSupportStatus,
) -> AnnualDetectability:
    """Detectability of one window, shared by every caller.

    One definition serves the calendar-year path, the cycle-window path and the
    seasonality candidate, so a record cannot be judged detectable by one and
    undetectable by another.
    """
    maximum, minimum = float(values.max()), float(values.min())
    amplitude_pp = maximum - minimum
    peak_rows = rows.loc[values.index[values == maximum]]
    trough_rows = rows.loc[values.index[values == minimum]]
    detectability_floor_pp = max(
        float(measurement_tolerance_pp),
        float(noise_pp),
        _resolution_pp(peak_rows),
        _resolution_pp(trough_rows),
        float(np.finfo(float).eps),
    )
    at_or_below_floor = amplitude_pp <= detectability_floor_pp
    ratio = 0.0 if at_or_below_floor else float(amplitude_pp / detectability_floor_pp)
    peak_n_water = _peak_water_pixels(peak_rows)
    detectable = bool(
        amplitude_pp > 0.0
        and not at_or_below_floor
        and ratio >= thresholds.min_amplitude_to_floor_ratio
        and (
            pixel_support_status == "unavailable"
            or peak_n_water is not None
            and peak_n_water >= thresholds.min_peak_water_pixels
        )
    )
    return AnnualDetectability(
        amplitude_pp=amplitude_pp,
        detectability_floor_pp=detectability_floor_pp,
        amplitude_to_floor_ratio=ratio,
        peak_n_water=peak_n_water,
        at_or_below_floor=at_or_below_floor,
        detectable=detectable,
    )
```

- [ ] **Step 4: Use the helper in `assess_window_timing`**

In `hydroseason/_timing_identifiability.py`, replace lines 233-257 (from `values = values.astype(float)` through the closing `)` of the `detectable = bool(...)` assignment) with:

```python
    values = values.astype(float)
    detectability = annual_detectability(
        values,
        rows,
        thresholds=thresholds,
        measurement_tolerance_pp=measurement_tolerance_pp,
        noise_pp=noise_pp,
        pixel_support_status=pixel_support_status,
    )
    amplitude_pp = detectability.amplitude_pp
    detectability_floor_pp = detectability.detectability_floor_pp
    at_or_below_floor = detectability.at_or_below_floor
    ratio = detectability.amplitude_to_floor_ratio
    peak_n_water = detectability.peak_n_water
    detectable = detectability.detectable
```

- [ ] **Step 5: Use the helper in `assess_timing_identifiability`**

In the same file, replace lines 371-399 (from `values = usable["extent_pct"].astype(float)` through the closing `)` of `detectable = bool(...)`) with:

```python
        values = usable["extent_pct"].astype(float)
        detectability = annual_detectability(
            values,
            usable,
            thresholds=thresholds,
            measurement_tolerance_pp=measurement_tolerance_pp,
            noise_pp=noise_pp,
            pixel_support_status=pixel_support_status,
        )
        amplitude_pp = detectability.amplitude_pp
        detectability_floor_pp = detectability.detectability_floor_pp
        at_or_below_floor = detectability.at_or_below_floor
        ratio = detectability.amplitude_to_floor_ratio
        peak_n_water = detectability.peak_n_water
        detectable = detectability.detectable
```

- [ ] **Step 6: Run the affected suites**

Run: `python -m pytest tests/test_timing_identifiability.py tests/test_timing_identifiability_cohort.py tests/test_regime.py tests/test_catchment_analysis.py -q`
Expected: PASS, no failures.

- [ ] **Step 7: Confirm the established baseline is untouched**

Run: `python -m pytest tests/test_scientific_baseline_0_1_1.py tests/test_regime.py tests/test_manual_review_regression.py -q`
Expected: PASS. These pin the 0.1.1 scientific baseline fixtures, the five protected case-study regimes, and the manual-review regression respectively. If any protected-catchment result differs, stop: the refactor changed behaviour and must be corrected before continuing.

Note: `scripts/_scientific_baseline_guard.py` is not a runnable check. It is a helper module exposing `refuse_protected_baseline_output()`, which the study-case builder scripts call to refuse overwriting the protected fixture directory.

- [ ] **Step 8: Lint and commit**

```bash
ruff check hydroseason tests
git add hydroseason/_timing_identifiability.py tests/test_timing_identifiability.py
git commit -m "refactor: share one annual detectability definition" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Classical 2×12 trend

**Files:**
- Create: `hydroseason/_seasonality_test.py`
- Test: `tests/test_seasonality_test.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `TrendEstimate(trend: pd.Series, detrended: pd.Series, interpolated: pd.Series, n_interpolated_months: int, n_months_without_trend: int)` and `classical_trend(prepared: pd.DataFrame, *, value_col: str = "extent_pct") -> TrendEstimate`. Both series are indexed on a complete monthly grid spanning the record.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seasonality_test.py`:

```python
import numpy as np
import pandas as pd

from hydroseason._seasonality_test import classical_trend
from hydroseason._state_input import prepare_monthly_extent


def _frame(values, *, start="1990-01-01", invalid_pct=0.0):
    index = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame(
        {"extent_pct": np.asarray(values, dtype=float), "invalid_pct": invalid_pct},
        index=index,
    )


def test_trend_removes_a_linear_ramp_exactly():
    months = np.arange(120)
    prepared = prepare_monthly_extent(_frame(10.0 + 0.2 * months))

    estimate = classical_trend(prepared)

    interior = estimate.detrended.dropna()
    assert len(interior) == 120 - 12
    assert np.allclose(interior.to_numpy(), 0.0, atol=1e-9)


def test_trend_annihilates_a_pure_annual_cycle():
    months = np.arange(120)
    prepared = prepare_monthly_extent(_frame(30.0 + 5.0 * np.cos(2 * np.pi * months / 12)))

    estimate = classical_trend(prepared)

    interior = estimate.trend.dropna()
    assert np.allclose(interior.to_numpy(), 30.0, atol=1e-9)


def test_ends_have_no_trend_and_no_detrended_value():
    prepared = prepare_monthly_extent(_frame(np.full(60, 20.0)))

    estimate = classical_trend(prepared)

    assert estimate.trend.iloc[:6].isna().all()
    assert estimate.trend.iloc[-6:].isna().all()
    assert estimate.detrended.iloc[:6].isna().all()
    assert estimate.detrended.iloc[-6:].isna().all()
    assert estimate.n_months_without_trend == 12


def test_internal_gaps_feed_the_trend_but_never_the_detrended_series():
    values = 10.0 + 0.2 * np.arange(120)
    frame = _frame(values)
    frame.loc[frame.index[40], "extent_pct"] = np.nan
    frame.loc[frame.index[40], "invalid_pct"] = 100.0
    prepared = prepare_monthly_extent(frame)

    estimate = classical_trend(prepared)

    gap = frame.index[40]
    assert estimate.interpolated.loc[gap]
    assert estimate.n_interpolated_months == 1
    assert np.isfinite(estimate.trend.loc[gap])
    assert np.isnan(estimate.detrended.loc[gap])
    assert np.isfinite(estimate.detrended.loc[frame.index[41]])


def test_leading_and_trailing_gaps_are_not_extrapolated():
    values = np.full(60, 20.0)
    frame = _frame(values)
    for position in (0, 59):
        frame.loc[frame.index[position], "extent_pct"] = np.nan
        frame.loc[frame.index[position], "invalid_pct"] = 100.0
    prepared = prepare_monthly_extent(frame)

    estimate = classical_trend(prepared)

    assert estimate.n_interpolated_months == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_seasonality_test.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydroseason._seasonality_test'`

- [ ] **Step 3: Write the implementation**

Create `hydroseason/_seasonality_test.py`:

```python
"""Seasonality as recurrence of annual timing, measured on a detrended record.

The question this module answers is not how much surface water varies inside a
year, but whether its annual high and low come back at the same time of year.
Magnitude belongs to the detectability rule; recurrence is what an annual
boundary scheme actually presupposes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_TREND_WINDOW_MONTHS = 13
_TREND_HALF_WINDOW = 6
_TREND_WEIGHTS = np.r_[0.5, np.ones(11), 0.5] / 12.0


@dataclass(frozen=True)
class TrendEstimate:
    """Centred 2x12 trend, the series it leaves behind, and what was filled."""

    trend: pd.Series
    detrended: pd.Series
    interpolated: pd.Series
    n_interpolated_months: int
    n_months_without_trend: int


def classical_trend(prepared: pd.DataFrame, *, value_col: str = "extent_pct") -> TrendEstimate:
    """Estimate the trend-cycle with the classical additive 2x12 moving average.

    Internal missing months are interpolated to feed the moving average only:
    an interpolated month never contributes timing evidence, because it is not
    an observation. The first and last six months have no centred window and
    therefore no trend.
    """
    if prepared.empty:
        empty = pd.Series(dtype=float)
        return TrendEstimate(empty, empty, pd.Series(dtype=bool), 0, 0)

    grid = pd.date_range(prepared.index.min(), prepared.index.max(), freq="MS")
    usable = prepared["candidate_usable"].to_numpy(dtype=bool)
    observed = prepared[value_col].astype(float).where(usable).reindex(grid)
    filled = observed.interpolate(method="time", limit_area="inside")
    interpolated = filled.notna() & observed.isna()

    values = filled.to_numpy(dtype=float)
    trend = np.full(len(values), np.nan)
    for position in range(_TREND_HALF_WINDOW, len(values) - _TREND_HALF_WINDOW):
        window = values[position - _TREND_HALF_WINDOW : position + _TREND_HALF_WINDOW + 1]
        if np.isfinite(window).all():
            trend[position] = float(np.dot(_TREND_WEIGHTS, window))

    trend_series = pd.Series(trend, index=grid, name="trend")
    detrended = (observed - trend_series).rename("detrended")
    return TrendEstimate(
        trend=trend_series,
        detrended=detrended,
        interpolated=interpolated,
        n_interpolated_months=int(interpolated.sum()),
        n_months_without_trend=int(trend_series.isna().sum()),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_seasonality_test.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Lint and commit**

```bash
ruff check hydroseason tests
git add hydroseason/_seasonality_test.py tests/test_seasonality_test.py
git commit -m "feat: estimate a classical 2x12 trend for the seasonality candidate" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Timing-recurrence assessment

**Files:**
- Modify: `hydroseason/_seasonality_test.py`
- Test: `tests/test_seasonality_test.py`

**Interfaces:**
- Consumes: `classical_trend` and `TrendEstimate` (Task 2); `annual_detectability` and `AnnualDetectability` (Task 1); `summarise_annual_timing`, `AnnualTimingSummary`, `equivalent_extremum_months` from `_circular_timing`; `robust_scale` from `_boundary`.
- Produces: `TIMING_RECURRENCE_ALPHA = 0.05` and
  `TimingRecurrenceResult(classification: Literal["seasonal", "aseasonal"] | None, status: Literal["ok", "insufficient_record"], reason: str, alpha: float, peak: AnnualTimingSummary, trough: AnnualTimingSummary, peak_month_sets: dict[int, tuple[int, ...]], trough_month_sets: dict[int, tuple[int, ...]], n_qualifying_years: int, n_timing_eligible_years: int, n_detectable_years: int, trend: TrendEstimate)`
  and `assess_timing_recurrence(prepared: pd.DataFrame, *, thresholds, value_col="extent_pct", measurement_tolerance_pct=0.0, min_months_per_year=9, min_years=5, alpha=TIMING_RECURRENCE_ALPHA, n_bootstrap=200, random_state=0) -> TimingRecurrenceResult`.
- Reason strings: `"too_few_qualifying_years"`, `"trend_unavailable"`, `"no_detectable_years"`, `"peak_and_trough_recur"`, `"peak_uniformity_not_rejected"`, `"trough_uniformity_not_rejected"`, `"peak_and_trough_uniformity_not_rejected"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_seasonality_test.py`:

```python
from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS
from hydroseason._seasonality_test import assess_timing_recurrence


def _assess(frame, **kwargs):
    prepared = prepare_monthly_extent(frame)
    return assess_timing_recurrence(
        prepared, thresholds=TIMING_IDENTIFIABILITY_DEFAULTS, **kwargs
    )


def _annual(years, *, amplitude=5.0, centre=50.0, slope=0.0, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    months = np.arange(12 * years)
    values = centre + slope * months + amplitude * np.cos(2 * np.pi * months / 12)
    if noise:
        values = values + rng.normal(0.0, noise, size=len(values))
    return _frame(values)


def test_annual_cycle_with_a_trend_is_seasonal():
    result = _assess(_annual(30, slope=0.2))

    assert result.status == "ok"
    assert result.classification == "seasonal"
    assert result.reason == "peak_and_trough_recur"
    assert result.peak.uniformity_p < 0.05
    assert result.trough.uniformity_p < 0.05


def test_white_noise_is_aseasonal():
    rng = np.random.default_rng(3)
    result = _assess(_frame(50.0 + rng.normal(0.0, 2.5, size=360)))

    assert result.status == "ok"
    assert result.classification == "aseasonal"
    assert result.reason.endswith("uniformity_not_rejected")


def test_a_short_record_is_insufficient_not_aseasonal():
    result = _assess(_annual(4))

    assert result.status == "insufficient_record"
    assert result.reason == "too_few_qualifying_years"
    assert result.classification is None


def test_a_record_without_enough_trend_months_is_insufficient():
    frame = _annual(6)
    frame.loc[frame.index[12:60], "extent_pct"] = np.nan
    frame.loc[frame.index[12:60], "invalid_pct"] = 100.0

    result = _assess(frame)

    assert result.status == "insufficient_record"
    assert result.reason == "trend_unavailable"


def test_a_flat_record_reports_no_detectable_years():
    result = _assess(_frame(np.full(360, 20.0)))

    assert result.status == "ok"
    assert result.classification == "aseasonal"
    assert result.reason == "no_detectable_years"
    assert result.n_detectable_years == 0


def test_detrending_never_sharpens_a_zero_plateau():
    values = np.zeros(240)
    months = np.arange(240) % 12
    values[np.isin(months, [1, 2, 3])] = 30.0
    result = _assess(_frame(values))

    interior_years = sorted(result.trough_month_sets)[1:-1]
    for year in interior_years:
        assert set(result.trough_month_sets[year]) == {1, 5, 6, 7, 8, 9, 10, 11, 12}


def test_classification_is_invariant_to_calendar_rotation():
    classes = set()
    for shift in range(12):
        months = np.arange(360)
        values = 50.0 + 5.0 * np.cos(2 * np.pi * (months - shift) / 12)
        classes.add(_assess(_frame(values)).classification)

    assert classes == {"seasonal"}


def test_results_are_reproducible_for_a_fixed_seed():
    frame = _annual(20, noise=2.5, seed=11)

    first = _assess(frame, random_state=7)
    second = _assess(frame, random_state=7)

    assert first.peak.uniformity_p == second.peak.uniformity_p
    assert first.trough.uniformity_p == second.trough.uniformity_p
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_seasonality_test.py -q -k "recur or aseasonal or insufficient or plateau or rotation or reproducible"`
Expected: FAIL with `ImportError: cannot import name 'assess_timing_recurrence'`

- [ ] **Step 3: Write the implementation**

Append to `hydroseason/_seasonality_test.py`, and extend its imports:

```python
from typing import Literal

from ._boundary import robust_scale
from ._circular_timing import (
    AnnualTimingSummary,
    equivalent_extremum_months,
    summarise_annual_timing,
)
from ._timing_identifiability import (
    TimingIdentifiabilityThresholds,
    _validate_tolerance,
    annual_detectability,
)

TIMING_RECURRENCE_ALPHA = 0.05

_COUNT_COLUMNS = {"n_water", "n_valid", "n_invalid", "n_aoi"}
_EMPTY_SUMMARY = AnnualTimingSummary(None, None, None, None, None, 0, None)


@dataclass(frozen=True)
class TimingRecurrenceResult:
    """Whether annual peak and trough timing recur on the calendar."""

    classification: Literal["seasonal", "aseasonal"] | None
    status: Literal["ok", "insufficient_record"]
    reason: str
    alpha: float
    peak: AnnualTimingSummary
    trough: AnnualTimingSummary
    peak_month_sets: dict[int, tuple[int, ...]]
    trough_month_sets: dict[int, tuple[int, ...]]
    n_qualifying_years: int
    n_timing_eligible_years: int
    n_detectable_years: int
    trend: TrendEstimate


def _insufficient(reason: str, trend: TrendEstimate, *, alpha: float, n_qualifying: int,
                  n_eligible: int) -> TimingRecurrenceResult:
    return TimingRecurrenceResult(
        classification=None,
        status="insufficient_record",
        reason=reason,
        alpha=alpha,
        peak=_EMPTY_SUMMARY,
        trough=_EMPTY_SUMMARY,
        peak_month_sets={},
        trough_month_sets={},
        n_qualifying_years=n_qualifying,
        n_timing_eligible_years=n_eligible,
        n_detectable_years=0,
        trend=trend,
    )


def assess_timing_recurrence(
    prepared: pd.DataFrame,
    *,
    thresholds: TimingIdentifiabilityThresholds,
    value_col: str = "extent_pct",
    measurement_tolerance_pct: float = 0.0,
    min_months_per_year: int = 9,
    min_years: int = 5,
    alpha: float = TIMING_RECURRENCE_ALPHA,
    n_bootstrap: int = 200,
    random_state: int = 0,
) -> TimingRecurrenceResult:
    """Test whether annual extremum timing recurs on the calendar.

    Detectability is judged on raw observed extent, so the calibrated rule is
    unchanged. Month sets are read off the detrended series, with the tie
    tolerance widened by the year's trend range: every month tied in raw extent
    stays tied, so detrending cannot manufacture timing precision.
    """
    measurement_tolerance_pp = _validate_tolerance(measurement_tolerance_pct)
    trend = classical_trend(prepared, value_col=value_col)
    if prepared.empty:
        return _insufficient(
            "too_few_qualifying_years", trend, alpha=alpha, n_qualifying=0, n_eligible=0
        )

    usable = prepared.loc[prepared["candidate_usable"]]
    qualifying_years = [
        int(year)
        for year, group in usable.groupby(usable.index.year)
        if len(set(group.index.month)) >= min_months_per_year
    ]
    if len(qualifying_years) < min_years:
        return _insufficient(
            "too_few_qualifying_years",
            trend,
            alpha=alpha,
            n_qualifying=len(qualifying_years),
            n_eligible=0,
        )

    detrended = trend.detrended.dropna()
    eligible: dict[int, pd.Series] = {}
    for year in qualifying_years:
        year_values = detrended.loc[detrended.index.year == year]
        if len(year_values) >= min_months_per_year:
            eligible[year] = year_values
    if len(eligible) < min_years:
        return _insufficient(
            "trend_unavailable",
            trend,
            alpha=alpha,
            n_qualifying=len(qualifying_years),
            n_eligible=len(eligible),
        )

    _amplitude_pp, noise_pp = robust_scale(prepared)
    pixel_support_status = (
        "available" if _COUNT_COLUMNS.issubset(prepared.columns) else "unavailable"
    )

    peak_month_sets: dict[int, tuple[int, ...]] = {}
    trough_month_sets: dict[int, tuple[int, ...]] = {}
    for year, year_values in eligible.items():
        rows = prepared.loc[year_values.index]
        raw_values = rows[value_col].astype(float)
        detectability = annual_detectability(
            raw_values,
            rows,
            thresholds=thresholds,
            measurement_tolerance_pp=measurement_tolerance_pp,
            noise_pp=noise_pp,
            pixel_support_status=pixel_support_status,
        )
        if not detectability.detectable:
            continue
        year_trend = trend.trend.loc[year_values.index]
        trend_range_pp = float(year_trend.max() - year_trend.min())
        tolerance = detectability.detectability_floor_pp + trend_range_pp
        peak_month_sets[year] = equivalent_extremum_months(
            year_values, kind="max", tolerance=tolerance
        )
        trough_month_sets[year] = equivalent_extremum_months(
            year_values, kind="min", tolerance=tolerance
        )

    if not peak_month_sets:
        return TimingRecurrenceResult(
            classification="aseasonal",
            status="ok",
            reason="no_detectable_years",
            alpha=alpha,
            peak=_EMPTY_SUMMARY,
            trough=_EMPTY_SUMMARY,
            peak_month_sets={},
            trough_month_sets={},
            n_qualifying_years=len(qualifying_years),
            n_timing_eligible_years=len(eligible),
            n_detectable_years=0,
            trend=trend,
        )

    peak = summarise_annual_timing(
        peak_month_sets, n_resamples=n_bootstrap, random_state=random_state
    )
    trough = summarise_annual_timing(
        trough_month_sets, n_resamples=n_bootstrap, random_state=random_state
    )
    peak_rejects = peak.uniformity_p is not None and peak.uniformity_p < alpha
    trough_rejects = trough.uniformity_p is not None and trough.uniformity_p < alpha
    if peak_rejects and trough_rejects:
        classification, reason = "seasonal", "peak_and_trough_recur"
    elif trough_rejects:
        classification, reason = "aseasonal", "peak_uniformity_not_rejected"
    elif peak_rejects:
        classification, reason = "aseasonal", "trough_uniformity_not_rejected"
    else:
        classification, reason = "aseasonal", "peak_and_trough_uniformity_not_rejected"

    return TimingRecurrenceResult(
        classification=classification,
        status="ok",
        reason=reason,
        alpha=alpha,
        peak=peak,
        trough=trough,
        peak_month_sets=peak_month_sets,
        trough_month_sets=trough_month_sets,
        n_qualifying_years=len(qualifying_years),
        n_timing_eligible_years=len(eligible),
        n_detectable_years=len(peak_month_sets),
        trend=trend,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_seasonality_test.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 5: Add the raw-tie property test**

Append to `tests/test_seasonality_test.py`:

```python
def test_raw_tied_months_stay_tied_after_detrending():
    rng = np.random.default_rng(5)
    months = np.arange(240)
    values = 40.0 + 0.05 * months + 6.0 * np.cos(2 * np.pi * months / 12)
    values = np.round(values + rng.normal(0.0, 1.0, size=values.size), 1)
    prepared = prepare_monthly_extent(_frame(values))
    result = assess_timing_recurrence(prepared, thresholds=TIMING_IDENTIFIABILITY_DEFAULTS)

    trend = result.trend
    for year, detrended_months in result.trough_month_sets.items():
        year_values = trend.detrended.dropna()
        year_values = year_values.loc[year_values.index.year == year]
        raw = prepared.loc[year_values.index, "extent_pct"].astype(float)
        year_trend = trend.trend.loc[year_values.index]
        floor = float(year_trend.max() - year_trend.min())
        raw_tied = {
            int(stamp.month)
            for stamp, value in raw.items()
            if value <= float(raw.min()) + floor
        }
        assert raw_tied.issubset(set(detrended_months))
```

- [ ] **Step 6: Run it**

Run: `python -m pytest tests/test_seasonality_test.py::test_raw_tied_months_stay_tied_after_detrending -q`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
ruff check hydroseason tests
git add hydroseason/_seasonality_test.py tests/test_seasonality_test.py
git commit -m "feat: test annual timing recurrence on a detrended record" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Candidate decision policy

**Files:**
- Modify: `hydroseason/_decision_policy.py:8-28` and end of file
- Test: `tests/test_decision_policy.py`

**Interfaces:**
- Consumes: `EstablishedDecision` (existing).
- Produces: `SeasonalityPolicy = Literal["timing_recurrence"]`, `CANDIDATE_TIMING_RECURRENCE_POLICY: DecisionPolicy = "candidate_timing_recurrence"`, and
  `decide_timing_recurrence(*, classification: str | None, status: str, reason: str) -> EstablishedDecision`.
  It takes plain values rather than the result object so `_seasonality_test` and `_decision_policy` never import each other.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_decision_policy.py`:

```python
def test_timing_recurrence_seasonal_routes_to_per_year_detection():
    from hydroseason._decision_policy import decide_timing_recurrence

    decision = decide_timing_recurrence(
        classification="seasonal", status="ok", reason="peak_and_trough_recur"
    )

    assert decision.regime == "seasonal"
    assert decision.route == "per_year_detection"
    assert decision.supports_per_year_boundaries is True
    assert decision.timing_evidence == "supported"
    assert decision.policy == "candidate_timing_recurrence"


def test_timing_recurrence_aseasonal_routes_to_events():
    from hydroseason._decision_policy import decide_timing_recurrence

    decision = decide_timing_recurrence(
        classification="aseasonal",
        status="ok",
        reason="peak_and_trough_uniformity_not_rejected",
    )

    assert decision.regime == "aseasonal"
    assert decision.route == "event_characterisation"
    assert decision.supports_per_year_boundaries is False
    assert decision.timing_evidence == "unsupported"


def test_timing_recurrence_never_emits_marginal_and_keeps_insufficiency():
    from hydroseason._decision_policy import decide_timing_recurrence

    decision = decide_timing_recurrence(
        classification=None, status="insufficient_record", reason="trend_unavailable"
    )

    assert decision.regime == "insufficient_record"
    assert decision.route == "insufficient_record"
    assert decision.timing_evidence == "insufficient"
    assert "trend_unavailable" in decision.reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_decision_policy.py -q -k timing_recurrence`
Expected: FAIL with `ImportError: cannot import name 'decide_timing_recurrence'`

- [ ] **Step 3: Extend the policy module**

In `hydroseason/_decision_policy.py`, replace line 15 and add the alpha constant:

```python
DecisionPolicy = Literal[
    "established_0_1_1", "established_0_2_0", "candidate_timing_recurrence"
]
SeasonalityPolicy = Literal["timing_recurrence"]
```

and immediately after `CANDIDATE_POLICY` (line 17) add:

```python
CANDIDATE_TIMING_RECURRENCE_POLICY: DecisionPolicy = "candidate_timing_recurrence"
```

Append at the end of the file:

```python
def decide_timing_recurrence(
    *,
    classification: str | None,
    status: str,
    reason: str,
) -> EstablishedDecision:
    """Map a timing-recurrence result onto regime and route.

    The candidate has two classes. ``aseasonal`` states that recurrence was not
    established; it is not a claim that timing is uniform, and an insufficient
    record is never folded into it.
    """
    if status != "ok":
        regime: Regime = "insufficient_record"
        route: Route = "insufficient_record"
        timing_evidence: TimingEvidence = "insufficient"
    elif classification == "seasonal":
        regime, route, timing_evidence = "seasonal", "per_year_detection", "supported"
    else:
        regime, route, timing_evidence = "aseasonal", "event_characterisation", "unsupported"
    return EstablishedDecision(
        policy=CANDIDATE_TIMING_RECURRENCE_POLICY,
        regime=regime,
        route=route,
        supports_per_year_boundaries=route == "per_year_detection",
        supports_fixed_window=False,
        timing_evidence=timing_evidence,
        reason=(
            f"candidate={CANDIDATE_TIMING_RECURRENCE_POLICY}: regime={regime}; "
            f"status={status}; reason={reason}; route={route}"
        ),
        implementation_policy=CANDIDATE_TIMING_RECURRENCE_POLICY,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_decision_policy.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check hydroseason tests
git add hydroseason/_decision_policy.py tests/test_decision_policy.py
git commit -m "feat: add the timing-recurrence candidate decision policy" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Wire the candidate into `assess_water_regime`

**Files:**
- Modify: `hydroseason/_regime.py:23-44` (imports), `:62-97` (dataclass), `:143-154` (signature), `:237-258` (decision and month selection), `:272-306` (caveats)
- Test: `tests/test_regime.py`

**Interfaces:**
- Consumes: `assess_timing_recurrence`, `TimingRecurrenceResult` (Task 3); `decide_timing_recurrence`, `SeasonalityPolicy` (Task 4).
- Produces: `assess_water_regime(..., seasonality_policy: SeasonalityPolicy | None = None)` and the new field `WaterRegimeAssessment.seasonality_test: TimingRecurrenceResult | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_regime.py`:

```python
def test_default_path_is_unchanged_by_the_new_keyword():
    frame = _series([2, 2, 2, 8, 14, 18, 14, 8, 2, 2, 2, 2], years=20, noise=0.5, seed=1)

    default = assess_water_regime(frame, n_bootstrap=200, random_state=0)
    explicit = assess_water_regime(
        frame, n_bootstrap=200, random_state=0, seasonality_policy=None
    )

    assert default == explicit
    assert default.seasonality_test is None
    assert default.decision_policy == "established_0_2_0"


def test_candidate_labels_a_trending_annual_record_seasonal():
    months = np.arange(360)
    frame = pd.DataFrame(
        {
            "extent_pct": 10.0 + 0.2 * months + 5.0 * np.cos(2 * np.pi * months / 12),
            "invalid_pct": 0.0,
        },
        index=pd.date_range("1990-01-01", periods=360, freq="MS"),
    )

    established = assess_water_regime(frame, n_bootstrap=200, random_state=0)
    candidate = assess_water_regime(
        frame, n_bootstrap=200, random_state=0, seasonality_policy="timing_recurrence"
    )

    assert established.regime == "aseasonal"
    assert candidate.regime == "seasonal"
    assert candidate.public_route == "per_year_detection"
    assert candidate.decision_policy == "candidate_timing_recurrence"
    assert candidate.seasonality_test.reason == "peak_and_trough_recur"
    assert candidate.mean_monthly_trough_month is not None


def test_candidate_never_returns_marginal():
    rng = np.random.default_rng(2)
    frame = pd.DataFrame(
        {"extent_pct": 50.0 + rng.normal(0.0, 2.5, size=180), "invalid_pct": 0.0},
        index=pd.date_range("1990-01-01", periods=180, freq="MS"),
    )

    candidate = assess_water_regime(
        frame, n_bootstrap=200, random_state=0, seasonality_policy="timing_recurrence"
    )

    assert candidate.regime in {"seasonal", "aseasonal", "insufficient_record"}
    assert candidate.regime != "marginal"
```

Note: `mean_monthly_trough_month` arrives in Task 7. Until then, assert `candidate.climatological_trough_month is not None` and update the line in Task 7.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_regime.py -q -k "candidate or default_path"`
Expected: FAIL with `TypeError: assess_water_regime() got an unexpected keyword argument 'seasonality_policy'`

- [ ] **Step 3: Extend imports and the dataclass**

In `hydroseason/_regime.py`, add to the `._decision_policy` import block:

```python
from ._decision_policy import (
    ESTABLISHED_POLICY,
    REGIME_THRESHOLDS,
    DecisionPolicy,
    EstablishedDecision,
    Regime,
    Route,
    SeasonalityPolicy,
    TimingEvidence,
    decide_established,
    decide_timing_recurrence,
)
```

and add a new import:

```python
from ._seasonality_test import TimingRecurrenceResult, assess_timing_recurrence
```

Add the field to `WaterRegimeAssessment`, directly above `decision_policy` (line 96):

```python
    seasonality_test: TimingRecurrenceResult | None = None
```

- [ ] **Step 4: Add the keyword and the candidate branch**

In the signature (line 143-154), add after `random_state: int = 0,`:

```python
    seasonality_policy: SeasonalityPolicy | None = None,
```

Replace the `decision = decide_established(...)` call (lines 237-245) with:

```python
    if seasonality_policy == "timing_recurrence":
        recurrence: TimingRecurrenceResult | None = assess_timing_recurrence(
            prepared,
            thresholds=TIMING_IDENTIFIABILITY_DEFAULTS,
            value_col=value_col,
            measurement_tolerance_pct=measurement_tolerance_pct,
            min_months_per_year=min_months_per_year,
            min_years=_MIN_USABLE_YEARS,
            n_bootstrap=n_bootstrap,
            random_state=random_state,
        )
        decision = decide_timing_recurrence(
            classification=recurrence.classification,
            status=recurrence.status,
            reason=recurrence.reason,
        )
    else:
        recurrence = None
        decision = decide_established(
            n_usable_years=len(qualifying_years),
            amplitude_snr=float(snr),
            peak_timing=peak_timing,
            trough_timing=trough_timing,
            n_peak_timing_years=timing_evidence.n_peak_timing_years,
            n_trough_timing_years=timing_evidence.n_trough_timing_years,
            min_informative_years=TIMING_IDENTIFIABILITY_DEFAULTS.min_informative_years,
        )
```

- [ ] **Step 5: Select the anchor months under both policies**

Replace lines 247-258 with:

```python
    if seasonality_policy == "timing_recurrence":
        # The candidate's own test established recurrence, so the anchor does
        # not additionally require a dominant month from the established
        # summaries. The months themselves are unchanged: mean monthly extent
        # over qualifying years, computed on raw observed values.
        populate_months = (
            decision.regime == "seasonal" and len(qualifying_years) >= _MIN_USABLE_YEARS
        )
        climatological_peak_month = int(climatology.idxmax()) if populate_months else None
        climatological_trough_month = int(climatology.idxmin()) if populate_months else None
    elif (
        decision.regime in ("seasonal", "marginal")
        and decision.timing_evidence != "insufficient"
    ):
        climatological_peak_month = (
            int(climatology.idxmax()) if peak_timing.dominant_month is not None else None
        )
        climatological_trough_month = (
            int(climatology.idxmin()) if trough_timing.dominant_month is not None else None
        )
    else:
        climatological_peak_month = climatological_trough_month = None
```

- [ ] **Step 6: Give the candidate its own caveats**

Replace the three established-policy caveat blocks (lines 272-301, from the `if _MIN_USABLE_YEARS <= peak_timing.n_years < ...` guard through the `aseasonal` caveat) with:

```python
    if seasonality_policy == "timing_recurrence" and recurrence is not None:
        caveats.append(
            "seasonality policy candidate_timing_recurrence (opt-in, unpromoted): "
            f"class decided by calendar recurrence of annual peak and trough timing at "
            f"alpha {recurrence.alpha:g}; aseasonal means recurrence was not established, "
            "not that timing is uniform"
        )
    else:
        if (
            _MIN_USABLE_YEARS
            <= peak_timing.n_years
            < REGIME_THRESHOLDS["timing_record_caution_years"]
        ):
            caveats.append(
                "fewer than 30 usable annual timings: classification is retained, "
                "but uncertainty intervals may be wide"
            )
        if (
            _MIN_USABLE_YEARS
            <= peak_timing.n_years
            < REGIME_THRESHOLDS["uniformity_min_timing_years"]
            and snr >= REGIME_THRESHOLDS["seasonal_min_snr"]
            and peak_timing.ci_low is not None
            and peak_timing.ci_low < REGIME_THRESHOLDS["strong_timing_concentration"]
            and peak_timing.uniformity_p is not None
            and peak_timing.uniformity_p >= REGIME_THRESHOLDS["circular_uniformity_alpha"]
        ):
            caveats.append(
                "the circular-uniformity result has little power with fewer than "
                "10 annual timings, so the record remains marginal"
            )
        if decision.regime == "marginal":
            caveats.append(
                "marginal seasonality: peak and trough timings exhibit interannual variability, "
                "so per-year boundaries are detected dynamically from local extrema"
            )
        if decision.regime == "aseasonal":
            caveats.append(
                "annual timing was not established by the current evidence: peak "
                "and trough are withheld because the record either lacks a "
                "reproducible annual cycle or leaves it unresolved (insufficient "
                "concentration, power, or informative years) -- a non-significant "
                "test does not itself prove uniform timing"
            )
```

Then add `seasonality_test=recurrence,` to the `WaterRegimeAssessment(...)` return, next to `decision_policy=decision.policy,`.

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_regime.py tests/test_seasonality_test.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS. Any failure here means the default path moved; fix before committing.

- [ ] **Step 9: Lint and commit**

```bash
ruff check hydroseason tests
git add hydroseason/_regime.py tests/test_regime.py
git commit -m "feat: offer the timing-recurrence candidate from assess_water_regime" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Pass the policy through `analyze_catchment`

**Files:**
- Modify: `hydroseason/_catchment.py:206-243` (signature and regime call), `:381-411` and `:429-442` (route reasons), `:486-491`
- Test: `tests/test_catchment_analysis.py`

**Interfaces:**
- Consumes: `assess_water_regime(..., seasonality_policy=...)` (Task 5).
- Produces: `analyze_catchment(..., seasonality_policy: SeasonalityPolicy | None = None)`; route reasons quote p-values under the candidate and the SNR otherwise.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_catchment_analysis.py`:

```python
def test_candidate_policy_flows_through_to_route_and_reason():
    import numpy as np
    import pandas as pd

    from hydroseason import analyze_catchment

    months = np.arange(360)
    frame = pd.DataFrame(
        {
            "extent_pct": 10.0 + 0.2 * months + 5.0 * np.cos(2 * np.pi * months / 12),
            "invalid_pct": 0.0,
        },
        index=pd.date_range("1990-01-01", periods=360, freq="MS"),
    )

    analysis = analyze_catchment(frame, seasonality_policy="timing_recurrence")

    assert analysis.regime.decision_policy == "candidate_timing_recurrence"
    assert "peak p=" in analysis.route_reason
    assert "SNR" not in analysis.route_reason
    assert analysis.summary_row(name="synthetic")["decision_policy"] == (
        "candidate_timing_recurrence"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_catchment_analysis.py -q -k candidate_policy`
Expected: FAIL with `TypeError: analyze_catchment() got an unexpected keyword argument 'seasonality_policy'`

- [ ] **Step 3: Add the keyword**

In `hydroseason/_catchment.py`, import `SeasonalityPolicy` from `._decision_policy` alongside the existing names, add to the signature after `trough_refinement_policy: TroughRefinementPolicy | None = None,`:

```python
    seasonality_policy: SeasonalityPolicy | None = None,
```

and pass it in the `assess_water_regime(...)` call (line 233-243):

```python
        seasonality_policy=seasonality_policy,
```

- [ ] **Step 4: Report the deciding evidence**

Add next to `_rounded` (after line 129):

```python
def _policy_evidence(regime: WaterRegimeAssessment) -> str:
    """Name the evidence the active policy actually decided on."""
    test = regime.seasonality_test
    if test is None:
        return f"SNR {regime.amplitude_snr:.2f}"
    peak_p = "n/a" if test.peak.uniformity_p is None else f"{test.peak.uniformity_p:.3f}"
    trough_p = "n/a" if test.trough.uniformity_p is None else f"{test.trough.uniformity_p:.3f}"
    return f"peak p={peak_p}, trough p={trough_p}"
```

Replace every `(SNR {regime.amplitude_snr:.2f})` fragment in route reasons (lines 381, 404, 409, 432, 439, 489) with `({_policy_evidence(regime)})`. For example, line 402-406 becomes:

```python
        if regime.regime == "seasonal":
            route_reason = (
                f"seasonal record ({_policy_evidence(regime)}): "
                "per-year dynamic boundaries are reproducible"
            )
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_catchment_analysis.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
ruff check hydroseason tests
git add hydroseason/_catchment.py tests/test_catchment_analysis.py
git commit -m "feat: route catchment analysis under the seasonality candidate" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Rename `climatological_*` to `mean_monthly_*`

`extent_pct` is observed surface water, not a climate variable, so the mean-by-calendar-month profile is *mean monthly extent*. Old attribute names stay as deprecated aliases; `summary_row` emits both keys until promotion.

**Files:**
- Modify: `hydroseason/_regime.py` (field names, aliases), `hydroseason/_catchment.py:58-59,117-118,282-303,420-421,451-452,460,521-522,541-542`, `hydroseason/_report_copy.py:361-369,470-473`, `hydroseason/_regime_compare.py:133-138`, `docs/report-columns.md`
- Test: `tests/test_regime.py`, `tests/test_catchment_analysis.py`

**Interfaces:**
- Consumes: Tasks 5 and 6.
- Produces: `WaterRegimeAssessment.mean_monthly_peak_month`, `.mean_monthly_trough_month`, `CatchmentAnalysis.mean_monthly_peak_month`, `.mean_monthly_trough_month`, each with a read-only `climatological_*` property alias; `summary_row` keys `mean_monthly_peak_month` and `mean_monthly_trough_month` alongside the existing keys.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_regime.py`:

```python
def test_mean_monthly_month_fields_have_deprecated_aliases():
    frame = _series([2, 2, 2, 8, 14, 18, 14, 8, 2, 2, 2, 2], years=20, noise=0.5, seed=1)

    regime = assess_water_regime(frame, n_bootstrap=200, random_state=0)

    assert regime.mean_monthly_peak_month == regime.climatological_peak_month
    assert regime.mean_monthly_trough_month == regime.climatological_trough_month
    assert regime.mean_monthly_peak_month == 6
```

Append to `tests/test_catchment_analysis.py`:

```python
def test_summary_row_carries_both_month_key_spellings():
    import numpy as np
    import pandas as pd

    from hydroseason import analyze_catchment

    months = np.arange(240)
    frame = pd.DataFrame(
        {"extent_pct": 20.0 + 8.0 * np.cos(2 * np.pi * months / 12), "invalid_pct": 0.0},
        index=pd.date_range("1990-01-01", periods=240, freq="MS"),
    )

    row = analyze_catchment(frame).summary_row(name="synthetic")

    assert row["mean_monthly_peak_month"] == row["climatological_peak_month"]
    assert row["mean_monthly_trough_month"] == row["climatological_trough_month"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_regime.py tests/test_catchment_analysis.py -q -k "alias or both_month_key"`
Expected: FAIL with `AttributeError: 'WaterRegimeAssessment' object has no attribute 'mean_monthly_peak_month'`

- [ ] **Step 3: Rename the regime fields and add aliases**

In `hydroseason/_regime.py`, rename the two fields (lines 86-87) and add aliases after the `supports_fixed_window` property:

```python
    mean_monthly_peak_month: int | None
    mean_monthly_trough_month: int | None
```

```python
    @property
    def climatological_peak_month(self) -> int | None:
        """Deprecated alias for :attr:`mean_monthly_peak_month`."""
        return self.mean_monthly_peak_month

    @property
    def climatological_trough_month(self) -> int | None:
        """Deprecated alias for :attr:`mean_monthly_trough_month`."""
        return self.mean_monthly_trough_month
```

Rename the local variables and the constructor keywords in the same module (lines 247-258 and 329-330) from `climatological_peak_month` / `climatological_trough_month` to `mean_monthly_peak_month` / `mean_monthly_trough_month`.

- [ ] **Step 4: Rename in `_catchment.py`**

Rename the dataclass fields (lines 58-59) to `mean_monthly_peak_month` / `mean_monthly_trough_month`, add the same two alias properties to `CatchmentAnalysis`, update every constructor keyword (lines 420-421, 451-452, 541-542), rename the local variables in the per-year branch (lines 282-303) to `operational_peak_month` / `operational_trough_month` sourced from `regime.mean_monthly_*`, and update lines 460 and 521-522.

In `summary_row`, replace lines 117-118 with:

```python
            "mean_monthly_peak_month": self.mean_monthly_peak_month,
            "mean_monthly_trough_month": self.mean_monthly_trough_month,
            # Deprecated spellings, retained until the candidate is promoted.
            "climatological_peak_month": self.mean_monthly_peak_month,
            "climatological_trough_month": self.mean_monthly_trough_month,
```

Update the warning text at line 301-304 to:

```python
                warnings.append(
                    "a diffuse annual timing summary has no dominant month; "
                    "the dynamic detector uses a private mean-monthly-extent anchor"
                )
```

- [ ] **Step 5: Rename in report copy and comparison**

In `hydroseason/_report_copy.py`, change `"climatological maximum"` to `"maximum of mean monthly extent"` (line 362) and `"climatological minimum"` to `"minimum of mean monthly extent"` (line 369), and read the new attribute names at lines 361, 368 and 470-473. In `hydroseason/_regime_compare.py`, read `.mean_monthly_peak_month` at lines 133-138.

- [ ] **Step 6: Document the columns**

In `docs/report-columns.md`, append these rows to the end of the three-column table under `## Summary information` (the table whose header is `| Field | Units / range | Null / zero semantics |`, currently ending with the `timing_evidence` row at line 207). The month fields are not documented there yet, so these are new rows, not edits:

```markdown
| `mean_monthly_peak_month`, `mean_monthly_trough_month` | Calendar month 1–12 | Month of the maximum/minimum of mean monthly extent over qualifying years. `null` unless the record is routed with identifiable annual timing. |
| `climatological_peak_month`, `climatological_trough_month` | Calendar month 1–12 | Deprecated spellings of the two fields above, emitted unchanged for compatibility. Removed when the seasonality candidate is promoted. |
```

Then, in the hydrological-years table, change the `boundary_basis` description (line 68) from "imposed from a fixed climatological window" to "imposed from a fixed window derived from mean monthly extent".

- [ ] **Step 7: Update the Task 5 test line**

In `tests/test_regime.py::test_candidate_labels_a_trending_annual_record_seasonal`, change the last assertion to `assert candidate.mean_monthly_trough_month is not None`.

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS. Existing tests that read `climatological_*` keep passing through the aliases.

- [ ] **Step 9: Lint and commit**

```bash
ruff check hydroseason tests
git add hydroseason tests docs/report-columns.md
git commit -m "refactor: name the mean monthly extent months without calling them climatology" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Known-truth synthetic records

**Files:**
- Create: `hydroseason/_seasonality_synthetic.py`
- Test: `tests/test_seasonality_synthetic.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `SEASONALITY_VALIDATION_SEEDS = range(90000, 95000)`, `SEASONALITY_FAMILIES: tuple[SeasonalityFamily, ...]`, `SeasonalityTruth`, `SeasonalityRecord(frame: pd.DataFrame, truth: SeasonalityTruth)`, `generate_seasonality_record(*, family: str, n_years: int, replicate: int, variant: str = "base") -> SeasonalityRecord`, `iter_seasonality_records(*, lengths: tuple[int, ...], replicates: int, variants: tuple[str, ...]) -> Iterator[SeasonalityRecord]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seasonality_synthetic.py`:

```python
import numpy as np
import pytest

from hydroseason._seasonality_synthetic import (
    SEASONALITY_FAMILIES,
    generate_seasonality_record,
    iter_seasonality_records,
)

_TRUTH_BY_FAMILY = {family.name: family.truth_seasonal for family in SEASONALITY_FAMILIES}


def test_every_record_stays_inside_the_extent_domain():
    for family in SEASONALITY_FAMILIES:
        record = generate_seasonality_record(family=family.name, n_years=15, replicate=0)
        values = record.frame["extent_pct"].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        assert finite.min() >= 0.0
        assert finite.max() <= 100.0


def test_records_are_deterministic():
    first = generate_seasonality_record(family="sinusoid", n_years=15, replicate=3)
    second = generate_seasonality_record(family="sinusoid", n_years=15, replicate=3)

    assert first.frame.equals(second.frame)
    assert first.truth == second.truth


def test_replicates_differ():
    first = generate_seasonality_record(family="white_noise", n_years=15, replicate=0)
    second = generate_seasonality_record(family="white_noise", n_years=15, replicate=1)

    assert not first.frame.equals(second.frame)


def test_truth_labels_match_the_family_table():
    for name, truth in _TRUTH_BY_FAMILY.items():
        record = generate_seasonality_record(family=name, n_years=7, replicate=0)
        assert record.truth.truth_seasonal is truth


def test_zero_dominated_pulse_has_exact_zero_dry_months():
    record = generate_seasonality_record(family="zero_dominated_pulse", n_years=15, replicate=0)
    values = record.frame["extent_pct"].to_numpy(dtype=float)

    assert (values == 0.0).sum() >= 9 * 15 - 1


def test_missing_variant_blanks_the_requested_fraction():
    record = generate_seasonality_record(
        family="white_noise", n_years=30, replicate=0, variant="missing_25"
    )
    invalid = record.frame["invalid_pct"].to_numpy(dtype=float)

    assert 0.2 <= float((invalid == 100.0).mean()) <= 0.3


def test_iteration_covers_families_lengths_and_replicates():
    records = list(
        iter_seasonality_records(lengths=(7,), replicates=2, variants=("base",))
    )

    assert len(records) == len(SEASONALITY_FAMILIES) * 2


def test_unknown_family_is_rejected():
    with pytest.raises(ValueError, match="unknown family"):
        generate_seasonality_record(family="nonsense", n_years=15, replicate=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_seasonality_synthetic.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydroseason._seasonality_synthetic'`

- [ ] **Step 3: Write the generator**

Create `hydroseason/_seasonality_synthetic.py`:

```python
"""Known-truth records for validating the seasonality candidate.

One partition only: the candidate fits nothing, so there is no calibration
set to keep separate. Seeds are disjoint from every existing corpus.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd

SEASONALITY_VALIDATION_SEEDS = range(90000, 95000)
_BASE_ENTROPY = 90000

_CENTRE_PCT = 50.0
_AMPLITUDE_PCT = 5.0
_NOISE_SD_PCT = 2.5
_TREND_TOTAL_PCT = 40.0
_STRONG_TREND_TOTAL_PCT = 72.0
_STRONG_TREND_NOISE_SD_PCT = 1.0
_STEP_PCT = 20.0
_EVENT_PROBABILITY = 0.08
_EVENT_DECAY_MONTHS = 1.5
_EVENT_BURN_IN_MONTHS = 120
_PULSE_LEVEL_PCT = 30.0
_PULSE_NOISE_SD_PCT = 2.0
_LOW_EXTENT_SCALE = 0.02
_PIXEL_N_AOI = 1000
_MAX_ATTEMPTS = 50

VARIANTS = ("base", "missing_10", "missing_25", "low_state_gap", "pixel_rounded")


@dataclass(frozen=True)
class SeasonalityFamily:
    family_id: int
    name: str
    truth_seasonal: bool | None


SEASONALITY_FAMILIES: tuple[SeasonalityFamily, ...] = (
    SeasonalityFamily(1, "white_noise", False),
    SeasonalityFamily(2, "ar1_0_5", False),
    SeasonalityFamily(3, "ar1_0_8", False),
    SeasonalityFamily(4, "trend", False),
    SeasonalityFamily(5, "strong_trend", False),
    SeasonalityFamily(6, "step", False),
    SeasonalityFamily(7, "events", False),
    SeasonalityFamily(8, "all_zero", False),
    SeasonalityFamily(21, "sinusoid", True),
    SeasonalityFamily(22, "narrow_pulse", True),
    SeasonalityFamily(23, "asymmetric", True),
    SeasonalityFamily(24, "annual_plus_trend", True),
    SeasonalityFamily(25, "annual_plus_strong_trend", True),
    SeasonalityFamily(26, "zero_dominated_pulse", True),
    SeasonalityFamily(27, "timing_jitter", True),
    SeasonalityFamily(41, "two_cycles", None),
    SeasonalityFamily(42, "phase_drift", None),
    SeasonalityFamily(43, "amplitude_curve", None),
)

_FAMILY_BY_NAME = {family.name: family for family in SEASONALITY_FAMILIES}


@dataclass(frozen=True)
class SeasonalityTruth:
    family: str
    family_id: int
    truth_seasonal: bool | None
    n_years: int
    replicate: int
    variant: str
    trough_month: int | None
    n_redraws: int


@dataclass(frozen=True)
class SeasonalityRecord:
    frame: pd.DataFrame
    truth: SeasonalityTruth


def _rng(family_id: int, n_years: int, replicate: int, attempt: int) -> np.random.Generator:
    return np.random.default_rng(
        np.random.SeedSequence([_BASE_ENTROPY, family_id, n_years, replicate, attempt])
    )


def _ar1(rng: np.random.Generator, n: int, coefficient: float, sd: float) -> np.ndarray:
    innovations = rng.normal(0.0, sd * np.sqrt(1.0 - coefficient**2), size=n)
    values = np.empty(n)
    values[0] = rng.normal(0.0, sd)
    for position in range(1, n):
        values[position] = coefficient * values[position - 1] + innovations[position]
    return values


def _centred_trend(n: int, total: float) -> np.ndarray:
    return total * (np.arange(n) / (n - 1) - 0.5)


def _events(rng: np.random.Generator, n: int) -> np.ndarray:
    total = n + _EVENT_BURN_IN_MONTHS
    series = np.zeros(total)
    starts = rng.random(total) < _EVENT_PROBABILITY
    for start in np.flatnonzero(starts):
        amplitude = rng.uniform(_AMPLITUDE_PCT, 2.0 * _AMPLITUDE_PCT)
        offsets = np.arange(total - start)
        series[start:] += amplitude * np.exp(-offsets / _EVENT_DECAY_MONTHS)
    expected = (
        _EVENT_PROBABILITY
        * 1.5
        * _AMPLITUDE_PCT
        / (1.0 - np.exp(-1.0 / _EVENT_DECAY_MONTHS))
    )
    return series[_EVENT_BURN_IN_MONTHS:] - expected


def _triangular_pulse(months: np.ndarray, phase: int, half_width: float) -> np.ndarray:
    offset = (months - phase + 6) % 12 - 6
    shape = np.clip(1.0 - np.abs(offset) / half_width, 0.0, None)
    return 2.0 * _AMPLITUDE_PCT * (shape - shape.mean())


def _asymmetric(months: np.ndarray, phase: int) -> np.ndarray:
    position = (months - phase) % 12
    shape = np.where(position < 3, position / 3.0, 1.0 - (position - 3) / 9.0)
    return 2.0 * _AMPLITUDE_PCT * (shape - shape.mean())


def _latent(family: str, n_years: int, rng: np.random.Generator) -> tuple[np.ndarray, int | None]:
    n = 12 * n_years
    months = np.arange(n)
    phase = int(rng.integers(12))
    noise = rng.normal(0.0, _NOISE_SD_PCT, size=n)
    annual = _AMPLITUDE_PCT * np.cos(2 * np.pi * (months - phase) / 12)
    trough_month = int((phase + 6) % 12) + 1

    if family == "white_noise":
        return _CENTRE_PCT + noise, None
    if family == "ar1_0_5":
        return _CENTRE_PCT + _ar1(rng, n, 0.5, _NOISE_SD_PCT), None
    if family == "ar1_0_8":
        return _CENTRE_PCT + _ar1(rng, n, 0.8, _NOISE_SD_PCT), None
    if family == "trend":
        return _CENTRE_PCT + _centred_trend(n, _TREND_TOTAL_PCT) + noise, None
    if family == "strong_trend":
        strong_noise = rng.normal(0.0, _STRONG_TREND_NOISE_SD_PCT, size=n)
        return _CENTRE_PCT + _centred_trend(n, _STRONG_TREND_TOTAL_PCT) + strong_noise, None
    if family == "step":
        step = np.where(months >= n // 2, _STEP_PCT, 0.0) - _STEP_PCT / 2.0
        return _CENTRE_PCT + step + noise, None
    if family == "events":
        return _CENTRE_PCT + _events(rng, n) + noise, None
    if family == "all_zero":
        return np.zeros(n), None
    if family == "sinusoid":
        return _CENTRE_PCT + annual + noise, trough_month
    if family == "narrow_pulse":
        return _CENTRE_PCT + _triangular_pulse(months, phase, 2.0) + noise, trough_month
    if family == "asymmetric":
        return _CENTRE_PCT + _asymmetric(months, phase) + noise, trough_month
    if family == "annual_plus_trend":
        return _CENTRE_PCT + annual + _centred_trend(n, _TREND_TOTAL_PCT) + noise, trough_month
    if family == "annual_plus_strong_trend":
        strong_noise = rng.normal(0.0, _STRONG_TREND_NOISE_SD_PCT, size=n)
        values = (
            _CENTRE_PCT + annual + _centred_trend(n, _STRONG_TREND_TOTAL_PCT) + strong_noise
        )
        return values, trough_month
    if family == "zero_dominated_pulse":
        wet = np.isin((months - phase) % 12, (0, 1, 2))
        values = np.zeros(n)
        values[wet] = np.clip(
            _PULSE_LEVEL_PCT + rng.normal(0.0, _PULSE_NOISE_SD_PCT, size=int(wet.sum())),
            0.0,
            None,
        )
        return values, int((phase + 6) % 12) + 1
    if family == "timing_jitter":
        jitter = np.repeat(rng.normal(0.0, 1.0, size=n_years), 12)
        shifted = _AMPLITUDE_PCT * np.cos(2 * np.pi * (months - phase - jitter) / 12)
        return _CENTRE_PCT + shifted + noise, trough_month
    if family == "two_cycles":
        return _CENTRE_PCT + _AMPLITUDE_PCT * np.cos(2 * np.pi * (months - phase) / 6) + noise, None
    if family == "phase_drift":
        drift = 6.0 * months / (n - 1)
        return _CENTRE_PCT + _AMPLITUDE_PCT * np.cos(
            2 * np.pi * (months - phase - drift) / 12
        ) + noise, None
    if family == "amplitude_curve":
        ratio = float(rng.choice([0.25, 0.5, 1.0, 2.0, 4.0]))
        scaled = ratio * _NOISE_SD_PCT * np.cos(2 * np.pi * (months - phase) / 12)
        return _CENTRE_PCT + scaled + noise, trough_month
    raise ValueError(f"unknown family {family!r}")


def _apply_variant(
    frame: pd.DataFrame, variant: str, rng: np.random.Generator, trough_month: int | None
) -> pd.DataFrame:
    out = frame.copy()
    if variant == "base":
        return out
    if variant in {"missing_10", "missing_25"}:
        fraction = 0.10 if variant == "missing_10" else 0.25
        blanked = rng.random(len(out)) < fraction
        out.loc[blanked, "extent_pct"] = np.nan
        out.loc[blanked, "invalid_pct"] = 100.0
        return out
    if variant == "low_state_gap":
        if trough_month is None:
            return out
        years = sorted({int(stamp.year) for stamp in out.index})
        for position, year in enumerate(years):
            if position % 3:
                continue
            centre = pd.Timestamp(year=year, month=trough_month, day=1)
            window = pd.date_range(centre - pd.DateOffset(months=1), periods=3, freq="MS")
            present = out.index.intersection(window)
            out.loc[present, "extent_pct"] = np.nan
            out.loc[present, "invalid_pct"] = 100.0
        return out
    if variant == "pixel_rounded":
        scaled = out["extent_pct"].astype(float) * _LOW_EXTENT_SCALE
        n_water = np.rint(scaled / 100.0 * _PIXEL_N_AOI)
        out["extent_pct"] = n_water / _PIXEL_N_AOI * 100.0
        out["n_water"] = n_water.astype("Int64")
        out["n_valid"] = _PIXEL_N_AOI
        out["n_invalid"] = 0
        out["n_aoi"] = _PIXEL_N_AOI
        return out
    raise ValueError(f"unknown variant {variant!r}")


def generate_seasonality_record(
    *,
    family: str,
    n_years: int,
    replicate: int,
    variant: str = "base",
) -> SeasonalityRecord:
    """Generate one record with its truth label, redrawing out-of-domain draws."""
    if family not in _FAMILY_BY_NAME:
        raise ValueError(f"unknown family {family!r}")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    definition = _FAMILY_BY_NAME[family]

    for attempt in range(_MAX_ATTEMPTS):
        rng = _rng(definition.family_id, n_years, replicate, attempt)
        values, trough_month = _latent(family, n_years, rng)
        if np.nanmin(values) < 0.0 or np.nanmax(values) > 100.0:
            continue
        index = pd.date_range("1990-01-01", periods=12 * n_years, freq="MS")
        frame = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)
        frame = _apply_variant(frame, variant, rng, trough_month)
        return SeasonalityRecord(
            frame=frame,
            truth=SeasonalityTruth(
                family=family,
                family_id=definition.family_id,
                truth_seasonal=definition.truth_seasonal,
                n_years=n_years,
                replicate=replicate,
                variant=variant,
                trough_month=trough_month,
                n_redraws=attempt,
            ),
        )
    raise RuntimeError(f"{family} could not be drawn inside 0-100% in {_MAX_ATTEMPTS} attempts")


def iter_seasonality_records(
    *,
    lengths: tuple[int, ...] = (7, 15, 30),
    replicates: int = 200,
    variants: tuple[str, ...] = ("base",),
) -> Iterator[SeasonalityRecord]:
    """Yield every family x length x replicate x variant record, in a fixed order."""
    for variant in variants:
        for definition in SEASONALITY_FAMILIES:
            for n_years in lengths:
                for replicate in range(replicates):
                    yield generate_seasonality_record(
                        family=definition.name,
                        n_years=n_years,
                        replicate=replicate,
                        variant=variant,
                    )
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_seasonality_synthetic.py -q`
Expected: PASS, 8 tests. If `test_every_record_stays_inside_the_extent_domain` fails for `annual_plus_strong_trend`, the redraw loop is working as designed only when the family can fit; check the centring maths before touching any constant.

- [ ] **Step 5: Lint and commit**

```bash
ruff check hydroseason tests
git add hydroseason/_seasonality_synthetic.py tests/test_seasonality_synthetic.py
git commit -m "test: add known-truth records for the seasonality candidate" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Evaluation script and acceptance report

**Files:**
- Create: `scripts/evaluate_timing_recurrence.py`
- Test: `tests/test_evaluate_timing_recurrence.py`

**Interfaces:**
- Consumes: `iter_seasonality_records` (Task 8), `assess_water_regime(..., seasonality_policy=...)` (Task 5).
- Produces: `wilson_upper(successes: int, trials: int, z: float = 1.6448536269514722) -> float`, `score_record(record) -> dict`, `acceptance(metrics: pd.DataFrame) -> dict`, and a CLI writing `protocol.json`, `synthetic_records.csv`, `synthetic_metrics.csv`, `acceptance.json`, `sensitivity_alpha_0_10.csv`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_evaluate_timing_recurrence.py`:

```python
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path("scripts/evaluate_timing_recurrence.py")


def _module():
    spec = importlib.util.spec_from_file_location("evaluate_timing_recurrence", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wilson_upper_matches_known_values():
    module = _module()

    # At n=200 the acceptance boundary sits between 4 and 5 errors: 4 clears the
    # 0.05 bound, 5 does not. Pin both sides so a formula slip cannot pass.
    assert module.wilson_upper(0, 200) == pytest.approx(0.0133, rel=0.01)
    assert module.wilson_upper(4, 200) == pytest.approx(0.0438, rel=0.01)
    assert module.wilson_upper(4, 200) < module.FALSE_SEASONAL_BOUND
    assert module.wilson_upper(5, 200) > module.FALSE_SEASONAL_BOUND


def test_acceptance_fails_when_a_negative_family_exceeds_the_bound():
    module = _module()
    metrics = pd.DataFrame(
        [
            {"family": "white_noise", "truth_seasonal": False, "seasonal": 40, "n": 600},
            {"family": "sinusoid", "truth_seasonal": True, "seasonal": 600, "n": 600,
             "n_years": 30},
        ]
    )

    verdict = module.acceptance(metrics)

    assert verdict["false_seasonal"]["passed"] is False
    assert verdict["false_seasonal"]["failures"][0]["family"] == "white_noise"


def test_scoring_one_record_reports_both_policies():
    module = _module()
    from hydroseason._seasonality_synthetic import generate_seasonality_record

    record = generate_seasonality_record(family="sinusoid", n_years=7, replicate=0)
    row = module.score_record(record)

    assert row["family"] == "sinusoid"
    assert row["truth_seasonal"] is True
    assert row["established_regime"] in {"seasonal", "marginal", "aseasonal", "insufficient_record"}
    assert row["candidate_class"] in {"seasonal", "aseasonal", None}
    assert "candidate_peak_p" in row
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_evaluate_timing_recurrence.py -q`
Expected: FAIL with `FileNotFoundError` for `scripts/evaluate_timing_recurrence.py`.

- [ ] **Step 3: Write the script**

Create `scripts/evaluate_timing_recurrence.py`:

```python
"""Score the seasonality candidate against known-truth synthetic records.

Nothing here selects a parameter. Alpha and every rule were fixed in the
design before any record was drawn, so this script only measures and reports:
a failed acceptance criterion is a finding, never a reason to retune.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import hydroseason  # noqa: E402
from hydroseason._regime import assess_water_regime  # noqa: E402
from hydroseason._seasonality_synthetic import (  # noqa: E402
    SEASONALITY_FAMILIES,
    SeasonalityRecord,
    iter_seasonality_records,
)

Z_ONE_SIDED_95 = 1.6448536269514722
FALSE_SEASONAL_BOUND = 0.05
DETECTION_FLOOR = 0.80
DETECTION_LENGTHS = (15, 30)
SENSITIVITY_ALPHA = 0.10


def wilson_upper(successes: int, trials: int, z: float = Z_ONE_SIDED_95) -> float:
    """One-sided Wilson upper bound for a proportion."""
    if trials <= 0:
        return 1.0
    proportion = successes / trials
    denominator = 1.0 + z**2 / trials
    centre = proportion + z**2 / (2 * trials)
    spread = z * np.sqrt(proportion * (1.0 - proportion) / trials + z**2 / (4 * trials**2))
    return float(min(1.0, (centre + spread) / denominator))


def score_record(record: SeasonalityRecord) -> dict:
    """Score one record under the established policy and the candidate."""
    established = assess_water_regime(record.frame, n_bootstrap=200, random_state=0)
    candidate = assess_water_regime(
        record.frame,
        n_bootstrap=200,
        random_state=0,
        seasonality_policy="timing_recurrence",
    )
    test = candidate.seasonality_test
    return {
        "family": record.truth.family,
        "family_id": record.truth.family_id,
        "truth_seasonal": record.truth.truth_seasonal,
        "n_years": record.truth.n_years,
        "replicate": record.truth.replicate,
        "variant": record.truth.variant,
        "n_redraws": record.truth.n_redraws,
        "established_regime": established.regime,
        "established_route": established.public_route,
        "established_snr": round(float(established.amplitude_snr), 4),
        "candidate_class": test.classification if test else None,
        "candidate_status": test.status if test else None,
        "candidate_reason": test.reason if test else None,
        "candidate_regime": candidate.regime,
        "candidate_route": candidate.public_route,
        "candidate_peak_p": test.peak.uniformity_p if test else None,
        "candidate_trough_p": test.trough.uniformity_p if test else None,
        "candidate_peak_r": test.peak.concentration if test else None,
        "candidate_trough_r": test.trough.concentration if test else None,
        "n_detectable_years": test.n_detectable_years if test else 0,
        "n_timing_eligible_years": test.n_timing_eligible_years if test else 0,
    }


def _seasonal_at(rows: pd.DataFrame, alpha: float) -> pd.Series:
    """Recompute the candidate class at another alpha from saved p-values."""
    peak = rows["candidate_peak_p"]
    trough = rows["candidate_trough_p"]
    return (peak.notna() & trough.notna() & (peak < alpha) & (trough < alpha))


def summarise(records: pd.DataFrame, *, alpha: float) -> pd.DataFrame:
    """Rates by family, length and variant, with Wilson bounds."""
    seasonal = _seasonal_at(records, alpha)
    frame = records.assign(seasonal_call=seasonal)
    grouped = frame.groupby(["family", "truth_seasonal", "variant", "n_years"], dropna=False)
    rows = []
    for (family, truth, variant, n_years), group in grouped:
        successes = int(group["seasonal_call"].sum())
        trials = int(len(group))
        rows.append(
            {
                "family": family,
                "truth_seasonal": truth,
                "variant": variant,
                "n_years": int(n_years),
                "seasonal": successes,
                "n": trials,
                "rate": successes / trials if trials else float("nan"),
                "wilson_upper": wilson_upper(successes, trials),
                "insufficient": int((group["candidate_status"] != "ok").sum()),
            }
        )
    return pd.DataFrame(rows)


def acceptance(metrics: pd.DataFrame) -> dict:
    """Apply the design's predeclared criteria to the metrics table."""
    negatives = metrics.loc[metrics["truth_seasonal"] == False]  # noqa: E712
    pooled = (
        negatives.groupby(["family", "variant"], dropna=False)[["seasonal", "n"]]
        .sum()
        .reset_index()
    )
    false_failures = []
    for row in pooled.itertuples():
        bound = wilson_upper(int(row.seasonal), int(row.n))
        if bound > FALSE_SEASONAL_BOUND:
            false_failures.append(
                {
                    "family": row.family,
                    "variant": row.variant,
                    "seasonal": int(row.seasonal),
                    "n": int(row.n),
                    "wilson_upper": bound,
                }
            )

    positives = metrics.loc[
        (metrics["truth_seasonal"] == True)  # noqa: E712
        & (metrics["n_years"].isin(DETECTION_LENGTHS))
        & (metrics["variant"] == "base")
    ]
    detection_failures = [
        {
            "family": row.family,
            "n_years": int(row.n_years),
            "rate": float(row.rate),
            "n": int(row.n),
        }
        for row in positives.itertuples()
        if float(row.rate) < DETECTION_FLOOR
    ]

    return {
        "false_seasonal": {
            "bound": FALSE_SEASONAL_BOUND,
            "passed": not false_failures,
            "failures": false_failures,
        },
        "detection": {
            "floor": DETECTION_FLOOR,
            "lengths": list(DETECTION_LENGTHS),
            "passed": not detection_failures,
            "failures": detection_failures,
        },
        "status_accounting": {
            "insufficient_records": int(metrics["insufficient"].sum()),
            "note": "insufficient records are counted separately and never as aseasonal",
        },
    }


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=200)
    parser.add_argument("--lengths", type=int, nargs="+", default=[7, 15, 30])
    parser.add_argument(
        "--variants", nargs="+",
        default=["base", "missing_10", "missing_25", "low_state_gap", "pixel_rounded"],
    )
    args = parser.parse_args(argv)

    out_dir = args.out_dir
    if out_dir.exists() and any(out_dir.iterdir()):
        parser.error(f"{out_dir} exists and is not empty; run directories are immutable")
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        score_record(record)
        for record in iter_seasonality_records(
            lengths=tuple(args.lengths),
            replicates=args.replicates,
            variants=tuple(args.variants),
        )
    ]
    records = pd.DataFrame(rows)
    records.to_csv(out_dir / "synthetic_records.csv", index=False)

    metrics = summarise(records, alpha=0.05)
    metrics.to_csv(out_dir / "synthetic_metrics.csv", index=False)
    summarise(records, alpha=SENSITIVITY_ALPHA).to_csv(
        out_dir / "sensitivity_alpha_0_10.csv", index=False
    )

    verdict = acceptance(metrics)
    (out_dir / "acceptance.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")

    protocol = {
        "commit": _git_commit(),
        "hydroseason_version": hydroseason.__version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "alpha": 0.05,
        "sensitivity_alpha": SENSITIVITY_ALPHA,
        "replicates": args.replicates,
        "lengths": args.lengths,
        "variants": args.variants,
        "families": [family.name for family in SEASONALITY_FAMILIES],
        "seed_range": "90000-95000",
        "n_records": int(len(records)),
    }
    (out_dir / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")

    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_evaluate_timing_recurrence.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 5: Smoke-run the script on a tiny grid**

Run: `python scripts/evaluate_timing_recurrence.py --out-dir output/timing-recurrence-smoke --replicates 2 --lengths 7 --variants base`
Expected: JSON verdict printed; `output/timing-recurrence-smoke/` holds five files. Delete the directory afterwards: `rm -rf output/timing-recurrence-smoke`.

- [ ] **Step 6: Lint and commit**

```bash
ruff check hydroseason tests scripts
git add scripts/evaluate_timing_recurrence.py tests/test_evaluate_timing_recurrence.py
git commit -m "test: score the seasonality candidate against known truth" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Full validation run and real-record table

Run the frozen evaluation once, then the protected and development records. Do not change any code in response to what these show; record findings instead.

**Files:**
- Modify: `scripts/evaluate_timing_recurrence.py` (add `--real-root`)
- Create: `case_studies/results/seasonality-timing-recurrence/<run_id>/` (outputs)
- Test: `tests/test_evaluate_timing_recurrence.py`

**Interfaces:**
- Consumes: Task 9.
- Produces: `real_record_rows(paths: dict[str, Path]) -> pd.DataFrame` and the files `real_records.csv`, `real_records.md`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_evaluate_timing_recurrence.py`:

```python
def test_real_record_rows_report_both_policies(tmp_path):
    import numpy as np

    module = _module()
    months = np.arange(240)
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2005-01-01", periods=240, freq="MS"),
            "extent_pct": 20.0 + 8.0 * np.cos(2 * np.pi * months / 12),
            "invalid_pct": 0.0,
        }
    )
    path = tmp_path / "synthetic_catchment.csv"
    frame.to_csv(path, index=False)

    table = module.real_record_rows({"synthetic": path})

    assert list(table["record"]) == ["synthetic"]
    assert table.loc[0, "candidate_class"] in {"seasonal", "aseasonal"}
    assert table.loc[0, "established_regime"] in {
        "seasonal", "marginal", "aseasonal", "insufficient_record"
    }
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_evaluate_timing_recurrence.py -q -k real_record_rows`
Expected: FAIL with `AttributeError: module has no attribute 'real_record_rows'`

- [ ] **Step 3: Add the real-record path**

Add to `scripts/evaluate_timing_recurrence.py`, after `score_record`:

```python
PROTECTED_RECORDS = ("daly_river_nt", "fitzroy_river_wa", "gilbert_river_qld",
                     "lachlan_river_nsw", "moonie_river_qld_nsw")


def _markdown_table(frame: pd.DataFrame) -> str:
    """Render markdown without `DataFrame.to_markdown`, which needs tabulate.

    tabulate is neither installed nor declared in this project, so calling
    `to_markdown` would fail at the end of an hour-long run.
    """
    header = "| " + " | ".join(str(column) for column in frame.columns) + " |"
    rule = "| " + " | ".join("---" for _ in frame.columns) + " |"
    rows = [
        "| " + " | ".join("" if pd.isna(value) else str(value) for value in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join([header, rule, *rows]) + "\n"


def real_record_rows(paths: dict[str, Path]) -> pd.DataFrame:
    """Score named real records under both policies, protected ones included."""
    from hydroseason import load_extent_csv

    rows = []
    for name, path in paths.items():
        frame = load_extent_csv(path, date_col="date", value_col="extent_pct")
        established = assess_water_regime(frame, n_bootstrap=200, random_state=0)
        candidate = assess_water_regime(
            frame, n_bootstrap=200, random_state=0, seasonality_policy="timing_recurrence"
        )
        test = candidate.seasonality_test
        rows.append(
            {
                "record": name,
                "protected": name in PROTECTED_RECORDS,
                "established_regime": established.regime,
                "established_route": established.public_route,
                "established_snr": round(float(established.amplitude_snr), 3),
                "candidate_class": test.classification if test else None,
                "candidate_status": test.status if test else None,
                "candidate_reason": test.reason if test else None,
                "candidate_route": candidate.public_route,
                "candidate_peak_p": test.peak.uniformity_p if test else None,
                "candidate_trough_p": test.trough.uniformity_p if test else None,
                "n_detectable_years": test.n_detectable_years if test else 0,
                "agrees": (
                    (established.regime in {"seasonal", "marginal"})
                    == (candidate.regime == "seasonal")
                ),
            }
        )
    return pd.DataFrame(rows)
```

and in `main`, after the acceptance block:

```python
    if args.real_root is not None:
        paths = {
            path.stem.replace("_30m", ""): path
            for path in sorted(args.real_root.glob("*_30m.csv"))
        }
        table = real_record_rows(paths)
        table.to_csv(out_dir / "real_records.csv", index=False)
        (out_dir / "real_records.md").write_text(_markdown_table(table), encoding="utf-8")
```

with the argument declared as:

```python
    parser.add_argument("--real-root", type=Path, default=None)
```

- [ ] **Step 4: Run the test**

Run: `python -m pytest tests/test_evaluate_timing_recurrence.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 5: Freeze the code, then run the full evaluation**

```bash
git add scripts/evaluate_timing_recurrence.py tests/test_evaluate_timing_recurrence.py
git commit -m "test: score protected and development records under both policies" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
python scripts/evaluate_timing_recurrence.py \
    --out-dir case_studies/results/seasonality-timing-recurrence/2026-09-12 \
    --real-root case_studies/data/extent
```

Expected: runs to completion (roughly 1–1.5 hours single-core) and prints the acceptance verdict.

- [ ] **Step 6: Write the findings**

Create `case_studies/results/seasonality-timing-recurrence/2026-09-12/findings.md` covering, with numbers from the run:
- the acceptance verdict for each criterion, with numerators and denominators;
- every family where the candidate and the established policy disagree;
- the protected records: Daly, Fitzroy and Gilbert must be `seasonal` with route `per_year_detection`; report Lachlan and Moonie changes with their p-values and month sets;
- the α = 0.10 sensitivity compared with α = 0.05;
- failure modes observed (families where detection fell below 0.80, and any false-seasonal bound above 0.05).

If a criterion fails, record it as a finding. Do not adjust α, the families, or any threshold.

- [ ] **Step 7: Commit the run**

```bash
git add case_studies/results/seasonality-timing-recurrence/2026-09-12
git commit -m "docs: record the timing-recurrence validation run" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Candidate documentation

**Files:**
- Create: `docs/decision-policy-timing-recurrence.md`
- Modify: `docs/decision-policy.md:5-11`, `docs/superpowers/plans/2026-09-11-camels-aus-validation-handoff.md` (step 2), `CHANGELOG.md`
- Test: `tests/test_decision_policy_docs.py`

**Interfaces:**
- Consumes: every earlier task.
- Produces: no code interface; the doc test pins the claims that must stay true.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_decision_policy_docs.py`:

```python
def test_timing_recurrence_candidate_is_documented_as_unpromoted():
    text = (ROOT / "docs" / "decision-policy-timing-recurrence.md").read_text(encoding="utf-8")
    main = (ROOT / "docs" / "decision-policy.md").read_text(encoding="utf-8")

    required = {
        "candidate_timing_recurrence",
        "alpha = 0.05",
        "centred 2x12 moving average",
        "mean monthly extent",
        "aseasonal means recurrence was not established",
        "SEASONALITY_VALIDATION_SEEDS = range(90000, 95000)",
        "false-seasonal Wilson upper bound <= 0.05",
        "detection >= 0.80 at 15 and 30 years",
        "ESTABLISHED_POLICY remains established_0_2_0",
    }
    missing = sorted(phrase for phrase in required if phrase not in text)
    assert not missing, f"candidate policy record is missing: {missing}"
    assert "candidate_timing_recurrence" in main
    assert "opt-in" in main
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_decision_policy_docs.py -q -k timing_recurrence`
Expected: FAIL with `FileNotFoundError` for `docs/decision-policy-timing-recurrence.md`.

- [ ] **Step 3: Write the policy record**

Create `docs/decision-policy-timing-recurrence.md` containing, in prose that includes every phrase the test requires:
- Status: opt-in candidate `candidate_timing_recurrence`, not promoted; `ESTABLISHED_POLICY remains established_0_2_0`.
- The rule: detrend with a `centred 2x12 moving average`; take tie-aware annual peak and trough month sets on the detrended series with the tolerance widened by the year's trend range; weighted Kuiper uniformity test on each; `seasonal` when both reject at `alpha = 0.05`; otherwise `aseasonal`, and `aseasonal means recurrence was not established`.
- The anchor months are the peak and trough of `mean monthly extent`, unchanged.
- Validation: `SEASONALITY_VALIDATION_SEEDS = range(90000, 95000)`, `false-seasonal Wilson upper bound <= 0.05` per non-seasonal family, `detection >= 0.80 at 15 and 30 years`, with the run directory named.
- What promotion still requires: the independent CAMELS-AUS cohort, migration notes, and removal of the deprecated `climatological_*` aliases.

- [ ] **Step 4: Point the main policy doc at it**

In `docs/decision-policy.md`, after the trough-refinement paragraph (line 11), add:

```markdown
Seasonality classification has one opt-in, unpromoted candidate,
`candidate_timing_recurrence`, selected with `seasonality_policy="timing_recurrence"`
and off by default. It classifies a record `seasonal` or `aseasonal` from the
calendar recurrence of annual peak and trough timing on a detrended record. See
[the candidate record](decision-policy-timing-recurrence.md); the promotion gate
below applies before it could become authoritative.
```

- [ ] **Step 5: Note it in the CAMELS handoff**

In `docs/superpowers/plans/2026-09-11-camels-aus-validation-handoff.md`, step 2, add a bullet:

```markdown
   Record `regime`/`route` under **both** `established_0_2_0` and
   `seasonality_policy="timing_recurrence"` in this same pass. The sealed
   partition is single-use, so a second run to obtain candidate labels is not
   available.
```

- [ ] **Step 6: Add the changelog entry**

In `CHANGELOG.md`, add an `### Added` subsection directly under the `## [Unreleased]` heading, above the existing `### Fixed` block:

```markdown
### Added
- Opt-in `seasonality_policy="timing_recurrence"` candidate on `assess_water_regime`
  and `analyze_catchment`: a binary seasonal/aseasonal classification from the
  calendar recurrence of annual peak and trough timing, tested on a detrended
  record. Default behaviour is unchanged.
- `mean_monthly_peak_month` and `mean_monthly_trough_month` replace the
  `climatological_*` spellings, which remain as deprecated aliases.
```

- [ ] **Step 7: Run the doc tests and the full suite**

Run: `python -m pytest tests/test_decision_policy_docs.py -q && python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add docs CHANGELOG.md tests/test_decision_policy_docs.py
git commit -m "docs: record the timing-recurrence candidate policy" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Out of scope

Named here so no task quietly absorbs them:

- The CAMELS-AUS cohort protocol and any CAMELS run.
- Switching the default policy, removing the deprecated aliases, or assigning a promoted policy identifier.
- Report columns beyond the month rename, CLI flags, and batch interfaces for the candidate.
- Manuscript Methods edits (the draft paragraph in the spec is applied only after promotion).
- The anchor month and every boundary method: `_dynamic_year`, trough refinement, and the resolved-cycle check are untouched.
- Renaming or removing the unreachable `fixed_climatological_window` route literal.
