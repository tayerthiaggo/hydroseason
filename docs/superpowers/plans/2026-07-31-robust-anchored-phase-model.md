# Robust-Anchored Monthly Phase Model Implementation Plan

> **Note:** Rule-based phase model scope implemented through Task 4 of the release readiness plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add monthly hydrological phases (`wet`, `recession`, `dry`, `recovery`) anchored to validated `robust_extrema` trough/peak cycles, without letting any phase model rewrite annual boundaries, peaks, or condition baselines.

**Architecture:** Keep `detector` as the boundary engine. Add orthogonal `phase_model` (`none` | `rule_based` | `semi_markov`). Cycle assembly in `_dynamic_year.py` stays pure. New `hydroseason/_phase.py` maps resolved robust cycles to a `monthly_phase` frame. Orchestrator attaches it on `HydrologicalStateResult`. Constrained HSMM is experimental and must honor robust cycle bounds.

**Tech Stack:** Python 3.10+, pandas, NumPy, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-31-robust-anchored-phase-model-design.md`

## Global Constraints

- **Annual invariance is mandatory.** Changing only `phase_model` must not alter any existing `ANNUAL_COLUMNS` values or annual condition columns.
- **Do not promote** free `detector="semi_markov"` to default.
- **Do not overload** `monthly_condition` with phase labels.
- **Do not export** internal phase/HSMM helpers at package top level unless a later task explicitly expands the public surface (default: no).
- **No network I/O** in ordinary tests.
- Prefer `assign_monthly_phases(...)` as a pure function over burying phase logic inside trough opportunity scanners.
- v1 requires `detector="robust_extrema"` whenever `phase_model != "none"` (raise clear `ValueError` otherwise).
- Default remains `phase_model="none"` until a later explicit default-change decision.

---

## File map

- Create: `hydroseason/_phase.py` — rule-based + dispatch + schema helpers
- Create: `tests/test_phase.py` — unit/invariance/order/anchor tests
- Modify: `hydroseason/_dynamic_year.py` — add `phase_model` config field + validation
- Modify: `hydroseason/_semi_markov.py` — add constrained phase fit API (Task 5+)
- Modify: `hydroseason/hydrological_state.py` — wire phases into result
- Modify: `tests/test_dynamic_year.py` — config validation cases
- Modify: `tests/test_hydrological_state.py` — result surface + invariance
- Modify: `tests/test_package_surface.py` — keep internals unexported
- Modify: `docs/hydrological-state.md` — user docs
- Modify: `CHANGELOG.md` — Unreleased additive entry
- Optional later: notebook/SVG smoke for phase strip (non-blocking)

---

### Task 1: Config field + validation

**Files:**
- Modify: `hydroseason/_dynamic_year.py` (`DynamicHydroYearConfig`)
- Modify: `tests/test_dynamic_year.py`

**Interfaces:**
- Adds: `phase_model: Literal["none", "rule_based", "semi_markov"] = "none"`
- Validation:
  - unknown value → `ValueError` matching `phase_model`
  - `phase_model != "none"` and `detector != "robust_extrema"` → `ValueError` explaining robust anchoring requirement

- [ ] **Step 1: Write failing config tests**

```python
def test_phase_model_defaults_to_none():
    config = DynamicHydroYearConfig(expected_trough_month=9)
    assert config.phase_model == "none"


def test_phase_model_rejects_unknown_value():
    with pytest.raises(ValueError, match="phase_model"):
        DynamicHydroYearConfig(expected_trough_month=9, phase_model="kmeans")


def test_phase_model_requires_robust_detector():
    with pytest.raises(ValueError, match="robust_extrema"):
        DynamicHydroYearConfig(
            expected_trough_month=9,
            detector="semi_markov",
            phase_model="rule_based",
        )


def test_phase_model_accepts_rule_based_with_robust_detector():
    config = DynamicHydroYearConfig(
        expected_trough_month=9,
        detector="robust_extrema",
        phase_model="rule_based",
    )
    assert config.phase_model == "rule_based"
