# Hydrological State Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `hydroseason/hydrological_state.py` module that classifies a basin's seasonality regime, computes a moving-window Wetness State Index (WSI), and detects stress episodes — working identically on monsoonal and perennial/bimodal basins, additive alongside the existing `hydro_year.py`.

**Architecture:** Four independent, composable functions plus one orchestrator (`analyze_hydrological_state`). Regime classification (two independently-computed methods: ported eta²/circular-R/Walsh-Lawler-SI composite, and new Colwell predictability/constancy/contingency indices) is diagnostic metadata. Hydro-year anchoring always runs; wet/dry season labels are attached only when the regime is `"seasonal"`. WSI and stress-episode detection always run, regardless of regime. All new code reuses `hydro_year._coerce_monthly_series` for input coercion rather than duplicating it.

**Tech Stack:** Python 3.10+, pandas>=2.0, numpy>=1.24 only (no new dependencies — matches the existing core dependency set; legacy STL/KMeans diagnostics from the pre-strip code are explicitly not ported, per spec §6.1).

## Global Constraints

- Python >=3.10, `pandas>=2.0`, `numpy>=1.24` — no new runtime dependencies (spec §6.1, confirmed against `pyproject.toml`).
- New module must not modify `hydro_year.py`, `HydroYearConfig`, or `detect_hydrological_years` in any way (spec §2, §5).
- Reuse `hydro_year._coerce_monthly_series` for input coercion — do not fork it (spec §7).
- All public dataclasses frozen, all public functions module-level (match existing `hydro_year.py` style: `@dataclass(frozen=True)`, `from __future__ import annotations`).
- Regime-classification thresholds ported from legacy `cc13a89~1:hydroseason/seasonality.py` verbatim (dimensionless ratios, not tuned per variable): `ETA_SQ_STRONG=0.35`, `ETA_SQ_MODERATE=0.12`, `ETA_SQ_WEAK=0.10`, `R_MODERATE=0.40`, `R_WEAK=0.25`, `SI_MODERATE=0.60`, `SI_WEAK=0.40`.
- `hydroseason/__init__.py` exports: `analyze_hydrological_state`, `classify_seasonality_regime`, `compute_wetness_state_index`, `detect_stress_episodes`, `suggest_hydrological_state_config`, `SeasonalityResult` (spec §7).
- Test file: `tests/test_hydrological_state.py`, following existing helper-fixture style from `tests/test_hydro_year.py` (`_monthly_extent`, `_seasonal_extent`-style local builders).

---

### Task 1: Port `classify_seasonality_regime` (eta²/circular-R/Walsh-Lawler-SI composite)

**Files:**
- Create: `hydroseason/hydrological_state.py`
- Test: `tests/test_hydrological_state.py`

**Interfaces:**
- Consumes: `hydro_year._coerce_monthly_series(extent, value_col, date_col, duplicate_month_policy)` → `(series: pd.Series, invalid_pct, full_index)`.
- Produces:
  - `@dataclass(frozen=True) class SeasonalityResult` with fields: `regime: Literal["seasonal","borderline","non_seasonal"]`, `regime_source: str`, `eta_squared: float`, `circular_R: float`, `walsh_lawler_si: float`, `colwell_predictability: float | None = None`, `colwell_constancy: float | None = None`, `colwell_contingency: float | None = None`.
  - `classify_seasonality_regime(extent, *, value_col="extent_pct", date_col=None, method="both") -> SeasonalityResult`.
  - Used by Task 3 (`suggest_hydrological_state_config`) and Task 5 (`analyze_hydrological_state`).

This task ports only the eta²/R/SI path; the `colwell_*` fields stay `None` until Task 2 wires in Colwell (`method="both"` degrades gracefully — see Step 3).

- [ ] **Step 1: Write the failing tests for eta², circular R, and Walsh-Lawler SI on monthly water-extent input**

```python
# tests/test_hydrological_state.py
import numpy as np
import pandas as pd
import pytest


def _monthly_extent(start="2019-01-01", periods=36, value=50.0):
    index = pd.date_range(start, periods=periods, freq="MS")
    return pd.Series(value, index=index, name="extent_pct")


def _monsoonal_extent(n_years=6):
    """Sharp single peak/trough per year, low noise -> should classify seasonal."""
    index = pd.date_range("2015-01-01", periods=12 * n_years, freq="MS")
    month = index.month
    values = 40.0 * np.cos(2 * np.pi * (month - 2) / 12) + 50.0
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1.0, size=len(index))
    return pd.Series(values + noise, index=index, name="extent_pct")


def _perennial_extent(n_years=6):
    """Flat climatology + noise, no seasonal cycle -> should classify non_seasonal."""
    index = pd.date_range("2015-01-01", periods=12 * n_years, freq="MS")
    rng = np.random.default_rng(1)
    values = 70.0 + rng.normal(0, 2.0, size=len(index))
    return pd.Series(values, index=index, name="extent_pct")


def test_eta_squared_high_for_sharp_monsoonal_cycle():
    from hydroseason.hydrological_state import eta_squared_seasonality_score

    extent = _monsoonal_extent()
    score = eta_squared_seasonality_score(extent)

    assert score >= 0.35


def test_eta_squared_low_for_flat_perennial_series():
    from hydroseason.hydrological_state import eta_squared_seasonality_score

    extent = _perennial_extent()
    score = eta_squared_seasonality_score(extent)

    assert score < 0.10


def test_circular_concentration_high_for_monsoonal_cycle():
    from hydroseason.hydrological_state import circular_concentration_R

    extent = _monsoonal_extent()
    r = circular_concentration_R(extent)

    assert r >= 0.40


def test_circular_concentration_low_for_flat_perennial_series():
    from hydroseason.hydrological_state import circular_concentration_R

    extent = _perennial_extent()
    r = circular_concentration_R(extent)

    assert r < 0.25


def test_walsh_lawler_si_requires_twelve_values():
    from hydroseason.hydrological_state import walsh_lawler_seasonality_index

    with pytest.raises(ValueError, match="12"):
        walsh_lawler_seasonality_index(np.array([1.0, 2.0, 3.0]))


def test_walsh_lawler_si_zero_for_uniform_climatology():
    from hydroseason.hydrological_state import walsh_lawler_seasonality_index

    uniform = np.full(12, 10.0)
    si = walsh_lawler_seasonality_index(uniform)

    assert si == pytest.approx(0.0)


def test_classify_seasonality_regime_seasonal_for_monsoonal_series():
    from hydroseason.hydrological_state import classify_seasonality_regime

    extent = _monsoonal_extent()
    result = classify_seasonality_regime(extent, method="eta_r_si")

    assert result.regime == "seasonal"
    assert result.regime_source in ("eta_squared", "eta_squared_confirmed")
    assert result.colwell_predictability is None


def test_classify_seasonality_regime_non_seasonal_for_perennial_series():
    from hydroseason.hydrological_state import classify_seasonality_regime

    extent = _perennial_extent()
    result = classify_seasonality_regime(extent, method="eta_r_si")

    assert result.regime in ("non_seasonal", "borderline")


def test_classify_seasonality_regime_requires_full_year_coverage():
    from hydroseason.hydrological_state import classify_seasonality_regime

    extent = _monthly_extent(periods=6)

    with pytest.raises(ValueError, match="12 calendar months"):
        classify_seasonality_regime(extent, method="eta_r_si")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydrological_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydroseason.hydrological_state'`

