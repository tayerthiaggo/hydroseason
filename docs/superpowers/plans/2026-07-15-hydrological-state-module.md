# Dynamic Hydrological-Year and Surface-Water Condition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add quality-aware, dynamic trough-to-trough hydrological years and historical surface-water condition metrics for intermittent rivers and wetlands, while preserving the existing fixed-window API.

**Architecture:** Keep `hydro_year.py` unchanged as the legacy comparison path. Add focused internal modules for monthly input quality, harmonic seasonality, dynamic cycle detection, condition metrics, and AOI aggregation; re-export a small public API through `hydrological_state.py`. Every scientific method is independently testable with deterministic monthly data before orchestration or documentation is added.

**Tech Stack:** Python 3.10+, pandas 2.0+, NumPy 1.24+, pytest 8.0+. No new runtime dependency.

**Approved design:** `docs/superpowers/specs/2026-07-15-hydrological-state-design.md`

## Global Constraints

- Surface-water extent condition and timing only: never label output as discharge, volume, drought, stress, ecological condition, or causal attribution.
- Dynamic years are one nominal trough opportunity per calendar year, with observed boundaries allowed to move three months early or late by default.
- A temporary mid-dry rise must not split a hydrological year: default recovery requires two rising months and four subsequent months without return to the low plateau.
- An unresolved nominal trough breaks the sequence; never join the surrounding cycles.
- Existing `HydroYearConfig`, `suggest_hydro_year_config`, `detect_hydrological_years`, reports, and notebooks remain behaviorally unchanged.
- Quality conversion is exactly `observed_fraction = 1 - invalid_pct / 100`; unknown quality is not fully observed.
- Public annual values are observed monthly values at selected dates; do not substitute harmonic fitted values.
- Historical peak and trough percentiles are separate axes and use a fixed, explicit reference period.
- Basin percentages come from summed pixel counts or explicit area weights; reject unweighted means of AOI percentages.
- Low-variability systems retain continuous metrics but do not receive public extreme-condition labels by default.
- Keep pandas/NumPy as the only core dependencies. Do not add SciPy, statsmodels, or a remote-data dependency.
- Use test-first implementation. Commit only the files listed in each task; never include unrelated dirty-worktree changes.

## File Structure

- Create `hydroseason/_state_input.py`: canonical monthly axis, counts validation, quality states, and observed fraction.
- Create `hydroseason/_seasonality.py`: small harmonic models, whole-year bootstrap, and advisory pattern result.
- Create `hydroseason/_dynamic_year.py`: dynamic configuration, trough opportunities, pulse rejection, and annual cycle metrics.
- Create `hydroseason/_condition.py`: annual recharge/refuge percentiles, sequences, and monthly same-month anomalies.
- Create `hydroseason/_aggregation.py`: count-weighted or explicit-area-weighted basin monthly extent.
- Create `hydroseason/hydrological_state.py`: stable public re-exports and `analyze_hydrological_state` orchestration.
- Modify `hydroseason/__init__.py`: additive public exports only.
- Create focused tests matching each internal module plus mock and Fitzroy validation tests.
- Create `tests/fixtures/dynamic_state_mock.csv` and `tests/fixtures/dynamic_state_truth.csv`: deterministic 30-year benchmark and independent truth.
- Create `tests/fixtures/fitzroy_kimberley_monthly.csv` and `tests/fixtures/fitzroy_kimberley_legacy.csv`: frozen, provenance-labelled real-case regression data.
- Create `docs/hydrological-state.md` and modify `mkdocs.yml`: usage, interpretation, validation, and limitations. Do not modify report generation in this plan.

---

### Task 1: Canonical monthly input and quality contract

**Files:**
- Create: `hydroseason/_state_input.py`
- Create: `tests/test_state_input.py`

**Interfaces:**
- Produces: `prepare_monthly_extent(extent, *, value_col="extent_pct", date_col=None, max_invalid_pct=20.0, allow_unknown_quality=False) -> pd.DataFrame`.
- Output columns: `extent_pct`, optional counts, `invalid_pct`, `observed_fraction`, `quality_state`, `candidate_usable` on a complete month-start index.
- Consumers: Tasks 2-6.

- [ ] **Step 1: Write failing tests for the percentage conversion and four quality states**

```python
# tests/test_state_input.py
import numpy as np
import pandas as pd
import pytest

from hydroseason._state_input import prepare_monthly_extent


def test_invalid_percentage_is_converted_to_fraction_once():
    frame = pd.DataFrame(
        {"extent_pct": [40.0], "invalid_pct": [5.0]},
        index=pd.to_datetime(["2020-01-01"]),
    )
    result = prepare_monthly_extent(frame)
    assert result.iloc[0]["observed_fraction"] == pytest.approx(0.95)
    assert result.iloc[0]["quality_state"] == "usable"
    assert bool(result.iloc[0]["candidate_usable"])


def test_quality_states_are_explicit_and_unknown_is_fail_closed():
    index = pd.date_range("2020-01-01", periods=4, freq="MS")
    frame = pd.DataFrame(
        {"extent_pct": [10.0, 20.0, np.nan, 40.0], "invalid_pct": [0.0, 21.0, 100.0, np.nan]},
        index=index,
    )
    result = prepare_monthly_extent(frame)
    assert result["quality_state"].tolist() == ["usable", "low", "missing", "unknown"]
    assert result["candidate_usable"].tolist() == [True, False, False, False]
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m pytest tests/test_state_input.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'hydroseason._state_input'`.

- [ ] **Step 3: Implement complete-axis coercion, count validation, and quality states**

```python
# hydroseason/_state_input.py
from __future__ import annotations

import numpy as np
import pandas as pd


def prepare_monthly_extent(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    max_invalid_pct: float = 20.0,
    allow_unknown_quality: bool = False,
) -> pd.DataFrame:
    if not 0.0 <= max_invalid_pct <= 100.0:
        raise ValueError("max_invalid_pct must be between 0 and 100.")
    if isinstance(extent, pd.Series):
        frame = extent.rename(value_col).to_frame()
    else:
        frame = extent.copy()
    if date_col is not None:
        frame.index = pd.to_datetime(frame.pop(date_col))
    else:
        frame.index = pd.to_datetime(frame.index)
    frame.index = frame.index.to_period("M").to_timestamp()
    if frame.index.has_duplicates:
        months = sorted(frame.index[frame.index.duplicated(False)].strftime("%Y-%m").unique())
        raise ValueError(f"duplicate month timestamps: {months}.")
    frame = frame.sort_index()
    if frame.empty:
        return pd.DataFrame(columns=[value_col, "invalid_pct", "observed_fraction", "quality_state", "candidate_usable"])
    frame = frame.reindex(pd.date_range(frame.index.min(), frame.index.max(), freq="MS"))

    count_cols = ["n_water", "n_valid", "n_invalid", "n_aoi"]
    present = set(count_cols).intersection(frame.columns)
    if present and present != set(count_cols):
        missing = sorted(set(count_cols) - present)
        raise ValueError(f"pixel-count input requires all count columns; missing {missing}.")
    if present:
        counts = frame[count_cols].apply(pd.to_numeric, errors="coerce")
        if (counts.dropna() < 0).any().any():
            raise ValueError("pixel counts must be non-negative.")
        complete_counts = counts.dropna()
        if ((complete_counts["n_water"] > complete_counts["n_valid"]) | (complete_counts["n_valid"] + complete_counts["n_invalid"] != complete_counts["n_aoi"])).any():
            raise ValueError("pixel counts violate n_water <= n_valid and n_valid + n_invalid == n_aoi.")
        frame[value_col] = np.where(counts["n_valid"] > 0, 100.0 * counts["n_water"] / counts["n_valid"], np.nan)
        frame["invalid_pct"] = np.where(counts["n_aoi"] > 0, 100.0 * counts["n_invalid"] / counts["n_aoi"], np.nan)

    frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
    if ((frame[value_col] < 0) | (frame[value_col] > 100)).dropna().any():
        raise ValueError("extent_pct must be between 0 and 100.")
    if "invalid_pct" not in frame:
        frame["invalid_pct"] = np.nan
    frame["invalid_pct"] = pd.to_numeric(frame["invalid_pct"], errors="coerce")
    if ((frame["invalid_pct"] < 0) | (frame["invalid_pct"] > 100)).dropna().any():
        raise ValueError("invalid_pct must be between 0 and 100.")

    frame["observed_fraction"] = 1.0 - frame["invalid_pct"] / 100.0
    frame["quality_state"] = np.select(
        [
            frame[value_col].isna(),
            frame["invalid_pct"].isna(),
            frame["invalid_pct"] > max_invalid_pct,
        ],
        ["missing", "unknown", "low"],
        default="usable",
    )
    frame["candidate_usable"] = (frame["quality_state"] == "usable") | (
        allow_unknown_quality & (frame["quality_state"] == "unknown")
    )
    return frame.rename(columns={value_col: "extent_pct"})
```

- [ ] **Step 4: Add count arithmetic, inserted-gap, unknown opt-in, duplicate, and range tests**

```python
def test_counts_are_authoritative_and_gap_month_is_missing():
    frame = pd.DataFrame(
        {
            "n_water": [20, 30], "n_valid": [80, 60],
            "n_invalid": [20, 40], "n_aoi": [100, 100],
            "extent_pct": [99.0, 99.0],
        },
        index=pd.to_datetime(["2020-01-01", "2020-03-01"]),
    )
    result = prepare_monthly_extent(frame)
    assert result.loc["2020-01-01", "extent_pct"] == pytest.approx(25.0)
    assert result.loc["2020-03-01", "invalid_pct"] == pytest.approx(40.0)
    assert result.loc["2020-02-01", "quality_state"] == "missing"


def test_unknown_quality_can_be_explicitly_enabled():
    series = pd.Series([12.0], index=pd.to_datetime(["2020-01-01"]))
    assert prepare_monthly_extent(series)["candidate_usable"].tolist() == [False]
    assert prepare_monthly_extent(series, allow_unknown_quality=True)["candidate_usable"].tolist() == [True]
```

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_state_input.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the quality seam**

```bash
git add hydroseason/_state_input.py tests/test_state_input.py
git commit -m "feat: normalize monthly extent quality"
```

---

### Task 2: Advisory harmonic seasonality and dynamic configuration