```

- [ ] **Step 2: Run tests — expect FAIL on missing attribute**

Run: `python -m pytest tests/test_dynamic_year.py::test_phase_model_defaults_to_none tests/test_dynamic_year.py::test_phase_model_rejects_unknown_value tests/test_dynamic_year.py::test_phase_model_requires_robust_detector tests/test_dynamic_year.py::test_phase_model_accepts_rule_based_with_robust_detector -q`

Expected: FAIL (`phase_model` missing / validation absent).

- [ ] **Step 3: Implement field + `__post_init__` checks**

```python
phase_model: Literal["none", "rule_based", "semi_markov"] = "none"

# in __post_init__:
if self.phase_model not in {"none", "rule_based", "semi_markov"}:
    raise ValueError("phase_model must be 'none', 'rule_based', or 'semi_markov'")
if self.phase_model != "none" and self.detector != "robust_extrema":
    raise ValueError(
        "phase_model requires detector='robust_extrema' "
        "(phases are anchored to robust trough/peak cycles)"
    )
```

- [ ] **Step 4: Re-run tests — expect PASS**

Run: same pytest command as Step 2  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_dynamic_year.py tests/test_dynamic_year.py
git commit -m "feat: add phase_model config axis for robust-anchored phases"
```

---

### Task 2: `monthly_phase` schema + disabled path

**Files:**
- Create: `hydroseason/_phase.py`
- Create: `tests/test_phase.py`

**Interfaces:**
- `PHASES = ("wet", "recession", "dry", "recovery")`
- `PHASE_COLUMNS = [...]` stable schema from spec §4.3
- `empty_monthly_phase(prepared: pd.DataFrame, *, method: str = "none") -> pd.DataFrame`
  - one row per prepared month
  - `phase="unspecified"`, `phase_status="disabled"`, `phase_method=method`
- `assign_monthly_phases(prepared, hydro_years, config, *, noise_pp: float | None = None) -> pd.DataFrame`
  - for now, if `phase_model=="none"` return disabled frame; else raise `NotImplementedError` for other models (filled in later tasks)

Match `monthly_condition` date convention (inspect `compute_monthly_surface_water_condition` output index/columns and mirror it).

- [ ] **Step 1: Write schema tests**

```python
def test_disabled_phase_frame_has_stable_schema_and_row_per_month():
    prepared = prepare_monthly_extent(_extent())
    out = empty_monthly_phase(prepared)
    assert list(out.columns) == PHASE_COLUMNS or set(PHASE_COLUMNS) <= set(out.columns)
    assert len(out) == len(prepared)
    assert (out["phase"] == "unspecified").all()
    assert (out["phase_status"] == "disabled").all()
    assert (out["phase_method"] == "none").all()


def test_assign_none_returns_disabled_frame():
    prepared = prepare_monthly_extent(_extent())
    years = detect_dynamic_hydrological_years(
        prepared.reset_index() if "extent_pct" in prepared else prepared,
        config=DynamicHydroYearConfig(expected_trough_month=9, phase_model="none"),
    )
    # use the same calling convention finalized in implementation
    out = assign_monthly_phases(
        prepared,
        years,
        DynamicHydroYearConfig(expected_trough_month=9, phase_model="none"),
    )
    assert (out["phase_status"] == "disabled").all()
```

- [ ] **Step 2: Run — expect FAIL missing module**

Run: `python -m pytest tests/test_phase.py -q`  
Expected: `ModuleNotFoundError` or collection failure.

- [ ] **Step 3: Implement `_phase.py` skeleton**

Include module docstring stating: phases are anchored to robust cycles; never rewrite annual boundaries.