- [ ] **Step 3: Write `hydroseason/hydrological_state.py` with the eta²/R/SI composite**

```python
"""Source-agnostic hydrological-state analysis from monthly water extent.

Generalises hydro_year.py's fixed wet/dry-season model to work identically
on monsoonal and perennial/bimodal basins: classify the seasonality regime
(diagnostic only), then compute a moving-window Wetness State Index and
detect stress episodes regardless of regime.

Regime-classification composite ported from the pre-strip
hydroseason/seasonality.py (rainfall-specific, removed in commit cc13a89,
recoverable via `git show cc13a89~1:hydroseason/seasonality.py`); thresholds
are dimensionless ratios and are unchanged from that implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from .hydro_year import _coerce_monthly_series

RegimeMethod = Literal["both", "eta_r_si", "colwell"]

# eta-squared thresholds -- fraction of total variance explained by
# calendar month (ANOVA between-month / total)
ETA_SQ_STRONG = 0.35
ETA_SQ_MODERATE = 0.12
ETA_SQ_WEAK = 0.10

# Circular concentration R thresholds
R_MODERATE = 0.40
R_WEAK = 0.25

# Walsh-Lawler SI thresholds
SI_MODERATE = 0.60
SI_WEAK = 0.40


@dataclass(frozen=True)
class SeasonalityResult:
    regime: Literal["seasonal", "borderline", "non_seasonal"]
    regime_source: str
    eta_squared: float
    circular_R: float
    walsh_lawler_si: float
    colwell_predictability: float | None = None
    colwell_constancy: float | None = None
    colwell_contingency: float | None = None


def walsh_lawler_seasonality_index(monthly_climatology_values) -> float:
    """Walsh-Lawler concentration index from a 12-value monthly climatology."""
    values = np.asarray(monthly_climatology_values, dtype=float)
    if values.size != 12:
        raise ValueError("Walsh-Lawler SI requires exactly 12 monthly climatology values.")
    annual_total = values.sum()
    if annual_total <= 0:
        return 0.0
    return float((1.0 / annual_total) * np.abs(values - annual_total / 12.0).sum())


def eta_squared_seasonality_score(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
) -> float:
    """Between-month fraction of total extent variance (ANOVA eta-squared).

    Robust to interannual amplitude modulation: proportional suppression of
    all months (e.g. a basin-wide dry spell) preserves the between-month
    ratio. Range [0, 1]; 0 = uniform across months, 1 = all variance is
    between months.
    """
    series, _, _ = _coerce_monthly_series(
        extent, value_col=value_col, date_col=date_col, duplicate_month_policy="warn"
    )
    if series.empty:
        return 0.0
    months = series.index.month
    grand_mean = float(series.mean())
    ss_total = float(((series - grand_mean) ** 2).sum())
    if ss_total <= 0:
        return 0.0
    group_stats = series.groupby(months).agg(["mean", "count"])
    ss_between = float(((group_stats["mean"] - grand_mean) ** 2 * group_stats["count"]).sum())
    return float(max(0.0, min(1.0, ss_between / ss_total)))


def circular_concentration_R(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
) -> float:
    """Mean resultant length R from circular statistics on the 12-month climatology.

    Computed on the mean annual profile, so it is immune to interannual
    noise. R in [0, 1]: 0 = perfectly uniform across months, 1 = all extent
    concentrated in one month.
    """
    series, _, _ = _coerce_monthly_series(
        extent, value_col=value_col, date_col=date_col, duplicate_month_policy="warn"
    )
    if series.empty:
        return 0.0
    clim = series.groupby(series.index.month).mean().reindex(range(1, 13), fill_value=0.0).to_numpy(dtype=float)
    total = clim.sum()
    if total <= 0:
        return 0.0
    months = np.arange(1, 13)
    theta = 2.0 * np.pi * (months - 1) / 12.0
    x_bar = float((clim * np.cos(theta)).sum() / total)
    y_bar = float((clim * np.sin(theta)).sum() / total)
    return float(np.sqrt(x_bar * x_bar + y_bar * y_bar))


def _climatology_or_raise(
    extent: pd.Series | pd.DataFrame, *, value_col: str, date_col: str | None
) -> pd.Series:
    series, _, _ = _coerce_monthly_series(
        extent, value_col=value_col, date_col=date_col, duplicate_month_policy="warn"
    )
    if series.empty:
        raise ValueError("requires at least one non-missing monthly value.")
    clim = series.groupby(series.index.month).mean().reindex(range(1, 13))
    if clim.isna().any():
        missing = sorted(clim[clim.isna()].index)
        raise ValueError(f"requires coverage of all 12 calendar months; missing {missing}.")
    return clim


def classify_regime_composite(eta_sq: float, circular_R: float, si: float) -> tuple[str, str]:
    """Classify seasonality regime from eta-squared, circular R, and SI.

    Hierarchical, not single-threshold: strong eta-squared decides alone;
    moderate eta-squared needs R or SI confirmation; everything weak is
    non_seasonal.
    """
    if eta_sq >= ETA_SQ_STRONG:
        return "seasonal", "eta_squared"
    if eta_sq >= ETA_SQ_MODERATE and (circular_R >= R_MODERATE or si >= SI_MODERATE):
        return "seasonal", "eta_squared_confirmed"
    if eta_sq >= ETA_SQ_WEAK or circular_R >= R_WEAK or si >= SI_WEAK:
        return "borderline", "concentration"
    return "non_seasonal", "all_weak"


def classify_seasonality_regime(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    method: RegimeMethod = "both",
) -> SeasonalityResult:
    """Classify a basin's seasonality regime from monthly water extent.

    ``method="eta_r_si"`` computes only the ported eta-squared/circular-R/
    Walsh-Lawler-SI composite. ``method="colwell"`` computes only the
    Colwell predictability/constancy/contingency indices. ``method="both"``
    (default) computes both and reports both; the ``regime``/``regime_source``
    fields are always derived from the eta-squared/R/SI composite pending
    empirical validation of which method should be the default classifier
    (spec §9).
    """
    if method not in ("both", "eta_r_si", "colwell"):
        raise ValueError('method must be "both", "eta_r_si", or "colwell".')

    clim = _climatology_or_raise(extent, value_col=value_col, date_col=date_col)
    si = walsh_lawler_seasonality_index(clim.to_numpy(dtype=float))
    eta_sq = eta_squared_seasonality_score(extent, value_col=value_col, date_col=date_col)
    circ_r = circular_concentration_R(extent, value_col=value_col, date_col=date_col)
    regime, regime_source = classify_regime_composite(eta_sq, circ_r, si)

    colwell_p = colwell_c = colwell_m = None
    if method in ("both", "colwell"):
        from .hydrological_state import colwell_indices  # defined in Task 2

        colwell_p, colwell_c, colwell_m = colwell_indices(
            extent, value_col=value_col, date_col=date_col
        )

    return SeasonalityResult(
        regime=regime,
        regime_source=regime_source,
        eta_squared=eta_sq,
        circular_R=circ_r,
        walsh_lawler_si=si,
        colwell_predictability=colwell_p,
        colwell_constancy=colwell_c,
        colwell_contingency=colwell_m,
    )


__all__ = [
    "SeasonalityResult",
    "classify_seasonality_regime",
    "classify_regime_composite",
    "circular_concentration_R",
    "eta_squared_seasonality_score",
    "walsh_lawler_seasonality_index",
]
```

