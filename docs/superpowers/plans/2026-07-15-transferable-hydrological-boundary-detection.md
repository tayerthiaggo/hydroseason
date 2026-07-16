# Transferable Hydrological Boundary Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver auditable, quality-aware trough/peak boundaries that unblock downstream workflows on Fitzroy and Gilbert River, then implement a hidden semi-Markov challenger behind the same interface.

**Architecture:** `hydroseason/_boundary.py` extracts robust observed extrema, contiguous low/high runs, coverage evidence, and sequence-consistent annual boundaries. `_dynamic_year.py` assembles cycles from those boundaries. `_semi_markov.py` supplies an opt-in four-state probabilistic challenger; both engines use one benchmark harness and additive diagnostics.

**Tech Stack:** Python 3.10+, pandas >=2.0, NumPy >=1.24, pytest >=8.0; existing optional raster/STAC dependencies only for fixture generation.

## Global Constraints

- Keep `hydro_year.py` and all fixed-calendar public behavior unchanged.
- Add no mandatory runtime dependency beyond pandas and NumPy.
- Never fetch network data during ordinary tests.
- Never silently replace a raw observed extremum.
- Count every eligible truth year in accuracy denominators; unresolved rows count as timing failures.
- Use percentage-point suffix `_pp` for absolute extent differences.
- Preserve one nominal opportunity per year; unresolved opportunities break cycle continuity.
- Preserve old recovery config fields and literal for one minor release with `DeprecationWarning`.
- Robust engine is default. Semi-Markov remains opt-in unless promotion gates pass.
- Stop after Task 8 for downstream-unblocking review; Tasks 9-10 add higher-rigor challenger without changing default.

---

## File map

- Create `hydroseason/_boundary.py`: robust statistics, candidates, windows, sequence optimization, support.
- Create `hydroseason/_boundary_validation.py`: event alignment and acceptance metrics.
- Create `hydroseason/_semi_markov.py`: log-space hidden semi-Markov inference.
- Create `scripts/build_real_extent_fixture.py`: reproducible DEA fixture generation.
- Create `tests/test_boundary.py`: robust detector unit tests.
- Create `tests/test_boundary_validation.py`: metric/alignment tests.
- Create `tests/test_semi_markov.py`: probabilistic engine tests.
- Create `tests/test_gilbert_regression.py`: frozen Gilbert acceptance gate.
- Create `tests/fixtures/gilbert_river_monthly.csv`: generated real monthly observations.
- Create `tests/fixtures/gilbert_river_reviewed_events.csv`: human-reviewed validation events.
- Modify `hydroseason/_dynamic_year.py`: config migration, engine dispatch, cycle assembly, additive diagnostics.
- Modify `hydroseason/hydrological_state.py`: propagate selected engine and diagnostics.
- Modify `tests/test_dynamic_year.py`: new boundary semantics and migration tests.
- Modify `tests/test_dynamic_state_benchmark.py`: all-eligible denominators and adversarial matrix.
- Modify `tests/test_fitzroy_regression.py`: interval matching and tail-error gates.
- Modify `docs/hydrological-state.md`, approved design, `CHANGELOG.md`: behavior, uncertainty, migration.

---

### Task 1: Build non-gameable validation metrics

**Files:**
- Create: `hydroseason/_boundary_validation.py`
- Create: `tests/test_boundary_validation.py`

**Interfaces:**
- Produces: `month_delta(left, right)`, `align_events_by_interval(truth, actual)`, `summarize_timing(aligned)`.
- Consumers: Fitzroy, Gilbert, synthetic, and semi-Markov comparison tests.

- [ ] **Step 1: Write failing tests proving unresolved events and tail errors cannot hide**

```python
# tests/test_boundary_validation.py
import pandas as pd

from hydroseason._boundary_validation import summarize_timing


def test_timing_summary_counts_unresolved_truth_as_failure():
    aligned = pd.DataFrame({
        "truth_month": pd.to_datetime(["2020-09-01", "2021-09-01"]),
        "actual_month": pd.to_datetime(["2020-09-01", None]),
    })
    metrics = summarize_timing(aligned)
    assert metrics["n_eligible"] == 2
    assert metrics["n_resolved"] == 1
    assert metrics["coverage"] == 0.5
    assert metrics["within_1_month"] == 0.5


def test_timing_summary_exposes_large_tail_error_despite_good_median():
    aligned = pd.DataFrame({
        "truth_month": pd.to_datetime(["2020-09-01", "2021-09-01", "2022-09-01"]),
        "actual_month": pd.to_datetime(["2020-09-01", "2021-10-01", "2023-09-01"]),
    })
    metrics = summarize_timing(aligned)
    assert metrics["median_abs_error_months"] == 1.0
    assert metrics["max_abs_error_months"] == 12.0
    assert metrics["p90_abs_error_months"] > 9.0
```

- [ ] **Step 2: Run tests and confirm missing module failure**

Run: `python -m pytest tests/test_boundary_validation.py -q`

Expected: FAIL with `ModuleNotFoundError: hydroseason._boundary_validation`.

- [ ] **Step 3: Implement complete timing summary**