- [ ] **Step 4: Tests PASS**

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_phase.py tests/test_phase.py
git commit -m "feat: add monthly_phase schema and disabled phase_model path"
```

---

### Task 3: Rule-based phase classifier

**Files:**
- Modify: `hydroseason/_phase.py`
- Modify: `tests/test_phase.py`

**Algorithm (from spec §5.1):**

For each `hydro_years` row with non-null `hy_start`, `hy_end`, `peak_month`, `trough_month`:

1. Select months in prepared frame with `hy_start <= date <= hy_end`.
2. Peak month → `wet` (if usable).
3. Trough month (`hy_end`) → `dry` (if usable).
4. Post-peak:
   - if `half_loss_month` valid: `(peak, half_loss]` → `recession`; `(half_loss, trough]` → `dry`
   - else split post-peak span at temporal midpoint.
5. Pre-peak:
   - `mid_level = (peak_extent_pct + previous_trough_extent) / 2`  
     previous trough extent = prepared extent at `hy_start - 1 month` (the starting trough).
   - from start forward: `recovery` until first usable month that is ≥ `mid_level - noise` and not before a forced rising-only prefix; then `wet` through peak.
6. Outside any such cycle → `unspecified` / `outside_cycle` or `unresolved_cycle`.
7. Unusable months inside cycle: keep positional phase, `phase_status="unusable"`, lower confidence.

Confidence heuristic from spec §5.1.

- [ ] **Step 1: Failing behavioral tests**

```python
def test_rule_based_labels_peak_wet_and_trough_dry():
    ...
    cfg = DynamicHydroYearConfig(expected_trough_month=9, phase_model="rule_based")
    years = detect_dynamic_hydrological_years(raw, config=cfg)
    prepared = prepare_monthly_extent(raw)
    phases = assign_monthly_phases(prepared, years, cfg)
    complete = years.loc[years["status"].eq("complete")].iloc[0]
    peak = complete["peak_month"]
    trough = complete["trough_month"]
    assert phases.loc[peak, "phase"] == "wet"
    assert phases.loc[trough, "phase"] == "dry"


def test_rule_based_follows_cyclic_order_inside_cycle():
    # ignore unusable; decode labels along time; assert each step is
    # same state or forward move in recovery→wet→recession→dry
    ...


def test_rule_based_marks_outside_cycle_months():
    ...


def test_rule_based_handles_missing_half_loss_with_midpoint_fallback():
    ...
```

Use existing monsoonal helpers from `tests/test_dynamic_year.py` / `tests/test_hydrological_state.py` rather than inventing fragile fixtures.

- [ ] **Step 2: Run — FAIL on NotImplementedError / wrong labels**

- [ ] **Step 3: Implement `assign_rule_based_phases(...)` and dispatch from `assign_monthly_phases`**

- [ ] **Step 4: Tests PASS**

- [ ] **Step 5: Commit**

```bash
git add hydroseason/_phase.py tests/test_phase.py
git commit -m "feat: rule-based monthly phases anchored to robust cycles"
```

---

### Task 4: Annual invariance + orchestrator wiring

**Files:**
- Modify: `hydroseason/hydrological_state.py`
- Modify: `tests/test_hydrological_state.py`
- Modify: `tests/test_phase.py`
- Modify: `tests/test_package_surface.py` if needed

**Wiring:**

```python
# analyze_hydrological_state
annual = detect_dynamic_hydrological_years(...)
...
monthly_phase = assign_monthly_phases(
    prepared,
    annual,
    selected,
    noise_pp=noise_pp,
)
return HydrologicalStateResult(
    pattern, selected, annual, monthly, monthly_phase, quality
)
```

Update `HydrologicalStateResult` dataclass field order carefully; fix all constructors/tests/fakes that build the result manually (`tests/test_build_multi_catchment_html.py`, report fakes, etc.).

- [ ] **Step 1: Write invariance tests**

```python
def test_phase_model_does_not_change_hydro_years():
    raw = _extent()
    base = DynamicHydroYearConfig(expected_trough_month=9, phase_model="none")
    phased = DynamicHydroYearConfig(expected_trough_month=9, phase_model="rule_based")
    a = detect_dynamic_hydrological_years(raw, config=base)
    b = detect_dynamic_hydrological_years(raw, config=phased)
    pd.testing.assert_frame_equal(a, b)