**Files:**
- Create: `hydroseason/_seasonality.py`
- Create: `tests/test_seasonality.py`
- Create: `hydroseason/_dynamic_year.py`
- Create: `tests/test_dynamic_year.py`

**Interfaces:**
- Produces: frozen `SeasonalPatternResult` exactly matching the approved spec.
- Produces: `classify_seasonal_pattern(extent, *, n_bootstrap=200, random_state=0, measurement_tolerance_pct=1.0) -> SeasonalPatternResult`.
- Produces: frozen `DynamicHydroYearConfig` exactly matching the approved spec.
- Produces: `suggest_dynamic_hydro_year_config(extent, *, pattern=None, **overrides) -> DynamicHydroYearConfig`.
- Consumes: `prepare_monthly_extent` from Task 1.

- [ ] **Step 1: Write failing classification tests using deterministic complete years**

```python
# tests/test_seasonality.py
import numpy as np
import pandas as pd

from hydroseason._seasonality import classify_seasonal_pattern


def _signal(values, years=12):
    index = pd.date_range("2000-01-01", periods=12 * years, freq="MS")
    return pd.DataFrame(
        {"extent_pct": np.tile(values, years), "invalid_pct": 0.0},
        index=index,
    )


def test_unimodal_bimodal_low_variability_and_short_records():
    unimodal = 30.0 + 20.0 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    bimodal = 30.0 + 15.0 * np.cos(4 * np.pi * (np.arange(12) - 1) / 12)
    assert classify_seasonal_pattern(_signal(unimodal), n_bootstrap=40).pattern == "unimodal_annual"
    assert classify_seasonal_pattern(_signal(bimodal), n_bootstrap=40).pattern == "bimodal_or_complex"
    assert classify_seasonal_pattern(_signal(np.repeat(20.0, 12)), n_bootstrap=40).pattern == "low_variability"
    assert classify_seasonal_pattern(_signal(unimodal, years=4), n_bootstrap=40).pattern == "insufficient_record"
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m pytest tests/test_seasonality.py -q`

Expected: FAIL during collection because `_seasonality.py` does not exist.

- [ ] **Step 3: Implement AICc model selection, circular extrema, and whole-year bootstrap**

```python
# hydroseason/_seasonality.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._state_input import prepare_monthly_extent


Pattern = Literal["unimodal_annual", "bimodal_or_complex", "weak_or_irregular", "low_variability", "insufficient_record"]


@dataclass(frozen=True)
class SeasonalPatternResult:
    pattern: Pattern
    expected_peak_month: int | None
    expected_trough_month: int | None
    secondary_peak_month: int | None
    secondary_trough_month: int | None
    seasonal_strength: float
    bootstrap_support: float
    peak_phase_iqr_months: float | None
    trough_phase_iqr_months: float | None
    n_complete_years: int


def _design(month: np.ndarray, order: int) -> np.ndarray:
    theta = 2.0 * np.pi * (month - 1) / 12.0
    columns = [np.ones(len(month))]
    for harmonic in range(1, order + 1):
        columns.extend([np.sin(harmonic * theta), np.cos(harmonic * theta)])
    return np.column_stack(columns)


def _fit(month: np.ndarray, values: np.ndarray, order: int) -> tuple[np.ndarray, float]:
    matrix = _design(month, order)
    beta = np.linalg.lstsq(matrix, values, rcond=None)[0]
    residual = values - matrix @ beta
    rss = max(float(residual @ residual), np.finfo(float).tiny)
    n, k = len(values), matrix.shape[1]
    aic = n * np.log(rss / n) + 2 * k
    aicc = aic + (2 * k * (k + 1) / (n - k - 1)) if n > k + 1 else np.inf
    return beta, float(aicc)


def _local_extrema(curve: np.ndarray, kind: str) -> list[int]:
    sign = 1.0 if kind == "max" else -1.0
    scaled = sign * curve
    return [i + 1 for i in range(12) if scaled[i] > scaled[(i - 1) % 12] and scaled[i] >= scaled[(i + 1) % 12]]


def _phase_iqr(months: list[int]) -> float | None:
    if not months:
        return None
    radians = 2.0 * np.pi * (np.asarray(months) - 1) / 12.0
    centre = np.angle(np.mean(np.exp(1j * radians)))
    offsets = np.angle(np.exp(1j * (radians - centre))) * 12.0 / (2.0 * np.pi)
    return float(np.percentile(offsets, 75) - np.percentile(offsets, 25))


def _classify_values(month: np.ndarray, values: np.ndarray, tolerance: float) -> tuple[Pattern, np.ndarray, int, float]:
    fits = [_fit(month, values, order) for order in (0, 1, 2)]
    order = int(np.argmin([item[1] for item in fits]))
    beta = fits[order][0]
    curve = _design(np.arange(1, 13), order) @ beta
    intercept_rss = max(float(np.sum((values - values.mean()) ** 2)), np.finfo(float).tiny)
    selected_rss = max(float(np.sum((values - _design(month, order) @ beta) ** 2)), np.finfo(float).tiny)
    strength = float(np.clip(1.0 - selected_rss / intercept_rss, 0.0, 1.0))
    if float(curve.max() - curve.min()) <= tolerance:
        return "low_variability", curve, order, strength
    if order == 0:
        return "weak_or_irregular", curve, order, strength
    maxima = _local_extrema(curve, "max")
    return ("unimodal_annual" if len(maxima) == 1 else "bimodal_or_complex"), curve, order, strength


def classify_seasonal_pattern(extent, *, n_bootstrap: int = 200, random_state: int = 0, measurement_tolerance_pct: float = 1.0) -> SeasonalPatternResult:
    frame = prepare_monthly_extent(extent, allow_unknown_quality=False)
    usable = frame.loc[frame["candidate_usable"]]
    complete_years = [year for year, group in usable.groupby(usable.index.year) if set(group.index.month) == set(range(1, 13))]
    if len(complete_years) < 5:
        return SeasonalPatternResult("insufficient_record", None, None, None, None, 0.0, 0.0, None, None, len(complete_years))
    sample = usable.loc[usable.index.year.isin(complete_years)]
    pattern, curve, _, strength = _classify_values(sample.index.month.to_numpy(), sample["extent_pct"].to_numpy(float), measurement_tolerance_pct)
    maxima, minima = _local_extrema(curve, "max"), _local_extrema(curve, "min")
    peaks = sorted(maxima, key=lambda month: curve[month - 1], reverse=True)
    troughs = sorted(minima, key=lambda month: curve[month - 1])
    peak = peaks[0] if peaks else int(np.argmax(curve) + 1)
    trough = troughs[0] if troughs else int(np.argmin(curve) + 1)

    rng = np.random.default_rng(random_state)
    support, boot_peaks, boot_troughs = 0, [], []
    by_year = {year: sample.loc[sample.index.year == year] for year in complete_years}
    for _ in range(n_bootstrap):
        draw = [by_year[int(year)] for year in rng.choice(complete_years, len(complete_years), replace=True)]
        boot = pd.concat(draw, ignore_index=True)
        boot_month = np.tile(np.arange(1, 13), len(draw))
        boot_pattern, boot_curve, _, _ = _classify_values(boot_month, boot["extent_pct"].to_numpy(float), measurement_tolerance_pct)
        support += int(boot_pattern == pattern)
        boot_peaks.append(int(np.argmax(boot_curve) + 1))
        boot_troughs.append(int(np.argmin(boot_curve) + 1))
    bootstrap_support = support / n_bootstrap if n_bootstrap else 0.0
    if pattern not in ("low_variability", "insufficient_record") and bootstrap_support < 0.80:
        pattern = "weak_or_irregular"
    stable_peak = None if pattern == "low_variability" else peak
    stable_trough = None if pattern == "low_variability" else trough
    return SeasonalPatternResult(
        pattern, stable_peak, stable_trough,
        peaks[1] if len(peaks) > 1 else None,
        troughs[1] if len(troughs) > 1 else None,
        strength, bootstrap_support, _phase_iqr(boot_peaks), _phase_iqr(boot_troughs), len(complete_years),
    )
```

- [ ] **Step 4: Add dataclass validation and advisory configuration tests**

```python
# tests/test_dynamic_year.py
import numpy as np
import pandas as pd
import pytest

from hydroseason._dynamic_year import DynamicHydroYearConfig, suggest_dynamic_hydro_year_config
from hydroseason._seasonality import classify_seasonal_pattern


def _monsoonal(years=12):
    index = pd.date_range("2000-01-01", periods=years * 12, freq="MS")
    values = 30.0 + 25.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_suggestion_uses_advisory_phase_and_user_overrides_win():
    extent = _monsoonal()
    pattern = classify_seasonal_pattern(extent, n_bootstrap=40)
    config = suggest_dynamic_hydro_year_config(extent, pattern=pattern, trough_search_radius_months=2)
    assert config.expected_trough_month == pattern.expected_trough_month
    assert config.expected_peak_month == pattern.expected_peak_month
    assert config.trough_search_radius_months == 2


def test_unstable_pattern_requires_explicit_trough():
    extent = _monsoonal(years=4)
    with pytest.raises(ValueError, match="expected_trough_month"):
        suggest_dynamic_hydro_year_config(extent)


def test_dynamic_config_rejects_invalid_recovery_geometry():
    with pytest.raises(ValueError):
        DynamicHydroYearConfig(expected_trough_month=13)
    with pytest.raises(ValueError):
        DynamicHydroYearConfig(expected_trough_month=9, pulse_rejection_window_months=0)
```

- [ ] **Step 5: Implement validated dynamic configuration and suggestion**

