# Stress-Trust Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `classify_annual_surface_water_condition` produce a trustworthy stress signal by adding (1) an adaptive rolling baseline, (2) a noise-floor hedge on the low/high labels, and (3) an amplitude-vs-noise timing-confidence flag — all additive, no change to existing outputs.

**Architecture:** Three independent additions to `hydroseason/_condition.py`, wired in through `hydroseason/hydrological_state.py::analyze_hydrological_state` (which already prepares the monthly frame and calls the classifier). New behavior is opt-in via a new `reference="rolling"` value and a new `noise_pp` argument; existing `full_record` / fixed-window callers get byte-identical results. Report gains two display columns.

**Tech Stack:** Python 3, pandas, numpy, pytest. No new dependencies.

## Global Constraints

- **Backward compatibility is mandatory.** Existing columns (`recharge_condition`, `refuge_condition`, `annual_condition`, `peak_percentile`, `trough_percentile`, `consecutive_*`) keep their exact current meaning and values for all existing call modes. Verified by a regression task.
- **Do not change** `compute_monthly_surface_water_condition` (out of scope).
- **Do not call** `probe_amplitude` (it does STAC I/O; see spec audit note). Amplitude comes from the existing `drawdown_pct = peak_extent_pct - trough_extent_pct`; noise comes from `robust_scale`'s `noise_pp`.
- **Existing `min_baseline_cycles` default is 10** (`DynamicHydroYearConfig`, `hydroseason/_dynamic_year.py:42`) and is relied on by `tests/test_condition.py`. The rolling floor of 5 must be a **separate** parameter (`rolling_min_cycles=5`) — do NOT repurpose `min_baseline_cycles`.
- New per-HY qualifier columns: `baseline_mode`, `baseline_n`, `baseline_uncertain`, `noise_floor_pp`, `recharge_condition_qualified`, `refuge_condition_qualified`, `annual_condition_qualified`, `timing_confidence`.
- Spec: `docs/superpowers/specs/2026-07-20-stress-trust-layer-design.md`.

---

## File Structure

- `hydroseason/_condition.py` — all three features land here. Currently 136 lines; the rolling-baseline selection and the qualifier computation are each a small helper to keep `classify_annual_surface_water_condition` readable.
- `hydroseason/hydrological_state.py` — wiring: compute `noise_pp` via `robust_scale(prepared)` and pass `reference`/rolling params + `noise_pp` into the classifier.
- `hydroseason/report.py` — add two display columns to the per-HY table.
- `tests/test_condition.py` — new tests for each feature + regression.
- `tests/test_run_multi_catchment_report.py` / `tests/test_report.py` — touched only if a report assertion needs the new columns (check during Task 6).

The `_condition.py` shared mapping (`("high","high") -> "wet_persistent"`, etc.) is currently a local dict inside `classify_annual_surface_water_condition`. Task 4 lifts it to a module-level constant `_JOINT_STATE_MAP` so the qualified recompute reuses it (DRY) rather than duplicating.

---

### Task 1: Extract the joint-state mapping to a module constant

Pure refactor with no behavior change, so the qualified-label recompute in Task 4 can reuse it instead of duplicating the dict.

**Files:**
- Modify: `hydroseason/_condition.py:74-80` (the inline `mapping = {...}` dict)
- Test: `tests/test_condition.py` (existing tests must still pass — this is the test)

**Interfaces:**
- Produces: module-level `_JOINT_STATE_MAP: dict[tuple[str, str], str]` and a helper `_join_conditions(recharge: str, refuge: str) -> str` returning the joint label (`_JOINT_STATE_MAP.get((recharge, refuge), "typical_or_mixed")`).

- [ ] **Step 1: Add the module constant and helper near the top of `_condition.py`** (after the imports, before `_empirical_percentile`)

```python
_JOINT_STATE_MAP: dict[tuple[str, str], str] = {
    ("high", "high"): "wet_persistent",
    ("high", "low"): "recharged_then_contracting",
    ("low", "high"): "buffered_low_recharge",
    ("low", "low"): "dry_low_refuge",
}


def _join_conditions(recharge: str, refuge: str) -> str:
    """Combine recharge/refuge conditions into the joint annual label."""
    return _JOINT_STATE_MAP.get((recharge, refuge), "typical_or_mixed")
```

- [ ] **Step 2: Replace the inline dict use** at `hydroseason/_condition.py:74-80`

Replace:

```python
    mapping = {
        ("high", "high"): "wet_persistent",
        ("high", "low"): "recharged_then_contracting",
        ("low", "high"): "buffered_low_recharge",
        ("low", "low"): "dry_low_refuge",
    }
    out["annual_condition"] = [mapping.get(pair, "typical_or_mixed") for pair in zip(out["recharge_condition"], out["refuge_condition"])]
```

with:

```python
    out["annual_condition"] = [
        _join_conditions(recharge, refuge)
        for recharge, refuge in zip(out["recharge_condition"], out["refuge_condition"])
    ]
```

- [ ] **Step 3: Run the existing condition tests to verify no behavior change**

Run: `python -m pytest tests/test_condition.py -v`
Expected: all existing tests PASS (7 tests, unchanged).