def test_analyze_attaches_monthly_phase_for_rule_based():
    result = analyze_hydrological_state(
        _extent(),
        config=DynamicHydroYearConfig(expected_trough_month=9, phase_model="rule_based"),
        n_bootstrap=40,
    )
    assert len(result.monthly_phase) == len(result.monthly_condition)
    assert set(result.monthly_phase["phase"].unique()) <= {
        "wet", "recession", "dry", "recovery", "unspecified"
    }


def test_analyze_phase_none_is_disabled_not_missing():
    result = analyze_hydrological_state(_extent(), n_bootstrap=40)
    assert (result.monthly_phase["phase_status"] == "disabled").all()
```

- [ ] **Step 2: Run — FAIL on result signature / equality**

- [ ] **Step 3: Implement wiring; repair all result fakes**

Search for `HydrologicalStateResult(` and positional constructions.

- [ ] **Step 4: Run focused + broader tests**

```bash
python -m pytest tests/test_phase.py tests/test_hydrological_state.py tests/test_dynamic_year.py tests/test_package_surface.py tests/test_build_multi_catchment_html.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hydroseason/hydrological_state.py hydroseason/_phase.py tests/
git commit -m "feat: attach monthly_phase on HydrologicalStateResult"
```

---

### Task 5: Constrained semi-Markov phase fit (experimental)

**Files:**
- Modify: `hydroseason/_semi_markov.py`
- Modify: `hydroseason/_phase.py`
- Modify: `tests/test_semi_markov.py`
- Modify: `tests/test_phase.py`

**API:**

```python
@dataclass(frozen=True)
class SemiMarkovPhaseResult:
    state_path: tuple[str, ...]
    state_posterior: np.ndarray  # (n_months, 4), aligned to frame index
    log_likelihood: float


def fit_semi_markov_phases(
    frame: pd.DataFrame,
    *,
    cycles: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]],
    # (hy_start, peak_month, hy_end/trough)
    config: SemiMarkovConfig = SemiMarkovConfig(),
) -> SemiMarkovPhaseResult:
    ...
```

**v1 algorithm (acceptable MVP):**

1. For each resolved cycle slice `frame.loc[start:end]`:
   - run existing emission + Viterbi on the slice (reuse internal helpers)
   - enforce anchors with cleanup:
     - force `end` → `dry` if usable
     - force `peak` → `wet` if usable
     - repair illegal adjacent pairs by projecting onto nearest legal cyclic step
2. Months outside cycles remain unlabeled (`unspecified`) at `_phase.py` layer.
3. Never return trough/peak boundary products from this function for annual use.

If cleanup becomes messy, upgrade to constrained DP in a follow-up commit inside this task before leaving experimental.

- [ ] **Step 1: Tests**

```python
def test_constrained_semi_markov_phases_honor_peak_and_trough_anchors():
    ...


def test_semi_markov_phase_model_dispatch():
    cfg = DynamicHydroYearConfig(
        expected_trough_month=9,
        phase_model="semi_markov",
    )
    ...
    assert phases["phase_method"].eq("semi_markov").all()
    # usable peak/trough anchors
    ...


def test_semi_markov_phase_model_does_not_change_annual_frame():
    ...  # same invariance as rule_based
```

- [ ] **Step 2: Implement fit + dispatch branch in `assign_monthly_phases`**

- [ ] **Step 3: pytest PASS for new tests; full phase suite PASS**

- [ ] **Step 4: Commit**

```bash
git add hydroseason/_semi_markov.py hydroseason/_phase.py tests/test_semi_markov.py tests/test_phase.py
git commit -m "feat: experimental constrained semi-Markov monthly phases"
```

---

### Task 6: Real-fixture regression guard

**Files:**
- Modify: `tests/test_phase.py` or add `tests/test_phase_regression.py`

Use frozen Fitzroy and/or Gilbert fixtures already in `tests/fixtures/`.

- [ ] **Step 1: For each fixture, assert**

```python
base = detect_dynamic_hydrological_years(monthly, config=replace(cfg, phase_model="none"))
for method in ("rule_based", "semi_markov"):
    phased_cfg = replace(cfg, detector="robust_extrema", phase_model=method)
    annual = detect_dynamic_hydrological_years(monthly, config=phased_cfg)
    pd.testing.assert_frame_equal(base, annual)
    prepared = prepare_monthly_extent(monthly, max_invalid_pct=cfg.max_invalid_pct)
    phases = assign_monthly_phases(prepared, annual, phased_cfg)
    assert len(phases) == len(prepared)
    # every complete cycle's usable peak/trough anchors hold