```python
# hydroseason/_dynamic_year.py -- initial content
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._seasonality import SeasonalPatternResult, classify_seasonal_pattern
from ._state_input import prepare_monthly_extent


@dataclass(frozen=True)
class DynamicHydroYearConfig:
    expected_trough_month: int
    expected_peak_month: int | None = None
    trough_search_radius_months: int = 3
    dry_plateau_rule: Literal["last_before_confirmed_recovery", "middle", "first"] = "last_before_confirmed_recovery"
    sustained_rise_months: int = 2
    pulse_rejection_window_months: int = 4
    max_invalid_pct: float = 20.0
    allow_unknown_quality: bool = False
    min_usable_months_per_cycle: int = 8
    min_usable_trough_candidates: int = 2
    min_baseline_cycles: int = 10
    low_percentile: float = 20.0
    high_percentile: float = 80.0
    measurement_tolerance_pct: float = 1.0

    def __post_init__(self) -> None:
        if self.expected_trough_month not in range(1, 13):
            raise ValueError("expected_trough_month must be in 1..12.")
        if self.expected_peak_month is not None and self.expected_peak_month not in range(1, 13):
            raise ValueError("expected_peak_month must be in 1..12.")
        if not 0 <= self.trough_search_radius_months <= 5:
            raise ValueError("trough_search_radius_months must be in 0..5.")
        if self.sustained_rise_months < 1 or self.pulse_rejection_window_months < 1:
            raise ValueError("recovery windows must be positive.")
        if not 0 <= self.max_invalid_pct <= 100:
            raise ValueError("max_invalid_pct must be between 0 and 100.")
        if not 0 <= self.low_percentile < self.high_percentile <= 100:
            raise ValueError("condition percentiles must satisfy 0 <= low < high <= 100.")
        if self.measurement_tolerance_pct < 0:
            raise ValueError("measurement_tolerance_pct must be non-negative.")


def suggest_dynamic_hydro_year_config(extent, *, pattern: SeasonalPatternResult | None = None, **overrides) -> DynamicHydroYearConfig:
    result = pattern or classify_seasonal_pattern(extent)
    user_supplied_trough = "expected_trough_month" in overrides
    expected_trough = overrides.pop("expected_trough_month", result.expected_trough_month)
    if expected_trough is None or result.pattern in {"weak_or_irregular", "low_variability", "insufficient_record"} and not user_supplied_trough:
        raise ValueError("No stable trough phase; supply expected_trough_month explicitly.")
    fields = {
        "expected_trough_month": expected_trough,
        "expected_peak_month": result.expected_peak_month,
    }
    fields.update(overrides)
    return DynamicHydroYearConfig(**fields)
```

- [ ] **Step 6: Run Task 2 tests**

Run: `python -m pytest tests/test_seasonality.py tests/test_dynamic_year.py -q`

Expected: PASS.

- [ ] **Step 7: Commit advisory classification and configuration**

```bash
git add hydroseason/_seasonality.py hydroseason/_dynamic_year.py tests/test_seasonality.py tests/test_dynamic_year.py
git commit -m "feat: advise dynamic hydro-year phase"
```

### Task 3: Nominal trough opportunities and pulse-rejected recovery

**Files:**
- Modify: `hydroseason/_dynamic_year.py`
- Modify: `tests/test_dynamic_year.py`

**Interfaces:**
- Produces internal `_find_trough_opportunities(frame: pd.DataFrame, config: DynamicHydroYearConfig) -> pd.DataFrame`.
- Each row contains `hy_year`, `status`, `status_reason`, `trough_month`, `trough_extent_pct`, `trough_invalid_pct`, `boundary_status`, and `phase_shift_months`.
- Consumer: Task 4.

- [ ] **Step 1: Write failing tests for temporary rain, provisional record end, and unresolved coverage**

```python
# append to tests/test_dynamic_year.py
from hydroseason._dynamic_year import _find_trough_opportunities
from hydroseason._state_input import prepare_monthly_extent


def _candidate_frame(start="2018-01-01", periods=60):
    index = pd.date_range(start, periods=periods, freq="MS")
    values = 20.0 + 15.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_mid_dry_two_month_rise_is_rejected_when_water_returns_low():
    raw = _candidate_frame()
    raw.loc["2020-07-01":"2021-02-01", "extent_pct"] = [5.0, 8.0, 9.0, 5.0, 8.0, 12.0, 20.0, 25.0]
    frame = prepare_monthly_extent(raw)
    config = DynamicHydroYearConfig(expected_trough_month=9, measurement_tolerance_pct=0.5)
    rows = _find_trough_opportunities(frame, config)
    row = rows.loc[rows["hy_year"] == 2020].iloc[0]
    assert row["trough_month"] == pd.Timestamp("2020-10-01")
    assert row["boundary_status"] == "confirmed"


def test_final_low_is_retained_as_provisional_when_recovery_window_is_incomplete():
    raw = _candidate_frame(periods=34)
    raw.loc["2020-09-01":"2020-10-01", "extent_pct"] = [2.0, 4.0]
    rows = _find_trough_opportunities(prepare_monthly_extent(raw), DynamicHydroYearConfig(expected_trough_month=9))
    row = rows.loc[rows["hy_year"] == 2020].iloc[0]
    assert row["trough_month"] == pd.Timestamp("2020-09-01")
    assert row["boundary_status"] == "provisional"


def test_insufficient_candidate_coverage_is_an_explicit_row():
    raw = _candidate_frame()
    raw.loc["2020-06-01":"2020-12-01", "invalid_pct"] = 100.0
    rows = _find_trough_opportunities(prepare_monthly_extent(raw), DynamicHydroYearConfig(expected_trough_month=9))
    row = rows.loc[rows["hy_year"] == 2020].iloc[0]
    assert row["status"] == "unresolved"
    assert row["status_reason"] == "insufficient_trough_candidates"
```

- [ ] **Step 2: Run tests and verify `_find_trough_opportunities` is missing**

Run: `python -m pytest tests/test_dynamic_year.py -q`

Expected: FAIL importing `_find_trough_opportunities`.

- [ ] **Step 3: Implement recovery confirmation with low-plateau re-entry rejection**

```python
# append to hydroseason/_dynamic_year.py
def _month_delta(actual: pd.Timestamp, expected: pd.Timestamp) -> int:
    return (actual.year - expected.year) * 12 + actual.month - expected.month


def _recovery_status(frame: pd.DataFrame, low_date: pd.Timestamp, plateau_ceiling: float, config: DynamicHydroYearConfig) -> str:
    threshold = plateau_ceiling
    tail = frame.loc[frame.index > low_date]
    consecutive = 0
    for position, (_, row) in enumerate(tail.iterrows()):
        if not bool(row["candidate_usable"]):
            consecutive = 0
            continue
        consecutive = consecutive + 1 if float(row["extent_pct"]) > threshold else 0
        if consecutive < config.sustained_rise_months:
            continue
        end_position = position + config.pulse_rejection_window_months
        if end_position >= len(tail):
            return "provisional"
        rejection = tail.iloc[position + 1 : end_position + 1]
        if (~rejection["candidate_usable"]).any():
            return "partial"
        if (rejection["extent_pct"] <= plateau_ceiling).any():
            consecutive = 0
            continue
        return "confirmed"
    return "provisional" if len(tail) < config.sustained_rise_months + config.pulse_rejection_window_months else "unconfirmed"


def _select_low_candidate(window: pd.DataFrame, full: pd.DataFrame, config: DynamicHydroYearConfig) -> tuple[pd.Timestamp | None, str]:
    minimum = float(window["extent_pct"].min())
    plateau = window.loc[window["extent_pct"] <= minimum + config.measurement_tolerance_pct]
    if config.dry_plateau_rule == "first":
        return pd.Timestamp(plateau.index[0]), "confirmed"
    if config.dry_plateau_rule == "middle":
        return pd.Timestamp(plateau.index[len(plateau) // 2]), "confirmed"
    provisional = None
    for candidate in reversed(plateau.index.tolist()):
        status = _recovery_status(full, pd.Timestamp(candidate), minimum + config.measurement_tolerance_pct, config)
        if status == "confirmed":
            return pd.Timestamp(candidate), status
        if status in {"provisional", "partial"} and provisional is None:
            provisional = (pd.Timestamp(candidate), status)
    return provisional if provisional is not None else (None, "unconfirmed")


def _find_trough_opportunities(frame: pd.DataFrame, config: DynamicHydroYearConfig) -> pd.DataFrame:
    rows = []
    for year in range(int(frame.index.min().year), int(frame.index.max().year) + 1):
        expected = pd.Timestamp(year, config.expected_trough_month, 1)
        start = expected - pd.DateOffset(months=config.trough_search_radius_months)
        end = expected + pd.DateOffset(months=config.trough_search_radius_months)
        usable = frame.loc[(frame.index >= start) & (frame.index <= end) & frame["candidate_usable"]]
        base = {
            "hy_year": year,
            "status": "unresolved",
            "status_reason": "insufficient_trough_candidates",
            "trough_month": pd.NaT,
            "trough_extent_pct": np.nan,
            "trough_invalid_pct": np.nan,
            "boundary_status": "provisional",
            "phase_shift_months": np.nan,
        }
        if len(usable) < config.min_usable_trough_candidates:
            rows.append(base)
            continue
        candidate, recovery = _select_low_candidate(usable, frame, config)
        if candidate is None:
            base["status_reason"] = "recovery_not_confirmed"
            rows.append(base)
            continue
        row = frame.loc[candidate]
        base.update(
            status="complete" if recovery == "confirmed" else "partial",
            status_reason="ok" if recovery == "confirmed" else f"boundary_{recovery}",
            trough_month=candidate,
            trough_extent_pct=float(row["extent_pct"]),
            trough_invalid_pct=float(row["invalid_pct"]) if pd.notna(row["invalid_pct"]) else np.nan,
            boundary_status="confirmed" if recovery == "confirmed" else "provisional",
            phase_shift_months=_month_delta(candidate, expected),
        )
        rows.append(base)
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run recovery tests**

Run: `python -m pytest tests/test_dynamic_year.py -q`

Expected: PASS, including selection of October rather than the temporary July low.

- [ ] **Step 5: Commit boundary detection**

```bash
git add hydroseason/_dynamic_year.py tests/test_dynamic_year.py
git commit -m "feat: detect pulse-safe trough boundaries"
```

---

### Task 4: Dynamic cycle metrics, bimodal descriptors, and sequence breaks

**Files:**
- Modify: `hydroseason/_dynamic_year.py`
- Modify: `tests/test_dynamic_year.py`

**Interfaces:**
- Produces public `detect_dynamic_hydrological_years(extent, *, config, value_col="extent_pct", date_col=None, pattern=None) -> pd.DataFrame`.
- Produces every annual column listed in approved design section 6.4.
- Consumes trough opportunities from Task 3 and optional `SeasonalPatternResult` from Task 2.

- [ ] **Step 1: Write failing metric and no-merge tests**

```python
# append to tests/test_dynamic_year.py
from dataclasses import replace

from hydroseason._dynamic_year import detect_dynamic_hydrological_years