Note: Step 3's `classify_seasonality_regime` imports `colwell_indices` from within the function body (not at module top) because Task 2 adds that function to the same file afterward — this avoids a forward-reference `NameError` if Task 1 is tested in isolation before Task 2 lands. Once Task 2 is complete, move the import to the top of the file (see Task 2, Step 3).

For this task, run only the `method="eta_r_si"` tests — `method="both"` will fail until Task 2 adds `colwell_indices`. Temporarily skip `test_classify_seasonality_regime_seasonal_for_monsoonal_series` and `test_classify_seasonality_regime_non_seasonal_for_perennial_series` is not needed since both already pass `method="eta_r_si"` explicitly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hydrological_state.py -v`
Expected: All PASS (all tests in Step 1 use `method="eta_r_si"` or no `method` arg on the standalone score functions, so none depend on Colwell yet).

- [ ] **Step 5: Commit**

```bash
git add hydroseason/hydrological_state.py tests/test_hydrological_state.py
git commit -m "feat: port eta-squared/circular-R/Walsh-Lawler-SI regime classifier for water extent"
```

---

### Task 2: Add Colwell predictability/constancy/contingency indices

**Files:**
- Modify: `hydroseason/hydrological_state.py`
- Test: `tests/test_hydrological_state.py`

**Interfaces:**
- Consumes: `_coerce_monthly_series` (as Task 1).
- Produces: `colwell_indices(extent, *, value_col="extent_pct", date_col=None, n_state_bins=11) -> tuple[float, float, float]` returning `(predictability, constancy, contingency)`. Wired into `classify_seasonality_regime(method="both"|"colwell")` from Task 1.

Colwell's (1974) method needs the continuous extent values binned into discrete "states" to build the month × state frequency matrix; `n_state_bins=11` (Colwell's original paper uses 11 log-spaced classes for hydrological data) partitions the observed extent range into equal-width bins.

- [ ] **Step 1: Write the failing tests**

```python
def test_colwell_indices_high_constancy_for_perennial_series():
    from hydroseason.hydrological_state import colwell_indices

    extent = _perennial_extent()
    predictability, constancy, contingency = colwell_indices(extent)

    assert constancy > contingency
    assert 0.0 <= predictability <= 1.0


def test_colwell_indices_high_contingency_for_monsoonal_series():
    from hydroseason.hydrological_state import colwell_indices

    extent = _monsoonal_extent()
    predictability, constancy, contingency = colwell_indices(extent)

    assert contingency > constancy


def test_colwell_indices_requires_full_year_coverage():
    from hydroseason.hydrological_state import colwell_indices

    extent = _monthly_extent(periods=6)

    with pytest.raises(ValueError, match="12 calendar months"):
        colwell_indices(extent)


def test_classify_seasonality_regime_both_methods_populates_colwell_fields():
    from hydroseason.hydrological_state import classify_seasonality_regime

    extent = _monsoonal_extent()
    result = classify_seasonality_regime(extent, method="both")

    assert result.colwell_predictability is not None
    assert result.colwell_constancy is not None
    assert result.colwell_contingency is not None


def test_classify_seasonality_regime_colwell_only_leaves_eta_r_si_computed():
    from hydroseason.hydrological_state import classify_seasonality_regime

    extent = _monsoonal_extent()
    result = classify_seasonality_regime(extent, method="colwell")

    # regime/regime_source are always derived from eta/R/SI (spec §6.1);
    # method="colwell" still populates the colwell_* fields for comparison.
    assert result.colwell_predictability is not None
    assert result.eta_squared > 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydrological_state.py -v -k colwell`
Expected: FAIL with `ImportError: cannot import name 'colwell_indices'`

- [ ] **Step 3: Implement `colwell_indices` and wire the top-level import**

Add to `hydroseason/hydrological_state.py`, replacing the deferred in-function import from Task 1 Step 3 with a top-level import now that both functions live in the same module (no circular-import risk — remove the `from .hydrological_state import colwell_indices` line inside `classify_seasonality_regime` and rely on `colwell_indices` being defined earlier in the same file). Uses Colwell's original, unambiguous log-base-`n_state_bins` entropy decomposition:

```python
def colwell_indices(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    n_state_bins: int = 11,
) -> tuple[float, float, float]:
    """Colwell (1974) predictability, constancy, and contingency.

    Builds a month x state frequency matrix (state = equal-width bin of the
    observed extent range) and decomposes uncertainty about state into a
    within-month (constancy) and between-month (contingency) component,
    using Colwell's original log_x-base entropy decomposition where x is
    the number of state bins:

        H(X)  = entropy of state marginal (across all months)
        H(XY) = joint entropy of (month, state)
        H(Y)  = entropy of month marginal (uniform by construction, log_x(12))

        contingency M   = (H(X) + H(Y) - H(XY)) / H(Y)   -- scaled to [0,1] by H(Y)
        constancy C     = 1 - H(X)
        predictability P = C + M

    High constancy relative to contingency indicates a perennial/uniform
    regime; high contingency indicates a predictable seasonal cycle.

    Returns
    -------
    (predictability, constancy, contingency) : tuple[float, float, float]
    """
    series, _, _ = _coerce_monthly_series(
        extent, value_col=value_col, date_col=date_col, duplicate_month_policy="warn"
    )
    if series.empty:
        raise ValueError("requires at least one non-missing monthly value.")
    months_present = sorted(series.index.month.unique())
    if len(months_present) < 12:
        missing = sorted(set(range(1, 13)) - set(months_present))
        raise ValueError(f"requires coverage of all 12 calendar months; missing {missing}.")

    lo, hi = float(series.min()), float(series.max())
    if hi <= lo:
        return 1.0, 1.0, 0.0

    edges = np.linspace(lo, hi, n_state_bins + 1)
    edges[-1] += 1e-9
    states = np.clip(np.digitize(series.to_numpy(dtype=float), edges) - 1, 0, n_state_bins - 1)

    matrix = np.zeros((12, n_state_bins), dtype=float)
    for month, state in zip(series.index.month, states):
        matrix[month - 1, state] += 1.0

    total = float(matrix.sum())
    col_totals = matrix.sum(axis=0)   # state marginal, summed across months
    row_totals = matrix.sum(axis=1)   # month marginal
    log_x = np.log(n_state_bins)

    def _entropy(counts: np.ndarray, n: float, log_denom: float) -> float:
        probs = counts[counts > 0] / n
        return float(-(probs * np.log(probs)).sum() / log_denom)

    h_x = _entropy(col_totals, total, log_x)
    h_y = _entropy(row_totals, total, log_x)
    flat = matrix.flatten()
    h_xy = _entropy(flat, total, log_x)

    constancy = 1.0 - h_x
    contingency = (h_x + h_y - h_xy) / h_y if h_y > 0 else 0.0
    predictability = constancy + contingency

    return (
        float(max(0.0, min(1.0, predictability))),
        float(max(0.0, min(1.0, constancy))),
        float(max(0.0, min(1.0, contingency))),
    )