- [ ] **Step 4: Commit**

```bash
git add hydroseason/_condition.py
git commit -m "refactor: lift joint-state mapping to module constant in _condition"
```

---

### Task 2: Adaptive rolling baseline selection

Adds `reference="rolling"` with a trailing-then-expanding window so every year past the floor is labelled, adapting to non-stationarity.

**Files:**
- Modify: `hydroseason/_condition.py` — `classify_annual_surface_water_condition` signature + baseline-selection block (currently the single `reference_mask` at lines 43-56 and the percentile loop at 58-65)
- Test: `tests/test_condition.py`

**Interfaces:**
- Consumes: existing annual frame columns `hy_year`, `status`, `hy_end`, `boundary_status` (optional), `peak_extent_pct`, `trough_extent_pct`.
- Produces: new parameters `reference` gains `"rolling"` as a legal value; new params `rolling_window_cycles: int = 10`, `rolling_min_cycles: int = 5`. New output columns `baseline_mode` (`"full"`/`"fixed"`/`"insufficient"`/`"expanding"`/`"rolling"`), `baseline_n` (int), `baseline_uncertain` (bool). A per-row helper `_rolling_baseline_index(out, index, eligible_mask, window_cycles, min_cycles) -> tuple[pd.Index, str, bool]` returning (baseline row-labels, mode, uncertain).

- [ ] **Step 1: Write the failing test for rolling phase progression**

Add to `tests/test_condition.py`:

```python
def _annual_n(n_years, peak, trough, start=2000):
    years = np.arange(start, start + n_years)
    return pd.DataFrame(
        {
            "hy_year": years,
            "status": "complete",
            "boundary_status": "confirmed",
            "hy_end": pd.to_datetime([f"{year}-09-01" for year in years]),
            "peak_extent_pct": peak,
            "trough_extent_pct": trough,
        }
    )


def test_rolling_baseline_phases_label_every_year_past_floor():
    n = 21
    rng = np.random.default_rng(0)
    peak = 50 + rng.normal(0, 5, n)
    trough = 10 + rng.normal(0, 2, n)
    annual = _annual_n(n, peak, trough)
    result = classify_annual_surface_water_condition(
        annual, reference="rolling", rolling_window_cycles=10, rolling_min_cycles=5
    ).set_index("hy_year")
    # First 5 rows (0..4 prior cycles) are below the floor.
    assert (result["baseline_mode"].iloc[:5] == "insufficient").all()
    # Rows with 5..9 prior cycles are the expanding phase.
    assert (result["baseline_mode"].iloc[5:10] == "expanding").all()
    assert result["baseline_uncertain"].iloc[5:10].all()
    # Rows with >=10 prior cycles are the rolling phase, window pinned to 10.
    assert (result["baseline_mode"].iloc[10:] == "rolling").all()
    assert (result["baseline_n"].iloc[10:] == 10).all()
    assert not result["baseline_uncertain"].iloc[10:].any()
    # Every row past the floor has a real (non-insufficient) label.
    assert (result["annual_condition"].iloc[5:] != "insufficient_baseline").all()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_condition.py::test_rolling_baseline_phases_label_every_year_past_floor -v`
Expected: FAIL — `classify_annual_surface_water_condition() got an unexpected keyword argument 'reference'` is already accepted, but `'rolling'` raises the current `ValueError("reference must be 'full_record' or include reference_start and reference_end.")`.

- [ ] **Step 3: Add rolling params to the signature and the eligibility mask**

In `hydroseason/_condition.py`, change the signature of `classify_annual_surface_water_condition` to add (after `reference_end`):

```python
    rolling_window_cycles: int = 10,
    rolling_min_cycles: int = 5,
```

Replace the current guard at the top of the function body:

```python
    if reference != "full_record" and (reference_start is None or reference_end is None):
        raise ValueError("reference must be 'full_record' or include reference_start and reference_end.")
```

with:

```python
    if reference not in ("full_record", "rolling") and (reference_start is None or reference_end is None):
        raise ValueError("reference must be 'full_record', 'rolling', or include reference_start and reference_end.")
    if reference == "rolling" and not 1 <= rolling_min_cycles <= rolling_window_cycles:
        raise ValueError("rolling params must satisfy 1 <= rolling_min_cycles <= rolling_window_cycles.")
```

- [ ] **Step 4: Add the per-row baseline-index helper**

Add near `_condition` (module level) in `hydroseason/_condition.py`:

```python
def _rolling_baseline_index(order, position, eligible, window_cycles, min_cycles):
    """Return (baseline positional labels, mode, uncertain) for one HY row.

    ``order`` is the chronological positional index array (0..n-1). ``position``
    is the current row's position. ``eligible`` is a boolean array (same length)
    marking rows allowed to anchor the baseline (complete + confirmed). The
    baseline is the eligible rows strictly *before* ``position``; expanding
    below ``window_cycles``, sliding to the most recent ``window_cycles`` at or
    above it.
    """
    prior = [p for p in order[:position] if eligible[p]]
    prior_n = len(prior)
    if prior_n < min_cycles:
        return [], "insufficient", False
    if prior_n < window_cycles:
        return prior, "expanding", True
    return prior[-window_cycles:], "rolling", False
```