def test_dynamic_cycle_reports_observed_peak_two_mid_dry_metrics_and_trough():
    raw = _candidate_frame(start="2017-01-01", periods=72)
    config = DynamicHydroYearConfig(expected_trough_month=8, dry_plateau_rule="middle")
    result = detect_dynamic_hydrological_years(raw, config=config)
    complete = result.loc[result["status"] == "complete"].iloc[0]
    assert complete["peak_extent_pct"] == raw.loc[complete["peak_month"], "extent_pct"]
    assert complete["trough_extent_pct"] == raw.loc[complete["trough_month"], "extent_pct"]
    assert complete["half_loss_target_pct"] == pytest.approx((complete["peak_extent_pct"] + complete["trough_extent_pct"]) / 2)
    assert complete["peak_month"] <= complete["temporal_mid_dry_month"] <= complete["trough_month"]
    assert complete["peak_month"] <= complete["half_loss_month"] <= complete["trough_month"]


def test_unresolved_nominal_year_breaks_cycles_instead_of_merging():
    raw = _candidate_frame(start="2017-01-01", periods=84)
    raw.loc["2020-06-01":"2020-12-01", "invalid_pct"] = 100.0
    config = DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle")
    result = detect_dynamic_hydrological_years(raw, config=config)
    assert result.loc[result["hy_year"] == 2020, "status"].item() == "unresolved"
    assert result.loc[result["hy_year"] == 2021, "status_reason"].item() == "no_previous_boundary"
    resolved_lengths = result.loc[result["status"] == "complete", "cycle_months"]
    assert (resolved_lengths <= 18).all()