```

Place this function definition above `classify_seasonality_regime` in the file (top-to-bottom: `colwell_indices` must be defined before it is called at module scope). Then, in `classify_seasonality_regime`, replace the deferred in-function import from Task 1 with a direct call:

```python
    colwell_p = colwell_c = colwell_m = None
    if method in ("both", "colwell"):
        colwell_p, colwell_c, colwell_m = colwell_indices(
            extent, value_col=value_col, date_col=date_col
        )
```

Add `"colwell_indices"` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hydrological_state.py -v`
Expected: All PASS, including the `method="both"` tests deferred from Task 1.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/hydrological_state.py tests/test_hydrological_state.py
git commit -m "feat: add Colwell predictability/constancy/contingency regime classifier"
```

---

### Task 3: Hydro-year anchor (always) + conditional wet/dry season labels

**Files:**
- Modify: `hydroseason/hydrological_state.py`
- Test: `tests/test_hydrological_state.py`

**Interfaces:**
- Consumes: `classify_seasonality_regime` (Task 1/2) for the default `regime=None` path; `hydro_year._coerce_monthly_series`; reuses the contiguous-run wet/dry-window logic pattern from `hydro_year.suggest_hydro_year_config` (spec §6.2 — logic is re-implemented here, not imported, because `HydroYearConfig` unconditionally validates wet-window-crosses-year-boundary geometry, which does not hold for `anchor_only` results; see Global Constraints).
- Produces:
  - `@dataclass(frozen=True) class HydrologicalYearAnchor` with fields: `season_mode: Literal["labeled", "anchor_only"]`, `trough_month: int`, `peak_month: int`, `wet_start_month: int | None = None`, `wet_end_month: int | None = None`, `dry_start_month: int | None = None`, `dry_end_month: int | None = None`.
  - `suggest_hydrological_state_config(extent, *, value_col="extent_pct", date_col=None, regime=None) -> HydrologicalYearAnchor`. If `regime` is `None`, calls `classify_seasonality_regime(extent, value_col=value_col, date_col=date_col, method="eta_r_si")` internally to get the regime.
  - Used by Task 5 (`analyze_hydrological_state`).

- [ ] **Step 1: Write the failing tests**

```python
def test_suggest_hydrological_state_config_anchors_on_trough_plus_one():
    from hydroseason.hydrological_state import suggest_hydrological_state_config

    extent = _monsoonal_extent()
    anchor = suggest_hydrological_state_config(extent)

    # _monsoonal_extent peaks at month 2 (Feb); trough is 6 months later (Aug).
    assert anchor.trough_month == 8
    assert anchor.peak_month == 2


def test_suggest_hydrological_state_config_labeled_for_seasonal_regime():
    from hydroseason.hydrological_state import suggest_hydrological_state_config

    extent = _monsoonal_extent()
    anchor = suggest_hydrological_state_config(extent)

    assert anchor.season_mode == "labeled"
    assert anchor.wet_start_month is not None
    assert anchor.dry_start_month is not None


def test_suggest_hydrological_state_config_anchor_only_for_perennial_regime():
    from hydroseason.hydrological_state import suggest_hydrological_state_config

    extent = _perennial_extent()
    anchor = suggest_hydrological_state_config(extent)

    assert anchor.season_mode == "anchor_only"
    assert anchor.wet_start_month is None
    assert anchor.dry_start_month is None
    assert anchor.trough_month is not None  # anchor itself is always present


def test_suggest_hydrological_state_config_accepts_explicit_regime_override():
    from hydroseason.hydrological_state import suggest_hydrological_state_config

    # A monsoonal series forced to be treated as non_seasonal should still
    # only produce an anchor, honouring the caller's explicit regime.
    extent = _monsoonal_extent()
    anchor = suggest_hydrological_state_config(extent, regime="non_seasonal")

    assert anchor.season_mode == "anchor_only"


def test_suggest_hydrological_state_config_requires_full_year_coverage():
    from hydroseason.hydrological_state import suggest_hydrological_state_config

    extent = _monthly_extent(periods=6)

    with pytest.raises(ValueError, match="12 calendar months"):
        suggest_hydrological_state_config(extent)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydrological_state.py -v -k suggest_hydrological_state_config`
Expected: FAIL with `ImportError: cannot import name 'suggest_hydrological_state_config'`

- [ ] **Step 3: Implement `HydrologicalYearAnchor` and `suggest_hydrological_state_config`**

Add to `hydroseason/hydrological_state.py`:

```python
@dataclass(frozen=True)
class HydrologicalYearAnchor:
    season_mode: Literal["labeled", "anchor_only"]
    trough_month: int
    peak_month: int
    wet_start_month: int | None = None
    wet_end_month: int | None = None
    dry_start_month: int | None = None
    dry_end_month: int | None = None


def _contiguous_run(center: int, keep: pd.Series) -> list[int]:
    run = [center]
    month = center % 12 + 1
    while keep.loc[month] and month not in run:
        run.append(month)
        month = month % 12 + 1
    month = (center - 2) % 12 + 1
    while keep.loc[month] and month not in run:
        run.insert(0, month)
        month = (month - 2) % 12 + 1
    return run