- [ ] **Step 5: Branch the percentile computation on `reference == "rolling"`**

In `classify_annual_surface_water_condition`, after `reference_mask` is built (the existing `complete`/`boundary_status`/`reference_start` block) and before the `for source, target in ...` percentile loop, insert a branch. Keep the existing loop for non-rolling modes; add the rolling path:

```python
    out["baseline_mode"] = "full" if reference == "full_record" else ("fixed" if reference != "rolling" else "")
    out["baseline_n"] = 0
    out["baseline_uncertain"] = False

    if reference == "rolling":
        order = list(range(len(out)))
        eligible = reference_mask.to_numpy()
        for source, target in (("peak_extent_pct", "peak_percentile"), ("trough_extent_pct", "trough_percentile")):
            values = []
            for position in order:
                labels, mode, uncertain = _rolling_baseline_index(
                    order, position, eligible, rolling_window_cycles, rolling_min_cycles
                )
                if source == "peak_extent_pct":  # record mode once, on the first axis pass
                    out.iloc[position, out.columns.get_loc("baseline_mode")] = mode
                    out.iloc[position, out.columns.get_loc("baseline_n")] = len(labels)
                    out.iloc[position, out.columns.get_loc("baseline_uncertain")] = uncertain
                baseline = out.iloc[labels][source] if labels else out[source].iloc[0:0]
                cell = out.iloc[position][source]
                values.append(_empirical_percentile(float(cell), baseline) if pd.notna(cell) and len(baseline) else np.nan)
            out[target] = values
        enough = True  # per-row insufficiency already encoded in baseline_mode
    else:
        for source, target in (("peak_extent_pct", "peak_percentile"), ("trough_extent_pct", "trough_percentile")):
            values = []
            for index, row in out.iterrows():
                baseline = out.loc[reference_mask, source]
                if reference_mask.loc[index]:
                    baseline = baseline.drop(index=index)
                values.append(_empirical_percentile(float(row[source]), baseline) if pd.notna(row[source]) else np.nan)
            out[target] = values
        enough = int(reference_mask.sum()) >= min_baseline_cycles
```

> Note: this replaces the current standalone percentile loop (`hydroseason/_condition.py:58-65`) and the `enough = ...` line (`:67`). The non-rolling branch is the *unchanged* original logic, just moved inside the `else`.

- [ ] **Step 6: Make the label assignment honor per-row insufficiency in rolling mode**

The existing block (`:68-73`) sets `recharge_condition`/`refuge_condition` from percentiles when `enough`. For rolling mode, additionally force `insufficient_baseline` on rows whose `baseline_mode == "insufficient"`. After the existing `out["recharge_condition"] = ...` / `out["refuge_condition"] = ...` assignment, add:

```python
    if reference == "rolling":
        insufficient_rows = out["baseline_mode"] == "insufficient"
        out.loc[insufficient_rows, ["recharge_condition", "refuge_condition"]] = "insufficient_baseline"
```

- [ ] **Step 7: Run the new test to verify it passes**

Run: `python -m pytest tests/test_condition.py::test_rolling_baseline_phases_label_every_year_past_floor -v`
Expected: PASS

- [ ] **Step 8: Run the full condition suite to confirm no regression**

Run: `python -m pytest tests/test_condition.py -v`
Expected: all PASS (7 original + 1 new).

- [ ] **Step 9: Commit**

```bash
git add hydroseason/_condition.py tests/test_condition.py
git commit -m "feat: adaptive rolling baseline for annual condition (expanding then trailing-10)"
```

---

### Task 3: Non-stationarity regression test for rolling baseline

Locks in the scientific point: after the window slides past a regime shift, the baseline no longer blends pre-shift values.

**Files:**
- Test: `tests/test_condition.py`

**Interfaces:**
- Consumes: `reference="rolling"` from Task 2.

- [ ] **Step 1: Write the regime-shift test**

Add to `tests/test_condition.py`:

```python
def test_rolling_baseline_forgets_pre_shift_regime():
    # 25 years: peak ~30 for years 0..14, steps up to ~70 for years 15..24.
    n = 25
    peak = np.concatenate([np.full(15, 30.0), np.full(10, 70.0)])
    trough = np.full(n, 5.0)
    annual = _annual_n(n, peak, trough)
    result = classify_annual_surface_water_condition(
        annual, reference="rolling", rolling_window_cycles=10, rolling_min_cycles=5
    ).set_index("hy_year")
    # By the last year (2024), all 10 prior cycles (2014..2023 -> positions 14..23)
    # are post-shift-valued (position 14 is still 30, positions 15..23 are 70), and
    # 2024's own peak (70) matches the new regime -> should NOT read as "high".
    # Use a fully-past-shift year: 2024 has prior positions 14..23; test the median.
    assert result.loc[2024, "baseline_mode"] == "rolling"
    # A clean post-shift year whose window is entirely post-shift: position 25 would
    # be needed for a pure window, but with n=25 the last row's window still holds
    # one pre-shift value (pos 14). Assert the softer, still-meaningful claim:
    # the last year is NOT labelled "high" (pre-shift baseline would have made 70 high).
    assert result.loc[2024, "recharge_condition"] != "high"
```