def test_temporary_rewetting_after_half_loss_is_counted():
    raw = _candidate_frame(start="2017-01-01", periods=72)
    raw.loc["2020-06-01":"2020-09-01", "extent_pct"] = [8.0, 14.0, 7.0, 4.0]
    result = detect_dynamic_hydrological_years(raw, config=DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle"))
    assert result.loc[result["hy_year"] == 2020, "n_rewetting_pulses"].item() >= 1
```

- [ ] **Step 2: Run tests and verify the public detector is missing**

Run: `python -m pytest tests/test_dynamic_year.py -q`

Expected: FAIL importing `detect_dynamic_hydrological_years`.

- [ ] **Step 3: Implement observed-value cycle metrics and coverage-based confidence**

```python
# append to hydroseason/_dynamic_year.py
ANNUAL_COLUMNS = [
    "hy_year", "status", "status_reason", "hy_start", "hy_end", "cycle_months",
    "peak_month", "peak_extent_pct", "peak_invalid_pct",
    "temporal_mid_dry_month", "temporal_mid_dry_extent_pct",
    "half_loss_month", "half_loss_extent_pct", "half_loss_target_pct",
    "trough_month", "trough_extent_pct", "trough_invalid_pct", "boundary_status",
    "drawdown_pct", "persistence_ratio", "recession_months", "half_loss_months",
    "n_rewetting_pulses", "n_usable_months", "confidence",
    "secondary_peak_month", "secondary_peak_extent_pct",
    "secondary_trough_month", "secondary_trough_extent_pct",
]


def _middle_tie(series: pd.Series, kind: str) -> pd.Timestamp:
    target = series.max() if kind == "max" else series.min()
    candidates = series.loc[series == target]
    return pd.Timestamp(candidates.index[len(candidates) // 2])


def _nearest_month(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> pd.Timestamp:
    target = start + (end - start) / 2
    return pd.Timestamp(index[int(np.argmin(np.abs(index - target)))])


def _secondary_extrema(series: pd.Series, peak: pd.Timestamp, trough: pd.Timestamp) -> tuple[pd.Timestamp | None, float, pd.Timestamp | None, float]:
    values = series.to_numpy(float)
    peaks = [i for i in range(1, len(values) - 1) if values[i] > values[i - 1] and values[i] >= values[i + 1] and abs(i - series.index.get_loc(peak)) >= 2]
    troughs = [i for i in range(1, len(values) - 1) if values[i] < values[i - 1] and values[i] <= values[i + 1] and abs(i - series.index.get_loc(trough)) >= 2]
    secondary_peak = max(peaks, key=lambda i: values[i]) if peaks else None
    secondary_trough = min(troughs, key=lambda i: values[i]) if troughs else None
    return (
        pd.Timestamp(series.index[secondary_peak]) if secondary_peak is not None else None,
        float(values[secondary_peak]) if secondary_peak is not None else np.nan,
        pd.Timestamp(series.index[secondary_trough]) if secondary_trough is not None else None,
        float(values[secondary_trough]) if secondary_trough is not None else np.nan,
    )


def _confidence(cycle: pd.DataFrame, boundary_status: str) -> str:
    usable_fraction = float(cycle["candidate_usable"].mean())
    observed = cycle.loc[cycle["candidate_usable"], "observed_fraction"]
    quality = float(observed.mean()) if observed.notna().any() else 0.5
    score = usable_fraction * quality * (0.75 if boundary_status == "provisional" else 1.0)
    if (cycle["quality_state"] == "unknown").any():
        score = min(score, 0.59)
    return "high" if score >= 0.80 else "medium" if score >= 0.60 else "low"


def _blank_cycle(opportunity: pd.Series) -> dict:
    row = {column: np.nan for column in ANNUAL_COLUMNS}
    row.update(
        hy_year=int(opportunity["hy_year"]), status=opportunity["status"],
        status_reason=opportunity["status_reason"], trough_month=opportunity["trough_month"],
        trough_extent_pct=opportunity["trough_extent_pct"], trough_invalid_pct=opportunity["trough_invalid_pct"],
        boundary_status=opportunity["boundary_status"], confidence="low",
    )
    return row


def detect_dynamic_hydrological_years(extent, *, config: DynamicHydroYearConfig, value_col: str = "extent_pct", date_col: str | None = None, pattern: SeasonalPatternResult | None = None) -> pd.DataFrame:
    frame = prepare_monthly_extent(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=config.max_invalid_pct,
        allow_unknown_quality=config.allow_unknown_quality,
    )
    opportunities = _find_trough_opportunities(frame, config)
    rows = []
    previous = None
    for _, opportunity in opportunities.iterrows():
        row = _blank_cycle(opportunity)
        if pd.isna(opportunity["trough_month"]):
            previous = None
            rows.append(row)
            continue
        if previous is None:
            row.update(status="partial", status_reason="no_previous_boundary")
            previous = opportunity
            rows.append(row)
            continue
        start = pd.Timestamp(previous["trough_month"]) + pd.DateOffset(months=1)
        end = pd.Timestamp(opportunity["trough_month"])
        cycle = frame.loc[start:end]
        usable = cycle.loc[cycle["candidate_usable"], "extent_pct"]
        if len(usable) < config.min_usable_months_per_cycle:
            row.update(status="partial", status_reason="insufficient_cycle_coverage", hy_start=start, hy_end=end, cycle_months=len(cycle), n_usable_months=len(usable))
            previous = opportunity
            rows.append(row)
            continue
        peak = _middle_tie(usable, "max")
        post_peak = usable.loc[peak:end]
        trough = end
        peak_value, trough_value = float(usable.loc[peak]), float(frame.loc[trough, "extent_pct"])
        target = (peak_value + trough_value) / 2.0
        half_candidates = post_peak.loc[post_peak <= target]
        half = pd.Timestamp(half_candidates.index[0]) if len(half_candidates) else pd.NaT
        midpoint = _nearest_month(post_peak.index, peak, trough)
        after_half = post_peak.loc[half:] if pd.notna(half) else post_peak.iloc[0:0]
        pulses = int((after_half.diff() > config.measurement_tolerance_pct).sum())
        secondary = _secondary_extrema(usable, peak, trough) if pattern is not None and pattern.pattern == "bimodal_or_complex" else (None, np.nan, None, np.nan)
        peak_invalid = frame.loc[peak, "invalid_pct"]
        row.update(
            status="complete" if opportunity["boundary_status"] == "confirmed" else "partial",
            status_reason="ok" if opportunity["boundary_status"] == "confirmed" else "boundary_provisional",
            hy_start=start, hy_end=end, cycle_months=len(cycle),
            peak_month=peak, peak_extent_pct=peak_value,
            peak_invalid_pct=float(peak_invalid) if pd.notna(peak_invalid) else np.nan,
            temporal_mid_dry_month=midpoint, temporal_mid_dry_extent_pct=float(frame.loc[midpoint, "extent_pct"]),
            half_loss_month=half, half_loss_extent_pct=float(frame.loc[half, "extent_pct"]) if pd.notna(half) else np.nan,
            half_loss_target_pct=target, trough_month=trough, trough_extent_pct=trough_value,
            trough_invalid_pct=opportunity["trough_invalid_pct"], boundary_status=opportunity["boundary_status"],
            drawdown_pct=peak_value - trough_value,
            persistence_ratio=trough_value / peak_value if peak_value > 0 else np.nan,
            recession_months=_month_delta(trough, peak),
            half_loss_months=_month_delta(half, peak) if pd.notna(half) else np.nan,
            n_rewetting_pulses=pulses, n_usable_months=len(usable), confidence=_confidence(cycle, opportunity["boundary_status"]),
            secondary_peak_month=secondary[0], secondary_peak_extent_pct=secondary[1],
            secondary_trough_month=secondary[2], secondary_trough_extent_pct=secondary[3],
        )
        previous = opportunity
        rows.append(row)
    return pd.DataFrame(rows, columns=ANNUAL_COLUMNS)
```

- [ ] **Step 4: Add low-peak zero guard, bimodal metadata, variable cycle-length, and unknown-quality confidence tests**

```python
def test_zero_peak_has_explicit_nan_persistence_ratio():
    raw = _candidate_frame(start="2017-01-01", periods=72)
    raw["extent_pct"] = 0.0
    result = detect_dynamic_hydrological_years(raw, config=DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle"))
    assert result.loc[result["status"] == "complete", "persistence_ratio"].isna().all()


def test_unknown_quality_never_receives_high_confidence():
    raw = _candidate_frame(start="2017-01-01", periods=72).drop(columns="invalid_pct")
    config = DynamicHydroYearConfig(expected_trough_month=9, dry_plateau_rule="middle", allow_unknown_quality=True)
    result = detect_dynamic_hydrological_years(raw, config=config)
    assert "high" not in set(result["confidence"])
```

- [ ] **Step 5: Run all dynamic-year tests and legacy regression tests**

Run: `python -m pytest tests/test_dynamic_year.py tests/test_hydro_year.py -q`

Expected: PASS; `tests/test_hydro_year.py` remains unchanged and green.

- [ ] **Step 6: Commit annual metrics**

```bash
git add hydroseason/_dynamic_year.py tests/test_dynamic_year.py
git commit -m "feat: measure dynamic surface-water cycles"
```

### Task 5: Annual recharge/refuge condition and monthly anomaly

**Files:**
- Create: `hydroseason/_condition.py`
- Create: `tests/test_condition.py`

**Interfaces:**
- Produces: `classify_annual_surface_water_condition(annual, *, reference="full_record", reference_start=None, reference_end=None, min_baseline_cycles=10, low_percentile=20.0, high_percentile=80.0, low_variability=False, allow_low_variability_labels=False) -> pd.DataFrame`.
- Produces: `compute_monthly_surface_water_condition(extent, *, reference_start=None, reference_end=None, value_col="extent_pct", date_col=None, max_invalid_pct=20.0, allow_unknown_quality=False) -> pd.DataFrame`.
- Consumes annual output from Task 4 and canonical monthly input from Task 1.

- [ ] **Step 1: Write failing tests for four extreme combinations, leave-one-out ranks, sequences, and low variability**

```python
# tests/test_condition.py
import numpy as np
import pandas as pd

from hydroseason._condition import (
    classify_annual_surface_water_condition,
    compute_monthly_surface_water_condition,
)


def _annual():
    years = np.arange(2000, 2012)
    return pd.DataFrame(
        {
            "hy_year": years,
            "status": "complete",
            "hy_end": pd.to_datetime([f"{year}-09-01" for year in years]),
            "peak_extent_pct": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120],
            "trough_extent_pct": [1, 12, 3, 4, 5, 6, 7, 8, 9, 10, 2, 11],
        }
    )


def test_recharge_and_refuge_axes_produce_all_four_joint_states():
    result = classify_annual_surface_water_condition(_annual())
    by_year = result.set_index("hy_year")["annual_condition"]
    assert by_year[2000] == "dry_low_refuge"
    assert by_year[2001] == "buffered_low_recharge"
    assert by_year[2010] == "recharged_then_contracting"
    assert by_year[2011] == "wet_persistent"
    assert result.loc[result["hy_year"] == 2000, "peak_percentile"].item() == 0.0
    assert result.loc[result["hy_year"] == 2011, "peak_percentile"].item() == 100.0


def test_consecutive_counts_only_follow_joint_extremes():
    annual = _annual()
    annual.loc[annual["hy_year"].isin([2002, 2003]), ["peak_extent_pct", "trough_extent_pct"]] = [5, 0]
    result = classify_annual_surface_water_condition(annual)
    assert result.loc[result["hy_year"] == 2003, "consecutive_dry_cycles"].item() >= 2


def test_low_variability_suppresses_public_labels_but_keeps_percentiles():
    result = classify_annual_surface_water_condition(_annual(), low_variability=True)
    assert result["peak_percentile"].notna().all()
    assert set(result["annual_condition"]) == {"not_applicable_low_variability"}
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run: `python -m pytest tests/test_condition.py -q`

Expected: FAIL during collection because `_condition.py` does not exist.

- [ ] **Step 3: Implement fixed-reference empirical percentiles and annual labels**

```python
# hydroseason/_condition.py
from __future__ import annotations

import numpy as np
import pandas as pd

from ._state_input import prepare_monthly_extent


def _empirical_percentile(value: float, reference: pd.Series) -> float:
    clean = reference.dropna().to_numpy(float)
    if not len(clean):
        return np.nan
    return 100.0 * (np.sum(clean < value) + 0.5 * np.sum(clean == value)) / len(clean)


def _condition(percentile: float, low: float, high: float) -> str:
    if pd.isna(percentile):
        return "insufficient_baseline"
    if percentile <= low:
        return "low"
    if percentile >= high:
        return "high"
    return "typical"


def classify_annual_surface_water_condition(
    annual: pd.DataFrame,
    *,
    reference: str = "full_record",
    reference_start: str | pd.Timestamp | None = None,
    reference_end: str | pd.Timestamp | None = None,
    min_baseline_cycles: int = 10,
    low_percentile: float = 20.0,
    high_percentile: float = 80.0,
    low_variability: bool = False,
    allow_low_variability_labels: bool = False,
) -> pd.DataFrame:
    if reference != "full_record" and (reference_start is None or reference_end is None):
        raise ValueError("reference must be 'full_record' or include reference_start and reference_end.")
    if not 0 <= low_percentile < high_percentile <= 100:
        raise ValueError("condition percentiles must satisfy 0 <= low < high <= 100.")
    out = annual.copy().sort_values("hy_year").reset_index(drop=True)
    complete = out["status"].eq("complete")
    reference_mask = complete.copy()
    if reference_start is not None:
        dates = pd.to_datetime(out["hy_end"])
        reference_mask &= dates.between(pd.Timestamp(reference_start), pd.Timestamp(reference_end))

    for source, target in (("peak_extent_pct", "peak_percentile"), ("trough_extent_pct", "trough_percentile")):
        values = []
        for index, row in out.iterrows():
            baseline = out.loc[reference_mask, source]
            if reference_mask.loc[index]:
                baseline = baseline.drop(index=index)
            values.append(_empirical_percentile(float(row[source]), baseline) if pd.notna(row[source]) else np.nan)
        out[target] = values

    enough = int(reference_mask.sum()) >= min_baseline_cycles
    if enough:
        out["recharge_condition"] = out["peak_percentile"].map(lambda value: _condition(value, low_percentile, high_percentile))
        out["refuge_condition"] = out["trough_percentile"].map(lambda value: _condition(value, low_percentile, high_percentile))
    else:
        out["recharge_condition"] = "insufficient_baseline"
        out["refuge_condition"] = "insufficient_baseline"
    mapping = {
        ("high", "high"): "wet_persistent",
        ("high", "low"): "recharged_then_contracting",
        ("low", "high"): "buffered_low_recharge",
        ("low", "low"): "dry_low_refuge",
    }
    out["annual_condition"] = [mapping.get(pair, "typical_or_mixed") for pair in zip(out["recharge_condition"], out["refuge_condition"])]
    if not enough:
        out["annual_condition"] = "insufficient_baseline"
    if low_variability and not allow_low_variability_labels:
        out[["recharge_condition", "refuge_condition", "annual_condition"]] = "not_applicable_low_variability"

    out["peak_change_from_previous_pct"] = out["peak_extent_pct"].diff()
    out["trough_change_from_previous_pct"] = out["trough_extent_pct"].diff()
    dry_count = wet_count = 0
    dry_counts, wet_counts = [], []
    for state in out["annual_condition"]:
        dry_count = dry_count + 1 if state == "dry_low_refuge" else 0
        wet_count = wet_count + 1 if state == "wet_persistent" else 0
        dry_counts.append(dry_count)
        wet_counts.append(wet_count)
    out["consecutive_dry_cycles"] = dry_counts
    out["consecutive_wet_cycles"] = wet_counts
    return out
```

- [ ] **Step 4: Write and run failing monthly same-calendar-month tests**

```python
def test_monthly_condition_uses_same_calendar_month_and_fixed_reference():
    index = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    frame = pd.DataFrame(
        {"extent_pct": index.year - 1999 + index.month / 100, "invalid_pct": 0.0},
        index=index,
    )
    result = compute_monthly_surface_water_condition(
        frame, reference_start="2000-01-01", reference_end="2009-12-01"
    )
    row = result.loc["2011-01-01"]
    assert row["reference_n"] == 10
    assert row["reference_median_pct"] == 5.51
    assert row["anomaly_pct"] == 6.5
    assert row["condition_percentile"] == 100.0


def test_low_quality_month_has_no_condition_rank():
    frame = pd.DataFrame(
        {"extent_pct": [10.0, 20.0], "invalid_pct": [0.0, 50.0]},
        index=pd.to_datetime(["2000-01-01", "2001-01-01"]),
    )
    result = compute_monthly_surface_water_condition(frame)
    assert pd.isna(result.loc["2001-01-01", "condition_percentile"])
```

Run: `python -m pytest tests/test_condition.py -q`

Expected: FAIL because `compute_monthly_surface_water_condition` is not defined.

- [ ] **Step 5: Implement same-month robust anomalies without a moving reference**

```python
# append to hydroseason/_condition.py
def compute_monthly_surface_water_condition(
    extent,
    *,
    reference_start=None,
    reference_end=None,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    max_invalid_pct: float = 20.0,
    allow_unknown_quality: bool = False,
) -> pd.DataFrame:
    frame = prepare_monthly_extent(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=max_invalid_pct, allow_unknown_quality=allow_unknown_quality,
    )
    reference_mask = frame["candidate_usable"].copy()
    if reference_start is not None or reference_end is not None:
        if reference_start is None or reference_end is None:
            raise ValueError("reference_start and reference_end must be supplied together.")
        reference_mask &= frame.index.to_series().between(pd.Timestamp(reference_start), pd.Timestamp(reference_end)).to_numpy()
    rows = []
    for date, row in frame.iterrows():
        baseline = frame.loc[reference_mask & (frame.index.month == date.month), "extent_pct"]
        if date in baseline.index:
            baseline = baseline.drop(index=date)
        usable = bool(row["candidate_usable"])
        median = float(baseline.median()) if len(baseline) else np.nan
        rows.append(
            {
                "extent_pct": row["extent_pct"],
                "reference_median_pct": median,
                "anomaly_pct": float(row["extent_pct"] - median) if usable and pd.notna(median) else np.nan,
                "condition_percentile": _empirical_percentile(float(row["extent_pct"]), baseline) if usable else np.nan,
                "reference_n": int(len(baseline)),
                "quality_state": row["quality_state"],
            }
        )
    return pd.DataFrame(rows, index=frame.index)
```

- [ ] **Step 6: Run condition tests**

Run: `python -m pytest tests/test_condition.py -q`

Expected: PASS.

- [ ] **Step 7: Commit condition metrics**

```bash
git add hydroseason/_condition.py tests/test_condition.py
git commit -m "feat: classify recharge and refuge condition"
```

---

### Task 6: Basin aggregation, public orchestration, and additive exports

**Files:**
- Create: `hydroseason/_aggregation.py`
- Create: `hydroseason/hydrological_state.py`
- Create: `tests/test_aggregation.py`
- Create: `tests/test_hydrological_state.py`
- Modify: `hydroseason/__init__.py`
- Modify: `tests/test_package_surface.py`

**Interfaces:**
- Produces: `aggregate_basin_monthly_extent(monthly, *, date_col="date", aoi_col="aoi_id", area_weight_col=None) -> pd.DataFrame`.
- Produces frozen `HydrologicalStateResult(pattern, config, hydro_years, monthly_condition, data_quality)`.
- Produces: `analyze_hydrological_state(extent, *, config=None, reference_start=None, reference_end=None, n_bootstrap=200, random_state=0) -> HydrologicalStateResult`.
- Re-exports all public state APIs without changing legacy exports.

- [ ] **Step 1: Write failing count-weighting and unweighted-rejection tests**

```python
# tests/test_aggregation.py
import pandas as pd
import pytest

from hydroseason._aggregation import aggregate_basin_monthly_extent


def test_basin_extent_uses_summed_counts_not_mean_percentages():
    frame = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-01"], "aoi_id": ["small", "large"],
            "n_water": [10, 180], "n_valid": [20, 900],
            "n_invalid": [0, 100], "n_aoi": [20, 1000],
        }
    )
    result = aggregate_basin_monthly_extent(frame)
    assert result.loc[pd.Timestamp("2020-01-01"), "extent_pct"] == pytest.approx(100 * 190 / 920)
    assert result.loc[pd.Timestamp("2020-01-01"), "aoi_coverage_pct"] == 100.0


def test_percentage_only_input_requires_explicit_area_weight():
    frame = pd.DataFrame(
        {"date": ["2020-01-01", "2020-01-01"], "aoi_id": ["a", "b"], "extent_pct": [10.0, 90.0]}
    )
    with pytest.raises(ValueError, match="area weight"):
        aggregate_basin_monthly_extent(frame)
```

- [ ] **Step 2: Implement count-first aggregation and explicit area fallback**

```python
# hydroseason/_aggregation.py
from __future__ import annotations

import numpy as np
import pandas as pd


def aggregate_basin_monthly_extent(monthly: pd.DataFrame, *, date_col: str = "date", aoi_col: str = "aoi_id", area_weight_col: str | None = None) -> pd.DataFrame:
    frame = monthly.copy()
    frame[date_col] = pd.to_datetime(frame[date_col]).dt.to_period("M").dt.to_timestamp()
    if frame.duplicated([date_col, aoi_col]).any():
        raise ValueError("each AOI may contribute at most one row per month.")
    expected_aoi = frame[aoi_col].nunique()
    count_cols = ["n_water", "n_valid", "n_invalid", "n_aoi"]
    if set(count_cols).issubset(frame.columns):
        grouped = frame.groupby(date_col)[count_cols].sum(min_count=1)
        grouped["extent_pct"] = np.where(grouped["n_valid"] > 0, 100.0 * grouped["n_water"] / grouped["n_valid"], np.nan)
        grouped["invalid_pct"] = np.where(grouped["n_aoi"] > 0, 100.0 * grouped["n_invalid"] / grouped["n_aoi"], np.nan)
        reporting = frame.loc[frame["n_valid"] > 0].groupby(date_col)[aoi_col].nunique()
    else:
        if area_weight_col is None or area_weight_col not in frame:
            raise ValueError("percentage-only aggregation requires an explicit area weight column.")
        if (frame[area_weight_col] <= 0).any():
            raise ValueError("area weights must be positive.")
        frame["weighted_extent"] = frame["extent_pct"] * frame[area_weight_col]
        grouped = frame.groupby(date_col).agg(weighted_extent=("weighted_extent", "sum"), total_weight=(area_weight_col, "sum"))
        grouped["extent_pct"] = grouped["weighted_extent"] / grouped["total_weight"]
        grouped["invalid_pct"] = np.nan
        reporting = frame.loc[frame["extent_pct"].notna()].groupby(date_col)[aoi_col].nunique()
    grouped["n_aoi_reporting"] = reporting.reindex(grouped.index, fill_value=0)
    grouped["n_aoi_expected"] = expected_aoi
    grouped["aoi_coverage_pct"] = 100.0 * grouped["n_aoi_reporting"] / expected_aoi
    return grouped
```

- [ ] **Step 3: Run aggregation tests**

Run: `python -m pytest tests/test_aggregation.py -q`

Expected: PASS.

- [ ] **Step 4: Write failing orchestrator and authoritative-config tests**

```python
# tests/test_hydrological_state.py
import numpy as np
import pandas as pd

from hydroseason.hydrological_state import (
    DynamicHydroYearConfig,
    HydrologicalStateResult,
    analyze_hydrological_state,
)


def _extent(years=15):
    index = pd.date_range("2000-01-01", periods=years * 12, freq="MS")
    values = 30.0 + 25.0 * np.cos(2 * np.pi * (index.month - 2) / 12)
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def test_orchestrator_returns_all_public_products():
    result = analyze_hydrological_state(_extent(), n_bootstrap=40)
    assert isinstance(result, HydrologicalStateResult)
    assert not result.hydro_years.empty
    assert len(result.monthly_condition) == 15 * 12
    assert result.data_quality["n_usable"] == 15 * 12


def test_user_configuration_is_authoritative_over_advisory_pattern():
    config = DynamicHydroYearConfig(expected_trough_month=7, dry_plateau_rule="middle")
    result = analyze_hydrological_state(_extent(), config=config, n_bootstrap=40)
    assert result.config is config
    assert result.config.expected_trough_month == 7
```

- [ ] **Step 5: Implement the public facade and orchestrator**

```python
# hydroseason/hydrological_state.py
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ._aggregation import aggregate_basin_monthly_extent
from ._condition import classify_annual_surface_water_condition, compute_monthly_surface_water_condition
from ._dynamic_year import DynamicHydroYearConfig, detect_dynamic_hydrological_years, suggest_dynamic_hydro_year_config
from ._seasonality import SeasonalPatternResult, classify_seasonal_pattern
from ._state_input import prepare_monthly_extent


@dataclass(frozen=True)
class HydrologicalStateResult:
    pattern: SeasonalPatternResult
    config: DynamicHydroYearConfig
    hydro_years: pd.DataFrame
    monthly_condition: pd.DataFrame
    data_quality: dict


def analyze_hydrological_state(
    extent,
    *,
    config: DynamicHydroYearConfig | None = None,
    reference_start=None,
    reference_end=None,
    n_bootstrap: int = 200,
    random_state: int = 0,
) -> HydrologicalStateResult:
    pattern = classify_seasonal_pattern(extent, n_bootstrap=n_bootstrap, random_state=random_state)
    selected = config or suggest_dynamic_hydro_year_config(extent, pattern=pattern)
    annual = detect_dynamic_hydrological_years(extent, config=selected, pattern=pattern)
    annual = classify_annual_surface_water_condition(
        annual,
        reference_start=reference_start,
        reference_end=reference_end,
        min_baseline_cycles=selected.min_baseline_cycles,
        low_percentile=selected.low_percentile,
        high_percentile=selected.high_percentile,
        low_variability=pattern.pattern == "low_variability",
    )
    monthly = compute_monthly_surface_water_condition(
        extent, reference_start=reference_start, reference_end=reference_end,
        max_invalid_pct=selected.max_invalid_pct,
        allow_unknown_quality=selected.allow_unknown_quality,
    )
    prepared = prepare_monthly_extent(
        extent, max_invalid_pct=selected.max_invalid_pct,
        allow_unknown_quality=selected.allow_unknown_quality,
    )
    quality = prepared["quality_state"].value_counts().to_dict()
    quality["n_usable"] = int(prepared["candidate_usable"].sum())
    quality["n_months"] = int(len(prepared))
    return HydrologicalStateResult(pattern, selected, annual, monthly, quality)


__all__ = [
    "DynamicHydroYearConfig", "HydrologicalStateResult", "SeasonalPatternResult",
    "aggregate_basin_monthly_extent", "analyze_hydrological_state",
    "classify_annual_surface_water_condition", "classify_seasonal_pattern",
    "compute_monthly_surface_water_condition", "detect_dynamic_hydrological_years",
    "suggest_dynamic_hydro_year_config",
]
```

- [ ] **Step 6: Add public package exports and pin both old and new surfaces**

```python
# hydroseason/__init__.py -- add after existing hydro_year imports
from .hydrological_state import (
    DynamicHydroYearConfig,
    HydrologicalStateResult,
    SeasonalPatternResult,
    aggregate_basin_monthly_extent,
    analyze_hydrological_state,
    classify_annual_surface_water_condition,
    classify_seasonal_pattern,
    compute_monthly_surface_water_condition,
    detect_dynamic_hydrological_years,
    suggest_dynamic_hydro_year_config,
)
```

Replace `hydroseason.__all__` with this exact legacy-first list, then make
`tests/test_package_surface.py` assert the same list:

```python
__all__ = [
    "__version__", "HydroYearConfig", "detect_hydrological_years",
    "label_hydrological_months", "monthly_water_extent", "suggest_hydro_year_config",
    "load_aoi", "load_wofs_from_stac", "load_monthly_masks",
    "load_monthly_masks_zarr", "load_extent_csv", "complete_monthly_axis",
    "generate_html_report", "DynamicHydroYearConfig", "HydrologicalStateResult",
    "SeasonalPatternResult", "aggregate_basin_monthly_extent",
    "analyze_hydrological_state", "classify_annual_surface_water_condition",
    "classify_seasonal_pattern", "compute_monthly_surface_water_condition",
    "detect_dynamic_hydrological_years", "suggest_dynamic_hydro_year_config",
]
```

- [ ] **Step 7: Run orchestration and package tests**

Run: `python -m pytest tests/test_aggregation.py tests/test_hydrological_state.py tests/test_package_surface.py -q`

Expected: PASS.

- [ ] **Step 8: Commit public API**

```bash
git add hydroseason/_aggregation.py hydroseason/hydrological_state.py hydroseason/__init__.py tests/test_aggregation.py tests/test_hydrological_state.py tests/test_package_surface.py
git commit -m "feat: expose hydrological state analysis"
```

### Task 7: Deterministic 30-year scientific benchmark

**Files:**
- Create: `tests/fixtures/build_dynamic_state_mock.py`
- Create: `tests/fixtures/dynamic_state_mock.csv`
- Create: `tests/fixtures/dynamic_state_truth.csv`
- Create: `tests/test_dynamic_state_benchmark.py`

**Interfaces:**
- Fixture has `site`, `date`, `extent_pct`, `invalid_pct`, and optional pixel counts.
- Truth has prescribed `hy_year`, extrema dates/values, midpoint, half-loss date, expected joint state, and `detectable`.
- The fixture builder never imports `hydroseason`; truth is independent from detector code.

- [ ] **Step 1: Create the independent fixture builder**

```python
# tests/fixtures/build_dynamic_state_mock.py
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).parent
YEARS = list(range(1990, 2020))
SHIFTS = [-1, 0, 1, 0, -1, 1] * 5


def magnitudes(position):
    if position < 3:
        return 20.0 + position, 1.0 + position, "dry_low_refuge"
    if position < 6:
        return 32.0 + position, 30.0 + position, "buffered_low_recharge"
    if position < 9:
        return 84.0 + position, 1.0 + position - 6, "recharged_then_contracting"
    if position < 12:
        return 84.0 + position, 30.0 + position - 6, "wet_persistent"
    return 55.0 + (position % 12), 10.0 + (position % 10), "typical_or_mixed"


def intermittent_panel():
    index = pd.date_range("1989-08-01", "2020-04-01", freq="MS")
    control = {}
    truth = []
    control[pd.Timestamp("1989-09-01")] = 10.0
    for position, (year, shift) in enumerate(zip(YEARS, SHIFTS)):
        peak_value, trough_value, state = magnitudes(position)
        peak = pd.Timestamp(year, 2 + shift, 1)
        trough = pd.Timestamp(year, 9 + shift, 1)
        control[peak], control[trough] = peak_value, trough_value
        midpoint_target = peak + (trough - peak) / 2
        midpoint = index[int(np.argmin(np.abs(index - midpoint_target)))]
        target = (peak_value + trough_value) / 2
        decline = pd.date_range(peak, trough, freq="MS")
        decline_values = np.linspace(peak_value, trough_value, len(decline))
        half_loss = decline[int(np.flatnonzero(decline_values <= target)[0])]
        truth.append(
            {
                "site": "intermittent", "hy_year": year,
                "peak_month": peak, "peak_extent_pct": peak_value,
                "trough_month": trough, "trough_extent_pct": trough_value,
                "temporal_mid_dry_month": midpoint, "half_loss_month": half_loss,
                "annual_condition": state, "detectable": year != 2008,
            }
        )
    series = pd.Series(control, dtype=float).sort_index().reindex(index).interpolate(method="time")
    frame = pd.DataFrame({"site": "intermittent", "date": index, "extent_pct": series.to_numpy(), "invalid_pct": 0.0})
    pulse_dates = pd.to_datetime(["2003-06-01", "2003-07-01", "2003-08-01"])
    frame.loc[frame["date"].isin(pulse_dates), "extent_pct"] += [4.0, 8.0, 0.0]
    frame.loc[frame["date"].between("2008-06-01", "2008-12-01"), "invalid_pct"] = 100.0
    return frame, pd.DataFrame(truth)


def diagnostic_site(name, formula):
    index = pd.date_range("1990-01-01", periods=30 * 12, freq="MS")
    values = formula(index.month.to_numpy())
    return pd.DataFrame({"site": name, "date": index, "extent_pct": values, "invalid_pct": 0.0})


def basin_sites(intermittent):
    rows = []
    for site, size, scale in (("basin_small", 100, 0.8), ("basin_large", 900, 1.1)):
        extent = np.clip(intermittent["extent_pct"].to_numpy() * scale, 0, 100)
        valid = np.full(len(extent), size, dtype=int)
        water = np.rint(valid * extent / 100).astype(int)
        rows.append(pd.DataFrame({
            "site": site, "date": intermittent["date"], "extent_pct": 100 * water / valid,
            "invalid_pct": 0.0, "n_water": water, "n_valid": valid,
            "n_invalid": 0, "n_aoi": valid,
        }))
    return pd.concat(rows, ignore_index=True)


intermittent, truth = intermittent_panel()
perennial = diagnostic_site("perennial", lambda month: 60.0 + 0.3 * np.cos(2 * np.pi * (month - 2) / 12))
bimodal = diagnostic_site("bimodal", lambda month: 35.0 + 15.0 * np.cos(4 * np.pi * (month - 2) / 12))
panel = pd.concat([intermittent, perennial, bimodal, basin_sites(intermittent)], ignore_index=True)
panel.to_csv(ROOT / "dynamic_state_mock.csv", index=False, date_format="%Y-%m-%d")
truth.to_csv(ROOT / "dynamic_state_truth.csv", index=False, date_format="%Y-%m-%d")
```

- [ ] **Step 2: Generate and inspect frozen fixtures**

Run: `python tests/fixtures/build_dynamic_state_mock.py`

Expected: two CSV files; `dynamic_state_truth.csv` has exactly 30 rows and exactly one `detectable=False` row.

Run: `python -c "import pandas as pd; t=pd.read_csv('tests/fixtures/dynamic_state_truth.csv'); assert len(t)==30 and (~t.detectable).sum()==1"`

Expected: exit code 0.

- [ ] **Step 3: Write the benchmark gate**

```python
# tests/test_dynamic_state_benchmark.py
from pathlib import Path

import numpy as np
import pandas as pd

from hydroseason import (
    DynamicHydroYearConfig,
    aggregate_basin_monthly_extent,
    classify_annual_surface_water_condition,
    classify_seasonal_pattern,
    detect_dynamic_hydrological_years,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _month_error(left, right):
    left, right = pd.to_datetime(left), pd.to_datetime(right)
    return np.abs((left.dt.year - right.dt.year) * 12 + left.dt.month - right.dt.month)


def test_mock_benchmark_meets_scientific_acceptance_gates():
    panel = pd.read_csv(FIXTURES / "dynamic_state_mock.csv", parse_dates=["date"])
    truth = pd.read_csv(FIXTURES / "dynamic_state_truth.csv", parse_dates=["peak_month", "trough_month", "temporal_mid_dry_month", "half_loss_month"])
    extent = panel.loc[panel["site"] == "intermittent"].set_index("date")[["extent_pct", "invalid_pct"]]
    config = DynamicHydroYearConfig(expected_trough_month=9)
    annual = detect_dynamic_hydrological_years(extent, config=config)
    assert annual["hy_year"].is_unique
    assert annual.loc[annual["hy_year"] == 2008, "status"].item() == "unresolved"
    assert annual.loc[annual["hy_year"] == 2009, "status_reason"].item() == "no_previous_boundary"
    pulse = annual.loc[annual["hy_year"] == 2003].iloc[0]
    expected_pulse_trough = truth.loc[truth["hy_year"] == 2003, "trough_month"].item()
    assert pulse["trough_month"] == expected_pulse_trough
    assert pulse["n_rewetting_pulses"] >= 1

    joined = annual.merge(truth.loc[truth["detectable"]], on="hy_year", suffixes=("_actual", "_truth"))
    complete = joined.loc[joined["status"] == "complete"]
    assert (_month_error(complete["peak_month_actual"], complete["peak_month_truth"]) <= 1).mean() >= 0.90
    assert (_month_error(complete["trough_month_actual"], complete["trough_month_truth"]) <= 1).mean() >= 0.90
    assert (_month_error(complete["half_loss_month_actual"], complete["half_loss_month_truth"]) <= 1).mean() >= 0.90
    source = extent["extent_pct"]
    assert all(source.loc[date] == value for date, value in zip(complete["peak_month_actual"], complete["peak_extent_pct_actual"]))
    assert all(source.loc[date] == value for date, value in zip(complete["trough_month_actual"], complete["trough_extent_pct_actual"]))

    classified = classify_annual_surface_water_condition(annual)
    state_check = classified.merge(truth[["hy_year", "annual_condition"]], on="hy_year", suffixes=("_actual", "_truth"))
    extremes = state_check["annual_condition_truth"] != "typical_or_mixed"
    assert (state_check.loc[extremes, "annual_condition_actual"] == state_check.loc[extremes, "annual_condition_truth"]).all()


def test_mock_regime_and_basin_cases():
    panel = pd.read_csv(FIXTURES / "dynamic_state_mock.csv", parse_dates=["date"])
    perennial = panel.loc[panel["site"] == "perennial"].set_index("date")[["extent_pct", "invalid_pct"]]
    bimodal = panel.loc[panel["site"] == "bimodal"].set_index("date")[["extent_pct", "invalid_pct"]]
    assert classify_seasonal_pattern(perennial, n_bootstrap=40).pattern == "low_variability"
    assert classify_seasonal_pattern(bimodal, n_bootstrap=40).pattern == "bimodal_or_complex"

    basin = panel.loc[panel["site"].isin(["basin_small", "basin_large"])].rename(columns={"site": "aoi_id"})
    result = aggregate_basin_monthly_extent(basin)
    first = basin.loc[basin["date"] == basin["date"].min()]
    expected = 100 * first["n_water"].sum() / first["n_valid"].sum()
    assert result.iloc[0]["extent_pct"] == expected
```

- [ ] **Step 4: Run the fixed benchmark**

Run: `python -m pytest tests/test_dynamic_state_benchmark.py -q`

Expected: PASS. If a threshold fails, correct detector logic or fixture construction; do not weaken the approved 90% gates.

- [ ] **Step 5: Commit benchmark data and gate**

```bash
git add tests/fixtures/build_dynamic_state_mock.py tests/fixtures/dynamic_state_mock.csv tests/fixtures/dynamic_state_truth.csv tests/test_dynamic_state_benchmark.py
git commit -m "test: add dynamic hydro-year benchmark"
```

---

### Task 8: Fitzroy regression, user documentation, and final verification

**Files:**
- Create: `tests/fixtures/fitzroy_kimberley_monthly.csv`
- Create: `tests/fixtures/fitzroy_kimberley_legacy.csv`
- Create: `tests/test_fitzroy_regression.py`
- Create: `docs/hydrological-state.md`
- Modify: `mkdocs.yml`

**Interfaces:**
- Monthly fixture columns: `date`, `n_water`, `n_aoi`, `n_valid`, `n_invalid`, `extent_pct`, `invalid_pct`, `source`, `aoi`.
- Legacy fixture columns are the exact current `detect_hydrological_years` output plus provenance fields.
- No test performs network access.

- [ ] **Step 1: Freeze the already-reviewed notebook variables once**

Run the existing `notebooks/hydroseason_fitzroy_kimberley_stac.ipynb` through its hydrological-year cell. In that live kernel, run this exact one-off cell; do not save the export cell into the notebook:

```python
from pathlib import Path

fixture_dir = Path("../tests/fixtures")
fixture_dir.mkdir(exist_ok=True)

monthly_fixture = extent.rename_axis("date").reset_index()
monthly_fixture["source"] = "DEA Water Observations via cached Fitzroy/Kimberley notebook run"
monthly_fixture["aoi"] = "data/fitzroy_kimberley_aoi.geojson"
monthly_fixture.to_csv(fixture_dir / "fitzroy_kimberley_monthly.csv", index=False, date_format="%Y-%m-%d")

legacy_fixture = hydro_years.copy()
legacy_fixture["source"] = "hydroseason.detect_hydrological_years v0.1.0"
legacy_fixture["aoi"] = "data/fitzroy_kimberley_aoi.geojson"
legacy_fixture.to_csv(fixture_dir / "fitzroy_kimberley_legacy.csv", index=False, date_format="%Y-%m-%d")
```

Expected: monthly fixture has 132 rows covering 2015-01 through 2025-12; legacy fixture has 11 rows covering HY2015-HY2025. If DEA cannot be queried, development may continue with Task 7, but this release gate remains visibly incomplete rather than replaced by synthetic evidence.

- [ ] **Step 2: Write old-output immutability and new-vs-old comparison tests**

```python
# tests/test_fitzroy_regression.py
from pathlib import Path

import numpy as np
import pandas as pd

from hydroseason import (
    DynamicHydroYearConfig,
    detect_dynamic_hydrological_years,
    detect_hydrological_years,
    suggest_hydro_year_config,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _month_shift(left, right):
    left, right = pd.to_datetime(left), pd.to_datetime(right)
    return (left.dt.year - right.dt.year) * 12 + left.dt.month - right.dt.month


def test_legacy_fitzroy_output_is_unchanged():
    monthly = pd.read_csv(FIXTURES / "fitzroy_kimberley_monthly.csv", parse_dates=["date"]).set_index("date")
    expected = pd.read_csv(FIXTURES / "fitzroy_kimberley_legacy.csv", parse_dates=["hy_start", "hy_end", "peak_month", "mid_dry_month", "end_dry_month"])
    actual = detect_hydrological_years(
        monthly, config=suggest_hydro_year_config(monthly),
        missing_month_policy="ignore", max_invalid_pct=95.0,
    )
    compare = [column for column in actual.columns if column in expected.columns]
    pd.testing.assert_frame_equal(actual[compare].reset_index(drop=True), expected[compare].reset_index(drop=True), check_dtype=False)


def test_dynamic_fitzroy_years_do_not_merge_and_remain_close_to_reviewed_results():
    monthly = pd.read_csv(FIXTURES / "fitzroy_kimberley_monthly.csv", parse_dates=["date"]).set_index("date")
    old = pd.read_csv(FIXTURES / "fitzroy_kimberley_legacy.csv", parse_dates=["peak_month", "end_dry_month"])
    config = DynamicHydroYearConfig(expected_trough_month=11, trough_search_radius_months=3, max_invalid_pct=95.0)
    new = detect_dynamic_hydrological_years(monthly, config=config)
    assert new["hy_year"].is_unique
    adequate = new.loc[new["status"].isin(["complete", "partial"]) & new["peak_month"].notna()]
    comparison = old.merge(adequate, on="hy_year", suffixes=("_old", "_new"))
    assert set(comparison["hy_year"]) == set(adequate["hy_year"])
    peak_shift = _month_shift(comparison["peak_month_new"], comparison["peak_month_old"]).abs()
    trough_shift = _month_shift(comparison["trough_month"], comparison["end_dry_month"]).abs()
    assert float(peak_shift.median()) <= 1.0
    assert float(trough_shift.median()) <= 1.0
    differences = comparison.loc[(peak_shift > 1) | (trough_shift > 1), [
        "hy_year", "peak_month_old", "peak_month_new", "end_dry_month", "trough_month",
        "peak_extent_pct_old", "peak_extent_pct_new", "end_extent_pct", "trough_extent_pct",
        "confidence_old", "confidence_new",
    ]]
    print("Fitzroy rows requiring scientific review:")
    print(differences.to_string(index=False))
```

The final `differences` table is diagnostic evidence. Review every listed year;
do not hide it by relaxing timing gates.

- [ ] **Step 3: Run the Fitzroy gate**

Run: `python -m pytest tests/test_fitzroy_regression.py -q -s`

Expected: PASS with no duplicate/merged hydrological years and median absolute peak/trough timing shifts no greater than one month.

- [ ] **Step 4: Write practical user documentation**

Create `docs/hydrological-state.md` with these exact sections and claims:

````markdown
# Dynamic hydrological years and surface-water condition

Use this workflow for monthly remotely sensed surface-water extent in a fixed river reach, pool complex, wetland, or count-aggregated basin. It measures observed extent timing and historical condition. It does not estimate discharge, depth, volume, drought, ecological condition, or cause.

## Minimal workflow

```python
from hydroseason import analyze_hydrological_state

result = analyze_hydrological_state(monthly_extent)
result.pattern          # advisory seasonal shape
result.config           # inspect the suggested phase and tolerance
result.hydro_years      # peak, temporal mid-dry, half-loss, trough, condition
result.monthly_condition
```

Pass `DynamicHydroYearConfig(expected_trough_month=...)` when local knowledge should override the advisory phase. The configured month centres the annual search; it is not a fixed hydrological-year boundary.

## Annual interpretation

- `peak_extent_pct`: maximum observed extent in the dynamic trough-to-trough cycle.
- `temporal_mid_dry_extent_pct`: observed extent nearest the temporal midpoint between peak and trough.
- `half_loss_extent_pct`: first observed post-peak extent at or below half the peak-to-trough loss.
- `trough_extent_pct`: ending low-water extent selected from that year's search opportunity.
- Recharge condition ranks annual peaks; refuge condition independently ranks annual troughs.
- Continuous percentiles are primary. Public labels are compact interpretation aids.

## Regime behaviour

Monsoonal intermittent systems are the primary case. Bimodal systems retain a caller-selected primary trough and report secondary extrema descriptively. Perennial-like low-variability systems retain timing and extent metrics but suppress extreme labels by default. Low-variability, weak, or irregular records require a user-supplied expected trough month because their fitted phase is not a defensible automatic boundary.

## Mid-dry rainfall pulses

The default boundary is the last low plateau before confirmed recovery. Recovery needs two rising months followed by four months without return to the plateau. A temporary rise that recedes remains inside the same hydrological year and is counted as a rewetting pulse. The final boundary is provisional when the record ends before confirmation.

## Quality and aggregation

`invalid_pct` is a percentage: observed fraction is `1 - invalid_pct / 100`. Missing, low-quality, and unknown-quality months are not boundary candidates by default. Aggregate basins with summed `n_water` and `n_valid` counts, or explicit AOI area weights; unweighted percentage means are rejected.

## Limitations

Surface extent is not volume or depth. Extent-discharge relationships may be lagged or hysteretic. Optical classifiers under-detect narrow, shaded, turbid, or vegetated water. Monthly composites miss short events. AOI changes alter the series meaning. Managed releases, barriers, and groundwater can decouple extent from flow. High trough extent alone does not prove ecological resilience. Basin aggregation can hide local refuge failure, so report AOI results alongside basin results.

## Validation direction for Australia

Use the frozen Fitzroy/Kimberley comparison first. Next replicate the Gilbert River dynamic hydrological-year and persistent-pool work (Tayer et al. 2023, 2026; open dataset DOI `10.26182/866c-5c36`). Use Warrego-Darling/Toorale event records for dry-sequence and reconnection direction, Macquarie Marshes as a vegetated-water limitation test, and nearby BoM Hydrologic Reference Stations only where gauge and mapped reach processes are spatially comparable.
````

In `mkdocs.yml`, add `- Dynamic hydrological state: hydrological-state.md` immediately after the usage guide.

- [ ] **Step 5: Run the full verification matrix**

Run: `python -m pytest -q`

Expected: all old and new tests PASS.

Run: `mkdocs build --strict`

Expected: exit code 0 with no broken navigation or API references.

Run: `python -m build`

Expected: sdist and wheel build successfully without adding runtime dependencies.

Run: `git diff --check`

Expected: no whitespace errors or conflict markers. Existing line-ending warnings may be reported separately and must not be rewritten across unrelated files.

- [ ] **Step 6: Commit validation and documentation**

```bash
git add tests/fixtures/fitzroy_kimberley_monthly.csv tests/fixtures/fitzroy_kimberley_legacy.csv tests/test_fitzroy_regression.py docs/hydrological-state.md mkdocs.yml
git commit -m "test: validate dynamic years against Fitzroy"
```

---

## Self-Review Checklist

- Spec sections 1-4: Tasks 1 and 8 constrain claims, quality, and usability.
- Spec section 5: Task 2 implements the harmonic advisory model and bootstrap.
- Spec section 6: Tasks 3-4 implement nominal opportunities, confirmed recovery, dynamic cycles, both mid-dry metrics, bimodal descriptors, status, and confidence.
- Spec sections 7-8: Task 5 implements fixed-reference annual and monthly condition.
- Spec section 9: Task 6 implements count-first basin aggregation.
- Spec section 10: Task 6 provides the additive API and preserves legacy exports.
- Spec section 11: Tasks 7-8 implement deterministic and Fitzroy gates; external Gilbert, Toorale, Macquarie, and BoM work remains a documented validation direction, not an unverified package claim.
- Spec sections 12-13: approved citations remain in the design; Task 8 puts relevant interpretation limits in user documentation.
- Type names and signatures are consistent across tasks: `SeasonalPatternResult`, `DynamicHydroYearConfig`, `HydrologicalStateResult`, and all public state APIs use the same names everywhere.
- No report integration occurs before Fitzroy review. Existing report code remains unchanged.