```python
# hydroseason/_boundary_validation.py
from __future__ import annotations

import numpy as np
import pandas as pd


def month_delta(left: pd.Series, right: pd.Series) -> pd.Series:
    left = pd.to_datetime(left)
    right = pd.to_datetime(right)
    return (left.dt.year - right.dt.year) * 12 + left.dt.month - right.dt.month


def summarize_timing(aligned: pd.DataFrame) -> dict[str, float | int]:
    required = {"truth_month", "actual_month"}
    if not required.issubset(aligned.columns):
        raise ValueError(f"aligned events require columns {sorted(required)}")
    eligible = aligned["truth_month"].notna()
    resolved = eligible & aligned["actual_month"].notna()
    signed = month_delta(
        aligned.loc[resolved, "actual_month"],
        aligned.loc[resolved, "truth_month"],
    ).astype(float)
    absolute = signed.abs()
    n_eligible = int(eligible.sum())
    n_resolved = int(resolved.sum())
    within = int((absolute <= 1).sum())
    penalized = pd.Series(12.0, index=aligned.index[eligible], dtype=float)
    penalized.loc[resolved] = absolute
    return {
        "n_eligible": n_eligible,
        "n_resolved": n_resolved,
        "coverage": n_resolved / n_eligible if n_eligible else np.nan,
        "within_1_month": within / n_eligible if n_eligible else np.nan,
        "signed_bias_months": float(signed.mean()) if len(signed) else np.nan,
        "resolved_mae_months": float(absolute.mean()) if len(absolute) else np.nan,
        "total_mae_months": float(penalized.mean()) if n_eligible else np.nan,
        "median_abs_error_months": float(penalized.median()) if n_eligible else np.nan,
        "p90_abs_error_months": float(penalized.quantile(0.90)) if n_eligible else np.nan,
        "max_abs_error_months": float(penalized.max()) if n_eligible else np.nan,
    }
```

- [ ] **Step 4: Add interval alignment test and implementation**

```python
def test_interval_alignment_uses_cycle_dates_not_raw_year_label():
    truth = pd.DataFrame({
        "event_id": ["a"],
        "interval_start": pd.to_datetime(["2015-12-01"]),
        "interval_end": pd.to_datetime(["2016-11-01"]),
        "truth_month": pd.to_datetime(["2016-03-01"]),
    })
    actual = pd.DataFrame({
        "actual_month": pd.to_datetime(["2016-03-01"]),
    })
    aligned = align_events_by_interval(truth, actual)
    assert aligned.loc[0, "actual_month"] == pd.Timestamp("2016-03-01")
```

```python
def align_events_by_interval(truth: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    rows = []
    actual_dates = pd.to_datetime(actual["actual_month"]).dropna()
    for row in truth.itertuples(index=False):
        candidates = actual_dates.loc[actual_dates.gt(row.interval_start) & actual_dates.lt(row.interval_end)]
        chosen = pd.NaT
        if len(candidates):
            delta = (candidates - row.truth_month).abs()
            chosen = pd.Timestamp(candidates.loc[delta.idxmin()])
        rows.append({"event_id": row.event_id, "truth_month": row.truth_month, "actual_month": chosen})
    return pd.DataFrame(rows)
```

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_boundary_validation.py -q`

Expected: PASS.

```bash
git add hydroseason/_boundary_validation.py tests/test_boundary_validation.py
git commit -m "test: add non-gameable boundary metrics"
```

---

### Task 2: Generate and review frozen Gilbert River evidence

**Files:**
- Create: `scripts/build_real_extent_fixture.py`
- Create: `tests/test_real_fixture_builder.py`
- Generate: `tests/fixtures/gilbert_river_monthly.csv`
- Create after review: `tests/fixtures/gilbert_river_reviewed_events.csv`

**Interfaces:**
- Consumes: `load_aoi`, `load_wofs_from_stac`, `monthly_water_extent`.
- Produces: provenance-bearing monthly CSV and independent reviewed-event CSV.

- [ ] **Step 1: Write a failing builder test using injected loaders**

```python
# tests/test_real_fixture_builder.py
import pandas as pd

from scripts.build_real_extent_fixture import add_provenance


def test_add_provenance_preserves_counts_and_identifies_source():
    frame = pd.DataFrame({
        "n_water": [2], "n_aoi": [10], "n_valid": [8], "n_invalid": [2],
        "extent_pct": [25.0], "invalid_pct": [20.0],
    }, index=pd.to_datetime(["2020-01-01"]))
    result = add_provenance(frame, source="DEA ga_ls_wo_3", aoi="data/a.geojson")
    assert result.index.name == "date"
    assert result.loc[pd.Timestamp("2020-01-01"), "source"] == "DEA ga_ls_wo_3"
    assert result.loc[pd.Timestamp("2020-01-01"), "aoi"] == "data/a.geojson"
```

- [ ] **Step 2: Implement reproducible command-line builder**

```python
# scripts/build_real_extent_fixture.py
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from hydroseason import load_aoi, load_wofs_from_stac, monthly_water_extent


def add_provenance(frame: pd.DataFrame, *, source: str, aoi: str) -> pd.DataFrame:
    result = frame.copy()
    result.index = pd.to_datetime(result.index)
    result.index.name = "date"
    result["source"] = source
    result["aoi"] = aoi
    return result