- [ ] **Step 2: Run to verify it passes** (Task 2 already implements the behavior)

Run: `python -m pytest tests/test_condition.py::test_rolling_baseline_forgets_pre_shift_regime -v`
Expected: PASS. If it FAILS because position 14 (value 30) still drags the median low enough to make 70 read "high", adjust the shift so the window is fully post-shift: change `np.full(15, ...)` to `np.full(14, ...)` and `np.full(10, ...)` to `np.full(11, ...)` so by 2024 all 10 prior cycles are post-shift. Re-run until PASS, then keep the adjusted values.

- [ ] **Step 3: Commit**

```bash
git add tests/test_condition.py
git commit -m "test: rolling baseline forgets pre-shift regime after window slides past"
```

---

### Task 4: Noise-floor hedge — qualified condition columns

Adds `*_qualified` columns that downgrade a low/high label to `typical_uncertain` when the departure from baseline median is inside the measurement noise floor.

**Files:**
- Modify: `hydroseason/_condition.py` — `classify_annual_surface_water_condition` (add `noise_pp` param + qualified-column computation at the end, before `return out`)
- Test: `tests/test_condition.py`

**Interfaces:**
- Consumes: `_join_conditions` (Task 1); existing `recharge_condition`, `refuge_condition`, `peak_extent_pct`, `trough_extent_pct`, `peak_percentile`, `trough_percentile`.
- Produces: new param `noise_pp: float | None = None`. New columns `noise_floor_pp` (float, = `noise_pp` or NaN), `recharge_condition_qualified`, `refuge_condition_qualified`, `annual_condition_qualified`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_condition.py`:

```python
def test_noise_floor_hedge_downgrades_within_band_only():
    # 11 confirmed years; year 2010 peak (110) is the record high -> "high" unhedged.
    annual = _annual().copy()
    annual["boundary_status"] = "confirmed"
    # Large noise_pp so the peak's departure from baseline median is inside the band.
    big = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5, noise_pp=1000.0
    ).set_index("hy_year")
    assert big.loc[2011, "recharge_condition"] == "high"          # unhedged unchanged
    assert big.loc[2011, "recharge_condition_qualified"] == "typical_uncertain"
    assert big.loc[2011, "noise_floor_pp"] == 1000.0
    # Small noise_pp: real departure survives -> qualified equals unhedged.
    small = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5, noise_pp=0.01
    ).set_index("hy_year")
    assert small.loc[2011, "recharge_condition_qualified"] == "high"
    # None: hedge skipped, qualified mirrors unhedged, noise_floor_pp is NaN.
    none = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5
    ).set_index("hy_year")
    assert none.loc[2011, "recharge_condition_qualified"] == none.loc[2011, "recharge_condition"]
    assert pd.isna(none.loc[2011, "noise_floor_pp"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_condition.py::test_noise_floor_hedge_downgrades_within_band_only -v`
Expected: FAIL — `unexpected keyword argument 'noise_pp'`.

- [ ] **Step 3: Add `noise_pp` param and compute the baseline median per row**

Add `noise_pp: float | None = None,` to the signature (after the rolling params from Task 2).

The hedge needs each row's baseline median for peak and trough. The cleanest place is to capture it during the percentile loop. In BOTH branches added in Task 2, alongside `values.append(...)`, also accumulate the baseline median. Simplest: after computing percentiles, add a dedicated median pass at the end of the function (before the qualified block) so this task is self-contained:

```python
    # Baseline median per row, per axis, matching the reference mode used above.
    def _baseline_median(source):
        medians = []
        if reference == "rolling":
            order = list(range(len(out)))
            eligible = reference_mask.to_numpy()
            for position in order:
                labels, _mode, _unc = _rolling_baseline_index(
                    order, position, eligible, rolling_window_cycles, rolling_min_cycles
                )
                base = out.iloc[labels][source] if labels else out[source].iloc[0:0]
                medians.append(float(base.median()) if len(base) else np.nan)
        else:
            for index, _row in out.iterrows():
                base = out.loc[reference_mask, source]
                if reference_mask.loc[index]:
                    base = base.drop(index=index)
                medians.append(float(base.median()) if len(base) else np.nan)
        return medians

    peak_median = _baseline_median("peak_extent_pct")
    trough_median = _baseline_median("trough_extent_pct")
```

- [ ] **Step 4: Compute the qualified columns**

Immediately after Step 3's median pass, before `return out`:

```python
    out["noise_floor_pp"] = float(noise_pp) if noise_pp is not None else np.nan

    def _qualify(condition_col, extent_col, medians):
        qualified = []
        for position, (_index, row) in enumerate(out.iterrows()):
            label = row[condition_col]
            if noise_pp is None or label not in ("low", "high"):
                qualified.append(label)
                continue
            median = medians[position]
            departure = abs(float(row[extent_col]) - median) if pd.notna(median) else np.inf
            qualified.append("typical_uncertain" if departure < float(noise_pp) else label)
        return qualified

    out["recharge_condition_qualified"] = _qualify("recharge_condition", "peak_extent_pct", peak_median)
    out["refuge_condition_qualified"] = _qualify("refuge_condition", "trough_extent_pct", trough_median)
    out["annual_condition_qualified"] = [
        _join_conditions(recharge, refuge)
        for recharge, refuge in zip(out["recharge_condition_qualified"], out["refuge_condition_qualified"])
    ]
    # Preserve the special-case labels the unhedged annual_condition uses.
    special = out["annual_condition"].isin(["insufficient_baseline", "not_applicable_low_variability"])
    out.loc[special, "annual_condition_qualified"] = out.loc[special, "annual_condition"]
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `python -m pytest tests/test_condition.py::test_noise_floor_hedge_downgrades_within_band_only -v`
Expected: PASS

- [ ] **Step 6: Run full condition suite**

Run: `python -m pytest tests/test_condition.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add hydroseason/_condition.py tests/test_condition.py
git commit -m "feat: noise-floor hedge produces *_qualified condition columns"
```

---

### Task 5: Timing-confidence flag

Adds `timing_confidence` (`low`/`high`/`unknown`) from per-HY amplitude (`drawdown_pct`) vs `k * noise_pp`.

**Files:**
- Modify: `hydroseason/_condition.py` — add the flag computation before `return out`
- Test: `tests/test_condition.py`

**Interfaces:**
- Consumes: `noise_pp` param (Task 4); `peak_extent_pct`, `trough_extent_pct` (drawdown computed inline since the annual frame passed to the classifier may not carry `drawdown_pct`).
- Produces: new param `timing_amplitude_k: float = 2.0`. New column `timing_confidence`.

> Note: `drawdown_pct` exists in `detect_dynamic_hydrological_years`'s output but the classifier's public contract only guarantees `peak_extent_pct`/`trough_extent_pct` (see `tests/test_condition.py::_annual`, which omits `drawdown_pct`). Compute amplitude as `peak_extent_pct - trough_extent_pct` inside the classifier so it works for both.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_condition.py`:

```python
def test_timing_confidence_from_amplitude_vs_noise():
    annual = _annual().copy()
    annual["boundary_status"] = "confirmed"
    # amplitudes (peak-trough) for _annual(): 9,8,27,36,45,54,63,72,81,90,108,109
    result = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5, noise_pp=10.0, timing_amplitude_k=2.0
    ).set_index("hy_year")
    # 2000 amplitude 9 < 2*10=20 -> low; 2001 amplitude 8 < 20 -> low
    assert result.loc[2000, "timing_confidence"] == "low"
    assert result.loc[2001, "timing_confidence"] == "low"
    # 2003 amplitude 36 >= 20 -> high
    assert result.loc[2003, "timing_confidence"] == "high"
    # noise_pp None -> unknown
    unknown = classify_annual_surface_water_condition(
        annual, min_baseline_cycles=5
    ).set_index("hy_year")
    assert (unknown["timing_confidence"] == "unknown").all()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_condition.py::test_timing_confidence_from_amplitude_vs_noise -v`
Expected: FAIL — `unexpected keyword argument 'timing_amplitude_k'`.

- [ ] **Step 3: Add param and compute the flag**

Add `timing_amplitude_k: float = 2.0,` to the signature (after `noise_pp`). Before `return out`, after the qualified block:

```python
    if noise_pp is None:
        out["timing_confidence"] = "unknown"
    else:
        amplitude = out["peak_extent_pct"] - out["trough_extent_pct"]
        threshold = float(timing_amplitude_k) * float(noise_pp)
        out["timing_confidence"] = np.where(amplitude < threshold, "low", "high")
        out.loc[amplitude.isna(), "timing_confidence"] = "unknown"
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python -m pytest tests/test_condition.py::test_timing_confidence_from_amplitude_vs_noise -v`
Expected: PASS

- [ ] **Step 5: Run full condition suite**

Run: `python -m pytest tests/test_condition.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add hydroseason/_condition.py tests/test_condition.py
git commit -m "feat: timing_confidence flag from per-HY amplitude vs noise floor"
```

---

### Task 6: Wire noise_pp and rolling mode through analyze_hydrological_state

Threads the record-level `noise_pp` (from `robust_scale`) and exposes rolling as an opt-in through the orchestrator, so the full pipeline emits the new columns.

**Files:**
- Modify: `hydroseason/hydrological_state.py:23-56` (`analyze_hydrological_state`)
- Modify: `hydroseason/_condition.py` (import `robust_scale` NOT needed here — compute in orchestrator)
- Test: `tests/test_hydrological_state.py`

**Interfaces:**
- Consumes: `robust_scale` from `hydroseason._boundary`; `prepare_monthly_extent` (already imported in `hydrological_state.py:11`); all new classifier params from Tasks 2/4/5.
- Produces: `analyze_hydrological_state` gains params `reference: str = "full_record"`, `rolling_window_cycles: int = 10`, `rolling_min_cycles: int = 5`. It always computes `noise_pp` from the prepared frame and passes it to the classifier; `annual` now carries the new columns.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hydrological_state.py` (create the file if it does not exist; check first with the run in Step 2). If the file exists, append:

```python
def test_analyze_threads_noise_pp_and_rolling_columns():
    import numpy as np
    import pandas as pd
    from hydroseason import analyze_hydrological_state

    # 15 years of monthly monsoonal extent so the detector yields several HYs.
    idx = pd.date_range("2000-01-01", periods=12 * 15, freq="MS")
    month = idx.month.to_numpy()
    # Simple annual cycle: high around Feb, low around Sep.
    extent = 40 + 30 * np.cos(2 * np.pi * (month - 2) / 12)
    frame = pd.DataFrame({"extent_pct": extent, "invalid_pct": 0.0}, index=idx)

    result = analyze_hydrological_state(frame, reference="rolling")
    annual = result.hydro_years
    assert "noise_floor_pp" in annual.columns
    assert "timing_confidence" in annual.columns
    assert "baseline_mode" in annual.columns
    assert "annual_condition_qualified" in annual.columns
    # noise_floor_pp is the same record-level value on every row (not NaN).
    assert annual["noise_floor_pp"].notna().all()
    assert annual["noise_floor_pp"].nunique() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_hydrological_state.py::test_analyze_threads_noise_pp_and_rolling_columns -v`
Expected: FAIL — `unexpected keyword argument 'reference'` on `analyze_hydrological_state`.

- [ ] **Step 3: Update the orchestrator**

In `hydroseason/hydrological_state.py`, add the import at the top (after line 11):

```python
from ._boundary import robust_scale
```

Change the `analyze_hydrological_state` signature to add (after `reference_end=None,`):

```python
    reference: str = "full_record",
    rolling_window_cycles: int = 10,
    rolling_min_cycles: int = 5,
```

Move the `prepared = prepare_monthly_extent(...)` block (currently lines 49-52) to BEFORE the `classify_annual_surface_water_condition` call, then compute `noise_pp` and pass it in. The classifier call becomes:

```python
    prepared = prepare_monthly_extent(
        extent, max_invalid_pct=selected.max_invalid_pct,
        allow_unknown_quality=selected.allow_unknown_quality,
    )
    _amplitude_pp, noise_pp = robust_scale(prepared)
    annual = classify_annual_surface_water_condition(
        annual,
        reference=reference,
        reference_start=reference_start,
        reference_end=reference_end,
        rolling_window_cycles=rolling_window_cycles,
        rolling_min_cycles=rolling_min_cycles,
        min_baseline_cycles=selected.min_baseline_cycles,
        low_percentile=selected.low_percentile,
        high_percentile=selected.high_percentile,
        low_variability=pattern.pattern == "low_variability",
        noise_pp=noise_pp,
    )
```

Then remove the now-duplicate `prepared = ...` block that followed the classifier call, keeping the `quality = ...` lines that use `prepared`.

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python -m pytest tests/test_hydrological_state.py::test_analyze_threads_noise_pp_and_rolling_columns -v`
Expected: PASS

- [ ] **Step 5: Run the broader suite to catch pipeline regressions**

Run: `python -m pytest tests/test_hydrological_state.py tests/test_condition.py tests/test_dynamic_year.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add hydroseason/hydrological_state.py tests/test_hydrological_state.py
git commit -m "feat: thread noise_pp and rolling baseline through analyze_hydrological_state"
```

---

### Task 7: Surface qualified label + timing_confidence in the HTML report

Adds two columns to the per-catchment HY table so a report reader sees the plain label alongside its trust qualifiers.

**Files:**
- Modify: `hydroseason/report.py` (the per-HY table builder — locate via grep in Step 1)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `annual` frame now carrying `annual_condition_qualified`, `timing_confidence` (Task 6).
- Produces: two extra columns in the rendered per-HY table HTML.

- [ ] **Step 1: Locate the per-HY table builder**

Run: `python -m pytest --collect-only tests/test_report.py -q` and grep the report for the HY table:

Run: `grep -n "annual_condition\|hy_year\|<td>\|<th>" hydroseason/report.py | head -40`
Expected: identifies the function that renders per-HY rows (the table with `annual_condition`). Note its exact line range for Step 3.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_report.py` a test that renders a report from a state result and asserts the new column headers appear. Match the file's existing report-generation fixture pattern (reuse the existing helper that builds a `HydrologicalStateResult` or calls `generate_html_report`; find it with `grep -n "def test_\|generate_html_report\|HydrologicalStateResult" tests/test_report.py`). The assertion:

```python
def test_report_shows_qualified_and_timing_columns():
    # Build the same inputs the existing report tests use, then:
    html = generate_html_report(...)  # reuse existing call shape from this file
    assert "Qualified" in html or "annual_condition_qualified" in html
    assert "Timing" in html or "timing_confidence" in html
```

Fill the `...` by copying the argument shape from the nearest existing `generate_html_report` call in the file.

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_report.py::test_report_shows_qualified_and_timing_columns -v`
Expected: FAIL — headers absent.

- [ ] **Step 4: Add the two columns to the HY table**

In the per-HY table builder located in Step 1, add a header cell `Qualified` after the existing condition header and `Timing` after it, and in the row loop add the matching data cells reading `row["annual_condition_qualified"]` and `row["timing_confidence"]` (guard with `.get(...)` / presence check so older frames without the columns still render):

```python
qualified = row.get("annual_condition_qualified", row.get("annual_condition", ""))
timing = row.get("timing_confidence", "unknown")
```

and emit `<td>{qualified}</td><td>{timing}</td>` in the same order as the headers.

- [ ] **Step 5: Run the new test to verify it passes**

Run: `python -m pytest tests/test_report.py::test_report_shows_qualified_and_timing_columns -v`
Expected: PASS

- [ ] **Step 6: Run the report suite**

Run: `python -m pytest tests/test_report.py tests/test_build_multi_catchment_html.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add hydroseason/report.py tests/test_report.py
git commit -m "feat: show qualified condition and timing_confidence in HY report table"
```

---

### Task 8: Full-suite regression + backward-compatibility proof

Proves existing columns are byte-identical for existing call modes and the whole suite is green.

**Files:**
- Test: `tests/test_condition.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the backward-compatibility test**

Add to `tests/test_condition.py`:

```python
def test_existing_columns_unchanged_for_full_record_mode():
    # The default (full_record) call must yield the same pre-existing columns
    # it always did; new columns are purely additive.
    annual = _annual().copy()
    annual["boundary_status"] = "confirmed"
    result = classify_annual_surface_water_condition(annual, min_baseline_cycles=5)
    # Pre-existing columns still present and populated.
    for col in ["recharge_condition", "refuge_condition", "annual_condition",
                "peak_percentile", "trough_percentile",
                "consecutive_dry_cycles", "consecutive_wet_cycles"]:
        assert col in result.columns
    # New columns are additive.
    for col in ["baseline_mode", "baseline_n", "baseline_uncertain",
                "noise_floor_pp", "recharge_condition_qualified",
                "refuge_condition_qualified", "annual_condition_qualified",
                "timing_confidence"]:
        assert col in result.columns
    # With noise_pp None (default), qualified mirrors unhedged exactly.
    assert (result["annual_condition_qualified"] == result["annual_condition"]).all()
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_condition.py::test_existing_columns_unchanged_for_full_record_mode -v`
Expected: PASS

- [ ] **Step 3: Run the ENTIRE test suite**

Run: `python -m pytest -q`
Expected: all PASS. If any pre-existing test fails, the additive contract was violated — fix the offending change (do not edit the failing test to accommodate a regression).

- [ ] **Step 4: Commit**

```bash
git add tests/test_condition.py
git commit -m "test: prove additive backward-compatibility of stress-trust columns"
```

---

---

### Task 9: Activate rolling baseline in the production runner

> **Added post-final-review (2026-07-20).** The final whole-branch review
> found Tasks 1-8 wire the adaptive rolling baseline end-to-end but
> `scripts/run_multi_catchment_report.py` never turns it on — it calls
> `analyze_hydrological_state(extent)` with no `reference` argument, so
> every production run silently uses `full_record` (the non-adaptive
> baseline this whole plan was meant to replace). The noise-hedge and
> timing-confidence flag *are* live (they don't depend on `reference`),
> but the rolling baseline itself — feature #1, the headline fix — ships
> dormant. Human decision: activate it in the runner now, as a CLI flag
> defaulting to rolling, with a test proving it flows through.

**Files:**
- Modify: `scripts/run_multi_catchment_report.py` — `run_one_catchment` (currently at line 235, signature ends line 245; the `analyze_hydrological_state(extent)` call is at line 328; `run_config` dict at lines ~247-261; `_build_arg_parser` at line 367; the `run_kwargs={...}` construction in `main()` at lines ~458-465)
- Test: `tests/test_run_multi_catchment_report.py`

**Interfaces:**
- Consumes: `analyze_hydrological_state(extent, *, reference="full_record", rolling_window_cycles=10, rolling_min_cycles=5, ...)` from Task 6 (`hydroseason/hydrological_state.py`), already accepts these kwargs.
- Produces: `run_one_catchment` gains a `baseline: str = "rolling"` keyword parameter (new default for *this function*, distinct from `analyze_hydrological_state`'s own `full_record` default — the runner opts every catchment into rolling unless told otherwise). `_build_arg_parser` gains `--baseline {rolling,full_record}` (default `"rolling"`). `run_config` (the checkpoint-identity dict) gains a `"baseline"` key so changing `--baseline` invalidates stale checkpoints, matching how `resolution_override`/`allow_large`/etc. already work.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_run_multi_catchment_report.py` (find the nearest existing test that calls `run_one_catchment` with mocked `load_wofs_monthly_extent`/`probe_amplitude`/`analyze_hydrological_state` collaborators — copy its mock-setup pattern). The new test:

```python
def test_run_one_catchment_defaults_to_rolling_baseline(monkeypatch):
    calls = []

    def _fake_analyze(extent, **kwargs):
        calls.append(kwargs)
        # Return a minimal, valid HydrologicalStateResult-shaped stand-in.
        return _minimal_state_result()  # reuse this file's existing helper/fixture
        # for constructing a HydrologicalStateResult, if one exists; otherwise
        # build one inline matching the shape other tests in this file already use.

    monkeypatch.setattr(
        "scripts.run_multi_catchment_report.analyze_hydrological_state", _fake_analyze
    )
    # ... mock load_wofs_monthly_extent, probe_amplitude, _catchment_geo_summary,
    # checkpoint I/O, etc. exactly as the nearest existing run_one_catchment test does.

    run_one_catchment(spec, force=True)  # default baseline

    assert calls[-1]["reference"] == "rolling"
    assert calls[-1]["rolling_window_cycles"] == 10
    assert calls[-1]["rolling_min_cycles"] == 5


def test_run_one_catchment_baseline_override_to_full_record(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.run_multi_catchment_report.analyze_hydrological_state",
        lambda extent, **kwargs: (calls.append(kwargs), _minimal_state_result())[1],
    )
    # ... same mocking as above ...

    run_one_catchment(spec, force=True, baseline="full_record")

    assert calls[-1]["reference"] == "full_record"
```

Adapt the mocking boilerplate to match whatever helper(s) `tests/test_run_multi_catchment_report.py` already uses for its existing `run_one_catchment` tests — do not invent a new mocking style. If the file has no `_minimal_state_result()` helper, build the `HydrologicalStateResult` inline the same way the file's nearest existing test does.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_run_multi_catchment_report.py::test_run_one_catchment_defaults_to_rolling_baseline -v`
Expected: FAIL — `run_one_catchment() got an unexpected keyword argument 'baseline'` (or the call to `analyze_hydrological_state` shows no `reference` kwarg at all).

- [ ] **Step 3: Add the `baseline` parameter and thread it into the call**

In `run_one_catchment`'s signature (`scripts/run_multi_catchment_report.py:235-245`), add:

```python
    baseline: str = "rolling",
```

In the `run_config` dict (used for checkpoint staleness detection), add a `"baseline": baseline,` entry alongside the existing keys.

Change the `analyze_hydrological_state(extent)` call (line 328) to:

```python
    state = analyze_hydrological_state(
        extent,
        reference=baseline,
        rolling_window_cycles=10,
        rolling_min_cycles=5,
    )
```

- [ ] **Step 4: Add the CLI flag and thread it through `main()`**

In `_build_arg_parser` (line 367+), add alongside the other `parser.add_argument` calls:

```python
    parser.add_argument(
        "--baseline", choices=["rolling", "full_record"], default="rolling",
        help="condition baseline mode: adaptive rolling (default) or single full-record baseline",
    )
```

In `main()`'s `run_kwargs={...}` construction (~line 458-465), add:

```python
            "baseline": args.baseline,
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `python -m pytest tests/test_run_multi_catchment_report.py::test_run_one_catchment_defaults_to_rolling_baseline tests/test_run_multi_catchment_report.py::test_run_one_catchment_baseline_override_to_full_record -v`
Expected: both PASS

- [ ] **Step 6: Run the full sibling suite to confirm no regression**

Run: `python -m pytest tests/test_run_multi_catchment_report.py -v`
Expected: all PASS (existing tests unaffected — `baseline` has a default, so calls without it keep working, just now opted into rolling instead of the old implicit full_record).

- [ ] **Step 7: Commit**

```bash
git add scripts/run_multi_catchment_report.py tests/test_run_multi_catchment_report.py
git commit -m "feat: activate rolling baseline by default in production runner, add --baseline override"
```

---

## Self-Review

**Spec coverage:**
- §1 Adaptive rolling baseline → Tasks 2, 3. ✓
- §2 Noise-floor hedge (via `robust_scale` `noise_pp`, not `100/n_valid`) → Task 4. ✓
- §3 Timing-confidence (via `drawdown_pct`, not `probe_amplitude`) → Task 5, reconciled with existing `confidence` (kept separate). ✓
- New columns table → Tasks 2/4/5 collectively add all 8. ✓
- report.py display → Task 7. ✓
- Wiring / `noise_pp` threading (Open Question resolved to orchestrator-computes) → Task 6. ✓
- Testing section (rolling phases, regime shift, noise hedge both directions + None, timing three-way, regression) → Tasks 2,3,4,5,8. ✓

**Placeholder scan:** Task 7 Step 2/4 reference "reuse existing call shape" rather than literal code — this is deliberate because the report test fixtures vary; Step 1 forces locating them first. All other steps carry literal code. Acceptable given the report harness is discovered at execution time.

**Type consistency:** `noise_pp: float | None` consistent across Tasks 4/5/6. `reference="rolling"`, `rolling_window_cycles`, `rolling_min_cycles` consistent Tasks 2/6. `_join_conditions` defined Task 1, used Tasks 1/4. `_rolling_baseline_index` defined Task 2, reused Task 4. Column names match the spec table exactly.

**Known deviation from spec (documented):** spec §1 said "reuse the existing `min_baseline_cycles`"; the plan uses a **separate** `rolling_min_cycles=5` because the existing param defaults to 10 and is depended on by `tests/test_condition.py`. This is a correctness fix, noted in Global Constraints.