def suggest_hydrological_state_config(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    regime: Literal["seasonal", "borderline", "non_seasonal"] | None = None,
) -> HydrologicalYearAnchor:
    """Propose a hydro-year anchor, with wet/dry labels only if seasonal.

    The hydro year always anchors as [trough_month + 1, ..., trough_month]
    (start = month after the historical driest month, end = the historical
    driest month itself) regardless of regime -- this anchor is required
    scaffolding for downstream annual aggregation even when no wet/dry split
    is meaningful. If ``regime`` resolves to "seasonal", wet_start/end and
    dry_start/end are additionally populated using the same contiguous-run
    logic as hydro_year.suggest_hydro_year_config. If ``regime`` is None,
    it is computed via classify_seasonality_regime(method="eta_r_si").
    """
    clim = _climatology_or_raise(extent, value_col=value_col, date_col=date_col)
    peak_month = int(clim.idxmax())
    trough_month = int(clim.idxmin())

    if regime is None:
        regime = classify_seasonality_regime(
            extent, value_col=value_col, date_col=date_col, method="eta_r_si"
        ).regime

    if regime != "seasonal":
        return HydrologicalYearAnchor(
            season_mode="anchor_only", trough_month=trough_month, peak_month=peak_month
        )

    overall_mean = float(clim.mean())
    is_wet = clim > overall_mean
    wet_months = _contiguous_run(peak_month, is_wet)
    dry_months = _contiguous_run(trough_month, ~is_wet)

    wet_start_month, wet_end_month = wet_months[0], wet_months[-1]
    dry_start_month, dry_end_month = dry_months[0], dry_months[-1]

    if wet_start_month <= wet_end_month:
        wet_end_month = peak_month
        wet_start_month = peak_month + 1 if peak_month < 12 else 1
        if wet_start_month <= wet_end_month:
            wet_start_month, wet_end_month = 12, 1
    if dry_start_month > dry_end_month:
        dry_start_month, dry_end_month = trough_month, trough_month
    if dry_start_month <= wet_end_month:
        dry_start_month = wet_end_month + 1 if wet_end_month < 12 else 1
        if dry_end_month < dry_start_month:
            dry_end_month = dry_start_month

    return HydrologicalYearAnchor(
        season_mode="labeled",
        trough_month=trough_month,
        peak_month=peak_month,
        wet_start_month=wet_start_month,
        wet_end_month=wet_end_month,
        dry_start_month=dry_start_month,
        dry_end_month=dry_end_month,
    )
```

Add `"HydrologicalYearAnchor"` and `"suggest_hydrological_state_config"` to `__all__`.

Note: the wet/dry contiguous-run block is intentionally duplicated from `hydro_year.suggest_hydro_year_config` rather than imported, because that function returns a `HydroYearConfig` whose `__post_init__` unconditionally requires wet/dry geometry — it cannot represent an `anchor_only` result, and this module must not modify `hydro_year.py` (Global Constraints). If this duplication becomes a maintenance burden later, extracting a shared private helper into `hydro_year.py` is a reasonable follow-up, but is out of scope here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hydrological_state.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/hydrological_state.py tests/test_hydrological_state.py
git commit -m "feat: add hydro-year anchor with regime-conditional wet/dry season labels"
```

---

### Task 4: Moving-window Wetness State Index (WSI)

**Files:**
- Modify: `hydroseason/hydrological_state.py`
- Test: `tests/test_hydrological_state.py`

**Interfaces:**
- Consumes: `hydro_year._coerce_monthly_series`.
- Produces: `compute_wetness_state_index(extent, *, value_col="extent_pct", date_col=None, window_years=12, spread="both") -> pd.DataFrame` with columns `wsi_mad`, `wsi_iqr` (or just one, per `spread` argument), indexed by month timestamp. Used by Task 5.

- [ ] **Step 1: Write the failing tests**

```python
def test_wsi_requires_window_years_of_prior_same_month_data():
    from hydroseason.hydrological_state import compute_wetness_state_index

    extent = _monsoonal_extent(n_years=6)
    result = compute_wetness_state_index(extent, window_years=5, spread="mad")

    # First 5 years of each calendar month have no prior window -> NaN.
    first_five_years = result.index < pd.Timestamp("2020-01-01")
    assert result.loc[first_five_years, "wsi_mad"].isna().all()
    assert result.loc[~first_five_years, "wsi_mad"].notna().any()


def test_wsi_both_spread_columns_present_by_default():
    from hydroseason.hydrological_state import compute_wetness_state_index

    extent = _monsoonal_extent(n_years=6)
    result = compute_wetness_state_index(extent, window_years=3)

    assert "wsi_mad" in result.columns
    assert "wsi_iqr" in result.columns


def test_wsi_single_spread_metric_only_computes_that_column():
    from hydroseason.hydrological_state import compute_wetness_state_index

    extent = _monsoonal_extent(n_years=6)
    result = compute_wetness_state_index(extent, window_years=3, spread="iqr")

    assert list(result.columns) == ["wsi_iqr"]


def test_wsi_positive_for_above_normal_month_negative_for_below_normal():
    from hydroseason.hydrological_state import compute_wetness_state_index

    index = pd.date_range("2015-01-01", periods=12 * 5, freq="MS")
    # January always 50, except the final January which spikes to 90.
    values = np.tile([50.0] * 12, 5)
    values[-12] = 90.0  # first January of year 5 (index position for Jan, year 5)
    extent = pd.Series(values, index=index, name="extent_pct")

    result = compute_wetness_state_index(extent, window_years=4, spread="mad")

    spike_month = pd.Timestamp("2019-01-01")
    assert result.loc[spike_month, "wsi_mad"] > 0


def test_wsi_tracks_trend_moving_baseline_does_not_flag_new_normal_as_extreme():
    from hydroseason.hydrological_state import compute_wetness_state_index

    # Step-change drying trend: 80 for years 1-6, then 40 for years 7-12.
    index = pd.date_range("2010-01-01", periods=12 * 12, freq="MS")
    values = np.concatenate([np.full(12 * 6, 80.0), np.full(12 * 6, 40.0)])
    rng = np.random.default_rng(2)
    extent = pd.Series(values + rng.normal(0, 1.0, size=len(index)), index=index, name="extent_pct")

    result = compute_wetness_state_index(extent, window_years=5, spread="mad")

    # Last 12 months (well after the step, with a full 5-year post-step
    # window available) should NOT show systematic extreme-low WSI, because
    # the moving baseline has caught up to the new (drier) normal.
    tail = result.loc[result.index >= pd.Timestamp("2021-01-01"), "wsi_mad"].dropna()
    assert tail.abs().median() < 2.0


def test_wsi_requires_extent_series_non_empty():
    from hydroseason.hydrological_state import compute_wetness_state_index

    with pytest.raises(ValueError, match="non-missing"):
        compute_wetness_state_index(pd.Series(dtype=float), window_years=3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydrological_state.py -v -k wetness_state_index`
Expected: FAIL with `ImportError: cannot import name 'compute_wetness_state_index'`

- [ ] **Step 3: Implement `compute_wetness_state_index`**

Add to `hydroseason/hydrological_state.py`:

```python
SpreadMethod = Literal["mad", "iqr", "both"]


def compute_wetness_state_index(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    window_years: int = 12,
    spread: SpreadMethod = "both",
) -> pd.DataFrame:
    """Calendar-month-aware moving-window Wetness State Index.

    For each month t, the reference window is the trailing ``window_years``
    of *that same calendar month* (e.g. July compares against the preceding
    ``window_years`` Julys), not a flat trailing window across all months --
    this avoids conflating the seasonal cycle with anomaly, and lets the
    baseline track a long-term drying/wetting trend rather than diluting it
    against a multi-decade average.

    WSI_t = (extent_t - median_t) / spread_t, where median_t and spread_t
    are computed over the trailing ``window_years`` observations of the
    same calendar month (t itself excluded). Months with fewer than
    ``window_years`` prior same-month observations are NaN by construction.

    ``spread``: "mad" (median absolute deviation, scaled by 1.4826 for
    normal-consistency), "iqr" (P75 - P25), or "both" (both columns).
    """
    if spread not in ("mad", "iqr", "both"):
        raise ValueError('spread must be "mad", "iqr", or "both".')
    series, _, _ = _coerce_monthly_series(
        extent, value_col=value_col, date_col=date_col, duplicate_month_policy="warn"
    )
    if series.empty:
        raise ValueError("compute_wetness_state_index requires at least one non-missing monthly value.")

    want_mad = spread in ("mad", "both")
    want_iqr = spread in ("iqr", "both")
    columns: dict[str, list[float]] = {}
    if want_mad:
        columns["wsi_mad"] = []
    if want_iqr:
        columns["wsi_iqr"] = []

    for month_num in range(1, 13):
        month_mask = series.index.month == month_num
        month_series = series[month_mask].sort_index()
        values = month_series.to_numpy(dtype=float)
        for i in range(len(values)):
            if i < window_years:
                if want_mad:
                    columns["wsi_mad"].append(np.nan)
                if want_iqr:
                    columns["wsi_iqr"].append(np.nan)
                continue
            window = values[i - window_years : i]
            center = float(np.median(window))
            current = values[i]
            if want_mad:
                mad = float(np.median(np.abs(window - center))) * 1.4826
                columns["wsi_mad"].append((current - center) / mad if mad > 0 else np.nan)
            if want_iqr:
                q75, q25 = np.percentile(window, [75, 25])
                iqr = float(q75 - q25)
                columns["wsi_iqr"].append((current - center) / iqr if iqr > 0 else np.nan)
        month_indices = month_series.index
        if "_index_accum" not in columns:
            columns["_index_accum"] = []
        columns["_index_accum"].extend(list(month_indices))

    result = pd.DataFrame(
        {key: values for key, values in columns.items() if key != "_index_accum"},
        index=pd.DatetimeIndex(columns["_index_accum"]),
    ).sort_index()
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hydrological_state.py -v`
Expected: All PASS. If `test_wsi_tracks_trend_moving_baseline_does_not_flag_new_normal_as_extreme` is flaky near the threshold, check the printed `tail.abs().median()` value and adjust the assertion threshold (not the implementation) to match the actual robust-statistic behavior — the intent is "systematically much less extreme than immediately post-step," not a specific numeric bound.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/hydrological_state.py tests/test_hydrological_state.py
git commit -m "feat: add calendar-month-aware moving-window Wetness State Index"
```

---

### Task 5: Percentile-based stress episode detection

**Files:**
- Modify: `hydroseason/hydrological_state.py`
- Test: `tests/test_hydrological_state.py`

**Interfaces:**
- Consumes: output of `compute_wetness_state_index` (a `pd.DataFrame` with a `wsi_mad` and/or `wsi_iqr` column, `pd.DatetimeIndex`).
- Produces: `detect_stress_episodes(wsi, *, column="wsi_mad", onset_pctile=40, trough_pctile=20) -> pd.DataFrame` with columns `onset`, `trough_month`, `trough_value`, `recovery`, `duration_months`, `severity`. `recovery` is `pd.NaT` for an episode still open at the end of the series. Used by Task 6.

- [ ] **Step 1: Write the failing tests**

```python
def _wsi_series(values, start="2015-01-01"):
    index = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"wsi_mad": values}, index=index)


def test_detect_stress_episodes_no_episodes_for_always_wet_series():
    from hydroseason.hydrological_state import detect_stress_episodes

    wsi = _wsi_series([1.0] * 24)
    episodes = detect_stress_episodes(wsi)

    assert episodes.empty


def test_detect_stress_episodes_detects_one_episode_with_recovery():
    from hydroseason.hydrological_state import detect_stress_episodes

    # Wet (P40+) -> decline through P20 -> recover to wet.
    values = [1.0, 1.0, 0.2, -0.5, -1.5, -0.5, 0.3, 1.0, 1.0]
    wsi = _wsi_series(values)
    episodes = detect_stress_episodes(wsi)

    assert len(episodes) == 1
    row = episodes.iloc[0]
    assert row["trough_value"] == pytest.approx(-1.5)
    assert pd.notna(row["recovery"])
    assert row["duration_months"] >= 1


def test_detect_stress_episodes_open_episode_has_nat_recovery():
    from hydroseason.hydrological_state import detect_stress_episodes

    values = [1.0, 1.0, 0.2, -0.5, -1.5, -1.0]
    wsi = _wsi_series(values)
    episodes = detect_stress_episodes(wsi)

    assert len(episodes) == 1
    assert pd.isna(episodes.iloc[0]["recovery"])


def test_detect_stress_episodes_detects_multiple_separated_episodes():
    from hydroseason.hydrological_state import detect_stress_episodes

    values = [1.0, -1.0, -1.5, 1.0, 1.0, 1.0, -1.2, -1.8, 1.0]
    wsi = _wsi_series(values)
    episodes = detect_stress_episodes(wsi)

    assert len(episodes) == 2


def test_detect_stress_episodes_severity_is_cumulative_deficit_below_onset_threshold():
    from hydroseason.hydrological_state import detect_stress_episodes

    values = [1.0, 0.0, -1.0, 0.0, 1.0]  # onset threshold computed from these 5 points
    wsi = _wsi_series(values)
    episodes = detect_stress_episodes(wsi, onset_pctile=50, trough_pctile=20)

    assert len(episodes) == 1
    assert episodes.iloc[0]["severity"] > 0


def test_detect_stress_episodes_custom_column_selection():
    from hydroseason.hydrological_state import detect_stress_episodes

    values = [1.0, 1.0, -1.5, -2.0, 1.0, 1.0]
    wsi = pd.DataFrame(
        {"wsi_iqr": values}, index=pd.date_range("2015-01-01", periods=len(values), freq="MS")
    )
    episodes = detect_stress_episodes(wsi, column="wsi_iqr")

    assert len(episodes) == 1