def build(aoi_path: Path, output: Path, start: str, end: str) -> None:
    aoi = load_aoi(aoi_path)
    masks = load_wofs_from_stac(
        "https://explorer.dea.ga.gov.au/stac",
        "ga_ls_wo_3",
        aoi,
        start,
        end,
    )
    extent = add_provenance(
        monthly_water_extent(masks),
        source="DEA Water Observations ga_ls_wo_3",
        aoi=aoi_path.as_posix(),
    )
    expected = pd.date_range(start, end, freq="MS")
    if not extent.index.equals(expected):
        raise RuntimeError("DEA fixture does not contain exactly one row per requested month")
    output.parent.mkdir(parents=True, exist_ok=True)
    extent.to_csv(output, date_format="%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aoi", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2025-12-31")
    args = parser.parse_args()
    build(args.aoi, args.output, args.start, args.end)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify helper without network, then generate Gilbert fixture explicitly**

Run: `python -m pytest tests/test_real_fixture_builder.py -q`

Expected: PASS.

Run only in approved network environment:

```bash
python scripts/build_real_extent_fixture.py --aoi data/Gilbert_river_buffer.geojson --output tests/fixtures/gilbert_river_monthly.csv --start 2015-01-01 --end 2025-12-31
```

Expected: 132 data rows plus header, complete monthly dates, count columns, source, AOI provenance.

- [ ] **Step 4: Produce independent reviewed events**

Create `tests/fixtures/gilbert_river_reviewed_events.csv` with exact schema:

```csv
event_id,interval_start,interval_end,trough_month,peak_month,detectable,reviewer,review_notes
```

Two reviewers inspect monthly counts, invalid coverage, plotted extent, and source imagery for disputed months. They record one row per complete review interval. Algorithm output may be shown only after initial dates are recorded. Disagreements are adjudicated and described in `review_notes`; neither detector writes this file.

- [ ] **Step 5: Freeze provenance and commit**

```bash
git add data/Gilbert_river_buffer.geojson scripts/build_real_extent_fixture.py tests/test_real_fixture_builder.py tests/fixtures/gilbert_river_monthly.csv tests/fixtures/gilbert_river_reviewed_events.csv
git commit -m "test: add reviewed Gilbert River evidence"
```

---

### Task 3: Define auditable boundary types and config migration

**Files:**
- Create: `hydroseason/_boundary.py`
- Create: `tests/test_boundary.py`
- Modify: `hydroseason/_dynamic_year.py:13-44`
- Modify: `tests/test_dynamic_year.py`

**Interfaces:**
- Produces: `BoundaryWindow`, `BoundarySelection`, `RobustBoundaryConfig`.
- Preserves: old recovery fields and literal with warnings.

- [ ] **Step 1: Write failing dataclass and migration tests**

```python
# tests/test_boundary.py
import pandas as pd
import pytest

from hydroseason._boundary import BoundarySelection, RobustBoundaryConfig


def test_boundary_selection_keeps_raw_and_selected_observations():
    selection = BoundarySelection(
        raw_month=pd.Timestamp("2020-09-01"), raw_extent_pct=2.0,
        selected_month=pd.Timestamp("2020-09-01"), selected_extent_pct=2.0,
        run_start=pd.Timestamp("2020-09-01"), run_end=pd.Timestamp("2020-10-01"),
        window_status="full", selection_status="raw", support=1.0,
        n_expected=7, n_usable=7, phase_shift_months=0,
    )
    assert selection.raw_month == selection.selected_month


def test_boundary_config_rejects_impossible_coverage():
    with pytest.raises(ValueError, match="min_window_coverage"):
        RobustBoundaryConfig(min_window_coverage=1.1)
```

```python
# append to tests/test_dynamic_year.py
def test_old_recovery_fields_warn_for_one_release():
    with pytest.warns(DeprecationWarning):
        DynamicHydroYearConfig(expected_trough_month=9, sustained_rise_months=2)
```

- [ ] **Step 2: Implement boundary types and validation**

```python
# hydroseason/_boundary.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

WindowStatus = Literal["full", "left_truncated", "right_truncated", "internal_gap"]
SelectionStatus = Literal["raw", "ambiguous", "quality_adjusted", "unresolved"]


@dataclass(frozen=True)
class RobustBoundaryConfig:
    min_usable_candidates: int = 2
    min_window_coverage: float = 0.70
    support_threshold: float = 0.80
    anomaly_noise_scales: float = 3.0

    def __post_init__(self) -> None:
        if self.min_usable_candidates < 1:
            raise ValueError("min_usable_candidates must be positive")
        if not 0 < self.min_window_coverage <= 1:
            raise ValueError("min_window_coverage must be in (0, 1]")
        if not 0 <= self.support_threshold <= 1:
            raise ValueError("support_threshold must be in [0, 1]")
        if self.anomaly_noise_scales <= 0:
            raise ValueError("anomaly_noise_scales must be positive")


@dataclass(frozen=True)
class BoundarySelection:
    raw_month: pd.Timestamp | None
    raw_extent_pct: float
    selected_month: pd.Timestamp | None
    selected_extent_pct: float
    run_start: pd.Timestamp | None
    run_end: pd.Timestamp | None
    window_status: WindowStatus
    selection_status: SelectionStatus
    support: float
    n_expected: int
    n_usable: int
    phase_shift_months: int | None
```

- [ ] **Step 3: Add compatibility fields and warnings**

In `DynamicHydroYearConfig`, add `detector: Literal["robust_extrema", "semi_markov"] = "robust_extrema"`. Keep recovery fields as `int | None = None`. In `__post_init__`, emit:

```python
import warnings

if self.sustained_rise_months is not None or self.pulse_rejection_window_months is not None:
    warnings.warn(
        "recovery-window fields are deprecated and ignored by robust_extrema",
        DeprecationWarning,
        stacklevel=2,
    )
if self.dry_plateau_rule == "last_before_confirmed_recovery":
    warnings.warn(
        "last_before_confirmed_recovery is deprecated; use raw_minimum",
        DeprecationWarning,
        stacklevel=2,
    )
if self.detector not in {"robust_extrema", "semi_markov"}:
    raise ValueError("detector must be 'robust_extrema' or 'semi_markov'")
```

Change default `dry_plateau_rule` to `"raw_minimum"`; accept old literal as compatibility input.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_boundary.py tests/test_dynamic_year.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_boundary.py hydroseason/_dynamic_year.py tests/test_boundary.py tests/test_dynamic_year.py
git commit -m "feat: define auditable boundary contract"
```

---

### Task 4: Implement adaptive noise, coverage, and contiguous low runs

**Files:**
- Modify: `hydroseason/_boundary.py`
- Modify: `tests/test_boundary.py`

**Interfaces:**
- Produces: `robust_scale(frame)` and `select_window_minimum(...)`.

- [ ] **Step 1: Write adversarial tests**

```python
def test_singleton_low_is_retained_but_marked_ambiguous():
    index = pd.date_range("2020-06-01", periods=7, freq="MS")
    frame = pd.DataFrame({
        "extent_pct": [20, 15, 10, 1, 11, 16, 22],
        "invalid_pct": 0.0, "candidate_usable": True,
    }, index=index)
    result = select_window_minimum(frame, expected=pd.Timestamp("2020-09-01"),
                                   expected_count=7, noise_pp=2.0, amplitude_pp=21.0)
    assert result.raw_month == pd.Timestamp("2020-09-01")
    assert result.selected_month == result.raw_month
    assert result.selection_status == "ambiguous"


def test_low_run_is_contiguous_and_does_not_cross_rewetting():
    index = pd.date_range("2020-06-01", periods=7, freq="MS")
    frame = pd.DataFrame({
        "extent_pct": [8, 2, 2.2, 9, 2.1, 10, 15],
        "invalid_pct": 0.0, "candidate_usable": True,
    }, index=index)
    result = select_window_minimum(frame, expected=pd.Timestamp("2020-09-01"),
                                   expected_count=7, noise_pp=0.5, amplitude_pp=13.0)
    assert result.run_start == pd.Timestamp("2020-07-01")
    assert result.run_end == pd.Timestamp("2020-08-01")


def test_right_truncated_window_is_provisional_evidence():
    index = pd.date_range("2020-08-01", periods=5, freq="MS")
    frame = pd.DataFrame({"extent_pct": [5, 4, 3, 2, 1], "invalid_pct": 0.0,
                          "candidate_usable": True}, index=index)
    result = select_window_minimum(frame, expected=pd.Timestamp("2020-11-01"),
                                   expected_count=7, noise_pp=0.2, amplitude_pp=4.0)
    assert result.window_status == "right_truncated"
    assert result.support < 0.80
```

- [ ] **Step 2: Implement robust scale and adaptive tolerance**

```python
import numpy as np


def robust_scale(frame: pd.DataFrame) -> tuple[float, float]:
    usable = frame.loc[frame["candidate_usable"], "extent_pct"].astype(float)
    if not len(usable):
        return 0.0, 0.0
    amplitude = float(usable.quantile(0.90) - usable.quantile(0.10))
    month_median = usable.groupby(usable.index.month).transform("median")
    delta = (usable - month_median).diff().dropna().to_numpy(float)
    if not len(delta):
        return amplitude, 0.0
    centre = float(np.median(delta))
    noise = 1.4826 * float(np.median(np.abs(delta - centre))) / np.sqrt(2.0)
    return amplitude, noise


def _epsilon_pp(row: pd.Series, *, noise_pp: float, amplitude_pp: float) -> float:
    resolution = 100.0 / float(row["n_valid"]) if "n_valid" in row and row["n_valid"] > 0 else 0.0
    return min(0.10 * amplitude_pp, max(resolution, noise_pp)) if amplitude_pp > 0 else 0.0
```

- [ ] **Step 3: Implement contiguous-run selection without automatic deletion**

Implement `select_window_minimum` so it:

```python
def select_window_minimum(
    window: pd.DataFrame,
    *,
    expected: pd.Timestamp,
    expected_count: int,
    noise_pp: float,
    amplitude_pp: float,
    config: RobustBoundaryConfig = RobustBoundaryConfig(),
) -> BoundarySelection:
    usable = window.loc[window["candidate_usable"]].copy()
    n_usable = len(usable)
    if n_usable < config.min_usable_candidates:
        return BoundarySelection(None, np.nan, None, np.nan, None, None,
                                 "internal_gap", "unresolved", 0.0,
                                 expected_count, n_usable, None)
    raw_month = pd.Timestamp(usable["extent_pct"].idxmin())
    raw_extent = float(usable.loc[raw_month, "extent_pct"])
    epsilon = _epsilon_pp(usable.loc[raw_month], noise_pp=noise_pp, amplitude_pp=amplitude_pp)
    equivalent = (
        window["candidate_usable"]
        & window["extent_pct"].le(raw_extent + epsilon)
    )
    groups = equivalent.ne(equivalent.shift(fill_value=False)).cumsum()
    raw_group = groups.loc[raw_month]
    run = window.loc[equivalent & groups.eq(raw_group)]
    local = usable["extent_pct"].rolling(3, center=True, min_periods=2).median()
    residual = float(local.loc[raw_month] - raw_extent)
    ambiguous = noise_pp > 0 and residual > config.anomaly_noise_scales * noise_pp
    full_start = expected - pd.DateOffset(months=(expected_count - 1) // 2)
    full_end = expected + pd.DateOffset(months=(expected_count - 1) // 2)
    if window.index.min() > full_start:
        window_status = "left_truncated"
    elif window.index.max() < full_end:
        window_status = "right_truncated"
    elif n_usable / expected_count < config.min_window_coverage:
        window_status = "internal_gap"
    else:
        window_status = "full"
    support = min(1.0, n_usable / expected_count)
    if ambiguous:
        support *= 0.60
    if window_status != "full":
        support *= 0.75
    return BoundarySelection(
        raw_month, raw_extent, raw_month, raw_extent,
        pd.Timestamp(run.index[0]), pd.Timestamp(run.index[-1]),
        window_status, "ambiguous" if ambiguous else "raw", support,
        expected_count, n_usable,
        (raw_month.year - expected.year) * 12 + raw_month.month - expected.month,
    )
```

- [ ] **Step 4: Run boundary tests**

Run: `python -m pytest tests/test_boundary.py -q`

Expected: PASS, including singleton and noncontiguous cases.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_boundary.py tests/test_boundary.py
git commit -m "feat: detect robust contiguous low runs"
```

---

### Task 5: Add sequence-consistent equivalent-candidate optimization

**Files:**
- Modify: `hydroseason/_boundary.py`
- Modify: `tests/test_boundary.py`

**Interfaces:**
- Produces: `select_boundary_sequence(opportunities)`.
- Constraint: may move within equivalent run only; never jump to materially higher month.

- [ ] **Step 1: Write failing cycle-coherence test**

```python
def test_sequence_optimizer_uses_equivalent_date_to_avoid_short_cycle():
    opportunities = [
        {"year": 2020, "expected": pd.Timestamp("2020-09-01"),
         "candidates": [(pd.Timestamp("2020-08-01"), 2.0), (pd.Timestamp("2020-09-01"), 2.1)]},
        {"year": 2021, "expected": pd.Timestamp("2021-09-01"),
         "candidates": [(pd.Timestamp("2021-07-01"), 1.9), (pd.Timestamp("2021-09-01"), 2.0)]},
    ]
    selected = select_boundary_sequence(opportunities)
    assert selected == [pd.Timestamp("2020-09-01"), pd.Timestamp("2021-09-01")]
```

- [ ] **Step 2: Implement dynamic programming with explicit cost**

```python
def select_boundary_sequence(opportunities: list[dict]) -> list[pd.Timestamp | None]:
    selected: list[pd.Timestamp | None] = [None] * len(opportunities)

    def optimize_block(block: list[dict]) -> list[pd.Timestamp]:
        costs: list[list[float]] = []
        parents: list[list[int | None]] = []
        for index, opportunity in enumerate(block):
            row_costs, row_parents = [], []
            for date, _ in opportunity["candidates"]:
                phase = abs(
                    (date.year - opportunity["expected"].year) * 12
                    + date.month - opportunity["expected"].month
                )
                if index == 0:
                    row_costs.append(float(phase))
                    row_parents.append(None)
                    continue
                best_cost, best_parent = float("inf"), None
                for parent_index, (previous_date, _) in enumerate(block[index - 1]["candidates"]):
                    cycle = (date.year - previous_date.year) * 12 + date.month - previous_date.month
                    candidate_cost = costs[index - 1][parent_index] + phase + abs(cycle - 12)
                    if candidate_cost < best_cost:
                        best_cost, best_parent = candidate_cost, parent_index
                row_costs.append(best_cost)
                row_parents.append(best_parent)
            costs.append(row_costs)
            parents.append(row_parents)
        cursor = int(np.argmin(costs[-1]))
        chosen = []
        for index in range(len(block) - 1, -1, -1):
            chosen.append(pd.Timestamp(block[index]["candidates"][cursor][0]))
            parent = parents[index][cursor]
            if parent is not None:
                cursor = parent
        return list(reversed(chosen))

    block_start = 0
    while block_start < len(opportunities):
        while block_start < len(opportunities) and not opportunities[block_start]["candidates"]:
            block_start += 1
        if block_start == len(opportunities):
            break
        block_end = block_start
        while block_end < len(opportunities) and opportunities[block_end]["candidates"]:
            block_end += 1
        selected[block_start:block_end] = optimize_block(opportunities[block_start:block_end])
        block_start = block_end
    return selected
```

- [ ] **Step 3: Add unresolved-year sequence-break test**

```python
def test_sequence_optimizer_preserves_unresolved_year_and_restarts():
    opportunities = [
        {"year": 2020, "expected": pd.Timestamp("2020-09-01"),
         "candidates": [(pd.Timestamp("2020-09-01"), 2.0)]},
        {"year": 2021, "expected": pd.Timestamp("2021-09-01"), "candidates": []},
        {"year": 2022, "expected": pd.Timestamp("2022-09-01"),
         "candidates": [(pd.Timestamp("2022-09-01"), 2.0)]},
    ]
    assert select_boundary_sequence(opportunities) == [
        pd.Timestamp("2020-09-01"), None, pd.Timestamp("2022-09-01")
    ]
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_boundary.py tests/test_boundary.py
git commit -m "feat: optimize annual boundary sequence"
```

---

### Task 6: Replace trough recovery gate and expose diagnostics

**Files:**
- Modify: `hydroseason/_dynamic_year.py:65-155,193-265`
- Modify: `tests/test_dynamic_year.py`
- Modify: `tests/test_dynamic_state_benchmark.py`

**Interfaces:**
- Consumes: `robust_scale`, `select_window_minimum`, `select_boundary_sequence`.
- Produces: existing annual columns plus additive boundary diagnostics.

- [ ] **Step 1: Rewrite removed-state-machine tests as observed-boundary tests**

Replace recovery confirmation assertions with:

```python
def test_mid_dry_rise_does_not_replace_later_lower_trough():
    raw = _candidate_frame()
    raw.loc["2020-07-01":"2021-02-01", "extent_pct"] = [5, 8, 9, 4, 8, 12, 20, 25]
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    row = result.loc[result["hy_year"] == 2020].iloc[0]
    assert row["raw_trough_month"] == pd.Timestamp("2020-10-01")
    assert row["trough_month"] == pd.Timestamp("2020-10-01")


def test_final_incomplete_search_window_is_provisional():
    raw = _candidate_frame(periods=34)
    result = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9)
    )
    row = result.loc[result["hy_year"] == 2020].iloc[0]
    assert row["window_status"] == "right_truncated"
    assert row["boundary_status"] == "provisional"
```

- [ ] **Step 2: Replace `_recovery_status` and `_select_low_candidate` calls**

Rename `_find_trough_opportunities` to
`_find_robust_trough_opportunities(frame: pd.DataFrame, config: DynamicHydroYearConfig) -> pd.DataFrame`.
Compute robust scale once, build exact expected windows, call
`select_window_minimum`, then sequence-optimize equivalent candidates. Delete
`_recovery_status`; retain no future-tail scan.

- [ ] **Step 3: Extend annual output contract**

Append to `ANNUAL_COLUMNS`:

```python
"raw_trough_month", "raw_trough_extent_pct",
"low_run_start_month", "low_run_end_month",
"window_status", "selection_status", "selection_support",
"window_n_expected", "window_n_usable", "phase_shift_months",
"raw_peak_month", "raw_peak_extent_pct",
"peak_selection_status", "peak_selection_support",
```

Map `BoundarySelection` fields without overloading `status_reason`. Set boundary:

```python
confirmed = (
    selection.window_status == "full"
    and selection.selection_status == "raw"
    and selection.support >= 0.80
)
boundary_status = "confirmed" if confirmed else "provisional"
```

- [ ] **Step 4: Run dynamic and synthetic tests**

Run: `python -m pytest tests/test_dynamic_year.py tests/test_dynamic_state_benchmark.py -q`

Expected: PASS; 2008 remains unresolved, 2009 remains `no_previous_boundary`, 2003 pulse trough remains exact.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_dynamic_year.py tests/test_dynamic_year.py tests/test_dynamic_state_benchmark.py
git commit -m "feat: replace recovery gate with robust boundaries"
```

---

### Task 7: Make peak selection symmetric and pulse counting gap-aware

**Files:**
- Modify: `hydroseason/_boundary.py`
- Modify: `hydroseason/_dynamic_year.py:224-259`
- Modify: `tests/test_boundary.py`
- Modify: `tests/test_dynamic_year.py`

**Interfaces:**
- Produces: `select_cycle_peak(cycle, start, end, noise_pp, amplitude_pp)`.

- [ ] **Step 1: Write high-glitch and strict-interval tests**

```python
def test_peak_selector_flags_isolated_high_without_hiding_raw_maximum():
    index = pd.date_range("2020-01-01", periods=8, freq="MS")
    cycle = pd.DataFrame({
        "extent_pct": [2, 10, 90, 11, 8, 6, 4, 2],
        "invalid_pct": 0.0, "candidate_usable": True,
    }, index=index)
    peak = select_cycle_peak(cycle, start=index[0], end=index[-1], noise_pp=5, amplitude_pp=88)
    assert peak.raw_month == pd.Timestamp("2020-03-01")
    assert peak.selection_status == "ambiguous"


def test_peak_candidates_exclude_both_trough_boundaries():
    peak = select_cycle_peak(cycle, start=index[0], end=index[-1], noise_pp=1, amplitude_pp=10)
    assert index[0] < peak.selected_month < index[-1]
```

- [ ] **Step 2: Implement peak by sign inversion through shared selector**

Create an internal `_select_window_extreme(kind="min"|"max")`; trough wrapper passes `min`, peak wrapper passes `max`. For maxima, invert extent only for comparisons, while returning original observed values.

- [ ] **Step 3: Make pulse events contiguous and gap-aware**

Replace compressed-series diff count with exact integer-month adjacency:

```python
post = cycle.loc[peak:end, ["extent_pct", "candidate_usable"]]
delta = post["extent_pct"].diff()
month_number = post.index.year * 12 + post.index.month
adjacent = pd.Series(
    np.diff(month_number, prepend=month_number[0] - 1) == 1,
    index=post.index,
)
rise = post["candidate_usable"] & post["candidate_usable"].shift(fill_value=False) & adjacent & delta.gt(noise_pp)
pulses = int((rise & ~rise.shift(fill_value=False)).sum())
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_boundary.py tests/test_dynamic_year.py tests/test_dynamic_state_benchmark.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_boundary.py hydroseason/_dynamic_year.py tests/test_boundary.py tests/test_dynamic_year.py
git commit -m "feat: add robust peak and pulse detection"
```

---

### Task 8: Pass Fitzroy and Gilbert downstream-unblocking gates

**Files:**
- Modify: `tests/test_fitzroy_regression.py`
- Create: `tests/test_gilbert_regression.py`
- Modify: `tests/test_dynamic_state_benchmark.py`
- Modify: `hydroseason/_condition.py`

**Interfaces:**
- Consumes: shared validation metrics and frozen reviewed events.
- Produces: release-blocking real/synthetic evidence.

- [ ] **Step 1: Replace median-only Fitzroy gate**

Use `align_events_by_interval` and `summarize_timing`. Assert:

```python
assert metrics["coverage"] >= 0.80
assert metrics["within_1_month"] >= 0.80
assert metrics["p90_abs_error_months"] <= 2.0
assert metrics["max_abs_error_months"] < 11.0
```

Keep legacy immutability test unchanged. Store diagnostic metric dictionary in assertion messages.

- [ ] **Step 2: Add Gilbert gate against reviewed events**

```python
# tests/test_gilbert_regression.py
from pathlib import Path

import pandas as pd

from hydroseason import detect_dynamic_hydrological_years, suggest_dynamic_hydro_year_config
from hydroseason._boundary_validation import align_events_by_interval, summarize_timing

FIXTURES = Path(__file__).parent / "fixtures"


def test_gilbert_reviewed_events_meet_unblocking_gate():
    monthly = pd.read_csv(FIXTURES / "gilbert_river_monthly.csv", parse_dates=["date"]).set_index("date")
    truth = pd.read_csv(
        FIXTURES / "gilbert_river_reviewed_events.csv",
        parse_dates=["interval_start", "interval_end", "trough_month", "peak_month"],
    )
    config = suggest_dynamic_hydro_year_config(monthly, max_invalid_pct=20.0)
    actual = detect_dynamic_hydrological_years(monthly, config=config)
    trough_actual = actual.rename(columns={"trough_month": "actual_month"})[["actual_month"]]
    detectable = truth["detectable"].astype(str).str.lower().eq("true")
    trough_truth = truth.loc[detectable].rename(columns={"trough_month": "truth_month"})
    aligned = align_events_by_interval(trough_truth, trough_actual)
    metrics = summarize_timing(aligned)
    assert metrics["coverage"] >= 0.80, metrics
    assert metrics["within_1_month"] >= 0.80, metrics
    assert metrics["p90_abs_error_months"] <= 2.0, metrics
    assert metrics["max_abs_error_months"] < 11.0, metrics
```

- [ ] **Step 3: Ensure provisional cycles do not activate condition baseline**

Add test with ten cycles where one boundary is provisional; assert public condition remains `insufficient_baseline`. In `_condition.py`, retain `status == "complete"` requirement and add `boundary_status == "confirmed"` when column exists.

- [ ] **Step 4: Run unblocking matrix**

Run:

```bash
python -m pytest tests/test_boundary.py tests/test_boundary_validation.py tests/test_dynamic_year.py tests/test_dynamic_state_benchmark.py tests/test_fitzroy_regression.py tests/test_gilbert_regression.py tests/test_condition.py -q -s
```

Expected: PASS with printed Fitzroy/Gilbert coverage, within-one-month, MAE, P90, and maximum errors. If either real gate fails, stop; do not loosen thresholds. Inspect event diagnostics, correct detector or reviewed truth provenance, then rerun.

- [ ] **Step 5: Commit downstream-unblocking milestone**

```bash
git add hydroseason/_condition.py tests/test_fitzroy_regression.py tests/test_gilbert_regression.py tests/test_dynamic_state_benchmark.py tests/test_condition.py
git commit -m "test: gate robust boundaries on Fitzroy and Gilbert"
```

**Milestone:** downstream workflow may integrate `detector="robust_extrema"` after this task passes. Continue Tasks 9-10 without changing default.

---

### Task 9: Implement four-state hidden semi-Markov challenger

**Files:**
- Create: `hydroseason/_semi_markov.py`
- Create: `tests/test_semi_markov.py`

**Interfaces:**
- Produces: `SemiMarkovConfig`, `SemiMarkovResult`, `fit_semi_markov_boundaries(frame, expected_trough_month, config)`.
- States: `wet`, `recession`, `dry`, `recovery` with cyclic transitions only.

- [ ] **Step 1: Write deterministic state-path and missingness tests**

```python
# tests/test_semi_markov.py
import numpy as np
import pandas as pd

from hydroseason._semi_markov import fit_semi_markov_boundaries


def _seasonal_frame():
    index = pd.date_range("2019-01-01", periods=36, freq="MS")
    annual = np.array([80, 75, 60, 40, 25, 15, 8, 4, 3, 5, 20, 55], dtype=float)
    return pd.DataFrame({
        "extent_pct": np.tile(annual, 3),
        "observed_fraction": 1.0,
        "candidate_usable": True,
    }, index=index)


def test_semi_markov_recovers_dry_to_recovery_boundary():
    frame = _seasonal_frame()
    result = fit_semi_markov_boundaries(frame, expected_trough_month=9)
    assert len(result.trough_months) == 3
    assert all(date.month in {9, 10} for date in result.trough_months)
    assert result.state_posterior.shape == (36, 4)
    np.testing.assert_allclose(result.state_posterior.sum(axis=1), 1.0)


def test_semi_markov_does_not_turn_missing_month_into_transition():
    frame = _seasonal_frame()
    frame.loc[pd.Timestamp("2020-09-01"), ["candidate_usable", "observed_fraction"]] = [False, 0.0]
    result = fit_semi_markov_boundaries(frame, expected_trough_month=9)
    assert pd.Timestamp("2020-09-01") not in result.trough_months
```

- [ ] **Step 2: Define configuration and result contracts**

```python
# hydroseason/_semi_markov.py
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

STATES = ("wet", "recession", "dry", "recovery")


@dataclass(frozen=True)
class SemiMarkovConfig:
    min_duration: tuple[int, int, int, int] = (1, 1, 1, 1)
    max_duration: tuple[int, int, int, int] = (8, 10, 8, 8)
    max_iterations: int = 25
    convergence_tol: float = 1e-5
    variance_floor: float = 0.05


@dataclass(frozen=True)
class SemiMarkovResult:
    trough_months: tuple[pd.Timestamp, ...]
    peak_months: tuple[pd.Timestamp, ...]
    state_path: tuple[str, ...]
    state_posterior: np.ndarray
    trough_support: tuple[float, ...]
    log_likelihood: float
```

- [ ] **Step 3: Implement emissions and explicit-duration dynamic program**

Normalize usable extent by median and `max(Q90-Q10, variance_floor)`. Build two observations: normalized level and one-month slope. Initialize state means from robust quantiles and slope signs:

```python
level_mean = np.array([0.9, 0.5, 0.1, 0.5])
slope_mean = np.array([0.0, -0.2, 0.0, 0.2])
```

Emission log density uses diagonal Gaussian variance divided by
`clip(observed_fraction, 0.05, 1.0)`. Missing observations contribute zero
emission information and cannot be selected as boundaries.

Implement log-sum-exp locally:

```python
def _logsumexp(values: np.ndarray) -> float:
    maximum = float(np.max(values))
    return maximum + float(np.log(np.exp(values - maximum).sum()))
```

For each state, time, and permitted duration, accumulate segment emission plus
previous cyclic-state score and duration log probability. Store Viterbi parent
and forward log mass. Run matching backward recursion to obtain normalized
monthly posterior. No transition outside `wet -> recession -> dry -> recovery -> wet` is permitted.

- [ ] **Step 4: Extract boundaries and support**

For each year window around expected phase, select usable `dry -> recovery`
transition with maximum posterior mass. Define trough support as summed transition
posterior within plus/minus one month of selected date. Select peak as maximum
usable raw observation assigned to wet state strictly inside consecutive troughs.

Run: `python -m pytest tests/test_semi_markov.py -q`

Expected: PASS and posterior rows sum to one within numerical tolerance.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_semi_markov.py tests/test_semi_markov.py
git commit -m "feat: add semi-Markov boundary challenger"
```

---

### Task 10: Dispatch semi-Markov engine and enforce promotion gate

**Files:**
- Modify: `hydroseason/_dynamic_year.py`
- Modify: `tests/test_dynamic_year.py`
- Create: `tests/test_detector_comparison.py`

**Interfaces:**
- Consumes: `fit_semi_markov_boundaries` and shared validation metrics.
- Produces: identical annual schema for both detector choices.

- [ ] **Step 1: Write engine-dispatch contract test**

```python
def test_both_detectors_return_identical_columns():
    raw = _candidate_frame(start="2017-01-01", periods=84)
    robust = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9, detector="robust_extrema")
    )
    semi = detect_dynamic_hydrological_years(
        raw, config=DynamicHydroYearConfig(expected_trough_month=9, detector="semi_markov")
    )
    assert list(semi.columns) == list(robust.columns)
    assert semi["trough_month"].notna().any()
```

- [ ] **Step 2: Add detector dispatch**

At start of `detect_dynamic_hydrological_years`, prepare input once. Dispatch only boundary opportunity generation:

```python
if config.detector == "robust_extrema":
    opportunities = _find_robust_trough_opportunities(frame, config)
else:
    opportunities = _find_semi_markov_trough_opportunities(frame, config)
```

Both adapters return identical opportunity columns. Cycle assembly remains one shared path.

- [ ] **Step 3: Compare engines on identical folds**

`tests/test_detector_comparison.py` loads synthetic, Fitzroy, and Gilbert fixtures; computes paired per-event absolute errors, coverage, P90, false singleton rejection, Brier score, and runtime. Use fixed bootstrap seed `20260715` with 2,000 site/year block draws.

Experimental promotion assertion:

```python
assert comparison["semi_minus_robust_mae_ci_high"] < 0.0
assert comparison["semi_coverage"] >= comparison["robust_coverage"] - 0.02
assert comparison["semi_p90"] <= comparison["robust_p90"]
assert comparison["semi_false_singleton_rejection"] <= comparison["robust_false_singleton_rejection"]
assert comparison["semi_brier"] < comparison["robust_brier"]
assert comparison["semi_runtime_seconds"] <= 5 * comparison["robust_runtime_seconds"]
```

Mark this comparison test with `@pytest.mark.experimental` from its first
commit. Keep robust as default regardless of result on Fitzroy and Gilbert.
Promotion requires this test to pass after additional untouched climate/sensor
sites are added; only then remove the marker and change the default in a
separate reviewed plan. Do not change thresholds to manufacture eligibility.

- [ ] **Step 4: Run comparison matrix**

Run: `python -m pytest tests/test_semi_markov.py tests/test_dynamic_year.py tests/test_detector_comparison.py -q -s`

Expected: core semi-Markov and schema tests PASS. Experimental promotion test
prints each criterion and may fail without blocking robust-engine release;
robust remains default.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_dynamic_year.py tests/test_dynamic_year.py tests/test_detector_comparison.py
git commit -m "feat: compare boundary detection engines"
```

---

### Task 11: Document uncertainty, migration, and downstream contract

**Files:**
- Modify: `docs/hydrological-state.md`
- Modify: `docs/superpowers/specs/2026-07-15-hydrological-state-design.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_package_surface.py`

**Interfaces:**
- Documents robust default, opt-in semi-Markov engine, diagnostics, and compatibility window.

- [ ] **Step 1: Rewrite detector documentation**

Document exact meanings of raw versus selected extrema, contiguous run, provisional/confirmed, support, truncated window, and `detector` choice. State that confidence remains quality grade until calibrated. Include:

```python
config = DynamicHydroYearConfig(
    expected_trough_month=11,
    detector="robust_extrema",
)
annual = detect_dynamic_hydrological_years(monthly, config=config)
annual[[
    "raw_trough_month", "trough_month", "window_status",
    "selection_status", "selection_support", "boundary_status",
]]
```

- [ ] **Step 2: Update approved design and changelog**

Replace recovery-confirmation mechanism in approved design with link to transferable-boundary design. Under `CHANGELOG.md` Unreleased, list additive diagnostics, deprecated recovery fields, new robust default, and experimental semi-Markov engine.

- [ ] **Step 3: Test public exports and warnings**

Keep top-level exports unchanged. Add tests that old config input warns, new detector choices construct, and annual outputs contain additive diagnostics.

- [ ] **Step 4: Build docs strictly**

Run: `mkdocs build --strict`

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add docs/hydrological-state.md docs/superpowers/specs/2026-07-15-hydrological-state-design.md CHANGELOG.md tests/test_package_surface.py
git commit -m "docs: explain robust hydrological boundaries"
```

---

### Task 12: Full verification and release evidence

**Files:**
- Modify only if a gate exposes a defect; never loosen acceptance thresholds.

**Interfaces:**
- Produces: verified package and documented detector-comparison report.

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest -q`

Expected: all non-experimental tests PASS. Experimental promotion result is reported separately, never hidden as default success.

- [ ] **Step 2: Run lint and documentation**

Run: `ruff check hydroseason tests scripts`

Expected: exit 0.

Run: `mkdocs build --strict`

Expected: exit 0.

- [ ] **Step 3: Verify package artifacts**

Run: `python -m build`

Expected: sdist and wheel build.

Run: `python -m twine check dist/*`

Expected: both artifacts PASS.

- [ ] **Step 4: Verify clean diff and inspect scientific evidence**

Run: `git diff --check`

Expected: no whitespace errors.

Review printed Fitzroy, Gilbert, synthetic, and engine-comparison metrics. Confirm robust engine meets Task 8 gate and remains default unless Task 10 plus external holdouts authorize promotion.

- [ ] **Step 5: Close verification**

If a defect was fixed, return to its owning task, rerun that task's focused
tests, and use that task's exact `git add` and commit command. Then repeat Tasks
12.1-12.4. If no fixes were needed, make no empty commit.

---

## Execution checkpoints

1. After Task 2: Gilbert evidence exists and has independent reviewed truth.
2. After Task 6: old recovery gate is gone; raw and inferred boundaries are auditable.
3. After Task 8: robust detector may unblock downstream workflow.
4. After Task 10: semi-Markov challenger exists; promotion decision is evidence-based.
5. After Task 12: package, docs, and scientific gates all verified.