```

Keep runtime modest; no bootstrap-heavy work.

- [ ] **Step 2: Run**

```bash
python -m pytest tests/test_phase.py tests/test_fitzroy_regression.py tests/test_gilbert_regression.py -q
```

Expected: PASS (existing trough gates unchanged).

- [ ] **Step 3: Commit**

```bash
git add tests/test_phase.py tests/test_phase_regression.py
git commit -m "test: guard annual invariance with phase models on real fixtures"
```

---

### Task 7: Docs + changelog

**Files:**
- Modify: `docs/hydrological-state.md`
- Modify: `CHANGELOG.md`
- Optional note in transferable boundary design: phases are separate axis

**Docs content:**

- New section **Monthly hydrological phases**
- Example:

```python
config = DynamicHydroYearConfig(
    expected_trough_month=11,
    detector="robust_extrema",
    phase_model="rule_based",  # or "semi_markov" (experimental)
)
result = analyze_hydrological_state(monthly, config=config)
result.monthly_phase
```

- Clarify:
  - `monthly_condition` ≠ phase
  - free `detector="semi_markov"` still experimental boundary engine
  - `phase_model="semi_markov"` is constrained/experimental phase labelling
  - annual metrics unchanged by phase_model

- [ ] **Step 1: Edit docs + changelog**

- [ ] **Step 2: Build docs if docs extra available**

```bash
python -m mkdocs build --strict
```

If docs extra missing in env, skip with note; do not block.

- [ ] **Step 3: Commit**

```bash
git add docs/hydrological-state.md CHANGELOG.md docs/superpowers/specs/2026-07-31-robust-anchored-phase-model-design.md docs/superpowers/plans/2026-07-31-robust-anchored-phase-model.md
git commit -m "docs: document robust-anchored monthly phase models"
```

---

### Task 8: Final verification

- [ ] **Step 1: Full unit suite**

```bash
python -m pytest -q
```

Expected: all non-experimental tests PASS. Experimental marks may xfail as today.

- [ ] **Step 2: Manual smoke (optional)**

```python
from hydroseason import analyze_hydrological_state, DynamicHydroYearConfig
import pandas as pd
monthly = pd.read_csv("tests/fixtures/gilbert_river_monthly.csv", parse_dates=["date"]).set_index("date")
result = analyze_hydrological_state(
    monthly,
    config=DynamicHydroYearConfig(expected_trough_month=9, phase_model="rule_based"),
    n_bootstrap=20,
)
print(result.monthly_phase["phase"].value_counts())
print(result.hydro_years[["hy_year", "peak_month", "trough_month", "status"]].head())
```

- [ ] **Step 3: Stop for human review** before any default change of `phase_model` away from `"none"`.

---

## Out of scope / follow-ups

- Default `phase_model="rule_based"`
- Report HTML phase strip / Plotly layer
- True constrained-duration DP if MVP cleanup proves weak
- Bimodal secondary-phase decomposition
- Calibrated phase probabilities
- Using phases as inputs to condition baselines

## Success checklist

- [ ] `phase_model` config exists and defaults to `none`
- [ ] `rule_based` produces continuous monthly phases on resolved robust cycles
- [ ] peak→wet and trough→dry anchors hold when months usable
- [ ] cyclic order respected inside cycles
- [ ] annual frames identical across phase models
- [ ] `analyze_hydrological_state` returns `monthly_phase`
- [ ] constrained `semi_markov` phase path available + experimental
- [ ] docs and changelog updated
- [ ] free HSMM boundary detector still non-default and unpromoted