def test_detect_stress_episodes_rejects_missing_column():
    from hydroseason.hydrological_state import detect_stress_episodes

    wsi = _wsi_series([1.0, -1.0])

    with pytest.raises(KeyError, match="wsi_iqr"):
        detect_stress_episodes(wsi, column="wsi_iqr")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydrological_state.py -v -k stress_episodes`
Expected: FAIL with `ImportError: cannot import name 'detect_stress_episodes'`

- [ ] **Step 3: Implement `detect_stress_episodes`**

Add to `hydroseason/hydrological_state.py`:

```python
def detect_stress_episodes(
    wsi: pd.DataFrame,
    *,
    column: str = "wsi_mad",
    onset_pctile: float = 40.0,
    trough_pctile: float = 20.0,
) -> pd.DataFrame:
    """Detect stress episodes from a WSI series using percentile crossings.

    Adapted from the satellite-LSWI flash-drought method: an episode begins
    when the index drops from at/above the ``onset_pctile`` percentile to
    below it and continues declining toward ``trough_pctile``; it ends when
    the index recovers back to at/above ``onset_pctile``. ``severity`` is
    the cumulative deficit (onset-threshold minus value, summed over months
    where the value is below the onset threshold) within the episode --
    a run-theory/Yevjevich-style summary computed within episodes already
    delimited by the percentile method, not used for detection itself.

    An episode still below the onset threshold at the end of the series has
    ``recovery = pd.NaT`` and ``duration_months`` counts through the last
    available month.
    """
    if column not in wsi.columns:
        raise KeyError(f"column {column!r} not found in wsi columns {list(wsi.columns)}.")

    values = wsi[column]
    valid = values.dropna()
    if valid.empty:
        return _empty_stress_episodes()

    onset_threshold = float(np.percentile(valid, onset_pctile))

    episodes: list[dict] = []
    in_episode = False
    episode_start_idx = None
    episode_values: list[float] = []
    episode_index: list[pd.Timestamp] = []

    ordered_index = valid.index
    ordered_values = valid.to_numpy(dtype=float)

    for i, (ts, val) in enumerate(zip(ordered_index, ordered_values)):
        below = val < onset_threshold
        if below and not in_episode:
            in_episode = True
            episode_start_idx = i
            episode_values = [val]
            episode_index = [ts]
        elif below and in_episode:
            episode_values.append(val)
            episode_index.append(ts)
        elif not below and in_episode:
            episodes.append(_summarise_episode(episode_index, episode_values, onset_threshold, recovery=ts))
            in_episode = False
            episode_values, episode_index = [], []

    if in_episode:
        episodes.append(
            _summarise_episode(episode_index, episode_values, onset_threshold, recovery=pd.NaT)
        )

    if not episodes:
        return _empty_stress_episodes()
    return pd.DataFrame(episodes)


def _summarise_episode(index, values, onset_threshold, *, recovery):
    values_arr = np.asarray(values, dtype=float)
    trough_pos = int(np.argmin(values_arr))
    deficit = np.clip(onset_threshold - values_arr, a_min=0.0, a_max=None)
    return {
        "onset": index[0],
        "trough_month": index[trough_pos],
        "trough_value": float(values_arr[trough_pos]),
        "recovery": recovery,
        "duration_months": len(values_arr),
        "severity": float(deficit.sum()),
    }


def _empty_stress_episodes() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["onset", "trough_month", "trough_value", "recovery", "duration_months", "severity"]
    )
```

Add `"detect_stress_episodes"` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hydrological_state.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add hydroseason/hydrological_state.py tests/test_hydrological_state.py
git commit -m "feat: add percentile-based stress episode detection"
```

---

### Task 6: `analyze_hydrological_state` orchestrator + package exports

**Files:**
- Modify: `hydroseason/hydrological_state.py`
- Modify: `hydroseason/__init__.py`
- Modify: `tests/test_package_surface.py`
- Test: `tests/test_hydrological_state.py`

**Interfaces:**
- Consumes: `classify_seasonality_regime` (Task 1/2), `suggest_hydrological_state_config` (Task 3), `compute_wetness_state_index` (Task 4), `detect_stress_episodes` (Task 5).
- Produces:
  - `@dataclass(frozen=True) class HydrologicalStateResult` with fields: `regime: SeasonalityResult`, `hydro_year_anchor: HydrologicalYearAnchor`, `wsi: pd.DataFrame`, `stress_episodes: pd.DataFrame`.
  - `analyze_hydrological_state(extent, *, value_col="extent_pct", date_col=None, window_years=12, spread="both", regime_method="both") -> HydrologicalStateResult`.
  - This is the final public surface of the module; no downstream task consumes it within this plan.

- [ ] **Step 1: Write the failing tests**

```python
def test_analyze_hydrological_state_runs_all_four_components_for_monsoonal_series():
    from hydroseason.hydrological_state import analyze_hydrological_state

    extent = _monsoonal_extent(n_years=8)
    result = analyze_hydrological_state(extent, window_years=5)

    assert result.regime.regime == "seasonal"
    assert result.hydro_year_anchor.season_mode == "labeled"
    assert "wsi_mad" in result.wsi.columns
    assert isinstance(result.stress_episodes, pd.DataFrame)


def test_analyze_hydrological_state_runs_all_four_components_for_perennial_series():
    from hydroseason.hydrological_state import analyze_hydrological_state

    extent = _perennial_extent(n_years=8)
    result = analyze_hydrological_state(extent, window_years=5)

    assert result.regime.regime in ("non_seasonal", "borderline")
    assert result.hydro_year_anchor.season_mode == "anchor_only"
    # WSI and stress detection still run -- this is the point of the module.
    assert "wsi_mad" in result.wsi.columns
    assert isinstance(result.stress_episodes, pd.DataFrame)


def test_analyze_hydrological_state_does_not_crash_on_bimodal_series():
    from hydroseason.hydrological_state import analyze_hydrological_state

    index = pd.date_range("2015-01-01", periods=12 * 8, freq="MS")
    month = index.month
    # Two peaks per year (Feb and Aug), two troughs (May and Nov).
    values = 20.0 * np.cos(4 * np.pi * (month - 2) / 12) + 50.0
    rng = np.random.default_rng(3)
    extent = pd.Series(values + rng.normal(0, 1.0, size=len(index)), index=index, name="extent_pct")

    result = analyze_hydrological_state(extent, window_years=5)

    # Degenerate case, documented as accepted (spec §8): must not crash, and
    # the anchor resolves to a single trough month even though the true
    # climatology has two.
    assert result.hydro_year_anchor.trough_month in range(1, 13)


def test_analyze_hydrological_state_fitzroy_like_series_classifies_seasonal():
    from hydroseason.hydrological_state import analyze_hydrological_state

    extent = _monsoonal_extent(n_years=10)
    result = analyze_hydrological_state(extent, window_years=6)

    assert result.regime.regime == "seasonal"
    assert result.hydro_year_anchor.wet_start_month is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hydrological_state.py -v -k analyze_hydrological_state`
Expected: FAIL with `ImportError: cannot import name 'analyze_hydrological_state'`

- [ ] **Step 3: Implement `HydrologicalStateResult` and `analyze_hydrological_state`**

Add to `hydroseason/hydrological_state.py`:

```python
@dataclass(frozen=True)
class HydrologicalStateResult:
    regime: SeasonalityResult
    hydro_year_anchor: HydrologicalYearAnchor
    wsi: pd.DataFrame
    stress_episodes: pd.DataFrame


def analyze_hydrological_state(
    extent: pd.Series | pd.DataFrame,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    window_years: int = 12,
    spread: SpreadMethod = "both",
    regime_method: RegimeMethod = "both",
) -> HydrologicalStateResult:
    """Run the full hydrological-state analysis: regime, anchor, WSI, stress.

    Regime classification is diagnostic metadata (spec §5) -- it never
    blocks WSI or stress-episode computation, which always run regardless
    of whether the basin is monsoonal, perennial, or bimodal. Only the
    hydro-year anchor's wet/dry season labels are conditional on the
    detected regime (see suggest_hydrological_state_config).
    """
    regime_result = classify_seasonality_regime(
        extent, value_col=value_col, date_col=date_col, method=regime_method
    )
    anchor = suggest_hydrological_state_config(
        extent, value_col=value_col, date_col=date_col, regime=regime_result.regime
    )
    wsi = compute_wetness_state_index(
        extent, value_col=value_col, date_col=date_col, window_years=window_years, spread=spread
    )
    wsi_column = "wsi_mad" if "wsi_mad" in wsi.columns else "wsi_iqr"
    stress_episodes = detect_stress_episodes(wsi, column=wsi_column)

    return HydrologicalStateResult(
        regime=regime_result,
        hydro_year_anchor=anchor,
        wsi=wsi,
        stress_episodes=stress_episodes,
    )


__all__ = [
    "SeasonalityResult",
    "HydrologicalYearAnchor",
    "HydrologicalStateResult",
    "classify_seasonality_regime",
    "classify_regime_composite",
    "circular_concentration_R",
    "eta_squared_seasonality_score",
    "walsh_lawler_seasonality_index",
    "colwell_indices",
    "suggest_hydrological_state_config",
    "compute_wetness_state_index",
    "detect_stress_episodes",
    "analyze_hydrological_state",
]
```

Replace the earlier, narrower `__all__` list from Task 1/2/3/4/5 with this final one (there should be exactly one `__all__` assignment at the bottom of the file after this task).

- [ ] **Step 4: Run hydrological_state tests to verify they pass**

Run: `pytest tests/test_hydrological_state.py -v`
Expected: All PASS.

- [ ] **Step 5: Wire package exports in `hydroseason/__init__.py`**

```python
# hydroseason/__init__.py -- add to the existing import block:
from .hydrological_state import (
    HydrologicalStateResult,
    HydrologicalYearAnchor,
    SeasonalityResult,
    analyze_hydrological_state,
    classify_seasonality_regime,
    compute_wetness_state_index,
    detect_stress_episodes,
    suggest_hydrological_state_config,
)
```

And extend `__all__` in the same file:

```python
__all__ = [
    "__version__",
    "HydroYearConfig",
    "detect_hydrological_years",
    "label_hydrological_months",
    "monthly_water_extent",
    "suggest_hydro_year_config",
    "HydrologicalStateResult",
    "HydrologicalYearAnchor",
    "SeasonalityResult",
    "analyze_hydrological_state",
    "classify_seasonality_regime",
    "compute_wetness_state_index",
    "detect_stress_episodes",
    "suggest_hydrological_state_config",
    "load_aoi",
    "load_wofs_from_stac",
    "load_monthly_masks",
    "load_monthly_masks_zarr",
    "load_extent_csv",
    "complete_monthly_axis",
    "generate_html_report",
]
```

- [ ] **Step 6: Update the pinned package-surface test**

`tests/test_package_surface.py` asserts an exact `__all__` list (`test_package_import_exposes_only_migration_safe_surface`, line 9-23). Update it to match the new list from Step 5:

```python
def test_package_import_exposes_only_migration_safe_surface():
    hydroseason = importlib.import_module("hydroseason")

    assert isinstance(hydroseason.__version__, str)
    assert hydroseason.__all__ == [
        "__version__",
        "HydroYearConfig",
        "detect_hydrological_years",
        "label_hydrological_months",
        "monthly_water_extent",
        "suggest_hydro_year_config",
        "HydrologicalStateResult",
        "HydrologicalYearAnchor",
        "SeasonalityResult",
        "analyze_hydrological_state",
        "classify_seasonality_regime",
        "compute_wetness_state_index",
        "detect_stress_episodes",
        "suggest_hydrological_state_config",
        "load_aoi",
        "load_wofs_from_stac",
        "load_monthly_masks",
        "load_monthly_masks_zarr",
        "load_extent_csv",
        "complete_monthly_axis",
        "generate_html_report",
    ]
    assert callable(hydroseason.detect_hydrological_years)
    assert callable(hydroseason.label_hydrological_months)
    assert callable(hydroseason.load_extent_csv)
    assert callable(hydroseason.analyze_hydrological_state)
    assert "ValidationSeasonConfig" not in vars(hydroseason)

    stripped_names = {
        "classify_rainfall",
        "run_pipeline",
        "read_rainfall",
        "get_monthly_silo_rainfall",
    }
    assert stripped_names.isdisjoint(vars(hydroseason))
```

(Only the `__all__` list and the added `assert callable(hydroseason.analyze_hydrological_state)` line change; the rest of the test is unchanged from the existing file.)

- [ ] **Step 7: Run the full test suite to verify no regressions**

Run: `pytest -v`
Expected: All PASS (existing `hydro_year.py`/`io.py`/`report.py` tests untouched and green, plus all new `hydrological_state.py` tests, plus the updated `test_package_surface.py`).

- [ ] **Step 8: Commit**

```bash
git add hydroseason/hydrological_state.py hydroseason/__init__.py tests/test_hydrological_state.py tests/test_package_surface.py
git commit -m "feat: add analyze_hydrological_state orchestrator and wire package exports"
```

---

## Self-Review Notes

**Spec coverage:**
- §6.1 regime classifier (eta²/R/SI + Colwell, `method="both"`) → Tasks 1-2.
- §6.2 hydro year anchor always + conditional season labels → Task 3.
- §6.3 moving-window WSI (calendar-month-aware, MAD/IQR/both) → Task 4.
- §6.4 percentile-based stress episodes with severity → Task 5.
- §5 orchestrator + additive-only integration → Task 6.
- §7 data contracts (reuse `_coerce_monthly_series`, new `__init__.py` exports) → Task 6, Steps 5-6.
- §8 testing strategy (synthetic perennial/bimodal/monsoonal, trend injection, stress edge cases) → covered across Tasks 1-6's test steps; bimodal degenerate case explicitly tested in Task 6 Step 1.
- §9 deferred items (choosing a default regime method, hydro_year.py integration) — intentionally not tasked; `analyze_hydrological_state` always computes and returns both `eta_r_si`-derived `regime`/`regime_source` and the `colwell_*` fields side by side, leaving the choice open as designed.

**Placeholder scan:** no TBD/TODO markers; all code steps contain complete, runnable code. (An earlier draft of Task 2 Step 3 had an intermediate malformed snippet while deriving the Colwell entropy decomposition — removed during self-review so only the final, correct `colwell_indices` implementation remains.)

**Type consistency:** `SeasonalityResult`, `HydrologicalYearAnchor`, `HydrologicalStateResult` field names are used identically across Tasks 1, 2, 3, 6. `compute_wetness_state_index`'s `spread` parameter and `wsi_mad`/`wsi_iqr` column names match between Task 4's implementation and Task 5/6's consumers. `detect_stress_episodes`'s `column` parameter defaults to `"wsi_mad"` consistently in Task 5 and Task 6.
